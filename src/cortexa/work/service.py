"""State transitions and participant authorization; all mutations lock the parent row."""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import and_, inspect, or_, select

from cortexa.security.access import actor_required, require_agent_use
from cortexa.security.models import Membership, User

from .models import Work, WorkActivity

STORAGE = Path(os.environ.get("WORK_STORAGE_DIR", Path(__file__).resolve().parents[3] / "data" / "works"))
CLOSED = {"completed", "cancelled"}


def actor():
    a = actor_required()
    if a.workspace_id not in a.memberships:
        raise HTTPException(403, "请先加入并选择工作空间")
    return a


def visibility(a):
    scope = Work.workspace_id == a.workspace_id
    if a.has("workspace.manage"):
        return scope
    return and_(
        scope,
        or_(
            Work.creator_id == a.user_id,
            Work.reviewer_id == a.user_id,
            and_(Work.assignee_type == "human", Work.assignee_id == a.user_id),
        ),
    )


def permissions(w, a):
    assignee = w.assignee_type == "human" and w.assignee_id == a.user_id
    manager = w.creator_id == a.user_id or a.has("workspace.manage")
    reviewer = (w.creator_id == a.user_id or w.reviewer_id == a.user_id or a.has("workspace.manage")) and not assignee
    return {
        "log": assignee or manager or w.reviewer_id == a.user_id,
        "edit": manager and w.status in {"draft", "pending", "todo"},
        "start": assignee and w.status in {"todo", "rejected"},
        "submit": assignee and w.status == "in_progress",
        "approve": reviewer and w.status == "review",
        "reject": reviewer and w.status == "review",
        "cancel": manager and w.status not in CLOSED,
        "knowledge": reviewer and w.status == "completed" and a.has("knowledge.manage"),
        "memory": reviewer and w.status == "completed" and a.has("memory.manage"),
    }


def allowed(w, action):
    if not permissions(w, actor()).get(action):
        raise HTTPException(403, "当前身份或工作状态不允许此操作")


async def get_work(db, ident, lock=False):
    q = select(Work).where(Work.id == ident, visibility(actor()))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    w = (await db.execute(q)).scalar_one_or_none()
    if w is None:
        raise HTTPException(404, "工作不存在或无权访问")
    return w


async def member(db, ident):
    row = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.workspace_id == actor().workspace_id, User.id == ident, User.status == "active")
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(422, "负责人和验收人必须是当前空间的有效成员")
    return row


async def validate_people(db, data):
    if data["assignee_type"] == "human":
        await member(db, data["assignee_id"])
    else:
        await require_agent_use(db, data["assignee_id"])
    await member(db, data["reviewer_id"])
    if data["assignee_type"] == "human" and data["assignee_id"] == data["reviewer_id"]:
        raise HTTPException(422, "验收人不能与负责人相同，请指定其他验收人")


async def event(db, w, action, data=None):
    a = actor()
    db.add(
        WorkActivity(workspace_id=w.workspace_id, work_id=w.id, actor_id=a.user_id, action=action, data_json=data or {})
    )
    w.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def create(db, payload, source=None):
    a = actor()
    data = payload.model_dump()
    data["reviewer_id"] = data["reviewer_id"] or a.user_id
    await validate_people(db, data)
    # Agent assignment is reserved and awaits a future runtime; never pretend execution started.
    w = Work(
        **data,
        workspace_id=a.workspace_id,
        creator_id=a.user_id,
        status="pending" if data["assignee_type"] == "agent" else "todo",
        **(source or {}),
    )
    db.add(w)
    await db.flush()
    await event(db, w, "created")
    await event(db, w, "dispatched", {"assignee_type": w.assignee_type, "assignee_id": str(w.assignee_id)})
    return w


async def transition(db, w, action, comment=""):
    allowed(w, action)
    if action == "reject" and not comment.strip():
        raise HTTPException(422, "请填写退回修改原因")
    w.status = {"start": "in_progress", "approve": "completed", "reject": "in_progress", "cancel": "cancelled"}[action]
    if action == "approve":
        w.completed_at = datetime.now(timezone.utc)
        w.completion_note = comment.strip()
    await event(
        db,
        w,
        {"start": "started", "approve": "approved", "reject": "rejected", "cancel": "cancelled"}[action],
        {"comment": comment.strip()},
    )
    return w


def serialize(row):
    return {c.key: getattr(row, c.key) for c in inspect(type(row)).columns}


async def output(db, w):
    data = serialize(w)
    data["permissions"] = permissions(w, actor())
    ids = {w.creator_id, w.reviewer_id}
    if w.assignee_type == "human":
        ids.add(w.assignee_id)
    users = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    names = {u.id: u.display_name for u in users}
    for field in ("creator", "reviewer", "assignee"):
        data[field + "_name"] = names.get(
            getattr(w, field + "_id"), "Agent（待接入执行）" if field == "assignee" else "已停用成员"
        )
    if w.source_id:
        from cortexa.db.models import Conversation

        conv = (
            await db.execute(
                select(Conversation).where(
                    Conversation.id == w.source_id, Conversation.owner_user_id == actor().user_id
                )
            )
        ).scalar_one_or_none()
        data["can_view_source"] = conv is not None and actor().has("agent.use")
    else:
        data["can_view_source"] = False
    return data


def blob_path(ident):
    return STORAGE / str(ident)
