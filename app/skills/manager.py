"""Skill manager — orchestrates skill discovery, relevance detection, and injection."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from app.skills.model import Skill
from app.skills.registry import SkillRegistry
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

# Default global registry looking in ./skills and workspace/skills
_DEFAULT_REGISTRY = SkillRegistry([
    Path("skills"),
    Path("workspace/skills"),
    Path("app/skills"),
])


def get_default_skill_registry() -> SkillRegistry:
    return _DEFAULT_REGISTRY


def list_available_skills(registry: SkillRegistry | None = None) -> List[str]:
    reg = registry or _DEFAULT_REGISTRY
    return [s.name for s in reg.list_all()]


def find_relevant_skills(
    user_message: str, registry: SkillRegistry | None = None
) -> List[Skill]:
    """Detect skills that match the user message or task description."""
    reg = registry or _DEFAULT_REGISTRY
    return reg.find_relevant(user_message)


def inject_skill_hints(
    messages: list[dict],
    user_message: str,
    registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> list[str]:
    """Detect and inject only required skills without bloating the prompt."""
    reg = registry or _DEFAULT_REGISTRY
    relevant = find_relevant_skills(user_message, reg)
    injected_names: list[str] = []

    for skill in relevant:
        reg.activate_skill(skill.name, tool_registry)
        hint = skill.to_system_hint()
        # Avoid duplicate skill hints in messages
        if not any(m.get("content") == hint for m in messages):
            messages.append({"role": "system", "content": hint})
            injected_names.append(skill.name)
            log.info("Injected skill '%s' into context", skill.name)

    return injected_names
