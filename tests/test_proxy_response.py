import json
import httpx
import pytest

from cortexa.agents.proxy_executor import _parse_proxy_response, _response_value


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


class SplitBody(httpx.AsyncByteStream):
    def __init__(self, data, width=97):
        self.data, self.width = data, width

    async def __aiter__(self):
        for offset in range(0, len(self.data), self.width):
            yield self.data[offset:offset + self.width]


def stream_request(monkeypatch, events, budget=1024, width=97, callback=None):
    import asyncio
    from cortexa.agents.proxy_executor import send_proxy_request
    body = ('\r\n\r\n'.join('data: ' + json.dumps(e, ensure_ascii=False) for e in events)).encode()
    client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=SplitBody(body,width)))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: client(transport=transport, **kwargs))
    return asyncio.run(send_proxy_request({'endpoint':'https://proxy.test/run'}, {'prompt':'取数'}, max_response_bytes=budget, on_event=callback))


def test_stream_telemetry_and_framing_do_not_consume_report_budget(monkeypatch):
    from unittest.mock import AsyncMock
    callback = AsyncMock()
    events = [{'type':'start','session_id':'original','request_id':'one'}]
    events.extend({'type':'tool_result','tool':'query_data','rows':'row ' * 4000} for _ in range(15))
    events.extend({'type':'text_delta','content':c} for c in '数据已完成核实，销量一百台。')
    events.append({'type':'done','status':'completed','answer':'数据已完成核实，销量一百台。'})
    result = stream_request(monkeypatch,events,width=101,callback=callback)
    assert result['answer'] == '数据已完成核实，销量一百台。'
    assert result['session_id'] == 'original'
    assert callback.await_count == 30


@pytest.mark.parametrize('events', [
    [{'type':'text_delta','content':'字' * 500}, {'type':'done'}],
    [{'type':'done','answer':'字' * 500}],
])
def test_stream_actual_report_still_has_response_limit(monkeypatch, events):
    with pytest.raises(ValueError, match='proxy_response_budget_exceeded'):
        stream_request(monkeypatch,events)


def test_stream_does_not_succeed_without_terminal_event(monkeypatch):
    with pytest.raises(ValueError, match='未正常结束'):
        stream_request(monkeypatch,[{'type':'text_delta','content':'未完成报告'}],width=3)


def test_stream_preserves_question_and_done_without_extra_blank_line(monkeypatch):
    result = stream_request(monkeypatch,[{'type':'start','session_id':'same'},
        {'type':'ask_user','question':'选择口径','options':['发货','零售']},
        {'type':'done','status':'awaiting_user','answer':'选择口径'}],width=1)
    assert result['requires_input'] and result['user_question']['options'] == ['发货','零售']


def test_stream_large_single_tool_frame_is_bounded(monkeypatch):
    with pytest.raises(ValueError, match='proxy_stream_budget_exceeded'):
        stream_request(monkeypatch,[{'type':'tool_result','rows':'x' * (1024 * 1024 + 1)}, {'type':'done','answer':'完成'}],width=65536)


def test_failed_tool_can_be_repaired_before_successful_agent_completion(monkeypatch):
    events = [
        {'type':'start','session_id':'original'},
        {'type':'tool_result','tool':'describe_workbook','status':'error','ok':False,
         'error_code':'WORKBOOK_UNAVAILABLE','error_message':'工具无法读取工作簿'},
        {'type':'tool_result','tool':'query_data','status':'success','ok':True},
        {'type':'text_delta','content':'使用业务查询取得销售数据。'},
        {'type':'done','status':'completed','ok':True,'answer':'使用业务查询取得销售数据。'},
    ]
    assert _parse_proxy_response(sse(events))['answer'] == '使用业务查询取得销售数据。'
    assert stream_request(monkeypatch,events,width=7)['answer'] == '使用业务查询取得销售数据。'


@pytest.mark.parametrize('terminal',[
    {'type':'error','message':'任务失败'},
    {'type':'done','status':'failed','ok':False,'error':'任务失败'},
])
def test_task_failure_is_distinct_from_tool_failure(monkeypatch,terminal):
    from cortexa.agents.proxy_executor import ProxyExecutionError
    events = [{'type':'tool_result','status':'error','ok':False},terminal]
    with pytest.raises(ProxyExecutionError):
        _parse_proxy_response(sse(events))
    with pytest.raises(ProxyExecutionError):
        stream_request(monkeypatch,events)


def test_tool_failure_without_completed_task_is_not_success(monkeypatch):
    with pytest.raises(ValueError,match='未正常结束'):
        stream_request(monkeypatch,[{'type':'tool_result','status':'error','ok':False},
                                   {'type':'text_delta','content':'尚未完成'}])
