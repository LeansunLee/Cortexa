"""Personal task editing and execution API."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db, get_current_workspace
from cortexa.api.schemas import TaskCreate, TaskOut, TaskRunOut, TaskUpdate
from cortexa.db.models import Task, TaskRun
from cortexa.security.access import actor_required, require, require_agent_use
from cortexa.workflow.engine import run_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _task(db: AsyncSession, task_id: uuid.UUID) -> Task:
    require("tasks.manage")
    task = await db.get(Task, task_id)
    actor = actor_required()
    if not task or task.workspace_id != actor.workspace_id or task.owner_user_id != actor.user_id:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("", response_model=list[TaskOut])
async def list_tasks(db: AsyncSession = Depends(get_db), workspace_id: str | None = Depends(get_current_workspace)):
    require("tasks.manage")
    if not workspace_id:
        raise HTTPException(400, "请先选择工作空间")
    rows = await db.scalars(
        select(Task).where(Task.workspace_id == uuid.UUID(workspace_id), Task.owner_user_id == actor_required().user_id)
        .order_by(Task.created_at.desc())
    )
    return list(rows.all())


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(payload: TaskCreate, db: AsyncSession = Depends(get_db), workspace_id: str | None = Depends(get_current_workspace)):
    require("tasks.manage")
    if not workspace_id:
        raise HTTPException(400, "请先选择工作空间")
    await require_agent_use(db, payload.agent_id)
    task = Task(
        workspace_id=uuid.UUID(workspace_id), owner_user_id=actor_required().user_id,
        name=payload.name.strip(), description=payload.description,
        agent_id=payload.agent_id, input_data=payload.input_data,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await _task(db, task_id)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(task_id: uuid.UUID, payload: TaskUpdate, db: AsyncSession = Depends(get_db)):
    task = await _task(db, task_id)
    if task.status == "running":
        raise HTTPException(409, "运行中的任务不能编辑")
    if payload.name is not None:
        task.name = payload.name.strip()
    if "description" in payload.model_fields_set:
        task.description = payload.description
    if payload.input_data is not None:
        task.input_data = payload.input_data
    task.status = "pending"
    task.output_data = {}
    await db.flush()
    return task


@router.post("/{task_id}/run", response_model=TaskRunOut, status_code=201)
async def run_single_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await _task(db, task_id)
    if task.status == "running":
        raise HTTPException(409, "任务正在运行")
    if not task.agent_id:
        raise HTTPException(422, "任务没有绑定 Agent")
    await require_agent_use(db, task.agent_id)
    return await run_task(db, task, [(task.name, task.agent_id)])


@router.get("/{task_id}/runs", response_model=list[TaskRunOut])
async def list_task_runs(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await _task(db, task_id)
    rows = await db.scalars(select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.started_at.desc()).limit(50))
    return list(rows.all())


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    task = await _task(db, task_id)
    if task.status == "running":
        raise HTTPException(409, "运行中的任务不能删除")
    await db.delete(task)
