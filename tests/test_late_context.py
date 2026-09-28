"""Unit tests for Late Prompt Injection and Context Prioritization."""
from __future__ import annotations

import pytest

from app.context.dedup import ContextDeduplicator
from app.context.late_injection import (
    LateContextManager,
    PRIORITY_PROJECT_RULES,
    PRIORITY_RECENT_RESULTS_ERRORS,
    PRIORITY_TASK_STATE,
)


def test_late_context_addition_and_ordering():
    """Context items are ordered by priority (highest priority first)."""
    mgr = LateContextManager()

    mgr.add(
        category="project_rules",
        content="Must use Python 3.12 syntax.",
        title="Project Rule",
        priority=PRIORITY_PROJECT_RULES,
    )
    mgr.add(
        category="task_state",
        content="Currently refactoring auth module.",
        title="Active Task",
        priority=PRIORITY_TASK_STATE,
    )
    mgr.add(
        category="compiler_error",
        content="SyntaxError at line 42",
        title="Syntax Error",
        priority=PRIORITY_RECENT_RESULTS_ERRORS,
    )

    items = mgr.get_items()
    # Task state (2) comes before Compiler error (4) which comes before Project rules (5)
    assert items[0].category == "task_state"
    assert items[1].category == "compiler_error"
    assert items[2].category == "project_rules"


def test_late_context_deduplication():
    """Identical late context items are deduplicated and not added twice."""
    mgr = LateContextManager()

    added1 = mgr.add("relevant_code", "def foo(): pass", title="Foo Function")
    added2 = mgr.add("relevant_code", "def foo(): pass", title="Foo Function")

    assert added1 is True
    assert added2 is False
    assert len(mgr.get_items()) == 1


def test_repeated_error_compression():
    """Repeated error messages are compressed to avoid prompt pollution."""
    mgr = LateContextManager()
    err_text = "ConnectionRefusedError: [Errno 111] Connection refused at server:8080\nTraceback line 10"

    mgr.add("compiler_error", err_text, title="Network Error")
    mgr.add("compiler_error", err_text, title="Network Error", key="err_2")

    items = mgr.get_items()
    assert len(items) == 2
    assert "Repeated error" in items[1].content


def test_transient_cleanup():
    """Transient items are cleared when requested, persistent items stay."""
    mgr = LateContextManager()

    mgr.add("test_failure", "test_x failed", title="Failed test", is_transient=True)
    mgr.add("task_plan", "Plan: step 1, step 2", title="Plan", is_transient=False)

    assert len(mgr.get_items()) == 2
    mgr.clear_transient()
    items = mgr.get_items()
    assert len(items) == 1
    assert items[0].category == "task_plan"
