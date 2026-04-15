"""/y do <task> → POST /tasks"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig
from .utils import fmt_status

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    if not args.strip():
        return "用法: /y do <任务描述>"

    client = HermesClient(config)
    data = await client.create_task(args.strip())

    task    = data.get("task", {})
    task_id = task.get("task_id", "?")
    status  = task.get("status", "pending")
    desc    = task.get("description", "")[:60]
    tid_short = task_id[:8]

    return (
        f"✅ 任务已提交\n"
        f"ID: {tid_short}\n"
        f"描述: {desc}\n"
        f"状态: {fmt_status(status)}"
    )
