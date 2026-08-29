"""The minimal model-tool-model Agent loop."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Protocol

from .context import ContextManager
from .planner import TaskPlan
from .tools import LocalTools, ToolError


class ModelClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]: ...


ToolObserver = Callable[[str, Any, str | None], None]


class AgentError(RuntimeError):
    """Raised when the Agent cannot continue safely."""


class Agent:
    def __init__(self, client: ModelClient, tools: LocalTools, *, max_steps: int = 20, max_repeated_errors: int = 3, max_context_chars: int = 24_000, logger: logging.Logger | None = None, on_tool_start: Callable[[str, Any], None] | None = None, on_tool_end: ToolObserver | None = None) -> None:
        self.client = client
        self.tools = tools
        self.max_steps = max_steps
        self.max_repeated_errors = max_repeated_errors
        self.logger = logger or logging.getLogger(__name__)
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.context = ContextManager(max_chars=max_context_chars)
        self.plan: TaskPlan = tools.plan

    def run(self, task: str) -> str:
        self.plan.reset()
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {"role": "user", "content": task},
        ]
        repeated_error = None
        repeated_count = 0
        last_tool_signature = None
        same_tool_count = 0
        inspection_rounds = 0
        for step in range(self.max_steps):
            messages[0]["content"] = self._system_prompt()
            messages = self.context.compact(messages)
            self.logger.info("context chars=%d", self.context.size(messages))
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
            round_names: list[str] = []
            for call in tool_calls:
                if not isinstance(call, dict):
                    raise AgentError("Model returned a malformed tool call")
                signature = None
                arguments: Any = "{}"
                name = "unknown"
                result: str | None = None
                try:
                    name = call["function"]["name"]
                    arguments = call["function"].get("arguments", "{}")
                    signature = self._tool_signature(name, arguments)
                    round_names.append(name)
                    if self.on_tool_start:
                        self.on_tool_start(name, arguments)
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
                    self.logger.info("tool success name=%s args=%s", name, self._safe_text(arguments))
                finally:
                    if self.on_tool_end:
                        self.on_tool_end(name, arguments, result)
                if signature is not None:
                    if signature == last_tool_signature:
                        same_tool_count += 1
                    else:
                        last_tool_signature, same_tool_count = signature, 1
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", "missing-id"),
                        "name": name,
                        "content": result,
                    }
                )
            if same_tool_count >= 3:
                messages.append({"role": "user", "content": "你刚才重复调用了相同工具。请不要重复读取相同内容；如果信息已经足够，请立即运行测试或给出最终总结。"})
                self.logger.warning("repeated tool call detected signature=%s", last_tool_signature)
                same_tool_count = 0
            if round_names and all(name in {"list_files", "read_file", "update_plan"} for name in round_names):
                inspection_rounds += 1
            elif any(name in {"run_command", "write_file", "edit_file"} for name in round_names):
                inspection_rounds = 0
            if inspection_rounds >= 3:
                messages.append({"role": "user", "content": "检查阶段已经持续多轮。请停止继续扫描文件，开始运行相关测试；如果无法运行测试，请说明原因并直接总结当前发现。"})
                self.logger.warning("inspection phase reminder sent")
                inspection_rounds = 0
        raise AgentError(f"Agent stopped after reaching the {self.max_steps}-step limit")

    @staticmethod
    def _tool_signature(name: str, arguments: Any) -> str:
        try:
            normalized = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            normalized = repr(arguments)
        return f"{name}:{normalized}"

    @staticmethod
    def _safe_text(value: Any, limit: int = 500) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = repr(value)
        return text[:limit]

    def _system_prompt(self) -> str:
        return (
            "You are a programming assistant operating on a local workspace. "
            "Use local tools when needed; the tool execution happens on the user's machine. "
            "For multi-step tasks, call update_plan first, keep it current, and mark completed steps. "
            "For project inspection tasks, inspect only the necessary files, then run tests or explain why they cannot run; do not repeatedly reread unchanged files. "
            "After the task is complete, provide a concise final answer.\n\n"
            f"Current task plan:\n{self.plan.render()}"
        )
