"""Bounded Goal Loop: one model response evaluates evidence and chooses the next action.

Native tool_calls are the structured reasoning decision. Text without tool calls is
final synthesis. No mandatory Planner/Evaluator/enrichment model calls are added.
"""

import asyncio
import hashlib
import json
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

from cortexa.agents.usage import UsageTotals
from cortexa.runtime.adapters import CapabilityAdapter
from cortexa.runtime.observations import Observation
from cortexa.runtime.projection import model_result_text
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


class GoalLoop:
    def __init__(self, state, payload, checkpoint, authorize):
        self.state, self.payload = state, payload
        self.budget = RuntimeBudget(state)
        self.checkpoint, self.authorize = checkpoint, authorize
        self.usage = UsageTotals()
        self.reply = ""
        self.trace = []

    def record(self, event, **details):
        # Only controlled enum/count/hash metadata, never prompt, fields or raw exceptions.
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

    async def run(self, model, bindings, *, required_names=()):
        messages = messages_from_dict(self.payload["messages"])
        by_name = {binding.tool.name: binding for binding in bindings}
        tools = [binding.tool for binding in bindings]
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
                model_messages = messages
                if phase == BudgetPhase.FINALIZING:
                    model_messages = [
                        *messages,
                        SystemMessage(
                            content="预算进入收尾阶段。不要调用工具或 Agent；"
                            "仅基于已有结果给出结论，明确说明缺失或未完成的部分。"
                        ),
                    ]
                context_size = token_upper_bound(serialize_messages(model_messages)) + token_upper_bound(
                    [binding.adapter.descriptor.input_schema for binding in active_bindings]
                )
                context_size += sum(len(t.description.encode()) + len(t.name.encode()) + 64 for t in active_tools)
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
                selected = selected.bind(
                    max_tokens=min(
                        4096,
                        remaining_output,
                        remaining_output if phase == BudgetPhase.FINALIZING else max(256, planning_output),
                    )
                )
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
                                    if isinstance(x, (str, dict))
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
                    self.payload["waiting_message"] = "模型返回了不完整的工具调用；本轮未执行该批操作。请继续重试。"
                    raise RuntimeHalt("invalid_reasoning_action", status=GoalStatus.WAITING, next_action="ASK_USER")
                messages.append(response)
                if not calls:
                    if not required_satisfied and phase != BudgetPhase.FINALIZING:
                        raise RuntimeHalt("required_capability_not_used")
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
                        raise RuntimeHalt("model_output_incomplete")
                    # A failed capability must not silently turn into a successful Goal.
                    if self.payload.get("unresolved_failures") and phase != BudgetPhase.FINALIZING:
                        raise RuntimeHalt("unresolved_capability_failure")
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
                                cap.type not in {"DATA", "WEB", "KNOWLEDGE", "MEMORY", "AGENT"}
                                or cap.availability != "available"
                            ):
                                raise RuntimeHalt("capability_unavailable")
                            try:
                                validated = binding.tool.args_schema.model_validate(call["args"])
                            except ValidationError as error:
                                fields = sorted({str(e["loc"][0]) for e in error.errors() if e["loc"]})
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
                                ) from error
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
                            await self.begin(
                                Action(kind="CAPABILITY", capability_id=cap.id, fingerprint=fingerprint), **costs
                            )
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
                                    self.state.current_action.phase = "unknown"
                                    raise RuntimeHalt(
                                        "action_result_unknown", status=GoalStatus.WAITING, next_action="ASK_USER"
                                    ) from None
                                record = observation_record(result)
                                self.payload["observations"].append(record)
                                remaining_context = self.state.limits.context_tokens - (
                                    token_upper_bound(serialize_messages(messages))
                                    + token_upper_bound([item.adapter.descriptor.input_schema for item in bindings])
                                    + sum(len(t.description.encode()) + len(t.name.encode()) + 64 for t in tools)
                                )
                                result_text = model_result_text(
                                    result, max_bytes=max(256, min(6000, remaining_context - 1024))
                                )
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
