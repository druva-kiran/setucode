"""Subagent Manager — task delegation, context isolation, and execution governance."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from app.agent.state import AgentState, AgentStatus
from app.events.bus import EventBus
from app.permissions.manager import PermissionManager
from app.providers.base import BaseProvider
from app.subagents.model import SubagentLimits, SubagentResult, SubagentRole
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)

ROLE_PROMPTS = {
    SubagentRole.RESEARCHER.value: (
        "You are the SetuCode Researcher Subagent. Your goal is to explore the codebase, "
        "read files, search patterns, and report clear findings. You have read-only access. "
        "Do not attempt to write or edit files."
    ),
    SubagentRole.CODE_ANALYZER.value: (
        "You are the SetuCode Code Analyzer Subagent. Inspect code architecture, dependencies, "
        "and data structures. You have read-only access. Report structural findings clearly."
    ),
    SubagentRole.CODER.value: (
        "You are the SetuCode Coder Subagent. Your goal is to implement a specific, isolated change. "
        "Always read files before editing and produce precise unified diffs."
    ),
    SubagentRole.TESTER.value: (
        "You are the SetuCode Tester Subagent. Inspect test files, identify missing test cases, "
        "and verify test coverage."
    ),
    SubagentRole.DEBUGGER.value: (
        "You are the SetuCode Debugger Subagent. Analyze error traces, inspect failure points, "
        "and determine root causes."
    ),
    SubagentRole.REVIEWER.value: (
        "You are the SetuCode Reviewer Subagent. Audit code changes, check for bugs, regression risks, "
        "and security flaws."
    ),
}


class SubagentManager:
    """Oversees subagent creation, strict isolation, and lifecycle limits."""

    def __init__(
        self,
        workspace: Path,
        parent_permissions: PermissionManager,
        parent_registry: ToolRegistry,
        limits: SubagentLimits | None = None,
        current_depth: int = 0,
    ) -> None:
        self.workspace = workspace
        self.permissions = parent_permissions
        self.parent_registry = parent_registry
        self.limits = limits or SubagentLimits()
        self.current_depth = current_depth
        self._spawned_count = 0

    def can_delegate(self) -> tuple[bool, Optional[str]]:
        """Verify whether delegation is permitted under current limits."""
        if self.current_depth >= self.limits.max_depth:
            return False, f"Maximum subagent depth ({self.limits.max_depth}) reached. Cannot spawn recursive subagents."

        if self._spawned_count >= self.limits.max_subagents:
            return False, f"Maximum subagent count ({self.limits.max_subagents}) reached."

        return True, None

    def _filter_tools_for_role(self, role: str) -> ToolRegistry:
        """Provide only the minimal tool subset required for this role."""
        sub_registry = ToolRegistry()
        all_tools = self.parent_registry.all_tools()

        # Read-only roles must not have modifying tools
        read_only_roles = {
            SubagentRole.RESEARCHER.value,
            SubagentRole.CODE_ANALYZER.value,
            SubagentRole.REVIEWER.value,
        }

        for tool in all_tools:
            if role in read_only_roles:
                if tool.permission_category == "readonly":
                    sub_registry.register(tool)
            else:
                sub_registry.register(tool)

        return sub_registry

    def run_subagent(
        self,
        role: str,
        task: str,
        isolated_context: str = "",
        model: BaseProvider | None = None,
        bus: EventBus | None = None,
    ) -> SubagentResult:
        """Run an isolated subagent session and return structured result."""
        allowed, reason = self.can_delegate()
        if not allowed:
            return SubagentResult(
                role=role,
                task=task,
                success=False,
                summary=f"Delegation rejected: {reason}",
                error=reason,
            )

        self._spawned_count += 1
        sub_bus = bus or EventBus()
        sub_tools = self._filter_tools_for_role(role)

        # Role-specific system instructions
        role_instruction = ROLE_PROMPTS.get(
            role, f"You are the SetuCode {role} subagent. Complete the specified task accurately."
        )

        sub_state = AgentState(
            session_id=f"sub-{role}-{self._spawned_count}",
            workspace=self.workspace,
            model=model,  # type: ignore
            available_tools=sub_tools.schema_list(),
        )
        sub_state.messages.append({"role": "system", "content": role_instruction})

        full_prompt = task
        if isolated_context:
            full_prompt = f"Context:\n{isolated_context}\n\nTask:\n{task}"

        from app.agent.loop import run
        try:
            summary = run(
                state=sub_state,
                user_message=full_prompt,
                bus=sub_bus,
                registry=sub_tools,
                permissions=self.permissions,  # Shared sandbox & permission gates!
            )
            # Find modified files by subagent
            modified = []
            for m in sub_state.messages:
                for tc in m.get("tool_calls", []):
                    if tc.get("name") in ("write_file", "edit_file", "move_file"):
                        p = tc.get("args", {}).get("path") or tc.get("args", {}).get("destination")
                        if p and p not in modified:
                            modified.append(p)

            return SubagentResult(
                role=role,
                task=task,
                success=sub_state.status == AgentStatus.FINISHED,
                summary=summary,
                modified_files=modified,
            )
        except Exception as exc:
            log.error("Subagent error [%s]: %s", role, exc)
            return SubagentResult(
                role=role,
                task=task,
                success=False,
                summary=f"Subagent execution failed: {exc}",
                error=str(exc),
            )
