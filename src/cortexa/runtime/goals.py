"""Pure Goal parsing and advisory routing. No I/O, model calls or authorization."""

import json
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from cortexa.agents.retrieval import plan_retrieval
from cortexa.collaboration.mention_parser import parse_mentions

PARSER_VERSION = "goal-shadow-v1"
MAX_PARSE_CHARS = 64000


class FieldSource(StrEnum):
    EXPLICIT = "EXPLICIT"
    DETERMINISTIC = "DETERMINISTIC"
    INFERRED = "INFERRED"
    DEFAULT = "DEFAULT"


class GapType(StrEnum):
    NONE = "NONE"
    PARAMETER_GAP = "PARAMETER_GAP"
    SEMANTIC_GAP = "SEMANTIC_GAP"
    INFORMATION_GAP = "INFORMATION_GAP"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    ENVIRONMENT_GAP = "ENVIRONMENT_GAP"


class Gap(BaseModel):
    kind: GapType
    code: str
    fields: list[str] = Field(default_factory=list)


class Participant(BaseModel):
    reference: str
    kind: str = "name"
    source: FieldSource = FieldSource.EXPLICIT


class CollaborationConstraint(BaseModel):
    allow_discovery: bool = True
    allow_collaboration: bool = True
    only_agents: list[str] = Field(default_factory=list)
    source: FieldSource = FieldSource.DEFAULT


class NormalizedGoal(BaseModel):
    version: str = PARSER_VERSION
    raw_request: str
    objective: str
    operations: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    explicit_agents: list[Participant] = Field(default_factory=list)
    collaboration_constraints: CollaborationConstraint = Field(default_factory=CollaborationConstraint)
    uncertainties: list[Gap] = Field(default_factory=list)
    field_sources: dict[str, FieldSource] = Field(default_factory=dict)
    retrieval_signals: list[str] = Field(default_factory=list)
    analysis_complete: bool = True


class Route(StrEnum):
    DIRECT = "DIRECT"
    RETRIEVAL = "RETRIEVAL"
    COLLABORATION = "COLLABORATION"
    ASK_USER = "ASK_USER"
    SEMANTIC_REVIEW = "SEMANTIC_REVIEW"
    RESOLVE_CAPABILITY = "RESOLVE_CAPABILITY"
    CHECK_ENVIRONMENT = "CHECK_ENVIRONMENT"


class GoalRoute(BaseModel):
    route: Route
    gap_types: list[GapType]
    enrichment_eligible: bool = False
    execution: str = "LEGACY_UNCHANGED"


_OPERATIONS = {
    "summarize": r"总结|汇总|摘要|\bsummari[sz]e\b",
    "translate": r"翻译|\btranslate\b",
    "rewrite": r"改写|润色|\brewrite\b",
    "query": r"查询|查找|检索|\bquery\b",
    "search": r"搜索|\bsearch\b",
    "analyze": r"分析|比较|对比|\banaly[sz]e\b|\bcompare\b",
    "create": r"创建|生成|撰写|\bcreate\b|\bwrite\b",
}
_LABELS = {
    "目标": "objective",
    "对象": "targets",
    "约束": "constraints",
    "成功标准": "success_criteria",
    "输出": "expected_output",
}


def analyze_gaps(goal: NormalizedGoal, *, required_inputs: tuple[str, ...] = ()) -> list[Gap]:
    """Only describe evidenced gaps; absence of catalog/history is not unavailability.

    required_inputs is used only by callers with a selected input contract and
    structured inputs. The Shadow integration does not guess a Proxy contract.
    """
    gaps = list(goal.uncertainties)
    missing = [name for name in required_inputs if name not in goal.inputs or goal.inputs[name] is None]
    if missing:
        gaps.append(Gap(kind=GapType.PARAMETER_GAP, code="required_inputs_missing", fields=missing))
    if not goal.objective and not goal.inputs:
        gaps.append(Gap(kind=GapType.PARAMETER_GAP, code="objective_missing", fields=["objective"]))
    if re.fullmatch(r"(?:请|帮我)?(?:处理|弄|搞)(?:一下|下)?[。！!]?", goal.objective):
        gaps.append(Gap(kind=GapType.SEMANTIC_GAP, code="operation_unspecified"))
    return gaps


