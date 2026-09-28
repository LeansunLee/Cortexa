"""Editable per-turn collaboration tasks; no persistent Agent mutations."""
import uuid
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from cortexa.agents.prompts import handoff_message, reference_message

PROXY_INSTRUCTIONS = (
    "你是本次协作的数据提供方，请直接调用你已有的能力查询并返回真实数据。"
    "不要再次要求其他智能体或用户提供同一批数据；查询失败或无权限时如实说明。"
    "后续综合分析由发起协作的智能体完成。\n\n"
)

class CollaborationDraft(BaseModel):
    agent_id: uuid.UUID
    task: str = Field(min_length=1, max_length=12000)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    expected_output: str = Field(default="给出专业分析和建议", max_length=4000)
    supplemental_prompt: str | None = Field(default=None, max_length=12000)
    depends_on: list[uuid.UUID] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.task.strip():
            raise ValueError("请填写协作任务")
        return self


def validate_drafts(drafts):
    seen = set()
    for draft in drafts:
        if draft.agent_id in seen:
            raise ValueError("每个 Agent 只能有一张任务卡")
        if not set(draft.depends_on) <= seen:
            raise ValueError("协作依赖必须是前面的任务，不能循环或引用已移除的任务")
        seen.add(draft.agent_id)


def proxy_request(handoff):
    # Do not forward history, background, or other Agents' results to external Agents.
    return PROXY_INSTRUCTIONS + handoff_message(handoff)["content"]


def visible_snapshot(snapshot):
    """Never publish credential fields or private system configuration to runtime users."""
    import re
    from cortexa.security.access import current_actor
    actor = current_actor.get()
    can_read = actor is None or actor.has("agent.read")
    def clean(value):
        if isinstance(value, dict):
            return {key: ("[已隐藏]" if re.search(r"token|secret|password|authorization|api.?key|cookie", key, re.I) else clean(item)) for key, item in value.items()}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value
    if not can_read:
        return {"type": snapshot.get("type"), "notice": "实际输入包含受限 Agent 配置；请查看本轮任务卡，完整配置需 Agent 查看权限。"}
    return clean(snapshot)


async def save_input_snapshot(conversation_id, snapshot):
    import asyncio
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[3] / "data" / "collaboration-inputs" / str(conversation_id)
    snapshot_id = str(uuid.uuid4())
    def write():
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{snapshot_id}.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    await asyncio.to_thread(write)
    return {"snapshot_id": snapshot_id, "conversation_id": str(conversation_id), "type": snapshot.get("type")}


async def read_input_snapshot(conversation_id, snapshot_id):
    import asyncio
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "data" / "collaboration-inputs" / str(uuid.UUID(str(conversation_id))) / f"{uuid.UUID(str(snapshot_id))}.json"
    return json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
