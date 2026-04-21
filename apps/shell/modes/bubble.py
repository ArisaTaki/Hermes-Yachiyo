"""Bubble 模式。

Bubble 是桌面常驻 launcher，不承载完整聊天 UI：
- 常驻形态是透明无边框的圆形头像气泡
- 单击气泡展开/收起统一 Chat Window
- 右键菜单提供主控台、模式设置、退出入口
- 会话与消息仍共享 Runtime 的 ChatSession / ChatStore
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.shell.chat_bridge import ChatBridge

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_MIN_LAUNCHER_SIZE = 96
_MAX_LAUNCHER_SIZE = 128
_DEFAULT_LAUNCHER_SIZE = 112

_BUBBLE_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo Bubble</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body {
            width: 100%;
            height: 100%;
            overflow: hidden;
            background: transparent;
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            user-select: none;
        }
        body {
            display: grid;
            place-items: center;
        }
        @keyframes launcher-breathe {
            0%, 100% { transform: scale(1); filter: drop-shadow(0 8px 18px rgba(0, 0, 0, 0.38)); }
            50% { transform: scale(1.035); filter: drop-shadow(0 11px 24px rgba(240, 171, 0, 0.22)); }
        }
        @keyframes unread-pulse {
            0% { box-shadow: 0 0 0 0 rgba(255, 100, 100, 0.72); }
            70% { box-shadow: 0 0 0 12px rgba(255, 100, 100, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 100, 100, 0); }
        }
        @keyframes thinking-dot {
            0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-1px); }
        }
        .bubble-launcher {
            position: relative;
            width: min(86vw, 112px);
            height: min(86vw, 112px);
            border: 0;
            border-radius: 50%;
            background: radial-gradient(circle at 48% 45%, #f5a400 0 54%, #151515 55% 64%, #2c2c2c 65% 74%, #171717 75% 100%);
            cursor: pointer;
            animation: launcher-breathe 4s ease-in-out infinite;
            outline: none;
            display: grid;
            place-items: center;
        }
        .bubble-launcher:hover {
            animation-duration: 2.6s;
        }
        .bubble-launcher:active {
            transform: scale(0.98);
        }
        .portrait {
            position: relative;
            width: 70%;
            height: 70%;
            border-radius: 50%;
            overflow: hidden;
            background:
                radial-gradient(circle at 50% 38%, #fff7f2 0 18%, transparent 19%),
                radial-gradient(circle at 40% 44%, #f7d6cf 0 4%, transparent 5%),
                radial-gradient(circle at 60% 44%, #f7d6cf 0 4%, transparent 5%),
                linear-gradient(110deg, transparent 0 22%, #e9edf6 23% 36%, transparent 37% 100%),
                linear-gradient(250deg, transparent 0 22%, #e4e9f5 23% 38%, transparent 39% 100%),
                linear-gradient(180deg, #f4f6fb 0 58%, #2b2b31 59% 100%);
            border: 2px solid rgba(255, 255, 255, 0.36);
            box-shadow: inset 0 -10px 18px rgba(0, 0, 0, 0.2);
        }
        .portrait::before,
        .portrait::after {
            content: "";
            position: absolute;
            top: 39%;
            width: 8%;
            height: 8%;
            border-radius: 50%;
            background: #5d6177;
            box-shadow: 0 0 0 1px rgba(255,255,255,0.35);
        }
        .portrait::before { left: 35%; }
        .portrait::after { right: 35%; }
        .mouth {
            position: absolute;
            left: 50%;
            top: 54%;
            width: 12%;
            height: 6%;
            border-bottom: 2px solid #d67d86;
            border-radius: 50%;
            transform: translateX(-50%);
        }
        .status-dot {
            position: absolute;
            right: 17%;
            top: 17%;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 2px solid rgba(20, 20, 20, 0.82);
            background: #71e28c;
        }
        .status-dot.processing {
            background: #ffd166;
            animation: unread-pulse 1.45s infinite;
        }
        .status-dot.failed { background: #ff6868; }
        .status-dot.empty { background: #7f8b9b; }
        .status-dot.attention {
            background: #ff6b6b;
            animation: unread-pulse 1.6s infinite;
        }
        .context-menu {
            position: fixed;
            right: 8px;
            bottom: 8px;
            min-width: 116px;
            padding: 6px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            background: rgba(22, 24, 29, 0.96);
            box-shadow: 0 16px 32px rgba(0, 0, 0, 0.36);
            display: none;
            z-index: 4;
        }
        .context-menu.visible { display: block; }
        .menu-btn {
            width: 100%;
            border: 0;
            background: transparent;
            color: #eef2f7;
            text-align: left;
            padding: 7px 8px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 12px;
        }
        .menu-btn:hover { background: rgba(255, 255, 255, 0.1); }
        .menu-btn.danger { color: #ffb5b5; }
    </style>
</head>
<body>
    <button class="bubble-launcher" id="bubble-launcher" type="button"
            title="Yachiyo - 点击展开对话" aria-label="Yachiyo Bubble"
            onclick="toggleChat()" oncontextmenu="showMenu(event)">
        <span class="portrait" aria-hidden="true"><span class="mouth"></span></span>
        <span class="status-dot empty" id="status-dot" aria-hidden="true"></span>
    </button>

    <div class="context-menu" id="context-menu">
        <button class="menu-btn" type="button" onclick="openChat()">打开对话</button>
        <button class="menu-btn" type="button" onclick="openMain()">主控台</button>
        <button class="menu-btn" type="button" onclick="openSettings()">设置</button>
        <button class="menu-btn danger" type="button" onclick="closeBubble()">退出</button>
    </div>

<script>
const ACTIVE_POLL_INTERVAL_MS = 1200;
const IDLE_POLL_INTERVAL_MS = 5000;
let polling = null;
let pollingIntervalMs = null;
let toggling = false;

function setPollingInterval(intervalMs) {
    if (polling && pollingIntervalMs === intervalMs) return;
    stopPolling();
    pollingIntervalMs = intervalMs;
    polling = setInterval(refreshBubble, intervalMs);
}

function startActivePolling() {
    setPollingInterval(ACTIVE_POLL_INTERVAL_MS);
}

function startIdlePolling() {
    setPollingInterval(IDLE_POLL_INTERVAL_MS);
}

function stopPolling() {
    if (polling) clearInterval(polling);
    polling = null;
    pollingIntervalMs = null;
}

function hideMenu() {
    document.getElementById('context-menu').classList.remove('visible');
}

function showMenu(event) {
    event.preventDefault();
    event.stopPropagation();
    document.getElementById('context-menu').classList.toggle('visible');
}

function renderBubble(view) {
    const bubble = view.bubble || {};
    const chat = view.chat || {};
    const dot = document.getElementById('status-dot');
    const status = bubble.latest_status || 'empty';
    dot.className = 'status-dot ' + status + (bubble.has_attention ? ' attention' : '');
    document.getElementById('bubble-launcher').title =
        chat.status_label ? ('Yachiyo - ' + chat.status_label) : 'Yachiyo - 点击展开对话';

    if (chat.is_processing) startActivePolling();
    else startIdlePolling();
}

async function refreshBubble() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        const view = await window.pywebview.api.get_bubble_view();
        if (!view.ok) return;
        renderBubble(view);
    } catch (error) {}
}

async function toggleChat() {
    if (toggling) return;
    hideMenu();
    toggling = true;
    try {
        if (window.pywebview && window.pywebview.api) {
            await window.pywebview.api.toggle_chat();
            await refreshBubble();
        }
    } finally {
        toggling = false;
    }
}

async function openChat() {
    hideMenu();
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_chat();
}

async function openMain() {
    hideMenu();
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_main_window();
}

async function openSettings() {
    hideMenu();
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_settings();
}

async function closeBubble() {
    hideMenu();
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.close_bubble();
}

function bootstrap() {
    refreshBubble();
    startIdlePolling();
}

document.addEventListener('click', function(event) {
    if (!event.target.closest('#context-menu')) hideMenu();
});
document.addEventListener('DOMContentLoaded', function() { setTimeout(bootstrap, 300); });
window.addEventListener('pywebviewready', bootstrap);
</script>
</body>
</html>
"""


