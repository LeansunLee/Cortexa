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


def test_edit_requires_correction_and_preserves_zero_importance(monkeypatch):
    from agentdevstu.api import memories as api
    from fastapi import HTTPException
    memory = SimpleNamespace(id=uuid.uuid4(),type="semantic",content="旧内容",importance=.7,revision=1,metadata_json={},source_type='manual')
    monkeypatch.setattr(api,'memory_access',AsyncMock(return_value=memory))
    monkeypatch.setattr(api,'event',AsyncMock())
    with pytest.raises(HTTPException) as error:
        asyncio.run(update_memory(memory.id,MemoryUpdate(type='focus',expected_revision=1),None))
    assert error.value.status_code==409
    result=asyncio.run(update_memory(memory.id,MemoryUpdate(importance=0,expected_revision=1),None))
    assert result['importance']==0 and result['content']=='旧内容' and result['revision']==2


def test_all_memory_labels_in_prompt():
    memories = [SimpleNamespace(type=t, content=t) for t in ("semantic", "episodic", "focus")]
    prompt = format_memories_for_prompt(memories)
    assert "[事实] semantic" in prompt
    assert "[事件] episodic" in prompt
    assert "[关注] focus" in prompt
