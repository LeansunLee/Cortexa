"""Agent 运维 API：集中管理 Agent 可用的知识、工具、数据能力和记忆。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db
from agentdevstu.db.models import (
    Agent,
    AgentDataBinding,
    DataCapability,
    DataSource,
    KnowledgeBase,
    Memory,
    Tool,
)
from agentdevstu.security.access import actor_required, require_agent_use, require

router = APIRouter(prefix="/agent-operations", tags=["agent-operations"])


class KnowledgeBindingsUpdate(BaseModel):
    knowledge_base_ids: list[uuid.UUID] = Field(default_factory=list)


class ToolBindingsUpdate(BaseModel):
    tool_ids: list[uuid.UUID] = Field(default_factory=list)


class DataBindingCreate(BaseModel):
    data_capability_id: uuid.UUID


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    type: str = "documents"


class MemoryCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    type: Literal["semantic", "episodic", "focus"] = "semantic"
    content: str = Field(min_length=1)
    importance: float = Field(default=0.7, ge=0, le=1)
    confidence: float = Field(default=0.8, ge=0, le=1)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    type: Literal["semantic", "episodic", "focus"] | None = None
    content: str | None = Field(default=None, min_length=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    status: Literal["active", "archived", "rejected"] | None = None

    @field_validator("type", "content", "importance", "status")
    @classmethod
    def disallow_null(cls, value):
        if value is None:
            raise ValueError("不能保存空值")
        return value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _knowledge_item(kb: KnowledgeBase) -> dict:
    return {
        "id": str(kb.id),
        "name": kb.name,
        "description": kb.description,
        "type": kb.type,
        "status": kb.status,
        "agent_id": str(kb.agent_id) if kb.agent_id else None,
        "created_at": _iso(kb.created_at),
    }


def _tool_item(tool: Tool) -> dict:
    return {
        "id": str(tool.id),
        "name": tool.name,
        "description": tool.description,
        "type": tool.type,
        "status": tool.status,
    }


def _memory_item(memory: Memory) -> dict:
    return {
        "id": str(memory.id),
        "agent_id": str(memory.agent_id) if memory.agent_id else None,
        "type": memory.type,
        "content": memory.content,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "status": memory.status,
        "source_type": memory.source_type,
        "created_at": _iso(memory.created_at),
        "updated_at": _iso(memory.updated_at),
    }


async def _agent(agent_id: uuid.UUID, db: AsyncSession) -> Agent:
    require("agent.operate")
    return await require_agent_use(db, agent_id)


@router.get("/{agent_id}/summary")
async def get_summary(agent_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict:
    agent = await _agent(agent_id, db)
    return await resource_summary(agent, db)


async def resource_summary(agent: Agent, db: AsyncSession) -> dict:
    agent_id = agent.id
    workspace_id = agent.workspace_id

    kb_rows = (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.workspace_id == workspace_id)
            .where((KnowledgeBase.agent_id.is_(None)) | (KnowledgeBase.agent_id == agent_id))
            .order_by(KnowledgeBase.created_at.desc())
        )
    ).scalars().all()
    tools = (
        await db.execute(
            select(Tool).where(Tool.workspace_id == workspace_id).order_by(Tool.created_at.desc())
        )
    ).scalars().all()
    capabilities = (
        await db.execute(
            select(DataCapability, DataSource)
            .join(DataSource, DataSource.id == DataCapability.data_source_id)
            .where(DataCapability.workspace_id == workspace_id)
            .where(DataSource.workspace_id == workspace_id)
            .order_by(DataCapability.created_at.desc())
        )
    ).all()
    bindings = (
        await db.execute(
            select(AgentDataBinding).where(AgentDataBinding.agent_id == agent_id)
        )
    ).scalars().all()
    memories = (
        await db.execute(
            select(Memory)
            .where(Memory.workspace_id == workspace_id, Memory.agent_id == agent_id,
                   Memory.owner_user_id == actor_required().user_id)
            .order_by(Memory.created_at.desc())
        )
    ).scalars().all()

    return {
        "agent": {
            "id": str(agent.id),
            "name": agent.name,
            "description": agent.description,
            "avatar": agent.avatar,
            "status": agent.status,
            "agent_type": agent.agent_type,
        },
        "knowledge_bases": [_knowledge_item(kb) for kb in kb_rows],
        "knowledge_base_ids": [str(value) for value in (agent.knowledge_base_ids or [])],
        "tools": [_tool_item(tool) for tool in tools],
        "tool_ids": [str(value) for value in (agent.tool_ids or [])],
        "capabilities": [
            {
                "id": str(cap.id),
                "name": cap.name,
                "description": cap.description,
                "type": cap.type,
                "status": cap.status,
                "data_source_id": str(source.id),
                "data_source_name": source.name,
            }
            for cap, source in capabilities
        ],
        "bindings": [
            {"id": str(binding.id), "data_capability_id": str(binding.data_capability_id), "created_at": _iso(binding.created_at)}
            for binding in bindings
        ],
        "memories": [_memory_item(memory) for memory in memories],
    }


@router.patch("/{agent_id}/knowledge-bindings")
async def update_knowledge_bindings(
    agent_id: uuid.UUID,
    payload: KnowledgeBindingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _agent(agent_id, db)
    requested = list(dict.fromkeys(payload.knowledge_base_ids))
    rows = (
        await db.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.id.in_(requested),
                KnowledgeBase.workspace_id == agent.workspace_id,
                KnowledgeBase.agent_id.is_(None),
            )
        )
    ).scalars().all() if requested else []
    if len(rows) != len(requested):
        raise HTTPException(422, "只能绑定当前工作空间的共享知识库")
    private_ids = (
        await db.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.agent_id == agent_id,
                KnowledgeBase.workspace_id == agent.workspace_id,
            )
        )
    ).scalars().all()
    agent.knowledge_base_ids = [str(value) for value in private_ids] + [str(value) for value in requested]
    await db.flush()
    return {"knowledge_base_ids": agent.knowledge_base_ids}


@router.post("/{agent_id}/knowledge-bases", status_code=201)
async def create_agent_knowledge_base(
    agent_id: uuid.UUID,
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _agent(agent_id, db)
    knowledge_base = KnowledgeBase(
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        name=payload.name.strip(),
        description=payload.description,
        type=payload.type,
        status="active",
    )
    db.add(knowledge_base)
    await db.flush()
    agent.knowledge_base_ids = list(agent.knowledge_base_ids or []) + [str(knowledge_base.id)]
    await db.flush()
    await db.refresh(knowledge_base)
    return _knowledge_item(knowledge_base)


@router.patch("/{agent_id}/tool-bindings")
async def update_tool_bindings(
    agent_id: uuid.UUID,
    payload: ToolBindingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _agent(agent_id, db)
    requested = list(dict.fromkeys(payload.tool_ids))
    rows = (
        await db.execute(
            select(Tool).where(Tool.id.in_(requested), Tool.workspace_id == agent.workspace_id)
        )
    ).scalars().all() if requested else []
    if len(rows) != len(requested):
        raise HTTPException(422, "只能绑定当前工作空间的工具")
    agent.tool_ids = [str(value) for value in requested]
    await db.flush()
    return {"tool_ids": agent.tool_ids}


@router.post("/{agent_id}/data-bindings", status_code=201)
async def create_data_binding(
    agent_id: uuid.UUID,
    payload: DataBindingCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _agent(agent_id, db)
    capability = await db.get(DataCapability, payload.data_capability_id)
    if not capability or capability.workspace_id != agent.workspace_id:
        raise HTTPException(422, "只能绑定当前工作空间的数据能力")
    existing = (
        await db.execute(
            select(AgentDataBinding).where(
                AgentDataBinding.agent_id == agent_id,
                AgentDataBinding.data_capability_id == capability.id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"id": str(existing.id), "data_capability_id": str(existing.data_capability_id), "created_at": _iso(existing.created_at)}
    binding = AgentDataBinding(agent_id=agent_id, data_capability_id=capability.id)
    db.add(binding)
    await db.flush()
    await db.refresh(binding)
    return {"id": str(binding.id), "data_capability_id": str(binding.data_capability_id), "created_at": _iso(binding.created_at)}


@router.delete("/{agent_id}/data-bindings/{binding_id}", status_code=204)
async def delete_data_binding(
    agent_id: uuid.UUID,
    binding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    await _agent(agent_id, db)
    binding = await db.get(AgentDataBinding, binding_id)
    if not binding or binding.agent_id != agent_id:
        raise HTTPException(404, "数据能力绑定不存在")
    await db.delete(binding)


@router.post("/{agent_id}/memories", status_code=201)
async def create_agent_memory(
    agent_id: uuid.UUID,
    payload: MemoryCreate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    agent = await _agent(agent_id, db)
    memory = Memory(
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        owner_user_id=actor_required().user_id,
        type=payload.type,
        content=payload.content.strip(),
        importance=payload.importance,
        confidence=payload.confidence,
        status="active",
        source_type="manual",
    )
    db.add(memory)
    await db.flush()
    await db.refresh(memory)
    return _memory_item(memory)


async def _owned_memory(agent_id: uuid.UUID, memory_id: uuid.UUID, db: AsyncSession) -> Memory:
    agent = await _agent(agent_id, db)
    memory = await db.get(Memory, memory_id)
    if (not memory or memory.agent_id != agent.id or memory.workspace_id != agent.workspace_id
            or memory.owner_user_id != actor_required().user_id):
        raise HTTPException(404, "Agent 记忆不存在")
    return memory


@router.patch("/{agent_id}/memories/{memory_id}")
async def update_agent_memory(
    agent_id: uuid.UUID,
    memory_id: uuid.UUID,
    payload: MemoryUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    memory = await _owned_memory(agent_id, memory_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(memory, field, value.strip() if field == "content" and isinstance(value, str) else value)
    await db.flush()
    await db.refresh(memory)
    return _memory_item(memory)


@router.delete("/{agent_id}/memories/{memory_id}", status_code=204)
async def archive_agent_memory(
    agent_id: uuid.UUID,
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    memory = await _owned_memory(agent_id, memory_id, db)
    memory.status = "archived"
    await db.flush()
