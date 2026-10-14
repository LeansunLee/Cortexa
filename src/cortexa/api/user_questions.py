"""One explicit human-answer entry point for all conversation executors."""

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, ToolMessage, messages_from_dict
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy import select

from cortexa.conversation.questions import (
    UserQuestionPause,
    answer_text,
    answered_question,
    ask_user_tool,
    files,
    pause_after_tool,
    persist_pause,
    proxy_context,
    question,
)
from cortexa.db.engine import async_session_factory
from cortexa.db.models import Conversation, ConversationMessage
from cortexa.runtime.store import own_conversation
from cortexa.security.access import require_agent_use

_decision_tasks = set()

router = APIRouter(prefix="/conversations", tags=["user decisions"])


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_indices: list[StrictInt] = Field(default_factory=list, max_length=12)
    text: str = Field(default="", max_length=4000)


@router.get("/{conv_id}/question")
async def pending_question(conv_id: uuid.UUID):
    async with async_session_factory() as db:
        conv = await own_conversation(db, conv_id)
        public = (conv.metadata_json or {}).get("pending_question")
        if public and public.get("status") in {"answering", "interrupted"}:
            context = files.read(public["id"], conv.metadata_json["question_context"])
            if context["engine"] == "goal":
                from cortexa.api.goals import store

                row = await store.get(conv_id, uuid.UUID(context["goal_id"]))
                if row.status == "COMPLETE":
                    await finish_question(conv_id, public["id"])
                    return {"question": None}
                if row.status != "RUNNING":
                    public = {
                        **public,
                        "status": "interrupted",
                        "can_recover": __import__('cortexa.api.goals', fromlist=['public_status']).public_status(row)['can_reconcile'],
                        "notice": "执行连接已中断，可以检查原会话的结果；不会重新派发任务。",
                    }
        return {"question": public}


@router.post("/{conv_id}/question/{question_id}/answer")
async def submit_answer(conv_id: uuid.UUID, question_id: uuid.UUID, body: Answer):
    # Lock plus question identity makes duplicate clicks and stale tabs harmless.
    async with async_session_factory() as db:
        await own_conversation(db, conv_id, use_agent=True)
        conv = await db.scalar(select(Conversation).where(Conversation.id == conv_id).with_for_update())
        meta = dict(conv.metadata_json or {})
        public = meta.get("pending_question")
        if not public or public["id"] != str(question_id):
            raise HTTPException(409, "问题已更新，请刷新后回答")
        if public["status"] != "pending":
            raise HTTPException(409, "回答已提交，请等待执行结果；不会重复调用 Agent")
        await require_agent_use(db, uuid.UUID(public["agent_id"]))
        text = answer_text(public, body.selected_indices, body.text)
        context = files.read(question_id, meta["question_context"])
        public = {**public, "status": "answering", "answer": text}
        meta["pending_question"] = public
        rows = (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conv_id, ConversationMessage.role == "assistant")
                .order_by(ConversationMessage.created_at.desc())
                .limit(100)
            )
        ).all()
        for row in rows:
            data = dict(row.metadata_json or {})
            if (data.get("user_question") or {}).get("id") == str(question_id):
                data["user_question"] = public
                row.metadata_json = data
        conv.metadata_json = meta
        await db.commit()
    try:
        if context["engine"] == "goal":
            from cortexa.api.goals import ResumeRequest, resume_goal, store

            row = await store.get(conv_id, uuid.UUID(context["goal_id"]))
            token = answered_question.set(str(question_id))
            try:
                response = await resume_goal(conv_id, row.id, ResumeRequest(content=text, revision=row.revision))
            finally:
                answered_question.reset(token)
            return wrap_completion(response, conv_id, question_id)
        return wrap_completion(legacy_response(conv_id, question_id, public, context, text), conv_id, question_id)
    except Exception:
        # Preflight failed before any external execution: safe to edit and resubmit.
        async with async_session_factory() as db:
            conv = await own_conversation(db, conv_id)
            meta = dict(conv.metadata_json or {})
            if (meta.get("pending_question") or {}).get("id") == str(question_id):
                meta["pending_question"] = {**public, "status": "pending"}
                conv.metadata_json = meta
                await db.commit()
        raise


def sse(value):
    return "data: " + json.dumps(value, ensure_ascii=False) + "\n\n"


