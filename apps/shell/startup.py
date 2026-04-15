"""启动决策层

负责：
  1. 检测 Hermes 安装状态
  2. 将状态映射到启动模式
  3. 分发到对应模式的启动函数

规则：
  - 所有"根据状态选择入口"的逻辑都在这里，不分散到 app.py 或 window.py
  - 新增状态时只改 _INSTALL_STATUS_TO_MODE 和对应的启动函数
  - core / bridge / installer 的边界不在此层处理
"""

import logging
import signal
import sys
import threading
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.shell.config import AppConfig
    from packages.protocol.install import HermesInstallInfo

logger = logging.getLogger(__name__)


# ── 启动模式枚举 ──────────────────────────────────────────────────────────────

class StartupMode(StrEnum):
    """应用启动模式"""

    NORMAL = "normal"          # Hermes 就绪，进入完整主界面
    INIT_WIZARD = "init_wizard"  # Hermes 已安装，Yachiyo workspace 待初始化
    INSTALLER = "installer"    # Hermes 未安装或存在问题，进入安装引导


# ── 状态 → 模式映射 ───────────────────────────────────────────────────────────

from packages.protocol.enums import HermesInstallStatus

# 每个 HermesInstallStatus 对应的启动模式。
# 未在此 dict 中的状态均 fallback 到 INSTALLER。
_INSTALL_STATUS_TO_MODE: dict[HermesInstallStatus, StartupMode] = {
    HermesInstallStatus.READY: StartupMode.NORMAL,
    HermesInstallStatus.INSTALLED_NOT_INITIALIZED: StartupMode.INIT_WIZARD,
}


def resolve_startup_mode(install_info: "HermesInstallInfo") -> StartupMode:
    """将安装检测结果映射为启动模式。

    Args:
        install_info: ``check_hermes_installation()`` 的返回值

    Returns:
        StartupMode 枚举值
    """
    mode = _INSTALL_STATUS_TO_MODE.get(install_info.status, StartupMode.INSTALLER)
    logger.info(
        "启动决策：install_status=%s → startup_mode=%s",
        install_info.status,
        mode,
    )
    return mode


# ── 各模式启动函数 ─────────────────────────────────────────────────────────────

def run_normal_mode(config: "AppConfig") -> None:
    """正常模式：启动 Core Runtime + Bridge + 主界面窗口。"""
    from apps.bridge.deps import set_runtime
    from apps.bridge.server import start_bridge, stop_bridge
    from apps.core.runtime import HermesRuntime
    from apps.shell.modes import launch_mode
    from apps.shell.tray import create_tray

    runtime = HermesRuntime(config)
    runtime.start()
    set_runtime(runtime)

    if config.bridge_enabled:
        bridge_thread = threading.Thread(
            target=start_bridge,
            kwargs={"host": config.bridge_host, "port": config.bridge_port},
            daemon=True,
            name="bridge-api",
        )
        bridge_thread.start()
    else:
        logger.info("Bridge 已禁用，跳过启动")

    def _shutdown(signum: int, frame: object) -> None:
        if config.bridge_enabled:
            stop_bridge()
        runtime.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if config.tray_enabled:
        threading.Thread(
            target=create_tray,
            kwargs={"runtime": runtime},
            daemon=True,
            name="system-tray",
        ).start()
    else:
        logger.info("系统托盘已禁用，跳过启动")

    # pywebview 需要在主线程运行
    launch_mode(runtime, config)

    # 窗口关闭后清理
    if config.bridge_enabled:
        stop_bridge()
    runtime.stop()


def run_installer_mode(config: "AppConfig", install_info: "HermesInstallInfo") -> None:
    """安装引导 / 初始化向导模式（共用同一个窗口入口）。

    安装引导（NOT_INSTALLED 等）和初始化向导（INSTALLED_NOT_INITIALIZED）
    都通过 ``create_installer_window`` 渲染，窗口内部根据状态展示不同 UI。
    """
    from apps.shell.window import create_installer_window

    def _shutdown(signum: int, frame: object) -> None:
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    create_installer_window(install_info=install_info, config=config)


# ── 统一入口 ──────────────────────────────────────────────────────────────────

def launch(config: "AppConfig") -> None:
    """应用统一启动入口。

    流程：
      1. 检测 Hermes 安装状态
      2. 映射为 StartupMode
      3. 分发到对应模式启动函数
    """
    from apps.installer.hermes_check import check_hermes_installation

    logger.info("检查 Hermes Agent 安装状态...")
    install_info = check_hermes_installation()
    logger.info("Hermes 检查结果: status=%s, platform=%s",
                install_info.status, install_info.platform)

    mode = resolve_startup_mode(install_info)

    if mode == StartupMode.NORMAL:
        run_normal_mode(config)
    else:
        # INSTALLER 和 INIT_WIZARD 都走 run_installer_mode，
        # 窗口内部根据 install_info.status 区分 UI。
        run_installer_mode(config, install_info)
