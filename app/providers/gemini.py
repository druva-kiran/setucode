"""Google Gemini provider — uses the current google-genai SDK."""
from __future__ import annotations

from google import genai
from google.genai import types

from app.providers.base import BaseProvider, ModelResponse, ToolCall


class GeminiProvider(BaseProvider):
    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

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
                text = content if isinstance(content, str) else ""
                history.append(
                    types.Content(role="model", parts=[types.Part(text=text)])
                )
            elif role == "tool":
                # Tool result — append as user turn with function response
                tool_id = m.get("tool_use_id") or m.get("tool_call_id") or ""
                name = m.get("name", tool_id)
                result_text = content if isinstance(content, str) else str(content)
                history.append(
                    types.Content(
                        role="user",
                        parts=[types.Part(
                            function_response=types.FunctionResponse(
                                id=tool_id,
                                name=name,
                                response={"result": result_text},
                            )
                        )],
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
