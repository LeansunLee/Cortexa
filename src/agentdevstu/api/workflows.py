"""Workflows API."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.api.schemas import WorkflowCreate, WorkflowOut
from agentdevstu.db.models import Workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[Workflow]:
    query = select(Workflow).order_by(Workflow.created_at.desc())
    if workspace_id:
        query = query.where(Workflow.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=WorkflowOut, status_code=201)
async def create_workflow(
    payload: WorkflowCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Workflow:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    wf = Workflow(
        workspace_id=uuid.UUID(workspace_id),
        name=payload.name,
        description=payload.description,
    )
    db.add(wf)
    await db.flush()
    await db.refresh(wf)
    return wf


@router.delete("/{wf_id}", status_code=204)
async def delete_workflow(
    wf_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    wf = await db.get(Workflow, wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(wf)
