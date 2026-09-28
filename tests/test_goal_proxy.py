"""Strict Proxy input/output and a real Goal SSE loop with isolated HTTP transport."""

import asyncio
import copy
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessageChunk
from pydantic import ValidationError
from sqlalchemy import select
from test_goal_collaboration import CONFIG, URL, collect, setup, start
from test_goal_loop import FakeModel, binding, tool_call

from cortexa.agents import proxy_executor
from cortexa.api import goals as api
from cortexa.db.models import Agent, AgentCollaboration
from cortexa.runtime.proxy import ProxyInvocation, build_invocation, enabled, validate_configuration


def proxy_agent(schema=None, fields=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        agent_type="proxy",
        input_schema=schema or {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]},
        output_schema={},
        proxy_config={
            "endpoint": "https://external.test/run",
            "retry": 5,
            "headers": {"Authorization": "Bearer PRIVATE_TOKEN"},
            "supplemental_prompt": "DO_NOT_FORWARD",
            "prompt_resolution": {"enabled": True},
            "input_resolution": {"enabled": True},
            "goal_contract": {"enabled": True, "fields": fields if fields is not None else {"input": ["goal_task"]}},
        },
    )


def payload(agent, inputs=None):
    return {
        "goal": {"raw_request": "查询销售", "objective": "查询销售"},
        "participant_inputs": {str(agent.id): inputs or {}},
        "messages": ["PRIVATE_CONVERSATION"],
        "memory": "PRIVATE_MEMORY",
        "knowledge": "PRIVATE_KNOWLEDGE",
        "system": "PRIVATE_SYSTEM",
        "observations": [],
    }


def test_default_deny_and_task_projection_never_copy_context():
    agent = proxy_agent()
    data = payload(agent, {"history": "PRIVATE_HISTORY", "input": "MODEL_CANNOT_REPLACE_TASK"})
    before = copy.deepcopy(data)
    projected, body, missing, oversized, trace = build_invocation(agent, data, {}, 32000)
    assert body == projected == {"input": "查询销售"} and not missing and not oversized
    assert data == before and "PRIVATE" not in json.dumps(body)
    assert trace["selected_fields"] == ["input"] and trace["rejected_field_count"] == 2
    assert trace["compression"] == "structural_projection"
    assert "primary_system_prompt" in trace["denied_context"]
    assert not enabled(agent, CONFIG)
    with pytest.raises(ValidationError):
        ProxyInvocation.model_validate({"inputs": {"input": "PRIVATE_SYSTEM"}})
    with pytest.raises(ValidationError):
        ProxyInvocation.model_validate({"task": "PRIVATE_SYSTEM"})


def test_nested_explicit_fields_only_and_no_coercion_or_inference():
    schema = {
        "type": "object",
        "properties": {
            "customer": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
        },
        "required": ["customer"],
    }
    agent = proxy_agent(schema, {"customer": ["explicit"]})
    projected, body, missing, _, trace = build_invocation(
        agent, payload(agent, {"customer": {"city": "杭州", "full_history": "SECRET"}, "admin": True}), {}, 32000
    )
    assert body == {"customer": {"city": "杭州"}} and not missing
    assert trace["rejected_field_count"] == 2
    _, _, missing, _, _ = build_invocation(agent, payload(agent, {"customer": {"city": 42}}), {}, 32000)
    assert missing == ["/customer/city"]
    _, _, missing, _, _ = build_invocation(agent, payload(agent, {"customer": {}}), {}, 32000)
    assert missing == ["/customer/city"]


@pytest.mark.parametrize(
    "source,value,pointer",
    [("observation_facts", [{"city": "杭州"}], "/0/city"), ("observation_summary", "已有摘要", "")],
)
def test_only_selected_successful_observation_field(source, value, pointer):
    agent = proxy_agent(fields={"input": [source]})
    data = payload(agent)
    ident = str(uuid.uuid4())
    data["observations"] = [
        {
            "action_id": ident,
            "status": "SUCCESS",
            "facts": value if source == "observation_facts" else [],
            "summary": value if source == "observation_summary" else "SECRET_SUMMARY",
            "raw_result": "SECRET_RAW",
        }
    ]
    args = {"observation_bindings": {"input": {"action_id": ident, "source": source, "pointer": pointer}}}
    projected, _, missing, _, trace = build_invocation(agent, data, args, 32000)
    assert projected == {"input": "杭州" if source == "observation_facts" else "已有摘要"} and not missing
    assert trace["sources"]["input"] == source
    data["observations"][0]["status"] = "FAILED"
    assert build_invocation(agent, data, args, 32000)[2] == ["/input"]
    args["observation_bindings"]["input"]["action_id"] = str(uuid.uuid4())
    assert build_invocation(agent, data, args, 32000)[2] == ["/input"]


