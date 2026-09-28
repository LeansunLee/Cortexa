import asyncio
import importlib
import os
import uuid
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
from cortexa.collaboration import manager
from cortexa.collaboration.schemas import AgentHandoff
from cortexa.db.models import Agent


@pytest.mark.parametrize("kind,config,expected", [
    ("proxy", {"timeout_ms": 1000000}, 1005),
    ("proxy", {"timeout_ms": 1000000, "retry": 1}, 2005),
    ("llm", {}, 120),
])
def test_outer_timeout_respects_proxy_budget(monkeypatch, kind, config, expected):
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.get.return_value = None
    monkeypatch.setattr(importlib.import_module("cortexa.db.engine"), "async_session_factory", lambda: session)
    monkeypatch.setattr(manager, "_execute_target_agent", AsyncMock(return_value="结果"))
    observed = []
    async def wait_for(awaitable, timeout):
        observed.append(timeout)
        return await awaitable
    monkeypatch.setattr(manager.asyncio, "wait_for", wait_for)
    source = Agent(id=uuid.uuid4(), name="销售部")
    target = Agent(id=uuid.uuid4(), name="目标", agent_type=kind, proxy_config=config)
    handoff = AgentHandoff(source_agent_id=str(source.id), target_agent_id=str(target.id), task="测试", question="测试")
    result = asyncio.run(manager.execute_handoff(source, target, handoff, None))
    assert result.status == "success"
    assert observed == [expected]


def test_waiting_stream_emits_heartbeat_without_ending_handoff(monkeypatch):
    original_wait = asyncio.wait_for
    timed_out = False
    async def wait_for(awaitable, timeout):
        nonlocal timed_out
        if not timed_out:
            timed_out = True
            awaitable.close()
            raise asyncio.TimeoutError()
        return await original_wait(awaitable, timeout)
    monkeypatch.setattr(manager.asyncio, "wait_for", wait_for)
    monkeypatch.setattr(manager, "execute_handoff", AsyncMock(return_value="完成"))
    async def scenario():
        return [event async for event in manager.stream_handoff()]
    assert asyncio.run(scenario()) == [{"heartbeat": True}, {"result": "完成"}]
