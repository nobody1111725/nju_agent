import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from nju_agent.agent import Agent
from nju_agent.cli import TerminalToolDisplay
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

    def test_repeated_tool_calls_receive_progress_reminder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "hello.txt").write_text("hello", encoding="utf-8")
            tool_response = {
                "content": "",
                "tool_calls": [{"id": "call", "function": {"name": "read_file", "arguments": '{"path":"hello.txt"}'}}],
            }
            client = FakeClient([tool_response, tool_response, tool_response, {"content": "已完成", "tool_calls": []}])
            answer = Agent(client, LocalTools(Path(directory)), max_steps=6).run("检查文件")
            self.assertEqual(answer, "已完成")
            self.assertTrue(any("重复调用了相同工具" in str(message.get("content")) for message in client.calls[3][0]))

    def test_tool_observers_receive_start_and_end_events(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            events = []
            client = FakeClient(
                [
                    {"content": "", "tool_calls": [{"id": "call", "function": {"name": "list_files", "arguments": "{}"}}]},
                    {"content": "完成", "tool_calls": []},
                ]
            )
            answer = Agent(
                client,
                LocalTools(Path(directory)),
                on_tool_start=lambda name, arguments: events.append(("start", name)),
                on_tool_end=lambda name, arguments, result: events.append(("end", name, result is not None)),
            ).run("查看目录")
            self.assertEqual(answer, "完成")
            self.assertEqual(events[0], ("start", "list_files"))
            self.assertEqual(events[1], ("end", "list_files", True))

    def test_terminal_display_parses_json_tool_arguments(self) -> None:
        self.assertEqual(
            TerminalToolDisplay._label("read_file", '{"path":"print_1_to_100.cpp","start_line":1,"end_line":20}'),
            "read_file: path=print_1_to_100.cpp, lines=1-20",
        )
        self.assertEqual(
            TerminalToolDisplay._label("write_file", '{"path":"main.py","content":"print(1)"}'),
            "write_file: path=main.py, chars=8",
        )

    def test_terminal_display_renders_detailed_output(self) -> None:
        output = StringIO()
        with patch("nju_agent.cli.sys.stdout", output):
            display = TerminalToolDisplay()
            display.start("read_file", '{"path":"src/main.py","start_line":3,"end_line":9}')
            display.end("read_file", '{"path":"src/main.py","start_line":3,"end_line":9}', "3: pass")
        self.assertIn("Tool> read_file: path=src/main.py, lines=3-9", output.getvalue())
        self.assertIn("Tool> [done] read_file: path=src/main.py, lines=3-9", output.getvalue())

    def test_terminal_display_keeps_unknown_arguments_visible(self) -> None:
        self.assertEqual(
            TerminalToolDisplay._label("new_tool", '{"path":"a.txt","mode":"fast"}'),
            'new_tool: args={"path":"a.txt","mode":"fast"}',
        )


if __name__ == "__main__":
    unittest.main()
