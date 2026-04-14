"""AstrBot 桥接插件 — QQ 命令路由骨架

职责：
- 解析 QQ 命令
- 验证发送者权限
- 路由到 Hermes-Yachiyo Bridge 或 Hapi
- 格式化响应返回 QQ

非职责：
- 不实现本地机器控制
- 不实现第二个任务系统
- 不成为 agent runtime
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Hermes-Yachiyo Bridge 默认地址
DEFAULT_HERMES_URL = "http://127.0.0.1:8420"
# Hapi 默认地址（Codex 执行后端）
DEFAULT_HAPI_URL = "http://127.0.0.1:8430"


@dataclass
class PluginConfig:
    """插件配置"""

    hermes_url: str = DEFAULT_HERMES_URL
    hapi_url: str = DEFAULT_HAPI_URL


# ── 命令路由表 ──────────────────────────────────────


# /y status /tasks /screen /window /do → Hermes-Yachiyo
# /y codex → Hapi
HERMES_COMMANDS = {"status", "tasks", "screen", "window", "do"}
HAPI_COMMANDS = {"codex"}


async def handle_command(command: str, args: str, config: PluginConfig | None = None) -> str:
    """处理 /y 命令并路由到对应后端

    Args:
        command: 子命令名（如 "status", "codex"）
        args: 命令参数
        config: 插件配置

    Returns:
        格式化后的响应文本
    """
    cfg = config or PluginConfig()

    if command in HERMES_COMMANDS:
        return await _route_to_hermes(command, args, cfg)
    elif command in HAPI_COMMANDS:
        return await _route_to_hapi(command, args, cfg)
    else:
        return f"未知命令: /y {command}"


async def _route_to_hermes(command: str, args: str, config: PluginConfig) -> str:
    """路由到 Hermes-Yachiyo Bridge"""
    # TODO: 实现 HTTP 调用 Hermes Bridge
    logger.info("路由到 Hermes: /y %s %s", command, args)
    return f"[Hermes] /y {command} — 尚未接入"


async def _route_to_hapi(command: str, args: str, config: PluginConfig) -> str:
    """路由到 Hapi（Codex 执行后端）"""
    # TODO: 实现 HTTP 调用 Hapi
    logger.info("路由到 Hapi: /y %s %s", command, args)
    return f"[Hapi] /y {command} — 尚未接入"
