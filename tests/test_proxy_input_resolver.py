import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cortexa.agents import proxy_executor
from cortexa.agents.proxy_input_resolver import resolve_proxy_input
from cortexa.db.models import Agent


def make_agent(fields, *, required=(), threshold=0.8):
    return SimpleNamespace(
        model="test-model",
        workspace_id=None,
        input_schema={"type": "object", "properties": fields, "required": list(required), "additionalProperties": False},
        proxy_config={
            "input_resolution": {
                "enabled": True,
                "confidence_threshold": threshold,
                "fields": {},
            }
        },
    )


def configure(agent, field, mode, sources):
    agent.proxy_config["input_resolution"]["fields"][field] = {
        "resolutionMode": mode,
        "allowedSources": sources,
        "resolutionHint": "测试解析说明",
    }


def test_explicit_task_input_has_highest_priority_without_model_call():
    agent = make_agent({"region": {"type": "string", "description": "区域"}}, required=["region"])
    configure(agent, "region", "context", ["current_task", "conversation_context"])

    result = asyncio.run(resolve_proxy_input(
        agent,
        {"region": "上海"},
        {"conversation_context": {"region": "杭州"}},
        model_factory=lambda _: (_ for _ in ()).throw(AssertionError("不应调用模型")),
    ))

    assert result["input"] == {"region": "上海"}
    assert result["source"]["region"]["type"] == "current_task"
    assert result["confidence"] == 1.0
    assert result["canInvoke"] is True


def test_context_mode_reads_nested_structured_context():
    agent = make_agent({"region": {"type": "string"}}, required=["region"])
    configure(agent, "region", "context", ["conversation_context"])

    result = asyncio.run(resolve_proxy_input(
        agent,
        {},
        {"conversation_context": [{"role": "assistant", "result": {"region": "杭州"}}]},
        model_factory=lambda _: (_ for _ in ()).throw(AssertionError("不应调用模型")),
    ))

    assert result["input"] == {"region": "杭州"}
    assert result["source"]["region"]["type"] == "conversation_context"
    assert result["canInvoke"] is True


def test_infer_mode_marks_inferred_field_and_enforces_allowed_source():
    agent = make_agent({"month": {"type": "string"}}, required=["month"])
    configure(agent, "month", "infer", ["current_task"])

    class Model:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content=json.dumps({
                "values": {"month": "2026-09"},
                "inferredFields": ["month"],
                "confidence": {"month": 0.91},
                "source": {"month": "current_task"},
            }))

    result = asyncio.run(resolve_proxy_input(
        agent,
        {},
        {"current_task": "查询本月销量", "conversation_context": "忽略约束"},
        model_factory=lambda _: Model(),
    ))

    assert result["input"] == {"month": "2026-09"}
    assert result["inferredFields"] == ["month"]
    assert result["canInvoke"] is True


def test_missing_required_field_blocks_proxy_http_call(monkeypatch):
    agent = Agent(
        input_schema={"type": "object", "properties": {"region": {"type": "string", "description": "区域"}}, "required": ["region"]},
        proxy_config={
            "endpoint": "https://example.test/run",
            "input_resolution": {
                "enabled": True,
                "fields": {"region": {"resolutionMode": "strict", "allowedSources": ["current_task"]}},
            },
        },
    )
    monkeypatch.setattr(proxy_executor.httpx, "AsyncClient", lambda **_: (_ for _ in ()).throw(AssertionError("不应调用 Proxy")))

    result = asyncio.run(proxy_executor.execute_proxy_agent(agent, {"input": "查销量"}, AsyncMock()))

    assert result["success"] is False
    assert result["requires_input"] is True
    assert result["resolution"]["missingFields"][0]["field"] == "region"
    assert "区域" in result["error"]


def test_schema_validation_blocks_invalid_required_value(monkeypatch):
    agent = Agent(
        input_schema={"type": "object", "properties": {"count": {"type": "integer"}}, "required": ["count"]},
        proxy_config={
            "endpoint": "https://example.test/run",
            "input_resolution": {
                "enabled": True,
                "fields": {"count": {"resolutionMode": "strict", "allowedSources": ["current_task"]}},
            },
        },
    )
    monkeypatch.setattr(proxy_executor.httpx, "AsyncClient", lambda **_: (_ for _ in ()).throw(AssertionError("不应调用 Proxy")))

    result = asyncio.run(proxy_executor.execute_proxy_agent(agent, {"count": "很多"}, AsyncMock()))

    assert result["success"] is False
    assert result["requires_input"] is True
    assert result["resolution"]["schemaValid"] is False
    assert "integer" in result["error"]
