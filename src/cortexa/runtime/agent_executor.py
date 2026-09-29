"""Agent Capability delegates to the bounded Goal Loop, sharing the parent's budgets."""

import json
import time
import uuid
from datetime import UTC, datetime

import anyio
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from cortexa.agents.prompts import build_system_prompt, reference_message
from cortexa.collaboration.schemas import AgentHandoff, AgentHandoffResult
from cortexa.config.llm_providers import create_llm
from cortexa.db.models import AgentCollaboration, Workspace
from cortexa.runtime.adapters import agent_adapter
from cortexa.runtime.bindings import prepare_bindings
from cortexa.runtime.collaboration import authorize_agent, discover
from cortexa.runtime.contracts import contract_errors
from cortexa.runtime.loop import Binding, GoalLoop, InvocationResult, serialize_messages, token_upper_bound
from cortexa.runtime.observations import Observation
from cortexa.runtime.policy import resolve_effective_policy
from cortexa.runtime.proxy import ProxyInvocation, contract_signature, invoke_proxy, policy
from cortexa.runtime.state import BudgetLimits, GoalState, GoalStatus, RuntimeHalt, tighten_limits
from cortexa.tools.runtime import should_require_business_tool
from cortexa.usage.context import usage_scope


class AgentInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: str = Field(min_length=1, max_length=4000, description="本次委托的具体任务，不包含主 Agent 私有上下文")
    inputs: dict = Field(default_factory=dict, description="目标 Agent 输入契约需要的结构化字段")
    observation_ids: list[str] = Field(
        default_factory=list, max_length=5, description="所需已完成 Observation 的 action_id；由 Runtime 投影其实际结果"
    )


def check_path(source_id, target_id, path, max_depth):
    chain = path or [str(source_id)]
    if str(target_id) in chain or str(source_id) == str(target_id):
        raise RuntimeHalt("collaboration_cycle")
    if len(chain) > max_depth:
        raise RuntimeHalt("budget_exhausted:agent_depth")
    return [*chain, str(target_id)]


