"""Memory governance regressions on a disposable schema in the configured development DB."""

import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from agentdevstu.db.engine import Base
from agentdevstu.db.models import Agent, Workspace, Memory, Conversation, ConversationMessage
from agentdevstu.security.models import User
from agentdevstu.security.access import Actor, current_actor
from agentdevstu.security import isolation  # noqa: F401
from agentdevstu.memory.governance import ingest, correct
from agentdevstu.memory.schemas import Candidate, Correction
from agentdevstu.memory.evidence import Source, visible_evidence
from agentdevstu.memory.models import MemoryEvidence, MemoryIssue
from agentdevstu.memory.retrieval import retrieve
from agentdevstu.memory.lifecycle import source_deleted
from agentdevstu.api.memories import Resolution, resolve_issue


def date(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.skipif(not os.getenv("MEMORY_TEST_DATABASE_URL"), reason="PostgreSQL test URL required")
def test_governance_shared_temporal_privacy(monkeypatch):
    asyncio.run(scenario(monkeypatch))


async def scenario(monkeypatch):
    url = os.environ["MEMORY_TEST_DATABASE_URL"]
    schema = "memory2_test_" + uuid.uuid4().hex
    root = create_async_engine(url)
    async with root.begin() as c:
        await c.execute(text("CREATE SCHEMA " + schema))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    context = None
    try:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with factory() as db:
            w = Workspace(name="Memory test")
            w2 = Workspace(name="Other")
            a = User(username="alice", display_name="Alice", password_hash="unused")
            b = User(username="bob", display_name="Bob", password_hash="unused")
            db.add_all([w, w2, a, b])
            await db.flush()
            agent = Agent(
                workspace_id=w.id,
                name="Sales",
                status="active",
                memory_config={"memory2": {"semantic_judgment": False}},
            )
            other = Agent(workspace_id=w.id, name="Other", status="active")
            foreign = Agent(workspace_id=w2.id, name="Foreign", status="active")
            db.add_all([agent, other, foreign])
            await db.flush()
            conv = Conversation(workspace_id=w.id, agent_id=agent.id, owner_user_id=a.id, title="Private source")
            db.add(conv)
            await db.flush()
            msg = ConversationMessage(conversation_id=conv.id, role="user", content="上海库存延迟一天")
            db.add(msg)
            await db.commit()

        def actor(user, manage=True):
            permissions = {"agent.use"} | ({"agent.operate", "workspace.manage"} if manage else set())
            return Actor(
                user.id,
                user.username,
                False,
                False,
                1,
                workspace_id=w.id,
                memberships={w.id: {"permissions": permissions, "agent_ids": {agent.id}, "all_agents": False}},
            )

        context = current_actor.set(actor(a))
        async with factory() as db:
            source = Source("conversation", str(conv.id), sub_type="message", sub_id=str(msg.id), user_id=a.id)
            cognition = await ingest(
                db,
                agent.id,
                Candidate(content=msg.content, source_mode="explicit", importance=0.7),
                source,
                use_model=False,
            )
            cid = cognition.id
            await db.commit()
        current_actor.set(actor(b, False))
        async with factory() as db:
            result = await retrieve(db, agent.id, "上海库存延迟")
            assert cid in {m.id for m in result.memories}, "Agent cognition must be shared"
            e = await db.scalar(select(MemoryEvidence).where(MemoryEvidence.memory_id == cid))
            visible = await visible_evidence(db, e)
            assert not visible["accessible"] and "source_id" not in visible and "summary" not in visible
            from agentdevstu.memory.access import memory_access

            with pytest.raises(HTTPException) as denied:
                await memory_access(db, cid, manage=True)
            assert denied.value.status_code == 403
            for forbidden in (other, foreign):
                with pytest.raises(HTTPException):
                    await retrieve(db, forbidden.id, "库存")
        current_actor.set(actor(a))
        async with factory() as db:
            duplicate = await ingest(
                db,
                agent.id,
                Candidate(content=msg.content, source_mode="explicit", importance=0.7),
                Source("manual", str(uuid.uuid4()), user_id=a.id),
                use_model=False,
            )
            assert duplicate.id == cid and duplicate.governance_outcome == "merged"
            old = await ingest(
                db,
                agent.id,
                Candidate(
                    content="张三负责华东区域",
                    memory_kind="relationship",
                    claim_key="east:owner",
                    source_mode="explicit",
                    valid_from=date("2025-01-01"),
                ),
                Source("manual", "old-fact", user_id=a.id),
                use_model=False,
            )
            old_id = old.id
            new = await ingest(
                db,
                agent.id,
                Candidate(
                    content="李四负责华东区域",
                    memory_kind="relationship",
                    claim_key="east:owner",
                    source_mode="explicit",
                    valid_from=date("2026-09-01"),
                ),
                Source("manual", "new-fact", user_id=a.id),
                use_model=False,
            )
            new_id = new.id
            assert old.status == "superseded" and old.valid_to == date("2026-09-01")
            historical = await retrieve(db, agent.id, "去年华东负责人", at=date("2026-09-19"))
            current = await retrieve(db, agent.id, "现在华东负责人", at=date("2026-09-19"))
            assert old_id in {m.id for m in historical.memories}
            assert new_id in {m.id for m in current.memories} and old_id not in {m.id for m in current.memories}
            await db.commit()
        async with factory() as db:
            new = await db.get(Memory, new_id)
            replacement = await correct(
                db,
                new,
                Correction(
                    new_content="王五负责华东区域",
                    reason="核实更正",
                    expected_revision=new.revision,
                    idempotency_key="correction-one",
                ),
            )
            assert new.status == "retracted" and replacement.status == "active"
            await db.commit()
        async with factory() as db:
            left = await ingest(
                db,
                agent.id,
                Candidate(content="渠道价格为100元", claim_key="price", source_mode="explicit"),
                Source("manual", "price-a", user_id=a.id),
                use_model=False,
            )
            right = await ingest(
                db,
                agent.id,
                Candidate(content="渠道价格为200元", claim_key="price", source_mode="explicit"),
                Source("manual", "price-b", user_id=a.id),
                use_model=False,
            )
            assert left.has_conflict and right.has_conflict
            conflict = await db.scalar(
                select(MemoryIssue).where(MemoryIssue.issue_type == "conflict", MemoryIssue.memory_id == right.id)
            )
            out = await retrieve(db, agent.id, "渠道价格", top_k=1)
            assert not out.memories, "Top N must not silently choose one conflict side"
            await resolve_issue(
                db,
                agent.id,
                conflict.id,
                Resolution(
                    action="neither",
                    reason="两者都错误",
                    revisions={str(left.id): left.revision, str(right.id): right.revision},
                ),
            )
            assert left.status == right.status == "retracted"
            await db.commit()
        async with factory() as db:
            await source_deleted(db, "conversation", conv.id, message_id=msg.id)
            await db.commit()
        async with factory() as db:
            retained = await db.get(Memory, cid)
            assert retained.metadata_json["source_review_required"] and not retained.metadata_json.get("content_purged")
            assert not (await retrieve(db, agent.id, "上海库存延迟")).memories
        # A correction retires its old conflict issue, without retaining false partner flags.
        async with factory() as db:
            first = await ingest(
                db,
                agent.id,
                Candidate(content="年度预算100万元", claim_key="budget", source_mode="explicit"),
                Source("manual", "budget-a", user_id=a.id),
                use_model=False,
            )
            second = await ingest(
                db,
                agent.id,
                Candidate(content="年度预算200万元", claim_key="budget", source_mode="explicit"),
                Source("manual", "budget-b", user_id=a.id),
                use_model=False,
            )
            assert first.has_conflict and second.has_conflict
            await correct(
                db,
                second,
                Correction(reason="核验后撤回", expected_revision=second.revision, idempotency_key="budget-correct"),
            )
            assert not first.has_conflict and second.status == "retracted"
            await db.commit()
        # Source changes during model processing must never be attributed to an old revision.
        async with factory() as db:
            from agentdevstu.memory.evidence import validate_source
            from agentdevstu.memory.policy import digest

            stale = Source(
                "conversation", str(conv.id), sub_type="message", sub_id=str(msg.id), revision=digest("旧的文本")
            )
            assert not await validate_source(db, stale)

        # Simultaneous identical intake converges to one canonical cognition.
        async def concurrent_intake():
            async with factory() as db:
                result = await ingest(
                    db,
                    agent.id,
                    Candidate(content="并发测试供应链周期为七天", source_mode="explicit"),
                    Source("manual", "concurrent-source", user_id=a.id),
                    use_model=False,
                    intake_key="concurrent-intake-key",
                )
                await db.commit()
                return result.id

        results = await asyncio.gather(concurrent_intake(), concurrent_intake())
        assert results[0] == results[1]
        async with factory() as db:
            with pytest.raises(HTTPException) as mismatch:
                await ingest(
                    db,
                    agent.id,
                    Candidate(content="完全不同的内容", source_mode="explicit"),
                    Source("manual", "concurrent-source", user_id=a.id),
                    use_model=False,
                    intake_key="concurrent-intake-key",
                )
            assert mismatch.value.status_code == 409
        # Importance cannot bypass relevance, even with a large corpus.
        async with factory() as db:
            from agentdevstu.memory.policy import terms

            db.add_all(
                [
                    Memory(
                        workspace_id=w.id,
                        agent_id=agent.id,
                        type="semantic",
                        content=f"烹饪菜谱资料{i}",
                        status="active",
                        importance=1,
                        confidence=0.9,
                        search_terms=terms("烹饪菜谱资料"),
                        metadata_json={},
                    )
                    for i in range(1000)
                ]
            )
            await db.commit()
            result = await retrieve(db, agent.id, "并发测试供应链周期", top_k=2)
            assert len(result.memories) <= 2
            assert results[0] in {m.id for m in result.memories}
            assert all("烹饪" not in m.content for m in result.memories)
        current_actor.set(None)
        async with factory() as db:
            assert not (await db.scalars(select(Memory))).all(), "No Actor must fail closed"
    finally:
        if context is not None:
            current_actor.reset(context)
        await engine.dispose()
        async with root.begin() as c:
            await c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        await root.dispose()


def test_correction_invalid_period():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Correction(
            reason="错误区间",
            expected_revision=1,
            idempotency_key="invalid-period",
            valid_from=date("2026-09-02"),
            valid_to=date("2026-09-01"),
        )
