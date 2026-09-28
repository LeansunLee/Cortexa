import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from cortexa.api import goals
from cortexa.security import debug_preferences
from cortexa.security.access import current_actor
from cortexa.security.api import DebugPreference, get_my_debug_preference, save_my_debug_preference


def test_debug_preference_is_private_and_permission_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(debug_preferences, "PREFERENCE_DIR", tmp_path / "private")
    user = uuid.uuid4()
    other = uuid.uuid4()
    actor = SimpleNamespace(user_id=user, has=lambda code: code == "conversation.debug")
    token = current_actor.set(actor)
    try:
        assert asyncio.run(get_my_debug_preference()) == {"allowed": True, "enabled": False}
        asyncio.run(save_my_debug_preference(DebugPreference(enabled=True)))
        assert asyncio.run(get_my_debug_preference())["enabled"] is True
        assert debug_preferences.debug_enabled(other) is False
        assert (tmp_path / "private" / f"{user}.json").stat().st_mode & 0o777 == 0o600
        actor.has = lambda code: False
        assert asyncio.run(get_my_debug_preference()) == {"allowed": False, "enabled": False}
        with pytest.raises(HTTPException) as denied:
            asyncio.run(save_my_debug_preference(DebugPreference(enabled=False)))
        assert denied.value.status_code == 403
        assert debug_preferences.debug_enabled(user) is True
    finally:
        current_actor.reset(token)


def test_message_route_keeps_greetings_ordinary_and_tasks_in_goal(tmp_path, monkeypatch):
    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    agent = SimpleNamespace(agent_type="llm")
    monkeypatch.setattr(goals.store, "sessions", lambda: Session())
    conversation = SimpleNamespace(agent_id=uuid.uuid4(), metadata_json={})
    monkeypatch.setattr(goals, "own_conversation", AsyncMock(return_value=conversation))
    monkeypatch.setattr(goals, "require_agent_use", AsyncMock(return_value=agent))
    config = tmp_path / "config.yaml"
    config.write_text("features: {goal_execution_enabled: true, goal_collaboration_enabled: true}")
    monkeypatch.setattr(goals, "CONFIG_PATH", config)
    conv = uuid.uuid4()

    async def route(content, **kwargs):
        return await goals.message_route(conv, goals.RouteRequest(content=content, **kwargs))

    assert asyncio.run(route("你好"))["use_goal"] is False
    assert asyncio.run(route("@销售部 @品牌部 一起研究10月策略"))["use_goal"] is True
    assert asyncio.run(route("请分析销售数据"))["use_goal"] is True
    assert asyncio.run(route("帮我做一份10月销售策略"))["use_goal"] is True
    assert asyncio.run(route("请分析附件", has_attachments=True))["use_goal"] is False
    assert asyncio.run(route("杭州呢"))["use_goal"] is False
    for mode in ("ASK_BEFORE_COLLABORATION", "AUTONOMOUS"):
        conversation.metadata_json = {"collaboration_mode": mode}
        assert asyncio.run(route("杭州呢"))["use_goal"] is True
        assert asyncio.run(route("你好"))["use_goal"] is False
        assert asyncio.run(route("请分析附件", has_attachments=True))["use_goal"] is False
    agent.agent_type = "proxy"
    assert asyncio.run(route("请分析销售数据"))["use_goal"] is False
