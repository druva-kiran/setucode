"""In-process publish/subscribe EventBus.

The Agent Loop emits events; the TUI and other listeners subscribe.
The bus calls listeners synchronously in registration order.
No listener may call back into the bus during dispatch.
"""
from __future__ import annotations

from typing import Callable

from app.events.events import AgentEvent


class EventBus:
    def __init__(self) -> None:
        self._listeners: list[Callable[[AgentEvent], None]] = []

    def subscribe(self, fn: Callable[[AgentEvent], None]) -> None:
        """Register a listener. All future events will be delivered to it."""
        self._listeners.append(fn)

    def unsubscribe(self, fn: Callable[[AgentEvent], None]) -> None:
        """Remove a listener."""
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def emit(self, event: AgentEvent) -> None:
        """Broadcast event to all registered listeners."""
        for fn in self._listeners:
            fn(event)
