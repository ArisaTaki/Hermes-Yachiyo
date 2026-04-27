"""AstrBot 桥接插件 — Hermes-Yachiyo QQ 接入点

职责：
- 解析 /y 命令
- 校验发送者权限（可选 allow-list）
- 路由到 command_router → handlers → api_client
- 格式化响应返回 QQ

非职责：
- 不实现本地机器控制
- 不实现第二个任务系统
- 不成为 agent runtime
"""

from __future__ import annotations

import logging

from .command_router import route
from .config import PluginConfig

logger = logging.getLogger(__name__)


def parse_y_command(text: str) -> tuple[str, str]:
    """解析 '/y <sub> [args]' 格式的命令文本。

    Returns:
        (sub_command, args) — sub_command 已转小写，args 保留原始格式
    """
    parts = text.strip().split(None, 2)
    # parts[0] 为 '/y'，由调用方保证
    sub = parts[1].lower() if len(parts) >= 2 else ""
    args = parts[2] if len(parts) >= 3 else ""
    return sub, args


async def on_y_command(
    text: str,
    sender_id: str = "",
    config: PluginConfig | None = None,
) -> str:
    """处理完整的 '/y ...' 消息。

    AstrBot 宿主在收到 /y 开头的消息时调用此函数。

    Args:
        text:       消息原文（包含 '/y'）
        sender_id:  发送者 QQ 号字符串（用于权限校验）
        config:     插件配置；None 时使用默认值

    Returns:
        格式化响应文本，直接发回 QQ
    """
    cfg = config or PluginConfig()

    # 权限校验：allow-list 非空时校验发送者
    if cfg.allowed_senders and sender_id not in cfg.allowed_senders:
        logger.warning("拒绝未授权发送者: %s", sender_id)
        return "❌ 无权限使用 Yachiyo 命令"

    sub, args = parse_y_command(text)
    return await route(sub, args, cfg, sender_id=sender_id)

