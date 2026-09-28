import uuid

from sqlalchemy import JSON, CheckConstraint, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cortexa.db.engine import Base


class OrgUnit(Base):
    __tablename__ = "t_org_units"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("workspace_id", "code"),
        ForeignKeyConstraint(["workspace_id", "parent_id"], ["t_org_units.workspace_id", "t_org_units.id"]),
        CheckConstraint("parent_id IS NULL OR parent_id <> id"),
        CheckConstraint("status IN ('active', 'disabled')"),
        CheckConstraint("type IN ('department', 'team')"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("t_workspaces.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None]
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str | None] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(20), default="department")
    manager_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("t_users.id", ondelete="SET NULL"))
    sort_order: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")


class MemberProfile(Base):
    __tablename__ = "t_workspace_member_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "workspace_id"],
            ["t_workspace_members.user_id", "t_workspace_members.workspace_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(["workspace_id", "org_unit_id"], ["t_org_units.workspace_id", "t_org_units.id"]),
        CheckConstraint("is_primary = true"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    org_unit_id: Mapped[uuid.UUID | None]
    position_title: Mapped[str] = mapped_column(String(120), default="")
    responsibility: Mapped[str] = mapped_column(String(2000), default="")
    responsibility_tags: Mapped[list] = mapped_column(JSON, default=list)
    coverage_scope: Mapped[str] = mapped_column(String(1000), default="")
    is_primary: Mapped[bool] = mapped_column(default=True)
