"""/y tasks → GET /tasks"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig
from .utils import fmt_dt, fmt_status, fmt_status_icon

logger = logging.getLogger(__name__)

_MAX_DISPLAY = 10


async def handle(args: str, config: PluginConfig) -> str:
    client = HermesClient(config)
    data = await client.list_tasks()

    tasks = data.get("tasks", [])
    total = data.get("total", len(tasks))

    if not tasks:
        return "📋 当前没有任务"

    lines = [f"📋 任务列表（共 {total} 条）"]
    for t in tasks[:_MAX_DISPLAY]:
        icon = fmt_status_icon(t.get("status", ""))
        status_label = fmt_status(t.get("status", ""))
        tid = t.get("task_id", "")[:8]
        desc = t.get("description", "")[:34]
        updated = fmt_dt(t.get("updated_at", ""))
        lines.append(f"  {icon} [{tid}] {desc}")
        lines.append(f"       {status_label}  {updated}")

    if total > _MAX_DISPLAY:
        lines.append(f"  … 共 {total} 条，仅显示前 {_MAX_DISPLAY} 条")

    return "\n".join(lines)
