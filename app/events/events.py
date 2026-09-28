"""Event dataclasses for the SetuCode agent lifecycle.

Each function is a named constructor that returns an AgentEvent. The Agent
Loop emits these; the TUI and other listeners consume them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AgentEvent:
    name: str
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.timestamp:%H:%M:%S}] {self.name} {self.data or ''}"


# ---------------------------------------------------------------------------
# Named constructors — one per lifecycle event
# ---------------------------------------------------------------------------

def Thinking() -> AgentEvent:
    """Emitted immediately before each LLM call."""
    return AgentEvent(name="Thinking")


def PreToolUse(tool_name: str, args: dict) -> AgentEvent:
    """Emitted when the loop detects a tool call, before permission check."""
    return AgentEvent(name="PreToolUse", data={"tool": tool_name, "args": args})


def PostToolUse(tool_name: str, result: Any, is_error: bool = False) -> AgentEvent:
    """Emitted after tool execution (success or failure)."""
    return AgentEvent(
        name="PostToolUse",
        data={"tool": tool_name, "result": result, "error": is_error},
    )


def Stop(reason: str = "done") -> AgentEvent:
    """Emitted when the loop terminates (final answer or error)."""
    return AgentEvent(name="Stop", data={"reason": reason})


def PermissionRequest(tool_name: str, path: str) -> AgentEvent:
    """Emitted when the permission system needs a human decision."""
    return AgentEvent(
        name="PermissionRequest", data={"tool": tool_name, "path": path}
    )
