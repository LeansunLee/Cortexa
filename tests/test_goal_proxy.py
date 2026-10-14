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
from cortexa.db.models import Agent, AgentCollaboration, Workspace
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


def test_all_sources_allowed_but_only_declared_inputs_are_sent():
    agent = proxy_agent()
    data = payload(agent, {"history": "PRIVATE_HISTORY", "input": "用户指定的任务"})
    before = copy.deepcopy(data)
    projected, body, missing, oversized, trace = build_invocation(agent, data, {}, 32000)
    assert body == projected == {"input": "用户指定的任务"} and not missing and not oversized
    assert data == before and "PRIVATE" not in json.dumps(body)
    assert trace["selected_fields"] == ["input"] and trace["rejected_field_count"] == 1
    assert trace["compression"] == "structural_projection"
    assert "primary_system_prompt" in trace["denied_context"]
    assert not enabled(agent, CONFIG)
    with pytest.raises(ValidationError):
        ProxyInvocation.model_validate({"inputs": {"input": "PRIVATE_SYSTEM"}})
    with pytest.raises(ValidationError):
        ProxyInvocation.model_validate({"task": "   "})


def test_task_field_selection_does_not_fill_unrelated_fields():
    schema = {"type": "object", "properties": {"requirement": {"type": "string"}, "target_users": {"type": "string"}, "priority": {"type": "integer"}}, "required": ["requirement"]}
    agent = proxy_agent(schema, fields={})
    projected, _, missing, _, _ = build_invocation(agent, payload(agent), {"task_fields": ["requirement"]}, 32000)
    assert projected == {"requirement": "查询销售"} and not missing
    from cortexa.runtime.proxy import policy
    assert all(set(sources) == {"explicit", "goal_task", "observation_facts", "observation_summary"} for sources in policy(agent).fields.values())


def test_proxy_invitation_and_discovery_are_always_allowed():
    from cortexa.runtime.collaboration import settings
    agent = proxy_agent()
    agent.collaboration = {"allow_incoming": False, "discoverable": False}
    assert settings(agent).allow_incoming and settings(agent).discoverable


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
        target, sent = await configure(ctx, monkeypatch, fields={"input": ["explicit"]}, schema={"type": "object", "properties": {"input": {"type": "string", "enum": ["只查询杭州"]}}, "required": ["input"]})
        async with ctx.store.sessions() as db:
            workspace = await db.get(Workspace, ctx.actor.workspace_id)
            await db.refresh(workspace, ["runtime_policy"])
            workspace.runtime_policy = {**workspace.runtime_policy, "budget": {"max_replans": 0}}
            await db.commit()
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
                    observed = json.loads(next(m.content for m in reversed(messages) if m.type == "tool"))["observation_id"]
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
@pytest.mark.parametrize("failure", ["timeout", "cancel", "output_schema", "rejected", "server_error", "terminal_error"])
def test_proxy_failure_no_retry_or_false_complete(tmp_path, monkeypatch, failure):
    asyncio.run(failure_scenario(tmp_path, monkeypatch, failure))


async def failure_scenario(tmp_path, monkeypatch, failure):
    async with setup(tmp_path, monkeypatch) as ctx:

        async def respond(request):
            if failure == "timeout":
                raise httpx.ReadTimeout("untrusted-secret-endpoint")
            if failure == "cancel":
                raise asyncio.CancelledError()
            if failure == "terminal_error":
                return httpx.Response(200, headers={"content-type":"text/event-stream"},
                    text='data: {"type":"error","message":"untrusted-secret-remote-error"}\n\n')
            if failure == "rejected": return httpx.Response(422, json={"detail": "PRIVATE_REMOTE_ERROR"})
            if failure == "server_error": return httpx.Response(500, json={"detail": "PRIVATE_REMOTE_ERROR"})
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
        if failure in ("timeout", "cancel", "server_error"):
            assert row.state["current_action"]["phase"] == "unknown"
            with pytest.raises(HTTPException):
                await api.resume_goal(ctx.conv, goal, api.ResumeRequest(content="继续", revision=row.revision))
        elif failure == "rejected":
            assert row.state["reason"] == "proxy_request_rejected"
            assert row.state["current_action"]["phase"] == "completed"
            assert "PRIVATE_REMOTE_ERROR" not in json.dumps(events)
            snapshot = ctx.store.files.read(row.id, row.artifacts["snapshot"])
            rejected = next(iter(snapshot["proxy_runs"].values()))
            assert rejected["status"] == "REJECTED" and rejected["http_status"] == 422
            # A user-requested resume is allowed; still no automatic transport retry.
            model.rounds = iter([[tool_call(name="agent_" + target.id.hex, args={})]])
            resumed = await api.resume_goal(ctx.conv, goal, api.ResumeRequest(content="配置已检查，继续", revision=row.revision))
            await collect(resumed)
            assert len(sent) == 2
        else:
            assert row.state["reason"] == "unresolved_capability_failure"
            if failure == "terminal_error":
                snapshot = ctx.store.files.read(row.id, row.artifacts["snapshot"])
                assert next(iter(snapshot["proxy_runs"].values()))["status"] == "FAILED"


