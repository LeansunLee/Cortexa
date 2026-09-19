"""Scoped source-deletion propagation, correction invalidation and bounded consolidation."""

import uuid
import time
from sqlalchemy import select, update, or_, cast, Text
from fastapi import HTTPException
from agentdevstu.db.models import Memory, ConversationMessage
from agentdevstu.work.models import WorkActivity
from agentdevstu.security.access import actor_required
from .models import MemoryEvidence, MemoryRelation, MemoryEvent, MemoryIssue
from .policy import now, digest
from .access import agent_access


async def descendants(db, ids, ws):
    if not ids:
        return set()
    rel = MemoryRelation.__table__
    tree = (
        select(rel.c.from_memory_id.label("id"))
        .where(rel.c.workspace_id == ws, rel.c.to_memory_id.in_(ids), rel.c.relation_type == "derived_from")
        .cte("memory_descendants", recursive=True)
    )
    tree = tree.union(
        select(rel.c.from_memory_id)
        .join(tree, rel.c.to_memory_id == tree.c.id)
        .where(rel.c.workspace_id == ws, rel.c.relation_type == "derived_from")
    )
    return set((await db.scalars(select(tree.c.id))).all()) - set(ids)


async def scrub_copies(db, ids, ws):
    if not ids:
        return
    # Core statements here are a narrowly scoped deletion capability, never an unscoped read API.
    message = ConversationMessage.__table__
    from agentdevstu.db.models import Conversation

    conversations = select(Conversation.__table__.c.id).where(Conversation.__table__.c.workspace_id == ws)
    for batch in [list(ids)[n : n + 100] for n in range(0, len(ids), 100)]:
        patterns = or_(*(cast(message.c.metadata_json, Text).contains(str(x)) for x in batch))
        for row in (
            await db.execute(
                select(message.c.id, message.c.metadata_json).where(
                    message.c.conversation_id.in_(conversations), patterns
                )
            )
        ).mappings():
            meta = dict(row["metadata_json"] or {})
            meta.pop("debug_trace", None)
            if "memory_trace" in meta:
                meta["memory_trace"] = {"redacted": True, "reason": "source_deleted"}
            await db.execute(update(message).where(message.c.id == row["id"]).values(metadata_json=meta))
        activity = WorkActivity.__table__
        for row in (
            await db.execute(
                select(activity.c.id, activity.c.data_json).where(
                    activity.c.workspace_id == ws,
                    activity.c.action == "memory",
                    or_(*(cast(activity.c.data_json, Text).contains(str(x)) for x in batch)),
                )
            )
        ).mappings():
            data = dict(row["data_json"] or {})
            data["content"] = "[来源已删除]"
            data["source_deleted"] = True
            await db.execute(update(activity).where(activity.c.id == row["id"]).values(data_json=data))


async def block_records(db, ids, *, purge, reason):
    a = actor_required()
    ws = a.workspace_id
    table = Memory.__table__
    ev = MemoryEvidence.__table__
    if not ids:
        return
    rows = (await db.execute(select(table).where(table.c.workspace_id == ws, table.c.id.in_(ids)))).mappings().all()
    for row in rows:
        meta = dict(row["metadata_json"] or {})
        meta["source_review_required"] = True
        values = {
            "metadata_json": meta,
            "revision": row["revision"] + 1,
            "updated_at": now(),
            "confidence": min(row["confidence"], 0.4),
        }
        if purge:
            meta["content_purged"] = True
            values.update(
                content="[来源已删除，记忆正文已清除]",
                status="archived",
                search_terms=[],
                normalized_hash=None,
                subject_id=None,
                subject_name=None,
                claim_key=None,
                source_id=None,
            )
            await db.execute(
                update(ev)
                .where(ev.c.memory_id == row["id"], ev.c.workspace_id == ws)
                .values(
                    summary=None,
                    source_id=None,
                    source_sub_id=None,
                    source_user_id=None,
                    source_agent_id=None,
                    root_keys=[],
                    metadata_json={},
                    source_status="deleted",
                )
            )
            await db.execute(
                update(MemoryEvent.__table__)
                .where(MemoryEvent.__table__.c.memory_id == row["id"])
                .values(reason=None, data_json={})
            )
            await db.execute(
                update(MemoryIssue.__table__)
                .where(MemoryIssue.__table__.c.memory_id == row["id"])
                .values(status="dismissed", detail_json={}, resolution_json={}, resolved_at=now())
            )
        await db.execute(update(table).where(table.c.id == row["id"], table.c.workspace_id == ws).values(**values))
        if not purge:
            key = digest(["source_review", str(row["id"])])
            from sqlalchemy.dialects.postgresql import insert

            await db.execute(
                insert(MemoryIssue.__table__)
                .values(
                    id=uuid.uuid4(),
                    workspace_id=ws,
                    agent_id=row["agent_id"],
                    memory_id=row["id"],
                    issue_type="governance_failure",
                    severity="warning",
                    status="open",
                    dedupe_key=key,
                    related_memory_ids=[str(row["id"])],
                    reason_code=reason,
                    detail_json={},
                    resolution_json={},
                )
                .on_conflict_do_nothing()
            )
    await scrub_copies(db, ids, ws)


