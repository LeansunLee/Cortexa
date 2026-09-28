import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk, messages_from_dict
from pydantic import BaseModel, ConfigDict, ValidationError

from agentdevstu.runtime.adapters import CapabilityAdapter
from agentdevstu.runtime.artifacts import ArtifactStore
from agentdevstu.runtime.capabilities import CapabilityDescriptor, CapabilityType
from agentdevstu.runtime.loop import Binding, GoalLoop, InvocationResult, serialize_messages
from agentdevstu.runtime.projection import model_result_text
from agentdevstu.runtime.state import GoalState, GoalStatus, RuntimeBudget, RuntimeHalt, effective_limits


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: str


class FakeModel:
    def __init__(self, rounds):
        self.rounds = iter(rounds)
        self.calls = []
        self.bound = []

    def bind_tools(self, tools):
        return self

    def bind(self, **kwargs):
        self.bound.append(kwargs)
        return self

    async def astream(self, messages):
        self.calls.append(copy.deepcopy(messages))
        for chunk in next(self.rounds):
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


def tool_call(ident="tc", name="query", args=None):
    return AIMessageChunk(
        content="", tool_calls=[{"id": ident, "name": name, "args": args if args is not None else {"city": "杭州"}}]
    )


def make_loop(limits=None, state=None, payload=None):
    state = state or GoalState(limits=effective_limits(limits))
    payload = payload or {"goal_id": "test", "messages": serialize_messages([{"role": "user", "content": "test"}])}
    saves = []

    async def save(state, payload):
        saves.append((state.model_copy(deep=True), copy.deepcopy(payload)))

    authorized = AsyncMock()
    loop = GoalLoop(state, payload, save, authorized)
    return loop, saves, authorized


def binding(raw=None, invoke=None, kind=CapabilityType.DATA):
    adapter = CapabilityAdapter(
        CapabilityDescriptor(
            id="cap",
            workspace_id="ws",
            type=kind,
            name="query",
            availability="available",
            risk_level="low",
            requires_confirmation=False,
        )
    )
    raw = raw if raw is not None else {"data": [{"sales": 2}], "row_count": 1}

    async def call(args, action_id):
        if invoke:
            return await invoke(args, action_id)
        return InvocationResult(adapter.observe(raw, action_id), str(raw), raw)

    fn = AsyncMock(side_effect=call)
    return Binding(SimpleNamespace(name="query", description="查询", args_schema=Args), adapter, fn)


def run(loop, model, bindings=(), required_names=()):
    async def collect():
        return [event async for event in loop.run(model, bindings, required_names=required_names)]

    return asyncio.run(collect())


def test_simple_goal_one_model_call_no_planner():
    loop, saves, auth = make_loop()
    model = FakeModel([[AIMessageChunk(content="你好")]])
    events = run(loop, model)
    assert loop.state.status == GoalStatus.COMPLETE
    assert len(model.calls) == 1 and auth.await_count >= 1
    assert loop.state.consumed["llm_calls"] == 1
    assert saves[0][0].current_action.phase == "started"
    assert events[-1]["status"] == "COMPLETE"


def test_tool_call_preamble_is_not_shown_as_a_completed_reply():
    loop, _, _ = make_loop()
    model = FakeModel([[AIMessageChunk(content="现在就发起。"), tool_call()], [AIMessageChunk(content="已取得结果。")]])
    events = run(loop, model, [binding()])
    assert loop.state.status == GoalStatus.COMPLETE
    assert [event["content"] for event in events if event["type"] == "token"] == ["已取得结果。"]
    assert loop.reply == "已取得结果。"


def test_empty_provider_call_does_not_block_complete_call():
    loop, _, _ = make_loop()
    tool = binding()
    complete = AIMessageChunk(content="", tool_call_chunks=[
        {"id": "valid", "name": "query", "args": '{"city":"杭州"}', "index": 0},
    ])
    placeholder = AIMessageChunk(content="", tool_call_chunks=[
        {"id": None, "name": "", "args": "", "index": 1},
    ])
    model = FakeModel([[complete, placeholder], [AIMessageChunk(content="已完成")]])
    run(loop, model, [tool])
    assert loop.state.status == GoalStatus.COMPLETE
    assert loop.state.consumed.get("max_replans", 0) == 0
    assert tool.invoke.await_count == 1
    assert len(loop.payload["observations"]) == 1
    assert len(model.calls) == 2
    assert len(messages_from_dict(loop.payload["messages"])[1].tool_calls) == 1


