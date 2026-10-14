"""Actual PostgreSQL/Goal integration; no production schema or model calls."""

import asyncio
import uuid

import pytest
from test_goal_collaboration import URL, setup, start
from test_goal_loop import FakeModel, tool_call

from cortexa.api import conversations, goals
from cortexa.db.models import Document, DocumentChunk, KnowledgeBase
from cortexa.rag.bm25_search import bm25_retrieve
from cortexa.rag.retriever import retrieve_relevant_chunks


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_real_bm25_metadata_and_runtime_trace_scope(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            meta = {
                "retrieval": {
                    "entities": [{"id": "M-250", "name": "金吉拉250", "aliases": ["J250"]}],
                    "intents": ["clearance"],
                    "document_type": "case",
                    "case_status": "completed",
                }
            }
            kb = KnowledgeBase(
                id=uuid.uuid4(), workspace_id=ctx.source.workspace_id, agent_id=ctx.source.id, name="测试授权资料"
            )
            target = Document(
                id=uuid.uuid4(), knowledge_base_id=kb.id, name="区域执行记录", content="132", metadata_json=meta
            )
            variant = Document(
                id=uuid.uuid4(),
                knowledge_base_id=kb.id,
                name="金吉拉250CVT清库复盘",
                content="已完成清库活动，售出300台",
            )
            unrelated = Document(
                id=uuid.uuid4(), knowledge_base_id=kb.id, name="公司介绍", content="金吉拉250库存清库活动营销政策"
            )
            hidden_kb = KnowledgeBase(
                id=uuid.uuid4(),
                workspace_id=ctx.source.workspace_id,
                agent_id=ctx.targets[1].id,
                name="未授权的其他Agent资料",
            )
            hidden = Document(
                id=uuid.uuid4(),
                knowledge_base_id=hidden_kb.id,
                name="金吉拉250清库复盘秘密",
                content="已执行清库活动，售出900台",
            )
            async with ctx.store.sessions() as db:
                db.add_all([kb, hidden_kb])
                await db.flush()
                db.add_all([target, variant, unrelated, hidden])
                await db.flush()
                db.add_all(
                    [
                        DocumentChunk(
                            id=uuid.uuid4(),
                            document_id=d.id,
                            knowledge_base_id=d.knowledge_base_id,
                            chunk_index=0,
                            content=d.content,
                        )
                        for d in [target, variant, unrelated, hidden]
                    ]
                )
                await db.commit()
            async with ctx.store.sessions() as db:
                results = await bm25_retrieve(db, [str(kb.id)], "model_id:M-250 清库案例", min_score=999)
                assert [r.document_id for r in results] == [target.id]
                assert results[0].score == 0 and results[0].metadata["evidence_grade"] == "DIRECT"
                rag = await retrieve_relevant_chunks(db, [str(kb.id)], "model_id:M-250 清库案例", top_k=10)
                assert [r.document_id for r in rag] == [target.id]
            from cortexa.runtime import bindings

            monkeypatch.setattr(bindings, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(goals, "prepare_bindings", bindings.prepare_bindings)

            class Model(FakeModel):
                async def astream(self, messages):
                    if self.calls:
                        import json

                        ident = json.loads(next(m.content for m in reversed(messages) if m.type == "tool"))[
                            "observation_id"
                        ]
                        self.calls.append(messages)
                        yield tool_call(
                            name="complete_task",
                            args={
                                "answer": "已根据已完成案例记录说明132",
                                "requirements": [
                                    {
                                        "requirement": "案例依据",
                                        "kind": "policy",
                                        "observation_ids": [ident],
                                        "satisfied": True,
                                    }
                                ],
                            },
                        )
                    else:
                        async for chunk in super().astream(messages):
                            yield chunk

            model = Model([[tool_call(name="knowledge_retrieve", args={"query": "J250 清库案例"})]])
            monkeypatch.setattr(goals, "create_llm", lambda *_: model)
            done = await start(ctx, "evidence-runtime", "查询J250清库案例")
            assert done["status"] == "COMPLETE", done
            row = await ctx.store.get(ctx.conv, uuid.UUID(done["goal_id"]))
            snapshot = ctx.store.files.read(row.id, row.artifacts["snapshot"])
            observation = next(o for o in snapshot["observations"] if o["source_type"] == "KNOWLEDGE")
            trace = observation["metadata"]["retrieval_trace"]
            assert trace["query_analysis"]["entities"][0]["id"] == "M-250"
            assert all(c["name"] != hidden.name for c in trace["ranking"])
            assert trace["injected_ids"] == [str(target.id)]
            async with ctx.store.sessions() as db:
                from cortexa.db.models import ConversationMessage

                reply = await db.get(ConversationMessage, uuid.UUID(row.state["result_message_id"]))
                entry = next(
                    e for e in reply.metadata_json["debug_trace"] if e["title"] == "Knowledge retrieval relevance"
                )
                assert "injected_context" in entry["detail"] and "ranking" in entry["detail"]
                assert "DIRECT" in entry["detail"]["injected_context"]
                assert hidden.name not in str(entry["detail"])
            # Existing read policy must keep diagnostic content out of normal
            # history responses for a viewer without debug permission.
            monkeypatch.setattr(conversations, "can_read_goal_trace", lambda: False)
            async with ctx.store.sessions() as db:
                visible = await conversations.list_messages(ctx.conv, db)
                assert all("debug_trace" not in (m.metadata_json or {}) for m in visible)

    asyncio.run(scenario())
