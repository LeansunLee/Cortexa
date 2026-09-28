"""Agent 运维 API：集中管理 Agent 可用的知识、工具、数据能力和记忆。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db
from cortexa.db.models import (
    Agent,
    AgentDataBinding,
    DataCapability,
    DataSource,
    KnowledgeBase,
    Memory,
    Tool,
)
from cortexa.security.access import actor_required, require_agent_use, require

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


from cortexa.memory.schemas import Candidate, MemoryConfig
from cortexa.api.memories import MemoryUpdate, Resolution


class MemoryCreate(Candidate):
    pass


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


def _memory_item(memory):
    from cortexa.api.memories import memory_item
    return memory_item(memory)


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
            .where(Memory.workspace_id == workspace_id, Memory.agent_id == agent_id)
            .order_by(Memory.created_at.desc()).limit(30)
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
async def create_agent_memory(agent_id: uuid.UUID, payload: MemoryCreate, db: AsyncSession = Depends(get_db)):
    from cortexa.api.memories import MemoryCreate as Input, create_memory
    return await create_memory(Input(agent_id=agent_id, **payload.model_dump()), db)


async def _owned_memory(agent_id, memory_id, db):
    from cortexa.memory.access import memory_access
    await _agent(agent_id, db)
    mem=await memory_access(db,memory_id,manage=True)
    if mem.agent_id!=agent_id:
        raise HTTPException(404,'Agent 记忆不存在')
    return mem


@router.patch("/{agent_id}/memories/{memory_id}")
async def update_agent_memory(agent_id: uuid.UUID, memory_id: uuid.UUID, payload: MemoryUpdate, db: AsyncSession = Depends(get_db)):
    from cortexa.api.memories import update_memory
    await _owned_memory(agent_id,memory_id,db)
    return await update_memory(memory_id,payload,db)


@router.delete("/{agent_id}/memories/{memory_id}",status_code=204)
async def archive_agent_memory(agent_id: uuid.UUID,memory_id: uuid.UUID,db: AsyncSession = Depends(get_db)):
    from cortexa.memory.governance import change_state
    mem=await _owned_memory(agent_id,memory_id,db)
    await change_state(db,mem,'archived')


@router.get('/{agent_id}/memory-summary')
async def memory_summary(agent_id:uuid.UUID,db:AsyncSession=Depends(get_db)):
    from cortexa.api.memories import summary
    return await summary(db,agent_id)


@router.get('/{agent_id}/memory-issues')
async def memory_issues(agent_id:uuid.UUID,cursor:uuid.UUID|None=None,db:AsyncSession=Depends(get_db)):
    from cortexa.memory.models import MemoryIssue
    from cortexa.api.memories import memory_item
    await _agent(agent_id,db)
    stmt=select(MemoryIssue).where(MemoryIssue.agent_id==agent_id,MemoryIssue.status.in_(['open','deferred']))
    if cursor:stmt=stmt.where(MemoryIssue.id<cursor)
    rows=(await db.scalars(stmt.order_by(MemoryIssue.id.desc()).limit(31))).all()
    more=len(rows)>30;rows=rows[:30];items=[]
    for row in rows:
        ids=[uuid.UUID(x) for x in row.related_memory_ids]
        memories=(await db.scalars(select(Memory).where(Memory.agent_id==agent_id,Memory.id.in_(ids)).order_by(Memory.id))).all()
        items.append({'id':row.id,'issue_type':row.issue_type,'severity':row.severity,'status':row.status,
            'reason_code':row.reason_code,'created_at':row.created_at,'memories':[memory_item(m) for m in memories]})
    return {'items':items,'has_more':more,'next_cursor':str(rows[-1].id) if more else None}


@router.post('/{agent_id}/memory-issues/{issue_id}/resolve')
async def memory_issue_resolve(agent_id:uuid.UUID,issue_id:uuid.UUID,payload:Resolution,db:AsyncSession=Depends(get_db)):
    from cortexa.api.memories import resolve_issue
    return await resolve_issue(db,agent_id,issue_id,payload)


@router.post('/{agent_id}/memory-consolidation')
async def memory_consolidation(agent_id:uuid.UUID,cursor:str|None=None,db:AsyncSession=Depends(get_db)):
    from cortexa.memory.lifecycle import consolidate
    return await consolidate(db,agent_id,cursor)


@router.get('/{agent_id}/memory-config')
async def get_memory_config(agent_id:uuid.UUID,db:AsyncSession=Depends(get_db)):
    from cortexa.memory.policy import config
    return config(await _agent(agent_id,db)).model_dump()


@router.patch('/{agent_id}/memory-config')
async def set_memory_config(agent_id:uuid.UUID,payload:MemoryConfig,db:AsyncSession=Depends(get_db)):
    agent=await _agent(agent_id,db)
    agent.memory_config={**(agent.memory_config or {}),'memory2':payload.model_dump()}
    from cortexa.security.models import AuditLog
    db.add(AuditLog(actor_id=actor_required().user_id,action='memory.policy_changed',target=str(agent.id),detail={'config':payload.model_dump()}))
    return payload.model_dump()