def test_repeated_partial_actions_wait_without_running_tools():
    loop, _, _ = make_loop()
    tool = binding()
    malformed = AIMessageChunk(content="", tool_calls=[
        {"id": "valid", "name": "query", "args": {"city": "杭州"}},
        {"id": None, "name": "other_action", "args": {}},
    ])
    model = FakeModel([[malformed], [malformed]])
    run(loop, model, [tool])
    assert loop.state.status == GoalStatus.WAITING
    assert loop.state.reason == "invalid_reasoning_action"
    assert tool.invoke.await_count == 0


def test_only_empty_provider_calls_are_retried_without_executing():
    loop, _, _ = make_loop()
    tool = binding()
    ghost = AIMessageChunk(content="", tool_calls=[{"id": None, "name": "", "args": {}}])
    model = FakeModel([[ghost], [ghost]])
    run(loop, model, [tool])
    assert loop.state.status == GoalStatus.WAITING
    assert loop.state.reason == "invalid_reasoning_action"
    assert tool.invoke.await_count == 0


def test_two_call_child_executes_required_tool_before_synthesis():
    state = GoalState(
        limits=effective_limits({"llm_calls": 2, "duration": 70}),
        runtime_role="CHILD",
        elapsed_seconds=61,
    )
    loop, _, _ = make_loop(state=state)
    tool = binding()
    model = FakeModel([[tool_call()], [AIMessageChunk(content="已查询并完成分析。")]])
    run(loop, model, [tool], ["query"])
    assert state.finalization_reserve["llm_calls"] == 0
    assert state.finalization_reserve["duration"] == 0
    assert tool.invoke.await_count == 1
    assert state.status == GoalStatus.COMPLETE


def test_failed_tool_call_preamble_is_not_saved_as_reply():
    loop, _, _ = make_loop()
    model = FakeModel([[AIMessageChunk(content="现在就发起。"), tool_call()], [tool_call("retry")]])
    events = run(loop, model, [binding({"error": "failed"})])
    assert loop.state.reason == "failure_limit"
    assert loop.reply == ""
    assert not any(event["type"] == "token" for event in events)


def test_observation_returns_to_reasoner_and_exact_result_cached():
    loop, saves, auth = make_loop()
    b = binding()
    model = FakeModel([[tool_call()], [tool_call("second")], [AIMessageChunk(content="销量为 2")]])
    run(loop, model, [b], ["query"])
    assert loop.state.status == GoalStatus.COMPLETE
    assert b.invoke.await_count == 1
    assert len(model.calls) == 3
    assert loop.state.consumed["tool_calls"] == 1
    assert loop.payload["observations"][0]["facts"] == [{"sales": 2}]
    assert model.calls[1][-1].content == str({"data": [{"sales": 2}], "row_count": 1})
    assert any(x[0].current_action.kind == "CAPABILITY" and x[0].current_action.phase == "started" for x in saves)


def test_large_data_results_keep_full_archive_and_fit_followup_context():
    rows = [{"门店": f"门店{i}", "地址": "完整地址" * 50, "区域": "华东"} for i in range(507)]
    raw = {
        "data": rows, "row_count": 507, "returned_rows": 507,
        "facets": {"区域": {"华东": 507}}, "truncated": False,
    }
    b = binding(raw)
    calls = [
        {"id": str(i), "name": "query", "args": {"city": str(i)}}
        for i in range(3)
    ]
    loop, _, _ = make_loop({"context_tokens": 32000})
    loop.payload["collaboration_runtime"] = True
    model = FakeModel([[AIMessageChunk(content="", tool_calls=calls)], [AIMessageChunk(content="已汇总。")]])
    run(loop, model, [b], ["query"])
    assert loop.state.status == GoalStatus.COMPLETE
    assert b.invoke.await_count == 3
    assert loop.payload["observations"][0]["raw_result"] == raw
    tool_messages = [m for m in messages_from_dict(loop.payload["messages"]) if m.type == "tool"]
    assert len(tool_messages) == 3
    projected = json.loads(json.loads(tool_messages[0].content)["result"])
    assert projected["row_count"] == 507
    assert projected["facets"] == raw["facets"]
    assert projected["sample_rows"][0] == rows[0]
    assert projected["omitted_rows"] > 0


def test_large_knowledge_view_selects_complete_sources():
    adapter = CapabilityAdapter(
        CapabilityDescriptor(id="kb", workspace_id="ws", type=CapabilityType.KNOWLEDGE, name="kb")
    )
    evidence = [{"document_id": str(i), "description": "完整片段" * 300} for i in range(10)]
    result = InvocationResult(
        adapter.observe("全文" * 10000, "action", evidence=evidence),
        "全文" * 10000,
        "全文" * 10000,
    )
    view = json.loads(model_result_text(result, max_bytes=6000))
    assert view["source_count"] == 10
    assert view["selected_sources"][0] == evidence[0]
    assert view["omitted_sources"] > 0
    assert len(json.dumps(view, ensure_ascii=False).encode()) <= 6000


