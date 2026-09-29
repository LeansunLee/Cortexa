"""Adapters for existing executors' results; they neither execute nor grant access."""

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .capabilities import CapabilityDescriptor, CapabilityType
from .observations import Observation
from .observations import ObservationStatus as Status


def _schema(value):
    return deepcopy(value) if isinstance(value, dict) else {}


def _availability(value):
    return "available" if value == "active" else "unknown" if value is None else "unavailable"


@dataclass
class CapabilityAdapter:
    descriptor: CapabilityDescriptor
    validation_messages: tuple[str, ...] = ()

    def observe(self, raw: Any, action_id: str, *, evidence=None, metadata=None, error=None) -> Observation:
        cap = self.descriptor
        observation = Observation(
            cap.type,
            cap.id,
            action_id,
            Status.UNKNOWN,
            raw_result=raw,
            evidence=list(evidence or []),
            metadata=dict(metadata or {}),
        )
        if error is not None:
            observation.status = Status.TIMEOUT if isinstance(error, TimeoutError) else Status.FAILED
            observation.error = {"type": type(error).__name__}
            observation.summary = "执行未完成"
            return observation
        if cap.type == CapabilityType.MEMORY:
            # Preserve full legacy result (including RetrievalResult.trace) and item provenance.
            memories = raw.memories if hasattr(raw, "memories") else raw
            observation.status = Status.SUCCESS if memories else Status.EMPTY
            observation.summary = f"召回 {len(memories)} 条记忆"
            observation.evidence.extend(
                {
                    "type": "memory",
                    "memory_id": str(item.id),
                    "source_mode": getattr(item, "source_mode", None),
                    "confidence": getattr(item, "confidence", None),
                    "has_conflict": getattr(item, "has_conflict", False),
                }
                for item in memories
            )
            # Memory claims are not promoted to new verified facts.
            return observation
        if cap.type == CapabilityType.KNOWLEDGE:
            observation.status = Status.SUCCESS if observation.evidence else Status.UNKNOWN if raw else Status.EMPTY
            if any(item.get("truncated") for item in observation.evidence if isinstance(item, dict)):
                observation.status = Status.PARTIAL
            if observation.metadata.get("pending_count") or observation.metadata.get("unreadable_count"):
                observation.status = (
                    Status.PARTIAL
                    if observation.evidence
                    else Status.NOT_READY
                    if observation.metadata.get("pending_count")
                    else Status.FAILED
                )
                observation.error = {"type": "knowledge_not_fully_readable"}
            observation.summary = f"知识检索返回 {len(observation.evidence)} 个来源"
            # A nonempty legacy text can consist solely of processing/read-failure notices.
            return observation
        if cap.type == CapabilityType.AGENT and hasattr(raw, "result"):
            observation.status = {
                "success": Status.SUCCESS,
                "partial": Status.PARTIAL,
                "failed": Status.FAILED,
                "timeout": Status.TIMEOUT,
                "input_required": Status.NOT_READY,
            }.get(raw.status, Status.UNKNOWN)
            observation.summary = raw.summary
            observation.evidence.extend(raw.sources)
            observation.confidence = raw.confidence
            observation.metadata.update(
                usage=raw.usage, input_snapshot=raw.input_snapshot, confidence_source="legacy_unvalidated"
            )
            if observation.status == Status.NOT_READY:
                resolution = raw.input_snapshot.get("resolution") or {}
                observation.metadata["missing_inputs"] = resolution.get("blockingMissingFields", [])
            if observation.status in {Status.FAILED, Status.TIMEOUT}:
                observation.error = {"type": raw.status, "message": raw.summary}
            return observation
        data = raw
        if isinstance(raw, str):
            if raw in self.validation_messages:
                observation.status = Status.NOT_READY
                observation.error = {"type": "input_validation"}
                return observation
            try:
                # Decode only complete JSON objects; retain original text unchanged.
                data = json.loads(raw) if raw.startswith("{") else raw
            except (ValueError, RecursionError):
                data = raw
        if not isinstance(data, dict):
            observation.status = Status.EMPTY if data is None or data == "" else Status.UNKNOWN
            return observation
        if data.get("requires_input"):
            observation.status = Status.NOT_READY
            observation.metadata["missing_inputs"] = (data.get("resolution") or {}).get("blockingMissingFields", [])
        elif data.get("error") or data.get("success") is False:
            observation.status = Status.FAILED
        elif data.get("truncated") is True:
            observation.status = Status.PARTIAL
        elif cap.type == CapabilityType.DATA and isinstance(data.get("data"), list):
            observation.status = Status.SUCCESS if data["data"] else Status.EMPTY
        elif cap.type == CapabilityType.WEB and isinstance(data.get("results"), list):
            observation.status = Status.SUCCESS if data["results"] else Status.EMPTY
        elif data.get("success") is True:
            observation.status = Status.SUCCESS
        if data.get("error"):
            observation.error = {"type": "legacy_error", "message": data["error"]}
        if cap.type == CapabilityType.DATA:
            observation.facts = data.get("data", []) if isinstance(data.get("data"), list) else []
            observation.metadata.update(
                {
                    key: data[key]
                    for key in ("row_count", "returned_rows", "truncated", "facets", "notice", "applied_parameters")
                    if key in data
                }
            )
            observation.summary = f"返回 {len(observation.facts)} 条数据；状态 {observation.status}"
        elif cap.type == CapabilityType.WEB:
            observation.evidence.extend(data["results"] if isinstance(data.get("results"), list) else [])
            observation.metadata.update({key: data[key] for key in ("notice", "query", "searched_at") if key in data})
            observation.summary = f"返回 {len(observation.evidence)} 个网页摘要来源；未读取全文"
        else:
            observation.summary = f"执行结果：{observation.status}"
        return observation


