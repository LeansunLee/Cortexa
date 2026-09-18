"""Memory Service — Agent 跨会话记忆的提取、存储、检索"""

from __future__ import annotations
from agentdevstu.usage.context import usage_action, annotate_usage

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from agentdevstu.db.models import Memory, ConversationMessage


# ── Extraction ──────────────────────────────────────────────────────

EXTRACTION_PROMPT = """你是一个记忆提取器。分析以下对话，判断是否产生了值得长期记住的信息。

## 规则
1. 只提取真正重要的、跨会话有用的信息
2. 不要提取闲聊、问候、一次性的简单问答
3. 每条记忆应该是独立的、自包含的，脱离上下文也能理解

## 记忆类型
- **semantic**: 长期稳定的事实、偏好、规则。例如"用户偏好简洁回答"、"公司重点发展年轻市场"
- **episodic**: 重要事件、决策、结论。例如"9月1日决定新品先在华东测试"

- **focus**: 用户明确希望持续关注的主题或事项。例如"持续关注竞品新品发布"。仅保存关注方向，不代表已创建后台监控或定时提醒。

## 输出格式
返回 JSON 数组，每条记忆包含：
- type: "semantic"、"episodic" 或 "focus"
- content: 记忆内容（一句话，自包含）
- importance: 0.0~1.0 的数字
- confidence: 0.0~1.0 的数字

示例输出（纯JSON，不要markdown包裹）：
[{{"type": "semantic", "content": "用户偏好简洁回答", "importance": 0.8, "confidence": 0.9}}]

如果没有值得记住的内容，返回空数组 []。

## 对话内容
{conversation}

## 当前用户消息
{current_message}

## Agent 信息
名称：{agent_name}
职责：{agent_responsibilities}
"""


@usage_action("memory_extract", background=True)
async def extract_memories(
    agent,
    conversation_id: uuid.UUID,
    current_message: str,
    recent_messages: list[dict],
    db: AsyncSession,
) -> list[dict]:
    """分析对话，提取值得长期保存的记忆。返回候选记忆列表。"""
    from agentdevstu.config.llm_providers import create_llm

    print(f"[MEMORY] extract_memories called for agent={agent.name}, msg_len={len(current_message)}", flush=True)

    # 构建对话摘要（取最近10轮）
    conv_lines = []
    for msg in recent_messages[-10:]:
        role = "用户" if msg["role"] == "user" else "Agent"
        conv_lines.append(f"{role}: {msg['content'][:500]}")
    conversation_text = "\n".join(conv_lines)

    prompt = EXTRACTION_PROMPT.format(
        conversation=conversation_text,
        current_message=current_message[:500],
        agent_name=agent.name or "Agent",
        agent_responsibilities=agent.responsibilities or "无",
    )

    try:
        model = create_llm(agent.model)
        print(f"[MEMORY] Calling LLM for extraction, model={agent.model}", flush=True)
        response = await model.ainvoke([{"role": "user", "content": prompt}])
        raw = response.content.strip()
        print(f"[MEMORY] LLM raw response (first 500 chars): {repr(raw[:500])}", flush=True)

        # Extract JSON from response - try multiple strategies
        import re
        # Strategy 1: look for ```json ... ```
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        # Strategy 2: try to find a JSON array
        match = re.search(r'\[\s*\{.*?\}\s*\]', raw, re.DOTALL)
        if match:
            raw = match.group(0)
        else:
            # Strategy 3: try to find individual JSON objects
            matches = re.findall(r'\{[^{}]+\}', raw, re.DOTALL)
            if matches:
                raw = "[" + ", ".join(matches) + "]"

        # Strategy 4: try to fix common JSON issues
        raw = raw.strip()
        if not raw.startswith("[") and not raw.startswith("{"):
            # If it's not valid JSON at all, return empty
            print(f"[MEMORY] No JSON found in response: {repr(raw[:200])}", flush=True)
            return []

        print(f"[MEMORY] Cleaned JSON (first 300 chars): {raw[:300]}", flush=True)
        candidates = json.loads(raw)
        if not isinstance(candidates, list):
            candidates = []

        # Filter: only keep items with importance >= 0.5
        valid = [
            c for c in candidates
            if isinstance(c, dict)
            and c.get("content")
            and c.get("type") in ("semantic", "episodic", "focus")
            and float(c.get("importance", 0)) >= 0.5
        ]
        print(f"[MEMORY] Extracted {len(valid)} valid memories from {len(candidates)} candidates", flush=True)
        return valid
    except Exception as e:
        err_type = type(e).__name__
        print(f"[MEMORY] Extraction failed: {err_type}: {e}", flush=True)
        if err_type == "TimeoutError":
            print("[MEMORY] Hint: LLM call exceeded timeout. Consider increasing timeout or using a faster model.", flush=True)
        import traceback; traceback.print_exc()
        return []


