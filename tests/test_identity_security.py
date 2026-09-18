"""Authorization regressions; integration uses a disposable PostgreSQL schema only."""

import asyncio
import os
import uuid
import pytest
from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
from agentdevstu.security.passwords import hash_password, verify_password
from agentdevstu.security.access import Actor
from types import SimpleNamespace


def test_password_storage_and_validation():
    value = hash_password("LongEnough-Test123")
    assert "LongEnough" not in value
    assert verify_password("LongEnough-Test123", value)
    assert not verify_password("wrong", value)
    with pytest.raises(HTTPException):
        hash_password("weak")


@pytest.mark.parametrize("password", ["12345678", "abcdefgh", "!!!!!!!!", "a" * 128])
def test_password_accepts_eight_or_more_without_composition_rules(password):
    encoded = hash_password(password)
    assert verify_password(password, encoded)


@pytest.mark.parametrize("password", ["", "1234567", "abcdefg", "a" * 129])
def test_password_rejects_outside_length_limits(password):
    with pytest.raises(HTTPException) as exc:
        hash_password(password)
    assert exc.value.status_code == 422


def test_agent_access_requires_membership_role_grant_and_publication():
    ws, other, ident = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor = Actor(uuid.uuid4(), "test", False, False, 1, workspace_id=ws)
    agent = SimpleNamespace(id=ident, workspace_id=ws, status="active")
    assert not actor.can_use(agent)
    actor.memberships[ws] = {"permissions": {"agent.use"}, "all_agents": False, "agent_ids": set()}
    assert not actor.can_use(agent)
    actor.memberships[ws]["agent_ids"].add(ident)
    assert actor.can_use(agent)
    agent.status = "draft"
    assert not actor.can_use(agent)
    agent.status, agent.workspace_id = "active", other
    assert not actor.can_use(agent)
    actor.superadmin = True
    assert not actor.can_use(agent)


@pytest.mark.skipif(
    not os.getenv("AUTH_TEST_DATABASE_URL"), reason="Disposable PostgreSQL integration URL not configured"
)
def test_auth_api_integration():
    asyncio.run(run_integration())


