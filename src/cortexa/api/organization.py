import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.api.deps import get_db
from cortexa.db.models import Workspace
from cortexa.organization.models import MemberProfile, OrgUnit
from cortexa.organization.schemas import ProfileInput, UnitInput
from cortexa.organization.service import directory
from cortexa.security.access import require
from cortexa.security.api import audit
from cortexa.security.models import Membership, User
from cortexa.work.service import actor, serialize

router = APIRouter(prefix="/organization", tags=["organization"])
Db = Annotated[AsyncSession, Depends(get_db)]


async def lock_space(db):
    require("members.manage")
    await db.execute(select(Workspace).where(Workspace.id == actor().workspace_id).with_for_update())


async def member(db, user_id):
    value = await db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == actor().workspace_id, Membership.user_id == user_id, User.status == "active")
        .with_for_update(of=Membership)
    )
    if value is None:
        raise HTTPException(422, "请选择当前空间的有效成员")
    return value


async def unit(db, ident):
    value = await db.scalar(select(OrgUnit).where(OrgUnit.workspace_id == actor().workspace_id, OrgUnit.id == ident))
    if value is None:
        raise HTTPException(404, "组织节点不存在或不属于当前空间")
    return value


async def validate_unit(db, payload, ident):
    seen = {ident}
    parent_id = payload.parent_id
    while parent_id:
        if parent_id in seen:
            raise HTTPException(422, "上级部门不能形成循环")
        seen.add(parent_id)
        parent = await unit(db, parent_id)
        if payload.status == "active" and parent.status != "active":
            raise HTTPException(422, "有效部门不能放在停用部门下")
        parent_id = parent.parent_id
    if payload.manager_user_id:
        await member(db, payload.manager_user_id)
    if payload.code and await db.scalar(
        select(OrgUnit.id).where(
            OrgUnit.workspace_id == actor().workspace_id, OrgUnit.code == payload.code, OrgUnit.id != ident
        )
    ):
        raise HTTPException(409, "当前空间已存在此组织编码")
    if payload.status == "disabled" and await db.scalar(
        select(OrgUnit.id).where(
            OrgUnit.workspace_id == actor().workspace_id, OrgUnit.parent_id == ident, OrgUnit.status == "active"
        )
    ):
        raise HTTPException(409, "请先调整或停用下级部门")


@router.get("/units")
async def list_units(db: Db):
    actor()
    values = (
        await db.execute(
            select(OrgUnit)
            .where(OrgUnit.workspace_id == actor().workspace_id)
            .order_by(OrgUnit.sort_order, OrgUnit.name, OrgUnit.id)
        )
    ).scalars()
    return [serialize(o) for o in values]


@router.get("/members")
async def list_members(db: Db):
    return await directory(db)


@router.post("/units", status_code=201)
async def create_unit(payload: UnitInput, db: Db):
    await lock_space(db)
    ident = uuid.uuid4()
    await validate_unit(db, payload, ident)
    row = OrgUnit(id=ident, workspace_id=actor().workspace_id, **payload.model_dump())
    db.add(row)
    audit(db, "organization.created", str(ident))
    await db.flush()
    return serialize(row)


@router.put("/units/{ident}")
async def update_unit(ident: uuid.UUID, payload: UnitInput, db: Db):
    await lock_space(db)
    row = await unit(db, ident)
    await validate_unit(db, payload, ident)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, "organization.updated", str(ident))
    await db.flush()
    return serialize(row)


@router.delete("/units/{ident}", status_code=204)
async def delete_unit(ident: uuid.UUID, db: Db):
    await lock_space(db)
    row = await unit(db, ident)
    children = await db.scalar(
        select(OrgUnit.id).where(OrgUnit.workspace_id == actor().workspace_id, OrgUnit.parent_id == ident).limit(1)
    )
    profiles = await db.scalar(
        select(MemberProfile.user_id)
        .where(MemberProfile.workspace_id == actor().workspace_id, MemberProfile.org_unit_id == ident)
        .limit(1)
    )
    if children or profiles:
        raise HTTPException(409, "请先转移下级部门和成员，再删除部门")
    await db.delete(row)
    audit(db, "organization.deleted", str(ident))
    await db.flush()


@router.put("/members/{user_id}")
async def save_profile(user_id: uuid.UUID, payload: ProfileInput, db: Db):
    await lock_space(db)
    await member(db, user_id)
    if payload.org_unit_id and (await unit(db, payload.org_unit_id)).status != "active":
        raise HTTPException(422, "请选择有效部门")
    row = await db.get(MemberProfile, (actor().workspace_id, user_id))
    if row is None:
        row = MemberProfile(workspace_id=actor().workspace_id, user_id=user_id)
        db.add(row)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    audit(db, "organization.profile_updated", str(user_id), workspace_id=str(actor().workspace_id))
    await db.flush()
    return serialize(row)


@router.delete("/members/{user_id}", status_code=204)
async def delete_profile(user_id: uuid.UUID, db: Db):
    await lock_space(db)
    row = await db.get(MemberProfile, (actor().workspace_id, user_id))
    if row:
        await db.delete(row)
        audit(db, "organization.profile_deleted", str(user_id))
        await db.flush()
