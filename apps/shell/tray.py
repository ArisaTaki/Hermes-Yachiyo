"""系统托盘管理

MVP 实现：使用 pystray 提供系统托盘图标。
后续可替换为其他桌面壳方案的原生托盘。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

try:
    import pystray
    from PIL import Image

    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)


def _create_icon_image() -> "Image.Image":
    """生成一个简单的占位托盘图标"""
    img = Image.new("RGB", (64, 64), color=(100, 149, 237))
    return img


def create_tray(runtime: "HermesRuntime") -> None:
    """创建并运行系统托盘图标"""
    if not _HAS_TRAY:
        logger.warning("pystray 未安装，跳过系统托盘")
        return

    def on_status(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        status = runtime.get_status()
        logger.info("状态: %s", status)

    def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("状态", on_status),
        pystray.MenuItem("退出", on_quit),
    )

    icon = pystray.Icon(
        name="hermes-yachiyo",
        icon=_create_icon_image(),
        title="Hermes-Yachiyo",
        menu=menu,
    )
    icon.run()
