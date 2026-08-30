"""Local, recoverable conversation session storage."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SessionError(RuntimeError):
    """Raised when persisted session data cannot be read or written."""


@dataclass
class Session:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @property
    def short_id(self) -> str:
        return self.id[:8]


class SessionStore:
    """Persist sessions in one atomic JSON file inside the configured workspace."""

    def __init__(self, workspace: Path, *, filename: str = ".nju-agent-sessions.json") -> None:
        self.workspace = workspace.resolve()
        self.path = self.workspace / filename

    def create(self) -> Session:
        now = _now()
        return Session(uuid.uuid4().hex, created_at=now, updated_at=now)

    def list(self) -> list[Session]:
        data = self._read()
        sessions = [_from_dict(item) for item in data.get("sessions", [])]
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def load(self, session_id: str | None = None) -> Session | None:
        sessions = self.list()
        if session_id is None:
            return sessions[0] if sessions else None
        for session in sessions:
            if session.id == session_id or session.short_id == session_id:
                return session
        return None

    def delete(self, session_id: str) -> Session | None:
        """Delete one saved session by its full or short identifier."""
        sessions = self.list()
        selected = next((item for item in sessions if item.id == session_id or item.short_id == session_id), None)
        if selected is None:
            return None
        payload = {"version": 1, "sessions": [_to_dict(item) for item in sessions if item.id != selected.id]}
        self._write(payload)
        return selected

    def save(self, session: Session) -> None:
        sessions = self.list()
        existing = next((item for item in sessions if item.id == session.id), None)
        if existing is None:
            session.created_at = session.created_at or _now()
        session.updated_at = _now()
        sessions = [item for item in sessions if item.id != session.id]
        sessions.insert(0, session)
        payload = {"version": 1, "sessions": [_to_dict(item) for item in sessions]}
        self._write(payload)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "sessions": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SessionError(f"Unable to read session store: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("sessions", []), list):
            raise SessionError("Session store has an invalid format")
        return data

    def _write(self, payload: dict[str, Any]) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            fd, temporary = tempfile.mkstemp(prefix=".nju-agent-sessions-", suffix=".tmp", dir=self.workspace)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temporary, self.path)
            temporary = None
        except OSError as exc:
            raise SessionError(f"Unable to save session store: {exc}") from exc
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dict(session: Session) -> dict[str, Any]:
    return {"id": session.id, "messages": session.messages, "plan": session.plan, "created_at": session.created_at, "updated_at": session.updated_at}


def _from_dict(data: Any) -> Session:
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not isinstance(data.get("messages", []), list):
        raise SessionError("Session store contains an invalid session")
    return Session(
        id=data["id"],
        messages=data.get("messages", []),
        plan=data.get("plan", {}) if isinstance(data.get("plan", {}), dict) else {},
        created_at=str(data.get("created_at", "")),
        updated_at=str(data.get("updated_at", "")),
    )
