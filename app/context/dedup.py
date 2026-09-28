"""Context and Error Deduplication.

Avoids repeatedly injecting identical:
- file contents
- tool results
- system instructions
- compiler/runtime errors
"""
from __future__ import annotations

import hashlib
from typing import Optional


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]


class ContextDeduplicator:
    """Tracks seen content hashes to prevent prompt pollution and token waste."""

    def __init__(self) -> None:
        self._seen_hashes: set[str] = set()
        self._error_counts: dict[str, int] = {}

    def is_duplicate(self, text: str, namespace: str = "general") -> bool:
        """Check whether this exact text was already recorded in this namespace."""
        key = f"{namespace}:{_hash_text(text)}"
        if key in self._seen_hashes:
            return True
        self._seen_hashes.add(key)
        return False

    def process_error(self, error_text: str) -> str:
        """Normalize and deduplicate repeated error messages.

        Returns either original error (on first occurrence) or an abbreviated note.
        """
        norm_key = _hash_text(error_text)
        count = self._error_counts.get(norm_key, 0) + 1
        self._error_counts[norm_key] = count

        if count > 1:
            first_line = error_text.splitlines()[0] if error_text else "Unknown error"
            return f"[Repeated error ({count}x) — identical to previous: {first_line[:120]}]"

        return error_text

    def clear(self) -> None:
        self._seen_hashes.clear()
        self._error_counts.clear()
