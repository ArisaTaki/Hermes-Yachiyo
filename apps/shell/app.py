"""Hermes-Yachiyo 桌面应用主入口

只负责：
  1. 初始化日志
  2. 加载用户配置
  3. 调用统一启动入口 startup.launch()

所有启动阶段状态判断均在 apps/shell/startup.py 中处理。
"""

import logging
import sys


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def main() -> None:
    """应用主入口"""
    _setup_logging()

    from apps.shell.config import load_config
    from apps.shell.startup import launch

    config = load_config()
    launch(config)


if __name__ == "__main__":
    main()
