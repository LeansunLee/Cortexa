import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from agentdevstu.api.memories import MemoryCreate, MemoryUpdate, update_memory
from agentdevstu.memory.service import format_memories_for_prompt


@pytest.mark.parametrize("schema", [MemoryCreate, MemoryUpdate])
@pytest.mark.parametrize("importance", [-0.01, 1.01, float("nan"), float("inf")])
def test_importance_rejects_invalid_values(schema, importance):
    with pytest.raises(ValidationError):
        schema(content="关注新品", importance=importance)


@pytest.mark.parametrize("importance", [0, 0.7, 1])
def test_focus_accepts_importance_boundaries(importance):
    payload = MemoryCreate(type="focus", content="关注新品", importance=importance)
    assert payload.type == "focus"
    assert payload.importance == importance


def test_edit_type_and_importance_including_zero():
    memory = SimpleNamespace(type="semantic", content="旧内容", importance=0.7)
    db = SimpleNamespace(get=AsyncMock(return_value=memory), flush=AsyncMock(), refresh=AsyncMock())
    result = asyncio.run(update_memory(uuid.uuid4(), MemoryUpdate(type="focus", importance=0), db))
    assert result.type == "focus"
    assert result.importance == 0
    assert result.content == "旧内容"
    db.flush.assert_awaited_once()


def test_all_memory_labels_in_prompt():
    memories = [SimpleNamespace(type=t, content=t) for t in ("semantic", "episodic", "focus")]
    prompt = format_memories_for_prompt(memories)
    assert "[事实] semantic" in prompt
    assert "[事件] episodic" in prompt
    assert "[关注] focus" in prompt
