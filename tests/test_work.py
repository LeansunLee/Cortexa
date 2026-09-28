"""Work contract tests plus real API integration in a disposable PostgreSQL schema."""

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from cortexa.work.schemas import WorkInput
from cortexa.work.service import permissions, transition
from cortexa.work.candidates import similar, Extraction
from cortexa.security.access import Actor, current_actor


def test_work_validation_and_conservative_dedup():
    with pytest.raises(ValidationError):
        WorkInput(title=" ", goal="目标", assignee_id=uuid.uuid4())
    with pytest.raises(ValidationError):
        WorkInput(title="调研", goal="目标", assignee_id=uuid.uuid4(), due_at="2026-09-20T10:00:00")
    assert similar("用户调研报告", "用户 调研报告！")
    assert not similar("用户调研", "完成接口开发")
    assert Extraction.model_validate({"works": []}).works == []


def test_assignee_cannot_review_even_as_creator_or_admin():
    uid, ws = uuid.uuid4(), uuid.uuid4()
    a = Actor(uid, "a", True, False, 1, memberships={ws: {"permissions": set()}}, workspace_id=ws)
    w = SimpleNamespace(assignee_type="human", assignee_id=uid, creator_id=uid, reviewer_id=uid, status="review")
    assert not permissions(w, a)["approve"]
    assert not permissions(w, a)["reject"]
    w.status = "completed"
    assert permissions(w, a)["log"]
    assert not any(value for key, value in permissions(w, a).items() if key != "log")


def test_rejection_requires_comment_and_returns_to_execution():
    uid, ws = uuid.uuid4(), uuid.uuid4()
    a = Actor(uid, "a", False, False, 1, memberships={ws: {"permissions": set()}}, workspace_id=ws)
    w = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=ws,
        assignee_type="human",
        assignee_id=uuid.uuid4(),
        creator_id=uid,
        reviewer_id=uid,
        status="review",
    )
    from unittest.mock import Mock

    db = SimpleNamespace(add=Mock(), flush=AsyncMock())
    token = current_actor.set(a)
    try:
        with pytest.raises(HTTPException):
            asyncio.run(transition(db, w, "reject", " "))
        asyncio.run(transition(db, w, "reject", "请补充数据"))
        assert w.status == "in_progress"
    finally:
        current_actor.reset(token)


def test_log_and_memory_validation():
    from cortexa.work.schemas import MemoryInput, WorkLogInput, WorkLogUpdate
    for kind in ("semantic", "episodic", "focus"):
        assert MemoryInput(agent_id=uuid.uuid4(), content="记忆", type=kind).type == kind
    for content in ("  ", "x" * 2001):
        with pytest.raises(ValidationError):
            WorkLogInput(content=content)
    with pytest.raises(ValidationError):
        WorkLogUpdate(content="修改", version=0)


