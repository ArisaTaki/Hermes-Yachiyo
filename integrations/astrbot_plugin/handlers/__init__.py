"""handler 注册表与统一分发入口"""

from __future__ import annotations

from ..config import PluginConfig


def _registry() -> dict:
    """延迟加载各 handler 模块，避免循环导入。"""
    from . import ask, cancel, check, codex, do, screen, status, tasks, window

    return {
        "status": status.handle,
        "tasks":  tasks.handle,
        "screen": screen.handle,
        "window": window.handle,
        "do":     do.handle,
        "ask":    ask.handle,
        "chat":   ask.handle,
        "check":  check.handle,
        "cancel": cancel.handle,
        "codex":  codex.handle,
    }


async def dispatch(command: str, args: str, config: PluginConfig, sender_id: str = "") -> str:
    """根据命令名调用对应 handler 并返回响应文本。"""
    handler = _registry()[command]
    if command in {"ask", "chat"}:
        return await handler(args, config, sender_id=sender_id)
    return await handler(args, config)
