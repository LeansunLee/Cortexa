"""Deterministic state transitions and hierarchical hard budgets."""

import time
import uuid
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GoalStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    FAILED = "FAILED"


class BudgetPhase(StrEnum):
    NORMAL = "NORMAL"
    CONSERVE = "CONSERVE"
    FINALIZING = "FINALIZING"
    EXHAUSTED = "EXHAUSTED"


UNLIMITED_BUDGET = 1_000_000_000_000_000
BUDGET_BOUNDED_MAX = {
    "duration": 600, "llm_calls": 12, "tool_calls": 20, "tool_iterations": 5,
    "web_calls": 3, "agent_calls": 5, "max_collaborators": 5, "agent_depth": 2,
    "context_tokens": 128000, "output_tokens": 32768, "max_steps": 64,
    "max_replans": 3, "max_failures": 5,
}


class BudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    duration: int = Field(default=180, ge=1, le=UNLIMITED_BUDGET)
    llm_calls: int = Field(default=6, ge=0, le=UNLIMITED_BUDGET)
    tool_calls: int = Field(default=10, ge=0, le=UNLIMITED_BUDGET)
    tool_iterations: int = Field(default=5, ge=0, le=UNLIMITED_BUDGET)
    web_calls: int = Field(default=3, ge=0, le=UNLIMITED_BUDGET)
    agent_calls: int = Field(default=3, ge=0, le=UNLIMITED_BUDGET)
    max_collaborators: int = Field(default=3, ge=0, le=UNLIMITED_BUDGET)
    agent_depth: int = Field(default=1, ge=0, le=UNLIMITED_BUDGET)
    context_tokens: int = Field(default=32000, ge=256, le=UNLIMITED_BUDGET)
    output_tokens: int = Field(default=16384, ge=0, le=UNLIMITED_BUDGET)
    max_steps: int = Field(default=24, ge=1, le=UNLIMITED_BUDGET)
    max_replans: int = Field(default=1, ge=0, le=UNLIMITED_BUDGET)
    max_failures: int = Field(default=2, ge=1, le=UNLIMITED_BUDGET)

    @model_validator(mode="before")
    @classmethod
    def normalize_unlimited(cls, value):
        if isinstance(value, dict):
            return {key: UNLIMITED_BUDGET if item is None else item for key, item in value.items()}
        return value


def effective_limits(*layers: dict | None) -> BudgetLimits:
    """Each layer may only tighten defaults and all earlier layers; reject invalid keys/types."""
    result = BudgetLimits().model_dump()
    for layer in layers:
        if layer is None:
            continue
        validated = BudgetLimits.model_validate(layer)
        for key in validated.model_fields_set:
            if getattr(validated, key) > BUDGET_BOUNDED_MAX[key]:
                raise ValueError(f"{key} exceeds the platform limit")
            result[key] = min(result[key], getattr(validated, key))
    return BudgetLimits(**result)


def platform_hard_limits(platform_budget: dict | None = None) -> dict[str, int]:
    """Field upper bounds are platform ceilings; optional config may tighten them."""
    ceilings = dict(BUDGET_BOUNDED_MAX)
    if platform_budget is not None:
        configured = BudgetLimits.model_validate(platform_budget)
        for name in configured.model_fields_set:
            if getattr(configured, name) > BUDGET_BOUNDED_MAX[name]:
                raise ValueError(f"{name} exceeds the platform limit")
            ceilings[name] = min(ceilings[name], getattr(configured, name))
    return ceilings


def tighten_limits(base: BudgetLimits, *layers: dict | None) -> BudgetLimits:
    """Tighten an already resolved allocation without reapplying platform defaults."""
    values = base.model_dump()
    for raw in layers:
        if raw is None:
            continue
        policy = BudgetLimits.model_validate(raw)
        for name in policy.model_fields_set:
            values[name] = min(values[name], getattr(policy, name))
    return BudgetLimits(**values)


