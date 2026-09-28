"""Agent Loop — the ReAct cycle that drives SetuCode.

Call run() with an AgentState, user message, EventBus, ToolRegistry, and
PermissionManager. The loop runs until the model produces a final text
response or an unrecoverable error occurs.

Design invariants:
  - The loop is single-threaded per session.
  - Tool calls always pass through PermissionManager before execution.
  - Tool errors are returned to the model, never raised.
  - The LLM has no path into the PermissionManager.
"""
from __future__ import annotations

import logging

from app.agent.state import AgentState, AgentStatus
from app.events.bus import EventBus
from app.events.events import (
    PermissionRequest,
    PostToolUse,
    PreToolUse,
    Stop,
    Thinking,
)
from app.permissions.manager import PermissionManager
from app.permissions.policy import PermissionDecision
from app.tools.base import ToolResult
from app.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


def _build_system_prompt(state: AgentState) -> str:
    """Compose the system prompt using cached static part + dynamic memories.

    The static portion is provided by :class:`app.context.prefix_cache.PrefixCache`
    which builds it once per process. This reduces prompt reconstruction overhead and
    enables KV‑cache reuse on providers that support it.
    """
    from app.context.prefix_cache import PrefixCache
    return PrefixCache.compose_prompt(state.user_memory, state.project_memory)


def _append_tool_result(
    messages: list[dict],
    tool_call_id: str,
    tool_name: str,
    result: ToolResult,
    provider_name: str,
) -> None:
    """Append a tool result in the correct format for the active provider."""
    content = result.to_message_content()
    messages.append({
        "role": "tool",
        "tool_use_id": tool_call_id,
        "tool_call_id": tool_call_id,
        "name": tool_name,
        "content": content,
    })


