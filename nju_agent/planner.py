"""Small in-memory task planner used as the Agent's showcase feature."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PlanError(ValueError):
    """Raised when a task plan is invalid."""


@dataclass
class TaskPlan:
    steps: list[str] = field(default_factory=list)
    completed_steps: set[int] = field(default_factory=set)
    current_step: int | None = None
    note: str = ""

    def reset(self) -> None:
        self.steps = []
        self.completed_steps.clear()
        self.current_step = None
        self.note = ""

    def snapshot(self) -> dict[str, Any]:
        return {"steps": self.steps[:], "completed_steps": sorted(self.completed_steps), "current_step": self.current_step, "note": self.note}

    def restore(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict) or not data or not data.get("steps"):
            self.reset()
            return
        self.update(data)

    def update(self, arguments: dict[str, Any]) -> str:
        steps = arguments.get("steps", self.steps)
        completed = arguments.get("completed_steps", list(self.completed_steps))
        current = arguments.get("current_step", self.current_step)
        note = arguments.get("note", self.note)
        if not isinstance(steps, list) or not steps or not all(isinstance(step, str) and step.strip() for step in steps):
            raise PlanError("steps must be a non-empty list of strings")
        if not isinstance(completed, list) or not all(isinstance(index, int) for index in completed):
            raise PlanError("completed_steps must be a list of integers")
        if any(index < 1 or index > len(steps) for index in completed):
            raise PlanError("completed_steps contains an invalid step number")
        if current is not None and (not isinstance(current, int) or current < 1 or current > len(steps)):
            raise PlanError("current_step must identify an existing step")
        if not isinstance(note, str):
            raise PlanError("note must be a string")
        self.steps = [step.strip() for step in steps]
        self.completed_steps = set(completed)
        self.current_step = current
        self.note = note.strip()
        return self.render()

    def render(self) -> str:
        if not self.steps:
            return "(no task plan)"
        lines = []
        for index, step in enumerate(self.steps, start=1):
            marker = "x" if index in self.completed_steps else (">" if index == self.current_step else " ")
            lines.append(f"[{marker}] {index}. {step}")
        if self.note:
            lines.append(f"Note: {self.note}")
        return "\n".join(lines)
