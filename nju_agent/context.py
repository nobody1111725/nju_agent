"""Deterministic conversation compaction for bounded model context."""

from __future__ import annotations

import json
from typing import Any


class ContextManager:
    """Keep required context and compact older tool exchanges by character budget."""

    def __init__(self, *, max_chars: int = 24_000, summary_limit: int = 4_000) -> None:
        if max_chars < 1_000:
            raise ValueError("max_chars must be at least 1000")
        self.max_chars = max_chars
        self.summary_limit = max(500, summary_limit)

    @staticmethod
    def size(messages: list[dict[str, Any]]) -> int:
        return len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")))

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.size(messages) <= self.max_chars or len(messages) <= 2:
            return messages
        head = messages[:2]
        groups = self._groups(messages[2:])
        kept: list[list[dict[str, Any]]] = []
        current_size = self.size(head)
        for group in reversed(groups):
            group_size = self.size(group)
            if kept and current_size + group_size > self.max_chars:
                break
            if not kept and current_size + group_size <= self.max_chars:
                kept.append(group)
                current_size += group_size
            elif kept and current_size + group_size <= self.max_chars:
                kept.append(group)
                current_size += group_size
            else:
                break
        kept.reverse()
        dropped = groups[: len(groups) - len(kept)]
        result = head[:]
        if dropped:
            summary = self._summarize(dropped)
            result.append({"role": "system", "content": summary})
        result.extend(message for group in kept for message in group)
        return self._trim_last_result(result)

    @staticmethod
    def _groups(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        groups: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for message in messages:
            role = message.get("role")
            if role == "assistant" and current:
                groups.append(current)
                current = []
            current.append(message)
        if current:
            groups.append(current)
        return groups

    def _summarize(self, groups: list[list[dict[str, Any]]]) -> str:
        lines = ["Earlier conversation was compacted to stay within the context budget."]
        for group in groups:
            for message in group:
                role = message.get("role", "unknown")
                if role == "tool":
                    name = message.get("name", "unknown")
                    content = str(message.get("content", "")).replace("\n", " ")
                    lines.append(f"tool {name}: {content[:500]}")
                elif role == "assistant" and message.get("tool_calls"):
                    calls = [call.get("function", {}).get("name", "unknown") for call in message["tool_calls"] if isinstance(call, dict)]
                    lines.append(f"assistant requested tools: {', '.join(calls)}")
        return "\n".join(lines)[: self.summary_limit]

    def _trim_last_result(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Guarantee a hard upper bound even when one recent result is huge."""
        if self.size(messages) <= self.max_chars:
            return messages
        for message in reversed(messages):
            content = message.get("content")
            if isinstance(content, str) and len(content) > 500:
                message["content"] = content[:500] + "...[context item truncated]"
                if self.size(messages) <= self.max_chars:
                    return messages
        return messages

