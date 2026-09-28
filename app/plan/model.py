"""Data models for Structured Planning and TODO tracking."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Literal, Optional

TaskStatus = Literal["pending", "in_progress", "completed", "blocked"]

STATUS_ICONS = {
    "pending": "[ ]",
    "in_progress": "[>]",
    "completed": "[x]",
    "blocked": "[!]",
}


@dataclass
class Task:
    id: int
    description: str
    status: TaskStatus = "pending"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            id=data["id"],
            description=data["description"],
            status=data.get("status", "pending"),
            notes=data.get("notes", ""),
        )


@dataclass
class Plan:
    tasks: list[Task] = field(default_factory=list)
    _counter: int = 0

    def add_task(
        self, description: str, status: TaskStatus = "pending", notes: str = ""
    ) -> Task:
        self._counter += 1
        task = Task(id=self._counter, description=description, status=status, notes=notes)
        self.tasks.append(task)
        return task

    def update_task(
        self,
        task_id: int,
        status: TaskStatus | None = None,
        notes: str | None = None,
    ) -> bool:
        for t in self.tasks:
            if t.id == task_id:
                if status:
                    t.status = status
                if notes is not None:
                    t.notes = notes
                return True
        return False

    def get_task(self, task_id: int) -> Optional[Task]:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def current_task(self) -> Optional[Task]:
        """Return the active in_progress task or first pending task."""
        for t in self.tasks:
            if t.status == "in_progress":
                return t
        for t in self.tasks:
            if t.status == "pending":
                return t
        return None

    def is_completed(self) -> bool:
        return bool(self.tasks) and all(t.status == "completed" for t in self.tasks)

    def render(self) -> str:
        """Render a readable Markdown representation of the plan."""
        if not self.tasks:
            return "No plan defined."

        lines = ["### TASK PLAN"]
        for t in self.tasks:
            icon = STATUS_ICONS.get(t.status, "[ ]")
            status_text = f" ({t.status})" if t.status != "pending" else ""
            note_text = f" — {t.notes}" if t.notes else ""
            lines.append(f"{icon} {t.id}. {t.description}{status_text}{note_text}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tasks": [t.to_dict() for t in self.tasks],
            "counter": self._counter,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        counter = data.get("counter", len(tasks))
        plan = cls(tasks=tasks)
        plan._counter = counter
        return plan
