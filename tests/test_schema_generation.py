import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from agentdevstu.api import schema_generation as api
from agentdevstu.security.access import Actor, current_actor


def schema():
    return {
        "type": "object",
        "properties": {"keyword": {"type": "string", "description": "经销商名称关键词"}},
        "required": [],
        "additionalProperties": False,
    }


def test_generated_schema_rejects_invented_fields_and_unsupported_types():
    assert api.validate_result("```json\n" + json.dumps(schema()) + "\n```", ["keyword"]) == schema()
    with pytest.raises(ValueError):
        api.validate_result(json.dumps(schema()), ["city"])
    invalid = schema()
    invalid["properties"]["keyword"]["type"] = "object"
    with pytest.raises(ValueError):
        api.validate_result(json.dumps(invalid), ["keyword"])
    invalid = schema()
    invalid["required"] = ["invented"]
    with pytest.raises(ValueError):
        api.validate_result(json.dumps(invalid), ["keyword"])


@pytest.mark.parametrize("mode", ["success", "missing_source", "permission", "no_params", "bad_model", "timeout"])
def test_generation_access_and_failure_handling(monkeypatch, mode):
    ws = uuid.uuid4()
    source = uuid.uuid4()
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
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None if mode == "missing_source" else source),
        get=AsyncMock(return_value=SimpleNamespace(default_model_provider="space-model")),
    )
    model = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content="bad" if mode == "bad_model" else json.dumps(schema())))
    )
    if mode == "timeout":
        model.ainvoke.side_effect = TimeoutError
    create = __import__("unittest.mock", fromlist=["Mock"]).Mock(return_value=model)
    monkeypatch.setattr(api, "create_llm", create)
    payload = api.GenerateInput(
        name="经销商",
        description="按关键词查询，可选过滤",
        query_template="SELECT 1"
        if mode == "no_params"
        else "SELECT name FROM dealers WHERE :keyword IS NULL OR name = :keyword",
        data_source_id=source,
    )
    try:
        expected = {"missing_source": 404, "permission": 403, "bad_model": 502, "timeout": 504}.get(mode)
        if expected:
            with pytest.raises(HTTPException) as exc:
                asyncio.run(api.generate_input_schema(payload, db))
            assert exc.value.status_code == expected
        else:
            result = asyncio.run(api.generate_input_schema(payload, db))
            assert result["input_schema"]["properties"] == ({} if mode == "no_params" else schema()["properties"])
        if mode in ("no_params", "missing_source", "permission"):
            create.assert_not_called()
        if mode == "success":
            create.assert_called_once_with("space-model")
            reference = json.loads(model.ainvoke.call_args.args[0][1]["content"])
            assert set(reference) == {"name", "description", "sql", "parameters"}
            assert reference["parameters"] == ["keyword"]
    finally:
        current_actor.reset(token)
