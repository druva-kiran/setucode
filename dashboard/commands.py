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
import json
import os
from pathlib import Path
from typing import Callable, Optional, List, Any

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.agent.state import AgentState
from app.config.settings import Settings, persist_selected_model
from app.events.bus import EventBus
from app.permissions.manager import PermissionManager
from app.providers.base import BaseProvider, ModelInfo
from app.skills.manager import get_default_skill_registry
from app.skills.registry import SkillRegistry
from app.tools.registry import ToolRegistry
from dashboard.keyboard import read_key, is_interactive
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
    category: str
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
        elif cmd_name in ("menu", ""):
            cmd_name = "menu"
        elif cmd_name == "settings":
            cmd_name = "config"
        elif cmd_name == "context":
            cmd_name = "compact"
        elif cmd_name == "history":
            cmd_name = "export"

        command = self._commands.get(cmd_name)
        if not command:
            # Check if it's a skill name — treat /skill-name as "read skill and use it"
            from app.skills.manager import get_default_skill_registry
            skill_reg = get_default_skill_registry(ctx.state.workspace)
            skill = skill_reg.get(cmd_name) or skill_reg.get(cmd_name.replace("_", "-"))
            if skill:
                return _dispatch_skill(ctx, skill, args)

            # Check for single prefix match across commands
            candidates = [c for c in self._commands.values() if c.name.startswith(cmd_name)]
            if len(candidates) == 1:
                return candidates[0].handler(ctx, args)

            ctx.console.print(
                f" [err]Unknown command '{parts[0]}'.[/err] [dim]Type /help for commands.[/dim]\n"
            )
            return True

        return command.handler(ctx, args)


# ── Command Handlers ─────────────────────────────────────────────────────────

def handle_menu(ctx: CommandContext, args: str) -> bool:
    """Handle /menu or bare '/' — interactive command palette."""
    router = build_default_command_router()
    commands = router.list_commands()

    seen_handlers = set()
    menu_commands: list[Command] = []
    for cmd in commands:
        if cmd.name in ("menu", "context", "history", "settings"):
            continue
        if cmd.name not in seen_handlers:
            seen_handlers.add(cmd.name)
            menu_commands.append(cmd)

    items: list[SelectItem] = [
        SelectItem(
            id=cmd.name,
            title=f"/{cmd.name}",
            category=cmd.category,
            description=f"{cmd.description}  [dim white]({cmd.usage})[/dim white]",
            badge=f"[{cmd.category}]",
        )
        for cmd in menu_commands
    ]

    selected = run_interactive_selector(
        ctx.console,
        title="SetuCode Command Palette",
        items=items,
        footer_hint="↑ ↓ Navigate  │  Type to search  │  Enter Select & Run  │  Esc Close",
    )

    if not selected:
        ctx.console.print(" [dim]Closed command palette.[/dim]\n")
        return True

    cmd = router.get_command(selected.id)
    if cmd:
        return cmd.handler(ctx, "")
    return True


# ── Command Handlers ─────────────────────────────────────────────────────────

