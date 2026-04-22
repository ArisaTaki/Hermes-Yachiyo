"""Live2D 模式。

当前阶段实现桌面角色 launcher，而不是完整聊天窗口：
- 透明无边框角色舞台
- 点击角色展开/收起统一 Chat Window
- 右键菜单提供主控台、模式设置、退出入口
- 保留 renderer / moc3 / 动作系统接入位
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict
from urllib.parse import quote

from apps.installer.workspace_init import get_workspace_status
from apps.shell.assets import data_uri, find_live2d_preview_path, project_display_path
from apps.shell.chat_bridge import ChatBridge
from apps.shell.mode_settings import _serialize_summary

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_PIXI_JS_CDN = "https://cdn.jsdelivr.net/npm/pixi.js@6/dist/browser/pixi.min.js"
_LIVE2D_CUBISM_CORE_CDN = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"
_PIXI_LIVE2D_DISPLAY_CDN = (
    "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.5.0-beta/dist/cubism4.min.js"
)

_LIVE2D_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo Live2D</title>
    <script src="{{PIXI_JS_CDN}}"></script>
    <script src="{{LIVE2D_CUBISM_CORE_CDN}}"></script>
    <script src="{{PIXI_LIVE2D_DISPLAY_CDN}}"></script>
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
            width: min(92vw, 360px);
            height: min(92vh, 620px);
            transform-origin: center bottom;
            filter: drop-shadow(0 14px 18px rgba(0, 0, 0, 0.24));
            animation: live2d-idle 4s ease-in-out infinite;
            display: flex;
            align-items: flex-end;
            justify-content: center;
        }
        .live2d-canvas,
        .live2d-preview-fallback {
            display: block;
            width: 100%;
            height: 100%;
            pointer-events: none;
            user-select: none;
        }
        .live2d-canvas {
            position: absolute;
            inset: 0;
        }
        .live2d-preview-fallback {
            position: absolute;
            inset: auto 0 0 0;
            max-height: 100%;
            object-fit: contain;
        }
        .live2d-preview-fallback.hidden,
        .live2d-loading.hidden,
        .live2d-error.hidden {
            display: none;
        }
        .live2d-loading,
        .live2d-error {
            position: absolute;
            left: 50%;
            bottom: 22px;
            transform: translateX(-50%);
            min-width: 132px;
            max-width: 90%;
            padding: 8px 10px;
            border-radius: 999px;
            background: rgba(20, 24, 31, 0.76);
            color: #edf2f7;
            font-size: 12px;
            line-height: 1.35;
            text-align: center;
            pointer-events: none;
            z-index: 8;
        }
        .live2d-error {
            background: rgba(116, 29, 29, 0.82);
            color: #ffe2e2;
        }
        .live2d-resource-hint {
            position: absolute;
            left: 50%;
            top: 14px;
            transform: translateX(-50%);
            max-width: 92%;
            padding: 8px 10px;
            border-radius: 12px;
            font-size: 12px;
            line-height: 1.45;
            text-align: center;
            z-index: 9;
            pointer-events: none;
            background: rgba(20, 24, 31, 0.72);
            color: #edf2f7;
        }
        .live2d-resource-hint.warn {
            background: rgba(108, 64, 18, 0.86);
            color: #ffe9bf;
        }
        .live2d-resource-hint.ok {
            background: rgba(24, 74, 45, 0.82);
            color: #d9ffe8;
        }
        .live2d-resource-hint.hidden {
            display: none;
        }
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
        .menu-btn:hover,
        .menu-btn:focus { background: rgba(255, 255, 255, 0.1); outline: none; }
        .menu-btn.danger { color: #ffb5b5; }
    </style>
</head>
<body>
    <div class="stage" id="stage" title="Yachiyo - 点击展开对话"
         tabindex="0"
         onpointerdown="trackLauncherPointerDown(event)"
         onpointermove="trackLauncherPointerMove(event)"
         onpointerup="trackLauncherPointerUp(event)"
         onclick="toggleChat(event)" oncontextmenu="showMenu(event)">
        <div class="character" id="character" aria-label="Yachiyo Live2D 角色舞台">
            <canvas class="live2d-canvas" id="live2d-canvas"></canvas>
            <img class="live2d-preview-fallback hidden" id="live2d-fallback-preview" src="{{PREVIEW_URL}}" alt="">
            <div class="live2d-resource-hint hidden" id="live2d-resource-hint"></div>
            <div class="live2d-loading hidden" id="live2d-loading">Live2D 加载中…</div>
            <div class="live2d-error hidden" id="live2d-error"></div>
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
    const CLICK_DRAG_THRESHOLD_PX = 6;
    let polling = null;
    let pollingIntervalMs = null;
    let toggling = false;
    let bootstrapped = false;
    let launcherPointerStart = null;
    let launcherClickSuppressed = false;
    let live2dApp = null;
    let live2dModel = null;
    let live2dModelUrl = '';
    let live2dScale = 1;
    let rendererLoadToken = 0;

    function getCanvas() { return document.getElementById('live2d-canvas'); }
    function getCharacter() { return document.getElementById('character'); }

    function setLoading(message) {
        const node = document.getElementById('live2d-loading');
        node.textContent = message || 'Live2D 加载中…';
        node.classList.remove('hidden');
    }

    function hideLoading() {
        document.getElementById('live2d-loading').classList.add('hidden');
    }

    function showError(message) {
        const node = document.getElementById('live2d-error');
        node.textContent = message;
        node.classList.remove('hidden');
    }

    function hideError() {
        document.getElementById('live2d-error').classList.add('hidden');
    }

    function renderResourceHint(resource) {
        const node = document.getElementById('live2d-resource-hint');
        if (!resource) {
            node.className = 'live2d-resource-hint hidden';
            node.textContent = '';
            return;
        }

        const state = resource.state || '';
        const tone = (state === 'path_valid' || state === 'loaded') ? 'ok' : 'warn';
        const lines = [resource.status_label || ''];
        if (resource.help_text) lines.push(resource.help_text);
        node.textContent = lines.filter(Boolean).join(' ');
        node.className = 'live2d-resource-hint ' + tone;
    }

    function showFallback() {
        document.getElementById('live2d-fallback-preview').classList.remove('hidden');
    }

    function hideFallback() {
        document.getElementById('live2d-fallback-preview').classList.add('hidden');
    }

    function rendererAvailable() {
        return !!(
            window.PIXI
            && window.PIXI.Application
            && window.PIXI.live2d
            && window.PIXI.live2d.Live2DModel
            && window.Live2DCubismCore
        );
    }

    function destroyLive2DRenderer() {
        if (live2dModel && live2dApp && live2dApp.stage) {
            live2dApp.stage.removeChild(live2dModel);
        }
        if (live2dModel && typeof live2dModel.destroy === 'function') {
            live2dModel.destroy();
        }
        live2dModel = null;
        live2dModelUrl = '';
        if (live2dApp && typeof live2dApp.destroy === 'function') {
            live2dApp.destroy(true, {children: true, texture: false, baseTexture: false});
        }
        live2dApp = null;
    }

    function ensurePixiApp() {
        if (live2dApp) return live2dApp;
        const canvas = getCanvas();
        const character = getCharacter();
        live2dApp = new window.PIXI.Application({
            view: canvas,
            autoStart: true,
            backgroundAlpha: 0,
            antialias: true,
            autoDensity: true,
            resizeTo: character,
            resolution: window.devicePixelRatio || 1,
        });
        return live2dApp;
    }

    function fitLive2DModel() {
        if (!live2dModel || !live2dApp) return;
        const character = getCharacter();
        const width = Math.max(character.clientWidth, 1);
        const height = Math.max(character.clientHeight, 1);
        live2dApp.renderer.resize(width, height);
        const bounds = live2dModel.getLocalBounds();
        if (!bounds.width || !bounds.height) return;
        const fitScale = Math.min(width / bounds.width, height / bounds.height) * 0.92;
        const finalScale = fitScale * Math.max(0.4, Math.min(2.0, Number(live2dScale || 1)));
        live2dModel.anchor.set(0.5, 1.0);
        live2dModel.scale.set(finalScale);
        live2dModel.x = width / 2;
        live2dModel.y = height - 6;
    }

    async function ensureLive2DRenderer(view) {
        const live2d = view.live2d || {};
        const renderer = live2d.renderer || {};
        live2dScale = Number(renderer.scale || live2d.scale || 1);

        if (!renderer.enabled || !renderer.model_url) {
            destroyLive2DRenderer();
            hideLoading();
            showFallback();
            if (renderer.reason) showError(renderer.reason);
            return;
        }

        if (!rendererAvailable()) {
            destroyLive2DRenderer();
            hideLoading();
            showFallback();
            showError('Live2D 渲染依赖未加载，已回退到静态预览');
            return;
        }

        hideError();
        setLoading('Live2D 模型加载中…');
        const currentToken = ++rendererLoadToken;

        try {
            if (!live2dModel || live2dModelUrl !== renderer.model_url) {
                destroyLive2DRenderer();
                const app = ensurePixiApp();
                const model = await window.PIXI.live2d.Live2DModel.from(renderer.model_url, {
                    autoInteract: false,
                });
                if (currentToken !== rendererLoadToken) {
                    if (typeof model.destroy === 'function') model.destroy();
                    return;
                }
                live2dModel = model;
                live2dModelUrl = renderer.model_url;
                live2dModel.interactive = false;
                app.stage.addChild(model);
            }
            fitLive2DModel();
            hideFallback();
            hideError();
        } catch (error) {
            destroyLive2DRenderer();
            showFallback();
            showError('Live2D 模型加载失败，已回退到静态预览');
        } finally {
            hideLoading();
        }
    }

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
            return;
        }
        launcherPointerStart = pointerPoint(event);
        launcherClickSuppressed = false;
    }

    function trackLauncherPointerMove(event) {
        if (launcherPointerMoved(event)) launcherClickSuppressed = true;
    }

    function trackLauncherPointerUp(event) {
        if (launcherPointerMoved(event)) launcherClickSuppressed = true;
    }

    function shouldIgnoreLauncherClick(event) {
        const ignore = launcherClickSuppressed || launcherPointerMoved(event);
        launcherPointerStart = null;
        launcherClickSuppressed = false;
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
        positionMenu(event);
        const firstItem = menu.querySelector('.menu-btn');
        if (firstItem) setTimeout(function() {
            try { firstItem.focus({preventScroll: true}); }
            catch (error) { firstItem.focus(); }
        }, 0);
    }

    function renderLive2D(view) {
        const live2d = view.live2d || {};
        const chat = view.chat || {};
        const resource = live2d.resource || {};
        const character = document.getElementById('character');
        const scale = Math.max(0.4, Math.min(2.0, Number(live2d.scale || 1)));
        live2dScale = scale;
        character.style.setProperty('--live2d-scale', String(scale));
        const dot = document.getElementById('status-dot');
        let status = 'ready';
        if (chat.is_processing) status = 'processing';
        else if (chat.messages && chat.messages.some(function(m) { return m.status === 'failed'; })) status = 'failed';

        const hasAttention = !!chat.latest_reply && !chat.is_processing;
        dot.className = 'status-dot visible ' + status + (hasAttention ? ' attention' : '');
        dot.style.display = (hasAttention || chat.is_processing || status === 'failed') ? 'block' : 'none';

        document.getElementById('stage').title =
            ((resource.status_label || 'Yachiyo Live2D') + '，点击展开对话');

        renderResourceHint(resource);

        ensureLive2DRenderer(view);

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

    async function toggleChat(event) {
        if (shouldIgnoreLauncherClick(event)) return;
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
        if (bootstrapped) return;
        bootstrapped = true;
        refreshLive2D();
        startIdlePolling();
    }

    document.addEventListener('pointerdown', function(event) {
        if (!event.target.closest('#context-menu') && !event.target.closest('#stage')) hideMenu();
    }, true);
    document.addEventListener('click', function(event) {
        if (!event.target.closest('#context-menu') && !event.target.closest('#stage')) hideMenu();
    });
    document.addEventListener('contextmenu', function(event) {
        if (!event.target.closest('#stage')) {
            event.preventDefault();
            hideMenu();
        }
    });
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape') hideMenu();
    });
    window.addEventListener('blur', hideMenu);
    window.addEventListener('resize', fitLive2DModel);
    document.addEventListener('DOMContentLoaded', function() { setTimeout(bootstrap, 300); });
    window.addEventListener('pywebviewready', bootstrap);
    </script>
</body>
</html>
"""