async def finish_question(conv_id, question_id):
    async with async_session_factory() as db:
        conv = await own_conversation(db, conv_id)
        await db.execute(select(Conversation.id).where(Conversation.id == conv_id).with_for_update())
        meta = dict(conv.metadata_json or {})
        if (meta.get("pending_question") or {}).get("id") == str(question_id):
            meta.pop("pending_question", None)
            meta.pop("question_context", None)
            conv.metadata_json = meta
        # Retain answered card in history without retaining private continuation.
        rows = (
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conv_id, ConversationMessage.role == "assistant")
                .order_by(ConversationMessage.created_at.desc())
                .limit(100)
            )
        ).all()
        for row in rows:
            data = dict(row.metadata_json or {})
            q = data.get("user_question")
            if q and q.get("id") == str(question_id):
                data["user_question"] = {**q, "status": "answered"}
                row.metadata_json = data
        await db.commit()


async def mark_interrupted(conv_id, question_id):
    async with async_session_factory() as db:
        conv = await own_conversation(db, conv_id)
        meta = dict(conv.metadata_json or {})
        public = meta.get("pending_question")
        if public and public["id"] == str(question_id):
            context = files.read(question_id, meta["question_context"])
            public = {key:value for key,value in public.items() if key != 'recovery_claim'}
            meta["pending_question"] = {
                **public,
                "status": "interrupted",
                "can_recover": context["engine"] in {"goal", "proxy", "proxy_reconcile"},
                "notice": "执行已中断，回答已保存。请核实原执行结果；不会自动重复调用。",
            }
            conv.metadata_json = meta
            await db.commit()


def wrap_completion(response, conv_id, question_id=None, *, goal_id=None):
    """The answer owns one bounded worker; browser disconnection only detaches."""

    queue = asyncio.Queue(maxsize=256)
    connection = {"connected": True, "attached": False}

    async def drive():
        from cortexa.memory.integration import request_session_token
        from cortexa.security.access import current_actor
        from cortexa.security.http import stream_authorization_reason

        from cortexa.runtime.background import workers, signal_path, heartbeat, release
        actor, token = current_actor.get(), request_session_token.get()
        current = asyncio.current_task()
        signature = actor.signature() if actor and token else None
        execution_id = goal_id or question_id
        if execution_id:
            workers[str(execution_id)] = current
            heartbeat(execution_id)

        async def watch():
            try:
                while True:
                    await asyncio.sleep(2)
                    if execution_id:
                        heartbeat(execution_id)
                    if goal_id and signal_path(goal_id).exists():
                        current.cancel()
                        return
                    reason = await stream_authorization_reason(
                        actor, token, signature, f"/api/conversations/{conv_id}/question", True
                    ) if actor and token else None
                    if reason:
                        current.cancel()
                        return
            except asyncio.CancelledError:
                raise
            except Exception:
                current.cancel()  # Fail closed if authorization cannot be checked.

        monitor = asyncio.create_task(watch()) if execution_id or (actor and token) else None
        completed = False
        try:
            async for item in response.body_iterator:
                if isinstance(item, str) and item.startswith("data: "):
                    try:
                        event = json.loads(item[6:])
                        completed |= event.get("type") == "done" and event.get("reason") not in {
                            "cancelled",
                            "action_result_unknown",
                        }
                    except ValueError:
                        pass
                if connection['connected']:
                    if not connection['attached']:
                        if queue.full():
                            queue.get_nowait()
                        queue.put_nowait(item)
                    else:
                        await queue.put(item)
            if completed and question_id:
                await finish_question(conv_id, question_id)
        finally:
            if execution_id and workers.get(str(execution_id)) is current:
                workers.pop(str(execution_id), None)
                release(execution_id)
            if not completed and question_id:
                try:
                    await mark_interrupted(conv_id, question_id)
                except Exception:
                    logging.getLogger(__name__).warning("Could not record interrupted answer state")
            if monitor:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            if connection['connected']:
                if not connection['attached'] and queue.full():
                    queue.get_nowait()
                await queue.put(None)


    worker = asyncio.create_task(drive())
    _decision_tasks.add(worker)
    worker.add_done_callback(_decision_tasks.discard)
    from cortexa.runtime.background import workers, heartbeat, release
    execution_id = goal_id or question_id
    if execution_id:
        workers[str(execution_id)] = worker
        heartbeat(execution_id)
        def cleanup(done):
            if workers.get(str(execution_id)) is done:
                workers.pop(str(execution_id), None)
                release(execution_id)
        worker.add_done_callback(cleanup)

    async def generate():
        connection['attached'] = True
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
            await worker
        finally:
            connection['connected'] = False
            while not queue.empty():
                queue.get_nowait()
            # Keep the private worker alive until its existing Goal budget ends.


    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

