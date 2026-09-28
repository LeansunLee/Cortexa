import asyncio
import pytest
import importlib
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from langchain_core.messages import AIMessageChunk
from cortexa.collaboration import manager
from cortexa.collaboration.schemas import AgentHandoff
from cortexa.db.models import Agent


@pytest.mark.parametrize("include_history", [True, False])
def test_target_context_preserves_history_and_uses_target_resources(monkeypatch, include_history):
    captured = []
    target = Agent(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="品牌部", model="test")
    history = [SimpleNamespace(id="a", role="assistant", content="原历史回答"), SimpleNamespace(id="u", role="user", content="原历史问题")]

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, query):
            rows = history if "t_conversation_messages" in str(query) else []
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    class Model:
        async def astream(self, messages):
            captured.extend(messages)
            yield AIMessageChunk(content="测试回答")

    organization = AsyncMock(return_value=[{"role": "user", "content": "当前空间组织职责目录"}])
    monkeypatch.setattr("cortexa.agents.context.organization_reference", organization)
    knowledge = AsyncMock(return_value="独立知识库正文")
    memories = AsyncMock(return_value=["目标记忆"])
    monkeypatch.setattr(importlib.import_module("cortexa.db.engine"), "async_session_factory", Session)
    monkeypatch.setattr("cortexa.config.llm_providers.create_llm", lambda name: Model())
    monkeypatch.setattr(manager, "retrieve_knowledge", knowledge)
    monkeypatch.setattr(manager, "retrieve_memories", memories)
    monkeypatch.setattr(manager, "format_memories_for_prompt", lambda values: "目标记忆")
    handoff = AgentHandoff(source_agent_id="source", target_agent_id=str(target.id), task="协作", question="本轮问题", include_history=include_history, known_facts=["待核实事实"], reference_materials=["附件正文"])
    result = asyncio.run(manager._execute_target_agent(target, "规则", handoff, uuid.uuid4()))
    assert result == "测试回答"
    context = next(m['content'] for m in captured if '主对话上下文' in m['content'])
    assert '原历史问题' in context or any('原历史问题' in m['content'] for m in captured)
    assert any('原历史回答' in m['content'] for m in captured)
    assert handoff.background_context['mode'] == 'conversation'
    assert [fact['quote'] for fact in handoff.background_context['facts']] == ['原历史问题', '原历史回答']
    assert captured[0] == {"role": "system", "content": "规则"}
    assert "本轮问题" in captured[-1]["content"]
    for value in ("独立知识库正文", "目标记忆", "附件正文", "待核实事实", "当前空间组织职责目录"):
        assert any(message["role"] == "user" and value in message["content"] for message in captured)
    assert organization.call_args.args[0] is target
    assert isinstance(organization.call_args.args[1], Session)
    assert knowledge.call_args.args[0] is target
    assert memories.call_args.kwargs["agent_id"] == target.id
    assert memories.call_args.kwargs["workspace_id"] == target.workspace_id
