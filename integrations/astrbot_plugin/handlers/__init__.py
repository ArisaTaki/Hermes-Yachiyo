"""handler 注册表与统一分发入口"""

from __future__ import annotations

from ..config import PluginConfig


def _registry() -> dict:
    """延迟加载各 handler 模块，避免循环导入。"""
    from . import cancel, check, codex, do, screen, status, tasks, window

    return {
        "status": status.handle,
        "tasks":  tasks.handle,
        "screen": screen.handle,
        "window": window.handle,
        "do":     do.handle,
        "check":  check.handle,
        "cancel": cancel.handle,
        "codex":  codex.handle,
    }


async def dispatch(command: str, args: str, config: PluginConfig) -> str:
    """根据命令名调用对应 handler 并返回响应文本。"""
    handler = _registry()[command]
    return await handler(args, config)
