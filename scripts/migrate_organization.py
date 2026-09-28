"""Add the two organization tables only. Rerunnable; never alters existing tables."""

import asyncio

from cortexa.db import models  # noqa: F401
from cortexa.db.engine import Base, engine
from cortexa.organization.models import MemberProfile, OrgUnit
from cortexa.security import models as identity  # noqa: F401


async def migrate():
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: Base.metadata.create_all(
                sync, tables=[OrgUnit.__table__, MemberProfile.__table__], checkfirst=True
            )
        )
    await engine.dispose()
    print("Organization migration complete: two additive tables.")


if __name__ == "__main__":
    asyncio.run(migrate())
