import asyncio
import json
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage
from test_goal_collaboration import setup, start, URL
from test_goal_loop import FakeModel

from cortexa.api import prompt_requests as api
from cortexa.api import goals
from cortexa.runtime import prompt_requests as storage


def test_snapshot_preserves_request_without_reasoning_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'ROOT', tmp_path)
    messages = [SystemMessage(content='实际系统提示词'), AIMessage(
        content=[{'type': 'text', 'text': '公开回复'}, {'type': 'thinking', 'thinking': 'PRIVATE_REASONING'}],
        additional_kwargs={'reasoning_content': 'PRIVATE_REASONING', 'api_key': 'SECRET'})]
    request = storage.model_request(messages, parameters={'max_tokens': 100})
    ref = storage.save_prompt(uuid.uuid4(), uuid.uuid4(), 'Peter', 'model', request)
    snapshot = storage.read_prompt(ref['id'])
    assert snapshot['request']['messages'][0]['content'] == '实际系统提示词'
    assert 'PRIVATE_REASONING' not in json.dumps(snapshot) and 'SECRET' not in json.dumps(snapshot)
    assert Path(tmp_path / (ref['id'] + '.json')).stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(not URL, reason='Isolated PostgreSQL required')
def test_prompt_reference_survives_checkpoint_and_access_is_checked(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            monkeypatch.setattr(storage, 'ROOT', tmp_path / 'requests')
            monkeypatch.setattr(api, 'async_session_factory', ctx.store.sessions)
            monkeypatch.setattr(api, 'can_read_goal_trace', lambda: True)
            model = FakeModel([[AIMessageChunk(content='已完成')]])
            monkeypatch.setattr(goals, 'create_llm', lambda *_: model)
            done = await start(ctx, 'prompt-ref', '你好')
            assert done['status'] == 'COMPLETE', done
            row = await ctx.store.get(ctx.conv, uuid.UUID(done['goal_id']))
            p = ctx.store.files.read(row.id, row.artifacts['snapshot'])
            ref = next(s['prompts'][0] for s in p['execution_steps'] if s.get('prompts'))
            result = await api.get_prompt(ctx.conv, uuid.UUID(ref['id']))
            snapshot = json.loads(result.body)
            assert snapshot['request']['messages'][-1]['content'] == '你好'
            assert result.headers['cache-control'] == 'no-store'
            assert 'request' not in ref
            monkeypatch.setattr(api, 'can_read_goal_trace', lambda: False)
            with pytest.raises(HTTPException) as denied:
                await api.get_prompt(ctx.conv, uuid.UUID(ref['id']))
            assert denied.value.status_code == 403
            monkeypatch.setattr(api, 'can_read_goal_trace', lambda: True)
            stolen = storage.save_prompt(uuid.uuid4(), ctx.source.id, 'Other', 'model', {})
            with pytest.raises(HTTPException) as wrong:
                await api.get_prompt(ctx.conv, uuid.UUID(stolen['id']))
            assert wrong.value.status_code == 404
    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason='Isolated PostgreSQL required')
def test_collaboration_and_child_model_have_separate_actual_requests(tmp_path, monkeypatch):
    from test_goal_loop import tool_call
    from cortexa.runtime import agent_executor
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            monkeypatch.setattr(storage, 'ROOT', tmp_path / 'requests')
            parent = FakeModel([[tool_call(name='agent_' + ctx.targets[0].id.hex, args={'task': '查询9月销量'})],
                                [AIMessageChunk(content='已完成计划')]])
            child = FakeModel([[AIMessageChunk(content='9月销量2')]])
            monkeypatch.setattr(goals, 'create_llm', lambda *_: parent)
            monkeypatch.setattr(agent_executor, 'create_llm', lambda *_: child)
            done = await start(ctx, 'child-prompts', '@销售Agent 制定计划')
            assert done['status'] == 'COMPLETE', done
            row = await ctx.store.get(ctx.conv, uuid.UUID(done['goal_id']))
            p = ctx.store.files.read(row.id, row.artifacts['snapshot'])
            refs = [ref for step in p['execution_steps'] for ref in step.get('prompts', [])]
            snapshots = [storage.read_prompt(ref['id']) for ref in refs]
            delegated = next(s for s in snapshots if s['kind'] == 'collaboration')
            assert delegated['request']['task'] == '查询9月销量'
            child_request = next(s for s in snapshots if s['kind'] == 'model' and s['agent_id'] == str(ctx.targets[0].id))
            assert '查询9月销量' in json.dumps(child_request['request'], ensure_ascii=False)
            assert len([s for s in snapshots if s['kind'] == 'model' and s['agent_id'] == str(ctx.source.id)]) == 2
    asyncio.run(scenario())
