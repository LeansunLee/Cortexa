"""Agent Memory API: management is separate from runtime use and source access."""

from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict, model_validator
from sqlalchemy import select, func, or_, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from agentdevstu.api.deps import get_db
from agentdevstu.db.models import Memory
from agentdevstu.security.access import actor_required
from agentdevstu.memory.schemas import Candidate, MemoryType, Correction
from agentdevstu.memory.access import agent_access, memory_access
from agentdevstu.memory.evidence import Source, visible_evidence
from agentdevstu.memory.models import MemoryEvidence, MemoryRelation, MemoryEvent, MemoryIssue
from agentdevstu.memory.governance import (
    ingest,
    correct,
    change_state,
    event,
    lock_agent,
    confidence,
    append_evidence,
)
from agentdevstu.memory.policy import now, STATUSES

router = APIRouter(prefix="/memories", tags=["memories"])


class MemoryCreate(Candidate):
    agent_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    type: MemoryType | None = None
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    importance: float | None = Field(default=None, ge=0, le=1)
    status: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def nonnull_changes(self):
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("更新字段不能为 null")
        if self.content is not None and not self.content.strip():
            raise ValueError("内容不能为空")
        return self


def memory_item(mem):
    values = {
        key: getattr(mem, key, None)
        for key in (
            "id",
            "agent_id",
            "type",
            "content",
            "memory_kind",
            "subject_type",
            "subject_id",
            "subject_name",
            "importance",
            "confidence",
            "status",
            "source_mode",
            "risk_level",
            "has_conflict",
            "revision",
            "occurred_at",
            "valid_from",
            "valid_to",
            "expires_at",
            "created_at",
            "updated_at",
            "access_count",
        )
    }
    values["source_type"] = mem.source_type
    values["confidence_basis"] = (mem.metadata_json or {}).get("confidence_basis", {})
    values["legacy_uncalibrated"] = bool((mem.metadata_json or {}).get("legacy_uncalibrated"))
    values["source_review_required"] = bool((mem.metadata_json or {}).get("source_review_required"))
    values["content_purged"] = bool((mem.metadata_json or {}).get("content_purged"))
    values["outcome"] = getattr(mem, "governance_outcome", None)
    return values


