"""SkillRegistry — catalogue and lifecycle manager for agent skills."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.skills.loader import SkillLoader
from app.skills.model import Skill
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


class SkillRegistry:
    """Manages skill discovery, selective activation, and isolation."""

    def __init__(self, search_paths: list[Path] | None = None) -> None:
        self._search_paths = search_paths or []
        self._skills: dict[str, Skill] = {}
        self._active_skills: set[str] = set()
        self._loaded = False

    def add_search_path(self, path: Path) -> None:
        if path not in self._search_paths:
            self._search_paths.append(path)
            self._loaded = False

    def register_skill(self, skill: Skill) -> None:
        """Register a skill programmatically."""
        self._skills[skill.name] = skill

    def refresh(self) -> None:
        """Discover skills from all configured search paths."""
        discovered = SkillLoader.discover_skills(self._search_paths)
        self._skills.update(discovered)
        self._loaded = True

    def get(self, name: str) -> Optional[Skill]:
        if not self._loaded:
            self.refresh()
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        if not self._loaded:
            self.refresh()
        return list(self._skills.values())

    def find_relevant(self, query: str) -> list[Skill]:
        """Find skills matching the query without activating every skill."""
        if not self._loaded:
            self.refresh()

        relevant: list[Skill] = []
        for skill in self._skills.values():
            if skill.is_relevant(query):
                relevant.append(skill)
        return relevant

    def activate_skill(
        self, name: str, tool_registry: ToolRegistry | None = None
    ) -> Optional[Skill]:
        """Activate a single skill, optionally binding its tools to ToolRegistry."""
        skill = self.get(name)
        if not skill:
            log.warning("Cannot activate unknown skill: %s", name)
            return None

        self._active_skills.add(name)
        if tool_registry and skill.tools:
            for tool in skill.tools:
                tool_registry.register(tool)
                log.info("Registered tool '%s' from skill '%s'", tool.name, skill.name)

        return skill

    def deactivate_skill(
        self, name: str, tool_registry: ToolRegistry | None = None
    ) -> bool:
        """Deactivate a skill and unbind any tools it registered."""
        if name not in self._active_skills:
            return False

        self._active_skills.remove(name)
        skill = self.get(name)
        if tool_registry and skill and skill.tools:
            for tool in skill.tools:
                tool_registry.unregister(tool.name)
                log.info("Unregistered tool '%s' from skill '%s'", tool.name, skill.name)
        return True

    def toggle_skill(
        self, name: str, tool_registry: ToolRegistry | None = None
    ) -> bool:
        """Toggle active state of a skill. Returns True if now active, False if inactive."""
        if self.is_active(name):
            self.deactivate_skill(name, tool_registry)
            return False
        else:
            self.activate_skill(name, tool_registry)
            return True

    def get_active_hints(self) -> list[str]:
        """Get system prompt hints for currently active skills."""
        hints = []
        for name in sorted(self._active_skills):
            skill = self.get(name)
            if skill:
                hints.append(skill.to_system_hint())
        return hints

    def is_active(self, name: str) -> bool:
        return name in self._active_skills

