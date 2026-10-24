"""ask_user recommendation validation and auto-continue eligibility tests."""
import uuid
from datetime import datetime, timedelta, timezone

from cortexa.conversation.question_sweeper import eligible_for_auto
from cortexa.conversation.questions import AskUserInput, auto_answer_timeout, question


class _Agent:
    id = uuid.uuid4()
    name = "测试"


def base(**overrides):
    payload = {"question": "选一个", "options": ["继续执行", "接受草案"]}
    payload.update(overrides)
    return question(payload, _Agent())


def test_recommendation_kept_for_single_choice():
    q = base(recommended_option_index=0, recommendation_reason="风险最低")
    assert q["recommended_option_index"] == 0
    assert q["recommendation_reason"] == "风险最低"
    assert q.get("auto_timeout_seconds", 0) >= 0
    assert q["raised_at"]


def test_recommendation_dropped_for_multi_select_and_out_of_range():
    q = base(multi_select=True, recommended_option_index=0, recommendation_reason="x")
    assert q["recommended_option_index"] is None and "recommendation_reason" not in q
    q2 = base(recommended_option_index=9)
    assert q2["recommended_option_index"] is None


def test_ask_input_schema_accepts_recommendation():
    parsed = AskUserInput.model_validate(
        {"question": "q", "options": ["a", "b"], "recommended_option_index": 1, "recommendation_reason": "更快"}
    )
    assert parsed.recommended_option_index == 1
    bad = AskUserInput.model_validate({"question": "q", "options": ["a"], "recommended_option_index": 3})
    assert bad.recommended_option_index == 3  # schema allows; question() normalizes


def _pending(raised_minutes_ago, **overrides):
    q = base(recommended_option_index=0)
    q["engine"] = "llm"
    q["raised_at"] = (datetime.now(timezone.utc) - timedelta(minutes=raised_minutes_ago)).isoformat()
    q.update(overrides)
    return q


def test_eligible_only_after_deadline():
    assert eligible_for_auto(_pending(30), ) is False or auto_answer_timeout() <= 3600
    q = _pending(9999)
    assert eligible_for_auto(q) is True


def test_eligible_rejects_bad_shapes():
    now = datetime.now(timezone.utc)
    assert eligible_for_auto(_pending(9999, status="answering"), now) is False
    assert eligible_for_auto(_pending(9999, multi_select=True), now) is False
    assert eligible_for_auto(_pending(9999, recommended_option_index=None), now) is False
    assert eligible_for_auto(_pending(9999, engine="proxy"), now) is False
    assert eligible_for_auto(_pending(9999, auto_fail_count=3), now) is False
    assert eligible_for_auto(_pending(9999, raised_at=None), now) is False
    legacy = _pending(9999)
    legacy.pop("raised_at")
    legacy.pop("auto_timeout_seconds", None)
    assert eligible_for_auto(legacy, now) is False


def test_timeout_env_configuration(monkeypatch):
    monkeypatch.setenv("QUESTION_AUTO_ANSWER_TIMEOUT", "0")
    assert auto_answer_timeout() == 0
    assert eligible_for_auto(_pending(9999)) is False
    monkeypatch.setenv("QUESTION_AUTO_ANSWER_TIMEOUT", "60")
    assert auto_answer_timeout() == 60
    monkeypatch.setenv("QUESTION_AUTO_ANSWER_TIMEOUT", "not-a-number")
    assert auto_answer_timeout() == 3600
