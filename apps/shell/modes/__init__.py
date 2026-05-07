"""Display mode identifiers shared by the Electron frontend and Python backend."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


class DisplayMode(StrEnum):
    """显示模式枚举"""

    BUBBLE = "bubble"    # 轻量常驻聊天模式
    LIVE2D = "live2d"    # 角色聊天壳


_DEFAULT_DISPLAY_MODE = DisplayMode.BUBBLE


def resolve_display_mode(config: "AppConfig") -> DisplayMode:
    """从配置中解析显示模式，未知值回退为 BUBBLE。

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
