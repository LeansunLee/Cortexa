"""Bounded Agent retrieval, temporal ranking and auditable prompt selection."""

from collections import Counter
from contextvars import ContextVar
from dataclasses import dataclass, field
import time
from sqlalchemy import select, or_, and_, cast, ARRAY, Text, Integer, update
from agentdevstu.db.models import Memory
from agentdevstu.security.access import actor_required
from .models import MemoryRelation
from .access import agent_access
from .policy import config, filter_reason, relevance, terms, time_window, token_estimate, now, POLICY_VERSION

last_trace = ContextVar("memory_retrieval_trace", default=None)


@dataclass
class RetrievalResult:
    memories: list = field(default_factory=list)
    trace: dict = field(default_factory=dict)


def public_item(mem):
    return {
        "id": str(mem.id),
        "type": mem.type,
        "memory_kind": mem.memory_kind,
        "content": mem.content,
        "subject": {"type": mem.subject_type, "id": mem.subject_id, "name": mem.subject_name},
        "status": mem.status,
        "source_mode": mem.source_mode,
        "confidence": mem.confidence,
        "has_conflict": mem.has_conflict,
        "occurred_at": str(mem.occurred_at) if mem.occurred_at else None,
        "valid_from": str(mem.valid_from) if mem.valid_from else None,
        "valid_to": str(mem.valid_to) if mem.valid_to else None,
    }


def format_context(memories):
    sections = {name: [] for name in ("稳定认知", "相关历史事件", "当前关注", "不确定或冲突认知")}
    for m in memories:
        # Supports legacy mock objects as well as Memory 2 records.
        uncertain = (
            getattr(m, "has_conflict", False)
            or getattr(m, "source_mode", None) == "inferred"
            or getattr(m, "confidence", 0.5) < 0.5
        )
        name = (
            "不确定或冲突认知"
            if uncertain
            else {"semantic": "稳定认知", "episodic": "相关历史事件", "focus": "当前关注"}.get(m.type, "稳定认知")
        )
        label = {"semantic": "事实", "episodic": "事件", "focus": "关注"}.get(m.type, m.type)
        bits = []
        for key, caption in [
            ("subject_name", "关于"),
            ("valid_from", "有效自"),
            ("valid_to", "有效至（不含）"),
            ("occurred_at", "发生于"),
        ]:
            value = getattr(m, key, None)
            if value:
                bits.append(f"{caption}：{value}")
        if getattr(m, "metadata_json", {}).get("legacy_uncalibrated"):
            bits.append("历史来源未校准")
        prefix = f"记忆 {m.id}；" if getattr(m, "id", None) else ""
        sections[name].append(
            f"- [{label}] {m.content}" + ("（" + prefix + "；".join(bits) + "）" if prefix or bits else "")
        )
    output = []
    for name, lines in sections.items():
        if not lines:
            continue
        note = (
            "\n以下信息存在推断、低可信或冲突，不得作为确定事实；不要静默选择一方。"
            if name == "不确定或冲突认知"
            else "\n仅提高相关场景关注权重，不代表已创建监控、提醒或后台任务。"
            if name == "当前关注"
            else ""
        )
        output.append("## " + name + note + "\n" + "\n".join(lines))
    return "\n\n".join(output)


