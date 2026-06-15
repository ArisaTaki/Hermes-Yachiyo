"""Chat delegation parsing helpers for runnable mentions."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any


class ChatRunnableMentionParser:
    """Parses Chat @mentions into runnable targets and user goals."""

    def __init__(self, *, list_runnables: Callable[[], list[dict[str, Any]]]) -> None:
        self._list_runnables = list_runnables

    def parse_known(self, text: str) -> tuple[str, str] | None:
        value = (text or "").strip()
        mention = self.mention_parts(value)
        if mention is None:
            return None
        prefix, body, remaining_lines = mention
        if not body.strip():
            return None
        if body.startswith('"') or body.startswith("'"):
            return self.parse(value)
        runnables = sorted(
            self._list_runnables(),
            key=lambda item: max(len(str(item.get("name") or "")), len(str(item.get("nickname") or ""))),
            reverse=True,
        )
        body_lower = body.lower()
        for runnable in runnables:
            aliases = [
                str(runnable.get("name") or "").strip(),
                str(runnable.get("nickname") or "").strip(),
            ]
            for name in sorted({alias for alias in aliases if alias}, key=len, reverse=True):
                if not body_lower.startswith(name.lower()):
                    continue
                remainder = body[len(name) :]
                if remainder and not remainder[0].isspace():
                    continue
                return name, self.mention_goal(prefix, remainder, remaining_lines)
        parsed = self.parse(value)
        if parsed is None:
            return None
        raw_name = str(parsed[0] or "").strip().lower()
        if raw_name in {"agent", "agents", "workflow", "workflows", "runnable", "runnables"}:
            return None
        return parsed

    @staticmethod
    def parse(text: str) -> tuple[str, str] | None:
        value = (text or "").strip()
        mention = ChatRunnableMentionParser.mention_parts(value)
        if mention is None:
            return None
        prefix, body, remaining_lines = mention
        match = re.match(r"^(?P<name>\"[^\"]+\"|'[^']+'|[^\s，。！？、；;,.!?]+)\s*(?P<body>.*)$", body)
        if not match:
            return None
        raw_name = match.group("name").strip("\"'")
        rest = match.group("body")
        return raw_name, ChatRunnableMentionParser.mention_goal(prefix, rest, remaining_lines)

    @staticmethod
    def mention_parts(text: str) -> tuple[str, str, list[str]] | None:
        value = (text or "").strip()
        if not value:
            return None
        lines = value.splitlines()
        first_line = lines[0]
        match = re.search(r"(^|[\s，。！？、；;,.!?])@(?P<body>.+)$", first_line)
        if not match:
            return None
        prefix = first_line[: match.start()].strip()
        body = match.group("body")
        return prefix, body, lines[1:]

    @staticmethod
    def mention_goal(prefix: str, remainder: str, remaining_lines: list[str]) -> str:
        first_line_parts = [part.strip() for part in (prefix, remainder) if part and part.strip()]
        first_line = " ".join(first_line_parts)
        return "\n".join([first_line, *remaining_lines]).strip()
