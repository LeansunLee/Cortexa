"""Skills API — procedural knowledge package management.

写操作要求 agent.operate 权限；绑定接口要求 agent.update；
列表要求 agent.read。正文存文件系统，API 接收/返回全文。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db, get_current_workspace
from cortexa.db.models import Agent, Skill
from cortexa.security.access import actor_required, require
from cortexa.tools.skills import (
    create_skill,
    delete_skill,
    get_skill,
    list_skills,
    read_instructions,
    set_skill_status,
    update_skill,
)

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillPayload(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(min_length=1, max_length=2000)
    instructions: str = Field(min_length=1, max_length=20000)
    tool_ids: list[str] = Field(default_factory=list, max_length=50)


class SkillStatusPayload(BaseModel):
    status: str


class SkillBindPayload(BaseModel):
    agent_ids: list[str] = Field(max_length=100)


class SkillOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str
    summary: str
    instructions: str
    tool_ids: list[str]
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def of(cls, record: Skill) -> "SkillOut":
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            name=record.name,
            description=record.description or "",
            summary=record.summary or "",
            instructions=read_instructions(record.instructions_path) or "",
            tool_ids=[str(value) for value in (record.tool_ids or [])],
            status=record.status,
            version=record.version or 1,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


async def _workspace_or_400(workspace_id: str | None) -> uuid.UUID:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    return uuid.UUID(workspace_id)


async def _owned_skill(db: AsyncSession, workspace_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
    record = await get_skill(db, workspace_id, skill_id)
    if record is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return record


@router.get("")
async def list_all(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[SkillOut]:
    require("agent.read")
    ws = await _workspace_or_400(workspace_id)
    return [SkillOut.of(record) for record in await list_skills(db, ws)]


@router.post("", status_code=201)
async def create(
    payload: SkillPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> SkillOut:
    require("agent.operate")
    ws = await _workspace_or_400(workspace_id)
    try:
        record = await create_skill(db, ws, name=payload.name.strip(), description=payload.description,
                                    instructions=payload.instructions, tool_ids=payload.tool_ids,
                                    created_by=actor_required().user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SkillOut.of(record)


@router.post("/agents-lookup")
async def agents_lookup(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[dict]:
    require("agent.read")
    ws = await _workspace_or_400(workspace_id)
    result = await db.execute(
        select(Agent.id, Agent.name, Agent.skill_ids).where(Agent.workspace_id == ws, Agent.status == "active")
    )
    return [
        {"id": str(row.id), "name": row.name, "skill_ids": [str(v) for v in (row.skill_ids or [])]}
        for row in result.all()
    ]


@router.put("/{skill_id}")
async def update(
    skill_id: uuid.UUID,
    payload: SkillPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> SkillOut:
    require("agent.operate")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_skill(db, ws, skill_id)
    try:
        record = await update_skill(db, record, name=payload.name.strip(), description=payload.description,
                                    instructions=payload.instructions, tool_ids=payload.tool_ids)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SkillOut.of(record)


@router.delete("/{skill_id}", status_code=204)
async def remove(
    skill_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> None:
    require("agent.operate")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_skill(db, ws, skill_id)
    await delete_skill(db, record)


@router.post("/{skill_id}/status")
async def change_status(
    skill_id: uuid.UUID,
    payload: SkillStatusPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> SkillOut:
    require("agent.operate")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_skill(db, ws, skill_id)
    try:
        record = await set_skill_status(db, record, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SkillOut.of(record)


@router.post("/{skill_id}/bind")
async def bind(
    skill_id: uuid.UUID,
    payload: SkillBindPayload,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> dict:
    """把技能绑定到一组智能体（增量编辑各自 skill_ids）。"""
    require("agent.update")
    ws = await _workspace_or_400(workspace_id)
    record = await _owned_skill(db, ws, skill_id)
    skill_key = str(record.id)
    bound, unbound = [], []
    for raw in payload.agent_ids:
        try:
            agent_id = uuid.UUID(raw)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"非法智能体 ID：{raw}") from exc
        agent = await db.get(Agent, agent_id)
        if agent is None or agent.workspace_id != ws:
            raise HTTPException(status_code=404, detail=f"智能体不存在：{raw}")
        ids = [str(value) for value in (agent.skill_ids or [])]
        if skill_key in ids:
            ids = [value for value in ids if value != skill_key]
            unbound.append(str(agent.id))
        else:
            ids.append(skill_key)
            bound.append(str(agent.id))
        agent.skill_ids = ids
    await db.flush()
    return {"bound": bound, "unbound": unbound}
