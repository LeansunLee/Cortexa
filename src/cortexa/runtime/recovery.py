"""Recovery is safe only before the child's durable execution checkpoint."""


def unstarted_agent_action(state, payload):
    action = state.current_action
    if not action or action.kind != "CAPABILITY" or not (action.capability_id or "").startswith("agent:"):
        return False
    if action.phase != "unknown" or action.id in payload.get("agent_runs", {}):
        return False
    if any(item.get("action_id") == action.id for item in payload.get("observations", [])):
        return False
    allocations = [item for item in state.child_allocations if item.get("action_id") == action.id]
    return len(allocations) == 1 and not allocations[0].get("consumed") and not state.active_agent_action


def reset_unstarted_agent(state):
    action = state.current_action
    target_id = action.capability_id.removeprefix("agent:")
    state.used_agents = [item for item in state.used_agents if item != target_id]
    state.child_allocations = [item for item in state.child_allocations if item.get("action_id") != action.id]
    state.active_agent_path = []
    state.active_agent_action = None
    action.phase = "completed"