def test_agent_view_keeps_child_answer_when_sources_are_large():
    adapter = CapabilityAdapter(
        CapabilityDescriptor(id="agent", workspace_id="ws", type=CapabilityType.AGENT, name="agent")
    )
    observation = adapter.observe(
        SimpleNamespace(status="success", summary="结论", result="10月方案：关注区域覆盖。", sources=[],
                        confidence=None, usage={}, input_snapshot={}),
        "action",
    )
    archived = {
        "result": "10月方案：关注区域覆盖。",
        "sources": [{"id": str(i), "name": f"来源{i}", "description": "全文" * 1000} for i in range(14)],
    }
    result = InvocationResult(observation, json.dumps(archived, ensure_ascii=False), archived)
    view = json.loads(model_result_text(result, max_bytes=6000))
    assert view["agent_result"] == archived["result"]
    assert view["source_count"] == 14


@pytest.mark.parametrize(
    "budget,reason",
    [({"llm_calls": 0}, "llm_calls"), ({"output_tokens": 0}, "output_tokens"), ({"context_tokens": 256}, "context")],
)
def test_exhaustion_before_model(budget, reason):
    loop, _, _ = make_loop(budget)
    if reason == "context":
        loop.payload["messages"] = serialize_messages([{"role": "user", "content": "长" * 200}])
    model = FakeModel([])
    run(loop, model)
    assert loop.state.status == GoalStatus.BLOCKED and reason in loop.state.reason
    assert not model.calls


def test_budget_hierarchy_and_atomic_reservation():
    limits = effective_limits({"tool_calls": 4}, {"tool_calls": 3}, {"tool_calls": 10}, {"tool_calls": 20})
    assert limits.tool_calls == 3
    state = GoalState(limits=limits)
    budget = RuntimeBudget(state)
    with pytest.raises(RuntimeHalt):
        budget.reserve(llm_calls=1, tool_calls=4)
    assert state.consumed == {}
    with pytest.raises(ValidationError):
        effective_limits({"llm_calls": -1})
    with pytest.raises(ValidationError):
        effective_limits({"llm_calls": True})
    with pytest.raises(ValueError):
        effective_limits({"agent_calls": 6})


def test_not_ready_waits_without_invocation_and_batch_protocol_is_complete():
    loop, _, _ = make_loop()
    b = binding()
    response = AIMessageChunk(
        content="",
        tool_calls=[{"name": "query", "args": {}, "id": "a"}, {"name": "query", "args": {"city": "杭州"}, "id": "b"}],
    )
    run(loop, FakeModel([[response]]), [b])
    assert loop.state.status == GoalStatus.WAITING
    assert loop.state.next_action == "ASK_USER"
    assert b.invoke.await_count == 0
    messages = messages_from_dict(loop.payload["messages"])
    assert [m.tool_call_id for m in messages if m.type == "tool"] == ["a", "b"]


def test_failure_replans_once_then_blocks_and_does_not_retry_same_tool():
    loop, _, _ = make_loop()
    b = binding({"error": "failed"})
    model = FakeModel([[tool_call()], [tool_call("retry")]])
    run(loop, model, [b])
    assert loop.state.status == GoalStatus.BLOCKED
    assert loop.state.reason == "failure_limit"
    assert b.invoke.await_count == 1
    assert loop.state.consumed["max_replans"] == 1


def test_external_timeout_is_unknown_and_waiting_not_auto_retry():
    async def timeout(*args):
        raise TimeoutError()

    b = binding(invoke=timeout)
    loop, _, _ = make_loop()
    run(loop, FakeModel([[tool_call()]]), [b])
    assert loop.state.status == GoalStatus.WAITING
    assert loop.state.reason == "action_result_unknown"
    assert loop.state.current_action.phase == "unknown"
    assert b.invoke.await_count == 1


def test_model_timeout_records_child_duration_failure():
    state = GoalState(limits=effective_limits({"duration": 42}), runtime_role="CHILD")
    loop, _, _ = make_loop(state=state)
    run(loop, FakeModel([[TimeoutError()]]))
    assert state.status == GoalStatus.BLOCKED
    assert state.reason == "budget_exhausted:duration"
    assert state.budget_failure["resource"] == "duration"
    assert state.budget_failure["limit"] == 42
    assert state.budget_failure["runtime"] == "CHILD"


def test_checkpoint_failure_prevents_external_action():
    loop, _, _ = make_loop()
    loop.checkpoint = AsyncMock(side_effect=RuntimeError("disk failure"))
    model = FakeModel([[tool_call()]])
    b = binding()
    with pytest.raises(RuntimeError):
        run(loop, model, [b])
    assert not model.calls and b.invoke.await_count == 0


