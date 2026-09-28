"""Unit tests for the modular Skills system."""
from __future__ import annotations

from pathlib import Path
import pytest

from app.skills.model import Skill
from app.skills.loader import SkillLoader
from app.skills.registry import SkillRegistry
from app.skills.manager import (
    find_relevant_skills,
    inject_skill_hints,
    list_available_skills,
)
from app.tools.registry import Tool, ToolRegistry
from app.tools.base import ToolResult


def test_parse_skill_from_directory(tmp_path: Path):
    """SkillLoader correctly parses SKILL.md with frontmatter, instructions, and examples."""
    skill_dir = tmp_path / "custom-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: custom-skill\n"
        "description: A test skill for custom tasks\n"
        "activation_conditions:\n"
        "  - custom task\n"
        "  - automate\n"
        "---\n"
        "# Custom Instructions\n"
        "Follow these rules.\n\n"
        "## Examples\n"
        "- Example 1\n"
        "- Example 2\n",
        encoding="utf-8",
    )

    skill = SkillLoader.load_from_dir(skill_dir)
    assert skill is not None
    assert skill.name == "custom-skill"
    assert skill.description == "A test skill for custom tasks"
    assert "custom task" in skill.activation_conditions
    assert "automate" in skill.activation_conditions
    assert "Follow these rules." in skill.instructions
    assert len(skill.examples) == 2
    assert skill.examples[0] == "Example 1"


def test_skill_relevance_matching():
    """Skills accurately detect relevance based on name and activation conditions."""
    skill = Skill(
        name="sql-optimizer",
        description="Optimizes SQL queries",
        instructions="Analyze queries for missing indexes.",
        activation_conditions=["sql", "slow query", "database"],
    )

    assert skill.is_relevant("Please optimize this sql query") is True
    assert skill.is_relevant("We have a slow query in reports") is True
    assert skill.is_relevant("Write some python css styles") is False


def test_skill_registry_selective_loading(tmp_path: Path):
    """Registry only activates relevant skills; irrelevant skills are not active."""
    s1_dir = tmp_path / "skill1"
    s1_dir.mkdir()
    (s1_dir / "SKILL.md").write_text(
        "---\nname: skill1\ndescription: Skill One\nactivation_conditions:\n  - apple\n---\nBody 1\n"
    )

    s2_dir = tmp_path / "skill2"
    s2_dir.mkdir()
    (s2_dir / "SKILL.md").write_text(
        "---\nname: skill2\ndescription: Skill Two\nactivation_conditions:\n  - banana\n---\nBody 2\n"
    )

    registry = SkillRegistry([tmp_path])
    all_skills = registry.list_all()
    assert len(all_skills) == 2

    # Query matching only skill1
    matched = registry.find_relevant("I want to eat an apple")
    assert len(matched) == 1
    assert matched[0].name == "skill1"

    # Activation marks it active
    registry.activate_skill("skill1")
    assert registry.is_active("skill1") is True
    assert registry.is_active("skill2") is False


def test_skill_tool_dynamic_registration():
    """Skills can register new tools dynamically into ToolRegistry upon activation."""
    dummy_tool = Tool(
        name="custom_analyze",
        description="Analyze something custom",
        input_schema={"type": "object", "properties": {}},
        execute=lambda args: ToolResult(output="analysis complete"),
        permission_category="readonly",
    )
    skill = Skill(
        name="analyzer",
        description="Analyzer skill",
        instructions="Analyze code",
        tools=[dummy_tool],
    )

    registry = SkillRegistry()
    registry.register_skill(skill)

    tools = ToolRegistry()
    assert tools.get("custom_analyze") is None

    registry.activate_skill("analyzer", tool_registry=tools)
    tool_in_reg = tools.get("custom_analyze")
    assert tool_in_reg is not None
    assert tool_in_reg.execute({}).output == "analysis complete"


def test_inject_skill_hints_deduplication():
    """Skill hints are only injected once and not duplicated in messages."""
    registry = SkillRegistry()
    skill = Skill(
        name="code-refactor",
        description="Refactoring",
        instructions="Refactor cleanly",
        activation_conditions=["refactor"],
    )
    registry.register_skill(skill)

    messages = [{"role": "user", "content": "please refactor this code"}]
    injected1 = inject_skill_hints(messages, "please refactor this code", registry=registry)
    assert "code-refactor" in injected1
    assert len(messages) == 2  # user + system hint

    # Second injection with same skill should not add duplicate message
    injected2 = inject_skill_hints(messages, "please refactor more", registry=registry)
    assert len(injected2) == 0
    assert len(messages) == 2


def test_get_standard_skill_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """get_standard_skill_paths includes workspace .agents/skills, .agent/skills, and SKILLS_PATH."""
    from app.skills.manager import get_standard_skill_paths

    ws = tmp_path / "my_project"
    ws.mkdir()

    monkeypatch.setenv("SKILLS_PATH", f"{tmp_path}/custom_skills1;{tmp_path}/custom_skills2")
    paths = get_standard_skill_paths(ws)

    # Check that workspace .agents/skills is prioritized
    assert any(".agents" in str(p) and "my_project" in str(p) for p in paths)
    assert any(".agent" in str(p) and "my_project" in str(p) for p in paths)
    assert any("skills" in str(p) and "my_project" in str(p) for p in paths)
    assert any("custom_skills1" in str(p) for p in paths)
    assert any("custom_skills2" in str(p) for p in paths)


def test_build_skill_registry_discovers_agents_skills(tmp_path: Path):
    """build_skill_registry discovers skills placed in workspace/.agents/skills."""
    from app.skills.manager import build_skill_registry

    ws = tmp_path / "workspace"
    agents_skills = ws / ".agents" / "skills" / "deploy-helper"
    agents_skills.mkdir(parents=True)
    (agents_skills / "SKILL.md").write_text(
        "---\nname: deploy-helper\ndescription: Helper for deployments\nactivation_conditions:\n  - deploy\n---\nDeployment guide.",
        encoding="utf-8",
    )

    registry = build_skill_registry(ws)
    skill_names = [s.name for s in registry.list_all()]
    assert "deploy-helper" in skill_names

