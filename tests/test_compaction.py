"""Unit tests for Context Compaction and Working State Preservation."""
from __future__ import annotations

import pytest

from app.context.budget import ContextBudget, estimate_tokens
from app.context.compaction import CompactWorkingState, ContextCompactor
from app.plan.model import Plan


def test_token_budget_and_compaction_trigger():
    """ContextBudget flags compaction when token threshold is reached."""
    budget = ContextBudget(max_tokens=1000, reserve_response_tokens=200, compaction_threshold_ratio=0.8)
    assert budget.usable_tokens == 800
    assert budget.compaction_token_limit == 640

    assert budget.should_compact(500) is False
    assert budget.should_compact(650) is True


def test_compact_working_state_render():
    """CompactWorkingState formats all required sections cleanly."""
    state = CompactWorkingState(
        task="Implement user authentication",
        current_state="Fixing token verification",
        important_decisions=["Use bcrypt for passwords"],
        files_modified=["app/auth.py", "tests/test_auth.py"],
        plan_text="[x] 1. Models\n[>] 2. Endpoint",
        errors=["Invalid token error"],
        test_status="Tests passing",
    )
    rendered = state.render()

    assert "**TASK:**\nImplement user authentication" in rendered
    assert "**CURRENT STATE:**\nFixing token verification" in rendered
    assert "- Use bcrypt for passwords" in rendered
    assert "- app/auth.py" in rendered
    assert "[x] 1. Models" in rendered
    assert "- Invalid token error" in rendered
    assert "**TEST STATUS:**\nTests passing" in rendered


def test_context_compaction_preserves_task_files_and_plan():
    """Compactor summarizes older messages without losing critical state or plan."""
    plan = Plan()
    plan.add_task("Create auth endpoint", status="in_progress")

    messages = [
        {"role": "system", "content": "You are SetuCode."},
        {"role": "user", "content": "Implement user authentication in app/auth.py"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "name": "write_file", "args": {"path": "app/auth.py"}}],
        },
        {"role": "tool", "name": "write_file", "content": "File written"},
        {"role": "assistant", "content": "I wrote the file, let me run tests."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "2", "name": "read_file", "args": {"path": "tests/test_auth.py"}}],
        },
        {"role": "tool", "name": "read_file", "content": "ERROR: File not found"},
        {"role": "assistant", "content": "Let me create tests now."},
        {"role": "user", "content": "Please proceed with tests."},
    ]

    compacted = ContextCompactor.compact(messages, plan=plan, preserve_recent_turns=2)

    # Must be shorter than original messages list
    assert len(compacted) < len(messages)
    # First message is system prompt
    assert compacted[0]["role"] == "system"
    # Second message is the compact working state
    assert compacted[1]["_compacted"] is True
    compact_text = compacted[1]["content"]
    assert "Implement user authentication" in compact_text
    assert "app/auth.py" in compact_text
    assert "Create auth endpoint" in compact_text
    # Recent user turn is preserved at the end
    assert compacted[-1]["content"] == "Please proceed with tests."
