"""Tasks API."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.api.schemas import TaskCreate, TaskOut
from agentdevstu.db.models import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[Task]:
    query = select(Task).order_by(Task.created_at.desc())
    if workspace_id:
        query = query.where(Task.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Task:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    task = Task(
        workspace_id=uuid.UUID(workspace_id),
        name=payload.name,
        description=payload.description,
        agent_id=payload.agent_id,
        input_data=payload.input_data,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await db.delete(task)
