"""Explicit Memory 2 migration. Defaults to read-only preflight; never runs on startup.

DATABASE_URL must be explicitly set. --apply requires --backup; --rollback restores
that snapshot and exports any post-upgrade rows before restoring the old schema.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import AddConstraint, CreateIndex
from sqlalchemy.dialects.postgresql import insert
from cortexa.db.models import Memory
from cortexa.memory.models import MemoryEvidence, MemoryRelation, MemoryEvent, MemoryIssue
from cortexa.memory.policy import terms, digest, normalize

TABLES = [MemoryEvidence.__table__, MemoryRelation.__table__, MemoryEvent.__table__, MemoryIssue.__table__]
NEW_DEFAULTS = {"risk_level": "'unknown'", "has_conflict": "false", "revision": "1", "search_terms": "'[]'::jsonb"}


def write_backup(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(data, file, ensure_ascii=False, default=str)


async def snapshot(conn):
    schema = await conn.scalar(text("SELECT current_schema()"))
    quote = conn.dialect.identifier_preparer.quote
    qualified = quote(schema) + "." + quote("t_memories")
    columns = (
        (
            await conn.execute(
                text("""SELECT a.attname AS name,format_type(a.atttypid,a.atttypmod) AS type,
        a.attnotnull AS notnull,pg_get_expr(d.adbin,d.adrelid) AS default
        FROM pg_attribute a LEFT JOIN pg_attrdef d ON a.attrelid=d.adrelid AND a.attnum=d.adnum
        WHERE a.attrelid=to_regclass(:table) AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum"""),
                {"table": qualified},
            )
        )
        .mappings()
        .all()
    )
    constraints = (
        (
            await conn.execute(
                text(
                    "SELECT conname AS name,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid=to_regclass(:table)"
                ),
                {"table": qualified},
            )
        )
        .mappings()
        .all()
    )
    indexes = (
        (
            await conn.execute(
                text(
                    "SELECT indexname AS name,indexdef AS definition FROM pg_indexes WHERE schemaname=:schema AND tablename=:table"
                ),
                {"schema": schema, "table": "t_memories"},
            )
        )
        .mappings()
        .all()
    )
    rows = (await conn.execute(text("SELECT * FROM t_memories"))).mappings().all()
    unique = await conn.run_sync(lambda c: inspect(c).get_unique_constraints("t_agents"))
    children = {}
    for table in TABLES:
        if await conn.run_sync(lambda c, t=table: inspect(c).has_table(t.name)):
            children[table.name] = [dict(r) for r in (await conn.execute(table.select())).mappings()]
    return {
        "children": children,
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema": schema,
        "columns": [dict(x) for x in columns],
        "constraints": [dict(x) for x in constraints],
        "indexes": [dict(x) for x in indexes],
        "rows": [dict(x) for x in rows],
        "agent_unique_existed": any(x["name"] == "uq_agent_workspace_id" for x in unique),
    }


async def preflight(conn):
    present = await conn.run_sync(lambda c: inspect(c).has_table("t_memories"))
    if not present:
        raise RuntimeError("t_memories does not exist; initialize the application schema explicitly first")
    count = await conn.scalar(text("SELECT count(*) FROM t_memories"))
    nulls = await conn.scalar(text("SELECT count(*) FROM t_memories WHERE agent_id IS NULL"))
    broken = await conn.scalar(
        text("""SELECT count(*) FROM t_memories m LEFT JOIN t_agents a ON a.id=m.agent_id
        WHERE m.agent_id IS NOT NULL AND (a.id IS NULL OR a.workspace_id <> m.workspace_id)""")
    )
    quality = await conn.scalar(
        text(
            "SELECT count(*) FROM t_memories WHERE NOT (importance>=0 AND importance<=1 AND confidence>=0 AND confidence<=1) OR status NOT IN ('candidate','active','superseded','expired','retracted','archived','rejected') OR type NOT IN ('semantic','episodic','focus')"
        )
    )
    if broken or quality:
        raise RuntimeError(
            f"Preflight blocked: invalid Agent scope={broken}, invalid quality/status/category={quality}; no data changed"
        )
    return {"total": count, "null_agent_to_delete": nulls}


async def migrate(engine, *, apply=False, backup=None):
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL lock_timeout='10s'"))
        await conn.execute(text("SELECT pg_advisory_xact_lock(2026091902)"))
        info = await preflight(conn)
        names = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("t_memories")})
        missing = [c for c in Memory.__table__.columns if c.name not in names]
        info["new_columns"] = [c.name for c in missing]
        info["apply"] = apply
        if not apply:
            return info
        if not backup:
            raise RuntimeError("--apply requires a private backup path")
        if missing or info["null_agent_to_delete"]:
            write_backup(backup, await snapshot(conn))
        elif not Path(backup).exists():
            write_backup(backup, await snapshot(conn))
        for column in missing:
            default = NEW_DEFAULTS.get(column.name)
            statement = f'ALTER TABLE t_memories ADD COLUMN "{column.name}" {column.type.compile(dialect=conn.dialect)}'
            if default:
                statement += " DEFAULT " + default
            await conn.execute(text(statement))
        await conn.execute(text("DELETE FROM t_memories WHERE agent_id IS NULL"))
        await conn.execute(text("ALTER TABLE t_memories ALTER COLUMN agent_id SET NOT NULL"))
        for name, default in NEW_DEFAULTS.items():
            await conn.execute(text(f'UPDATE t_memories SET "{name}"={default} WHERE "{name}" IS NULL'))
            await conn.execute(text(f'ALTER TABLE t_memories ALTER COLUMN "{name}" SET NOT NULL'))
            await conn.execute(text(f'ALTER TABLE t_memories ALTER COLUMN "{name}" SET DEFAULT {default}'))
        uniques = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_unique_constraints("t_agents")})
        if "uq_agent_workspace_id" not in uniques:
            await conn.execute(
                text("ALTER TABLE t_agents ADD CONSTRAINT uq_agent_workspace_id UNIQUE (workspace_id,id)")
            )
        fks = await conn.run_sync(lambda c: inspect(c).get_foreign_keys("t_memories"))
        for fk in fks:
            if fk["constrained_columns"] == ["agent_id"]:
                await conn.execute(
                    text("ALTER TABLE t_memories DROP CONSTRAINT " + conn.dialect.identifier_preparer.quote(fk["name"]))
                )
        # Named constraints can be rerun; unnamed source-user FKs are checked by columns.
        existing = (
            (await conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid='t_memories'::regclass")))
            .scalars()
            .all()
        )
        existing_fks = {tuple(fk["constrained_columns"]) for fk in fks if fk["constrained_columns"] != ["agent_id"]}
        for constraint in Memory.__table__.constraints:
            if constraint.__class__.__name__ == "PrimaryKeyConstraint":
                continue
            if constraint.name and constraint.name in existing:
                continue
            if (
                constraint.__class__.__name__ == "ForeignKeyConstraint"
                and not constraint.name
                and tuple(c.name for c in constraint.columns) in existing_fks
            ):
                continue
            await conn.execute(AddConstraint(constraint, isolate_from_table=False))
        for table in TABLES:
            await conn.run_sync(lambda sync, t=table: t.create(sync, checkfirst=True))
        indexes = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_indexes("t_memories")})
        for index in Memory.__table__.indexes:
            if index.name not in indexes:
                await conn.execute(CreateIndex(index))
        if missing:
            rows = (await conn.execute(Memory.__table__.select())).mappings().all()
            for row in rows:
                meta = {
                    **(row["metadata_json"] or {}),
                    "legacy_import": True,
                    "legacy_uncalibrated": True,
                    "memory2_migrated": True,
                }
                await conn.execute(
                    Memory.__table__.update()
                    .where(Memory.id == row["id"])
                    .values(
                        metadata_json=meta,
                        normalized_hash=digest(normalize(row["content"])),
                        search_terms=terms(row["content"]),
                    )
                )
                if row["source_type"] and row["source_id"]:
                    key = digest(["legacy", row["source_type"], str(row["source_id"])])
                    await conn.execute(
                        insert(MemoryEvidence.__table__)
                        .values(
                            id=__import__("uuid").uuid4(),
                            workspace_id=row["workspace_id"],
                            agent_id=row["agent_id"],
                            memory_id=row["id"],
                            source_type=row["source_type"],
                            source_id=str(row["source_id"]),
                            source_status="unverified",
                            stance="supports",
                            evidence_key=key,
                            root_keys=[],
                            metadata_json={"legacy_reference": True},
                        )
                        .on_conflict_do_nothing()
                    )
        info["retained"] = await conn.scalar(text("SELECT count(*) FROM t_memories"))
        return info


async def rollback(engine, backup, export):
    data = json.loads(Path(backup).read_text())
    async with engine.begin() as conn:
        schema = await conn.scalar(text("SELECT current_schema()"))
        if schema != data["schema"]:
            raise RuntimeError("Backup schema does not match current schema")
        write_backup(export, await snapshot(conn))
        # No CASCADE: unexpected external dependencies must stop rollback rather than be destroyed.
        for table in reversed(TABLES):
            await conn.execute(text("DROP TABLE IF EXISTS " + table.name))
        await conn.execute(text("DROP TABLE t_memories"))
        quote = conn.dialect.identifier_preparer.quote
        definitions = []
        for c in data["columns"]:
            definitions.append(
                quote(c["name"])
                + " "
                + c["type"]
                + (" DEFAULT " + c["default"] if c["default"] else "")
                + (" NOT NULL" if c["notnull"] else "")
            )
        definitions.extend("CONSTRAINT " + quote(c["name"]) + " " + c["definition"] for c in data["constraints"])
        await conn.execute(text("CREATE TABLE t_memories (" + ",".join(definitions) + ")"))
        if data["rows"]:
            await conn.execute(
                text(
                    "INSERT INTO t_memories SELECT * FROM json_populate_recordset(NULL::t_memories,CAST(:rows AS json))"
                ),
                {"rows": json.dumps(data["rows"])},
            )
        existing = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_indexes("t_memories")})
        pk = await conn.run_sync(lambda c: inspect(c).get_pk_constraint("t_memories")["name"])
        for index in data["indexes"]:
            if index["name"] not in existing and index["name"] != pk:
                await conn.execute(text(index["definition"]))
        if not data["agent_unique_existed"]:
            await conn.execute(text("ALTER TABLE t_agents DROP CONSTRAINT IF EXISTS uq_agent_workspace_id"))
    return {"restored": len(data["rows"]), "post_upgrade_export": str(export)}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--export")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("Set DATABASE_URL explicitly (no default database is permitted)")
    engine = create_async_engine(url, echo=False)
    try:
        if args.rollback:
            if not args.backup or not args.export:
                parser.error("--rollback requires --backup and --export")
            result = await rollback(engine, args.backup, args.export)
        else:
            result = await migrate(engine, apply=args.apply, backup=args.backup)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
