"""Conversation titles are derived once from the first user turn."""

import asyncio
import uuid

from cortexa.api import conversation_titles
from cortexa.api.conversation_titles import (
    assign_first_message_title,
    clean_generated_title,
    overwrite_placeholder_title,
    title_from_first_message,
)


def test_title_uses_first_turn_text_without_collaboration_mentions():
    assert title_from_first_message("@品牌部 @销售部 研究下10月销售计划") == "研究下10月销售计划"
    assert title_from_first_message("  第一行\n 第二行  ") == "第一行 第二行"
    assert title_from_first_message("x" * 50) == "x" * 39 + "…"
    assert title_from_first_message("   ") == ""


def test_first_title_write_requires_empty_title_and_no_prior_user_turn():
    class Result:
        def scalar(self):
            return "研究下10月销售计划"

    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()
    title = asyncio.run(assign_first_message_title(session, uuid.uuid4(), "@品牌部 研究下10月销售计划"))
    assert title == "研究下10月销售计划"
    sql = str(session.statement)
    assert "NOT (EXISTS" in sql
    assert "t_conversations.title IS NULL" in sql
    assert "t_conversation_messages.role" in sql


def test_generated_title_cleanup_strips_quotes_whitespace_and_caps_length():
    assert clean_generated_title("“研究下10月销售计划”") == "研究下10月销售计划"
    assert clean_generated_title("  关于\n A6L 销量 的 标题。 ") == "关于 A6L 销量 的 标题"
    assert clean_generated_title("t" * 50) == "t" * 39 + "…"
    assert clean_generated_title("''") == ""
    assert clean_generated_title(None) == ""


def test_llm_title_overwrite_requires_no_manual_rename_flag():
    class Session:
        statement = None

        async def execute(self, statement):
            self.statement = statement

    session = Session()
    asyncio.run(overwrite_placeholder_title(session, uuid.uuid4(), "10月销量分析"))
    sql = str(session.statement)
    compiled = session.statement.compile()
    assert "UPDATE t_conversations" in sql
    assert "IS NULL" in sql
    assert compiled.params.get("metadata_json_1") == "title_manual"


def test_schedule_llm_title_dedupes_per_conversation(monkeypatch):
    created = []

    class FakeTask:
        def add_done_callback(self, callback):
            pass

    def fake_create_task(coroutine):
        coroutine.close()
        created.append(coroutine)
        return FakeTask()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)
    conv_id = uuid.uuid4()
    conversation_titles._scheduled.discard(conv_id)
    try:
        conversation_titles.schedule_llm_title(conv_id)
        conversation_titles.schedule_llm_title(conv_id)
    finally:
        conversation_titles._scheduled.discard(conv_id)
    assert len(created) == 1
