"""气泡模式（占位实现）

桌面悬浮气泡显示。当前以小窗口展示占位提示，预留后续完整实现接口。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_BUBBLE_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo — 气泡模式</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            text-align: center;
            padding: 24px;
        }
        .icon { font-size: 3em; margin-bottom: 16px; }
        h2 { color: #6495ed; margin-bottom: 8px; font-size: 1.2em; }
        p { color: #888; font-size: 0.9em; }
        .hint {
            margin-top: 24px;
            background: #2d2d54;
            padding: 14px 20px;
            border-radius: 8px;
            font-size: 0.85em;
            color: #aaa;
            line-height: 1.7;
        }
    </style>
</head>
<body>
    <div class="icon">💬</div>
    <h2>气泡模式</h2>
    <p>桌面悬浮气泡 — 即将推出</p>
    <div class="hint">
        当前模式：<strong style="color:#6495ed">bubble</strong><br>
        完整实现将在后续版本中推出，当前以窗口形式展示占位。<br>
        如需立即使用，请在设置中切换至<strong>窗口模式</strong>。
    </div>
</body>
</html>
"""


def run(runtime: "HermesRuntime", config: "AppConfig") -> None:  # noqa: ARG001
    """运行气泡模式（当前为占位）"""
    logger.info("气泡模式尚未完整实现，以占位窗口运行")
    try:
        import webview  # type: ignore[import]

        webview.create_window(
            title="Hermes-Yachiyo — 气泡模式",
            html=_BUBBLE_HTML,
            width=360,
            height=300,
            resizable=False,
        )
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，气泡模式无法展示")

