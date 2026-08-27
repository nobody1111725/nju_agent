"""Small OpenAI-compatible chat-completions client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ModelError(RuntimeError):
    """Raised when a model request fails or returns an invalid response."""


class ChatClient:
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"model": self.model, "messages": messages, "tools": tools}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            raise ModelError(f"Model request failed: {exc}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelError("Model returned invalid JSON") from exc

        try:
            message = result["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("Model response has no choices[0].message") from exc
        if not isinstance(message, dict):
            raise ModelError("Model message is not an object")
        return message

