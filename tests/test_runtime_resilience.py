import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from cortexa.agents import proxy_executor
from cortexa.api import user_questions
from cortexa.runtime import background
from cortexa.runtime.completion import CompletionReview, validate_completion
from cortexa.runtime.proxy import contract_signature
from cortexa.runtime.reconciliation import verified_result
from cortexa.runtime.state import GoalState


def agent():
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="代理",
        input_schema={"type": "object", "properties": {"input": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        proxy_config={"endpoint": "https://proxy.test/run", "retry": 5, "request_mapping": {"prompt": "$.input"}},
    )


@pytest.mark.parametrize("case", ["failed_json", "timeout", "bad_output", "server_error"])
def test_ordinary_proxy_is_bounded_and_never_blindly_reposts(case):
    target = agent()
    response = {"ok": False, "status": "failed", "error": "已失败"} if case == "failed_json" else {"answer": 42}
    send = AsyncMock(side_effect=httpx.ReadTimeout("mock")) if case == "timeout" else AsyncMock(return_value=response)
    if case == "server_error":
        req = httpx.Request("POST", "https://proxy.test/run")
        send = AsyncMock(
            side_effect=httpx.HTTPStatusError("mock", request=req, response=httpx.Response(500, request=req))
        )
    with (
        patch.object(proxy_executor, "_get_version_id", AsyncMock(return_value=None)),
        patch.object(proxy_executor, "_save_run", AsyncMock()),
        patch.object(proxy_executor, "send_proxy_request", send),
    ):
        result = asyncio.run(proxy_executor.execute_proxy_agent(target, {"input": "任务"}, SimpleNamespace()))
    assert not result["success"]
    assert send.await_count == 1
    assert send.call_args.kwargs["max_response_bytes"] == 128000
    assert result["result_unknown"] == (case in {"timeout", "server_error"})


def test_ordinary_stream_interruption_retains_readonly_recovery_identity():
    from cortexa.conversation.questions import UserQuestionPause

    target = agent()

    async def send(cfg, body, **kwargs):
        await kwargs["on_event"]({"type": "start", "session_id": "original", "request_id": "r1"})
        raise httpx.ReadTimeout("mock")

    with (
        patch.object(proxy_executor, "_get_version_id", AsyncMock(return_value=None)),
        patch.object(proxy_executor, "_save_run", AsyncMock()),
        patch.object(proxy_executor, "send_proxy_request", AsyncMock(side_effect=send)),
    ):
        with pytest.raises(UserQuestionPause) as error:
            asyncio.run(proxy_executor.execute_proxy_agent(target, {"input": "任务"}, SimpleNamespace()))
    pause = error.value
    assert pause.question["can_recover"] and pause.question["status"] == "interrupted"
    assert pause.context["run"]["remote_execution"]["session_id"] == "original"
    assert pause.context["run"]["request_body"] == {"prompt": "任务"}


@pytest.mark.parametrize("fault", ["running", "session", "prompt", "signature", "output", "request_id", "oversize"])
def test_reconciliation_proof_blocks_wrong_or_unfinished_results(fault):
    target = agent()
    run = {
        "input": {"input": "原任务"},
        "request_body": {"prompt": "原任务"},
        "remote_execution": {"session_id": "original", "request_id": "r1", "signature": contract_signature(target)},
    }
    remote = {
        "session_id": "original",
        "request_id": "r1",
        "status": "completed",
        "answered_prompt": "原任务",
        "answer": "完成报告",
    }
    if fault == "running":
        remote["status"] = "running"
    if fault == "session":
        remote["session_id"] = "other"
    if fault == "prompt":
        remote["answered_prompt"] = "other"
    if fault == "signature":
        run["remote_execution"]["signature"] = "changed"
    if fault == "output":
        remote["answer"] = 42
    if fault == "request_id":
        remote["request_id"] = "other"
    if fault == "oversize":
        remote["answer"] = "x" * 130000
    with pytest.raises(HTTPException):
        verified_result(target, run, remote)


def test_structured_completion_needs_real_sources_and_per_agent_denial():
    state = GoalState(denied_agents=["A"])
    payload = {
        "goal": {"raw_request": "完成计划"},
        "observations": [{"action_id": "real", "source_type": "DATA", "status": "SUCCESS"}],
    }
    good = CompletionReview(
        answer="完成", requirements=[{"requirement": "月度销量", "observation_ids": ["real"], "satisfied": True}]
    )
    assert validate_completion(good, state, payload) is None
    bad = CompletionReview(
        answer="完成", requirements=[{"requirement": "月度销量", "observation_ids": ["invented"], "satisfied": True}]
    )
    assert validate_completion(bad, state, payload)
    assert validate_completion(CompletionReview(answer="完成", denied_agents=["B"]), state, payload)
    assert validate_completion(CompletionReview(answer="完成", unresolved=["渠道基数"]), state, payload)
    payload["clarifications"] = ["接受标明数据缺失的草案"]
    assert validate_completion(CompletionReview(answer="草案", unresolved=["渠道基数"]), state, payload) is None


def test_initial_stream_detaches_and_explicit_stop_cancels_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(background, "CONTROL_ROOT", tmp_path)

    async def scenario():
        completed = asyncio.Event()
        release = asyncio.Event()

        async def produce():
            yield 'data: {"type":"start"}\n\n'
            await release.wait()
            completed.set()
            yield 'data: {"type":"done","status":"COMPLETE"}\n\n'

        gid = uuid.uuid4()
        response = user_questions.wrap_completion(StreamingResponse(produce()), uuid.uuid4(), goal_id=gid)
        iterator = response.body_iterator
        await anext(iterator)
        await iterator.aclose()
        assert str(gid) in background.workers
        release.set()
        worker = background.workers[str(gid)]
        await worker
        assert completed.is_set() and str(gid) not in background.workers
        release.clear()
        completed.clear()
        gid = uuid.uuid4()
        response = user_questions.wrap_completion(StreamingResponse(produce()), uuid.uuid4(), goal_id=gid)
        await anext(response.body_iterator)
        worker = background.request_stop(gid)
        await asyncio.gather(worker, return_exceptions=True)
        await response.body_iterator.aclose()
        assert not completed.is_set() and str(gid) not in background.workers

    asyncio.run(scenario())


def test_generic_initial_proxy_reconciliation_is_owned_and_does_not_repost(tmp_path, monkeypatch):
    from test_goal_collaboration import URL, collect, setup, start

    if not URL:
        pytest.skip("Isolated PostgreSQL required")
    from langchain_core.messages import AIMessageChunk
    from test_goal_loop import FakeModel, tool_call
    from test_goal_proxy import configure

    from cortexa.api import goals

    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:

            async def respond(request):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    text='data: {"type":"start","session_id":"original","request_id":"r1"}\n\n'
                    'data: {"type":"text_delta","content":"未完成"}\n\n',
                )

            target, sent = await configure(ctx, monkeypatch, respond=respond)
            model = FakeModel(
                [
                    [tool_call(name="agent_" + target.id.hex, args={})],
                    [AIMessageChunk(content="根据找回的报告完成任务")],
                ]
            )
            monkeypatch.setattr(goals, "create_llm", lambda *_: model)
            stopped = await start(ctx, "first-reconcile", "@销售Agent 查询销售")
            gid = uuid.UUID(stopped["goal_id"])
            assert stopped["can_reconcile"] and stopped["reason"] == "action_result_unknown"
            reader = AsyncMock(
                return_value={
                    "session_id": "original",
                    "request_id": "r1",
                    "status": "completed",
                    "answered_prompt": "@销售Agent 查询销售",
                    "answer": "销量42台",
                }
            )
            monkeypatch.setattr(proxy_executor, "read_proxy_turn", reader)
            with pytest.raises(HTTPException):
                await goals.reconcile(uuid.uuid4(), gid)
            reader.assert_not_awaited()
            response = await goals.reconcile(ctx.conv, gid)
            with pytest.raises(HTTPException):
                await goals.reconcile(ctx.conv, gid)
            result = (await collect(response))[-1]
            assert result["status"] == "COMPLETE"
            assert len(sent) == 1
            row = await ctx.store.get(ctx.conv, gid)
            snapshot = ctx.store.files.read(row.id, row.artifacts["snapshot"])
            assert next(iter(snapshot["proxy_runs"].values()))["recovered"]
            assert any(item.get("status") == "SUCCESS" for item in snapshot["cache"].values())

    asyncio.run(scenario())


