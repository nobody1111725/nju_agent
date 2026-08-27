"""Local tools exposed to the model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


ToolFunction = Callable[[dict[str, Any]], str]


class ToolError(ValueError):
    """Raised when a tool call cannot be executed."""


class LocalTools:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.functions: dict[str, ToolFunction] = {"list_files": self.list_files}

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List files and directories under the configured workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string", "description": "Relative directory path."}},
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            }
        ]

    def execute(self, name: str, arguments: str | dict[str, Any]) -> str:
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

    def list_files(self, arguments: dict[str, Any]) -> str:
        relative = arguments.get("path", ".")
        if not isinstance(relative, str):
            raise ToolError("list_files.path must be a string")
        target = (self.workspace / relative).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ToolError("Requested path is outside the workspace")
        if not target.exists():
            raise ToolError(f"Path does not exist: {relative}")
        if not target.is_dir():
            raise ToolError(f"Path is not a directory: {relative}")
        entries = []
        for item in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
            prefix = "dir " if item.is_dir() else "file"
            entries.append(f"{prefix}: {item.relative_to(self.workspace)}")
        return "\n".join(entries) if entries else "(empty directory)"