class BubbleWindowAPI:
    """Bubble 模式 WebView API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)
        self._bubble_window = None

    def get_bubble_view(self) -> Dict[str, Any]:
        bubble = self._config.bubble_mode
        chat = self._chat_bridge.get_conversation_overview(
            summary_count=bubble.summary_count,
            session_limit=3,
        )
        latest_status = "ready"
        if chat.get("empty"):
            latest_status = "empty"
        elif chat.get("is_processing"):
            latest_status = "processing"
        elif any(item.get("status") == "failed" for item in chat.get("messages", [])):
            latest_status = "failed"

        return {
            "ok": True,
            "chat": chat,
            "bubble": {
                "default_display": bubble.default_display,
                "show_unread_dot": bubble.show_unread_dot,
                "has_attention": bool(chat.get("latest_reply")) and not chat.get("is_processing"),
                "latest_status": latest_status,
                "subtitle": (
                    "从当前会话继续对话"
                    if not chat.get("empty")
                    else "点击展开对话"
                ),
            },
        }

    def send_quick_message(self, text: str) -> Dict[str, Any]:
        return self._chat_bridge.send_quick_message(text)

    def toggle_chat(self) -> Dict[str, Any]:
        from apps.shell.chat_window import is_chat_window_open, toggle_chat_window

        was_open = is_chat_window_open()
        open_after_toggle = toggle_chat_window(self._runtime)
        return {"ok": was_open or open_after_toggle, "open": open_after_toggle}

    def open_chat(self) -> Dict[str, Any]:
        from apps.shell.chat_window import open_chat_window

        return {"ok": open_chat_window(self._runtime)}

    def open_main_window(self) -> Dict[str, Any]:
        from apps.shell.window import open_main_window

        return {"ok": open_main_window(self._runtime, self._config)}

    def open_settings(self) -> Dict[str, Any]:
        from apps.shell.settings import open_mode_settings_window

        return {"ok": open_mode_settings_window(self._config, "bubble")}

    def close_bubble(self) -> Dict[str, Any]:
        try:
            from apps.shell.window import request_app_exit

            request_app_exit()
            return {"ok": True}
        except Exception as exc:
            logger.error("退出 Bubble 模式失败: %s", exc)
            return {"ok": False, "error": str(exc)}


def _resolve_launcher_size(width: int, height: int) -> int:
    raw = min(width or _DEFAULT_LAUNCHER_SIZE, height or _DEFAULT_LAUNCHER_SIZE)
    return max(_MIN_LAUNCHER_SIZE, min(_MAX_LAUNCHER_SIZE, int(raw)))


def run(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """运行 Bubble 模式（阻塞主线程）。"""
    logger.info("启动 Bubble 模式")
    try:
        import webview  # type: ignore[import]

        bubble = config.bubble_mode
        launcher_size = _resolve_launcher_size(bubble.width, bubble.height)
        api = BubbleWindowAPI(runtime, config)
        win = webview.create_window(
            title="Hermes-Yachiyo Bubble",
            html=_BUBBLE_HTML,
            width=launcher_size,
            height=launcher_size,
            x=bubble.position_x,
            y=bubble.position_y,
            resizable=False,
            on_top=bubble.always_on_top,
            js_api=api,
            frameless=True,
            transparent=True,
            easy_drag=True,
            text_select=False,
        )
        api._bubble_window = win
        try:
            from apps.shell.window import bind_app_window_exit

            bind_app_window_exit(win, label="Bubble 气泡")
        except Exception as exc:
            logger.warning("绑定 Bubble 退出事件失败: %s", exc)
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，Bubble 模式无法展示")
