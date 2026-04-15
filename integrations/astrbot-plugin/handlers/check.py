"""/y check <task_id> → GET /tasks/{task_id}

查询单个任务的当前状态和详情。
"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig
from .utils import fmt_dt, fmt_status

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    task_id = args.strip()
    if not task_id:
        return "用法: /y check <任务ID>"

    client = HermesClient(config)
    data = await client.get_task(task_id)

    task    = data.get("task", {})
    tid     = task.get("task_id", task_id)
    desc    = task.get("description", "")
    status  = task.get("status", "")
    created = fmt_dt(task.get("created_at", ""))
    updated = fmt_dt(task.get("updated_at", ""))
    result  = task.get("result")
    error   = task.get("error")

    lines = [
        f"🔍 任务详情",
        f"ID: {tid}",
        f"描述: {desc}",
        f"状态: {fmt_status(status)}",
        f"创建: {created}  更新: {updated}",
    ]
    if result:
        lines.append(f"结果: {result}")
    if error:
        lines.append(f"错误: {error}")

    return "\n".join(lines)
