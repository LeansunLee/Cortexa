"""Resolve platform, workspace, Agent and Goal runtime rules in one place."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from cortexa.runtime.collaboration import LEVEL, Autonomy, effective_policy
from cortexa.runtime.state import UNLIMITED_BUDGET, BudgetLimits, platform_hard_limits


@dataclass(frozen=True)
class EffectiveRuntimePolicy:
    effective_budget: BudgetLimits
    collaboration_mode: Autonomy
    candidate_limit: int
    collaboration_enabled: bool
    trace: dict


def platform_config():
    path = Path(__file__).resolve().parents[3] / "config.yaml"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def resolve_effective_policy(config, workspace_policy=None, agent=None, goal_budget=None, *, conversation_mode=None):
    workspace = workspace_policy or {}
    if workspace.get("version", 1) != 1:
        raise ValueError("Unsupported Workspace runtime policy version")
    agent_policy = (getattr(agent, "quality_policy", None) or {}).get("runtime", {}) if agent else {}
    platform_budget = (config or {}).get("runtime", {}).get("budget")
    ceilings = platform_hard_limits(platform_budget)
    values = BudgetLimits().model_dump()
    budget_trace = {key: {"source": "Platform default", "value": value} for key, value in values.items()}
    for key in values:
        if values[key] > ceilings[key]:
            values[key] = ceilings[key]
            budget_trace[key] = {"source": "Platform", "value": ceilings[key]}
    for source, raw in (
        ("Workspace", workspace.get("budget")),
        ("Agent", agent_policy.get("budget")),
        ("Goal", goal_budget),
    ):
        if raw is None:
            continue
        validated = BudgetLimits.model_validate(raw)
        for key in validated.model_fields_set:
            value = getattr(validated, key)
            if source == "Workspace":
                values[key] = value if value == UNLIMITED_BUDGET else min(value, ceilings[key])
                budget_trace[key] = {
                    "source": "Workspace" if value <= ceilings[key] or value == UNLIMITED_BUDGET else "Platform",
                    "value": values[key],
                }
            elif value <= values[key]:
                values[key] = value
                budget_trace[key] = {"source": source, "value": value}
    platform_collaboration = (config or {}).get("runtime", {}).get("collaboration")
    workspace_collaboration = workspace.get("collaboration")
    mode, candidate_limit, enabled = effective_policy(
        agent or type("DefaultAgent", (), {"collaboration": {}})(),
        platform_collaboration,
        workspace_collaboration,
    )
    agent_autonomy = (getattr(agent, "collaboration", None) or {}).get("autonomy") if agent else None
    workspace_mode = (workspace_collaboration or {}).get("max_autonomy")
    platform_mode = (platform_collaboration or {}).get("max_autonomy")
    mode_layers = []
    if agent_autonomy and agent_autonomy != "INHERIT_WORKSPACE":
        mode_layers.append(("Agent", Autonomy(agent_autonomy)))
    elif workspace_mode:
        mode_layers.append(("Workspace", Autonomy(workspace_mode)))
    else:
        mode_layers.append(("Platform default", Autonomy.EXPLICIT_ONLY))
    if workspace_mode:
        mode_layers.append(("Workspace", Autonomy(workspace_mode)))
    if platform_mode:
        mode_layers.append(("Platform", Autonomy(platform_mode)))
    if conversation_mode is not None:
        # A workspace sets the ceiling; every conversation makes its own choice.
        ceiling = Autonomy(workspace_mode or Autonomy.EXPLICIT_ONLY)
        selected = Autonomy(conversation_mode)
        mode = min(mode, ceiling, selected, key=LEVEL.get)
        mode_layers.extend([("Workspace", ceiling), ("Conversation", selected)])
    mode_source = min(mode_layers, key=lambda item: LEVEL[item[1]])[0]
    return EffectiveRuntimePolicy(
        effective_budget=BudgetLimits(**values),
        collaboration_mode=mode,
        candidate_limit=candidate_limit,
        collaboration_enabled=enabled,
        trace={
            "budget": budget_trace,
            "collaboration": {
                "source": mode_source,
                "mode": mode,
                "enabled": enabled,
                "layers": [{"source": source, "mode": value} for source, value in mode_layers],
            },
        },
    )


def conversation_modes(config, workspace_policy=None, agent=None):
    policy = resolve_effective_policy(
        config, workspace_policy, agent, conversation_mode=Autonomy.AUTONOMOUS
    )
    ceiling = policy.collaboration_mode if policy.collaboration_enabled else Autonomy.EXPLICIT_ONLY
    return [mode for mode in Autonomy if LEVEL[mode] <= LEVEL[ceiling]]
