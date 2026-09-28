"""Local identity is stable; external identities never replace business user IDs."""

import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from cortexa.db.engine import Base


class User(Base):
    __tablename__ = "t_users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    is_superadmin: Mapped[bool] = mapped_column(default=False)
    must_change_password: Mapped[bool] = mapped_column(default=True)
    source: Mapped[str] = mapped_column(String(80), default="local")
    auth_version: Mapped[int] = mapped_column(default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoginSession(Base):
    __tablename__ = "t_login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id", ondelete="CASCADE"), index=True)
    auth_version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Role(Base):
    __tablename__ = "t_roles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(20))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    builtin: Mapped[bool] = mapped_column(default=False)


class SystemRoleBinding(Base):
    __tablename__ = "t_user_system_roles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_roles.id", ondelete="RESTRICT"), primary_key=True)


class Membership(Base):
    __tablename__ = "t_workspace_members"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_workspaces.id", ondelete="CASCADE"), index=True)
    all_agents: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemberRole(Base):
    __tablename__ = "t_workspace_member_roles"
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("t_workspace_members.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_roles.id", ondelete="RESTRICT"), primary_key=True)


class AgentGrant(Base):
    __tablename__ = "t_agent_grants"
    member_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("t_workspace_members.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_agents.id", ondelete="CASCADE"), primary_key=True)


class IdentityProvider(Base):
    __tablename__ = "t_identity_providers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    protocol: Mapped[str] = mapped_column(String(32), default="oidc")
    issuer: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(default=False)
    field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)


class ExternalIdentity(Base):
    __tablename__ = "t_external_identities"
    __table_args__ = (UniqueConstraint("provider_id", "tenant_id", "subject"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_identity_providers.id"))
    tenant_id: Mapped[str] = mapped_column(String(160), default="")
    subject: Mapped[str] = mapped_column(String(255))
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "t_security_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("t_users.id"))
    action: Mapped[str] = mapped_column(String(120))
    target: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ProtectedUpload(Base):
    __tablename__ = "t_protected_uploads"
    path: Mapped[str] = mapped_column(String(700), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_users.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_workspaces.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("t_conversations.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
