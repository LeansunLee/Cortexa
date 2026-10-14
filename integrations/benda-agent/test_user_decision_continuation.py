"""Run in benda-agent/backend; every external model/tool is mocked."""

import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, PropertyMock
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from app.api.routes import public_agent as api
from app.data.session import ChatSession, SessionManager


class ContinuationTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_restores_completed_tools_and_answer_same_session(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as patches:
            patches.enter_context(patch("app.data.session.SESSIONS_DIR", Path(directory)))
            manager = SessionManager()
            patches.enter_context(patch.object(api, "session_manager", manager))
            logger = SimpleNamespace(
                **{
                    key: lambda *a, **k: None
                    for key in [
                        "turn_start",
                        "system_prompt",
                        "reasoning",
                        "tool_call_full",
                        "usage",
                        "error",
                        "assistant_response",
                        "turn_end",
                    ]
                }
            )
            patches.enter_context(patch.object(api, "get_logger", return_value=logger))
            patches.enter_context(
                patch.object(api, "get_llm_settings", return_value=SimpleNamespace(default_provider="test"))
            )
            patches.enter_context(patch.object(api, "build_chat_model", return_value=object()))
            patches.enter_context(patch.object(api, "get_provider_cfg", return_value=SimpleNamespace(model="test")))
            patches.enter_context(patch.object(api.source_manager, "get_agent_table_catalog", return_value=[]))
            patches.enter_context(patch.object(api.source_manager, "get_combined_schema", return_value=""))
            patches.enter_context(patch.object(api.source_manager, "list_all", return_value=[]))
            patches.enter_context(
                patch.object(type(api.source_manager), "first_source", new_callable=PropertyMock, return_value=None)
            )
            patches.enter_context(patch("app.mcp.client.load_mcp_tools", new=AsyncMock(return_value=([], [], None))))
            patches.enter_context(
                patch("app.mcp.registry.get_mcp_registry", return_value=SimpleNamespace(list=lambda: []))
            )
            original = [
                HumanMessage(content="原销售计划任务"),
                AIMessage(content="", tool_calls=[{"id": "query1", "name": "query", "args": {}}]),
                ToolMessage(content="已完成查询，销量42", tool_call_id="query1"),
            ]
            graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values={"messages": original})))
            patches.enter_context(patch.object(api, "build_graph", return_value=graph))
            turns = []

            async def stream(g, state, config, *args):
                turns.append((state, config))
                if len(turns) == 1:
                    yield {"type": "ask_user", "question": "选方向", "options": ["目标", "发货"]}
                else:
                    yield {"type": "text_delta", "content": "已按用户方向完成"}
                yield {"type": "done"}

            patches.enter_context(patch.object(api, "run_stream", side_effect=stream))
            request = SimpleNamespace(state=SimpleNamespace(request_id="test"))
            first = await api._run_public_agent_turn("原销售计划任务", request)
            self.assertEqual(first["status"], "awaiting_user")
            self.assertEqual(first["pending_ask"]["options"], ["目标", "发货"])
            sid = first["session_id"]
            # Simulate service restart and lost MemorySaver; only disk remains.
            patches.enter_context(patch.object(api, "session_manager", SessionManager()))
            graph.aget_state = AsyncMock(return_value=SimpleNamespace(values={}))
            second = await api._run_public_agent_turn("目标", request, resume_session_id=sid)
            self.assertEqual(second["session_id"], sid)
            self.assertEqual(second["status"], "completed")
            self.assertIn("销量42", str(turns[-1][0]["messages"]))
            self.assertIn("目标", turns[-1][0]["messages"][-1].content)
            self.assertEqual(turns[0][1]["configurable"]["thread_id"], turns[1][1]["configurable"]["thread_id"])
            with self.assertRaises(api.HTTPException):
                await api._run_public_agent_turn("目标", request, resume_session_id=sid)
            for invalid in ["../../a", "someone_else_123456789012", "public-agent-api_000000000000"]:
                with self.assertRaises(api.HTTPException):
                    await api._run_public_agent_turn("目标", request, resume_session_id=invalid)


    async def test_read_only_result_is_bound_to_answer_and_prior_question(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.data.session.SESSIONS_DIR',Path(directory)):
                manager=SessionManager()
                sid='public-agent-api_123456789abc'
                sess=manager.create(sid,owner='public-agent-api')
                sess.add_user('原任务')
                sess.add_assistant('选方向',events=[{'type':'ask_user','question':'选方向','options':['A','B']}],status='awaiting_user')
                sess.add_user('B')
                sess.add_assistant('完整报告',events=[{'type':'reasoning','text':'PRIVATE_THOUGHTS'}],status='completed')
                with patch.object(api,'session_manager',manager),patch.object(api,'_validate_api_key') as authenticate:
                    result=await api.public_agent_result(sid,SimpleNamespace())
                authenticate.assert_called_once()
                self.assertEqual(result['answered_prompt'],'B')
                self.assertEqual(result['prior_question'],'选方向')
                self.assertEqual(result['answer'],'完整报告')
                self.assertNotIn('PRIVATE_THOUGHTS',json.dumps(result))

if __name__ == "__main__":
    unittest.main()