def test_actual_goal_disconnect_continues_and_stop_is_explicit(tmp_path, monkeypatch):
    from test_goal_collaboration import URL, setup

    if not URL:
        pytest.skip("Isolated PostgreSQL required")
    from langchain_core.messages import AIMessageChunk

    from cortexa.api import goals

    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            release = asyncio.Event()
            started = asyncio.Event()

            class Model:
                def bind(self, **kwargs):
                    return self

                async def astream(self, messages):
                    started.set()
                    await release.wait()
                    yield AIMessageChunk(content="完成后台任务")

            monkeypatch.setattr(goals, "create_llm", lambda *_: Model())
            response = await goals.create_goal_stream(
                ctx.conv, goals.GoalRequest(content="你好", idempotency_key="detached")
            )
            initial = json.loads((await anext(response.body_iterator))[6:])
            gid = uuid.UUID(initial["goal_id"])
            await started.wait()
            worker = background.workers[str(gid)]
            await response.body_iterator.aclose()
            assert (await ctx.store.get(ctx.conv, gid)).status == "RUNNING"
            release.set()
            await worker
            assert (await ctx.store.get(ctx.conv, gid)).status == "COMPLETE"
            release.clear()
            started.clear()
            response = await goals.create_goal_stream(
                ctx.conv, goals.GoalRequest(content="你好", idempotency_key="stop")
            )
            initial = json.loads((await anext(response.body_iterator))[6:])
            gid = uuid.UUID(initial["goal_id"])
            await started.wait()
            result = await goals.stop_goal(ctx.conv, gid)
            assert result["status"] == "WAITING" and result["reason"] == "cancelled"
            await response.body_iterator.aclose()

    asyncio.run(scenario())


