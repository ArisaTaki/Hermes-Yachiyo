"""主窗口管理

MVP 实现：使用 pywebview 展示本地状态页。
这只是桌面壳原型方案，后续允许迁移到更完整的桌面壳技术。
pywebview 的使用不影响 core / bridge / protocol 的长期边界。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

try:
    import webview

    _HAS_WEBVIEW = True
except ImportError:
    _HAS_WEBVIEW = False

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

# 最小状态页 HTML
_STATUS_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo</title>
    <style>
        body {
            font-family: -apple-system, "Helvetica Neue", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
        }
        h1 { color: #6495ed; margin-bottom: 0.2em; }
        .status { color: #90ee90; font-size: 1.2em; }
        .info { color: #888; margin-top: 2em; font-size: 0.9em; }
    </style>
</head>
<body>
    <h1>Hermes-Yachiyo</h1>
    <p class="status">● 运行中</p>
    <p class="info">桌面优先本地个人 agent</p>
    <p class="info">Bridge API: http://{host}:{port}</p>
</body>
</html>
"""


def create_main_window(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """创建并显示主窗口（阻塞主线程）"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，以无窗口模式运行")
        # 无窗口模式下保持主线程活跃
        import threading

        threading.Event().wait()
        return

    html = _STATUS_HTML.format(host=config.bridge_host, port=config.bridge_port)

    webview.create_window(
        title="Hermes-Yachiyo",
        html=html,
        width=480,
        height=360,
        resizable=True,
    )
    webview.start()
