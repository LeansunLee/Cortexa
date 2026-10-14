import pytest

from cortexa.runtime.recovery import reset_unstarted_agent, unstarted_agent_action
from cortexa.runtime.state import Action, GoalState


def state_before_child_execution():
    return GoalState(
        current_action=Action(id="action", kind="CAPABILITY", capability_id="agent:target", phase="unknown"),
        used_agents=["target"],
        active_agent_path=["source", "target"],
        child_allocations=[{"action_id": "action", "agent_id": "target", "consumed": {}}],
    )


def test_initialization_failure_can_resume_without_replaying_business_queries():
    state = state_before_child_execution()
    state.consumed = {"tool_calls": 3, "llm_calls": 2}
    payload = {"observations": [{"action_id": "previous-query", "status": "SUCCESS"}]}
    assert unstarted_agent_action(state, payload)
    reset_unstarted_agent(state)
    assert state.current_action.phase == "completed"
    assert not state.used_agents and not state.child_allocations and not state.active_agent_path
    assert state.consumed == {"tool_calls": 3, "llm_calls": 2}
    assert len(payload["observations"]) == 1


@pytest.mark.parametrize("evidence", ["checkpoint", "consumption", "active_action", "observation", "proxy", "no_allocation"])
def test_execution_or_missing_proof_prevents_automatic_retry(evidence):
    state = state_before_child_execution()
    payload = {}
    if evidence == "checkpoint":
        payload["agent_runs"] = {"action": {"state": {}}}
    elif evidence == "consumption":
        state.child_allocations[0]["consumed"] = {"llm_calls": 1}
    elif evidence == "active_action":
        state.active_agent_action = {"agent_id": "target"}
    elif evidence == "observation":
        payload["observations"] = [{"action_id": "action"}]
    elif evidence == "proxy":
        state.child_allocations = []  # Proxy calls do not use child-loop allocations.
    elif evidence == "no_allocation":
        state.child_allocations = []
    assert not unstarted_agent_action(state, payload)
