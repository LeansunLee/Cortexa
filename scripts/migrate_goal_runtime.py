"""Explicit additive migration, approved in GOAL_RUNTIME_DB_PROPOSAL_20260923.md.

Default is read-only preflight; --apply performs the transaction. Physical rollback
is deliberately only a callable for isolated tests, not a production CLI command.
"""

import argparse
import asyncio
import re

from sqlalchemy import inspect, text

from cortexa.db.engine import engine
from cortexa.runtime.models import RuntimeGoal
from cortexa.security import models as identity  # noqa: F401

POLICY_CHECK = "runtime_policy IS NULL OR jsonb_typeof(runtime_policy) = 'object'"
POLICY_NAME = "ck_workspace_runtime_policy"
TABLE = RuntimeGoal.__table__


def _normalized(value):
    # PostgreSQL rewrites simple CHECKs; compare the canonical database form below.
    return re.sub(r"\s+", " ", str(value)).strip()


def inspect_schema(conn):
    i = inspect(conn)
    required = {"t_workspaces", "t_users", "t_conversations", "t_conversation_messages", "t_agents"}
    if not required <= set(i.get_table_names()):
        raise RuntimeError("Goal migration prerequisites missing")
    uniques = i.get_unique_constraints("t_agents")
    if not any(c["column_names"] == ["workspace_id", "id"] for c in uniques):
        raise RuntimeError("Expected Agent workspace/id unique constraint missing")
    columns = {c["name"]: c for c in i.get_columns("t_workspaces")}
    has_policy = "runtime_policy" in columns
    has_goal = i.has_table(TABLE.name)
    if has_policy != has_goal:
        raise RuntimeError("Partial Goal schema; refusing automatic repair")
    checks = {c["name"]: c["sqltext"] for c in i.get_check_constraints("t_workspaces")}
    if not has_goal:
        if POLICY_NAME in checks:
            raise RuntimeError("Policy constraint exists without column")
        return {"version": "goal-runtime-v1", "installed": False}
    policy = columns["runtime_policy"]
    if str(policy["type"]) != "JSONB" or not policy["nullable"] or policy["default"] is not None:
        raise RuntimeError("Unexpected Workspace runtime_policy definition")
    # Compare reflected definitions without creating objects in read-only preflight.
    actual_columns = i.get_columns(TABLE.name)
    if {c["name"] for c in actual_columns} != set(TABLE.c.keys()):
        raise RuntimeError("Unexpected Goal columns")
    for c in actual_columns:
        expected = TABLE.c[c["name"]]
        if (
            str(c["type"].compile(dialect=conn.dialect)) != str(expected.type.compile(dialect=conn.dialect))
            or c["nullable"] != expected.nullable
        ):
            raise RuntimeError("Unexpected Goal column type/nullability: " + c["name"])
        default = c["default"]
        expected_default = {
            "status": "'RUNNING'::character varying",
            "revision": "1",
            "state": "'{}'::jsonb",
            "artifacts": "'{}'::jsonb",
            "created_at": "now()",
            "updated_at": "now()",
        }.get(c["name"])
        if default != expected_default:
            raise RuntimeError("Unexpected Goal column default: " + c["name"])
    expected_checks = {
        "ck_runtime_goal_key": "(length(TRIM(BOTH FROM idempotency_key)) > 0)",
        "ck_runtime_goal_status": (
            "((status)::text = ANY ((ARRAY['RUNNING'::character varying, "
            "'COMPLETE'::character varying, 'BLOCKED'::character varying, "
            "'WAITING'::character varying, 'FAILED'::character varying])::text[]))"
        ),
        "ck_runtime_goal_revision": "(revision > 0)",
        "ck_runtime_goal_state": "(jsonb_typeof(state) = 'object'::text)",
        "ck_runtime_goal_artifacts": "(jsonb_typeof(artifacts) = 'object'::text)",
    }
    actual_checks = {c["name"]: c["sqltext"] for c in i.get_check_constraints(TABLE.name)}

    # Inspector strips the outer parentheses on some PG versions.
    def norm_check(v):
        return re.sub(r"[\s()]", "", v).lower()

    if {k: norm_check(v) for k, v in actual_checks.items()} != {k: norm_check(v) for k, v in expected_checks.items()}:
        raise RuntimeError("Unexpected Goal CHECK constraints")
    if norm_check(checks.get(POLICY_NAME, "")) != norm_check(
        "((runtime_policy IS NULL) OR (jsonb_typeof(runtime_policy) = 'object'::text))"
    ):
        raise RuntimeError("Unexpected Workspace policy CHECK")
    if i.get_pk_constraint(TABLE.name)["constrained_columns"] != ["id"]:
        raise RuntimeError("Unexpected Goal primary key")
    unique = i.get_unique_constraints(TABLE.name)
    if (
        len(unique) != 1
        or unique[0]["name"] != "uq_runtime_goal_request"
        or unique[0]["column_names"] != ["workspace_id", "owner_user_id", "idempotency_key"]
    ):
        raise RuntimeError("Unexpected Goal idempotency constraint")
    actual_fk = {
        (
            tuple(f["constrained_columns"]),
            f["referred_table"],
            tuple(f["referred_columns"]),
            f["options"].get("ondelete"),
        )
        for f in i.get_foreign_keys(TABLE.name)
    }
    expected_fk = {
        (
            tuple(e.parent.name for e in f.elements),
            f.referred_table.name,
            tuple(e.column.name for e in f.elements),
            f.ondelete,
        )
        for f in TABLE.foreign_key_constraints
    }
    if actual_fk != expected_fk:
        raise RuntimeError("Unexpected Goal foreign keys")
    indexes = [x for x in i.get_indexes(TABLE.name) if not x.get("duplicates_constraint")]
    if (
        len(indexes) != 1
        or indexes[0]["name"] != "ix_runtime_goal_conversation"
        or indexes[0]["unique"]
        or indexes[0]["column_names"] != ["workspace_id", "owner_user_id", "conversation_id", "updated_at", "id"]
    ):
        raise RuntimeError("Unexpected Goal query index")
    return {"version": "goal-runtime-v1", "installed": True}


