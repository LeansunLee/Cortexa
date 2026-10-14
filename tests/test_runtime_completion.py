import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessageChunk
from test_goal_loop import FakeModel, binding, make_loop, run

from cortexa.conversation.questions import ask_user_tool, question
from cortexa.runtime.capabilities import CapabilityType
from cortexa.runtime.completion import collaboration_status, completion_gap
from cortexa.runtime.loop import InvocationResult
from cortexa.runtime.observations import Observation
from cortexa.runtime.state import GoalState, GoalStatus


def ask_binding():
    tool = binding()
    tool.tool = ask_user_tool()

    async def invoke(args, action_id):
        public = question(args, SimpleNamespace(id=uuid.uuid4(), name="测试 Agent"))
        return InvocationResult(
            Observation("TOOL", "ask_user", action_id, "NOT_READY", metadata={"user_question": public}), "", {}
        )

    tool.invoke = AsyncMock(side_effect=invoke)
    return tool


def test_current_state_does_not_inherit_history_denial():
    state = GoalState()
    agent = binding(kind=CapabilityType.AGENT)
    assert "本轮 denied" in collaboration_status(state, [agent], [], []).content
    assert '"denied": []' in collaboration_status(state, [agent], []).content
    assert '"executable_tools": []' in collaboration_status(state, [agent], [], []).content
    assert completion_gap("数据分析协作前序已被拒绝，未取得销量基数", state, [agent], {})
    assert completion_gap("数据尚未取得，请确认后再执行", state, [agent], {})
    assert not completion_gap("协作并未被拒绝，本次方案已完成", state, [agent], {})
    state.denied_agents = ["actual-denial"]
    assert not completion_gap("协作已被拒绝，已完成其他部分", state, [agent], {})


def test_explicit_draft_request_and_unrelated_answer_do_not_force_collaboration():
    agent = binding(kind=CapabilityType.AGENT)
    assert not completion_gap(
        "销量数据未取得", GoalState(), [agent], {"goal": {"raw_request": "只给返利框架，不用查询"}}
    )
    assert not completion_gap("销量数据未取得", GoalState(), [agent], {"clarifications": ["接受标明数据缺失的草案"]})
    assert not completion_gap("销量数据未取得", GoalState(), [], {})
    assert not completion_gap("方案完成", GoalState(), [agent], {})


def test_missing_data_cannot_finish_without_decision_after_bounded_correction():
    loop, saves, _ = make_loop()
    agent, ask = binding(kind=CapabilityType.AGENT), ask_binding()
    model = FakeModel(
        [
            [AIMessageChunk(content="历史销量数据未取得，直接下发计划。")],
            [AIMessageChunk(content="销量基数仍缺，直接下发计划。")],
        ]
    )
    events = run(loop, model, [agent, ask])
    assert loop.state.status == GoalStatus.WAITING
    assert loop.state.reason == "user_decision_required"
    assert len(model.calls) == 2
    assert not any(e.get("type") == "token" for e in events)
    assert ask.invoke.await_count == 1
    assert loop.payload["pending_question"]["options"] == ["继续获取所需数据后完成任务", "接受标明数据缺失的草案"]
    assert any("本轮协作执行状态" in m.content for m in model.calls[0])
    assert any("上一轮草案尚未交付" in m.content for m in model.calls[1])
    assert saves[-1][1]["pending_question"]["id"] == loop.payload["pending_question"]["id"]


def test_correction_can_call_existing_user_question_tool():
    import json

    loop, _, _ = make_loop()
    agent, ask = binding(kind=CapabilityType.AGENT), ask_binding()
    request = {"question": "是否先获取销量数据？", "options": ["获取数据", "只给草案"]}
    model = FakeModel(
        [
            [AIMessageChunk(content="协作前序被拒绝，因此只给缺数草案。")],
            [
                AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": "ask_user",
                            "id": "choice",
                            "args": json.dumps(request, ensure_ascii=False),
                            "index": 0,
                        }
                    ],
                )
            ],
        ]
    )
    run(loop, model, [agent, ask])
    assert loop.state.reason == "user_decision_required"
    assert loop.payload["pending_question"]["question"] == request["question"]