async def retrieve(db, agent_id, query, *, top_k=None, at=None):
    started = time.monotonic()
    agent = await agent_access(db, agent_id)
    cfg = config(agent)
    a = actor_required()
    k = min(top_k or cfg.top_k, cfg.top_k, 10)
    words = terms(query)[:32]
    start, end, historical = time_window(query, at)
    trace = {
        "version": POLICY_VERSION,
        "agent_id": str(agent.id),
        "workspace_id": str(agent.workspace_id),
        "query_hash": __import__("hashlib").sha256(query.encode()).hexdigest(),
        "query_terms_count": len(words),
        "time": {"from": str(start), "to": str(end), "historical": historical},
        "top_k": k,
        "token_budget": cfg.token_budget,
        "token_estimator": "conservative_chars",
        "candidate_limit": cfg.candidate_limit,
        "candidates": [],
        "filter_counts": {},
        "selected_ids": [],
        "injected_ids": [],
    }
    last_trace.set(trace)
    if not words:
        trace["skip_reason"] = "no_relevance_signal"
        return RetrievalResult([], trace)
    lexical = sum(cast(Memory.search_terms.has_key(word), Integer) for word in words)
    match = Memory.search_terms.op("?|")(cast(words, ARRAY(Text)))
    from sqlalchemy.dialects.postgresql import JSONB

    metadata = cast(Memory.metadata_json, JSONB)
    eligible = [
        ~metadata.contains({"source_review_required": True}),
        ~metadata.contains({"content_purged": True}),
        or_(Memory.risk_level != "high", metadata.contains({"risk_approved": True})),
    ]
    if historical:
        eligible.append(
            or_(
                and_(Memory.type == "episodic", Memory.occurred_at >= start, Memory.occurred_at < end),
                and_(
                    Memory.type != "episodic",
                    or_(Memory.valid_from.is_not(None), Memory.valid_to.is_not(None)),
                    or_(Memory.valid_from.is_(None), Memory.valid_from < end),
                    or_(Memory.valid_to.is_(None), Memory.valid_to > start),
                ),
            )
        )
    else:
        eligible.extend(
            [
                Memory.status == "active",
                or_(Memory.valid_from.is_(None), Memory.valid_from <= start),
                or_(Memory.valid_to.is_(None), Memory.valid_to > start),
                or_(Memory.expires_at.is_(None), Memory.expires_at > start),
            ]
        )
    all_candidates = []
    # Category channels prevent focus/new events from consuming the whole candidate pool.
    share = max(1, cfg.candidate_limit // 3)
    for category in ("semantic", "episodic", "focus"):
        rows = await db.scalars(
            select(Memory)
            .where(
                Memory.workspace_id == agent.workspace_id,
                Memory.agent_id == agent.id,
                Memory.type == category,
                Memory.status.in_(["active", "superseded", "expired"]),
                match,
                *eligible,
            )
            .order_by(lexical.desc(), Memory.id)
            .limit(share)
        )
        all_candidates.extend(rows.all())
    scored = []
    counts = Counter()
    for m in all_candidates:
        reason = filter_reason(m, start, end, historical)
        if (
            m.subject_type == "user"
            and m.memory_kind == "preference"
            and m.subject_id != str(a.user_id)
            and not (m.subject_name and m.subject_name in query)
        ):
            reason = "different_user_subject"
        rel = relevance(words, m)
        if rel < cfg.relevance_threshold:
            reason = reason or "relevance"
        c = min(m.confidence, 0.5) if (m.metadata_json or {}).get("legacy_uncalibrated") else m.confidence
        subject = (
            1.0
            if (m.subject_name and m.subject_name in query)
            or (m.subject_type == "user" and m.subject_id == str(a.user_id))
            else 0.0
        )
        recency = max(0.0, 1.0 - abs((start - m.occurred_at).total_seconds()) / (86400 * 365)) if m.occurred_at else 0.0
        boost = cfg.focus_boost if m.type == "focus" and rel >= cfg.relevance_threshold else 0.0
        score = (
            0.6 * rel + 0.25 * c + 0.1 * subject + 0.05 * m.importance
            if m.type == "semantic"
            else 0.6 * rel + 0.15 * c + 0.15 * recency + 0.1 * m.importance
            if m.type == "episodic"
            else 0.6 * rel + 0.2 * subject + 0.1 * c + 0.1 * m.importance + boost
        )
        entry = {
            "memory_id": str(m.id),
            "category": m.type,
            "kind": m.memory_kind,
            "subject": m.subject_id or m.subject_name,
            "status": m.status,
            "source_mode": m.source_mode,
            "confidence": c,
            "importance": m.importance,
            "relevance": round(rel, 3),
            "focus_boost": boost,
            "final_score": round(score, 3),
            "conflict": m.has_conflict,
            "evidence_count": (m.metadata_json or {}).get("confidence_basis", {}).get("evidence_count"),
            "filter_reason": reason,
            "selected": False,
            "injected": False,
            "final_rank": None,
            "temporal": {
                "occurred_at": str(m.occurred_at) if m.occurred_at else None,
                "valid_from": str(m.valid_from) if m.valid_from else None,
                "valid_to": str(m.valid_to) if m.valid_to else None,
            },
        }
        if reason:
            counts[reason] += 1
        else:
            scored.append((score, m, entry))
        trace["candidates"].append(entry)
    scored.sort(key=lambda x: (-x[0], str(x[1].id)))
    chosen = []
    seen = set()
    for rank, (_, m, entry) in enumerate(scored, 1):
        entry["final_rank"] = rank
        if m.id in seen:
            continue
        bundle = [m]
        if m.has_conflict:
            ids = {m.id}
            frontier = {m.id}
            complete = True
            # Include the complete unresolved conflict component, or omit it altogether.
            while frontier and len(ids) <= k:
                rels = (
                    await db.scalars(
                        select(MemoryRelation).where(
                            MemoryRelation.relation_type == "conflicts_with",
                            or_(MemoryRelation.from_memory_id.in_(frontier), MemoryRelation.to_memory_id.in_(frontier)),
                        )
                    )
                ).all()
                linked = {x for r in rels for x in (r.from_memory_id, r.to_memory_id)} - ids
                if not linked:
                    break
                partners = (
                    await db.scalars(
                        select(Memory).where(
                            Memory.id.in_(linked),
                            Memory.agent_id == agent.id,
                            Memory.workspace_id == agent.workspace_id,
                        )
                    )
                ).all()
                if len(partners) != len(linked):
                    complete = False
                    break
                # Resolved historical edges remain auditable but do not join current conflicts.
                partners = [p for p in partners if p.has_conflict]
                if any(filter_reason(p, start, end, historical) for p in partners):
                    complete = False
                    break
                frontier = {p.id for p in partners}
                ids.update(frontier)
                bundle.extend(partners)
            if not complete or len(ids) > k:
                entry["filter_reason"] = "unavailable_or_oversized_conflict_bundle"
                counts[entry["filter_reason"]] += 1
                continue
        bundle = [x for x in bundle if x.id not in seen]
        entry["selected"] = True
        trace["selected_ids"].extend(str(x.id) for x in bundle)
        if len(chosen) + len(bundle) > k or token_estimate(format_context(chosen + bundle)) > cfg.token_budget:
            entry["filter_reason"] = "budget_or_conflict_bundle"
            counts["budget_or_conflict_bundle"] += 1
            continue
        chosen.extend(bundle)
        seen.update(x.id for x in bundle)
        if len(chosen) >= k:
            break
    for entry in trace["candidates"]:
        entry["injected"] = entry["memory_id"] in {str(x.id) for x in chosen}
    trace.update(
        injected_ids=[str(m.id) for m in chosen],
        candidate_count=len(all_candidates),
        candidates=sorted(trace["candidates"], key=lambda e: (not e["injected"], e["final_rank"] or 9999))[:50],
        filter_counts=dict(counts),
        estimated_tokens=token_estimate(format_context(chosen)) if chosen else 0,
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    if chosen:
        await db.execute(
            update(Memory)
            .where(
                Memory.id.in_([m.id for m in chosen]),
                Memory.agent_id == agent.id,
                Memory.workspace_id == agent.workspace_id,
            )
            .values(access_count=Memory.access_count + 1, last_accessed_at=now())
            .execution_options(synchronize_session=False)
        )
    return RetrievalResult(chosen, trace)