def _resolve_live2d_preview_path(config: "AppConfig") -> Path:
    resolved_path = config.live2d_mode.resolve_model_path()
    return find_live2d_preview_path(resolved_path or "")


def _get_bridge_state() -> str:
    try:
        from apps.bridge.server import get_bridge_state as _get

        return _get()
    except Exception:
        return "not_started"


def _get_bridge_running_config(config: "AppConfig") -> dict[str, object]:
    try:
        from apps.bridge.server import get_running_config as _get

        return _get()
    except Exception:
        return {"host": config.bridge_host, "port": config.bridge_port}


def _resolve_live2d_renderer_entry(config: "AppConfig") -> Path | None:
    summary = config.live2d_mode.resource_info().summary
    if summary and summary.renderer_entry:
        return Path(summary.renderer_entry).expanduser().resolve()
    return None


def _build_live2d_model_url(config: "AppConfig") -> str:
    entry = _resolve_live2d_renderer_entry(config)
    if entry is None:
        return ""

    resolved_root = config.live2d_mode.resolve_model_path()
    if resolved_root is None:
        return ""
    root = resolved_root.expanduser().resolve()
    try:
        rel_path = entry.relative_to(root).as_posix()
    except ValueError:
        return ""

    runtime_config = _get_bridge_running_config(config)
    host = runtime_config.get("host") or config.bridge_host
    port = runtime_config.get("port") or config.bridge_port
    return f"http://{host}:{port}/live2d/assets/{quote(rel_path, safe='/')}"


