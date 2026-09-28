"""Tests for the Permission system — covers AC-13 through AC-17."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.permissions.manager import PermissionManager
from app.permissions.policy import PermissionDecision
from app.permissions.storage import PermissionStorage
from app.tools.base import ToolResult
from app.tools.registry import build_default_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "permissions.json"


@pytest.fixture
def storage(storage_path):
    return PermissionStorage(storage_path)


@pytest.fixture
def registry(workspace):
    return build_default_registry(workspace)


def make_manager(storage, decision: PermissionDecision):
    """Build a PermissionManager whose request_fn always returns decision."""
    request_fn = MagicMock(return_value=decision)
    return PermissionManager(storage, request_fn), request_fn


class TestReadonlyAutoAllow:
    def test_readonly_tool_is_auto_allowed(self, storage, registry, workspace):
        """AC-10: list_directory and read_file must never trigger a prompt."""
        mgr, request_fn = make_manager(storage, PermissionDecision.ALLOW_ONCE)
        tool = registry.get("read_file")
        decision = mgr.check(tool, {"path": "x.txt"}, workspace)
        assert decision == PermissionDecision.AUTO_ALLOWED
        request_fn.assert_not_called()

    def test_list_directory_auto_allowed(self, storage, registry, workspace):
        mgr, request_fn = make_manager(storage, PermissionDecision.ALLOW_ONCE)
        tool = registry.get("list_directory")
        decision = mgr.check(tool, {"path": "."}, workspace)
        assert decision == PermissionDecision.AUTO_ALLOWED
        request_fn.assert_not_called()


class TestAllowOnce:
    def test_allow_once_does_not_persist(self, storage, registry, workspace, storage_path):
        """AC-14: Allow once must not write a rule; next call prompts again."""
        mgr, request_fn = make_manager(storage, PermissionDecision.ALLOW_ONCE)
        tool = registry.get("write_file")
        (workspace / "x.txt").write_text("")

        first = mgr.check(tool, {"path": "x.txt"}, workspace)
        assert first == PermissionDecision.ALLOW_ONCE

        second = mgr.check(tool, {"path": "x.txt"}, workspace)
        assert second == PermissionDecision.ALLOW_ONCE
        assert request_fn.call_count == 2   # prompted twice


class TestAllowAlways:
    def test_allow_always_stores_rule(self, storage, registry, workspace, storage_path):
        """AC-15: Allow always must write a rule and skip future prompts."""
        mgr, request_fn = make_manager(storage, PermissionDecision.ALLOW_ALWAYS)
        tool = registry.get("write_file")
        (workspace / "y.txt").write_text("")

        first = mgr.check(tool, {"path": "y.txt"}, workspace)
        assert first == PermissionDecision.ALLOW_ALWAYS

        # Second call: storage should have the rule, so no prompt
        mgr2, request_fn2 = make_manager(storage, PermissionDecision.DENY)
        second = mgr2.check(tool, {"path": "y.txt"}, workspace)
        assert second == PermissionDecision.AUTO_ALLOWED
        request_fn2.assert_not_called()

    def test_allow_always_dir_a_does_not_cover_dir_b(
        self, storage, registry, workspace
    ):
        """AC-15 (D-2): allow always for dir_A must not suppress prompt for dir_B."""
        (workspace / "src").mkdir()
        (workspace / "tests").mkdir()

        # Store allow-always for src/
        storage.store_always("write_file", str(workspace / "src"))

        mgr, request_fn = make_manager(storage, PermissionDecision.DENY)
        tool = registry.get("write_file")

        # src/ → auto-allowed
        (workspace / "src" / "main.py").write_text("")
        decision_src = mgr.check(tool, {"path": "src/main.py"}, workspace)
        assert decision_src == PermissionDecision.AUTO_ALLOWED

        # tests/ → prompts
        (workspace / "tests" / "test_main.py").write_text("")
        decision_tests = mgr.check(tool, {"path": "tests/test_main.py"}, workspace)
        assert decision_tests == PermissionDecision.DENY
        request_fn.assert_called_once()


class TestDeny:
    def test_deny_blocks_execution(self, storage, registry, workspace):
        """AC-16: Deny must return DENY; nothing written to storage."""
        mgr, _ = make_manager(storage, PermissionDecision.DENY)
        tool = registry.get("edit_file")
        decision = mgr.check(tool, {"path": "x.txt"}, workspace)
        assert decision == PermissionDecision.DENY

    def test_deny_does_not_write_storage(self, storage, registry, workspace, storage_path):
        mgr, _ = make_manager(storage, PermissionDecision.DENY)
        tool = registry.get("write_file")
        mgr.check(tool, {"path": "x.txt"}, workspace)
        assert not storage_path.exists() or storage_path.read_text() in ("{}", "")


class TestStorageFallback:
    def test_missing_storage_file_returns_empty_rules(self, tmp_path):
        """Permission storage must not crash when the file is missing."""
        s = PermissionStorage(tmp_path / "nonexistent.json")
        assert not s.is_always_allowed("write_file", tmp_path / "x.txt")

    def test_corrupt_storage_file_returns_empty_rules(self, tmp_path):
        """Permission storage must not crash when the file is corrupt."""
        p = tmp_path / "permissions.json"
        p.write_text("NOT JSON {{{{")
        s = PermissionStorage(p)
        assert not s.is_always_allowed("write_file", tmp_path / "x.txt")