def handle_model(ctx: CommandContext, args: str) -> bool:
    """Handle /model — interactive searchable model selector or direct model assignment."""
    # 1. Direct assignment: e.g. /model gpt-4o
    if args:
        target_model = args.strip()
        ctx.provider.set_model(target_model)
        ctx.settings.update_model(target_model, persist=True)
        ctx.console.print(f" [ok]✓[/ok] Model changed to [bold cyan]{target_model}[/bold cyan]\n")
        return True

    # 2. Interactive discovery and selection
    provider_name = getattr(ctx.provider, "provider_name", ctx.settings.provider)
    ctx.console.print(f" [dim]Fetching available models from {provider_name}...[/dim]")
    models, warning_or_error = ctx.provider.get_available_models()

    if warning_or_error:
        ctx.console.print(f" [warn]Notice:[/warn] {warning_or_error}")

    current_model = getattr(ctx.provider, "model", ctx.settings.model)

    # Convert to SelectItems with category for provider
    items: list[SelectItem] = []
    for m in (models or []):
        badge = "● active" if m.id == current_model else (f"[{m.provider}]" if m.provider else "")
        items.append(
            SelectItem(
                id=m.id,
                title=m.name or m.id,
                description=m.description or (f"Provider: {m.provider}" if m.provider else ""),
                badge=badge,
                is_current=(m.id == current_model),
                category=m.provider or provider_name,
            )
        )

    # Option for manual custom model entry
    items.append(
        SelectItem(
            id="__custom_model__",
            title="[+ Enter Custom Model Name]",
            description="Type any custom fine-tuned or local model identifier",
            badge="[custom]",
            category="custom",
        )
    )

    selected = run_interactive_selector(
        ctx.console,
        title=f"Select Model ({provider_name})",
        items=items,
        current_id=current_model,
        footer_hint="↑ ↓ Navigate  │  Type to search  │  Enter Select  │  Esc Cancel",
    )

    if selected is None:
        ctx.console.print(f" [dim]Cancelled. Active model remains {current_model}.[/dim]\n")
        return True

    if selected.id == "__custom_model__":
        ctx.console.print("\n [bold cyan]Enter custom model name:[/bold cyan] ", end="")
        try:
            custom_name = input().strip()
        except (EOFError, KeyboardInterrupt):
            ctx.console.print()
            return True

        if custom_name:
            ctx.provider.set_model(custom_name)
            ctx.settings.update_model(custom_name, persist=True)
            ctx.console.print(f" [ok]✓[/ok] Model changed to [bold cyan]{custom_name}[/bold cyan]\n")
        return True

    if selected.id != current_model:
        ctx.provider.set_model(selected.id)
        ctx.settings.update_model(selected.id, persist=True)
        ctx.console.print(f" [ok]✓[/ok] Model changed to [bold cyan]{selected.id}[/bold cyan]\n")
    else:
        ctx.console.print(f" [dim]Model unchanged ({current_model}).[/dim]\n")

    return True


def _dispatch_skill(ctx: CommandContext, skill: Any, args: str) -> bool:
    """Execute a skill directly as an on-demand slash command."""
    import time
    from app.agent.loop import run as agent_run
    from dashboard.keyboard import is_interactive

    # Register any tools attached to this skill
    if getattr(skill, "tools", None):
        for tool in skill.tools:
            ctx.registry.register(tool)

    # Inject skill instructions into system prompt
    hint = skill.to_system_hint()
    if not any(m.get("content") == hint for m in ctx.state.messages):
        ctx.state.messages.append({"role": "system", "content": hint})

    user_task = args.strip()
    if not user_task:
        ctx.console.print()
        lines = [
            Text.from_markup(f"[bold cyan]Skill:[/bold cyan] [bold white]{skill.name}[/bold white]\n"),
            Text.from_markup(f"[cyan]Description:[/cyan] {skill.description or 'None'}\n"),
        ]
        if skill.instructions:
            preview = skill.instructions.strip().splitlines()
            snippet = "\n".join(preview[:6]) + ("\n..." if len(preview) > 6 else "")
            lines.append(Text.from_markup(f"[cyan]Instructions Preview:[/cyan]\n[dim]{snippet}[/dim]\n"))

        ctx.console.print(Panel(Group(*lines), title=f"[bold cyan]Skill: {skill.name}[/bold cyan]", border_style="cyan", padding=(1, 2), expand=False))
        if is_interactive():
            try:
                ctx.console.print(f"  [bold cyan]Enter task for {skill.name}[/bold cyan] [dim](or press Enter to run general instructions)[/dim]:\n  [bold cyan]❯[/bold cyan] ", end="")
                user_task = input().strip()
            except (EOFError, KeyboardInterrupt, Exception):
                user_task = ""

        if not user_task:
            user_task = f"Execute instructions from skill '{skill.name}'."

    ctx.console.print(f"  [bold cyan]● Running skill:[/bold cyan] [bold white]{skill.name}[/bold white]\n")

    start_time = time.perf_counter()
    result = agent_run(ctx.state, user_task, ctx.bus, ctx.registry, ctx.permissions)
    elapsed = time.perf_counter() - start_time

    from dashboard.app import _print_response
    active_model = getattr(ctx.provider, "model", ctx.settings.model)
    _print_response(result, elapsed_seconds=elapsed, model_name=active_model)
    return True


