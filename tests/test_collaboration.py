"""
Tests for Agent Collaboration module.
"""
import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestMentionParser:
    """Tests for @mention parsing."""

    def test_parse_single_mention(self):
        from cortexa.collaboration.mention_parser import parse_mentions
        result = parse_mentions("@市场部 分析一下年轻用户市场")
        assert result.has_mentions is True
        assert len(result.mentions) == 1
        assert result.mentions[0].name == "市场部"
        assert result.mentions[0].message_after == "分析一下年轻用户市场"

    def test_parse_multiple_mentions(self):
        from cortexa.collaboration.mention_parser import parse_mentions
        result = parse_mentions("@市场部 做用户调研 @财务部 算预算")
        assert result.has_mentions is True
        assert len(result.mentions) == 2
        assert result.mentions[0].name == "市场部"
        assert result.mentions[1].name == "财务部"

    def test_parse_no_mentions(self):
        from cortexa.collaboration.mention_parser import parse_mentions
        result = parse_mentions("帮我分析一下市场数据")
        assert result.has_mentions is False
        assert len(result.mentions) == 0

    def test_parse_mention_only(self):
        from cortexa.collaboration.mention_parser import parse_mentions
        result = parse_mentions("@市场部")
        assert result.has_mentions is True
        assert result.mentions[0].name == "市场部"
        assert result.mentions[0].message_after == ""

    def test_mention_names(self):
        from cortexa.collaboration.mention_parser import parse_mentions
        result = parse_mentions("@市场部 @产品部 @财务部")
        assert result.mention_names == ["市场部", "产品部", "财务部"]


class TestFuzzyMatch:
    """Tests for agent name fuzzy matching."""

    def test_exact_match(self):
        from cortexa.collaboration.mention_parser import fuzzy_match_agent
        names = ["市场部", "产品部", "财务部"]
        assert fuzzy_match_agent("市场部", names) == "市场部"

    def test_partial_match(self):
        from cortexa.collaboration.mention_parser import fuzzy_match_agent
        names = ["市场营销部", "产品部", "财务部"]
        assert fuzzy_match_agent("市场", names) == "市场营销部"

    def test_no_match(self):
        from cortexa.collaboration.mention_parser import fuzzy_match_agent
        names = ["市场部", "产品部", "财务部"]
        assert fuzzy_match_agent("技术部", names) is None

    def test_alias_match(self):
        from cortexa.collaboration.mention_parser import fuzzy_match_agent
        names = ["市场营销部", "产品研发部"]
        result = fuzzy_match_agent("marketing", names)
        assert result == "市场营销部"


class TestCollaborationSchemas:
    """Tests for collaboration data schemas."""

    def test_handoff_schema(self):
        from cortexa.collaboration.schemas import AgentHandoff
        handoff = AgentHandoff(
            source_agent_id="agent-1",
            target_agent_id="agent-2",
            task="验证品牌定位",
            question="请分析年轻用户市场",
        )
        assert handoff.source_agent_id == "agent-1"
        assert handoff.target_agent_id == "agent-2"
        assert handoff.known_facts == []
        assert handoff.constraints == []

    def test_handoff_result_schema(self):
        from cortexa.collaboration.schemas import AgentHandoffResult
        result = AgentHandoffResult(
            status="success",
            summary="分析完成",
            result="年轻用户对品牌认知...",
        )
        assert result.status == "success"
        assert result.confidence is None

    def test_collaboration_limits(self):
        from cortexa.collaboration.schemas import CollaborationLimits, DEFAULT_LIMITS
        limits = CollaborationLimits()
        assert limits.max_agents_per_request == 3
        assert limits.max_call_depth == 2
        assert limits.timeout_seconds == 120
        assert DEFAULT_LIMITS.max_agents_per_request == 3


class TestHandoffPromptBuilding:
    """Tests for handoff system prompt generation."""

    def test_build_handoff_prompt(self):
        import sys
        # Agent attributes are mocked; importing ORM modules does not open a connection.
        from unittest.mock import MagicMock

        # We need to test _build_handoff_system_prompt directly
        # It only uses Agent object attributes, so we can mock those
        from cortexa.collaboration.schemas import AgentHandoff
        from unittest.mock import MagicMock as MM

        source = MagicMock()
        source.name = "品牌策划"
        source.personality = None
        source.role = None
        source.responsibilities = None
        source.boundaries = None
        source.system_prompt = None

        target = MagicMock()
        target.name = "市场部"
        target.personality = "专业、数据驱动"
        target.role = "市场分析师"
        target.responsibilities = "负责市场调研和数据分析"
        target.boundaries = None
        target.system_prompt = None

        handoff = AgentHandoff(
            source_agent_id=str(source.id),
            target_agent_id=str(target.id),
            task="验证品牌年轻化定位",
            known_facts=["品牌计划扩大年轻用户市场"],
            question="请分析年轻用户对该品牌的认知",
            expected_output="给出关键结论",
        )

        # Import with mocked DB
        from cortexa.collaboration.manager import _build_handoff_system_prompt
        prompt = _build_handoff_system_prompt(source, target, handoff)

        assert "你是市场部" in prompt
        assert "市场分析师" in prompt
        from cortexa.agents.prompts import handoff_message
        task = handoff_message(handoff)
        assert "验证品牌年轻化定位" not in prompt
        assert "品牌计划扩大年轻用户市场" not in prompt
        assert task["role"] == "user"
        assert "请分析年轻用户对该品牌的认知" in task["content"]
        assert "给出关键结论" in task["content"]
        assert "500 字" not in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
