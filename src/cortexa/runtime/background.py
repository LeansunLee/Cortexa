"""Private stop signals and bounded in-process workers; no request owns their lifetime."""

import uuid
from pathlib import Path

from cortexa.runtime.artifacts import ROOT

workers = {}
CONTROL_ROOT = ROOT / "controls"


def signal_path(goal_id):
    return Path(CONTROL_ROOT) / (str(uuid.UUID(str(goal_id))) + ".stop")


def request_stop(goal_id):
    path = signal_path(goal_id)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.exists():
        path.touch(mode=0o600)
    worker = workers.get(str(goal_id))
    if worker and not worker.done():
        worker.cancel()
    return worker


def clear_stop(goal_id):
    signal_path(goal_id).unlink(missing_ok=True)


def heartbeat(goal_id):
    path = signal_path(goal_id).with_suffix(".lease")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.touch(mode=0o600)


def lease_expired(goal_id):
    import time

    worker = workers.get(str(goal_id))
    if worker and not worker.done():
        return False
    path = signal_path(goal_id).with_suffix(".lease")
    return path.exists() and time.time() - path.stat().st_mtime > 30


def release(goal_id):
    signal_path(goal_id).with_suffix(".lease").unlink(missing_ok=True)
