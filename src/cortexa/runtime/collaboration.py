"""Deterministic Agent discovery and Goal-scoped collaboration authorization."""

import hashlib
import json
import re
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from cortexa.db.models import Agent, Workspace
from cortexa.runtime.adapters import agent_adapter
from cortexa.runtime.capabilities import MatchScope, match_capabilities
from cortexa.runtime.goals import parse_goal
from cortexa.runtime.proxy import enabled as proxy_enabled
from cortexa.runtime.state import GoalStatus, RuntimeHalt
from cortexa.security.access import actor_required, require_agent_use


class Autonomy(StrEnum):
    EXPLICIT_ONLY = "EXPLICIT_ONLY"
    ASK_BEFORE_COLLABORATION = "ASK_BEFORE_COLLABORATION"
    AUTONOMOUS = "AUTONOMOUS"


LEVEL = {value: index for index, value in enumerate(Autonomy)}


class CollaborationSettings(BaseModel):
    model_config = ConfigDict(extra="allow")  # Preserve existing consult/delegate configuration.
    autonomy: Autonomy | Literal["INHERIT_WORKSPACE"] = "INHERIT_WORKSPACE"
    allow_incoming: bool = True
    discoverable: bool = True
    aliases: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=20)
    operations: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=20)
    candidate_limit: int = Field(default=3, ge=1, le=5)


class CollaborationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_autonomy: Autonomy = Autonomy.AUTONOMOUS
    enabled: bool = True
    candidate_limit: int = Field(default=3, ge=1, le=5)


def settings(agent):
    return CollaborationSettings.model_validate(getattr(agent, "collaboration", None) or {})


def effective_policy(source, *policies):
    own = settings(source)
    own_raw = getattr(source, "collaboration", None) or {}
    workspace_mode = None
    if len(policies) >= 2 and isinstance(policies[-1], dict):
        workspace_mode = policies[-1].get("max_autonomy")
    mode = (
        Autonomy(workspace_mode)
        if own.autonomy == "INHERIT_WORKSPACE" and workspace_mode
        else Autonomy.EXPLICIT_ONLY
        if own.autonomy == "INHERIT_WORKSPACE"
        else own.autonomy
    )
    workspace_raw = policies[-1] if len(policies) >= 2 and isinstance(policies[-1], dict) else {}
    limit = own.candidate_limit if "candidate_limit" in own_raw else workspace_raw.get("candidate_limit", 3)
    enabled = True
    for raw in policies:
        policy = CollaborationPolicy.model_validate(
            {key: value for key, value in (raw or {}).items() if key in CollaborationPolicy.model_fields}
        )
        mode = min(mode, policy.max_autonomy, key=LEVEL.get)
        if raw and "candidate_limit" in raw:
            limit = min(limit, policy.candidate_limit)
        enabled = enabled and policy.enabled
    return mode, limit, enabled


def goal_constraints(payload):
    texts = [payload["goal"]["raw_request"], *payload.get("clarifications", [])]
    constraints = [parse_goal(text).collaboration_constraints for text in texts]
    return constraints


def permitted_by_goal(agent, payload, *, discovery=False):
    names = {agent.name.casefold(), *(x.casefold() for x in settings(agent).aliases)}
    for constraint in goal_constraints(payload):
        if not constraint.allow_collaboration or (discovery and not constraint.allow_discovery):
            return False
        if constraint.only_agents and not any(name.casefold() in names for name in constraint.only_agents):
            return False
    return True


async def policy_for(db, source, config, state=None):
    workspace = await db.scalar(select(Workspace.runtime_policy).where(Workspace.id == source.workspace_id))
    try:
        from cortexa.runtime.policy import resolve_effective_policy

        resolved = resolve_effective_policy(config, workspace, source)
        mode = resolved.collaboration_mode
        if state is not None:
            mode = min(mode, Autonomy(state.collaboration_mode), key=LEVEL.get)
        return mode, resolved.candidate_limit, resolved.collaboration_enabled
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "协作策略格式或范围不合法") from None


async def available_agents(db, source):
    actor = actor_required()
    # ORM scope + explicit runtime grants before ranking. Never put this directory in a prompt.
    agents = (
        await db.scalars(
            select(Agent)
            .where(Agent.workspace_id == source.workspace_id, Agent.status == "active", Agent.id != source.id)
            .order_by(Agent.id)
        )
    ).all()
    return [a for a in agents if actor.can_use(a) and settings(a).allow_incoming]


async def resolve_explicit(db, source, goal, ids=(), config=None):
    agents = await available_agents(db, source)
    by_id = {str(a.id): a for a in agents}
    selected = set(str(i) for i in ids)
    from types import SimpleNamespace

    references = list(goal.explicit_agents) + [
        SimpleNamespace(reference=name, kind="name") for name in goal.collaboration_constraints.only_agents
    ]
    for participant in references:
        if participant.kind == "id":
            selected.add(participant.reference)
            continue
        matches = [
            a
            for a in agents
            if participant.reference.casefold() in {a.name.casefold(), *(x.casefold() for x in settings(a).aliases)}
        ]
        if len(matches) != 1:
            raise HTTPException(422, "@Agent 不存在、未授权或名称不唯一，请从候选列表选择")
        selected.add(str(matches[0].id))
    if len(selected) > 5 or any(ident not in by_id for ident in selected):
        raise HTTPException(422, "显式参与者超出范围、未授权或不可用")
    if any(not proxy_enabled(by_id[ident], config or {}) for ident in selected):
        raise HTTPException(409, "该代理尚未开启目标输入契约，请配置发布后使用，或切换普通对话")
    return sorted(selected)


