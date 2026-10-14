import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessageChunk
from test_goal_loop import FakeModel, binding, tool_call

from cortexa.api import goals as api
from cortexa.db.models import Agent
from cortexa.runtime import agent_executor
from cortexa.runtime.loop import GoalLoop, InvocationResult, serialize_messages
from cortexa.runtime.capabilities import CapabilityType
from cortexa.runtime.policy import resolve_effective_policy
from cortexa.runtime.state import GoalState


def test_sse_forwards_child_drafts_before_parent_finishes(monkeypatch):
    agent = Agent(id=uuid.uuid4(), workspace_id=uuid.uuid4(), name="主角色", model="test", role="助手")
    config = {"features": {"goal_execution_enabled": True, "goal_collaboration_enabled": True}}
    policy = resolve_effective_policy(config, agent=agent)
    state = GoalState(runtime_agent_id=str(agent.id), latest_message_id=str(uuid.uuid4()))
    row = SimpleNamespace(id=uuid.uuid4(), conversation_id=uuid.uuid4(), agent_id=agent.id,
                          state=state.model_dump(mode="json"), status=state.status, revision=1,
                          updated_at=datetime.now(UTC), created_at=datetime.now(UTC))
    payload = {"goal_id": str(row.id), "goal": {"raw_request": "确认收到"}, "sources": [],
               "prepared": True, "messages": serialize_messages([{"role": "user", "content": "确认收到"}])}

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    async def checkpoint(row, state, payload, **kwargs):
        row.state = state.model_dump(mode="json")
        row.status = state.status
        row.revision += 1
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(api, "store", SimpleNamespace(sessions=Session, checkpoint=checkpoint))
    monkeypatch.setattr(api, "environment", AsyncMock(return_value=(agent, None, policy)))
    monkeypatch.setattr(api, "own_conversation", AsyncMock())
    monkeypatch.setattr(api, "execution_config", lambda: config)
    monkeypatch.setattr(api, "prepare_bindings", AsyncMock(return_value=([], [])))
    monkeypatch.setattr("cortexa.memory.integration.register_extraction", AsyncMock())
    model = FakeModel([[tool_call()], [AIMessageChunk(content="主角色"), AIMessageChunk(content="汇总", usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10})]])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)

    async def agent_bindings(source, state, payload, loop, *args):
        async def invoke(args, action_id):
            child_state = GoalState(runtime_role="CHILD", runtime_agent_id="child")
            child_payload = {"goal_id": str(row.id), "messages": serialize_messages([{"role": "user", "content": "确认收到"}])}
            child = GoalLoop(child_state, child_payload, AsyncMock(), AsyncMock(), event_sink=loop.event_sink, agent_name="协作角色")
            child_model = FakeModel([[AIMessageChunk(content="协作", additional_kwargs={"reasoning_content": "PRIVATE_REASONING"}), AIMessageChunk(content="回复", usage_metadata={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})]])
            async for _ in child.run(child_model, []): pass
            raw = SimpleNamespace(status="success", summary="协作完成", result=child.reply, sources=[], confidence=None, usage={}, input_snapshot={})
            archived = {"status": "success", "result": child.reply, "sources": []}
            return InvocationResult(tool.adapter.observe(raw, action_id), json.dumps(archived), archived)
        tool = binding(invoke=invoke, kind=CapabilityType.AGENT)
        return [tool]

    monkeypatch.setattr(agent_executor, "prepare_agent_bindings", agent_bindings)

    async def collect():
        response = api.stream_response(row, state, payload, agent, None)
        return [json.loads(chunk.strip()[6:]) async for chunk in response.body_iterator]

    events = asyncio.run(collect())
    drafts = [e for e in events if e["type"] == "runtime_draft"]
    assert {e["agent_name"] for e in drafts} == {"主角色", "协作角色"}
    assert "".join(e["content"] for e in drafts if e["runtime_role"] == "CHILD") == "协作回复"
    assert events[-1]["type"] == "done" and events[-1]["status"] == "COMPLETE"
    assert events.index(drafts[0]) < next(i for i, e in enumerate(events) if e["type"] == "token")
    assert "PRIVATE_REASONING" not in str(events)
    assert payload["execution_steps"]

    usage = [e for e in events if e["type"] == "runtime_usage"]
    assert sum(e["stats"]["token_count"] or 0 for e in usage) == 17
    assert sum(e["token_count"] or 0 for e in payload["execution_usage"].values()) == 17
    child_step = next(s for s in payload["execution_steps"] if s.get("draft") == "协作回复")
    assert child_step["agent_name"] == "协作角色"
    assert child_step["usage"]["token_count"] == 7
