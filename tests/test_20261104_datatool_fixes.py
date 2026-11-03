"""Behavioral regressions for the 2026-11-04 data-tool round (#14-#19)."""

import textwrap
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from cortexa.agents.retrieval import bounded_result
from cortexa.config.llm_providers import provider_exists
from cortexa.tools.runtime import (
    MarkupGuard,
    parse_text_tool_calls,
    promote_text_tool_calls,
    should_require_business_tool,
    strip_text_tool_markup,
)

MARKUP = (
    "<tool_call><function=query_1da02b61e1ef4aec93c4b38d93dcb13b>"
    "<parameter=model_name>灰旗400</parameter></function></tool_call>"
)


def tool(name):
    return SimpleNamespace(name=name, description="查询数据能力：测试能力。")


# ---------------------------------------------------------------- PDT-14
def test_parse_text_tool_calls_extracts_name_and_params():
    calls = parse_text_tool_calls("前言" + MARKUP + "后记")
    assert calls == [{
        "name": "query_1da02b61e1ef4aec93c4b38d93dcb13b",
        "args": {"model_name": "灰旗400"},
        "id": "text_call_0",
    }]


def test_parse_text_tool_calls_plain_text_is_empty():
    assert parse_text_tool_calls("第一次查询未成功执行，我换更宽的关键词重试。") == []


def test_strip_text_tool_markup_removes_blocks_and_unterminated_tail():
    assert strip_text_tool_markup("答案： " + MARKUP) == "答案："
    assert strip_text_tool_markup("开头 <tool_call><function=x>") == "开头"


def test_promote_text_tool_calls_routes_known_tool_into_structured_call():
    response = AIMessage(content=MARKUP)
    promoted = promote_text_tool_calls(response, [tool("query_1da02b61e1ef4aec93c4b38d93dcb13b")])
    assert promoted.tool_calls and promoted.tool_calls[0]["name"] == "query_1da02b61e1ef4aec93c4b38d93dcb13b"
    assert promoted.tool_calls[0]["args"] == {"model_name": "灰旗400"}
    assert promoted.content == ""


def test_promote_text_tool_calls_strips_unknown_tool_markup():
    response = AIMessage(content="<tool_call><function=no_such_tool><parameter=a>1</parameter></function></tool_call>")
    out = promote_text_tool_calls(response, [tool("query_x")])
    assert not getattr(out, "tool_calls", None)
    assert "tool_call" not in out.content


def test_promote_text_tool_calls_leaves_clean_response_alone():
    response = AIMessage(content="库里有黑旗500。", tool_calls=[{"name": "t", "args": {}, "id": "1"}])
    assert promote_text_tool_calls(response, [tool("t")]) is response
    plain = AIMessage(content="普通回答")
    assert promote_text_tool_calls(plain, [tool("t")]) is plain


def test_markup_guard_suppresses_split_sentinel_and_flushes_tail():
    guard = MarkupGuard()
    assert guard.feed("查询结果<tool_") == "查询结果"
    assert guard.feed("call><function=x>") == ""
    assert guard.suppressed
    assert guard.feed("更多") == ""
    assert guard.flush() == ""

    guard2 = MarkupGuard()
    assert guard2.feed("正常文本") == "正常文本"
    assert guard2.feed("继续") == "继续"
    assert guard2.flush() == ""


# ---------------------------------------------------------------- PDT-17
TOOLS = [tool("query_cap"), SimpleNamespace(name="query_cap2", description="两车型对比，model_a/model_b 模糊模式")]


@pytest.mark.parametrize("query,expected", [
    ("你刚才给我的这些数据是最新的吗？数据从哪来的？", False),
    ("你给我的价格数据来源是什么？可信吗？", False),
    ("这个数据准不准？多久更新一次？", False),
    ("查一下最新的黑旗500价格", True),
    ("黑旗500多少钱", True),
    ("列出黑旗500的所有版本", True),
])
def test_meta_questions_skip_forced_grounding(query, expected):
    assert should_require_business_tool(query, TOOLS) is expected


# ---------------------------------------------------------------- PDT-15
def test_extract_json_dict_tolerates_wrappers():
    from cortexa.api.conversations import _extract_json_dict

    assert _extract_json_dict('{"model_a": "%黑旗950%"}') == {"model_a": "%黑旗950%"}
    assert _extract_json_dict(textwrap.dedent("""
        ```json
        {"model_a": "a", "model_b": "b"}
        ```
    """).strip()) == {"model_a": "a", "model_b": "b"}
    assert _extract_json_dict('解析结果如下：{"model_a": "a", "model_b": "b"} 请查收') == {"model_a": "a", "model_b": "b"}
    with pytest.raises(ValueError):
        _extract_json_dict("抱歉，我无法确定参数。")


