"""list_directory tool — lists entries inside a workspace directory."""
from __future__ import annotations

from pathlib import Path

from app.tools.base import ToolResult
from app.tools.read_file import _validate_path


def make_list_directory(workspace_root: Path):
    def execute(args: dict) -> ToolResult:
        raw = args.get("path", ".")

        resolved, err = _validate_path(workspace_root, raw)
        if err:
            return ToolResult(error=err)

        if not resolved.exists():
            return ToolResult(error=f"Directory does not exist: {resolved.relative_to(workspace_root)}")

        if not resolved.is_dir():
            return ToolResult(error=f"Not a directory: {resolved.relative_to(workspace_root)}")

        try:
            entries = sorted(resolved.iterdir(), key=lambda p: (p.is_file(), p.name))
            lines = []
            for entry in entries:
                marker = "📁" if entry.is_dir() else "📄"
                lines.append(f"{marker} {entry.name}")
        except Exception as e:
            return ToolResult(error=f"Could not list directory: {e}")

        if not lines:
            return ToolResult(output="(empty directory)")

        return ToolResult(output="\n".join(lines))

    return execute
