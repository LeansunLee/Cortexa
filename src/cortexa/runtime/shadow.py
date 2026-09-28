"""Fail-open, content-minimizing adapter to the existing Conversation Debug trace."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import yaml

from .goals import PARSER_VERSION, parse_goal, route_goal

PROTECTED_TRACE_STAGES = frozenset({"goal", "runtime_capability", "runtime_observation", "runtime_goal"})


def shadow_enabled(config_path: Path, *, feature="goal_shadow_enabled") -> bool:
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return config.get("features", {}).get(feature) is True
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        return False


def can_read_goal_trace() -> bool:
    from cortexa.security.access import current_actor
    from cortexa.security.debug_preferences import can_view_debug

    return can_view_debug(current_actor.get())


def visible_trace(entries: list[dict]) -> list[dict]:
    return entries if can_read_goal_trace() else []


def goal_shadow_entry(raw_request: str, message_id: str, *, explicit_agent_ids: tuple[str, ...] = ()) -> dict:
    """Store references and bounded semantic metadata, never raw fields or values.

    The original message remains the source for Raw Goal. In particular, names,
    schema keys, credentials in text/JSON, and inferred source data are not logged.
    """
    started = perf_counter()
    detail = {
        "version": PARSER_VERSION,
        "mode": "SHADOW",
        "raw_goal": {
            "message_id": message_id,
            "sha256": hashlib.sha256(raw_request.encode(errors="surrogatepass")).hexdigest(),
        },
        "llm_calls_added": 0,
        "execution": "LEGACY_UNCHANGED",
    }
    status = "success"
    try:
        goal = parse_goal(raw_request, explicit_agent_ids=explicit_agent_ids)
        route = route_goal(goal)
        detail.update(
            {
                "parse": {
                    "operations": goal.operations,
                    "field_sources": goal.field_sources,
                    "retrieval_signals": goal.retrieval_signals,
                    "analysis_complete": goal.analysis_complete,
                    "counts": {
                        "targets": len(goal.targets),
                        "inputs": len(goal.inputs),
                        "constraints": len(goal.constraints),
                        "success_criteria": len(goal.success_criteria),
                        "explicit_agents": len(goal.explicit_agents),
                    },
                    "has_expected_output": goal.expected_output is not None,
                    "collaboration_constraints": {
                        "allow_discovery": goal.collaboration_constraints.allow_discovery,
                        "allow_collaboration": goal.collaboration_constraints.allow_collaboration,
                        "only_agents_count": len(goal.collaboration_constraints.only_agents),
                    },
                },
                "gaps": [{"type": gap.kind, "code": gap.code} for gap in goal.uncertainties],
                "route": route.model_dump(mode="json"),
                "enrichment_executed": False,
            }
        )
    except Exception:
        # Never log exception text: parser errors may include private input.
        status = "error"
        detail["error_code"] = "goal_shadow_parse_failed"
    detail["duration_ms"] = round((perf_counter() - started) * 1000, 3)
    return {
        "stage": "goal",
        "title": "Goal 影子解析",
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
        "summary": "仅记录目标解析与路由建议，继续现有执行路径",
        "detail": detail,
    }
