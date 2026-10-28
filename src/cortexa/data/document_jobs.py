"""Process-safe job locks; metadata remains the durable recovery marker."""

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows dev/test runs single-process; POSIX servers keep flock.
    fcntl = None

from cortexa.data.doc_storage import DOC_STORAGE_DIR

_PROCESS_LOCKS: dict[str, asyncio.Lock] = {}


def _locks_root() -> Path:
    return Path(DOC_STORAGE_DIR) / '.locks'


@asynccontextmanager
async def document_job_lock(document_id, kind):
    # Keep locks outside document directories so deletion cannot invalidate one.
    root = _locks_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f'{document_id}.{kind}'
    if fcntl is None:
        lock = _PROCESS_LOCKS.setdefault(str(path), asyncio.Lock())
        async with lock:
            yield
        return
    with path.open('a') as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def clear_document_locks(document_id):
    """Drop every lock variant of a deleted document (extraction/index/summary)."""
    root = _locks_root()
    removed = []
    if not root.exists():
        return removed
    for path in root.glob(f'{document_id}.*'):
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            pass
    return removed


def sweep_orphan_locks(max_age_minutes=60):
    """Remove lock files stale enough that no live job can still hold them."""
    root = _locks_root()
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_minutes * 60
    removed = 0
    for path in root.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed
