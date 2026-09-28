"""Memory operations always require a live Actor and an authorized Agent."""

from fastapi import HTTPException
from sqlalchemy import select
from cortexa.db.models import Memory
from cortexa.security.access import actor_required, require, require_agent_use


async def agent_access(db, agent_id, *, manage=False):
    actor_required()
    if manage:
        require("agent.operate")
    return await require_agent_use(db, agent_id)


async def memory_access(db, memory_id, *, manage=False, lock=False):
    actor_required()
    q = select(Memory).where(Memory.id == memory_id)
    mem = await db.scalar(q)
    if mem is None:
        raise HTTPException(404, "记忆不存在或无权访问")
    await agent_access(db, mem.agent_id, manage=manage)
    if lock:
        from .governance import lock_agent

        await lock_agent(db, mem.agent_id)
        await db.refresh(mem)
    return mem
