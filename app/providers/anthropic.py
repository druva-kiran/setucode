"""Anthropic Claude provider implementation."""
from __future__ import annotations

import json
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
        system_msg = ""
        filtered = []

        for m in messages:
            role = m.get("role")

            if role == "system":
                system_msg = m.get("content", "")

            elif role == "tool":
                tool_use_id = m.get("tool_call_id") or m.get("tool_use_id")
                tool_result_content = {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": str(m.get("content", ""))
                }

                if filtered and filtered[-1]["role"] == "user":
                    prev_content = filtered[-1]["content"]
                    if isinstance(prev_content, str):
                        filtered[-1]["content"] = [{"type": "text", "text": prev_content}]
                    elif not isinstance(prev_content, list):
                        filtered[-1]["content"] = [{"type": "text", "text": str(prev_content)}]
                    filtered[-1]["content"].append(tool_result_content)
                else:
                    filtered.append({
                        "role": "user",
                        "content": [tool_result_content]
                    })

            elif role == "assistant" and m.get("tool_calls"):
                content_blocks = []
                if m.get("content"):
                    content_blocks.append({"type": "text", "text": str(m["content"])})

                for tc in m["tool_calls"]:
                    tc_id = getattr(tc, "id", None) if not isinstance(tc, dict) else tc.get("id")

                    tc_name = getattr(tc, "name", None) if not isinstance(tc, dict) else tc.get("name")
                    if not tc_name:
                        func = getattr(tc, "function", None) if not isinstance(tc, dict) else tc.get("function", {})
                        tc_name = getattr(func, "name", None) if not isinstance(func, dict) else func.get("name")

                    tc_args = getattr(tc, "args", getattr(tc, "arguments", None)) if not isinstance(tc, dict) else tc.get("args", tc.get("arguments"))
                    if tc_args is None:
                        func = getattr(tc, "function", None) if not isinstance(tc, dict) else tc.get("function", {})
                        tc_args = getattr(func, "arguments", "{}") if not isinstance(func, dict) else func.get("arguments", "{}")

                    if isinstance(tc_args, str):
                        try:
                            tc_args = json.loads(tc_args)
                        except Exception:
                            tc_args = {}

                    if tc_args is None:
                        tc_args = {}

                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc_id,
                        "name": tc_name,
                        "input": tc_args
                    })

                filtered.append({
                    "role": "assistant",
                    "content": content_blocks
                })

            elif role == "user":
                if filtered and filtered[-1]["role"] == "user":
                    prev_content = filtered[-1]["content"]
                    curr_content = m.get("content", "")
                    if isinstance(prev_content, str):
                        filtered[-1]["content"] = [{"type": "text", "text": prev_content}]
                    elif not isinstance(prev_content, list):
                        filtered[-1]["content"] = [{"type": "text", "text": str(prev_content)}]
                    filtered[-1]["content"].append({"type": "text", "text": str(curr_content)})
                else:
                    filtered.append({
                        "role": "user",
                        "content": m.get("content", "")
                    })

            else:
                filtered.append({
                    "role": role,
                    "content": m.get("content", "")
                })

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
