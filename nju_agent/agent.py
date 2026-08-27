"""The minimal model-tool-model Agent loop."""

from __future__ import annotations

from typing import Any, Protocol

from .tools import LocalTools, ToolError


class ModelClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]: ...


class AgentError(RuntimeError):
    """Raised when the Agent cannot continue safely."""


class Agent:
    def __init__(self, client: ModelClient, tools: LocalTools, *, max_steps: int = 8) -> None:
        self.client = client
        self.tools = tools
        self.max_steps = max_steps

    def run(self, task: str) -> str:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": "You are a programming assistant. Use the available local tools when they help answer the task. Be concise.",
            },
            {"role": "user", "content": task},
        ]
        for _ in range(self.max_steps):
            message = self.client.complete(messages, self.tools.definitions())
            tool_calls = message.get("tool_calls") or []
            content = message.get("content") or ""
            if not tool_calls:
                if not isinstance(content, str) or not content.strip():
                    raise AgentError("Model returned neither a final answer nor a tool call")
                return content.strip()

            assistant_message = {"role": "assistant", "content": content, "tool_calls": tool_calls}
            messages.append(assistant_message)
            for call in tool_calls:
                try:
                    name = call["function"]["name"]
                    arguments = call["function"].get("arguments", "{}")
                    result = self.tools.execute(name, arguments)
                except (KeyError, TypeError, ToolError) as exc:
                    result = f"Tool error: {exc}"
                    name = call.get("function", {}).get("name", "unknown")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", "missing-id"),
                        "name": name,
                        "content": result,
                    }
                )
        raise AgentError(f"Agent stopped after reaching the {self.max_steps}-step limit")

