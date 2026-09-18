import asyncio
import importlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agentdevstu.agents.retrieval import plan_retrieval, select_capabilities, bounded_result, web_reference


def test_explicit_web_query_never_defaults_to_internal_sources():
    plan = plan_retrieval("查一下网上关于黑旗600的信息")
    assert plan.web and not plan.knowledge and not plan.memory and not plan.data
    assert not plan_retrieval("在网上查经销商信息").data
    assert not plan_retrieval("不要联网，查询内部销售政策").web


def test_followups_and_business_queries_use_different_sources():
    for query in ("谢谢", "继续", "把上面的内容总结一下", "翻译这段话"):
        assert not any((plan_retrieval(query).web, plan_retrieval(query).knowledge, plan_retrieval(query).data))
    assert plan_retrieval("查询销售政策").knowledge
    assert not plan_retrieval("查询杭州门店").data
    assert plan_retrieval("联网查询并结合内部销售政策").knowledge


def test_capabilities_are_not_filtered_by_domain_language_or_top_k():
    items = [{"capability": SimpleNamespace(name=name)} for name in
             ("工资核算", "实验结果", "账龄", "设备健康", "订阅续费", "排课")]
    for query in ("去年同期呢？", "How many are overdue?", "谢谢", "查询杭州门店", ""):
        assert select_capabilities(items, query) == items


def test_result_budget_preserves_truncation_information():
    rows = [{"name": f"门店{i}", "province": "浙江省" if i < 41 else "上海市"} for i in range(53)]
    complete = bounded_result({"data": rows, "row_count": 53})
    assert not complete["truncated"] and complete["returned_rows"] == 53
    assert complete["data"][-1]["name"] == "门店52"
    assert complete["facets"]["province"] == {"浙江省": 41, "上海市": 12}

    result = bounded_result({"data": [{"name": "门店" * 100}] * 500, "row_count": 500}, max_chars=6000)
    assert result["truncated"] and result["returned_rows"] < 500
    assert len(json.dumps(result["data"], ensure_ascii=False)) <= 6000
    assert result["row_count"] == 500


def test_query_parameters_are_derived_from_sql_not_invented_query_field():
    from agentdevstu.api.conversations import _build_data_tools, _query_parameter_names

    assert _query_parameter_names("SELECT now()::date WHERE region=:region OR city=:city OR backup=:region") == ["region", "city"]
    cap = SimpleNamespace(
        id=uuid.uuid4(), name="门店", description="查询门店", query_template="SELECT * FROM stores",
        input_schema={"properties": {"query": {"type": "string"}}},
    )
    tool = _build_data_tools([{"capability": cap, "data_source": SimpleNamespace(id=uuid.uuid4())}])[0]
    assert tool.args_schema.model_json_schema()["properties"] == {}
    assert "不接受筛选参数" in tool.description


def test_data_capability_description_is_injected_as_supplemental_prompt():
    from agentdevstu.api.conversations import _build_data_tools, _build_tool_usage_instructions

    cap = SimpleNamespace(
        id=uuid.uuid4(),
        name="经销商",
        description="只按工具返回字段回答；经销商名称支持模糊匹配。",
        query_template="SELECT name FROM dealers WHERE (:dealer_name IS NULL OR name LIKE :dealer_name)",
        input_schema={"properties": {"dealer_name": {"type": "string", "description": "经销商名称"}}},
    )
    item = {"capability": cap, "data_source": SimpleNamespace(id=uuid.uuid4())}
    tool = _build_data_tools([item])[0]
    instructions = _build_tool_usage_instructions([item], [tool])

    assert "补充提示词：只按工具返回字段回答；经销商名称支持模糊匹配。" in tool.description
    assert "补充提示词：只按工具返回字段回答；经销商名称支持模糊匹配。" in instructions
    assert "选择工具、填写入参、解释结果时" in instructions


