"""Organization rules and real API isolation in a disposable PostgreSQL schema."""

import asyncio
import os
import uuid
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agentdevstu.organization.schemas import ProfileInput, UnitInput
from agentdevstu.organization.service import score_member


def test_validation_and_scoring():
    with pytest.raises(ValidationError):
        UnitInput(name=" ")
    with pytest.raises(ValidationError):
        ProfileInput(responsibility_tags=["x" * 41])
    assert ProfileInput(responsibility_tags=["测试", "测试"]).responsibility_tags == ["测试"]
    p = dict(
        user_id="1",
        display_name="测试工程师",
        org_unit_name="研发",
        position_title="测试工程师",
        responsibility="接口测试 自动化 回归测试",
        coverage_scope="支付接口",
        responsibility_tags=["测试", "自动化"],
    )
    task = {"title": "支付接口自动化测试", "goal": "完成接口回归测试"}
    score = score_member(p, task, ["支付接口自动化测试"], 0)
    assert score["score"] > 40
    assert score["score"] > score_member(p, task, [], 8)["score"]
    assert score_member(p, {"title": "展厅展台搭建装修"}) is None
    assert score_member(p, {"title": "完成相关工作任务"}) is None


def test_proxy_context_never_reads_directory():
    from agentdevstu.agents.context import organization_reference

    db = SimpleNamespace(execute=AsyncMock())
    assert asyncio.run(organization_reference(SimpleNamespace(agent_type="proxy"), db)) == []
    db.execute.assert_not_called()


def test_context_requires_current_workspace():
    from agentdevstu.organization.service import organization_context
    from agentdevstu.security.access import Actor, current_actor

    ws = uuid.uuid4()
    token = current_actor.set(Actor(uuid.uuid4(), "a", False, False, 1, memberships={ws: {}}, workspace_id=ws))
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(organization_context(None, uuid.uuid4()))
        assert exc.value.status_code == 403
    finally:
        current_actor.reset(token)


@pytest.mark.skipif(
    not os.getenv("WORK_TEST_DATABASE_URL"), reason="Set WORK_TEST_DATABASE_URL for PostgreSQL integration"
)
def test_organization_api(monkeypatch):
    asyncio.run(integration(monkeypatch))