def run(
    state: AgentState,
    user_message: str,
    bus: EventBus,
    registry: ToolRegistry,
    permissions: PermissionManager,
) -> str:
    """Run the ReAct loop until a final response is produced.

    Returns the final text response string.
    Mutates state.messages and state.status in place.
    """
    log.info("Agent started | session=%s | workspace=%s", state.session_id, state.workspace)
    log.info("Model selected: %s", type(state.model).__name__)

    # --- Feature 1 & 7: Context Manager initialization ---
    if getattr(state, "context_manager", None) is None:
        from app.context.manager import ContextManager
        state.context_manager = ContextManager()

    # --- Feature 4: Plan Detection & Recovery ---
    from app.plan.manager import PlanManager, is_complex_task, create_initial_plan
    from app.plan.tools import build_plan_tools

    if getattr(state, "plan", None) is None:
        persisted_plan = PlanManager.load_plan(state.workspace)
        if persisted_plan:
            state.plan = persisted_plan
            log.info("Recovered persisted plan with %d tasks", len(persisted_plan.tasks))
        elif is_complex_task(user_message):
            state.plan = create_initial_plan(user_message)
            PlanManager.save_plan(state.workspace, state.plan)
            log.info("Created initial plan for complex task with %d steps", len(state.plan.tasks))

    # Register plan tools if plan is active
    if getattr(state, "plan", None) and not registry.get("get_plan"):
        for pt in build_plan_tools(
            state.workspace,
            get_plan_fn=lambda: getattr(state, "plan", None),
            set_plan_fn=lambda p: setattr(state, "plan", p),
        ):
            registry.register(pt)

    # --- Feature 8: Register Subagent Delegation Tool ---
    if not registry.get("delegate_task"):
        from app.subagents.manager import SubagentManager
        from app.subagents.tools import make_delegate_task
        sub_mgr = SubagentManager(state.workspace, permissions, registry)
        registry.register(make_delegate_task(sub_mgr, state.model, bus))

    # Inject static & memory system prompt on first message
    if not state.messages:
        system_prompt = _build_system_prompt(state)
        state.messages.append({"role": "system", "content": system_prompt})

    # Append user message
    state.messages.append({"role": "user", "content": user_message})

    # --- Feature 2: Detect & Inject relevant skills ---
    from app.skills.manager import inject_skill_hints
    inject_skill_hints(state.messages, user_message, tool_registry=registry)

    # --- Feature 3: Inject initial plan into late context ---
    if getattr(state, "plan", None):
        state.context_manager.add_late_context(
            category="task_plan",
            title="Current Task Plan",
            content=state.plan.render(),
            priority=2,
            key="active_task_plan",
        )

    log.info("User message received: %r", user_message[:120])
    provider_name = type(state.model).__name__

    while True:
        # --- Feature 6 & 7: Check token budget and compact if needed ---
        state.context_manager.check_and_compact(state)

        # --- Feature 3: Inject pending dynamic/late context before LLM call ---
        state.context_manager.inject_pending_late_context(state)

        # --- LLM call ---
        state.status = AgentStatus.THINKING
        bus.emit(Thinking())
        log.info("LLM call starting | messages=%d", len(state.messages))

        try:
            response = state.model.generate(
                messages=state.messages,
                tools=registry.schema_list(),
            )
        except Exception as exc:
            log.error("LLM API error: %s", exc)
            state.status = AgentStatus.ERROR
            bus.emit(Stop(reason=f"LLM error: {exc}"))
            return f"Error communicating with LLM: {exc}"

        log.info(
            "LLM response received | tool_calls=%d | has_text=%s",
            len(response.tool_calls),
            response.final_text is not None,
        )

        # Record usage & cache metrics
        if getattr(response, "usage", None):
            from app.context.prefix_cache import PrefixCache
            PrefixCache.record_usage(
                cached=response.usage.get("cached_tokens", 0),
                uncached=response.usage.get("input_tokens", 0),
            )

        # --- Final answer ---
        if response.final_text is not None and not response.has_tool_calls:
            state.messages.append({"role": "assistant", "content": response.final_text})
            state.status = AgentStatus.FINISHED
            bus.emit(Stop(reason="done"))
            log.info("Agent finished | session=%s", state.session_id)

            # Persist plan upon completion
            if getattr(state, "plan", None):
                PlanManager.save_plan(state.workspace, state.plan)

            return response.final_text

        # --- Malformed response (neither text nor tool calls) ---
        if not response.has_tool_calls and response.final_text is None:
            log.error("LLM returned empty response")
            state.status = AgentStatus.ERROR
            bus.emit(Stop(reason="empty response"))
            return "Error: LLM returned an empty response."

        # --- Process tool calls ---
        state.messages.append({
            "role": "assistant",
            "content": response.final_text or "",
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "args": tc.args}
                for tc in response.tool_calls
            ],
        })

        for tc in response.tool_calls:
            log.info("Tool requested: %s | args=%s", tc.name, tc.args)
            bus.emit(PreToolUse(tc.name, tc.args))

            tool = registry.get(tc.name)

            if tool is None:
                log.warning("Unknown tool: %s", tc.name)
                result = ToolResult(error=f"Unknown tool '{tc.name}'.")
                bus.emit(PostToolUse(tc.name, result, is_error=True))
                _append_tool_result(state.messages, tc.id, tc.name, result, provider_name)
                continue

            # --- Permission & Sandbox check ---
            state.status = AgentStatus.WAITING_FOR_PERMISSION
            state.pending_permission = tc

            raw_path = tc.args.get("path") or tc.args.get("source") or ""
            bus.emit(PermissionRequest(tc.name, raw_path))

            log.info("Permission requested: %s", tc.name)
            decision = permissions.check(tool, tc.args, state.workspace)
            log.info("Permission response: %s → %s", tc.name, decision.value)

            state.pending_permission = None

            if decision == PermissionDecision.DENY:
                denial_reason = getattr(permissions, "last_denial_reason", None) or "Permission denied by user."
                result = ToolResult(error=denial_reason)
                bus.emit(PostToolUse(tc.name, result, is_error=True))
                _append_tool_result(state.messages, tc.id, tc.name, result, provider_name)
                continue

            # --- Execute tool ---
            state.status = AgentStatus.EXECUTING_TOOL
            log.info("Tool started: %s", tc.name)

            try:
                result = tool.execute(tc.args)
            except Exception as exc:
                log.error("Tool execution error: %s | %s", tc.name, exc)
                result = ToolResult(error=str(exc))

            # Secret redaction
            if result.output:
                from app.permissions.sandbox import SecuritySandbox
                result.output = SecuritySandbox.redact_secrets(result.output)

            # If tool produced an error, inject into late context for targeted error recovery
            if result.is_error and result.error:
                state.context_manager.add_late_context(
                    category="compiler_error",
                    title=f"Error in {tc.name}",
                    content=result.error,
                    priority=4,
                    is_transient=True,
                )

            log.info("Tool completed: %s | error=%s", tc.name, result.is_error)
            bus.emit(PostToolUse(tc.name, result, is_error=result.is_error))
            _append_tool_result(state.messages, tc.id, tc.name, result, provider_name)

        # Loop continues — next iteration calls LLM with updated messages