def test_data_tool_respects_capability_limit_and_keeps_complete_result(monkeypatch):
    from agentdevstu.api import conversations
    from agentdevstu.db.models import DataCapability, DataSource

    cap_id = uuid.uuid4()
    ds_id = uuid.uuid4()
    cap = SimpleNamespace(
        id=cap_id, name="门店", description="查询门店",
        query_template="SELECT name FROM stores WHERE (:region IS NULL OR region=:region) AND (:city IS NULL OR city=:city)",
        input_schema={"properties": {
            "region": {"type": "string", "description": "地区"},
            "city": {"type": "string", "description": "城市"},
        }},
    )
    ds = SimpleNamespace(id=ds_id)
    cap_db = SimpleNamespace(query_template=cap.query_template, row_limit=1000, timeout_seconds=30)
    ds_db = SimpleNamespace(type="mysql", config={}, credential_id=None)

    class FakeSession:
        async def get(self, model, item_id):
            if model is DataCapability and item_id == cap_id:
                return cap_db
            if model is DataSource and item_id == ds_id:
                return ds_db
            return None

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *_args):
            return None

    query_rows = [{"门店名称": f"门店{i}"} for i in range(53)]
    execute = AsyncMock(return_value={"success": True, "data": query_rows, "row_count": 53})
    engine_module = importlib.import_module("agentdevstu.db.engine")
    monkeypatch.setattr(engine_module, "async_session_factory", lambda: FakeSessionContext())
    monkeypatch.setattr(conversations, "execute_query", execute)

    sources = []
    ds.name = "配置数据源"
    ds.description = "测试来源"
    tool = conversations._build_data_tools([{"capability": cap, "data_source": ds}], sources)[0]
    result = asyncio.run(tool.ainvoke({"region": "华东"}))

    assert execute.await_args.kwargs["params"] == {"region": "华东", "city": None}
    assert execute.await_args.kwargs["row_limit"] == 1000
    assert result["applied_parameters"] == {"region": "华东", "city": None}
    assert result["returned_rows"] == 53
    assert result["truncated"] is False
    assert result["data"][-1]["门店名称"] == "门店52"
    # Runtime must preserve explicit nulls and user overrides, even when the
    # description contains defaults or similarly worded SQL literals.
    asyncio.run(tool.ainvoke({"region": None, "city": "任意用户值"}))
    assert execute.await_args.kwargs["params"] == {"region": None, "city": "任意用户值"}
    # More than three distinct queries are valid within the enclosing tool loop.
    for index in range(4):
        asyncio.run(tool.ainvoke({"region": str(index)}))
    assert execute.await_count == 6
    # Duplicate calls use the same result without a second database query.
    asyncio.run(tool.ainvoke({"region": "3"}))
    assert execute.await_count == 6
    # Unknown arguments fail validation before reaching the database.
    result = asyncio.run(tool.ainvoke({"invented": "filter"}))
    assert isinstance(result, str) and "validation" in result.lower()
    assert execute.await_count == 6
    # Model-based semantics can clear a filter; no heuristic restores defaults.
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='{"region":null,"city":"实验区"}')))
    resolved_tool = conversations._build_data_tools(
        [{"capability": cap, "data_source": ds}], model=model,
        user_query="所有区域", context=[{"role": "user", "content": "此前条件"}],
    )[0]
    asyncio.run(resolved_tool.ainvoke({"region": "None", "city": "实验区"}))
    assert execute.await_args.kwargs["params"] == {"region": None, "city": "实验区"}
    prompt = json.loads(model.ainvoke.await_args.args[0][1]["content"])
    assert prompt["conversation"] == [{"role": "user", "content": "此前条件"}]
    assert prompt["instructions"] == cap.description
    before_failure = execute.await_count
    for invalid in ('not JSON', '{"invented":"x"}'):
        model.ainvoke.return_value = SimpleNamespace(content=invalid)
        failure = asyncio.run(resolved_tool.ainvoke({"region": "新条件"}))
        assert "未执行数据库查询" in failure["error"]
        assert execute.await_count == before_failure
    assert sources == [{
        "type": "data_source", "name": "配置数据源",
        "capability": "门店", "description": "测试来源",
    }]


