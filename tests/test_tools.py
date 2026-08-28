import tempfile
import unittest
from pathlib import Path

from nju_agent.tools import LocalTools, ToolError


class LocalToolsTests(unittest.TestCase):
    def test_file_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory))
            self.assertIn("Wrote", tools.execute("write_file", {"path": "src/main.py", "content": "print('old')\n"}))
            self.assertEqual(tools.execute("read_file", {"path": "src/main.py"}), "1: print('old')")
            tools.execute("edit_file", {"path": "src/main.py", "old_text": "old", "new_text": "new"})
            self.assertEqual(tools.execute("read_file", {"path": "src/main.py"}), "1: print('new')")

    def test_path_cannot_escape_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory))
            with self.assertRaisesRegex(ToolError, "outside the workspace"):
                tools.execute("read_file", {"path": ".."})

    def test_edit_requires_unique_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory))
            tools.execute("write_file", {"path": "a.txt", "content": "same same"})
            with self.assertRaisesRegex(ToolError, "exactly once"):
                tools.execute("edit_file", {"path": "a.txt", "old_text": "same", "new_text": "x"})

    def test_run_command_reports_exit_code_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory))
            result = tools.execute("run_command", {"command": "python -c \"import os; print(os.path.basename(os.getcwd()))\""})
            self.assertIn("exit_code: 0", result)
            self.assertIn(Path(directory).name, result)

    def test_output_is_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tools = LocalTools(Path(directory), output_limit=20)
            result = tools.execute("run_command", {"command": "python -c \"print('x' * 100)\""})
            self.assertIn("output truncated", result)


if __name__ == "__main__":
    unittest.main()
