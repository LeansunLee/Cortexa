"""Explicit, idempotent identity migration. Run only after a database backup.

  python scripts/migrate_identity.py --apply
  AGENTDEVSTU_BOOTSTRAP_PASSWORD=... python scripts/migrate_identity.py --bootstrap admin

No schema changes happen at application startup. Passwords are never printed by this script.
"""

import argparse
import asyncio
import os
from sqlalchemy import select, text
from dotenv import load_dotenv

load_dotenv()
from agentdevstu.db.engine import engine, async_session_factory, Base
from agentdevstu.db import models as m
from agentdevstu.security import models as sm
from agentdevstu.security.catalog import BUILTINS
from agentdevstu.security.passwords import hash_password

OWNED = ["t_conversations", "t_memories", "t_meetings", "t_tasks", "t_agent_runs", "t_task_runs", "t_data_queries"]


async def migrate(app_role=None):
    tables = [
        t
        for t in Base.metadata.sorted_tables
        if t.name
        in {
            mapper.local_table.name
            for mapper in Base.registry.mappers
            if mapper.class_.__module__ == "agentdevstu.security.models"
        }
    ]
    async with engine.begin() as conn:
        await conn.execute(text("SELECT pg_advisory_xact_lock(260908001)"))
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
        for name in OWNED:
            await conn.execute(
                text(f"ALTER TABLE {name} ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES t_users(id)")
            )
            await conn.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{name}_owner_user_id ON {name}(owner_user_id)"))
        # Enforce same-workspace grants even outside the API. Membership deletion cascades grants.
        await conn.execute(
            text("""CREATE OR REPLACE FUNCTION check_agent_grant_workspace() RETURNS trigger AS $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM t_workspace_members m JOIN t_agents a ON a.workspace_id=m.workspace_id
                         WHERE m.id=NEW.member_id AND a.id=NEW.agent_id) THEN
            RAISE EXCEPTION 'Agent grant requires membership in its workspace' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        )
        await conn.execute(text("DROP TRIGGER IF EXISTS agent_grant_workspace ON t_agent_grants"))
        await conn.execute(
            text(
                "CREATE TRIGGER agent_grant_workspace BEFORE INSERT OR UPDATE ON t_agent_grants FOR EACH ROW EXECUTE FUNCTION check_agent_grant_workspace()"
            )
        )
        await conn.execute(
            text("""CREATE OR REPLACE FUNCTION revoke_moved_agent_grants() RETURNS trigger AS $$
        BEGIN
          IF OLD.workspace_id IS DISTINCT FROM NEW.workspace_id THEN
            DELETE FROM t_agent_grants WHERE agent_id=NEW.id;
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql""")
        )
        await conn.execute(text("DROP TRIGGER IF EXISTS agent_move_revoke ON t_agents"))
        await conn.execute(
            text(
                "CREATE TRIGGER agent_move_revoke AFTER UPDATE OF workspace_id ON t_agents FOR EACH ROW EXECUTE FUNCTION revoke_moved_agent_grants()"
            )
        )
        if app_role:
            import re

            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", app_role):
                raise ValueError("Invalid application database role")
            quote = engine.dialect.identifier_preparer.quote
            names = ", ".join(quote(t.name) for t in tables)
            await conn.execute(
                text(f"GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES ON {names} TO {quote(app_role)}")
            )
    async with async_session_factory() as db:
        for code, name, scope, permissions in BUILTINS:
            if not await db.scalar(select(sm.Role.id).where(sm.Role.code == code)):
                db.add(sm.Role(code=code, name=name, scope=scope, permissions=permissions, builtin=True))
        await db.commit()
    print("Identity migration complete: 11 identity tables; 7 ownership columns; grant constraints; builtin roles.")


async def bootstrap(username):
    password = os.environ.get("AGENTDEVSTU_BOOTSTRAP_PASSWORD")
    if not password:
        raise SystemExit("AGENTDEVSTU_BOOTSTRAP_PASSWORD is required")
    async with async_session_factory() as db:
        existing = await db.scalar(select(sm.User).where(sm.User.username == username))
        if existing:
            raise SystemExit("User already exists; refusing to overwrite credentials")
        user = sm.User(
            username=username,
            display_name="超级管理员",
            password_hash=hash_password(password),
            is_superadmin=True,
            must_change_password=True,
        )
        db.add(user)
        await db.flush()
        role = await db.scalar(select(sm.Role).where(sm.Role.code == "space_admin"))
        if role is None:
            raise SystemExit("Run --apply first")
        for ws in (await db.execute(select(m.Workspace))).scalars():
            member = sm.Membership(user_id=user.id, workspace_id=ws.id, all_agents=True)
            db.add(member)
            await db.flush()
            db.add(sm.MemberRole(member_id=member.id, role_id=role.id))
        db.add(
            sm.AuditLog(
                actor_id=user.id,
                action="bootstrap.superadmin",
                target=str(user.id),
                detail={"historical_data": "unowned_restricted"},
            )
        )
        await db.commit()
    print("Superadmin created. First login requires password change. Historical private data remains unassigned.")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--bootstrap")
    parser.add_argument("--app-role", help="Grant DML on new tables when migration runs as a DBA")
    args = parser.parse_args()
    if not args.apply and not args.bootstrap:
        parser.error("Choose --apply or --bootstrap")
    try:
        if args.apply:
            await migrate(args.app_role)
        if args.bootstrap:
            await bootstrap(args.bootstrap)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
