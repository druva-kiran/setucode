"""run_command tool — execute a shell command inside the workspace.

Provides the agent with the ability to run commands such as lint, test,
build, or any shell command the user approves. Output is captured and
returned to the LLM. Commands are executed with a timeout to prevent hangs.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.tools.base import ToolResult


def make_run_command(workspace_root: Path):
    def execute(args: dict) -> ToolResult:
        command = args.get("command", "").strip()
        if not command:
            return ToolResult(error="No command provided.")

        timeout = min(args.get("timeout", 30), 120)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(workspace_root),
                timeout=timeout,
            )

            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout[-4000:])
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr[-2000:]}")
            output_parts.append(f"\nExit code: {result.returncode}")

            combined = "\n".join(output_parts)
            if result.returncode != 0:
                return ToolResult(output=combined)
            return ToolResult(output=combined)

        except subprocess.TimeoutExpired:
            return ToolResult(error=f"Command timed out after {timeout}s.")
        except Exception as e:
            return ToolResult(error=f"Command failed: {e}")

    return execute
