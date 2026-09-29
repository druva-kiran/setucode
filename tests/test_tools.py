"""Tests for all 5 file tools — covers AC-6 through AC-12."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from app.tools.registry import build_default_registry
from app.tools.base import ToolResult


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def registry(workspace):
    return build_default_registry(workspace)


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

class TestReadFile:
    def test_reads_existing_file(self, workspace, registry):
        f = workspace / "hello.txt"
        f.write_text("hello world", encoding="utf-8")
        tool = registry.get("read_file")
        result = tool.execute({"path": "hello.txt"})
        assert result.output == "hello world"
        assert not result.is_error

    def test_missing_file_returns_error(self, workspace, registry):
        tool = registry.get("read_file")
        result = tool.execute({"path": "missing.txt"})
        assert result.is_error
        assert "does not exist" in result.error

    def test_path_outside_workspace_blocked(self, workspace, registry):
        tool = registry.get("read_file")
        result = tool.execute({"path": "../../etc/passwd"})
        assert result.is_error
        assert "outside workspace" in result.error

    def test_directory_path_returns_error(self, workspace, registry):
        subdir = workspace / "subdir"
        subdir.mkdir()
        tool = registry.get("read_file")
        result = tool.execute({"path": "subdir"})
        assert result.is_error


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------

class TestWriteFile:
    def test_creates_new_file(self, workspace, registry):
        tool = registry.get("write_file")
        result = tool.execute({"path": "new.py", "content": "print('hi')"})
        assert not result.is_error
        assert (workspace / "new.py").read_text() == "print('hi')"

    def test_overwrites_existing_file(self, workspace, registry):
        f = workspace / "existing.txt"
        f.write_text("old", encoding="utf-8")
        tool = registry.get("write_file")
        result = tool.execute({"path": "existing.txt", "content": "new"})
        assert not result.is_error
        assert f.read_text() == "new"

    def test_creates_parent_dirs(self, workspace, registry):
        tool = registry.get("write_file")
        result = tool.execute({"path": "a/b/c.txt", "content": "deep"})
        assert not result.is_error
        assert (workspace / "a" / "b" / "c.txt").exists()

    def test_path_outside_workspace_blocked(self, workspace, registry):
        tool = registry.get("write_file")
        result = tool.execute({"path": "../escape.txt", "content": "x"})
        assert result.is_error
        assert "outside workspace" in result.error


# ---------------------------------------------------------------------------
# edit_file
# ---------------------------------------------------------------------------

class TestEditFile:
    def _make_patch(self, original: str, old: str, new: str, filename: str = "test.py") -> str:
        """Build a minimal unified diff patch."""
        orig_lines = original.splitlines(keepends=True)
        import difflib
        new_content = original.replace(old, new)
        new_lines = new_content.splitlines(keepends=True)
        diff = list(difflib.unified_diff(
            orig_lines, new_lines,
            fromfile=f"a/{filename}", tofile=f"b/{filename}"
        ))
        return "".join(diff)

    def test_applies_valid_patch(self, workspace, registry):
        f = workspace / "code.py"
        original = "def foo():\n    pass\n"
        f.write_text(original, encoding="utf-8")
        patch = self._make_patch(original, "    pass\n", "    return 42\n", "code.py")
        tool = registry.get("edit_file")
        result = tool.execute({"path": "code.py", "patch": patch})
        assert not result.is_error, result.error
        assert "return 42" in f.read_text()

    def test_empty_patch_returns_error(self, workspace, registry):
        f = workspace / "code.py"
        f.write_text("x = 1\n")
        tool = registry.get("edit_file")
        result = tool.execute({"path": "code.py", "patch": ""})
        assert result.is_error
        assert "empty" in result.error.lower()

    def test_bad_patch_returns_structured_error(self, workspace, registry):
        f = workspace / "code.py"
        f.write_text("x = 1\n")
        bad_patch = "--- a/code.py\n+++ b/code.py\n@@ -99,3 +99,3 @@\n-nonexistent line\n+replaced\n"
        tool = registry.get("edit_file")
        result = tool.execute({"path": "code.py", "patch": bad_patch})
        assert result.is_error

    def test_missing_file_returns_error(self, workspace, registry):
        tool = registry.get("edit_file")
        result = tool.execute({"path": "ghost.py", "patch": "--- a/ghost.py\n+++ b/ghost.py\n"})
        assert result.is_error


# ---------------------------------------------------------------------------
# move_file
# ---------------------------------------------------------------------------

class TestMoveFile:
    def test_moves_file(self, workspace, registry):
        src = workspace / "old.txt"
        src.write_text("content")
        tool = registry.get("move_file")
        result = tool.execute({"source": "old.txt", "destination": "new.txt"})
        assert not result.is_error
        assert not src.exists()
        assert (workspace / "new.txt").read_text() == "content"

    def test_missing_source_returns_error(self, workspace, registry):
        tool = registry.get("move_file")
        result = tool.execute({"source": "ghost.txt", "destination": "out.txt"})
        assert result.is_error

    def test_destination_outside_workspace_blocked(self, workspace, registry):
        src = workspace / "file.txt"
        src.write_text("x")
        tool = registry.get("move_file")
        result = tool.execute({"source": "file.txt", "destination": "../../out.txt"})
        assert result.is_error
        assert "outside workspace" in result.error


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------

class TestListDirectory:
    def test_lists_entries(self, workspace, registry):
        (workspace / "a.py").write_text("")
        (workspace / "b.py").write_text("")
        (workspace / "subdir").mkdir()
        tool = registry.get("list_directory")
        result = tool.execute({"path": "."})
        assert not result.is_error
        assert "a.py" in result.output
        assert "subdir" in result.output

    def test_empty_dir_returns_message(self, workspace, registry):
        sub = workspace / "empty"
        sub.mkdir()
        tool = registry.get("list_directory")
        result = tool.execute({"path": "empty"})
        assert not result.is_error
        assert "empty" in result.output.lower()

    def test_outside_workspace_blocked(self, workspace, registry):
        tool = registry.get("list_directory")
        result = tool.execute({"path": "../../"})
        assert result.is_error


# ---------------------------------------------------------------------------
# Workspace boundary — AC-11 / AC-12
# ---------------------------------------------------------------------------

class TestWorkspaceBoundary:
    def test_symlink_escape_blocked(self, workspace, registry):
        """A symlink pointing outside the workspace must be rejected."""
        import tempfile, os
        # Create a truly separate temp directory (not inside workspace)
        with tempfile.TemporaryDirectory() as outside_dir:
            target = Path(outside_dir) / "secret.txt"
            target.write_text("secret")
            link = workspace / "link.txt"
            link.symlink_to(target)
            tool = registry.get("read_file")
            result = tool.execute({"path": "link.txt"})
            # Symlink resolves outside workspace_root → should be blocked
            assert result.is_error
            assert "outside workspace" in result.error


# ---------------------------------------------------------------------------
# run_command tool
# ---------------------------------------------------------------------------

class TestRunCommand:
    def test_run_simple_command(self, workspace, registry):
        tool = registry.get("run_command")
        assert tool is not None
        result = tool.execute({"command": "echo hello_setucode"})
        assert not result.is_error
        assert "hello_setucode" in result.output

    def test_run_empty_command(self, workspace, registry):
        tool = registry.get("run_command")
        result = tool.execute({"command": ""})
        assert result.is_error