def parse_goal(
    raw_request: str,
    *,
    explicit_agent_ids: tuple[str, ...] = (),
    explicit_inputs: dict[str, Any] | None = None,
) -> NormalizedGoal:
    """Raw text is always a valid objective; extraction never replaces it with a guess."""
    text = raw_request.replace("\r\n", "\n").replace("\r", "\n").strip()
    goal = NormalizedGoal(raw_request=raw_request, objective=text)
    goal.field_sources = {
        key: FieldSource.DEFAULT
        for key in (
            "operations",
            "targets",
            "inputs",
            "constraints",
            "success_criteria",
            "expected_output",
            "explicit_agents",
            "collaboration_constraints",
            "retrieval_signals",
        )
    }
    goal.field_sources["objective"] = FieldSource.EXPLICIT
    # Bound parsing work without silently truncating an objective or structured input.
    if len(text) > MAX_PARSE_CHARS:
        goal.analysis_complete = False
        goal.uncertainties = [Gap(kind=GapType.INFORMATION_GAP, code="analysis_size_limit")]
        return goal

    # Only explicitly labelled, line-separated fields are promoted to user requirements.
    for line in text.splitlines():
        match = re.fullmatch(r"\s*(目标|对象|约束|成功标准|输出)\s*[:：]\s*(.+?)\s*", line)
        if match:
            name, value = _LABELS[match[1]], match[2]
            if name in {"targets", "constraints", "success_criteria"}:
                getattr(goal, name).append(value)
            elif name == "objective":
                # Keep all request constraints in raw_request; multiple objectives are joined.
                goal.objective = (
                    value if goal.field_sources.get("labelled_objective") is None else goal.objective + "\n" + value
                )
                goal.field_sources["labelled_objective"] = FieldSource.EXPLICIT
            else:
                goal.expected_output = value if goal.expected_output is None else goal.expected_output + "\n" + value
            goal.field_sources[name] = FieldSource.EXPLICIT

    if explicit_inputs is not None:
        goal.inputs = dict(explicit_inputs)
        goal.field_sources["inputs"] = FieldSource.EXPLICIT
    elif text.startswith("{"):
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                goal.inputs = value
                goal.field_sources["inputs"] = FieldSource.EXPLICIT
        except (ValueError, RecursionError):
            # Prose containing braces is still a legal raw Goal.
            pass

    mentions = parse_mentions(text)
    participants = {(p.name, "name") for p in mentions.mentions}
    participants.update((ident, "id") for ident in explicit_agent_ids)
    goal.explicit_agents = [Participant(reference=ref, kind=kind) for ref, kind in sorted(participants)]
    if participants:
        goal.field_sources["explicit_agents"] = FieldSource.EXPLICIT

    clauses = re.split(r"[，,；;。\n]", mentions.cleaned_text)
    affirmative = "\n".join(
        clause for clause in clauses if not re.match(r"\s*(?:请)?(?:不要|不用|无需|禁止|别)", clause)
    )
    goal.operations = [name for name, pattern in _OPERATIONS.items() if re.search(pattern, affirmative, re.I)]
    goal.field_sources["operations"] = FieldSource.DETERMINISTIC
    policy = goal.collaboration_constraints
    if re.search(r"不要(?:找|调用|使用)(?:其他|其它)\s*(?:Agent|智能体)|不(?:要|允许)自主协作", text, re.I):
        policy.allow_discovery = False
        policy.source = FieldSource.EXPLICIT
    if re.search(r"不要协作|禁止协作|不要(?:找|调用|使用)任何\s*(?:Agent|智能体)", text, re.I):
        policy.allow_collaboration = False
        policy.allow_discovery = False
        policy.source = FieldSource.EXPLICIT
    only = re.findall(
        r"(?:只找|只允许(?:调用|使用))\s*(@?[^\s，,；;。]+?(?:Agent|智能体))(?=$|[\s，,；;。])", text, re.I
    )
    if only:
        policy.only_agents = sorted({name.removeprefix("@") for name in only})
        policy.allow_discovery = False
        policy.source = FieldSource.EXPLICIT
    goal.field_sources["collaboration_constraints"] = policy.source

    # Reuse existing lexical policy as advisory signals, not proof of availability.
    plan = plan_retrieval(text)
    goal.retrieval_signals = [name for name in ("web", "knowledge", "memory", "data") if getattr(plan, name)]
    goal.field_sources["retrieval_signals"] = FieldSource.DETERMINISTIC
    goal.uncertainties = analyze_gaps(goal)
    return goal


def route_goal(goal: NormalizedGoal) -> GoalRoute:
    """A proposal only. No Reasoner, enrichment, discovery or executor is called."""
    gaps = {gap.kind for gap in goal.uncertainties}
    route = Route.DIRECT
    for kind, proposal in (
        (GapType.PARAMETER_GAP, Route.ASK_USER),
        (GapType.ENVIRONMENT_GAP, Route.CHECK_ENVIRONMENT),
        (GapType.CAPABILITY_GAP, Route.RESOLVE_CAPABILITY),
        (GapType.INFORMATION_GAP, Route.RETRIEVAL),
        (GapType.SEMANTIC_GAP, Route.SEMANTIC_REVIEW),
    ):
        if kind in gaps:
            route = proposal
            break
    else:
        if goal.explicit_agents and goal.collaboration_constraints.allow_collaboration:
            route = Route.COLLABORATION
        elif goal.retrieval_signals:
            route = Route.RETRIEVAL
    return GoalRoute(
        route=route,
        gap_types=sorted(gaps) or [GapType.NONE],
        enrichment_eligible=bool(goal.analysis_complete and gaps == {GapType.SEMANTIC_GAP}),
    )
