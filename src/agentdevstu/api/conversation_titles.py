"""Give untitled conversations a short title from their first user turn."""

import re

from sqlalchemy import exists, func, or_, select, update

from agentdevstu.db.models import Conversation, ConversationMessage


def title_from_first_message(content: str, *, max_length: int = 40) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    without_mentions = re.sub(r"(?<!\S)@[^\s@]+", " ", text)
    title = re.sub(r"\s+", " ", without_mentions).strip(" \t,，。.!！?？:：;；") or text
    if len(title) <= max_length:
        return title
    return title[: max_length - 1].rstrip() + "…"


async def assign_first_message_title(db, conversation_id, content: str) -> str | None:
    """Set a title only if there is no explicit title or earlier user message."""
    title = title_from_first_message(content)
    if not title:
        return None
    prior_user_message = exists(
        select(ConversationMessage.id).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.role == "user",
        )
    )
    result = await db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            or_(Conversation.title.is_(None), func.btrim(Conversation.title) == ""),
            ~prior_user_message,
        )
        .values(title=title)
        .returning(Conversation.title)
    )
    scalar = getattr(result, "scalar", None)
    return scalar() if scalar else None
