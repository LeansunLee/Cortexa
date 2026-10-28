"""2026-10-01 regression round: fixes for GitHub issues #8, #10 and #13.

#8 raw tool-call markup must never become a goal/participant reply;
#10 memory-honesty prompt rule and correction-aware explicit extraction;
#13 document job locks are cleaned with the document and swept when orphaned.
"""
import os
import time
from types import SimpleNamespace

from langchain_core.messages import AIMessageChunk

from cortexa.agents.prompts import PLATFORM_RULES
from cortexa.memory.service import EXTRACTION_PROMPT, explicit_memory_candidate
from cortexa.runtime.loop import (
    GoalStatus,
    raw_tool_call_syntax,
    strip_raw_tool_calls,
)
from test_goal_loop import FakeModel, binding, make_loop, run


RAW_REPLY = (
    "<tool_call><function=project_context><parameter=action>retrieve</parameter>"
    "</function></tool_call>"
)


# ── #8 helpers ───────────────────────────────────────────────────────


def test_raw_tool_call_syntax_detection():
    assert raw_tool_call_syntax(RAW_REPLY)
    assert raw_tool_call_syntax("<tool_call><function=retrieve_memory_list></function></tool_call>")
    assert raw_tool_call_syntax("前缀文字 <function=search> 后缀")
    assert not raw_tool_call_syntax("正常结论：北极熊是吉祥物。")
    assert raw_tool_call_syntax("The tag <tool_call> appears in docs")
    assert not raw_tool_call_syntax("")
    assert not raw_tool_call_syntax(None)


def test_strip_raw_tool_calls_keeps_surrounding_prose():
    assert strip_raw_tool_calls(f"结论：北极熊。{RAW_REPLY}").strip() == "结论：北极熊。"
    assert strip_raw_tool_calls(RAW_REPLY).strip() == ""
    assert strip_raw_tool_calls("<tool_call><function=a><parameter=x>1</parameter>").strip() == ""


# ── #8 goal loop behaviour ───────────────────────────────────────────


def test_raw_tool_call_reply_is_rejected_then_model_answers_in_prose():
    loop, _, _ = make_loop()
    model = FakeModel([[AIMessageChunk(content=RAW_REPLY)], [AIMessageChunk(content="吉祥物是北极熊。")]])
    events = run(loop, model)
    assert loop.state.status == GoalStatus.COMPLETE
    assert loop.state.partial is not True
    assert loop.state.consumed["max_replans"] == 1
    assert loop.reply == "吉祥物是北极熊。"
    assert [e["content"] for e in events if e["type"] == "token"] == ["吉祥物是北极熊。"]
    nudge = model.calls[-1][-1]
    assert nudge.type == "system" and "工具调用语法" in nudge.content


def test_raw_tool_call_with_prose_retries_then_answers_in_prose():
    # Markup next to prose still signals an attempted tool call: nudge once,
    # then accept the clean prose answer.
    loop, _, _ = make_loop()
    model = FakeModel(
        [
            [AIMessageChunk(content=f"结论：北极熊。{RAW_REPLY}")],
            [AIMessageChunk(content="结论：北极熊。")],
        ]
    )
    run(loop, model)
    assert loop.state.status == GoalStatus.COMPLETE
    assert loop.state.consumed["max_replans"] == 1
    assert loop.reply == "结论：北极熊。"
    assert "<tool_call" not in loop.reply


def test_persistent_raw_tool_call_finalizes_from_collected_results():
    loop, _, _ = make_loop(limits={"max_replans": 0})
    loop.payload["observations"] = [
        {"status": "SUCCESS", "summary": "已收集 2 条来源", "facts": [], "evidence": [], "metadata": {}}
    ]
    model = FakeModel([[AIMessageChunk(content=RAW_REPLY)]])
    events = run(loop, model, [binding()])
    assert loop.state.status == GoalStatus.COMPLETE
    assert loop.state.partial is True
    assert "已取得部分结果" in loop.reply and "已收集 2 条来源" in loop.reply
    assert all(RAW_REPLY not in e.get("content", "") for e in events if e["type"] == "token")


def test_persistent_raw_tool_call_without_results_fails_closed():
    loop, _, _ = make_loop(limits={"max_replans": 0})
    model = FakeModel([[AIMessageChunk(content=RAW_REPLY)]])
    run(loop, model)
    assert loop.state.status == GoalStatus.FAILED
    assert loop.state.reason == "model_empty"


