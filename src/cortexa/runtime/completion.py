"""Current execution facts override historical prose about collaboration."""

import json
import re
from typing import Literal

from langchain_core.messages import SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field


def collaboration_status(state, bindings, observations, active_bindings=None):
    agents = [b for b in bindings if b.adapter.descriptor.type == "AGENT"]
    if not agents and not state.denied_agents and not state.approved_agents:
        return None
    values = {
        "mode": state.collaboration_mode,
        "executable_tools": [b.tool.name for b in (bindings if active_bindings is None else active_bindings)],
        "available": [{"tool": b.tool.name, "name": b.adapter.descriptor.name} for b in agents],
        "approved": state.approved_agents,
        "denied": state.denied_agents,
        "used": state.used_agents,
        "results": [
            {"action_id": o.get("action_id"), "status": o.get("status"), "summary": o.get("summary")}
            for o in observations
            if o.get("source_type") == "AGENT"
        ],
    }
    return SystemMessage(
        content="本轮协作执行状态（服务器事实，优先于历史回复和记忆）："
        + json.dumps(values, ensure_ascii=False)
        + "\n历史目标的允许或拒绝不适用于本轮。拒绝只能依据本轮 denied；"
        "denied 为空表示没有参与者被拒绝，未调用不等于拒绝。询问模式下仍可发起 Agent 工具调用，平台会先让用户授权。"
        "任务需要的关键数据无法自行取得时，拆解具体数据需求并调用合适协作者；"
        "如需要用户确定范围、是否取数或接受缺失数据的草案，调用 ask_user 等待回答，不能直接结束任务。"
        "只有用户明确接受缺失条件、任务本来仅要求方法或草案、或预算收尾时，才可交付标明缺失的部分结果。"
    )


def completion_gap(text, state, bindings, payload):
    if not any(b.adapter.descriptor.type == "AGENT" for b in bindings):
        return None
    # Contradictory denial is actionable even when a partial draft was requested.
    denial_claims = re.findall(
        r"[^\n。；]{0,60}协作[^\n。；]{0,35}(?:拒绝|不允许)|"
        r"(?:拒绝|不允许)[^\n。；]{0,25}协作",
        text,
    )
    denial_claims = [
        claim for claim in denial_claims if not re.search(r"(?:没有|并未|未|并非|不是)(?:被|遭|受到)?拒绝", claim)
    ]
    contradicted = any(
        str(b.adapter.descriptor.id).removeprefix("agent:") not in state.denied_agents
        and any(
            name and name.casefold() in claim.casefold()
            for name in [b.adapter.descriptor.name, *b.adapter.descriptor.aliases]
        )
        for claim in denial_claims
        for b in bindings
        if b.adapter.descriptor.type == "AGENT"
    )
    if denial_claims and (not state.denied_agents or contradicted):
        return "回复声称协作被拒绝，但相应参与者未被本轮拒绝；历史描述不能决定当前授权。"
    request = payload.get("goal", {}).get("raw_request", "") + "\n" + "\n".join(payload.get("clarifications", []))
    if re.search(
        r"仅.*(?:草案|框架|方法)|只.*(?:草案|框架|方法)|不(?:用|要|需).*?(?:查询|查数|取数)|接受.*(?:缺失|草案)|先.*草案",
        request,
    ):
        return None
    # A conservative prose signal, not a claim that arbitrary omissions are detected.
    match = re.search(
        r"[^\n。；]{0,90}(?:(?:数据|销量|基数|明细)[^\n。；]{0,25}(?:未取得|仍缺|缺失|未获取|缺少)|"
        r"(?:未取得|仍缺|缺少|暂无|未获取)[^\n。；]{0,25}(?:数据|销量|基数|明细))[^\n。；]{0,90}",
        text,
    )
    return match.group(0).strip() if match else None


class RequiredEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: str = Field(min_length=1, max_length=300)
    kind: Literal["data", "policy", "preference", "lookup"] = "data"
    observation_ids: list[str] = Field(default_factory=list, max_length=12)
    user_text: str | None = Field(
        default=None, max_length=1000, description="偏好依据：逐字引用本轮任务或用户回答，不得编造"
    )
    satisfied: bool = False


class CompletionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=32768)
    requirements: list[RequiredEvidence] = Field(default_factory=list, max_length=16)
    unresolved: list[str] = Field(default_factory=list, max_length=16)
    denied_agents: list[str] = Field(default_factory=list, max_length=5)


def completion_tool():
    async def complete(**kwargs):
        return kwargs

    return StructuredTool.from_function(
        coroutine=complete,
        name="complete_task",
        args_schema=CompletionReview,
        description="完成本轮任务并提交最终答复。列出任务必需的数据/政策/偏好、实际 observation_ids 和是否满足；"
        "lookup 只声明检索是否命中，EMPTY 只支持无结果，不能冒充已取得事实。"
        "缺失信息必须放入 unresolved。拒绝名单只按本轮服务器状态填写。不能用历史回复或记忆冒充业务查询证据。",
    )


def partial_requested(payload):
    request = payload.get("goal", {}).get("raw_request", "") + "\n" + "\n".join(payload.get("clarifications", []))
    return bool(
        re.search(
            r"仅.*(?:草案|框架|方法)|只.*(?:草案|框架|方法)|不(?:用|要|需).*?(?:查询|查数|取数)|接受.*(?:缺失|草案)|先.*草案",
            request,
        )
    )


def validate_completion(review, state, payload):
    known = {o.get("action_id"): o for o in payload.get("observations", [])}
    missing = list(review.unresolved)
    if not set(review.denied_agents) <= set(state.denied_agents):
        return "完成声明把本轮未拒绝的参与者标记为拒绝。"
    for requirement in review.requirements:
        if not requirement.satisfied:
            missing.append(requirement.requirement)
            continue
        refs = [known.get(ident) for ident in requirement.observation_ids]
        if requirement.kind == "preference":
            actual = [payload.get("goal", {}).get("raw_request", ""), *payload.get("clarifications", [])]
            if not requirement.user_text or not any(requirement.user_text in text for text in actual):
                missing.append(requirement.requirement)
            continue
        if requirement.kind == "lookup":
            valid = all(
                o
                and o.get("source_type") in {"DATA", "AGENT", "KNOWLEDGE", "MEMORY", "WEB"}
                and (
                    o.get("status") in {"SUCCESS", "EMPTY", "PARTIAL"}
                    or (
                        o.get("source_type") == "KNOWLEDGE"
                        and o.get("metadata", {}).get("retrieval_trace", {}).get("evidence_status")
                        == "EVIDENCE_INSUFFICIENT"
                    )
                )
                for o in refs
            )
            if not refs or not valid:
                missing.append(requirement.requirement)
            continue
        permitted = {"DATA", "AGENT"} if requirement.kind == "data" else {"KNOWLEDGE", "AGENT"}
        if not refs or any(
            not o or o.get("source_type") not in permitted or o.get("status") not in {"SUCCESS", "PARTIAL"}
            for o in refs
        ):
            missing.append(requirement.requirement)
        elif requirement.kind == "policy" and any(
            o.get("source_type") == "KNOWLEDGE"
            and not any(e.get("evidence_grade") == "DIRECT" for e in o.get("evidence", []))
            for o in refs
        ):
            missing.append(requirement.requirement)
    if missing and not partial_requested(payload):
        return "尚有未满足的任务条件：" + "；".join(missing)[:600]
    return None
