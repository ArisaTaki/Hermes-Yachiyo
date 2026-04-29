"""Hermes-Yachiyo 桌面应用兼容入口

默认转发到 React + Electron 前端；旧 pywebview shell 只保留给显式
``hermes-yachiyo-legacy-pywebview`` 命令或环境变量开关使用。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _legacy_pywebview_requested() -> bool:
    argv0 = Path(sys.argv[0]).name.lower()
    return _env_enabled("HERMES_YACHIYO_LEGACY_PYWEBVIEW") or "legacy-pywebview" in argv0


def _launch_legacy_pywebview() -> None:
    """旧 pywebview 入口，保留给显式 legacy 命令使用。"""
    _setup_logging()

    from apps.shell.config import load_config
    from apps.shell.startup import launch

    config = load_config()
    launch(config)


def legacy_main() -> None:
    """显式启动旧 pywebview shell。"""
    _launch_legacy_pywebview()


def main() -> None:
    """应用主入口：默认进入 React + Electron 前端。"""
    if _legacy_pywebview_requested():
        _launch_legacy_pywebview()
        return

    from apps.desktop_launcher import main as launch_electron

    launch_electron()


if __name__ == "__main__":
    main()
