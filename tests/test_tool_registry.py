"""工具注册表单元测试：manifest 校验、SSRF 守卫、HTTP 执行器、不可信输出边界。"""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from cortexa.tools.manifest import (
    HttpEndpointSpec,
    ToolManifest,
    ToolParameterSpec,
    assert_public_http_url,
)
from cortexa.tools.registry import UNTRUSTED_NOTICE, _bounded_result, build_http_tool, manifest_from_record


def _manifest(**overrides):
    from cortexa.tools.manifest import HttpAuthSpec
    base = dict(
        name="weather_query",
        description="查询城市实时天气",
        provider_type="http",
        parameters=[ToolParameterSpec(name="city", type="string", description="城市名", required=True, max_length=100)],
        http=HttpEndpointSpec(url="https://api.example.com/weather", method="GET",
                              auth=HttpAuthSpec(type="bearer")),
    )
    base.update(overrides)
    return ToolManifest(**base)


def _record(manifest=None, secret=""):
    manifest = manifest or _manifest()
    from cortexa.db.encryption import encrypt_value
    return SimpleNamespace(
        id="x", name=manifest.name, description=manifest.description,
        provider_type="http",
        endpoint=manifest.http.model_dump(mode="json"),
        manifest=manifest.model_dump(mode="json", exclude={"http", "mcp"}),
        auth_secret_enc=encrypt_value(secret) if secret else None,
    )


# --- manifest 校验 ---

def test_manifest_rejects_bad_name_and_missing_endpoint():
    for name in ["Web_Search", "1abc", "a", "a" * 65, "bad name"]:
        with pytest.raises(Exception):
            _manifest(name=name)
    with pytest.raises(Exception):
        ToolManifest(name="http_tool", description="缺少端点", provider_type="http")
    with pytest.raises(Exception):
        ToolManifest(name="mcp_tool", description="缺少端点", provider_type="mcp")


def test_manifest_high_risk_forces_confirmation_and_reserved_guard():
    manifest = _manifest(risk_level="high")
    assert manifest.requires_confirmation is True
    from cortexa.tools.registry import RESERVED_TOOL_NAMES
    assert "web_search" in RESERVED_TOOL_NAMES and "load_skill" in RESERVED_TOOL_NAMES


def test_parameter_default_type_mismatch_rejected():
    with pytest.raises(Exception):
        ToolParameterSpec(name="count", type="integer", default="many")


def test_args_model_roundtrip_and_schema():
    manifest = _manifest(parameters=[
        ToolParameterSpec(name="city", type="string", required=True),
        ToolParameterSpec(name="days", type="integer", default=3),
    ])
    model = manifest.args_model()
    instance = model(city="北京")
    assert instance.city == "北京" and instance.days == 3
    schema = manifest.input_schema()
    assert schema["required"] == ["city"]
    assert schema["properties"]["days"]["type"] == "integer"


# --- SSRF 守卫 ---

def test_ssrf_guard_rejects_malformed_and_private_targets(monkeypatch):
    for url in [
        "ftp://example.com",
        "https://u:p@example.com",
        "https://example.com/?x=1",
        "https://example.com#frag",
    ]:
        with pytest.raises(ValueError):
            assert_public_http_url(url)

    real_getaddrinfo = __import__("socket").getaddrinfo
    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "internal.example":
            return [(2, 1, 6, "", ("10.0.0.5", 0))]
        if host == "public.example":
            return [(2, 1, 6, "", ("93.184.216.34", 0))]
        return real_getaddrinfo(host, *args, **kwargs)
    monkeypatch.setattr("cortexa.tools.manifest.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError):
        assert_public_http_url("https://internal.example/api")
    assert_public_http_url("https://internal.example/api", allow_private=True)
    assert_public_http_url("https://public.example/api")


# --- 不可信输出边界 ---

def test_bounded_result_parses_truncates_and_marks_untrusted():
    result = _bounded_result(json.dumps({"ok": True, "items": [1, 2]}), 4000)
    assert result["ok"] is True
    assert result["notice"] == UNTRUSTED_NOTICE

    huge = json.dumps({"data": "字" * 9000})
    result = _bounded_result(huge, 2000)
    assert result["truncated"] is True and len(result["data"]) <= 2000
    assert UNTRUSTED_NOTICE in result["notice"]

    result = _bounded_result("纯文本响应", 4000)
    assert result["data"] == "纯文本响应"
    result = _bounded_result("", 4000)
    assert result.get("empty") is True


# --- HTTP 执行器 ---

def test_http_tool_success_quota_and_cache(monkeypatch):
    record = _record(_manifest(quota={"per_goal": 2}), secret="sk-secret")
    calls = []
    original = httpx.AsyncClient
    def handler(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer sk-secret"
        return httpx.Response(200, json={"temp": "28C"})
    def factory(**kw):
        return original(**kw, transport=httpx.MockTransport(handler))
    monkeypatch.setattr("cortexa.tools.registry.httpx", httpx)
    monkeypatch.setattr(httpx, "AsyncClient", factory)

    tool = build_http_tool(record)
    first = asyncio.run(tool.ainvoke({"city": "北京"}))
    assert first["temp"] == "28C" and first["notice"] == UNTRUSTED_NOTICE
    second = asyncio.run(tool.ainvoke({"city": "北京"}))
    assert second == first and len(calls) == 1  # 命中缓存
    third = asyncio.run(tool.ainvoke({"city": "上海"}))
    assert third["temp"] == "28C"
    fourth = asyncio.run(tool.ainvoke({"city": "广州"}))
    assert "预算" in fourth["error"] and len(calls) == 2

    out = json.dumps(first, ensure_ascii=False)
    assert "sk-secret" not in out


def test_http_tool_error_mapping(monkeypatch):
    original = httpx.AsyncClient
    def make_handler(status):
        def handler(request):
            return httpx.Response(status, json={})
        return handler
    def factory_for(status):
        return lambda **kw: original(**kw, transport=httpx.MockTransport(make_handler(status)))
    monkeypatch.setattr("cortexa.tools.registry.httpx", httpx)
    for status, expected in [(401, "鉴权失败"), (429, "额度不足或被限流"), (500, "500")]:
        monkeypatch.setattr(httpx, "AsyncClient", factory_for(status))
        tool = build_http_tool(_record())
        result = asyncio.run(tool.ainvoke({"city": "北京"}))
        assert expected in result["error"], result


def test_manifest_from_record_roundtrip():
    manifest = _manifest()
    record = _record(manifest, secret="sk")
    rebuilt = manifest_from_record(record)
    assert rebuilt.name == manifest.name
    assert rebuilt.http.url == manifest.http.url
    assert rebuilt.quota.per_goal == manifest.quota.per_goal
    assert rebuilt.parameters[0].name == "city"
