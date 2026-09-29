"""OpenAI provider implementation."""
from __future__ import annotations

from openai import OpenAI

from app.providers.base import BaseProvider, ModelInfo, ModelResponse, ToolCall


class OpenAIProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        kwargs: dict = dict(api_key=api_key or "no-key-required")
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model
        self.model = model
        self.base_url = base_url
        if base_url and "openrouter" in base_url.lower():
            self.provider_name = "openrouter"
        elif base_url and ("11434" in base_url or "ollama" in base_url.lower()):
            self.provider_name = "ollama"
        elif base_url:
            self.provider_name = "custom/local"
        else:
            self.provider_name = "openai"

    def get_fallback_models(self) -> list[ModelInfo]:
        """Sensible fallbacks when discovery cannot connect."""
        if self.provider_name == "ollama":
            fallback_ids = [self.model or "llama3.2", "llama3.2", "qwen2.5-coder", "deepseek-r1", "mistral"]
        elif self.provider_name == "openrouter":
            fallback_ids = [
                self.model or "anthropic/claude-3.5-sonnet",
                "anthropic/claude-3.5-sonnet",
                "openai/gpt-4o",
                "deepseek/deepseek-r1",
                "google/gemini-2.0-flash-exp:free",
            ]
        elif self.base_url:
            fallback_ids = [self.model or "local-model", "llama3.2", "mistral"]
        else:
            fallback_ids = [
                self.model or "gpt-4o",
                "gpt-4o",
                "gpt-4o-mini",
                "o3-mini",
                "o1",
                "gpt-4-turbo",
            ]

        # Deduplicate while preserving order
        seen = set()
        result = []
        for mid in fallback_ids:
            if mid and mid not in seen:
                seen.add(mid)
                result.append(
                    ModelInfo(
                        id=mid,
                        name=mid,
                        provider=self.provider_name,
                        is_default=(mid == self.model),
                    )
                )
        return result

    def list_models(self) -> list[ModelInfo]:
        """Query available models from OpenAI or OpenAI-compatible endpoint."""
        resp = self._client.models.list()
        data = getattr(resp, "data", resp)
        models: list[ModelInfo] = []

        is_official_openai = not self.base_url or "api.openai.com" in self.base_url

        for m in data:
            mid = getattr(m, "id", str(m))
            # If official OpenAI, filter out whisper/tts/dall-e/embedding/babbage/davinci
            if is_official_openai:
                low = mid.lower()
                non_chat = any(x in low for x in ["tts", "whisper", "dall-e", "embedding", "davinci", "babbage", "moderation", "realtime", "audio"])
                if non_chat and mid != self.model:
                    continue

            models.append(
                ModelInfo(
                    id=mid,
                    name=mid,
                    provider=self.provider_name,
                    is_default=(mid == self.model),
                )
            )

        if not models:
            return self.get_fallback_models()

        # Sort so that chat models starting with gpt, o1, o3, or the current model come first
        def _sort_key(m: ModelInfo):
            if m.id == self.model:
                return 0
            if m.id.startswith(("gpt-4o", "o3", "o1", "gpt-4")):
                return 1
            if m.id.startswith("gpt-"):
                return 2
            return 3

        models.sort(key=_sort_key)
        return models


    def generate(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        import json

        # Normalise messages for OpenAI Chat Completions API
        formatted_messages = []
        for m in messages:
            role = m.get("role")
            content = m.get("content")

            if role == "tool":
                formatted_messages.append({
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id") or m.get("tool_use_id", ""),
                    "content": str(content) if content is not None else "",
                })
            elif role == "assistant" and m.get("tool_calls"):
                tcs = []
                for tc in m["tool_calls"]:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                    tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                    tc_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                    if not isinstance(tc_args, str):
                        tc_args = json.dumps(tc_args or {})

                    tcs.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tc_name,
                            "arguments": tc_args,
                        },
                    })
                formatted_messages.append({
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tcs,
                })
            else:
                formatted_messages.append({
                    "role": role,
                    "content": content if content is not None else "",
                })

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

        kwargs: dict = dict(model=self._model, messages=formatted_messages)
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
