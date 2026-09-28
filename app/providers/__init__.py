"""Provider factory — builds the correct BaseProvider from Settings."""
from __future__ import annotations

from app.config.settings import Settings
from app.providers.base import BaseProvider


def build_provider(settings: Settings) -> BaseProvider:
    """Instantiate and return the configured LLM provider."""
    match settings.provider:
        case "claude":
            from app.providers.anthropic import AnthropicProvider
            return AnthropicProvider(settings.anthropic_api_key, settings.model)
        case "openai":
            from app.providers.openai import OpenAIProvider
            return OpenAIProvider(settings.openai_api_key, settings.model)
        case "gemini":
            from app.providers.gemini import GeminiProvider
            return GeminiProvider(settings.gemini_api_key, settings.model)
        case _:
            raise ValueError(
                f"Unknown provider '{settings.provider}'. "
                "Run /setup to configure a provider."
            )
