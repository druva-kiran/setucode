"""Unit tests for Sandbox boundaries, policy checks, and secret redaction."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.permissions.manager import PermissionManager
from app.permissions.policy import PermissionDecision
from app.permissions.sandbox import SandboxPolicy, SecuritySandbox
from app.tools.base import ToolResult
from app.tools.registry import Tool, build_default_registry


def test_sandbox_blocks_paths_outside_workspace(tmp_path: Path):
    """Sandbox prevents tools from escaping workspace boundaries."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside data")

    sandbox = SecuritySandbox()
    allowed, reason = sandbox.validate_tool_request("read_file", {"path": str(outside)}, ws)
    assert allowed is False
    assert "outside allowed workspace boundaries" in reason


def test_sandbox_blocks_secret_files(tmp_path: Path):
    """Sandbox blocks access to .env and credentials by default."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    env_file = ws / ".env"
    env_file.write_text("SECRET_KEY=12345")

    sandbox = SecuritySandbox()
    allowed, reason = sandbox.validate_tool_request("read_file", {"path": ".env"}, ws)
    assert allowed is False
    assert "blocked by security policy" in reason


def test_sandbox_blocks_configured_tool(tmp_path: Path):
    """Configuring blocked tools prevents their execution."""
    policy = SandboxPolicy(blocked_tools={"shell_exec", "eval"})
    sandbox = SecuritySandbox(policy)

    allowed, reason = sandbox.validate_tool_request("shell_exec", {}, tmp_path)
    assert allowed is False
    assert "blocked by security policy" in reason


def test_permission_manager_denies_on_sandbox_violation(tmp_path: Path):
    """PermissionManager returns DENY and captures denial reason on sandbox violation."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    storage = MagicMock()
    request_fn = MagicMock()

    mgr = PermissionManager(storage, request_fn)
    tool = Tool(
        name="read_file",
        description="read",
        input_schema={},
        execute=lambda args: ToolResult(output="ok"),
        permission_category="readonly",
    )

    decision = mgr.check(tool, {"path": ".env"}, ws)
    assert decision == PermissionDecision.DENY
    assert "blocked by security policy" in mgr.last_denial_reason
    request_fn.assert_not_called()  # Never even asks user because policy blocks it outright!


def test_secret_redaction_in_tool_output():
    """SecuritySandbox redacts API keys, bearer tokens, and private keys from output."""
    raw = (
        "Here is the config: sk-abcdef12345678901234567890\n"
        "And Gemini key: AIzaSyD1234567890123456789012345678901\n"
        "GitHub token: ghp_123456789012345678901234567890123456\n"
        "Private: -----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQ...\n-----END RSA PRIVATE KEY-----"
    )

    redacted = SecuritySandbox.redact_secrets(raw)

    assert "sk-abcdef" not in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "AIzaSyD" not in redacted
    assert "[REDACTED_GEMINI_KEY]" in redacted
    assert "ghp_" not in redacted
    assert "[REDACTED_GITHUB_TOKEN]" in redacted
    assert "-----BEGIN RSA PRIVATE KEY-----" not in redacted
    assert "[REDACTED_PRIVATE_KEY]" in redacted
