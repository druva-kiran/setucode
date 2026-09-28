"""Late Prompt Injection and Dynamic Context Management.

Coordinates injecting dynamic context after initial planning:
- discovered project info
- relevant file excerpts
- compiler errors / test failures
- subagent results
- dynamically activated skills
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.context.dedup import ContextDeduplicator

log = logging.getLogger(__name__)


# Priority constants (lower number = higher priority)
PRIORITY_USER_REQUEST = 1
PRIORITY_TASK_STATE = 2
PRIORITY_RELEVANT_CODE = 3
PRIORITY_RECENT_RESULTS_ERRORS = 4
PRIORITY_PROJECT_RULES = 5
PRIORITY_HISTORICAL = 6
PRIORITY_LOW_VALUE = 7


@dataclass
class ContextItem:
    category: str
    content: str
    title: str = ""
    priority: int = PRIORITY_RECENT_RESULTS_ERRORS
    key: str = ""
    is_transient: bool = False


class LateContextManager:
    """Maintains, prioritizes, deduplicates, and formats late context for injection."""

    def __init__(self, deduplicator: ContextDeduplicator | None = None) -> None:
        self._deduplicator = deduplicator or ContextDeduplicator()
        self._items: dict[str, ContextItem] = {}

    def add(
        self,
        category: str,
        content: str,
        title: str = "",
        priority: int = PRIORITY_RECENT_RESULTS_ERRORS,
        key: str | None = None,
        is_transient: bool = False,
    ) -> bool:
        """Add context item. Returns True if added, False if duplicate."""
        if not content or not content.strip():
            return False

        item_key = key or f"{category}:{title}:{content[:64]}"

        # For error categories, process through error deduplicator
        if category in ("compiler_error", "test_failure", "error"):
            processed_content = self._deduplicator.process_error(content)
        else:
            if self._deduplicator.is_duplicate(content, namespace=category):
                log.debug("Late context duplicate skipped: %s", item_key)
                return False
            processed_content = content

        self._items[item_key] = ContextItem(
            category=category,
            content=processed_content,
            title=title or category.replace("_", " ").title(),
            priority=priority,
            key=item_key,
            is_transient=is_transient,
        )
        log.info("Late context added [%s]: %s (priority %d)", category, title, priority)
        return True

    def get_items(self) -> list[ContextItem]:
        """Return items sorted by priority (highest first)."""
        return sorted(self._items.values(), key=lambda x: x.priority)

    def render_markdown(self) -> str:
        """Render all pending late context items into a structured markdown block."""
        items = self.get_items()
        if not items:
            return ""

        sections = ["## Relevant Dynamic Context (Late Injection)"]
        for item in items:
            sections.append(f"### {item.title}\n{item.content.strip()}")

        return "\n\n".join(sections)

    def clear_transient(self) -> None:
        """Remove transient items after prompt generation."""
        transient_keys = [k for k, item in self._items.items() if item.is_transient]
        for k in transient_keys:
            del self._items[k]

    def clear_all(self) -> None:
        self._items.clear()
        self._deduplicator.clear()
