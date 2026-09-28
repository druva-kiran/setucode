"""Context budgeting and token estimation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


def estimate_tokens(obj: Any) -> int:
    """Fast approximation of token count.

    Uses ~3.8 chars per token heuristic for code/English text.
    """
    if isinstance(obj, str):
        text = obj
    elif isinstance(obj, (dict, list)):
        text = json.dumps(obj)
    else:
        text = str(obj)

    # 1 token ~= 3.8 characters
    return max(1, int(len(text) / 3.8))


@dataclass
class ContextBudget:
    """Manages the token budget, headroom reservation, and compaction thresholds."""

    max_tokens: int = 16384
    reserve_response_tokens: int = 2048
    compaction_threshold_ratio: float = 0.75  # compact when reaching 75% capacity

    @property
    def usable_tokens(self) -> int:
        return max(0, self.max_tokens - self.reserve_response_tokens)

    @property
    def compaction_token_limit(self) -> int:
        return int(self.usable_tokens * self.compaction_threshold_ratio)

    def should_compact(self, current_token_count: int) -> bool:
        """Return True if current context exceeds the safe threshold for compaction."""
        return current_token_count >= self.compaction_token_limit

    def remaining_tokens(self, current_token_count: int) -> int:
        """Estimated tokens remaining before hitting response reserve buffer."""
        return max(0, self.usable_tokens - current_token_count)
