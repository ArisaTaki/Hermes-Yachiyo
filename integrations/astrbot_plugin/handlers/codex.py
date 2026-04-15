"""/y codex <task> → Hapi（Codex 执行后端）

当前为占位实现：Hapi /codex 端点设计待确认后完整实现。
在此之前，收到 /y codex 命令直接返回占位提示，不发起网络请求。
"""

from __future__ import annotations

import logging

from ..config import PluginConfig

logger = logging.getLogger(__name__)

# Hapi /codex 端点设计未确认，暂不发起真实 HTTP 请求
_PLACEHOLDER = (
    "🤖 /y codex 即将推出\n"
    "Codex CLI 通过 Hapi 执行，后端端点正在对接中\n"
    "敬请期待"
)


async def handle(args: str, config: PluginConfig) -> str:
    if not args.strip():
        return "用法: /y codex <任务描述>"
    return _PLACEHOLDER
