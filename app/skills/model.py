"""Data models for the modular Skills system."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from app.tools.registry import Tool


@dataclass
class Skill:
    """Represents a modular capability plugin for the agent."""
    name: str
    description: str
    instructions: str
    activation_conditions: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    tools: list[Tool] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_relevant(self, text: str) -> bool:
        """Check if this skill is relevant to the given user text or context."""
        lowered = text.lower()
        # Direct name match
        if self.name.lower() in lowered:
            return True
        # Activation conditions match (keyword or phrase)
        for condition in self.activation_conditions:
            cond_lower = condition.strip().lower()
            if cond_lower and cond_lower in lowered:
                return True
        return False

    def to_system_hint(self) -> str:
        """Render the skill as an instructional system prompt hint."""
        parts = [f"## Skill: {self.name}", f"**Description:** {self.description}"]
        if self.instructions:
            parts.append(f"### Instructions\n{self.instructions.strip()}")
        if self.examples:
            parts.append("### Examples")
            for ex in self.examples:
                parts.append(f"- {ex}")
        return "\n\n".join(parts)