def test_align_resolved_args_matches_aliases_and_drops_extras():
    from cortexa.api.conversations import _align_resolved_args

    resolved = {"model_name": "%黑旗%", "extra_key": "x", "MODEL_B": "%骠骑%"}
    aligned = _align_resolved_args(resolved, ("model_name", "model_b"))
    assert aligned == {"model_name": "%黑旗%", "model_b": "%骠骑%"}
    assert _align_resolved_args("not-a-dict", ("model_name",)) == {}
    assert _align_resolved_args({"a": 1}, ()) == {}


def test_capability_exec_falls_back_to_raw_args_when_resolver_fails(monkeypatch):
    """A resolver hiccup must not kill a call whose raw args satisfy the schema."""
    import asyncio

    from cortexa.api import conversations as conv_mod

    cap = SimpleNamespace(
        id=uuid.uuid4(), name="cap", description="补充提示词", query_template="SELECT 1 WHERE x = :model_a AND y = :model_b",
        input_schema={}, row_limit=5, timeout_seconds=10, workspace_id=uuid.uuid4(), data_source_id=uuid.uuid4(),
    )
    ds = SimpleNamespace(id=cap.data_source_id, name="ds", type="postgres", config={}, credential_id=None, description="")

    class FakeInput:
        def model_json_schema(self):
            return {}

        def model_validate(self, value):
            if not value.get("model_a") or not value.get("model_b"):
                raise ValueError("missing")
            return SimpleNamespace(model_dump=lambda: dict(value))

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, model, key):
            return cap if str(key) == str(cap.id) else ds

        def add(self, row):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    async def boom(*args, **kwargs):
        raise RuntimeError("resolver output not json")

    async def fake_query(**kwargs):
        return {"success": True, "data": [{"a": 1}], "row_count": 1, "columns": ["a"], "duration_ms": 1, "error": None}

    monkeypatch.setattr(conv_mod, "_resolve_data_tool_args", boom)
    monkeypatch.setattr(conv_mod, "execute_query", fake_query)
    import sys
    db_engine_module = sys.modules["cortexa.db.engine"]
    monkeypatch.setattr(db_engine_module, "async_session_factory", lambda: FakeSession())

    tools = conv_mod._build_data_tools(
        [{"capability": cap, "data_source": ds}],
        model=object(), user_query="对比黑旗950和黑旗600", context=[], agent_id=uuid.uuid4(),
    )
    assert len(tools) == 1
    raw = {"model_a": "%黑旗950%", "model_b": "%黑旗600%", "rogue": "drop-me"}
    result = asyncio.run(tools[0].coroutine(**raw))
    assert isinstance(result, dict) and result.get("data"), result
    assert "notice" in result  # bounded_result attached execution guidance


def test_capability_exec_fails_explicitly_and_audits_when_args_unresolvable(monkeypatch):
    """No usable resolution and no usable raw args -> explicit failure, with an
    audit row so the ungrounded answer stays explainable (PDT-19)."""
    import asyncio
    import sys

    from cortexa.api import conversations as conv_mod

    cap = SimpleNamespace(
        id=uuid.uuid4(), name="cap", description="补充提示词",
        query_template="SELECT 1 WHERE x = :model_a AND y = :model_b",
        input_schema={}, row_limit=5, timeout_seconds=10,
        workspace_id=uuid.uuid4(), data_source_id=uuid.uuid4(),
    )
    ds = SimpleNamespace(id=cap.data_source_id, name="ds", type="postgres", config={}, credential_id=None, description="")

    class FakeInput:
        def model_json_schema(self):
            return {}

        def model_validate(self, value):
            raise ValueError("required params missing")

    added = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, model, key):
            return cap if str(key) == str(cap.id) else ds

        def add(self, row):
            added.append(row)

        async def commit(self):
            pass

        async def rollback(self):
            pass

    async def boom(*args, **kwargs):
        raise RuntimeError("resolver output not json")

    monkeypatch.setattr(conv_mod, "_resolve_data_tool_args", boom)
    monkeypatch.setattr(sys.modules["cortexa.db.engine"], "async_session_factory", lambda: FakeSession())

    tools = conv_mod._build_data_tools(
        [{"capability": cap, "data_source": ds}],
        model=object(), user_query="对比两个车型", context=[], agent_id=uuid.uuid4(),
    )
    result = asyncio.run(tools[0].coroutine())
    assert result.get("error") == "未能确认工具参数，请补充或重试；本次未执行数据库查询。"
    assert added, "resolution failure must leave an audit row"
    assert added[0].status == "failed"
    assert "arg_resolution_failed" in (added[0].error_message or "")
    assert added[0].input_params == {}
