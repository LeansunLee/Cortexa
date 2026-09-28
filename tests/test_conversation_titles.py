"""Conversation titles are derived once from the first user turn."""

import asyncio
import uuid

from agentdevstu.api.conversation_titles import assign_first_message_title, title_from_first_message


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