def test_budget_counts_mapped_wire_body_without_string_truncation():
    agent = proxy_agent(fields={"input": ["explicit"]})
    agent.proxy_config["goal_contract"]["input_budget"] = 256
    text = "完整内容。" * 100
    result = build_invocation(agent, payload(agent, {"input": text}), {}, 32000)
    assert result[0]["input"] == text and result[3]
    agent.proxy_config["request_mapping"] = {"query": "$.input", "fixed": "X" * 500}
    assert build_invocation(agent, payload(agent, {"input": "短"}), {}, 32000)[3]


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"type": "object", "properties": {"input": {"$ref": "https://external.test/schema"}}},
        {"type": "object", "properties": {"input": {"type": "object"}}},
        {"type": "object", "properties": {"input": {"anyOf": [{"type": "string"}]}}},
    ],
)
def test_dynamic_or_unscoped_contract_rejected(schema):
    agent = proxy_agent()
    agent.input_schema = schema
    with pytest.raises(ValueError):
        validate_configuration(agent)


async def configure(ctx, monkeypatch, *, fields=None, schema=None, output=None, respond=None):
    target = ctx.targets[0]
    spec = proxy_agent(schema, fields)
    async with ctx.store.sessions() as db:
        agent = await db.get(Agent, target.id)
        agent.agent_type = "proxy"
        agent.input_schema = spec.input_schema
        agent.output_schema = output or {}
        agent.proxy_config = spec.proxy_config
        await db.commit()
    monkeypatch.setattr(
        api, "execution_config", lambda: {"features": {**CONFIG["features"], "goal_proxy_enabled": True}}
    )
    sent = []

    async def handle(request):
        sent.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer PRIVATE_TOKEN"
        if respond:
            return await respond(request)
        return httpx.Response(200, json={"answer": "销量 2"})

    client = httpx.AsyncClient
    monkeypatch.setattr(
        proxy_executor.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handle), **kw)
    )
    return target, sent


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_goal_proxy_no_resolver_model_mapping_and_file_audit(tmp_path, monkeypatch):
    asyncio.run(success_scenario(tmp_path, monkeypatch))


async def success_scenario(tmp_path, monkeypatch):
    async with setup(tmp_path, monkeypatch) as ctx:
        target, sent = await configure(ctx, monkeypatch)
        model = FakeModel([[tool_call(name="agent_" + target.id.hex, args={})], [AIMessageChunk(content="销量为 2")]])
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        done = await start(ctx, "proxy-success", "@销售Agent 查询销售")
        assert done["status"] == "COMPLETE", done
        assert sent == [{"input": "@销售Agent 查询销售"}]
        assert done["consumed"]["llm_calls"] == 2 and done["consumed"]["agent_calls"] == 1
        assert len(model.calls) == 2 and "销量 2" in str(model.calls[-1])
        row = await ctx.store.get(ctx.conv, uuid.UUID(done["goal_id"]))
        snapshot = ctx.store.files.read(row.id, row.artifacts["snapshot"])
        run = next(iter(snapshot["proxy_runs"].values()))
        assert run["status"] == "SUCCESS" and run["request_body"] == sent[0]
        assert "PRIVATE_TOKEN" not in json.dumps(snapshot)
        async with ctx.store.sessions() as db:
            audit = await db.scalar(select(AgentCollaboration))
            assert audit.status == "success" and audit.result_content is None


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_proxy_missing_explicit_input_resume_changes_cache_key(tmp_path, monkeypatch):
    asyncio.run(missing_scenario(tmp_path, monkeypatch))


