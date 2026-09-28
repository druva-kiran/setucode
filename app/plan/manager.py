"""Plan Manager — persistent plan storage, complexity detection, and recovery."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from app.plan.model import Plan, Task

log = logging.getLogger(__name__)

# Heuristics for detecting complex multi-step tasks
_COMPLEX_PATTERNS = [
    r"\b(first|then|after that|finally)\b",
    r"\b(implement|refactor|create|build|migrate|setup)\b.{10,}\b(and|with|test|verify)\b",
    r"\b(step\s*1|step\s*2|phase\s*1)\b",
    r"\b(architecture|multi-step|workflow|pipeline)\b",
    r"(\n\s*[-*]\s+.+){2,}",  # Multi-line bullet points
    r"(\n\s*\d+\.\s+.+){2,}",  # Numbered lists
]


def is_complex_task(user_message: str) -> bool:
    """Determine whether the request warrants an explicit structured plan."""
    text = user_message.strip()
    # Simple short greetings or single-file commands shouldn't trigger heavy planning
    if len(text.split()) < 6 and "\n" not in text:
        return False

    for pattern in _COMPLEX_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    # If it's a long, detailed instruction (>35 words), treat as complex
    if len(text.split()) > 35:
        return True

    return False


def create_initial_plan(user_message: str) -> Plan:
    """Generate a sensible task breakdown from a complex user request."""
    plan = Plan()

    # If numbered or bullet list is present in the prompt, extract tasks directly
    bullet_items = re.findall(r"(?:^|\n)\s*(?:[-*]|\d+\.)\s+([^\n]+)", user_message)
    if len(bullet_items) >= 2:
        for item in bullet_items:
            plan.add_task(item.strip())
        return plan

    # Otherwise, create structured milestones based on coding workflow
    plan.add_task("Inspect workspace and relevant files", status="in_progress")
    plan.add_task("Design changes and prepare implementation")
    plan.add_task("Apply code modifications")
    plan.add_task("Run tests and verify functionality")
    return plan


class PlanManager:
    """Handles plan persistence to workspace and plan recovery after context compaction."""

    @staticmethod
    def plan_path(workspace: Path) -> Path:
        return workspace / "plan.json"

    @classmethod
    def load_plan(cls, workspace: Path) -> Optional[Plan]:
        """Recover the plan from disk or return None."""
        path = cls.plan_path(workspace)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Plan.from_dict(data)
        except Exception as exc:
            log.warning("Failed to load plan from %s: %s", path, exc)
            return None

    @classmethod
    def save_plan(cls, workspace: Path, plan: Plan) -> None:
        """Persist plan to disk."""
        path = cls.plan_path(workspace)
        try:
            path.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("Failed to save plan to %s: %s", path, exc)

    @classmethod
    def delete_plan(cls, workspace: Path) -> None:
        path = cls.plan_path(workspace)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
