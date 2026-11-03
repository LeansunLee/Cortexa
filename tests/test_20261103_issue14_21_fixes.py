"""Regressions for the 2026-11-03 smoke-round issues #14/#16/#19/#20.

#15 (middleware skills gate), #17 (regenerate provider guard), #18 (workspace
delete pre-clean) and #21 (sidebar affordance) are covered by live verification
on the dev server; see the issue-close comments.
"""

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from cortexa.security.access import Actor, current_actor


def _actor(ws_id, uid):
    return Actor(
        uid, "tester", False, False, 1,
        memberships={ws_id: {"permissions": {"workspace.manage"}}}, workspace_id=ws_id,
    )


def test_issue14_conversation_summary_imports_user_from_security_models():
    """A human-assignee work must not crash conversation_summary with
    `cannot import name 'User' from 'cortexa.db.models'` (#14)."""
    from cortexa.work import runtime as work_runtime

    ws_id, uid = uuid.uuid4(), uuid.uuid4()
    work = SimpleNamespace(
        id=uuid.uuid4(), title="bugtest-工作A", status="completed", priority="P1",
        goal="目标", deliverable_requirement="", assignee_type="human", assignee_id=uid,
        updated_at=datetime(2026, 11, 3),
    )
    user = SimpleNamespace(id=uid, display_name="验收人甲")
    works_result = Mock(scalars=lambda: Mock(all=lambda: [work]))
    users_result = Mock(scalars=lambda: Mock(all=lambda: [user]))
    db = SimpleNamespace(execute=AsyncMock(side_effect=[works_result, users_result]))
    token = current_actor.set(_actor(ws_id, uid))
    try:
        text, refs = asyncio.run(work_runtime.conversation_summary(db, uuid.uuid4()))
    finally:
        current_actor.reset(token)
    assert "bugtest-工作A" in text and refs and refs[0]["name"] == "bugtest-工作A"


def _decide(doc, query):
    from cortexa.rag.relevance import select_documents

    _, ranked = select_documents([doc], query, {str(doc.id): doc.content})
    return ranked[0][0]


def _doc(name, text):
    return SimpleNamespace(id=uuid.uuid4(), name=name, content=text, metadata_json={})


def test_issue16_generic_phrase_query_matches_document_containing_it():
    """A query whose phrase is tagged as an unresolved entity must still hit a
    document literally containing the phrase (#16)."""
    hit = _doc("说明文档.txt", "Cortexa 冒烟测试知识文档。产品定位：AI 智能体管理平台。核心价值：企业级 AI Agent。")
    decision = _decide(hit, "产品定位")
    assert decision["eligible"] and decision["evidence_grade"] == "DIRECT"

    interrogative = _decide(hit, "产品定位 是什么")
    assert interrogative["eligible"] and interrogative["evidence_grade"] == "DIRECT"


def test_issue16_absent_phrase_stays_excluded():
    """When the queried terms are absent the gate still excludes the document."""
    miss = _doc("无关文档.txt", "完全无关的其他内容。")
    decision = _decide(miss, "产品定位")
    assert not decision["eligible"]
    assert "query_terms_absent" in decision["filter_reasons"]


def test_issue16_business_entity_queries_keep_the_strict_gate():
    """Hard entity queries must not be loosened by the lexical fast path."""
    other = _doc("黑旗600清库复盘", "已执行清库120台")
    decision = _decide(other, "金吉拉250清库案例")
    assert not decision["eligible"]
    assert "query_terms_absent" not in decision["filter_reasons"]


def test_issue19_stream_sources_are_not_seeded_with_duplicate_work_refs():
    """The stream's sources seed must contain project refs only; works refs are
    appended once by the conditional extends (#19)."""
    import ast
    import pathlib

    source = pathlib.Path("src/cortexa/api/conversations.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    stream_fn = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "create_message_stream"
    )
    assigns = [n for n in ast.walk(stream_fn) if isinstance(n, ast.Assign)]
    seeds = [a for a in assigns if getattr(a.targets[0], "id", None) == "sources"
             and isinstance(a.value, ast.BinOp)]
    assert not seeds, f"sources must not be seeded with duplicated list adds: {[ast.unparse(a.value) for a in seeds]}"
    extends = [
        ast.unparse(n)
        for n in ast.walk(stream_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "extend"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "sources"
    ]
    assert any("works_refs" in call for call in extends)


def test_issue20_datasource_create_rejects_top_level_connection_fields():
    from cortexa.api.schemas import DataSourceCreate

    with pytest.raises(ValidationError):
        DataSourceCreate(
            name="x", type="postgres", host="127.0.0.1", port=5432,
            database="db", username="u", password="p",
        )
    ok = DataSourceCreate(name="x", type="postgres", config={"host": "127.0.0.1"}, credential_id=None)
    assert ok.config == {"host": "127.0.0.1"}


def test_issue20_missing_credential_reports_readable_error():
    from cortexa.data.adapter import execute_query, test_connection

    result = asyncio.run(test_connection("postgres", {"host": "127.0.0.1"}, None))
    assert not result["success"] and "未绑定凭证" in result["message"]

    result = asyncio.run(
        execute_query("postgres", {"host": "127.0.0.1"}, None, "SELECT 1", {}, read_only=False)
    )
    assert not result["success"] and "未绑定凭证" in result["error"]
