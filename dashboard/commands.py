"""Slash command architecture and handlers for SetuCode TUI.

Provides a unified CommandRouter and first-class TUI command handlers:
- /model   : Interactive model selection and discovery
- /skills  : Interactive skill browser and activation manager
- /status  : Agent runtime status and metrics
- /help    : Command directory
- /plan    : Task plan status
- /clear   : Terminal screen clear
- /exit    : Graceful shutdown
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.agent.state import AgentState
from app.config.settings import Settings
from app.events.bus import EventBus
from app.permissions.manager import PermissionManager
from app.providers.base import BaseProvider, ModelInfo
from app.skills.manager import get_default_skill_registry
from app.skills.registry import SkillRegistry
from app.tools.registry import ToolRegistry
from dashboard.keyboard import read_key
from dashboard.selector import SelectItem, run_interactive_selector


@dataclass
class CommandContext:
    console: Console
    state: AgentState
    settings: Settings
    provider: BaseProvider
    registry: ToolRegistry
    permissions: PermissionManager
    bus: EventBus


@dataclass
class Command:
    name: str
    description: str
    usage: str
    handler: Callable[[CommandContext, str], bool]


class CommandRouter:
    """Central router for slash commands. Prevents command leakage to LLM."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        self._commands[command.name.lower()] = command

    def is_command(self, text: str) -> bool:
        return text.strip().startswith("/")

    def get_command(self, name: str) -> Optional[Command]:
        return self._commands.get(name.lower().lstrip("/"))

    def list_commands(self) -> list[Command]:
        return list(self._commands.values())

    def dispatch(self, text: str, ctx: CommandContext) -> bool:
        """Route and execute a slash command.

        Returns True to continue the REPL loop, or False to exit.
        """
        raw = text.strip()
        parts = raw.split(maxsplit=1)
        cmd_name = parts[0].lstrip("/").lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        # Support aliases
        if cmd_name in ("quit", "q"):
            cmd_name = "exit"

        command = self._commands.get(cmd_name)
        if not command:
            ctx.console.print(
                f" [err]Unknown command '{parts[0]}'.[/err] [dim]Type /help for available commands.[/dim]\n"
            )
            return True

        return command.handler(ctx, args)


# ── Command Handlers ─────────────────────────────────────────────────────────

def handle_model(ctx: CommandContext, args: str) -> bool:
    """Handle /model — interactive model selector or direct model assignment."""
    # 1. Direct assignment: e.g. /model gpt-4o
    if args:
        target_model = args.strip()
        ctx.provider.set_model(target_model)
        ctx.settings.update_model(target_model, persist=True)
        ctx.console.print(f" [ok]✓[/ok] Model changed to [bold cyan]{target_model}[/bold cyan]\n")
        return True

    # 2. Interactive discovery and selection
    provider_name = getattr(ctx.provider, "provider_name", ctx.settings.provider)
    with ctx.console.status(f"[dim]Fetching available models from {provider_name}...[/dim]", spinner="dots"):
        models, warning_or_error = ctx.provider.get_available_models()

    if warning_or_error:
        ctx.console.print(f" [warn]Notice:[/warn] {warning_or_error}")

    if not models:
        ctx.console.print(" [err]No models available for the active provider.[/err]\n")
        return True

    current_model = getattr(ctx.provider, "model", ctx.settings.model)

    # Convert to SelectItems
    items: list[SelectItem] = []
    for m in models:
        badge = "● active" if m.id == current_model else (f"[{m.provider}]" if m.provider else "")
        items.append(
            SelectItem(
                id=m.id,
                title=m.name or m.id,
                description=m.description or (f"Provider: {m.provider}" if m.provider else ""),
                badge=badge,
                is_current=(m.id == current_model),
            )
        )

    selected = run_interactive_selector(
        ctx.console,
        title=f"Select Model ({provider_name})",
        items=items,
        current_id=current_model,
        footer_hint="↑ ↓  Navigate  │  Enter  Select  │  Esc  Cancel",
    )

    if selected is None:
        ctx.console.print(f" [dim]Cancelled. Active model remains {current_model}.[/dim]\n")
        return True

    if selected.id != current_model:
        ctx.provider.set_model(selected.id)
        ctx.settings.update_model(selected.id, persist=True)
        ctx.console.print(f" [ok]✓[/ok] Model changed to [bold cyan]{selected.id}[/bold cyan]\n")
    else:
        ctx.console.print(f" [dim]Model unchanged ({current_model}).[/dim]\n")

    return True


