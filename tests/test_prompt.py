"""Unit tests for interactive prompt, autocomplete popup, and key handling."""
from __future__ import annotations

from pathlib import Path
from rich.console import Console

from dashboard.keyboard import set_mock_keys, clear_mock_keys
from dashboard.prompt import get_all_suggestions, prompt_interactive


def test_get_all_suggestions(tmp_path: Path):
    suggestions = get_all_suggestions(str(tmp_path))
    names = [s.name for s in suggestions]
    assert "model" in names
    assert "skills" in names
    assert "plan" in names
    assert "config" in names
    assert "help" in names
    assert "exit" in names


def test_prompt_interactive_regular_input():
    console = Console(record=True, width=100)
    # Simulate typing 'hello' then ENTER
    set_mock_keys(["h", "e", "l", "l", "o", "ENTER"])
    try:
        result = prompt_interactive(console)
        assert result == "hello"
    finally:
        clear_mock_keys()


def test_prompt_interactive_tab_completion():
    console = Console(record=True, width=100)
    # Simulate typing '/' then TAB (completes first suggestion, e.g. '/model ') then ENTER
    set_mock_keys(["/", "TAB", "ENTER"])
    try:
        result = prompt_interactive(console)
        assert result.startswith("/model")
    finally:
        clear_mock_keys()


def test_prompt_interactive_filter_and_tab():
    console = Console(record=True, width=100)
    # Simulate typing '/pl' then TAB (completes '/plan ') then ENTER
    set_mock_keys(["/", "p", "l", "TAB", "ENTER"])
    try:
        result = prompt_interactive(console)
        assert result == "/plan" or result == "/plan "
    finally:
        clear_mock_keys()


def test_prompt_interactive_ctrl_c():
    console = Console(record=True, width=100)
    # Simulate CTRL_C on empty buffer -> returns /exit
    set_mock_keys(["CTRL_C"])
    try:
        result = prompt_interactive(console)
        assert result == "/exit"
    finally:
        clear_mock_keys()
