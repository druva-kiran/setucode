"""Plan tools for LLM agent interaction."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.plan.manager import PlanManager
from app.plan.model import Plan, TaskStatus
from app.tools.base import ToolResult
from app.tools.registry import Tool


def make_create_plan(workspace: Path, get_plan_fn: Callable[[], Plan | None], set_plan_fn: Callable[[Plan], None]):
    def execute(args: dict) -> ToolResult:
        tasks = args.get("tasks", [])
        if not tasks or not isinstance(tasks, list):
            return ToolResult(error="Must provide a non-empty list of task descriptions.")

        plan = Plan()
        for idx, desc in enumerate(tasks):
            # First task starts in_progress
            status: TaskStatus = "in_progress" if idx == 0 else "pending"
            plan.add_task(str(desc).strip(), status=status)

        set_plan_fn(plan)
        PlanManager.save_plan(workspace, plan)
        return ToolResult(output=f"Plan created successfully:\n{plan.render()}")

    return execute


def make_update_plan_task(workspace: Path, get_plan_fn: Callable[[], Plan | None]):
    def execute(args: dict) -> ToolResult:
        plan = get_plan_fn()
        if not plan:
            return ToolResult(error="No active plan exists. Create a plan first.")

        task_id = args.get("task_id")
        if task_id is None:
            return ToolResult(error="Missing required 'task_id'.")

        status = args.get("status")
        notes = args.get("notes")

        valid_statuses = ("pending", "in_progress", "completed", "blocked")
        if status and status not in valid_statuses:
            return ToolResult(
                error=f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
            )

        updated = plan.update_task(int(task_id), status=status, notes=notes)
        if not updated:
            return ToolResult(error=f"Task with id {task_id} not found in plan.")

        PlanManager.save_plan(workspace, plan)
        return ToolResult(output=f"Task {task_id} updated:\n{plan.render()}")

    return execute


def make_get_plan(get_plan_fn: Callable[[], Plan | None]):
    def execute(args: dict) -> ToolResult:
        plan = get_plan_fn()
        if not plan:
            return ToolResult(output="No active plan currently defined.")
        return ToolResult(output=plan.render())

    return execute


def build_plan_tools(
    workspace: Path,
    get_plan_fn: Callable[[], Plan | None],
    set_plan_fn: Callable[[Plan], None],
) -> list[Tool]:
    """Build the planning tools for registration."""
    return [
        Tool(
            name="create_plan",
            description="Create a structured task plan with ordered steps for a complex task.",
            input_schema={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of task step descriptions.",
                    }
                },
                "required": ["tasks"],
            },
            execute=make_create_plan(workspace, get_plan_fn, set_plan_fn),
            permission_category="readonly",
        ),
        Tool(
            name="update_plan_task",
            description="Update the status or notes of a task in the plan.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer", "description": "The ID of the task to update."},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed", "blocked"],
                        "description": "New status for the task.",
                    },
                    "notes": {"type": "string", "description": "Optional notes or result summary for this task."},
                },
                "required": ["task_id"],
            },
            execute=make_update_plan_task(workspace, get_plan_fn),
            permission_category="readonly",
        ),
        Tool(
            name="get_plan",
            description="View the current status of the task plan.",
            input_schema={"type": "object", "properties": {}},
            execute=make_get_plan(get_plan_fn),
            permission_category="readonly",
        ),
    ]
