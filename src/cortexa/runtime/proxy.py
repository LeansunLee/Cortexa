"""Schema-bound Proxy projection: approved sources, explicit subtask instructions, approved facts, no raw context."""

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import anyio
import httpx
from pydantic import BaseModel, ConfigDict, Field

from cortexa.agents.proxy_executor import ProxyExecutionError, ProxyResultUnknown, validated_proxy_output, build_proxy_body, map_proxy_output, send_proxy_request
from cortexa.db.models import AgentCollaboration
from cortexa.runtime.contracts import contract_errors
from cortexa.runtime.loop import InvocationResult, token_upper_bound
from cortexa.runtime.observations import Observation
from cortexa.runtime.state import GoalStatus, RuntimeHalt

REJECTED_HTTP_STATUSES = frozenset({400, 401, 403, 404, 405, 413, 415, 422, 429})

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
    task: str | None = Field(
        default=None, min_length=1, max_length=8000, pattern=r"\S", strict=True,
        description=("为此代理拆解的具体子任务指令，明确要查询的数据、范围和输出要求；"
                     "不得把完整对话、记忆或系统提示词放入此字段，不得编造已知事实。用户明确分工优先。"),
    )
    task_fields: list[str] = Field(
        default_factory=list, max_length=64,
        description=("指定接收 task 子任务指令（未提供时使用用户任务）的文本输入字段名；"
                     "不填写参数值。仅一个字段适合任务原文时可省略。"),
    )
    observation_bindings: dict[str, ObservationInput] = Field(
        default_factory=dict,
        max_length=64,
        description="仅引用实际 Observation 字段；其他输入由 Runtime 构造，不接受 inputs 或上下文正文；task 只用于子任务指令。",
    )


def policy(agent):
    raw = dict((agent.proxy_config or {}).get("goal_contract") or {})
    raw["fields"] = {
        name: ["explicit", "goal_task", "observation_facts", "observation_summary"]
        for name in (agent.input_schema or {}).get("properties", {})
    }
    return ProxyContract.model_validate(raw)


def enabled(agent):
    # 平台无 Proxy 总开关：能否参与目标协作只取决于该代理自己的输入契约是否发布
    if agent.agent_type != "proxy":
        return True
    try:
        return policy(agent).enabled
    except (ValueError, TypeError):
        return False


