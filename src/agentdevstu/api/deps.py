"""FastAPI dependency injection helpers."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.db.engine import get_db_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db_session():
        yield session


async def get_current_workspace(
    x_workspace_id: str | None = Header(None, alias="X-Workspace-Id"),
) -> str | None:
    """Optional workspace header — returns UUID string or None."""
    return x_workspace_id
