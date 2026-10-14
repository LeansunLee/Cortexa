import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessageChunk
from test_goal_collaboration import URL, collect, executor, setup, start
from test_goal_loop import FakeModel, tool_call
from test_goal_proxy import configure

from cortexa.api import goals
from cortexa.api import user_questions as api
from cortexa.conversation import questions
from cortexa.runtime.adapters import tool_adapter
from cortexa.runtime.artifacts import ArtifactStore
from cortexa.runtime.loop import Binding, InvocationResult
from cortexa.runtime.observations import Observation


def ask_binding(agent):
    tool = questions.ask_user_tool()
    adapter = tool_adapter(tool, str(agent.workspace_id))
    adapter.descriptor.type = "TOOL"
    adapter.descriptor.risk_level = "low"
    adapter.descriptor.requires_confirmation = False
    adapter.descriptor.availability = "available"

    async def invoke(args, action):
        q = questions.question(args, agent)
        return InvocationResult(
            Observation(
                "TOOL", adapter.descriptor.id, action, "NOT_READY", summary=q["question"], metadata={"user_question": q}
            ),
            q["question"],
            {},
        )

    return Binding(tool, adapter, invoke)


def test_answers_validate_choices_and_no_automatic_selection():
    q = {"options": ["目标分解", "发货计划"], "multi_select": False, "allow_free_text": True}
    assert questions.answer_text(q, [1], "杭州") == "发货计划\n杭州"
    for selected, text in [([], ""), ([2], ""), ([0, 1], ""), ([0, 0], "")]:
        with pytest.raises(HTTPException):
            questions.answer_text(q, selected, text)


def test_proxy_waiting_user_is_not_failure_and_keeps_question():
    from cortexa.agents.proxy_executor import _parse_proxy_response

    events = [
        {"type": "start", "session_id": "PRIVATE_SESSION"},
        {"type": "ask_user", "question": "选择方向", "options": ["A", "B"]},
        {"type": "done", "ok": False, "status": "awaiting_user", "answer": "选择方向"},
    ]
    r = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="".join("data: " + json.dumps(e) + "\n\n" for e in events),
    )
    parsed = _parse_proxy_response(r)
    assert parsed["requires_input"] and parsed["user_question"]["options"] == ["A", "B"]
    with pytest.raises(ValueError):
        _parse_proxy_response(
            httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text='data: {"type":"done","ok":false,"status":"failed"}\n\n',
            )
        )


