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


@dataclass
class Settings:
    provider: str = ""              # "claude" | "openai" | "gemini" | "ollama" | "openrouter"
    model: str = ""
    workspace_root: Path = Path(".")        # validated absolute path to workspace
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    user_memory_path: Path = Path("USER.md")      # ~/.setucode/USER.md
    permission_storage_path: Path = Path("permissions.json")  # ~/.setucode/permissions.json
    anthropic_base_url: str = ""   # custom endpoint for Anthropic / proxies
    openai_base_url: str = ""      # custom endpoint (Ollama, LMStudio, OpenRouter, vLLM)
    gemini_base_url: str = ""      # custom endpoint for Gemini

    def update_model(self, new_model: str, persist: bool = True, env_path: Path = Path(".env")) -> None:
        """Update active model in settings and optionally persist to .env."""
        self.model = new_model
        if persist:
            persist_selected_model(new_model, env_path)


def persist_selected_model(model_id: str, env_path: Path = Path(".env")) -> bool:
    """Update LLM_MODEL in .env if the file exists."""
    if not env_path.exists():
        return False
    try:
        content = env_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("LLM_MODEL="):
                new_lines.append(f"LLM_MODEL={model_id}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"LLM_MODEL={model_id}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Failed to persist model to .env: %s", e)
        return False




def load_settings() -> Settings:
    """Load settings from environment variables (populated by .env)."""
    workspace = Path(os.environ.get("WORKSPACE_ROOT", "./workspace")).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    home = Path.home() / ".setucode"
    home.mkdir(exist_ok=True)

    openai_endpoint = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or os.environ.get("LLM_BASE_URL", "")
    ).strip()

    anthropic_endpoint = os.environ.get("ANTHROPIC_BASE_URL", "").strip()

    gemini_endpoint = (
        os.environ.get("GEMINI_BASE_URL")
        or os.environ.get("GEMINI_API_ENDPOINT", "")
    ).strip()

    return Settings(
        provider=os.environ.get("LLM_PROVIDER", "").lower().strip(),
        model=os.environ.get("LLM_MODEL", "").strip(),
        workspace_root=workspace,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY", "").strip(),
        user_memory_path=home / "USER.md",
        permission_storage_path=home / "permissions.json",
        anthropic_base_url=anthropic_endpoint,
        openai_base_url=openai_endpoint,
        gemini_base_url=gemini_endpoint,
    )
