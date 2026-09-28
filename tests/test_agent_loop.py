"""Tests for the Agent Loop — covers AC-1, AC-2, AC-3."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.agent.loop import run
from app.agent.state import AgentState, AgentStatus
from app.events.bus import EventBus
from app.permissions.manager import PermissionManager
from app.permissions.policy import PermissionDecision
from app.providers.base import BaseProvider, ModelResponse, ToolCall
from app.tools.base import ToolResult
from app.tools.registry import build_default_registry


class MockProvider(BaseProvider):
    """Provider that returns pre-configured responses in sequence."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = iter(responses)

    def generate(self, messages, tools) -> ModelResponse:
        return next(self._responses)


def make_state(workspace: Path, provider: BaseProvider, registry) -> AgentState:
    return AgentState(
        session_id="test-session",
        workspace=workspace,
        model=provider,
        available_tools=registry.schema_list(),
    )


def make_auto_permissions(workspace: Path) -> PermissionManager:
    from app.permissions.storage import PermissionStorage
    storage = MagicMock(spec=PermissionStorage)
    storage.is_always_allowed.return_value = False
    request_fn = MagicMock(return_value=PermissionDecision.ALLOW_ONCE)
    return PermissionManager(storage, request_fn)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def registry(workspace):
    return build_default_registry(workspace)


class TestFinalResponse:
    def test_returns_final_text(self, workspace, registry):
        """AC-1: Loop must return the LLM's final text response."""
        provider = MockProvider([ModelResponse(final_text="Hello, world!")])
        bus = EventBus()
        state = make_state(workspace, provider, registry)
        perms = make_auto_permissions(workspace)

        result = run(state, "Say hello", bus, registry, perms)

        assert result == "Hello, world!"
        assert state.status == AgentStatus.FINISHED

    def test_emits_stop_on_finish(self, workspace, registry):
        """Loop must emit Stop when a final response is reached."""
        provider = MockProvider([ModelResponse(final_text="Done")])
        bus = EventBus()
        received = []
        bus.subscribe(received.append)
        state = make_state(workspace, provider, registry)
        perms = make_auto_permissions(workspace)

        run(state, "Do something", bus, registry, perms)

        names = [e.name for e in received]
        assert "Thinking" in names
        assert "Stop" in names

    def test_emits_thinking_before_llm_call(self, workspace, registry):
        provider = MockProvider([ModelResponse(final_text="ok")])
        bus = EventBus()
        received = []
        bus.subscribe(received.append)
        state = make_state(workspace, provider, registry)
        perms = make_auto_permissions(workspace)

        run(state, "test", bus, registry, perms)

        assert received[0].name == "Thinking"


class TestToolCallFlow:
    def test_tool_call_dispatched_through_permissions(self, workspace, registry):
        """AC-2: tool calls must pass through permission layer, never skipped."""
        # First response: tool call. Second: final text.
        tc = ToolCall(id="tc1", name="list_directory", args={"path": "."})
        provider = MockProvider([
            ModelResponse(tool_calls=[tc]),
            ModelResponse(final_text="Listed files."),
        ])
        bus = EventBus()
        received = []
        bus.subscribe(received.append)

        state = make_state(workspace, provider, registry)

        from app.permissions.storage import PermissionStorage
        storage = MagicMock(spec=PermissionStorage)
        storage.is_always_allowed.return_value = False
        request_fn = MagicMock(return_value=PermissionDecision.ALLOW_ONCE)
        perms = PermissionManager(storage, request_fn)

        result = run(state, "list files", bus, registry, perms)

        assert result == "Listed files."
        names = [e.name for e in received]
        assert "PreToolUse" in names
        assert "PostToolUse" in names

    def test_unknown_tool_returns_error_to_loop(self, workspace, registry):
        """AC-3: unknown tool must return error, not crash."""
        tc = ToolCall(id="tc1", name="nonexistent_tool", args={})
        provider = MockProvider([
            ModelResponse(tool_calls=[tc]),
            ModelResponse(final_text="I understand."),
        ])
        bus = EventBus()
        state = make_state(workspace, provider, registry)
        perms = make_auto_permissions(workspace)

        result = run(state, "do something weird", bus, registry, perms)

        # Loop should recover and return the second response
        assert result == "I understand."
        assert state.status == AgentStatus.FINISHED


class TestErrorRecovery:
    def test_tool_error_does_not_crash_loop(self, workspace, registry):
        """AC-3: tool execution errors must be returned to the LLM, not raised."""
        tc = ToolCall(id="tc1", name="read_file", args={"path": "missing.txt"})
        provider = MockProvider([
            ModelResponse(tool_calls=[tc]),
            ModelResponse(final_text="File not found, sorry."),
        ])
        bus = EventBus()
        state = make_state(workspace, provider, registry)
        perms = make_auto_permissions(workspace)

        result = run(state, "read missing.txt", bus, registry, perms)

        assert result == "File not found, sorry."
        assert state.status == AgentStatus.FINISHED

    def test_llm_api_error_returns_error_string(self, workspace, registry):
        """Loop must handle LLM exceptions gracefully."""
        class ErrorProvider(BaseProvider):
            def generate(self, messages, tools):
                raise ConnectionError("timeout")

        bus = EventBus()
        state = make_state(workspace, ErrorProvider(), registry)
        perms = make_auto_permissions(workspace)

        result = run(state, "hello", bus, registry, perms)

        assert "Error" in result
        assert state.status == AgentStatus.ERROR

    def test_deny_returns_denial_result_to_llm(self, workspace, registry):
        """AC-16: Deny must not crash; LLM receives denial message."""
        tc = ToolCall(id="tc1", name="write_file", args={"path": "x.txt", "content": "y"})
        provider = MockProvider([
            ModelResponse(tool_calls=[tc]),
            ModelResponse(final_text="Understood, I won't write."),
        ])
        bus = EventBus()
        state = make_state(workspace, provider, registry)

        from app.permissions.storage import PermissionStorage
        storage = MagicMock(spec=PermissionStorage)
        storage.is_always_allowed.return_value = False
        deny_fn = MagicMock(return_value=PermissionDecision.DENY)
        perms = PermissionManager(storage, deny_fn)

        result = run(state, "write x.txt", bus, registry, perms)

        assert result == "Understood, I won't write."
        # Check the denial was in the messages sent to LLM
        tool_result_msgs = [m for m in state.messages if m.get("role") == "tool"]
        assert any("Permission denied" in m.get("content", "") for m in tool_result_msgs)
