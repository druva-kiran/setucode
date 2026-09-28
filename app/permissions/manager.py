"""PermissionManager — the gate between a tool call and tool execution.

The Agent Loop calls check() for every tool call. This module decides
whether to auto-allow, ask the user, or block. It NEVER calls the LLM.
The LLM has no programmatic path into this component.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from app.permissions.policy import PermissionDecision
from app.permissions.sandbox import SecuritySandbox
from app.permissions.storage import PermissionStorage
from app.tools.registry import Tool

log = logging.getLogger(__name__)

# Callable type: (tool_name, resolved_path_str) -> PermissionDecision
RequestFn = Callable[[str, str], PermissionDecision]


class PermissionManager:
    def __init__(
        self,
        storage: PermissionStorage,
        request_fn: RequestFn,
        sandbox: SecuritySandbox | None = None,
    ) -> None:
        """
        Args:
            storage:    Persisted allow-always rules.
            request_fn: Supplied by the TUI. Called when user input is needed.
                        Blocks until the user clicks Allow once / Always / Deny.
            sandbox:    Security sandbox and boundary policy enforcement.
        """
        self._storage = storage
        self._request = request_fn
        self._sandbox = sandbox or SecuritySandbox()
        self.last_denial_reason: Optional[str] = None

    @property
    def sandbox(self) -> SecuritySandbox:
        return self._sandbox

    def check(
        self,
        tool: Tool,
        args: dict,
        workspace_root: Path,
    ) -> PermissionDecision:
        """Determine whether the tool call may proceed.

        Decision order:
          0. Sandbox / policy validation (paths, secrets, blocked tools) → DENY if failed
          1. readonly → AUTO_ALLOWED
          2. stored 'always' rule covering the path (unless high_risk) → AUTO_ALLOWED
          3. ask user → ALLOW_ONCE | ALLOW_ALWAYS | DENY
        """
        self.last_denial_reason = None

        # Step 0: Sandbox Policy Verification
        valid, reason = self._sandbox.validate_tool_request(tool.name, args, workspace_root)
        if not valid:
            log.warning("Sandbox policy check failed for %s: %s", tool.name, reason)
            self.last_denial_reason = reason
            return PermissionDecision.DENY

        # Step 1: readonly tools are auto-allowed (only if sandbox passed)
        if tool.permission_category == "readonly":
            log.info("Permission auto-allowed (readonly): %s", tool.name)
            return PermissionDecision.AUTO_ALLOWED

        # Resolve the target path for rule lookup
        raw_path = args.get("path") or args.get("source") or ""
        resolved = (workspace_root / raw_path).resolve()
        directory = str(resolved.parent)

        # Step 2: check stored always-rules (high_risk always requires explicit confirmation)
        if tool.permission_category != "high_risk" and self._storage.is_always_allowed(tool.name, resolved):
            log.info("Permission auto-allowed (stored rule): %s on %s", tool.name, resolved)
            return PermissionDecision.AUTO_ALLOWED

        # Step 3: ask the user
        log.info("Permission requested: %s on %s", tool.name, resolved)
        decision = self._request(tool.name, str(resolved))
        log.info("Permission response: %s → %s", tool.name, decision.value)

        if decision == PermissionDecision.ALLOW_ALWAYS:
            self._storage.store_always(tool.name, directory)
        elif decision == PermissionDecision.DENY:
            self.last_denial_reason = "Permission denied by user."

        return decision
