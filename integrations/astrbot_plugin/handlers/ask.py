"""/y ask|chat <内容> → Bridge /assistant/intent。"""

from __future__ import annotations

import logging

from ..api_client import HermesClient
from ..config import PluginConfig

logger = logging.getLogger(__name__)


async def handle(args: str, config: PluginConfig, sender_id: str = "") -> str:
    text = args.strip()
    if not text:
        return "用法: /y ask <内容>"

    client = HermesClient(config)
    data = await client.assistant_intent(text, source="astrbot", sender_id=sender_id)

    if not data.get("ok"):
        return f"⚠️ 处理失败\n{data.get('message') or 'Bridge 未返回错误详情'}"

    action = data.get("action", "unknown")
    task_id = data.get("task_id")
    message = data.get("message") or "已处理"
    lines = ["💬 Yachiyo", f"动作: {action}", message]
    if task_id:
        lines.append(f"任务 ID: {task_id}")
        lines.append(f"用 /y check {str(task_id)[:8]} 查询进度")
    return "\n".join(lines)
