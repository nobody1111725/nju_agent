import tempfile
import unittest
from pathlib import Path

from nju_agent.agent import Agent
from nju_agent.tools import LocalTools


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def complete(self, messages, tools):
        self.calls.append((messages, tools))
        return next(self.responses)


class AgentTests(unittest.TestCase):
    def test_final_answer_without_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient([{"content": "完成了", "tool_calls": []}])
            answer = Agent(client, LocalTools(Path(directory))).run("做一件事")
            self.assertEqual(answer, "完成了")
            self.assertEqual(len(client.calls), 1)

    def test_tool_call_is_executed_and_returned_to_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "hello.txt").write_text("hello", encoding="utf-8")
            client = FakeClient(
                [
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {"name": "list_files", "arguments": "{}"},
                            }
                        ],
                    },
                    {"content": "工作区包含 hello.txt", "tool_calls": []},
                ]
            )
            answer = Agent(client, LocalTools(Path(directory))).run("查看文件")
            self.assertEqual(answer, "工作区包含 hello.txt")
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(client.calls[1][0][-1]["role"], "tool")
            self.assertIn("hello.txt", client.calls[1][0][-1]["content"])


if __name__ == "__main__":
    unittest.main()

