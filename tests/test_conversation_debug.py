import asyncio

import yaml

from agentdevstu.api.conversations import _conversation_debug_enabled, _debug_safe
from agentdevstu.web.app import ConversationDebugPayload, save_conversation_debug_config


def test_debug_payload_redacts_credentials_and_bounds_large_content():
    payload = _debug_safe({
        "api_key": "secret-key",
        "authorization": "Bearer secret",
        "token_count": 123,
        "content": "内容" * 3000,
    })

    assert payload["api_key"] == "[已隐藏]"
    assert payload["authorization"] == "[已隐藏]"
    assert payload["token_count"] == 123
    assert payload["content"].endswith("…（已截断）")


def test_debug_feature_flag_defaults_to_false_and_reads_yaml(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"features": {"conversation_debug_enabled": True}}), encoding="utf-8")
    monkeypatch.setattr("agentdevstu.api.conversations._CONFIG_PATH", config_path)
    assert _conversation_debug_enabled() is True

    config_path.write_text("llm: {}\n", encoding="utf-8")
    assert _conversation_debug_enabled() is False


def test_debug_config_update_preserves_existing_configuration(monkeypatch):
    config = {"llm": {"default": "provider-a", "providers": {"provider-a": {"model": "test"}}}}
    saved = {}
    monkeypatch.setattr("agentdevstu.web.app._load_config", lambda: config)
    monkeypatch.setattr("agentdevstu.web.app._save_config", lambda value: saved.update(value))

    result = asyncio.run(save_conversation_debug_config(ConversationDebugPayload(enabled=True)))

    assert result == {"status": "ok", "enabled": True}
    assert saved["features"]["conversation_debug_enabled"] is True
    assert saved["llm"] == config["llm"]