async def integration(monkeypatch):
    import sys
    from datetime import datetime, timedelta

    import httpx
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from agentdevstu.api.deps import get_db
    from agentdevstu.db.engine import Base
    from agentdevstu.db.models import Workspace
    from agentdevstu.organization.models import MemberProfile, OrgUnit
    from agentdevstu.security.http import COOKIE
    from agentdevstu.security.models import LoginSession, MemberRole, Membership, Role, User
    from agentdevstu.security.passwords import token_digest
    from agentdevstu.web.app import app

    schema = "org_test_" + uuid.uuid4().hex
    base = create_async_engine(os.environ["WORK_TEST_DATABASE_URL"])
    async with base.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_async_engine(
        os.environ["WORK_TEST_DATABASE_URL"], connect_args={"server_settings": {"search_path": schema}}
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("agentdevstu.") and hasattr(mod, "async_session_factory"):
            monkeypatch.setattr(mod, "async_session_factory", factory)

    async def dependency():
        async with factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = dependency
    clients = []
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            spaces = [Workspace(name="组织测试"), Workspace(name="隔离空间")]
            role = Role(code="org_manager", name="组织维护", scope="workspace", permissions=["members.manage"])
            users = [
                User(username=n, display_name=n, must_change_password=False, email="sensitive@example.test")
                for n in ("admin", "engineer", "outsider")
            ]
            db.add_all([*spaces, role, *users])
            await db.flush()
            tokens = [uuid.uuid4().hex for _ in users]
            for i, user in enumerate(users):
                m = Membership(user_id=user.id, workspace_id=spaces[i // 2].id)
                db.add(m)
                await db.flush()
                if i in (0, 2):
                    db.add(MemberRole(member_id=m.id, role_id=role.id))
                db.add(
                    LoginSession(
                        token_hash=token_digest(tokens[i]),
                        user_id=user.id,
                        auth_version=1,
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
            await db.commit()
        for i, t in enumerate(tokens):
            clients.append(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://test",
                    cookies={COOKIE: t},
                    headers={"X-Workspace-Id": str(spaces[i // 2].id), "X-Requested-With": "AgentDevStu"},
                )
            )
        admin, reader, outsider = clients

        async def call(client, method, path, status=200, **kw):
            res = await client.request(method, "/api" + path, **kw)
            assert res.status_code == status, (method, path, res.status_code, res.text[:2000])
            return res.json() if res.content else None

        root = await call(
            admin,
            "POST",
            "/organization/units",
            201,
            json={"name": "研发中心", "code": "DEV", "manager_user_id": str(users[1].id)},
        )
        child = await call(admin, "POST", "/organization/units", 201, json={"name": "前端组", "parent_id": root["id"]})
        foreign = await call(outsider, "POST", "/organization/units", 201, json={"name": "秘密部门"})
        await call(reader, "POST", "/organization/units", 403, json={"name": "越权"})
        await call(admin, "POST", "/organization/units", 409, json={"name": "重复编码", "code": "DEV"})
        await call(
            admin, "PUT", "/organization/units/" + root["id"], 422, json={"name": "循环", "parent_id": child["id"]}
        )
        await call(admin, "PUT", "/organization/units/" + foreign["id"], 404, json={"name": "越权"})
        await call(admin, "POST", "/organization/units", 404, json={"name": "跨空间", "parent_id": foreign["id"]})
        await call(
            admin,
            "POST",
            "/organization/units",
            422,
            json={"name": "跨空间负责人", "manager_user_id": str(users[2].id)},
        )
        profile_url = "/organization/members/" + str(users[1].id)
        # A profile without any department must be valid (nullable composite FK).
        await call(admin, "PUT", profile_url, json={"position_title": "工程师"})
        await call(
            admin,
            "PUT",
            profile_url,
            json={
                "org_unit_id": child["id"],
                "position_title": "前端工程师",
                "responsibility": "负责 Vue 前端开发",
                "responsibility_tags": ["前端", "Vue"],
                "coverage_scope": "业务页面",
            },
        )
        await call(reader, "PUT", profile_url, 403, json={"responsibility": "越权"})
        await call(admin, "PUT", "/organization/members/" + str(users[2].id), 422, json={})
        await call(admin, "PUT", profile_url, 404, json={"org_unit_id": foreign["id"]})
        people = await call(reader, "GET", "/organization/members")
        assert len(people) == 2 and all("email" not in p for p in people)
        recommended = await call(
            reader, "POST", "/works/assignee-recommendations", json={"title": "Vue 前端开发", "goal": "新增业务页面"}
        )
        assert recommended[0]["user_id"] == str(users[1].id)
        assert not await call(reader, "POST", "/works/assignee-recommendations", json={"title": "展台装修"})
        assert not await call(outsider, "POST", "/works/assignee-recommendations", json={"title": "Vue 前端开发"})
        await call(reader, "GET", "/organization/members", 403, headers={"X-Workspace-Id": str(spaces[1].id)})
        await call(admin, "DELETE", "/organization/units/" + root["id"], 409)
        await call(admin, "DELETE", "/organization/units/" + child["id"], 409)
        await call(
            admin, "PUT", "/organization/units/" + root["id"], 409, json={"name": "研发中心", "status": "disabled"}
        )
        await call(
            admin,
            "PUT",
            "/organization/units/" + child["id"],
            json={"name": "前端组", "parent_id": root["id"], "status": "disabled"},
        )
        assert not await call(reader, "POST", "/works/assignee-recommendations", json={"title": "Vue 前端开发"})
        await call(admin, "PUT", "/organization/units/" + child["id"], json={"name": "前端组", "parent_id": root["id"]})
        from agentdevstu.organization.service import organization_context
        from agentdevstu.security.access import current_actor, load_actor

        a = await load_actor(tokens[0])
        a.workspace_id = spaces[0].id
        ctx = current_actor.set(a)
        try:
            async with factory() as db:
                context = await organization_context(db, spaces[0].id)
                assert len(context["members"]) == 2
                assert "秘密部门" not in str(context) and "sensitive@" not in str(context)
        finally:
            current_actor.reset(ctx)
        await call(admin, "DELETE", f"/admin/workspaces/{spaces[0].id}/members/{users[1].id}", 204)
        async with factory() as db:
            assert await db.get(MemberProfile, (spaces[0].id, users[1].id)) is None
            assert (await db.get(OrgUnit, uuid.UUID(root["id"]))).manager_user_id is None
        await call(admin, "DELETE", "/organization/units/" + child["id"], 204)
        await call(admin, "DELETE", "/organization/units/" + root["id"], 204)
    finally:
        app.dependency_overrides.pop(get_db, None)
        for c in clients:
            await c.aclose()
        await engine.dispose()
        async with base.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        await base.dispose()
