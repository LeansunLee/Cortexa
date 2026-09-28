"""Goal collaboration policies and real persistence with scripted model decisions."""

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessageChunk
from referencing.exceptions import Unresolvable
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_goal_loop import FakeModel, binding, tool_call

from cortexa.api import goals as api
from cortexa.db.engine import Base
from cortexa.db.models import Agent, AgentCollaboration, Conversation, ConversationMessage, Workspace
from cortexa.runtime import agent_executor as executor
from cortexa.runtime.artifacts import ArtifactStore
from cortexa.runtime.collaboration import Autonomy, discover, effective_policy, permitted_by_goal, resolve_explicit
from cortexa.runtime.goals import parse_goal
from cortexa.runtime.state import GoalState, RuntimeHalt
from cortexa.runtime.store import GoalStore
from cortexa.security import isolation  # noqa: F401
from cortexa.security.access import Actor, current_actor
from cortexa.security.models import User

URL = os.getenv("GOAL_TEST_DATABASE_URL")
CONFIG = {"features": {"goal_execution_enabled": True, "goal_collaboration_enabled": True}}


def test_policy_layers_only_tighten():
    source = SimpleNamespace(collaboration={"autonomy": "AUTONOMOUS", "candidate_limit": 5})
    assert effective_policy(source, {"max_autonomy": "ASK_BEFORE_COLLABORATION", "candidate_limit": 2}) == (
        Autonomy.ASK_BEFORE_COLLABORATION,
        2,
        True,
    )
    assert effective_policy(source, {"enabled": False})[-1] is False
    assert effective_policy(SimpleNamespace(collaboration={}))[0] == Autonomy.EXPLICIT_ONLY


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")
def test_workspace_mode_is_inherited_without_copying_agent_config(tmp_path, monkeypatch):
    from cortexa.runtime.collaboration import policy_for

    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            async with ctx.store.sessions() as db:
                source = await db.get(Agent, ctx.source.id)
                source.collaboration = {}
                workspace = await db.get(Workspace, source.workspace_id)
                workspace.runtime_policy = {
                    "version": 1,
                    "collaboration": {"max_autonomy": "AUTONOMOUS"},
                }
                await db.commit()
            async with ctx.store.sessions() as db:
                source = await db.get(Agent, ctx.source.id)
                mode, _, _ = await policy_for(db, source, CONFIG)
                assert mode == Autonomy.AUTONOMOUS
                workspace = await db.get(Workspace, source.workspace_id)
                workspace.runtime_policy = {
                    "version": 1,
                    "collaboration": {"max_autonomy": "ASK_BEFORE_COLLABORATION"},
                }
                await db.commit()
            async with ctx.store.sessions() as db:
                source = await db.get(Agent, ctx.source.id)
                mode, _, _ = await policy_for(db, source, CONFIG)
                assert mode == Autonomy.ASK_BEFORE_COLLABORATION
                assert source.collaboration == {}

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "query,allowed,discovery",
    [
        ("不要协作", False, False),
        ("不要找其他 Agent", True, False),
        ("只找销售Agent", True, False),
        ("分析销售", True, True),
    ],
)
def test_explicit_user_constraints(query, allowed, discovery):
    target = SimpleNamespace(name="销售Agent", collaboration={})
    payload = {"goal": {"raw_request": query}}
    assert permitted_by_goal(target, payload) is allowed
    assert permitted_by_goal(target, payload, discovery=True) is discovery
    payload["clarifications"] = ["禁止协作"]
    assert not permitted_by_goal(target, payload)


@pytest.mark.parametrize(
    "source,target,path,depth,reason",
    [
        ("a", "a", [], 1, "collaboration_cycle"),
        ("a", "b", ["a", "b"], 2, "collaboration_cycle"),
        ("a", "b", [], 0, "agent_depth"),
        ("a", "c", ["a", "b"], 1, "agent_depth"),
    ],
)
def test_depth_and_cycles(source, target, path, depth, reason):
    with pytest.raises(RuntimeHalt, match=reason):
        executor.check_path(source, target, path, depth)


