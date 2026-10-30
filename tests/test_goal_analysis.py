"""目标入口模型拆解：JSON 解析、名册过滤与失败静默降级。"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from cortexa.runtime import goal_analysis
from cortexa.runtime.goal_analysis import GoalAnalysis, analyze_request, extract_json

ROSTER = [
    SimpleNamespace(name="数据分析部门", role="数据分析师", responsibilities="查询并分析历史销量、销售额"),
    SimpleNamespace(name="销售部", role="国内销售负责人", responsibilities="制定销售计划，完成销售目标"),
]


class FakeModel:
    def __init__(self, content=None, error=None):
        self._content = content
        self._error = error

    def model_copy(self, update=None):
        return self

    async def ainvoke(self, messages):
        if self._error:
            raise self._error
        return SimpleNamespace(content=self._content)


def patch_env(monkeypatch, model):
    monkeypatch.setattr(goal_analysis, "available_agents", lambda db, source: _async(ROSTER))
    monkeypatch.setattr(goal_analysis, "proxy_enabled", lambda a: True)
    monkeypatch.setattr(goal_analysis, "settings", lambda a: SimpleNamespace(allow_incoming=True))
    monkeypatch.setattr(goal_analysis, "create_llm", lambda name: model)


def _async(value):
    async def _inner():
        return value

    return _inner()


def payload():
    return {"goal": {"raw_request": "黑旗600在华南卖的咋样"}, "clarifications": []}


def test_extract_json_ignores_surrounding_prose():
    text = '好的，拆解如下：\n{"objective": "查询黑旗600华南销量", "agents": []} \n以上。'
    assert extract_json(text)["objective"] == "查询黑旗600华南销量"


def test_analyze_request_filters_agents_to_roster(monkeypatch):
    content = json.dumps(
        {
            "objective": "查询黑旗600车型在华南市场的销售表现",
            "agents": ["数据分析部门", "不存在的部门"],
            "domains": ["销量数据"],
            "clarification": None,
        },
        ensure_ascii=False,
    )
    patch_env(monkeypatch, FakeModel(content=content))
    out = asyncio.run(
        analyze_request(SimpleNamespace(model="Mimo"), payload(), object(), {"features": {}})
    )
    assert out == GoalAnalysis(
        objective="查询黑旗600车型在华南市场的销售表现",
        agents=["数据分析部门"],
        domains=["销量数据"],
        clarification=None,
    )


def test_analyze_request_accepts_role_and_dedupes(monkeypatch):
    # 模型偶尔回角色名或"名字｜角色"整行：都应映射回同一个名字并去重。
    content = json.dumps(
        {"objective": "查销量", "agents": ["数据分析师", "数据分析部门｜数据分析师", "国内销售负责人"]},
        ensure_ascii=False,
    )
    patch_env(monkeypatch, FakeModel(content=content))
    out = asyncio.run(
        analyze_request(SimpleNamespace(model="Mimo"), payload(), object(), {"features": {}})
    )
    assert out.agents == ["数据分析部门", "销售部"]


def test_analyze_request_disabled_flag_skips_model(monkeypatch):
    called = []

    def boom(name):
        called.append(name)
        raise AssertionError("should not call model")

    monkeypatch.setattr(goal_analysis, "create_llm", boom)
    monkeypatch.setattr(goal_analysis, "available_agents", lambda db, source: _async(ROSTER))
    monkeypatch.setattr(goal_analysis, "proxy_enabled", lambda a: True)
    monkeypatch.setattr(goal_analysis, "settings", lambda a: SimpleNamespace(allow_incoming=True))
    out = asyncio.run(
        analyze_request(
            SimpleNamespace(model="Mimo"), payload(), object(), {"features": {"goal_analysis_enabled": False}}
        )
    )
    assert out is None and not called


@pytest.mark.parametrize("model", [
    FakeModel(content="我不会输出JSON"),
    FakeModel(error=RuntimeError("provider down")),
])
def test_analyze_request_degrades_silently(monkeypatch, model):
    patch_env(monkeypatch, model)
    out = asyncio.run(
        analyze_request(SimpleNamespace(model="Mimo"), payload(), object(), {"features": {}})
    )
    assert out is None
