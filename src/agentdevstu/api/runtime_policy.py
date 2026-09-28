"""Workspace runtime budget configuration, without exposing future policy namespaces."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from agentdevstu.api.deps import get_db
from agentdevstu.db.models import Workspace
from agentdevstu.runtime.collaboration import CollaborationPolicy
from agentdevstu.runtime.policy import platform_config, resolve_effective_policy
from agentdevstu.runtime.state import BudgetLimits, platform_hard_limits
from agentdevstu.security.access import actor_required, require

router = APIRouter(prefix="/workspaces", tags=["runtime-policy"])


class BudgetPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget: dict | None = None
    collaboration: CollaborationPolicy | None = None


def authorize(workspace_id):
    if actor_required().workspace_id != workspace_id:
        raise HTTPException(403, "请先选择对应工作空间")
    require("workspace.manage")


@router.get("/{workspace_id}/runtime-policy")
async def get_policy(workspace_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]):
    authorize(workspace_id)
    policy = await db.scalar(select(Workspace.runtime_policy).where(Workspace.id == workspace_id))
    config = platform_config()
    effective = resolve_effective_policy(config, policy)
    return {
        "version": 1,
        "budget": (policy or {}).get("budget"),
        "collaboration": (policy or {}).get("collaboration"),
        "platform_defaults": resolve_effective_policy(config).effective_budget.model_dump(),
        "platform_limits": platform_hard_limits(config.get("runtime", {}).get("budget")),
        "effective_budget": effective.effective_budget.model_dump(),
        "effective_collaboration_policy": effective.collaboration_mode,
        "source_trace": effective.trace,
    }


@router.put("/{workspace_id}/runtime-policy")
async def put_policy(
    workspace_id: uuid.UUID, payload: BudgetPolicyUpdate, db: Annotated[AsyncSession, Depends(get_db)]
):
    authorize(workspace_id)
    config = platform_config()
    platform = platform_hard_limits(config.get("runtime", {}).get("budget"))
    try:
        BudgetLimits.model_validate(payload.budget or {})
    except ValidationError as exc:
        field = exc.errors()[0]["loc"][0]
        if field in BudgetLimits.model_fields:
            raise HTTPException(422, f"Runtime 预算 {field} 格式或范围不合法") from None
        raise HTTPException(422, f"Runtime 预算包含未知字段：{field}") from None
    for key, value in (payload.budget or {}).items():
        if value is not None and value > platform[key]:
            raise HTTPException(422, f"Runtime 预算 {key} 超过平台上限 {platform[key]}")
    workspace = await db.scalar(
        select(Workspace)
        .options(undefer(Workspace.runtime_policy))
        .where(Workspace.id == workspace_id)
        .with_for_update()
    )
    if workspace is None:
        raise HTTPException(404, "Workspace not found")
    policy = dict(workspace.runtime_policy or {})
    if policy.get("version", 1) != 1:
        raise HTTPException(409, "Runtime 策略版本不兼容")
    policy.update(version=1)
    updates = payload.model_dump(mode="json", exclude_unset=True)
    for namespace, value in updates.items():
        policy[namespace] = {**(policy.get(namespace) or {}), **value} if isinstance(value, dict) else value
    workspace.runtime_policy = policy
    await db.commit()
    effective = resolve_effective_policy(config, policy)
    return {
        "version": 1,
        "budget": policy.get("budget"),
        "collaboration": policy.get("collaboration"),
        "effective_budget": effective.effective_budget.model_dump(),
        "effective_collaboration_policy": effective.collaboration_mode,
        "source_trace": effective.trace,
    }
