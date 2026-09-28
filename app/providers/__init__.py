"""Provider factory — builds the correct BaseProvider from Settings."""
from __future__ import annotations

from app.config.settings import Settings
from app.providers.base import BaseProvider


def build_provider(settings: Settings) -> BaseProvider:
    """Instantiate and return the configured LLM provider, supporting custom endpoints."""
    match settings.provider:
        case "claude" | "anthropic":
            from app.providers.anthropic import AnthropicProvider
            return AnthropicProvider(
                settings.anthropic_api_key,
                settings.model,
                base_url=settings.anthropic_base_url or None,
            )
        case "openai" | "ollama" | "openrouter" | "vllm" | "lmstudio" | "local":
            from app.providers.openai import OpenAIProvider
            return OpenAIProvider(
                settings.openai_api_key,
                settings.model,
                base_url=settings.openai_base_url or None,
            )
        case "gemini" | "google":
            from app.providers.gemini import GeminiProvider
            return GeminiProvider(
                settings.gemini_api_key,
                settings.model,
                base_url=settings.gemini_base_url or None,
            )
        case _:
            raise ValueError(
                f"Unknown provider '{settings.provider}'. "
                "Supported: claude, openai (including ollama/openrouter/vllm/local), gemini. "
                "Run setucode --setup to configure a provider."
            )
