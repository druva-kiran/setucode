"""Unit tests for Subagent architecture, delegation limits, and sandbox inheritance."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.events.bus import EventBus
from app.permissions.manager import PermissionManager
from app.permissions.policy import PermissionDecision
from app.providers.base import BaseProvider, ModelResponse, ToolCall
from app.subagents.manager import SubagentManager
from app.subagents.model import SubagentLimits, SubagentRole
from app.subagents.tools import make_delegate_task
from app.tools.registry import build_default_registry


class MockLLM(BaseProvider):
    def __init__(self, text: str = "Task accomplished."):
        self.text = text

    def generate(self, messages, tools):
        return ModelResponse(final_text=self.text)


def make_test_env(tmp_path: Path):
    storage = MagicMock()
    storage.is_always_allowed.return_value = False
    perms = PermissionManager(storage, lambda name, path: PermissionDecision.ALLOW_ONCE)
    registry = build_default_registry(tmp_path)
    return perms, registry


def test_subagent_role_tool_filtering(tmp_path: Path):
    """Read-only subagents only receive read-only tools."""
    perms, registry = make_test_env(tmp_path)
    mgr = SubagentManager(tmp_path, perms, registry)

    researcher_tools = mgr._filter_tools_for_role(SubagentRole.RESEARCHER.value)
    coder_tools = mgr._filter_tools_for_role(SubagentRole.CODER.value)

    # Researcher has read_file but NOT write_file
    assert researcher_tools.get("read_file") is not None
    assert researcher_tools.get("write_file") is None

    # Coder has both
    assert coder_tools.get("read_file") is not None
    assert coder_tools.get("write_file") is not None


def test_subagent_count_limit(tmp_path: Path):
    """SubagentManager prevents spawning more than max_subagents."""
    perms, registry = make_test_env(tmp_path)
    limits = SubagentLimits(max_subagents=2, max_depth=1)
    mgr = SubagentManager(tmp_path, perms, registry, limits=limits)

    model = MockLLM()
    # First 2 should succeed
    res1 = mgr.run_subagent(SubagentRole.RESEARCHER.value, "Task 1", model=model)
    assert res1.success is True

    res2 = mgr.run_subagent(SubagentRole.RESEARCHER.value, "Task 2", model=model)
    assert res2.success is True

    # 3rd must be rejected due to count limit
    res3 = mgr.run_subagent(SubagentRole.RESEARCHER.value, "Task 3", model=model)
    assert res3.success is False
    assert "Maximum subagent count" in res3.summary


def test_subagent_depth_limit(tmp_path: Path):
    """Subagents at max depth cannot spawn nested subagents."""
    perms, registry = make_test_env(tmp_path)
    limits = SubagentLimits(max_subagents=5, max_depth=1)
    # Child manager created with depth 1
    child_mgr = SubagentManager(tmp_path, perms, registry, limits=limits, current_depth=1)

    allowed, reason = child_mgr.can_delegate()
    assert allowed is False
    assert "depth" in reason.lower()


def test_subagent_sandbox_inheritance(tmp_path: Path):
    """Subagent executions are subject to the same permission and sandbox rules."""
    storage = MagicMock()
    storage.is_always_allowed.return_value = False
    # Deny all mutating actions
    perms = PermissionManager(storage, lambda name, path: PermissionDecision.DENY)
    registry = build_default_registry(tmp_path)
    mgr = SubagentManager(tmp_path, perms, registry)

    # Model that tries to call write_file
    class CoderLLM(BaseProvider):
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(
                    tool_calls=[ToolCall("1", "write_file", {"path": "secret.txt", "content": "data"})]
                )
            return ModelResponse(final_text="Permission was denied, stopping.")

    res = mgr.run_subagent(SubagentRole.CODER.value, "Write secret.txt", model=CoderLLM())
    assert res.success is True
    # secret.txt must not exist because permission was denied!
    assert not (tmp_path / "secret.txt").exists()


def test_delegate_task_tool(tmp_path: Path):
    """delegate_task tool executes subagent and returns markdown summary."""
    perms, registry = make_test_env(tmp_path)
    mgr = SubagentManager(tmp_path, perms, registry)
    tool = make_delegate_task(mgr, MockLLM("Analysis complete."), EventBus())

    result = tool.execute({
        "role": "researcher",
        "task": "Investigate repo structure",
    })
    assert not result.is_error
    assert "Subagent Result: RESEARCHER" in result.output
    assert "Analysis complete." in result.output
