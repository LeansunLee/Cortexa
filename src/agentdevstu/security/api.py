"""User/role/member administration. All grants are bounded by the administrator's scope."""

import asyncio
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from agentdevstu.api.deps import get_db
from agentdevstu.db.models import Workspace, Agent
from .models import (
    User,
    Role,
    Membership,
    MemberRole,
    AgentGrant,
    SystemRoleBinding,
    LoginSession,
    AuditLog,
    IdentityProvider,
    ExternalIdentity,
)
from .access import actor_required, current_actor, require, raw
from .catalog import PERMISSIONS, SPACE, SYSTEM
from .passwords import hash_password, verify_password, token_digest
from .http import COOKIE
from .debug_preferences import debug_enabled, set_debug_enabled

router = APIRouter(tags=["identity"])
_failures = defaultdict(deque)


class DebugPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.get("/me/conversation-debug")
async def get_my_debug_preference():
    actor = actor_required()
    allowed = actor.has("conversation.debug")
    return {"allowed": allowed, "enabled": allowed and debug_enabled(actor.user_id)}


@router.put("/me/conversation-debug")
async def save_my_debug_preference(payload: DebugPreference):
    actor = actor_required()
    require("conversation.debug")
    set_debug_enabled(actor.user_id, payload.enabled)
    return {"allowed": True, "enabled": payload.enabled}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(StrictModel):
    old_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class UserCreate(StrictModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,80}$")
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(max_length=128)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)