def handle_skills(ctx: CommandContext, args: str) -> bool:
    """Handle /skills — browse discovered skills and run them directly."""
    skill_reg: SkillRegistry = get_default_skill_registry(ctx.state.workspace)
    skill_reg.refresh()

    if args.strip():
        target = args.strip().lstrip("/")
        skill = skill_reg.get(target) or skill_reg.get(target.replace("_", "-"))
        if skill:
            return _dispatch_skill(ctx, skill, "")
        ctx.console.print(f" [err]Skill '{args.strip()}' not found.[/err]\n")
        return True

    all_skills = skill_reg.list_all()
    if not all_skills:
        ctx.console.print(" [dim]No skills discovered. Create one with /skills create[/dim]\n")
        return True

    items: list[SelectItem] = [
        SelectItem(
            id=s.name,
            title=f"/{s.name}",
            description=s.description or "No description provided.",
            badge="[skill]",
            category="skill",
        )
        for s in all_skills
    ]

    items.append(
        SelectItem(
            id="__create_skill__",
            title="[+ Create New Custom Skill]",
            description="Create a new skill template in .agents/skills/<name>/SKILL.md",
            badge="[create]",
            category="action",
        )
    )

    selected = run_interactive_selector(
        ctx.console,
        title=f"Skills Browser ({len(all_skills)} available) — Select to Run",
        items=items,
        footer_hint="↑ ↓ Navigate  │  Type to search  │  Enter Run Skill  │  Esc Close",
    )

    if selected is None:
        ctx.console.print(" [dim]Closed skills browser.[/dim]\n")
        return True

    if selected.id == "__create_skill__":
        _create_skill_flow(ctx, skill_reg)
        return True

    skill = skill_reg.get(selected.id)
    if skill:
        return _dispatch_skill(ctx, skill, "")
    return True


def _create_skill_flow(ctx: CommandContext, reg: SkillRegistry) -> None:
    """Prompt user to create a new custom skill folder and SKILL.md."""
    ctx.console.print("\n[bold cyan]Create New Skill[/bold cyan]")
    try:
        ctx.console.print("  Skill Name (e.g. fast-api-expert): ", end="")
        name = input().strip().lower().replace(" ", "-")
        if not name:
            ctx.console.print(" [dim]Cancelled skill creation.[/dim]\n")
            return

        ctx.console.print("  Short Description: ", end="")
        desc = input().strip() or f"Specialized instructions for {name}"

        ctx.console.print("  Trigger Keywords (comma separated, e.g. api, fastapi, endpoint): ", end="")
        triggers = input().strip()
        trigger_list = [t.strip() for t in triggers.split(",") if t.strip()]

        skill_dir = Path(".agents/skills") / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"

        yaml_triggers = "\n".join(f"  - {t}" for t in trigger_list) if trigger_list else "  - " + name
        content = f"""---
name: {name}
description: {desc}
activation_conditions:
{yaml_triggers}
---

## Overview
{desc}

## Instructions
1. Follow domain best practices when working with {name}.
2. Always verify implementation with tests.

## Examples
- Use when refactoring or creating {name} components.
"""
        skill_md.write_text(content, encoding="utf-8")
        reg.refresh()
        ctx.console.print(f" [ok]✓[/ok] Created skill [bold cyan]{name}[/bold cyan] at [dim]{skill_md}[/dim]\n")
    except (EOFError, KeyboardInterrupt):
        ctx.console.print("\n [dim]Cancelled.[/dim]\n")