def tool_adapter(tool, workspace_id: str, *, capability=None) -> CapabilityAdapter:
    kind = (
        CapabilityType.DATA
        if capability is not None
        else CapabilityType.WEB
        if tool.name == "web_search"
        else CapabilityType.TOOL
    )
    schema = tool.args_schema
    input_schema = schema.model_json_schema() if hasattr(schema, "model_json_schema") else _schema(schema)
    cap_id = f"data:{capability.id}" if capability is not None else f"{kind.lower()}:{workspace_id}:{tool.name}"
    descriptor = CapabilityDescriptor(
        id=cap_id,
        workspace_id=str(getattr(capability, "workspace_id", None) or workspace_id),
        name=capability.name if capability is not None else tool.name,
        type=kind,
        description=tool.description or "",
        input_schema=input_schema,
        output_schema=_schema(getattr(capability, "output_schema", None)),
        operations=["query"] if kind == CapabilityType.DATA else ["search"] if kind == CapabilityType.WEB else [],
        availability=_availability(getattr(capability, "status", None)) if capability is not None else "available",
        constraints={"legacy_executor": True},
        risk_level="low" if kind == CapabilityType.WEB else "unknown",
        requires_confirmation=kind != CapabilityType.WEB,
        context_policy={"mode": "existing_tool_arguments", "enforced_by": "legacy_executor"},
        timeout=getattr(capability, "timeout_seconds", None)
        if capability is not None
        else 20
        if kind == CapabilityType.WEB
        else None,
    )
    if capability is not None:
        descriptor.constraints.update(
            row_limit=getattr(capability, "row_limit", None),
            configured_input_schema=_schema(getattr(capability, "input_schema", None)),
        )
    validation = getattr(tool, "handle_validation_error", None)
    messages = (
        ("Tool input validation error",) if validation is True else (validation,) if isinstance(validation, str) else ()
    )
    return CapabilityAdapter(descriptor, messages)


def retrieval_adapter(agent, kind: CapabilityType) -> CapabilityAdapter:
    if kind not in {CapabilityType.KNOWLEDGE, CapabilityType.MEMORY}:
        raise ValueError("Not a retrieval capability")
    return CapabilityAdapter(
        CapabilityDescriptor(
            id=f"{kind.lower()}:{agent.id}",
            workspace_id=str(agent.workspace_id),
            name=kind.value,
            type=kind,
            operations=["retrieve"],
            availability=_availability(agent.status),
            risk_level="low",
            requires_confirmation=False,
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            context_policy={"mode": "agent_owned_retrieval", "enforced_by": "legacy_executor"},
            timeout=10 if kind == CapabilityType.KNOWLEDGE else 5,
        )
    )


def agent_adapter(agent) -> CapabilityAdapter:
    # Never copy proxy_config, endpoint/headers, permissions or private System Prompt.
    return CapabilityAdapter(
        CapabilityDescriptor(
            id=f"agent:{agent.id}",
            workspace_id=str(agent.workspace_id),
            name=agent.role or "AI助手",
            type=CapabilityType.AGENT,
            description=agent.responsibilities or "",
            input_schema=_schema(agent.input_schema),
            output_schema=_schema(agent.output_schema),
            availability=_availability(agent.status),
            constraints={"agent_type": agent.agent_type},
            context_policy={
                "mode": "legacy_proxy_resolver" if agent.agent_type == "proxy" else "legacy_handoff",
                "enforced_by": "legacy_executor",
                "strict_projection": False,
            },
        )
    )
