"""Bounded Goal Loop: one model response evaluates evidence and chooses the next action.

Native tool_calls are the structured reasoning decision. Text without tool calls is
final synthesis. No mandatory Planner/Evaluator/enrichment model calls are added.
"""

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import (
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
    messages_from_dict,
    messages_to_dict,
)
from pydantic import ValidationError
from pydantic_core import PydanticUndefined

from cortexa.agents.usage import UsageTotals
from cortexa.runtime.adapters import CapabilityAdapter
from cortexa.runtime.observations import Observation
from cortexa.runtime.projection import model_result_text
from cortexa.runtime.recovery import reset_unstarted_agent, unstarted_agent_action
from cortexa.runtime.state import Action, BudgetPhase, GoalStatus, RuntimeBudget, RuntimeHalt
from cortexa.usage.context import usage_scope


@dataclass
class InvocationResult:
    observation: Observation
    text: str
    archive: Any


@dataclass
class Binding:
    tool: Any
    adapter: CapabilityAdapter
    invoke: Callable[[dict, str], Awaitable[InvocationResult]]
    authorize: Callable[[], Awaitable[None]] | None = None
    cache_scope: dict | None = None


def serialize_messages(messages):
    from langchain_core.messages import convert_to_messages

    return messages_to_dict(convert_to_messages(messages))


def observation_record(result):
    observation = result.observation
    return {
        "source_type": observation.source_type,
        "source_id": observation.source_id,
        "action_id": observation.action_id,
        "status": observation.status,
        "summary": observation.summary,
        "facts": observation.facts,
        "evidence": observation.evidence,
        "confidence": observation.confidence,
        "error": observation.error,
        "metadata": observation.metadata,
        "occurred_at": observation.occurred_at.isoformat(),
        "raw_result": result.archive,
    }


def token_upper_bound(value):
    # Conservative UTF-8 byte budget plus message framing; no lossy truncation.
    return len(json.dumps(value, ensure_ascii=False, default=str).encode()) + 64


def valid_tool_call_batch(calls):
    """Reject incomplete provider calls before any action in their batch runs."""
    ids = []
    for call in calls:
        if (
            not isinstance(call, dict)
            or not isinstance(call.get("name"), str)
            or not call["name"].strip()
            or not isinstance(call.get("id"), str)
            or not call["id"].strip()
            or not isinstance(call.get("args"), dict)
        ):
            return False
        ids.append(call["id"])
    return len(ids) == len(set(ids))


def empty_tool_call_placeholder(call):
    """Recognize a provider's empty streaming slot, not a malformed action."""
    return (
        isinstance(call, dict)
        and not call.get("name")
        and not call.get("id")
        and call.get("args") == {}
    )


RAW_TOOL_CALL_BLOCK = re.compile(r"<tool_call\b[^>]*>.*?(?:</tool_call\s*>|(?=<tool_call\b)|\Z)", re.S | re.I)
RAW_TOOL_TAG = re.compile(r"</?(?:function|parameter)\b[^>]*>", re.I)


def raw_tool_call_syntax(text):
    """Detect provider tool-call markup emitted as plain text (observed with Mimo)."""
    return bool(re.search(r"<\s*/?\s*tool_call\b|<function=[\w.\-]", text or "", re.I))


def strip_raw_tool_calls(text):
    """Remove tool-call markup so leftover prose can still serve as the reply."""
    cleaned = RAW_TOOL_CALL_BLOCK.sub("", text or "")
    return RAW_TOOL_TAG.sub("", cleaned)


def repair_tool_args(schema, args, error):
    """Deterministically repair invalid tool arguments, or return None.

    A field the model sent with an out-of-range/null value falls back to its
    schema default by removal; unknown extra fields are dropped. Missing or
    type-invalid required fields without a default are not repairable and must
    still reach the user.
    """
    fields = getattr(schema, "model_fields", None)
    if fields is None or not isinstance(args, dict):
        return None
    repaired, dropped = dict(args), []
    for item in error.errors():
        loc = item.get("loc") or ()
        if not loc or not isinstance(loc[0], str):
            return None
        name = loc[0]
        if name in repaired:
            info = fields.get(name)
            if info is None:
                if item.get("type") != "extra_forbidden":
                    return None
            elif info.default is PydanticUndefined and info.default_factory is None:
                return None
            repaired.pop(name, None)
        elif fields.get(name) is not None:
            return None
        if name not in dropped:
            dropped.append(name)
    return (repaired, dropped) if dropped else None


