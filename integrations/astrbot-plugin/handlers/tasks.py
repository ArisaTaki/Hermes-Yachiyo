"""/y tasks → GET /tasks"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig

logger = logging.getLogger(__name__)

_MAX_DISPLAY = 10

# TaskStatus 枚举值 → 短标签映射（与 Bridge 保持一致）
_STATUS_LABEL: dict[str, str] = {
    "pending": "⏳",
    "running": "🔄",
    "completed": "✅",
    "cancelled": "🚫",
    "failed": "❌",
}


async def handle(args: str, config: PluginConfig) -> str:
    client = HermesClient(config)
    data = await client.list_tasks()

    tasks = data.get("tasks", [])
    total = data.get("total", len(tasks))

    if not tasks:
        return "📋 当前没有任务"

    lines = [f"📋 任务列表（共 {total} 条）"]
    for t in tasks[:_MAX_DISPLAY]:
        icon = _STATUS_LABEL.get(t.get("status", ""), "❓")
        desc = t.get("description", "")[:40]
        lines.append(f"  {icon} {desc}")

    if total > _MAX_DISPLAY:
        lines.append(f"  … 共 {total} 条，仅显示前 {_MAX_DISPLAY} 条")

    return "\n".join(lines)