def handle_skills(ctx: CommandContext, args: str) -> bool:
    """Handle /skills — interactive skill browser and activation toggle."""
    skill_reg: SkillRegistry = get_default_skill_registry(ctx.state.workspace)
    all_skills = skill_reg.list_all()

    if not all_skills:
        ctx.console.print(" [dim]No skills discovered in .agents/skills or skills/[/dim]\n")
        return True

    while True:
        items: list[SelectItem] = []
        for s in all_skills:
            is_act = skill_reg.is_active(s.name)
            items.append(
                SelectItem(
                    id=s.name,
                    title=s.name,
                    badge="● active" if is_act else "[available]",
                    description=s.description or "No description provided.",
                    is_current=is_act,
                )
            )

        selected = run_interactive_selector(
            ctx.console,
            title="Skills Browser",
            items=items,
            footer_hint="↑ ↓  Navigate  │  Enter  Inspect & Toggle  │  Esc  Close",
        )

        if selected is None:
            ctx.console.print(" [dim]Closed skills browser.[/dim]\n")
            break

        # User selected a skill to inspect & toggle
        skill = skill_reg.get(selected.id)
        if not skill:
            continue

        is_act = skill_reg.is_active(skill.name)
        status_label = "[bold green]Active (injected into context)[/bold green]" if is_act else "[dim yellow]Available (on-demand)[/dim yellow]"
        conds = ", ".join(skill.activation_conditions) if skill.activation_conditions else "None (manual only)"
        tool_names = ", ".join(t.name for t in skill.tools) if skill.tools else "None"

        # Show detailed inspection panel
        lines = [
            Text.from_markup(f"[bold white]{skill.name}[/bold white] — {status_label}\n"),
            Text.from_markup(f"[cyan]Description:[/cyan] {skill.description or 'None'}"),
            Text.from_markup(f"[cyan]Triggers:[/cyan] [dim]{conds}[/dim]"),
            Text.from_markup(f"[cyan]Registered Tools:[/cyan] [dim]{tool_names}[/dim]\n"),
        ]
        if skill.instructions:
            preview = skill.instructions.strip().splitlines()
            snippet = "\n".join(preview[:5]) + ("..." if len(preview) > 5 else "")
            lines.append(Text.from_markup(f"[cyan]Instructions Preview:[/cyan]\n[dim]{snippet}[/dim]\n"))

        action_toggle = "Deactivate" if is_act else "Activate"
        lines.append(Text.from_markup(f"  [bold]t[/bold] {action_toggle} skill  [dim]│[/dim]  [bold]b[/bold] Back to list  [dim]│[/dim]  [bold]Esc[/bold] Close"))

        panel = Panel(
            Group(*lines),
            title=f"[bold cyan]Skill: {skill.name}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
        ctx.console.print(panel)

        key = read_key()
        if key in ("t", "T", "ENTER"):
            new_active = skill_reg.toggle_skill(skill.name, tool_registry=ctx.registry)
            status_word = "activated" if new_active else "deactivated"
            ctx.console.print(f" [ok]✓[/ok] Skill [bold cyan]{skill.name}[/bold cyan] {status_word}.\n")
        elif key in ("ESC", "CTRL_C", "q"):
            ctx.console.print()
            break
        else:
            # Back to list
            ctx.console.print()
            continue

    return True


def handle_help(ctx: CommandContext, args: str) -> bool:
    """Handle /help — display available slash commands in a clean TUI panel."""
    table = Table(box=None, padding=(0, 2), show_header=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Usage", style="dim white")
    table.add_column("Description", style="white")

    router = build_default_command_router()
    for cmd in router.list_commands():
        table.add_row(f"/{cmd.name}", cmd.usage, cmd.description)

    panel = Panel(
        table,
        title="[bold cyan]SetuCode Commands[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    ctx.console.print()
    ctx.console.print(panel)
    ctx.console.print()
    return True


def handle_status(ctx: CommandContext, args: str) -> bool:
    """Handle /status — display agent status, model, endpoints, and metrics."""
    table = Table(box=None, padding=(0, 2), show_header=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value", style="white")

    provider_name = getattr(ctx.provider, "provider_name", ctx.settings.provider)
    current_model = getattr(ctx.provider, "model", ctx.settings.model)

    endpoint = "Official API"
    if ctx.settings.openai_base_url:
        endpoint = f"Custom ({ctx.settings.openai_base_url})"
    elif ctx.settings.anthropic_base_url:
        endpoint = f"Custom ({ctx.settings.anthropic_base_url})"
    elif ctx.settings.gemini_base_url:
        endpoint = f"Custom ({ctx.settings.gemini_base_url})"

    tools_count = len(ctx.registry.all_tools())
    skill_reg = get_default_skill_registry(ctx.state.workspace)
    skills_total = len(skill_reg.list_all())
    skills_active = len(skill_reg.get_active_hints())

    table.add_row("Provider", provider_name)
    table.add_row("Active Model", current_model)
    table.add_row("Endpoint", endpoint)
    table.add_row("Workspace", str(ctx.state.workspace))
    table.add_row("Tools Registered", str(tools_count))
    table.add_row("Skills Discovered", f"{skills_total} ({skills_active} active)")

    plan = getattr(ctx.state, "plan", None)
    if plan and plan.tasks:
        completed = sum(1 for t in plan.tasks if t.status.value == "completed")
        table.add_row("Active Plan", f"{completed}/{len(plan.tasks)} tasks completed")
    else:
        table.add_row("Active Plan", "None")

    table.add_row("Session ID", ctx.state.session_id)

    panel = Panel(
        table,
        title="[bold cyan]Agent Status[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    ctx.console.print()
    ctx.console.print(panel)
    ctx.console.print()
    return True


def handle_plan(ctx: CommandContext, args: str) -> bool:
    """Handle /plan — view active plan status."""
    plan = getattr(ctx.state, "plan", None)
    if plan and plan.tasks:
        ctx.console.print()
        ctx.console.print(Markdown(plan.render()))
        ctx.console.print()
    else:
        ctx.console.print(" [dim]No active plan defined.[/dim]\n")
    return True


def handle_clear(ctx: CommandContext, args: str) -> bool:
    """Handle /clear — clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")
    return True


def handle_exit(ctx: CommandContext, args: str) -> bool:
    """Handle /exit or /quit — gracefully exit SetuCode."""
    ctx.console.print(" [dim]Goodbye.[/dim]\n")
    return False


def build_default_command_router() -> CommandRouter:
    """Build and register all default TUI slash commands."""
    router = CommandRouter()
    router.register(
        Command(
            name="model",
            description="Select or change active LLM model",
            usage="/model [name]",
            handler=handle_model,
        )
    )
    router.register(
        Command(
            name="skills",
            description="Interactive skill browser & manager",
            usage="/skills",
            handler=handle_skills,
        )
    )
    router.register(
        Command(
            name="status",
            description="Show agent runtime status and metrics",
            usage="/status",
            handler=handle_status,
        )
    )
    router.register(
        Command(
            name="plan",
            description="View current task plan and TODO status",
            usage="/plan",
            handler=handle_plan,
        )
    )
    router.register(
        Command(
            name="clear",
            description="Clear terminal screen",
            usage="/clear",
            handler=handle_clear,
        )
    )
    router.register(
        Command(
            name="help",
            description="Show available commands",
            usage="/help",
            handler=handle_help,
        )
    )
    router.register(
        Command(
            name="exit",
            description="Exit SetuCode",
            usage="/exit",
            handler=handle_exit,
        )
    )
    return router
