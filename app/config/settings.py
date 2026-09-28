"""App configuration — loads .env and exposes a typed Settings object.

Read-only after startup. All other modules import from here; nothing
imports into this module from the rest of the app.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    provider: str               # "claude" | "openai" | "gemini"
    model: str
    workspace_root: Path        # validated absolute path to workspace
    anthropic_api_key: str
    openai_api_key: str
    gemini_api_key: str
    user_memory_path: Path      # ~/.setucode/USER.md
    permission_storage_path: Path  # ~/.setucode/permissions.json


def load_settings() -> Settings:
    """Load settings from environment variables (populated by .env)."""
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "./workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    home = Path.home() / ".setucode"
    home.mkdir(exist_ok=True)

    return Settings(
        provider=os.environ.get("LLM_PROVIDER", "").lower().strip(),
        model=os.environ.get("LLM_MODEL", "").strip(),
        workspace_root=workspace,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        user_memory_path=home / "USER.md",
        permission_storage_path=home / "permissions.json",
    )
