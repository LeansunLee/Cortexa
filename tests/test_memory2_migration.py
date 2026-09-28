"""Upgrade/rollback rehearsal in a disposable schema on the existing development database."""

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path
import pytest
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from cortexa.db.engine import Base

spec = importlib.util.spec_from_file_location(
    "memory_migration", Path(__file__).parents[1] / "scripts/migrate_memory_2.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.mark.skipif(not os.getenv("MEMORY_TEST_DATABASE_URL"), reason="PostgreSQL URL required")
def test_upgrade_idempotency_and_rollback(tmp_path):
    asyncio.run(rehearsal(tmp_path))


async def rehearsal(tmp):
    url = os.environ["MEMORY_TEST_DATABASE_URL"]
    schema = "memory_migration_" + uuid.uuid4().hex
    root = create_async_engine(url)
    async with root.begin() as c:
        await c.execute(text("CREATE SCHEMA " + schema))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
            for table in reversed(migration.TABLES):
                await c.execute(text("DROP TABLE " + table.name))
            await c.execute(text("DROP TABLE t_memories"))
            # Explicit Memory 1.x contract; no dependency on mutable live table/data.
            await c.execute(
                text("""CREATE TABLE t_memories (
                id uuid PRIMARY KEY, workspace_id uuid NOT NULL REFERENCES t_workspaces(id),
                agent_id uuid REFERENCES t_agents(id) ON DELETE SET NULL,
                owner_user_id uuid REFERENCES t_users(id), type varchar(20) NOT NULL,
                content text NOT NULL, source_type varchar(50), source_id uuid,
                importance double precision NOT NULL DEFAULT .5, confidence double precision NOT NULL DEFAULT .5,
                status varchar(20) NOT NULL DEFAULT 'active', metadata_json json NOT NULL DEFAULT '{}',
                embedding json, expires_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(), access_count integer NOT NULL DEFAULT 0,
                last_accessed_at timestamptz)""")
            )
            ws, ag, keep, dirty = [uuid.uuid4() for _ in range(4)]
            # ORM table inserts populate Python defaults without requiring an Actor.
            from cortexa.db.models import Workspace, Agent

            await c.execute(Workspace.__table__.insert().values(id=ws, name="migration"))
            await c.execute(Agent.__table__.insert().values(id=ag, workspace_id=ws, name="migration", status="active"))
            await c.execute(
                text(
                    "INSERT INTO t_memories(id,workspace_id,agent_id,type,content) VALUES (:keep,:ws,:ag,'semantic','历史认知'),(:dirty,:ws,NULL,'focus','开发脏数据')"
                ),
                dict(keep=keep, dirty=dirty, ws=ws, ag=ag),
            )
        backup = tmp / "backup.json"
        export = tmp / "export.json"
        pre = await migration.migrate(engine)
        assert pre["null_agent_to_delete"] == 1 and pre["apply"] is False
        result = await migration.migrate(engine, apply=True, backup=backup)
        assert result["retained"] == 1 and backup.stat().st_mode & 0o777 == 0o600
        async with engine.begin() as c:
            row = (await c.execute(text("SELECT * FROM t_memories"))).mappings().one()
            assert row["id"] == keep and row["agent_id"] == ag
            assert row["valid_from"] is None and row["source_mode"] is None and row["memory_kind"] is None
            assert row["metadata_json"]["legacy_uncalibrated"]
        second = await migration.migrate(engine, apply=True, backup=backup)
        assert second["new_columns"] == [] and second["retained"] == 1
        result = await migration.rollback(engine, backup, export)
        assert result["restored"] == 2
        async with engine.begin() as c:
            assert await c.scalar(text("SELECT count(*) FROM t_memories")) == 2
            columns = await c.run_sync(lambda conn: {x["name"] for x in inspect(conn).get_columns("t_memories")})
            assert "memory_kind" not in columns
            assert not await c.run_sync(lambda conn: inspect(conn).has_table("t_memory_evidences"))
    finally:
        await engine.dispose()
        async with root.begin() as c:
            await c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        await root.dispose()
