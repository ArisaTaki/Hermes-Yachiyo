"""/y screen → GET /screen/current"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig) -> str:
    client = HermesClient(config)
    data = await client.get_screen()

    width = data.get("width", 0)
    height = data.get("height", 0)
    captured_at = data.get("captured_at", "")
    fmt = data.get("format", "png")

    # TODO: AstrBot 支持图片消息后，将 image_base64 包装成图片消息对象返回
    #       目前只返回元信息摘要
    return (
        f"📸 截图已获取\n"
        f"格式: {fmt}  分辨率: {width}×{height}\n"
        f"时间: {captured_at}\n"
        "（图片发送能力待 AstrBot 联调后启用）"
    )
