"""Unit tests for Prefix Cache and KV-cache optimization."""
from __future__ import annotations

import pytest

from app.context.prefix_cache import PrefixCache, CacheMetrics
from app.providers.anthropic import AnthropicProvider
from app.providers.openai import OpenAIProvider
from app.providers.base import BaseProvider, ModelResponse, ToolCall
from app.agent.loop import run
from app.agent.state import AgentState, AgentStatus
from app.events.bus import EventBus
from app.permissions.manager import PermissionManager
from app.permissions.policy import PermissionDecision
from app.tools.registry import build_default_registry
from unittest.mock import MagicMock


def test_static_prefix_is_stable_and_cached():
    """PrefixCache must return identical static prefix on repeated calls."""
    p1 = PrefixCache.get_static()
    p2 = PrefixCache.get_static()
    assert p1 == p2
    assert "You are SetuCode" in p1
    assert "Work only inside the workspace" in p1


def test_compose_prompt_places_static_first():
    """Static instructions must precede dynamic memories for prefix caching."""
    static = PrefixCache.get_static()
    composed = PrefixCache.compose_prompt(
        user_memory="User likes pytest",
        project_memory="Python 3.12 only",
    )
    assert composed.startswith(static)
    assert "## User Preferences\nUser likes pytest" in composed
    assert "## Project Instructions\nPython 3.12 only" in composed


def test_anthropic_system_format_cache_control():
    """Anthropic system formatting should include cache_control ephemeral on static prefix."""
    blocks = PrefixCache.format_anthropic_system(
        user_memory="User likes pytest",
        project_memory="Project rule",
    )
    assert isinstance(blocks, list)
    assert len(blocks) == 2
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == PrefixCache.get_static()
    assert "User likes pytest" in blocks[1]["text"]


def test_cache_provider_support_and_fallback():
    """Check detection of KV cache support with graceful fallback."""
    assert PrefixCache.supports_caching("AnthropicProvider") is True
    assert PrefixCache.supports_caching("OpenAIProvider") is True
    assert PrefixCache.supports_caching("NonExistentProvider") is False


def test_metrics_tracking():
    """Cache metrics must track cached vs uncached tokens correctly."""
    metrics = CacheMetrics()
    metrics.record(cached=150, uncached=50)
    assert metrics.cached_tokens == 150
    assert metrics.uncached_tokens == 50
    assert metrics.cache_hits == 1

    metrics.record(cached=0, uncached=200)
    assert metrics.cached_tokens == 150
    assert metrics.uncached_tokens == 250
    assert metrics.cache_misses == 1


def test_loop_records_provider_usage(tmp_path):
    """Agent loop records usage stats into PrefixCache when returned by provider."""
    class UsageProvider(BaseProvider):
        def generate(self, messages, tools):
            return ModelResponse(
                final_text="Done",
                usage={"cached_tokens": 120, "input_tokens": 40},
            )

    registry = build_default_registry(tmp_path)
    state = AgentState(
        session_id="s1",
        workspace=tmp_path,
        model=UsageProvider(),
        available_tools=registry.schema_list(),
    )
    storage = MagicMock()
    storage.is_always_allowed.return_value = False
    perms = PermissionManager(storage, lambda name, path: PermissionDecision.ALLOW_ONCE)
    bus = EventBus()

    run(state, "Hello", bus, registry, perms)

    metrics = PrefixCache.get_metrics()
    assert metrics.cached_tokens >= 120
