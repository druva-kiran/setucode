"""write_file tool — creates or fully overwrites a file inside the workspace."""
from __future__ import annotations

from pathlib import Path

from app.tools.base import ToolResult
from app.tools.read_file import _validate_path


def make_write_file(workspace_root: Path):
    def execute(args: dict) -> ToolResult:
        raw = args.get("path", "")
        content = args.get("content", "")

        resolved, err = _validate_path(workspace_root, raw)
        if err:
            return ToolResult(error=err)

        if resolved.suffix == ".py":
            import ast
            try:
                ast.parse(content, filename=str(resolved))
            except SyntaxError as e:
                return ToolResult(error=f"SyntaxError in python file: {e}\nFile not written. Please fix the syntax error.")

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
        except Exception as e:
            return ToolResult(error=f"Could not write file: {e}")

        return ToolResult(output=f"Wrote {len(content)} bytes to {resolved.relative_to(workspace_root)}")

    return execute
