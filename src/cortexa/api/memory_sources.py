"""Read-only restoration of memory references; never expose archived memory text."""

import uuid
from copy import deepcopy

from sqlalchemy import select

from cortexa.runtime.artifacts import ArtifactStore
from cortexa.runtime.models import RuntimeGoal
from cortexa.runtime.store import owned


def restore_sources(metadata, snapshot):
    result = deepcopy(metadata or {})
    observations = {o.get("action_id"): o for o in snapshot.get("observations", []) if o.get("action_id")}
    for step in result.get("steps", []):
        sources = step.get("sources", [])
        if not any(s.get("type") == "memory" and not s.get("memory_id") for s in sources):
            continue
        evidence = observations.get(step.get("tool"), {}).get("evidence", [])
        memories = [e for e in evidence if e.get("type") == "memory" and e.get("memory_id")]
        # Exact action and count required: never infer identity from a nearby step.
        if len(memories) != sum(s.get("type") == "memory" for s in sources):
            continue
        refs = iter(memories)
        for source in sources:
            if source.get("type") == "memory":
                source["memory_id"] = next(refs)["memory_id"]
    for step in result.get("steps", []):
        for i, source in enumerate(step.get("sources", [])):
            if source.get("type") == "memory":
                source.setdefault("name", f"记忆 {i + 1}")
    return result


async def restored_messages(db, conv_id, messages):
    ids = set()
    for message in messages:
        meta = message.metadata_json or {}
        if not any(
            source.get("type") == "memory" and not source.get("memory_id")
            for step in meta.get("steps", [])
            for source in step.get("sources", [])
        ):
            continue
        try:
            ids.add(uuid.UUID(str((message.metadata_json or {}).get("goal_id"))))
        except (ValueError, TypeError):
            pass
    snapshots = {}
    if ids:
        rows = await db.scalars(
            select(RuntimeGoal).where(*owned(), RuntimeGoal.conversation_id == conv_id, RuntimeGoal.id.in_(ids))
        )
        for row in rows:
            try:
                snapshots[str(row.id)] = ArtifactStore().read(row.id, row.artifacts["snapshot"])
            except (OSError, ValueError, KeyError):
                continue
    return [
        (
            message,
            restore_sources(
                message.metadata_json, snapshots.get(str((message.metadata_json or {}).get("goal_id")), {})
            ),
        )
        for message in messages
    ]


def contains_memory(metadata, memory_id):
    refs = list(metadata.get("sources", []))
    for step in metadata.get("steps", []):
        refs.extend(step.get("sources", []))
    return any(s.get("type") == "memory" and s.get("memory_id") == str(memory_id) for s in refs)


async def recalled_in_snapshot(db, conv_id, memory_id):
    rows = await db.scalars(select(RuntimeGoal).where(*owned(), RuntimeGoal.conversation_id == conv_id))
    for row in rows:
        try:
            snapshot = ArtifactStore().read(row.id, row.artifacts["snapshot"])
        except (OSError, ValueError, KeyError):
            continue
        for observation in snapshot.get("observations", []):
            if any(
                e.get("type") == "memory" and e.get("memory_id") == str(memory_id)
                for e in observation.get("evidence", [])
            ):
                return True
    return False
