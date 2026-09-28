"""Add only the four Work tables. Safe to rerun; no existing table alterations."""

import asyncio

from cortexa.db import meetings, models  # noqa: F401
from cortexa.db.engine import Base, engine
from cortexa.security import models as identity  # noqa: F401
from cortexa.work.models import Work, WorkActivity, WorkCandidate, WorkDeliverable


async def migrate():
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=[Work.__table__, WorkCandidate.__table__, WorkDeliverable.__table__, WorkActivity.__table__],
                checkfirst=True,
            )
        )
    print("Work migration complete: four additive tables.")


if __name__ == "__main__":
    asyncio.run(migrate())
