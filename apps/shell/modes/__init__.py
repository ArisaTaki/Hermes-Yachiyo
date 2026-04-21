"""显示模式系统

提供 DisplayMode 枚举、resolve_display_mode() 解析函数和统一分发入口 launch_mode()。
每个模式模块导出一个 run(runtime, config) 函数，负责阻塞主线程直到界面关闭。

模式说明：
  window  — 总控台 / 仪表盘 / 入口中心
  bubble  — 轻量常驻悬浮聊天模式
  live2d  — 角色聊天壳（保留 renderer 接入位）
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


class DisplayMode(StrEnum):
    """显示模式枚举"""

    WINDOW = "window"    # 总控台
    BUBBLE = "bubble"    # 轻量常驻聊天模式
    LIVE2D = "live2d"    # 角色聊天壳


_DEFAULT_DISPLAY_MODE = DisplayMode.WINDOW


def resolve_display_mode(config: "AppConfig") -> DisplayMode:
    """从配置中解析显示模式，未知值回退为 WINDOW。

    Args:
        config: 应用配置对象

    Returns:
        DisplayMode 枚举值
    """
    raw = getattr(config, "display_mode", None) or ""
    try:
        mode = DisplayMode(raw)
    except ValueError:
        logger.warning("未知显示模式 %r，回退为 %s", raw, _DEFAULT_DISPLAY_MODE)
        mode = _DEFAULT_DISPLAY_MODE
    return mode


def launch_mode(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """根据 config.display_mode 启动对应显示模式（阻塞主线程）。

    调用方通常已通过 resolve_display_mode() 记录了决策日志；
    此处只负责分发，不重复记录。
    """
    mode = resolve_display_mode(config)

    if mode == DisplayMode.WINDOW:
        from apps.shell.modes.window import run
    elif mode == DisplayMode.BUBBLE:
        from apps.shell.modes.bubble import run
    else:  # LIVE2D
        from apps.shell.modes.live2d import run

    run(runtime, config)
