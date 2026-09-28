"""AgentState — single source of truth for one running session.

One AgentState instance is created per session. Multiple concurrent sessions
each get their own independent instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.providers.base import BaseProvider, ToolCall


class AgentStatus(Enum):
    IDLE = "Idle"
    THINKING = "Thinking"
    WAITING_FOR_PERMISSION = "Waiting for permission"
    EXECUTING_TOOL = "Executing tool"
    FINISHED = "Finished"
    ERROR = "Error"


@dataclass
class AgentState:
    """All mutable state for one agent session.

    Does NOT own: permission rules (PermissionStorage), LLM credentials (Settings).
    """
    session_id: str
    workspace: Path                   # validated absolute path; set once at creation
    model: BaseProvider
    available_tools: list[dict]       # JSON-schema defs passed to LLM

    messages: list[dict] = field(default_factory=list)
    status: AgentStatus = AgentStatus.IDLE
    pending_permission: ToolCall | None = None
    user_memory: str = ""             # contents of USER.md, injected at session start
    project_memory: str = ""          # contents of AGENTS.md, injected at session start
    plan: Any = None                  # active Plan instance if planning is active
    context_manager: Any = None       # ContextManager instance for late injection / compaction
