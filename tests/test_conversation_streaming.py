import asyncio
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from langchain_core.messages import AIMessageChunk

from agentdevstu.api.conversations import _stream_model_response


def test_first_token_arrives_before_model_finishes():
    async def scenario():
        released = asyncio.Event()

        class Model:
            async def astream(self, messages):
                yield AIMessageChunk(content="第一段")
                await released.wait()
                yield AIMessageChunk(content="第二段")

        stream = _stream_model_response(Model(), [])
        assert await asyncio.wait_for(anext(stream), 1) == ("第一段", None)
        released.set()
        assert await anext(stream) == ("第二段", None)
        token, response = await anext(stream)
        assert token is None
        assert response.content == "第一段第二段"
        await stream.aclose()

    asyncio.run(scenario())


def test_fragmented_tool_arguments_are_assembled_without_leaking_as_text():
    class Model:
        async def astream(self, messages):
            yield AIMessageChunk(content="", tool_call_chunks=[{"name": "query_dealers", "args": '{"city":', "id": "call_1", "index": 0}])
            yield AIMessageChunk(content="", tool_call_chunks=[{"name": None, "args": '"杭州"}', "id": None, "index": 0}])

    async def scenario():
        events = [event async for event in _stream_model_response(Model(), [])]
        assert len(events) == 1
        token, response = events[0]
        assert token is None
        assert response.tool_calls[0]["args"] == {"city": "杭州"}
        assert response.tool_calls[0]["id"] == "call_1"

    asyncio.run(scenario())


def test_text_blocks_exclude_reasoning_and_preserve_streamed_text():
    class Model:
        async def astream(self, messages):
            yield AIMessageChunk(content=[{"type": "reasoning", "text": "内部推理"}, {"type": "text", "text": "可见回复"}])

    async def scenario():
        events = [event async for event in _stream_model_response(Model(), [])]
        assert events[0] == ("可见回复", None)

    asyncio.run(scenario())


def test_collaboration_forwards_tokens_before_completion(monkeypatch):
    from agentdevstu.collaboration import manager

    async def scenario():
        released = asyncio.Event()

        async def execute(**kwargs):
            await kwargs["on_token"]("协作第一段")
            await released.wait()
            await kwargs["on_token"]("协作第二段")
            return "completed"

        monkeypatch.setattr(manager, "execute_handoff", execute)
        stream = manager.stream_handoff()
        assert await asyncio.wait_for(anext(stream), 1) == {"token": "协作第一段"}
        released.set()
        assert await anext(stream) == {"token": "协作第二段"}
        assert await anext(stream) == {"result": "completed"}
        await stream.aclose()

    asyncio.run(scenario())


def test_closing_collaboration_stream_cancels_target(monkeypatch):
    from agentdevstu.collaboration import manager

    async def scenario():
        cancelled = asyncio.Event()

        async def execute(**kwargs):
            try:
                await kwargs["on_token"]("已生成内容")
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(manager, "execute_handoff", execute)
        stream = manager.stream_handoff()
        await anext(stream)
        await stream.aclose()
        assert cancelled.is_set()

    asyncio.run(scenario())
