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
    category: str = ""


def _highlight_matches(text: str, query: str, base_style: str = "", match_style: str = "bold cyan underline") -> Text:
    """Highlight matched query characters in a Text object."""
    res = Text()
    if not query:
        res.append(text, style=base_style)
        return res

    lower_text = text.lower()
    lower_query = query.lower()
    start = 0
    while True:
        idx = lower_text.find(lower_query, start)
        if idx == -1:
            res.append(text[start:], style=base_style)
            break
        if idx > start:
            res.append(text[start:idx], style=base_style)
        res.append(text[idx : idx + len(lower_query)], style=match_style)
        start = idx + len(lower_query)
    return res


def run_interactive_selector(
    console: Console,
    title: str,
    items: list[SelectItem],
    current_id: str | None = None,
    empty_message: str = "No items available.",
    footer_hint: str = "↑ ↓ Navigate  │  Type to search  │  Enter Select  │  Esc Cancel",
    max_visible: int = 12,
    enable_search: bool = True,
) -> Optional[SelectItem]:
    """Run an interactive arrow-key selector inside the terminal.

    Features real-time search/filter, match highlighting, and sliding navigation.
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

    search_query = ""

    def _get_filtered_items() -> list[SelectItem]:
        if not search_query.strip():
            return items
        q = search_query.strip().lower()
        return [
            item for item in items
            if q in item.title.lower() or q in item.id.lower() or q in item.description.lower() or q in item.category.lower()
        ]

    def _render() -> Panel:
        nonlocal cursor
        filtered = _get_filtered_items()
        total_filtered = len(filtered)

        if total_filtered == 0:
            cursor = 0
            search_bar = Text()
            search_bar.append("  🔍 Search: ", style="bold cyan")
            search_bar.append(search_query, style="bold white underline")
            search_bar.append("▌\n", style="bold cyan")

            empty_text = Text(f"\n  No items matching \"{search_query}\". Press Backspace or Esc to clear.\n", style="dim red")
            return Panel(
                Group(search_bar, empty_text, Text(f"\n{footer_hint}", style="dim")),
                title=f"[bold cyan]{title}[/bold cyan] [dim](0/{len(items)})[/dim]",
                border_style="cyan",
                expand=False,
                padding=(1, 2),
            )

        if cursor >= total_filtered:
            cursor = max(0, total_filtered - 1)

        # Compute sliding window
        start_idx = 0
        if total_filtered > max_visible:
            half = max_visible // 2
            start_idx = max(0, min(cursor - half, total_filtered - max_visible))
        end_idx = min(start_idx + max_visible, total_filtered)

        content_lines: list[Text] = []

        # Search bar line if search is enabled or query is active
        if enable_search or search_query:
            search_bar = Text()
            search_bar.append("  🔍 Filter: ", style="dim cyan")
            if search_query:
                search_bar.append(search_query, style="bold white underline")
                search_bar.append("▌\n", style="bold cyan")
            else:
                search_bar.append("(type to search)\n", style="dim italic")
            content_lines.append(search_bar)

        for i in range(start_idx, end_idx):
            item = filtered[i]
            is_active_cursor = (i == cursor)

            line = Text()
            if is_active_cursor:
                line.append("  ❯ ", style="bold cyan")
                line.append_text(_highlight_matches(item.title, search_query, base_style="bold white", match_style="bold cyan underline"))
            else:
                line.append("    ", style="dim")
                line.append_text(_highlight_matches(item.title, search_query, base_style="dim white", match_style="cyan underline"))

            if item.category:
                line.append(f" [{item.category}]", style="dim magenta")

            if item.badge:
                badge_style = "bold green" if ("active" in item.badge.lower() or item.is_current) else "dim cyan"
                line.append(f" {item.badge}", style=badge_style)
            elif item.is_current:
                line.append(" ● active", style="bold green")

            content_lines.append(line)

        # Selected item description
        curr_item = filtered[cursor]
        info_text = Text()
        if curr_item.description:
            info_text.append(f"\n  {curr_item.description}", style="dim")

        # Scroll indicator if long
        scroll_indicator = f" [dim]({cursor + 1}/{total_filtered})[/dim]"

        full_group = Group(
            *content_lines,
            info_text,
            Text(f"\n  {footer_hint}", style="dim"),
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
            filtered = _get_filtered_items()
            total_filtered = len(filtered)

            if key == "UP":
                if total_filtered > 0:
                    cursor = (cursor - 1) % total_filtered
            elif key == "DOWN":
                if total_filtered > 0:
                    cursor = (cursor + 1) % total_filtered
            elif key == "PAGE_UP":
                if total_filtered > 0:
                    cursor = max(0, cursor - 5)
            elif key == "PAGE_DOWN":
                if total_filtered > 0:
                    cursor = min(total_filtered - 1, cursor + 5)
            elif key == "HOME":
                cursor = 0
            elif key == "END":
                if total_filtered > 0:
                    cursor = total_filtered - 1
            elif key == "ENTER":
                if total_filtered > 0:
                    return filtered[cursor]
                return None
            elif key in ("ESC", "CTRL_C"):
                if search_query:
                    search_query = ""
                    cursor = 0
                else:
                    return None
            elif key == "BACKSPACE":
                if search_query:
                    search_query = search_query[:-1]
                    cursor = 0
            elif len(key) == 1 and key.isprintable() and enable_search:
                search_query += key
                cursor = 0
