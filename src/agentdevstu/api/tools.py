"""Tools API."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.api.deps import get_db, get_current_workspace
from agentdevstu.api.schemas import ToolCreate, ToolOut
from agentdevstu.db.models import Tool

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolOut])
async def list_tools(
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> list[Tool]:
    query = select(Tool).order_by(Tool.created_at.desc())
    if workspace_id:
        query = query.where(Tool.workspace_id == uuid.UUID(workspace_id))
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post("", response_model=ToolOut, status_code=201)
async def create_tool(
    payload: ToolCreate,
    db: AsyncSession = Depends(get_db),
    workspace_id: str | None = Depends(get_current_workspace),
) -> Tool:
    if not workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id is required")
    tool = Tool(
        workspace_id=uuid.UUID(workspace_id),
        name=payload.name,
        description=payload.description,
        type=payload.type,
        config=payload.config,
        input_schema=payload.input_schema,
        output_schema=payload.output_schema,
    )
    db.add(tool)
    await db.flush()
    await db.refresh(tool)
    return tool


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    await db.delete(tool)