def _resolve_live2d_preview_uri(config: "AppConfig") -> str:
    return data_uri(_resolve_live2d_preview_path(config))


def _render_live2d_html(config: "AppConfig") -> str:
    return (
        _LIVE2D_HTML
        .replace("{{PREVIEW_URL}}", _resolve_live2d_preview_uri(config))
        .replace("{{PIXI_JS_CDN}}", _PIXI_JS_CDN)
        .replace("{{LIVE2D_CUBISM_CORE_CDN}}", _LIVE2D_CUBISM_CORE_CDN)
        .replace("{{PIXI_LIVE2D_DISPLAY_CDN}}", _PIXI_LIVE2D_DISPLAY_CDN)
    )


class Live2DWindowAPI:
    """Live2D 模式 WebView API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)
        self._live2d_window: Any = None

    def get_live2d_view(self) -> Dict[str, Any]:
        live2d = self._config.live2d_mode
        resource = live2d.resource_info()
        chat = self._chat_bridge.get_conversation_overview(summary_count=3, session_limit=3)
        runner = self._runtime.task_runner
        executor_label = "执行器不可用"
        if runner is not None:
            executor_label = "Hermes" if runner.executor.name == "HermesExecutor" else "模拟"

        bridge_state = _get_bridge_state()
        bridge_label_map = {
            "running": "Bridge 运行中",
            "failed": "Bridge 异常",
        }
        preview_path = _resolve_live2d_preview_path(self._config)
        model_url = _build_live2d_model_url(self._config)
        renderer_enabled = (
            bool(model_url)
            and bridge_state == "running"
            and self._config.bridge_enabled
            and resource.state.value in {"path_valid", "loaded"}
        )
        if resource.state.value not in {"path_valid", "loaded"}:
            renderer_reason = resource.help_text or resource.status_label
        elif bridge_state != "running":
            renderer_reason = "Bridge 未运行，暂时无法加载 Live2D 模型"
        elif not model_url:
            renderer_reason = "未找到可加载的 model3.json 入口"
        else:
            renderer_reason = ""

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
                "model_state": resource.state.value,
                "model_name": resource.display_name,
                "configured_model_name": live2d.model_name or "",
                "model_path": live2d.model_path or "",
                "model_path_display": resource.configured_path_display,
                "effective_model_path": resource.effective_model_path,
                "effective_model_path_display": resource.effective_model_path_display,
                "preview_path": str(preview_path),
                "preview_path_display": project_display_path(preview_path),
                "renderer_mode": "static_preview",
                "scale": live2d.scale,
                "window_on_top": live2d.window_on_top,
                "show_on_all_spaces": live2d.show_on_all_spaces,
                "show_reply_bubble": live2d.show_reply_bubble,
                "enable_quick_input": live2d.enable_quick_input,
                "preview_url": data_uri(preview_path),
                "click_action": "open_chat",
                "default_open_behavior": live2d.default_open_behavior,
                "status_label": resource.status_label,
                "help_text": resource.help_text,
                "summary": _serialize_summary(resource.summary),
                "resource": {
                    "state": resource.state.value,
                    "source": resource.source,
                    "source_label": resource.source_label,
                    "display_name": resource.display_name,
                    "configured_path": resource.configured_path,
                    "configured_path_display": resource.configured_path_display,
                    "effective_model_path": resource.effective_model_path,
                    "effective_model_path_display": resource.effective_model_path_display,
                    "default_assets_root": resource.default_assets_root,
                    "default_assets_root_display": resource.default_assets_root_display,
                    "releases_url": resource.releases_url,
                    "status_label": resource.status_label,
                    "help_text": resource.help_text,
                },
                "renderer": {
                    "enabled": renderer_enabled,
                    "model_url": model_url,
                    "reason": renderer_reason,
                    "scale": live2d.scale,
                    "idle_motion_group": live2d.idle_motion_group,
                    "enable_expressions": live2d.enable_expressions,
                    "enable_physics": live2d.enable_physics,
                },
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

    def focus_window(self) -> Dict[str, Any]:
        try:
            if self._live2d_window is not None:
                for method_name in ("restore", "show", "bring_to_front", "focus"):
                    method = getattr(self._live2d_window, method_name, None)
                    if callable(method):
                        method()
            try:
                from apps.shell.native_window import focus_macos_window

                focus_macos_window(title="Hermes-Yachiyo Live2D")
            except Exception:
                pass
            return {"ok": True}
        except Exception as exc:
            logger.debug("聚焦 Live2D 窗口失败: %s", exc)
            return {"ok": False, "error": str(exc)}

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
            html=_render_live2d_html(config),
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
        api._live2d_window = win
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
