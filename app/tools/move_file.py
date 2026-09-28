"""move_file tool — moves or renames a file within the workspace."""
from __future__ import annotations

import shutil
from pathlib import Path

from app.tools.base import ToolResult
from app.tools.read_file import _validate_path


def make_move_file(workspace_root: Path):
    def execute(args: dict) -> ToolResult:
        raw_src = args.get("source", "")
        raw_dst = args.get("destination", "")

        src, err = _validate_path(workspace_root, raw_src)
        if err:
            return ToolResult(error=f"Source: {err}")

        dst, err = _validate_path(workspace_root, raw_dst)
        if err:
            return ToolResult(error=f"Destination: {err}")

        if not src.exists():
            return ToolResult(error=f"Source does not exist: {src.relative_to(workspace_root)}")

        if dst.exists():
            return ToolResult(error=f"Destination already exists: {dst.relative_to(workspace_root)}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except Exception as e:
            return ToolResult(error=f"Could not move file: {e}")

        return ToolResult(
            output=f"Moved {src.relative_to(workspace_root)} → {dst.relative_to(workspace_root)}"
        )

    return execute
