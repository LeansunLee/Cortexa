import json
import httpx
import pytest

from agentdevstu.agents.proxy_executor import _parse_proxy_response, _response_value


def sse(events):
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="\n\n".join("data: " + json.dumps(event, ensure_ascii=False) for event in events))


def test_external_agent_sse_uses_final_answer_and_preserves_mapping_fields():
    response = sse([
        {"type": "start", "session_id": "session", "request_id": "request"},
        {"type": "tool_result", "result": "内部工具信息"},
        {"type": "text_delta", "content": "连接"},
        {"type": "text_delta", "content": "正常"},
        {"type": "final_answer"},
        {"type": "done", "answer": "连接正常。", "status": "completed", "ok": True},
    ])
    result = _parse_proxy_response(response)
    assert result["answer"] == "连接正常。"
    assert result["session_id"] == "session"
    assert result["request_id"] == "request"
    assert "内部工具信息" not in result["answer"]


def test_sse_can_assemble_deltas_without_final_answer():
    assert _parse_proxy_response(sse([{"type": "text_delta", "content": "你好"}, {"type": "done"}]))["answer"] == "你好"


@pytest.mark.parametrize("events", [
    [{"type": "text_delta", "content": "部分回答"}],
    [{"type": "done", "ok": False, "error": "失败"}],
    [{"type": "done"}],
])
def test_failed_empty_or_incomplete_stream_is_not_success(events):
    with pytest.raises(ValueError):
        _parse_proxy_response(sse(events))


def test_json_text_nested_mapping_and_invalid_response():
    assert _parse_proxy_response(httpx.Response(200, json={"answer": "JSON回答"}))["answer"] == "JSON回答"
    assert _parse_proxy_response(httpx.Response(200, headers={"content-type": "text/plain"}, text="纯文本回答"))["answer"] == "纯文本回答"
    assert _response_value({"data": {"answer": "嵌套回答"}}, "$.data.answer") == "嵌套回答"
    for response in (httpx.Response(200, text=""), httpx.Response(200, headers={"content-type": "text/html"}, text="<html>错误</html>")):
        with pytest.raises(ValueError):
            _parse_proxy_response(response)
