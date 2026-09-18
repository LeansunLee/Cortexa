"""Provider callbacks write a bounded, content-free durable outbox.

SQLite commits survive PostgreSQL outages. PostgreSQL upserts are idempotent;
acknowledgement checks the version so a concurrent completion cannot be lost.
"""

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

from .context import current_usage, root_context

logger = logging.getLogger(__name__)
INSTANCE = uuid.uuid4().hex
BOOT_TIME = datetime.now(UTC)
_health = {"last_flush_at": None, "last_error": None, "write_failures": 0}
_task = None


def spool_path():
    return Path(
        os.environ.get("USAGE_SPOOL_PATH", str(Path(__file__).resolve().parents[3] / "data/usage/outbox.sqlite3"))
    )


@contextmanager
def connect():
    path = spool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, version INTEGER NOT NULL, "
            "instance TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        with db:
            yield db
    finally:
        db.close()


def enqueue(record, version):
    try:
        with connect() as db:
            # UPDATE + INSERT OR IGNORE supports the development server's SQLite 3.7.
            # Both writes share one transaction; older events cannot overwrite completion.
            ident = record["call"]["id"]
            payload = json.dumps(record)
            db.execute(
                "UPDATE outbox SET version=?, instance=?, payload=? WHERE id=? AND version<=?",
                (version, INSTANCE, payload, ident, version),
            )
            db.execute("INSERT OR IGNORE INTO outbox VALUES (?, ?, ?, ?)", (ident, version, INSTANCE, payload))

    except Exception as exc:
        _health["write_failures"] += 1
        _health["last_error"] = type(exc).__name__
        logger.exception("Usage outbox write failed")


