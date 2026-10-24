"""Background sweeper: auto-continue recommended single-choice questions past the deadline.

Runs one scan per minute. Only questions raised with a valid recommendation, single
selection and a known non-proxy engine are eligible; the answer goes through the exact
same pipeline as a user click (apply_answer), executed under the conversation owner's
actor context, and the conversation receives an explicit "auto-continued" notice.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from cortexa.conversation.questions import auto_answer_timeout

logger = logging.getLogger(__name__)
SCAN_INTERVAL = 60
MAX_ATTEMPTS = 3


def eligible_for_auto(public, now=None) -> bool:
    """Pure check: pending + single-choice + valid recommendation + past deadline."""
    if not isinstance(public, dict) or public.get("status") != "pending":
        return False
    if public.get("multi_select") or not public.get("options"):
        return False
    index = public.get("recommended_option_index")
    if not isinstance(index, int) or index < 0 or index >= len(public["options"]):
        return False
    engine = public.get("engine")
    if engine not in {"llm", "goal"}:
        return False
    if public.get("auto_fail_count", 0) >= MAX_ATTEMPTS:
        return False
    raised = public.get("raised_at")
    timeout = auto_answer_timeout()
    if timeout <= 0 or not raised:
        return False
    try:
        raised_at = datetime.fromisoformat(raised)
    except ValueError:
        return False
    if raised_at.tzinfo is None:
        raised_at = raised_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - raised_at).total_seconds() >= timeout


async def _owner_actor(user_id, workspace_id):
    from cortexa.security.access import hydrate_actor
    from cortexa.security.models import User

    from cortexa.db.engine import async_session_factory

    async with async_session_factory() as db:
        user = await db.get(User, user_id)
    if user is None or user.status != "active":
        return None
    actor = await hydrate_actor(user)
    if workspace_id not in actor.memberships:
        return None
    actor.workspace_id = workspace_id
    actor.runtime = True
    return actor


async def _record_failure(conv_id, question_id):
    from cortexa.db.engine import async_session_factory
    from cortexa.db.models import Conversation
    from sqlalchemy import select

    try:
        async with async_session_factory() as db:
            conv = await db.scalar(
                select(Conversation).where(Conversation.id == conv_id).with_for_update()
            )
            if conv is None:
                return
            meta = dict(conv.metadata_json or {})
            public = meta.get("pending_question") or {}
            if public.get("id") == str(question_id) and public.get("status") == "pending":
                meta["pending_question"] = {**public, "auto_fail_count": public.get("auto_fail_count", 0) + 1}
                conv.metadata_json = meta
                await db.commit()
    except Exception:
        logger.warning("auto-continue failure bookkeeping failed", exc_info=True)


async def process(conv_id: uuid.UUID, question_id: uuid.UUID, user_id, workspace_id):
    from cortexa.security.access import current_actor

    from cortexa.db.engine import async_session_factory
    from cortexa.db.models import Conversation
    from sqlalchemy import select

    from cortexa.api.user_questions import apply_answer

    # Recheck under lock: the user may have answered since the scan.
    async with async_session_factory() as db:
        conv = await db.scalar(select(Conversation).where(Conversation.id == conv_id))
        if conv is None:
            return
        public = (conv.metadata_json or {}).get("pending_question") or {}
        if public.get("id") != str(question_id) or not eligible_for_auto(public):
            return
        index = public["recommended_option_index"]
    actor = await _owner_actor(user_id, workspace_id)
    if actor is None:
        logger.info("auto-continue skipped: owner not active or not a member (conv=%s)", conv_id)
        return
    token = current_actor.set(actor)
    try:
        response = await apply_answer(conv_id, question_id, [index], "", auto=True)
        # Draining runs the shared worker to completion, mirroring an HTTP consumer.
        async for _ in response.body_iterator:
            pass
        logger.info("auto-continued question %s with recommended option %d", question_id, index)
    except Exception:
        logger.warning("auto-continue failed for question %s", question_id, exc_info=True)
        await _record_failure(conv_id, question_id)
    finally:
        current_actor.reset(token)


async def sweep_once() -> int:
    from sqlalchemy import cast, select
    from sqlalchemy.dialects.postgresql import JSONB

    from cortexa.db.engine import async_session_factory
    from cortexa.db.models import Conversation

    if auto_answer_timeout() <= 0:
        return 0
    now = datetime.now(timezone.utc)
    launched = 0
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                select(Conversation).where(cast(Conversation.metadata_json, JSONB).has_key("pending_question"))
            )
        ).scalars()
        for conv in rows:
            public = (conv.metadata_json or {}).get("pending_question") or {}
            if not eligible_for_auto(public, now):
                continue
            question_id = uuid.UUID(public["id"])
            asyncio.create_task(process(conv.id, question_id, conv.owner_user_id, conv.workspace_id))
            launched += 1
    return launched


async def run():
    logger.info("question auto-continue sweeper started (interval=%ss)", SCAN_INTERVAL)
    while True:
        try:
            await sweep_once()
        except Exception:
            logger.warning("question sweep round failed", exc_info=True)
        await asyncio.sleep(SCAN_INTERVAL)
