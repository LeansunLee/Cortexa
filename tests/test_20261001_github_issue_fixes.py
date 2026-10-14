"""Behavioral regressions for the 2026-10-01 GitHub issue round (#1-#7)."""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from cortexa.api.data import delete_capability, delete_credential, delete_data_source
from cortexa.data import adapter
from cortexa.memory.policy import EXPLICIT_RELEVANCE_FLOOR, MemoryConfig, relevance_threshold
from cortexa.security.access import current_actor
from cortexa.workflow import engine as workflow_engine
from cortexa.workflow.engine import run_task


def make_db(source, cap_ids=()):
    db = AsyncMock()
    db.get.return_value = source
    db.scalars.return_value = SimpleNamespace(all=lambda: list(cap_ids))
    return db


@pytest.mark.parametrize('with_capabilities,executes', [(False, 1), (True, 4)])
def test_delete_data_source_detaches_references_and_commits_before_204(with_capabilities, executes):
    source = SimpleNamespace(id=uuid.uuid4(), credential_id=None)
    db = make_db(source, [uuid.uuid4()] if with_capabilities else [])
    asyncio.run(delete_data_source(source.id, db))
    assert db.execute.await_count == executes
    assert db.delete.await_args.args == (source,)
    # The commit must land before the response, or the client reloads a zombie.
    assert db.commit.await_count == 1


def test_delete_data_source_commit_failure_is_reported_not_204():
    source = SimpleNamespace(id=uuid.uuid4(), credential_id=None)
    db = make_db(source)
    db.commit.side_effect = IntegrityError('fk', None, Exception())
    with pytest.raises(HTTPException) as error:
        asyncio.run(delete_data_source(source.id, db))
    assert error.value.status_code == 409
    db.rollback.assert_awaited_once()


def test_delete_credential_in_use_is_rejected_with_409():
    cred = SimpleNamespace(id=uuid.uuid4())
    db = make_db(cred)
    db.scalar.return_value = 1
    with pytest.raises(HTTPException) as error:
        asyncio.run(delete_credential(cred.id, db))
    assert error.value.status_code == 409
    db.delete.assert_not_awaited()
    db.scalar.return_value = 0
    asyncio.run(delete_credential(cred.id, db))
    db.delete.assert_awaited_once_with(cred)
    assert db.commit.await_count == 1


def test_delete_capability_detaches_audit_rows_and_commits():
    cap = SimpleNamespace(id=uuid.uuid4())
    db = make_db(cap)
    asyncio.run(delete_capability(cap.id, db))
    assert db.execute.await_count == 1
    assert db.delete.await_args.args == (cap,)
    assert db.commit.await_count == 1


def test_explicit_memories_recall_below_generic_threshold():
    cfg = MemoryConfig()
    # 长问法 8 个查询词仅 1 个命中 → 相关度 0.125：通用阈值会过滤，显式记忆放行。
    assert 0.125 < cfg.relevance_threshold
    assert relevance_threshold(cfg, SimpleNamespace(source_mode='explicit')) == EXPLICIT_RELEVANCE_FLOOR
    assert 0.125 >= relevance_threshold(cfg, SimpleNamespace(source_mode='explicit'))
    assert relevance_threshold(cfg, SimpleNamespace(source_mode='inferred')) == cfg.relevance_threshold
    assert relevance_threshold(cfg, SimpleNamespace(source_mode=None)) == cfg.relevance_threshold


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


def test_multi_step_run_persists_every_step_output(monkeypatch):
    """Issue #3: shallow copies + dirty checking silently dropped steps 2+."""
    first = SimpleNamespace(id=uuid.uuid4(), name='研究', model='test')
    second = SimpleNamespace(id=uuid.uuid4(), name='撰写', model='test')
    version = SimpleNamespace(id=uuid.uuid4())
    task = SimpleNamespace(id=uuid.uuid4(), name='调研', description='', input_data={'prompt': '分析'}, status='pending', output_data={})
    session = FakeSession(task, version)
    monkeypatch.setattr(
        workflow_engine, 'require_agent_use',
        AsyncMock(side_effect=lambda db, agent_id: {first.id: first, second.id: second}[agent_id]),
    )
    monkeypatch.setattr(workflow_engine, '_build_system_prompt', lambda _: '系统提示')
    monkeypatch.setattr(workflow_engine, 'annotate_usage', lambda **_: None)
    outputs = iter(['第一步结果', '第二步结果'])
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=lambda *_: SimpleNamespace(content=next(outputs))))
    monkeypatch.setattr(workflow_engine, 'create_llm', lambda _: model)
    token = current_actor.set(SimpleNamespace(user_id=uuid.uuid4()))
    try:
        run = asyncio.run(run_task(session, task, [('第一步', first.id), ('第二步', second.id)]))
    finally:
        current_actor.reset(token)
    assert run.status == task.status == 'completed'
    assert run.output_data['steps'] == {'第一步': '第一步结果', '第二步': '第二步结果'}
    assert task.output_data['steps'] == run.output_data['steps']
    # Per-step AgentRun snapshots stay frozen at their own step.
    agent_runs = [item for item in session.objects if item.__class__.__name__ == 'AgentRun']
    assert agent_runs[0].input_data['steps'] == {}
    assert agent_runs[1].input_data['steps'] == {'第一步': '第一步结果'}


class ProbeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, *_):
        return SimpleNamespace(scalar=lambda: 1)


class ProbeEngine:
    def connect(self):
        return ProbeConn()

    async def dispose(self):
        pass


def test_postgres_probe_connecting_with_junk_password_still_succeeds(monkeypatch):
    """Issue #5: trust-auth databases make the credential unverifiable, not wrong."""
    engines = [ProbeEngine(), ProbeEngine()]
    monkeypatch.setattr(adapter, 'decrypt_dict', lambda _: {'username': 'u', 'password': 'real'})
    monkeypatch.setattr(adapter, 'create_async_engine', lambda *_a, **_k: engines.pop(0))
    result = asyncio.run(adapter.test_connection('postgres', {'host': '127.0.0.1', 'database': 'd'}, 'enc'))
    assert result == {
        'success': True,
        'message': '连接成功；注意：数据库不校验密码（任意密码均可连接），无法验证此凭证是否正确',
        'password_verified': False,
    }