def test_standalone_proxy_recovery_reads_once_and_marks_card_answered(tmp_path, monkeypatch):
    from test_goal_collaboration import URL, collect, setup

    if not URL:
        pytest.skip("Isolated PostgreSQL required")
    from test_goal_proxy import configure

    from cortexa.conversation import questions
    from cortexa.db.models import Agent
    from cortexa.runtime.artifacts import ArtifactStore

    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            target, sent = await configure(ctx, monkeypatch)
            monkeypatch.setattr(user_questions, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "async_session_factory", ctx.store.sessions)
            files = ArtifactStore(tmp_path / "question-files")
            monkeypatch.setattr(questions, "files", files)
            monkeypatch.setattr(user_questions, "files", files)
            async with ctx.store.sessions() as db:
                fresh = await db.get(Agent, target.id)
                signature = contract_signature(fresh)
            public = questions.question({"question": "检查原会话"}, target)
            public.update(status="interrupted", can_recover=True)
            await questions.save_question(
                ctx.conv,
                public,
                {
                    "engine": "proxy_reconcile",
                    "agent_id": str(target.id),
                    "run": {
                        "input": {"input": "任务"},
                        "request_body": {"input": "任务"},
                        "remote_execution": {"session_id": "original", "signature": signature},
                    },
                },
                sessions=ctx.store.sessions,
            )
            reader = AsyncMock(
                return_value={
                    "status": "completed",
                    "session_id": "original",
                    "answered_prompt": "任务",
                    "answer": "原报告",
                }
            )
            monkeypatch.setattr(proxy_executor, "read_proxy_turn", reader)
            response = await user_questions.recover_answer(ctx.conv, uuid.UUID(public["id"]))
            with pytest.raises(HTTPException):
                await user_questions.recover_answer(ctx.conv, uuid.UUID(public["id"]))
            events = await collect(response)
            assert events[-1]["type"] == "done" and events[-1]["content"] == "原报告"
            assert not sent
            assert (await user_questions.pending_question(ctx.conv))["question"] is None

    asyncio.run(scenario())


def test_async_proxy_acknowledgement_is_not_completion():
    from cortexa.agents.proxy_executor import ProxyResultUnknown, validated_proxy_output

    with pytest.raises(ProxyResultUnknown):
        validated_proxy_output(agent(), {"status": "running", "session_id": "s1", "answer": "已接收"})


def test_empty_lookup_is_valid_negative_evidence_but_not_sales_facts():
    state = GoalState()
    payload = {"observations": [{"action_id": "empty", "source_type": "DATA", "status": "EMPTY"}]}
    review = CompletionReview(
        answer="没有检索到",
        requirements=[
            {"requirement": "是否存在相关数据", "kind": "lookup", "satisfied": True, "observation_ids": ["empty"]}
        ],
    )
    assert validate_completion(review, state, payload) is None
    review.requirements[0].kind = "data"
    assert validate_completion(review, state, payload)
