"""Window 模式。

Window mode 是总控台，不承载完整聊天消息区。
完整会话由独立 Chat Window 承担。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


def run(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """运行窗口模式（阻塞主线程）"""
    from apps.shell.window import create_main_window

    create_main_window(runtime=runtime, config=config)
