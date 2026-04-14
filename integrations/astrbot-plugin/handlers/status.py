"""/y status → GET /status"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    client = HermesClient(config)
    data = await client.get_status()

    uptime = int(data.get("uptime_seconds", 0))
    counts = data.get("task_counts", {})
    version = data.get("version", "?")

    mins, secs = divmod(uptime, 60)
    uptime_str = f"{mins}m {secs}s" if mins else f"{secs}s"

    return (
        "📊 Hermes-Yachiyo 状态\n"
        f"版本: {version}\n"
        f"运行时长: {uptime_str}\n"
        f"任务: 等待 {counts.get('pending', 0)} / "
        f"运行 {counts.get('running', 0)} / "
        f"完成 {counts.get('completed', 0)}"
    )