def test_web_results_and_failures_are_explicit(monkeypatch):
    monkeypatch.setattr("agentdevstu.tools.search.search_web", lambda *args, **kwargs: [{"title": "公开信息", "url": "https://example.com", "snippet": "摘要"}])
    context, sources, status = asyncio.run(web_reference("网上查询黑旗600"))
    assert context["role"] == "user" and sources[0]["url"] == "https://example.com"
    def fail(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr("agentdevstu.tools.search.search_web", fail)
    context, sources, status = asyncio.run(web_reference("网上查询黑旗600"))
    assert not sources and "失败" in status and "不能声称" in context["content"]


def test_web_request_keeps_knowledge_policy_but_tool_selection_is_model_driven():
    from agentdevstu.agents.knowledge import retrieve_knowledge
    assert asyncio.run(retrieve_knowledge(None, "查一下网上的信息", AsyncMock())) == ""


def test_business_tool_requirement_detects_data_questions_without_blocking_followups():
    from agentdevstu.tools.runtime import should_require_business_tool

    tool = SimpleNamespace(name="query_configured_records", description="查询数据能力：经销商。按条件查询经销商记录。")
    assert should_require_business_tool("状态为已终止的经销商", [tool])
    assert should_require_business_tool("福建终止合作的经销商", [tool])
    assert should_require_business_tool("有哪些终止合作的", [tool])
    assert should_require_business_tool("杭州有几家门店", [tool])
    assert not should_require_business_tool("谢谢", [tool])
    assert not should_require_business_tool("把上面的结果总结一下", [tool])
    assert not should_require_business_tool("不要查询数据库，解释一下字段含义", [tool])
    assert not should_require_business_tool("状态不错，辛苦了", [tool])


def test_data_tool_schema_defaults_aliases_and_user_overrides(monkeypatch):
    from agentdevstu.api import conversations
    from agentdevstu.db.models import DataCapability, DataSource

    cap_id = uuid.uuid4()
    ds_id = uuid.uuid4()
    cap = SimpleNamespace(
        id=cap_id,
        name="经销商",
        description="用户若不指定合作状态，则默认查询状态为“合作中”的经销商，如果用户指定，则按指定状态查询",
        query_template="SELECT * FROM dealers WHERE (:status IS NULL OR status=:status) AND (:province IS NULL OR province=:province)",
        input_schema={"properties": {
            "status": {
                "type": "string",
                "description": "合作状态",
                "enum": ["合作中", "已终止", "已删除"],
                "default": "合作中",
                "x-aliases": {"已终止": ["终止合作", "已解约", "解约"]},
            },
            "province": {"type": "string", "description": "省份"},
        }},
    )
    ds = SimpleNamespace(id=ds_id, name="DMS", description="经销商数据源")
    cap_db = SimpleNamespace(query_template=cap.query_template, row_limit=1000, timeout_seconds=30)
    ds_db = SimpleNamespace(type="postgresql", config={}, credential_id=None)

    class FakeSession:
        async def get(self, model, item_id):
            if model is DataCapability and item_id == cap_id:
                return cap_db
            if model is DataSource and item_id == ds_id:
                return ds_db
            return None

    class FakeSessionContext:
        async def __aenter__(self):
            return FakeSession()
        async def __aexit__(self, *_args):
            return None

    execute = AsyncMock(return_value={"success": True, "data": [], "row_count": 0})
    engine_module = importlib.import_module("agentdevstu.db.engine")
    monkeypatch.setattr(engine_module, "async_session_factory", lambda: FakeSessionContext())
    monkeypatch.setattr(conversations, "execute_query", execute)

    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content='{"status":"合作中","province":"福建"}')))
    tool = conversations._build_data_tools(
        [{"capability": cap, "data_source": ds}],
        model=model,
        user_query="福建终止合作的经销商",
        context=[],
    )[0]
    asyncio.run(tool.ainvoke({"province": "福建"}))
    assert execute.await_args.kwargs["params"] == {"status": "已终止", "province": "福建"}

    default_tool = conversations._build_data_tools([{"capability": cap, "data_source": ds}], user_query="福建经销商", context=[])[0]
    asyncio.run(default_tool.ainvoke({"province": "福建"}))
    assert execute.await_args.kwargs["params"] == {"status": "合作中", "province": "福建"}

    explicit_tool = conversations._build_data_tools([{"capability": cap, "data_source": ds}], user_query="查询全部状态的福建经销商", context=[])[0]
    asyncio.run(explicit_tool.ainvoke({"status": None, "province": "福建"}))
    assert execute.await_args.kwargs["params"] == {"status": None, "province": "福建"}


def test_input_schema_validation_preserves_generic_parameter_metadata():
    from agentdevstu.api.schema_generation import validate_result

    schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "状态",
                "enum": ["A", "B"],
                "default": "A",
                "x-aliases": {"B": ["bee"]},
                "x-clear-terms": ["全部状态"],
            }
        },
        "required": [],
        "additionalProperties": False,
    }
    result = validate_result(json.dumps(schema), ["status"])
    prop = result["properties"]["status"]
    assert prop["enum"] == ["A", "B"]
    assert prop["default"] == "A"
    assert prop["x-aliases"] == {"B": ["bee"]}
    assert prop["x-clear-terms"] == ["全部状态"]
