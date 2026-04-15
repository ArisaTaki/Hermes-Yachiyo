"""/y cancel <task_id> → POST /tasks/{task_id}/cancel"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig
from .utils import fmt_status

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    task_id = args.strip()
    if not task_id:
        return "用法: /y cancel <任务ID>"

    client = HermesClient(config)
    data = await client.cancel_task(task_id)

    task   = data.get("task", {})
    tid    = task.get("task_id", task_id)
    status = task.get("status", "cancelled")
    desc   = task.get("description", "")[:50]

    return (
        f"🚫 任务已取消\n"
        f"ID: {tid}\n"
        f"描述: {desc}\n"
        f"状态: {fmt_status(status)}"
    )