@router.get("")
async def list_memories(
    agent_id: uuid.UUID,
    type: MemoryType | None = None,
    status: str | None = None,
    q: str | None = Query(None, max_length=200),
    kind: str | None = None,
    subject: str | None = Query(None, max_length=128),
    risk: str | None = None,
    conflict: bool | None = None,
    confidence_min: float | None = Query(None, ge=0, le=1),
    cursor: uuid.UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await agent_access(db, agent_id, manage=True)
    stmt = select(Memory).where(Memory.agent_id == agent_id)
    if status:
        if status not in STATUSES:
            raise HTTPException(422, "未知记忆状态")
        stmt = stmt.where(Memory.status == status)
    else:
        stmt = stmt.where(Memory.status.not_in(["archived", "rejected"]))
    if type:
        stmt = stmt.where(Memory.type == type)
    if kind:
        stmt = stmt.where(Memory.memory_kind == kind)
    if q:
        stmt = stmt.where(Memory.content.ilike("%" + q.replace("%", "\\%").replace("_", "\\_") + "%"))
    if subject:
        stmt = stmt.where(or_(Memory.subject_id == subject, Memory.subject_name.ilike("%" + subject + "%")))
    if risk:
        stmt = stmt.where(Memory.risk_level == risk)
    if conflict is not None:
        stmt = stmt.where(Memory.has_conflict == conflict)
    if confidence_min is not None:
        stmt = stmt.where(Memory.confidence >= confidence_min)
    if cursor:
        stmt = stmt.where(Memory.id < cursor)
    items = list((await db.scalars(stmt.order_by(Memory.id.desc()).limit(limit + 1))).all())
    more = len(items) > limit
    items = items[:limit]
    return {
        "items": [memory_item(m) for m in items],
        "has_more": more,
        "next_cursor": str(items[-1].id) if more else None,
    }


@router.post("", status_code=201)
async def create_memory(payload: MemoryCreate, db: AsyncSession = Depends(get_db)):
    if not payload.agent_id:
        raise HTTPException(422, "记忆必须指定 Agent")
    await agent_access(db, payload.agent_id, manage=True)
    key = payload.idempotency_key or str(uuid.uuid4())
    source = Source("manual", key, user_id=actor_required().user_id, mode="explicit")
    data = payload.model_dump(exclude={"agent_id", "idempotency_key"})
    data["source_mode"] = "explicit"
    mem = await ingest(db, payload.agent_id, data, source, trusted=True, intake_key="manual:" + key)
    return memory_item(mem)


@router.get("/{memory_id}")
async def get_memory(memory_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    mem = await memory_access(db, memory_id, manage=True)
    relations = (
        await db.scalars(
            select(MemoryRelation)
            .where(or_(MemoryRelation.from_memory_id == mem.id, MemoryRelation.to_memory_id == mem.id))
            .limit(100)
        )
    ).all()
    item = memory_item(mem)
    item["relations"] = [
        {"from_memory_id": r.from_memory_id, "to_memory_id": r.to_memory_id, "type": r.relation_type} for r in relations
    ]
    item["permissions"] = {
        "correct": mem.status not in {"retracted", "rejected"} and not item["content_purged"],
        "archive": mem.status != "archived",
        "restore": mem.status == "archived" and not item["content_purged"],
        "purge": actor_required().has("workspace.manage"),
    }
    return item


@router.patch("/{memory_id}")
async def update_memory(memory_id: uuid.UUID, payload: MemoryUpdate, db: AsyncSession = Depends(get_db)):
    mem = await memory_access(db, memory_id, manage=True, lock=True)
    if payload.expected_revision is None:
        raise HTTPException(422, "需要 expected_revision")
    if payload.expected_revision != mem.revision:
        raise HTTPException(409, "记忆已变化，请刷新")
    if payload.content is not None or payload.type is not None:
        raise HTTPException(409, "认知内容或类别变化请使用纠正记忆")
    if payload.status:
        await change_state(db, mem, payload.status, expected_revision=payload.expected_revision)
    if payload.importance is not None:
        before = mem.revision
        mem.importance = payload.importance
        mem.revision += 1
        mem.updated_at = now()
        await event(db, mem, "metadata_updated", "importance", before=before)
    return memory_item(mem)


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(memory_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    mem = await memory_access(db, memory_id, manage=True)
    await change_state(db, mem, "archived")


@router.post("/{memory_id}/restore")
async def restore(memory_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    mem = await memory_access(db, memory_id, manage=True)
    return memory_item(await change_state(db, mem, "active"))


@router.post("/{memory_id}/purge")
async def purge(memory_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from agentdevstu.memory.lifecycle import purge_memory

    mem = await memory_access(db, memory_id, manage=True)
    return memory_item(await purge_memory(db, mem))


@router.post("/{memory_id}/corrections")
async def corrections(memory_id: uuid.UUID, payload: Correction, db: AsyncSession = Depends(get_db)):
    mem = await memory_access(db, memory_id, manage=True)
    return memory_item(await correct(db, mem, payload))


@router.post("/{memory_id}/supersessions")
async def supersessions(memory_id: uuid.UUID, payload: Correction, db: AsyncSession = Depends(get_db)):
    mem = await memory_access(db, memory_id, manage=True)
    return memory_item(await correct(db, mem, payload, supersede=True))


@router.get("/{memory_id}/evidences")
async def evidences(
    memory_id: uuid.UUID,
    cursor: uuid.UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await memory_access(db, memory_id, manage=True)
    q = select(MemoryEvidence).where(MemoryEvidence.memory_id == memory_id)
    if cursor:
        q = q.where(MemoryEvidence.id < cursor)
    rows = list((await db.scalars(q.order_by(MemoryEvidence.id.desc()).limit(limit + 1))).all())
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [await visible_evidence(db, r) for r in rows],
        "has_more": more,
        "next_cursor": str(rows[-1].id) if more else None,
    }


@router.get("/{memory_id}/history")
async def history(
    memory_id: uuid.UUID,
    cursor: uuid.UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    await memory_access(db, memory_id, manage=True)
    stmt = select(MemoryEvent).where(MemoryEvent.memory_id == memory_id)
    if cursor:
        previous = await db.scalar(
            select(MemoryEvent).where(MemoryEvent.id == cursor, MemoryEvent.memory_id == memory_id)
        )
        if previous is None:
            raise HTTPException(422, "无效的历史记录游标")
        stmt = stmt.where(tuple_(MemoryEvent.created_at, MemoryEvent.id) < tuple_(previous.created_at, previous.id))
    rows = list(
        (await db.scalars(stmt.order_by(MemoryEvent.created_at.desc(), MemoryEvent.id.desc()).limit(limit + 1))).all()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    # Reasons can contain private source prose. Only the recording actor sees it.
    return {
        "items": [
            {
                "id": r.id,
                "event_type": r.event_type,
                "created_at": r.created_at,
                "before_revision": r.before_revision,
                "after_revision": r.after_revision,
                "reason": r.reason if r.actor_user_id == actor_required().user_id else None,
            }
            for r in rows
        ],
        "has_more": more,
        "next_cursor": str(rows[-1].id) if more else None,
    }


async def summary(db, agent_id):
    await agent_access(db, agent_id, manage=True)
    current = now()
    q = (
        select(func.count())
        .select_from(Memory)
        .where(
            Memory.agent_id == agent_id,
            Memory.status == "active",
            or_(Memory.valid_from.is_(None), Memory.valid_from <= current),
            or_(Memory.valid_to.is_(None), Memory.valid_to > current),
            or_(Memory.expires_at.is_(None), Memory.expires_at > current),
            or_(
                Memory.risk_level != "high",
                Memory.metadata_json.cast(__import__("sqlalchemy").dialects.postgresql.JSONB).contains(
                    {"risk_approved": True}
                ),
            ),
            ~Memory.metadata_json.cast(__import__("sqlalchemy").dialects.postgresql.JSONB).contains(
                {"source_review_required": True}
            ),
        )
    )
    active = await db.scalar(q)
    from zoneinfo import ZoneInfo

    local = current.astimezone(ZoneInfo("Asia/Shanghai"))
    week = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    groups = (
        await db.execute(
            select(MemoryEvent.event_type, func.count())
            .where(MemoryEvent.agent_id == agent_id, MemoryEvent.created_at >= week)
            .group_by(MemoryEvent.event_type)
        )
    ).all()
    stats = dict(groups)
    issues = await db.scalar(
        select(func.count())
        .select_from(MemoryIssue)
        .where(MemoryIssue.agent_id == agent_id, MemoryIssue.status.in_(["open", "deferred"]))
    )
    return {
        "active": active,
        "created": stats.get("created", 0),
        "merged": stats.get("merged", 0),
        "superseded": stats.get("superseded", 0),
        "issues": issues,
    }


class Resolution(BaseModel):
    action: Literal["confirm_a", "confirm_b", "temporal", "neither", "defer", "confirm", "retry"]
    reason: str = Field(min_length=1, max_length=1000)
    revisions: dict[str, int]
    periods: dict[str, dict[str, datetime | None]] = Field(default_factory=dict)


async def resolve_issue(db, agent_id, issue_id, payload):
    await agent_access(db, agent_id, manage=True)
    if payload.action == "retry":
        obj = await db.scalar(select(MemoryIssue).where(MemoryIssue.id == issue_id, MemoryIssue.agent_id == agent_id))
        if not obj or obj.issue_type != "governance_failure" or obj.status not in {"open", "deferred"}:
            raise HTTPException(409, "当前事项不能重试治理")
        mem = await memory_access(db, obj.memory_id, manage=True)
        if payload.revisions.get(str(mem.id)) != mem.revision:
            raise HTTPException(409, "记忆已变化，请刷新")
        from agentdevstu.memory.governance import reprocess

        outcome = await reprocess(db, mem)
        return {"status": "open" if outcome == "review" else "resolved", "outcome": outcome}
    await lock_agent(db, agent_id)
    obj = await db.scalar(
        select(MemoryIssue).where(MemoryIssue.id == issue_id, MemoryIssue.agent_id == agent_id).with_for_update()
    )
    if not obj:
        raise HTTPException(404, "异常事项不存在")
    if obj.status not in {"open", "deferred"}:
        raise HTTPException(409, "该事项已处理")
    ids = [uuid.UUID(x) for x in obj.related_memory_ids]
    memories = list(
        (
            await db.scalars(
                select(Memory)
                .where(Memory.id.in_(ids), Memory.agent_id == agent_id)
                .order_by(Memory.id)
                .with_for_update()
            )
        ).all()
    )
    if not memories or any(payload.revisions.get(str(m.id)) != m.revision for m in memories):
        raise HTTPException(409, "认知已变化，请刷新后处理")
    if any(m.metadata_json.get("content_purged") for m in memories):
        raise HTTPException(409, "来源正文已删除，不能恢复")
    if payload.action == "confirm" and obj.issue_type == "conflict":
        raise HTTPException(422, "冲突必须逐项裁决，不能直接确认全部")
    if payload.action == "temporal" and obj.issue_type != "conflict":
        raise HTTPException(422, "时间裁决仅用于冲突")
    if payload.action == "defer":
        obj.status = "deferred"
        obj.updated_at = now()
        for m in memories:
            await event(db, m, "issue_deferred", payload.reason, data={"issue_id": str(obj.id)})
        return {"status": "deferred"}
    if payload.action in {"confirm_a", "confirm_b"} and (len(memories) != 2 or obj.issue_type != "conflict"):
        raise HTTPException(422, "请选择有效冲突双方")
    selected = (
        memories[0 if payload.action == "confirm_a" else 1] if payload.action in {"confirm_a", "confirm_b"} else None
    )
    if payload.action == "temporal":
        for m in memories:
            data = payload.periods.get(str(m.id), {})
            try:
                validated = Candidate(
                    content=m.content, valid_from=data.get("valid_from"), valid_to=data.get("valid_to")
                )
            except ValueError:
                raise HTTPException(422, "有效时间区间不正确")
            if not validated.valid_from or not validated.valid_to:
                raise HTTPException(422, "每条认知需明确有效区间")
            payload.periods[str(m.id)] = {"valid_from": validated.valid_from, "valid_to": validated.valid_to}
        periods = [(payload.periods[str(m.id)]["valid_from"], payload.periods[str(m.id)]["valid_to"]) for m in memories]
        if len(periods) == 2 and periods[0][0] < periods[1][1] and periods[1][0] < periods[0][1]:
            raise HTTPException(422, "时间区间仍然重叠")
    for m in memories:
        source = Source(
            "human_feedback",
            str(obj.id) + ":" + str(m.revision),
            user_id=actor_required().user_id,
            summary=payload.reason,
        )
        if payload.action == "neither" or (selected is not None and selected.id != m.id):
            m.status = "retracted"
            await append_evidence(db, m, source, "corrects")
            from agentdevstu.memory.lifecycle import invalidate_dependents

            await invalidate_dependents(db, m.id)
        else:
            if payload.action == "temporal":
                period = payload.periods[str(m.id)]
                m.valid_from = period["valid_from"]
                m.valid_to = period["valid_to"]
            m.status = "superseded" if m.valid_to and m.valid_to <= now() else "active"
            m.metadata_json = {
                **m.metadata_json,
                "risk_approved": True,
                "human_corrected": True,
                "source_review_required": False,
            }
            await append_evidence(db, m, source)
        m.has_conflict = False
        m.revision += 1
        m.updated_at = now()
        await confidence(db, m)
        await event(db, m, "issue_resolved", payload.reason, data={"issue_id": str(obj.id), "action": payload.action})
    obj.status = "resolved"
    obj.resolved_at = now()
    obj.updated_at = now()
    obj.resolved_by_user_id = actor_required().user_id
    obj.resolution_json = {"action": payload.action}
    from agentdevstu.memory.governance import refresh_conflicts
    from agentdevstu.memory.governance import close_retired_conflicts

    for retired in memories:
        if retired.status == "retracted":
            await close_retired_conflicts(db, retired)
    await refresh_conflicts(db, memories)
    await db.flush()
    return {"status": "resolved", "items": [memory_item(m) for m in memories]}
