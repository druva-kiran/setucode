"""read_file tool — returns file contents, enforces workspace boundary."""
from __future__ import annotations

from pathlib import Path

from app.tools.base import ToolResult


def _validate_path(workspace_root: Path, raw: str) -> tuple[Path | None, str | None]:
    """Resolve and validate that raw is inside workspace_root.

    Returns (resolved_path, None) on success or (None, error_message) on failure.
    """
    try:
        resolved = (workspace_root / raw).resolve()
    except Exception as e:
        return None, f"Invalid path: {e}"

    if not str(resolved).startswith(str(workspace_root)):
        return None, f"Path is outside workspace: {resolved}"

    return resolved, None


def make_read_file(workspace_root: Path):
    """Factory — returns an execute(args) callable bound to workspace_root."""

    def execute(args: dict) -> ToolResult:
        raw = args.get("path", "")
        resolved, err = _validate_path(workspace_root, raw)
        if err:
            return ToolResult(error=err)
        if not resolved.exists():
            return ToolResult(error=f"File does not exist: {resolved.relative_to(workspace_root)}")
        if not resolved.is_file():
            return ToolResult(error=f"Not a file: {resolved.relative_to(workspace_root)}")
        try:
            content = resolved.read_text(encoding="utf-8")
        except Exception as e:
            return ToolResult(error=f"Could not read file: {e}")

        start_line = args.get("start_line")
        end_line = args.get("end_line")

        if start_line is not None or end_line is not None:
            lines = content.splitlines()
            total_lines = len(lines)
            s_idx = max(1, int(start_line)) if start_line else 1
            e_idx = min(total_lines, int(end_line)) if end_line else total_lines

            if s_idx > total_lines:
                return ToolResult(
                    output=f"[File has {total_lines} lines; requested start_line {s_idx} is out of range]"
                )

            selected = lines[s_idx - 1 : e_idx]
            numbered = [
                f"{s_idx + i}: {line}" for i, line in enumerate(selected)
            ]
            header = f"[Lines {s_idx}-{e_idx} of {total_lines} from {resolved.relative_to(workspace_root)}]\n"
            return ToolResult(output=header + "\n".join(numbered))

        return ToolResult(output=content)

    return execute
