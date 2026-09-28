import asyncio
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk
from cortexa.api import conversations as api
from cortexa.api.schemas import ConversationMessageCreate
from cortexa.collaboration.schemas import AgentHandoffResult
from cortexa.db.models import Agent, Conversation, ConversationMessage


@pytest.mark.parametrize('bound_data_tools', [True, False])
@pytest.mark.parametrize('explicit_dependency', [True, False])
@pytest.mark.parametrize('second_type', ['llm', 'proxy'])
@pytest.mark.parametrize('first_success', [True, False])
def test_edited_tasks_dependency_results_and_snapshot_persist(monkeypatch, first_success, second_type, explicit_dependency, bound_data_tools):
    monkeypatch.setattr(api, 'capability_shadow_enabled', lambda path: True)
    source = Agent(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name='主Agent', agent_type='llm', model='test')
    first = Agent(id=uuid.uuid4(), workspace_id=source.workspace_id, name='数据', agent_type='proxy')
    second = Agent(id=uuid.uuid4(), workspace_id=source.workspace_id, name='市场', agent_type=second_type)
    conv = Conversation(id=uuid.uuid4(), workspace_id=source.workspace_id, agent_id=source.id)
    objects = {obj.id: obj for obj in (source, first, second, conv)}
    saved, handoffs, model_inputs = [], [], []

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, kind, ident): return objects.get(ident)
        def add(self, obj):
            obj.id = obj.id or uuid.uuid4()
            obj.created_at = datetime.now(timezone.utc)
            saved.append(obj)
        async def flush(self): pass
        async def refresh(self, obj): pass
        async def commit(self): pass
        async def rollback(self): pass
        async def execute(self, query):
            return SimpleNamespace(scalar=lambda: 0, scalars=lambda: SimpleNamespace(all=lambda: list(reversed(saved))))

    async def handoff(**kwargs):
        value = kwargs['handoff']
        handoffs.append(value)
        yield {'result': AgentHandoffResult(status='success' if first_success else 'failed', result='真实数据100台', summary='数据', input_snapshot={'input': value.question})}

    class Model:
        def bind_tools(self, tools):
            assert len(tools) == 1
            return self
        async def astream(self, messages):
            model_inputs.extend(messages)
            yield AIMessageChunk(content='汇总结果')

    monkeypatch.setattr('cortexa.collaboration.drafts.save_input_snapshot', AsyncMock(side_effect=lambda conv, snapshot: snapshot))
    monkeypatch.setattr(api, 'async_session_factory', Session)
    organization = AsyncMock(return_value=[{'role':'user', 'content':'当前空间组织职责目录'}])
    monkeypatch.setattr(api, 'organization_reference', organization)
    monkeypatch.setattr('cortexa.security.access.require_agent_use', AsyncMock(side_effect=lambda db, ident: objects[ident]))
    monkeypatch.setattr(api, 'list_collaboration_agents', AsyncMock(return_value=[{'id':str(a.id), 'name':a.name} for a in (first, second)]))
    monkeypatch.setattr(api, 'stream_handoff', handoff)
    capability = SimpleNamespace(id=uuid.uuid4(), name="实验档案", description="实验记录查询", query_template="SELECT 1", input_schema={})
    capabilities = [{"capability": capability, "data_source": SimpleNamespace(id=uuid.uuid4())}] if bound_data_tools else []
    monkeypatch.setattr(api, '_load_agent_capabilities', AsyncMock(return_value=capabilities))
    monkeypatch.setattr(api, 'extract_memories', AsyncMock(return_value=[]))
    monkeypatch.setattr('cortexa.config.llm_providers.create_llm', lambda model: Model())
    payload = ConversationMessageCreate(content='请@数据 原始任务 @市场 原始计划', collaboration_drafts=[
        {'agent_id': first.id, 'task':'编辑后的查询', 'context_mode':'manual', 'supplemental_prompt':'本轮覆盖'},
        {'agent_id': second.id, 'task':'编辑后的计划', 'context_mode':'manual', 'depends_on':[first.id] if explicit_dependency else []},
    ])
    async def run():
        response = await api.create_message_stream(conv.id, payload)
        return [chunk async for chunk in response.body_iterator]
    events = ''.join(asyncio.run(run()))
    assert '"type": "error"' not in events, events
    assert organization.call_args.args[0] is source
    assert isinstance(organization.call_args.args[1], Session)
    assert handoffs[0].background_context['mode'] == 'none'
    assert handoffs[0].background_context['facts'] == []
    assert handoffs[0].question == '编辑后的查询'
    assert handoffs[0].include_history is False
    assert handoffs[0].known_facts == []
    assert handoffs[0].supplemental_prompt == '本轮覆盖'
    assert len(handoffs) == (1 if explicit_dependency and not first_success else 2)
    assert handoffs[0].dependency_results == []
    if len(handoffs) == 2:
        if second_type == 'proxy':
            assert handoffs[1].background_context['facts'] == []
            assert handoffs[1].dependency_results == []
        else:
            assert handoffs[1].background_context['mode'] == 'conversation'
            assert handoffs[1].background_context['facts'][-1]['quote'] == payload.content
            prior = handoffs[1].dependency_results
            assert len(prior) == 1 and prior[0]['agent_name'] == '数据'
            assert prior[0]['status'] == ('success' if first_success else 'failed')
            assert prior[0]['result'] == ('真实数据100台' if first_success else '')
    assistant = next(msg for msg in saved if isinstance(msg, ConversationMessage) and msg.role == 'assistant')
    assert len(assistant.metadata_json['collaborations']) == 2
    assert assistant.metadata_json['collaborations'][0]['input_snapshot']['input'] == '编辑后的查询'
    assert assistant.content == '汇总结果'
    observations = [entry for entry in assistant.metadata_json['debug_trace']
                    if entry['stage'] == 'runtime_observation']
    assert len(observations) == 2
    assert all(entry['detail']['source_type'] == 'AGENT' for entry in observations)
