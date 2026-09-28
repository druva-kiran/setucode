"""Unified Context Manager for SetuCode agent.

Brings together:
- PrefixCache (KV-cache optimization & static prompt stability)
- ContextBudget (token estimation, headroom reservation)
- ContextDeduplicator (content & error deduplication)
- LateContextManager (late prompt injection of errors, subagent results, dynamic context)
- ContextCompactor (context compaction preserving task, modified files, plan, errors)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.state import AgentState
from app.context.budget import ContextBudget, estimate_tokens
from app.context.compaction import ContextCompactor
from app.context.dedup import ContextDeduplicator
from app.context.late_injection import LateContextManager
from app.context.prefix_cache import PrefixCache

log = logging.getLogger(__name__)


class ContextManager:
    """Central manager for context lifecycle, budgeting, and late injection."""

    def __init__(
        self,
        budget: ContextBudget | None = None,
        deduplicator: ContextDeduplicator | None = None,
    ) -> None:
        self.budget = budget or ContextBudget()
        self.deduplicator = deduplicator or ContextDeduplicator()
        self.late_context = LateContextManager(self.deduplicator)

    def add_late_context(
        self,
        category: str,
        content: str,
        title: str = "",
        priority: int = 4,
        key: str | None = None,
        is_transient: bool = False,
    ) -> bool:
        """Add dynamic late context (e.g. error, test result, subagent output)."""
        return self.late_context.add(
            category=category,
            content=content,
            title=title,
            priority=priority,
            key=key,
            is_transient=is_transient,
        )

    def check_and_compact(self, state: AgentState) -> bool:
        """Evaluate context size against budget and compact if approaching limits."""
        current_tokens = estimate_tokens(state.messages)
        if self.budget.should_compact(current_tokens):
            log.warning(
                "Context token count (%d) exceeded compaction threshold (%d); initiating compaction",
                current_tokens,
                self.budget.compaction_token_limit,
            )
            state.messages = ContextCompactor.compact(
                state.messages, plan=getattr(state, "plan", None)
            )
            return True
        return False

    def inject_pending_late_context(self, state: AgentState) -> bool:
        """Inject any pending late context items as a system message before the next LLM call."""
        rendered = self.late_context.render_markdown()
        if not rendered:
            return False

        state.messages.append({
            "role": "system",
            "content": rendered,
            "_late_injection": True,
        })
        self.late_context.clear_transient()
        return True

    def build_initial_system_prompt(self, state: AgentState) -> str:
        """Build KV-cache-friendly system prompt with static prefix first."""
        user_mem = getattr(state, "user_memory", "")
        proj_mem = getattr(state, "project_memory", "")
        return PrefixCache.compose_prompt(user_mem, proj_mem)
