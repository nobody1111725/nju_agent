"""Local programming tools executed by the Agent process."""

from __future__ import annotations

import json
import difflib
import subprocess
from pathlib import Path
from typing import Any, Callable

from .planner import PlanError, TaskPlan

ToolFunction = Callable[[dict[str, Any]], str]


class ToolError(ValueError):
    """Raised when a tool call cannot be executed."""


class LocalTools:
    """Definitions and implementations of tools available to the model."""

    def __init__(self, workspace: Path, *, command_timeout: float = 30.0, output_limit: int = 12_000, plan: TaskPlan | None = None) -> None:
        self.workspace = workspace.resolve()
        self.command_timeout = command_timeout
        self.output_limit = output_limit
        self.plan = plan or TaskPlan()
        self.last_diff: dict[str, Any] | None = None
        self.functions: dict[str, ToolFunction] = {
            "list_files": self.list_files,
            "read_file": self.read_file,
            "write_file": self.write_file,
            "edit_file": self.edit_file,
            "run_command": self.run_command,
            "update_plan": self.update_plan,
        }

    def definitions(self) -> list[dict[str, Any]]:
        return [
            self._definition("list_files", "List files and directories under the configured workspace.", {"path": {"type": "string", "description": "Relative directory path."}}),
            self._definition("read_file", "Read a UTF-8 text file in the workspace, optionally selecting a line range.", {"path": {"type": "string", "description": "Relative file path."}, "start_line": {"type": "integer", "description": "1-based first line, default 1."}, "end_line": {"type": "integer", "description": "Inclusive last line, default end of file."}}, required=["path"]),
            self._definition("write_file", "Create or overwrite a UTF-8 text file in the workspace.", {"path": {"type": "string", "description": "Relative file path."}, "content": {"type": "string", "description": "Complete file content."}}, required=["path", "content"]),
            self._definition("edit_file", "Replace one exact text snippet in a UTF-8 file. The old text must occur exactly once.", {"path": {"type": "string", "description": "Relative file path."}, "old_text": {"type": "string", "description": "Exact text to replace."}, "new_text": {"type": "string", "description": "Replacement text."}}, required=["path", "old_text", "new_text"]),
            self._definition("run_command", "Run a shell command in the configured workspace and return its exit code and output.", {"command": {"type": "string", "description": "Command to execute."}}, required=["command"]),
            self._definition("update_plan", "Create or update the task plan. Use this for multi-step programming tasks and mark completed steps.", {"steps": {"type": "array", "items": {"type": "string"}, "description": "Ordered task steps."}, "completed_steps": {"type": "array", "items": {"type": "integer"}, "description": "1-based step numbers already completed."}, "current_step": {"type": "integer", "description": "1-based step currently being worked on."}, "note": {"type": "string", "description": "Short progress note."}}, required=["steps"]),
        ]

    @staticmethod
    def _definition(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}}}

    def execute(self, name: str, arguments: str | dict[str, Any]) -> str:
        self.last_diff = None
        function = self.functions.get(name)
        if function is None:
            raise ToolError(f"Unknown tool: {name}")
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError as exc:
            raise ToolError(f"Invalid arguments for {name}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ToolError(f"Arguments for {name} must be an object")
        return function(parsed)

    def _path(self, value: Any, *, expect_directory: bool = False) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolError("path must be a non-empty string")
        target = (self.workspace / value).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ToolError("Requested path is outside the workspace")
        if expect_directory and target.exists() and not target.is_dir():
            raise ToolError(f"Path is not a directory: {value}")
        return target

    def list_files(self, arguments: dict[str, Any]) -> str:
        relative = arguments.get("path", ".")
        target = self._path(relative, expect_directory=True)
        if not target.exists():
            raise ToolError(f"Path does not exist: {relative}")
        entries = []
        for item in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
            prefix = "dir " if item.is_dir() else "file"
            entries.append(f"{prefix}: {item.relative_to(self.workspace)}")
        return self._limit("\n".join(entries) if entries else "(empty directory)")

    def read_file(self, arguments: dict[str, Any]) -> str:
        relative = arguments.get("path")
        target = self._path(relative)
        if not target.exists():
            raise ToolError(f"File does not exist: {relative}")
        if not target.is_file():
            raise ToolError(f"Path is not a file: {relative}")
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ToolError(f"File is not valid UTF-8 text: {relative}") from exc
        start = arguments.get("start_line", 1)
        end = arguments.get("end_line", len(lines))
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise ToolError("start_line and end_line must be valid 1-based integers")
        selected = lines[start - 1 : end]
        numbered = "\n".join(f"{number}: {line}" for number, line in enumerate(selected, start=start))
        return self._limit(numbered or "(empty selection)")

    def write_file(self, arguments: dict[str, Any]) -> str:
        relative = arguments.get("path")
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be a string")
        target = self._path(relative)
        before = ""
        if target.is_file():
            try:
                before = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                before = None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
        self.last_diff = self._make_diff(str(relative), before, content)
        return f"Wrote {len(content)} characters to {target.relative_to(self.workspace)}"

    def edit_file(self, arguments: dict[str, Any]) -> str:
        relative = arguments.get("path")
        old_text = arguments.get("old_text")
        new_text = arguments.get("new_text")
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise ToolError("old_text and new_text must be strings")
        target = self._path(relative)
        if not target.is_file():
            raise ToolError(f"File does not exist: {relative}")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"File is not valid UTF-8 text: {relative}") from exc
        occurrences = content.count(old_text)
        if occurrences != 1:
            raise ToolError(f"old_text must occur exactly once; found {occurrences}")
        updated = content.replace(old_text, new_text, 1)
        target.write_text(updated, encoding="utf-8", newline="")
        self.last_diff = self._make_diff(str(relative), content, updated)
        return f"Edited {target.relative_to(self.workspace)}"

    @staticmethod
    def _make_diff(path: str, before: str | None, after: str) -> dict[str, Any]:
        """Build a bounded unified diff for the local UI."""
        if before is None:
            before_lines: list[str] = []
            before_available = False
        else:
            before_lines = before.splitlines()
            before_available = True
        after_lines = after.splitlines()
        raw_lines = list(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        max_lines = 500
        max_chars = 20_000
        lines: list[str] = []
        used_chars = 0
        truncated = False
        for line in raw_lines:
            if len(lines) >= max_lines or used_chars + len(line) > max_chars:
                truncated = True
                break
            lines.append(line)
            used_chars += len(line)
        if truncated:
            lines.append("... diff truncated ...")
        return {
            "path": path,
            "lines": lines,
            "added": sum(1 for line in raw_lines if line.startswith("+") and not line.startswith("+++")),
            "removed": sum(1 for line in raw_lines if line.startswith("-") and not line.startswith("---")),
            "before_available": before_available,
            "truncated": truncated,
        }

    def run_command(self, arguments: dict[str, Any]) -> str:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolError("command must be a non-empty string")
        if self._is_blocked_command(command):
            raise ToolError("Command blocked by safety policy")
        try:
            completed = subprocess.run(command, cwd=self.workspace, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.command_timeout)
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + (exc.stderr or "")
            return self._limit(f"timed out after {self.command_timeout:g}s\n{output}")
        except OSError as exc:
            raise ToolError(f"Could not start command: {exc}") from exc
        output = (completed.stdout or "") + (completed.stderr or "")
        return self._limit(f"exit_code: {completed.returncode}\n{output}")

    def update_plan(self, arguments: dict[str, Any]) -> str:
        try:
            return self.plan.update(arguments)
        except PlanError as exc:
            raise ToolError(str(exc)) from exc

    def _limit(self, text: str) -> str:
        if len(text) <= self.output_limit:
            return text
        return text[: self.output_limit] + f"\n...[output truncated at {self.output_limit} characters]"

    @staticmethod
    def _is_blocked_command(command: str) -> bool:
        normalized = " ".join(command.lower().split())
        blocked = (
            "rm -rf",
            "rmdir /s",
            "del /s",
            "format ",
            "shutdown ",
            "git push",
        )
        return any(token in normalized for token in blocked)