def number(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def normalize_usage(message=None, llm_output=None):
    metadata = getattr(message, "response_metadata", None) or {}
    usage = getattr(message, "usage_metadata", None)
    raw = metadata.get("token_usage") or metadata.get("usage") or (llm_output or {}).get("token_usage") or {}
    if usage:
        inp, out, total = (number(usage.get(k)) for k in ("input_tokens", "output_tokens", "total_tokens"))
        in_detail, out_detail = usage.get("input_token_details") or {}, usage.get("output_token_details") or {}
    else:
        inp = number(raw.get("prompt_tokens", raw.get("input_tokens")))
        out = number(raw.get("completion_tokens", raw.get("output_tokens")))
        total = number(raw.get("total_tokens"))
        in_detail = raw.get("prompt_tokens_details") or {}
        out_detail = raw.get("completion_tokens_details") or {}
        # Anthropic raw input excludes cache reads/writes; LangChain usage above includes them.
        if "input_tokens" in raw and "prompt_tokens" not in raw and inp is not None:
            inp += (number(raw.get("cache_read_input_tokens")) or 0) + (
                number(raw.get("cache_creation_input_tokens")) or 0
            )
    if total is None and inp is not None and out is not None:
        total = inp + out
    status = (
        "complete"
        if all(v is not None for v in (inp, out, total))
        else "partial"
        if any(v is not None for v in (inp, out, total))
        else "unknown"
    )
    return dict(
        input_tokens=inp,
        output_tokens=out,
        total_tokens=total,
        usage_status=status,
        cache_read_tokens=number(
            in_detail.get("cache_read", in_detail.get("cached_tokens", raw.get("cache_read_input_tokens")))
        ),
        cache_creation_tokens=number(in_detail.get("cache_creation", raw.get("cache_creation_input_tokens"))),
        reasoning_tokens=number(out_detail.get("reasoning", out_detail.get("reasoning_tokens"))),
    )


class UsageCallback(BaseCallbackHandler):
    run_inline = True

    def __init__(self, provider, kind, model):
        self.provider, self.kind, self.model = str(provider)[:160], str(kind)[:40], str(model)[:200]
        self.agent_context = {k: v for k, v in (current_usage.get() or {}).items() if k in ("agent_id", "agent_name")}
        self.active = {}
        self.lock = threading.Lock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        # Deliberately ignore serialized/messages: they may contain prompts or credentials.
        from agentdevstu.security.access import current_actor

        actor = current_actor.get()
        ctx = dict(current_usage.get() or root_context())
        ctx.update(self.agent_context)
        now = datetime.now(UTC).isoformat()
        operation = dict(
            id=ctx["operation_id"],
            started_at=ctx["started_at"],
            source=ctx["source"],
            trigger="user" if actor else "system",
            user_id=str(actor.user_id) if actor else ctx.get("user_id"),
            user_name=actor.username if actor else ctx.get("user_name"),
            workspace_id=ctx.get("workspace_id") or (str(actor.workspace_id) if actor and actor.workspace_id else None),
            object_type=ctx.get("object_type"),
            object_id=ctx.get("object_id"),
        )
        call = dict(
            id=str(run_id),
            operation_id=operation["id"],
            step_id=ctx["step_id"],
            parent_step_id=ctx.get("parent_step_id"),
            started_at=now,
            ended_at=None,
            action=ctx.get("action", "model_call"),
            trigger=ctx["trigger"],
            agent_id=ctx.get("agent_id"),
            agent_name=str(ctx.get("agent_name") or "")[:160] or None,
            provider=self.provider,
            provider_kind=self.kind,
            requested_model=self.model,
            actual_model=None,
            provider_request_id=None,
            status="running",
            duration_ms=None,
            retry_count=0,
            error_type=None,
            usage_detail={"source": "provider", "retry_visibility": "callback_only"},
            **normalize_usage(),
        )
        record = {"operation": operation, "call": call}
        with self.lock:
            self.active[str(run_id)] = (record, time.monotonic())
        enqueue(record, 0)

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self.on_chat_model_start(serialized, None, run_id=run_id, **kwargs)

    def on_retry(self, retry_state, *, run_id, **kwargs):
        with self.lock:
            item = self.active.get(str(run_id))
            if item:
                item[0]["call"]["retry_count"] += 1

    def finish(self, run_id, response=None, error=None):
        with self.lock:
            item = self.active.pop(str(run_id), None)
        if item is None:
            return
        record, started = item
        call = record["call"]
        message, output = None, getattr(response, "llm_output", None) or {}
        generations = getattr(response, "generations", None) or []
        if generations and generations[0]:
            message = getattr(generations[0][0], "message", None)
        metadata = getattr(message, "response_metadata", None) or {}
        call.update(normalize_usage(message, output))
        call.update(
            ended_at=datetime.now(UTC).isoformat(),
            duration_ms=round((time.monotonic() - started) * 1000),
            actual_model=str(metadata.get("model_name") or metadata.get("model") or output.get("model_name") or "")[
                :200
            ]
            or None,
            provider_request_id=str(metadata.get("id") or metadata.get("request_id") or "")[:200] or None,
            status="cancelled" if isinstance(error, asyncio.CancelledError) else "failed" if error else "success",
            error_type=type(error).__name__[:100] if error else None,
        )
        enqueue(record, 1)

    def on_llm_end(self, response, *, run_id, **kwargs):
        self.finish(run_id, response)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.finish(run_id, kwargs.get("response"), error)


def pending_batch(limit=200):
    with connect() as db:
        return db.execute("SELECT id, version, instance, payload FROM outbox LIMIT ?", (limit,)).fetchall()


def acknowledge(rows):
    with connect() as db:
        db.executemany("DELETE FROM outbox WHERE id=? AND version=? AND instance=?", [(r[0], r[1], r[2]) for r in rows])


def decode(values, *, call=False):
    values = dict(values)
    for key in ("id", "operation_id") if call else ("id",):
        values[key] = uuid.UUID(values[key])
    for key in ("started_at", "ended_at") if call else ("started_at",):
        if values.get(key):
            values[key] = datetime.fromisoformat(values[key])
    return values


async def flush_once():
    from sqlalchemy.dialects.postgresql import insert

    from agentdevstu.db.engine import async_session_factory

    from .models import UsageCall, UsageOperation

    rows = await asyncio.to_thread(pending_batch)
    if not rows:
        return 0
    async with async_session_factory() as db:
        for _ident, version, instance, payload in rows:
            record = json.loads(payload)
            operation, call = decode(record["operation"]), decode(record["call"], call=True)
            if version == 0 and instance != INSTANCE:
                call.update(status="interrupted", error_type="ProcessInterrupted")
            await db.execute(insert(UsageOperation).values(**operation).on_conflict_do_nothing(index_elements=["id"]))
            stmt = insert(UsageCall).values(**call)
            await db.execute(
                stmt.on_conflict_do_update(
                    index_elements=["id"],
                    set_={k: getattr(stmt.excluded, k) for k in call if k != "id"},
                    where=UsageCall.ended_at.is_(None),
                )
            )
        await db.commit()
    await asyncio.to_thread(acknowledge, rows)
    _health.update(last_flush_at=datetime.now(UTC).isoformat(), last_error=None)
    return len(rows)


async def health():
    def counts():
        with connect() as db:
            return db.execute("SELECT count(*) FROM outbox").fetchone()[0]

    try:
        pending = await asyncio.to_thread(counts)
    except Exception as exc:
        pending = None
        _health["last_error"] = type(exc).__name__
    return {**_health, "pending_records": pending}


async def recover_interrupted():
    # Single-process deployment: calls predating this process cannot still be running.
    from sqlalchemy import update

    from agentdevstu.db.engine import async_session_factory

    from .models import UsageCall

    async with async_session_factory() as db:
        await db.execute(
            update(UsageCall)
            .where(UsageCall.status == "running", UsageCall.started_at < BOOT_TIME)
            .values(status="interrupted", error_type="ProcessInterrupted")
        )
        await db.commit()


async def worker():
    recovered = False
    while True:
        try:
            if not recovered:
                await asyncio.wait_for(recover_interrupted(), timeout=15)
                recovered = True
            count = await asyncio.wait_for(flush_once(), timeout=15)
        except Exception as exc:
            _health["last_error"] = type(exc).__name__
            logger.warning("Usage flush deferred: %s", type(exc).__name__)
            count = 0
        await asyncio.sleep(0.1 if count == 200 else 2)


async def start():
    global _task
    _task = asyncio.create_task(worker())


async def stop():
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    try:
        await asyncio.wait_for(flush_once(), 5)
    except Exception:
        pass  # Durable outbox is replayed on next start.


class AuditedEmbeddingClient:
    """Wrap each actual embedding batch, before LangChain discards response usage."""

    def __init__(self, client, provider, model):
        self.client, self.provider, self.model = client, provider, model

    def create(self, *args, **kwargs):
        from types import SimpleNamespace

        from .context import usage_scope

        action = (
            "embedding_query" if (current_usage.get() or {}).get("action") == "embedding_query" else "embedding_index"
        )
        with usage_scope(action, source="knowledge"):
            callback = UsageCallback(self.provider, "embedding", self.model)
            run_id = uuid.uuid4()
            callback.on_chat_model_start(None, None, run_id=run_id)
            try:
                response = self.client.create(*args, **kwargs)
                data = response if isinstance(response, dict) else response.model_dump()
                raw = dict(data.get("usage") or {})
                if raw:
                    raw["completion_tokens"] = 0
                message = SimpleNamespace(
                    response_metadata={
                        "usage": raw,
                        "model": data.get("model"),
                        "request_id": getattr(response, "_request_id", None),
                    }
                )
                callback.finish(run_id, SimpleNamespace(generations=[[SimpleNamespace(message=message)]]))
                return response
            except BaseException as exc:
                callback.on_llm_error(exc, run_id=run_id)
                raise