def test_contract_required_and_no_remote_references():
    assert executor.contract_errors({"type": "object", "required": ["city"]}, {})
    assert not executor.contract_errors({"type": "object", "required": ["city"]}, {"city": "杭州"})
    with pytest.raises(Unresolvable):
        executor.contract_errors({"$ref": "https://example.com/schema"}, {})


@asynccontextmanager
async def setup(tmp_path, monkeypatch):
    root = create_async_engine(URL)
    schema = "collab_test_" + uuid.uuid4().hex
    async with root.begin() as db:
        await db.execute(text("CREATE SCHEMA " + schema))
    engine = create_async_engine(URL, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    token = None
    try:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        ws, other_ws, owner, conv = [uuid.uuid4() for _ in range(4)]
        source = Agent(
            id=uuid.uuid4(),
            workspace_id=ws,
            name="主Agent",
            status="active",
            system_prompt="PRIMARY_PRIVATE_SECRET",
            collaboration={"autonomy": "ASK_BEFORE_COLLABORATION"},
        )
        targets = [
            Agent(
                id=uuid.UUID(int=i + 1),
                workspace_id=ws,
                name=name,
                status="active",
                description="分析销售汇总",
                collaboration={},
            )
            for i, name in enumerate(["销售Agent", "分析Agent", "未授权Agent"])
        ]
        async with sessions() as db:
            db.add_all(
                [
                    Workspace(id=ws, name="test", runtime_policy={"collaboration": {"max_autonomy": "AUTONOMOUS"}}),
                    Workspace(id=other_ws, name="other"),
                    User(id=owner, username="goal-owner", password_hash="test", display_name="test"),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    source,
                    *targets,
                    Agent(
                        id=uuid.uuid4(),
                        workspace_id=other_ws,
                        name="异空间Agent",
                        status="active",
                        description="分析销售",
                    ),
                ]
            )
            await db.flush()
            db.add(Conversation(id=conv, workspace_id=ws, agent_id=source.id, owner_user_id=owner,
                                metadata_json={"collaboration_mode": "ASK_BEFORE_COLLABORATION"}))
            await db.commit()
        actor = Actor(
            user_id=owner,
            username="goal-owner",
            superadmin=False,
            must_change=False,
            version=1,
            workspace_id=ws,
            memberships={
                ws: {
                    "permissions": {"agent.use", "workspace.manage", "agent.update", "agent.create"},
                    "all_agents": False,
                    "agent_ids": {source.id, targets[0].id, targets[1].id},
                }
            },
            runtime=True,
        )
        token = current_actor.set(actor)
        store = GoalStore(sessions, ArtifactStore(tmp_path))
        monkeypatch.setattr(api, "store", store)
        monkeypatch.setattr(api, "execution_config", lambda: CONFIG)
        monkeypatch.setattr(api, "prepare_bindings", AsyncMock(return_value=([], [])))
        monkeypatch.setattr(executor, "prepare_bindings", AsyncMock(return_value=([], [])))
        monkeypatch.setattr("cortexa.memory.integration.register_extraction", AsyncMock())
        yield SimpleNamespace(store=store, source=source, targets=targets, conv=conv, actor=actor)
    finally:
        if token:
            current_actor.reset(token)
        await engine.dispose()
        async with root.begin() as db:
            await db.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        await root.dispose()


async def collect(response):
    return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in response.body_iterator]


async def start(ctx, key, content="分析销售数据", **kwargs):
    events = await collect(
        await api.create_goal_stream(ctx.conv, api.GoalRequest(content=content, idempotency_key=key, **kwargs))
    )
    assert events[-1]["type"] == "done", events
    return events[-1]


