"""Abstract provider interface and shared data types.

All LLM provider implementations must subclass BaseProvider and implement
generate(). The Agent Loop only ever calls this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    """A single tool call requested by the LLM."""
    id: str
    name: str
    args: dict


@dataclass
class ModelResponse:
    """Normalised response from any LLM provider.

    Either final_text is set (loop terminates) or tool_calls is non-empty
    (loop continues). Never both.
    """
    final_text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class BaseProvider(ABC):
    """Common interface for all LLM providers."""

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> ModelResponse:
        """Send messages + tool definitions to the LLM, return normalised response."""
        ...