async def run_integration():
    import sys
    import httpx
    from sqlalchemy import text, select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from agentdevstu.web.app import app
    from agentdevstu.db.engine import Base
    from agentdevstu.db import models as m
    from agentdevstu.security import models as sm

    schema = "identity_test_" + uuid.uuid4().hex
    base_engine = create_async_engine(os.environ["AUTH_TEST_DATABASE_URL"])
    async with base_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
    test_engine = create_async_engine(
        os.environ["AUTH_TEST_DATABASE_URL"], connect_args={"server_settings": {"search_path": schema}}
    )
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    original = []
    upload = None
    from pathlib import Path

    # All runtime paths, including SSE and collaboration, must use the isolated test DB.
    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("agentdevstu.") and hasattr(module, "async_session_factory"):
            original.append((module, module.async_session_factory))
            module.async_session_factory = factory
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(lambda sync: Base.metadata.create_all(sync, checkfirst=False))
        # Exercise the actual migration twice in the isolated schema, including DB grant triggers.
        import importlib.util

        spec = importlib.util.spec_from_file_location("identity_migration_test", "scripts/migrate_identity.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.engine, migration.async_session_factory = test_engine, factory
        await migration.migrate()
        await migration.migrate()
        async with factory() as db:
            admin = sm.User(
                username="admin",
                display_name="Admin",
                password_hash=hash_password("Admin-Test-12345"),
                is_superadmin=True,
                must_change_password=False,
            )
            a = sm.User(
                username="alice",
                display_name="Alice",
                password_hash=hash_password("Alice-Test-12345"),
                must_change_password=False,
            )
            b = sm.User(
                username="bob",
                display_name="Bob",
                password_hash=hash_password("Bob-Test-12345"),
                must_change_password=False,
            )
            db.add_all([admin, a, b])
            await db.flush()
            w1, w2 = m.Workspace(name="One"), m.Workspace(name="Two")
            db.add_all([w1, w2])
            await db.flush()
            ag1 = m.Agent(workspace_id=w1.id, name="Allowed", status="active")
            ag2 = m.Agent(workspace_id=w1.id, name="Not granted", status="active")
            ag3 = m.Agent(workspace_id=w2.id, name="Other space", status="active")
            db.add_all([ag1, ag2, ag3])
            await db.flush()
            for user in [admin, a, b]:
                member = sm.Membership(user_id=user.id, workspace_id=w1.id, all_agents=user == admin)
                db.add(member)
                await db.flush()
                role = await db.scalar(
                    select(sm.Role).where(sm.Role.code == ("space_admin" if user == admin else "member"))
                )
                db.add(sm.MemberRole(member_id=member.id, role_id=role.id))
                if user != admin:
                    db.add(sm.AgentGrant(member_id=member.id, agent_id=ag1.id))
            role = await db.scalar(select(sm.Role).where(sm.Role.code == "space_admin"))
            admin_m2 = sm.Membership(user_id=admin.id, workspace_id=w2.id, all_agents=True)
            db.add(admin_m2)
            await db.flush()
            db.add(sm.MemberRole(member_id=admin_m2.id, role_id=role.id))
            private = m.Conversation(workspace_id=w1.id, agent_id=ag1.id, title="Bob private", owner_user_id=b.id)
            legacy = m.Conversation(workspace_id=w1.id, agent_id=ag1.id, title="Legacy unowned")
            db.add_all([private, legacy])
            await db.flush()
            db.add(m.ConversationMessage(conversation_id=private.id, role="user", content="PRIVATE"))
            db.add(m.Memory(workspace_id=w1.id, agent_id=ag1.id, content="Bob secret", owner_user_id=b.id))
            await db.commit()
        headers = {"X-Requested-With": "AgentDevStu", "X-Workspace-Id": str(w1.id)}
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
            assert (await client.get("/api/workspaces")).status_code == 401
            assert (
                await client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
            ).status_code == 401
            response = await client.post("/api/auth/login", json={"username": "alice", "password": "Alice-Test-12345"})
            assert response.status_code == 200, response.text
            assert "HttpOnly" in response.headers["set-cookie"]
            alice_cookie = client.cookies.get("agentdevstu_session")
            response = await client.get("/api/workspaces")
            assert response.status_code == 200, response.text
            assert [w["id"] for w in response.json()] == [str(w1.id)]
            assert (await client.get("/api/agents")).status_code == 403
            assert (await client.get("/api/config")).status_code == 403
            cards = (await client.get("/api/auth/agents")).json()
            assert [i["id"] for i in cards] == [str(ag1.id)], cards
            assert "system_prompt" not in cards[0] and "proxy_config" not in cards[0]
            assert (await client.get("/api/auth/agents", headers={"X-Workspace-Id": str(w2.id)})).status_code == 403
            assert (await client.post("/api/conversations", json={"agent_id": str(ag2.id)})).status_code == 403
            assert (await client.post("/api/conversations", json={"agent_id": str(ag3.id)})).status_code == 403
            assert (await client.get(f"/api/conversations/{private.id}/messages")).status_code == 404
            assert (await client.get(f"/api/conversations/{legacy.id}")).status_code == 404
            assert (await client.get("/api/memories")).json() == []
            response = await client.post("/api/conversations", json={"agent_id": str(ag1.id), "title": "Alice own"})
            assert response.status_code == 201, response.text
            conv = response.json()["id"]
            assert len((await client.get("/api/conversations")).json()) == 1
            # SSE uses its own session but must retain the same identity and ownership scope.
            from unittest.mock import patch, AsyncMock
            from langchain_core.messages import AIMessageChunk

            class FakeModel:
                async def astream(self, messages):
                    assert "Bob secret" not in str(messages)
                    yield AIMessageChunk(content="Authorized reply")

            with (
                patch("agentdevstu.config.llm_providers.create_llm", return_value=FakeModel()),
                patch("agentdevstu.api.conversations.extract_memories", new=AsyncMock(return_value=[])),
            ):
                streamed = await client.post(f"/api/conversations/{conv}/messages/stream", json={"content": "hello"})
                assert streamed.status_code == 200 and "Authorized reply" in streamed.text, streamed.text
                assert '"type": "error"' not in streamed.text, streamed.text
            assert len((await client.get(f"/api/conversations/{conv}/messages")).json()) == 2
            # Revocation cancels a running stream even when the model is waiting without tokens.
            entered = asyncio.Event()

            class SlowModel:
                async def astream(self, messages):
                    yield AIMessageChunk(content="Before revoke")
                    entered.set()
                    await asyncio.sleep(30)
                    yield AIMessageChunk(content="MUST NOT ARRIVE")

            with (
                patch("agentdevstu.config.llm_providers.create_llm", return_value=SlowModel()),
                patch("agentdevstu.api.conversations.extract_memories", new=AsyncMock(return_value=[])),
            ):
                task = asyncio.create_task(
                    client.post(f"/api/conversations/{conv}/messages/stream", json={"content": "slow"})
                )
                await asyncio.wait_for(entered.wait(), 10)
                async with factory() as db:
                    member = await db.scalar(
                        select(sm.Membership).where(sm.Membership.user_id == a.id, sm.Membership.workspace_id == w1.id)
                    )
                    grant = await db.get(sm.AgentGrant, (member.id, ag1.id))
                    await db.delete(grant)
                    await db.commit()
                revoked = await asyncio.wait_for(task, 8)
                assert "MUST NOT ARRIVE" not in revoked.text and "Authorization changed" in revoked.text, revoked.text
                async with factory() as db:
                    db.add(sm.AgentGrant(member_id=member.id, agent_id=ag1.id))
                    await db.commit()

            assert (
                await client.post(
                    f"/api/conversations/{conv}/messages/stream",
                    json={"content": "hello", "attachments": [{"url": "/uploads/chat/bob-secret.txt"}]},
                )
            ).status_code == 403
            assert (await client.get("/uploads/chat/bob-secret.txt")).status_code == 404
            assert (await client.post("/api/chat", json={"message": "legacy bypass"})).status_code == 410
            assert (
                await client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
            ).status_code == 403
            response = await client.post(
                f"/api/conversations/{conv}/upload", files={"file": ("hello.txt", b"Private attachment", "text/plain")}
            )
            assert response.status_code == 200, response.text
            upload = response.json()["url"]
            # ProtectedUpload is checked even when the file itself is not in the default runtime test path.
            assert (await client.get(upload)).status_code == 200
            # Admin cannot read Alice's private conversation either.
            response = await client.post("/api/auth/login", json={"username": "admin", "password": "Admin-Test-12345"})
            assert response.status_code == 200, response.text
            created_space = await client.post("/api/workspaces", json={"name": "Created through API"})
            assert created_space.status_code == 201, created_space.text
            created_id = created_space.json()["id"]
            assert created_id in [w["id"] for w in (await client.get("/api/workspaces")).json()]
            assert (await client.get("/api/admin/workspaces/" + created_id + "/members")).status_code == 200
            assert (await client.get(f"/api/conversations/{conv}")).status_code == 404
            assert (await client.get("/api/agents/" + str(ag3.id))).status_code == 404
            # First-login password enforcement and session invalidation.
            created = await client.post(
                "/api/admin/users",
                json={"username": "charlie", "display_name": "Charlie", "password": "Charlie-Initial123"},
            )
            assert created.status_code == 201, created.text
            admin_cookie = client.cookies.get("agentdevstu_session")
            assert (
                await client.post("/api/auth/login", json={"username": "charlie", "password": "Charlie-Initial123"})
            ).status_code == 200
            assert (await client.get("/api/workspaces")).status_code == 403
            assert (
                await client.post(
                    "/api/auth/password",
                    json={"old_password": "Charlie-Initial123", "new_password": "Charlie-Changed123"},
                )
            ).status_code == 204
            assert (await client.get("/api/auth/me")).status_code == 401
            assert (
                await client.post("/api/auth/login", json={"username": "charlie", "password": "Charlie-Changed123"})
            ).status_code == 200
            assert (await client.get("/api/workspaces")).json() == []
            assert (
                await client.post(
                    "/api/admin/roles",
                    json={"name": "Escalate", "code": "escalate", "scope": "system", "permissions": ["users.manage"]},
                )
            ).status_code == 403
            client.cookies.set("agentdevstu_session", admin_cookie, domain="test.local", path="/")
            roles = (await client.get("/api/admin/roles")).json()
            member_role = next(r["id"] for r in roles if r["code"] == "member")
            response = await client.put(
                f"/api/admin/workspaces/{w1.id}/members",
                json={"user_id": str(a.id), "role_ids": [member_role], "agent_ids": [str(ag3.id)]},
            )
            assert response.status_code == 422, response.text
            # A user can join multiple spaces and receive only that space's Agent.
            response = await client.put(
                f"/api/admin/workspaces/{w2.id}/members",
                json={"user_id": str(a.id), "role_ids": [member_role], "agent_ids": [str(ag3.id)]},
            )
            assert response.status_code == 200, response.text
            response = await client.delete(f"/api/admin/workspaces/{w1.id}/members/{a.id}")
            assert response.status_code == 204, response.text
            client.cookies.set("agentdevstu_session", alice_cookie, domain="test.local", path="/")
            assert (await client.get("/api/auth/agents")).status_code == 403
            response = await client.get("/api/auth/agents", headers={"X-Workspace-Id": str(w2.id)})
            assert response.status_code == 200 and [x["id"] for x in response.json()] == [str(ag3.id)], response.text
            assert (await client.get(upload)).status_code == 404
            await client.post("/api/auth/login", json={"username": "admin", "password": "Admin-Test-12345"})
            response = await client.patch(f"/api/admin/users/{a.id}", json={"status": "disabled"})
            assert response.status_code == 200, response.text
            client.cookies.set("agentdevstu_session", alice_cookie, domain="test.local", path="/")
            assert (await client.get("/api/auth/me")).status_code == 401
    finally:
        if upload:
            path = Path(upload.lstrip("/"))
            if path.exists():
                path.unlink()
        for module, old in original:
            module.async_session_factory = old
        await test_engine.dispose()
        async with base_engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await base_engine.dispose()
