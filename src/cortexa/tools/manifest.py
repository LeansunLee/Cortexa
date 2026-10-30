"""Tool manifest schema — the registry contract for builtin/http/mcp tools.

一份 manifest 描述一个可装载工具的全部元数据：参数、端点、安全策略、配额与使用规则。
注册（API/前端表单）与装载（bindings）共用这里的一套 Pydantic 模型，保证两端一致。
"""

from __future__ import annotations

import enum
import ipaddress
import re
import socket
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

MAX_PARAMETERS = 20
MAX_RESPONSE_BYTES = 1_000_000
MAX_USAGE_RULES_CHARS = 2000

PARAM_TYPES = {"string", "integer", "number", "boolean"}


class ProviderType(enum.StrEnum):
    BUILTIN = "builtin"
    HTTP = "http"
    MCP = "mcp"


def assert_public_http_url(
    url: str,
    *,
    allow_loopback: bool = False,
    allow_private: bool = False,
    mode: Literal["register", "execute"] = "register",
) -> None:
    """Reject non-public or malformed http(s) endpoints (SSRF guard).

    注册时（mode=register）DNS 解析失败视为配置错误；
    执行时（mode=execute）解析失败直接放行——后续请求会以同样原因失败，
    避免守卫本身成为受限网络环境的故障点。
    allow_private 仅供管理员显式登记的内网/自建服务（企业内网 API）放行。
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("端点必须使用 http/https")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("端点不得携带用户信息、查询串或片段")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        if mode == "register":
            raise ValueError(f"端点主机无法解析：{parsed.hostname}") from exc
        return
    if allow_private or allow_loopback:
        return
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValueError("端点必须指向公网地址；内网服务请由管理员显式开启 allow_private")


class HttpAuthSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["none", "bearer", "header"] = "none"
    header: str = Field(default="Authorization", min_length=1, max_length=64)
    prefix: str = Field(default="Bearer", max_length=32)

    @field_validator("header")
    @classmethod
    def _valid_header(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]+", value):
            raise ValueError("认证头名称只能包含字母、数字与连字符")
        return value


class HttpEndpointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=8, max_length=1000)
    method: Literal["GET", "POST"] = "POST"
    auth: HttpAuthSpec = Field(default_factory=HttpAuthSpec)
    # 静态额外头（如 Accept）；值不得含敏感凭证，凭证一律走 auth+密文。
    headers: dict[str, str] = Field(default_factory=dict, max_length=8)
    # 仅限管理员知情的内网/自建服务（如 SearXNG）。默认拒绝私网地址；
    # 开启后仍拒绝畸形 URL，执行期不再复查私网段。
    allow_private: bool = False

    @field_validator("headers")
    @classmethod
    def _bounded_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for key, content in value.items():
            if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", key):
                raise ValueError(f"非法请求头名称：{key}")
            if len(content) > 300:
                raise ValueError(f"请求头 {key} 值过长")
        return value


class McpEndpointSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # streamable HTTP 远端服务器；stdio 子进程暂不开放前端注册。
    url: str = Field(min_length=8, max_length=1000)
    auth: HttpAuthSpec = Field(default_factory=HttpAuthSpec)
    tool_prefix: str = Field(default="", max_length=32)
    allow_private: bool = False

    @field_validator("tool_prefix")
    @classmethod
    def _valid_prefix(cls, value: str) -> str:
        if value and not TOOL_NAME_PATTERN.fullmatch(value):
            raise ValueError("工具前缀需满足小写工具名规范")
        return value


class ToolParameterSpec(BaseModel):
    """扁平参数定义——面向表单编辑；导出为 JSON Schema 供模型绑定。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str = Field(default="", max_length=500)
    required: bool = False
    default: Any = None
    max_length: int = Field(default=2000, gt=0, le=20000)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value):
            raise ValueError("参数名只能是字母/数字/下划线，且不以数字开头")
        return value

    @model_validator(mode="after")
    def _default_matches_type(self) -> "ToolParameterSpec":
        if self.default is None:
            return self
        checks = {
            "string": lambda v: isinstance(v, str),
            "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "boolean": lambda v: isinstance(v, bool),
        }
        if not checks[self.type](self.default):
            raise ValueError(f"参数 {self.name} 的默认值与类型 {self.type} 不匹配")
        return self


