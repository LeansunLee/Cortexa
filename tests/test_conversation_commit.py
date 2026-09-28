import asyncio
import uuid
from types import SimpleNamespace
from cortexa.api.conversations import create_conversation, delete_conversation
from cortexa.api.schemas import ConversationCreate


def test_create_and_delete_commit_before_returning_success(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("cortexa.memory.lifecycle.source_deleted",AsyncMock())
    actions = []
    class Session:
        def add(self, obj): actions.append('add')
        async def flush(self): actions.append('flush')
        async def refresh(self, obj): actions.append('refresh')
        async def commit(self): actions.append('commit')
        async def get(self, kind, ident): return SimpleNamespace(id=ident)
        async def delete(self, obj): actions.append('delete')
    session = Session()
    asyncio.run(create_conversation(ConversationCreate(agent_id=uuid.uuid4()), session, str(uuid.uuid4())))
    assert actions == ['add','flush','refresh','commit']
    actions.clear()
    asyncio.run(delete_conversation(uuid.uuid4(), session))
    assert actions == ['delete','commit']