async def set_mode(ctx, mode):
    async with ctx.store.sessions() as db:
        agent = await db.get(Agent, ctx.source.id)
        agent.collaboration = {"autonomy": mode}
        conv = await db.get(Conversation, ctx.conv)
        conv.metadata_json = {"collaboration_mode": mode}
        await db.commit()
    ctx.source.collaboration = {"autonomy": mode}


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")
def test_discovery_permissions_no_static_order_and_shared_budget(tmp_path, monkeypatch):
    asyncio.run(discovery_scenario(tmp_path, monkeypatch))


async def discovery_scenario(tmp_path, monkeypatch):
    async with setup(tmp_path, monkeypatch) as ctx:
        payload = {"goal": parse_goal("分析销售数据").model_dump(mode="json")}
        async with ctx.store.sessions() as db:
            state = GoalState(collaboration_mode="ASK_BEFORE_COLLABORATION")
            agents, _ = await discover(db, ctx.source, state, payload, CONFIG)
            assert {a.id for a in agents} == {a.id for a in ctx.targets[:2]}
            forward = await resolve_explicit(db, ctx.source, parse_goal("@销售Agent @分析Agent 分析销售数据"))
            reverse = await resolve_explicit(db, ctx.source, parse_goal("@分析Agent @销售Agent 分析销售数据"))
            assert forward == reverse
            assert await resolve_explicit(db, ctx.source, parse_goal("只找销售Agent")) == [str(ctx.targets[0].id)]
            with pytest.raises(HTTPException):
                await resolve_explicit(db, ctx.source, parse_goal("@未授权Agent 分析销售"))
        await set_mode(ctx, "EXPLICIT_ONLY")
        async with ctx.store.sessions() as db:
            agents, _ = await discover(db, ctx.source, GoalState(), payload, CONFIG)
            assert agents == []
            # Downgrading source policy also removes previous approvals from the prompt.
            agents, _ = await discover(db, ctx.source, GoalState(approved_agents=reverse), payload, CONFIG)
            assert agents == []
        second = ctx.targets[1]
        model = FakeModel(
            [
                [tool_call(name="agent_" + second.id.hex, args={"task": "独立分析销售"})],
                [AIMessageChunk(content="最终分析")],
            ]
        )
        child = FakeModel(
            [
                [
                    AIMessageChunk(
                        content="销售结果", usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
                    )
                ]
            ]
        )
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        monkeypatch.setattr(executor, "create_llm", lambda *_: child)
        done = await start(ctx, "order", "@销售Agent @分析Agent 分析销售数据")
        assert done["status"] == "COMPLETE", done
        assert done["consumed"]["agent_calls"] == 1
        assert done["consumed"]["llm_calls"] == 3
        assert done["collaborations"][0]["agent_name"] == "分析Agent"
        assert done["collaborations"][0]["authorization"] == "USER_EXPLICIT"
        assert "PRIMARY_PRIVATE_SECRET" not in str(child.calls)
        assert "销售结果" in str(model.calls[-1])
        assert done["stats"]["token_count"] == 5
        result = await api.collaboration_result(
            ctx.conv, uuid.UUID(done["goal_id"]), uuid.UUID(done["collaborations"][0]["action_id"])
        )
        assert result["result"] == "销售结果"
        async with ctx.store.sessions() as db:
            saved = await db.get(ConversationMessage, uuid.UUID(done["id"]))
            assert "result" not in saved.metadata_json["collaborations"][0]
            assert saved.metadata_json["collaborations"][0]["goal_result"]["goal_id"] == done["goal_id"]
        async with ctx.store.sessions() as db:
            audits = (await db.scalars(select(AgentCollaboration))).all()
            assert len(audits) == 1 and audits[0].target_agent_id == second.id
        for budget, key in [({"agent_calls": 0}, "agent_calls"), ({"agent_depth": 0}, "agent_depth")]:
            model = FakeModel([[tool_call(name="agent_" + second.id.hex, args={"task": "分析"})]])
            monkeypatch.setattr(api, "create_llm", lambda *_, model=model: model)
            with pytest.raises(HTTPException) as blocked:
                await start(ctx, key, "@分析Agent 分析销售", budget=budget)
            assert blocked.value.status_code == 422
            assert len(child.calls) == 1
        model = FakeModel([[tool_call(name="agent_" + second.id.hex, args={"task": "分析"})]])
        child = FakeModel([[AIMessageChunk(content="预算内执行")]])
        monkeypatch.setattr(executor, "create_llm", lambda *_: child)
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        with pytest.raises(HTTPException) as blocked:
            await start(ctx, "shared-budget", "@分析Agent 分析销售", budget={"llm_calls": 1})
        assert blocked.value.status_code == 422 and not child.calls


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")
def test_ask_multi_select_denial_idempotency_and_resume(tmp_path, monkeypatch):
    asyncio.run(ask_scenario(tmp_path, monkeypatch))


