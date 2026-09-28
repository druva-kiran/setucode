"""Tests for MemoryManager — covers AC-19, AC-20, AC-21."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.memory.manager import MemoryManager
from app.providers.base import BaseProvider, ModelResponse


class TestLoadUserMemory:
    def test_returns_content_when_exists(self, tmp_path):
        user_md = tmp_path / "USER.md"
        user_md.write_text("- Prefers minimal changes\n", encoding="utf-8")
        mgr = MemoryManager(user_md)
        assert "Prefers minimal changes" in mgr.load_user_memory()

    def test_returns_empty_when_missing(self, tmp_path):
        mgr = MemoryManager(tmp_path / "USER.md")
        assert mgr.load_user_memory() == ""


class TestLoadProjectMemory:
    def test_returns_content_when_agents_md_exists(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "AGENTS.md").write_text("- Use Python 3.12", encoding="utf-8")
        mgr = MemoryManager(tmp_path / "USER.md")
        assert "Use Python 3.12" in mgr.load_project_memory(workspace)

    def test_returns_empty_when_agents_md_missing(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        mgr = MemoryManager(tmp_path / "USER.md")
        assert mgr.load_project_memory(workspace) == ""


class TestSeparateContextBlocks:
    def test_user_and_project_memory_are_separate(self, tmp_path):
        """AC-21: USER.md and AGENTS.md must be loaded as distinct strings."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        user_md = tmp_path / "USER.md"
        user_md.write_text("USER PREF", encoding="utf-8")
        (workspace / "AGENTS.md").write_text("PROJECT RULE", encoding="utf-8")

        mgr = MemoryManager(user_md)
        user_mem = mgr.load_user_memory()
        project_mem = mgr.load_project_memory(workspace)

        assert "USER PREF" in user_mem
        assert "PROJECT RULE" not in user_mem
        assert "PROJECT RULE" in project_mem
        assert "USER PREF" not in project_mem


class TestWriteSessionMemories:
    def test_appends_new_preferences(self, tmp_path):
        """AC-19: new preferences from session must be written to USER.md."""
        user_md = tmp_path / "USER.md"
        user_md.write_text("- Existing pref\n", encoding="utf-8")

        class MockProvider(BaseProvider):
            def generate(self, messages, tools):
                return ModelResponse(final_text="- New pref extracted\n")

        mgr = MemoryManager(user_md)
        messages = [
            {"role": "user", "content": "Use tabs for indentation."},
            {"role": "assistant", "content": "Got it."},
        ]
        mgr.write_session_memories(messages, MockProvider())
        content = user_md.read_text()
        assert "Existing pref" in content
        assert "New pref extracted" in content

    def test_none_response_does_not_write(self, tmp_path):
        user_md = tmp_path / "USER.md"
        user_md.write_text("- Existing\n")

        class NoneProvider(BaseProvider):
            def generate(self, messages, tools):
                return ModelResponse(final_text="NONE")

        mgr = MemoryManager(user_md)
        mgr.write_session_memories(
            [{"role": "user", "content": "hi"}], NoneProvider()
        )
        assert user_md.read_text() == "- Existing\n"

    def test_llm_failure_does_not_crash(self, tmp_path):
        user_md = tmp_path / "USER.md"
        user_md.write_text("")

        class FailProvider(BaseProvider):
            def generate(self, messages, tools):
                raise RuntimeError("network error")

        mgr = MemoryManager(user_md)
        # Must not raise
        mgr.write_session_memories([{"role": "user", "content": "x"}], FailProvider())
