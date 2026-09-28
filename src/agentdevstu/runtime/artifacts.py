"""Private, immutable snapshots. No user-supplied paths, no public static mount."""

import base64
import hashlib
import json
import os
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "data" / "runtime_goals"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def typed_scalar(value):
    """Preserve non-JSON database scalars with explicit type tags and exact values."""
    if isinstance(value, (datetime, date)):
        return {"$runtime_type": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, (Decimal, uuid.UUID)):
        return {"$runtime_type": type(value).__name__, "value": str(value)}
    if isinstance(value, bytes):
        return {"$runtime_type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    raise TypeError("Unsupported Goal artifact value")


class ArtifactStore:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def write(self, goal_id, payload):
        goal_id = str(uuid.UUID(str(goal_id)))
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=typed_scalar).encode()
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ValueError("goal_artifact_size_limit")
        directory = self.root / goal_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = uuid.uuid4().hex
        path = directory / (key + ".json")
        # Unique immutable file: orphan on failed DB commit is harmless and never referenced.
        with path.open("xb") as file:
            os.chmod(path, 0o600)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        return {"version": 1, "key": key, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def read(self, goal_id, ref):
        goal_id = str(uuid.UUID(str(goal_id)))
        key = uuid.UUID(hex=ref["key"]).hex
        path = self.root / goal_id / (key + ".json")
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ValueError("goal_artifact_size_limit")
        data = path.read_bytes()
        if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("goal_artifact_integrity_failed")
        return json.loads(data)
