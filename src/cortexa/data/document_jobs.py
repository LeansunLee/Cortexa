"""Process-safe job locks; metadata remains the durable recovery marker."""

import asyncio
import fcntl
from contextlib import asynccontextmanager
from pathlib import Path

from cortexa.data.doc_storage import DOC_STORAGE_DIR


@asynccontextmanager
async def document_job_lock(document_id, kind):
    # Keep locks outside document directories so deletion cannot invalidate one.
    root = Path(DOC_STORAGE_DIR) / '.locks'
    root.mkdir(parents=True, exist_ok=True)
    with (root / f'{document_id}.{kind}').open('a') as handle:
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
