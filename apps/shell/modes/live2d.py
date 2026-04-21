"""Live2D 模式。

当前阶段实现桌面角色 launcher，而不是完整聊天窗口：
- 透明无边框角色舞台
- 点击角色展开/收起统一 Chat Window
- 右键菜单提供主控台、模式设置、退出入口
- 保留 renderer / moc3 / 动作系统接入位
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.bridge.server import get_bridge_state
from apps.installer.workspace_init import get_workspace_status
from apps.shell.chat_bridge import ChatBridge
from apps.shell.mode_settings import _serialize_summary

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_LIVE2D_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo Live2D</title>
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
        @keyframes live2d-idle {
            0%, 100% { transform: translateY(0) scale(var(--live2d-scale, 1)); }
            50% { transform: translateY(-8px) scale(var(--live2d-scale, 1)); }
        }
        @keyframes unread-pulse {
            0% { box-shadow: 0 0 0 0 rgba(255, 100, 100, 0.72); }
            70% { box-shadow: 0 0 0 13px rgba(255, 100, 100, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 100, 100, 0); }
        }
        @keyframes thinking-dot {
            0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-1px); }
        }
        .stage {
            position: relative;
            width: min(92vw, 330px);
            height: min(94vh, 610px);
            display: flex;
            align-items: flex-end;
            justify-content: center;
            cursor: pointer;
        }
        .character {
            position: relative;
            width: 250px;
            height: 520px;
            transform-origin: center bottom;
            filter: drop-shadow(0 18px 22px rgba(0, 0, 0, 0.34));
            animation: live2d-idle 4s ease-in-out infinite;
        }
        .hair-back {
            position: absolute;
            left: 37px;
            top: 42px;
            width: 176px;
            height: 360px;
            border-radius: 88px 88px 110px 110px;
            background:
                linear-gradient(90deg, transparent 0 10%, rgba(245, 212, 232, 0.92) 11% 18%, transparent 19% 81%, rgba(215, 234, 255, 0.92) 82% 89%, transparent 90%),
                linear-gradient(180deg, #f7f8ff 0%, #eef1ff 56%, rgba(213, 250, 245, 0.94) 100%);
            z-index: 1;
        }
        .head {
            position: absolute;
            left: 74px;
            top: 55px;
            width: 102px;
            height: 112px;
            border-radius: 48% 48% 45% 45%;
            background: linear-gradient(180deg, #fff1ea 0%, #f6d4ca 100%);
            z-index: 5;
            box-shadow: inset 0 -8px 12px rgba(210, 120, 120, 0.08);
        }
        .bangs {
            position: absolute;
            left: 62px;
            top: 42px;
            width: 126px;
            height: 72px;
            border-radius: 70px 70px 32px 32px;
            background: linear-gradient(180deg, #fff 0%, #edf2ff 100%);
            z-index: 7;
            clip-path: polygon(0 0, 100% 0, 94% 72%, 78% 43%, 67% 78%, 52% 40%, 42% 76%, 30% 44%, 17% 72%, 8% 44%);
        }
        .tail-left,
        .tail-right {
            position: absolute;
            top: 74px;
            width: 48px;
            height: 330px;
            background: linear-gradient(180deg, #f9fbff 0%, #eef3ff 62%, rgba(236, 198, 230, 0.94) 100%);
            z-index: 2;
            border-radius: 32px 32px 80% 80%;
        }
        .tail-left { left: 36px; transform: rotate(4deg); }
        .tail-right { right: 36px; transform: rotate(-4deg); }
        .ear-left,
        .ear-right {
            position: absolute;
            top: 28px;
            width: 38px;
            height: 38px;
            border: 7px solid #f7f9ff;
            border-bottom-color: transparent;
            border-radius: 50%;
            z-index: 4;
        }
        .ear-left { left: 66px; }
        .ear-right { right: 66px; }
        .eye {
            position: absolute;
            top: 105px;
            width: 13px;
            height: 18px;
            border-radius: 50%;
            background: radial-gradient(circle at 40% 36%, #ffffff 0 13%, #7c8ddb 14% 42%, #37395a 43% 100%);
            z-index: 8;
        }
        .eye.left { left: 101px; }
        .eye.right { right: 101px; }
        .mouth {
            position: absolute;
            left: 50%;
            top: 135px;
            width: 18px;
            height: 9px;
            border-bottom: 2px solid #d77a87;
            border-radius: 50%;
            transform: translateX(-50%);
            z-index: 8;
        }
        .neck {
            position: absolute;
            left: 108px;
            top: 157px;
            width: 34px;
            height: 44px;
            background: #f1c9c0;
            z-index: 4;
        }
        .torso {
            position: absolute;
            left: 66px;
            top: 182px;
            width: 118px;
            height: 142px;
            border-radius: 42px 42px 30px 30px;
            background: linear-gradient(180deg, #312a48 0 42%, #24394a 43% 100%);
            z-index: 5;
        }
        .collar {
            position: absolute;
            left: 92px;
            top: 176px;
            width: 66px;
            height: 54px;
            background: #f1c9c0;
            clip-path: polygon(0 0, 100% 0, 76% 100%, 50% 58%, 24% 100%);
            z-index: 6;
        }
        .sleeve-left,
        .sleeve-right {
            position: absolute;
            top: 206px;
            width: 58px;
            height: 96px;
            background: linear-gradient(180deg, #354f67 0%, #2a3047 100%);
            border-radius: 28px;
            z-index: 4;
        }
        .sleeve-left { left: 24px; transform: rotate(18deg); }
        .sleeve-right { right: 24px; transform: rotate(-18deg); }
        .hand-left,
        .hand-right {
            position: absolute;
            top: 293px;
            width: 24px;
            height: 34px;
            background: #f2ccc4;
            border-radius: 14px;
            z-index: 3;
        }
        .hand-left { left: 21px; transform: rotate(20deg); }
        .hand-right { right: 21px; transform: rotate(-20deg); }
        .skirt {
            position: absolute;
            left: 44px;
            top: 300px;
            width: 162px;
            height: 140px;
            background:
                linear-gradient(145deg, transparent 0 18%, #69d7c6 19% 43%, transparent 44%),
                linear-gradient(215deg, transparent 0 18%, #7761a8 19% 43%, transparent 44%),
                linear-gradient(180deg, #2c3048 0%, #2d3250 62%, #9ce7de 63% 100%);
            clip-path: polygon(15% 0, 85% 0, 100% 82%, 76% 72%, 60% 100%, 49% 75%, 35% 100%, 23% 72%, 0 82%);
            z-index: 4;
        }
        .leg-left,
        .leg-right {
            position: absolute;
            top: 414px;
            width: 28px;
            height: 86px;
            background: linear-gradient(180deg, #f6dbd4 0%, #eac5bd 100%);
            border-radius: 16px;
            z-index: 2;
        }
        .leg-left { left: 93px; }
        .leg-right { right: 93px; }
        .shoe-left,
        .shoe-right {
            position: absolute;
            top: 492px;
            width: 34px;
            height: 18px;
            background: #f8eee2;
            border-radius: 12px 12px 8px 8px;
            z-index: 2;
        }
        .shoe-left { left: 88px; }
        .shoe-right { right: 88px; }
        .status-dot {
            position: absolute;
            right: 38px;
            top: 90px;
            width: 14px;
            height: 14px;
            border-radius: 50%;
            border: 2px solid rgba(20, 20, 20, 0.76);
            background: #71e28c;
            z-index: 10;
            display: none;
        }
        .status-dot.visible { display: block; }
        .status-dot.processing {
            background: #ffd166;
            animation: unread-pulse 1.45s infinite;
        }
        .status-dot.failed,
        .status-dot.attention {
            background: #ff6b6b;
            animation: unread-pulse 1.6s infinite;
        }
        .context-menu {
            position: fixed;
            right: 12px;
            bottom: 12px;
            min-width: 128px;
            padding: 6px;
            border-radius: 8px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            background: rgba(22, 24, 29, 0.96);
            box-shadow: 0 16px 32px rgba(0, 0, 0, 0.36);
            display: none;
            z-index: 20;
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
    <div class="stage" id="stage" title="Yachiyo - 点击展开对话"
         onclick="toggleChat()" oncontextmenu="showMenu(event)">
        <div class="character" id="character" aria-label="Yachiyo Live2D renderer 预留">
            <div class="hair-back"></div>
            <div class="tail-left"></div>
            <div class="tail-right"></div>
            <div class="ear-left"></div>
            <div class="ear-right"></div>
            <div class="head"></div>
            <div class="bangs"></div>
            <div class="eye left"></div>
            <div class="eye right"></div>
            <div class="mouth"></div>
            <div class="neck"></div>
            <div class="collar"></div>
            <div class="torso"></div>
            <div class="sleeve-left"></div>
            <div class="sleeve-right"></div>
            <div class="hand-left"></div>
            <div class="hand-right"></div>
            <div class="skirt"></div>
            <div class="leg-left"></div>
            <div class="leg-right"></div>
            <div class="shoe-left"></div>
            <div class="shoe-right"></div>
            <span class="status-dot" id="status-dot" aria-hidden="true"></span>
        </div>
    </div>

    <div class="context-menu" id="context-menu">
        <button class="menu-btn" type="button" onclick="openChat()">打开对话</button>
        <button class="menu-btn" type="button" onclick="openMainWindow()">主控台</button>
        <button class="menu-btn" type="button" onclick="openSettings()">设置</button>
        <button class="menu-btn danger" type="button" onclick="closeLive2D()">退出</button>
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
        polling = setInterval(refreshLive2D, intervalMs);
    }

    function startActivePolling() { setPollingInterval(ACTIVE_POLL_INTERVAL_MS); }
    function startIdlePolling() { setPollingInterval(IDLE_POLL_INTERVAL_MS); }
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

    function renderLive2D(view) {
        const live2d = view.live2d || {};
        const chat = view.chat || {};
        const character = document.getElementById('character');
        const scale = Math.max(0.4, Math.min(2.0, Number(live2d.scale || 1)));
        character.style.setProperty('--live2d-scale', String(scale));
        const dot = document.getElementById('status-dot');
        let status = 'ready';
        if (chat.is_processing) status = 'processing';
        else if (chat.messages && chat.messages.some(function(m) { return m.status === 'failed'; })) status = 'failed';

        const hasAttention = !!chat.latest_reply && !chat.is_processing;
        dot.className = 'status-dot visible ' + status + (hasAttention ? ' attention' : '');
        dot.style.display = (hasAttention || chat.is_processing || status === 'failed') ? 'block' : 'none';

        const stateLabels = {
            not_configured: 'Live2D renderer 预留 - 模型未配置',
            path_invalid: 'Live2D renderer 预留 - 模型路径不存在',
            path_not_live2d: 'Live2D renderer 预留 - 目录无模型文件',
            path_valid: 'Live2D renderer 预留 - 模型目录就绪',
            loaded: 'Live2D 模型已加载',
        };
        document.getElementById('stage').title =
            (stateLabels[live2d.model_state] || 'Yachiyo Live2D') + '，点击展开对话';

        if (chat.is_processing) startActivePolling();
        else startIdlePolling();
    }

    async function refreshLive2D() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const view = await window.pywebview.api.get_live2d_view();
            if (!view.ok) return;
            renderLive2D(view);
        } catch (error) {}
    }

    async function toggleChat() {
        if (toggling) return;
        hideMenu();
        toggling = true;
        try {
            if (window.pywebview && window.pywebview.api) {
                await window.pywebview.api.toggle_chat();
                await refreshLive2D();
            }
        } finally {
            toggling = false;
        }
    }

    async function openChat() {
        hideMenu();
        if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_chat();
    }

    async function openMainWindow() {
        hideMenu();
        if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_main_window();
    }

    async function openSettings() {
        hideMenu();
        if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_settings();
    }

    async function closeLive2D() {
        hideMenu();
        if (window.pywebview && window.pywebview.api) await window.pywebview.api.close_live2d();
    }

    function bootstrap() {
        refreshLive2D();
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


class Live2DWindowAPI:
    """Live2D 模式 WebView API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)

    def get_live2d_view(self) -> Dict[str, Any]:
        live2d = self._config.live2d_mode
        chat = self._chat_bridge.get_conversation_overview(summary_count=3, session_limit=3)
        runner = self._runtime.task_runner
        executor_label = "执行器不可用"
        if runner is not None:
            executor_label = "Hermes" if runner.executor.name == "HermesExecutor" else "模拟"

        bridge_state = get_bridge_state()
        bridge_label_map = {
            "running": "Bridge 运行中",
            "failed": "Bridge 异常",
        }

        return {
            "ok": True,
            "chat": chat,
            "hermes": {
                "ready": self._runtime.is_hermes_ready(),
                "status": self._runtime.get_status().get("hermes", {}).get("install_status", "unknown"),
            },
            "workspace": {
                "initialized": get_workspace_status().get("initialized", False),
            },
            "live2d": {
                "model_state": live2d.validate().value,
                "model_name": live2d.model_name or "",
                "model_path": live2d.model_path or "",
                "scale": live2d.scale,
                "window_on_top": live2d.window_on_top,
                "show_on_all_spaces": live2d.show_on_all_spaces,
                "show_reply_bubble": live2d.show_reply_bubble,
                "enable_quick_input": live2d.enable_quick_input,
                "click_action": "open_chat",
                "default_open_behavior": live2d.default_open_behavior,
                "summary": _serialize_summary(live2d.scan()),
            },
            "bridge_label": bridge_label_map.get(bridge_state, "Bridge 启动中"),
            "executor_label": executor_label,
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

        return {"ok": open_mode_settings_window(self._config, "live2d")}

    def close_live2d(self) -> Dict[str, Any]:
        try:
            from apps.shell.window import request_app_exit

            request_app_exit()
            return {"ok": True}
        except Exception as exc:
            logger.error("退出 Live2D 模式失败: %s", exc)
            return {"ok": False, "error": str(exc)}


def run(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """Live2D 模式入口（阻塞主线程）。"""
    logger.info("启动 Live2D 模式（透明角色 launcher）")
    try:
        import webview  # type: ignore[import]

        live2d = config.live2d_mode
        api = Live2DWindowAPI(runtime, config)
        win = webview.create_window(
            title="Hermes-Yachiyo Live2D",
            html=_LIVE2D_HTML,
            width=live2d.width,
            height=live2d.height,
            x=live2d.position_x,
            y=live2d.position_y,
            resizable=False,
            on_top=live2d.window_on_top,
            js_api=api,
            frameless=True,
            transparent=True,
            easy_drag=True,
            text_select=False,
        )
        try:
            from apps.shell.window import bind_app_window_exit

            bind_app_window_exit(win, label="Live2D 窗口")
        except Exception as exc:
            logger.warning("绑定 Live2D 退出事件失败: %s", exc)

        try:
            from apps.shell.native_window import schedule_macos_window_behavior

            schedule_macos_window_behavior(
                title="Hermes-Yachiyo Live2D",
                always_on_top=live2d.window_on_top,
                show_on_all_spaces=live2d.show_on_all_spaces,
            )
        except Exception as exc:
            logger.debug("调度 macOS Live2D 窗口行为失败: %s", exc)

        if live2d.auto_open_chat_window:
            try:
                from apps.shell.chat_window import open_chat_window

                open_chat_window(runtime)
            except Exception as exc:
                logger.warning("Live2D 启动时打开 Chat Window 失败: %s", exc)

        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，Live2D 模式无法展示")
