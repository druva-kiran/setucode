"""Skill loader — discovers, parses, and loads skills from directory structures."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from app.skills.model import Skill

log = logging.getLogger(__name__)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter between leading '---' delimiters."""
    meta: dict[str, Any] = {}
    lines = content.splitlines()

    if not lines or lines[0].strip() != "---":
        return meta, content

    end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx == -1:
        return meta, content

    fm_lines = lines[1:end_idx]
    body_lines = lines[end_idx + 1 :]

    current_list_key: str | None = None
    for line in fm_lines:
        line_str = line.strip()
        if not line_str or line_str.startswith("#"):
            continue

        if line_str.startswith("- ") and current_list_key:
            item = line_str[2:].strip().strip('"').strip("'")
            meta[current_list_key].append(item)
            continue

        if ":" in line_str:
            key, val = line_str.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not val:
                # Potential list header
                meta[key] = []
                current_list_key = key
            else:
                meta[key] = val
                current_list_key = None

    return meta, "\n".join(body_lines).strip()


class SkillLoader:
    """Discovers and parses skills from folders without hardcoding."""

    @classmethod
    def load_from_dir(cls, skill_dir: Path) -> Optional[Skill]:
        """Load a single Skill from its directory."""
        if not skill_dir.is_dir():
            return None

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return None

        try:
            content = skill_md.read_text(encoding="utf-8")
        except Exception as exc:
            log.warning("Failed to read skill at %s: %s", skill_md, exc)
            return None

        meta, body = _parse_frontmatter(content)
        name = meta.get("name") or skill_dir.name
        description = meta.get("description") or f"Skill {name}"

        # Activation conditions
        conditions = meta.get("activation_conditions") or []
        if isinstance(conditions, str):
            conditions = [c.strip() for c in conditions.split(",") if c.strip()]

        # Parse examples from body if sections exist
        examples: list[str] = []
        instructions = body
        if "## Examples" in body:
            parts = body.split("## Examples", 1)
            instructions = parts[0].strip()
            ex_lines = parts[1].strip().splitlines()
            for el in ex_lines:
                s = el.strip()
                if s.startswith("- ") or s.startswith("* "):
                    examples.append(s[2:].strip())

        return Skill(
            name=name,
            description=description,
            instructions=instructions,
            activation_conditions=conditions,
            examples=examples,
            metadata=meta,
        )

    @classmethod
    def discover_skills(cls, roots: list[Path]) -> dict[str, Skill]:
        """Scan one or more root directories for skill folders."""
        discovered: dict[str, Skill] = {}
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for entry in root.iterdir():
                if entry.is_dir():
                    skill = cls.load_from_dir(entry)
                    if skill:
                        discovered[skill.name] = skill
        return discovered
