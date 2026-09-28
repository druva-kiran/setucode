"""Anthropic Claude provider implementation."""
from __future__ import annotations

import anthropic

from app.providers.base import BaseProvider, ModelInfo, ModelResponse, ToolCall


class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        kwargs: dict = dict(api_key=api_key or "no-key-required")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)
        self._model = model
        self.model = model
        self.base_url = base_url
        self.provider_name = "claude"

    def get_fallback_models(self) -> list[ModelInfo]:
        """Sensible fallbacks for Anthropic Claude."""
        fallback_ids = [
            self.model or "claude-3-5-sonnet-20241022",
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ]
        seen = set()
        result = []
        for mid in fallback_ids:
            if mid and mid not in seen:
                seen.add(mid)
                result.append(
                    ModelInfo(
                        id=mid,
                        name=mid,
                        provider="claude",
                        is_default=(mid == self.model),
                    )
                )
        return result

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from the Anthropic API."""
        if not hasattr(self._client, "models"):
            return self.get_fallback_models()

        resp = self._client.models.list()
        data = getattr(resp, "data", resp)
        models: list[ModelInfo] = []

        for m in data:
            mid = getattr(m, "id", str(m))
            display_name = getattr(m, "display_name", mid) or mid
            models.append(
                ModelInfo(
                    id=mid,
                    name=display_name,
                    provider="claude",
                    is_default=(mid == self.model),
                )
            )

        return models or self.get_fallback_models()


    def generate(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        # Anthropic requires the system message to be a top-level param, not in messages
        system_msg = ""
        filtered = []
        for m in messages:
            if m.get("role") == "system":
                system_msg = m.get("content", "")
            else:
                filtered.append(m)

        # Convert generic tool schema to Anthropic format
        anthropic_tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in tools
        ] if tools else []

        kwargs: dict = dict(
            model=self._model,
            max_tokens=8096,
            messages=filtered,
        )
        if system_msg:
            kwargs["system"] = system_msg
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        response = self._client.messages.create(**kwargs)

        tool_calls = [
            ToolCall(id=b.id, name=b.name, args=b.input)
            for b in response.content
            if b.type == "tool_use"
        ]
        final_text = next(
            (b.text for b in response.content if b.type == "text"), None
        )

        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", 0),
                "output_tokens": getattr(response.usage, "output_tokens", 0),
                "cached_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
                "cache_creation_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
            }

        # If there are tool calls, suppress any text fragment
        return ModelResponse(
            final_text=final_text if not tool_calls else None,
            tool_calls=tool_calls,
            usage=usage,
        )
