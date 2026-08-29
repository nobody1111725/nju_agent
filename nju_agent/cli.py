"""Command-line entry point for the programming Agent."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from typing import Any

from .config import ConfigurationError, Settings
from .agent import Agent, AgentError
from .model import ChatClient, ModelError
from .tools import LocalTools


class TerminalToolDisplay:
    """Render live tool activity with a lightweight terminal spinner."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active = False

    def start(self, name: str, arguments: Any) -> None:
        label = self._label(name, arguments)
        self._stop.clear()
        with self._lock:
            self._active = True
        if not sys.stdout.isatty():
            print(f"Tool> {label}", flush=True)
            return
        self._thread = threading.Thread(target=self._animate, args=(label,), daemon=True)
        self._thread.start()

    def end(self, name: str, arguments: Any, result: str | None) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        success = result is not None and not result.startswith("Tool error:")
        status = "done" if success else "failed"
        with self._lock:
            self._active = False
        if sys.stdout.isatty():
            print(f"\r\x1b[2KTool> [{status}] {self._label(name, arguments)}", flush=True)
        else:
            print(f"Tool> [{status}] {self._label(name, arguments)}", flush=True)

    def _animate(self, label: str) -> None:
        frames = "|/-\\"
        index = 0
        while not self._stop.is_set():
            emphasis = "\x1b[1m" if index % 2 == 0 else "\x1b[2m"
            print(f"\r\x1b[2K{emphasis}Tool {frames[index % len(frames)]}\x1b[0m {label}", end="", flush=True)
            index += 1
            time.sleep(0.12)

    @staticmethod
    def _label(name: str, arguments: Any) -> str:
        arguments = TerminalToolDisplay._parse_arguments(arguments)
        if name == "run_command" and isinstance(arguments, dict):
            command = str(arguments.get("command", ""))
            return f"run_command: {command[:240]}"
        if name == "read_file" and isinstance(arguments, dict):
            path = arguments.get("path", "?")
            start = arguments.get("start_line", 1)
            end = arguments.get("end_line", "end")
            return f"read_file: path={path}, lines={start}-{end}"
        if name == "write_file" and isinstance(arguments, dict):
            path = arguments.get("path", "?")
            content = arguments.get("content", "")
            size = len(content) if isinstance(content, str) else "?"
            return f"write_file: path={path}, chars={size}"
        if name == "edit_file" and isinstance(arguments, dict):
            path = arguments.get("path", "?")
            old_text = arguments.get("old_text", "")
            new_text = arguments.get("new_text", "")
            old_size = len(old_text) if isinstance(old_text, str) else "?"
            new_size = len(new_text) if isinstance(new_text, str) else "?"
            return f"edit_file: path={path}, replace_chars={old_size}->{new_size}"
        if name == "list_files" and isinstance(arguments, dict):
            return f"list_files: {arguments.get('path', '.')}"
        if name == "update_plan":
            if isinstance(arguments, dict):
                steps = arguments.get("steps", [])
                current = arguments.get("current_step", "?")
                count = len(steps) if isinstance(steps, list) else "?"
                return f"update_plan: steps={count}, current={current}"
            return "update_plan"
        # Keep the invocation visible even when a model returns an unfamiliar
        # argument shape or a newly added tool is not yet covered above.
        if arguments in (None, "", {}):
            return name
        try:
            details = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            details = repr(arguments)
        return f"{name}: args={details[:240]}"

    @staticmethod
    def _parse_arguments(arguments: Any) -> Any:
        if not isinstance(arguments, str):
            return arguments
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        # Some OpenAI-compatible clients serialize the arguments field twice.
        if isinstance(parsed, str):
            try:
                return json.loads(parsed)
            except json.JSONDecodeError:
                return parsed
        return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nju-agent", description="A local programming-agent scaffold.")
    parser.add_argument("--version", action="version", version="nju-agent 0.5.3")
    return parser


def run_interactive(settings: Settings) -> int:
    print("nju-agent 0.5.3")
    print(f"Workspace: {settings.workspace}")
    logging.basicConfig(filename=settings.workspace / ".nju-agent.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    display = TerminalToolDisplay()
    agent = None
    if settings.api_key and settings.model:
        print(f"Model configuration found: {settings.model}")
        agent = Agent(
            ChatClient(api_key=settings.api_key, base_url=settings.base_url, model=settings.model),
            LocalTools(settings.workspace),
            on_tool_start=display.start,
            on_tool_end=display.end,
        )
    else:
        print("Model configuration is not set; running in scaffold mode.")
    print("Type a task, or press Ctrl-D/Ctrl-Z to exit.")

    while True:
        try:
            task = input("\nYou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0
        if task:
            if agent is None:
                print("Agent> Please set NJU_AGENT_API_KEY and NJU_AGENT_MODEL first.")
                continue
            try:
                answer = agent.run(task)
                print(f"Agent> {answer}")
                if agent.plan.steps:
                    print(f"Plan>\n{agent.plan.render()}")
            except KeyboardInterrupt:
                print("\nAgent> Task interrupted.")
            except (AgentError, ModelError) as exc:
                print(f"Agent error> {exc}")


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    return run_interactive(settings)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
