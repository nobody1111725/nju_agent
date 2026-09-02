import json
import base64
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path

from nju_agent.web import AgentWebServer


class _TwoTurnClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        return {"content": f"第{self.calls}轮完成", "tool_calls": []}


class _CaptureClient:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append(messages)
        return {"content": "已读取附件", "tool_calls": []}


class _EditClient:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1:
            return {"content": "", "tool_calls": [{"id": "edit-1", "function": {"name": "edit_file", "arguments": json.dumps({"path": "main.py", "old_text": "old", "new_text": "new"})}}]}
        return {"content": "已完成修改", "tool_calls": []}


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
                self.assertIn("event: answer", first)
                first_event = complete_event(first)
                second = send("第二轮", first_event["id"])
                second_event = complete_event(second)

                self.assertEqual(second_event["answer"], "第2轮完成")
                self.assertEqual([item["content"] for item in second_event["messages"]], ["第一轮", "第1轮完成", "第二轮", "第2轮完成"])
                self.assertEqual([item["assistant_message_index"] for item in second_event["tool_runs"]], [1, 3])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


class WebAttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.client = _CaptureClient()
        self.server = AgentWebServer(("127.0.0.1", 0), Path(self.directory.name), lambda: self.client)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def post_json(self, path, payload):
        body = json.dumps(payload).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def post_stream(self, path, payload):
        body = json.dumps(payload).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, response.read().decode()

    def delete_json(self, path):
        request = urllib.request.Request(f"{self.base_url}{path}", headers={"Content-Type": "application/json"}, method="DELETE")
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def get_json(self, path):
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=3) as response:
            return response.status, json.loads(response.read())

    def get_text(self, path):
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=3) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def test_upload_and_chat_exposes_attachment_to_agent(self) -> None:
        content = "print('hello')\n"
        status, uploaded = self.post_json("/api/uploads", {"name": "hello.py", "content_base64": base64.b64encode(content.encode()).decode()})
        self.assertEqual(status, 201)
        self.assertEqual(uploaded["name"], "hello.py")
        attachment = Path(self.directory.name) / uploaded["path"]
        self.assertTrue(attachment.is_file())
        self.assertEqual(attachment.read_text(encoding="utf-8"), content)

        status, stream = self.post_stream("/api/chat/stream", {"task": "检查附件", "attachments": [uploaded["path"]]})
        self.assertEqual(status, 200)
        self.assertIn("event: complete", stream)

        request_messages = self.client.requests[0]
        self.assertIn(uploaded["path"], request_messages[-1]["content"])
        complete = next(chunk for chunk in stream.split("\n\n") if chunk.startswith("event: complete\n"))
        event = json.loads(complete.split("data: ", 1)[1])
        self.assertEqual(event["messages"][-2]["content"], "检查附件")
        self.assertEqual(event["messages"][-2]["attachments"], [{"name": "hello.py", "size": len(content.encode())}])

        status, restored = self.get_json(f"/api/sessions/{event['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(restored["messages"][-2]["attachments"], [{"name": "hello.py", "size": len(content.encode())}])

    def test_cancel_upload_removes_temporary_attachment(self) -> None:
        content = "print('temporary')\n"
        status, uploaded = self.post_json("/api/uploads", {"name": "temporary.py", "content_base64": base64.b64encode(content.encode()).decode()})
        self.assertEqual(status, 201)
        attachment = Path(self.directory.name) / uploaded["path"]
        self.assertTrue(attachment.is_file())

        status, payload = self.delete_json(f"/api/uploads?{urllib.parse.urlencode({'path': uploaded['path']})}")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"deleted": True, "path": uploaded["path"]})
        self.assertFalse(attachment.exists())

        status, payload = self.delete_json(f"/api/uploads?{urllib.parse.urlencode({'path': uploaded['path']})}")
        self.assertEqual(status, 400)
        self.assertIn("Attachment", payload["error"])

    def test_upload_rejects_unsupported_binary_and_invalid_names(self) -> None:
        encoded = base64.b64encode(b"data").decode()
        for name in ("program.exe", "../escape.py", "folder/file.py"):
            status, payload = self.post_json("/api/uploads", {"name": name, "content_base64": encoded})
            self.assertEqual(status, 400)
            self.assertIn("error", payload)

        status, payload = self.post_json("/api/uploads", {"name": "bad.py", "content_base64": "%%%"})
        self.assertEqual(status, 400)
        self.assertIn("base64", payload["error"])

        status, payload = self.post_json("/api/uploads", {"name": "bad.py", "content_base64": base64.b64encode(b"\xff").decode()})
        self.assertEqual(status, 400)
        self.assertIn("UTF-8", payload["error"])

    def test_chat_rejects_paths_outside_upload_directory(self) -> None:
        outside = Path(self.directory.name) / "outside.py"
        outside.write_text("print(1)", encoding="utf-8")
        for path in ("outside.py", "../outside.py", ".nju-agent-attachments/missing.py"):
            status, payload = self.post_json("/api/chat/stream", {"task": "读取", "attachments": [path]})
            self.assertEqual(status, 400)
            self.assertIn("Attachment", payload["error"])

    def test_chat_rejects_more_than_ten_attachments(self) -> None:
        paths = [f".nju-agent-attachments/{index}/file.py" for index in range(11)]
        status, payload = self.post_json("/api/chat/stream", {"task": "读取", "attachments": paths})
        self.assertEqual(status, 400)
        self.assertIn("at most 10", payload["error"])

    def test_upload_rejects_file_larger_than_two_megabytes(self) -> None:
        content = b"a" * (2 * 1024 * 1024 + 1)
        status, payload = self.post_json("/api/uploads", {"name": "large.txt", "content_base64": base64.b64encode(content).decode()})
        self.assertEqual(status, 400)
        self.assertIn("2 MB", payload["error"])

    def test_edit_tool_stream_includes_file_diff(self) -> None:
        Path(self.directory.name, "main.py").write_text("old\nkeep\n", encoding="utf-8")
        self.client = _EditClient()
        self.server.client_factory = lambda: self.client
        status, stream = self.post_stream("/api/chat/stream", {"task": "修改 main.py"})
        self.assertEqual(status, 200)
        events = []
        for chunk in stream.split("\n\n"):
            if chunk.startswith("event: tool_end\n"):
                events.append(json.loads(chunk.split("data: ", 1)[1]))
        self.assertEqual(len(events), 1)
        diff = events[0].get("diff")
        self.assertIsNotNone(diff)
        self.assertEqual(diff["path"], "main.py")
        self.assertIn("-old", diff["lines"])
        self.assertIn("+new", diff["lines"])
        complete = next(chunk for chunk in stream.split("\n\n") if chunk.startswith("event: complete\n"))
        saved = json.loads(complete.split("data: ", 1)[1])
        self.assertEqual(saved["tool_runs"][0]["task"], "修改 main.py")
        self.assertEqual(saved["tool_runs"][0]["assistant_message_index"], 1)
        self.assertEqual(saved["tool_runs"][0]["events"][0]["diff"]["path"], "main.py")

        status, restored = self.get_json(f"/api/sessions/{saved['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(restored["tool_runs"], saved["tool_runs"])

    def test_modified_file_endpoint_opens_only_files_from_session_diffs(self) -> None:
        Path(self.directory.name, "main.py").write_text("print('current')\n", encoding="utf-8")
        Path(self.directory.name, "unrelated.py").write_text("print('private')\n", encoding="utf-8")
        session = self.server.store.create()
        session.tool_runs = [{"id": "run-1", "events": [{"diff": {"path": "main.py"}}]}]
        self.server.store.save(session)
        query = urllib.parse.urlencode({"session_id": session.id, "path": "main.py"})

        status, content = self.get_text(f"/api/modified-file?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(content, "print('current')\n")

        query = urllib.parse.urlencode({"session_id": session.id, "path": "unrelated.py"})
        status, content = self.get_text(f"/api/modified-file?{query}")
        self.assertEqual(status, 400)
        self.assertIn("not modified", content)

    def test_delete_session_removes_entire_saved_record(self) -> None:
        status, stream = self.post_stream("/api/chat/stream", {"task": "需要删除的会话"})
        self.assertEqual(status, 200)
        complete = next(chunk for chunk in stream.split("\n\n") if chunk.startswith("event: complete\n"))
        event = json.loads(complete.split("data: ", 1)[1])
        session_id = event["id"]
        short_id = event["short_id"]

        status, deleted = self.delete_json(f"/api/sessions/{short_id}")
        self.assertEqual(status, 200)
        self.assertEqual(deleted, {"deleted": True, "id": session_id, "short_id": short_id})

        status, sessions = self.get_json("/api/sessions")
        self.assertEqual(status, 200)
        self.assertFalse(any(item["id"] == session_id for item in sessions["sessions"]))
        status, payload = self.delete_json(f"/api/sessions/{session_id}")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "Session not found")


if __name__ == "__main__":
    unittest.main()