# ── Storage ──────────────────────────────────────────────────────────

async def store_memory(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    memory_data: dict,
    source_type: str = "conversation",
    source_id: uuid.UUID | None = None,
    db: AsyncSession = None,
) -> Memory:
    """将候选记忆写入数据库，状态直接为 active（全自动策略）。"""
    memory = Memory(
        workspace_id=workspace_id,
        agent_id=agent_id,
        type=memory_data.get("type", "semantic"),
        content=memory_data["content"],
        importance=float(memory_data.get("importance", 0.5)),
        confidence=float(memory_data.get("confidence", 0.5)),
        status="active",
        source_type=source_type,
        source_id=source_id,
    )
    db.add(memory)
    await db.flush()
    await db.refresh(memory)
    return memory


# ── Retrieval ────────────────────────────────────────────────────────

async def retrieve_memories(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    query: str,
    db: AsyncSession,
    top_k: int = 5,
) -> list[Memory]:
    """检索与 query 相关的记忆。使用 jieba 分词 + 关键词匹配。

    检索范围：
    1. 当前 Agent 的记忆
    2. 工作空间级记忆（agent_id 为空的）
    排除其他 Agent 的私有记忆。
    """
    import jieba

    # Build query
    q = (
        select(Memory)
        .where(Memory.workspace_id == workspace_id)
        .where(Memory.status == "active")
        .where(
            (Memory.agent_id == agent_id) | (Memory.agent_id.is_(None))
        )
    )
    result = await db.execute(q)
    all_memories = list(result.scalars().all())

    if not all_memories:
        return []

    # jieba keyword scoring
    query_words = set(jieba.cut(query))
    query_words = {w.strip() for w in query_words if len(w.strip()) >= 2}

    scored = []
    for mem in all_memories:
        content_lower = mem.content.lower()
        # Simple keyword overlap score
        score = 0
        for word in query_words:
            if word in content_lower:
                score += 1
        # Boost by importance
        score += mem.importance * 0.3
        if score > 0:
            scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [mem for _, mem in scored[:top_k]]

    # Update access stats
    now = datetime.now(timezone.utc)
    for mem in top:
        mem.access_count = (mem.access_count or 0) + 1
        mem.last_accessed_at = now
    await db.flush()

    return top


# ── Context Building ────────────────────────────────────────────────

def format_memories_for_prompt(memories: list[Memory]) -> str:
    """将检索到的记忆格式化为 system prompt 片段。"""
    if not memories:
        return ""

    parts = []
    for mem in memories:
        tag = {"semantic": "事实", "episodic": "事件", "focus": "关注"}.get(mem.type, mem.type)
        parts.append(f"- [{tag}] {mem.content}")

    return "## 相关记忆\n" + "\n".join(parts)


# ── Conversation Summary ─────────────────────────────────────────────

SUMMARY_PROMPT = """请将以下对话压缩为一段简洁的摘要（不超过200字），保留关键信息、决策和结论。

对话内容：
{messages}

输出摘要："""


@usage_action("memory_summary", background=True)
async def summarize_conversation(
    messages: list[dict],
    model_name: str,
) -> str:
    """对对话历史做摘要，用于替代固定20条限制。"""
    from agentdevstu.config.llm_providers import create_llm

    if len(messages) <= 4:
        # 太短不需要摘要
        return ""

    # Take messages beyond the most recent 4 (keep recent raw)
    older = messages[:-4]
    conv_text = "\n".join(
        f"{'用户' if m['role'] == 'user' else 'Agent'}: {m['content'][:300]}"
        for m in older
    )

    try:
        model = create_llm(model_name)
        print(f"[CONTEXT] Calling LLM for summary, model={model_name}, text_len={len(conv_text)}", flush=True)
        response = await model.ainvoke([{
            "role": "user",
            "content": SUMMARY_PROMPT.format(messages=conv_text)
        }])
        summary = response.content.strip()
        print(f"[CONTEXT] Summary result (first 100 chars): {summary[:100]}", flush=True)
        return summary
    except Exception as e:
        print(f"[CONTEXT] Summarization failed: {type(e).__name__}: {e}", flush=True)
        return ""
