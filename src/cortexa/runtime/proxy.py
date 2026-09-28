"""Strict Proxy projection: default deny, no model-created values or raw context."""

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field

from cortexa.agents.proxy_executor import build_proxy_body, map_proxy_output, send_proxy_request
from cortexa.db.models import AgentCollaboration
from cortexa.runtime.contracts import contract_errors
from cortexa.runtime.loop import InvocationResult, token_upper_bound
from cortexa.runtime.observations import Observation
from cortexa.runtime.state import RuntimeHalt

Source = Literal["explicit", "goal_task", "observation_facts", "observation_summary"]
DENIED_CONTEXT = ["conversation", "memory", "knowledge", "agent_raw_context", "primary_system_prompt"]


class ProxyContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool = False
    input_budget: int = Field(default=4000, ge=256, le=8000)
    response_bytes: int = Field(default=128000, ge=1024, le=1048576)
    fields: dict[str, list[Source]] = Field(default_factory=dict, max_length=64)


class ObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: uuid.UUID
    source: Literal["observation_facts", "observation_summary"] = "observation_facts"
    pointer: str = Field(
        default="", max_length=256, description="事实内的 JSON Pointer，例如 /0/city；摘要只允许空路径"
    )


class ProxyInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_bindings: dict[str, ObservationInput] = Field(
        default_factory=dict,
        max_length=64,
        description="仅引用实际 Observation 字段；其他输入由 Runtime 构造，不接受 task、inputs 或上下文正文。",
    )


def policy(agent):
    return ProxyContract.model_validate((agent.proxy_config or {}).get("goal_contract") or {})


def enabled(agent, config):
    if agent.agent_type != "proxy":
        return True
    try:
        return config.get("features", {}).get("goal_proxy_enabled") is True and policy(agent).enabled
    except (ValueError, TypeError):
        return False


