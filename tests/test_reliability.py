import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nju_agent.agent import Agent, AgentError
from nju_agent.config import Settings
from nju_agent.tools import LocalTools, ToolError


class RepeatingClient:
    def complete(self, messages, tools):
        return {
            "content": "",
            "tool_calls": [{"id": "bad", "function": {"name": "missing_tool", "arguments": "{}"}}],
        }


class ReliabilityTests(unittest.TestCase):
    def test_repeated_tool_failures_are_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AgentError, "repeated tool failure"):
                Agent(RepeatingClient(), LocalTools(Path(directory)), max_steps=8, max_repeated_errors=3).run("do it")

    def test_malformed_tool_calls_are_rejected(self) -> None:
        class Client:
            def complete(self, messages, tools):
                return {"content": "", "tool_calls": ["not an object"]}

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AgentError, "malformed tool call"):
                Agent(Client(), LocalTools(Path(directory))).run("do it")

    def test_blocked_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory))
            with self.assertRaisesRegex(ToolError, "blocked"):
                tools.execute("run_command", {"command": "git push origin main"})

    def test_dotenv_is_loaded_without_overwriting_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory, ".env")
            env_file.write_text("NJU_AGENT_MODEL=from-file\nNJU_AGENT_BASE_URL=https://file.test/v1\n", encoding="utf-8")
            with patch.dict(os.environ, {"NJU_AGENT_WORKSPACE": directory, "NJU_AGENT_MODEL": "from-env"}, clear=True), patch("pathlib.Path.cwd", return_value=Path(directory)):
                settings = Settings.from_env()
            self.assertEqual(settings.model, "from-env")
            self.assertEqual(settings.base_url, "https://file.test/v1")


if __name__ == "__main__":
    unittest.main()

