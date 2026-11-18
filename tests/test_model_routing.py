"""场景模型调度：resolve 解析链与 /api/config/model-routing API。"""

import asyncio

import pytest

from cortexa.config import llm_providers
from cortexa.config.llm_providers import resolve_model_name
from cortexa.web.app import ModelRoutingPayload, delete_provider, list_model_routing, save_model_routing


class FakeAgent:
    def __init__(self, model=None):
        self.model = model


@pytest.fixture()
def routing_config(monkeypatch):
    config = {
        "llm": {
            "default": "mimo",
            "providers": {"mimo": {"kind": "openai", "model": "m"}, "zhipu": {"kind": "openai", "model": "g"}},
        },
        "model_routing": {"title": "zhipu"},
    }
    monkeypatch.setattr(llm_providers, "_load_yaml_config", lambda path=None: config)
    return config


def test_routing_override_beats_agent_model(routing_config):
    assert resolve_model_name(FakeAgent("mimo"), "title") == "zhipu"


def test_unset_and_agent_choice_follow_agent_model(routing_config):
    # 未配置的场景：缺省策略 agent → agent.model
    assert resolve_model_name(FakeAgent("mimo"), "memory_extraction") == "mimo"
    # 显式选「跟随智能体」
    routing_config["model_routing"]["memory_extraction"] = "agent"
    assert resolve_model_name(FakeAgent("mimo"), "memory_extraction") == "mimo"


def test_agent_without_model_falls_back_to_caller_fallback(routing_config):
    assert resolve_model_name(FakeAgent(None), "chat_reply", "workspace-default") == "workspace-default"
    # 没有任何回退 → None → create_llm(None) 全局默认（与旧行为一致）
    assert resolve_model_name(None, "chat_reply") is None


def test_global_policy_ignores_fallback(routing_config):
    assert resolve_model_name(None, "rag_summary", "should-be-ignored") is None


def test_stale_provider_reference_falls_back_to_agent_model(routing_config):
    routing_config["model_routing"]["title"] = "deleted-provider"
    assert resolve_model_name(FakeAgent("mimo"), "title") == "mimo"


def test_workspace_scenario_prefers_fallback_then_routing(routing_config):
    assert resolve_model_name(None, "sql_draft", "ws-provider") == "ws-provider"
    routing_config["model_routing"]["sql_draft"] = "zhipu"
    assert resolve_model_name(None, "sql_draft", "ws-provider") == "zhipu"


def test_no_scenario_keeps_legacy_chain(routing_config):
    assert resolve_model_name(FakeAgent("mimo")) == "mimo"
    assert resolve_model_name(None, None, "ws-provider") == "ws-provider"


@pytest.fixture()
def app_store(monkeypatch):
    config = {
        "llm": {"default": "mimo", "providers": {"mimo": {"kind": "openai"}, "zhipu": {"kind": "openai"}}},
        "model_routing": {"title": "zhipu"},
    }
    saved = {}
    monkeypatch.setattr("cortexa.web.app._load_config", lambda: config)
    monkeypatch.setattr("cortexa.web.app._save_config", lambda value: saved.update(value))
    return config, saved


def test_list_model_routing_reports_catalog_and_values(app_store):
    _, _ = app_store
    data = asyncio.run(list_model_routing())
    by_key = {s["key"]: s for s in data["scenarios"]}
    assert len(by_key) == 12
    assert by_key["title"]["value"] == "zhipu"
    assert by_key["title"]["default_label"] == "跟随智能体"
    assert by_key["rag_summary"]["default_label"] == "全局默认"
    assert by_key["sql_draft"]["default_label"] == "跟随工作空间默认"
    assert set(data["providers"]) == {"mimo", "zhipu"}


def test_save_model_routing_merges_and_clears(app_store):
    _, saved = app_store
    out = asyncio.run(
        save_model_routing(ModelRoutingPayload(routing={"memory_extraction": "zhipu", "title": ""}))
    )
    assert out["status"] == "ok"
    assert saved["model_routing"]["memory_extraction"] == "zhipu"
    assert "title" not in saved["model_routing"]  # 空串 = 清除覆盖，回到缺省策略
    assert saved["llm"]["default"] == "mimo"  # 非 routing 内容原样保留


def test_save_model_routing_rejects_unknown_scenario(app_store):
    with pytest.raises(Exception) as exc:
        asyncio.run(save_model_routing(ModelRoutingPayload(routing={"nope": "zhipu"})))
    assert "nope" in str(exc.value)


def test_save_model_routing_rejects_unknown_provider(app_store):
    with pytest.raises(Exception) as exc:
        asyncio.run(save_model_routing(ModelRoutingPayload(routing={"title": "ghost"})))
    assert "ghost" in str(exc.value)


def test_delete_provider_resets_routing_references(monkeypatch):
    config = {
        "llm": {"providers": {"mimo": {}, "zhipu": {}}},
        "model_routing": {"title": "zhipu", "memory_extraction": "mimo"},
    }
    saved = {}
    monkeypatch.setattr("cortexa.web.app._load_config", lambda: config)
    monkeypatch.setattr("cortexa.web.app._save_config", lambda value: saved.update(value))
    out = asyncio.run(delete_provider("zhipu"))
    assert out["status"] == "ok" and out["routing_reset"] == ["title"]
    assert "zhipu" not in saved["model_routing"]
    assert saved["model_routing"]["memory_extraction"] == "mimo"
