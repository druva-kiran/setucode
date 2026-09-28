"""Security Sandbox, Path Boundaries, and Secret Sanitization."""
from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

log = logging.getLogger(__name__)

# Patterns that indicate secrets or sensitive files
DEFAULT_BLOCKED_PATTERNS = [
    "*.env",
    "*.env.*",
    "*.key",
    "*.pem",
    "id_rsa*",
    "id_ed25519*",
    "*.pfx",
    "*.p12",
    "*credential*",
    ".git/config",
    ".git/credentials",
]

# Regex patterns for detecting API keys and tokens in tool output
SECRET_REGEXES = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"AIza[0-9A-Za-z_\-]{30,45}"), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,255}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(password|secret|api_key|token)\s*=\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE), r"\1 = [REDACTED_SECRET]"),
]


@dataclass
class SandboxPolicy:
    """Configurable sandbox policy for tool execution."""

    allowed_roots: list[Path] = field(default_factory=list)
    blocked_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_PATTERNS))
    blocked_tools: set[str] = field(default_factory=set)
    require_confirmation_categories: set[str] = field(default_factory=lambda: {"high_risk"})
    allow_secret_reads: bool = False
    max_file_size_bytes: int = 10 * 1024 * 1024  # 10 MB

    def is_path_allowed(self, path: Path, workspace_root: Path) -> tuple[bool, Optional[str]]:
        """Verify that path is within allowed roots and does not touch blocked patterns."""
        try:
            resolved = path.resolve()
        except Exception as exc:
            return False, f"Invalid path resolution: {exc}"

        roots = self.allowed_roots or [workspace_root.resolve()]
        in_allowed_root = any(
            str(resolved).startswith(str(r.resolve())) for r in roots
        )
        if not in_allowed_root:
            return False, f"Path '{resolved}' is outside allowed workspace boundaries."

        # Check blocked patterns (like .env or credentials)
        if not self.allow_secret_reads:
            for pattern in self.blocked_patterns:
                if fnmatch.fnmatch(resolved.name, pattern) or fnmatch.fnmatch(str(resolved), pattern):
                    return False, f"Access to '{resolved.name}' is blocked by security policy (matches pattern: {pattern})."

        return True, None


class SecuritySandbox:
    """Enforces execution boundaries, policy checks, and secret redaction."""

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()

    def validate_tool_request(
        self, tool_name: str, args: dict, workspace_root: Path
    ) -> tuple[bool, Optional[str]]:
        """Perform pre-execution sandbox validation."""
        # 1. Check if tool is explicitly blocked
        if tool_name in self.policy.blocked_tools:
            return False, f"Tool '{tool_name}' is blocked by security policy."

        # 2. Extract path arguments
        raw_path = args.get("path") or args.get("source")
        if raw_path:
            target_path = workspace_root / raw_path
            allowed, reason = self.policy.is_path_allowed(target_path, workspace_root)
            if not allowed:
                return False, reason

        # Destination path for move operations
        dest_path = args.get("destination")
        if dest_path:
            target_dest = workspace_root / dest_path
            allowed, reason = self.policy.is_path_allowed(target_dest, workspace_root)
            if not allowed:
                return False, reason

        return True, None

    @classmethod
    def redact_secrets(cls, text: str) -> str:
        """Sanitize output by removing secrets, private keys, and API tokens."""
        if not text:
            return text
        sanitized = text
        for pattern, replacement in SECRET_REGEXES:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized
