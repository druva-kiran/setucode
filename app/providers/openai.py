"""OpenAI provider implementation."""
from __future__ import annotations

from openai import OpenAI

from app.providers.base import BaseProvider, ModelResponse, ToolCall


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        kwargs: dict = dict(api_key=api_key or "no-key-required")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self.base_url = base_url

    def generate(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        # Convert generic schema to OpenAI function format
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ] if tools else []

        kwargs: dict = dict(model=self._model, messages=messages)
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            import json
            for tc in msg.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        args=json.loads(tc.function.arguments),
                    )
                )

        usage = None
        if hasattr(response, "usage") and response.usage:
            prompt_details = getattr(response.usage, "prompt_tokens_details", None)
            cached_tokens = getattr(prompt_details, "cached_tokens", 0) if prompt_details else 0
            usage = {
                "input_tokens": getattr(response.usage, "prompt_tokens", 0),
                "output_tokens": getattr(response.usage, "completion_tokens", 0),
                "cached_tokens": cached_tokens,
            }

        return ModelResponse(
            final_text=msg.content if not tool_calls else None,
            tool_calls=tool_calls,
            usage=usage,
        )
