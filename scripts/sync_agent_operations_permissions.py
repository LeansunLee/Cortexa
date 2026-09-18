"""Update permission JSON only; never create or alter database tables."""
import asyncio
from sqlalchemy import select
from agentdevstu.config.settings import load_env

load_env()

from agentdevstu.db.engine import async_session_factory
from agentdevstu.security.models import Role


async def sync():
    async with async_session_factory() as db:
        roles = (await db.execute(select(Role))).scalars().all()
        changed = 0
        for role in roles:
            permissions = [p for p in role.permissions if p != 'agent.test']
            if role.builtin and role.code in ('space_admin', 'agent_developer') and 'agent.operate' not in permissions:
                permissions.append('agent.operate')
            if permissions != role.permissions:
                role.permissions = permissions
                changed += 1
        await db.commit()
        print(f'Updated {changed} roles; no schema changes.')


if __name__ == '__main__':
    asyncio.run(sync())
