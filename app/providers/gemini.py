"""Google Gemini provider — uses the current google-genai SDK."""
from __future__ import annotations

from google import genai
from google.genai import types

from app.providers.base import BaseProvider, ModelInfo, ModelResponse, ToolCall


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        kwargs: dict = dict(api_key=api_key or "no-key-required")
        if base_url:
            kwargs["http_options"] = types.HttpOptions(base_url=base_url)
        self._client = genai.Client(**kwargs)
        self._model = model
        self.model = model
        self.base_url = base_url
        self.provider_name = "gemini"

    def get_fallback_models(self) -> list[ModelInfo]:
        """Sensible fallbacks for Google Gemini."""
        fallback_ids = [
            self.model or "gemini-2.5-flash",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
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
                        provider="gemini",
                        is_default=(mid == self.model),
                    )
                )
        return result

    def list_models(self) -> list[ModelInfo]:
        """Fetch available models from the Gemini API."""
        if not hasattr(self._client, "models"):
            return self.get_fallback_models()

        resp = self._client.models.list()
        models: list[ModelInfo] = []

        for m in resp:
            m_name = getattr(m, "name", "")
            clean_id = m_name[7:] if m_name.startswith("models/") else m_name
            if not clean_id or not ("gemini" in clean_id.lower() or clean_id == self.model):
                continue

            display_name = getattr(m, "display_name", "") or clean_id
            label = f"{display_name} ({clean_id})" if display_name and display_name != clean_id else clean_id
            models.append(
                ModelInfo(
                    id=clean_id,
                    name=label,
                    description=getattr(m, "description", "") or "",
                    provider="gemini",
                    is_default=(clean_id == self.model),
                )
            )

        return models or self.get_fallback_models()


    def generate(self, messages: list[dict], tools: list[dict]) -> ModelResponse:
        # Separate system prompt from conversation history
        system_instruction = ""
        history: list[types.Content] = []
        last_user_text = ""

        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")

            if role == "system":
                system_instruction = content
            elif role == "user":
                last_user_text = content if isinstance(content, str) else ""
                history.append(
                    types.Content(role="user", parts=[types.Part(text=last_user_text)])
                )
            elif role == "assistant":
                parts = []
                if content:
                    parts.append(types.Part(text=str(content)))
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")
                        tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                        tc_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                        if isinstance(tc_args, str):
                            try:
                                import json
                                tc_args = json.loads(tc_args)
                            except Exception:
                                tc_args = {}
                        parts.append(
                            types.Part(
                                function_call=types.FunctionCall(
                                    id=tc_id or tc_name,
                                    name=tc_name,
                                    args=tc_args or {},
                                )
                            )
                        )
                if not parts:
                    parts.append(types.Part(text=""))
                history.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                # Tool result — append as user turn with function response
                tool_id = m.get("tool_use_id") or m.get("tool_call_id") or ""
                name = m.get("name", tool_id)
                result_text = content if isinstance(content, str) else str(content)
                fn_part = types.Part(
                    function_response=types.FunctionResponse(
                        id=tool_id or name,
                        name=name,
                        response={"result": result_text},
                    )
                )
                if history and history[-1].role == "user":
                    history[-1].parts.append(fn_part)
                else:
                    history.append(
                        types.Content(
                            role="user",
                            parts=[fn_part],
                        )
                    )

        # Build function declarations for the tool list
        genai_tools = None
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=t["input_schema"],
                )
                for t in tools
            ]
            genai_tools = [types.Tool(function_declarations=declarations)]

        config = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            tools=genai_tools,
        )

        # Use full history as the chat contents
        response = self._client.models.generate_content(
            model=self._model,
            contents=history,
            config=config,
        )

        tool_calls: list[ToolCall] = []
        final_text: str | None = None

        for part in response.candidates[0].content.parts:
            if fn := getattr(part, "function_call", None):
                tool_calls.append(
                    ToolCall(
                        id=getattr(fn, "id", fn.name),
                        name=fn.name,
                        args=dict(fn.args),
                    )
                )
            elif text := getattr(part, "text", None):
                final_text = text

        return ModelResponse(
            final_text=final_text if not tool_calls else None,
            tool_calls=tool_calls,
        )
