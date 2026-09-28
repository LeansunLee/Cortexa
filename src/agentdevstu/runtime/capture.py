"""Bounded Phase 2 shadow projection into the existing Debug trace."""

import hashlib
from collections import Counter
from datetime import UTC, datetime

from .capabilities import MatchScope, match_capabilities
from .shadow import shadow_enabled


def capability_shadow_enabled(config_path):
    return shadow_enabled(config_path, feature="capability_shadow_enabled")


def _opaque(value):
    return hashlib.sha256(str(value).encode(errors="surrogatepass")).hexdigest()[:24]


class CapabilityCapture:
    """No raw payload retained here; adapters expose lossless observations in-process."""

    def __init__(self, enabled: bool, trace: list, *, max_entries=64):
        self.enabled = enabled
        self.trace = trace
        self.max_entries = max_entries
        self.count = 0
        self.overflow = None

    def _entry(self, stage, detail, *, failed=False):
        if self.count >= self.max_entries:
            if self.overflow is None:
                self.overflow = {
                    "seq": len(self.trace) + 1,
                    "stage": "runtime_observation",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "status": "info",
                    "title": "Observation 影子记录达到上限",
                    "summary": "不影响实际执行",
                    "detail": {"omitted_entries": 0},
                }
                self.trace.append(self.overflow)
            self.overflow["detail"]["omitted_entries"] += 1
            return None
        self.count += 1
        entry = {
            "seq": len(self.trace) + 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "stage": stage,
            "status": "error" if failed else "success",
            "title": "Capability / Observation 影子记录",
            "summary": "沿用现有执行器和原始结果",
            "detail": {"version": "capability-shadow-v1", "mode": "SHADOW", **detail},
        }
        self.trace.append(entry)
        return entry

    def observe(self, adapter_factory, raw, *, action_id=None, evidence=None, metadata=None, error=None):
        if not self.enabled:
            return None
        # Do not normalize/copy large results after the trace budget is exhausted.
        if self.count >= self.max_entries:
            return self._entry("runtime_observation", {})
        try:
            observation = adapter_factory().observe(
                raw,
                action_id or f"observation:{self.count + 1}",
                evidence=evidence,
                metadata=metadata,
                error=error,
            )
            return self._entry(
                "runtime_observation",
                {
                    "source_type": observation.source_type,
                    "source_id_hash": _opaque(observation.source_id),
                    "action_id_hash": _opaque(observation.action_id),
                    "observation_status": observation.status,
                    "facts_count": len(observation.facts),
                    "evidence_count": len(observation.evidence),
                    "has_error": observation.error is not None,
                    "has_raw_result": observation.raw_result is not None,
                    "missing_inputs_count": len(observation.metadata.get("missing_inputs") or []),
                    "reused_cache": observation.metadata.get("reused_cache") is True,
                    "execution_skipped": observation.metadata.get("skipped") is True,
                },
            )
        except Exception:
            return self._entry("runtime_observation", {"error_code": "observation_adapter_failed"}, failed=True)

    def catalog(self, adapter_factories, query, workspace_id):
        if not self.enabled:
            return None
        if self.count >= self.max_entries:
            return self._entry("runtime_capability", {})
        try:
            # Snapshot only already loaded/authorized tools; do not enumerate Workspace Agents.
            caps = [factory().descriptor for factory in adapter_factories[:128]]
            scope = MatchScope(str(workspace_id), frozenset(cap.id for cap in caps))
            matches = match_capabilities(query, caps, scope)
            return self._entry(
                "runtime_capability",
                {
                    "registered_count": len(caps),
                    "omitted_count": max(0, len(adapter_factories) - len(caps)),
                    "types": dict(Counter(cap.type for cap in caps)),
                    "matches": [
                        {
                            "id_hash": _opaque(match.capability.id),
                            "type": match.capability.type,
                            "score": match.score,
                            "reasons": match.reasons,
                        }
                        for match in matches
                    ],
                    "legacy_tool_selection_unchanged": True,
                },
            )
        except Exception:
            return self._entry("runtime_capability", {"error_code": "capability_adapter_failed"}, failed=True)
