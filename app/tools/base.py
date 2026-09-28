"""ToolResult — the normalised return type for every tool execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ToolResult:
    output: str | None = None
    error: str | None = None

    @property
    def is_error(self) -> bool:
        return self.error is not None

    def to_message_content(self) -> str:
        """Format result for insertion into the LLM conversation."""
        if self.output is not None:
            return self.output
        return f"ERROR: {self.error}"


PermissionCategory = Literal["readonly", "modifying", "high_risk"]