class ToolQuota(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_goal: int = Field(default=5, ge=1, le=20, description="单次目标执行内最多调用次数")


class ToolManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=64, description="工具调用名，小写下划线")
    description: str = Field(min_length=4, max_length=2000)
    provider_type: ProviderType = ProviderType.HTTP

    parameters: list[ToolParameterSpec] = Field(default_factory=list, max_length=MAX_PARAMETERS)
    aliases: list[str] = Field(default_factory=list, max_length=8)
    domains: list[str] = Field(default_factory=list, max_length=8)

    risk_level: Literal["low", "high"] = "low"
    requires_confirmation: bool = False
    timeout: float = Field(default=10, gt=0, le=60)
    input_budget: int = Field(default=4000, ge=500, le=20000, description="响应注入上下文的字符上限")
    quota: ToolQuota = Field(default_factory=ToolQuota)
    usage_rules: str = Field(default="", max_length=MAX_USAGE_RULES_CHARS)

    http: HttpEndpointSpec | None = None
    mcp: McpEndpointSpec | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not TOOL_NAME_PATTERN.fullmatch(value):
            raise ValueError("工具名需为 2-64 位小写字母/数字/下划线，字母开头")
        return value

    @field_validator("aliases", "domains")
    @classmethod
    def _bounded_texts(cls, value: list[str]) -> list[str]:
        for item in value:
            if not item.strip() or len(item) > 100:
                raise ValueError("别名/领域需为 1-100 字的非空文本")
        return value

    @model_validator(mode="after")
    def _provider_endpoint(self) -> "ToolManifest":
        if self.provider_type == ProviderType.HTTP and self.http is None:
            raise ValueError("provider_type=http 需要提供 http 端点")
        if self.provider_type == ProviderType.MCP and self.mcp is None:
            raise ValueError("provider_type=mcp 需要提供 mcp 端点")
        if self.risk_level == "high":
            self.requires_confirmation = True
        return self

    def args_model(self, *, secret_suffix: str = "Model"):
        """Build a pydantic args model for LangChain StructuredTool binding."""
        from pydantic import create_model

        python_types = {"string": str, "integer": int, "number": float, "boolean": bool}
        fields: dict[str, Any] = {}
        for parameter in self.parameters:
            annotation = python_types[parameter.type]
            if parameter.required:
                fields[parameter.name] = (annotation, Field(description=parameter.description or parameter.name))
            else:
                fields[parameter.name] = (
                    annotation | None,
                    Field(default=parameter.default, description=parameter.description or parameter.name),
                )
        model = create_model(self.name, __config_name__=f"{self.name}{secret_suffix}", **fields)  # type: ignore[call-overload]
        return model

    def input_schema(self) -> dict[str, Any]:
        schema = self.args_model().model_json_schema()
        # 可选参数生成 anyOf[T, null]；拍平为 T 保留 default，利于各 provider 工具协议兼容。
        properties = schema.get("properties", {})
        for name, spec in properties.items():
            options = spec.get("anyOf")
            if not options:
                continue
            non_null = [item for item in options if item.get("type") != "null"]
            if len(non_null) == 1:
                properties[name] = non_null[0]
        return schema


def manifest_from_record(record) -> ToolManifest:
    """Rebuild a manifest from a t_tools row (endpoint+manifest JSONB)."""
    payload = dict(record.manifest or {})
    payload.setdefault("name", record.name)
    payload.setdefault("description", record.description or record.name)
    payload.setdefault("provider_type", getattr(record, "provider_type", None) or "builtin")
    endpoint = record.endpoint or {}
    provider = payload["provider_type"]
    if provider == ProviderType.HTTP:
        payload.setdefault("http", endpoint)
    elif provider == ProviderType.MCP:
        payload.setdefault("mcp", endpoint)
    return ToolManifest.model_validate(payload)