async def continue_agent(context, answer, conv_id, emit):
    if 'recovered_output' in context:
        output = context.pop('recovered_output')
        text = output.get('answer', '') if isinstance(output, dict) else str(output)
        emit({'type':'token','content':text})
        return text
    async with async_session_factory() as db:
        await own_conversation(db, conv_id, use_agent=True)
        agent = await require_agent_use(db, uuid.UUID(context["agent_id"]))
        if context.get("project_ids"):
            from cortexa.projects.service import get
            for ident in context["project_ids"]:
                await get(db,uuid.UUID(str(ident)))
    if context["engine"] == "proxy_setup":
        from cortexa.agents.proxy_executor import execute_proxy_agent

        async with async_session_factory() as db:
            result = await execute_proxy_agent(
                agent,
                {**context["input_data"], "input": context["input_data"].get("input", "") + "\n用户补充：" + answer},
                db,
                supplemental_prompt=context.get("supplemental_prompt"),
                resolution_context=context.get("resolution_context"),
            )
            await db.commit()
        if not result.get("success"):
            raise RuntimeError("代理请求仍未通过校验")
        output = result["output_data"]
        text = output.get("answer", "") if isinstance(output, dict) else str(output)
        emit({"type": "token", "content": text})
        return text
    if context["engine"] == "proxy":
        from cortexa.agents.proxy_executor import validated_proxy_output, response_limit, send_proxy_request
        from cortexa.runtime.proxy import contract_signature

        if contract_signature(agent) != context["signature"]:
            raise HTTPException(409, "代理配置已改变，请核实后恢复")
        raw = await send_proxy_request(
            agent.proxy_config,
            {**context["body"], context["answer_field"]: answer, "session_id": context["session_id"]},
            max_response_bytes=response_limit(agent.proxy_config),
        )
        if raw.get("user_question"):
            raise UserQuestionPause(question(raw["user_question"], agent), proxy_context(agent, raw, context["body"]))
        if raw.get("ok") is False or raw.get("status") in {"failed", "error"}:
            raise RuntimeError("外部 Agent 续接失败，请核实执行结果")
        output = validated_proxy_output(agent, raw)
        text = output.get("answer", "") if isinstance(output, dict) else str(output)
        emit({"type": "token", "content": text})
        return text
    from cortexa.api.conversations import _build_data_tools, _load_agent_capabilities, _stream_model_response
    from cortexa.config.llm_providers import create_llm
    from cortexa.runtime.loop import serialize_messages
    from cortexa.tools.web_search import load_search_tools

    messages = messages_from_dict(context["messages"])
    original_query = next(
        (
            message.content
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
            and isinstance(message.content, str)
            and not message.content.startswith("以下 JSON 是参考数据")
        ),
        "",
    )
    query = original_query + "\n用户回答：" + answer
    messages.append(HumanMessage(content=answer))
    sources = []
    if context.get("project_ids"):
        from cortexa.projects.service import summaries
        from cortexa.agents.prompts import reference_message
        async with async_session_factory() as project_db:
            project_text, refs = await summaries(project_db,context["project_ids"])
        sources.extend(refs)
        messages.append(reference_message("本轮引用项目（只读参考）",project_text))
    model = create_llm(agent.model)
    async with async_session_factory() as db:
        caps = await _load_agent_capabilities(agent.id, db, query)
        from cortexa.projects.runtime import tools as project_tools
        tools = [
            *project_tools(agent.id,context.get("project_ids",[]),sources),
            *_build_data_tools(caps, sources, model=model, user_query=query, context=messages, agent_id=agent.id),
            *await load_search_tools(agent, db, query, sources),
            ask_user_tool(),
        ]
    bound = model.bind_tools(tools)
    from cortexa.agents.usage import UsageTotals

    usage = UsageTotals()
    cache, calls = {}, {}
    for message in messages:
        for call in getattr(message, "tool_calls", []):
            calls[call["id"]] = (call["name"], json.dumps(call["args"], sort_keys=True, default=str))
        if (
            isinstance(message, ToolMessage)
            and message.tool_call_id in calls
            and not message.content.startswith("未执行：")
        ):
            cache[calls[message.tool_call_id]] = message.content
    remaining = context.get("remaining_iterations", 5)
    for iteration in range(remaining + 1):
        response = None
        chunks = []
        async for token, completed in _stream_model_response(bound, messages):
            if token:
                chunks.append(token)
                emit({"type": "runtime_draft", "agent_name": agent.name, "content": token})
            if completed is not None:
                response = completed
                usage.add(completed)
                emit(
                    {
                        "type": "runtime_usage",
                        "agent_id": str(agent.id),
                        "agent_name": agent.name,
                        "stats": usage.stats(),
                    }
                )
        if not response.tool_calls:
            text = "".join(chunks)
            emit({"type": "token", "content": text})
            return text
        if iteration == remaining:
            raise RuntimeError("本轮工具调用预算已耗尽，请检查已有执行结果")
        results = []
        for call in response.tool_calls:
            tool = next((t for t in tools if t.name == call["name"]), None)
            if tool is None:
                raise HTTPException(403, "原任务使用的能力已不可用")
            async with async_session_factory() as db:
                await require_agent_use(db, agent.id)
            emit(
                {
                    "type": "runtime_progress",
                    "agent_name": agent.name,
                    "status": "running",
                    "message": "继续执行 · " + tool.name,
                }
            )
            key = (call["name"], json.dumps(call["args"], sort_keys=True, default=str))
            raw = cache[key] if key in cache and call["name"] != "ask_user" else await tool.ainvoke(call["args"])
            cache[key] = raw
            results.append(ToolMessage(content=str(raw), tool_call_id=call["id"]))
            pause_after_tool(raw, agent, messages, response, results, call, remaining=remaining - iteration - 1)
        messages.extend([response, *results])
        context["messages"] = serialize_messages(messages)


