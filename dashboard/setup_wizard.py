"""/setup wizard — interactive configuration flow.

Writes provider, model, and API key to .env in the project root.
Called when settings.provider is empty (first run or after /setup).
"""
from __future__ import annotations

from pathlib import Path


_PROVIDERS = {
    "1": ("claude", "ANTHROPIC_API_KEY", "claude-opus-4-5"),
    "2": ("openai", "OPENAI_API_KEY", "gpt-4o"),
    "3": ("gemini", "GEMINI_API_KEY", "gemini-1.5-pro"),
}


def run_setup_cli() -> None:
    """Run the /setup flow in the terminal (blocking, no TUI needed)."""
    print("\n" + "=" * 50)
    print("  SetuCode — Setup Wizard")
    print("=" * 50)
    print("\nSelect your LLM provider:\n")
    print("  1. Claude (Anthropic)")
    print("  2. OpenAI")
    print("  3. Gemini (Google)\n")

    choice = ""
    while choice not in _PROVIDERS:
        choice = input("Enter 1, 2, or 3: ").strip()

    provider_id, key_name, default_model = _PROVIDERS[choice]

    model = input(f"Model name [{default_model}]: ").strip() or default_model
    api_key = input(f"{key_name}: ").strip()
    workspace = input("Workspace path [./workspace]: ").strip() or "./workspace"

    _write_env(provider_id, model, key_name, api_key, workspace)

    print("\n✓ Configuration saved to .env")
    print(f"  Provider : {provider_id}")
    print(f"  Model    : {model}")
    print(f"  Workspace: {workspace}")
    print("\nStart SetuCode again to begin coding.\n")


def _write_env(
    provider: str,
    model: str,
    key_name: str,
    api_key: str,
    workspace: str,
) -> None:
    env_path = Path(".env")
    lines = [
        f"LLM_PROVIDER={provider}\n",
        f"LLM_MODEL={model}\n",
        f"{key_name}={api_key}\n",
        f"WORKSPACE_ROOT={workspace}\n",
    ]
    env_path.write_text("".join(lines), encoding="utf-8")

    # Ensure .gitignore exists and includes .env
    gitignore = Path(".gitignore")
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".env" not in content:
        with gitignore.open("a", encoding="utf-8") as f:
            f.write("\n.env\n")
