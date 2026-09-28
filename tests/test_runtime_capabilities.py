import asyncio
import json
import uuid
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessageChunk
from pydantic import BaseModel
from test_goal_shadow import stream_fixture

from agentdevstu.collaboration.schemas import AgentHandoffResult
from agentdevstu.runtime.adapters import agent_adapter, retrieval_adapter, tool_adapter
from agentdevstu.runtime.capabilities import CapabilityDescriptor, MatchScope, match_capabilities
from agentdevstu.runtime.capabilities import CapabilityType as Kind
from agentdevstu.runtime.capture import CapabilityCapture
from agentdevstu.runtime.observations import ObservationStatus as Status
from agentdevstu.runtime.shadow import PROTECTED_TRACE_STAGES, visible_trace


class Input(BaseModel):
    city: str


def agent():
    return SimpleNamespace(
        id="agent-id",
        workspace_id="ws",
        name="销售",
        description="销售数据分析",
        tags=["销售"],
        input_schema={"type": "object"},
        output_schema={},
        status="active",
        agent_type="proxy",
        proxy_config={"endpoint": "private-host", "headers": {"Authorization": "secret"}},
        system_prompt="secret-prompt",
    )


def tool(kind=Kind.DATA):
    legacy = SimpleNamespace(
        name="web_search" if kind == Kind.WEB else "data_query",
        description="查询销售数据",
        args_schema=Input,
        handle_validation_error=True,
    )
    cap = (
        SimpleNamespace(
            id="data-id",
            name="销售查询",
            workspace_id="ws",
            status="active",
            input_schema={"properties": {"city": {"aliases": ["杭城"]}}},
            output_schema={"type": "array"},
            row_limit=100,
            timeout_seconds=30,
        )
        if kind == Kind.DATA
        else None
    )
    return tool_adapter(legacy, "ws", capability=cap)


def test_descriptor_reuses_effective_schema_without_copying_secrets():
    descriptor = tool().descriptor
    assert descriptor.input_schema == Input.model_json_schema()
    assert descriptor.constraints["configured_input_schema"]["properties"]["city"]["aliases"] == ["杭城"]
    assert descriptor.output_schema == {"type": "array"}
    assert descriptor.timeout == 30
    assert descriptor.requires_confirmation  # Unknown risk is not silently classified as safe.
    assert "secret" not in agent_adapter(agent()).descriptor.model_dump_json()
    assert "private-host" not in agent_adapter(agent()).descriptor.model_dump_json()
    assert agent_adapter(agent()).descriptor.context_policy["strict_projection"] is False


def test_matcher_filters_scope_availability_and_reserved_types_before_ranking():
    base = CapabilityDescriptor(
        id="sales",
        name="销售",
        description="门店销售分析",
        type=Kind.AGENT,
        workspace_id="ws",
        availability="available",
        operations=["analyze"],
    )
    candidates = [
        base.model_copy(update=changes)
        for changes in [
            {"id": "foreign", "workspace_id": "other"},
            {"id": "denied"},
            {"id": "disabled", "availability": "unavailable"},
            {"id": "unknown", "availability": "unknown"},
            {"id": "human", "type": Kind.HUMAN},
            {"id": "a"},
            {"id": "b"},
        ]
    ]
    scope = MatchScope("ws", frozenset({"foreign", "disabled", "unknown", "human", "a", "b"}))
    results = match_capabilities("销售分析", list(reversed(candidates)), scope, top_k=1)
    assert [match.capability.id for match in results] == ["a"]
    assert not match_capabilities("销售分析", candidates, MatchScope("", scope.allowed_ids))
    assert not match_capabilities("天气", candidates, scope)
    assert not match_capabilities("销售", candidates, scope, types=(Kind.WEB,))
    assert not match_capabilities("销售", candidates, scope, top_k=0)
    assert len(match_capabilities("", candidates, scope, operations=("analyze",))) == 2