async def continue_chain(context, answer, conv_id, emit):
    parent = context.get("parent")
    try:
        result = await continue_agent(context, answer, conv_id, emit)
    except UserQuestionPause as pause:
        if parent:
            pause.context["parent"] = parent
        raise
    if not parent:
        return result
    from cortexa.agents.prompts import reference_message
    from cortexa.collaboration.manager import execute_handoff
    from cortexa.collaboration.schemas import AgentHandoff
    from cortexa.runtime.loop import serialize_messages

    messages = messages_from_dict(parent["messages"])
    messages.append(reference_message("用户回答后的协作结果", result))
    for item in parent.pop("completed_results", []):
        messages.append(reference_message("已完成协作结果", item["result"]))
    completed = parent.setdefault("finished_results", [])
    completed.append({"agent_id": context["agent_id"], "result": result})
    siblings = parent.get("siblings", [])
    while siblings:
        sibling = siblings[0]
        async with async_session_factory() as db:
            origin = await require_agent_use(db, uuid.UUID(parent["agent_id"]))
            target = await require_agent_use(db, uuid.UUID(sibling["agent_id"]))
            from cortexa.collaboration.background import prepare_background
            from cortexa.collaboration.schemas import CollaborationDraft

            draft = CollaborationDraft.model_validate(sibling["draft"]) if sibling.get("draft") else None
            background = await prepare_background(
                db,
                conv_id,
                draft,
                parent.get("original_task", sibling["task"]),
                target_type=target.agent_type,
                attachments=parent.get("attachments", []),
                exclude_message_id=uuid.UUID(parent["exclude_message_id"])
                if parent.get("exclude_message_id")
                else None,
            )
            try:
                output = await execute_handoff(
                    source_agent=origin,
                    target_agent=target,
                    handoff=AgentHandoff(
                        project_ids=parent.get("project_ids",[]),
                        source_agent_id=str(origin.id),
                        target_agent_id=str(target.id),
                        task=sibling["task"],
                        question=sibling["task"],
                        constraints=sibling["constraints"],
                        expected_output=sibling.get("expected_output", "给出专业分析和建议"),
                        background_context=background,
                        dependency_results=[
                            item
                            for item in completed
                            if draft is None or item["agent_id"] in {str(i) for i in draft.depends_on}
                        ],
                    ),
                    conversation_id=conv_id,
                    db=db,
                )
                await db.commit()
            except UserQuestionPause as pause:
                await db.commit()
                siblings.pop(0)
                parent["messages"] = serialize_messages(messages)
                pause.context["parent"] = parent
                raise
        completed.append({"agent_id": str(target.id), "result": output.result})
        messages.append(reference_message("后续协作结果", output.result))
        siblings.pop(0)
    parent["messages"] = serialize_messages(messages)
    return await continue_agent(parent, "依据已完成协作结果继续原任务。", conv_id, emit)


