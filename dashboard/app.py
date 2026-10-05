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
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
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
from app.skills.manager import get_default_skill_registry
from app.tools.registry import build_default_registry
from dashboard.prompt import prompt_interactive

theme = Theme({
    "prompt": "bold cyan",
    "prompt_sub": "dim cyan",
    "meta": "dim white",
    "tool": "bold cyan",
    "tool_target": "white",
    "ok": "bold green",
    "err": "bold red",
    "warn": "bold yellow",
    "path": "dim cyan underline",
    "plan": "bold magenta",
    "accent": "bold magenta",
    "border": "cyan",
    "time": "dim yellow",
})

console = Console(theme=theme, highlight=False)
log = logging.getLogger(__name__)

# State tracking for tool durations
_active_tool_start: Optional[float] = None
_active_tool_name: Optional[str] = None


def _format_tool_action(tool: str, args: dict) -> tuple[str, str]:
    """Human-friendly verb and target for tool actions."""
    path = args.get("path") or args.get("source") or args.get("destination") or args.get("query") or ""

    match tool:
        case "read_file":
            lines = ""
            if args.get("start_line") or args.get("end_line"):
                s = args.get("start_line", 1)
                e = args.get("end_line", "end")
                lines = f" [dim](L{s}-L{e})[/dim]"
            return "Read", f"{path}{lines}"
        case "write_file":
            size = len(args.get("content", ""))
            return "Write", f"{path} [dim]({size} bytes)[/dim]"
        case "edit_file":
            return "Edit", path
        case "move_file":
            dest = args.get("destination", "")
            return "Move", f"{path} → {dest}" if dest else path
        case "list_directory":
            return "Explore", path or "."
        case "search_files":
            q = args.get("query", "")
            return "Search", f'"{q}"'
        case "create_plan":
            tasks = args.get("tasks", [])
            return "Plan", f"Created {len(tasks)} tasks"
        case "update_plan_task":
            tid = args.get("task_id", "?")
            st = args.get("status", "")
            return "Plan", f"Task #{tid} → {st}"
        case "get_plan":
            return "Plan", "Inspect task plan"
        case "run_command":
            cmd = args.get("command", "")
            return "Run", cmd[:60] + ("…" if len(cmd) > 60 else "")
        case "delegate_task":
            role = args.get("role", "subagent")
            return f"Delegate ({role})", args.get("task", "")[:45]
        case _:
            return tool, path


# ── Event handler ────────────────────────────────────────────────────────────

def on_event(event: AgentEvent) -> None:
    global _active_tool_start, _active_tool_name

    if event.name == "Thinking":
        console.print("  [dim cyan]⚡ Thinking...[/dim cyan]")

    elif event.name == "PreToolUse":
        tool = event.data.get("tool", "?")
        args = event.data.get("args", {})
        _active_tool_name = tool
        _active_tool_start = time.perf_counter()

        action, target = _format_tool_action(tool, args)
        target_str = f" [white]{target}[/white]" if target else ""
        console.print(f"  [cyan]╭─[/cyan] [bold cyan]⚙ {action}[/bold cyan]{target_str}")

    elif event.name == "PostToolUse":
        tool = event.data.get("tool", "?")
        is_err = event.data.get("error", False)

        duration_str = ""
        if _active_tool_start is not None:
            elapsed = (time.perf_counter() - _active_tool_start) * 1000
            duration_str = f" [dim yellow]({elapsed:.0f}ms)[/dim yellow]"
            _active_tool_start = None
            _active_tool_name = None

        if is_err:
            error_data = event.data.get("result", {})
            error_msg = getattr(error_data, "error", "Unknown error")
            if isinstance(error_msg, str) and len(error_msg) > 80:
                error_msg = error_msg[:80] + "…"
            console.print(f"  [red]╰─[/red] [bold red]✗ {tool} failed:[/bold red] [dim red]{error_msg}[/dim red]{duration_str}")
        else:
            console.print(f"  [green]╰─[/green] [dim green]✓ {tool} completed[/dim green]{duration_str}")

    elif event.name == "Stop":
        reason = event.data.get("reason", "done")
        if "error" in reason.lower():
            console.print(f"  [bold red]✗ {reason}[/bold red]")


# ── Permission prompt ────────────────────────────────────────────────────────

def request_permission(tool_name: str, path: str) -> PermissionDecision:
    console.print()
    display_path = f" [path]{path}[/path]" if path else ""

    panel_content = (
        f"  Tool: [bold cyan]{tool_name}[/bold cyan]{display_path}\n\n"
        f"  [bold white]\\[a][/bold white] [green]Allow once[/green]    "
        f"[bold white]\\[s][/bold white] [cyan]Allow always for this directory[/cyan]    "
        f"[bold white]\\[d][/bold white] [red]Deny[/red]"
    )
    console.print(Panel(panel_content, title="[bold yellow]⚠ Permission Required[/bold yellow]", border_style="yellow", padding=(1, 2)))

    while True:
        try:
            console.print("  [bold yellow]❯[/bold yellow] ", end="")
            raw = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            return PermissionDecision.DENY

        if raw in ("a", "allow", "y", "yes"):
            return PermissionDecision.ALLOW_ONCE
        if raw in ("s", "always"):
            return PermissionDecision.ALLOW_ALWAYS
        if raw in ("d", "deny", "n", "no", ""):
            return PermissionDecision.DENY

        console.print("    [dim red]Invalid option. Enter 'a', 's', or 'd'.[/dim red]")


