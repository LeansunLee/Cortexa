"""Workspace CRUD API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db
from cortexa.api.schemas import WorkspaceCreate, WorkspaceOut, WorkspaceUpdate
from cortexa.db.models import Workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(db: AsyncSession = Depends(get_db)) -> list[Workspace]:
    result = await db.execute(select(Workspace).order_by(Workspace.created_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(payload: WorkspaceCreate, db: AsyncSession = Depends(get_db)) -> Workspace:
    ws = Workspace(name=payload.name, description=payload.description, default_model_provider=payload.default_model_provider)
    db.add(ws)
    await db.flush()
    from cortexa.security.access import current_actor
    from cortexa.security.models import User, Membership, MemberRole, Role
    actor = current_actor.get()
    if actor:
        role = await db.scalar(select(Role).where(Role.code == 'space_admin'))
        users = set((await db.execute(select(User.id).where(User.is_superadmin == True))).scalars())
        users.add(actor.user_id)
        for user_id in users:
            member = Membership(user_id=user_id, workspace_id=ws.id, all_agents=True)
            db.add(member)
            await db.flush()
            db.add(MemberRole(member_id=member.id, role_id=role.id))
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Workspace:
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.put("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: uuid.UUID, payload: WorkspaceUpdate, db: AsyncSession = Depends(get_db)
) -> Workspace:
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ws, field, value)
    await db.flush()
    await db.refresh(ws)
    return ws


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    from sqlalchemy import delete
    from cortexa.db.models import Memory
    await db.execute(delete(Memory.__table__).where(Memory.__table__.c.workspace_id==ws.id))
    await db.delete(ws)
