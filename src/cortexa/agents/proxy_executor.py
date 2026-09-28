"""Proxy Agent Executor — forwards requests to external system agents."""

from __future__ import annotations

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
            if kind == "error" or event.get("ok") is False or event.get("status") in ("failed", "error"):
                raise ValueError(
                    "外部智能体执行失败：" + str(event.get("error") or event.get("message") or "未提供错误详情")
                )
            if kind == "start":
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
        return output
    try:
        return json.loads(text)
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


async def send_proxy_request(cfg, request_body, *, timeout_seconds=None, max_response_bytes=None):
    """One transport attempt. Goal callers supply a bounded, already validated body."""
    endpoint = _resolve_env(cfg["endpoint"])
    method = cfg.get("method", "POST").upper()
    headers = _resolve_headers(cfg.get("headers", {}))
    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    timeout = timeout_seconds if timeout_seconds is not None else cfg.get("timeout_ms", 30000) / 1000
    async with httpx.AsyncClient(timeout=timeout) as client:
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
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_response_bytes:
                        raise ValueError("proxy_response_budget_exceeded")
                    chunks.append(chunk)
                response = httpx.Response(
                    response.status_code, headers=response.headers, content=b"".join(chunks), request=response.request
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


async def execute_proxy_agent(
    agent: Agent,
    input_data: dict[str, Any],
    db: AsyncSession,
    supplemental_prompt: str | None = None,
    resolution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute a proxy agent by calling the external system endpoint."""
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
            return {
                "success": False,
                "requires_input": bool(resolution_result["blockingMissingFields"])
                or bool(validation_errors and not validation_errors[0].startswith("Input Schema 配置无效")),
                "error": resolution_result["message"],
                "resolution": resolution_result,
                "duration_ms": int((time.time() - start_time) * 1000),
            }
    retry = cfg.get("retry", 0)

    try:
        request_body = build_proxy_body(cfg, resolved_input, outbound_supplemental_prompt)
    except ValueError as error:
        return {"success": False, "error": str(error), "duration_ms": 0}

    version_id = await _get_version_id(agent.id, db)
    last_error = None

    for attempt in range(retry + 1):
        try:
            raw_output = await send_proxy_request(cfg, request_body)
            output_data = map_proxy_output(cfg, raw_output)

            duration_ms = int((time.time() - start_time) * 1000)
            await _save_run(agent.id, version_id, resolved_input, output_data, "completed", None, duration_ms, db)
            return {
                "success": True,
                "output_data": output_data,
                "resolution": resolution_result,
                "request_body": request_body,
                "duration_ms": duration_ms,
            }

        except Exception as e:
            last_error = str(e)
            if attempt < retry:
                continue

    duration_ms = int((time.time() - start_time) * 1000)
    await _save_run(agent.id, version_id, resolved_input, None, "failed", last_error, duration_ms, db)
    return {"success": False, "error": last_error, "resolution": resolution_result, "duration_ms": duration_ms}
