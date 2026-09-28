"""edit_file tool — applies a unified diff patch to a workspace file.

The model must produce a standard unified diff:
    --- a/<path>
    +++ b/<path>
    @@ -L,N +L,N @@
     context
    -removed
    +added
     context

Uses whatthepatch to parse and apply. Returns a structured error if the
patch cannot be applied cleanly — never raises an unhandled exception.
"""
from __future__ import annotations

from pathlib import Path

import whatthepatch

from app.tools.base import ToolResult
from app.tools.read_file import _validate_path


def make_edit_file(workspace_root: Path):
    def execute(args: dict) -> ToolResult:
        raw = args.get("path", "")
        patch_text = args.get("patch", "")

        resolved, err = _validate_path(workspace_root, raw)
        if err:
            return ToolResult(error=err)

        if not resolved.is_file():
            return ToolResult(error=f"File does not exist: {resolved.relative_to(workspace_root)}")

        if not patch_text.strip():
            return ToolResult(error="Patch text is empty.")

        try:
            # whatthepatch expects plain strings (no trailing newlines)
            raw = resolved.read_text(encoding="utf-8")
            original_lines = raw.splitlines()
        except Exception as e:
            return ToolResult(error=f"Could not read file: {e}")

        # Normalise patch line endings for whatthepatch (must be \n on all platforms)
        patch_text = patch_text.replace("\r\n", "\n").replace("\r", "\n")

        try:
            diffs = list(whatthepatch.parse_patch(patch_text))
        except Exception as e:
            return ToolResult(error=f"Could not parse patch: {e}")

        if not diffs:
            return ToolResult(error="Patch text is empty or could not be parsed.")

        try:
            result_lines = whatthepatch.apply_diff(diffs[0], original_lines)
        except Exception as e:
            return ToolResult(error=f"Patch did not apply: {e}")

        if result_lines is None:
            return ToolResult(error="Patch did not apply cleanly (context mismatch). Re-read the file and try again.")

        try:
            # apply_diff returns lines without newlines; rejoin them
            patched = "\n".join(result_lines)
            if patched and not patched.endswith("\n"):
                patched += "\n"
            resolved.write_text(patched, encoding="utf-8")
        except Exception as e:
            return ToolResult(error=f"Could not write patched file: {e}")

        return ToolResult(output=f"Applied patch to {resolved.relative_to(workspace_root)}")

    return execute
