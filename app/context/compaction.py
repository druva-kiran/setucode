"""Context Compaction — compress conversational history while preserving critical task state."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

from app.plan.model import Plan

log = logging.getLogger(__name__)


@dataclass
class CompactWorkingState:
    """State preserved across context compaction cycles."""

    task: str = ""
    current_state: str = ""
    important_decisions: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    plan_text: str = ""
    errors: list[str] = field(default_factory=list)
    test_status: str = "unknown"
    relevant_context: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render the standardized compact working state string."""
        sections = [
            "## COMPACT WORKING STATE (Preserved after Context Compaction)",
            f"**TASK:**\n{self.task or 'N/A'}",
            f"**CURRENT STATE:**\n{self.current_state or 'In progress'}",
        ]

        if self.important_decisions:
            decisions = "\n".join(f"- {d}" for d in self.important_decisions)
            sections.append(f"**IMPORTANT DECISIONS:**\n{decisions}")

        if self.files_modified:
            files = "\n".join(f"- {f}" for f in sorted(set(self.files_modified)))
            sections.append(f"**FILES MODIFIED:**\n{files}")

        if self.plan_text:
            sections.append(f"**PLAN:**\n{self.plan_text}")

        if self.errors:
            errs = "\n".join(f"- {e}" for e in self.errors[-3:])  # keep latest errors
            sections.append(f"**ERRORS:**\n{errs}")

        sections.append(f"**TEST STATUS:**\n{self.test_status}")

        if self.relevant_context:
            ctx = "\n".join(f"- {c}" for c in self.relevant_context)
            sections.append(f"**RELEVANT CONTEXT:**\n{ctx}")

        return "\n\n".join(sections)


class ContextCompactor:
    """Compresses message lists to maintain context efficiency without losing state."""

    @classmethod
    def extract_state(
        cls, messages: list[dict], plan: Plan | None = None
    ) -> CompactWorkingState:
        """Extract critical task, files, errors, and decisions from message history."""
        state = CompactWorkingState()

        # Extract initial task
        for m in messages:
            if m.get("role") == "user" and not state.task:
                state.task = m.get("content", "")
                break

        # Extract modified files and errors from tool calls and results
        for m in messages:
            content = str(m.get("content", ""))
            # Tool calls
            for tc in m.get("tool_calls", []):
                name = tc.get("name")
                args = tc.get("args", {})
                if name in ("write_file", "edit_file"):
                    path = args.get("path")
                    if path and path not in state.files_modified:
                        state.files_modified.append(path)
                elif name == "move_file":
                    dest = args.get("destination")
                    if dest and dest not in state.files_modified:
                        state.files_modified.append(dest)

            # Tool errors
            if m.get("role") == "tool" and "ERROR:" in content:
                first_line = content.splitlines()[0]
                if first_line not in state.errors:
                    state.errors.append(first_line)

            # Test indicators
            if "passed in" in content or "PASSED" in content:
                state.test_status = "Tests passing"
            elif "FAILED" in content or "FAILURES" in content:
                state.test_status = "Tests failing"

        if plan:
            state.plan_text = plan.render()
            current = plan.current_task()
            if current:
                state.current_state = f"Working on task {current.id}: {current.description}"

        return state

    @classmethod
    def compact(
        cls,
        messages: list[dict],
        plan: Plan | None = None,
        preserve_recent_turns: int = 3,
    ) -> list[dict]:
        """Compact conversation history by substituting intermediate turns with state."""
        if len(messages) <= (preserve_recent_turns * 2 + 2):
            return messages

        # Separate system message
        system_msg = None
        other_messages: list[dict] = []
        for m in messages:
            if m.get("role") == "system" and system_msg is None:
                system_msg = m
            else:
                other_messages.append(m)

        # Extract compact working state
        working_state = cls.extract_state(messages, plan=plan)

        # Retain the most recent N messages
        recent_messages = other_messages[-preserve_recent_turns:]

        # Build compacted sequence:
        compacted: list[dict] = []
        if system_msg:
            compacted.append(system_msg)

        # Add the compact state block as a system checkpoint
        compacted.append({
            "role": "system",
            "content": working_state.render(),
            "_compacted": True,
        })

        # Append recent turns to preserve conversation flow
        compacted.extend(recent_messages)
        log.info(
            "Context compacted: %d messages -> %d messages",
            len(messages),
            len(compacted),
        )
        return compacted
