"""Command-line entry point for the programming Agent."""

from __future__ import annotations

import argparse
import sys

from .config import ConfigurationError, Settings
from .agent import Agent, AgentError
from .model import ChatClient, ModelError
from .tools import LocalTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nju-agent", description="A local programming-agent scaffold.")
    parser.add_argument("--version", action="version", version="nju-agent 0.2.0")
    return parser


def run_interactive(settings: Settings) -> int:
    print("nju-agent 0.2.0")
    print(f"Workspace: {settings.workspace}")
    agent = None
    if settings.api_key and settings.model:
        print(f"Model configuration found: {settings.model}")
        agent = Agent(ChatClient(api_key=settings.api_key, base_url=settings.base_url, model=settings.model), LocalTools(settings.workspace))
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
                print(f"Agent> {agent.run(task)}")
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
