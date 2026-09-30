"""Behavioral regressions from the 2026-09-30 non-meeting bug review."""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from cortexa.api.agents import router as agent_router, update_agent
from cortexa.api.schemas import AgentUpdate
from cortexa.api.goals import strip_email_addresses
from cortexa.api.knowledge import _unique_kb_name
from cortexa.api.data import execute_data_query
from cortexa.api.schemas import DataQueryCreate
from cortexa.db.models import DataCapability, DataSource
from cortexa.data import adapter
from cortexa.memory.service import explicit_memory_candidate
from cortexa.db.models import Agent
from cortexa.security.access import current_actor
from cortexa.web.app import serve_vue
from cortexa.workflow.engine import ordered_nodes, run_task


def test_explicit_memory_fallback_preserves_provenance_and_rejects_secrets():
    source_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())
    item = explicit_memory_candidate('请记住：我喜欢喝乌龙茶', source_id, 'revision', user_id, '测试用户')
    assert item['content'] == '我喜欢喝乌龙茶'
    assert item['memory_kind'] == 'preference'
    assert item['source_message_id'] == source_id
    assert item['subject_id'] == user_id
    assert explicit_memory_candidate('请记住：我的密码是 abc123', source_id, 'revision', user_id, '测试用户') is None
    assert explicit_memory_candidate('请记住明天开会', source_id, 'revision', user_id, '测试用户') is None


def test_task_words_inside_email_do_not_trigger_routing():
    cleaned = strip_email_addresses('请把说明发给 admin@bugtest-调研员.com')
    assert '调研' not in cleaned
    assert '请把说明发给' in cleaned
    assert '调研' in strip_email_addresses('请调研后发给 admin@example.com')


def test_unknown_api_get_never_serves_spa():
    with pytest.raises(HTTPException) as error:
        asyncio.run(serve_vue(None, 'api/workflows/unknown'))
    assert error.value.status_code == 404


def test_agent_update_accepts_put_and_patch():
    routes = [r for r in agent_router.routes if r.path == '/agents/{agent_id}']
    methods = set().union(*(r.methods for r in routes))
    assert {'PUT', 'PATCH'} <= methods


def test_binding_only_update_keeps_published_agent_available():
    agent = Agent(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name='测试', role='研究员', agent_type='llm', status='active', knowledge_base_ids=[])
    db = AsyncMock()
    db.get.return_value = agent
    asyncio.run(update_agent(agent.id, AgentUpdate(knowledge_base_ids=[uuid.uuid4()]), db))
    assert agent.status == 'active'
    asyncio.run(update_agent(agent.id, AgentUpdate(name='新名称'), db))
    assert agent.status == 'draft'


@pytest.mark.parametrize('name', [' ', '\n\t', 'bad/name'])
def test_invalid_knowledge_base_name_rejected(name):
    with pytest.raises(HTTPException) as error:
        asyncio.run(_unique_kb_name(AsyncMock(), uuid.uuid4(), None, name))
    assert error.value.status_code == 400


def test_duplicate_knowledge_base_name_rejected():
    db = AsyncMock()
    db.scalar.return_value = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        asyncio.run(_unique_kb_name(db, uuid.uuid4(), None, ' Existing '))
    assert error.value.status_code == 409


def test_manual_query_returns_rows_without_persisting_them(monkeypatch):
    from cortexa.api import data as data_api
    workspace_id, source_id = uuid.uuid4(), uuid.uuid4()
    capability = SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id, data_source_id=source_id, query_template='SELECT 1', row_limit=10, timeout_seconds=5)
    source = SimpleNamespace(id=source_id, credential_id=None, type='postgres', config={})
    db = AsyncMock()
    db.get.side_effect = lambda model, _: capability if model is DataCapability else source if model is DataSource else None
    def add(audit):
        audit.id = uuid.uuid4()
        audit.created_at = datetime.now(timezone.utc)
    db.add = Mock(side_effect=add)
    run_query = AsyncMock(return_value={'success': True, 'data': [{'answer': 42}], 'row_count': 1, 'columns': ['answer'], 'duration_ms': 3, 'error': None})
    monkeypatch.setattr(data_api, 'execute_query', run_query)
    result = asyncio.run(execute_data_query(DataQueryCreate(data_capability_id=str(capability.id)), db, str(workspace_id)))
    assert result['data'] == [{'answer': 42}]
    assert result['output_result'] == {'row_count': 1, 'columns': ['answer']}
    assert run_query.await_args.kwargs['read_only'] is True