def test_replayed_history_denial_requests_real_collaboration_approval(tmp_path, monkeypatch):
    import asyncio

    import pytest
    from test_goal_collaboration import URL, setup, start
    from test_goal_loop import tool_call

    from cortexa.api import goals

    if not URL:
        pytest.skip("Isolated PostgreSQL required")

    async def scenario():
        async with setup(tmp_path, monkeypatch) as ctx:

            async def prepare(*args, **kwargs):
                return [ask_binding()], []

            monkeypatch.setattr(goals, "prepare_bindings", prepare)
            model = FakeModel(
                [
                    [AIMessageChunk(content="数据分析部门协作前序被拒绝，未取得销量基数。")],
                    [
                        tool_call(
                            name="agent_" + ctx.targets[1].id.hex,
                            args={
                                "task": "查询目标车型最近三个月销量及各门店目标基数，按月和门店汇总；不要制定返利政策。"
                            },
                        )
                    ],
                ]
            )
            monkeypatch.setattr(goals, "create_llm", lambda *_: model)
            result = await start(ctx, "history-denial-regression", "给目标车型制定返利计划，分析销售数据")
            assert result["status"] == "WAITING", result
            assert result["reason"] == "collaboration_approval_required", result
            row = await ctx.store.get(ctx.conv, uuid.UUID(result["goal_id"]))
            assert row.state["denied_agents"] == []
            assert str(ctx.targets[1].id) in row.state["pending_agents"]
            assert len(model.calls) == 2

    asyncio.run(scenario())


def test_user_accepts_partial_draft_without_repeated_question():
    loop, _, _ = make_loop()
    loop.payload["clarifications"] = ["接受标明数据缺失的草案"]
    model = FakeModel([[AIMessageChunk(content="销量数据未取得，以下为标明缺失的草案。")]])
    ask = ask_binding()
    run(loop, model, [binding(kind=CapabilityType.AGENT), ask])
    assert loop.state.status == GoalStatus.COMPLETE
    ask.invoke.assert_not_awaited()


def test_budget_finalization_cannot_publish_fabricated_denial():
    loop, _, _ = make_loop()
    loop.payload["force_finalizing"] = True
    model = FakeModel([[AIMessageChunk(content="数据部门协作已被拒绝，无法取得明细。")]])
    run(loop, model, [binding(kind=CapabilityType.AGENT), ask_binding()])
    assert loop.state.reason == "user_decision_required"
    assert loop.state.status == GoalStatus.WAITING
    assert not loop.reply


def test_structured_completion_detects_missing_conditions_without_keywords():
    from test_goal_loop import tool_call

    loop, _, _ = make_loop()
    ask = ask_binding()
    model = FakeModel(
        [
            [tool_call(name="complete_task", args={"answer": "方案如下", "unresolved": ["财务授权尚未作出"]})],
            [
                tool_call(
                    name="ask_user", args={"question": "是否先取得财务授权？", "options": ["先确认", "仅保留建议"]}
                )
            ],
        ]
    )
    run(loop, model, [binding(kind=CapabilityType.AGENT), ask])
    assert loop.state.reason == "user_decision_required"
    assert loop.payload["pending_question"]["question"] == "是否先取得财务授权？"


def test_structured_completed_task_is_delivered_without_extra_model_call():
    from test_goal_loop import tool_call

    loop, _, _ = make_loop()
    loop.payload["observations"] = [{"source_type": "DATA", "action_id": "data1", "status": "SUCCESS"}]
    model = FakeModel(
        [
            [
                tool_call(
                    name="complete_task",
                    args={
                        "answer": "已完成计划",
                        "requirements": [
                            {"requirement": "经营基线", "kind": "data", "satisfied": True, "observation_ids": ["data1"]}
                        ],
                    },
                )
            ]
        ]
    )
    events = run(loop, model, [binding(kind=CapabilityType.AGENT), ask_binding()])
    assert loop.state.status == GoalStatus.COMPLETE
    assert len(model.calls) == 1
    assert any(e.get("content") == "已完成计划" for e in events)


def test_denial_is_checked_per_agent_even_when_other_agent_was_denied():
    state = GoalState(denied_agents=["A"])
    other = binding(kind=CapabilityType.AGENT)
    other.adapter.descriptor.name = "分析部门"
    other.adapter.descriptor.id = "agent:B"
    assert completion_gap("分析部门协作已被拒绝", state, [other], {})
