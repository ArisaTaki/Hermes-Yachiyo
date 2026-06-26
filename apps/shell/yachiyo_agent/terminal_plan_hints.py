"""Terminal command hints for capability-first planning."""

from __future__ import annotations

import re


def terminal_command_hint(text: str) -> dict[str, str]:
    value = str(text or "").strip()
    if not value:
        return {}
    patterns = (
        r"(?:打开|启动|开启|拉起|open|launch|start)?\s*"
        r"(?:终端|命令行|terminal|shell)\s*(?:里|中|上|内|app|应用)?\s*"
        r"(?:运行|执行|跑|run|execute)\s*(?P<command>[^。！？!?]+)",
        r"(?:运行|执行|跑|run|execute)\s+(?P<command>[^。！？!?]+?)\s*"
        r"(?:在|用|通过|in|with|using)\s*(?:终端|命令行|terminal|shell)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        command = _clean_terminal_command(match.group("command"))
        if command:
            return {"command": command}
    return {}


def _clean_terminal_command(value: str) -> str:
    command = str(value or "").strip()
    command = re.sub(r"\s*(?:一下|下|吧|吗|嘛|呢)$", "", command, flags=re.IGNORECASE).strip()
    command = command.strip("「」『』“”\"'`")
    if command in {"", "起来", "一下", "下"}:
        return ""
    return command