class FakeConnection:
    def __init__(self, reject=False):
        self.reject = reject

    async def __aenter__(self):
        if self.reject:
            raise RuntimeError('password authentication failed')
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, *_):
        return SimpleNamespace(scalar=lambda: 1)


class FakeEngine:
    def __init__(self, reject=False):
        self.reject = reject

    def connect(self):
        return FakeConnection(self.reject)

    async def dispose(self):
        pass


@pytest.mark.parametrize('probe_reject,expected', [(False, False), (True, True)])
def test_postgres_test_rejects_unverifiable_password(monkeypatch, probe_reject, expected):
    engines = [FakeEngine(), FakeEngine(probe_reject)]
    monkeypatch.setattr(adapter, 'decrypt_dict', lambda _: {'username': 'test', 'password': 'wrong'})
    monkeypatch.setattr(adapter, 'create_async_engine', lambda *_args, **_kwargs: engines.pop(0))
    result = asyncio.run(adapter.test_connection('postgres', {'host': '127.0.0.1', 'database': 'test'}, 'encrypted'))
    assert result['success'] is expected
    assert not engines


def make_node(name):
    return SimpleNamespace(id=uuid.uuid4(), name=name, type='agent', agent_id=uuid.uuid4())


def test_workflow_requires_connected_acyclic_steps():
    first, second = make_node('研究'), make_node('撰写')
    edge = SimpleNamespace(source_node_id=first.id, target_node_id=second.id)
    assert ordered_nodes([second, first], [edge]) == [first, second]
    with pytest.raises(ValueError):
        ordered_nodes([first, second], [])
    reverse = SimpleNamespace(source_node_id=second.id, target_node_id=first.id)
    with pytest.raises(ValueError):
        ordered_nodes([first, second], [edge, reverse])


class FakeSession:
    def __init__(self, task, version):
        self.task, self.version = task, version
        self.objects = []

    def add(self, item):
        self.objects.append(item)

    async def commit(self):
        for item in self.objects:
            if getattr(item, 'id', None) is None:
                item.id = uuid.uuid4()
            if getattr(item, 'created_at', None) is None:
                item.created_at = datetime.now(timezone.utc)

    async def refresh(self, _):
        pass

    async def scalar(self, _):
        return self.version

    async def rollback(self):
        pass

    async def get(self, model, ident):
        if model.__name__ == 'Task':
            return self.task
        return next((item for item in self.objects if isinstance(item, model) and item.id == ident), None)


@pytest.mark.parametrize('model_error', [False, True])
def test_task_run_persists_real_result_or_failure(monkeypatch, model_error):
    from cortexa.workflow import engine
    agent = SimpleNamespace(id=uuid.uuid4(), name='研究员', model='test')
    version = SimpleNamespace(id=uuid.uuid4())
    task = SimpleNamespace(id=uuid.uuid4(), name='调研', description='', input_data={'prompt': '解释 A'}, status='pending', output_data={})
    session = FakeSession(task, version)
    monkeypatch.setattr(engine, 'require_agent_use', AsyncMock(return_value=agent))
    monkeypatch.setattr(engine, '_build_system_prompt', lambda _: '系统提示')
    monkeypatch.setattr(engine, 'annotate_usage', lambda **_: None)
    if model_error:
        model = SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError('model unavailable')))
    else:
        model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='实际模型输出')))
    monkeypatch.setattr(engine, 'create_llm', lambda _: model)
    token = current_actor.set(SimpleNamespace(user_id=uuid.uuid4()))
    try:
        run = asyncio.run(run_task(session, task, [('研究', agent.id)]))
    finally:
        current_actor.reset(token)
    assert run.status == task.status == ('failed' if model_error else 'completed')
    if model_error:
        assert run.error_message
        assert '实际模型输出' not in str(run.output_data)
    else:
        assert run.output_data['steps']['研究'] == '实际模型输出'