async def discover(db, source, state, payload, config):
    mode, top_k, enabled = await policy_for(db, source, config, state)
    top_k = min(top_k, max(0, state.limits.max_collaborators - len(state.used_agents)))
    agents = await available_agents(db, source)
    fixed = set(state.explicit_agents) | (set(state.approved_agents) if mode != Autonomy.EXPLICIT_ONLY else set())
    denied = set(state.denied_agents)
    allowed = [
        a
        for a in agents
        if enabled
        and proxy_enabled(a, config)
        and str(a.id) not in denied
        and permitted_by_goal(a, payload)
        and (
            str(a.id) in state.explicit_agents
            or (
                str(a.id) in state.approved_agents
                and mode != Autonomy.EXPLICIT_ONLY
                and settings(a).discoverable
                and permitted_by_goal(a, payload, discovery=True)
            )
            or (
                mode != Autonomy.EXPLICIT_ONLY
                and settings(a).discoverable
                and permitted_by_goal(a, payload, discovery=True)
            )
        )
    ]
    explicit = [a for a in allowed if str(a.id) in fixed]
    candidates = [a for a in allowed if str(a.id) not in fixed]
    descriptors = []
    for agent in candidates:
        descriptor = agent_adapter(agent).descriptor
        descriptor.aliases = settings(agent).aliases
        descriptor.operations = settings(agent).operations
        descriptors.append(descriptor)
    query = payload["goal"]["raw_request"] + "\n" + "\n".join(payload.get("clarifications", []))
    invitation_requested = bool(re.search(
        r"(?:邀请|请|找|叫|让|委托|协同|协作).{0,12}(?:同事|智能体|Agent|代理|帮手)|"
        r"(?:同事|智能体|Agent|代理).{0,8}(?:一起|参与|协作|帮忙)",
        query, re.I,
    ))
    payload["explicit_invitation"] = invitation_requested
    matches = match_capabilities(
        query,
        descriptors,
        MatchScope(str(source.workspace_id), frozenset(c.id for c in descriptors)),
        top_k=top_k,
        operations=tuple(payload["goal"].get("operations", [])),
    )
    selected_ids = {m.capability.id.removeprefix("agent:") for m in matches}
    if invitation_requested and not selected_ids:
        # Let the model assess bounded eligible descriptions when the user's
        # invitation has no lexical overlap with the catalog.
        selected_ids = {str(a.id) for a in candidates[:top_k]}
    chosen = sorted(explicit + [a for a in candidates if str(a.id) in selected_ids], key=lambda a: str(a.id))
    state.candidate_agents = sorted(str(a.id) for a in chosen if str(a.id) not in fixed)
    return chosen, mode


async def authorize_agent(db, source_id, target_id, state, payload, config, *, in_progress=False):
    source = await require_agent_use(db, source_id)
    target = await require_agent_use(db, target_id)
    ident = str(target.id)
    if not in_progress and ident not in state.used_agents and len(state.used_agents) >= state.limits.max_collaborators:
        state.budget_failure = {
            "resource": "max_collaborators",
            "current": len(state.used_agents),
            "requested": 1,
            "limit": state.limits.max_collaborators,
            "runtime": state.runtime_role,
            "agent_id": state.runtime_agent_id,
            "phase": state.budget_phase,
        }
        raise RuntimeHalt("budget_exhausted:max_collaborators")
    mode, _, enabled = await policy_for(db, source, config, state)
    if (
        config.get("features", {}).get("goal_collaboration_enabled") is not True
        or not proxy_enabled(target, config)
        or target.workspace_id != source.workspace_id
        or not enabled
        or not settings(target).allow_incoming
        or not permitted_by_goal(target, payload)
    ):
        raise RuntimeHalt("collaboration_policy_denied")
    if ident == str(source.id) or (ident in state.active_agent_path and not in_progress):
        raise RuntimeHalt("collaboration_cycle")
    if ident in state.denied_agents:
        raise RuntimeHalt("collaboration_denied")
    if ident in state.explicit_agents:
        return target, "USER_EXPLICIT"
    if mode == Autonomy.EXPLICIT_ONLY or not permitted_by_goal(target, payload, discovery=True):
        raise RuntimeHalt("collaboration_explicit_only")
    if not settings(target).discoverable:
        raise RuntimeHalt("collaboration_unavailable")
    if ident in state.approved_agents:
        return target, "USER_APPROVED"
    if ident not in state.candidate_agents:
        raise RuntimeHalt("collaboration_not_candidate")
    if mode == Autonomy.ASK_BEFORE_COLLABORATION:
        state.pending_agents = sorted(
            set(state.candidate_agents) - set(state.denied_agents) - set(state.approved_agents)
        )
        raise RuntimeHalt("collaboration_approval_required", status=GoalStatus.WAITING, next_action="REQUEST_APPROVAL")
    return target, "RUNTIME_AUTONOMOUS"


def decision_fingerprint(revision, approved, denied):
    return hashlib.sha256(json.dumps([revision, sorted(approved), sorted(denied)]).encode()).hexdigest()
