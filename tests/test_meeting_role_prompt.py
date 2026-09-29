import json
import uuid
from types import SimpleNamespace

from cortexa.api.meetings import (
    _build_agent_meeting_prompt,
    _build_host_summary_prompt,
    _generate_todos_sync,
)


def test_meeting_prompts_use_role_instead_of_display_name():
    agent = SimpleNamespace(
        name="Peter", role="产品经理", responsibilities="梳理需求", personality=None,
        boundaries=None, system_prompt=None,
    )
    participant_prompt = _build_agent_meeting_prompt(agent, "版本规划", "分析")
    host_prompt = _build_host_summary_prompt(agent, "版本规划", 1, 2)

    assert "产品经理" in participant_prompt
    assert "产品经理" in host_prompt
    assert "梳理需求" in participant_prompt
    assert "Peter" not in participant_prompt + host_prompt


def test_meeting_todos_resolve_role_reference_without_exposing_display_name(monkeypatch):
    participant = SimpleNamespace(agent_id=uuid.uuid4(), name="Peter", role="产品经理")
    captured = {}

    class Model:
        def invoke(self, messages):
            captured["prompt"] = messages[0]["content"]
            return SimpleNamespace(content=json.dumps([{
                "title": "梳理需求", "description": "输出清单", "assignee_ref": "P1",
                "assignee_name": "伪造姓名", "assignee_agent_id": "伪造 ID", "priority": "medium",
            }]))

    monkeypatch.setattr("cortexa.config.llm_providers.create_llm", lambda: Model())
    todos = _generate_todos_sync("版本规划", "梳理需求", [participant])

    assert "P1: 产品经理" in captured["prompt"]
    assert "Peter" not in captured["prompt"]
    assert todos[0]["assignee_name"] == "Peter"
    assert todos[0]["assignee_agent_id"] == str(participant.agent_id)
    assert "assignee_ref" not in todos[0]