# ── Response renderer ────────────────────────────────────────────────────────

def _print_response(text: str, elapsed_seconds: float | None = None, model_name: str = "") -> None:
    """Render agent response as clean Markdown in an elegant bordered panel."""
    if not text or not text.strip():
        return

    render_width = min(console.width - 2, 105)

    stats_parts = []
    if elapsed_seconds is not None:
        stats_parts.append(f"⏱ {elapsed_seconds:.1f}s")
    if model_name:
        stats_parts.append(f"⚡ {model_name}")

    subtitle = f"[dim]({'  │  '.join(stats_parts)})[/dim]" if stats_parts else None

    response_panel = Panel(
        Markdown(text.strip()),
        border_style="cyan",
        padding=(1, 2),
        expand=False,
        title="[bold cyan]SetuCode[/bold cyan]",
        title_align="left",
        subtitle=subtitle,
        subtitle_align="right",
    )

    console.print()
    console.print(Padding(response_panel, (0, 0, 0, 1)), width=render_width)
    console.print()


def _get_git_branch(workspace: Path) -> str:
    """Detect current Git branch name if inside a Git repository."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(workspace),
            timeout=1,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


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

    # ── Welcome banner ──
    git_branch = _get_git_branch(settings.workspace_root)
    git_label = f"  🌿 Git       : [bold green]{git_branch}[/bold green]\n" if git_branch else ""

    endpoint_info = ""
    if settings.openai_base_url:
        endpoint_info = f"\n  🌐 Endpoint  : [dim]{settings.openai_base_url}[/dim]"
    elif settings.anthropic_base_url:
        endpoint_info = f"\n  🌐 Endpoint  : [dim]{settings.anthropic_base_url}[/dim]"
    elif settings.gemini_base_url:
        endpoint_info = f"\n  🌐 Endpoint  : [dim]{settings.gemini_base_url}[/dim]"

    skill_reg = get_default_skill_registry(settings.workspace_root)
    discovered_skills = len(skill_reg.list_all())

    banner_text = (
        f"  [bold white]⚡ SetuCode[/bold white] [dim]v0.1.0 — Autonomous AI Coding Assistant[/dim]\n\n"
        f"  🤖 Provider  : [bold cyan]{settings.provider}[/bold cyan]\n"
        f"  ⚡ Model     : [bold white]{settings.model}[/bold white]{endpoint_info}\n"
        f"  📁 Workspace : [dim]{settings.workspace_root}[/dim]\n"
        f"{git_label}"
        f"  🧩 Skills    : [dim]{discovered_skills} available (use /<skill-name> or /skills)[/dim]  [dim]│[/dim]  "
        f"⚙ Tools: [dim]{len(registry.all_tools())} loaded[/dim]"
    )

    banner_width = min(console.width - 2, 90)
    console.print()
    console.print(
        Padding(
            Panel(
                banner_text,
                border_style="cyan",
                padding=(1, 2),
                expand=False,
                title="[bold cyan]✦ Welcome ✦[/bold cyan]",
                title_align="left",
            ),
            (0, 0, 0, 1),
        ),
        width=banner_width,
    )
    console.print(
        "  [dim]Commands: [bold cyan]/menu[/bold cyan] [bold cyan]/model[/bold cyan] [bold cyan]/skills[/bold cyan] "
        "[bold cyan]/plan[/bold cyan] [bold cyan]/config[/bold cyan] [bold cyan]/help[/bold cyan] [bold cyan]/exit[/bold cyan] "
        "[dim white](Type '/' for instant command & skill autocomplete)[/dim white][/dim]\n"
    )

    try:
        while True:
            try:
                user_input = prompt_interactive(console, "  ❯ ", str(settings.workspace_root))
            except (EOFError, KeyboardInterrupt):
                console.print()
                break

            if not user_input:
                continue

            # Support multiline entry if ending with '\' or '/multiline'
            if user_input.endswith("\\") or user_input == "/multiline":
                lines = [user_input.rstrip("\\")] if user_input != "/multiline" else []
                console.print("  [dim]... (multiline mode: enter empty line to submit)[/dim]")
                while True:
                    try:
                        console.print("  [dim cyan]│[/dim cyan] ", end="")
                        line = input()
                        if not line:
                            break
                        lines.append(line)
                    except (EOFError, KeyboardInterrupt):
                        break
                user_input = "\n".join(lines).strip()
                if not user_input:
                    continue

            console.print()

            if cmd_router.is_command(user_input):
                should_continue = cmd_router.dispatch(user_input, cmd_ctx)
                if not should_continue:
                    break
                continue

            # Run agent loop with timer
            start_time = time.perf_counter()
            result = agent_run(state, user_input, bus, registry, perms)
            elapsed = time.perf_counter() - start_time

            active_model = getattr(provider, "model", settings.model)
            _print_response(result, elapsed_seconds=elapsed, model_name=active_model)

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
