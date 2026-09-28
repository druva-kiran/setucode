"""Prefix cache and KV-cache management.

This module provides prompt-prefix caching and KV-cache friendly prompt construction:
1. Separates static prompt content from dynamic content.
2. Places static instructions at the beginning of the prompt.
3. Provides cache-control markers for providers that support prompt caching (e.g. Anthropic).
4. Tracks cached vs uncached usage metrics when provided by model APIs.
5. Gracefully falls back when provider does not support KV caching.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class CacheMetrics:
    """Metrics for tracking cache hits, token usage, and latency savings."""
    cached_tokens: int = 0
    uncached_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    def record(self, cached: int = 0, uncached: int = 0) -> None:
        if cached > 0:
            self.cached_tokens += cached
            self.cache_hits += 1
        if uncached > 0:
            self.uncached_tokens += uncached
            if cached == 0:
                self.cache_misses += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "cached_tokens": self.cached_tokens,
            "uncached_tokens": self.uncached_tokens,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


class PrefixCache:
    """Thread-safe cache for static prompt prefix and KV-cache optimization."""

    _static_prompt: Optional[str] = None
    _metrics = CacheMetrics()
    _lock = threading.Lock()

    # Known providers with explicit prefix/prompt caching support
    _KV_CAPABLE_PROVIDERS = {"AnthropicProvider", "OpenAIProvider", "GeminiProvider"}

    @classmethod
    def _build_static(cls) -> str:
        """Construct the unchanging, reusable static prompt."""
        parts = [
            "You are SetuCode, a precise coding agent.",
            "Work only inside the workspace.",
            "Use tools to read before editing.",
            "When using edit_file, produce a valid unified diff patch.",
        ]
        return "\n".join(parts)

    @classmethod
    def get_static(cls) -> str:
        """Return the cached static prompt prefix, building once per process."""
        if cls._static_prompt is None:
            with cls._lock:
                if cls._static_prompt is None:
                    cls._static_prompt = cls._build_static()
        return cls._static_prompt

    @classmethod
    def compose_prompt(cls, user_memory: str = "", project_memory: str = "") -> str:
        """Combine the cached static prompt with dynamic memory blocks.

        Static instructions remain at the very front to maximize prefix-cache hits.
        """
        parts = [cls.get_static()]
        if user_memory:
            parts.append(f"\n## User Preferences\n{user_memory}")
        if project_memory:
            parts.append(f"\n## Project Instructions\n{project_memory}")
        return "\n".join(parts)

    @classmethod
    def format_anthropic_system(
        cls, user_memory: str = "", project_memory: str = ""
    ) -> list[dict[str, Any]] | str:
        """Format system prompt for Anthropic with ephemeral cache_control."""
        static_text = cls.get_static()
        dynamic_blocks = []
        if user_memory:
            dynamic_blocks.append(f"## User Preferences\n{user_memory}")
        if project_memory:
            dynamic_blocks.append(f"## Project Instructions\n{project_memory}")

        # If Anthropic supports structured prompt caching blocks:
        blocks: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": static_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if dynamic_blocks:
            blocks.append({
                "type": "text",
                "text": "\n\n".join(dynamic_blocks),
            })
        return blocks

    @classmethod
    def supports_caching(cls, provider_or_name: Any) -> bool:
        """Check if the provider supports prefix caching."""
        name = (
            provider_or_name
            if isinstance(provider_or_name, str)
            else type(provider_or_name).__name__
        )
        return name in cls._KV_CAPABLE_PROVIDERS

    @classmethod
    def record_usage(cls, cached: int = 0, uncached: int = 0) -> None:
        """Record token usage metrics."""
        with cls._lock:
            cls._metrics.record(cached=cached, uncached=uncached)

    @classmethod
    def get_metrics(cls) -> CacheMetrics:
        """Return a snapshot of current cache metrics."""
        return cls._metrics