def test_proxy_mapping_must_reference_declared_schema_field():
    agent = proxy_agent({"type": "object", "properties": {"requirement": {"type": "string"}}, "required": ["requirement"]})
    agent.proxy_config["request_mapping"] = {"prompt": "$.input"}
    with pytest.raises(ValueError, match="未在输入 Schema 中声明"):
        validate_configuration(agent)
    agent.proxy_config["request_mapping"] = {"prompt": "$.requirement"}
    projected, body, missing, _, _ = build_invocation(agent, payload(agent), {}, 32000)
    assert projected == {"requirement": "查询销售"} and body == {"prompt": "查询销售"} and not missing


SALES_SUBTASK = (
    "为制定2026年10月国内整车销售计划提供数据支持：1）近6个月（2026年4月-9月）"
    "分月度的整体销量、销售额及目标达成率；2）分车型的销售结构（各车型销量占比）；"
    "3）分区域/省份的销量与达成率排名；4）当前工厂库存与经销商渠道库存情况（如有）；"
    "5）重点经销商表现。输出真实数据基线，供10月目标测算与分解使用。"
)


def test_decomposed_sales_task_reaches_external_prompt_with_provenance():
    agent = proxy_agent()
    agent.proxy_config["request_mapping"] = {"prompt": "$.input"}
    data = payload(agent)
    data["goal"]["raw_request"] = "制定10月销售计划"
    projected, body, missing, oversized, trace = build_invocation(agent, data, {"task": SALES_SUBTASK}, 32000)
    assert projected == {"input": SALES_SUBTASK}
    assert body == {"prompt": SALES_SUBTASK}
    assert not missing and not oversized
    assert trace["sources"] == {"input": "delegated_task"}
    assert "PRIVATE" not in json.dumps(body)
    data["participant_tasks"] = {str(agent.id): "用户指定：只查9月库存"}
    assert build_invocation(agent, data, {"task": SALES_SUBTASK}, 32000)[1] == {"prompt": "用户指定：只查9月库存"}
    data["participant_inputs"][str(agent.id)] = {"input": "用户显式参数"}
    assert build_invocation(agent, data, {"task": SALES_SUBTASK}, 32000)[1] == {"prompt": "用户显式参数"}


def test_subtask_does_not_populate_structured_facts_or_override_observation():
    agent = proxy_agent({"type": "object", "properties": {"input": {"type": "string"}, "count": {"type": "integer"}}, "required": ["input", "count"]})
    data = payload(agent)
    ident = str(uuid.uuid4())
    data["observations"] = [{"action_id": ident, "status": "SUCCESS", "facts": {"count": 7}, "summary": "已有摘要"}]
    args = {"task": SALES_SUBTASK, "observation_bindings": {"count": {"action_id": ident, "pointer": "/count"}}}
    result, _, missing, _, trace = build_invocation(agent, data, args, 32000)
    assert result == {"input": SALES_SUBTASK, "count": 7} and not missing
    assert trace["sources"]["count"] == "observation_facts"
    assert build_invocation(agent, data, {"task": SALES_SUBTASK}, 32000)[2] == ["/count"]
    with pytest.raises(ValidationError):
        ProxyInvocation.model_validate({"task": SALES_SUBTASK, "inputs": {"count": 9}})
    with pytest.raises(ValidationError):
        ProxyInvocation.model_validate({"task": "x" * 8001})