def contract_signature(agent):
    return hashlib.sha256(
        json.dumps(
            [agent.input_schema, agent.output_schema, agent.proxy_config], sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()


def check_shape(schema, depth=0):
    # Static field topology is necessary for deterministic allow-list projection.
    # Dynamic/ref-based contracts remain available on the legacy path.
    if depth > 12 or not isinstance(schema, dict):
        raise ValueError("static_contract_required")
    if any(
        key in schema
        for key in (
            "$ref",
            "$dynamicRef",
            "allOf",
            "anyOf",
            "oneOf",
            "not",
            "if",
            "patternProperties",
            "dependentSchemas",
        )
    ):
        raise ValueError("static_contract_required")
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(schema.get("properties"), dict):
            raise ValueError("declared_properties_required")
        for value in schema["properties"].values():
            check_shape(value, depth + 1)
    elif kind == "array":
        check_shape(schema.get("items"), depth + 1)
    elif kind not in ("string", "number", "integer", "boolean", "null"):
        raise ValueError("explicit_type_required")


def validate_configuration(agent):
    cfg = policy(agent)
    if not cfg.enabled:
        return cfg
    schema = agent.input_schema or {}
    if schema.get("type") != "object" or not schema.get("properties"):
        raise ValueError("需要声明 object 输入契约及 properties")
    contract_errors(schema, {})  # Validate schema definition without accepting an input yet.
    check_shape(schema)
    if not set(cfg.fields) <= set(schema["properties"]):
        raise ValueError("来源白名单只能包含输入契约声明的字段")
    if not agent.proxy_config.get("endpoint") or agent.proxy_config.get("method", "POST").upper() not in (
        "GET",
        "POST",
    ):
        raise ValueError("目标代理需要 GET/POST Endpoint")
    return cfg


def project(value, schema, path, rejected):
    if isinstance(value, dict) and schema.get("type") == "object":
        properties = schema["properties"]
        result = {}
        for key, item in value.items():
            if key not in properties:
                rejected.append(path + "/" + str(key))
            else:
                result[key] = project(item, properties[key], path + "/" + key, rejected)
        return result
    if isinstance(value, list) and schema.get("type") == "array":
        return [project(item, schema["items"], path + "/" + str(i), rejected) for i, item in enumerate(value)]
    return value


def pointer_value(value, pointer):
    if not pointer:
        return value
    if not pointer.startswith("/"):
        raise ValueError("invalid_pointer")
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[token]
        elif isinstance(value, list) and token.isdigit():
            value = value[int(token)]
        else:
            raise ValueError("missing_pointer")
    return value


def build_invocation(agent, payload, args, context_limit):
    cfg = validate_configuration(agent)
    ident = str(agent.id)
    explicit = payload.get("participant_inputs", {}).get(ident, {})
    task = payload.get("participant_tasks", {}).get(ident) or payload["goal"]["raw_request"]
    observations = {
        o["action_id"]: o for o in payload.get("observations", []) if o["status"] in {"SUCCESS", "EMPTY", "PARTIAL"}
    }
    bindings = ProxyInvocation.model_validate(args).observation_bindings
    result, selected, rejected = {}, {}, []
    properties = agent.input_schema["properties"]
    for name, sources in cfg.fields.items():
        value = None
        found = False
        if "explicit" in sources and name in explicit:
            value, found = explicit[name], True
            selected[name] = "explicit"
        elif "goal_task" in sources:
            value, found = task, True
            selected[name] = "goal_task"
        elif name in bindings:
            binding = bindings[name]
            observation = observations.get(str(binding.action_id))
            if binding.source in sources and observation:
                try:
                    if binding.source == "observation_summary" and binding.pointer:
                        raise ValueError("summary_pointer_denied")
                    value = pointer_value(
                        observation["facts"] if binding.source == "observation_facts" else observation["summary"],
                        binding.pointer,
                    )
                    found = True
                    selected[name] = binding.source
                except (ValueError, KeyError, IndexError, TypeError):
                    pass
        if found:
            result[name] = project(value, properties[name], "/" + name, rejected)
    rejected.extend("/" + name for name in explicit if selected.get(name) != "explicit")
    rejected.extend("/" + name for name in bindings if name not in selected)
    errors = contract_errors(agent.input_schema, result)
    missing = set()
    for error in errors:
        if error.validator == "required" and isinstance(error.instance, dict):
            missing.update(
                "/" + "/".join([*map(str, error.absolute_path), name])
                for name in error.validator_value
                if name not in error.instance
            )
        else:
            missing.add("/" + "/".join(map(str, error.absolute_path)))
    body = build_proxy_body(agent.proxy_config, result, supplemental_prompt="")
    # Count the final wire payload including mappings/constants, without string truncation.
    size = token_upper_bound(body)
    oversized = size > min(cfg.input_budget, context_limit)
    trace = {
        "selected_fields": sorted(selected),
        "sources": selected,
        "denied_context": DENIED_CONTEXT,
        "rejected_field_count": len(rejected),
        "compression": "structural_projection" if rejected else "none",
        "input_token_upper_bound": size,
        "validation": "budget_exceeded" if oversized else "not_ready" if errors else "valid",
    }
    return result, body, sorted(missing), oversized, trace


async def invoke_proxy(agent, args, action_id, origin, state, payload, loop, store, row):
    child_seconds = loop.budget.remaining("duration", protect_finalization=True)
    if child_seconds < 1 or not loop.budget.can_expand(max_steps=0):
        raise RuntimeHalt("child_budget_unavailable")
    try:
        projected, body, missing, oversized, trace = build_invocation(agent, payload, args, state.limits.context_tokens)
    except (ValueError, TypeError, KeyError):
        raise RuntimeHalt("proxy_contract_invalid") from None
    loop.record("Proxy projection", **trace)
    cfg = policy(agent)
    if oversized or missing:
        message = (
            "代理输入超过预算，请缩小所选字段或数据范围。"
            if oversized
            else "请补充代理输入字段：" + "、".join(missing) + "。可 @该代理，在参数卡中填写 JSON 后继续。"
        )
        repairable = (
            bool(missing)
            and not oversized
            and all(
                set(cfg.fields.get(field.split("/")[1], [])) & {"observation_facts", "observation_summary"}
                for field in missing
            )
        )
        observation = Observation(
            "AGENT",
            "agent:" + str(agent.id),
            action_id,
            "NOT_READY",
            summary=message,
            metadata={**trace, "missing_inputs": missing, "repairable_from_observations": repairable},
        )
        return InvocationResult(observation, message, {"projection": trace, "missing_inputs": missing})
    allocation = {
        "action_id": action_id,
        "agent_id": str(agent.id),
        "limits": {"duration": min(child_seconds, 120), "llm_calls": 0, "output_tokens": 0},
        "consumed": {},
        "status": "RUNNING",
    }
    state.child_allocations.append(allocation)
    loop.record("Child Budget Allocation", agent_id=str(agent.id), limits=allocation["limits"])
    # Persist a projected request snapshot before the single outbound attempt.
    audit_id = uuid.uuid4()
    async with store.sessions() as db:
        db.add(
            AgentCollaboration(
                id=audit_id,
                conversation_id=row.conversation_id,
                source_agent_id=row.agent_id,
                target_agent_id=agent.id,
                task="目标代理调用",
                question="按显式输入契约执行",
                status="running",
                call_depth=1,
                started_at=datetime.now(UTC),
                result_sources={"runtime": {"goal_id": str(row.id), "action_id": action_id, "authorization": origin}},
            )
        )
        await db.commit()
    payload.setdefault("proxy_runs", {})[action_id] = {
        "input": projected,
        "request_body": body,
        "projection": trace,
        "status": "started",
    }
    state.used_agents = sorted(set(state.used_agents) | {str(agent.id)})
    await loop.save()
    started = time.monotonic()
    status, summary, output = "UNKNOWN", "外部行动结果待核实", None
    try:
        raw = await send_proxy_request(
            agent.proxy_config,
            body,
            timeout_seconds=min(
                max(0.1, float(agent.proxy_config.get("timeout_ms", 30000)) / 1000),
                allocation["limits"]["duration"],
                loop.budget.remaining_time(),
            ),
            max_response_bytes=cfg.response_bytes,
        )
        output = map_proxy_output(agent.proxy_config, raw)
        status, summary = "SUCCESS", "代理已返回结果"
        remote_missing = []
        if isinstance(raw, dict) and (
            raw.get("requires_input") is True or raw.get("status") in ("not_ready", "input_required")
        ):
            status, summary = "NOT_READY", "代理要求补充输入"
            remote_missing = [
                x for x in raw.get("missing_inputs", []) if isinstance(x, str) and x in agent.input_schema["properties"]
            ]
        elif isinstance(raw, dict) and (
            raw.get("success") is False or raw.get("ok") is False or raw.get("status") in ("failed", "error")
        ):
            status, summary = "FAILED", "代理返回执行失败"
        elif agent.output_schema:
            try:
                if contract_errors(agent.output_schema, output):
                    status, summary = "FAILED", "代理输出未通过契约校验"
            except Exception:
                status, summary = "FAILED", "代理输出契约配置无效"
        payload["proxy_runs"][action_id].update(status=status, output=output)
        safe_output = (
            output if status == "SUCCESS" else {"status": status, "missing_inputs": remote_missing, "message": summary}
        )
        observation = Observation(
            "AGENT",
            "agent:" + str(agent.id),
            action_id,
            status,
            summary=summary,
            facts=[output] if status == "SUCCESS" else [],
            metadata={**trace, "authorization": origin, "output_validation": status, "missing_inputs": remote_missing},
        )
        text = json.dumps(safe_output, ensure_ascii=False)
        payload.setdefault("collaborations", []).append(
            {
                "action_id": action_id,
                "agent_name": agent.name,
                "agent_avatar": agent.avatar,
                "status": {"SUCCESS": "success", "NOT_READY": "input_required"}.get(status, "failed"),
                "summary": summary,
                "result": text,
                "duration_ms": round((time.monotonic() - started) * 1000),
                "authorization": origin,
            }
        )
        loop.record("Proxy observation", output_validation=status)
        return InvocationResult(observation, text, {"output": safe_output, "projection": trace})
    finally:
        allocation["consumed"]["duration"] = round(max(0, time.monotonic() - started))
        allocation["status"] = status
        with anyio.CancelScope(shield=True):
            payload["proxy_runs"][action_id]["status"] = status
            async with store.sessions() as db:
                record = await db.get(AgentCollaboration, audit_id)
                if record:
                    record.status = {"SUCCESS": "success", "NOT_READY": "input_required"}.get(status, "failed")
                    record.result_summary = summary
                    record.completed_at = datetime.now(UTC)
                    record.duration_ms = round((time.monotonic() - started) * 1000)
                    await db.commit()
            await loop.save()
