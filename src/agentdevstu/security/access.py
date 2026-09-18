"""Authorization snapshots are request-local, including child tasks and SSE sessions."""

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from agentdevstu.db.engine import async_session_factory
from agentdevstu.db.models import Agent, Workspace
from .models import User, LoginSession, Role, SystemRoleBinding, Membership, MemberRole, AgentGrant
from .passwords import token_digest
from .catalog import SYSTEM, SPACE


@dataclass
class Actor:
    user_id: uuid.UUID
    username: str
    superadmin: bool
    must_change: bool
    version: int
    system_permissions: set = field(default_factory=set)
    memberships: dict = field(default_factory=dict)
    workspace_id: uuid.UUID | None = None
    runtime: bool = False
    runtime_agent_ids: set = field(default_factory=set)
    operations_knowledge_id: uuid.UUID | None = None

    @property
    def permissions(self):
        return self.memberships.get(self.workspace_id, {}).get("permissions", set())

    def has(self, code):
        if code in SYSTEM:
            return self.superadmin or code in self.system_permissions
        return self.workspace_id in self.memberships and (self.superadmin or code in self.permissions)

    def can_use(self, agent):
        member = self.memberships.get(agent.workspace_id)
        return bool(
            member
            and self.has("agent.use")
            and agent.workspace_id == self.workspace_id
            and agent.status == "active"
            and (self.superadmin or member["all_agents"] or agent.id in member["agent_ids"])
        )

    def signature(self):
        return (
            self.version,
            self.must_change,
            self.superadmin,
            sorted(self.system_permissions),
            repr(self.memberships),
        )


current_actor: ContextVar[Actor | None] = ContextVar("current_actor", default=None)


def actor_required() -> Actor:
    actor = current_actor.get()
    if actor is None:
        raise HTTPException(401, "请先登录")
    return actor


def require(code):
    if not actor_required().has(code):
        raise HTTPException(403, "没有此操作权限")


def raw(stmt):
    # Used only inside security services and migration/bootstrap, never from request data.
    return stmt.execution_options(security_unscoped=True)


async def load_actor(token: str) -> Actor | None:
    async with async_session_factory() as db:
        row = (
            await db.execute(
                select(LoginSession, User)
                .join(User, User.id == LoginSession.user_id)
                .where(
                    LoginSession.token_hash == token_digest(token),
                    LoginSession.expires_at > datetime.now(timezone.utc),
                    User.status == "active",
                    LoginSession.auth_version == User.auth_version,
                )
            )
        ).first()
        if not row:
            return None
        session, user = row
        actor = Actor(user.id, user.username, user.is_superadmin, user.must_change_password, user.auth_version)
        sys_roles = (
            await db.execute(
                select(Role)
                .join(SystemRoleBinding, SystemRoleBinding.role_id == Role.id)
                .where(SystemRoleBinding.user_id == user.id, Role.scope == "system")
                .order_by(Role.code)
            )
        ).scalars()
        for role in sys_roles:
            actor.system_permissions.update(role.permissions)
        rows = (
            (
                await db.execute(
                    raw(
                        select(Membership)
                        .join(Workspace, Workspace.id == Membership.workspace_id)
                        .where(Membership.user_id == user.id, Workspace.status == "active")
                        .order_by(Membership.id)
                    )
                )
            )
            .scalars()
            .all()
        )
        for member in rows:
            roles = (
                (
                    await db.execute(
                        select(Role)
                        .join(MemberRole, MemberRole.role_id == Role.id)
                        .where(MemberRole.member_id == member.id, Role.scope == "workspace")
                        .order_by(Role.code)
                    )
                )
                .scalars()
                .all()
            )
            grants = (
                (
                    await db.execute(
                        raw(
                            select(AgentGrant.agent_id)
                            .join(Agent, Agent.id == AgentGrant.agent_id)
                            .where(AgentGrant.member_id == member.id, Agent.workspace_id == member.workspace_id)
                            .order_by(AgentGrant.agent_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            actor.memberships[member.workspace_id] = {
                "id": member.id,
                "permissions": set(SPACE) if user.is_superadmin else {p for r in roles for p in r.permissions},
                "role_ids": [r.id for r in roles],
                "all_agents": member.all_agents,
                "agent_ids": set(grants),
            }
        return actor


async def require_agent_use(db, agent_id):
    agent = (await db.execute(raw(select(Agent).where(Agent.id == agent_id)))).scalar_one_or_none()
    if agent is None or not actor_required().can_use(agent):
        raise HTTPException(403, "Agent 未授权、未发布或不属于当前工作空间")
    actor_required().runtime_agent_ids.add(agent.id)
    return agent
