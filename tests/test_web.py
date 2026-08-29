import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from nju_agent.web import AgentWebServer


class _TwoTurnClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        return {"content": f"第{self.calls}轮完成", "tool_calls": []}


class WebConversationTests(unittest.TestCase):
    def test_same_new_session_accepts_a_second_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _TwoTurnClient()
            server = AgentWebServer(("127.0.0.1", 0), Path(directory), lambda: client)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{server.server_address[1]}/api/chat/stream"

                def send(task, session_id=None):
                    body = json.dumps({"task": task, "session_id": session_id}).encode()
                    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                    return urllib.request.urlopen(request, timeout=3).read().decode()

                def complete_event(body):
                    for chunk in body.split("\n\n"):
                        if chunk.startswith("event: complete\n"):
                            return json.loads(chunk.split("data: ", 1)[1])
                    self.fail("SSE response has no complete event")

                first = send("第一轮")
                self.assertIn("event: model_response", first)
                first_event = complete_event(first)
                second = send("第二轮", first_event["id"])
                second_event = complete_event(second)

                self.assertEqual(second_event["answer"], "第2轮完成")
                self.assertEqual([item["content"] for item in second_event["messages"]], ["第一轮", "第1轮完成", "第二轮", "第2轮完成"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
