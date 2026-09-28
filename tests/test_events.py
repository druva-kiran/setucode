"""Tests for EventBus and event emission — covers AC-18."""
from __future__ import annotations

from app.events.bus import EventBus
from app.events.events import (
    AgentEvent,
    PermissionRequest,
    PostToolUse,
    PreToolUse,
    Stop,
    Thinking,
)


class TestEventBus:
    def test_single_listener_receives_event(self):
        bus = EventBus()
        received = []
        bus.subscribe(received.append)
        event = Thinking()
        bus.emit(event)
        assert received == [event]

    def test_multiple_listeners_all_receive_event(self):
        bus = EventBus()
        r1, r2 = [], []
        bus.subscribe(r1.append)
        bus.subscribe(r2.append)
        e = Stop("done")
        bus.emit(e)
        assert r1 == [e]
        assert r2 == [e]

    def test_no_listeners_does_not_crash(self):
        bus = EventBus()
        bus.emit(Thinking())  # must not raise

    def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        received = []
        fn = received.append
        bus.subscribe(fn)
        bus.unsubscribe(fn)
        bus.emit(Thinking())
        assert received == []


class TestEventConstructors:
    def test_thinking_event(self):
        e = Thinking()
        assert e.name == "Thinking"

    def test_pre_tool_use_event(self):
        e = PreToolUse("read_file", {"path": "x.txt"})
        assert e.name == "PreToolUse"
        assert e.data["tool"] == "read_file"
        assert e.data["args"]["path"] == "x.txt"

    def test_post_tool_use_event(self):
        from app.tools.base import ToolResult
        r = ToolResult(output="ok")
        e = PostToolUse("read_file", r)
        assert e.name == "PostToolUse"
        assert not e.data["error"]

    def test_stop_event(self):
        e = Stop(reason="done")
        assert e.name == "Stop"
        assert e.data["reason"] == "done"

    def test_permission_request_event(self):
        e = PermissionRequest("write_file", "/workspace/x.py")
        assert e.name == "PermissionRequest"
        assert e.data["tool"] == "write_file"
