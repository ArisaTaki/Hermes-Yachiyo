"""Bubble 模式。

Bubble 是桌面常驻 launcher，不承载完整聊天 UI：
- 常驻形态是透明无边框的圆形头像气泡
- 单击气泡展开/收起统一 Chat Window
- 右键菜单提供主控台、模式设置、退出入口
- 会话与消息仍共享 Runtime 的 ChatSession / ChatStore
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Dict

from apps.shell.assets import DEFAULT_BUBBLE_AVATAR_PATH, data_uri
from apps.shell.chat_bridge import ChatBridge
from apps.shell.proactive import ProactiveDesktopService

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
            background: rgba(0, 0, 0, 0) !important;
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            user-select: none;
        }
        body {
            display: grid;
            place-items: center;
            background-color: rgba(0, 0, 0, 0) !important;
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
            width: min(84vw, 108px);
            height: min(84vw, 108px);
            padding: 3px;
            border: 2px solid rgba(236, 177, 39, 0.9);
            border-radius: 50%;
            background: transparent;
            cursor: pointer;
            outline: none;
            display: grid;
            place-items: center;
            box-shadow: none;
            backdrop-filter: none;
            -webkit-backdrop-filter: none;
            appearance: none;
            -webkit-appearance: none;
            transition: transform 120ms ease, border-color 120ms ease;
        }
        .bubble-launcher:hover {
            transform: scale(1.02);
            border-color: rgba(249, 199, 78, 0.95);
        }
        .bubble-launcher.auto-hidden {
            transform: scale(0.96);
        }
        .bubble-launcher:active {
            transform: scale(0.98);
        }
        .portrait {
            position: relative;
            width: 100%;
            height: 100%;
            border-radius: 50%;
            overflow: hidden;
            background-image: url("{{AVATAR_URL}}");
            background-size: cover;
            background-position: center center;
            border: 1px solid rgba(255, 244, 203, 0.86);
            box-shadow: none;
        }
        .portrait::before,
        .portrait::after {
            content: "";
            position: absolute;
            display: none;
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
            display: none;
        }
        .status-dot {
            position: absolute;
            right: 17%;
            top: 17%;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 2px solid rgba(255, 255, 255, 0.88);
            background: #71e28c;
            display: none;
            box-shadow: 0 1px 4px rgba(24, 32, 28, 0.22);
        }
        .status-dot.visible { display: block; }
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
        .bubble-summary {
            position: absolute;
            left: 50%;
            bottom: -2px;
            max-width: 120px;
            transform: translateX(-50%);
            padding: 2px 7px;
            border-radius: 999px;
            background: rgba(20, 24, 31, 0.74);
            color: #fff6d6;
            font-size: 10px;
            line-height: 1.25;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            pointer-events: none;
        }
        .bubble-summary.hidden { display: none; }
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
        .menu-btn:hover,
        .menu-btn:focus { background: rgba(255, 255, 255, 0.1); outline: none; }
        .menu-btn.danger { color: #ffb5b5; }
    </style>
</head>
<body>
    <button class="bubble-launcher" id="bubble-launcher" type="button"
            title="Yachiyo - 点击展开对话" aria-label="Yachiyo Bubble"
            onpointerdown="trackLauncherPointerDown(event)"
            onpointermove="trackLauncherPointerMove(event)"
            onpointerup="trackLauncherPointerUp(event)"
            onpointerenter="handleLauncherPointerEnter(event)"
            onclick="toggleChat(event)" oncontextmenu="showMenu(event)">
        <span class="portrait" aria-hidden="true"><span class="mouth"></span></span>
        <span class="status-dot empty" id="status-dot" aria-hidden="true"></span>
        <span class="bubble-summary hidden" id="bubble-summary" aria-hidden="true"></span>
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
const CLICK_DRAG_THRESHOLD_PX = 6;
let polling = null;
let pollingIntervalMs = null;
let toggling = false;
let launcherPointerStart = null;
let launcherClickSuppressed = false;
let launcherDragging = false;
let currentBubbleView = null;
let hoverOpening = false;

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
    const menu = document.getElementById('context-menu');
    const wasVisible = menu.classList.contains('visible');
    menu.classList.remove('visible');
    if (wasVisible) setContextMenuOpen(false);
}

function isMenuVisible() {
    return document.getElementById('context-menu').classList.contains('visible');
}

function pointerPoint(event) {
    return {
        x: Number.isFinite(event.screenX) ? event.screenX : event.clientX,
        y: Number.isFinite(event.screenY) ? event.screenY : event.clientY,
    };
}

function launcherPointerMoved(event) {
    if (!launcherPointerStart || !event) return false;
    const point = pointerPoint(event);
    return Math.abs(point.x - launcherPointerStart.x) > CLICK_DRAG_THRESHOLD_PX
        || Math.abs(point.y - launcherPointerStart.y) > CLICK_DRAG_THRESHOLD_PX;
}

function trackLauncherPointerDown(event) {
    if (event.button === 2) {
        launcherPointerStart = null;
        launcherClickSuppressed = false;
        setDraggingState(false);
        return;
    }
    launcherPointerStart = pointerPoint(event);
    launcherClickSuppressed = false;
    setDraggingState(true);
}

function trackLauncherPointerMove(event) {
    if (launcherPointerMoved(event)) launcherClickSuppressed = true;
}

function trackLauncherPointerUp(event) {
    if (launcherPointerMoved(event)) launcherClickSuppressed = true;
    setDraggingState(false);
}

function shouldIgnoreLauncherClick(event) {
    const ignore = launcherClickSuppressed || launcherPointerMoved(event);
    launcherPointerStart = null;
    launcherClickSuppressed = false;
    setDraggingState(false);
    if (ignore && event) {
        event.preventDefault();
        event.stopPropagation();
    }
    return ignore;
}

async function focusLauncherWindow() {
    try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.focus_window) {
            await window.pywebview.api.focus_window();
        }
    } catch (error) {}
}

function getExpandTrigger() {
    const bubble = currentBubbleView && currentBubbleView.bubble ? currentBubbleView.bubble : {};
    return bubble.expand_trigger || 'click';
}

async function handleLauncherPointerEnter(event) {
    await focusLauncherWindow();
    if (getExpandTrigger() !== 'hover') return;
    if (hoverOpening || launcherDragging || isMenuVisible()) return;
    hoverOpening = true;
    try {
        await openChat();
        await refreshBubble();
    } finally {
        hoverOpening = false;
    }
}

function setContextMenuOpen(isOpen) {
    try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_context_menu_open) {
            window.pywebview.api.set_context_menu_open(!!isOpen);
        }
    } catch (error) {}
}

function setDraggingState(isDragging) {
    const normalized = !!isDragging;
    if (launcherDragging === normalized) return;
    launcherDragging = normalized;
    try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_dragging) {
            window.pywebview.api.set_dragging(normalized);
        }
    } catch (error) {}
}

function positionMenu(event) {
    const menu = document.getElementById('context-menu');
    const margin = 4;
    menu.style.right = 'auto';
    menu.style.bottom = 'auto';
    menu.style.left = Math.max(margin, event.clientX + margin) + 'px';
    menu.style.top = Math.max(margin, event.clientY + margin) + 'px';
    const rect = menu.getBoundingClientRect();
    const x = Math.max(margin, Math.min(event.clientX + margin, window.innerWidth - rect.width - margin));
    const y = Math.max(margin, Math.min(event.clientY + margin, window.innerHeight - rect.height - margin));
    menu.style.left = x + 'px';
    menu.style.top = y + 'px';
}

function showMenu(event) {
    event.preventDefault();
    event.stopPropagation();
    focusLauncherWindow();
    const menu = document.getElementById('context-menu');
    menu.classList.add('visible');
    setContextMenuOpen(true);
    positionMenu(event);
    const firstItem = menu.querySelector('.menu-btn');
    if (firstItem) setTimeout(function() {
        try { firstItem.focus({preventScroll: true}); }
        catch (error) { firstItem.focus(); }
    }, 0);
}

function renderBubble(view) {
    currentBubbleView = view;
    const bubble = view.bubble || {};
    const chat = view.chat || {};
    const proactive = view.proactive || {};
    const launcher = document.getElementById('bubble-launcher');
    const summaryNode = document.getElementById('bubble-summary');
    const dot = document.getElementById('status-dot');
    const status = bubble.latest_status || 'empty';
    let dotClass = 'status-dot';
    const showDot = bubble.show_unread_dot !== false;
    if (showDot && bubble.has_attention) dotClass += ' visible attention';
    else if (showDot && (status === 'processing' || status === 'failed')) dotClass += ' visible ' + status;
    else dotClass += ' ' + status;
    dot.className = dotClass;
    const displayMode = bubble.default_display || 'summary';
    const latestMessage = (chat.messages || []).length
        ? chat.messages[chat.messages.length - 1].content
        : '';
    const summaryText = displayMode === 'recent_reply'
        ? (chat.latest_reply || latestMessage || chat.status_label || '')
        : displayMode === 'summary'
            ? (chat.status_label || latestMessage || bubble.subtitle || '')
            : '';
    summaryNode.textContent = summaryText;
    summaryNode.classList.toggle('hidden', displayMode === 'icon' || !summaryText);
    const titleParts = [
        displayMode === 'icon'
            ? 'Yachiyo - 头像图标'
            : ('Yachiyo - ' + (summaryText || chat.status_label || '点击展开对话')),
    ];
    if (proactive.error) titleParts.push('主动对话：' + proactive.error);
    else if (proactive.has_attention) titleParts.push('主动对话：有新的观察结果');
    else if (proactive.enabled && proactive.message) titleParts.push('主动对话：' + proactive.message);
    launcher.title = titleParts.join('\n');
    launcher.setAttribute(
        'aria-label',
        (displayMode === 'icon' ? 'Yachiyo Bubble' : ('Yachiyo Bubble - ' + (summaryText || chat.status_label || '')))
    );
    const configuredOpacity = Math.max(0.2, Math.min(1, Number(bubble.opacity || 0.92)));
    const isIdle = !!bubble.auto_hide
        && !chat.is_processing
        && !bubble.has_attention
        && !proactive.has_attention
        && !isMenuVisible();
    launcher.style.opacity = String(isIdle ? Math.max(0.24, configuredOpacity * 0.52) : configuredOpacity);
    launcher.classList.toggle('auto-hidden', isIdle);

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

async function toggleChat(event) {
    if (shouldIgnoreLauncherClick(event)) return;
    if (getExpandTrigger() !== 'click') {
        if (event) event.preventDefault();
        return;
    }
    if (isMenuVisible()) {
        hideMenu();
        if (event) event.stopPropagation();
        return;
    }
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

document.addEventListener('pointerdown', function(event) {
    if (!event.target.closest('#context-menu') && !event.target.closest('#bubble-launcher')) hideMenu();
}, true);
document.addEventListener('click', function(event) {
    if (!event.target.closest('#context-menu') && !event.target.closest('#bubble-launcher')) hideMenu();
});
document.addEventListener('contextmenu', function(event) {
    if (!event.target.closest('#bubble-launcher')) {
        event.preventDefault();
        hideMenu();
    }
});
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') hideMenu();
});
document.addEventListener('pointercancel', function() {
    launcherPointerStart = null;
    launcherClickSuppressed = false;
    setDraggingState(false);
}, true);
window.addEventListener('blur', hideMenu);
window.addEventListener('blur', function() {
    launcherPointerStart = null;
    launcherClickSuppressed = false;
    setDraggingState(false);
});
document.addEventListener('DOMContentLoaded', function() { setTimeout(bootstrap, 300); });
window.addEventListener('pywebviewready', bootstrap);
</script>
</body>
</html>
"""


