"""Private per-user debug display preference, independent of global collection."""

import json
import os
import uuid
from pathlib import Path

PREFERENCE_DIR = Path(__file__).resolve().parents[3] / "data" / "user_preferences"


def debug_enabled(user_id: uuid.UUID) -> bool:
    try:
        data = json.loads((PREFERENCE_DIR / f"{user_id}.json").read_text(encoding="utf-8"))
        return data.get("conversation_debug") is True
    except (OSError, ValueError, AttributeError):
        return False


def set_debug_enabled(user_id: uuid.UUID, enabled: bool) -> None:
    PREFERENCE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(PREFERENCE_DIR, 0o700)
    destination = PREFERENCE_DIR / f"{user_id}.json"
    temporary = PREFERENCE_DIR / f".{user_id}.{uuid.uuid4().hex}.tmp"
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"conversation_debug": enabled}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def can_view_debug(actor) -> bool:
    return bool(
        actor and actor.has("conversation.debug") and getattr(actor, "user_id", None)
        and debug_enabled(actor.user_id)
    )
