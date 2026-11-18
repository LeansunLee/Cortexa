"""项目-Agent 权限授权：授权 CRUD、工具门禁（use/manage）、上下文注入过滤。"""

import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from cortexa.projects import service as s
from cortexa.projects import runtime as projects_runtime
from cortexa.api import projects as api
from cortexa.security.access import Actor, current_actor
from cortexa.security.models import Membership
from cortexa.work.models import Work, WorkActivity

from test_goal_collaboration import setup

URL = os.getenv("GOAL_TEST_DATABASE_URL")


def test_grant_level_semantics_manage_implies_use():
    assert s.grant_allows("manage", "use") and s.grant_allows("manage", "manage")
    assert s.grant_allows("use", "use") and not s.grant_allows("use", "manage")
    assert not s.grant_allows(None, "use") and not s.grant_allows("", "manage")


async def _project(db, pid):
    return await s.get(db, pid, lock=True)


async def _replace_grants(store, pid, items):
    async with store.sessions() as db:
        await s.replace_agent_grants(db, await _project(db, pid), items)
        await db.commit()


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_project_agent_grants_crud_tools_and_summaries(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            a = ctx.actor
            ws = a.workspace_id
            monkeypatch.setattr(projects_runtime, "async_session_factory", ctx.store.sessions)
            source, manage_agent = ctx.source, ctx.targets[0]

            # ── 建项目（setup 的 owner 无 Membership 行，先补上） ──
            async with ctx.store.sessions() as db:
                db.add(Membership(user_id=a.user_id, workspace_id=ws))
                await db.flush()
                p = await api.save(db, api.ProjectInput(title="浙江拓展", goal="拓展新门店", owner_id=a.user_id))
                await db.commit()
                pid = p.id

            # ── 授权 CRUD：整体替换、同 Agent 去重后写生效、附带名称 ──
            async with ctx.store.sessions() as db:
                out = await api.replace_agent_grants(pid, api.AgentGrantsPayload(grants=[
                    api.AgentGrantInput(agent_id=source.id, level="use"),
                    api.AgentGrantInput(agent_id=manage_agent.id, level="manage"),
                    api.AgentGrantInput(agent_id=manage_agent.id, level="use"),  # 去重：后写生效
                ]), db)
                await db.commit()
            by_id = {row["agent_id"]: row for row in out}
            assert by_id[source.id]["level"] == "use"
            assert by_id[manage_agent.id]["level"] == "use"
            assert by_id[source.id]["agent_name"]
            async with ctx.store.sessions() as db:
                listed = await api.agent_grants(pid, db)
                detail = await api.detail(pid, db)
            assert {row["agent_id"] for row in listed} == {source.id, manage_agent.id}
            assert {row["agent_id"] for row in detail["agent_grants"]} == {source.id, manage_agent.id}

            # ── 校验：跨工作空间 Agent 422、非法级别 422 ──
            async with ctx.store.sessions() as db:
                from cortexa.db.models import Agent
                foreign = await db.scalar(select(Agent.id).where(Agent.workspace_id != ws).limit(1))
            with pytest.raises(HTTPException) as exc:
                await _replace_grants(ctx.store, pid, [{"agent_id": foreign, "level": "use"}])
            assert exc.value.status_code == 422
            with pytest.raises(HTTPException):
                await _replace_grants(ctx.store, pid, [{"agent_id": source.id, "level": "admin"}])

            # ── 权限：项目成员（可见但非负责人/创建人/空间管理员）不能改授权 → 403 ──
            outsider_id = uuid.uuid4()
            outsider = Actor(user_id=outsider_id, username="outsider", superadmin=False, must_change=False,
                             version=1, workspace_id=ws,
                             memberships={ws: {"permissions": set(), "all_agents": False, "agent_ids": set()}})
            async with ctx.store.sessions() as db:
                from cortexa.projects.models import ProjectMember
                from cortexa.security.models import User
                db.add(User(id=outsider_id, username="outsider", display_name="成员", password_hash="test"))
                await db.flush()  # 先落 User，否则 ProjectMember 外键可能先校验
                db.add(ProjectMember(workspace_id=ws, project_id=pid, user_id=outsider_id))
                await db.commit()
            token = current_actor.set(outsider)
            try:
                with pytest.raises(HTTPException) as exc:
                    async with ctx.store.sessions() as db:
                        await api.replace_agent_grants(pid, api.AgentGrantsPayload(grants=[]), db)
                assert exc.value.status_code == 403
            finally:
                current_actor.reset(token)

            # ── 工具门禁 ──
            def tool(name, agent_id):
                return next(t for t in projects_runtime.tools(agent_id, [pid], []) if t.name == name)

            await _replace_grants(ctx.store, pid, [])  # 清空授权
            denied = await tool("project_read", source.id).coroutine(project_id=pid)
            assert not denied["success"] and "授权" in denied["error"]

            # use：可读、不可改名、不可派发
            await _replace_grants(ctx.store, pid, [{"agent_id": source.id, "level": "use"}])
            read_ok = await tool("project_read", source.id).coroutine(project_id=pid)
            assert read_ok["success"] and read_ok["result"]["project"]["title"] == "浙江拓展"
            upd = await tool("project_update", source.id).coroutine(project_id=pid, title="改不了")
            assert not upd["success"] and "授权" in upd["error"]
            dis = await tool("work_dispatch", source.id).coroutine(project_id=pid, title="t", goal="g")
            assert not dis["success"] and "授权" in dis["error"]

            # manage：可改名（含无时区 due_at 拒绝）、可派发（缺省负责人=项目负责人）
            await _replace_grants(ctx.store, pid, [{"agent_id": source.id, "level": "manage"}])
            upd = await tool("project_update", source.id).coroutine(
                project_id=pid, title="浙江拓展二期", due_at="2026-12-31T18:00:00+08:00")
            assert upd["success"] and upd["result"]["title"] == "浙江拓展二期"
            bad_due = await tool("project_update", source.id).coroutine(project_id=pid, due_at="2026-12-31")
            assert not bad_due["success"]
            dis = await tool("work_dispatch", source.id).coroutine(
                project_id=pid, title="门店选址", goal="完成10个门店选址", deliverable_requirement="选址报告")
            assert dis["success"], dis
            async with ctx.store.sessions() as db:
                w = await db.get(Work, uuid.UUID(dis["result"]["work_id"]))
                assert w.project_id == pid and w.status == "todo"  # 人类负责人工作初始 todo（pending 仅 Agent 负责人）
                acts = [r.action for r in await db.scalars(
                    select(WorkActivity).where(WorkActivity.work_id == w.id))]
            assert "dispatched" in acts

            # 归档项目拒绝派发
            async with ctx.store.sessions() as db:
                await api.archive(pid, db)
                await db.commit()
            dis2 = await tool("work_dispatch", source.id).coroutine(project_id=pid, title="t2", goal="g2")
            assert not dis2["success"] and "归档" in dis2["error"]

            # ── summaries 过滤：未授权只留 notice 且 refs 剔除；授权后注入内容；不传 agent_id 行为不变 ──
            use_agent = ctx.targets[1]
            await _replace_grants(ctx.store, pid, [])
            async with ctx.store.sessions() as db:
                text, refs = await s.summaries(db, [pid], agent_id=use_agent.id)
                assert "未获得该项目的使用授权" in text and not refs
            await _replace_grants(ctx.store, pid, [{"agent_id": use_agent.id, "level": "use"}])
            async with ctx.store.sessions() as db:
                text, refs = await s.summaries(db, [pid], agent_id=use_agent.id)
                assert "浙江拓展二期" in text and refs and refs[0]["type"] == "project"
                text, refs = await s.summaries(db, [pid])
                assert "浙江拓展二期" in text and refs

    asyncio.run(scenario())
