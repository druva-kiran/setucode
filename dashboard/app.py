"""SetuCode CLI — Linux terminal aesthetic.

Inspired by zsh/fish prompts and tools like aider, lazygit, gh CLI.
- Muted colours, information-dense, no decorative emoji
- ❯ prompt (zsh/fish style)
- Tool activity as compact dimmed log lines
- Permission prompt as a drawn box with single-key options
- Agent output indented with a left bar
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path

from rich.console import Console
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
from app.tools.registry import build_default_registry

# ── Colour palette ──────────────────────────────────────────────────────────
theme = Theme({
    "prompt":   "bold #5f87ff",      # blue — the ❯ glyph
    "meta":     "dim white",         # dimmed metadata
    "tool":     "dim cyan",          # tool name in activity log
    "ok":       "dim green",         # ✓ success marker
    "err":      "red",               # ✗ / errors
    "warn":     "yellow",            # warnings
    "bar":      "dim white",         # │ response left bar
    "heading":  "bold white",        # section headings
    "box":      "dim white",         # permission box border
    "key":      "bold white",        # [a] key hints
    "path":     "dim #87afff",       # file paths
})

console = Console(theme=theme, highlight=False)
log = logging.getLogger(__name__)

# ── Symbols ──────────────────────────────────────────────────────────────────
PROMPT_GLYPH  = "❯"
CONT_GLYPH    = " "      # continuation (no glyph)
OK_MARK       = "✓"
ERR_MARK      = "✗"
WAIT_MARK     = "·"
RESP_BAR      = "│"


# ── Event handler ────────────────────────────────────────────────────────────

def on_event(event: AgentEvent) -> None:
    if event.name == "Thinking":
        # Subtle — just a waiting dot, overwritten when tool fires
        console.print(f"  [meta]{WAIT_MARK}[/meta]", end="\r")

    elif event.name == "PreToolUse":
        tool = event.data.get("tool", "?")
        args = event.data.get("args", {})
        path = args.get("path") or args.get("source") or ""
        # pad tool name to align paths
        console.print(
            f"  [meta]{WAIT_MARK}[/meta] [tool]{tool:<18}[/tool] [path]{path}[/path]",
            end="\r",
        )

    elif event.name == "PostToolUse":
        tool  = event.data.get("tool", "?")
        is_err = event.data.get("error", False)
        args  = (event.data.get("result") or {})
        # Clear the \r line then print final status
        mark  = f"[err]{ERR_MARK}[/err]" if is_err else f"[ok]{OK_MARK}[/ok]"
        console.print(f"  {mark} [tool]{tool:<18}[/tool]")

    elif event.name == "Stop":
        reason = event.data.get("reason", "done")
        if "error" in reason.lower():
            console.print(f"\n  [err]{ERR_MARK} {reason}[/err]")


# ── Permission prompt ────────────────────────────────────────────────────────

def _box(lines: list[str], width: int = 54) -> str:
    """Return a simple unicode box around lines."""
    inner = width - 2
    top    = "┌" + "─" * inner + "┐"
    bottom = "└" + "─" * inner + "┘"
    rows   = [top]
    for line in lines:
        # truncate if needed
        visible = line[:inner]
        padding = " " * (inner - len(visible))
        rows.append("│" + visible + padding + "│")
    rows.append(bottom)
    return "\n".join(rows)


def request_permission(tool_name: str, path: str) -> PermissionDecision:
    console.print()
    box_lines = [
        f"  permission required",
        f"",
        f"  tool  {tool_name}",
        f"  path  {path[:44]}",
        f"",
        f"  [a] allow once   [s] always   [d] deny",
    ]
    # Print box in dim white
    for line in _box(box_lines).splitlines():
        console.print(f"  [box]{line}[/box]")
    console.print()

    while True:
        try:
            raw = input("  ❯ ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return PermissionDecision.DENY
        if raw in ("a", "1", "allow"):
            return PermissionDecision.ALLOW_ONCE
        if raw in ("s", "2", "always"):
            return PermissionDecision.ALLOW_ALWAYS
        if raw in ("d", "3", "deny", "n", "no"):
            return PermissionDecision.DENY
        console.print(f"  [meta]a · s · d[/meta]")


# ── Response printer ─────────────────────────────────────────────────────────

def _print_response(text: str) -> None:
    """Print agent response with a left bar, like a quoted block."""
    console.print()
    for line in text.splitlines():
        console.print(f"  [bar]{RESP_BAR}[/bar] {line}")
    console.print()


# ── Main REPL loop ───────────────────────────────────────────────────────────

def run_session(settings: Settings) -> None:
    memory = MemoryManager(settings.user_memory_path)

    try:
        provider = build_provider(settings)
    except ValueError as e:
        console.print(f"\n  [err]{ERR_MARK}[/err] {e}")
        console.print("  run [heading]setucode --setup[/heading] to configure\n")
        return

    registry = build_default_registry(settings.workspace_root)
    storage  = PermissionStorage(settings.permission_storage_path)
    perms    = PermissionManager(storage, request_permission)

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

    console.print()
    console.print(f"  [heading]setucode[/heading]  [meta]{settings.provider}/{settings.model}[/meta]")
    console.print(f"  [meta]workspace  {settings.workspace_root}[/meta]")
    console.print(f"  [meta]ctrl+c to quit · /help for commands[/meta]")
    console.print()

    try:
        while True:
            # ❯ prompt — bold blue
            try:
                console.print(f"[prompt]{PROMPT_GLYPH}[/prompt] ", end="")
                user_input = input().strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n")
                break

            if not user_input:
                continue

            if user_input.lower() in ("/quit", "/exit", "exit", "quit", "q"):
                console.print()
                break

            # separator before agent activity
            console.print()

            result = agent_run(state, user_input, bus, registry, perms)
            _print_response(result)

    finally:
        try:
            memory.write_session_memories(state.messages, provider)
        except Exception as e:
            log.error("memory write: %s", e)


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
        console.print("\n  [warn]no provider configured[/warn] — running setup\n")
        from dashboard.setup_wizard import run_setup_cli
        run_setup_cli()
        settings = load_settings()

    if not settings.provider:
        console.print("  [err]setup incomplete.[/err] run [heading]setucode --setup[/heading]\n")
        return

    run_session(settings)


if __name__ == "__main__":
    main()