@pytest.mark.skipif(not URL, reason="Isolated PG required")
@pytest.mark.parametrize("kind", ["main", "child", "proxy"])
def test_pause_answer_resume_original_execution(tmp_path, monkeypatch, kind):
    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:
            monkeypatch.setattr(api, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "files", ArtifactStore(tmp_path / "questions"))
            monkeypatch.setattr(api, "files", questions.files)
            target = ctx.targets[0]
            qargs = {"question": "选择规划方向", "options": ["目标分解", "发货计划"]}
            if kind == "main":
                model = FakeModel(
                    [[tool_call(name="ask_user", args=qargs)], [tool_call(name="complete_task", args={"answer":"按目标分解完成", "requirements":[]})]]
                )
                monkeypatch.setattr(goals, "prepare_bindings", AsyncMock(return_value=([ask_binding(ctx.source)], [])))
                monkeypatch.setattr(goals, "create_llm", lambda *_: model)
                prompt = "制定销售计划"
            elif kind == "child":
                child = FakeModel(
                    [[tool_call(name="ask_user", args=qargs)], [tool_call(name="complete_task", args={"answer":"子部门已完成原任务", "requirements":[]})]]
                )
                parent = FakeModel(
                    [
                        [tool_call(name="agent_" + target.id.hex, args={"task": "制定计划"})],
                        [AIMessageChunk(content="已汇总子部门结果")],
                    ]
                )
                monkeypatch.setattr(goals, "create_llm", lambda *_: parent)
                monkeypatch.setattr(executor, "create_llm", lambda *_: child)
                monkeypatch.setattr(executor, "prepare_bindings", AsyncMock(return_value=([ask_binding(target)], [])))
                prompt = "@销售Agent 制定销售计划"
            else:

                async def respond(request):
                    body = json.loads(request.content)
                    if body.get("session_id"):
                        assert body["input"] == "目标分解"
                        return httpx.Response(200, json={"ok": True, "status": "completed", "answer": "真实查询已完成"})
                    return httpx.Response(
                        200,
                        json={
                            "ok": False,
                            "status": "awaiting_user",
                            "answer": "选择规划方向",
                            "session_id": "PRIVATE_SESSION",
                            "pending_ask": qargs,
                        },
                    )

                target, sent = await configure(ctx, monkeypatch, respond=respond)
                parent = FakeModel(
                    [[tool_call(name="agent_" + target.id.hex, args={})], [AIMessageChunk(content="已完成销售计划")]]
                )
                monkeypatch.setattr(goals, "create_llm", lambda *_: parent)
                prompt = "@销售Agent 制定销售计划"
            done = await start(ctx, "decision-" + kind, prompt)
            assert done["status"] == "WAITING" and done["reason"] == "user_decision_required", done
            public = (await api.pending_question(ctx.conv))["question"]
            row = await ctx.store.get(ctx.conv, uuid.UUID(done["goal_id"]))
            assert goals.public_status(row)["user_question"] == public
            assert public["status"] == "pending" and public["options"] == qargs["options"]
            assert "PRIVATE_SESSION" not in json.dumps(done)
            with pytest.raises(HTTPException):
                await goals.resume_goal(
                    ctx.conv,
                    uuid.UUID(done["goal_id"]),
                    goals.ResumeRequest(content="目标分解", revision=done["revision"]),
                )
            response = await api.submit_answer(ctx.conv, uuid.UUID(public["id"]), api.Answer(selected_indices=[0]))
            with pytest.raises(HTTPException) as duplicate:
                await api.submit_answer(ctx.conv, uuid.UUID(public["id"]), api.Answer(selected_indices=[0]))
            assert duplicate.value.status_code == 409
            events = await collect(response)
            assert events[-1]["status"] == "COMPLETE", events
            assert (await api.pending_question(ctx.conv))["question"] is None
            if kind == "main":
                assert "目标分解" in str(model.calls[-1]) and len(model.calls) == 2
            elif kind == "child":
                assert len(child.calls) == 2 and len(parent.calls) == 2
                assert "目标分解" in str(child.calls[-1]) and "子部门已完成原任务" in str(parent.calls[-1])
                assert events[-1]["consumed"]["agent_calls"] == 1
            else:
                assert len(sent) == 2 and sent[-1]["session_id"] == "PRIVATE_SESSION"

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Isolated PG required")
@pytest.mark.parametrize("kind", ["llm", "collaboration", "proxy"])
def test_normal_chat_resumes_saved_tools_or_proxy_session(tmp_path, monkeypatch, kind):
    async def scenario():
        from langchain_core.messages import AIMessage, ToolMessage

        from cortexa.api import conversations
        from cortexa.runtime.loop import serialize_messages
        from cortexa.runtime.proxy import contract_signature

        async with setup(tmp_path, monkeypatch) as ctx:
            monkeypatch.setattr(api, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "files", ArtifactStore(tmp_path / "questions"))
            monkeypatch.setattr(api, "files", questions.files)
            agent = ctx.targets[0] if kind == "collaboration" else ctx.source
            messages = [
                {"role": "user", "content": "原销售计划"},
                AIMessage(content="", tool_calls=[{"id": "query1", "name": "query", "args": {"city": "杭州"}}]),
                ToolMessage(content="真实销量42", tool_call_id="query1"),
                AIMessage(content="", tool_calls=[{"id": "ask1", "name": "ask_user", "args": {"question": "选方向"}}]),
                ToolMessage(content="等待用户回答", tool_call_id="ask1"),
            ]
            public = questions.question({"question": "选方向", "options": ["目标", "发货"]}, agent)
            context = {
                "engine": "llm",
                "agent_id": str(agent.id),
                "messages": serialize_messages(messages),
                "remaining_iterations": 4,
            }
            child = FakeModel(
                [[tool_call(name="query", args={"city": "杭州"})], [AIMessageChunk(content="计划依据真实销量42完成")]]
            )
            query = SimpleNamespace(
                name="query",
                description="query",
                args_schema=__import__("test_goal_loop").Args,
                ainvoke=AsyncMock(return_value="不得重复查询"),
            )
            monkeypatch.setattr(conversations, "_load_agent_capabilities", AsyncMock(return_value=[]))
            monkeypatch.setattr(conversations, "_build_data_tools", lambda *a, **k: [query])
            monkeypatch.setattr("cortexa.tools.web_search.load_search_tools", AsyncMock(return_value=[]))
            parent = FakeModel([[AIMessageChunk(content="汇总协作结果")]])
            monkeypatch.setattr("cortexa.config.llm_providers.create_llm", lambda model: child)
            if kind == "collaboration":
                parent_context = {
                    "engine": "llm",
                    "agent_id": str(ctx.source.id),
                    "messages": serialize_messages([{"role": "user", "content": "原主任务"}]),
                    "siblings": [],
                    "remaining_iterations": 4,
                }
                context["parent"] = parent_context
                ctx.source.model = "parent-test"
                async with ctx.store.sessions() as db:
                    source = await db.get(__import__("cortexa.db.models", fromlist=["Agent"]).Agent, ctx.source.id)
                    source.model = "parent-test"
                    await db.commit()
                monkeypatch.setattr(
                    "cortexa.config.llm_providers.create_llm", lambda model: parent if model == "parent-test" else child
                )
            if kind == "proxy":
                target, sent = await configure(ctx, monkeypatch)
                async with ctx.store.sessions() as db:
                    fresh = await db.get(__import__("cortexa.db.models", fromlist=["Agent"]).Agent, target.id)
                context = {
                    "engine": "proxy",
                    "agent_id": str(target.id),
                    "body": {"input": "原任务"},
                    "answer_field": "input",
                    "session_id": "PRIVATE_SESSION",
                    "signature": contract_signature(fresh),
                }
                public = questions.question({"question": "选方向", "options": ["目标", "发货"]}, target)
            await questions.persist_pause(ctx.conv, questions.UserQuestionPause(public, context))
            events = await collect(
                await api.submit_answer(ctx.conv, uuid.UUID(public["id"]), api.Answer(selected_indices=[0]))
            )
            assert events[-1]["type"] == "done", events
            assert (await api.pending_question(ctx.conv))["question"] is None
            if kind == "proxy":
                assert sent == [{"input": "目标", "session_id": "PRIVATE_SESSION"}]
            else:
                query.ainvoke.assert_not_awaited()
                assert "真实销量42" in str(child.calls[-1]) and len(child.calls) == 2
                if kind == "collaboration":
                    assert "计划依据真实销量42完成" in str(parent.calls[-1])

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Isolated PG required")
def test_disconnected_answer_worker_finishes_once(tmp_path, monkeypatch):
    async def scenario():
        from fastapi.responses import StreamingResponse

        async with setup(tmp_path, monkeypatch) as ctx:
            monkeypatch.setattr(api, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "files", ArtifactStore(tmp_path / "questions"))
            public = questions.question({"question": "选择方向"}, ctx.source)
            await questions.persist_pause(ctx.conv, questions.UserQuestionPause(public, {"engine": "llm"}))
            ready = asyncio.Event()
            calls = []

            async def inner():
                calls.append("once")
                yield 'data: {"type":"start"}\n\n'
                await ready.wait()
                yield 'data: {"type":"done"}\n\n'

            response = api.wrap_completion(StreamingResponse(inner()), ctx.conv, public["id"])
            iterator = response.body_iterator
            await anext(iterator)
            await iterator.aclose()
            assert calls == ["once"]
            assert api._decision_tasks
            ready.set()
            await asyncio.gather(*list(api._decision_tasks))
            assert (await api.pending_question(ctx.conv))["question"] is None
            assert calls == ["once"]

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Isolated PG required")
def test_unknown_proxy_turn_recovers_verified_result_without_reposting(tmp_path, monkeypatch):
    async def scenario():
        from cortexa.agents import proxy_executor

        async with setup(tmp_path, monkeypatch) as ctx:
            monkeypatch.setattr(api, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "async_session_factory", ctx.store.sessions)
            monkeypatch.setattr(questions, "files", ArtifactStore(tmp_path / "questions"))
            monkeypatch.setattr(api, "files", questions.files)

            async def remote(request):
                if json.loads(request.content).get("session_id"):
                    raise httpx.ReadTimeout("lost connection")
                return httpx.Response(
                    200,
                    json={
                        "ok": False,
                        "status": "awaiting_user",
                        "answer": "选方向",
                        "session_id": "private-session",
                        "pending_ask": {"question": "选方向", "options": ["车型结构", "目标分解"]},
                    },
                )

            target, sent = await configure(ctx, monkeypatch, respond=remote)
            model = FakeModel(
                [
                    [tool_call(name="agent_" + target.id.hex, args={})],
                    [AIMessageChunk(content="已使用找回的报告完成计划")],
                ]
            )
            monkeypatch.setattr(goals, "create_llm", lambda *_: model)
            await start(ctx, "recover", "@销售Agent 制定计划")
            public = (await api.pending_question(ctx.conv))["question"]
            await collect(await api.submit_answer(ctx.conv, uuid.UUID(public["id"]), api.Answer(selected_indices=[0])))
            interrupted = (await api.pending_question(ctx.conv))["question"]
            assert interrupted["status"] == "interrupted" and interrupted["can_recover"]
            monkeypatch.setattr(
                proxy_executor,
                "read_proxy_turn",
                AsyncMock(
                    return_value={
                        "status": "completed",
                        "session_id": "wrong",
                        "answered_prompt": "车型结构",
                        "prior_question": "选方向",
                        "answer": "报告已完成",
                    }
                ),
            )
            with pytest.raises(HTTPException):
                await api.recover_answer(ctx.conv, uuid.UUID(public["id"]))
            monkeypatch.setattr(
                proxy_executor,
                "read_proxy_turn",
                AsyncMock(
                    return_value={
                        "status": "completed",
                        "session_id": "private-session",
                        "answered_prompt": "车型结构",
                        "prior_question": "选方向",
                        "answer": "报告已完成，实际销量42",
                    }
                ),
            )
            events = await collect(await api.recover_answer(ctx.conv, uuid.UUID(public["id"])))
            assert events[-1]["status"] == "COMPLETE", events
            assert len(sent) == 2
            assert (await api.pending_question(ctx.conv))["question"] is None
            assert "实际销量42" in str(model.calls[-1])

    asyncio.run(scenario())


@pytest.mark.skipif(not URL, reason="Isolated PG required")
def test_detached_worker_still_stops_on_authorization_revocation(tmp_path, monkeypatch):
    async def scenario():
        from fastapi.responses import StreamingResponse
        from cortexa.memory.integration import request_session_token

        async with setup(tmp_path, monkeypatch) as ctx:
            monkeypatch.setattr(api, "async_session_factory", ctx.store.sessions)
            ctx.actor.memberships[ctx.actor.workspace_id].update(id=uuid.uuid4(), role_ids=[])
            checked = AsyncMock(return_value="authorization_changed")
            monkeypatch.setattr("cortexa.security.http.stream_authorization_reason", checked)
            stopped = asyncio.Event()

            async def inner():
                try:
                    yield 'data: {"type":"start"}\n\n'
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

            token = request_session_token.set("test-session-token")
            try:
                response = api.wrap_completion(StreamingResponse(inner()), ctx.conv, uuid.uuid4())
                await anext(response.body_iterator)
                await response.body_iterator.aclose()
                await asyncio.wait_for(stopped.wait(), timeout=5)
                checked.assert_awaited()
            finally:
                request_session_token.reset(token)

    asyncio.run(scenario())
