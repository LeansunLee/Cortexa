"""Accounting correctness through real LangChain callbacks and isolated PG aggregation."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
import httpx
import pytest
from cortexa.usage import collector
from cortexa.usage.context import current_usage, root_context, usage_scope, usage_action
from cortexa.usage.collector import UsageCallback, normalize_usage


@pytest.fixture
def spool(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_SPOOL_PATH", str(tmp_path / "outbox.sqlite3"))
    collector._health.update(last_flush_at=None, last_error=None, write_failures=0)
    token = current_usage.set(None)
    yield
    current_usage.reset(token)


def records():
    return [json.loads(row[3]) for row in collector.pending_batch(1000)]


def test_normalize_missing_zero_partial_and_provider_subtokens():
    assert normalize_usage()["total_tokens"] is None
    zero = normalize_usage(SimpleNamespace(usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}))
    assert zero["total_tokens"] == 0 and zero["usage_status"] == "complete"
    partial = normalize_usage(SimpleNamespace(response_metadata={"usage": {"prompt_tokens": 10}}))
    assert partial["input_tokens"] == 10 and partial["total_tokens"] is None and partial["usage_status"] == "partial"
    usage = normalize_usage(
        SimpleNamespace(
            response_metadata={
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 3,
                }
            }
        )
    )
    assert usage["total_tokens"] == 38 and usage["input_tokens"] == 33 and usage["cache_read_tokens"] == 20
    usage = normalize_usage(
        SimpleNamespace(
            usage_metadata={
                "input_tokens": 33,
                "output_tokens": 5,
                "total_tokens": 38,
                "input_token_details": {"cache_read": 20, "cache_creation": 3},
                "output_token_details": {"reasoning": 2},
            }
        )
    )
    assert usage["total_tokens"] == 38 and usage["reasoning_tokens"] == 2


def mock_model(callback):
    from langchain_openai import ChatOpenAI

    def respond(request):
        payload = json.loads(request.content)
        common = {"id": "chatcmpl-test", "created": 1, "model": "actual-model"}
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": 4},
            "completion_tokens_details": {"reasoning_tokens": 2},
        }
        if payload.get("stream"):
            frames = [
                {
                    **common,
                    "object": "chat.completion.chunk",
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant", "content": "secret-reply"}, "finish_reason": None}
                    ],
                },
                {
                    **common,
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
                {**common, "object": "chat.completion.chunk", "choices": [], "usage": usage},
            ]
            text = "".join("data: " + json.dumps(frame) + "\n\n" for frame in frames) + "data: [DONE]\n\n"
            return httpx.Response(200, text=text, headers={"content-type": "text/event-stream"})
        return httpx.Response(
            200,
            json={
                **common,
                "object": "chat.completion",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "secret-reply"}, "finish_reason": "stop"}
                ],
                "usage": usage,
            },
        )

    transport = httpx.MockTransport(respond)
    return ChatOpenAI(
        model="requested-model",
        api_key="secret-key",
        callbacks=[callback],
        stream_usage=True,
        http_client=httpx.Client(transport=transport),
        http_async_client=httpx.AsyncClient(transport=transport),
        max_retries=0,
    )


def test_sync_async_stream_and_tool_binding_once_each(spool):
    root = root_context("conversation")
    token = current_usage.set(root)
    try:
        model = mock_model(UsageCallback("provider-a", "openai", "requested-model"))
        model.invoke("secret-prompt")

        async def run():
            await model.ainvoke("secret-prompt")
            async for _ in model.astream("secret-prompt"):
                pass
            bound = model.bind_tools(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "lookup",
                            "description": "lookup",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ]
            )
            await bound.ainvoke("secret-prompt")

        asyncio.run(run())
        rows = records()
        assert len(rows) == 4
        assert {r["operation"]["id"] for r in rows} == {root["operation_id"]}
        assert sum(r["call"]["total_tokens"] for r in rows) == 60
        assert all(r["call"]["status"] == "success" and r["call"]["actual_model"] == "actual-model" for r in rows)
        assert "secret" not in json.dumps(rows)
    finally:
        current_usage.reset(token)


def test_concurrent_context_and_background_inheritance(spool):
    callback = UsageCallback("provider", "openai", "model")

    @usage_action("memory_extract", background=True)
    async def child():
        await asyncio.sleep(0)
        run_id = uuid.uuid4()
        callback.on_chat_model_start(None, None, run_id=run_id)
        callback.on_llm_error(asyncio.CancelledError(), run_id=run_id)

    async def request(ident):
        ctx = root_context("conversation", "conversation", ident, "user")
        token = current_usage.set(ctx)
        try:
            await asyncio.create_task(child())
        finally:
            current_usage.reset(token)

    async def run():
        await asyncio.gather(request("one"), request("two"))

    asyncio.run(run())
    rows = records()
    assert len({r["operation"]["id"] for r in rows}) == 2
    assert {r["operation"]["object_id"] for r in rows} == {"one", "two"}
    assert all(
        r["call"]["action"] == "memory_extract"
        and r["call"]["trigger"] == "background"
        and r["call"]["status"] == "cancelled"
        and r["call"]["total_tokens"] is None
        for r in rows
    )


def test_outbox_ack_does_not_delete_concurrent_completion(spool):
    cb = UsageCallback("p", "openai", "m")
    ident = uuid.uuid4()
    cb.on_chat_model_start(None, None, run_id=ident)
    start_rows = collector.pending_batch()
    cb.on_llm_error(RuntimeError("secret-error"), run_id=ident)
    collector.acknowledge(start_rows)
    assert len(records()) == 1 and records()[0]["call"]["status"] == "failed"
    assert "secret-error" not in json.dumps(records())


def test_api_superadmin_only_and_filters():
    from fastapi import FastAPI
    from cortexa.usage.api import router
    from cortexa.security.access import Actor, current_actor

    app = FastAPI()
    app.include_router(router)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            for superadmin, permissions in [(False, set()), (False, {"users.manage", "audit.read", "config.manage"})]:
                token = current_actor.set(
                    Actor(uuid.uuid4(), "user", superadmin, False, 1, system_permissions=permissions)
                )
                try:
                    for path in ("summary", "groups", "calls", "options", "export", f"operations/{uuid.uuid4()}"):
                        response = await client.get("/admin/usage/" + path)
                        assert response.status_code == 403, (path, response.text)
                finally:
                    current_actor.reset(token)

    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("USAGE_TEST_DATABASE_URL"), reason="Disposable PostgreSQL schema URL not configured")
def test_postgres_replay_aggregates_filters_and_csv(spool, monkeypatch):
    asyncio.run(pg_integration(monkeypatch))


async def pg_integration(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import text, select
    from sqlalchemy.engine import make_url
    from fastapi import FastAPI
    from cortexa.usage.api import router
    from cortexa.usage.models import UsageOperation, UsageCall
    from cortexa.api.deps import get_db
    import importlib

    engine_module = importlib.import_module("cortexa.db.engine")
    from cortexa.security.access import Actor, current_actor

    url = make_url(os.environ["USAGE_TEST_DATABASE_URL"]).set(drivername="postgresql+asyncpg")
    base = create_async_engine(url)
    schema = "usage_test_" + uuid.uuid4().hex
    async with base.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "async_session_factory", factory)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: UsageOperation.metadata.create_all(c, tables=[UsageOperation.__table__, UsageCall.__table__])
            )
        token = current_usage.set(root_context("conversation", "conversation", "conv-test", "user"))
        try:
            model = mock_model(UsageCallback("p", "openai", "m"))
            await model.ainvoke("test")
            with usage_scope("memory_extract", background=True):
                await model.ainvoke("test")
            cb = UsageCallback("p", "openai", "m")
            ident = uuid.uuid4()
            cb.on_chat_model_start(None, None, run_id=ident)
            cb.on_llm_error(RuntimeError(), run_id=ident)
        finally:
            current_usage.reset(token)
        replay = collector.pending_batch()
        assert await collector.flush_once() == 3
        for row in replay:
            collector.enqueue(json.loads(row[3]), row[1])
        assert await collector.flush_once() == 3
        async with factory() as db:
            assert len((await db.scalars(select(UsageCall))).all()) == 3

        async def session():
            async with factory() as db:
                yield db

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = session
        actor_token = current_actor.set(Actor(uuid.uuid4(), "admin", True, False, 1))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                summary = await client.get("/admin/usage/summary")
                assert summary.status_code == 200, summary.text
                data = summary.json()
                assert (
                    data["totals"]["total_tokens"] == 30
                    and data["totals"]["calls"] == 3
                    and data["totals"]["operations"] == 1
                )
                assert data["totals"]["unknown_calls"] == 1 and data["totals"]["completeness"] == 2 / 3
                assert data["trend"][0]["total_tokens"] == 30
                groups = (await client.get("/admin/usage/groups", params={"dimension": "action"})).json()
                assert sum(r["total_tokens"] or 0 for r in groups["items"]) == 30
                filtered = (await client.get("/admin/usage/calls", params={"action": "memory_extract"})).json()
                assert filtered["total"] == 1 and filtered["items"][0]["trigger"] == "background"
                calls = (await client.get("/admin/usage/calls", params={"page_size": 1})).json()
                assert calls["total"] == 3 and len(calls["items"]) == 1
                op = (await client.get("/admin/usage/operations/" + calls["items"][0]["operation_id"])).json()
                assert op["total"] == 3 and op["total_tokens"] == 30
                exported = await client.get("/admin/usage/export")
                assert exported.status_code == 200
                import csv, io

                rows = list(csv.DictReader(io.StringIO(exported.text.lstrip("\ufeff"))))
                assert len(rows) == 3 and sum(int(r["总Token"] or 0) for r in rows) == 30
                assert (
                    await client.get("/admin/usage/summary", params={"start": "2026-01-01", "end": "2026-02-01"})
                ).status_code == 422
                assert (await client.get("/admin/usage/summary", params={"workspace_id": str(uuid.uuid4())})).json()[
                    "totals"
                ]["calls"] == 0
        finally:
            current_actor.reset(actor_token)
        # Outage leaves events durable, then replay succeeds once DB connectivity returns.
        cb = UsageCallback("p", "openai", "m")
        ident = uuid.uuid4()
        cb.on_chat_model_start(None, None, run_id=ident)
        saved = engine_module.async_session_factory

        def broken():
            raise ConnectionError("simulated outage")

        monkeypatch.setattr(engine_module, "async_session_factory", broken)
        with pytest.raises(ConnectionError):
            await collector.flush_once()
        assert len(records()) == 1
        monkeypatch.setattr(engine_module, "async_session_factory", saved)
        await collector.flush_once()
        # Restart recovery must not discard a completion that is still queued.
        cb.on_llm_end(SimpleNamespace(generations=[], llm_output={}), run_id=ident)
        from sqlalchemy import update

        async with factory() as db:
            await db.execute(update(UsageCall).where(UsageCall.id == ident).values(status="interrupted"))
            await db.commit()
        await collector.flush_once()
        async with factory() as db:
            assert (await db.get(UsageCall, ident)).status == "success"
    finally:
        await engine.dispose()
        async with base.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await base.dispose()


def test_embedding_batches_account_input_only(spool):
    from cortexa.usage.collector import AuditedEmbeddingClient
    class Client:
        def create(self, **kwargs):
            return {"model": "embed-model", "usage": {"prompt_tokens": 12, "total_tokens": 12}, "data": []}
    client = AuditedEmbeddingClient(Client(), "embedding-provider", "embed-model")
    with usage_scope("embedding_query", source="knowledge"):
        client.create(input=["secret"])
        client.create(input=["secret"])
    rows = records()
    assert len(rows) == 2 and sum(r["call"]["total_tokens"] for r in rows) == 24
    assert all(r["call"]["output_tokens"] == 0 and r["call"]["action"] == "embedding_query" for r in rows)
    assert "secret" not in json.dumps(rows)


def test_unknown_fields_do_not_become_zero_and_csv_formula_is_escaped():
    from cortexa.usage.api import csv_cell
    assert csv_cell(None) == ""
    assert csv_cell("=SUM(A1)") == "'=SUM(A1)"
    assert csv_cell("  +1+2").startswith("'")
    result = normalize_usage(SimpleNamespace(response_metadata={"usage": {"total_tokens": 19}}))
    assert result["input_tokens"] is None and result["output_tokens"] is None and result["total_tokens"] == 19
    assert result["usage_status"] == "partial"