async def ask_scenario(tmp_path, monkeypatch):
    async with setup(tmp_path, monkeypatch) as ctx:
        selected, denied = ctx.targets[:2]
        model = FakeModel([[tool_call(name="agent_" + selected.id.hex, args={"task": "分析销售"})]])
        child = FakeModel([[AIMessageChunk(content="已完成分析")]])
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        monkeypatch.setattr(executor, "create_llm", lambda *_: child)
        done = await start(ctx, "ask")
        assert done["reason"] == "collaboration_approval_required" and done["status"] == "WAITING", done
        assert not child.calls and done["consumed"].get("agent_calls", 0) == 0
        goal = uuid.UUID(done["goal_id"])
        candidates = await api.approval_candidates(ctx.conv, goal)
        assert {c["id"] for c in candidates} == {str(a.id) for a in ctx.targets[:2]}
        with pytest.raises(HTTPException) as invalid:
            await api.authorize_collaboration(
                ctx.conv,
                goal,
                api.AuthorizationRequest(
                    revision=done["revision"], approved_agents=[ctx.targets[2].id], denied_agents=[denied.id]
                ),
            )
        assert invalid.value.status_code == 422
        decision = api.AuthorizationRequest(
            revision=done["revision"], approved_agents=[selected.id], denied_agents=[denied.id]
        )
        approved = await api.authorize_collaboration(ctx.conv, goal, decision)
        again = await api.authorize_collaboration(ctx.conv, goal, decision)
        assert again == approved
        model = FakeModel(
            [
                [tool_call(name="agent_" + selected.id.hex, args={"task": "分析销售"})],
                [AIMessageChunk(content="目标完成")],
            ]
        )
        resumed = await collect(
            await api.resume_goal(
                ctx.conv, goal, api.ResumeRequest(content="继续执行目标", revision=approved["revision"])
            )
        )
        assert resumed[-1]["status"] == "COMPLETE", resumed
        assert resumed[-1]["collaborations"][0]["authorization"] == "USER_APPROVED"
        row = await ctx.store.get(ctx.conv, goal)
        state = GoalState.model_validate(row.state)
        snapshot = ctx.store.files.read(row.id, row.artifacts["snapshot"])
        async with ctx.store.sessions() as db:
            agents, _ = await discover(db, ctx.source, state, snapshot, CONFIG)
            assert denied.id not in {a.id for a in agents}
        with pytest.raises(HTTPException):
            await api.authorize_collaboration(
                ctx.conv,
                goal,
                api.AuthorizationRequest(
                    revision=done["revision"], approved_agents=[denied.id], denied_agents=[selected.id]
                ),
            )
        # Autonomous authorization still records its origin and honors permission filtering.
        await set_mode(ctx, "AUTONOMOUS")
        model = FakeModel(
            [[tool_call(name="agent_" + selected.id.hex, args={"task": "分析销售"})], [AIMessageChunk(content="完成")]]
        )
        child = FakeModel([[AIMessageChunk(content="销售 3")]])
        done = await start(ctx, "auto")
        assert done["status"] == "COMPLETE" and done["collaborations"][0]["authorization"] == "RUNTIME_AUTONOMOUS", done


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")
def test_child_contract_tools_isolation_and_cancellation(tmp_path, monkeypatch):
    asyncio.run(child_scenario(tmp_path, monkeypatch))


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")
def test_child_budget_with_observation_returns_partial(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            target = ctx.targets[0]
            async with ctx.store.sessions() as db:
                current = await db.get(Agent, target.id)
                current.quality_policy = {"runtime": {"budget": {"output_tokens": 150}}}
                await db.commit()
            parent = FakeModel([
                [tool_call(name="agent_" + target.id.hex, args={"task": "分析销售"})],
                [AIMessageChunk(content="已取得部分数据，完整方案仍需补充。")],
            ])
            child = FakeModel([[tool_call()], [AIMessageChunk(content="很长的分析" * 80)]])
            data = binding()
            monkeypatch.setattr(api, "create_llm", lambda *_: parent)
            monkeypatch.setattr(executor, "create_llm", lambda *_: child)
            monkeypatch.setattr(executor, "prepare_bindings", AsyncMock(return_value=([data], [])))
            done = await start(ctx, "child-partial", "@销售Agent 分析销售")
            assert done["status"] == "COMPLETE", done
            assert data.invoke.await_count == 1
            assert done["collaborations"][0]["status"] == "partial"
            assert "已取得部分结果" in done["collaborations"][0]["result"]

    asyncio.run(scenario())


async def child_scenario(tmp_path, monkeypatch):
    async with setup(tmp_path, monkeypatch) as ctx:
        target = ctx.targets[0]
        async with ctx.store.sessions() as db:
            a = await db.get(Agent, target.id)
            a.input_schema = {"type": "object", "required": ["city"], "properties": {"city": {"type": "string"}}}
            await db.commit()
        model = FakeModel([[tool_call(name="agent_" + target.id.hex, args={"task": "分析销售"})]])
        child = FakeModel([])
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        monkeypatch.setattr(executor, "create_llm", lambda *_: child)
        done = await start(ctx, "missing", "@销售Agent 分析销售")
        assert done["status"] == "WAITING" and done["reason"] == "missing_inputs" and not child.calls, done
        model = FakeModel(
            [
                [tool_call(name="agent_" + target.id.hex, args={"task": "分析销售", "inputs": {"city": "杭州"}})],
                [AIMessageChunk(content="销量 2")],
            ]
        )
        b = binding()
        monkeypatch.setattr(executor, "prepare_bindings", AsyncMock(return_value=([b], [])))
        child = FakeModel([[tool_call()], [AIMessageChunk(content="销量 2")]])
        done = await start(ctx, "tools", "@销售Agent 分析销售")
        assert done["status"] == "COMPLETE", done
        assert done["consumed"]["llm_calls"] == 4 and done["consumed"]["tool_calls"] == 1
        assert done["consumed"]["agent_calls"] == 1 and b.invoke.await_count == 1
        assert "PRIMARY_PRIVATE_SECRET" not in str(child.calls)
        model = FakeModel(
            [[tool_call(name="agent_" + target.id.hex, args={"task": "分析销售", "inputs": {"city": "杭州"}})]]
        )
        child = FakeModel([[AIMessageChunk(content="中断部分"), asyncio.CancelledError()]])
        response = await api.create_goal_stream(
            ctx.conv, api.GoalRequest(content="@销售Agent 分析销售", idempotency_key="cancel")
        )
        observed = []
        with pytest.raises(asyncio.CancelledError):
            async for chunk in response.body_iterator:
                observed.append(json.loads(chunk.removeprefix("data: ").strip()))
        goal = uuid.UUID(observed[0]["goal_id"])
        row = await ctx.store.get(ctx.conv, goal)
        assert row.status == "WAITING" and row.state["current_action"]["phase"] == "unknown"
        assert row.state["consumed"]["llm_calls"] == 2
        with pytest.raises(HTTPException) as unsafe:
            await api.resume_goal(ctx.conv, goal, api.ResumeRequest(content="继续", revision=row.revision))
        assert unsafe.value.status_code == 409


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")
def test_settings_merge_publication_and_policy_revocation(tmp_path, monkeypatch):
    asyncio.run(settings_scenario(tmp_path, monkeypatch))


async def settings_scenario(tmp_path, monkeypatch):
    from cortexa.api.agents import (
        AgentRuntimeBudgetUpdate,
        _create_version_impl,
        get_agent_runtime_budget,
        put_agent_runtime_budget,
        update_agent,
    )
    from cortexa.api.runtime_policy import BudgetPolicyUpdate, put_policy
    from cortexa.api.schemas import AgentUpdate
    from cortexa.runtime.collaboration import authorize_agent

    async with setup(tmp_path, monkeypatch) as ctx:
        ctx.actor.runtime = False
        ctx.actor.memberships[ctx.actor.workspace_id]["permissions"].add("agent.read")
        async with ctx.store.sessions() as db:
            agent = await db.get(Agent, ctx.source.id)
            agent.collaboration = {
                "autonomy": "ASK_BEFORE_COLLABORATION",
                "legacy_consult": True,
                "discoverable": False,
            }
            await db.commit()
            await update_agent(agent.id, AgentUpdate(collaboration={"autonomy": "AUTONOMOUS"}), db)
            assert agent.collaboration == {"autonomy": "AUTONOMOUS", "legacy_consult": True, "discoverable": False}
            version = await _create_version_impl(agent.id, None, db)
            assert version.snapshot["collaboration"] == agent.collaboration
            await put_policy(agent.workspace_id, BudgetPolicyUpdate(budget={"llm_calls": 4, "context_tokens": 64000}), db)
            inherited = await get_agent_runtime_budget(agent.id, db)
            assert inherited["budget"] is None
            assert inherited["effective_budget"]["context_tokens"] == 64000
            agent.quality_policy = {"checks": {"strict": True}}
            configured = await put_agent_runtime_budget(
                agent.id, AgentRuntimeBudgetUpdate(budget={"context_tokens": 48000}), db
            )
            assert configured["effective_budget"]["context_tokens"] == 48000
            assert configured["source_trace"]["context_tokens"]["source"] == "Agent"
            assert agent.quality_policy["checks"] == {"strict": True}
            with pytest.raises(HTTPException) as exceeded:
                await put_agent_runtime_budget(agent.id, AgentRuntimeBudgetUpdate(budget={"context_tokens": 70000}), db)
            assert exceeded.value.status_code == 422
            assert agent.quality_policy["runtime"]["budget"]["context_tokens"] == 48000
            reset = await put_agent_runtime_budget(agent.id, AgentRuntimeBudgetUpdate(budget=None), db)
            assert reset["effective_budget"]["context_tokens"] == 64000
            await put_policy(
                agent.workspace_id, BudgetPolicyUpdate(collaboration={"max_autonomy": "EXPLICIT_ONLY"}), db
            )
            policy = await db.scalar(select(Workspace.runtime_policy))
            assert policy["budget"] == {"llm_calls": 4, "context_tokens": 64000}
            # Existing approved agents are no longer executable after Workspace tightening.
            agent.status = "active"
            await db.commit()
            state = GoalState(approved_agents=[str(ctx.targets[0].id)])
            payload = {"goal": parse_goal("分析销售").model_dump(mode="json")}
            with pytest.raises(RuntimeHalt, match="explicit_only"):
                await authorize_agent(db, agent.id, ctx.targets[0].id, state, payload, CONFIG)