def test_unauthorized_model_capability_and_no_grounding_are_blocked():
    loop, _, _ = make_loop()
    run(loop, FakeModel([[tool_call(name="invented")]]), [binding()])
    assert loop.state.reason == "capability_not_authorized"
    loop, _, _ = make_loop()
    events = run(loop, FakeModel([[AIMessageChunk(content="编造数据")]]), [binding()], ["query"])
    assert loop.state.reason == "required_capability_not_used"
    assert not any(e["type"] == "token" for e in events)


def test_duration_uses_cumulative_work_time_and_does_not_reset_on_resume():
    now = [10]
    state = GoalState(limits=effective_limits({"duration": 5}), elapsed_seconds=3)
    budget = RuntimeBudget(state, clock=lambda: now[0])
    now[0] = 12
    with pytest.raises(RuntimeHalt, match="duration"):
        budget.reserve(llm_calls=1)


def test_cancel_propagates_with_partial_reply_and_no_more_actions():
    loop, _, _ = make_loop()
    model = FakeModel([[AIMessageChunk(content="部分"), asyncio.CancelledError()]])
    with pytest.raises(asyncio.CancelledError):
        run(loop, model)
    assert loop.reply == "部分"
    assert loop.state.current_action.phase == "started"


def test_output_limit_stops_stream_and_no_false_complete():
    loop, _, _ = make_loop({"output_tokens": 4})
    events = run(loop, FakeModel([[AIMessageChunk(content="abcdef")]]))
    assert loop.state.reason == "budget_exhausted:output_tokens"
    assert not any(e["type"] == "token" for e in events)


def test_artifacts_private_and_integrity_checked(tmp_path):
    files = ArtifactStore(tmp_path)
    import uuid

    goal_id = uuid.uuid4()
    ref = files.write(goal_id, {"evidence": "完整资料"})
    assert files.read(goal_id, ref)["evidence"] == "完整资料"
    path = tmp_path / str(goal_id) / (ref["key"] + ".json")
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_text("{}")
    with pytest.raises(ValueError):
        files.read(goal_id, ref)
    with pytest.raises(ValueError):
        files.read(goal_id, {**ref, "key": "../../.env"})


def test_revoked_capability_is_checked_even_for_cached_results():
    loop, _, _ = make_loop()
    b = binding()
    b.authorize = AsyncMock(side_effect=[None, PermissionError("revoked")])
    model = FakeModel([[tool_call()], [tool_call("cached")]])
    with pytest.raises(PermissionError):
        run(loop, model, [b])
    assert b.invoke.await_count == 1 and b.authorize.await_count == 2


def test_completed_or_waiting_state_does_not_execute_again():
    for status in (GoalStatus.COMPLETE, GoalStatus.WAITING, GoalStatus.BLOCKED):
        loop, _, _ = make_loop(state=GoalState(status=status))
        model = FakeModel([])
        run(loop, model, [binding()])
        assert not model.calls


def test_usage_correlates_goal_and_action_without_prompt(monkeypatch, tmp_path):
    from test_model_usage import mock_model

    from agentdevstu.usage.collector import UsageCallback, pending_batch

    monkeypatch.setenv("USAGE_SPOOL_PATH", str(tmp_path / "usage.sqlite"))
    callback = UsageCallback("test", "openai", "model")
    model = mock_model(callback)
    loop, _, _ = make_loop()
    run(loop, model)
    entries = [json.loads(row[3])["call"] for row in pending_batch()]
    assert len(entries) == 1
    runtime = entries[0]["usage_detail"]["runtime"]
    assert runtime["goal_id"] == "test" and runtime["action_id"] == loop.state.current_action.id
    assert runtime["purpose"] == "RUNTIME_REASONING"
    assert "secret-prompt" not in json.dumps(entries)


def test_high_risk_capability_waits_for_approval_without_execution():
    b = binding()
    b.adapter.descriptor.requires_confirmation = True
    loop, _, _ = make_loop()
    run(loop, FakeModel([[tool_call()]]), [b])
    assert loop.state.status == GoalStatus.WAITING
    assert loop.state.next_action == "REQUEST_APPROVAL"
    assert b.invoke.await_count == 0


def test_artifact_keeps_decimal_and_date_type_information(tmp_path):
    import uuid
    from datetime import date
    from decimal import Decimal

    files = ArtifactStore(tmp_path)
    goal_id = uuid.uuid4()
    ref = files.write(goal_id, {"price": Decimal("123.000000000000000001"), "date": date(2026, 9, 23)})
    result = files.read(goal_id, ref)
    assert result["price"] == {"$runtime_type": "Decimal", "value": "123.000000000000000001"}
    assert result["date"] == {"$runtime_type": "date", "value": "2026-09-23"}