def test_data_observation_preserves_rows_facets_evidence_and_exact_result():
    raw = {
        "data": [{"门店": "完整名称", "销量": 17}],
        "row_count": 120,
        "returned_rows": 1,
        "truncated": True,
        "facets": {"销量": {"17": 1}},
        "applied_parameters": {"city": "杭州"},
        "notice": "结果受限",
    }
    original = deepcopy(raw)
    evidence = [{"source_id": "query-record", "private": "keep-original"}]
    observed = tool().observe(raw, "action-1", evidence=evidence)
    assert observed.status == Status.PARTIAL
    assert observed.raw_result is raw and raw == original
    assert observed.facts == raw["data"]
    assert observed.metadata["facets"] == raw["facets"]
    assert observed.metadata["row_count"] == 120
    assert observed.evidence == evidence
    assert observed.confidence is None
    assert observed.action_id == "action-1"
    assert observed.occurred_at.tzinfo is not None


@pytest.mark.parametrize(
    "raw,status",
    [
        ({"data": []}, Status.EMPTY),
        ({"error": "query failed", "data": []}, Status.FAILED),
        ({"success": False}, Status.FAILED),
        ("Tool input validation error", Status.NOT_READY),
        ('{"data": [{"n": 1}]}', Status.SUCCESS),
        ("arbitrary output", Status.UNKNOWN),
        (None, Status.EMPTY),
        ({"status": "unknown"}, Status.UNKNOWN),
    ],
)
def test_observation_distinguishes_empty_failure_and_unstructured_outputs(raw, status):
    observed = tool().observe(raw, "action")
    assert observed.status == status
    assert observed.raw_result is raw


def test_web_returns_evidence_without_promoting_search_snippets_to_verified_facts():
    raw = {"results": [{"title": "标题", "url": "https://example.com", "snippet": "网页摘要"}], "searched_at": "now"}
    observed = tool(Kind.WEB).observe(raw, "web-action")
    assert observed.status == Status.SUCCESS
    assert observed.evidence == raw["results"] and observed.facts == []
    assert tool(Kind.WEB).observe({"results": [], "error": "timeout"}, "fail").status == Status.FAILED
    assert tool(Kind.WEB).observe({"results": []}, "empty").status == Status.EMPTY


def test_knowledge_and_memory_keep_provenance_and_processing_failures():
    adapter = retrieval_adapter(agent(), Kind.KNOWLEDGE)
    assert adapter.observe("", "id").status == Status.EMPTY
    assert adapter.observe("尚未读取正文", "id").status == Status.UNKNOWN
    assert adapter.observe("识别中", "id", metadata={"pending_count": 1}).status == Status.NOT_READY
    assert adapter.observe("失败", "id", metadata={"unreadable_count": 1}).status == Status.FAILED
    assert (
        adapter.observe("部分可读", "id", evidence=[{"document_id": "doc"}], metadata={"pending_count": 1}).status
        == Status.PARTIAL
    )
    memory = SimpleNamespace(
        id="mem", content="仍需核实的认知", source_mode="inferred", confidence=0.4, has_conflict=True
    )
    result = SimpleNamespace(memories=[memory], trace={"selected_ids": ["mem"]})
    observed = retrieval_adapter(agent(), Kind.MEMORY).observe(result, "id")
    assert observed.raw_result is result
    assert observed.evidence[0]["has_conflict"]
    assert observed.evidence[0]["confidence"] == 0.4
    assert observed.facts == []


def test_agent_proxy_readiness_and_legacy_confidence_are_not_fabricated():
    adapter = agent_adapter(agent())
    raw = {
        "success": False,
        "requires_input": True,
        "error": "缺少 city",
        "resolution": {"blockingMissingFields": [{"field": "city"}]},
    }
    observed = adapter.observe(raw, "id")
    assert observed.status == Status.NOT_READY
    assert observed.metadata["missing_inputs"] == [{"field": "city"}]
    handoff = AgentHandoffResult(
        status="success",
        result="全部原文",
        summary="摘要",
        confidence=0.85,
        sources=[{"type": "memory", "memory_id": "mem"}],
        usage={"token_count": 12},
    )
    observed = adapter.observe(handoff, "id")
    assert observed.raw_result is handoff and observed.evidence == handoff.sources
    assert observed.confidence == 0.85
    assert observed.metadata["confidence_source"] == "legacy_unvalidated"
    assert observed.metadata["usage"] == handoff.usage
    assert adapter.observe(None, "id", error=TimeoutError()).status == Status.TIMEOUT
    assert adapter.observe(None, "id", error=RuntimeError()).status == Status.FAILED