class Action(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: Literal["REASON", "CAPABILITY"]
    capability_id: str | None = None
    fingerprint: str | None = None
    phase: Literal["started", "completed", "unknown"] = "started"
    observation_status: str | None = None


class GoalState(BaseModel):
    version: str = "goal-runtime-v1"
    status: GoalStatus = GoalStatus.RUNNING
    reason: str | None = None
    next_action: Literal["CONTINUE", "ASK_USER", "REQUEST_APPROVAL", "ASK_HUMAN", "RETRY", "REPLAN", "FAIL", "NONE"] = (
        "CONTINUE"
    )
    limits: BudgetLimits = Field(default_factory=BudgetLimits)
    consumed: dict[str, int] = Field(default_factory=dict)
    budget_phase: BudgetPhase = BudgetPhase.NORMAL
    finalization_reserve: dict[str, int] = Field(default_factory=dict)
    child_allocations: list[dict] = Field(default_factory=list)
    policy_trace: dict = Field(default_factory=dict)
    collaboration_mode: str = "EXPLICIT_ONLY"
    runtime_role: str = "PARENT"
    runtime_agent_id: str | None = None
    partial: bool = False
    budget_failure: dict | None = None
    elapsed_seconds: float = 0
    current_action: Action | None = None
    observation_counts: dict[str, int] = Field(default_factory=dict)
    explicit_agents: list[str] = Field(default_factory=list)
    approved_agents: list[str] = Field(default_factory=list)
    denied_agents: list[str] = Field(default_factory=list)
    used_agents: list[str] = Field(default_factory=list)
    candidate_agents: list[str] = Field(default_factory=list)
    pending_agents: list[str] = Field(default_factory=list)
    active_agent_path: list[str] = Field(default_factory=list)
    active_agent_action: dict | None = None
    last_authorization: str | None = None
    request_hash: str = ""
    latest_message_id: str = ""
    result_message_id: str | None = None


class RuntimeHalt(Exception):
    def __init__(self, reason, *, status=GoalStatus.BLOCKED, next_action="FAIL"):
        super().__init__(reason)
        self.reason, self.status, self.next_action = reason, status, next_action


class RuntimeBudget:
    def __init__(self, state: GoalState, *, clock=time.monotonic):
        self.state = state
        self.clock = clock
        self.started = clock()
        self.previous = state.elapsed_seconds
        if not state.finalization_reserve:
            limits = state.limits
            state.finalization_reserve = {
                "output_tokens": min(4096, limits.output_tokens // 4),
                # A two-call child needs one call to request its required tool and
                # one to synthesize. Its parent already protects finalization.
                "llm_calls": (
                    0 if state.runtime_role == "CHILD" and limits.llm_calls <= 2
                    else 1 if limits.llm_calls > 1 else 0
                ),
                "max_steps": 1 if limits.max_steps > 1 else 0,
                "duration": 0 if state.runtime_role == "CHILD" else min(30, limits.duration // 6),
            }

    def remaining(self, name: str, *, protect_finalization: bool = False) -> int:
        if name == "duration":
            available = max(0, int(self.state.limits.duration - self.state.elapsed_seconds))
        else:
            available = max(0, getattr(self.state.limits, name) - self.state.consumed.get(name, 0))
        if protect_finalization:
            available = max(0, available - self.state.finalization_reserve.get(name, 0))
        return available

    def phase(self) -> BudgetPhase:
        self.sync()
        watched = ("duration", "llm_calls", "output_tokens", "max_steps")
        if any(self.remaining(name) <= 0 for name in watched):
            phase = BudgetPhase.EXHAUSTED
        elif any(self.remaining(name, protect_finalization=True) <= 0 for name in watched):
            phase = BudgetPhase.FINALIZING
        elif any(
            self.remaining(name, protect_finalization=True) <= max(1, getattr(self.state.limits, name) // 4)
            for name in watched
        ):
            phase = BudgetPhase.CONSERVE
        else:
            phase = BudgetPhase.NORMAL
        self.state.budget_phase = phase
        return phase

    def can_expand(self, **costs: int) -> bool:
        if self.phase() in {BudgetPhase.FINALIZING, BudgetPhase.EXHAUSTED}:
            return False
        return all(self.remaining(name, protect_finalization=True) >= amount for name, amount in costs.items())

    def mark_failure(self, name: str, *, current: int | None = None, requested: int = 0):
        self.state.budget_failure = {
            "resource": name,
            "current": self.state.consumed.get(name, 0) if current is None else current,
            "requested": requested,
            "limit": getattr(self.state.limits, name),
            "runtime": self.state.runtime_role,
            "agent_id": self.state.runtime_agent_id,
            "phase": self.phase(),
        }

    def sync(self):
        self.state.elapsed_seconds = self.previous + max(0, self.clock() - self.started)

    def remaining_time(self):
        self.sync()
        remaining = self.state.limits.duration - self.state.elapsed_seconds
        if remaining <= 0:
            self.mark_failure("duration", current=int(self.state.elapsed_seconds))
            raise RuntimeHalt("budget_exhausted:duration")
        return remaining

    def reserve(self, **costs):
        self.remaining_time()
        for name, amount in costs.items():
            if amount < 0 or name not in BudgetLimits.model_fields:
                raise ValueError("Invalid budget cost")
            if self.state.consumed.get(name, 0) + amount > getattr(self.state.limits, name):
                self.mark_failure(name, requested=amount)
                raise RuntimeHalt("budget_exhausted:" + name)
        for name, amount in costs.items():
            self.state.consumed[name] = self.state.consumed.get(name, 0) + amount

    def observe(self, status):
        self.state.observation_counts[status] = self.state.observation_counts.get(status, 0) + 1
        if status == "NOT_READY":
            raise RuntimeHalt("missing_inputs", status=GoalStatus.WAITING, next_action="ASK_USER")
        if status in {"FAILED", "TIMEOUT", "UNKNOWN"}:
            failures = self.state.consumed.get("max_failures", 0) + 1
            self.state.consumed["max_failures"] = failures
            if failures >= self.state.limits.max_failures:
                raise RuntimeHalt("failure_limit")
            if self.phase() == BudgetPhase.NORMAL:
                self.reserve(max_replans=1)
                self.state.next_action = "REPLAN"
            else:
                self.state.next_action = "CONTINUE"

    def halt(self, reason, *, status=GoalStatus.BLOCKED, next_action="FAIL"):
        self.sync()
        self.state.status = status
        self.state.reason = reason
        self.state.next_action = next_action
