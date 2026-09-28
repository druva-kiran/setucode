"""Anthropic Claude provider implementation."""
from __future__ import annotations

import anthropic

from app.providers.base import BaseProvider, ModelResponse, ToolCall


class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        kwargs: dict = dict(api_key=api_key or "no-key-required")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)
        self._model = model
        self.base_url = base_url

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
