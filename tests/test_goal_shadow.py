import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk

from cortexa.runtime.goals import (
    MAX_PARSE_CHARS,
    FieldSource,
    Gap,
    GapType,
    Route,
    analyze_gaps,
    parse_goal,
    route_goal,
)
from cortexa.runtime.shadow import goal_shadow_entry, shadow_enabled


def test_raw_goal_and_explicit_fields_keep_provenance():
    raw = "  目标：分析销量\r\n对象：杭州门店\n约束：只使用本季度数据\n成功标准：覆盖全部门店\n输出：表格  "
    goal = parse_goal(raw, explicit_inputs={"city": "杭州"})
    assert goal.raw_request == raw
    assert goal.objective == "分析销量"
    assert goal.targets == ["杭州门店"]
    assert goal.constraints == ["只使用本季度数据"]
    assert goal.success_criteria == ["覆盖全部门店"]
    assert goal.expected_output == "表格"
    assert goal.inputs == {"city": "杭州"}
    assert goal.operations == ["analyze"]
    assert goal.field_sources["inputs"] == FieldSource.EXPLICIT
    assert goal.field_sources["operations"] == FieldSource.DETERMINISTIC
    assert FieldSource.INFERRED not in goal.field_sources.values()
    other = parse_goal("帮我评估未知的问题，不要编造成功标准")
    assert other.objective == other.raw_request
    assert other.success_criteria == []
    assert other.field_sources["success_criteria"] == FieldSource.DEFAULT


def test_gap_policy_never_uses_parameter_or_information_gap_for_enrichment():
    simple = parse_goal("你好")
    assert route_goal(simple).route == Route.DIRECT
    assert route_goal(simple).gap_types == [GapType.NONE]
    assert not route_goal(simple).enrichment_eligible
    semantic = parse_goal("请处理一下")
    assert route_goal(semantic).enrichment_eligible
    assert route_goal(semantic).route == Route.SEMANTIC_REVIEW
    semantic.uncertainties = analyze_gaps(semantic, required_inputs=("city",))
    assert route_goal(semantic).route == Route.ASK_USER
    assert not route_goal(semantic).enrichment_eligible
    for kind, route in [
        (GapType.INFORMATION_GAP, Route.RETRIEVAL),
        (GapType.CAPABILITY_GAP, Route.RESOLVE_CAPABILITY),
        (GapType.ENVIRONMENT_GAP, Route.CHECK_ENVIRONMENT),
    ]:
        simple.uncertainties = [Gap(kind=kind, code="verified_by_caller")]
        assert route_goal(simple).route == route
        assert not route_goal(simple).enrichment_eligible


def test_participants_are_unordered_and_explicit_constraints_are_preserved():
    first = parse_goal("@销售 @分析 不要找其他Agent")
    second = parse_goal("@分析 @销售 不要找其他Agent")
    assert first.explicit_agents == second.explicit_agents
    assert not first.collaboration_constraints.allow_discovery
    assert first.collaboration_constraints.allow_collaboration
    assert route_goal(first).route == Route.COLLABORATION
    restricted = parse_goal("只找销售Agent")
    assert restricted.collaboration_constraints.only_agents == ["销售Agent"]
    assert not restricted.collaboration_constraints.allow_discovery
    assert not parse_goal("@销售 不要协作").collaboration_constraints.allow_collaboration
    assert "search" not in parse_goal("不要搜索").operations


def test_json_long_and_ambiguous_inputs_do_not_truncate_or_invent_facts():
    goal = parse_goal('{"city":"杭州","limit":10}')
    assert goal.inputs == {"city": "杭州", "limit": 10}
    assert analyze_gaps(goal, required_inputs=("city", "date"))[0].fields == ["date"]
    assert parse_goal("帮我解读 {invalid json}").inputs == {}
    raw = "长" * (MAX_PARSE_CHARS + 1)
    oversized = parse_goal(raw)
    assert oversized.objective == raw and oversized.raw_request == raw
    assert not oversized.analysis_complete
    assert not route_goal(oversized).enrichment_eligible


def test_trace_is_content_minimized_and_parser_failure_is_fail_open(monkeypatch):
    raw = "目标：secret-business\n对象：secret-person\n输出：secret-format\napi_key=secret-key"
    trace = goal_shadow_entry(raw, "message-id")
    assert "secret-" not in json.dumps(trace)
    assert trace["detail"]["raw_goal"]["message_id"] == "message-id"
    assert trace["detail"]["llm_calls_added"] == 0
    assert not trace["detail"]["enrichment_executed"]

    def fail(*args, **kwargs):
        raise ValueError("secret-input")

    monkeypatch.setattr("cortexa.runtime.shadow.parse_goal", fail)
    failure = goal_shadow_entry("private", "id")
    assert failure["status"] == "error"
    assert "secret-input" not in json.dumps(failure)
    assert failure["detail"]["execution"] == "LEGACY_UNCHANGED"


def test_flag_is_explicit_boolean_and_bad_config_disables_shadow(tmp_path):
    path = tmp_path / "config.yaml"
    assert not shadow_enabled(path)
    for config in ("features: {}", 'features: {goal_shadow_enabled: "false"}', "[invalid", "features: null"):
        path.write_text(config)
        assert not shadow_enabled(path)
    path.write_text("features: {goal_shadow_enabled: true}")
    assert shadow_enabled(path)