def _resolve_avatar_uri(config: "AppConfig") -> str:
    avatar_path = Path(config.bubble_mode.avatar_path or DEFAULT_BUBBLE_AVATAR_PATH).expanduser()
    if not avatar_path.exists():
        avatar_path = DEFAULT_BUBBLE_AVATAR_PATH
    return data_uri(avatar_path)


def _render_bubble_html(config: "AppConfig") -> str:
    return _BUBBLE_HTML.replace("{{AVATAR_URL}}", _resolve_avatar_uri(config))


class BubbleWindowAPI:
    """Bubble 模式 WebView API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)
        proactive_config = getattr(
            config,
            "bubble_mode",
            SimpleNamespace(
                proactive_enabled=False,
                proactive_desktop_watch_enabled=False,
                proactive_interval_seconds=300,
            ),
        )
        self._proactive = ProactiveDesktopService(runtime, proactive_config)
        self._bubble_window: Any = None
        self._context_menu_open = False
        self._pointer_dragging = False

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

        proactive = self._get_proactive_state()
        has_proactive_attention = bool(proactive.get("has_attention"))
        return {
            "ok": True,
            "chat": chat,
            "proactive": proactive,
            "bubble": {
                "default_display": bubble.default_display,
                "expand_trigger": bubble.expand_trigger,
                "show_unread_dot": bubble.show_unread_dot,
                "auto_hide": bubble.auto_hide,
                "opacity": bubble.opacity,
                "has_attention": has_proactive_attention,
                "latest_status": latest_status,
                "subtitle": (
                    "从当前会话继续对话"
                    if not chat.get("empty")
                    else "点击展开对话"
                ),
            },
        }

    def _get_proactive_state(self) -> Dict[str, Any]:
        return self._proactive.get_state()

    def _clear_proactive_attention(self) -> None:
        self._proactive.acknowledge()

    def send_quick_message(self, text: str) -> Dict[str, Any]:
        return self._chat_bridge.send_quick_message(text)

    def toggle_chat(self) -> Dict[str, Any]:
        from apps.shell.chat_window import is_chat_window_open, toggle_chat_window

        self._clear_proactive_attention()
        was_open = is_chat_window_open()
        open_after_toggle = toggle_chat_window(self._runtime)
        return {"ok": was_open or open_after_toggle, "open": open_after_toggle}

    def open_chat(self) -> Dict[str, Any]:
        from apps.shell.chat_window import open_chat_window

        self._clear_proactive_attention()
        return {"ok": open_chat_window(self._runtime)}

    def open_main_window(self) -> Dict[str, Any]:
        from apps.shell.window import open_main_window

        return {"ok": open_main_window(self._runtime, self._config)}

    def open_settings(self) -> Dict[str, Any]:
        from apps.shell.settings import open_mode_settings_window

        return {"ok": open_mode_settings_window(self._config, "bubble")}

    def set_context_menu_open(self, is_open: bool) -> Dict[str, Any]:
        self._context_menu_open = bool(is_open)
        return {"ok": True}

    def set_dragging(self, is_dragging: bool) -> Dict[str, Any]:
        self._pointer_dragging = bool(is_dragging)
        return {"ok": True}

    def is_pointer_interactive(self, width: float, height: float, x: float, y: float) -> bool:
        if self._context_menu_open or self._pointer_dragging:
            return True
        try:
            from apps.shell.native_window import bubble_visual_hit_test

            return bubble_visual_hit_test(width, height, x, y)
        except Exception:
            return True

    def focus_window(self) -> Dict[str, Any]:
        try:
            if self._bubble_window is not None:
                for method_name in ("restore", "show", "bring_to_front", "focus"):
                    method = getattr(self._bubble_window, method_name, None)
                    if callable(method):
                        method()
            try:
                from apps.shell.native_window import focus_macos_window

                focus_macos_window(title="Hermes-Yachiyo Bubble")
            except Exception:
                pass
            return {"ok": True}
        except Exception as exc:
            logger.debug("聚焦 Bubble 窗口失败: %s", exc)
            return {"ok": False, "error": str(exc)}

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
            html=_render_bubble_html(config),
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
        try:
            from apps.shell.native_window import schedule_macos_window_behavior

            schedule_macos_window_behavior(
                title="Hermes-Yachiyo Bubble",
                always_on_top=bubble.always_on_top,
                show_on_all_spaces=False,
            )
            from apps.shell.native_window import schedule_macos_pointer_passthrough

            schedule_macos_pointer_passthrough(
                title="Hermes-Yachiyo Bubble",
                hit_test=api.is_pointer_interactive,
                delay_seconds=0.12,
                interval_seconds=0.016,
                focus_on_hover=True,
            )
        except Exception as exc:
            logger.debug("调度 macOS Bubble 窗口行为失败: %s", exc)
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，Bubble 模式无法展示")
