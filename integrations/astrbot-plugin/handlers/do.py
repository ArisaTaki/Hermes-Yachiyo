"""/y do <task> → POST /tasks"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    if not args.strip():
        return "用法: /y do <任务描述>"

    client = HermesClient(config)
    data = await client.create_task(args.strip())

    task = data.get("task", {})
    task_id = task.get("task_id", "?")
    status = task.get("status", "?")
    desc = task.get("description", "")[:60]

    return (
        f"✅ 任务已创建\n"
        f"ID: {task_id}\n"
        f"描述: {desc}\n"
        f"状态: {status}"
    )
