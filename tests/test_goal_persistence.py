"""Migration, owner isolation and CAS in a disposable local PostgreSQL schema."""

import asyncio
import copy
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from cortexa.db.engine import Base
from cortexa.db.models import Agent, Conversation, ConversationMessage, Workspace
from cortexa.runtime.artifacts import ArtifactStore
from cortexa.runtime.models import RuntimeGoal
from cortexa.runtime.state import GoalState
from cortexa.runtime.store import GoalStore
from cortexa.security import isolation  # noqa: F401
from cortexa.security.access import Actor, current_actor
from cortexa.security.models import User

spec = importlib.util.spec_from_file_location(
    "goal_migration", Path(__file__).parents[1] / "scripts/migrate_goal_runtime.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
URL = os.getenv("GOAL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")


def test_migration_idempotency_downgrade_ownership_and_cas(tmp_path, monkeypatch):
    asyncio.run(rehearsal(tmp_path, monkeypatch))


async def rehearsal(tmp_path, monkeypatch):
    root = create_async_engine(URL)
    schema = "goal_test_" + uuid.uuid4().hex
    async with root.begin() as db:
        await db.execute(text("CREATE SCHEMA " + schema))
    engine = create_async_engine(URL, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    token = None
    try:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
            await db.execute(text("DROP TABLE t_runtime_goals"))
            await db.execute(text("ALTER TABLE t_workspaces DROP COLUMN runtime_policy"))
        assert not (await migration.migrate(engine))["installed"]
        assert (await migration.migrate(engine, apply=True))["changed"]
        assert not (await migration.migrate(engine, apply=True))["changed"]
        async with engine.begin() as db:
            await migration.rollback_empty_test_schema(db)
        assert not (await migration.migrate(engine))["installed"]
        await migration.migrate(engine, apply=True)
        ws, ag, owner, other, conv_id = [uuid.uuid4() for _ in range(5)]
        async with sessions() as db:
            db.add(Workspace(id=ws, name="test"))
            db.add_all(
                [
                    User(id=owner, username="goal-owner", password_hash="test", display_name="test"),
                    User(id=other, username="goal-other", password_hash="test", display_name="test"),
                ]
            )
            await db.flush()
            db.add(Agent(id=ag, workspace_id=ws, name="test", status="active"))
            await db.flush()
            db.add(Conversation(id=conv_id, workspace_id=ws, agent_id=ag, owner_user_id=owner))
            await db.commit()
        actor = Actor(
            user_id=owner,
            username="goal-owner",
            superadmin=True,
            must_change=False,
            version=1,
            workspace_id=ws,
            memberships={ws: {"permissions": {"agent.use"}, "all_agents": True}},
            runtime=True,
        )
        token = current_actor.set(actor)
        store = GoalStore(sessions, ArtifactStore(tmp_path))
        state = GoalState()
        row, created = await store.create(conv_id, "once", "hello", state, {"messages": []})
        assert created
        duplicate, created = await store.create(conv_id, "once", "hello", GoalState(), {"messages": []})
        assert not created and duplicate.id == row.id
        with pytest.raises(HTTPException) as conflict:
            await store.create(conv_id, "once", "different", GoalState(), {})
        assert conflict.value.status_code == 409
        stale = copy.copy(row)
        await store.checkpoint(row, state, {"messages": []})
        with pytest.raises(HTTPException) as conflict:
            await store.checkpoint(stale, state, {"messages": []}, reply="must roll back")
        assert conflict.value.status_code == 409
        async with sessions() as db:
            assert len((await db.scalars(select(ConversationMessage))).all()) == 1
        current_actor.set(
            Actor(
                user_id=other,
                username="goal-other",
                superadmin=True,
                must_change=False,
                version=1,
                workspace_id=ws,
                memberships={ws: {"permissions": {"agent.use"}, "all_agents": True}},
                runtime=True,
            )
        )
        with pytest.raises(HTTPException) as hidden:
            await store.get(conv_id, row.id)
        assert hidden.value.status_code == 404
        async with sessions() as db:
            assert await db.get(RuntimeGoal, row.id) is None
            assert not (await db.scalars(select(RuntimeGoal))).all()
        current_actor.set(actor)
        # Simultaneous requests within one conversation share one Goal and one message.
        results = await asyncio.gather(*[store.create(conv_id, "race", "same", GoalState(), {}) for _ in range(2)])
        assert results[0][0].id == results[1][0].id
        assert sum(int(r[1]) for r in results) == 1
        await api_scenarios(monkeypatch, store, conv_id)
        await readonly_scenario(engine, schema)
        # Invalid same-name schema is rejected rather than silently accepted.
        async with engine.begin() as db:
            await db.execute(text("ALTER TABLE t_runtime_goals DROP CONSTRAINT ck_runtime_goal_revision"))
        with pytest.raises(RuntimeError, match="CHECK"):
            await migration.migrate(engine, apply=True)
    finally:
        if token:
            current_actor.reset(token)
        await engine.dispose()
        async with root.begin() as db:
            await db.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        await root.dispose()


async def api_scenarios(monkeypatch, store, conv_id):
    import json
    from unittest.mock import AsyncMock

    from langchain_core.messages import AIMessageChunk
    from test_goal_loop import FakeModel, binding, tool_call

    from cortexa.api import goals as api

    monkeypatch.setattr(api, "store", store)
    monkeypatch.setattr(api, "execution_config", lambda: {"features": {"goal_execution_enabled": True}})
    monkeypatch.setattr("cortexa.memory.integration.register_extraction", AsyncMock())
    monkeypatch.setattr(api, "prepare_bindings", AsyncMock(return_value=([], [])))
    model = FakeModel([[AIMessageChunk(content="hello")]])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)

    async def collect(response):
        return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in response.body_iterator]

    response = await api.create_goal_stream(conv_id, api.GoalRequest(content="你好", idempotency_key="api-hello"))
    events = await collect(response)
    assert events[-1]["type"] == "done", events
    assert events[-1]["status"] == "COMPLETE"
    assert len(model.calls) == 1
    ident = uuid.UUID(events[-1]["goal_id"])
    row = await store.get(conv_id, ident)
    assert row.state["consumed"]["llm_calls"] == 1
    assert store.files.read(row.id, row.artifacts["snapshot"])["final_reply"] == "hello"
    duplicate = await api.create_goal_stream(conv_id, api.GoalRequest(content="你好", idempotency_key="api-hello"))
    assert duplicate["goal_id"] == str(ident) and len(model.calls) == 1

    # Parameter gap -> WAITING -> explicit owner/revision resume -> original Goal COMPLETE.
    b = binding()
    monkeypatch.setattr(api, "prepare_bindings", AsyncMock(return_value=([b], [])))
    model = FakeModel([[tool_call(args={})], [tool_call(args={"city": "杭州"})], [AIMessageChunk(content="销量 2")]])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)
    events = await collect(
        await api.create_goal_stream(conv_id, api.GoalRequest(content="查询城市销量", idempotency_key="api-input"))
    )
    assert events[-1]["status"] == "WAITING", events
    assert "city" in events[-1]["content"]
    assert b.invoke.await_count == 0
    goal_id, revision = uuid.UUID(events[-1]["goal_id"]), events[-1]["revision"]
    response = await api.resume_goal(conv_id, goal_id, api.ResumeRequest(content="杭州", revision=revision))
    resumed = await collect(response)
    assert resumed[-1]["status"] == "COMPLETE", resumed
    assert resumed[-1]["goal_id"] == str(goal_id)
    assert resumed[-1]["consumed"]["llm_calls"] == 3
    assert b.invoke.await_count == 1
    with pytest.raises(HTTPException) as stale:
        await api.resume_goal(conv_id, goal_id, api.ResumeRequest(content="杭州", revision=revision))
    assert stale.value.status_code == 409

    # Client cancellation persists WAITING and partial assistant text; no false COMPLETE.
    monkeypatch.setattr(api, "prepare_bindings", AsyncMock(return_value=([], [])))
    model = FakeModel([[AIMessageChunk(content="部分结果"), asyncio.CancelledError()]])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)
    response = await api.create_goal_stream(conv_id, api.GoalRequest(content="你好", idempotency_key="api-cancel"))
    observed = []
    with pytest.raises(asyncio.CancelledError):
        async for chunk in response.body_iterator:
            observed.append(json.loads(chunk.removeprefix("data: ").strip()))
    cancel_id = uuid.UUID(observed[0]["goal_id"])
    cancelled = await store.get(conv_id, cancel_id)
    assert cancelled.status == "WAITING" and cancelled.state["reason"] == "cancelled"
    assert cancelled.state["consumed"]["output_tokens"] > 0
    async with store.sessions() as db:
        message = await db.get(ConversationMessage, uuid.UUID(cancelled.state["result_message_id"]))
        assert message.content == "部分结果" and message.metadata_json["stopped"]

    # Ambiguous raw goal asks for clarification without a model call.
    model = FakeModel([])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)
    events = await collect(
        await api.create_goal_stream(conv_id, api.GoalRequest(content="处理一下", idempotency_key="api-clarify"))
    )
    assert events[-1]["status"] == "WAITING" and events[-1]["reason"] == "clarify_goal"
    assert not model.calls

    # Tool execution cannot start when its hard budget is zero.
    monkeypatch.setattr(api, "prepare_bindings", AsyncMock(return_value=([b], [])))
    model = FakeModel([[tool_call()]])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)
    events = await collect(
        await api.create_goal_stream(
            conv_id, api.GoalRequest(content="查询", idempotency_key="api-budget", budget={"tool_calls": 0})
        )
    )
    assert events[-1]["status"] == "BLOCKED" and events[-1]["reason"] == "budget_exhausted:tool_calls", events
    assert b.invoke.await_count == 1

    # Explicit crash recovery marks unknown external work, then refuses replay.
    from datetime import UTC, datetime, timedelta

    from cortexa.runtime.state import Action

    unknown = GoalState(current_action=Action(kind="CAPABILITY", capability_id="external"))
    crashed, _ = await store.create(
        conv_id, "api-crash", "original", unknown, {"goal": {"raw_request": "original"}, "messages": [], "sources": []}
    )
    async with store.sessions() as db:
        await db.execute(
            RuntimeGoal.__table__.update()
            .where(RuntimeGoal.id == crashed.id)
            .values(updated_at=datetime.now(UTC) - timedelta(seconds=1000))
        )
        await db.commit()
    recovered = await api.resume_goal(conv_id, crashed.id, api.ResumeRequest(content="继续", revision=crashed.revision))
    assert recovered["status"] == "WAITING" and recovered["reason"] == "interrupted"
    with pytest.raises(HTTPException) as unsafe:
        await api.resume_goal(conv_id, crashed.id, api.ResumeRequest(content="继续", revision=recovered["revision"]))
    assert unsafe.value.status_code == 409

    # A validation error after a durable tool result keeps that result and
    # allows an explicit continuation without repeating the external call.
    from pydantic import BaseModel

    class InvalidValue(BaseModel):
        required_field: int

    original_save = api.GoalLoop.save
    injected = False

    async def validation_failure_after_tool(loop):
        nonlocal injected
        action = loop.state.current_action
        if not injected and action and action.kind == "CAPABILITY" and action.phase == "completed":
            injected = True
            InvalidValue.model_validate({})
        await original_save(loop)

    monkeypatch.setattr(api.GoalLoop, "save", validation_failure_after_tool)
    monkeypatch.setattr(api, "prepare_bindings", AsyncMock(return_value=([b], [])))
    model = FakeModel([[tool_call()], [AIMessageChunk(content="已完成")]])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)
    before = b.invoke.await_count
    events = await collect(
        await api.create_goal_stream(conv_id, api.GoalRequest(content="查询销售", idempotency_key="api-validation"))
    )
    assert events[-1]["type"] == "done" and events[-1]["status"] == "WAITING", events
    assert events[-1]["reason"] == "runtime_validation_error"
    assert b.invoke.await_count == before + 1
    goal_id = uuid.UUID(events[-1]["goal_id"])
    waiting = await store.get(conv_id, goal_id)
    assert len(store.files.read(goal_id, waiting.artifacts["snapshot"])["observations"]) == 1
    monkeypatch.setattr(api.GoalLoop, "save", original_save)
    model = FakeModel([[AIMessageChunk(content="已完成")]])
    monkeypatch.setattr(api, "create_llm", lambda *_: model)
    resumed = await collect(
        await api.resume_goal(conv_id, goal_id, api.ResumeRequest(content="继续", revision=waiting.revision))
    )
    assert resumed[-1]["status"] == "COMPLETE", resumed
    assert b.invoke.await_count == before + 1

    # Workspace policy writes merge the budget namespace under workspace.manage.
    from cortexa.api.runtime_policy import BudgetPolicyUpdate, put_policy

    async with store.sessions() as db:
        ws = await db.scalar(select(Workspace))
        ws.runtime_policy = {"version": 1, "collaboration": {"future": "preserve"}}
        await db.commit()
        await put_policy(ws.id, BudgetPolicyUpdate(budget={"llm_calls": 2}), db)
    async with store.sessions() as db:
        policy = await db.scalar(select(Workspace.runtime_policy))
        assert policy["collaboration"] == {"future": "preserve"}
        assert policy["budget"]["llm_calls"] == 2


async def readonly_scenario(engine, schema):
    from sqlalchemy.engine import make_url

    from cortexa.data.adapter import execute_query
    from cortexa.db.encryption import encrypt_dict

    url = make_url(URL)
    config = {"host": url.host, "port": url.port, "database": url.database}
    credential = encrypt_dict({"username": url.username, "password": url.password})
    result = await execute_query(
        "postgres", config, credential, "SELECT current_setting('transaction_read_only') AS mode", {}, read_only=True
    )
    assert result["success"] and result["data"] == [{"mode": "on"}]
    async with engine.begin() as db:
        await db.execute(text("CREATE SEQUENCE goal_readonly_seq"))
    result = await execute_query(
        "postgres", config, credential, "SELECT nextval('" + schema + ".goal_readonly_seq') AS n", {}, read_only=True
    )
    assert not result["success"]
    async with engine.begin() as db:
        assert not await db.scalar(text("SELECT is_called FROM goal_readonly_seq"))
    with pytest.raises(ValueError):
        await execute_query("postgres", config, credential, "DELETE FROM t_users", {}, read_only=True)