@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_recorded_sales_delegation_corrects_then_dispatches_specific_subtask(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            target, sent = await configure(ctx, monkeypatch)
            async with ctx.store.sessions() as db:
                fresh = await db.get(Agent, target.id)
                fresh.proxy_config = {**fresh.proxy_config, "request_mapping": {"prompt": "$.input"}}
                await db.commit()
            model = FakeModel([
                [tool_call(name="agent_" + target.id.hex, args={"input": SALES_SUBTASK, "priority": "high", "target_users": '["国内销售负责人"]'})],
                [tool_call(ident="corrected", name="agent_" + target.id.hex, args={"task": SALES_SUBTASK})],
                [AIMessageChunk(content="已根据真实数据完成10月销售计划")],
            ])
            monkeypatch.setattr(api, "create_llm", lambda *_: model)
            done = await start(ctx, "sales-subtask", "@销售Agent 制定10月销售计划")
            assert done["status"] == "COMPLETE", done
            assert sent == [{"prompt": SALES_SUBTASK}]
            assert done["consumed"]["agent_calls"] == 1
            row = await ctx.store.get(ctx.conv, uuid.UUID(done["goal_id"]))
            snapshot = ctx.store.files.read(row.id, row.artifacts["snapshot"])
            run = next(iter(snapshot["proxy_runs"].values()))
            assert run["projection"]["sources"] == {"input": "delegated_task"}
            async with ctx.store.sessions() as db:
                audit = await db.scalar(select(AgentCollaboration))
                assert audit.task == SALES_SUBTASK
            assert "不要直接提交" in str(model.calls[0]) or "task" in str(model.calls[1])
    asyncio.run(scenario())


def test_proxy_timeout_honors_config_and_shared_budget():
    from cortexa.runtime.proxy import proxy_timeout
    agent = proxy_agent()
    agent.proxy_config['timeout_ms'] = 1000000
    assert proxy_timeout(agent, 2000) == 1000
    assert proxy_timeout(agent, 160) == 160
    assert proxy_timeout(agent, 90) == 90


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_long_proxy_budget_and_private_start_checkpoint(tmp_path, monkeypatch):
    async def scenario():
        from cortexa.runtime import proxy as runtime_proxy
        async with setup(tmp_path, monkeypatch) as ctx:
            async def respond(request):
                events = [
                    {'type': 'start', 'session_id': 'private-remote-session', 'request_id': 'remote-request'},
                    {'type': 'text_delta', 'content': '销量 2'},
                    {'type': 'done', 'status': 'completed', 'answer': '销量 2'},
                ]
                return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                      text='\n\n'.join('data: ' + json.dumps(e) for e in events) + '\n\n')
            target, _ = await configure(ctx, monkeypatch, respond=respond)
            async with ctx.store.sessions() as db:
                fresh = await db.get(Agent, target.id)
                fresh.proxy_config = {**fresh.proxy_config, 'timeout_ms': 1000000}
                ws = await db.get(Workspace, fresh.workspace_id)
                await db.refresh(ws, ['runtime_policy'])
                ws.runtime_policy = {**ws.runtime_policy, 'budget': {'duration': 600}}
                await db.commit()
            from cortexa.runtime import agent_executor
            prepared_timeouts = []
            prepare = agent_executor.prepare_agent_bindings
            async def capture_bindings(*args, **kwargs):
                items = await prepare(*args, **kwargs)
                prepared_timeouts.extend(b.adapter.descriptor.timeout for b in items)
                return items
            monkeypatch.setattr(agent_executor, 'prepare_agent_bindings', capture_bindings)
            timeouts = []
            original = runtime_proxy.send_proxy_request
            async def capture(*args, **kwargs):
                timeouts.append(kwargs['timeout_seconds'])
                return await original(*args, **kwargs)
            monkeypatch.setattr(runtime_proxy, 'send_proxy_request', capture)
            model = FakeModel([[tool_call(name='agent_' + target.id.hex, args={'task': '查询9月销量'})],
                               [AIMessageChunk(content='销量2')]])
            monkeypatch.setattr(api, 'create_llm', lambda *_: model)
            done = await start(ctx, 'long-proxy', '@销售Agent 查询9月销量')
            assert done['status'] == 'COMPLETE', done
            assert len(timeouts) == 1 and 500 < timeouts[0] < 1000
            assert prepared_timeouts and prepared_timeouts[0] == 600
            row = await ctx.store.get(ctx.conv, uuid.UUID(done['goal_id']))
            snapshot = ctx.store.files.read(row.id, row.artifacts['snapshot'])
            run = next(iter(snapshot['proxy_runs'].values()))
            assert run['remote_execution']['session_id'] == 'private-remote-session'
            assert row.state['child_allocations'][0]['limits']['duration'] > 500
            assert 'remote_execution' not in json.dumps(done)
    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Isolated PostgreSQL required")
def test_failed_remote_tool_does_not_end_successful_goal(tmp_path, monkeypatch):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            async def respond(request):
                events = [
                    {'type':'start','session_id':'original'},
                    {'type':'tool_result','tool':'describe_workbook','status':'error','ok':False},
                    {'type':'tool_result','tool':'query_data','status':'success','ok':True},
                    {'type':'done','status':'completed','ok':True,'answer':'使用业务查询取得真实数据'},
                ]
                return httpx.Response(200, headers={'content-type':'text/event-stream'},
                    text='\n\n'.join('data: ' + json.dumps(e,ensure_ascii=False) for e in events))
            target, sent = await configure(ctx, monkeypatch, respond=respond)
            model = FakeModel([[tool_call(name='agent_' + target.id.hex,args={})],
                               [AIMessageChunk(content='已完成销售分析')]])
            monkeypatch.setattr(api,'create_llm',lambda *_:model)
            result = await start(ctx,'tool-failure-repaired','@销售Agent 查询销售')
            assert result['status'] == 'COMPLETE', result
            assert len(sent) == 1
            row = await ctx.store.get(ctx.conv,uuid.UUID(result['goal_id']))
            snapshot = ctx.store.files.read(row.id,row.artifacts['snapshot'])
            assert next(iter(snapshot['proxy_runs'].values()))['status'] == 'SUCCESS'
            assert any(s['status'] == 'runtime_error' and 'Agent 可继续处理' in s['message']
                       for s in snapshot['execution_steps'])
    asyncio.run(scenario())