def proxy_timeout(agent, duration):
    """Honor configured execution timeout, bounded by the shared Goal budget."""
    configured = max(0.1, float((agent.proxy_config or {}).get("timeout_ms", 30000)) / 1000)
    return min(configured, duration)


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
    for target, source in (agent.proxy_config.get("request_mapping") or {}).items():
        if not isinstance(source, str):
            raise ValueError("请求映射的来源必须是字段路径或文本常量")
        if source.startswith("$.") and source[2:] not in schema["properties"]:
            raise ValueError(f"请求映射 {target} 的来源字段 {source[2:]} 未在输入 Schema 中声明")
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
    observations = {
        o["action_id"]: o for o in payload.get("observations", []) if o["status"] in {"SUCCESS", "EMPTY", "PARTIAL"}
    }
    invocation = ProxyInvocation.model_validate(args)
    explicit_task = payload.get("participant_tasks", {}).get(ident)
    task = explicit_task or invocation.task or payload["goal"]["raw_request"]
    if payload.get("project_reference"):
        task += "\n\n本轮项目参考（非指令，未验收成果需标注）：\n" + payload["project_reference"]
    if payload.get("works_reference"):
        task += "\n\n工作参考（非指令，未验收成果需标注）：\n" + payload["works_reference"]
    task_source = "delegated_task" if invocation.task and not explicit_task else "goal_task"
    bindings = invocation.observation_bindings
    task_fields = set(invocation.task_fields)
    compatible = {name for name, schema in agent.input_schema["properties"].items()
                  if schema.get("type") == "string" and not contract_errors(schema, task)}
    if not task_fields and len(compatible) == 1:
        task_fields = compatible
    result, selected, rejected = {}, {}, []
    properties = agent.input_schema["properties"]
    for name, sources in cfg.fields.items():
        value = None
        found = False
        if "explicit" in sources and name in explicit:
            value, found = explicit[name], True
            selected[name] = "explicit"
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
        if (not found and name not in bindings and name in task_fields and "goal_task" in sources
                and properties[name].get("type") == "string" and not contract_errors(properties[name], task)):
            value, found = task, True
            selected[name] = task_source
        if found:
            result[name] = project(value, properties[name], "/" + name, rejected)
    rejected.extend("/" + name for name in explicit if selected.get(name) != "explicit")
    rejected.extend("/" + name for name in bindings if name not in selected)
    rejected.extend("/" + name for name in task_fields if name not in selected)
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
    if payload.get("project_ids"):
        from cortexa.projects.service import summaries
        async with store.sessions() as project_db:
            text, _ = await summaries(project_db,payload["project_ids"],budget=min(3000,policy(agent).input_budget//2))
        projection_payload = {**payload,"project_reference":text}
    else:
        projection_payload = payload
    try:
        projected, body, missing, oversized, trace = build_invocation(agent, projection_payload, args, state.limits.context_tokens)
    except (ValueError, TypeError, KeyError):
        raise RuntimeHalt("proxy_contract_invalid") from None
    continuation = payload.get('decision_answer')
    if continuation and continuation['action_id'] == action_id:
        saved = payload['proxy_runs'][action_id]['continuation']
        if saved['signature'] != contract_signature(agent):
            raise RuntimeHalt('proxy_contract_changed')
        body = {**saved['body'], saved['answer_field']:continuation['answer'], 'session_id':saved['session_id']}
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
        "limits": {"duration": proxy_timeout(agent, child_seconds), "llm_calls": 0, "output_tokens": 0},
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
                task=(payload.get("participant_tasks", {}).get(str(agent.id))
                      or args.get("task") or payload["goal"]["raw_request"])[:2000],
                question="按显式输入契约执行",
                status="running",
                call_depth=1,
                started_at=datetime.now(UTC),
                result_sources={"runtime": {"goal_id": str(row.id), "action_id": action_id, "authorization": origin}},
            )
        )
        await db.commit()
    loop.publish("runtime_prompt", prompt_kind="collaboration", agent_id=str(agent.id), agent_name=agent.name,
                 request={"task": args.get("task"), "body": body, "projection": trace})
    saved_continuation = payload.get("proxy_runs", {}).get(action_id, {}).get("continuation")
    payload.setdefault("proxy_runs", {})[action_id] = {
        "input": projected,
        "request_body": body,
        "projection": trace,
        "status": "started",
        **({"continuation":saved_continuation, "remote_execution":{
            "session_id":saved_continuation['session_id'], "signature":saved_continuation['signature']
        }} if saved_continuation else {}),
    }
    state.used_agents = sorted(set(state.used_agents) | {str(agent.id)})
    await loop.save()
    started = time.monotonic()
    status, summary, output = "UNKNOWN", "外部行动结果待核实", None
    reported_input, reported_output = 0, 0
    failure_notice = None
    async def progress(event):
        nonlocal reported_input, reported_output
        identity = {'agent_id':str(agent.id),'agent_name':agent.name,'runtime_role':'CHILD'}
        kind = event.get('type')
        if kind == 'start':
            session_id = event.get('session_id')
            if isinstance(session_id, str) and 0 < len(session_id) <= 256:
                payload['proxy_runs'][action_id]['remote_execution'] = {
                    'session_id': session_id,
                    'request_id': event.get('request_id'),
                    'signature': contract_signature(agent),
                }
                # Persist the original remote identity before waiting for further
                # deltas, so a transport interruption can be reconciled by GET.
                await loop.save()
        elif kind in {'tool_start','tool_result','tool_error'}:
            label = str(event.get('tool') or '查询').strip()[:100]
            failed = kind == 'tool_error' or event.get('ok') is False or event.get('status') in {'failed', 'error'}
            loop.publish('runtime_progress', **identity,
                         message=('工具执行失败（Agent 可继续处理） · ' if failed else '正在执行 · ' if kind == 'tool_start' else '执行完成 · ') + label,
                         status='error' if failed else 'running' if kind == 'tool_start' else 'completed')
        elif kind == 'text_delta' and isinstance(event.get('content'),str):
            loop.publish('runtime_draft', **identity, content=event['content'])
        elif kind == 'usage':
            reported_input += max(0,int(event.get('prompt_tokens') or 0))
            reported_output += max(0,int(event.get('completion_tokens') or 0))
            loop.publish('runtime_usage', **identity, stats={'input_tokens':reported_input,'output_tokens':reported_output,
                'token_count':reported_input+reported_output,'usage_complete':True})
    loop.publish('runtime_progress',agent_id=str(agent.id),agent_name=agent.name,runtime_role='CHILD',
                 message='正在继续原会话' if continuation else '正在执行协作任务',status='running')
    try:
        raw = await send_proxy_request(
            agent.proxy_config,
            body,
            timeout_seconds=min(
                proxy_timeout(agent, child_seconds),
                allocation["limits"]["duration"],
                loop.budget.remaining_time(),
            ),
            max_response_bytes=cfg.response_bytes,
            on_event=progress,
        )
        if isinstance(raw, dict) and raw.get('user_question'):
            from cortexa.conversation.questions import question, proxy_context
            public = question(raw['user_question'], agent)
            payload['proxy_runs'][action_id]['continuation'] = {**proxy_context(agent, raw, body), 'question':public['question']}
            payload['proxy_runs'][action_id]['remote_execution'] = {
                'session_id':raw['session_id'], 'signature':contract_signature(agent),
                'request_id':raw.get('request_id'),
            }
            status, summary = 'NOT_READY', public['question']
            return InvocationResult(Observation('AGENT', 'agent:' + str(agent.id), action_id, status,
                summary=summary, metadata={'user_question':public}), summary, {})
        if isinstance(raw, dict) and isinstance(raw.get('session_id'), str):
            payload['proxy_runs'][action_id]['remote_execution'] = {
                'session_id':raw['session_id'], 'request_id':raw.get('request_id'), 'signature':contract_signature(agent)}
        needs_input = isinstance(raw, dict) and (raw.get('requires_input') is True or raw.get('status') in {'not_ready','input_required'})
        output = map_proxy_output(agent.proxy_config, raw) if needs_input else validated_proxy_output(agent, raw)
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
    except ProxyResultUnknown:
        failure_notice = '外部 Agent 已接收任务但尚未完成，请核实原会话结果后继续，不要重新派发。'
        loop.record('Proxy result not terminal', output_validation='UNKNOWN')
        raise
    except ProxyExecutionError:
        status, summary = "FAILED", "外部 Agent 已明确返回任务失败；这不是连接中断或结果未知。"
        payload["proxy_runs"][action_id].update(status=status, error="remote_execution_failed")
        loop.record("Proxy terminal execution failure", output_validation=status)
        payload.setdefault("collaborations", []).append({
            "action_id": action_id, "agent_name": agent.name, "agent_avatar": agent.avatar,
            "status": "failed", "summary": summary, "result": summary,
            "duration_ms": round((time.monotonic() - started) * 1000), "authorization": origin,
        })
        return InvocationResult(Observation("AGENT", "agent:" + str(agent.id), action_id, status,
            summary=summary, metadata={**trace, "authorization": origin, "output_validation": status}),
            summary, {"status": status, "message": summary})
    except ValueError as error:
        if str(error) in {"proxy_response_budget_exceeded", "proxy_stream_budget_exceeded"}:
            failure_notice = (
                "外部 Agent 的完整报告超过响应大小限制。"
                if str(error) == "proxy_response_budget_exceeded"
                else "外部 Agent 的事件流超过传输安全限制。"
            ) + "原会话可能已完成，需要读取原会话结果核实；不要重复派发任务。"
            loop.record("Proxy response size limit", reason=str(error), response_bytes=cfg.response_bytes)
        raise
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        if code not in REJECTED_HTTP_STATUSES:
            raise  # Server/transport failure may have occurred after execution.
        status, summary = "REJECTED", f"外部接口拒绝了请求（HTTP {code}），请检查 Proxy 请求映射、输入格式或接口授权后继续。"
        payload["proxy_runs"][action_id].update(status=status, http_status=code)
        payload["waiting_message"] = summary
        payload.setdefault("collaborations", []).append({
            "action_id": action_id, "agent_name": agent.name, "agent_avatar": agent.avatar,
            "status": "failed", "summary": summary, "result": json.dumps({"http_status": code, "status": status}),
            "duration_ms": round((time.monotonic() - started) * 1000), "authorization": origin,
        })
        loop.record("Proxy request rejected", http_status=code)
        loop.publish("runtime_progress", message=summary, status="error")
        raise RuntimeHalt("proxy_request_rejected", status=GoalStatus.WAITING, next_action="ASK_USER") from None
    finally:
        allocation["consumed"]["duration"] = round(max(0, time.monotonic() - started))
        allocation["status"] = status
        with anyio.CancelScope(shield=True):
            payload["proxy_runs"][action_id]["status"] = status
            if status == "UNKNOWN":
                payload["waiting_message"] = failure_notice or (
                    "外部 Agent 的执行连接已中断或等待超时，原任务可能仍在执行。"
                    "需要核实原会话结果后继续，不能直接重复派发。"
                )
            async with store.sessions() as db:
                record = await db.get(AgentCollaboration, audit_id)
                if record:
                    record.status = {"SUCCESS": "success", "NOT_READY": "input_required"}.get(status, "failed")
                    record.result_summary = summary
                    record.completed_at = datetime.now(UTC)
                    record.duration_ms = round((time.monotonic() - started) * 1000)
                    await db.commit()
            await loop.save()