def stream_fixture(monkeypatch, *, enabled, debug=False, can_operate=False, proxy=False, pause=False, content="你好"):
    """All external boundaries mocked; never connects to any database/model/provider."""
    from cortexa.api import conversations as api
    from cortexa.db.models import Agent, Conversation, Workspace
    from cortexa.security.access import current_actor

    agent = Agent(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="助手",
        agent_type="proxy" if proxy else "llm",
        model="fake",
        proxy_config={},
        knowledge_base_ids=[],
        tool_ids=[],
    )
    conv = Conversation(id=uuid.uuid4(), workspace_id=agent.workspace_id, agent_id=agent.id)
    saved, calls = [], []
    token_seen = asyncio.Event()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, kind, ident):
            return conv if kind is Conversation else None if kind is Workspace else agent

        def add(self, value):
            value.id = value.id or uuid.uuid4()
            value.created_at = datetime.now(UTC)
            saved.append(value)

        async def flush(self):
            pass

        async def refresh(self, value):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

        async def execute(self, query):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(reversed(saved))))

    class Model:
        async def astream(self, messages):
            calls.append(messages)
            yield AIMessageChunk(
                content="原有回答", usage_metadata={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
            )
            if pause:
                token_seen.set()
                await asyncio.Event().wait()

    monkeypatch.setattr(api, "async_session_factory", Session)
    monkeypatch.setattr(api, "shadow_enabled", lambda path: enabled)
    monkeypatch.setattr(api, "_conversation_debug_enabled", lambda: debug)
    monkeypatch.setattr(api, "organization_reference", AsyncMock(return_value=[]))
    monkeypatch.setattr(api, "_load_agent_capabilities", AsyncMock(return_value=[]))
    monkeypatch.setattr("cortexa.tools.web_search.load_search_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr("cortexa.memory.integration.register_extraction", AsyncMock())
    monkeypatch.setattr("cortexa.config.llm_providers.create_llm", lambda name: Model())
    monkeypatch.setattr(
        "cortexa.collaboration.background.prepare_proxy_resolution_context", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "cortexa.agents.proxy_executor.execute_proxy_agent",
        AsyncMock(return_value={"success": True, "output_data": {"answer": "原有回答"}, "duration_ms": 1}),
    )
    monkeypatch.setattr("cortexa.security.debug_preferences.debug_enabled", lambda user_id: True)
    actor = SimpleNamespace(user_id=uuid.uuid4(), has=lambda code: can_operate)

    async def run():
        from cortexa.api.schemas import ConversationMessageCreate

        token = current_actor.set(actor)
        try:
            response = await api.create_message_stream(conv.id, ConversationMessageCreate(content=content))
            return [json.loads(chunk[6:]) async for chunk in response.body_iterator if chunk.startswith("data: ")]
        finally:
            current_actor.reset(token)

    return run, saved, calls, token_seen


@pytest.mark.parametrize("proxy", [False, True])
@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("can_operate", [False, True])
def test_shadow_preserves_reply_calls_and_trace_access(monkeypatch, proxy, debug, can_operate):
    baseline, _, baseline_calls, _ = stream_fixture(
        monkeypatch, enabled=False, debug=debug, can_operate=can_operate, proxy=proxy
    )
    before = asyncio.run(baseline())
    run, saved, calls, _ = stream_fixture(monkeypatch, enabled=True, debug=debug, can_operate=can_operate, proxy=proxy)
    after = asyncio.run(run())
    assert not any(event["type"] == "error" for event in after), after
    assert calls == baseline_calls
    assert len(calls) == (0 if proxy else 1)
    assert [event.get("content") for event in before if event["type"] == "token"] == [
        event.get("content") for event in after if event["type"] == "token"
    ]
    assert saved[-1].content == "原有回答"
    assert any(entry["stage"] == "goal" for entry in saved[-1].metadata_json["debug_trace"])
    live_goal = [event for event in after if event["type"] == "debug" and event["entry"]["stage"] == "goal"]
    assert bool(live_goal) == (debug and can_operate)
    done = next(event for event in after if event["type"] == "done")
    assert any(entry["stage"] == "goal" for entry in done.get("debug_trace", [])) == (debug and can_operate)


def test_shadow_failure_does_not_break_stream(monkeypatch):
    run, saved, calls, _ = stream_fixture(monkeypatch, enabled=True)

    def fail(*args, **kwargs):
        raise ValueError("private")

    monkeypatch.setattr("cortexa.runtime.shadow.parse_goal", fail)
    events = asyncio.run(run())
    assert events[-1]["type"] == "done"
    assert len(calls) == 1
    assert saved[-1].metadata_json["debug_trace"][0]["status"] == "error"


def test_cancellation_preserves_partial_reply_and_shadow(monkeypatch):
    async def scenario():
        run, saved, _, token_seen = stream_fixture(monkeypatch, enabled=True, pause=True)
        task = asyncio.create_task(run())
        await asyncio.wait_for(token_seen.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert saved[-1].content == "原有回答"
        assert saved[-1].metadata_json["stopped"] is True
        assert saved[-1].metadata_json["debug_trace"][0]["stage"] == "goal"
        assert saved[0].metadata_json["debug_trace"][0]["stage"] == "goal"

    asyncio.run(scenario())


@pytest.mark.parametrize("can_operate", [False, True])
def test_history_filters_goal_trace_for_runtime_users(monkeypatch, can_operate):
    from cortexa.api.conversations import list_messages
    from cortexa.db.models import ConversationMessage

    msg = ConversationMessage(metadata_json={"debug_trace": [{"stage": "goal"}, {"stage": "response"}]})
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [msg]))
    monkeypatch.setattr("cortexa.api.conversations.can_read_goal_trace", lambda: can_operate)
    rows = asyncio.run(list_messages(uuid.uuid4(), db))
    assert ("debug_trace" in rows[0].metadata_json) == can_operate
