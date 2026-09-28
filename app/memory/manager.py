"""MemoryManager — loads and writes USER.md and AGENTS.md.

USER.md lives at ~/.setucode/USER.md (shared across all projects).
AGENTS.md lives at the workspace root (per-project).

At session start: load both files (silently skip if missing).
At session end:   call the LLM to extract new preferences and append to USER.md.
"""
from __future__ import annotations

import logging
from pathlib import Path

from filelock import FileLock

log = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, user_memory_path: Path) -> None:
        self._user_path = user_memory_path
        self._lock = FileLock(str(user_memory_path) + ".lock")

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load_user_memory(self) -> str:
        """Return USER.md contents, or '' if the file does not exist."""
        if self._user_path.exists():
            try:
                return self._user_path.read_text(encoding="utf-8")
            except Exception as e:
                log.warning("Could not read USER.md: %s", e)
        return ""

    def load_project_memory(self, workspace_root: Path) -> str:
        """Return AGENTS.md contents from workspace root, or '' if missing."""
        agents_md = workspace_root / "AGENTS.md"
        if agents_md.exists():
            try:
                return agents_md.read_text(encoding="utf-8")
            except Exception as e:
                log.warning("Could not read AGENTS.md: %s", e)
        else:
            log.info("AGENTS.md not found in workspace (normal for new projects)")
        return ""

    # ------------------------------------------------------------------
    # Write (session end)
    # ------------------------------------------------------------------

    def write_session_memories(
        self,
        messages: list[dict],
        provider,  # BaseProvider — avoids circular import
    ) -> None:
        """Ask the LLM to extract new preferences and append them to USER.md.

        This call is completely separate from the agent conversation.
        It runs after Stop is emitted and never affects the session loop.
        """
        existing = self.load_user_memory()
        transcript = _format_transcript(messages)

        if not transcript.strip():
            return

        prompt = (
            "Review the following conversation transcript. "
            "Identify any NEW reusable coding preferences the user expressed "
            "(e.g., style, language, patterns they want remembered). "
            "Return ONLY bullet points, one per line, starting with '- '. "
            "Do NOT repeat preferences already listed in the existing USER.md. "
            "If there are no new preferences, return exactly: NONE\n\n"
            f"EXISTING USER.md:\n{existing or '(empty)'}\n\n"
            f"TRANSCRIPT:\n{transcript}"
        )

        try:
            response = provider.generate(
                messages=[{"role": "user", "content": prompt}],
                tools=[],
            )
            new_prefs = (response.final_text or "").strip()
        except Exception as e:
            log.error("Memory extraction LLM call failed: %s", e)
            return

        if not new_prefs or new_prefs.upper() == "NONE":
            log.info("No new preferences to save.")
            return

        log.info("Writing new preferences to USER.md")
        with self._lock:
            try:
                with self._user_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n{new_prefs}\n")
            except Exception as e:
                log.error("Could not write USER.md: %s", e)


def _format_transcript(messages: list[dict]) -> str:
    """Format conversation messages into a readable transcript for the LLM."""
    lines = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            continue  # skip system prompt from transcript
        if isinstance(content, str) and content:
            lines.append(f"{role.upper()}: {content[:600]}")
    return "\n".join(lines)
