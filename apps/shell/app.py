"""Hermes-Yachiyo 桌面应用主入口

启动流程：
1. 加载用户配置
2. 启动 Core Runtime
3. 启动 Bridge/API（后台线程）
4. 启动系统托盘
5. 显示主窗口
"""

import signal
import sys
import threading

from apps.bridge.deps import set_runtime
from apps.bridge.server import start_bridge, stop_bridge
from apps.core.runtime import HermesRuntime
from apps.shell.config import load_config
from apps.shell.tray import create_tray
from apps.shell.window import create_main_window


def main() -> None:
    """应用主入口"""
    config = load_config()

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


if __name__ == "__main__":
    main()
