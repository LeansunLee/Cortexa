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

from agentdevstu.db.models import Agent, AgentRun, AgentVersion


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
        select(AgentVersion.id).where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc()).limit(1)
    )
    return ver_result.scalar()


async def execute_proxy_agent(
    agent: Agent,
    input_data: dict[str, Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Execute a proxy agent by calling the external system endpoint."""
    cfg = agent.proxy_config or {}
    if not cfg.get("endpoint"):
        return {"success": False, "error": "Proxy endpoint is not configured", "duration_ms": 0}

    start_time = time.time()
    endpoint = _resolve_env(cfg["endpoint"])
    method = cfg.get("method", "POST").upper()
    headers = _resolve_headers(cfg.get("headers", {}))
    timeout_ms = cfg.get("timeout_ms", 30000)
    retry = cfg.get("retry", 0)

    # Apply request mapping
    request_body = input_data
    req_mapping = cfg.get("request_mapping", {})
    if req_mapping:
        mapped = {}
        for target_key, source_path in req_mapping.items():
            if source_path.startswith("$."):
                mapped[target_key] = input_data.get(source_path[2:])
            else:
                mapped[target_key] = source_path
        request_body = mapped

    if "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    version_id = await _get_version_id(agent.id, db)
    last_error = None

    for attempt in range(retry + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
                if method == "GET":
                    resp = await client.get(endpoint, headers=headers, params=request_body)
                else:
                    resp = await client.post(endpoint, headers=headers, json=request_body)

            resp.raise_for_status()
            raw_output = resp.json()

            # Apply response mapping
            output_data = raw_output
            resp_mapping = cfg.get("response_mapping", {})
            if resp_mapping:
                mapped = {}
                for target_key, source_path in resp_mapping.items():
                    if source_path.startswith("$."):
                        mapped[target_key] = raw_output.get(source_path[2:])
                    else:
                        mapped[target_key] = raw_output
                output_data = mapped

            duration_ms = int((time.time() - start_time) * 1000)
            await _save_run(agent.id, version_id, input_data, output_data, "completed", None, duration_ms, db)
            return {"success": True, "output_data": output_data, "duration_ms": duration_ms}

        except Exception as e:
            last_error = str(e)
            if attempt < retry:
                continue

    duration_ms = int((time.time() - start_time) * 1000)
    await _save_run(agent.id, version_id, input_data, None, "failed", last_error, duration_ms, db)
    return {"success": False, "error": last_error, "duration_ms": duration_ms}
