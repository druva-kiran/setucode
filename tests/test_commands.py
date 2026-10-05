"""Unit tests for TUI Slash Command Architecture, /model, /skills, /help, and /status."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from rich.console import Console

from app.agent.state import AgentState
from app.config.settings import Settings
from app.events.bus import EventBus
from app.permissions.manager import PermissionManager
from app.providers.base import BaseProvider, ModelInfo, ModelResponse
from app.skills.model import Skill
from app.skills.registry import SkillRegistry
from app.tools.registry import ToolRegistry
from dashboard.commands import (
    CommandContext,
    build_default_command_router,
)
from dashboard.keyboard import set_mock_keys, clear_mock_keys


class DummyProvider(BaseProvider):
    def __init__(self, model: str = "test-model-1") -> None:
        self.model = model
        self._model = model
        self.provider_name = "dummy"

    def generate(self, messages, tools) -> ModelResponse:
        return ModelResponse(final_text=f"Generated with {self.model}")

    def list_models(self) -> list[ModelInfo]:
        return [
            ModelInfo(id="test-model-1", name="Test Model 1", provider="dummy"),
            ModelInfo(id="test-model-2", name="Test Model 2", provider="dummy"),
            ModelInfo(id="test-model-3", name="Test Model 3", provider="dummy"),
        ]


@pytest.fixture
def cmd_context(tmp_path: Path):
    console = Console(record=True, width=100)
    provider = DummyProvider("test-model-1")
    settings = Settings(provider="dummy", model="test-model-1", workspace_root=tmp_path)
    registry = ToolRegistry()
    perms = MagicMock(spec=PermissionManager)
    bus = EventBus()
    state = AgentState(
        session_id="session-123",
        workspace=tmp_path,
        model=provider,
        available_tools=[],
    )
    return CommandContext(
        console=console,
        state=state,
        settings=settings,
        provider=provider,
        registry=registry,
        permissions=perms,
        bus=bus,
    )


def test_command_router_detection():
    """CommandRouter accurately distinguishes slash commands from normal user messages."""
    router = build_default_command_router()
    assert router.is_command("/model") is True
    assert router.is_command("/skills") is True
    assert router.is_command("/help") is True
    assert router.is_command("hello agent please help me") is False
    assert router.is_command("write a python function") is False


def test_command_direct_model_switch(cmd_context: CommandContext, tmp_path: Path):
    """/model <name> directly switches active model and updates runtime state and settings."""
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=test-model-1\n", encoding="utf-8")

    with patch("app.config.settings.persist_selected_model") as mock_persist:
        router = build_default_command_router()
        cont = router.dispatch("/model test-model-2", cmd_context)
        assert cont is True
        assert cmd_context.provider.model == "test-model-2"
        assert cmd_context.settings.model == "test-model-2"
        mock_persist.assert_called_with("test-model-2", Path(".env"))


def test_interactive_model_selection_with_arrow_keys(cmd_context: CommandContext):
    """Interactive /model selects second item when DOWN + ENTER are pressed."""
    router = build_default_command_router()

    # Cursor starts on test-model-1 (index 0). DOWN moves to test-model-2 (index 1). ENTER selects.
    set_mock_keys(["DOWN", "ENTER"])
    try:
        cont = router.dispatch("/model", cmd_context)
        assert cont is True
        assert cmd_context.provider.model == "test-model-2"
        assert cmd_context.settings.model == "test-model-2"
    finally:
        clear_mock_keys()


def test_interactive_model_cancel_with_esc(cmd_context: CommandContext):
    """Interactive /model cancels when ESC is pressed; model remains unchanged."""
    router = build_default_command_router()
    set_mock_keys(["DOWN", "ESC"])
    try:
        cont = router.dispatch("/model", cmd_context)
        assert cont is True
        assert cmd_context.provider.model == "test-model-1"
        assert cmd_context.settings.model == "test-model-1"
    finally:
        clear_mock_keys()


def test_selected_model_is_used_by_subsequent_request(cmd_context: CommandContext):
    """Verify that after /model changes the model, agent loop uses the new model."""
    from app.agent.loop import run as agent_run

    router = build_default_command_router()
    router.dispatch("/model test-model-2", cmd_context)
    assert cmd_context.state.model.model == "test-model-2"

    res = agent_run(
        cmd_context.state,
        "What model are you?",
        cmd_context.bus,
        cmd_context.registry,
        cmd_context.permissions,
    )
    assert "test-model-2" in res


def test_help_command(cmd_context: CommandContext):
    """/help displays commands without sending to LLM."""
    router = build_default_command_router()
    cont = router.dispatch("/help", cmd_context)
    assert cont is True
    output = cmd_context.console.export_text()
    assert "/model" in output
    assert "/skills" in output
    assert "/status" in output


def test_status_command(cmd_context: CommandContext):
    """/status displays agent status panel."""
    router = build_default_command_router()
    cont = router.dispatch("/status", cmd_context)
    assert cont is True
    output = cmd_context.console.export_text()
    assert "Active Model" in output
    assert "test-model-1" in output


def test_exit_command(cmd_context: CommandContext):
    """/exit returns False to break REPL loop."""
    router = build_default_command_router()
    assert router.dispatch("/exit", cmd_context) is False
    assert router.dispatch("/quit", cmd_context) is False


def test_menu_command_palette(cmd_context: CommandContext):
    """/menu or bare '/' opens command palette and dispatches selected command."""
    router = build_default_command_router()
    # Select first command in palette and press ENTER
    set_mock_keys(["ENTER"])
    try:
        cont = router.dispatch("/menu", cmd_context)
        assert cont is True
        output = cmd_context.console.export_text()
        assert "Command Palette" in output or "Commands" in output or "Model" in output
    finally:
        clear_mock_keys()


def test_plan_interactive_status_toggle(cmd_context: CommandContext):
    """/plan opens interactive task manager and allows toggling task status."""
    from app.plan.model import Plan
    from app.plan.manager import PlanManager

    plan = Plan()
    plan.add_task("Write tests", status="pending")
    cmd_context.state.plan = plan
    PlanManager.save_plan(cmd_context.state.workspace, plan)

    # ENTER on first task (id=1) toggles status to 'in_progress', then ESC exits
    set_mock_keys(["ENTER", "ESC"])
    try:
        router = build_default_command_router()
        cont = router.dispatch("/plan", cmd_context)
        assert cont is True
        assert plan.get_task(1).status == "in_progress"
    finally:
        clear_mock_keys()


def test_skills_dispatch(cmd_context: CommandContext):
    """/skills allows browsing skills and direct /<skill-name> invocation."""
    from app.skills.manager import get_default_skill_registry

    reg = get_default_skill_registry(cmd_context.state.workspace)
    skill = Skill(
        name="test-skill",
        description="A test capability",
        instructions="Special instructions for test-skill",
    )
    reg.register_skill(skill)

    set_mock_keys(["ENTER"])
    try:
        router = build_default_command_router()
        cont = router.dispatch("/skills", cmd_context)
        assert cont is True

        # Test direct invocation by name with arguments
        cont2 = router.dispatch("/test-skill run my unit tests", cmd_context)
        assert cont2 is True
        # Check skill instructions got injected
        assert any("Special instructions for test-skill" in m.get("content", "") or "test-skill" in m.get("content", "") for m in cmd_context.state.messages)
    finally:
        clear_mock_keys()


def test_tools_interactive_inspector(cmd_context: CommandContext):
    """/tools displays registered tools and schemas."""
    from app.tools.registry import Tool
    from app.tools.base import ToolResult

    dummy_tool = Tool(
        name="dummy_tool",
        description="A test tool",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        execute=lambda args: ToolResult(output="ok"),
        permission_category="readonly",
    )
    cmd_context.registry.register(dummy_tool)

    set_mock_keys(["ENTER"])
    try:
        router = build_default_command_router()
        cont = router.dispatch("/tools", cmd_context)
        assert cont is True
        output = cmd_context.console.export_text()
        assert "dummy_tool" in output
    finally:
        clear_mock_keys()


def test_memory_interactive_manager(cmd_context: CommandContext, tmp_path: Path):
    """/memory displays preferences and project context."""
    user_md = tmp_path / "USER.md"
    user_md.write_text("- Prefer Python 3.12+\n", encoding="utf-8")
    cmd_context.settings.user_memory_path = user_md

    set_mock_keys(["ENTER"])  # Select "View / Edit User Preferences"
    try:
        router = build_default_command_router()
        cont = router.dispatch("/memory", cmd_context)
        assert cont is True
        output = cmd_context.console.export_text()
        assert "Prefer Python 3.12+" in output
    finally:
        clear_mock_keys()


def test_export_command(cmd_context: CommandContext, tmp_path: Path):
    """/export writes session transcript markdown to file."""
    cmd_context.state.messages.append({"role": "user", "content": "Hello SetuCode"})
    cmd_context.state.messages.append({"role": "assistant", "content": "Hello! How can I assist?"})

    export_path = tmp_path / "test-transcript.md"
    router = build_default_command_router()
    cont = router.dispatch(f"/export {export_path}", cmd_context)
    assert cont is True
    assert export_path.exists()
    content = export_path.read_text(encoding="utf-8")
    assert "Hello SetuCode" in content
    assert "Hello! How can I assist?" in content


def test_selector_search_filtering(cmd_context: CommandContext):
    """Interactive selector filters items in real-time when typing characters."""
    from dashboard.selector import SelectItem, run_interactive_selector

    items = [
        SelectItem(id="gpt4", title="GPT-4o", description="OpenAI model"),
        SelectItem(id="claude", title="Claude 3.5 Sonnet", description="Anthropic model"),
        SelectItem(id="gemini", title="Gemini 2.5 Flash", description="Google model"),
    ]

    # Type 'c', 'l', 'a' to filter down to Claude, then press ENTER
    set_mock_keys(["c", "l", "a", "ENTER"])
    try:
        chosen = run_interactive_selector(cmd_context.console, "Test Filter", items)
        assert chosen is not None
        assert chosen.id == "claude"
    finally:
        clear_mock_keys()

