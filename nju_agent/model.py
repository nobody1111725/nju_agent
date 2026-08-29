"""Small OpenAI-compatible chat-completions client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ModelError(RuntimeError):
    """Raised when a model request fails or returns an invalid response."""


class ChatClient:
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout: float = 60.0, max_retries: int = 2) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

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
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise ModelError(self._request_error_message(exc, attempt + 1)) from exc
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ModelError("Model returned invalid JSON") from exc
        else:
            raise ModelError(f"Model request failed: {last_error}")

        try:
            message = result["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("Model response has no choices[0].message") from exc
        if not isinstance(message, dict):
            raise ModelError("Model message is not an object")
        return message

    @staticmethod
    def _request_error_message(error: Exception, attempts: int) -> str:
        """Turn common local network failures into actionable user messages."""
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        if isinstance(reason, PermissionError) and (
            getattr(reason, "winerror", None) == 10013 or getattr(reason, "errno", None) == 10013
        ):
            return (
                "模型请求失败：Windows 拒绝了当前 Python 的网络访问（WinError 10013）。"
                "新会话已创建，但无法连接模型。请检查防火墙、网络代理或安全软件，"
                "并确认运行 nju-agent 的 Python 已获准访问 HTTPS 网络。"
            )
        if isinstance(reason, TimeoutError):
            return f"模型请求在 {attempts} 次尝试后超时，请检查网络连接或稍后重试。"
        return f"模型请求在 {attempts} 次尝试后失败：{error}"
