"""/y window → GET /system/active-window"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig
from .utils import fmt_dt

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    client = HermesClient(config)
    data = await client.get_active_window()

    title    = data.get("title") or "（无标题）"
    app_name = data.get("app_name") or "未知"
    pid      = data.get("pid")
    queried  = fmt_dt(data.get("queried_at", ""))

    lines = [
        "🪟 当前活动窗口",
        f"应用: {app_name}",
        f"标题: {title}",
    ]
    if pid is not None:
        lines.append(f"PID: {pid}")
    lines.append(f"查询时间: {queried}")

    return "\n".join(lines)
