"""/y screen → GET /screen/current"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig
from .utils import fmt_dt

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    client = HermesClient(config)
    data = await client.get_screen()

    width  = data.get("width", 0)
    height = data.get("height", 0)
    fmt    = data.get("format", "png").upper()
    ts     = fmt_dt(data.get("captured_at", ""))

    # TODO: AstrBot 支持图片消息后，将 image_base64 包装成图片消息对象返回
    lines = [
        "📸 截图已获取",
        f"分辨率: {width}×{height}  格式: {fmt}",
        f"拍摄时间: {ts}",
        "（图片消息待 AstrBot 联调后发送）",
    ]
    return "\n".join(lines)