def test_log_edit_authorization_conflict_and_audit(monkeypatch):
    from unittest.mock import Mock
    from cortexa.api import works as api
    from cortexa.work import service
    from cortexa.work.schemas import WorkLogInput, WorkLogUpdate
    from cortexa.work.models import WorkActivity
    uid, other, ws, wid = (uuid.uuid4() for _ in range(4))
    a = Actor(uid, "author", False, False, 1, memberships={ws: {"permissions": set()}}, workspace_id=ws)
    w = SimpleNamespace(id=wid, workspace_id=ws, assignee_type="human", assignee_id=uid,
                        creator_id=other, reviewer_id=other, status="completed")
    row = WorkActivity(id=uuid.uuid4(), work_id=wid, workspace_id=ws, actor_id=uid,
                       action="log", data_json={"content": "原内容", "version": 1})
    db = SimpleNamespace(add=Mock(), flush=AsyncMock(), execute=AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: row)))
    get = AsyncMock(return_value=w)
    audit = AsyncMock()
    monkeypatch.setattr(service, "get_work", get)
    monkeypatch.setattr(service, "event", audit)
    token = current_actor.set(a)
    try:
        asyncio.run(api.create_log(wid, WorkLogInput(content="完成调研"), db))
        assert db.add.call_args.args[0].action == "log"
        assert db.add.call_args.args[0].data_json["content"] == "完成调研"
        payload = WorkLogUpdate(content="更新内容", version=1)
        asyncio.run(api.edit_log(wid, row.id, payload, db))
        get.assert_awaited_with(db, wid, True)
        assert row.data_json["content"] == "更新内容" and row.data_json["version"] == 2
        assert audit.call_args.args[3]["before"] == "原内容"
        with pytest.raises(HTTPException) as conflict:
            asyncio.run(api.edit_log(wid, row.id, payload, db))
        assert conflict.value.status_code == 409
        row.actor_id = other
        with pytest.raises(HTTPException) as forbidden:
            asyncio.run(api.edit_log(wid, row.id, WorkLogUpdate(content="越权", version=2), db))
        assert forbidden.value.status_code == 403
        db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
        with pytest.raises(HTTPException) as missing:
            asyncio.run(api.edit_log(wid, uuid.uuid4(), payload, db))
        assert missing.value.status_code == 404
    finally:
        current_actor.reset(token)


@pytest.mark.skipif(not os.getenv("WORK_TEST_DATABASE_URL"), reason="Disposable PostgreSQL URL not configured")
def test_work_api_closed_loop(tmp_path, monkeypatch):
    asyncio.run(integration(tmp_path, monkeypatch))


