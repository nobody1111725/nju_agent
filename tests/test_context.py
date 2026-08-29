import tempfile
import unittest
from pathlib import Path

from nju_agent.context import ContextManager
from nju_agent.tools import LocalTools


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


if __name__ == "__main__":
    unittest.main()
