"""Interactive TUI list selector with arrow navigation, Enter to select, and Esc to cancel."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from dashboard.keyboard import is_interactive, read_key


@dataclass
class SelectItem:
    id: str
    title: str
    description: str = ""
    badge: str = ""
    is_current: bool = False


def run_interactive_selector(
    console: Console,
    title: str,
    items: list[SelectItem],
    current_id: str | None = None,
    empty_message: str = "No items available.",
    footer_hint: str = "↑ ↓  Navigate  │  Enter  Select  │  Esc  Cancel",
    max_visible: int = 12,
) -> Optional[SelectItem]:
    """Run an interactive arrow-key selector inside the terminal.

    Returns the chosen SelectItem, or None if the user cancelled with Esc.
    """
    if not items:
        console.print(f"[dim]{empty_message}[/dim]")
        return None

    # Determine initial cursor index
    cursor = 0
    if current_id:
        for idx, item in enumerate(items):
            if item.id == current_id or item.is_current:
                cursor = idx
                break

    # If running in a non-interactive environment (CI, pipes)
    if not is_interactive():
        return items[cursor]

    total = len(items)

    def _render() -> Panel:
        nonlocal cursor
        # Compute sliding window
        start_idx = 0
        if total > max_visible:
            half = max_visible // 2
            start_idx = max(0, min(cursor - half, total - max_visible))
        end_idx = min(start_idx + max_visible, total)

        content_lines: list[Text] = []

        for i in range(start_idx, end_idx):
            item = items[i]
            is_active_cursor = (i == cursor)

            line = Text()
            if is_active_cursor:
                line.append("❯ ", style="bold cyan")
                line.append(item.title, style="bold white")
            else:
                line.append("  ", style="dim")
                line.append(item.title, style="dim white")

            if item.badge:
                badge_style = "bold green" if ("active" in item.badge.lower() or item.is_current) else "dim cyan"
                line.append(f" {item.badge}", style=badge_style)
            elif item.is_current:
                line.append(" ● active", style="bold green")

            content_lines.append(line)

        # Selected item description
        curr_item = items[cursor]
        info_text = Text()
        if curr_item.description:
            info_text.append(f"\n{curr_item.description}", style="dim")

        # Scroll indicator if long
        scroll_indicator = ""
        if total > max_visible:
            scroll_indicator = f" [dim]({cursor + 1}/{total})[/dim]"

        full_group = Group(
            *content_lines,
            info_text,
            Text(f"\n{footer_hint}", style="dim"),
        )

        return Panel(
            full_group,
            title=f"[bold cyan]{title}[/bold cyan]{scroll_indicator}",
            border_style="cyan",
            expand=False,
            padding=(1, 2),
        )

    # Run live rendering loop
    with Live(_render(), console=console, auto_refresh=False, transient=True) as live:
        while True:
            live.update(_render(), refresh=True)
            key = read_key()

            if key == "UP":
                cursor = (cursor - 1) % total
            elif key == "DOWN":
                cursor = (cursor + 1) % total
            elif key == "ENTER":
                return items[cursor]
            elif key in ("ESC", "CTRL_C", "q"):
                return None
