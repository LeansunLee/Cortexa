"""Give untitled conversations a short title from their first user turn.

The instant truncated title acts as a placeholder; a background task then asks
the model for a concise name and overwrites the placeholder unless the user
renamed the conversation meanwhile (``metadata_json.title_manual``).
"""

import asyncio
import logging
import re
import uuid

from sqlalchemy import exists, func, or_, select, update

from cortexa.config.llm_providers import create_llm_for
from cortexa.db.engine import async_session_factory
from cortexa.db.models import Agent, Conversation, ConversationMessage

logger = logging.getLogger(__name__)

TITLE_TIMEOUT_SECONDS = 12
GENERATION_DELAY_SECONDS = 2

TITLE_SYSTEM_PROMPT = (
    "你是对话命名助手。根据用户与智能体第一轮对话的文本，起一个简洁的对话标题。\n"
    "规则：不超过 20 个字；保留关键对象（车型、指标、业务域、动作等）；"
    "跟随用户文本的主要语言；只输出标题本身，不要引号、句号、前缀或任何解释。"
)

_tasks: set[asyncio.Task] = set()
_scheduled: set[uuid.UUID] = set()


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


def clean_generated_title(text: str, *, max_length: int = 40) -> str:
    title = re.sub(r"\s+", " ", (text or "").strip())
    title = title.strip("\"'`「」『』“”‘’").strip(" \t,，。.!！?？:：;；")
    if not title:
        return ""
    if len(title) <= max_length:
        return title
    return title[: max_length - 1].rstrip() + "…"


async def _request_title(content: str, agent) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    model = create_llm_for(agent, "title")
    if hasattr(model, "max_retries"):
        model = model.model_copy(update={"max_retries": 0})
    response = await asyncio.wait_for(
        model.ainvoke(
            [
                SystemMessage(content=TITLE_SYSTEM_PROMPT),
                HumanMessage(content=f"# 用户第一条消息\n{content[:600]}"),
            ]
        ),
        TITLE_TIMEOUT_SECONDS,
    )
    text = response.content if isinstance(response.content, str) else "".join(
        str(part) for part in (response.content or [])
    )
    return clean_generated_title(text)


async def overwrite_placeholder_title(db, conversation_id, title: str) -> None:
    """Overwrite the auto title; a manual rename wins, a deleted row matches none."""
    await db.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.metadata_json["title_manual"].as_string().is_(None),
        )
        .values(title=title)
    )


async def generate_conversation_title(conversation_id: uuid.UUID) -> None:
    """Refine the placeholder title into a concise model-generated name, once."""
    await asyncio.sleep(GENERATION_DELAY_SECONDS)
    try:
        async with async_session_factory() as db:
            conv = await db.get(Conversation, conversation_id)
            if conv is None:
                return
            content = await db.scalar(
                select(ConversationMessage.content)
                .where(
                    ConversationMessage.conversation_id == conversation_id,
                    ConversationMessage.role == "user",
                )
                .order_by(ConversationMessage.created_at)
                .limit(1)
            )
            if not content:
                return
            agent = await db.get(Agent, conv.agent_id) if conv.agent_id else None
            title = await _request_title(content, agent)
            if not title:
                return
            await overwrite_placeholder_title(db, conversation_id, title)
            await db.commit()
    except Exception:
        logger.warning(
            "LLM title generation failed for conversation %s", conversation_id, exc_info=True
        )


def schedule_llm_title(conversation_id: uuid.UUID) -> None:
    """Start the background title refinement once per conversation."""
    if conversation_id in _scheduled:
        return
    _scheduled.add(conversation_id)
    task = asyncio.create_task(generate_conversation_title(conversation_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    task.add_done_callback(lambda _task: _scheduled.discard(conversation_id))
