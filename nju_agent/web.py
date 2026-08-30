"""Local web UI and HTTP API for the programming Agent."""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import queue
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .agent import Agent, AgentError
from .cli import TerminalToolDisplay
from .model import ChatClient, ModelError
from .session import Session, SessionError, SessionStore
from .tools import LocalTools


WEB_ROOT = Path(__file__).with_name("web")
ATTACHMENT_ROOT_NAME = ".nju-agent-attachments"
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENTS_PER_TURN = 10
ALLOWED_ATTACHMENT_EXTENSIONS = frozenset(
    {
        ".bat", ".c", ".cc", ".cmake", ".cpp", ".css", ".csv", ".cxx", ".go", ".h", ".hpp",
        ".htm", ".html", ".ini", ".java", ".js", ".json", ".jsonl", ".jsx", ".md", ".ps1",
        ".py", ".pyi", ".rs", ".sh", ".sql", ".toml", ".ts", ".tsv", ".tsx", ".txt", ".xml",
        ".yaml", ".yml",
    }
)
ALLOWED_ATTACHMENT_FILENAMES = frozenset({"makefile", "dockerfile"})


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _chat_messages(session: Session) -> list[dict[str, str]]:
    return [
        {"role": str(item["role"]), "content": str(item["content"])}
        for item in session.messages
        if isinstance(item, dict)
        if item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str)
        and item.get("content", "").strip()
    ]


