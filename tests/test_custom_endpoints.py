"""Tests for custom LLM endpoints and provider aliases."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest

from app.config.settings import Settings, load_settings
from app.providers import build_provider
from app.providers.openai import OpenAIProvider
from app.providers.anthropic import AnthropicProvider
from app.providers.gemini import GeminiProvider


def test_settings_loads_custom_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.com/anthropic")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://proxy.example.com/gemini")

    s = load_settings()
    assert s.openai_base_url == "http://localhost:11434/v1"
    assert s.anthropic_base_url == "https://proxy.example.com/anthropic"
    assert s.gemini_base_url == "https://proxy.example.com/gemini"


def test_build_provider_ollama_alias():
    s = Settings(
        provider="ollama",
        model="llama3:latest",
        openai_base_url="http://localhost:11434/v1",
    )
    with patch("app.providers.openai.OpenAI") as mock_openai:
        provider = build_provider(s)
        assert isinstance(provider, OpenAIProvider)
        mock_openai.assert_called_once()
        _, kwargs = mock_openai.call_args
        assert kwargs.get("base_url") == "http://localhost:11434/v1"
        assert kwargs.get("api_key") == "no-key-required"


def test_build_provider_openrouter():
    s = Settings(
        provider="openrouter",
        model="anthropic/claude-3.5-sonnet",
        openai_api_key="sk-or-test",
        openai_base_url="https://openrouter.ai/api/v1",
    )
    with patch("app.providers.openai.OpenAI") as mock_openai:
        provider = build_provider(s)
        assert isinstance(provider, OpenAIProvider)
        mock_openai.assert_called_once()
        _, kwargs = mock_openai.call_args
        assert kwargs.get("base_url") == "https://openrouter.ai/api/v1"
        assert kwargs.get("api_key") == "sk-or-test"


def test_build_provider_anthropic_custom_base_url():
    s = Settings(
        provider="claude",
        model="claude-3-5-sonnet-20241022",
        anthropic_api_key="sk-ant-test",
        anthropic_base_url="https://anthropic.proxy.internal",
    )
    with patch("anthropic.Anthropic") as mock_anthropic:
        provider = build_provider(s)
        assert isinstance(provider, AnthropicProvider)
        mock_anthropic.assert_called_once()
        _, kwargs = mock_anthropic.call_args
        assert kwargs.get("base_url") == "https://anthropic.proxy.internal"


def test_build_provider_gemini_custom_base_url():
    s = Settings(
        provider="gemini",
        model="gemini-2.5-flash",
        gemini_api_key="gem-test",
        gemini_base_url="https://gemini.proxy.internal",
    )
    with patch("google.genai.Client") as mock_client:
        provider = build_provider(s)
        assert isinstance(provider, GeminiProvider)
        mock_client.assert_called_once()
        _, kwargs = mock_client.call_args
        http_options = kwargs.get("http_options")
        assert http_options is not None
        assert http_options.base_url == "https://gemini.proxy.internal"
