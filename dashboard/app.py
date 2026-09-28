"""SetuCode CLI — Minimal, clean terminal interface.

Focuses on clarity, low visual noise, and native markdown rendering:
- Clean ❯ prompt
- Native Rich Markdown rendering (true syntax highlighting, no line bars)
- Clean, minimal tool activity lines without carriage return artifacts
- Minimal permission confirmations
- Quick commands: /plan, /skills, /clear, /help, /exit
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from rich.theme import Theme

from app.agent.loop import run as agent_run
from app.agent.state import AgentState
from app.config.settings import Settings, load_settings
from app.events.bus import EventBus
from app.events.events import AgentEvent
from app.memory.manager import MemoryManager
from app.permissions.manager import PermissionManager
from app.permissions.policy import PermissionDecision
from app.permissions.storage import PermissionStorage
from app.providers import build_provider
from app.skills.manager import list_available_skills
from app.tools.registry import build_default_registry

theme = Theme({
    "prompt": "bold cyan",
    "meta": "dim white",
    "tool": "cyan",
    "ok": "green",
    "err": "red",
    "warn": "yellow",
    "path": "dim cyan",
    "plan": "bold magenta",
})

console = Console(theme=theme, highlight=False)
log = logging.getLogger(__name__)


def _format_tool_action(tool: str, args: dict) -> tuple[str, str]:
    """Human-friendly verb and target for tool actions."""
    path = args.get("path") or args.get("source") or args.get("destination") or args.get("query") or ""

    match tool:
        case "read_file":
            return "Read", path
        case "write_file":
            return "Write", path
        case "edit_file":
            return "Edit", path
        case "move_file":
            dest = args.get("destination", "")
            return "Move", f"{path} → {dest}" if dest else path
        case "list_directory":
            return "Explore", path or "."
        case "search_files":
            return "Search", f'"{path}"'
        case "get_plan" | "update_plan_task" | "add_plan_task":
            return "Plan", tool.replace("_", " ")
        case "delegate_task":
            role = args.get("role", "subagent")
            return f"Delegate ({role})", args.get("task", "")[:40]
        case _:
            return tool, path


# ── Event handler ────────────────────────────────────────────────────────────

def on_event(event: AgentEvent) -> None:
    if event.name == "Thinking":
        pass  # Kept quiet for clean, minimal output

    elif event.name == "PreToolUse":
        tool = event.data.get("tool", "?")
        args = event.data.get("args", {})
        action, target = _format_tool_action(tool, args)
        target_str = f" [white]{target}[/white]" if target else ""
        console.print(f"    [dim]●[/dim] [dim cyan]{action}[/dim cyan]{target_str}")

    elif event.name == "PostToolUse":
        tool = event.data.get("tool", "?")
        is_err = event.data.get("error", False)
        if is_err:
            console.print(f"    [err]✗ {tool} failed or denied[/err]")

    elif event.name == "Stop":
        reason = event.data.get("reason", "done")
        if "error" in reason.lower():
            console.print(f"    [err]✗ {reason}[/err]")


# ── Permission prompt ────────────────────────────────────────────────────────

def request_permission(tool_name: str, path: str) -> PermissionDecision:
    console.print()
    display_path = f" on [path]{path}[/path]" if path else ""
    console.print(f"  [bold yellow]?[/bold yellow] Allow [bold]{tool_name}[/bold]{display_path}?")
    console.print("    [bold]a[/bold] allow once  [dim]│[/dim]  [bold]s[/bold] allow always  [dim]│[/dim]  [bold]d[/bold] deny")

    while True:
        try:
            raw = input("    ❯ ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return PermissionDecision.DENY

        if raw in ("a", "1", "allow", "y", "yes"):
            return PermissionDecision.ALLOW_ONCE
        if raw in ("s", "2", "always"):
            return PermissionDecision.ALLOW_ALWAYS
        if raw in ("d", "3", "deny", "n", "no", ""):
            return PermissionDecision.DENY

        console.print("    [meta]Please enter 'a' (once), 's' (always), or 'd' (deny)[/meta]")


# ── Response renderer ────────────────────────────────────────────────────────

def _print_response(text: str) -> None:
    """Render agent response as native, clean Markdown with syntax highlighting, indentation, and breathing room."""
    if not text or not text.strip():
        return

    from rich.padding import Padding

    # Maximum comfortable line width for reading (80-100 chars)
    render_width = min(console.width - 8, 100) if console.width > 105 else max(console.width - 4, 50)

    console.print()
    console.print(Padding(Markdown(text.strip()), (0, 0, 0, 4)), width=render_width)
    console.print()


# ── Main REPL session ────────────────────────────────────────────────────────

def run_session(settings: Settings) -> None:
    memory = MemoryManager(settings.user_memory_path)

    try:
        provider = build_provider(settings)
    except ValueError as e:
        console.print(f"\n[err]✗ Configuration error:[/err] {e}")
        console.print("[dim]Run 'setucode --setup' to configure a valid provider.[/dim]\n")
        return

    registry = build_default_registry(settings.workspace_root)
    storage = PermissionStorage(settings.permission_storage_path)
    perms = PermissionManager(storage, request_permission)

    state = AgentState(
        session_id=str(uuid.uuid4()),
        workspace=settings.workspace_root,
        model=provider,
        available_tools=registry.schema_list(),
        user_memory=memory.load_user_memory(),
        project_memory=memory.load_project_memory(settings.workspace_root),
    )

    bus = EventBus()
    bus.subscribe(on_event)

    # Clean, minimal single-line status banner
    endpoint_info = ""
    if settings.openai_base_url:
        endpoint_info = f" [dim]({settings.openai_base_url})[/dim]"
    elif settings.anthropic_base_url:
        endpoint_info = f" [dim]({settings.anthropic_base_url})[/dim]"
    elif settings.gemini_base_url:
        endpoint_info = f" [dim]({settings.gemini_base_url})[/dim]"

    from dashboard.commands import CommandContext, build_default_command_router

    cmd_router = build_default_command_router()
    cmd_ctx = CommandContext(
        console=console,
        state=state,
        settings=settings,
        provider=provider,
        registry=registry,
        permissions=perms,
        bus=bus,
    )

    console.print()
    console.print(
        f" [bold cyan]SetuCode[/bold cyan] [dim]│[/dim] "
        f"[white]{settings.provider}[/white]:[dim]{settings.model}[/dim]{endpoint_info} [dim]│[/dim] "
        f"[dim]{settings.workspace_root}[/dim]"
    )
    console.print(" [dim]Type your message. Commands: /model, /skills, /status, /plan, /help, /exit[/dim]\n")

    try:
        while True:
            try:
                console.print("  [prompt]❯[/prompt] ", end="")
                user_input = input().strip()
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not user_input:
                continue

            console.print()

            # First-class slash command handling
            if cmd_router.is_command(user_input):
                should_continue = cmd_router.dispatch(user_input, cmd_ctx)
                if not should_continue:
                    break
                continue

            # Run agent loop with clean status indicator
            with console.status("    [dim]Thinking...[/dim]", spinner="dots"):
                result = agent_run(state, user_input, bus, registry, perms)

            _print_response(result)

    finally:
        try:
            memory.write_session_memories(state.messages, provider)
        except Exception as e:
            log.error("memory write error: %s", e)


# ── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        filename="setucode.log",
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if "--setup" in sys.argv:
        from dashboard.setup_wizard import run_setup_cli
        run_setup_cli()
        return

    settings = load_settings()

    if not settings.provider:
        console.print("\n [warn]No provider configured[/warn] — launching setup wizard.\n")
        from dashboard.setup_wizard import run_setup_cli
        run_setup_cli()
        settings = load_settings()

    if not settings.provider:
        console.print(" [err]Setup incomplete.[/err] Run [heading]setucode --setup[/heading]\n")
        return

    run_session(settings)


if __name__ == "__main__":
    main()
