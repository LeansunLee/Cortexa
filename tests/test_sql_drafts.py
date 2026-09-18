import asyncio
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from agentdevstu.api import sql_drafts as api
from agentdevstu.data.sql_drafts import validate_sql
from agentdevstu.security.access import Actor, current_actor

SCHEMA = {
    "type": "object",
    "properties": {"keyword": {"type": "string", "description": "关键词"}},
    "required": [],
    "additionalProperties": False,
}
SQL = "SELECT name FROM dealers WHERE CAST(:keyword AS TEXT) IS NULL OR name = :keyword"


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM t",
        "SELECT 1; SELECT 2",
        "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x",
        "SELECT * INTO backup FROM t",
        "SELECT 1 FOR UPDATE",
        "SELECT /*!50000 INTO OUTFILE */ 1",
    ],
)
def test_read_only_sql_guard(sql):
    with pytest.raises(ValueError):
        validate_sql(sql)


def test_sql_schema_and_typed_parameters():
    assert validate_sql("SELECT 'delete', 1 AS \"update\" -- comment\n")[1] == []
    assert validate_sql(SQL)[1] == ["keyword"]
    assert api.checked_pair(SQL, SCHEMA) == (SQL, SCHEMA)
    with pytest.raises(HTTPException):
        api.checked_pair(SQL, {**SCHEMA, "properties": {}})
    assert api.bind_values(SCHEMA, {}) == {"keyword": None}
    with pytest.raises(HTTPException):
        api.bind_values(SCHEMA, {"keyword": 1})
    with pytest.raises(HTTPException):
        api.bind_values({**SCHEMA, "required": ["keyword"]}, {})
    with pytest.raises(HTTPException):
        api.bind_values(SCHEMA, {"unknown": "x"})
    with pytest.raises(ValueError):
        validate_sql("SELECT ':fake'")


@pytest.mark.parametrize("mode", ["success", "permission", "foreign_source", "invalid_model", "timeout"])
def test_sql_rewrite_contract(monkeypatch, mode):
    ws, source = uuid.uuid4(), uuid.uuid4()
    a = Actor(
        uuid.uuid4(),
        "test",
        False,
        False,
        1,
        memberships={ws: {"permissions": set() if mode == "permission" else {"data.manage"}}},
        workspace_id=ws,
    )
    token = current_actor.set(a)
    source_row = SimpleNamespace(id=source, type="postgres", credential_id=None)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None if mode == "foreign_source" else source_row),
        get=AsyncMock(return_value=SimpleNamespace(default_model_provider="space-model")),
    )
    execute = AsyncMock(
        return_value={"success": True, "row_count": 0, "rows": [], "columns": ["name"], "truncated": False}
    )
    monkeypatch.setattr(api, "execute_draft", execute)
    response = {"query_template": SQL, "input_schema": SCHEMA, "explanation": "保留返回列，增加可选关键词"}
    if mode == "invalid_model":
        response["input_schema"] = {**SCHEMA, "properties": {}}
    model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content=json.dumps(response))))
    if mode == "timeout":
        model.ainvoke.side_effect = TimeoutError
    create = Mock(return_value=model)
    monkeypatch.setattr(api, "create_llm", create)
    try:
        payload = api.RewriteInput(
            data_source_id=source, description="支持可选关键词", query_template="SELECT name FROM dealers"
        )
        expected = {"permission": 403, "foreign_source": 404}.get(mode)
        if expected:
            with pytest.raises(HTTPException) as exc:
                asyncio.run(api.parameterize(payload, db))
            assert exc.value.status_code == expected
        else:
            result = asyncio.run(api.parameterize(payload, db))
            assert result["query_template"]
            assert result["input_schema"]["type"] == "object"
            assert result["input_schema"]["additionalProperties"] is False
            assert "name" in result["input_schema"]["properties"]
            assert "rewritten_query" in result["query_template"]
            assert "全部查询结果字段" in result["explanation"]
        create.assert_not_called()
        if mode not in ("permission", "foreign_source"):
            execute.assert_awaited_once_with(source_row, None, "SELECT name FROM dealers", {})
    finally:
        current_actor.reset(token)


