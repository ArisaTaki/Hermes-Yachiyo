"""/y status → GET /status"""

from __future__ import annotations

import logging

from ..api_client import OhaClient
from ..config import PluginConfig
from .utils import fmt_status_icon, fmt_uptime

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    client = OhaClient(config)
    data = await client.get_status()

    version = data.get("version", "?")
    uptime_str = fmt_uptime(data.get("uptime_seconds", 0))
    native_agent_ready = data.get("native_agent_ready", False)
    native_agent_line = "✅ 已就绪" if native_agent_ready else "⚠️ 未就绪"
    counts = data.get("task_counts", {})

    pending   = counts.get("pending", 0)
    running   = counts.get("running", 0)
    completed = counts.get("completed", 0)
    failed    = counts.get("failed", 0)

    lines = [
        f"📊 Oha-Yachiyo 状态",
        f"版本: v{version}  运行: {uptime_str}",
        f"Native Agent: {native_agent_line}",
        f"任务: {fmt_status_icon('pending')} {pending}  "
        f"{fmt_status_icon('running')} {running}  "
        f"{fmt_status_icon('completed')} {completed}",
    ]
    if failed:
        lines.append(f"失败任务: {fmt_status_icon('failed')} {failed}")
    if not native_agent_ready:
        lines.append("请在桌面应用中完成 Native Agent 模型配置")

    return "\n".join(lines)
