"""Unit tests for Structured Planning and TODO tracking."""
from __future__ import annotations

from pathlib import Path
import pytest

from app.plan.manager import PlanManager, is_complex_task, create_initial_plan
from app.plan.model import Plan, Task
from app.plan.tools import build_plan_tools


def test_complexity_detection():
    """Simple tasks do not trigger planning; complex multi-step tasks do."""
    # Simple requests
    assert is_complex_task("hello") is False
    assert is_complex_task("what is Python?") is False
    assert is_complex_task("read app/main.py") is False

    # Complex multi-step requests
    assert is_complex_task("First inspect the repo, then implement auth, and finally run tests") is True
    assert is_complex_task("Refactor database layer and verify with tests") is True
    bullet_prompt = "Please do:\n- inspect code\n- write migration\n- verify tests"
    assert is_complex_task(bullet_prompt) is True


def test_initial_plan_creation():
    """Initial plan extracts tasks from bullet points or sets default milestones."""
    prompt = "Task list:\n1. Update models\n2. Add endpoint\n3. Write unit tests"
    plan = create_initial_plan(prompt)
    assert len(plan.tasks) == 3
    assert plan.tasks[0].description == "Update models"
    assert plan.tasks[0].status == "pending"

    # Default fallback milestones
    default_plan = create_initial_plan("Implement a complex distributed cache and test it")
    assert len(default_plan.tasks) == 4
    assert default_plan.tasks[0].status == "in_progress"


def test_plan_status_transitions_and_render():
    """Plan tasks transition between pending, in_progress, completed, and blocked."""
    plan = Plan()
    t1 = plan.add_task("Step 1")
    t2 = plan.add_task("Step 2")

    assert plan.current_task().id == t1.id

    plan.update_task(t1.id, status="completed", notes="Done cleanly")
    assert t1.status == "completed"
    assert plan.current_task().id == t2.id

    plan.update_task(t2.id, status="blocked", notes="Waiting on API key")
    assert t2.status == "blocked"

    rendered = plan.render()
    assert "[x] 1. Step 1" in rendered
    assert "[!] 2. Step 2 (blocked) — Waiting on API key" in rendered


def test_plan_persistence_and_recovery(tmp_path: Path):
    """Plan correctly saves to workspace plan.json and recovers after restart/compaction."""
    plan = Plan()
    plan.add_task("Task 1", status="completed")
    plan.add_task("Task 2", status="in_progress")

    PlanManager.save_plan(tmp_path, plan)
    assert (tmp_path / "plan.json").exists()

    recovered = PlanManager.load_plan(tmp_path)
    assert recovered is not None
    assert len(recovered.tasks) == 2
    assert recovered.tasks[0].status == "completed"
    assert recovered.tasks[1].status == "in_progress"


def test_plan_tools(tmp_path: Path):
    """Planning tools allow the agent to create and update tasks."""
    state_holder = {"plan": None}

    def get_plan():
        return state_holder["plan"]

    def set_plan(p):
        state_holder["plan"] = p

    tools = {
        t.name: t
        for t in build_plan_tools(tmp_path, get_plan_fn=get_plan, set_plan_fn=set_plan)
    }

    # create_plan
    create_res = tools["create_plan"].execute({"tasks": ["Review code", "Fix bug"]})
    assert not create_res.is_error
    assert state_holder["plan"] is not None
    assert len(state_holder["plan"].tasks) == 2

    # update_plan_task
    update_res = tools["update_plan_task"].execute({
        "task_id": 1,
        "status": "completed",
        "notes": "Reviewed",
    })
    assert not update_res.is_error
    assert state_holder["plan"].tasks[0].status == "completed"

    # get_plan
    get_res = tools["get_plan"].execute({})
    assert "[x] 1. Review code" in get_res.output
