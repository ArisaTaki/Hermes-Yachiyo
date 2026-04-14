"""显示模式系统

提供统一的模式分发入口 launch_mode()，根据 config.display_mode 启动对应的显示模式。
每个模式模块导出一个 run(runtime, config) 函数，负责阻塞主线程直到界面关闭。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_SUPPORTED_MODES = ("window", "bubble", "live2d")


def launch_mode(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """根据 config.display_mode 启动对应显示模式（阻塞主线程）。

    未知模式自动回退为 window。
    """
    mode = config.display_mode
    if mode not in _SUPPORTED_MODES:
        logger.warning("未知显示模式 %r，回退为 window 模式", mode)
        mode = "window"

    logger.info("启动显示模式: %s", mode)

    if mode == "window":
        from apps.shell.modes.window import run
    elif mode == "bubble":
        from apps.shell.modes.bubble import run
    else:  # live2d
        from apps.shell.modes.live2d import run

    run(runtime, config)