def test_capture_is_bounded_fail_open_and_contains_no_raw_values():
    trace = []
    capture = CapabilityCapture(True, trace, max_entries=2)
    capture.observe(lambda: tool(), {"data": [{"secret-key": "secret-business"}]}, action_id="secret-action")
    capture.catalog([lambda: tool()], "销售", "ws")
    for _ in range(20):
        capture.observe(lambda: (_ for _ in ()).throw(AssertionError("must not normalize overflow")), None)
    assert len(trace) == 3
    assert trace[-1]["detail"]["omitted_entries"] == 20
    assert "secret-" not in json.dumps(trace)
    disabled = CapabilityCapture(False, [])
    assert disabled.observe(lambda: (_ for _ in ()).throw(AssertionError()), None) is None
    failure = CapabilityCapture(True, [])
    entry = failure.observe(lambda: (_ for _ in ()).throw(ValueError("private-error")), None)
    assert entry["detail"]["error_code"] == "observation_adapter_failed"
    assert "private-error" not in json.dumps(entry)


@pytest.mark.parametrize("allowed", [True, False])
def test_all_phase2_trace_stages_follow_existing_operator_permission(monkeypatch, allowed):
    from agentdevstu.api.conversations import list_messages
    from agentdevstu.db.models import ConversationMessage

    monkeypatch.setattr("agentdevstu.runtime.shadow.can_read_goal_trace", lambda: allowed)
    trace = [{"stage": stage} for stage in PROTECTED_TRACE_STAGES] + [{"stage": "response"}]
    assert len(visible_trace(trace)) == (len(PROTECTED_TRACE_STAGES) + 1 if allowed else 0)
    msg = ConversationMessage(metadata_json={"debug_trace": trace})
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [msg]))
    monkeypatch.setattr("agentdevstu.api.conversations.can_read_goal_trace", lambda: allowed)
    rows = asyncio.run(list_messages(uuid.uuid4(), db))
    assert len(rows[0].metadata_json.get("debug_trace", [])) == (len(PROTECTED_TRACE_STAGES) + 1 if allowed else 0)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("adapter_failure", [False, True])
def test_real_stream_tool_results_are_unchanged_and_cached_once(monkeypatch, enabled, allowed, adapter_failure):
    from agentdevstu.api import conversations as api

    run, saved, _, _ = stream_fixture(monkeypatch, enabled=False, debug=True, can_operate=allowed)
    monkeypatch.setattr(api, "capability_shadow_enabled", lambda path: enabled)
    if adapter_failure:

        def fail(*args, **kwargs):
            raise ValueError("private input")

        monkeypatch.setattr(api, "tool_adapter", fail)
    monkeypatch.setattr(api, "_build_system_prompt", lambda *args: "原有系统提示")
    cap = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=None,
        name="销售",
        description="销售查询",
        status="active",
        input_schema={},
        output_schema={},
        row_limit=10,
        timeout_seconds=30,
    )
    raw = {"data": [{"销量": 17}], "row_count": 1, "truncated": False, "facets": {"销量": {"17": 1}}}
    executed, prompts = [], []

    class Tool:
        name = f"query_{cap.id.hex}"
        description = "销售查询"
        args_schema = Input
        handle_validation_error = True

        async def ainvoke(self, args):
            executed.append(args)
            return raw

    legacy_tool = Tool()

    class Model:
        def bind_tools(self, tools):
            assert tools == [legacy_tool]
            return self

        async def astream(self, messages):
            prompts.append(deepcopy(messages))
            if len(prompts) <= 2:
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {"name": legacy_tool.name, "args": '{"city":"杭州"}', "id": f"call-{len(prompts)}", "index": 0}
                    ],
                )
            else:
                yield AIMessageChunk(content="原有回答")

    monkeypatch.setattr("agentdevstu.config.llm_providers.create_llm", lambda name: Model())
    monkeypatch.setattr(
        api, "_load_agent_capabilities", AsyncMock(return_value=[{"capability": cap, "data_source": None}])
    )
    monkeypatch.setattr(api, "_build_data_tools", lambda *args, **kwargs: [legacy_tool])
    events = asyncio.run(run())
    assert not any(event["type"] == "error" for event in events), events
    assert saved[-1].content == "原有回答"
    assert executed == [{"city": "杭州"}] and len(prompts) == 3
    tool_messages = [m for m in prompts[-1] if getattr(m, "type", None) == "tool"]
    assert len(tool_messages) == 2 and all(m.content == str(raw) for m in tool_messages)
    observations = [
        entry for entry in saved[-1].metadata_json.get("debug_trace", []) if entry["stage"] == "runtime_observation"
    ]
    assert len(observations) == (2 if enabled else 0)
    if enabled and not adapter_failure:
        assert [entry["detail"]["reused_cache"] for entry in observations] == [False, True]
        assert all(entry["detail"]["source_type"] == "DATA" for entry in observations)
    public = next(event for event in events if event["type"] == "done").get("debug_trace", [])
    assert any(entry["stage"] == "runtime_observation" for entry in public) == (enabled and allowed)