async def invalidate_dependents(db, memory_id, *, purge=False):
    ws = actor_required().workspace_id
    ids = await descendants(db, {memory_id}, ws)
    evidence = MemoryEvidence.__table__
    if ids:
        await db.execute(
            update(evidence)
            .where(
                evidence.c.workspace_id == ws,
                evidence.c.memory_id.in_(ids),
                evidence.c.source_type == "other_agent_memory",
                evidence.c.source_id.in_([str(x) for x in ids | {memory_id}]),
            )
            .values(source_status="unavailable")
        )
        for ident in ids:
            independent = await db.scalar(
                select(evidence.c.id)
                .where(
                    evidence.c.workspace_id == ws,
                    evidence.c.memory_id == ident,
                    evidence.c.source_status == "available",
                    evidence.c.stance == "supports",
                    evidence.c.source_type.not_in(["other_agent_memory", "collaboration"]),
                )
                .limit(1)
            )
            await block_records(db, {ident}, purge=purge and not independent, reason="upstream_changed")
    return ids


async def source_deleted(db, source_type, source_id, *, message_id=None):
    a = actor_required()
    ws = a.workspace_id
    # The caller must still own the existing Source; do not accept arbitrary IDs for cross-user cleanup.
    from .evidence import Source, validate_source

    source = Source(
        source_type,
        str(source_id),
        sub_type="message" if message_id else None,
        sub_id=str(message_id) if message_id else None,
    )
    if not await validate_source(db, source):
        raise HTTPException(404, "来源不存在或无权删除")
    from .governance import source_lock

    await source_lock(db, source)
    ev = MemoryEvidence.__table__
    table = Memory.__table__
    where = [ev.c.workspace_id == ws, ev.c.source_type == source_type, ev.c.source_id == str(source_id)]
    if message_id:
        where.append(or_(ev.c.source_sub_id == str(message_id), ev.c.source_sub_id.is_(None)))
    ids = set((await db.scalars(select(ev.c.memory_id).where(*where))).all())
    ids.update(
        (
            await db.scalars(
                select(table.c.id).where(
                    table.c.workspace_id == ws,
                    table.c.source_type == source_type,
                    table.c.source_id == source_id,
                    ~select(ev.c.id).where(ev.c.memory_id == table.c.id).exists(),
                )
            )
        ).all()
    )
    await db.execute(
        update(ev)
        .where(*where)
        .values(
            source_status="deleted",
            summary=None,
            source_id=None,
            source_sub_id=None,
            source_user_id=None,
            source_agent_id=None,
            root_keys=[],
            metadata_json={},
        )
    )
    for memory_id in ids:
        remaining = await db.scalar(
            select(ev.c.id)
            .where(ev.c.memory_id == memory_id, ev.c.source_status == "available", ev.c.stance == "supports")
            .limit(1)
        )
        await block_records(db, {memory_id}, purge=remaining is None, reason="source_deleted")
        await invalidate_dependents(db, memory_id, purge=remaining is None)
    return len(ids)


async def purge_memory(db, mem):
    from agentdevstu.security.access import require

    await agent_access(db, mem.agent_id, manage=True)
    require("workspace.manage")
    await invalidate_dependents(db, mem.id, purge=True)
    await block_records(db, {mem.id}, purge=True, reason="privacy_purged")
    # Tombstone keeps relation integrity and an audit marker; it has no recoverable cognition.
    await db.refresh(mem)
    return mem


async def consolidate(db, agent_id, cursor=None, limit=100):
    await agent_access(db, agent_id, manage=True)
    from .governance import lock_agent, event, confidence, issue, reprocess

    q = select(Memory).where(Memory.agent_id == agent_id, Memory.status.in_(["active", "candidate"]))
    if cursor:
        q = q.where(Memory.id > uuid.UUID(cursor))
    rows = (await db.scalars(q.order_by(Memory.id).limit(min(limit, 100) + 1))).all()
    more = len(rows) > min(limit, 100)
    rows = rows[: min(limit, 100)]
    result = {
        "processed": 0,
        "expired": 0,
        "superseded": 0,
        "review": 0,
        "next_cursor": str(rows[-1].id) if more else None,
    }
    started = time.monotonic()
    for mem in rows:
        if time.monotonic() - started > 20 and result["processed"]:
            result["next_cursor"] = str(rows[result["processed"] - 1].id)
            break
        result["processed"] += 1
        if mem.status in {"active", "candidate"} and not mem.has_conflict:
            outcome = await reprocess(db, mem, use_model=True)
            result[outcome] = result.get(outcome, 0) + 1
        await lock_agent(db, agent_id)
        await db.refresh(mem)
        if mem.status == "active" and (
            (mem.expires_at and mem.expires_at <= now()) or (mem.valid_to and mem.valid_to <= now())
        ):
            has_successor = await db.scalar(
                select(MemoryRelation.id)
                .where(MemoryRelation.to_memory_id == mem.id, MemoryRelation.relation_type == "supersedes")
                .limit(1)
            )
            mem.status = "superseded" if has_successor else "expired"
            mem.revision += 1
            result[mem.status] += 1
            await event(db, mem, mem.status, "temporal_policy")
        elif mem.status == "candidate" or mem.metadata_json.get("source_review_required"):
            await issue(db, mem, "governance_failure", "candidate_or_source_review")
            result["review"] += 1
        else:
            await confidence(db, mem)
        await db.commit()
    return result