async def missing_scenario(tmp_path, monkeypatch):
    async with setup(tmp_path, monkeypatch) as ctx:
        target, sent = await configure(ctx, monkeypatch, fields={"input": ["explicit"]})
        model = FakeModel(
            [
                [tool_call(name="agent_" + target.id.hex, args={})],
                [tool_call(name="agent_" + target.id.hex, args={})],
                [AIMessageChunk(content="完成")],
            ]
        )
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        done = await start(ctx, "proxy-missing", "@销售Agent 查询销售")
        assert done["status"] == "WAITING" and done["reason"] == "missing_inputs" and not sent, done
        resumed = await collect(
            await api.resume_goal(
                ctx.conv,
                uuid.UUID(done["goal_id"]),
                api.ResumeRequest(
                    content="补充参数",
                    revision=done["revision"],
                    participants=[
                        api.ParticipantRequest(
                            agent_id=target.id, inputs={"input": "只查询杭州", "history": "NEVER_SEND"}
                        )
                    ],
                ),
            )
        )
        assert resumed[-1]["status"] == "COMPLETE", resumed
        assert sent == [{"input": "只查询杭州"}]
        assert resumed[-1]["consumed"]["llm_calls"] == 3


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_not_ready_can_acquire_observation_then_invoke(tmp_path, monkeypatch):
    asyncio.run(observation_scenario(tmp_path, monkeypatch))


async def observation_scenario(tmp_path, monkeypatch):
    async with setup(tmp_path, monkeypatch) as ctx:
        target, sent = await configure(
            ctx,
            monkeypatch,
            fields={"input": ["observation_facts"]},
            schema={"type": "object", "properties": {"input": {"type": "integer"}}, "required": ["input"]},
        )
        b = binding()
        monkeypatch.setattr(
            api,
            "prepare_bindings",
            __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(return_value=([b], [])),
        )

        class Model(FakeModel):
            async def astream(self, messages):
                self.calls.append(copy.deepcopy(messages))
                n = len(self.calls)
                if n == 1:
                    yield tool_call(name="agent_" + target.id.hex, args={})
                elif n == 2:
                    yield tool_call()
                elif n == 3:
                    observed = json.loads(messages[-1].content)["observation_id"]
                    yield tool_call(
                        name="agent_" + target.id.hex,
                        args={"observation_bindings": {"input": {"action_id": observed, "pointer": "/0/sales"}}},
                    )
                else:
                    yield AIMessageChunk(content="完成")

        model = Model([])
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        done = await start(ctx, "proxy-observation", "@销售Agent 查询销售")
        assert done["status"] == "COMPLETE", done
        assert sent == [{"input": 2}] and b.invoke.await_count == 1
        assert done["consumed"]["llm_calls"] == 4 and done["consumed"]["max_replans"] == 1


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
@pytest.mark.parametrize("failure", ["timeout", "cancel", "output_schema"])
def test_proxy_failure_no_retry_or_false_complete(tmp_path, monkeypatch, failure):
    asyncio.run(failure_scenario(tmp_path, monkeypatch, failure))


async def failure_scenario(tmp_path, monkeypatch, failure):
    async with setup(tmp_path, monkeypatch) as ctx:

        async def respond(request):
            if failure == "timeout":
                raise httpx.ReadTimeout("untrusted-secret-endpoint")
            if failure == "cancel":
                raise asyncio.CancelledError()
            return httpx.Response(200, json={"answer": 42})

        target, sent = await configure(
            ctx,
            monkeypatch,
            respond=respond,
            output={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        )
        model = FakeModel(
            [[tool_call(name="agent_" + target.id.hex, args={})], [AIMessageChunk(content="不能伪造完成")]]
        )
        monkeypatch.setattr(api, "create_llm", lambda *_: model)
        response = await api.create_goal_stream(
            ctx.conv, api.GoalRequest(content="@销售Agent 查询销售", idempotency_key="failure")
        )
        events = []
        try:
            async for chunk in response.body_iterator:
                events.append(json.loads(chunk.removeprefix("data: ").strip()))
        except asyncio.CancelledError:
            assert failure == "cancel"
        assert len(sent) == 1  # Existing retry=5 must never cause six external calls.
        goal = uuid.UUID(events[0]["goal_id"])
        row = await ctx.store.get(ctx.conv, goal)
        assert row.status != "COMPLETE"
        assert "untrusted-secret" not in json.dumps(events)
        if failure in ("timeout", "cancel"):
            assert row.state["current_action"]["phase"] == "unknown"
            with pytest.raises(HTTPException):
                await api.resume_goal(ctx.conv, goal, api.ResumeRequest(content="继续", revision=row.revision))
        else:
            assert row.state["reason"] == "unresolved_capability_failure"
