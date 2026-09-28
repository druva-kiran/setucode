"""Data models and limits for Subagent delegation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional


class SubagentRole(str, Enum):
    RESEARCHER = "researcher"
    CODE_ANALYZER = "code_analyzer"
    CODER = "coder"
    TESTER = "tester"
    DEBUGGER = "debugger"
    REVIEWER = "reviewer"


@dataclass
class SubagentLimits:
    """Execution limits to prevent runaway loops or unbounded recursion."""
    max_subagents: int = 5
    max_depth: int = 1
    max_steps_per_subagent: int = 8


@dataclass
class SubagentResult:
    """Structured result returned by a subagent to the main agent."""
    role: str
    task: str
    success: bool
    summary: str
    modified_files: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    tokens_used: int = 0

    def to_markdown(self) -> str:
        status_str = "SUCCESS" if self.success else "FAILED"
        lines = [
            f"#### Subagent Result: {self.role.upper()} [{status_str}]",
            f"**Task:** {self.task}",
            f"**Summary:** {self.summary}",
        ]
        if self.modified_files:
            lines.append(f"**Modified Files:** {', '.join(self.modified_files)}")
        if self.error:
            lines.append(f"**Error:** {self.error}")
        return "\n".join(lines)