def allocate_child_limits(parent_budget, target_limits, remaining_slots):
    """Grant a bounded share while leaving the parent's synthesis reserve untouched."""
    parent = parent_budget.state
    limits = tighten_limits(parent.limits, target_limits.model_dump()).model_dump()
    for key in ("duration", "llm_calls", "tool_calls", "tool_iterations", "web_calls", "output_tokens", "max_steps"):
        available = parent_budget.remaining(key, protect_finalization=True)
        if key == "duration" and remaining_slots > 1:
            # Keep a usable time window for later collaborators without forcing
            # the current one to stop while the parent still has ample time.
            reserve_for_others = min(45, available // remaining_slots) * (remaining_slots - 1)
            limits[key] = min(limits[key], available - reserve_for_others)
        else:
            limits[key] = min(limits[key], available // max(1, remaining_slots))
        if key == "llm_calls" and available >= 2 and limits[key] < 2 and target_limits.llm_calls >= 2:
            limits[key] = 2
    limits["agent_calls"] = 0
    limits["max_collaborators"] = 0
    if limits["duration"] < 1 or limits["max_steps"] < 1 or limits["llm_calls"] < 1 or limits["output_tokens"] < 1:
        return None
    return BudgetLimits(**limits)


async def prepare_agent_bindings(source, state, payload, loop, store, row, config):
    async with store.sessions() as db:
        candidates, _ = await discover(db, source, state, payload, config())
    bindings = []
    for target in candidates:
        descriptor = agent_adapter(target).descriptor
        descriptor.requires_confirmation = False  # Goal-scoped checks below, including ASK before invocation.
        descriptor.risk_level = "low"
        descriptor.timeout = min(120, state.limits.duration)
        invocation_schema = ProxyInvocation if target.agent_type == "proxy" else AgentInvocation
        descriptor.input_schema = invocation_schema.model_json_schema()
        descriptor.constraints["target_input_contract"] = target.input_schema or {}
        ident = str(target.id)
        explicit_task = payload.get("participant_tasks", {}).get(ident, "")
        description = f"协作角色：{target.role or 'AI助手'}\n执行职责：{(target.responsibilities or '')[:1200]}"
        if explicit_task:
            description += "\n用户明确分工：" + explicit_task
        description += "\n输入契约：" + json.dumps(target.input_schema or {}, ensure_ascii=False)
        signature = contract_signature(target)
        if target.agent_type == "proxy":
            description += "\n字段来源白名单：" + json.dumps(policy(target).fields, ensure_ascii=False)
            description += (
                "\n只提交 observation_bindings；用户显式参数与获准的目标文本由 Runtime 构造，"
                "不要提交 task/inputs 或原始上下文。"
            )
            descriptor.context_policy = {
                "mode": "explicit_allow",
                "enforced_by": "goal_proxy_projector",
                "strict_projection": True,
            }
        adapter = agent_adapter(target)
        adapter.descriptor = descriptor

        async def authorize(target_id=target.id, signature=signature):
            check_path(source.id, target_id, state.active_agent_path, state.limits.agent_depth)
            async with store.sessions() as db:
                current, _ = await authorize_agent(db, source.id, target_id, state, payload, config())
                if current.agent_type == "proxy" and contract_signature(current) != signature:
                    raise RuntimeHalt("proxy_contract_changed")

        async def invoke(args, action_id, target_id=target.id, adapter=adapter):
            async with store.sessions() as db:
                fresh, origin = await authorize_agent(db, source.id, target_id, state, payload, config())
                workspace = await db.get(Workspace, fresh.workspace_id)
                workspace_policy = await db.scalar(
                    select(Workspace.runtime_policy).where(Workspace.id == fresh.workspace_id)
                )
            ident = str(fresh.id)
            chain = check_path(source.id, target_id, state.active_agent_path, state.limits.agent_depth)
            if fresh.agent_type == "proxy":
                return await invoke_proxy(fresh, args, action_id, origin, state, payload, loop, store, row)
            errors = contract_errors(fresh.input_schema, args.get("inputs", {}))
            if errors:
                observation = Observation(
                    "AGENT",
                    adapter.descriptor.id,
                    action_id,
                    "NOT_READY",
                    summary="Agent 输入契约未满足",
                    metadata={"missing_inputs": sorted({str(e.path[0]) if e.path else "inputs" for e in errors})},
                )
                return InvocationResult(
                    observation,
                    "目标 Agent 输入不完整，请补充：" + json.dumps(fresh.input_schema, ensure_ascii=False),
                    {"validation": "not_ready"},
                )
            requested = set(args.get("observation_ids", []))
            known = {
                o["action_id"]: o
                for o in payload.get("observations", [])
                if o["status"] in {"SUCCESS", "EMPTY", "PARTIAL"}
            }
            if not requested <= set(known):
                raise RuntimeHalt("dependency_not_ready", status=GoalStatus.WAITING, next_action="ASK_USER")
            references = [
                {
                    "action_id": key,
                    "facts": known[key]["facts"],
                    "evidence": known[key]["evidence"],
                    "result": known[key]["raw_result"],
                }
                for key in sorted(requested)
            ]
            task = payload.get("participant_tasks", {}).get(ident) or args["task"]
            invocation = {"task": task, "inputs": args.get("inputs", {}), "dependencies": references}
            if token_upper_bound(invocation) > min(8000, state.limits.context_tokens):
                raise RuntimeHalt("agent_input_budget_exceeded")
            target_policy = resolve_effective_policy(config(), workspace_policy, fresh)
            pending_explicit = set(state.explicit_agents) - set(state.used_agents)
            remaining_slots = (
                max(1, len(pending_explicit))
                if pending_explicit
                else min(5, max(1, state.limits.max_collaborators - len(state.used_agents)))
            )
            child_limits = allocate_child_limits(loop.budget, target_policy.effective_budget, remaining_slots)
            if child_limits is None:
                resource = next(
                    (
                        key
                        for key in ("llm_calls", "output_tokens", "duration", "max_steps")
                        if loop.budget.remaining(key, protect_finalization=True) < remaining_slots
                    ),
                    "output_tokens",
                )
                loop.budget.mark_failure(resource)
                raise RuntimeHalt("child_budget_unavailable")
            handoff = AgentHandoff(
                source_agent_id=str(source.id),
                target_agent_id=ident,
                task=task,
                question=task,
                include_history=False,
                dependency_results=references,
            )
            collab_id = uuid.uuid4()
            async with store.sessions() as db:
                db.add(
                    AgentCollaboration(
                        id=collab_id,
                        conversation_id=row.conversation_id,
                        source_agent_id=source.id,
                        target_agent_id=target_id,
                        task=task,
                        question=task,
                        status="running",
                        call_depth=len(chain) - 1,
                        started_at=datetime.now(UTC),
                        result_sources={
                            "runtime": {"goal_id": str(row.id), "action_id": action_id, "authorization": origin}
                        },
                    )
                )
                await db.commit()
            state.used_agents = sorted(set(state.used_agents) | {ident})
            state.active_agent_path = chain
            loop.record("Agent collaboration", authorization=origin, depth=len(chain) - 1)
            allocation = {
                "action_id": action_id,
                "agent_id": ident,
                "limits": child_limits.model_dump(),
                "consumed": {},
                "status": "RUNNING",
            }
            state.child_allocations.append(allocation)
            loop.record("Child Budget Allocation", agent_id=ident, limits=allocation["limits"])
            child_state = GoalState(
                limits=child_limits,
                policy_trace=target_policy.trace,
                collaboration_mode=target_policy.collaboration_mode,
                runtime_role="CHILD",
                runtime_agent_id=ident,
            )
            child_payload = {
                "goal_id": str(row.id),
                "sources": [],
                "messages": serialize_messages(
                    [
                        {"role": "system", "content": build_system_prompt(fresh, workspace)},
                        {"role": "user", "content": handoff.task},
                        reference_message("本次授权输入与依赖结果", invocation),
                    ]
                ),
            }
            accounted = {}

            async def checkpoint(child, snapshot):
                # Reserve all child work against parent before child execution. A child
                # cannot mint another budget or replace the parent's started Action.
                costs = {
                    key: min(value, getattr(child_limits, key)) - accounted.get(key, 0)
                    for key, value in child.consumed.items()
                    if key in child_limits.model_fields
                    and min(value, getattr(child_limits, key)) > accounted.get(key, 0)
                }
                if any(loop.budget.remaining(key, protect_finalization=True) < value for key, value in costs.items()):
                    raise RuntimeHalt("child_budget_exceeds_parent_reserve")
                loop.budget.reserve(**costs)
                for key, value in costs.items():
                    accounted[key] = accounted.get(key, 0) + value
                allocation["consumed"] = dict(accounted)
                state.active_agent_action = {
                    "agent_id": ident,
                    "action": child.current_action.model_dump() if child.current_action else None,
                }
                payload.setdefault("agent_runs", {})[action_id] = {
                    "state": child.model_dump(mode="json"),
                    "payload": snapshot,
                }
                await loop.save()

            async def child_authorize():
                await loop.authorize()
                async with store.sessions() as db:
                    current, _ = await authorize_agent(
                        db, source.id, target_id, state, payload, config(), in_progress=True
                    )
                    current_workspace = await db.scalar(
                        select(Workspace.runtime_policy).where(Workspace.id == current.workspace_id)
                    )
                    current_policy = resolve_effective_policy(config(), current_workspace, current)
                    child_state.limits = tighten_limits(
                        child_state.limits, current_policy.effective_budget.model_dump()
                    )
                    if current.agent_type == "proxy":
                        raise RuntimeHalt("collaboration_unavailable")
                child_state.policy_trace = current_policy.trace

            child_loop = GoalLoop(child_state, child_payload, checkpoint, child_authorize)
            started = time.monotonic()
            result = None
            try:
                async with store.sessions() as db:
                    child_bindings, business = await prepare_bindings(fresh, task, child_payload["sources"], db)
                model = create_llm(fresh.model)
                if hasattr(model, "max_retries"):
                    model = model.model_copy(update={"max_retries": 0})
                with usage_scope(
                    "collaboration_execute",
                    agent_id=ident,
                    agent_name=fresh.name,
                    goal_id=str(row.id),
                    action_id=action_id,
                ):
                    async for _ in child_loop.run(
                        model,
                        child_bindings,
                        required_names=[t.name for t in business]
                        if should_require_business_tool(task, business)
                        else [],
                    ):
                        pass
                if child_state.reason == "action_result_unknown":
                    raise TimeoutError("nested_action_unknown")
                status = (
                    "success"
                    if child_state.status == GoalStatus.COMPLETE
                    else "input_required"
                    if child_state.reason == "missing_inputs"
                    else "failed"
                )
                output = child_loop.reply or child_payload.get("waiting_message", "")
                useful = [
                    item
                    for item in child_payload.get("observations", [])
                    if item.get("status") in {"SUCCESS", "PARTIAL"}
                ]
                if not output and useful:
                    output = "已取得部分结果，尚未完成最终分析：" + "；".join(
                        item.get("summary", "已取得结果") for item in useful[:5]
                    )
                    status = "partial"
                if output and child_state.partial:
                    status = "partial"
                elif output and status == "failed" and useful:
                    status = "partial"
                if not output and status == "failed":
                    failure = child_state.budget_failure
                    if failure and failure["resource"] == "duration" and not child_payload.get("observations"):
                        output = (
                            f"目标角色 {fresh.role or 'AI助手'} 的模型推理在分配的 {failure['limit']} 秒内未取得可用回复；"
                            "本次尚未执行工具。"
                        )
                    elif failure:
                        status_text = "预算已耗尽" if failure["current"] >= failure["limit"] else "可用预算不足"
                        output = f"目标角色 {fresh.role or 'AI助手'} 的 {failure['resource']} {status_text}，未能完成协作。"
                    else:
                        output = {
                            "budget_exhausted:output_tokens": "目标 Agent 的共享输出预算已耗尽",
                            "budget_exhausted:llm_calls": "目标 Agent 的共享模型调用预算已耗尽",
                            "context_budget_exceeded": "目标 Agent 的上下文超过预算",
                            "required_capability_not_used": "必需的数据查询未完成；请检查子任务预算或数据能力",
                        }.get(child_state.reason, "目标 Agent 未完成任务")
                if status == "success" and fresh.output_schema:
                    try:
                        parsed = json.loads(output)
                        if contract_errors(fresh.output_schema, parsed):
                            status = "failed"
                    except (ValueError, TypeError):
                        status = "failed"
                result = AgentHandoffResult(
                    status=status,
                    summary=output[:200] or "目标 Agent 未完成任务",
                    result=output,
                    sources=child_payload["sources"],
                    confidence=None,
                    duration_ms=round((time.monotonic() - started) * 1000),
                    usage=child_loop.usage.stats(),
                    input_snapshot={"type": "goal_projection", "selected_observations": sorted(requested)},
                )
                observation = adapter.observe(result, action_id)
                observation.metadata.update(
                    authorization=origin, goal_id=str(row.id), target_agent_id=ident, child_reason=child_state.reason
                )
                allocation["status"] = status.upper()
                loop.record(
                    "Child Budget Result",
                    agent_id=ident,
                    status=status,
                    consumed=child_state.consumed,
                    budget_failure=child_state.budget_failure,
                )
                payload.setdefault("collaborations", []).append(
                    {
                        "action_id": action_id,
                        "agent_name": fresh.name,
                        "agent_avatar": fresh.avatar,
                        "status": status,
                        "summary": result.summary,
                        "result": output,
                        "duration_ms": result.duration_ms,
                        "authorization": origin,
                    }
                )
                payload["sources"].extend(result.sources)
                return InvocationResult(
                    observation,
                    json.dumps(
                        {
                            "action_id": action_id,
                            "status": observation.status,
                            "result": output,
                            "sources": result.sources,
                        },
                        ensure_ascii=False,
                    ),
                    result.model_dump(mode="json"),
                )
            finally:
                # Merge actual provider usage once, including interrupted child runs.
                for key in ("calls", "reported", "input_tokens", "output_tokens", "total_tokens"):
                    setattr(loop.usage, key, getattr(loop.usage, key) + getattr(child_loop.usage, key))
                # These costs already happened. Record them even if output or time
                # exceeded a limit; cleanup must not mask cancellation/unknown work.
                with anyio.CancelScope(shield=True):
                    try:
                        for key, value in child_state.consumed.items():
                            if key not in child_limits.model_fields:
                                continue
                            delta = max(0, min(value, getattr(child_limits, key)) - accounted.get(key, 0))
                            charged = min(delta, loop.budget.remaining(key, protect_finalization=True))
                            state.consumed[key] = state.consumed.get(key, 0) + charged
                            if charged < delta:
                                allocation.setdefault("overrun", {})[key] = delta - charged
                        allocation["consumed"] = {
                            key: min(value, getattr(child_limits, key))
                            for key, value in child_state.consumed.items()
                            if key in child_limits.model_fields
                        }
                        if allocation["status"] == "RUNNING":
                            allocation["status"] = child_state.status
                        payload.setdefault("agent_runs", {})[action_id] = {
                            "state": child_state.model_dump(mode="json"),
                            "payload": child_payload,
                        }
                        async with store.sessions() as db:
                            record = await db.get(AgentCollaboration, collab_id)
                            if record:
                                record.status = result.status if result else "failed"
                                record.result_summary = result.summary if result else "执行中断，结果待核实"
                                record.result_content = result.result[:1000] if result else None
                                record.completed_at = datetime.now(UTC)
                                record.duration_ms = round((time.monotonic() - started) * 1000)
                                record.result_sources = {
                                    **(record.result_sources or {}),
                                    "items": child_payload["sources"],
                                }
                                await db.commit()
                    finally:
                        state.active_agent_path = []
                        state.active_agent_action = None
                        await loop.save()

        async def placeholder(task: str):
            raise RuntimeError("Use Goal agent executor")

        tool = StructuredTool.from_function(
            coroutine=placeholder, name="agent_" + target.id.hex, description=description, args_schema=invocation_schema
        )
        bindings.append(
            Binding(
                tool,
                adapter,
                invoke,
                authorize,
                cache_scope={
                    "contract": signature,
                    "inputs": payload.get("participant_inputs", {}).get(ident, {}),
                    "task": payload.get("participant_tasks", {}).get(ident),
                }
                if target.agent_type == "proxy"
                else None,
            )
        )
    return bindings