def legacy_response(conv_id, question_id, public, context, text):
    async def generate():
        queue = asyncio.Queue()
        async with async_session_factory() as db:
            msg = ConversationMessage(
                conversation_id=conv_id,
                role="user",
                content=text,
                metadata_json={"answer_to_question": str(question_id)},
            )
            db.add(msg)
            await db.commit()
            user_id = str(msg.id)
        yield sse({"type": "user_message", "id": user_id, "content": text})

        async def execute():
            try:
                result = await continue_chain(context, text, conv_id, queue.put_nowait)
                async with async_session_factory() as db:
                    msg = ConversationMessage(conversation_id=conv_id, role="assistant", content=result)
                    db.add(msg)
                    await db.commit()
                    msg_id = str(msg.id)
                await finish_question(conv_id, question_id)
                queue.put_nowait({"type": "done", "id": msg_id, "content": result})
            except UserQuestionPause as pause:
                msg_id = await persist_pause(conv_id, pause)
                await finish_question(conv_id, question_id)
                queue.put_nowait({"type": "user_question", "question": pause.question})
                queue.put_nowait(
                    {
                        "type": "done",
                        "id": msg_id,
                        "content": pause.question["question"],
                        "user_question": pause.question,
                    }
                )
            except Exception:
                logging.getLogger(__name__).exception("User answer continuation failed")
                # Do not reset the claim: an external call may already have executed.
                queue.put_nowait(
                    {"type": "error", "error": "回答已接收，但续接执行中断。请核实执行结果；系统不会自动重复调用。"}
                )
            finally:
                queue.put_nowait(None)

        worker = asyncio.create_task(execute())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield ": waiting\n\n"
                    continue
                if item is None:
                    break
                yield sse(item)
            await worker
        finally:
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/{conv_id}/question/{question_id}/recover")
async def recover_answer(conv_id: uuid.UUID, question_id: uuid.UUID):
    """Read back a proven finished Proxy turn, never repeat its write/query call."""
    from cortexa.runtime.reconciliation import reconcile_goal
    async with async_session_factory() as db:
        conv = await own_conversation(db, conv_id, use_agent=True)
        public = (conv.metadata_json or {}).get("pending_question")
        if not public or public["id"] != str(question_id) or public.get("status") not in {"answering", "interrupted"}:
            raise HTTPException(409, "待核实的问题已改变，请刷新状态")
        context = files.read(question_id, conv.metadata_json["question_context"])
    if context.get('engine') in {'proxy', 'proxy_reconcile'}:
        from cortexa.runtime.reconciliation import verified_result
        from cortexa.runtime.proxy import contract_signature
        from cortexa.agents.proxy_executor import read_proxy_turn
        async with async_session_factory() as db:
            target = await require_agent_use(db, uuid.UUID(context['agent_id']))
        if context['engine'] == 'proxy':
            run = {'input':{}, 'request_body':{**context['body'], context['answer_field']:public.get('answer'), 'session_id':context['session_id']},
                   'remote_execution':{'session_id':context['session_id'], 'signature':context['signature']},
                   'continuation':{'answer_field':context['answer_field'],'question':public['question']}}
        else:
            run = context['run']
        identity = run['remote_execution']
        if identity['signature'] != contract_signature(target):
            raise HTTPException(409, '代理契约已变化，请人工核实旧会话')
        remote = await read_proxy_turn(target.proxy_config, identity['session_id'])
        context['recovered_output'] = verified_result(target, run, remote, public)
        async with async_session_factory() as db:
            conv = await db.scalar(select(Conversation).where(Conversation.id == conv_id).with_for_update())
            current = (conv.metadata_json or {}).get('pending_question') if conv else None
            if not current or current['id'] != str(question_id) or current.get('recovery_claim'):
                raise HTTPException(409, '恢复请求已处理，请读取最新状态')
            from cortexa.runtime.background import workers
            if str(question_id) in workers and not workers[str(question_id)].done():
                raise HTTPException(409, '原执行仍在进行，请等待完成')
            current = {**current, 'status':'answering','recovery_claim':str(uuid.uuid4())}
            conv.metadata_json = {**conv.metadata_json, 'pending_question':current}
            await db.commit()
        return wrap_completion(legacy_response(conv_id, question_id, public, context, public.get('answer', '')), conv_id, question_id)
    if context.get("engine") != "goal":
        raise HTTPException(409, "此执行尚不支持原会话核实；不会重新派发任务")
    response = await reconcile_goal(conv_id, uuid.UUID(context["goal_id"]), public)
    return wrap_completion(response, conv_id, question_id)
