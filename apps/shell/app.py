"""Hermes-Yachiyo 桌面应用主入口

启动流程：
1. 加载用户配置
2. 检查 Hermes Agent 安装状态
3. 根据状态决定启动模式：
   - Hermes 可用：正常模式（Core Runtime + Bridge + 主窗口）
   - Hermes 不可用：安装引导模式（仅显示安装指导界面）
"""

import logging
import signal
import sys
import threading

from apps.bridge.deps import set_runtime
from apps.bridge.server import start_bridge, stop_bridge
from apps.core.runtime import HermesRuntime
from apps.installer.hermes_check import check_hermes_installation
from apps.shell.config import load_config
from apps.shell.tray import create_tray
from apps.shell.window import create_installer_window, create_main_window
from packages.protocol.enums import HermesInstallStatus

logger = logging.getLogger(__name__)


def main() -> None:
    """应用主入口"""
    config = load_config()

    # 1. 首先检查 Hermes Agent 安装状态
    logger.info("检查 Hermes Agent 安装状态...")
    hermes_install_info = check_hermes_installation()
    
    logger.info(
        "Hermes 检查结果: status=%s, platform=%s", 
        hermes_install_info.status,
        hermes_install_info.platform
    )
    
    # 2. 根据安装状态决定启动模式
    if hermes_install_info.status == HermesInstallStatus.INSTALLED:
        # Hermes 可用：正常启动模式
        logger.info("Hermes Agent 已安装，进入正常启动模式")
        _start_normal_mode(config)
    else:
        # Hermes 不可用：安装引导模式
        logger.info("Hermes Agent 不可用，进入安装引导模式")
        _start_installer_mode(config, hermes_install_info)


def _start_normal_mode(config) -> None:
    """正常启动模式：完整的 Hermes-Yachiyo 功能"""
    # 初始化 Core Runtime
    runtime = HermesRuntime(config)
    runtime.start()

    # 将 Runtime 注入 Bridge（shell → core → bridge 连通）
    set_runtime(runtime)

    # 启动内部 Bridge/API（后台线程）
    bridge_thread = threading.Thread(
        target=start_bridge,
        kwargs={"host": config.bridge_host, "port": config.bridge_port},
        daemon=True,
        name="bridge-api",
    )
    bridge_thread.start()

    # 注册退出信号
    def _shutdown(signum: int, frame: object) -> None:
        stop_bridge()
        runtime.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 启动系统托盘（后台线程）
    tray_thread = threading.Thread(
        target=create_tray,
        kwargs={"runtime": runtime},
        daemon=True,
        name="system-tray",
    )
    tray_thread.start()

    # 主线程运行窗口（pywebview 需要在主线程）
    create_main_window(runtime=runtime, config=config)

    # 窗口关闭后执行清理
    stop_bridge()
    runtime.stop()


def _start_installer_mode(config, hermes_install_info) -> None:
    """安装引导模式：仅显示 Hermes Agent 安装指导"""
    logger.info("启动 Hermes Agent 安装引导界面")

    # 简单的退出信号处理
    def _shutdown(signum: int, frame: object) -> None:
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # 主线程运行安装引导窗口
    create_installer_window(install_info=hermes_install_info, config=config)


if __name__ == "__main__":
    main()
