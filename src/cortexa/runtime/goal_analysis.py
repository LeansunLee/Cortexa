"""目标入口的一次模型拆解：把随口提问转成结构化目标，并从协作名册中预选人选。

分词/二元组匹配对"卖得咋样"这类口语无法建立与"销量分析"的词面关联；这里用一次
模型调用完成语义理解。任何失败（开关关闭、模型异常、JSON 不合法）都返回 None，
路由静默回退到既有词法 + 目录行为。
"""

import asyncio
import json
import re

from pydantic import BaseModel, Field

from cortexa.config.llm_providers import create_llm
from cortexa.runtime.collaboration import available_agents, proxy_enabled, settings

ANALYSIS_TIMEOUT_SECONDS = 30


class GoalAnalysis(BaseModel):
    objective: str = ""
    agents: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    clarification: str | None = None


SYSTEM_PROMPT = (
    "你是目标拆解器。把用户的原始请求转成一个 JSON 对象，不输出任何其他文字：\n"
    '{"objective": "规范化的一句话目标，补全指代，保留数字、车型、区域等关键对象", '
    '"agents": ["最适合处理该请求的智能体，1-3个，按优先级排序"], '
    '"domains": ["涉及的数据或业务域，如：车型参数/销量数据/门店经销商"], '
    '"clarification": null 或 "缺少关键对象无法拆解时的一句追问"}\n'
    "规则：agents 从候选名单中选，填写名单第一列的「名字」（不是角色名），逐字复制；"
    "名单为空则给空数组；没有足够信息时宁缺勿猜；clarification 一般为 null。"
)


def extract_json(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        raise ValueError("no json object")
    return json.loads(match.group(0))


def _roster_lines(agents):
    return "\n".join(
        f"- {a.name}｜{a.role or 'AI助手'}｜{(a.responsibilities or '')[:80]}" for a in agents
    )


async def analyze_request(source, payload, db, config):
    """调用一次模型完成问题拆解；返回 GoalAnalysis 或 None（回退词法/目录行为）。"""
    if not bool((config or {}).get("features", {}).get("goal_analysis_enabled", True)):
        return None
    roster = [
        a
        for a in await available_agents(db, source)
        if proxy_enabled(a) and settings(a).allow_incoming
    ]
    if not roster:
        return None
    request = payload["goal"]["raw_request"]
    clarifications = "\n".join(payload.get("clarifications", []))
    user_prompt = f"# 用户请求\n{request}"
    if clarifications:
        user_prompt += f"\n\n# 补充说明\n{clarifications}"
    user_prompt += f"\n\n# 候选名单\n{_roster_lines(roster)}"
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        model = create_llm(source.model)
        if hasattr(model, "max_retries"):
            model = model.model_copy(update={"max_retries": 0})
        response = await asyncio.wait_for(
            model.ainvoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]),
            ANALYSIS_TIMEOUT_SECONDS,
        )
        content = response.content if isinstance(response.content, str) else "".join(
            str(part) for part in (response.content or [])
        )
        data = extract_json(content)
        # 模型可能回角色名，或把名单行的"名字｜角色"整段抄回来：精确命中接受，
        # 否则取被该串包含的最长名字，统一映射回名字。
        names = sorted({a.name for a in roster}, key=len, reverse=True)
        exact = {}
        for a in roster:
            exact[a.name.casefold()] = a.name
            exact[(a.role or "").casefold()] = a.name
        agents = []
        for n in data.get("agents") or []:
            if not isinstance(n, str):
                continue
            hit = exact.get(n.casefold())
            if hit is None:
                folded = n.casefold()
                hit = next((name for name in names if name.casefold() in folded), None)
            if hit and hit not in agents:
                agents.append(hit)
        return GoalAnalysis(
            objective=str(data.get("objective") or "")[:300],
            agents=agents[:3],
            domains=[str(x)[:30] for x in (data.get("domains") or [])[:5] if isinstance(x, str)],
            clarification=str(data.get("clarification"))[:200] if data.get("clarification") else None,
        )
    except Exception:
        return None
