"""Proof-based GET reconciliation of a single unknown external action; never POST it again."""

import json
import uuid

from fastapi import HTTPException
from langchain_core.messages import messages_from_dict
from sqlalchemy import select

from cortexa.agents.prompts import reference_message
from cortexa.agents.proxy_executor import response_limit, validated_proxy_output
from cortexa.db.models import AgentCollaboration
from cortexa.runtime.loop import InvocationResult, observation_record, serialize_messages
from cortexa.runtime.observations import Observation
from cortexa.runtime.proxy import contract_signature
from cortexa.runtime.state import GoalState, GoalStatus
from cortexa.security.access import require_agent_use


def verified_result(target, run, remote, public_question=None):
    identity = run.get("remote_execution") or {}
    if remote.get("status") == "running":
        raise HTTPException(409, "外部 Agent 仍在执行，请稍后核实；不会重新派发")
    if identity.get("signature") != contract_signature(target):
        raise HTTPException(409, "代理契约已变化，无法自动接回旧结果")
    if remote.get("status") != "completed" or remote.get("session_id") != identity.get("session_id"):
        raise HTTPException(409, "尚未取得原会话的完整成功结果；不会重新派发")
    if identity.get("request_id") and remote.get("request_id") and identity["request_id"] != remote["request_id"]:
        raise HTTPException(409, "原会话请求标识不匹配")
    body = run.get("request_body") or {}
    continuation = run.get("continuation") or {}
    mapped = [
        key
        for key, source in (target.proxy_config.get("request_mapping") or {}).items()
        if source.startswith("$.") and source[2:] in (run.get("input") or {}) and isinstance(body.get(key), str)
    ]
    single = [key for key, value in body.items() if isinstance(value, str) and key != "session_id"]
    field = (
        continuation.get("answer_field")
        or target.proxy_config.get("answer_field")
        or (mapped[0] if len(mapped) == 1 else single[0] if len(single) == 1 else None)
    )
    expected = body.get(field)
    if not isinstance(expected, str) or remote.get("answered_prompt") != expected:
        raise HTTPException(409, "原会话结果与本次任务或回答不匹配")
    if continuation:
        prior = continuation.get("question") or (
            (public_question or {}).get("question")
            if (public_question or {}).get("agent_id") == str(target.id)
            else None
        )
        if not prior or remote.get("prior_question") != prior:
            raise HTTPException(409, "原会话缺少匹配的提问身份，不能接回其他轮次的回答")
    try:
        output = validated_proxy_output(target, remote)
    except (ValueError, TypeError):
        raise HTTPException(409, "原会话报告未通过输出契约校验") from None
    if output is None or len(json.dumps(output, ensure_ascii=False).encode()) > response_limit(target.proxy_config):
        raise HTTPException(409, "原会话报告未满足输出契约或大小限制")
    return output


async def reconcile_goal(conv_id, goal_id, public_question=None):
    from cortexa.api.goals import environment, preserve_saved_budget, store, stream_response

    row = await store.get(conv_id, goal_id)
    state = GoalState.model_validate(row.state)
    action = state.current_action
    if row.status == GoalStatus.RUNNING:
        raise HTTPException(409, "原任务仍在执行，不能重复恢复")
    if not action or action.phase != "unknown" or not (action.capability_id or "").startswith("agent:"):
        raise HTTPException(409, "本轮没有需要核实的代理调用")
    payload = store.files.read(row.id, row.artifacts["snapshot"])
    run = payload.get("proxy_runs", {}).get(action.id, {})
    identity = run.get("remote_execution") or {}
    if not identity.get("session_id"):
        raise HTTPException(409, "未记录原会话标识，不能安全核实或重复调用")
    async with store.sessions() as db:
        target = await require_agent_use(db, uuid.UUID(action.capability_id.removeprefix("agent:")))
    if target.agent_type != "proxy":
        raise HTTPException(409, "该行动不是可只读核实的外部代理")
    if identity.get("signature") != contract_signature(target):
        raise HTTPException(409, "代理契约已变化，请人工核实旧任务")
    from cortexa.agents import proxy_executor

    remote = await proxy_executor.read_proxy_turn(target.proxy_config, identity["session_id"])
    output = verified_result(target, run, remote, public_question)
    text = json.dumps(output, ensure_ascii=False)
    observation = Observation(
        "AGENT",
        action.capability_id,
        action.id,
        "SUCCESS",
        summary="已从原会话核实完整结果，未重复派发",
        facts=[output],
    )
    payload.setdefault("observations", []).append(
        observation_record(InvocationResult(observation, text, {"output": output}))
    )
    payload["messages"] = serialize_messages(
        [*messages_from_dict(payload["messages"]), reference_message("原外部会话的核实结果（无需重复查询）", output)]
    )
    payload.setdefault("cache", {})[action.fingerprint] = {"status": "SUCCESS", "text": text, "repairable": False}
    run.update(status="SUCCESS", output=output, recovered=True)
    payload.setdefault("collaborations", []).append(
        {
            "action_id": action.id,
            "agent_name": target.name,
            "agent_avatar": target.avatar,
            "status": "success",
            "summary": observation.summary,
            "result": text,
        }
    )
    for key in ("waiting_message", "decision_answer", "decision_continuation", "pending_question"):
        payload.pop(key, None)
    payload["force_finalizing"] = False
    action.phase, action.observation_status = "completed", "SUCCESS"
    for allocation in state.child_allocations:
        if allocation.get("action_id") == action.id:
            allocation["status"] = "SUCCESS"
    agent, workspace, policy = await environment(conv_id)
    state.limits = preserve_saved_budget(policy, state.limits.model_dump())
    state.status, state.reason, state.next_action = GoalStatus.RUNNING, None, "CONTINUE"
    state.result_message_id = None
    # CAS wins once. A racing request cannot start another worker.
    await store.checkpoint(row, state, payload)
    async with store.sessions() as db:
        rows = await db.scalars(select(AgentCollaboration).where(AgentCollaboration.conversation_id == conv_id))
        for audit in rows:
            if (audit.result_sources or {}).get("runtime", {}).get("action_id") == action.id:
                audit.status, audit.result_summary = "success", observation.summary
        await db.commit()
    return stream_response(row, state, payload, agent, workspace)