class GoalLoop:
    def __init__(self, state, payload, checkpoint, authorize, *, event_sink=None, agent_name=None):
        self.state, self.payload = state, payload
        self.budget = RuntimeBudget(state)
        self.checkpoint, self.authorize = checkpoint, authorize
        self.usage = UsageTotals()
        self.reply = ""
        self.trace = []
        self.event_sink = event_sink
        self.agent_name = agent_name

    def publish(self, kind, **details):
        if self.event_sink:
            self.event_sink({"type": kind, "agent_id": self.state.runtime_agent_id,
                             "agent_name": self.agent_name, "runtime_role": self.state.runtime_role,
                             "action_id": self.state.current_action.id if self.state.current_action else None,
                             **details})

    def record(self, event, **details):
        # Runtime metadata and authorized retrieval diagnostics. Access to traces
        # is filtered by existing conversation debug permissions. Never log auth secrets.
        self.trace.append(
            {
                "seq": self.trace[-1]["seq"] + 1 if self.trace else 1,
                "timestamp": datetime.now(UTC).isoformat(),
                "stage": "runtime_goal",
                "title": event,
                "status": "error" if self.state.budget_failure else "info",
                "detail": {
                    "status": self.state.status,
                    "reason": self.state.reason,
                    "steps": self.state.consumed.get("max_steps", 0),
                    "budget_phase": self.state.budget_phase,
                    "consumed_budget": dict(self.state.consumed),
                    "remaining_budget": {
                        name: self.budget.remaining(name)
                        for name in (
                            "duration",
                            "llm_calls",
                            "tool_calls",
                            "web_calls",
                            "agent_calls",
                            "agent_depth",
                            "max_collaborators",
                            "max_steps",
                            "max_replans",
                            "max_failures",
                            "tool_iterations",
                            "context_tokens",
                            "output_tokens",
                        )
                    },
                    "finalization_reserve": self.state.finalization_reserve,
                    "runtime_role": self.state.runtime_role,
                    "agent_id": self.state.runtime_agent_id,
                    **({"budget_failure": self.state.budget_failure} if self.state.budget_failure else {}),
                    **details,
                },
            }
        )
        self.trace = self.trace[-128:]

    async def save(self):
        self.budget.sync()
        await self.checkpoint(self.state, self.payload)

    async def begin(self, action, **costs):
        await self.authorize()
        self.budget.reserve(max_steps=1, **costs)
        self.state.current_action = action
        self.state.next_action = "CONTINUE"
        self.record("Action started", kind=action.kind)
        await self.save()  # Must durably succeed before calling any model/tool.
        self.publish("runtime_progress", message="正在分析任务并生成回复" if action.kind == "REASON" else "正在执行查询或协作", status="running")

    async def run(self, model, bindings, *, required_names=()):
        messages = messages_from_dict(self.payload["messages"])
        by_name = {binding.tool.name: binding for binding in bindings}
        tools = [binding.tool for binding in bindings]
        from cortexa.runtime.completion import completion_tool, CompletionReview, validate_completion, partial_requested
        completion = completion_tool() if "ask_user" in by_name else None
        required_satisfied = self.payload.get("required_satisfied", not bool(required_names))
        cache = self.payload.setdefault("cache", {})
        self.payload.setdefault("observations", [])
        self.payload.setdefault("final_reply", "")
        self.record(
            "Effective Runtime Policy",
            policy_source=self.state.policy_trace,
            collaboration_mode=self.state.collaboration_mode,
            limits=self.state.limits.model_dump(),
        )
        try:
            while self.state.status == GoalStatus.RUNNING:
                await self.authorize()
                self.budget.remaining_time()
                phase = self.budget.phase()
                if phase == BudgetPhase.EXHAUSTED:
                    exhausted = next(
                        name
                        for name in ("output_tokens", "llm_calls", "max_steps", "duration")
                        if self.budget.remaining(name) <= 0
                    )
                    self.budget.mark_failure(exhausted)
                    raise RuntimeHalt("budget_exhausted:" + exhausted)
                if self.payload.get("force_finalizing"):
                    phase = BudgetPhase.FINALIZING
                    self.state.budget_phase = phase
                if (
                    self.state.runtime_role == "CHILD"
                    and (self.state.consumed.get("llm_calls", 0) > 0 or required_satisfied)
                    and self.budget.remaining("llm_calls") == 1
                ):
                    phase = BudgetPhase.FINALIZING
                    self.state.budget_phase = phase
                valid_observations = [
                    item
                    for item in self.payload["observations"]
                    if item.get("status") in {"SUCCESS", "EMPTY", "PARTIAL"}
                ]
                if phase == BudgetPhase.FINALIZING:
                    active_bindings = []
                    self.state.partial = (
                        self.state.partial or not required_satisfied or bool(self.payload.get("unresolved_failures"))
                    )
                    self.record("Final synthesis", observations=len(valid_observations))
                elif phase == BudgetPhase.CONSERVE:
                    active_bindings = [
                        item
                        for item in bindings
                        if (item.tool.name in required_names and not required_satisfied)
                        or (
                            item.adapter.descriptor.type == "AGENT"
                            and item.adapter.descriptor.id.removeprefix("agent:") in self.state.explicit_agents
                            and item.adapter.descriptor.id.removeprefix("agent:") not in self.state.used_agents
                        )
                    ]
                    self.record("Conserve budget", available_tools=len(active_bindings))
                else:
                    active_bindings = bindings
                active_tools = [item.tool for item in active_bindings]
                if completion and phase != BudgetPhase.FINALIZING:
                    active_tools.append(completion)
                from cortexa.runtime.completion import collaboration_status
                status_message = collaboration_status(self.state, bindings, self.payload["observations"], active_bindings)
                model_messages = [*messages, status_message] if status_message else messages
                if phase == BudgetPhase.FINALIZING:
                    model_messages = [
                        *model_messages,
                        SystemMessage(
                            content="预算进入收尾阶段。不要调用工具或 Agent；"
                            "仅基于已有结果在本次回复中完成总结，明确说明缺失或未完成的部分。"
                            "不要只承诺稍后读取、查询或汇总。"
                        ),
                    ]
                if completion and phase != BudgetPhase.FINALIZING:
                    model_messages = [*model_messages, SystemMessage(content=
                        "结束任务时必须使用 complete_task 提交结构化完成声明，列出必需条件、实际 observation_ids 和未决项。"
                        "未满足条件时先协作或 ask_user，不得把缺参方案当完成。纯方法或草案可列空数据要求，但不得隐瞒任务实际需要的数据。")]
                context_size = token_upper_bound(serialize_messages(model_messages)) + token_upper_bound(
                    [binding.adapter.descriptor.input_schema for binding in active_bindings]
                )
                context_size += sum(len(t.description.encode()) + len(t.name.encode()) + 64 for t in active_tools)
                if completion and phase != BudgetPhase.FINALIZING:
                    context_size += token_upper_bound(completion.args_schema.model_json_schema())
                if context_size > self.state.limits.context_tokens:
                    self.budget.mark_failure("context_tokens", current=context_size)
                    raise RuntimeHalt("context_budget_exceeded")
                remaining_output = self.state.limits.output_tokens - self.state.consumed.get("output_tokens", 0)
                if remaining_output <= 0:
                    self.budget.mark_failure("output_tokens")
                    raise RuntimeHalt("budget_exhausted:output_tokens")
                await self.begin(Action(kind="REASON"), llm_calls=1)
                self.record("Runtime reasoning", context_upper_bound=context_size)
                selected = model.bind_tools(active_tools) if active_tools else model
                # Provider override supplements local enforcement; provider availability
                # and routing continue using the existing Agent model configuration.
                planning_output = self.budget.remaining("output_tokens", protect_finalization=True)
                requested_max_tokens = min(
                        remaining_output if phase == BudgetPhase.FINALIZING else 4096,
                        remaining_output,
                        remaining_output if phase == BudgetPhase.FINALIZING else max(256, planning_output),
                    )
                selected = selected.bind(max_tokens=requested_max_tokens)
                from cortexa.runtime.prompt_requests import model_request
                self.publish("runtime_prompt", prompt_kind="model", request=model_request(
                    model_messages, active_tools, {"max_tokens": requested_max_tokens}
                ))
                await self.save()
                response = None
                chunk_cost = 0
                previous_output = self.state.consumed.get("output_tokens", 0)
                round_text = ""
                planning_cutoff = False
                with usage_scope(
                    "runtime_reasoning",
                    goal_id=self.payload["goal_id"],
                    action_id=self.state.current_action.id,
                    purpose="RUNTIME_REASONING",
                ):
                    async with asyncio.timeout(self.budget.remaining_time()):
                        stream = selected.astream(model_messages)
                        async for chunk in stream:
                            response = chunk if response is None else response + chunk
                            text = chunk.content
                            if isinstance(text, list):
                                text = "".join(
                                    x if isinstance(x, str) else x.get("text", "")
                                    for x in text
                                    if isinstance(x, str) or (isinstance(x, dict) and x.get("type") in {None, "text", "output_text"})
                                )
                            # Count the new stream fragments, not a JSON wrapper for every
                            # fragment (which amplified long tool calls dramatically).
                            chunk_cost += len((text or "").encode()) + sum(
                                len(str(part.get("args") or "").encode())
                                for part in (getattr(chunk, "tool_call_chunks", []) or [])
                                if isinstance(part, dict)
                            )
                            self.state.consumed["output_tokens"] = previous_output + chunk_cost
                            if chunk_cost > remaining_output:
                                self.budget.mark_failure("output_tokens", current=previous_output + chunk_cost)
                                raise RuntimeHalt("budget_exhausted:output_tokens")
                            if phase != BudgetPhase.FINALIZING and chunk_cost >= planning_output:
                                self.payload["force_finalizing"] = True
                                self.state.partial = True
                                self.record("Planning stopped for finalization", output_bytes=chunk_cost)
                                planning_cutoff = True
                                break
                            if text:
                                # A model may emit prose before tool calls. Keep it
                                # provisional until the complete response is known.
                                round_text += text
                                if (
                                    not getattr(chunk, "tool_call_chunks", [])
                                    and not raw_tool_call_syntax(round_text)
                                    and not any(tag in round_text.lower() for tag in ("<think", "<analysis", "<reasoning"))
                                ):
                                    self.publish("runtime_draft", content=text)
                        if planning_cutoff and hasattr(stream, "aclose"):
                            await stream.aclose()
                if planning_cutoff:
                    self.state.current_action.phase = "completed"
                    await self.save()
                    continue
                if response is None:
                    raise RuntimeHalt("model_empty", status=GoalStatus.FAILED)
                response = message_chunk_to_message(response)
                self.usage.add(response)
                call_usage = UsageTotals()
                call_usage.add(response)
                self.publish("runtime_usage", stats=call_usage.stats())
                reported = (getattr(response, "usage_metadata", None) or {}).get("output_tokens")
                complete_call_bytes = (
                    len(json.dumps(response.tool_calls, ensure_ascii=False).encode()) if response.tool_calls else 0
                )
                complete_bytes = len(round_text.encode()) + complete_call_bytes
                self.state.consumed["output_tokens"] = previous_output + max(chunk_cost, complete_bytes, reported or 0)
                if self.state.consumed["output_tokens"] > self.state.limits.output_tokens:
                    self.budget.mark_failure("output_tokens", current=self.state.consumed["output_tokens"])
                    raise RuntimeHalt("budget_exhausted:output_tokens")
                self.state.current_action.phase = "completed"
                calls = response.tool_calls
                empty_calls = sum(empty_tool_call_placeholder(call) for call in calls)
                if empty_calls and empty_calls < len(calls) and not response.invalid_tool_calls:
                    remaining_calls = [call for call in calls if not empty_tool_call_placeholder(call)]
                    if valid_tool_call_batch(remaining_calls):
                        self.record("Ignored empty provider tool-call placeholders", count=empty_calls)
                        response = response.model_copy(update={"tool_calls": remaining_calls})
                        calls = remaining_calls
                if response.invalid_tool_calls or not valid_tool_call_batch(calls):
                    self.record(
                        "Invalid tool call batch",
                        count=len(calls),
                        empty_placeholders=empty_calls,
                        invalid_calls=len(response.invalid_tool_calls),
                    )
                    if (
                        self.budget.remaining("max_replans") > 0
                        and self.budget.can_expand(llm_calls=1, max_steps=1)
                    ):
                        self.budget.reserve(max_replans=1)
                        messages.append(SystemMessage(
                            content="上一轮工具调用格式不完整，未执行其中任何调用。"
                            "请重新决定操作；每个工具调用都必须有非空名称、唯一非空 ID 和对象参数。"
                        ))
                        self.payload["messages"] = serialize_messages(messages)
                        await self.save()
                        continue
                    if valid_observations:
                        # Retry responsibility sits with the model, not the user:
                        # synthesize from the collected evidence instead of
                        # parking the Goal on an instruction the user cannot act on.
                        self.state.partial = True
                        self.payload["force_finalizing"] = True
                        self.record("Invalid tool call batch stopped for finalization", count=len(calls))
                        self.payload["messages"] = serialize_messages(messages)
                        await self.save()
                        continue
                    self.payload["waiting_message"] = (
                        "模型多次返回不完整的工具调用，本轮仍未执行。请重试；"
                        "若反复出现，请更换模型或简化目标后重新发起。"
                    )
                    raise RuntimeHalt("invalid_reasoning_action", status=GoalStatus.WAITING, next_action="ASK_USER")
                review_gap = None
                if completion and len(calls) == 1 and calls[0]["name"] == "complete_task":
                    try:
                        review = CompletionReview.model_validate(calls[0]["args"])
                        review_gap = validate_completion(review, self.state, self.payload)
                        if required_names and not partial_requested(self.payload) and not any(r.kind in {'data','lookup'} for r in review.requirements):
                            review_gap = review_gap or '本轮必需业务查询未列入完成依据。'
                        self.record("Structured completion review", requirements=[r.model_dump() for r in review.requirements],
                                    unresolved=review.unresolved, valid=not bool(review_gap))
                        response = response.model_copy(update={"content": review.answer, "tool_calls": []})
                        round_text, calls = review.answer, []
                    except ValidationError:
                        review_gap = "完成声明格式无效，需提供任务条件与真实来源。"
                        response = response.model_copy(update={"tool_calls": []})
                        calls = []
                elif completion and not calls and phase != BudgetPhase.FINALIZING and not partial_requested(self.payload):
                    review_gap = "尚未提交本轮任务的结构化完成依据，不能直接标记完成。"
                messages.append(response)
                if not calls:
                    from cortexa.runtime.completion import completion_gap
                    gap = review_gap or completion_gap(round_text, self.state, bindings, self.payload)
                    if gap and phase == BudgetPhase.FINALIZING:
                        self.state.partial = True
                    if gap and "ask_user" in by_name and (
                        phase != BudgetPhase.FINALIZING or review_gap or gap.startswith("回复声称协作被拒绝")
                    ):
                        messages.pop()  # An unaccepted draft is not an execution fact.
                        self.record("Completion needs data or user decision", reason=gap)
                        if phase != BudgetPhase.FINALIZING and not self.payload.get("completion_gap_checked") and self.budget.can_expand(max_replans=1, llm_calls=1, max_steps=1):
                            self.payload["completion_gap_checked"] = True
                            self.budget.reserve(max_replans=1)
                            messages.append(SystemMessage(content="上一轮草案尚未交付：" + gap +
                                "请依据本轮真实协作状态，拆解缺失数据需求后调用合适 Agent；"
                                "若需要用户确认方向或是否接受不完整草案，调用 ask_user；条件满足则用 complete_task 提交完成声明。不要再次直接输出缺失说明结束任务。"))
                            self.payload["messages"] = serialize_messages(messages)
                            await self.save()
                            continue
                        result = await by_name["ask_user"].invoke({
                            "question": "当前方案仍有未解决的数据或协作问题：" + gap[:400] + "。你希望如何继续？",
                            "options": ["继续获取所需数据后完成任务", "接受标明数据缺失的草案"],
                            "allow_free_text": True,
                        }, self.state.current_action.id)
                        self.payload["pending_question"] = result.observation.metadata["user_question"]
                        self.payload["waiting_message"] = self.payload["pending_question"]["question"]
                        self.payload["messages"] = serialize_messages(messages)
                        self.budget.halt("user_decision_required", status=GoalStatus.WAITING, next_action="ASK_USER")
                        await self.save()
                        self.publish("user_question", question=self.payload["pending_question"])
                        raise RuntimeHalt("user_decision_required", status=GoalStatus.WAITING, next_action="ASK_USER")
                    if not required_satisfied and phase != BudgetPhase.FINALIZING:
                        if self.budget.can_expand(max_replans=1, llm_calls=1, max_steps=1):
                            self.budget.reserve(max_replans=1)
                            messages.append(SystemMessage(content=
                                "尚未取得本轮必需的业务查询结果，上一条回答未交付。请先调用已授权的业务查询工具，"
                                "不要把任务输入中的数字当作已核实的查询结果。可用查询工具：" + json.dumps(list(required_names), ensure_ascii=False)
                            ))
                            self.payload["messages"] = serialize_messages(messages)
                            self.record("Required business query requested")
                            await self.save()
                            continue
                        raise RuntimeHalt("required_capability_not_used")
                    if raw_tool_call_syntax(round_text):
                        # Tool-call markup as text must never become the final
                        # answer: nudge the model once, then fall back to the
                        # prose around the markup or to collected results.
                        cleaned = strip_raw_tool_calls(round_text).strip()
                        if (
                            phase != BudgetPhase.FINALIZING
                            and self.budget.remaining("max_replans") > 0
                            and self.budget.can_expand(llm_calls=1, max_steps=1)
                        ):
                            self.budget.reserve(max_replans=1)
                            self.record("Raw tool-call syntax rejected in final answer")
                            messages.append(SystemMessage(
                                content="上一轮回复混入了未执行的工具调用语法（例如 <tool_call>）。"
                                "工具只能通过原生工具调用执行；请直接用自然语言给出本轮结论，不要再输出任何工具调用语法。"
                            ))
                            self.payload["messages"] = serialize_messages(messages)
                            await self.save()
                            continue
                        if not cleaned and valid_observations:
                            self.state.partial = True
                            cleaned = "已取得部分结果，尚未完成最终分析：" + "；".join(
                                item.get("summary", "已取得结果") for item in valid_observations[:5]
                            )
                        if not cleaned:
                            raise RuntimeHalt("model_empty", status=GoalStatus.FAILED)
                        self.record("Raw tool-call syntax stripped from final answer")
                        round_text = cleaned
                    if not round_text.strip() and phase != BudgetPhase.FINALIZING and (
                        (response.response_metadata or {}).get("finish_reason") in {"length", "max_tokens"}
                    ):
                        self.state.partial = True
                        self.payload["force_finalizing"] = True
                        self.record("Empty planning response stopped for finalization")
                        self.payload["messages"] = serialize_messages(messages)
                        await self.save()
                        continue
                    if not round_text.strip():
                        if self.state.limits.output_tokens <= 1000:
                            self.state.partial = True
                            raise RuntimeHalt("model_empty", status=GoalStatus.BLOCKED)
                        raise RuntimeHalt("model_empty", status=GoalStatus.FAILED)
                    if (response.response_metadata or {}).get("finish_reason") in {"length", "max_tokens"}:
                        if phase != BudgetPhase.FINALIZING and self.budget.remaining("llm_calls") > 0:
                            self.payload["force_finalizing"] = True
                            messages.append(SystemMessage(content="上一轮输出达到单次额度而中断，尚未交付。请利用剩余输出额度重新给出完整、精简的最终回复。"))
                            self.payload["messages"] = serialize_messages(messages)
                            self.record("Interrupted planning answer queued for final synthesis")
                            await self.save()
                            continue
                        raise RuntimeHalt("model_output_incomplete")
                    # A failed capability must not silently turn into a successful Goal.
                    if self.payload.get("unresolved_failures") and phase != BudgetPhase.FINALIZING:
                        if not valid_observations:
                            raise RuntimeHalt("unresolved_capability_failure")
                        # Collected results stay usable: wrap up and declare the
                        # failure (same semantics as a depleted web budget) instead
                        # of discarding every successful source.
                        self.state.partial = True
                        self.payload["force_finalizing"] = True
                        self.record(
                            "Capability failure downgraded to declared wrap-up",
                            failures=self.payload["unresolved_failures"],
                        )
                        self.payload["messages"] = serialize_messages(messages)
                        await self.save()
                        continue
                    if phase == BudgetPhase.FINALIZING and (
                        not required_satisfied or self.payload.get("unresolved_failures")
                    ):
                        if not valid_observations:
                            raise RuntimeHalt("required_capability_not_used")
                        self.state.partial = True
                    self.state.status, self.state.next_action = GoalStatus.COMPLETE, "NONE"
                    self.state.reason = None
                    self.reply += round_text
                    yield {"type": "token", "content": round_text}
                else:
                    self.budget.reserve(tool_iterations=1)
                    halt = None
                    for call in calls:
                        # Complete protocol pairs even if execution stops mid-batch.
                        if halt:
                            messages.append(ToolMessage(content="本次行动未执行：Goal 已停止", tool_call_id=call["id"]))
                            continue
                        result_text = "本次行动未执行"
                        try:
                            binding = by_name.get(call["name"])
                            if binding is None:
                                if self.budget.remaining("max_replans") > 0 and phase != BudgetPhase.FINALIZING:
                                    self.budget.reserve(max_replans=1)
                                    self.state.next_action = "REPLAN"
                                    result_text = "该工具名称不可用，本次未执行。请使用当前已授权工具的准确名称：" + json.dumps(
                                        [item.tool.name for item in active_bindings], ensure_ascii=False
                                    )
                                    self.record("Unknown tool rejected for bounded correction", authorized_tools=len(active_bindings))
                                    continue
                                raise RuntimeHalt("capability_not_authorized", next_action="FAIL")
                            if call["name"] not in {
                                item.tool.name for item in active_bindings
                            } or not self.budget.can_expand(max_steps=1, duration=1):
                                self.state.partial = True
                                result_text = (
                                    "预算已进入收尾阶段，本次调用未执行。请使用已有结果收尾，并说明未完成部分。"
                                )
                                continue
                            cap = binding.adapter.descriptor
                            if cap.requires_confirmation or cap.risk_level != "low":
                                raise RuntimeHalt(
                                    "capability_approval_required",
                                    status=GoalStatus.WAITING,
                                    next_action="REQUEST_APPROVAL",
                                )
                            if binding.authorize:
                                await binding.authorize()
                            # Only adapters loaded through permission and policy checks
                            # are executable; a model cannot invent capability access.
                            if (
                                cap.type not in {"DATA", "WEB", "KNOWLEDGE", "MEMORY", "AGENT", "TOOL"}
                                or cap.availability != "available"
                            ):
                                raise RuntimeHalt("capability_unavailable")
                            validated = None
                            validation_error = None
                            try:
                                validated = binding.tool.args_schema.model_validate(call["args"])
                            except ValidationError as error:
                                validation_error = error
                                repair = (None if cap.type == "AGENT" else
                                          repair_tool_args(binding.tool.args_schema, call["args"], error))
                                if repair is not None:
                                    repaired, repaired_fields = repair
                                    try:
                                        validated = binding.tool.args_schema.model_validate(repaired)
                                    except ValidationError:
                                        validated = None
                                    if validated is not None:
                                        # Deterministic local correction; the defaults
                                        # answer for the fields the model got wrong.
                                        self.record(
                                            "Invalid tool arguments fell back to schema defaults",
                                            fields=repaired_fields,
                                        )
                            if validated is None:
                                fields = sorted({str(e["loc"][0]) for e in validation_error.errors() if e["loc"]})
                                if cap.type == "AGENT":
                                    result_text = (
                                        "协作参数不符合调用契约，本次未派发，任务内容未被删除。请按以下协作调用 Schema 重新提交；"
                                        "具体子任务写入 task，外部请求字段由平台构造："
                                        + json.dumps(binding.tool.args_schema.model_json_schema(), ensure_ascii=False)
                                    )
                                    if self.budget.remaining("max_replans") > 0 and phase != BudgetPhase.FINALIZING:
                                        self.budget.reserve(max_replans=1)
                                        self.state.next_action = "REPLAN"
                                        self.record("Invalid collaboration arguments rejected for bounded correction", fields=fields)
                                        continue
                                    raise RuntimeHalt("invalid_collaboration_arguments", status=GoalStatus.BLOCKED, next_action="FAIL") from validation_error
                                result_text = "请补充或修正工具参数：" + "、".join(fields)
                                self.payload["waiting_message"] = result_text
                                await self.begin(Action(kind="CAPABILITY", capability_id=cap.id))
                                observation = Observation(
                                    cap.type,
                                    cap.id,
                                    self.state.current_action.id,
                                    "NOT_READY",
                                    summary="工具参数未通过校验",
                                    metadata={"missing_inputs": fields},
                                )
                                self.payload["observations"].append(
                                    observation_record(
                                        InvocationResult(observation, result_text, {"validation": "failed"})
                                    )
                                )
                                self.state.current_action.phase = "completed"
                                self.state.current_action.observation_status = "NOT_READY"
                                self.state.observation_counts["NOT_READY"] = (
                                    self.state.observation_counts.get("NOT_READY", 0) + 1
                                )
                                raise RuntimeHalt(
                                    "missing_inputs", status=GoalStatus.WAITING, next_action="ASK_USER"
                                ) from validation_error
                            args = validated.model_dump(exclude_unset=True)
                            fingerprint = hashlib.sha256(
                                json.dumps(
                                    [cap.id, args, binding.cache_scope],
                                    sort_keys=True,
                                    ensure_ascii=False,
                                    default=str,
                                ).encode()
                            ).hexdigest()
                            reused = fingerprint in cache
                            costs = (
                                {}
                                if reused
                                else {"agent_calls": 1}
                                if cap.type == "AGENT"
                                else {"tool_calls": 1, **({"web_calls": 1} if cap.type == "WEB" else {})}
                            )
                            if any(self.budget.remaining(key, protect_finalization=True) < value for key, value in costs.items()):
                                self.state.partial = True
                                self.payload["force_finalizing"] = True
                                result_text = "本次调用未执行：剩余调用预算不足，请使用已有结果完成回复并说明缺失信息。"
                                continue
                            await self.begin(
                                Action(kind="CAPABILITY", capability_id=cap.id, fingerprint=fingerprint), **costs
                            )
                            self.publish("runtime_progress", message={"DATA": "查询业务数据", "KNOWLEDGE": "检索知识库", "MEMORY": "检索相关记忆", "WEB": "搜索公开信息", "AGENT": "邀请协作 Agent"}.get(cap.type, "执行任务") + " · " + cap.name, status="running")
                            if reused:
                                record = cache[fingerprint]
                                result_text, status = record["text"], record["status"]
                            else:
                                try:
                                    async with asyncio.timeout(
                                        min(
                                            cap.timeout or 30,
                                            self.budget.remaining_time(),
                                            self.budget.remaining("duration", protect_finalization=True),
                                        )
                                    ):
                                        result = await binding.invoke(args, self.state.current_action.id)
                                except asyncio.CancelledError:
                                    raise
                                except RuntimeHalt:
                                    self.state.current_action.phase = "completed"
                                    raise
                                except TimeoutError:
                                    # External completion is unknown; never retry automatically.
                                    self.state.current_action.phase = "unknown"
                                    raise RuntimeHalt(
                                        "action_result_unknown", status=GoalStatus.WAITING, next_action="ASK_USER"
                                    ) from None
                                except Exception:
                                    logging.getLogger(__name__).exception("Capability invocation failed: %s", cap.id)
                                    self.state.current_action.phase = "unknown"
                                    if unstarted_agent_action(self.state, self.payload):
                                        reset_unstarted_agent(self.state)
                                        raise RuntimeHalt(
                                            "agent_initialization_failed", status=GoalStatus.WAITING, next_action="ASK_USER"
                                        ) from None
                                    raise RuntimeHalt(
                                        "action_result_unknown", status=GoalStatus.WAITING, next_action="ASK_USER"
                                    ) from None
                                if result.observation.metadata.get('user_question'):
                                    self.payload['pending_question'] = result.observation.metadata['user_question']
                                    if cap.type == 'AGENT':
                                        self.payload['decision_continuation'] = {'capability_id':cap.id,
                                            'args':args, 'action_id':self.state.current_action.id}
                                    self.payload['waiting_message'] = self.payload['pending_question']['question']
                                    self.state.current_action.phase = 'completed'
                                    self.state.current_action.observation_status = 'NOT_READY'
                                    result_text = self.payload['waiting_message']
                                    self.publish('user_question', question=self.payload['pending_question'])
                                    raise RuntimeHalt('user_decision_required', status=GoalStatus.WAITING, next_action='ASK_USER')
                                record = observation_record(result)
                                source_keys = {"type", "name", "title", "document_id", "kb_id", "knowledge_base_id", "url", "page", "evidence_grade", "purpose", "memory_id"}
                                source_refs = [{k: v for k, v in item.items() if k in source_keys and isinstance(v, (str, int))}
                                               for item in (result.observation.evidence or [])[:30] if isinstance(item, dict)]
                                self.publish("runtime_progress", message=result.observation.summary or "已取得执行结果", status="completed", sources=source_refs, data_result=cap.type == "DATA")
                                self.payload["observations"].append(record)
                                remaining_context = self.state.limits.context_tokens - (
                                    token_upper_bound(serialize_messages(messages))
                                    + token_upper_bound([item.adapter.descriptor.input_schema for item in bindings])
                                    + sum(len(t.description.encode()) + len(t.name.encode()) + 64 for t in tools)
                                )
                                projection_budget = max(256, min(6000, remaining_context - 1024))
                                if cap.type == "AGENT":
                                    # A finished report must reach the synthesizing model.
                                    # Reserve half the available context for further reasoning.
                                    projection_budget = max(256, (remaining_context - 1024) // 2)
                                result_text = model_result_text(result, max_bytes=projection_budget)
                                status = result.observation.status
                                if self.payload.get("collaboration_runtime"):
                                    result_text = json.dumps(
                                        {
                                            "observation_id": self.state.current_action.id,
                                            "status": status,
                                            "result": result_text,
                                        },
                                        ensure_ascii=False,
                                    )
                                if cap.type == "KNOWLEDGE" and result.observation.metadata.get("retrieval_trace"):
                                    self.record("Knowledge retrieval relevance", **{
                                        **result.observation.metadata["retrieval_trace"],
                                        "injected_context": result_text,
                                    })
                                    self.publish("runtime_retrieval", entry=self.trace[-1])
                                cache[fingerprint] = {
                                    "text": result_text,
                                    "status": status,
                                    "repairable": result.observation.metadata.get(
                                        "repairable_from_observations", False
                                    ),
                                }
                            self.state.current_action.phase = "completed"
                            self.state.current_action.observation_status = status
                            self.record("Observation", observation_status=status, reused_cache=reused)
                            if call["name"] in required_names and status in {"SUCCESS", "EMPTY", "PARTIAL"}:
                                required_satisfied = True
                            failures = set(self.payload.get("unresolved_failures", []))
                            if status in {"FAILED", "TIMEOUT", "UNKNOWN"}:
                                failures.add(cap.id)
                            elif status in {"SUCCESS", "EMPTY", "PARTIAL"}:
                                failures.discard(cap.id)
                            self.payload["unresolved_failures"] = sorted(failures)
                            # NOT_READY -> ASK_USER, failures -> bounded replan; no
                            # repeated blind invocation of the same failed arguments.
                            if status == "NOT_READY":
                                self.payload["waiting_message"] = result_text
                            if (
                                status == "NOT_READY"
                                and cache[fingerprint].get("repairable")
                                and self.state.consumed.get("max_replans", 0) < self.state.limits.max_replans
                                and self.budget.phase() == BudgetPhase.NORMAL
                            ):
                                self.budget.reserve(max_replans=1)
                                self.state.observation_counts[status] = self.state.observation_counts.get(status, 0) + 1
                                self.state.next_action = "REPLAN"
                            else:
                                self.budget.observe(status)
                        except RuntimeHalt as error:
                            halt = error
                        finally:
                            messages.append(ToolMessage(content=result_text, tool_call_id=call["id"]))
                            self.payload["messages"] = serialize_messages(messages)
                            self.payload["required_satisfied"] = required_satisfied
                            if halt:
                                self.budget.halt(halt.reason, status=halt.status, next_action=halt.next_action)
                            await self.save()
                    if halt:
                        if halt.reason == 'user_decision_required':
                            finished = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
                            messages.extend(ToolMessage(content='未执行：等待用户回答。', tool_call_id=c['id'])
                                            for c in response.tool_calls if c['id'] not in finished)
                        self.payload["messages"] = serialize_messages(messages)
                        raise halt
                self.payload["messages"] = serialize_messages(messages)
                self.payload["final_reply"] = self.reply
                self.record("Goal state updated")
                await self.save()
                yield {"type": "goal_status", "status": self.state.status, "reason": self.state.reason}
        except asyncio.CancelledError:
            # Preserve an interrupted draft for recovery, without presenting it
            # as a completed answer during normal tool execution.
            self.reply += round_text
            raise
        except TimeoutError:
            self.budget.sync()
            self.budget.mark_failure("duration", current=int(self.state.elapsed_seconds))
            self.budget.halt("budget_exhausted:duration")
        except RuntimeHalt as error:
            self.budget.halt(error.reason, status=error.status, next_action=error.next_action)
        finally:
            self.budget.sync()
