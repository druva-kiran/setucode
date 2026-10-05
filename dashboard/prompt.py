"""Interactive prompt with real-time slash command & skill autocomplete suggestions.

Provides a responsive terminal input interface:
- Real-time command & skill autocomplete popup as the user types '/'
- Tab completion for slash commands and discovered skills
- Up/Down navigation across suggestions or command history
- Cross-platform key handling with graceful fallback for non-interactive environments
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from app.skills.manager import get_default_skill_registry
from dashboard.keyboard import is_interactive, read_key

_COMMAND_HISTORY: list[str] = []


@dataclass
class Suggestion:
    name: str
    category: str
    description: str


def get_all_suggestions(workspace_path: Optional[str] = None) -> list[Suggestion]:
    """Gather all built-in commands and all discovered skills as suggestions."""
    suggestions: list[Suggestion] = [
        Suggestion("model", "Core", "Select or change active LLM model"),
        Suggestion("skills", "Skills", "Browse, inspect, or create skills"),
        Suggestion("plan", "Agent", "Interactive task plan & TODO status"),
        Suggestion("tools", "Tools", "Inspect registered tool schemas"),
        Suggestion("memory", "Memory", "Manage USER.md & AGENTS.md"),
        Suggestion("config", "Settings", "Configure provider, endpoint & workspace"),
        Suggestion("status", "Status", "Agent runtime status & metrics dashboard"),
        Suggestion("compact", "Context", "View token usage & compact context"),
        Suggestion("export", "History", "Export session transcript to Markdown"),
        Suggestion("clear", "Core", "Clear terminal screen ('/clear all' for history)"),
        Suggestion("help", "Core", "Show all available commands"),
        Suggestion("exit", "Core", "Exit SetuCode"),
    ]

    # Discover all skills and add as first-class suggestions
    try:
        from pathlib import Path
        ws = Path(workspace_path) if workspace_path else None
        skill_reg = get_default_skill_registry(ws)
        skill_reg.refresh()
        for skill in skill_reg.list_all():
            suggestions.append(
                Suggestion(
                    name=skill.name,
                    category="Skill",
                    description=skill.description or f"Skill instructions for {skill.name}",
                )
            )
    except Exception:
        pass

    return suggestions


def prompt_interactive(
    console: Console,
    prompt_symbol: str = "  ❯ ",
    workspace_path: Optional[str] = None,
) -> str:
    """Prompt the user for input with live autocomplete suggestions for slash commands & skills."""
    if not is_interactive():
        # Fallback for piped/mock/automated environments
        try:
            console.print(f"[bold cyan]{prompt_symbol}[/bold cyan]", end="")
            line = sys.stdin.readline()
            if not line:
                return ""
            return line.strip()
        except Exception:
            return ""

    all_suggestions = get_all_suggestions(workspace_path)
    buffer = ""
    cursor_pos = 0
    history_idx = len(_COMMAND_HISTORY)
    selected_sugg_idx = 0

    def _get_matches() -> list[Suggestion]:
        if not buffer.startswith("/"):
            return []
        query = buffer[1:].split()[0].lower() if buffer[1:] else ""
        if not query:
            return all_suggestions
        return [s for s in all_suggestions if query in s.name.lower() or query in s.description.lower()]

    def _render() -> Group:
        # 1. Prompt line
        prompt_text = Text()
        prompt_text.append(prompt_symbol, style="bold cyan")
        if cursor_pos < len(buffer):
            prompt_text.append(buffer[:cursor_pos], style="bold white")
            prompt_text.append(buffer[cursor_pos], style="bold black on cyan")
            prompt_text.append(buffer[cursor_pos + 1:], style="bold white")
        else:
            prompt_text.append(buffer, style="bold white")
            prompt_text.append("▌", style="bold cyan")

        matches = _get_matches()
        if not matches or " " in buffer:
            return Group(prompt_text)

        # 2. Autocomplete suggestions popup
        nonlocal selected_sugg_idx
        total_matches = len(matches)
        if selected_sugg_idx >= total_matches:
            selected_sugg_idx = max(0, total_matches - 1)

        max_show = 6
        start_idx = 0
        if total_matches > max_show:
            start_idx = max(0, min(selected_sugg_idx - 2, total_matches - max_show))
        end_idx = min(start_idx + max_show, total_matches)

        sugg_lines: list[Text] = []
        for idx in range(start_idx, end_idx):
            s = matches[idx]
            is_active = (idx == selected_sugg_idx)
            line = Text()
            if is_active:
                line.append("  ❯ ", style="bold cyan")
                line.append(f"/{s.name:<18}", style="bold cyan")
            else:
                line.append("    ", style="dim")
                line.append(f"/{s.name:<18}", style="bold white")

            cat_style = "bold magenta" if s.category == "Skill" else "dim cyan"
            line.append(f" [{s.category}]", style=cat_style)

            desc = s.description
            if len(desc) > 42:
                desc = desc[:42] + "…"
            line.append(f"  {desc}", style="dim")
            sugg_lines.append(line)

        sugg_count = f" ({selected_sugg_idx + 1}/{total_matches})" if total_matches > max_show else ""
        panel = Panel(
            Group(*sugg_lines),
            title=f"[bold cyan]Suggestions{sugg_count}[/bold cyan] [dim](Tab to complete, ↑↓ to select)[/dim]",
            border_style="dim cyan",
            padding=(0, 1),
            expand=False,
        )
        return Group(prompt_text, panel)

    with Live(_render(), console=console, auto_refresh=False, transient=True) as live:
        while True:
            live.update(_render(), refresh=True)
            key = read_key()
            matches = _get_matches()

            if key == "ENTER":
                if buffer.strip():
                    if not _COMMAND_HISTORY or _COMMAND_HISTORY[-1] != buffer.strip():
                        _COMMAND_HISTORY.append(buffer.strip())
                # Clean prompt display
                console.print(f"[bold cyan]{prompt_symbol}[/bold cyan][bold white]{buffer}[/bold white]")
                return buffer.strip()

            elif key == "TAB":
                if matches and " " not in buffer:
                    # Autocomplete with current highlighted suggestion
                    chosen = matches[selected_sugg_idx]
                    buffer = f"/{chosen.name} "
                    cursor_pos = len(buffer)
                elif not buffer:
                    buffer = "/"
                    cursor_pos = 1

            elif key == "UP":
                if matches and " " not in buffer:
                    selected_sugg_idx = (selected_sugg_idx - 1) % len(matches)
                elif _COMMAND_HISTORY:
                    history_idx = max(0, history_idx - 1)
                    buffer = _COMMAND_HISTORY[history_idx]
                    cursor_pos = len(buffer)

            elif key == "DOWN":
                if matches and " " not in buffer:
                    selected_sugg_idx = (selected_sugg_idx + 1) % len(matches)
                elif _COMMAND_HISTORY:
                    history_idx = min(len(_COMMAND_HISTORY), history_idx + 1)
                    if history_idx < len(_COMMAND_HISTORY):
                        buffer = _COMMAND_HISTORY[history_idx]
                    else:
                        buffer = ""
                    cursor_pos = len(buffer)

            elif key == "LEFT":
                cursor_pos = max(0, cursor_pos - 1)

            elif key == "RIGHT":
                cursor_pos = min(len(buffer), cursor_pos + 1)

            elif key == "HOME":
                cursor_pos = 0

            elif key == "END":
                cursor_pos = len(buffer)

            elif key == "BACKSPACE":
                if cursor_pos > 0:
                    buffer = buffer[:cursor_pos - 1] + buffer[cursor_pos:]
                    cursor_pos -= 1
                    selected_sugg_idx = 0

            elif key == "DELETE":
                if cursor_pos < len(buffer):
                    buffer = buffer[:cursor_pos] + buffer[cursor_pos + 1:]
                    selected_sugg_idx = 0

            elif key == "CTRL_C":
                if buffer:
                    buffer = ""
                    cursor_pos = 0
                else:
                    console.print()
                    return "/exit"

            elif key == "ESC":
                if buffer.startswith("/"):
                    buffer = ""
                    cursor_pos = 0
                selected_sugg_idx = 0

            elif len(key) == 1 and key.isprintable():
                buffer = buffer[:cursor_pos] + key + buffer[cursor_pos:]
                cursor_pos += 1
                selected_sugg_idx = 0
