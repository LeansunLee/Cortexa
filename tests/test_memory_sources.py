import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from cortexa.api import conversations, memory_sources
from cortexa.memory import access, evidence
from cortexa.runtime import store
from cortexa.runtime.adapters import CapabilityAdapter
from cortexa.runtime.capabilities import CapabilityDescriptor


def test_adapter_retains_memory_identity_without_copying_private_content():
    ident = uuid.uuid4()
    mem = SimpleNamespace(id=ident, subject_name="华东销售", content="PRIVATE_TEXT")
    adapter = CapabilityAdapter(CapabilityDescriptor(id="memory", workspace_id="ws", name="记忆", type="MEMORY"))
    ref = adapter.observe([mem], "action").evidence[0]
    assert ref["memory_id"] == str(ident)
    assert ref["name"] == "记忆 · 华东销售"
    assert "PRIVATE_TEXT" not in json.dumps(ref)


def test_history_restoration_uses_exact_action_and_count():
    metadata = {"steps": [{"tool": "a", "sources": [{"type": "memory"}, {"type": "memory"}]}]}
    snapshot = {
        "observations": [
            {
                "action_id": "a",
                "evidence": [
                    {"type": "memory", "memory_id": "1", "content": "PRIVATE"},
                    {"type": "memory", "memory_id": "2"},
                ],
            }
        ]
    }
    restored = memory_sources.restore_sources(metadata, snapshot)
    assert memory_sources.contains_memory(restored, "1")
    assert [s["name"] for s in restored["steps"][0]["sources"]] == ["记忆 1", "记忆 2"]
    assert "PRIVATE" not in json.dumps(restored)
    assert "memory_id" not in metadata["steps"][0]["sources"][0]
    snapshot["observations"][0]["action_id"] = "other"
    assert not memory_sources.contains_memory(memory_sources.restore_sources(metadata, snapshot), "1")
    snapshot["observations"][0]["action_id"] = "a"
    snapshot["observations"][0]["evidence"].pop()
    assert not memory_sources.contains_memory(memory_sources.restore_sources(metadata, snapshot), "1")


def endpoint_setup(monkeypatch, *, referenced=True):
    ident = uuid.uuid4()
    monkeypatch.setattr(store, "own_conversation", AsyncMock())
    monkeypatch.setattr(
        memory_sources,
        "restored_messages",
        AsyncMock(
            return_value=[(None, {"sources": [{"type": "memory", "memory_id": str(ident)}] if referenced else []})]
        ),
    )
    monkeypatch.setattr(memory_sources, "recalled_in_snapshot", AsyncMock(return_value=False))
    mem = SimpleNamespace(
        id=ident,
        content="销售记忆正文",
        type="semantic",
        subject_name="华东",
        status="active",
        confidence=0.8,
        source_mode="explicit",
        has_conflict=False,
        updated_at=None,
        metadata_json={},
        risk_level="low",
    )
    reader = AsyncMock(return_value=mem)
    monkeypatch.setattr(access, "memory_access", reader)
    monkeypatch.setattr(
        evidence, "visible_evidence", AsyncMock(return_value={"accessible": False, "label": "内部业务沟通"})
    )
    db = SimpleNamespace(scalars=AsyncMock(side_effect=[[], [SimpleNamespace()]]))
    return ident, mem, reader, db


def test_detail_requires_recalled_reference_and_live_memory_access(monkeypatch):
    ident, mem, reader, db = endpoint_setup(monkeypatch)
    result = asyncio.run(conversations.memory_source_detail(uuid.uuid4(), ident, db))
    data = json.loads(result.body)
    assert data["content"] == "销售记忆正文"
    assert result.headers["cache-control"] == "no-store"
    assert data["evidences"] == [{"accessible": False, "label": "内部业务沟通"}]
    reader.assert_awaited_once_with(db, ident)
    ident, _, reader, db = endpoint_setup(monkeypatch, referenced=False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(conversations.memory_source_detail(uuid.uuid4(), ident, db))
    assert error.value.status_code == 404
    reader.assert_not_awaited()


@pytest.mark.parametrize("state", ["purged", "archived", "retracted", "review", "high_risk", "permission"])
def test_unavailable_or_unauthorized_memory_does_not_return_content(monkeypatch, state):
    ident, mem, reader, db = endpoint_setup(monkeypatch)
    if state == "purged":
        mem.metadata_json = {"content_purged": True}
    elif state == "review":
        mem.metadata_json = {"source_review_required": True}
    elif state == "high_risk":
        mem.risk_level = "high"
    elif state == "permission":
        reader.side_effect = HTTPException(403, "无权使用该 Agent")
    else:
        mem.status = state
    with pytest.raises(HTTPException) as error:
        asyncio.run(conversations.memory_source_detail(uuid.uuid4(), ident, db))
    assert error.value.status_code == (403 if state == "permission" else 410)
    assert "销售记忆正文" not in str(error.value)


def test_real_database_source_history_and_agent_permissions(tmp_path, monkeypatch):
    from test_goal_collaboration import URL, setup

    if not URL:
        pytest.skip("Isolated PostgreSQL required")
    from cortexa.db.models import ConversationMessage, Memory
    from cortexa.security.access import actor_required

    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            ident = uuid.uuid4()
            async with ctx.store.sessions() as db:
                db.add(
                    Memory(
                        id=ident,
                        workspace_id=ctx.source.workspace_id,
                        agent_id=ctx.source.id,
                        content="仅授权销售记忆",
                        subject_name="华东销售",
                        risk_level="low",
                    )
                )
                await db.flush()
                db.add(
                    ConversationMessage(
                        id=uuid.uuid4(),
                        conversation_id=ctx.conv,
                        role="assistant",
                        content="已召回记忆",
                        metadata_json={
                            "steps": [
                                {
                                    "tool": "action",
                                    "sources": [{"type": "memory", "memory_id": str(ident), "name": "记忆 · 华东销售"}],
                                }
                            ]
                        },
                    )
                )
                await db.commit()
            async with ctx.store.sessions() as db:
                response = await conversations.memory_source_detail(ctx.conv, ident, db)
                assert json.loads(response.body)["content"] == "仅授权销售记忆"
                assert not actor_required().has("agent.operate")
                with pytest.raises(HTTPException) as error:
                    await conversations.memory_source_detail(uuid.uuid4(), ident, db)
                assert error.value.status_code == 404
            actor = actor_required()
            actor.memberships[ctx.source.workspace_id]["agent_ids"].remove(ctx.source.id)
            async with ctx.store.sessions() as db:
                with pytest.raises(HTTPException) as error:
                    await conversations.memory_source_detail(ctx.conv, ident, db)
                assert error.value.status_code in {403, 404}

    asyncio.run(scenario())