def test_ai_failure_falls_back_without_504_when_rules_cannot_generate_params(monkeypatch):
    ws, source = uuid.uuid4(), uuid.uuid4()
    a = Actor(uuid.uuid4(), "test", False, False, 1, memberships={ws: {"permissions": {"data.manage"}}}, workspace_id=ws)
    token = current_actor.set(a)
    source_row = SimpleNamespace(id=source, type="postgres", credential_id=None)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=source_row),
        get=AsyncMock(return_value=SimpleNamespace(default_model_provider="space-model")),
    )
    execute = AsyncMock(
        return_value={"success": True, "row_count": 0, "rows": [], "columns": [], "truncated": False}
    )
    monkeypatch.setattr(api, "execute_draft", execute)
    model = SimpleNamespace(ainvoke=AsyncMock(side_effect=TimeoutError))
    create = Mock(return_value=model)
    monkeypatch.setattr(api, "create_llm", create)
    try:
        payload = api.RewriteInput(data_source_id=source, query_template="SELECT 1")
        result = asyncio.run(api.parameterize(payload, db))
        assert result["query_template"] == "SELECT 1"
        assert result["input_schema"] == {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        assert "AI 增强未在限定时间内完成" in result["explanation"]
        create.assert_called_once_with("space-model")
    finally:
        current_actor.reset(token)


def test_rule_rewrite_parameterizes_all_result_columns():
    sql = """SELECT dealer_name, dealer_code
FROM dealers
WHERE dealer_name = '华东经销商'
  AND status = 'active'"""
    result = api.build_rule_rewrite(sql, "postgres", {"columns": ["dealer_name", "dealer_code"]})
    assert "SELECT * FROM (" in result["query_template"]
    assert "WHERE dealer_name = '华东经销商'" in result["query_template"]
    assert "status = 'active'" in result["query_template"]
    assert "CAST(:dealer_name AS TEXT) IS NULL" in result["query_template"]
    assert 'CAST("dealer_name" AS TEXT) ILIKE' in result["query_template"]
    assert "CAST(:dealer_code AS TEXT) IS NULL" in result["query_template"]
    assert 'CAST("dealer_code" AS TEXT) ILIKE' in result["query_template"]
    assert result["input_schema"] == {
        "type": "object",
        "properties": {
            "dealer_name": {"type": "string", "description": "用于筛选结果字段：dealer_name"},
            "dealer_code": {"type": "string", "description": "用于筛选结果字段：dealer_code"},
        },
        "required": [],
        "additionalProperties": False,
    }
    assert "全部查询结果字段" in result["explanation"]


def test_rule_rewrite_uses_result_columns_without_touching_inner_strings_and_comments():
    sql = """SELECT 'dealer_name = ''华东经销商''' AS label, dealer_name
FROM dealers
WHERE status = 'active' -- dealer_code = 'SHOULD_NOT_CHANGE'
  AND note LIKE 'VIP'"""
    result = api.build_rule_rewrite(sql, "postgres", {"columns": ["label", "dealer_name"]})
    assert "'dealer_name = ''华东经销商'''" in result["query_template"]
    assert "-- dealer_code = 'SHOULD_NOT_CHANGE'" in result["query_template"]
    assert set(result["input_schema"]["properties"]) == {"label", "dealer_name"}




def test_rule_rewrite_parameterizes_duplicate_result_columns_with_aliases():
    result = api.build_rule_rewrite("SELECT 1 AS id, 2 AS id", "postgres", {"columns": ["id", "id"]})
    assert 'AS rewritten_query("id", "id_2")' in result["query_template"]
    assert set(result["input_schema"]["properties"]) == {"id", "id_2"}
    assert "独立参数" in result["explanation"]


def test_ai_rewrite_requires_original_sql_to_execute(monkeypatch):
    ws, source = uuid.uuid4(), uuid.uuid4()
    a = Actor(uuid.uuid4(), "test", False, False, 1, memberships={ws: {"permissions": {"data.manage"}}}, workspace_id=ws)
    token = current_actor.set(a)
    source_row = SimpleNamespace(id=source, type="postgres", credential_id=None)
    db = SimpleNamespace(scalar=AsyncMock(return_value=source_row), get=AsyncMock())
    execute = AsyncMock(
        return_value={
            "success": False,
            "row_count": 0,
            "rows": [],
            "columns": [],
            "truncated": False,
            "error": "relation does not exist",
        }
    )
    create = Mock()
    monkeypatch.setattr(api, "execute_draft", execute)
    monkeypatch.setattr(api, "create_llm", create)
    try:
        payload = api.RewriteInput(
            data_source_id=source,
            description="支持可选关键词",
            query_template="SELECT name FROM missing_table",
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(api.parameterize(payload, db))
        assert exc.value.status_code == 422
        assert "原始 SQL 测试未通过" in exc.value.detail
        execute.assert_awaited_once_with(source_row, None, "SELECT name FROM missing_table", {})
        create.assert_not_called()
        db.get.assert_not_called()
    finally:
        current_actor.reset(token)


def test_draft_tests_exact_unsaved_pair_without_saving(monkeypatch):
    ws, source = uuid.uuid4(), uuid.uuid4()
    a = Actor(
        uuid.uuid4(), "test", False, False, 1, memberships={ws: {"permissions": {"data.manage"}}}, workspace_id=ws
    )
    token = current_actor.set(a)
    row = SimpleNamespace(id=source, type="postgres", credential_id=None)
    db = SimpleNamespace(scalar=AsyncMock(return_value=row), add=Mock())
    execute = AsyncMock(
        return_value={"success": True, "row_count": 0, "rows": [], "columns": ["name"], "truncated": False}
    )
    monkeypatch.setattr(api, "execute_draft", execute)
    try:
        payload = api.DraftTestInput(
            data_source_id=source, query_template=SQL, input_schema=SCHEMA, params={"keyword": "a"}
        )
        result = asyncio.run(api.test_draft(payload, db))
        assert result["success"]
        execute.assert_awaited_once_with(row, None, SQL, {"keyword": "a"})
        assert db.add.call_args.args[0].action == "data.draft_test"
    finally:
        current_actor.reset(token)


@pytest.mark.skipif(not os.getenv("WORK_TEST_DATABASE_URL"), reason="PostgreSQL read-only preview integration")
def test_real_readonly_preview():
    from sqlalchemy.engine import make_url

    from agentdevstu.data.sql_drafts import execute_draft
    from agentdevstu.db.encryption import encrypt_dict

    url = make_url(os.environ["WORK_TEST_DATABASE_URL"])
    source = SimpleNamespace(
        type="postgres", config={"host": url.host, "port": url.port or 5432, "database": url.database}
    )
    encrypted = encrypt_dict({"username": url.username, "password": url.password})

    async def run():
        result = await execute_draft(
            source,
            encrypted,
            "SELECT current_setting('transaction_read_only') AS readonly, "
            "CAST(:keyword AS TEXT) AS keyword, n FROM generate_series(1, 60) n",
            {"keyword": "示例"},
        )
        assert result["success"], result
        assert result["truncated"] and result["row_count"] == 50
        assert result["rows"][0][:2] == ["on", "示例"]
        result = await execute_draft(source, encrypted, "SELECT missing_column", {})
        assert not result["success"] and not result["rows"]
        assert url.password not in result["error"]

    asyncio.run(run())
