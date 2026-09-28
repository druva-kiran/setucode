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


@dataclass
class ModelInfo:
    """Normalized model information."""
    id: str
    name: str = ""
    description: str = ""
    provider: str = ""
    is_default: bool = False
    context_window: int | None = None


class BaseProvider(ABC):
    """Common interface for all LLM providers."""

    model: str = ""
    provider_name: str = ""
    base_url: str | None = None

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> ModelResponse:
        """Send messages + tool definitions to the LLM, return normalised response."""
        ...

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from the provider API.

        Subclasses should query their provider's model API and return normalized ModelInfo.
        """
        return self.get_fallback_models()

    def get_fallback_models(self) -> list[ModelInfo]:
        """Return fallback models when live discovery is unsupported or fails."""
        current = getattr(self, "model", "")
        if current:
            return [ModelInfo(id=current, name=current, provider=getattr(self, "provider_name", ""))]
        return []

    def get_available_models(self) -> tuple[list[ModelInfo], str | None]:
        """Fetch models safely with fallback.

        Returns (models_list, error_or_warning_message_if_any).
        Never crashes.
        """
        try:
            models = self.list_models()
            if models:
                # Ensure the current active model is present
                current = getattr(self, "model", "")
                if current and not any(m.id == current for m in models):
                    models.insert(
                        0,
                        ModelInfo(
                            id=current,
                            name=f"{current} (active)",
                            provider=getattr(self, "provider_name", ""),
                            is_default=True,
                        ),
                    )
                return models, None
        except Exception as e:
            fallback = self.get_fallback_models()
            err_msg = str(e)
            return fallback, f"Model discovery error: {err_msg}"

        return self.get_fallback_models(), None

    def set_model(self, model_id: str) -> None:
        """Update active model on this provider instance."""
        self._model = model_id
        self.model = model_id

