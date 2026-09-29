"""Tool Registry — central catalogue of available tools.

Tools register themselves here. The Agent Loop reads schema_list() and passes
it to the LLM. The loop also calls execute() via registry.get(name).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from app.tools.base import PermissionCategory, ToolResult


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema — passed verbatim to LLM API
    execute: Callable[[dict], ToolResult]
    permission_category: PermissionCategory


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def schema_list(self) -> list[dict]:
        """Returns tool definitions in the format expected by all provider APIs."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self._tools.values()
        ]


def build_default_registry(workspace_root: Path) -> ToolRegistry:
    """Create and populate the standard set of MVP tools."""
    from app.tools.read_file import make_read_file
    from app.tools.write_file import make_write_file
    from app.tools.edit_file import make_edit_file
    from app.tools.move_file import make_move_file
    from app.tools.list_directory import make_list_directory
    from app.tools.search_files import make_search_files
    from app.tools.run_command import make_run_command

    registry = ToolRegistry()

    registry.register(Tool(
        name="read_file",
        description="Read the contents of a file inside the workspace, optionally between line ranges.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from workspace root."},
                "start_line": {"type": "integer", "description": "Optional 1-indexed starting line number."},
                "end_line": {"type": "integer", "description": "Optional 1-indexed ending line number."},
            },
            "required": ["path"],
        },
        execute=make_read_file(workspace_root),
        permission_category="readonly",
    ))

    registry.register(Tool(
        name="search_files",
        description="Search for text or regex across workspace files to locate relevant code.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search string or regex pattern."},
                "path": {"type": "string", "description": "Optional subpath to search within. Defaults to '.' (root)."},
                "is_regex": {"type": "boolean", "description": "Whether to treat query as regex."},
            },
            "required": ["query"],
        },
        execute=make_search_files(workspace_root),
        permission_category="readonly",
    ))

    registry.register(Tool(
        name="list_directory",
        description="List the files and subdirectories inside a workspace directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from workspace root. Use '.' for root."},
            },
            "required": ["path"],
        },
        execute=make_list_directory(workspace_root),
        permission_category="readonly",
    ))

    registry.register(Tool(
        name="write_file",
        description="Create a new file or completely overwrite an existing file.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from workspace root."},
                "content": {"type": "string", "description": "Full file content to write."},
            },
            "required": ["path", "content"],
        },
        execute=make_write_file(workspace_root),
        permission_category="modifying",
    ))

    registry.register(Tool(
        name="edit_file",
        description=(
            "Apply a unified diff patch to an existing file. "
            "The patch must be in standard unified diff format "
            "(--- a/file\\n+++ b/file\\n@@ ... @@ ...)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path from workspace root."},
                "patch": {"type": "string", "description": "Unified diff patch string."},
            },
            "required": ["path", "patch"],
        },
        execute=make_edit_file(workspace_root),
        permission_category="modifying",
    ))

    registry.register(Tool(
        name="move_file",
        description="Move or rename a file within the workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Relative source path."},
                "destination": {"type": "string", "description": "Relative destination path."},
            },
            "required": ["source", "destination"],
        },
        execute=make_move_file(workspace_root),
        permission_category="modifying",
    ))

    registry.register(Tool(
        name="run_command",
        description=(
            "Run a shell command inside the workspace directory. Use this to run tests, "
            "build the project, execute scripts, or perform any command-line operation. "
            "Output is captured and returned."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute inside the workspace root.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Optional timeout in seconds (default: 30, max: 120).",
                },
            },
            "required": ["command"],
        },
        execute=make_run_command(workspace_root),
        permission_category="high_risk",
    ))

    return registry