class AgentWebHandler(BaseHTTPRequestHandler):
    server: "AgentWebServer"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/sessions":
            self._sessions()
            return
        if parsed.path.startswith("/api/sessions/"):
            self._session(unquote(parsed.path.rsplit("/", 1)[-1]))
            return
        self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/uploads":
            self._upload()
            return
        if path != "/api/chat/stream":
            self._json_response({"error": "Not found"}, 404)
            return
        self._chat_stream()

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/sessions/"):
            self._delete_session(unquote(parsed.path.rsplit("/", 1)[-1]))
            return
        self._json_response({"error": "Not found"}, 404)

    def _read_json_body(self, *, maximum_bytes: int = 3 * 1024 * 1024) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > maximum_bytes:
            raise ValueError(f"Request body must be between 1 byte and {maximum_bytes} bytes")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def _upload(self) -> None:
        try:
            payload = self._read_json_body()
            name = payload.get("name")
            encoded = payload.get("content_base64")
            if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
                raise ValueError("Attachment name must be a plain file name")
            if name.lower() not in ALLOWED_ATTACHMENT_FILENAMES and Path(name).suffix.lower() not in ALLOWED_ATTACHMENT_EXTENSIONS:
                raise ValueError("Unsupported attachment type")
            if not isinstance(encoded, str):
                raise ValueError("Attachment content must be base64 text")
            try:
                content = base64.b64decode(encoded, validate=True)
            except binascii.Error as exc:
                raise ValueError("Attachment content must be valid base64") from exc
            try:
                content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Attachment must be valid UTF-8 text") from exc
            if len(content) > MAX_ATTACHMENT_BYTES:
                raise ValueError(f"Attachment exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit")
            relative = Path(ATTACHMENT_ROOT_NAME) / uuid.uuid4().hex / name
            target = (self.server.workspace / relative).resolve()
            target.parent.mkdir(parents=True, exist_ok=False)
            target.write_bytes(content)
        except (OSError, ValueError) as exc:
            self._json_response({"error": str(exc)}, 400)
            return
        self._json_response({"name": name, "path": relative.as_posix(), "size": len(content)}, 201)

    def _sessions(self) -> None:
        try:
            sessions = self.server.store.list()
            self._json_response({"sessions": [{"id": item.id, "short_id": item.short_id, "updated_at": item.updated_at, "messages": _chat_messages(item)} for item in sessions]})
        except SessionError as exc:
            self._json_response({"error": str(exc)}, 500)

    def _session(self, session_id: str) -> None:
        try:
            session = self.server.store.load(session_id)
        except SessionError as exc:
            self._json_response({"error": str(exc)}, 500)
            return
        if session is None:
            self._json_response({"error": "Session not found"}, 404)
            return
        self._json_response({"id": session.id, "short_id": session.short_id, "updated_at": session.updated_at, "messages": _chat_messages(session)})

    def _delete_session(self, session_id: str) -> None:
        if not session_id:
            self._json_response({"error": "Session ID is required"}, 400)
            return
        try:
            deleted = self.server.store.delete(session_id)
        except SessionError as exc:
            self._json_response({"error": str(exc)}, 500)
            return
        if deleted is None:
            self._json_response({"error": "Session not found"}, 404)
            return
        self._json_response({"deleted": True, "id": deleted.id, "short_id": deleted.short_id})

    def _chat_stream(self) -> None:
        try:
            payload = self._read_json_body(maximum_bytes=128 * 1024)
            task = payload.get("task", "")
            requested_id = payload.get("session_id")
            attachment_paths = self._attachment_paths(payload.get("attachments", []))
            if not isinstance(task, str) or not task.strip():
                raise ValueError("task must be a non-empty string")
            if requested_id is not None and not isinstance(requested_id, str):
                raise ValueError("session_id must be a string")
            session = self.server.store.load(requested_id) if requested_id else None
            if requested_id and session is None:
                raise ValueError("session not found")
        except (ValueError, json.JSONDecodeError, SessionError) as exc:
            self._json_response({"error": str(exc)}, 400)
            return

        if session is None:
            session = self.server.store.create()
        local_tools = LocalTools(self.server.workspace)
        events: queue.Queue[dict[str, Any]] = queue.Queue()
        finished = threading.Event()
        result: dict[str, Any] = {}

        def on_start(name: str, arguments: Any) -> None:
            events.put({"event": "tool_start", "name": name, "label": TerminalToolDisplay._label(name, arguments)})

        def on_end(name: str, arguments: Any, output: str | None) -> None:
            success = output is not None and not output.startswith("Tool error:")
            event: dict[str, Any] = {"event": "tool_end", "name": name, "label": TerminalToolDisplay._label(name, arguments), "status": "done" if success else "failed"}
            if success and local_tools.last_diff is not None and name in {"write_file", "edit_file"}:
                event["diff"] = local_tools.last_diff
            events.put(event)

        def on_model_response() -> None:
            events.put({"event": "model_response"})

        def run() -> None:
            agent: Agent | None = None
            try:
                agent = Agent(self.server.client_factory(), local_tools, on_tool_start=on_start, on_tool_end=on_end, on_model_response=on_model_response)
                if session.messages:
                    agent.plan.restore(session.plan)
                agent_task = self._task_with_attachments(task, attachment_paths)
                answer = agent.run(agent_task, history=session.messages if session.messages else None, resume=bool(session.messages))
                session.messages = self._persisted_messages(agent.last_messages, agent_task, task)
                session.plan = agent.plan.snapshot()
                self.server.store.save(session)
                result.update({"id": session.id, "short_id": session.short_id, "answer": answer, "messages": _chat_messages(session)})
            except (AgentError, ModelError, SessionError) as exc:
                # A new session should remain recoverable even if the first
                # model call cannot leave this machine.
                if agent is not None and agent.last_messages:
                    session.messages = self._persisted_messages(agent.last_messages, self._task_with_attachments(task, attachment_paths), task)
                    session.plan = agent.plan.snapshot()
                try:
                    self.server.store.save(session)
                    result.update({"id": session.id, "short_id": session.short_id, "messages": _chat_messages(session)})
                except SessionError as save_error:
                    result["save_error"] = str(save_error)
                result["error"] = str(exc)
            finally:
                finished.set()

        threading.Thread(target=run, daemon=True).start()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # One response represents one complete Agent turn. Closing it after
        # the `complete` event lets the browser finish reading and re-enable
        # the composer for the next turn.
        self.send_header("Connection", "close")
        self.end_headers()
        while not finished.is_set() or not events.empty():
            try:
                event = events.get(timeout=0.2)
            except queue.Empty:
                continue
            self._sse(event)
        self._sse({"event": "complete", **result})
        self.close_connection = True

    def _attachment_paths(self, values: Any) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list) or len(values) > MAX_ATTACHMENTS_PER_TURN:
            raise ValueError(f"attachments must contain at most {MAX_ATTACHMENTS_PER_TURN} files")
        root = (self.server.workspace / ATTACHMENT_ROOT_NAME).resolve()
        paths: list[str] = []
        for value in values:
            if not isinstance(value, str):
                raise ValueError("attachment paths must be strings")
            target = (self.server.workspace / value).resolve()
            if root not in target.parents or not target.is_file():
                raise ValueError("Attachment is unavailable or outside the upload area")
            relative = target.relative_to(self.server.workspace).as_posix()
            if relative not in paths:
                paths.append(relative)
        return paths

    @staticmethod
    def _task_with_attachments(task: str, paths: list[str]) -> str:
        if not paths:
            return task
        listed = "\n".join(f"- {path}" for path in paths)
        return f"{task}\n\n附件已保存到本地工作区。需要时请先使用 read_file 查看：\n{listed}"

    @staticmethod
    def _persisted_messages(messages: list[dict[str, Any]], agent_task: str, task: str) -> list[dict[str, Any]]:
        """Keep attachment instructions out of the chat transcript shown to users."""
        persisted = [dict(message) for message in messages]
        for message in reversed(persisted):
            if message.get("role") == "user" and message.get("content") == agent_task:
                message["content"] = task
                break
        return persisted

    def _sse(self, event: dict[str, Any]) -> None:
        name = event.get("event", "message")
        data = json.dumps({key: value for key, value in event.items() if key != "event"}, ensure_ascii=False)
        self.wfile.write(f"event: {name}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (WEB_ROOT / relative).resolve()
        if WEB_ROOT.resolve() not in target.parents and target != WEB_ROOT.resolve():
            self._json_response({"error": "Not found"}, 404)
            return
        if not target.is_file():
            self._json_response({"error": "Not found"}, 404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_response(self, payload: dict[str, Any], status: int = 200) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class AgentWebServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], workspace: Path, client_factory):
        super().__init__(address, AgentWebHandler)
        self.workspace = workspace.resolve()
        self.store = SessionStore(self.workspace)
        self.client_factory = client_factory


def serve(workspace: Path, *, host: str = "127.0.0.1", port: int = 8765, api_key: str, base_url: str, model: str) -> None:
    def client_factory() -> ChatClient:
        return ChatClient(api_key=api_key, base_url=base_url, model=model)

    server = AgentWebServer((host, port), workspace, client_factory)
    print(f"nju-agent web UI: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