@pytest.mark.parametrize("unreadable", [False, True])
def test_stream_retrieval_uses_existing_results_and_does_not_change_model_input(monkeypatch, unreadable):
    from agentdevstu.api import conversations as api

    run, saved, calls, _ = stream_fixture(monkeypatch, enabled=False, content="分析内部资料")
    monkeypatch.setattr(api, "capability_shadow_enabled", lambda path: True)

    def retrieve(agent, query, db, sources=None, stats=None):
        async def execute():
            if unreadable:
                stats.update(unreadable_count=1)
                return "原有文档读取失败说明"
            sources.append({"type": "knowledge_base", "document_id": "doc", "name": "说明", "description": "原有知识"})
            return "原有知识"

        return execute()

    monkeypatch.setattr(api, "_retrieve_knowledge", retrieve)
    monkeypatch.setattr(api, "retrieve_memories", AsyncMock(return_value=[SimpleNamespace(id="mem")]))
    monkeypatch.setattr(api, "format_memories_for_prompt", lambda memories: "原有记忆")
    events = asyncio.run(run())
    assert not any(event["type"] == "error" for event in events), events
    assert saved[-1].content == "原有回答" and len(calls) == 1
    text = json.dumps(calls[0], ensure_ascii=False)
    assert "原有记忆" in text and ("原有文档读取失败说明" if unreadable else "原有知识") in text
    assert "Observation" not in text
    entries = [
        entry["detail"] for entry in saved[-1].metadata_json["debug_trace"] if entry["stage"] == "runtime_observation"
    ]
    assert [(entry["source_type"], entry["observation_status"]) for entry in entries] == [
        ("KNOWLEDGE", "FAILED" if unreadable else "SUCCESS"),
        ("MEMORY", "SUCCESS"),
    ]


def test_proxy_stream_maps_readiness_without_adding_any_local_model_call(monkeypatch):
    from agentdevstu.api import conversations as api

    run, saved, calls, _ = stream_fixture(monkeypatch, enabled=False, proxy=True)
    monkeypatch.setattr(api, "capability_shadow_enabled", lambda path: True)
    monkeypatch.setattr(
        "agentdevstu.agents.proxy_executor.execute_proxy_agent",
        AsyncMock(
            return_value={
                "success": False,
                "requires_input": True,
                "error": "请补充城市",
                "resolution": {"blockingMissingFields": [{"field": "city"}]},
            }
        ),
    )
    events = asyncio.run(run())
    assert not any(event["type"] == "error" for event in events), events
    assert calls == [] and saved[-1].content == "请补充城市"
    observation = saved[-1].metadata_json["debug_trace"][0]["detail"]
    assert observation["observation_status"] == "NOT_READY"
    assert observation["missing_inputs_count"] == 1


def test_generic_tool_adapter_is_descriptive_and_does_not_execute():
    observed = tool(Kind.TOOL).observe({"success": True, "output": "original"}, "id")
    assert observed.source_type == Kind.TOOL and observed.status == Status.SUCCESS
    assert observed.raw_result["output"] == "original"
