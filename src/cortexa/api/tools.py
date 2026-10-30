"""Tools registry API — manifest-driven external tool management.

路径保留 /tools；旧 CRUD 已按工具与技能体系提案重写为注册表接口。
写操作要求 tools.manage 权限；绑定接口要求 agent.update。
凭证只写不读：响应仅回 has_secret。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db, get_current_workspace
from cortexa.db.models import Agent, Tool
from cortexa.security.access import actor_required, require
from cortexa.tools.manifest import ProviderType, ToolManifest
from cortexa.tools.registry import (
    create_registry_tool,
    delete_registry_tool,
    get_registry_tool,
    list_registry_tools,
    record_health,
    set_tool_status,
    test_connection,
    update_registry_tool,
)

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolRegistryPayload(BaseModel):
    manifest: dict[str, Any]
    secret: str = Field(default="", max_length=4000)


class ToolStatusPayload(BaseModel):
    status: str


class ToolBindPayload(BaseModel):
    agent_ids: list[str] = Field(max_length=100)


class ToolOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    provider_type: str
    endpoint: dict[str, Any]
    manifest: dict[str, Any]
    input_schema: dict[str, Any]
    status: str
    version: int
    health_status: str
    health_checked_at: datetime | None
    has_secret: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def of(cls, record: Tool) -> "ToolOut":
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            name=record.name,
            description=record.description,
            provider_type=record.provider_type or "builtin",
            endpoint=record.endpoint or {},
            manifest=record.manifest or {},
            input_schema=record.input_schema or {},
            status=record.status,
            version=record.version or 1,
            health_status=record.health_status or "unknown",
            health_checked_at=record.health_checked_at,
            has_secret=bool(record.auth_secret_enc),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


def _parse_manifest(payload: dict[str, Any]) -> ToolManifest:
    try:
        return ToolManifest.model_validate(payload)
    except Exception as exc:  # pydantic ValidationError → 422 with readable detail
        raise HTTPException(status_code=422, detail=f"清单校验失败：{exc}") from exc


async def _workspace_or_400(workspace_id: str | None) -> uuid.UUID:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    return uuid.UUID(workspace_id)


async def _owned_tool(db: AsyncSession, workspace_id: uuid.UUID, tool_id: uuid.UUID) -> Tool:
    record = await get_registry_tool(db, workspace_id, tool_id)
    if record is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    return record


@router.get("")
async def list_tools(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[ToolOut]:
    require("tools.manage")
    ws = await _workspace_or_400(workspace_id)
    records = await list_registry_tools(db, ws)
    return [ToolOut.of(record) for record in records]


@router.post("", status_code=201)
async def create_tool(
    payload: ToolRegistryPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> ToolOut:
    require("tools.manage")
    ws = await _workspace_or_400(workspace_id)
    manifest = _parse_manifest(payload.manifest)
    try:
        record = await create_registry_tool(db, ws, manifest, secret=payload.secret, created_by=actor_required().user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ToolOut.of(record)


@router.post("/validate")
async def validate_manifest(payload: ToolRegistryPayload) -> dict:
    manifest = _parse_manifest(payload.manifest)
    return {"ok": True, "name": manifest.name, "input_schema": manifest.input_schema()}


@router.get("/agents-lookup")
async def agents_lookup(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[dict]:
    """绑定面板用：当前空间智能体清单（id/name/绑定状态）。"""
    require("agent.read")
    ws = await _workspace_or_400(workspace_id)
    result = await db.execute(
        select(Agent.id, Agent.name, Agent.tool_ids).where(Agent.workspace_id == ws, Agent.status == "active")
    )
    return [
        {"id": str(row.id), "name": row.name, "tool_ids": [str(v) for v in (row.tool_ids or [])]}
        for row in result.all()
    ]


@router.put("/{tool_id}")
async def update_tool(
    tool_id: uuid.UUID,
    payload: ToolRegistryPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> ToolOut:
    require("tools.manage")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_tool(db, ws, tool_id)
    manifest = _parse_manifest(payload.manifest)
    try:
        record = await update_registry_tool(db, record, manifest, secret=payload.secret or None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ToolOut.of(record)


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> None:
    require("tools.manage")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_tool(db, ws, tool_id)
    try:
        await delete_registry_tool(db, record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{tool_id}/test")
async def test_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> dict:
    require("tools.manage")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_tool(db, ws, tool_id)
    result = await test_connection(record)
    await record_health(db, record, result)
    return result


@router.post("/{tool_id}/status")
async def change_status(
    tool_id: uuid.UUID,
    payload: ToolStatusPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> ToolOut:
    require("tools.manage")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_tool(db, ws, tool_id)
    try:
        record = await set_tool_status(db, record, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ToolOut.of(record)


@router.post("/{tool_id}/bind")
async def bind_tool(
    tool_id: uuid.UUID,
    payload: ToolBindPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> dict:
    """把工具绑定到一组智能体（增量编辑各自 tool_ids，不触碰其他绑定）。"""
    require("agent.update")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_tool(db, ws, tool_id)
    if record.provider_type == ProviderType.BUILTIN:
        raise HTTPException(status_code=409, detail="内置工具请通过智能体的联网搜索开关管理")
    tool_key = str(record.id)
    bound, unbound = [], []
    for raw in payload.agent_ids:
        try:
            agent_id = uuid.UUID(raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"非法智能体 ID：{raw}") from exc
        agent = await db.get(Agent, agent_id)
        if agent is None or agent.workspace_id != ws:
            raise HTTPException(status_code=404, detail=f"智能体不存在：{raw}")
        ids = [str(value) for value in (agent.tool_ids or [])]
        if tool_key in ids:
            ids = [value for value in ids if value != tool_key]
            unbound.append(str(agent.id))
        else:
            ids.append(tool_key)
            bound.append(str(agent.id))
        agent.tool_ids = ids
    await db.flush()
    return {"bound": bound, "unbound": unbound}

