"""技能层单元测试：文件正文存取、索引渐进披露边界、名称与保留名校验。"""

from types import SimpleNamespace

import pytest

from cortexa.tools import skills


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "_SKILLS_DIR_OVERRIDE", str(tmp_path / "skillsroot"))
    return tmp_path / "skillsroot"


def _skill(name="web_research", description="需要公开信息时使用", status="active"):
    return SimpleNamespace(name=name, description=description, status=status)


def test_instructions_file_roundtrip(isolated_storage):
    path = skills.save_instructions("ws-1", "skill-abc", "# 步骤\n1. 检索")
    assert path == "ws-1/skill-abc.md"
    assert skills.read_instructions(path) == "# 步骤\n1. 检索"
    skills.delete_instructions(path)
    assert skills.read_instructions(path) is None


def test_instructions_rejects_empty_and_oversized(isolated_storage):
    with pytest.raises(ValueError):
        skills.save_instructions("ws-1", "s1", "   ")
    with pytest.raises(ValueError):
        skills.save_instructions("ws-1", "s2", "字" * (skills.MAX_INSTRUCTIONS_CHARS + 1))


def test_read_instructions_path_traversal_blocked(isolated_storage):
    assert skills.read_instructions("../../etc/passwd") is None
    assert skills.read_instructions("/abs/path.md") is None
    assert skills.read_instructions("") is None


def test_make_summary_compacts_and_truncates():
    assert skills.make_summary("第一行\n\n第二行  内容") == "第一行 第二行 内容"
    long = "字" * 500
    summary = skills.make_summary(long, max_len=200)
    assert len(summary) == 201 and summary.endswith("…")


def test_skill_index_respects_bounds_and_status():
    many = [_skill(f"skill_{i:02d}") for i in range(12)]
    index = skills.skill_index_text(many)
    assert index.count("- skill_") == skills.MAX_INDEX_SKILLS
    assert "load_skill" in index

    disabled = [_skill("a", status="disabled"), _skill("b")]
    assert skills.skill_index_text(disabled).count("- b：") == 1

    assert skills.skill_index_text([]) == ""


def test_skill_index_truncates_long_description():
    index = skills.skill_index_text([_skill(description="长" * 300)])
    assert "…" in index
    body_line = [line for line in index.splitlines() if line.startswith("- ")][0]
    assert len(body_line) < 200


def test_guard_line_present_in_constant():
    assert "不是平台规则豁免" in skills.SKILL_GUARD_LINE


def test_feature_gate_off_disables_index(monkeypatch):
    monkeypatch.setattr("cortexa.tools.skills.feature_flag", lambda name, default=False: False)
    agent = SimpleNamespace(workspace_id="ws", skill_ids=["x"])
    import asyncio
    assert asyncio.run(skills.build_skill_index(agent, None)) == ""


def test_reserved_names_cover_runtime_tools():
    from cortexa.tools.registry import RESERVED_TOOL_NAMES
    assert "load_skill" in RESERVED_TOOL_NAMES
