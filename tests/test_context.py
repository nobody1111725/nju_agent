import tempfile
import unittest
from pathlib import Path

from nju_agent.context import ContextManager
from nju_agent.tools import LocalTools
from nju_agent.session import SessionStore
from nju_agent.session import Session


class ContextAndPlanTests(unittest.TestCase):
    def test_old_tool_exchanges_are_compacted(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
        ]
        for index in range(8):
            messages.extend(
                [
                    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file"}}]},
                    {"role": "tool", "name": "read_file", "content": "x" * 500},
                ]
            )
        compacted = ContextManager(max_chars=2_500, summary_limit=500).compact(messages)
        self.assertLessEqual(ContextManager.size(compacted), 2_500)
        self.assertTrue(any("Earlier conversation was compacted" in str(item.get("content")) for item in compacted))
        self.assertEqual(compacted[0]["role"], "system")
        self.assertEqual(compacted[1]["role"], "user")

    def test_plan_tool_tracks_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory))
            result = tools.execute("update_plan", {"steps": ["读取代码", "修复问题", "运行测试"], "current_step": 1})
            self.assertIn(">] 1. 读取代码", result)
            result = tools.execute("update_plan", {"completed_steps": [1], "current_step": 2})
            self.assertIn("[x] 1. 读取代码", result)
            self.assertIn(">] 2. 修复问题", result)

    def test_empty_saved_plan_restores_as_no_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory))
            tools.plan.update({"steps": ["临时步骤"], "current_step": 1})
            tools.plan.restore({"steps": [], "completed_steps": [], "current_step": None, "note": ""})
            self.assertEqual(tools.plan.steps, [])

    def test_saved_session_history_contains_human_chat(self) -> None:
        session = Session(
            "12345678abcdef",
            messages=[
                {"role": "system", "content": "internal prompt"},
                {"role": "user", "content": "第一次问题"},
                {"role": "assistant", "content": "第一次回答"},
                {"role": "tool", "content": "内部工具结果"},
            ],
        )
        from io import StringIO
        from unittest.mock import patch
        from nju_agent.cli import _print_session_history

        output = StringIO()
        with patch("nju_agent.cli.sys.stdout", output):
            _print_session_history(session)
        rendered = output.getvalue()
        self.assertIn("You> 第一次问题", rendered)
        self.assertIn("Agent> 第一次回答", rendered)
        self.assertNotIn("internal prompt", rendered)
        self.assertNotIn("内部工具结果", rendered)

    def test_plan_resets_between_agent_tasks(self) -> None:
        class Client:
            def __init__(self):
                self.calls = 0

            def complete(self, messages, tools):
                self.calls += 1
                if self.calls == 1:
                    return {"content": "", "tool_calls": [{"id": "p", "function": {"name": "update_plan", "arguments": '{"steps":["第一步"],"current_step":1}'}}]}
                return {"content": "完成", "tool_calls": []}

        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            from nju_agent.agent import Agent

            agent = Agent(client, LocalTools(Path(directory)))
            agent.run("第一个任务")
            self.assertEqual(agent.plan.steps, ["第一步"])
            agent.run("第二个任务")
            self.assertEqual(agent.plan.steps, [])

    def test_sessions_round_trip_and_short_id_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            session = store.create()
            session.messages = [{"role": "user", "content": "继续修复"}]
            session.plan = {"steps": ["修复"], "current_step": 1}
            store.save(session)
            loaded = store.load(session.short_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.id, session.id)
            self.assertEqual(loaded.messages[0]["content"], "继续修复")
            self.assertEqual(store.list()[0].id, session.id)

    def test_agent_appends_final_answer_to_resumed_history(self) -> None:
        class Client:
            def complete(self, messages, tools):
                return {"content": "第二次完成", "tool_calls": []}

        with tempfile.TemporaryDirectory() as directory:
            from nju_agent.agent import Agent

            agent = Agent(Client(), LocalTools(Path(directory)))
            history = [{"role": "system", "content": "system"}, {"role": "user", "content": "第一次"}, {"role": "assistant", "content": "第一次完成"}]
            answer = agent.run("第二次", history=history, resume=True)
            self.assertEqual(answer, "第二次完成")
            self.assertEqual(agent.last_messages[-1], {"role": "assistant", "content": "第二次完成"})

    def test_agent_preserves_full_history_when_request_is_compacted(self) -> None:
        class Client:
            def __init__(self):
                self.requests = []

            def complete(self, messages, tools):
                self.requests.append(messages)
                if len(self.requests) == 1:
                    return {"content": "", "tool_calls": [{"id": "r", "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'}}]}
                return {"content": "完成", "tool_calls": []}

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "a.txt").write_text("x" * 600, encoding="utf-8")
            from nju_agent.agent import Agent

            client = Client()
            agent = Agent(client, LocalTools(Path(directory)), max_context_chars=1_000)
            agent.run("读取文件")
            self.assertGreater(len(agent.last_messages), len(client.requests[-1]))
            self.assertEqual(agent.last_messages[1]["content"], "读取文件")
            self.assertEqual(agent.last_messages[-1]["content"], "完成")

    def test_web_arguments_are_available_from_cli(self) -> None:
        from nju_agent.cli import build_parser

        args = build_parser().parse_args(["--web", "--host", "0.0.0.0", "--port", "9000"])
        self.assertTrue(args.web)
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9000)


if __name__ == "__main__":
    unittest.main()
