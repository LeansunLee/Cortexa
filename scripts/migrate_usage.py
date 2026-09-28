"""Create only the two user-approved model usage tables; safe to rerun."""

import asyncio

from cortexa.db.engine import Base, engine
from cortexa.usage.models import UsageCall, UsageOperation


async def migrate():
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: Base.metadata.create_all(
                sync, tables=[UsageOperation.__table__, UsageCall.__table__], checkfirst=True
            )
        )
    print("Usage migration complete: two additive tables.")


if __name__ == "__main__":
    asyncio.run(migrate())
