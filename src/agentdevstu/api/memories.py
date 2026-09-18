"""Memory API — 记忆管理接口"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.db.models import Memory

router = APIRouter(prefix="/memories", tags=["memories"])


# ── Schemas ──

MemoryType = Literal["semantic", "episodic", "focus"]

class MemoryOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    type: str
    content: str
    importance: float
    confidence: float
    status: str
    source_type: str
    source_id: uuid.UUID | None
    access_count: int
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class MemoryUpdate(BaseModel):
    type: MemoryType | None = None
    content: str | None = None
    importance: float | None = Field(default=None, ge=0, le=1)
    status: str | None = None


class MemoryCreate(BaseModel):
    agent_id: uuid.UUID | None = None
    type: MemoryType = "semantic"
    content: str
    importance: float = Field(default=0.7, ge=0, le=1)
    confidence: float = 0.8


# ── Create ──

@router.post("", response_model=MemoryOut, status_code=201)
async def create_memory(
    payload: MemoryCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> MemoryOut:
    memory = Memory(
        workspace_id=uuid.UUID(workspace_id) if workspace_id else None,
        agent_id=payload.agent_id,
        type=payload.type,
        content=payload.content,
        importance=payload.importance,
        confidence=payload.confidence,
        status="active",
        source_type="manual",
    )
    db.add(memory)
    await db.flush()
    await db.refresh(memory)
    return memory


# ── List ──

@router.get("", response_model=list[MemoryOut])
async def list_memories(
    agent_id: uuid.UUID | None = None,
    type: MemoryType | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[MemoryOut]:
    q = select(Memory).order_by(Memory.created_at.desc())
    if workspace_id:
        q = q.where(Memory.workspace_id == uuid.UUID(workspace_id))
    if agent_id:
        q = q.where(Memory.agent_id == agent_id)
    if type:
        q = q.where(Memory.type == type)
    if status:
        q = q.where(Memory.status == status)
    else:
        q = q.where(Memory.status != "archived")
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Get ──

@router.get("/{memory_id}", response_model=MemoryOut)
async def get_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    mem = await db.get(Memory, memory_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    return mem


# ── Update ──

@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_memory(
    memory_id: uuid.UUID,
    payload: MemoryUpdate,
    db: AsyncSession = Depends(get_db),
) -> MemoryOut:
    mem = await db.get(Memory, memory_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    if payload.type is not None:
        mem.type = payload.type
    if payload.content is not None:
        mem.content = payload.content
    if payload.importance is not None:
        mem.importance = payload.importance
    if payload.status is not None:
        mem.status = payload.status
    mem.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(mem)
    return mem


# ── Delete (archive) ──

@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    mem = await db.get(Memory, memory_id)
    if not mem:
        raise HTTPException(status_code=404, detail="Memory not found")
    mem.status = "archived"
    mem.updated_at = datetime.now(timezone.utc)
    await db.flush()
