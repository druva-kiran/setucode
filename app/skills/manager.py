"""Skill manager — orchestrates skill discovery, relevance detection, and injection."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from app.skills.model import Skill
from app.skills.registry import SkillRegistry
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


def get_standard_skill_paths(workspace: Path | None = None) -> list[Path]:
    """Return all standard skill discovery search paths in order of priority:

    1. Workspace-specific:
       - <workspace>/.agents/skills
       - <workspace>/.agent/skills
       - <workspace>/skills
    2. Project-root / CWD:
       - .agents/skills
       - .agent/skills
       - skills
    3. User home directories:
       - ~/.agents/skills
       - ~/.setucode/skills
    4. Custom env directories (from SKILLS_PATH or EXTRA_SKILLS_DIRS):
       e.g. SKILLS_PATH=/custom/skills;/team/skills
    5. Builtin app skills:
       - app/skills
    """
    paths: list[Path] = []

    # 1. Workspace-specific
    if workspace:
        paths.append(workspace / ".agents" / "skills")
        paths.append(workspace / ".agent" / "skills")
        paths.append(workspace / "skills")

    # 2. Project root / CWD
    paths.append(Path(".agents/skills"))
    paths.append(Path(".agent/skills"))
    paths.append(Path("skills"))

    # 3. User home directory
    home = Path.home()
    paths.append(home / ".agents" / "skills")
    paths.append(home / ".setucode" / "skills")

    # 4. Custom env directories
    env_paths = os.environ.get("SKILLS_PATH") or os.environ.get("EXTRA_SKILLS_DIRS") or ""
    if env_paths:
        # Support both ':' and ';' path separators
        sep = ";" if ";" in env_paths else ":"
        for p in env_paths.split(sep):
            p = p.strip()
            if p:
                paths.append(Path(p))

    # 5. Builtin app skills
    paths.append(Path("app/skills"))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_paths: list[Path] = []
    for p in paths:
        resolved = str(p.resolve()) if p.is_absolute() else str(p)
        if resolved not in seen:
            seen.add(resolved)
            unique_paths.append(p)

    return unique_paths


def build_skill_registry(workspace: Path | None = None) -> SkillRegistry:
    """Build a SkillRegistry populated with all standard search paths."""
    paths = get_standard_skill_paths(workspace)
    return SkillRegistry(paths)


_DEFAULT_REGISTRY = build_skill_registry()


def get_default_skill_registry(workspace: Path | None = None) -> SkillRegistry:
    if workspace:
        for p in get_standard_skill_paths(workspace):
            _DEFAULT_REGISTRY.add_search_path(p)
    return _DEFAULT_REGISTRY


def list_available_skills(
    registry: SkillRegistry | None = None, workspace: Path | None = None
) -> List[str]:
    reg = registry or get_default_skill_registry(workspace)
    return [s.name for s in reg.list_all()]


def find_relevant_skills(
    user_message: str,
    registry: SkillRegistry | None = None,
    workspace: Path | None = None,
) -> List[Skill]:
    """Detect skills that match the user message or task description."""
    reg = registry or get_default_skill_registry(workspace)
    return reg.find_relevant(user_message)


def inject_skill_hints(
    messages: list[dict],
    user_message: str,
    registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    workspace: Path | None = None,
) -> list[str]:
    """Detect and inject only required skills without bloating the prompt."""
    reg = registry or get_default_skill_registry(workspace)
    relevant = find_relevant_skills(user_message, reg, workspace=workspace)
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
