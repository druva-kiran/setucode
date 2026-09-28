"""/setup wizard — interactive configuration flow.

Writes provider, model, API key, and optional custom endpoint to .env in the project root.
Called when settings.provider is empty (first run or after setucode --setup).
"""
from __future__ import annotations

from pathlib import Path

_PROVIDERS = {
    "1": ("claude", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-20241022", "ANTHROPIC_BASE_URL"),
    "2": ("openai", "OPENAI_API_KEY", "gpt-4o", "OPENAI_BASE_URL"),
    "3": ("gemini", "GEMINI_API_KEY", "gemini-1.5-pro", "GEMINI_BASE_URL"),
    "4": ("openai", "OPENAI_API_KEY", "llama3.2", "OPENAI_BASE_URL"),  # Local / Ollama / OpenRouter
}


def run_setup_cli() -> None:
    """Run the setup flow in the terminal."""
    print("\n" + "─" * 50)
    print("  SetuCode Setup Wizard")
    print("─" * 50)
    print("\nSelect your LLM provider:\n")
    print("  1. Claude (Anthropic)")
    print("  2. OpenAI (Official)")
    print("  3. Gemini (Google)")
    print("  4. Custom Endpoint (Ollama, OpenRouter, LMStudio, vLLM)\n")

    choice = ""
    while choice not in _PROVIDERS:
        choice = input("Enter 1, 2, 3, or 4: ").strip()

    provider_id, key_name, default_model, endpoint_env_var = _PROVIDERS[choice]

    endpoint = ""
    if choice == "4":
        endpoint = input("Custom Base URL [http://localhost:11434/v1]: ").strip() or "http://localhost:11434/v1"
        api_key = input("API Key (optional for local models): ").strip()
    else:
        api_key = input(f"{key_name}: ").strip()
        custom_ep = input("Custom Base URL (press Enter to skip): ").strip()
        if custom_ep:
            endpoint = custom_ep

    workspace = input("Workspace path [./workspace]: ").strip() or "./workspace"

    # Auto-discover models or use sensible default without asking user to manually type model names
    model = default_model
    try:
        from app.config.settings import Settings
        from app.providers import build_provider
        from dashboard.keyboard import is_interactive

        temp_settings = Settings(
            provider=provider_id,
            model=default_model,
            anthropic_api_key=api_key if provider_id == "claude" else "",
            openai_api_key=api_key if provider_id == "openai" else "",
            gemini_api_key=api_key if provider_id == "gemini" else "",
            anthropic_base_url=endpoint if provider_id == "claude" else "",
            openai_base_url=endpoint if provider_id == "openai" else "",
            gemini_base_url=endpoint if provider_id == "gemini" else "",
        )
        prov = build_provider(temp_settings)
        print(f"\nChecking connection to {provider_id}...")
        models, err = prov.get_available_models()
        if models and len(models) > 1 and is_interactive():
            from dashboard.selector import SelectItem, run_interactive_selector
            from rich.console import Console
            console = Console()
            items = [
                SelectItem(
                    id=m.id,
                    title=m.name or m.id,
                    badge="[default]" if m.id == default_model else (f"[{m.provider}]" if m.provider else ""),
                    is_current=(m.id == default_model),
                )
                for m in models
            ]
            sel = run_interactive_selector(
                console,
                title="Select Initial Model",
                items=items,
                current_id=default_model,
                footer_hint="↑ ↓  Navigate  │  Enter  Select  │  Esc  Use Default",
            )
            if sel:
                model = sel.id
        elif models:
            model = models[0].id
    except Exception:
        model = default_model

    _write_env(provider_id, model, key_name, api_key, workspace, endpoint_env_var, endpoint)

    print("\n✓ Configuration saved to .env")
    print(f"  Provider : {provider_id}")
    print(f"  Model    : {model}")
    if endpoint:
        print(f"  Endpoint : {endpoint}")
    print(f"  Workspace: {workspace}")
    print("\nRun setucode to begin coding. Use /model anytime to change models.\n")


def _write_env(
    provider: str,
    model: str,
    key_name: str,
    api_key: str,
    workspace: str,
    endpoint_env_var: str = "",
    endpoint: str = "",
) -> None:
    env_path = Path(".env")
    lines = [
        f"LLM_PROVIDER={provider}\n",
        f"LLM_MODEL={model}\n",
        f"{key_name}={api_key}\n",
        f"WORKSPACE_ROOT={workspace}\n",
    ]
    if endpoint and endpoint_env_var:
        lines.append(f"{endpoint_env_var}={endpoint}\n")

    env_path.write_text("".join(lines), encoding="utf-8")

    # Ensure .gitignore exists and includes .env
    gitignore = Path(".gitignore")
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".env" not in content:
        with gitignore.open("a", encoding="utf-8") as f:
            f.write("\n.env\n")
