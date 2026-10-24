import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Annotated

from fastapi import HTTPException
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from cortexa.db.engine import async_session_factory
from cortexa.db.models import Conversation
from cortexa.runtime.artifacts import ROOT, ArtifactStore


class AskUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=2000)
    options: list[Annotated[str, StringConstraints(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=12
    )
    multi_select: bool = False
    allow_free_text: bool = True
    recommended_option_index: int | None = Field(default=None, ge=0, lt=12)
    recommendation_reason: str = Field(default="", max_length=500)


class UserQuestionPause(Exception):
    def __init__(self, question, context):
        self.question = question
        self.context = context
        super().__init__(question["question"])


answered_question = ContextVar("answered_question", default=None)
files = ArtifactStore(ROOT.parent / "user_questions")


def auto_answer_timeout() -> int:
    """Seconds before a recommended single-select question auto-continues; 0 disables."""
    import os

    try:
        return max(0, int(os.environ.get("QUESTION_AUTO_ANSWER_TIMEOUT", "3600")))
    except ValueError:
        return 3600


def question(raw, agent):
    parsed = AskUserInput.model_validate({k: v for k, v in raw.items() if k in AskUserInput.model_fields})
    values = parsed.model_dump()
    values["options"] = [value.strip() for value in values["options"] if value.strip()]
    if not values["options"]:
        values["allow_free_text"] = True
    # A recommendation is only meaningful for single-choice questions with options.
    if values.get("recommended_option_index") is not None and (
        values["multi_select"] or not values["options"] or values["recommended_option_index"] >= len(values["options"])
    ):
        values["recommended_option_index"] = None
        values["recommendation_reason"] = ""
    if values.get("recommended_option_index") is None:
        values.pop("recommendation_reason", None)
    timeout = auto_answer_timeout()
    return {
        "id": str(uuid.uuid4()),
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "status": "pending",
        "raised_at": datetime.now(timezone.utc).isoformat(),
        **({"auto_timeout_seconds": timeout} if values.get("recommended_option_index") is not None and timeout > 0 else {}),
        **values,
    }


def ask_user_tool():
    async def ask(
        question: str,
        options: list[str] | None = None,
        multi_select: bool = False,
        allow_free_text: bool = True,
        recommended_option_index: int | None = None,
        recommendation_reason: str = "",
    ):
        return {
            "user_question": AskUserInput(
                question=question,
                options=options or [],
                multi_select=multi_select,
                allow_free_text=allow_free_text,
                recommended_option_index=recommended_option_index,
                recommendation_reason=recommendation_reason,
            ).model_dump()
        }

    return StructuredTool.from_function(
        coroutine=ask,
        name="ask_user",
        args_schema=AskUserInput,
        description=(
            "需要用户作出选择、确认偏好、确定业务口径或补充关键信息时调用。提供问题与选项，暂停并等待用户回答；"
            "不得替用户选择。单选问题应在业务上评估选项并给出推荐：设置 recommended_option_index 为推荐项序号，"
            "并用 recommendation_reason 说明理由；推荐会在卡片上标注，用户长时间未选择时将按推荐继续。"
        ),
    )


async def save_question(conv_id, public, context, *, sessions=None):
    async with (sessions or async_session_factory)() as db:
        conv = await db.scalar(select(Conversation).where(Conversation.id == conv_id).with_for_update())
        if conv is None:
            raise HTTPException(404, "对话已删除或无权访问")
        if context.get("engine") and not public.get("engine"):
            public = {**public, "engine": context["engine"]}
        ref = files.write(public["id"], context)
        conv.metadata_json = {**(conv.metadata_json or {}), "pending_question": public, "question_context": ref}
        await db.commit()
    return public


def pause_after_tool(raw, agent, messages, response, results, call, *, remaining=5):
    """Checkpoint completed tools and close unstarted calls before asking a human."""
    from langchain_core.messages import ToolMessage

    from cortexa.runtime.loop import serialize_messages

    if isinstance(raw, dict) and raw.get("user_question"):
        public = question(raw["user_question"], agent)
        checkpoint = [*messages, response, *results]
        finished = {m.tool_call_id for m in results}
        checkpoint.extend(
            ToolMessage(content="未执行：等待用户回答。", tool_call_id=c["id"])
            for c in response.tool_calls
            if c["id"] not in finished
        )
        raise UserQuestionPause(
            public,
            {
                "engine": "llm",
                "agent_id": str(agent.id),
                "messages": serialize_messages(checkpoint),
                "remaining_iterations": remaining,
            },
        )


def answer_text(public, selected, text):
    if len(selected) != len(set(selected)) or any(i < 0 or i >= len(public["options"]) for i in selected):
        raise HTTPException(422, "选项无效，请刷新问题后重试")
    if not public["multi_select"] and len(selected) > 1:
        raise HTTPException(422, "此问题只能选择一项")
    text = text.strip()
    if text and not public["allow_free_text"]:
        raise HTTPException(422, "此问题不允许自由填写")
    if not selected and not text:
        raise HTTPException(422, "请选择一项或填写回答")
    return "\n".join([*[public["options"][i] for i in selected], *([text] if text else [])])


def proxy_context(agent, raw, body):
    """Only server-owned artifacts carry transport/session information."""
    session = raw.get("session_id")
    if not isinstance(session, str) or not session:
        raise ValueError("外部 Agent 提问但未返回可续接的会话标识")
    mapping = (agent.proxy_config or {}).get("request_mapping") or {}
    field = (agent.proxy_config or {}).get("answer_field") or next(
        (key for key, value in mapping.items() if value == "$.input"), None
    )
    if not field:
        text_fields = [key for key, value in body.items() if isinstance(value, str)]
        field = (
            text_fields[0]
            if len(text_fields) == 1
            else next((key for key in ("prompt", "input") if key in text_fields), None)
        )
    if not field:
        raise ValueError("请在代理配置中声明回答续接字段 answer_field")
    from cortexa.runtime.proxy import contract_signature

    return {
        "engine": "proxy",
        "agent_id": str(agent.id),
        "body": body,
        "session_id": session,
        "answer_field": field,
        "signature": contract_signature(agent),
    }


async def persist_pause(conv_id, pause, steps=None):
    from cortexa.db.models import ConversationMessage

    await save_question(conv_id, pause.question, pause.context)
    async with async_session_factory() as db:
        msg = ConversationMessage(
            conversation_id=conv_id,
            role="assistant",
            content=pause.question["question"],
            metadata_json={"user_question": pause.question, "steps": steps or []},
        )
        db.add(msg)
        await db.commit()
        return str(msg.id)


async def require_no_pending(conv_id, *, sessions=None):
    from cortexa.runtime.store import own_conversation

    async with (sessions or async_session_factory)() as db:
        conv = await own_conversation(db, conv_id)
        if (conv.metadata_json or {}).get("pending_question"):
            raise HTTPException(409, "请先回答待你决策卡片中的问题，再继续当前任务")
