"""Effective Workspace policy, preflight and protected runtime budgets."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessageChunk
from test_goal_loop import FakeModel, binding, make_loop, run

from cortexa.api import runtime_policy as runtime_policy_api
from cortexa.api.goals import budget_preflight
from cortexa.runtime.adapters import CapabilityAdapter
from cortexa.runtime.agent_executor import allocate_child_limits
from cortexa.runtime.capabilities import CapabilityDescriptor, CapabilityType
from cortexa.runtime.collaboration import Autonomy
from cortexa.runtime.policy import resolve_effective_policy
from cortexa.runtime.state import (
    UNLIMITED_BUDGET,
    BudgetPhase,
    GoalState,
    GoalStatus,
    RuntimeBudget,
    effective_limits,
    platform_hard_limits,
)


def agent(collaboration=None, quality_policy=None):
    return SimpleNamespace(collaboration=collaboration or {}, quality_policy=quality_policy or {})


def test_policy_inheritance_dynamic_sources_and_hard_limits():
    a = agent()
    legacy = resolve_effective_policy({}, None, a)
    assert legacy.effective_budget.output_tokens == 16384
    assert legacy.collaboration_mode == Autonomy.EXPLICIT_ONLY

    workspace = {
        "version": 1,
        "budget": {"llm_calls": 4, "agent_calls": 2},
        "collaboration": {"max_autonomy": "AUTONOMOUS", "candidate_limit": 2},
    }
    effective = resolve_effective_policy({}, workspace, a, {"llm_calls": 3, "agent_calls": 5})
    assert effective.effective_budget.llm_calls == 3
    assert effective.effective_budget.agent_calls == 2
    assert effective.collaboration_mode == Autonomy.AUTONOMOUS
    assert effective.trace["budget"]["llm_calls"]["source"] == "Goal"
    assert effective.trace["budget"]["agent_calls"]["source"] == "Workspace"
    assert effective.trace["collaboration"]["source"] == "Workspace"

    workspace["budget"]["llm_calls"] = 2
    assert resolve_effective_policy({}, workspace, a).effective_budget.llm_calls == 2
    assert resolve_effective_policy({}, workspace, agent({"autonomy": "EXPLICIT_ONLY"})).collaboration_mode == (
        Autonomy.EXPLICIT_ONLY
    )
    assert resolve_effective_policy({}, None, agent({"autonomy": "AUTONOMOUS"})).collaboration_mode == (
        Autonomy.AUTONOMOUS
    )


def test_workspace_can_raise_defaults_within_platform_ceiling():
    defaults = resolve_effective_policy({}, None, agent())
    assert defaults.effective_budget.agent_calls == 3
    assert defaults.candidate_limit == 3
    workspace = {
        "budget": {"agent_calls": 5, "max_collaborators": 5, "llm_calls": 10},
        "collaboration": {"candidate_limit": 5, "max_autonomy": "AUTONOMOUS"},
    }
    resolved = resolve_effective_policy({}, workspace, agent())
    assert resolved.effective_budget.agent_calls == 5
    assert resolved.effective_budget.max_collaborators == 5
    assert resolved.effective_budget.llm_calls == 10
    assert resolved.candidate_limit == 5
    assert resolved.trace["budget"]["agent_calls"]["source"] == "Workspace"
    assert platform_hard_limits()["agent_calls"] == 5
    assert (
        resolve_effective_policy(
            {}, workspace, agent(quality_policy={"runtime": {"budget": {"llm_calls": 4}}})
        ).effective_budget.llm_calls
        == 4
    )
    assert resolve_effective_policy({}, workspace, agent(), {"agent_calls": 3}).effective_budget.agent_calls == 3

    parent = GoalState(limits=resolved.effective_budget)
    child = allocate_child_limits(RuntimeBudget(parent), resolved.effective_budget, remaining_slots=1)
    assert child is not None
    assert child.llm_calls > defaults.effective_budget.llm_calls


def test_workspace_unlimited_field_removes_application_budget_ceiling():
    workspace = {"budget": {"output_tokens": None, "llm_calls": None}}
    resolved = resolve_effective_policy({}, workspace, agent())
    assert resolved.effective_budget.output_tokens == UNLIMITED_BUDGET
    assert resolved.effective_budget.llm_calls == UNLIMITED_BUDGET
    assert resolved.effective_budget.duration == 180
    assert platform_hard_limits()["output_tokens"] == 32768
    state = GoalState(limits=resolved.effective_budget)
    budget = RuntimeBudget(state)
    budget.reserve(llm_calls=100, output_tokens=200000)
    assert budget.remaining("output_tokens") > 0
    assert budget.phase() == BudgetPhase.NORMAL
    agent_limit = resolve_effective_policy(
        {}, workspace, agent(quality_policy={"runtime": {"budget": {"output_tokens": 163840}}})
    )
    assert agent_limit.effective_budget.output_tokens == 163840


def test_workspace_policy_api_saves_unlimited_and_reports_finite_overage(monkeypatch):
    class FakeDB:
        def __init__(self):
            self.workspace = SimpleNamespace(runtime_policy={})

        async def scalar(self, _query):
            return self.workspace

        async def commit(self):
            pass

    monkeypatch.setattr(runtime_policy_api, "authorize", lambda _id: None)
    monkeypatch.setattr(runtime_policy_api, "platform_config", lambda: {})
    db = FakeDB()
    result = asyncio.run(runtime_policy_api.put_policy(
        uuid.uuid4(), runtime_policy_api.BudgetPolicyUpdate(budget={"output_tokens": None}), db
    ))
    assert result["budget"]["output_tokens"] is None
    assert result["effective_budget"]["output_tokens"] == UNLIMITED_BUDGET
    with pytest.raises(HTTPException, match="output_tokens 超过平台上限 32768"):
        asyncio.run(runtime_policy_api.put_policy(
            uuid.uuid4(), runtime_policy_api.BudgetPolicyUpdate(budget={"output_tokens": 163840}), db
        ))


def test_preflight_rejects_obvious_participant_and_call_shortage():
    state = GoalState(limits=effective_limits({"max_collaborators": 2}))
    with pytest.raises(HTTPException, match="最多允许 2 个"):
        budget_preflight(state, ["a", "b", "c"])
    with pytest.raises(HTTPException, match="至少需要 6 次模型调用"):
        budget_preflight(GoalState(limits=effective_limits({"llm_calls": 3})), ["a", "b"])


def test_child_allocation_preserves_parent_finalization_reserve():
    parent = GoalState()
    budget = RuntimeBudget(parent)
    child = allocate_child_limits(budget, parent.limits, remaining_slots=2)
    assert child is not None
    assert child.output_tokens <= 6144
    assert child.llm_calls <= 2
    assert child.duration > 75  # usable time for a slow first model, with time left for the next child
    budget.reserve(output_tokens=child.output_tokens, llm_calls=child.llm_calls)
    assert budget.remaining("output_tokens") >= parent.finalization_reserve["output_tokens"]
    assert budget.remaining("llm_calls") >= parent.finalization_reserve["llm_calls"]


def test_budget_phases_conserve_then_finalize():
    state = GoalState()
    budget = RuntimeBudget(state)
    assert budget.phase() == BudgetPhase.NORMAL
    state.consumed["output_tokens"] = 9000
    assert budget.phase() == BudgetPhase.CONSERVE
    state.consumed["output_tokens"] = 12288
    assert budget.phase() == BudgetPhase.FINALIZING
    assert not budget.can_expand(max_steps=1)
    state.consumed["output_tokens"] = 16384
    assert budget.phase() == BudgetPhase.EXHAUSTED


def test_finalizing_synthesizes_existing_observation_as_partial():
    state = GoalState(limits=effective_limits({"output_tokens": 1000}))
    state.consumed["output_tokens"] = 750
    loop, _, _ = make_loop(state=state)
    loop.payload["observations"] = [{"status": "SUCCESS", "summary": "已获得部分数据"}]
    model = FakeModel([[AIMessageChunk(content="已获得部分数据；其余尚未完成。")]])
    run(loop, model, [binding()], ["query"])
    assert loop.state.status == GoalStatus.COMPLETE
    assert loop.state.partial is True
    assert loop.state.budget_phase == BudgetPhase.FINALIZING
    assert "其余尚未完成" in loop.reply
    policy_event = loop.trace[0]["detail"]
    assert policy_event["limits"]["output_tokens"] == 1000
    assert "finalization_reserve" in policy_event
    assert loop.trace[-1]["detail"]["budget_phase"] == BudgetPhase.FINALIZING


def test_conserve_hides_optional_tools():
    class TrackingModel(FakeModel):
        def bind_tools(self, tools):
            self.offered = [tool.name for tool in tools]
            return self

    state = GoalState(limits=effective_limits({"output_tokens": 1000}))
    state.consumed["output_tokens"] = 500
    loop, _, _ = make_loop(state=state)
    model = TrackingModel([[AIMessageChunk(content="根据已有信息回答。")]])
    run(loop, model, [binding()])
    assert loop.state.status == GoalStatus.COMPLETE
    assert not hasattr(model, "offered")


def test_planning_output_stops_before_consuming_finalization_budget():
    loop, _, _ = make_loop({"output_tokens": 1000})
    model = FakeModel(
        [
            [AIMessageChunk(content="x" * 800)],
            [AIMessageChunk(content="已有信息不足，任务尚未完成。")],
        ]
    )
    run(loop, model)
    assert loop.state.status == GoalStatus.COMPLETE
    assert loop.state.partial is True
    assert loop.payload["force_finalizing"] is True
    assert loop.reply == "已有信息不足，任务尚未完成。"
    assert loop.state.consumed["output_tokens"] < loop.state.limits.output_tokens


def test_partial_agent_result_is_a_usable_observation():
    adapter = CapabilityAdapter(
        CapabilityDescriptor(id="agent:child", workspace_id="ws", type=CapabilityType.AGENT, name="child")
    )
    result = SimpleNamespace(
        status="partial",
        summary="已取得部分结果",
        result="已取得部分结果",
        sources=[],
        confidence=None,
        usage={},
        input_snapshot={},
    )
    assert adapter.observe(result, "action").status == "PARTIAL"