def handle_plan(ctx: CommandContext, args: str) -> bool:
    """Handle /plan — interactive task plan manager with status toggles and task adder."""
    from app.plan.manager import PlanManager
    from app.plan.model import Plan, Task

    plan = getattr(ctx.state, "plan", None)
    if plan is None:
        plan = PlanManager.load_plan(ctx.state.workspace)
        if plan:
            ctx.state.plan = plan

    # If direct markdown render was requested via non-interactive mode or /plan view
    if args.strip() == "view" or not is_interactive():
        if plan and plan.tasks:
            ctx.console.print()
            ctx.console.print(Markdown(plan.render()))
            ctx.console.print()
        else:
            ctx.console.print(" [dim]No active plan defined.[/dim]\n")
        return True

    # If no plan exists, offer interactive creation
    if not plan or not plan.tasks:
        ctx.console.print()
        ctx.console.print(Panel(
            " [dim]No active task plan currently defined.[/dim]\n\n"
            "  [bold]1[/bold] Create a new step-by-step plan\n"
            "  [bold]2[/bold] Back to chat",
            title="[bold cyan]Task Plan[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))
        try:
            choice = input("  Select (1-2) or press Enter to return: ").strip()
            if choice == "1":
                ctx.console.print("  Enter task steps (one per line, empty line to finish):")
                tasks = []
                while True:
                    step = input(f"    Step {len(tasks)+1}: ").strip()
                    if not step:
                        break
                    tasks.append(step)
                if tasks:
                    new_plan = Plan()
                    for idx, t in enumerate(tasks):
                        st = "in_progress" if idx == 0 else "pending"
                        new_plan.add_task(t, status=st)
                    ctx.state.plan = new_plan
                    PlanManager.save_plan(ctx.state.workspace, new_plan)
                    ctx.console.print(f" [ok]✓[/ok] Created plan with {len(tasks)} tasks.\n")
                    plan = new_plan
            else:
                return True
        except (EOFError, KeyboardInterrupt):
            ctx.console.print()
            return True

    if not plan or not plan.tasks:
        return True

    # Interactive plan management loop
    while True:
        total = len(plan.tasks)
        completed = sum(1 for t in plan.tasks if t.status == "completed")
        pct = int((completed / total) * 100) if total > 0 else 0

        # Build visual progress bar
        bar_len = 20
        filled = int((completed / total) * bar_len) if total > 0 else 0
        prog_bar = f"[{'█' * filled}{'░' * (bar_len - filled)}] {pct}% ({completed}/{total} completed)"

        items: list[SelectItem] = []
        for t in plan.tasks:
            icon = {"pending": "○", "in_progress": "▶", "completed": "✓", "blocked": "✗"}.get(t.status, "○")
            badge = f"[{t.status}]"
            items.append(
                SelectItem(
                    id=str(t.id),
                    title=f"{icon} #{t.id} {t.description}",
                    description=f"Status: {t.status}" + (f" │ Notes: {t.notes}" if t.notes else ""),
                    badge=badge,
                    category=t.status,
                )
            )

        items.append(SelectItem(id="__add_task__", title="[+ Add New Task]", description="Add a new task step to the plan", badge="[action]"))
        items.append(SelectItem(id="__clear_done__", title="[✓ Clear Completed Tasks]", description="Remove all finished tasks from plan", badge="[action]"))
        items.append(SelectItem(id="__reset_plan__", title="[✗ Reset Entire Plan]", description="Delete current plan and start fresh", badge="[action]"))

        selected = run_interactive_selector(
            ctx.console,
            title=f"Task Plan — {prog_bar}",
            items=items,
            footer_hint="↑ ↓ Navigate  │  Enter Toggle Status / Action  │  Esc Return to Chat",
        )

        if not selected:
            break

        if selected.id == "__add_task__":
            ctx.console.print("  [bold cyan]New task description:[/bold cyan] ", end="")
            try:
                desc = input().strip()
                if desc:
                    plan.add_task(desc)
                    PlanManager.save_plan(ctx.state.workspace, plan)
                    ctx.console.print(f" [ok]✓[/ok] Added task: {desc}\n")
            except (EOFError, KeyboardInterrupt):
                ctx.console.print()
            continue

        if selected.id == "__clear_done__":
            plan.tasks = [t for t in plan.tasks if t.status != "completed"]
            PlanManager.save_plan(ctx.state.workspace, plan)
            ctx.console.print(" [ok]✓[/ok] Cleared completed tasks.\n")
            if not plan.tasks:
                break
            continue

        if selected.id == "__reset_plan__":
            ctx.state.plan = None
            PlanManager.delete_plan(ctx.state.workspace)
            ctx.console.print(" [ok]✓[/ok] Task plan reset.\n")
            break

        # Toggle status of selected task
        task_id = int(selected.id)
        task = plan.get_task(task_id)
        if task:
            next_status = {
                "pending": "in_progress",
                "in_progress": "completed",
                "completed": "blocked",
                "blocked": "pending",
            }.get(task.status, "pending")
            task.status = next_status
            PlanManager.save_plan(ctx.state.workspace, plan)

    return True


def handle_tools(ctx: CommandContext, args: str) -> bool:
    """Handle /tools — interactive tool registry inspector."""
    tools = ctx.registry.all_tools()
    if not tools:
        ctx.console.print(" [dim]No tools currently registered.[/dim]\n")
        return True

    items: list[SelectItem] = []
    for t in tools:
        items.append(
            SelectItem(
                id=t.name,
                title=t.name,
                description=t.description,
                badge=f"[{t.permission_category}]",
                category=t.permission_category,
            )
        )

    selected = run_interactive_selector(
        ctx.console,
        title=f"Tool Registry ({len(tools)} tools)",
        items=items,
        footer_hint="↑ ↓ Navigate  │  Type to search  │  Enter Inspect Schema  │  Esc Close",
    )

    if not selected:
        ctx.console.print(" [dim]Closed tool inspector.[/dim]\n")
        return True

    tool = ctx.registry.get(selected.id)
    if tool:
        schema_json = json.dumps(tool.input_schema, indent=2)
        panel = Panel(
            Group(
                Text.from_markup(f"[bold white]{tool.name}[/bold white] — [bold magenta]{tool.permission_category}[/bold magenta]\n"),
                Text.from_markup(f"[cyan]Description:[/cyan] {tool.description}\n"),
                Text.from_markup("[cyan]Input Schema:[/cyan]"),
                Text(schema_json, style="dim white"),
            ),
            title=f"[bold cyan]Tool: {tool.name}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
        ctx.console.print()
        ctx.console.print(panel)
        ctx.console.print()

    return True


def handle_memory(ctx: CommandContext, args: str) -> bool:
    """Handle /memory — inspect and manage user preferences (USER.md) and project memory (AGENTS.md)."""
    from app.memory.manager import MemoryManager

    mem = MemoryManager(ctx.settings.user_memory_path)
    user_mem = mem.load_user_memory()
    proj_mem = mem.load_project_memory(ctx.state.workspace)

    items = [
        SelectItem(id="view_user", title="View / Edit User Preferences", description=f"Stored at {ctx.settings.user_memory_path}", badge="[USER.md]"),
        SelectItem(id="view_proj", title="View Project Context & Memory", description=f"Stored at {ctx.state.workspace / 'AGENTS.md'}", badge="[AGENTS.md]"),
        SelectItem(id="add_pref", title="Add New Coding Preference", description="Append a new persistent rule to USER.md", badge="[+ Add]"),
    ]

    selected = run_interactive_selector(
        ctx.console,
        title="Agent Memory Manager",
        items=items,
        footer_hint="↑ ↓ Navigate  │  Enter Select  │  Esc Close",
    )

    if not selected:
        ctx.console.print(" [dim]Closed memory manager.[/dim]\n")
        return True

    if selected.id == "view_user":
        content = user_mem.strip() or "(No preferences saved yet. The agent learns preferences automatically at session end.)"
        ctx.console.print()
        ctx.console.print(Panel(Markdown(content), title=f"[bold cyan]User Preferences ({ctx.settings.user_memory_path})[/bold cyan]", border_style="cyan", padding=(1, 2)))
        ctx.console.print()

    elif selected.id == "view_proj":
        content = proj_mem.strip() or "(No AGENTS.md found in workspace root. Create AGENTS.md to define project-specific conventions.)"
        ctx.console.print()
        ctx.console.print(Panel(Markdown(content), title="[bold cyan]Project Context (AGENTS.md)[/bold cyan]", border_style="cyan", padding=(1, 2)))
        ctx.console.print()

    elif selected.id == "add_pref":
        ctx.console.print("\n  [bold cyan]Enter preference (e.g. Always write type annotations):[/bold cyan] ", end="")
        try:
            pref = input().strip()
            if pref:
                bullet = f"- {pref.lstrip('- ')}"
                ctx.settings.user_memory_path.parent.mkdir(parents=True, exist_ok=True)
                with ctx.settings.user_memory_path.open("a", encoding="utf-8") as f:
                    f.write(f"\n{bullet}\n")
                ctx.state.user_memory = mem.load_user_memory()
                ctx.console.print(f" [ok]✓[/ok] Added preference to [dim]{ctx.settings.user_memory_path}[/dim]\n")
        except (EOFError, KeyboardInterrupt):
            ctx.console.print()

    return True


def handle_config(ctx: CommandContext, args: str) -> bool:
    """Handle /config or /settings — view and edit runtime configuration."""
    provider_name = getattr(ctx.provider, "provider_name", ctx.settings.provider)
    current_model = getattr(ctx.provider, "model", ctx.settings.model)

    items = [
        SelectItem(id="model", title=f"Change Active Model ({current_model})", description="Switch active LLM model with discovery or custom name", badge="[Model]"),
        SelectItem(id="provider", title=f"Switch LLM Provider ({provider_name})", description="Switch between Claude, OpenAI, Gemini, Ollama, OpenRouter", badge="[Provider]"),
        SelectItem(id="endpoint", title="Configure Custom API Endpoint", description="Set or change OpenAI / Anthropic / Gemini base URL", badge="[Endpoint]"),
        SelectItem(id="workspace", title=f"Change Workspace Root ({ctx.state.workspace})", description="Point SetuCode to another workspace directory", badge="[Workspace]"),
    ]

    selected = run_interactive_selector(
        ctx.console,
        title="SetuCode Configuration",
        items=items,
        footer_hint="↑ ↓ Navigate  │  Enter Edit  │  Esc Close",
    )

    if not selected:
        ctx.console.print(" [dim]Closed settings.[/dim]\n")
        return True

    if selected.id == "model":
        return handle_model(ctx, "")

    if selected.id == "provider":
        prov_items = [
            SelectItem(id="claude", title="Claude (Anthropic)", description="Official Claude 3.5 Sonnet / 3.7 Sonnet / Haiku"),
            SelectItem(id="openai", title="OpenAI (Official)", description="GPT-4o, o1, o3-mini, GPT-4.5"),
            SelectItem(id="gemini", title="Gemini (Google)", description="Gemini 2.5 Flash, 2.5 Pro, 2.0 Flash"),
            SelectItem(id="ollama", title="Ollama / Local LLM", description="Local models at http://localhost:11434/v1"),
            SelectItem(id="openrouter", title="OpenRouter", description="OpenRouter multi-model gateway at https://openrouter.ai/api/v1"),
        ]
        sel_prov = run_interactive_selector(ctx.console, title="Select Provider", items=prov_items)
        if sel_prov:
            ctx.settings.provider = "openai" if sel_prov.id in ("ollama", "openrouter") else sel_prov.id
            if sel_prov.id == "ollama" and not ctx.settings.openai_base_url:
                ctx.settings.openai_base_url = "http://localhost:11434/v1"
            elif sel_prov.id == "openrouter" and not ctx.settings.openai_base_url:
                ctx.settings.openai_base_url = "https://openrouter.ai/api/v1"

            from app.providers import build_provider
            try:
                new_prov = build_provider(ctx.settings)
                ctx.provider = new_prov
                ctx.state.model = new_prov
                persist_selected_model(ctx.settings.model)
                ctx.console.print(f" [ok]✓[/ok] Switched provider to [bold cyan]{sel_prov.title}[/bold cyan]\n")
            except Exception as e:
                ctx.console.print(f" [err]Failed to initialize provider: {e}[/err]\n")

    elif selected.id == "endpoint":
        ctx.console.print("\n  Enter Custom Base URL (leave empty to use official API): ", end="")
        try:
            ep = input().strip()
            if ctx.settings.provider == "claude":
                ctx.settings.anthropic_base_url = ep
            elif ctx.settings.provider == "gemini":
                ctx.settings.gemini_base_url = ep
            else:
                ctx.settings.openai_base_url = ep

            from app.providers import build_provider
            new_prov = build_provider(ctx.settings)
            ctx.provider = new_prov
            ctx.state.model = new_prov
            ctx.console.print(f" [ok]✓[/ok] Updated endpoint to: [bold cyan]{ep or 'Official API'}[/bold cyan]\n")
        except (EOFError, KeyboardInterrupt):
            ctx.console.print()

    elif selected.id == "workspace":
        ctx.console.print(f"\n  Current workspace: {ctx.state.workspace}")
        ctx.console.print("  Enter new workspace path: ", end="")
        try:
            new_ws = input().strip()
            if new_ws:
                p = Path(new_ws).resolve()
                p.mkdir(parents=True, exist_ok=True)
                ctx.state.workspace = p
                ctx.settings.workspace_root = p
                ctx.registry = ToolRegistry()
                from app.tools.registry import build_default_registry
                ctx.registry = build_default_registry(p)
                ctx.console.print(f" [ok]✓[/ok] Workspace changed to: [bold cyan]{p}[/bold cyan]\n")
        except (EOFError, KeyboardInterrupt):
            ctx.console.print()

    return True


def handle_compact(ctx: CommandContext, args: str) -> bool:
    """Handle /compact or /context — view token usage and compact history."""
    from app.context.prefix_cache import PrefixCache
    from app.context.budget import estimate_tokens

    metrics = PrefixCache.get_metrics()
    current_tokens = estimate_tokens(ctx.state.messages)
    compaction_limit = 80_000

    pct = min(100, int((current_tokens / compaction_limit) * 100))
    bar_len = 24
    filled = min(bar_len, int((current_tokens / compaction_limit) * bar_len))
    bar_str = f"[{'█' * filled}{'░' * (bar_len - filled)}] {pct}% of auto-compaction limit"

    table = Table(box=None, padding=(0, 2), show_header=False)
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Context Usage", bar_str)
    table.add_row("Estimated Tokens", f"{current_tokens:,} / {compaction_limit:,} tokens")
    table.add_row("Messages in Context", str(len(ctx.state.messages)))
    table.add_row("Cached Tokens Used", f"[bold green]{metrics.cached_tokens:,}[/bold green]")
    table.add_row("Uncached Tokens", f"[bold yellow]{metrics.uncached_tokens:,}[/bold yellow]")

    panel = Panel(
        table,
        title="[bold cyan]Context & Token Usage[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    ctx.console.print()
    ctx.console.print(panel)

    if args.strip() == "now" and ctx.state.context_manager:
        ctx.console.print("\n [dim]Compacting conversation history...[/dim]")
        before_len = len(ctx.state.messages)
        ctx.state.context_manager.check_and_compact(ctx.state)
        after_len = len(ctx.state.messages)
        ctx.console.print(f"  [ok]✓[/ok] Messages reduced from {before_len} to [bold white]{after_len}[/bold white]\n")
    else:
        ctx.console.print("\n  [dim]Tip: Use '/compact now' to manually trigger context compaction.[/dim]\n")

    return True


def handle_export(ctx: CommandContext, args: str) -> bool:
    """Handle /export or /history — export chat transcript to markdown."""
    messages = ctx.state.messages
    if not messages:
        ctx.console.print(" [dim]No messages in current session history.[/dim]\n")
        return True

    target_file = Path("setucode-transcript.md")
    if args:
        target_file = Path(args.strip())

    lines = [
        f"# SetuCode Session Transcript",
        f"- Session ID: `{ctx.state.session_id}`",
        f"- Model: `{getattr(ctx.provider, 'model', ctx.settings.model)}`",
        f"- Messages: {len(messages)}",
        "",
        "---",
        "",
    ]

    for m in messages:
        role = m.get("role", "unknown").upper()
        content = m.get("content", "")
        if role == "SYSTEM" and not args:
            continue
        lines.append(f"### {role}")
        if content:
            lines.append(str(content))
        if m.get("tool_calls"):
            for tc in m["tool_calls"]:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                args_dict = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                lines.append(f"```json\n// Tool Call: {name}\n{json.dumps(args_dict, indent=2)}\n```")
        lines.append("")

    try:
        target_file.write_text("\n".join(lines), encoding="utf-8")
        ctx.console.print(f" [ok]✓[/ok] Transcript exported to [bold cyan]{target_file}[/bold cyan]\n")
    except Exception as e:
        ctx.console.print(f" [err]Failed to export transcript: {e}[/err]\n")

    return True


def handle_status(ctx: CommandContext, args: str) -> bool:
    """Handle /status — display agent status, model, endpoints, git info, and metrics."""
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
    skills_active = len(skill_reg._active_skills)

    # Git branch detection
    git_info = "Not a git repo"
    try:
        import subprocess
        git_res = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=str(ctx.state.workspace), timeout=2)
        if git_res.returncode == 0:
            git_info = f"branch [bold green]{git_res.stdout.strip()}[/bold green]"
    except Exception:
        pass

    table.add_row("Provider", provider_name)
    table.add_row("Active Model", current_model)
    table.add_row("Endpoint", endpoint)
    table.add_row("Workspace", str(ctx.state.workspace))
    table.add_row("Git Status", git_info)
    table.add_row("Registered Tools", str(tools_count))
    table.add_row("Skills Discovered", f"{skills_total} ({skills_active} active)")

    plan = getattr(ctx.state, "plan", None)
    if plan and plan.tasks:
        completed = sum(1 for t in plan.tasks if t.status == "completed")
        table.add_row("Active Plan", f"{completed}/{len(plan.tasks)} tasks completed")
    else:
        table.add_row("Active Plan", "None")

    table.add_row("Session ID", ctx.state.session_id)

    panel = Panel(
        table,
        title="[bold cyan]Agent Status Dashboard[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    ctx.console.print()
    ctx.console.print(panel)
    ctx.console.print()
    return True


def handle_help(ctx: CommandContext, args: str) -> bool:
    """Handle /help — display available slash commands in a clean categorized TUI panel."""
    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Category", style="dim magenta")
    table.add_column("Usage", style="dim white")
    table.add_column("Description", style="white")

    router = build_default_command_router()
    commands = router.list_commands()

    # Filter out hidden aliases
    seen = set()
    for cmd in commands:
        if cmd.name in ("menu", "context", "history", "settings") or cmd.name in seen:
            continue
        seen.add(cmd.name)
        table.add_row(f"/{cmd.name}", cmd.category, cmd.usage, cmd.description)

    panel = Panel(
        table,
        title="[bold cyan]SetuCode Slash Commands[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    ctx.console.print()
    ctx.console.print(panel)
    ctx.console.print("  [dim]Tip: Type '/' or hit Tab anytime to open the interactive Command Palette.[/dim]\n")
    return True


def handle_clear(ctx: CommandContext, args: str) -> bool:
    """Handle /clear — clear terminal screen and (optionally) history."""
    if args.strip() == "all":
        ctx.state.messages.clear()
        ctx.console.print(" [dim]Conversation history and screen cleared.[/dim]\n")
    else:
        ctx.console.print(" [dim]Screen cleared. Use '/clear all' to clear history.[/dim]\n")
    os.system("cls" if os.name == "nt" else "clear")
    return True


def handle_exit(ctx: CommandContext, args: str) -> bool:
    """Handle /exit or /quit — gracefully exit SetuCode."""
    ctx.console.print(" [dim]Goodbye.[/dim]\n")
    return False


def build_default_command_router() -> CommandRouter:
    """Build and register all default TUI slash commands with categories."""
    router = CommandRouter()
    router.register(
        Command(
            name="menu",
            description="Open interactive command palette",
            usage="/menu or /",
            category="Core",
            handler=handle_menu,
        )
    )
    router.register(
        Command(
            name="model",
            description="Select or change active LLM model",
            usage="/model [name]",
            category="Model",
            handler=handle_model,
        )
    )
    router.register(
        Command(
            name="skills",
            description="Interactive skill browser & manager",
            usage="/skills",
            category="Skills",
            handler=handle_skills,
        )
    )
    router.register(
        Command(
            name="plan",
            description="Interactive task plan and TODO status",
            usage="/plan",
            category="Agent",
            handler=handle_plan,
        )
    )
    router.register(
        Command(
            name="tools",
            description="Inspect registered tools & schemas",
            usage="/tools",
            category="Tools",
            handler=handle_tools,
        )
    )
    router.register(
        Command(
            name="memory",
            description="Inspect & edit user preferences (USER.md)",
            usage="/memory",
            category="Memory",
            handler=handle_memory,
        )
    )
    router.register(
        Command(
            name="config",
            description="Live provider, model & endpoint settings",
            usage="/config",
            category="Settings",
            handler=handle_config,
        )
    )
    router.register(
        Command(
            name="settings",
            description="Alias for /config",
            usage="/settings",
            category="Settings",
            handler=handle_config,
        )
    )
    router.register(
        Command(
            name="status",
            description="Show agent runtime status and metrics",
            usage="/status",
            category="Status",
            handler=handle_status,
        )
    )
    router.register(
        Command(
            name="compact",
            description="View token budget or compact context",
            usage="/compact [now]",
            category="Context",
            handler=handle_compact,
        )
    )
    router.register(
        Command(
            name="context",
            description="Alias for /compact",
            usage="/context",
            category="Context",
            handler=handle_compact,
        )
    )
    router.register(
        Command(
            name="export",
            description="Export session transcript to Markdown",
            usage="/export [filename.md]",
            category="History",
            handler=handle_export,
        )
    )
    router.register(
        Command(
            name="history",
            description="Alias for /export",
            usage="/history",
            category="History",
            handler=handle_export,
        )
    )
    router.register(
        Command(
            name="clear",
            description="Clear screen ('/clear all' for history)",
            usage="/clear [all]",
            category="Core",
            handler=handle_clear,
        )
    )
    router.register(
        Command(
            name="help",
            description="Show available commands",
            usage="/help",
            category="Core",
            handler=handle_help,
        )
    )
    router.register(
        Command(
            name="exit",
            description="Exit SetuCode",
            usage="/exit",
            category="Core",
            handler=handle_exit,
        )
    )
    return router