async def integration(tmp_path, monkeypatch):
    import sys
    import httpx
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text, select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from cortexa.web.app import app
    from cortexa.db.engine import Base
    from cortexa.db import models as m
    from cortexa.security import models as sm
    from cortexa.security.http import COOKIE
    from cortexa.security.passwords import token_digest
    from cortexa.work import service
    from cortexa.data import doc_storage, document_preview
    from cortexa.api import knowledge
    from cortexa.config import llm_providers
    from cortexa.work.models import WorkCandidate
    from cortexa.api.deps import get_db

    schema = "work_test_" + uuid.uuid4().hex
    base = create_async_engine(os.environ["WORK_TEST_DATABASE_URL"])
    async with base.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(
        os.environ["WORK_TEST_DATABASE_URL"], connect_args={"server_settings": {"search_path": schema}}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service, "STORAGE", tmp_path / "works")
    monkeypatch.setattr(doc_storage, "DOC_STORAGE_DIR", str(tmp_path / "documents"))
    monkeypatch.setattr(document_preview, "DOC_STORAGE_DIR", str(tmp_path / "documents"))
    monkeypatch.setattr(knowledge, "_safe_index", AsyncMock())
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("cortexa.") and hasattr(mod, "async_session_factory"):
            monkeypatch.setattr(mod, "async_session_factory", factory)

    async def db_dependency():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = db_dependency
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            ws = m.Workspace(name="Work test")
            other_ws = m.Workspace(name="Other test")
            role = sm.Role(
                code="work_test_member",
                name="Test",
                scope="workspace",
                permissions=["agent.use", "memory.manage", "knowledge.manage"],
            )
            db.add_all([ws, other_ws, role])
            await db.flush()
            people = []
            tokens = []
            for name in ["alice", "bob", "eve"]:
                user = sm.User(username=name, display_name=name, must_change_password=False, status="active")
                db.add(user)
                await db.flush()
                member = sm.Membership(user_id=user.id, workspace_id=ws.id, all_agents=True)
                db.add(member)
                await db.flush()
                db.add(sm.MemberRole(member_id=member.id, role_id=role.id))
                token = uuid.uuid4().hex
                db.add(
                    sm.LoginSession(
                        token_hash=token_digest(token),
                        user_id=user.id,
                        auth_version=1,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    )
                )
                tokens.append(token)
                people.append(user)
            agent = m.Agent(workspace_id=ws.id, name="Research", status="active", model="test")
            kb = m.KnowledgeBase(workspace_id=ws.id, name="Work results")
            db.add_all([agent, kb])
            await db.flush()
            conv = m.Conversation(workspace_id=ws.id, agent_id=agent.id, owner_user_id=people[0].id, title="研究计划")
            db.add(conv)
            await db.flush()
            msg = m.ConversationMessage(
                conversation_id=conv.id, role="assistant", content="请完成人群调研，形成调研报告。"
            )
            db.add(msg)
            await db.commit()
        transport = httpx.ASGITransport(app=app)
        clients = [
            httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={COOKIE: t},
                headers={"X-Workspace-Id": str(ws.id), "X-Requested-With": "Cortexa"},
            )
            for t in tokens
        ]
        a, b, c = clients

        async def call(client, method, url, expected=200, **kwargs):
            res = await client.request(method, url, **kwargs)
            assert res.status_code == expected, (method, url, res.status_code, res.text[:1000])
            return res.json() if res.content else None

        payload = {
            "title": "竞品分析",
            "goal": "明确主要五款竞品价格策略",
            "assignee_id": str(people[1].id),
            "deliverable_requirement": "提交分析报告",
        }
        w = await call(a, "POST", "/api/works", 201, json=payload)
        wid = w["id"]
        url = f"/api/works/{wid}"
        assert w["status"] == "todo"
        assert len(await call(b, "GET", "/api/works")) == 1
        assert not await call(c, "GET", "/api/works?view=all")
        for suffix in ["", "/deliverables", "/activities"]:
            await call(c, "GET", url + suffix, 404)
        await call(c, "POST", url + "/logs", 404, json={"content": "越权日志"})
        await call(b, "POST", url + "/logs", 422, json={"content": " "})
        log = await call(b, "POST", url + "/logs", 201, json={"content": "已启动价格调研"})
        log_url = url + "/logs/" + log["id"]
        await call(a, "PATCH", log_url, 403, json={"content": "修改他人日志", "version": 1})
        await call(b, "PATCH", log_url, json={"content": "已完成第一轮调研", "version": 1})
        await call(b, "PATCH", log_url, 409, json={"content": "旧版本覆盖", "version": 1})
        saved_log = next(e for e in await call(b, "GET", url + "/activities") if e["id"] == log["id"])
        assert saved_log["data_json"]["content"] == "已完成第一轮调研" and saved_log["can_edit"]
        assert any(e["action"] == "log_edited" for e in await call(b, "GET", url + "/activities"))
        await call(a, "POST", "/api/works", 422, json={**payload, "reviewer_id": str(people[1].id)})
        await call(a, "POST", url + "/start", 403)
        await call(b, "PATCH", url, 403, json=payload)
        await call(b, "POST", url + "/start")
        await call(b, "POST", url + "/start", 403)
        await call(a, "PATCH", url, 403, json=payload)
        await call(b, "POST", url + "/submit", 422, data={"content": " "})
        await call(
            b,
            "POST",
            url + "/submit",
            data={"content": "已完成五款分析"},
            files={"file": ("竞品.txt", b"competitor price 100", "text/plain")},
        )
        await call(b, "POST", url + "/approve", 403, json={})
        await call(a, "POST", url + "/reject", 422, json={"comment": " "})
        ds = await call(a, "GET", url + "/deliverables")
        file_d = next(d for d in ds if d["type"] == "file")
        file_url = url + f"/deliverables/{file_d['id']}"
        await call(c, "GET", file_url + "/download", 404)
        res = await b.get(file_url + "/download")
        assert res.content == b"competitor price 100"
        await call(a, "POST", file_url + "/knowledge", 403, json={"knowledge_base_id": str(kb.id)})
        await call(a, "POST", url + "/memory", 403, json={"agent_id": str(agent.id), "content": "结论"})
        await call(a, "POST", url + "/reject", json={"comment": "请补充价格策略分析"})
        assert (await call(b, "GET", url))["status"] == "in_progress"
        await call(b, "POST", url + "/submit", data={"content": "已补充价格策略"})
        done = await call(a, "POST", url + "/approve", json={"comment": "通过"})
        assert done["status"] == "completed" and done["completed_at"]
        await call(a, "PATCH", url, 403, json=payload)
        await call(a, "POST", url + "/cancel", 403, json={})
        saved = await call(a, "POST", file_url + "/knowledge", json={"knowledge_base_id": str(kb.id)})
        repeated = await call(a, "POST", file_url + "/knowledge", json={"knowledge_base_id": str(kb.id)})
        assert saved["document_id"] == repeated["document_id"] and repeated["existing"]
        assert knowledge._safe_index.await_count == 1
        mem = await call(
            a,
            "POST",
            url + "/memory",
            json={"agent_id": str(agent.id), "content": "主要竞品价格集中在100元", "type": "semantic"},
        )
        assert mem["memory_id"] and mem["outcome"] in {"created","candidate","merged"}
        await call(a,"GET","/api/memories",403)
        for kind in ("episodic", "focus"):
            body = {"agent_id": str(agent.id), "content": "持续关注竞品变化" + kind, "type": kind}
            first = await call(a, "POST", url + "/memory", json=body)
            repeated = await call(a, "POST", url + "/memory", json=body)
            assert first["memory_id"] == repeated["memory_id"] and repeated["existing"]
        assert len([e for e in await call(a, "GET", url + "/activities") if e["action"] == "memory"]) == 3
        # Extraction and confirmation, then duplicate suppression across messages.
        model = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=SimpleNamespace(
                    content='{"works":[{"title":"年轻用户调研","goal":"验证年轻用户需求","deliverableRequirement":"形成用户调研报告","confidence":0.95}]}'
                )
            )
        )
        monkeypatch.setattr(llm_providers, "create_llm", lambda *_: model)
        cs = await call(
            a, "POST", f"/api/conversations/{conv.id}/work-candidates/extract", json={"message_id": str(msg.id)}
        )
        assert len(cs) == 1
        await call(c, "POST", f"/api/work-candidates/{cs[0]['id']}/accept", 404, json=payload)
        proposed = {**payload, "title": cs[0]["title"], "goal": cs[0]["goal"]}
        candidate_url = f"/api/work-candidates/{cs[0]['id']}/accept"
        accepted = await call(a, "POST", candidate_url, json=proposed)
        assert accepted["source_message_id"] == str(msg.id) and accepted["can_view_source"]
        assert not (await call(b, "GET", "/api/works/" + accepted["id"]))["can_view_source"]
        assert (await call(a, "POST", candidate_url, json=proposed))["id"] == accepted["id"]
        await call(a, "POST", f"/api/conversations/{conv.id}/work-candidates/extract", json={"message_id": str(msg.id)})
        assert model.ainvoke.await_count == 1
        async with factory() as db:
            second = m.ConversationMessage(conversation_id=conv.id, role="assistant", content="请完成相同调研")
            db.add(second)
            await db.commit()
        cs = await call(
            a, "POST", f"/api/conversations/{conv.id}/work-candidates/extract", json={"message_id": str(second.id)}
        )
        assert len(cs) == 1
        ev = await call(a, "GET", url + "/activities")
        assert {"created", "dispatched", "started", "submitted", "rejected", "approved", "knowledge", "memory"} <= {
            x["action"] for x in ev
        }
        await call(a, "GET", url, 403, headers={"X-Workspace-Id": str(other_ws.id)})
        # Work survives source deletion, without granting participants access to private chat.
        await call(a, "DELETE", f"/api/conversations/{conv.id}", 204)
        assert (await call(b, "GET", "/api/works/" + accepted["id"]))["source_excerpt"]
        for client in clients:
            await client.aclose()
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
        async with base.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await base.dispose()
