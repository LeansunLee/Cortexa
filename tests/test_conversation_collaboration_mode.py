"""Conversation choices are persisted and never exceed the workspace ceiling."""

import asyncio
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from test_goal_collaboration import CONFIG, URL, setup

from cortexa.api import goals as api
from cortexa.db.models import Agent, Conversation, Workspace
from cortexa.runtime.collaboration import Autonomy, authorize_agent, discover
from cortexa.runtime.goals import parse_goal
from cortexa.runtime.policy import conversation_modes, resolve_effective_policy
from cortexa.runtime.state import GoalState, RuntimeHalt
from cortexa.security.access import current_actor


@pytest.mark.parametrize("ceiling,count", [(mode, i + 1) for i, mode in enumerate(Autonomy)])
def test_workspace_limits_conversation_choices_and_defaults(ceiling, count):
    workspace = {"collaboration": {"max_autonomy": ceiling}}
    agent = SimpleNamespace(collaboration={}, quality_policy={})
    assert conversation_modes({}, workspace, agent) == list(Autonomy)[:count]
    conv = SimpleNamespace(metadata_json={"unrelated": "preserved"})
    assert api.conversation_mode_options(conv, agent, workspace, {})["collaboration_mode"] == Autonomy.EXPLICIT_ONLY
    for selection in Autonomy:
        resolved = resolve_effective_policy({}, workspace, agent, conversation_mode=selection)
        assert list(Autonomy).index(resolved.collaboration_mode) < count
    conv.metadata_json["collaboration_mode"] = "AUTONOMOUS"
    assert api.conversation_mode_options(conv, agent, workspace, {})["collaboration_mode"] == ceiling


def test_platform_agent_and_disabled_collaboration_can_tighten_options():
    workspace = {"collaboration": {"max_autonomy": "AUTONOMOUS"}}
    agent = SimpleNamespace(collaboration={"autonomy": "ASK_BEFORE_COLLABORATION"}, quality_policy={})
    assert conversation_modes({}, workspace, agent) == list(Autonomy)[:2]
    assert conversation_modes({}, {}, agent) == [Autonomy.EXPLICIT_ONLY]
    assert conversation_modes({"runtime": {"collaboration": {"enabled": False}}}, workspace, agent) == [
        Autonomy.EXPLICIT_ONLY
    ]
    assert conversation_modes({"runtime": {"collaboration": {"max_autonomy": "EXPLICIT_ONLY"}}}, workspace, agent) == [
        Autonomy.EXPLICIT_ONLY
    ]


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL URL required")
def test_selection_persistence_runtime_gates_and_ownership(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            async with ctx.store.sessions() as db:
                agent = await db.get(Agent, ctx.source.id)
                agent.collaboration = {}
                conv = await db.get(Conversation, ctx.conv)
                conv.metadata_json = {"other": "keep"}
                await db.commit()
            ctx.source.collaboration = {}
            options = await api.goal_options(ctx.conv)
            assert options["collaboration_mode"] == "EXPLICIT_ONLY"
            assert options["allowed_collaboration_modes"] == list(Autonomy)
            payload = {"goal": parse_goal("分析销售数据").model_dump(mode="json")}
            target = ctx.targets[0]
            async with ctx.store.sessions() as db:
                state = GoalState()
                assert (await discover(db, ctx.source, state, payload, CONFIG))[0] == []
                with pytest.raises(RuntimeHalt, match="collaboration_explicit_only"):
                    await authorize_agent(db, ctx.source.id, target.id, state, payload, CONFIG)
                state.explicit_agents = [str(target.id)]
                assert (await authorize_agent(db, ctx.source.id, target.id, state, payload, CONFIG))[
                    1
                ] == "USER_EXPLICIT"

            for mode in (Autonomy.ASK_BEFORE_COLLABORATION, Autonomy.AUTONOMOUS):
                await api.set_collaboration_mode(ctx.conv, api.CollaborationModeRequest(collaboration_mode=mode))
                assert (await api.goal_options(ctx.conv))["collaboration_mode"] == mode
                _, _, effective = await api.environment(ctx.conv)
                assert effective.collaboration_mode == mode
                state = GoalState(collaboration_mode=mode, candidate_agents=[str(target.id)])
                async with ctx.store.sessions() as db:
                    if mode == Autonomy.ASK_BEFORE_COLLABORATION:
                        with pytest.raises(RuntimeHalt, match="collaboration_approval_required"):
                            await authorize_agent(db, ctx.source.id, target.id, state, payload, CONFIG)
                        state.approved_agents = [str(target.id)]
                        assert (await authorize_agent(db, ctx.source.id, target.id, state, payload, CONFIG))[
                            1
                        ] == "USER_APPROVED"
                    else:
                        assert (await authorize_agent(db, ctx.source.id, target.id, state, payload, CONFIG))[
                            1
                        ] == "RUNTIME_AUTONOMOUS"

            async with ctx.store.sessions() as db:
                conv = await db.get(Conversation, ctx.conv)
                assert conv.metadata_json == {"other": "keep", "collaboration_mode": "AUTONOMOUS"}
                workspace = await db.get(Workspace, ctx.source.workspace_id)
                workspace.runtime_policy = {"collaboration": {"max_autonomy": "EXPLICIT_ONLY"}}
                await db.commit()
            options = await api.goal_options(ctx.conv)
            assert options["allowed_collaboration_modes"] == [Autonomy.EXPLICIT_ONLY]
            assert options["collaboration_mode"] == Autonomy.EXPLICIT_ONLY
            assert (await api.environment(ctx.conv))[2].collaboration_mode == Autonomy.EXPLICIT_ONLY
            with pytest.raises(HTTPException) as denied:
                await api.set_collaboration_mode(
                    ctx.conv, api.CollaborationModeRequest(collaboration_mode="AUTONOMOUS")
                )
            assert denied.value.status_code == 422
            async with ctx.store.sessions() as db:
                with pytest.raises(RuntimeHalt, match="collaboration_explicit_only"):
                    await authorize_agent(db, ctx.source.id, target.id, state, payload, CONFIG)
            token = current_actor.set(replace(ctx.actor, user_id=uuid.uuid4()))
            try:
                with pytest.raises(HTTPException) as denied:
                    await api.set_collaboration_mode(
                        ctx.conv, api.CollaborationModeRequest(collaboration_mode="EXPLICIT_ONLY")
                    )
                assert denied.value.status_code == 404
            finally:
                current_actor.reset(token)

    asyncio.run(scenario())
