"""search_files tool — search for regex or substring in workspace files."""
from __future__ import annotations

import re
from pathlib import Path

from app.tools.base import ToolResult


def make_search_files(workspace_root: Path):
    """Factory — returns an execute(args) callable bound to workspace_root."""

    def execute(args: dict) -> ToolResult:
        query = args.get("query", "")
        if not query:
            return ToolResult(error="Search query cannot be empty.")

        path_filter = args.get("path", ".")
        try:
            target_dir = (workspace_root / path_filter).resolve()
        except Exception as e:
            return ToolResult(error=f"Invalid path: {e}")

        if not str(target_dir).startswith(str(workspace_root)):
            return ToolResult(error=f"Path is outside workspace: {target_dir}")

        if not target_dir.exists():
            return ToolResult(error=f"Path does not exist: {target_dir.relative_to(workspace_root)}")

        is_regex = bool(args.get("is_regex", False))
        max_matches = int(args.get("max_matches", 50))

        pattern = None
        if is_regex:
            try:
                pattern = re.compile(query, re.IGNORECASE)
            except re.error as err:
                return ToolResult(error=f"Invalid regex: {err}")

        matches: list[str] = []
        files = [target_dir] if target_dir.is_file() else target_dir.rglob("*")

        for f in files:
            if len(matches) >= max_matches:
                break
            if not f.is_file():
                continue
            # Skip hidden, cache, and virtualenv files
            parts = f.relative_to(workspace_root).parts
            if any(p.startswith(".") or p in ("__pycache__", "venv", ".venv", "node_modules") for p in parts):
                continue

            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            lines = text.splitlines()
            for line_no, line in enumerate(lines, start=1):
                found = bool(pattern.search(line)) if pattern else (query.lower() in line.lower())
                if found:
                    rel = f.relative_to(workspace_root)
                    matches.append(f"{rel}:{line_no}: {line.strip()[:160]}")
                    if len(matches) >= max_matches:
                        break

        if not matches:
            return ToolResult(output=f"No matches found for {query!r}.")

        header = f"Found {len(matches)} match(es):\n"
        return ToolResult(output=header + "\n".join(matches))

    return execute
