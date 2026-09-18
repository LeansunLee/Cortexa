import asyncio
import importlib
from unittest.mock import AsyncMock, Mock

import pytest

from agentdevstu.collaboration.manager import _execute_target_agent
from agentdevstu.collaboration.schemas import AgentHandoff
from agentdevstu.db.models import Agent


@pytest.mark.parametrize("success", [True, False])
def test_proxy_collaboration_calls_external_executor_not_local_model(monkeypatch, success):
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(importlib.import_module("agentdevstu.db.engine"), "async_session_factory", lambda: session)
    execute = AsyncMock(return_value={"success": success, "output_data": {"answer": "杭州本月交付数据"}, "error": "外部失败"})
    monkeypatch.setattr("agentdevstu.agents.proxy_executor.execute_proxy_agent", execute)
    model = Mock(side_effect=AssertionError("Proxy 不应调用本地模型"))
    monkeypatch.setattr("agentdevstu.config.llm_providers.create_llm", model)
    callback = AsyncMock()
    agent = Agent(name="侯子豪", agent_type="proxy")
    handoff = AgentHandoff(source_agent_id="source", target_agent_id="target", task="查询交付量", question="杭州本月黑旗600交付量")
    coroutine = _execute_target_agent(agent, "", handoff, on_token=callback)
    if success:
        assert asyncio.run(coroutine) == "杭州本月交付数据"
        callback.assert_awaited_once_with("杭州本月交付数据")
    else:
        with pytest.raises(RuntimeError, match="外部失败"):
            asyncio.run(coroutine)
        callback.assert_not_called()
    model.assert_not_called()
    assert "杭州本月黑旗600交付量" in execute.call_args.args[1]["input"]
