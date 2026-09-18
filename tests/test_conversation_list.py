import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from agentdevstu.api.conversations import list_conversations, _load_agent_capabilities


def test_list_returns_conversations_without_tool_filtering():
    workspace_id = uuid.uuid4()
    conversation = SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id, agent_id=uuid.uuid4(), title="销售政策讨论", status="active", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [conversation]))
    db.get.return_value = SimpleNamespace(name="销售部", avatar=None)
    result = asyncio.run(list_conversations(db, str(workspace_id)))
    assert len(result) == 1
    assert result[0].id == conversation.id
    assert result[0].title == "销售政策讨论"
    assert result[0].agent_name == "销售部"


def test_capability_loader_exposes_all_bound_tools_for_model_selection():
    caps = [SimpleNamespace(name=name, data_source_id=uuid.uuid4()) for name in ("经销商", "门店", "车型")]
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: caps))
    result = asyncio.run(_load_agent_capabilities(uuid.uuid4(), db, "查询杭州门店"))
    assert [item["capability"].name for item in result] == ["经销商", "门店", "车型"]