# ── #10 extraction honesty ───────────────────────────────────────────


def test_correction_statement_is_an_explicit_memory_candidate():
    actor = SimpleNamespace(user_id="u1", username="alice")
    candidate = explicit_memory_candidate(
        "更正：公司正式名称变更为云帆数联", "msg-1", "rev-1", actor.user_id, actor.username
    )
    assert candidate is not None
    assert candidate["source_mode"] == "explicit"
    assert "云帆数联" in candidate["content"]
    assert explicit_memory_candidate("跟你说个事，下周三去杭州拜访客户。", "m", "r", "u", "a") is None
    assert explicit_memory_candidate("请记住：我的密码是 Dolphin@2026", "m", "r", "u", "a") is None


def test_prompts_carry_memory_honesty_and_correction_rules():
    assert "已记下" in PLATFORM_RULES and "请记住" in PLATFORM_RULES
    assert "更正" in EXTRACTION_PROMPT and "作废" in EXTRACTION_PROMPT


def test_user_facing_halt_reasons_have_readable_messages():
    # Issue #11 follow-up: halt reasons must not surface as raw codes.
    from cortexa.api.goals import HALT_MESSAGES

    for reason in (
        "unresolved_capability_failure",
        "capability_unavailable",
        "capability_not_authorized",
        "collaboration_unavailable",
        "dependency_not_ready",
        "agent_input_budget_exceeded",
        "action_result_unknown",
    ):
        assert reason in HALT_MESSAGES and "：" + reason not in HALT_MESSAGES[reason]


# ── #13 document job locks ───────────────────────────────────────────


def test_document_locks_are_cleared_and_swept(tmp_path, monkeypatch):
    from cortexa.data import document_jobs

    monkeypatch.setattr(document_jobs, "DOC_STORAGE_DIR", str(tmp_path))
    root = tmp_path / ".locks"
    root.mkdir()
    doc_id = "11111111-1111-1111-1111-111111111111"
    for kind in ("pdf", "index", "summary"):
        (root / f"{doc_id}.{kind}").touch()
    other = root / "22222222-2222-2222-2222-222222222222.extract"
    other.touch()

    removed = document_jobs.clear_document_locks(doc_id)
    assert sorted(removed) == [f"{doc_id}.index", f"{doc_id}.pdf", f"{doc_id}.summary"]
    assert list(root.glob(f"{doc_id}.*")) == []
    assert other.exists()

    aged = root / "33333333-3333-3333-3333-333333333333.pdf"
    aged.touch()
    old = time.time() - 2 * 3600
    os.utime(aged, (old, old))

    assert document_jobs.sweep_orphan_locks(max_age_minutes=60) == 1
    assert not aged.exists() and other.exists()


def test_document_job_lock_imports_without_fcntl():
    # Windows dev boxes lack fcntl; the module must stay importable for KB tests.
    import cortexa.data.document_jobs as jobs

    assert hasattr(jobs, "document_job_lock") and hasattr(jobs, "clear_document_locks")


def test_textless_image_is_textless_not_error(monkeypatch, tmp_path):
    # Issue #12: a valid image without recognizable text must reach the
    # unsupported flow, not surface as a pipeline error.
    import asyncio

    from cortexa.data import document_extraction, pdf_extraction

    def fake_extract(path):
        raise RuntimeError("未识别到文字，请上传清晰的文字图片，或手动填写摘要")

    monkeypatch.setattr(pdf_extraction, "extract_image", fake_extract)
    original = tmp_path / "original"
    original.write_bytes(b"png")
    text, pages, info_only = asyncio.run(
        document_extraction.extract_document("doc", "图.png", {"content_type": "image/png"}, original)
    )
    assert text == "" and pages == 0 and info_only is False

    def broken(path):
        raise RuntimeError("cannot identify image file")

    monkeypatch.setattr(pdf_extraction, "extract_image", broken)
    try:
        asyncio.run(
            document_extraction.extract_document("doc", "图.png", {"content_type": "image/png"}, original)
        )
    except RuntimeError as error:
        assert "cannot identify" in str(error)
    else:
        raise AssertionError("corrupt image must still raise")
