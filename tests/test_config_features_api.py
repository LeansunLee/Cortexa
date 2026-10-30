"""平台功能开关 API：目录化校验与 config.yaml 写回。"""

import asyncio

import pytest

from cortexa.web.app import FeaturesPayload, list_feature_flags, save_feature_flags


@pytest.fixture()
def store(monkeypatch):
    config = {"features": {"skills_enabled": False}, "llm": {"default": "mimo", "providers": {}}}
    saved = {}
    monkeypatch.setattr("cortexa.web.app._load_config", lambda: config)
    monkeypatch.setattr("cortexa.web.app._save_config", lambda value: saved.update(value))
    return config, saved


def test_list_features_reports_effective_values(store):
    config, _ = store
    by_key = {f["key"]: f for f in asyncio.run(list_feature_flags())["features"]}
    assert len(by_key) == 7 and "goal_proxy_enabled" not in by_key
    assert by_key["skills_enabled"]["value"] is False  # 文件显式值
    assert by_key["goal_execution_enabled"]["value"] is False and by_key["goal_execution_enabled"]["default"] is False
    assert by_key["external_tools_enabled"]["value"] is True and by_key["external_tools_enabled"]["default"] is True


def test_save_feature_flags_writes_back_and_preserves_config(store):
    config, saved = store
    out = asyncio.run(
        save_feature_flags(FeaturesPayload(features={"goal_collaboration_enabled": True, "skills_enabled": True}))
    )
    assert out["status"] == "ok" and out["features"]["goal_collaboration_enabled"] is True
    assert saved["features"]["goal_collaboration_enabled"] is True
    assert saved["llm"]["default"] == "mimo"  # 非 features 内容原样保留


def test_save_feature_flags_rejects_unknown_keys(store):
    with pytest.raises(Exception) as exc:
        asyncio.run(save_feature_flags(FeaturesPayload(features={"goal_proxy_enabled": True})))
    assert "goal_proxy_enabled" in str(exc.value)
