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
    # Most child tables are covered by ORM relationships or DB-level ON DELETE
    # CASCADE, but the project/work/candidate/audit families have neither, and a
    # plain db.delete(ws) used to violate their FKs at commit time — after the
    # 204 was already returned, silently rolling the whole delete back.
    # Pre-clean those rows here; anything unforeseen still surfaces as a 409.
    from pathlib import Path

    from sqlalchemy import delete
    from sqlalchemy.exc import IntegrityError
    from starlette.concurrency import run_in_threadpool

    from cortexa.db.meetings import TodoItem
    from cortexa.db.models import DataQuery, Memory, Skill
    from cortexa.projects.models import Project, ProjectActivity, ProjectMember
    from cortexa.tools.skills import delete_instructions
    from cortexa.work.models import Work, WorkActivity, WorkCandidate, WorkDeliverable
    from cortexa.work.service import blob_path as work_blob_path

    deliverable_ids = (
        await db.scalars(select(WorkDeliverable.id).where(WorkDeliverable.workspace_id == ws.id))
    ).all()
    skill_paths = (
        await db.scalars(select(Skill.instructions_path).where(Skill.workspace_id == ws.id))
    ).all()
    await db.execute(delete(WorkCandidate.__table__).where(WorkCandidate.__table__.c.workspace_id == ws.id))
    await db.execute(delete(WorkDeliverable.__table__).where(WorkDeliverable.__table__.c.workspace_id == ws.id))
    await db.execute(delete(WorkActivity.__table__).where(WorkActivity.__table__.c.workspace_id == ws.id))
    await db.execute(delete(Work.__table__).where(Work.__table__.c.workspace_id == ws.id))
    await db.execute(delete(ProjectActivity.__table__).where(ProjectActivity.__table__.c.workspace_id == ws.id))
    await db.execute(delete(ProjectMember.__table__).where(ProjectMember.__table__.c.workspace_id == ws.id))
    await db.execute(delete(Project.__table__).where(Project.__table__.c.workspace_id == ws.id))
    await db.execute(delete(DataQuery.__table__).where(DataQuery.__table__.c.workspace_id == ws.id))
    await db.execute(delete(Skill.__table__).where(Skill.__table__.c.workspace_id == ws.id))
    await db.execute(delete(TodoItem.__table__).where(TodoItem.__table__.c.workspace_id == ws.id))
    await db.execute(delete(Memory.__table__).where(Memory.__table__.c.workspace_id == ws.id))
    await db.delete(ws)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            409, "工作空间下仍有受关联约束的数据，删除未完成；请核查该空间的项目、工作或会议后重试"
        ) from error
    stale_files: list[Path] = [work_blob_path(ident) for ident in deliverable_ids]
    for path in stale_files:
        await run_in_threadpool(path.unlink, missing_ok=True)
    for relative in skill_paths:
        await run_in_threadpool(delete_instructions, relative)
