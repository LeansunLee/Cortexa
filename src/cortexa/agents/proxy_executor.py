"""Proxy Agent Executor — forwards requests to external system agents."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortexa.db.models import Agent, AgentRun, AgentVersion

_ENV_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _resolve_env(value: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2) or ""
        return os.getenv(var_name, default)

    return _ENV_PATTERN.sub(_replace, value)


def _resolve_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: _resolve_env(v) for k, v in headers.items()}


async def _save_run(agent_id, version_id, input_data, output_data, status, error_message, duration_ms, db):
    """Save run record only if version exists."""
    if not version_id:
        return
    run = AgentRun(
        agent_id=agent_id,
        agent_version_id=version_id,
        input_data=input_data,
        output_data=output_data,
        status=status,
        error_message=error_message,
        duration_ms=duration_ms,
    )
    db.add(run)
    await db.flush()


async def _get_version_id(agent_id, db):
    ver_result = await db.execute(
        select(AgentVersion.id)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
        .limit(1)
    )
    return ver_result.scalar()


class ProxyExecutionError(ValueError):
    """The remote Agent explicitly failed its task, rather than losing transport."""


class ProxyResultUnknown(ValueError):
    """The remote endpoint acknowledged work but has no terminal result yet."""


def _run_failed(event):
    # Tools may fail and be repaired by the Agent; only task-level events end the run.
    if event.get("type") in {"tool_start", "tool_result", "tool_error"}:
        return False
    return (event.get("type") == "error" or event.get("status") in {"failed", "error"}
            or (event.get("ok") is False and event.get("status") != "awaiting_user"))


def _parse_proxy_response(response):
    content_type = response.headers.get("content-type", "").lower()
    text = response.text.lstrip("\ufeff").strip()
    if not text:
        raise ValueError("外部接口返回空响应")
    if "text/event-stream" in content_type or text.startswith(("data:", "event:", ":")):
        output = {}
        chunks = []
        completed = False
        frames = re.split(r"\r?\n\r?\n", text)
        for frame in frames:
            data = "\n".join(line[5:].lstrip(" ") for line in frame.splitlines() if line.startswith("data:"))
            if not data:
                continue
            if data == "[DONE]":
                completed = True
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError as error:
                raise ValueError("外部接口 SSE 事件包含无效 JSON") from error
            if not isinstance(event, dict):
                continue
            kind = event.get("type", "")
            if _run_failed(event):
                raise ProxyExecutionError(
                    "外部智能体执行失败：" + str(event.get("error") or event.get("message") or "未提供错误详情")
                )
            if kind == 'ask_user':
                output['user_question'] = {k:event[k] for k in ('question', 'options', 'multi_select', 'allow_free_text') if k in event}
            elif kind == "start":
                for key in ("session_id", "request_id", "model_provider"):
                    if key in event:
                        output[key] = event[key]
            elif kind in ("text_delta", "token", "delta"):
                content = event.get("content", event.get("text", ""))
                if isinstance(content, str):
                    chunks.append(content)
            elif kind == "usage":
                output["usage"] = event
            elif kind in ("done", "message_end", "final_answer"):
                if kind in ("done", "message_end"):
                    completed = True
                output.update({key: value for key, value in event.items() if key != "type"})
        if not completed:
            raise ValueError("外部事件流未正常结束，请重试（未将不完整结果当作成功）")
        output["answer"] = output.get("answer") or "".join(chunks)
        if not output["answer"]:
            raise ValueError("外部事件流已结束，但没有返回回答正文")
        if output.get('status') == 'awaiting_user':
            output['requires_input'] = True
            output['user_question'] = output.get('user_question') or output.get('pending_ask') or {'question':output['answer']}
        return output
    try:
        output = json.loads(text)
        if isinstance(output, dict) and output.get('status') == 'awaiting_user':
            output['requires_input'] = True
            output['user_question'] = output.get('user_question') or output.get('pending_ask') or {'question':output.get('answer', '')}
        return output
    except json.JSONDecodeError as error:
        if "text/plain" in content_type or "text/markdown" in content_type:
            return {"answer": text}
        raise ValueError("外部接口返回的内容不是有效 JSON、SSE 或纯文本回答") from error


def _response_value(output, path):
    value = output
    for key in path[2:].split("."):
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            return None
    return value


def build_proxy_body(cfg, input_data, supplemental_prompt=None):
    # Adapt the external agent input before request field mapping.
    request_input = dict(input_data)
    supplemental_prompt = (
        (cfg.get("supplemental_prompt", "") or "") if supplemental_prompt is None else supplemental_prompt
    )
    if not isinstance(supplemental_prompt, str):
        raise ValueError("Proxy 补充提示词必须是文本")
    if supplemental_prompt.strip():
        if not isinstance(request_input.get("input"), str):
            raise ValueError("配置 Proxy 补充提示词后，请提供字符串类型的 input 字段")
        request_input["input"] = supplemental_prompt.strip() + "\n\n" + request_input["input"]

    # Apply request mapping
    request_body = request_input
    req_mapping = cfg.get("request_mapping", {})
    if req_mapping:
        mapped = {}
        for target_key, source_path in req_mapping.items():
            if source_path.startswith("$."):
                mapped[target_key] = request_input.get(source_path[2:])
            else:
                mapped[target_key] = source_path
        request_body = mapped

    return request_body


async def send_proxy_request(cfg, request_body, *, timeout_seconds=None, max_response_bytes=None, on_event=None):
    """One transport attempt. Goal callers supply a bounded, already validated body."""
    endpoint = _resolve_env(cfg["endpoint"])
    method = cfg.get("method", "POST").upper()
    headers = _resolve_headers(cfg.get("headers", {}))
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    timeout = timeout_seconds if timeout_seconds is not None else cfg.get("timeout_ms", 30000) / 1000
    async with asyncio.timeout(timeout), httpx.AsyncClient(timeout=timeout) as client:
        if max_response_bytes is None:
            response = await (
                client.get(endpoint, headers=headers, params=request_body)
                if method == "GET"
                else client.post(endpoint, headers=headers, json=request_body)
            )
        else:
            kwargs = {"params" if method == "GET" else "json": request_body}
            async with client.stream(method, endpoint, headers=headers, **kwargs) as response:
                response.raise_for_status()
                import codecs
                decoder, events_buffer = codecs.getincrementaldecoder('utf-8')(), ''
                streaming = 'text/event-stream' in response.headers.get('content-type', '').lower()
                chunks, size = [], 0
                text_parts, text_size, retained = [], 0, {}
                # Result budget covers the report, not repeated SSE framing or tool telemetry.
                # Transport and individual frames remain separately bounded.
                wire_limit = max(4 * 1024 * 1024, min(32 * max_response_bytes, 32 * 1024 * 1024))
                frame_limit = max(1024 * 1024, max_response_bytes)

                async def consume(frame):
                    nonlocal text_size
                    data = '\n'.join(line[5:].lstrip(' ') for line in frame.splitlines() if line.startswith('data:'))
                    if not data:
                        return
                    if data == '[DONE]':
                        retained['done'] = retained.get('done', {'type': 'done'})
                        return
                    try:
                        event = json.loads(data)
                    except ValueError as error:
                        raise ValueError('外部接口 SSE 事件包含无效 JSON') from error
                    if not isinstance(event, dict):
                        return
                    kind = event.get('type')
                    if _run_failed(event):
                        raise ProxyExecutionError('外部智能体执行失败：' + str(event.get('error') or event.get('message') or '未提供错误详情'))
                    if kind in ('text_delta', 'token', 'delta'):
                        content = event.get('content', event.get('text', ''))
                        if isinstance(content, str):
                            text_size += len(content.encode())
                            if text_size > max_response_bytes:
                                raise ValueError('proxy_response_budget_exceeded')
                            text_parts.append(content)
                    elif kind in ('start', 'usage', 'ask_user'):
                        retained[kind] = event
                    elif kind in ('done', 'message_end', 'final_answer'):
                        retained.setdefault('final_answer', {'type': 'final_answer'}).update(
                            {key: value for key, value in event.items() if key != 'type'})
                        if kind in ('done', 'message_end'):
                            retained['done'] = {'type': 'done'}
                    if sum(len(json.dumps(e, ensure_ascii=False).encode()) for e in retained.values()) > max_response_bytes:
                        raise ValueError('proxy_response_budget_exceeded')
                    if on_event and kind in {'start', 'tool_start', 'tool_result', 'tool_error', 'text_delta', 'usage'}:
                        pending = on_event(event)
                        if inspect.isawaitable(pending):
                            await pending

                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > (wire_limit if streaming else max_response_bytes):
                        raise ValueError('proxy_stream_budget_exceeded' if streaming else 'proxy_response_budget_exceeded')
                    if not streaming:
                        chunks.append(chunk)
                        continue
                    events_buffer = (events_buffer + decoder.decode(chunk)).replace('\r\n', '\n')
                    while '\n\n' in events_buffer:
                        frame, events_buffer = events_buffer.split('\n\n', 1)
                        if len(frame.encode()) > frame_limit:
                            raise ValueError('proxy_stream_budget_exceeded')
                        await consume(frame)
                    if len(events_buffer.encode()) > frame_limit:
                        raise ValueError('proxy_stream_budget_exceeded')
                if streaming:
                    events_buffer += decoder.decode(b'', final=True)
                    if events_buffer.strip():
                        await consume(events_buffer)
                    events = [retained[k] for k in ('start', 'usage', 'ask_user') if k in retained]
                    if text_parts:
                        events.append({'type': 'text_delta', 'content': ''.join(text_parts)})
                    events.extend(retained[k] for k in ('final_answer', 'done') if k in retained)
                    compact = '\n\n'.join('data: ' + json.dumps(e, ensure_ascii=False) for e in events)
                    parsed = _parse_proxy_response(httpx.Response(response.status_code, headers=response.headers,
                        text=compact, request=response.request))
                    if len(json.dumps(parsed, ensure_ascii=False).encode()) > max_response_bytes:
                        raise ValueError('proxy_response_budget_exceeded')
                    return parsed
                response = httpx.Response(
                    response.status_code, headers=response.headers, content=b''.join(chunks), request=response.request
                )
    response.raise_for_status()
    return _parse_proxy_response(response)


def map_proxy_output(cfg, raw_output):
    mapping = cfg.get("response_mapping", {})
    if not mapping:
        return raw_output
    mapped = {
        key: _response_value(raw_output, value) if value.startswith("$.") else raw_output
        for key, value in mapping.items()
    }
    if "answer" in mapped and mapped["answer"] is None:
        raise ValueError("外部响应中未找到配置映射的回答字段，请检查 response_mapping")
    return mapped


def response_limit(cfg):
    value = (cfg.get("goal_contract") or {}).get("response_bytes", 128000)
    return max(1024, min(1048576, int(value)))


def validated_proxy_output(agent, raw):
    """Apply the same terminal state and output contract in every Proxy entry."""
    if isinstance(raw, dict):
        if raw.get('status') in {'running', 'pending', 'queued', 'started'}:
            raise ProxyResultUnknown('外部任务尚未完成，需要核实原会话；不能重复派发')
        if raw.get("user_question") or raw.get("status") == "awaiting_user":
            return None
        if raw.get("success") is False or raw.get("requires_input") or _run_failed(raw):
            raise ProxyExecutionError("外部 Agent 未完成任务，请查看失败或缺参状态")
    output = map_proxy_output(agent.proxy_config, raw)
    if agent.output_schema:
        from cortexa.runtime.contracts import contract_errors
        if contract_errors(agent.output_schema, output):
            raise ProxyExecutionError("代理输出未通过契约校验")
    return output


async def execute_proxy_agent(
    agent: Agent,
    input_data: dict[str, Any],
    db: AsyncSession,
    supplemental_prompt: str | None = None,
    resolution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a proxy agent by calling the external system endpoint."""
    from cortexa.conversation.questions import UserQuestionPause
    cfg = agent.proxy_config or {}
    if not cfg.get("endpoint"):
        return {"success": False, "error": "Proxy endpoint is not configured", "duration_ms": 0}

    start_time = time.time()
    resolved_input = input_data
    resolution_result = None
    from cortexa.agents.proxy_input_resolver import (
        prompt_resolution_enabled,
        resolution_enabled,
        resolve_proxy_input,
        resolve_proxy_prompt,
    )

    outbound_supplemental_prompt = supplemental_prompt
    if prompt_resolution_enabled(cfg):
        resolution_result = await resolve_proxy_prompt(
            agent,
            input_data,
            resolution_context,
            supplemental_prompt=supplemental_prompt,
        )
        resolved_input = resolution_result["input"]
        # In prompt mode the supplemental prompt is an instruction to the local
        # resolver. Only its synthesized prompt is sent to the external Agent.
        outbound_supplemental_prompt = ""
    elif resolution_enabled(cfg):
        resolution_result = await resolve_proxy_input(agent, input_data, resolution_context)
        resolved_input = resolution_result["input"]
    if resolution_result is not None:
        if not resolution_result["canInvoke"]:
            validation_errors = resolution_result.get("validationErrors") or []
            if resolution_result['blockingMissingFields']:
                from cortexa.conversation.questions import UserQuestionPause, question
                public = question({'question':resolution_result['message'] or '请补充代理执行所需信息。'}, agent)
                raise UserQuestionPause(public, {'engine':'proxy_setup','agent_id':str(agent.id),
                    'input_data':input_data,'supplemental_prompt':supplemental_prompt,'resolution_context':resolution_context})
            return {
                "success": False,
                "requires_input": bool(resolution_result["blockingMissingFields"])
                or bool(validation_errors and not validation_errors[0].startswith("Input Schema 配置无效")),
                "error": resolution_result["message"],
                "resolution": resolution_result,
                "duration_ms": int((time.time() - start_time) * 1000),
            }

    try:
        request_body = build_proxy_body(cfg, resolved_input, outbound_supplemental_prompt)
    except ValueError as error:
        return {"success": False, "error": str(error), "duration_ms": 0}

    from cortexa.runtime.proxy import contract_signature, REJECTED_HTTP_STATUSES
    identity = {}
    async def remember(event):
        if event.get('type') == 'start' and isinstance(event.get('session_id'), str):
            identity.update(session_id=event['session_id'], request_id=event.get('request_id'), signature=contract_signature(agent))
    version_id = await _get_version_id(agent.id, db)
    last_error = None
    evidence_error = None

    for attempt in range(1):
        try:
            raw_output = await send_proxy_request(cfg, request_body, max_response_bytes=response_limit(cfg), on_event=remember)
            if isinstance(raw_output, dict) and raw_output.get('user_question'):
                from cortexa.conversation.questions import UserQuestionPause, question, proxy_context
                raise UserQuestionPause(question(raw_output['user_question'], agent), proxy_context(agent, raw_output, request_body))
            if isinstance(raw_output, dict) and isinstance(raw_output.get('session_id'), str):
                identity.update(session_id=raw_output['session_id'], request_id=raw_output.get('request_id'), signature=contract_signature(agent))
            output_data = validated_proxy_output(agent, raw_output)

            duration_ms = int((time.time() - start_time) * 1000)
            await _save_run(agent.id, version_id, resolved_input, output_data, "completed", None, duration_ms, db)
            return {
                "success": True,
                "output_data": output_data,
                "resolution": resolution_result,
                "request_body": request_body,
                "duration_ms": duration_ms,
            }

        except UserQuestionPause:
            raise
        except Exception as e:
            evidence_error = e
            last_error = ("外部 Agent 明确返回失败或输出未满足契约，请核对配置与执行结果。"
                if isinstance(e, ProxyExecutionError) else "外部调用未取得可靠结果；如已开始执行，请核实原会话，不能重复派发。")

    duration_ms = int((time.time() - start_time) * 1000)
    unknown = isinstance(evidence_error, (httpx.TransportError, TimeoutError, ProxyResultUnknown)) or (
        isinstance(evidence_error, httpx.HTTPStatusError) and evidence_error.response.status_code not in REJECTED_HTTP_STATUSES
    ) or (
        isinstance(evidence_error, ValueError) and not isinstance(evidence_error, ProxyExecutionError)
        and any(term in str(evidence_error) for term in ('未正常结束', 'proxy_response_budget', 'proxy_stream_budget', 'SSE 事件包含无效')))
    await _save_run(agent.id, version_id, resolved_input, None, "unknown" if unknown else "failed", last_error, duration_ms, db)
    if unknown and identity.get('session_id'):
        from cortexa.conversation.questions import question
        public = question({'question':'原外部会话结果需要核实，将读取原会话而不重新派发任务。'}, agent)
        public.update(status='interrupted', can_recover=True)
        raise UserQuestionPause(public, {'engine':'proxy_reconcile','agent_id':str(agent.id),
            'run':{'input':resolved_input,'request_body':request_body,'remote_execution':identity}})
    return {"success": False, "error": last_error, "resolution": resolution_result, "duration_ms": duration_ms,
            "result_unknown": unknown}


async def read_proxy_turn(cfg, session_id):
    """Read-only reconciliation; never send the original run request again."""
    from urllib.parse import quote
    endpoint = _resolve_env(cfg.get('result_endpoint') or '')
    run_endpoint = _resolve_env(cfg.get('endpoint') or '')
    if endpoint:
        endpoint = endpoint.replace('{session_id}', quote(session_id, safe=''))
    elif run_endpoint.rstrip('/').endswith('/run'):
        endpoint = run_endpoint.rstrip('/')[:-4] + '/sessions/' + quote(session_id, safe='') + '/result'
    else:
        raise ValueError('此代理尚未配置只读结果查询接口')
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(endpoint, headers=_resolve_headers(cfg.get('headers') or {}))
        response.raise_for_status()
        if len(response.content) > 1048576:
            raise ValueError('外部报告超过读取预算')
        return response.json()
