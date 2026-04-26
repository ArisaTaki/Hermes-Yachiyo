"""命令路由：将 /y <sub> <args> 分发到对应 handler。

路由规则：
    /y status tasks screen window do ask/chat  → Hermes-Yachiyo Bridge
  /y codex                          → Hapi（Codex 执行后端）
"""

from __future__ import annotations

import logging

from .config import PluginConfig

logger = logging.getLogger(__name__)

# ── 路由表 ────────────────────────────────────────────

HERMES_COMMANDS: frozenset[str] = frozenset({"status", "tasks", "screen", "window", "do", "check", "cancel", "ask", "chat"})
HAPI_COMMANDS: frozenset[str] = frozenset({"codex"})
ALL_COMMANDS: frozenset[str] = HERMES_COMMANDS | HAPI_COMMANDS

HELP_TEXT = (
    "Yachiyo 命令列表：\n"
    "  /y status           — 查看 Hermes Agent 运行状态\n"
    "  /y tasks            — 查看任务列表\n"
    "  /y do <任务>        — 创建新任务\n"
    "  /y ask <内容>       — 低风险自然语言入口\n"
    "  /y chat <内容>      — 同 /y ask\n"
    "  /y check <任务ID>   — 查询任务详情\n"
    "  /y cancel <任务ID>  — 取消任务\n"
    "  /y screen           — 获取当前屏幕截图\n"
    "  /y window           — 查看当前活动窗口\n"
    "  /y codex <任务>     — 通过 Hapi 执行 Codex 任务\n"
    "  /y help             — 显示此帮助"
)


async def route(command: str, args: str, config: PluginConfig, sender_id: str = "") -> str:
    """将命令分发到对应 handler，返回格式化响应文本。

    Args:
        command: 子命令名（已转小写）
        args:    命令参数原文
        config:  插件配置

    Returns:
        直接发回 QQ 的文本
    """
    if command in ("help", ""):
        return HELP_TEXT

    if command not in ALL_COMMANDS:
        return f"未知命令: /y {command}\n{HELP_TEXT}"

    # 延迟导入避免循环依赖
    from .handlers import dispatch

    try:
        return await dispatch(command, args, config, sender_id=sender_id)
    except Exception as exc:
        logger.exception("命令执行失败: /y %s", command)
        from .handlers.utils import fmt_error
        return fmt_error(exc, command)
