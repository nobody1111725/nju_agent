"""The minimal model-tool-model Agent loop."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from .tools import LocalTools, ToolError


class ModelClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]: ...


class AgentError(RuntimeError):
    """Raised when the Agent cannot continue safely."""


class Agent:
    def __init__(self, client: ModelClient, tools: LocalTools, *, max_steps: int = 8, max_repeated_errors: int = 3, logger: logging.Logger | None = None) -> None:
        self.client = client
        self.tools = tools
        self.max_steps = max_steps
        self.max_repeated_errors = max_repeated_errors
        self.logger = logger or logging.getLogger(__name__)

    def run(self, task: str) -> str:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": "You are a programming assistant. Use the available local tools when they help answer the task. Be concise.",
            },
            {"role": "user", "content": task},
        ]
        repeated_error = None
        repeated_count = 0
        for step in range(self.max_steps):
            self.logger.info("model request step=%d", step + 1)
            try:
                message = self.client.complete(messages, self.tools.definitions())
            except KeyboardInterrupt:
                raise AgentError("Task interrupted by user") from None
            if not isinstance(message, dict):
                raise AgentError("Model returned an invalid message object")
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                raise AgentError("Model returned invalid tool_calls")
            content = message.get("content") or ""
            if not tool_calls:
                if not isinstance(content, str) or not content.strip():
                    raise AgentError("Model returned neither a final answer nor a tool call")
                return content.strip()

            assistant_message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            messages.append(assistant_message)
            for call in tool_calls:
                if not isinstance(call, dict):
                    raise AgentError("Model returned a malformed tool call")
                try:
                    name = call["function"]["name"]
                    arguments = call["function"].get("arguments", "{}")
                    result = self.tools.execute(name, arguments)
                except (KeyError, TypeError, ToolError) as exc:
                    result = f"Tool error: {exc}"
                    function_data = call.get("function")
                    name = function_data.get("name", "unknown") if isinstance(function_data, dict) else "unknown"
                    if result == repeated_error:
                        repeated_count += 1
                    else:
                        repeated_error, repeated_count = result, 1
                    self.logger.warning("tool failure name=%s count=%d", name, repeated_count)
                    if repeated_count >= self.max_repeated_errors:
                        raise AgentError(f"Stopped after repeated tool failure: {result}")
                else:
                    repeated_error, repeated_count = None, 0
                    self.logger.info("tool success name=%s", name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", "missing-id"),
                        "name": name,
                        "content": result,
                    }
                )
        raise AgentError(f"Agent stopped after reaching the {self.max_steps}-step limit")
