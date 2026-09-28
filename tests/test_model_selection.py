"""Unit tests for model discovery, normalization, fallback, and state persistence."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app.config.settings import Settings, persist_selected_model
from app.providers.base import ModelInfo
from app.providers.openai import OpenAIProvider
from app.providers.anthropic import AnthropicProvider
from app.providers.gemini import GeminiProvider


def test_openai_model_discovery():
    """OpenAIProvider.list_models parses model list and filters chat models."""
    with patch("app.providers.openai.OpenAI"):
        provider = OpenAIProvider(api_key="sk-test", model="gpt-4o")

    # Mock response
    m1 = MagicMock()
    m1.id = "gpt-4o"
    m2 = MagicMock()
    m2.id = "gpt-4o-mini"
    m3 = MagicMock()
    m3.id = "text-embedding-3-small"  # non-chat model, should be filtered out
    m4 = MagicMock()
    m4.id = "o1-preview"

    mock_resp = MagicMock()
    mock_resp.data = [m1, m2, m3, m4]
    provider._client.models.list.return_value = mock_resp

    models = provider.list_models()
    ids = [m.id for m in models]
    assert "gpt-4o" in ids
    assert "gpt-4o-mini" in ids
    assert "o1-preview" in ids
    assert "text-embedding-3-small" not in ids


def test_anthropic_model_discovery():
    """AnthropicProvider.list_models parses available models from API."""
    with patch("anthropic.Anthropic"):
        provider = AnthropicProvider(api_key="sk-ant", model="claude-3-5-sonnet-20241022")

    m1 = MagicMock()
    m1.id = "claude-3-7-sonnet-20250219"
    m1.display_name = "Claude 3.7 Sonnet"
    m2 = MagicMock()
    m2.id = "claude-3-5-haiku-20241022"
    m2.display_name = "Claude 3.5 Haiku"

    mock_resp = MagicMock()
    mock_resp.data = [m1, m2]
    provider._client.models.list.return_value = mock_resp

    models = provider.list_models()
    ids = [m.id for m in models]
    assert "claude-3-7-sonnet-20250219" in ids
    assert "claude-3-5-haiku-20241022" in ids


def test_gemini_model_discovery():
    """GeminiProvider.list_models parses available Gemini generative models."""
    with patch("google.genai.Client"):
        provider = GeminiProvider(api_key="gem-test", model="gemini-2.5-flash")

    m1 = MagicMock()
    m1.name = "models/gemini-2.5-flash"
    m1.display_name = "Gemini 2.5 Flash"
    m1.description = "Fast model"

    m2 = MagicMock()
    m2.name = "models/embedding-001"  # non-gemini model, filtered
    m2.display_name = "Embedding"

    provider._client.models.list.return_value = [m1, m2]

    models = provider.list_models()
    ids = [m.id for m in models]
    assert "gemini-2.5-flash" in ids
    assert "embedding-001" not in ids


def test_discovery_failure_returns_fallback_without_crashing():
    """When API call raises an error, get_available_models returns fallback models and warning."""
    with patch("app.providers.openai.OpenAI"):
        provider = OpenAIProvider(api_key="sk-test", model="gpt-4o")

    provider._client.models.list.side_effect = Exception("401 Unauthorized API Key")

    models, err = provider.get_available_models()
    assert err is not None
    assert "401 Unauthorized" in err
    assert len(models) > 0
    # Fallback must contain gpt-4o
    assert any(m.id == "gpt-4o" for m in models)


def test_set_model_updates_provider_state():
    """Calling set_model updates both _model and model attributes."""
    with patch("app.providers.openai.OpenAI"):
        provider = OpenAIProvider(api_key="sk-test", model="gpt-4o")

    assert provider.model == "gpt-4o"
    provider.set_model("o3-mini")
    assert provider.model == "o3-mini"
    assert provider._model == "o3-mini"


def test_persist_selected_model_updates_env(tmp_path: Path):
    """persist_selected_model modifies LLM_MODEL in .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LLM_PROVIDER=openai\nLLM_MODEL=gpt-4o\nOPENAI_API_KEY=test\n",
        encoding="utf-8",
    )

    success = persist_selected_model("gpt-4o-mini", env_path=env_file)
    assert success is True
    content = env_file.read_text(encoding="utf-8")
    assert "LLM_MODEL=gpt-4o-mini" in content
    assert "LLM_MODEL=gpt-4o\n" not in content


def test_setup_wizard_does_not_ask_for_model_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Setup wizard does not ask user to manually type model name."""
    from dashboard.setup_wizard import run_setup_cli

    # Inputs: choice 4, default endpoint (Enter), empty key (Enter), default workspace (Enter)
    inputs = iter(["4", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda *args: next(inputs))
    monkeypatch.chdir(tmp_path)

    run_setup_cli()

    env_file = tmp_path / ".env"
    assert env_file.exists()
    content = env_file.read_text(encoding="utf-8")
    assert "LLM_PROVIDER=openai" in content
    assert "LLM_MODEL=llama3.2" in content
    assert "OPENAI_BASE_URL=http://localhost:11434/v1" in content

