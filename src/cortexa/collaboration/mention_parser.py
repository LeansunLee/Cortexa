"""
@Agent 提及解析器

从用户消息中解析 @Agent名称 引用，生成结构化的协作请求。

支持格式:
- @市场部 分析一下年轻用户市场
- @财务部 @产品部 帮我做预算分析
- @市场部 做一下用户调研，@财务部 算一下预算
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Mention:
    """一个 @提及"""
    name: str           # Agent 名称（不含 @）
    start: int          # 在原文中的起始位置
    end: int            # 在原文中的结束位置
    message_after: str = ""  # 该 @ 后到下一个 @ 或末尾的消息内容


@dataclass
class ParsedMentions:
    """解析结果"""
    mentions: list[Mention] = field(default_factory=list)
    raw_text: str = ""
    cleaned_text: str = ""  # 去除 @ 后的纯文本

    @property
    def has_mentions(self) -> bool:
        return len(self.mentions) > 0

    @property
    def mention_names(self) -> list[str]:
        return [m.name for m in self.mentions]


def parse_mentions(text: str) -> ParsedMentions:
    """
    从用户消息中解析 @Agent 名称提及。

    Args:
        text: 用户原始消息文本

    Returns:
        ParsedMentions 包含解析出的所有提及

    Examples:
        >>> p = parse_mentions("@市场部 分析一下年轻用户市场")
        >>> p.has_mentions
        True
        >>> p.mentions[0].name
        '市场部'
        >>> p.mentions[0].message_after
        '分析一下年轻用户市场'
    """
    # 匹配 @名称，名称可以包含中文、英文、数字、下划线、连字符
    # 名称以 @ 开头，后面跟至少一个非空白字符，直到遇到空白或另一个 @ 或行尾
    # An address such as admin@example.com is ordinary text, not an invocation.
    pattern = r'(?<![\w.+-])@([^\s@]+)'

    mentions = []
    cleaned_parts = []
    last_end = 0

    for match in re.finditer(pattern, text):
        name = match.group(1).strip()
        start = match.start()
        end = match.end()

        # 提取该 @ 后面到下一个 @ 之间的消息内容
        # end is right after the matched name, skip whitespace
        rest = text[end:].lstrip()
        next_at_pos = rest.find('@')
        if next_at_pos == -1:
            message_after = rest.strip()
        else:
            message_after = rest[:next_at_pos].strip()

        mentions.append(Mention(
            name=name,
            start=start,
            end=end,
            message_after=message_after,
        ))

        # 构建 cleaned text
        cleaned_parts.append(text[last_end:start])
        last_end = end

    cleaned_parts.append(text[last_end:])
    cleaned_text = ''.join(cleaned_parts).strip()

    return ParsedMentions(
        mentions=mentions,
        raw_text=text,
        cleaned_text=cleaned_text,
    )


def build_mention_display_html(name: str, agent_name: str = "") -> str:
    """构建 @提及 的显示 HTML（用于前端渲染）"""
    display = agent_name or name
    return f'<span class="mention-tag" data-agent="{name}">@{display}</span>'


def fuzzy_match_agent(query: str, agent_names: list[str]) -> str | None:
    """
    Only the Agent's display name can identify an @ participant.

    Args:
        query: 用户输入的 @名称
        agent_names: 系统中所有可用的 Agent 名称列表

    Returns:
        匹配到的 Agent 名称，或 None
    """
    query_lower = query.lower().strip()

    for name in agent_names:
        if name.lower() == query_lower:
            return name
    return None
