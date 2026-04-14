"""/y codex <task> → Hapi（Codex 执行后端）

当前为占位实现：Hapi /codex 端点设计待确认后完整实现。
"""

from __future__ import annotations

import logging

from ..api_client import HapiClient
from ..config import PluginConfig

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    if not args.strip():
        return "用法: /y codex <任务描述>"

    # TODO: 确认 Hapi /codex 请求/响应 schema 后完整实现
    client = HapiClient(config)
    data = await client.run_codex(args.strip())

    result = data.get("result", "（无输出）")
    return f"🤖 Codex 执行结果\n{result}"
