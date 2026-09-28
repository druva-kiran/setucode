"""Tool definition for delegating subtasks to specialized subagents."""
from __future__ import annotations

from app.events.bus import EventBus
from app.providers.base import BaseProvider
from app.subagents.manager import SubagentManager
from app.tools.base import ToolResult
from app.tools.registry import Tool


def make_delegate_task(
    manager: SubagentManager,
    model: BaseProvider,
    bus: EventBus,
) -> Tool:
    """Create the delegate_task tool."""

    def execute(args: dict) -> ToolResult:
        role = args.get("role", "")
        task = args.get("task", "")
        context = args.get("context", "")

        if not role or not task:
            return ToolResult(error="Must provide both 'role' and 'task' for subagent delegation.")

        result = manager.run_subagent(
            role=role,
            task=task,
            isolated_context=context,
            model=model,
            bus=bus,
        )

        if not result.success and result.error:
            return ToolResult(error=result.error)

        return ToolResult(output=result.to_markdown())

    return Tool(
        name="delegate_task",
        description=(
            "Delegate an isolated subtask to a specialized subagent "
            "(researcher, code_analyzer, coder, tester, debugger, reviewer)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "enum": [
                        "researcher",
                        "code_analyzer",
                        "coder",
                        "tester",
                        "debugger",
                        "reviewer",
                    ],
                    "description": "Specialized subagent role.",
                },
                "task": {
                    "type": "string",
                    "description": "The specific task instructions for the subagent.",
                },
                "context": {
                    "type": "string",
                    "description": "Isolated context, file excerpts, or guidance necessary for this task.",
                },
            },
            "required": ["role", "task"],
        },
        execute=execute,
        permission_category="readonly",
    )