class UserUpdate(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    status: Literal["active", "disabled"] | None = None


class PasswordReset(StrictModel):
    password: str = Field(max_length=128)


class RoleInput(StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    name: str = Field(min_length=1, max_length=120)
    scope: Literal["system", "workspace"]
    permissions: list[str]


class RolesInput(StrictModel):
    role_ids: list[uuid.UUID] = Field(default_factory=list)


class MemberInput(RolesInput):
    user_id: uuid.UUID
    all_agents: bool = False
    agent_ids: list[uuid.UUID] = Field(default_factory=list)


class ProviderInput(StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,79}$")
    name: str = Field(min_length=1, max_length=160)
    protocol: Literal["oidc", "dingtalk", "custom"] = "oidc"
    issuer: str | None = Field(default=None, max_length=500)
    field_mapping: dict[str, str] = Field(default_factory=dict)


def user_out(user):
    return {
        key: getattr(user, key)
        for key in [
            "id",
            "username",
            "display_name",
            "email",
            "phone",
            "status",
            "is_superadmin",
            "must_change_password",
            "source",
            "last_login_at",
            "created_at",
        ]
    }


def role_out(role):
    return {k: getattr(role, k) for k in ["id", "code", "name", "scope", "permissions", "builtin"]}


def audit(db, action, target=None, **detail):
    actor = current_actor.get()
    db.add(
        AuditLog(
            actor_id=actor.user_id if actor else None,
            action=action,
            target=str(target) if target else None,
            detail=detail,
        )
    )


@router.post("/auth/login")
async def login(payload: Login, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    now = time.monotonic()
    username = payload.username.strip().lower()
    # Bound memory and throttle by both account and peer, without trusting forwarded headers.
    for key in list(_failures):
        while _failures[key] and now - _failures[key][0] > 900:
            _failures[key].popleft()
        if not _failures[key]:
            del _failures[key]
    peer = request.client.host if request.client else "unknown"
    keys = ["user:" + username, "ip:" + peer]
    if any(len(_failures[k]) >= (10 if k.startswith("user:") else 60) for k in keys):
        raise HTTPException(429, "登录尝试过多，请 15 分钟后重试")
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    valid = await asyncio.to_thread(verify_password, payload.password, user.password_hash if user else None)
    if not valid or user.status != "active":
        for k in keys:
            _failures[k].append(now)
        audit(db, "login.failed", username)
        await db.commit()
        raise HTTPException(401, "账号或密码错误，或账号已停用")
    for k in keys:
        _failures.pop(k, None)
    token = secrets.token_urlsafe(48)
    expires = datetime.now(timezone.utc) + timedelta(hours=12)
    db.add(
        LoginSession(
            token_hash=token_digest(token), user_id=user.id, auth_version=user.auth_version, expires_at=expires
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    db.add(AuditLog(actor_id=user.id, action="login.success", target=str(user.id), detail={"source": "local"}))
    await db.execute(delete(LoginSession).where(LoginSession.expires_at < datetime.now(timezone.utc)))
    await db.commit()
    response.set_cookie(
        COOKIE, token, max_age=43200, httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/"
    )
    return user_out(user)


@router.get("/auth/me")
async def me(db: AsyncSession = Depends(get_db)):
    actor = actor_required()
    user = await db.get(User, actor.user_id)
    return {
        **user_out(user),
        "system_permissions": list(SYSTEM) if actor.superadmin else sorted(actor.system_permissions),
        "memberships": [
            {
                "workspace_id": str(ws),
                "permissions": sorted(v["permissions"]),
                "all_agents": v["all_agents"],
                "agent_ids": [str(i) for i in v["agent_ids"]],
            }
            for ws, v in actor.memberships.items()
        ],
    }


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    await db.execute(
        delete(LoginSession).where(LoginSession.token_hash == token_digest(request.cookies.get(COOKIE, "")))
    )
    audit(db, "logout", actor_required().user_id)
    await db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.post("/auth/password", status_code=204)
async def change_password(payload: PasswordChange, response: Response, db: AsyncSession = Depends(get_db)):
    user = await db.get(User, actor_required().user_id, with_for_update=True)
    if not await asyncio.to_thread(verify_password, payload.old_password, user.password_hash):
        raise HTTPException(400, "原密码不正确")
    if payload.old_password == payload.new_password:
        raise HTTPException(422, "新密码不能与原密码相同")
    user.password_hash = await asyncio.to_thread(hash_password, payload.new_password)
    user.must_change_password = False
    user.auth_version += 1
    await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, "password.changed", user.id)
    await db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/auth/agents")
async def available_agents(db: AsyncSession = Depends(get_db)):
    actor = actor_required()
    require("agent.use")
    agents = (await db.execute(select(Agent).order_by(Agent.name))).scalars().all()
    return [
        {k: getattr(a, k) for k in ["id", "workspace_id", "name", "description", "avatar", "status", "agent_type"]}
        for a in agents
        if actor.can_use(a)
    ]


@router.get("/admin/users")
async def users(q: str = "", db: AsyncSession = Depends(get_db)):
    require("users.manage")
    stmt = select(User).order_by(User.created_at.desc())
    if q:
        stmt = stmt.where(User.username.ilike("%" + q + "%") | User.display_name.ilike("%" + q + "%"))
    return [user_out(u) for u in (await db.execute(stmt.limit(1000))).scalars()]


@router.get("/admin/user-options")
async def user_options(db: AsyncSession = Depends(get_db)):
    require("members.manage")
    return [
        {"id": u.id, "username": u.username, "display_name": u.display_name}
        for u in (
            await db.execute(select(User).where(User.status == "active").order_by(User.display_name).limit(1000))
        ).scalars()
    ]


@router.post("/admin/users", status_code=201)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    require("users.manage")
    if await db.scalar(select(User.id).where(User.username == payload.username.lower())):
        raise HTTPException(409, "用户名已存在")
    values = payload.model_dump(exclude={"password"})
    values["username"] = payload.username.lower()
    user = User(**values, password_hash=await asyncio.to_thread(hash_password, payload.password))
    db.add(user)
    await db.flush()
    audit(db, "user.created", user.id)
    await db.commit()
    return user_out(user)


async def managed_user(db, user_id):
    user = await db.get(User, user_id, with_for_update=True)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if user.is_superadmin and not actor_required().superadmin:
        raise HTTPException(403, "不能修改超级管理员")
    return user


@router.patch("/admin/users/{user_id}")
async def update_user(user_id: uuid.UUID, payload: UserUpdate, db: AsyncSession = Depends(get_db)):
    require("users.manage")
    user = await managed_user(db, user_id)
    if payload.status == "disabled" and (user.is_superadmin or user.id == actor_required().user_id):
        raise HTTPException(409, "不能停用超级管理员或当前账号")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is None and k in ("display_name", "status"):
            raise HTTPException(422, "名称和状态不能为空")
        setattr(user, k, v)
    if payload.status == "disabled":
        user.auth_version += 1
        await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, "user.updated", user.id, fields=list(payload.model_fields_set))
    await db.commit()
    return user_out(user)


@router.post("/admin/users/{user_id}/reset-password", status_code=204)
async def reset_password(user_id: uuid.UUID, payload: PasswordReset, db: AsyncSession = Depends(get_db)):
    require("users.manage")
    user = await managed_user(db, user_id)
    user.password_hash = await asyncio.to_thread(hash_password, payload.password)
    user.must_change_password = True
    user.auth_version += 1
    await db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
    audit(db, "password.reset", user.id)
    await db.commit()


@router.get("/admin/permissions")
async def permissions():
    actor = actor_required()
    if not (actor.has("roles.manage") or actor.has("members.manage")):
        raise HTTPException(403)
    return [
        {"code": code, "name": name, "scope": "system" if code in SYSTEM else "workspace"}
        for code, name in PERMISSIONS.items()
    ]


@router.get("/admin/roles")
async def roles(db: AsyncSession = Depends(get_db)):
    actor = actor_required()
    if not (actor.has("roles.manage") or actor.has("members.manage") or actor.has("users.manage")):
        raise HTTPException(403)
    return [role_out(r) for r in (await db.execute(select(Role).order_by(Role.scope, Role.name))).scalars()]


def validate_role(payload):
    allowed = SYSTEM if payload.scope == "system" else SPACE
    if set(payload.permissions) - set(allowed):
        raise HTTPException(422, "权限编码与角色范围不匹配")
    actor = actor_required()
    # Editing reusable roles can elevate every assignee; only superadmin changes their permission content.
    if not actor.superadmin:
        raise HTTPException(403, "角色权限定义仅限超级管理员维护")


@router.post("/admin/roles", status_code=201)
async def create_role(payload: RoleInput, db: AsyncSession = Depends(get_db)):
    require("roles.manage")
    validate_role(payload)
    if await db.scalar(select(Role.id).where(Role.code == payload.code)):
        raise HTTPException(409, "角色编码已存在")
    role = Role(**payload.model_dump())
    db.add(role)
    await db.flush()
    audit(db, "role.created", role.id, permissions=role.permissions)
    await db.commit()
    return role_out(role)


@router.put("/admin/roles/{role_id}")
async def update_role(role_id: uuid.UUID, payload: RoleInput, db: AsyncSession = Depends(get_db)):
    require("roles.manage")
    validate_role(payload)
    role = await db.get(Role, role_id, with_for_update=True)
    if role is None:
        raise HTTPException(404)
    if role.builtin or role.scope != payload.scope or role.code != payload.code:
        raise HTTPException(409, "内置角色不可修改，角色编码和范围不可变更")
    role.name, role.permissions = payload.name, payload.permissions
    audit(db, "role.updated", role.id, permissions=role.permissions)
    await db.commit()
    return role_out(role)


@router.delete("/admin/roles/{role_id}", status_code=204)
async def delete_role(role_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    require("roles.manage")
    if not actor_required().superadmin:
        raise HTTPException(403)
    role = await db.get(Role, role_id, with_for_update=True)
    if role is None:
        raise HTTPException(404)
    if (
        role.builtin
        or await db.scalar(select(MemberRole.member_id).where(MemberRole.role_id == role_id).limit(1))
        or await db.scalar(select(SystemRoleBinding.user_id).where(SystemRoleBinding.role_id == role_id).limit(1))
    ):
        raise HTTPException(409, "内置角色或已分配角色不能删除")
    await db.delete(role)
    audit(db, "role.deleted", role_id)
    await db.commit()


async def checked_roles(db, ids, scope):
    roles = list((await db.execute(select(Role).where(Role.id.in_(ids)).with_for_update())).scalars())
    if len(roles) != len(set(ids)) or any(r.scope != scope for r in roles):
        raise HTTPException(422, "角色不存在或范围不匹配")
    actor = actor_required()
    if not actor.superadmin:
        available = actor.system_permissions if scope == "system" else actor.permissions
        if {p for r in roles for p in r.permissions} - available:
            raise HTTPException(403, "不能授予超出自身范围的权限")
    return roles


@router.get("/admin/users/{user_id}/system-roles")
async def get_system_roles(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    require("users.manage")
    return list(
        (await db.execute(select(SystemRoleBinding.role_id).where(SystemRoleBinding.user_id == user_id))).scalars()
    )


@router.put("/admin/users/{user_id}/system-roles", status_code=204)
async def set_system_roles(user_id: uuid.UUID, payload: RolesInput, db: AsyncSession = Depends(get_db)):
    require("roles.manage")
    await managed_user(db, user_id)
    await checked_roles(db, payload.role_ids, "system")
    await db.execute(delete(SystemRoleBinding).where(SystemRoleBinding.user_id == user_id))
    for role_id in set(payload.role_ids):
        db.add(SystemRoleBinding(user_id=user_id, role_id=role_id))
    audit(db, "user.system_roles", user_id, role_ids=[str(i) for i in payload.role_ids])
    await db.commit()


async def manage_space(db, workspace_id):
    actor = actor_required()
    actor.workspace_id = workspace_id
    require("members.manage")
    ws = (
        await db.execute(raw(select(Workspace).where(Workspace.id == workspace_id).with_for_update()))
    ).scalar_one_or_none()
    if ws is None:
        raise HTTPException(404)
    return ws


@router.get("/admin/workspaces/{workspace_id}/members")
async def members(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await manage_space(db, workspace_id)
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.workspace_id == workspace_id)
            .order_by(User.display_name)
        )
    ).all()
    result = []
    for member, user in rows:
        roles = list((await db.execute(select(MemberRole.role_id).where(MemberRole.member_id == member.id))).scalars())
        grants = list(
            (await db.execute(select(AgentGrant.agent_id).where(AgentGrant.member_id == member.id))).scalars()
        )
        result.append(
            {
                "id": member.id,
                "user_id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "status": user.status,
                "role_ids": roles,
                "all_agents": member.all_agents,
                "agent_ids": grants,
            }
        )
    return result


@router.get("/admin/workspaces/{workspace_id}/agents")
async def grant_options(workspace_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await manage_space(db, workspace_id)
    actor = actor_required()
    rows = (await db.execute(select(Agent).where(Agent.workspace_id == workspace_id).order_by(Agent.name))).scalars()
    return [
        {k: getattr(a, k) for k in ["id", "name", "status"]}
        for a in rows
        if actor.superadmin
        or actor.memberships[workspace_id]["all_agents"]
        or a.id in actor.memberships[workspace_id]["agent_ids"]
    ]


@router.put("/admin/workspaces/{workspace_id}/members")
async def save_member(workspace_id: uuid.UUID, payload: MemberInput, db: AsyncSession = Depends(get_db)):
    await manage_space(db, workspace_id)
    user = await db.get(User, payload.user_id)
    if user is None or user.status != "active":
        raise HTTPException(422, "用户不存在或已停用")
    actor = actor_required()
    if user.is_superadmin and not actor.superadmin:
        raise HTTPException(403, "不能修改超级管理员的授权")
    await checked_roles(db, payload.role_ids, "workspace")
    own_member = actor.memberships[workspace_id]
    if not actor.superadmin:
        if payload.all_agents and not own_member["all_agents"]:
            raise HTTPException(403, "不能授予全部 Agent")
        if not own_member["all_agents"] and set(payload.agent_ids) - own_member["agent_ids"]:
            raise HTTPException(403, "不能分配未获授权的 Agent")
    agents = (
        (await db.execute(raw(select(Agent).where(Agent.id.in_(payload.agent_ids)).with_for_update()))).scalars().all()
    )
    if len(agents) != len(set(payload.agent_ids)) or any(a.workspace_id != workspace_id for a in agents):
        raise HTTPException(422, "Agent 必须属于该工作空间")
    member = await db.scalar(
        select(Membership)
        .where(Membership.user_id == payload.user_id, Membership.workspace_id == workspace_id)
        .with_for_update()
    )
    if member is None:
        member = Membership(user_id=payload.user_id, workspace_id=workspace_id)
        db.add(member)
        await db.flush()
    member.all_agents = payload.all_agents
    await db.execute(delete(MemberRole).where(MemberRole.member_id == member.id))
    await db.execute(delete(AgentGrant).where(AgentGrant.member_id == member.id))
    for role_id in set(payload.role_ids):
        db.add(MemberRole(member_id=member.id, role_id=role_id))
    for ident in set(payload.agent_ids):
        db.add(AgentGrant(member_id=member.id, agent_id=ident))
    audit(
        db,
        "workspace.member_granted",
        member.id,
        workspace_id=str(workspace_id),
        user_id=str(user.id),
        role_ids=[str(i) for i in payload.role_ids],
        all_agents=payload.all_agents,
        agent_ids=[str(i) for i in payload.agent_ids],
    )
    await db.commit()
    return {"id": member.id}


@router.delete("/admin/workspaces/{workspace_id}/members/{user_id}", status_code=204)
async def remove_member(workspace_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    await manage_space(db, workspace_id)
    await db.execute(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    user = await db.get(User, user_id)
    if user and user.is_superadmin:
        raise HTTPException(409, "保留超级管理员的空间成员资格")
    member = await db.scalar(
        select(Membership)
        .where(Membership.user_id == user_id, Membership.workspace_id == workspace_id)
        .with_for_update()
    )
    if member is None:
        raise HTTPException(404)
    from agentdevstu.organization.models import OrgUnit
    nodes = (await db.execute(select(OrgUnit).where(
        OrgUnit.workspace_id == workspace_id, OrgUnit.manager_user_id == user_id))).scalars()
    for node in nodes:
        node.manager_user_id = None
    await db.flush()
    await db.delete(member)  # Database also cascades the responsibility profile.
    audit(db, "workspace.member_removed", user_id, workspace_id=str(workspace_id))
    await db.commit()


@router.get("/admin/audit")
async def audit_logs(db: AsyncSession = Depends(get_db)):
    require("audit.read")
    rows = (
        await db.execute(
            select(AuditLog, User.username)
            .outerjoin(User, User.id == AuditLog.actor_id)
            .order_by(AuditLog.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        {
            "id": a.id,
            "actor": name,
            "action": a.action,
            "target": a.target,
            "detail": a.detail,
            "created_at": a.created_at,
        }
        for a, name in rows
    ]


@router.get("/admin/identity-providers")
async def identity_providers(db: AsyncSession = Depends(get_db)):
    require("identity.manage")
    rows = (await db.execute(select(IdentityProvider).order_by(IdentityProvider.name))).scalars()
    return [
        {k: getattr(p, k) for k in ["id", "code", "name", "protocol", "issuer", "enabled", "field_mapping"]}
        for p in rows
    ]


@router.post("/admin/identity-providers", status_code=201)
async def create_provider(payload: ProviderInput, db: AsyncSession = Depends(get_db)):
    require("identity.manage")
    if await db.scalar(select(IdentityProvider.id).where(IdentityProvider.code == payload.code)):
        raise HTTPException(409, "来源编码已存在")
    provider = IdentityProvider(**payload.model_dump(), enabled=False)
    db.add(provider)
    await db.flush()
    audit(db, "identity.provider_reserved", provider.id)
    await db.commit()
    return {"id": provider.id, "enabled": False}


@router.get("/admin/users/{user_id}/identities")
async def user_identities(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    require("identity.manage")
    rows = (await db.execute(select(ExternalIdentity).where(ExternalIdentity.user_id == user_id))).scalars()
    return [{k: getattr(i, k) for k in ["id", "provider_id", "tenant_id", "subject", "last_synced_at"]} for i in rows]
