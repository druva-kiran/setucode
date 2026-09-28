"""PermissionStorage — persists "Allow always" rules as (tool, directory) pairs.

Storage key format: "<tool_name>:<absolute_directory>"
Value: "always"

Falls back to an empty rule set (ask for everything) if the file is missing
or corrupt — the agent loop continues normally.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from filelock import FileLock

log = logging.getLogger(__name__)


class PermissionStorage:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = FileLock(str(path) + ".lock")
        self._rules: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as e:
            log.error("Permission storage corrupted, falling back to empty: %s", e)
            return {}

    def is_always_allowed(self, tool_name: str, resolved_path: Path) -> bool:
        """Return True if an 'allow always' rule covers this tool + path."""
        path_str = str(resolved_path)
        for key, decision in self._rules.items():
            if decision != "always":
                continue
            parts = key.split(":", 1)
            if len(parts) != 2:
                continue
            stored_tool, stored_dir = parts
            if stored_tool == tool_name and path_str.startswith(stored_dir):
                return True
        return False

    def store_always(self, tool_name: str, directory: str) -> None:
        """Persist an 'allow always' rule for (tool, directory)."""
        key = f"{tool_name}:{directory}"
        with self._lock:
            self._rules[key] = "always"
            try:
                self._path.write_text(
                    json.dumps(self._rules, indent=2), encoding="utf-8"
                )
            except Exception as e:
                log.error("Could not write permission storage: %s", e)