async def migrate(db_engine, *, apply=False):
    async with db_engine.begin() as conn:
        await conn.execute(text("SET LOCAL lock_timeout = '3s'"))
        await conn.execute(text("SET LOCAL statement_timeout = '30s'"))
        pre = await conn.run_sync(inspect_schema)
        if pre["installed"] or not apply:
            return {**pre, "changed": False}
        await conn.execute(text("ALTER TABLE t_workspaces ADD COLUMN runtime_policy JSONB"))
        await conn.execute(text(f"ALTER TABLE t_workspaces ADD CONSTRAINT {POLICY_NAME} CHECK ({POLICY_CHECK})"))
        await conn.run_sync(lambda c: TABLE.create(c, checkfirst=False))
        result = await conn.run_sync(inspect_schema)
        return {**result, "changed": True}


async def rollback_empty_test_schema(conn):
    schema = await conn.scalar(text("SELECT current_schema()"))
    if not schema.startswith("goal_test_"):
        raise RuntimeError("Physical rollback allowed only in disposable goal_test_ schemas")
    if await conn.scalar(text("SELECT count(*) FROM t_runtime_goals")):
        raise RuntimeError("Refusing to drop nonempty Goal checkpoints")
    await conn.execute(text("DROP TABLE t_runtime_goals"))
    await conn.execute(text(f"ALTER TABLE t_workspaces DROP CONSTRAINT {POLICY_NAME}"))
    await conn.execute(text("ALTER TABLE t_workspaces DROP COLUMN runtime_policy"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(migrate(engine, apply=args.apply)))
