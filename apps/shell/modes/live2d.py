"""Live2D 模式。

当前阶段实现桌面角色 launcher，而不是完整聊天窗口：
- 透明无边框角色舞台
- 点击角色展开/收起统一 Chat Window
- 右键菜单提供主控台、模式设置、退出入口
- 保留 renderer / moc3 / 动作系统接入位
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from apps.installer.workspace_init import get_workspace_status
from apps.shell.assets import (
    data_uri,
    find_live2d_preview_path,
    get_yachiyo_workspace_dir,
    project_display_path,
)
from apps.shell.chat_bridge import ChatBridge
from apps.shell.launcher_notifications import LauncherNotificationTracker
from apps.shell.mode_settings import _serialize_summary
from apps.shell.proactive import ProactiveDesktopService
from apps.shell.tts import TTSService

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_PIXI_JS_CDN = "https://cdn.jsdelivr.net/npm/pixi.js@6/dist/browser/pixi.min.js"
_LIVE2D_CUBISM_CORE_CDN = "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js"
_PIXI_LIVE2D_DISPLAY_CDN = (
    "https://cdn.jsdelivr.net/npm/pixi-live2d-display@0.5.0-beta/dist/cubism4.min.js"
)
_LIVE2D_RUNTIME_DEPENDENCY_STATE: dict[str, object] = {
    "primed": False,
    "ready": False,
    "error": "",
}

_LIVE2D_RUNTIME_ENV_SHIM = """
<script>
(function() {
    var scope = typeof globalThis !== 'undefined' ? globalThis : window;
    scope.process = scope.process || {};
    scope.process.env = scope.process.env || {};
    if (!scope.process.env.NODE_ENV) {
        scope.process.env.NODE_ENV = 'production';
    }
})();
</script>
""".strip()


def _compact_client_detail(value: object, *, limit: int = 360) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text


def _get_live2d_runtime_cache_dir() -> Path:
    return get_yachiyo_workspace_dir() / "cache" / "live2d-web"


def _get_live2d_runtime_dependency_specs() -> dict[str, tuple[str, Path]]:
    cache_dir = _get_live2d_runtime_cache_dir()
    return {
        "pixi_js": (_PIXI_JS_CDN, cache_dir / "pixi.min.js"),
        "live2d_cubism_core": (
            _LIVE2D_CUBISM_CORE_CDN,
            cache_dir / "live2dcubismcore.min.js",
        ),
        "pixi_live2d_display": (
            _PIXI_LIVE2D_DISPLAY_CDN,
            cache_dir / "pixi-live2d-display-cubism4.min.js",
        ),
    }


def _runtime_dependency_files_ready() -> bool:
    specs = _get_live2d_runtime_dependency_specs()
    return all(path.exists() and path.is_file() and path.stat().st_size > 0 for _, path in specs.values())


def _download_live2d_runtime_dependency(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": "Hermes-Yachiyo/0.1"})
    with urlopen(request, timeout=20) as response:
        payload = response.read()
    if not payload:
        raise RuntimeError(f"下载 {target.name} 时收到空响应")

    temp_path = target.with_name(f".{target.name}.tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(target)


def _prime_live2d_runtime_dependencies(force: bool = False) -> tuple[bool, str]:
    if not force and _LIVE2D_RUNTIME_DEPENDENCY_STATE.get("primed"):
        return bool(_LIVE2D_RUNTIME_DEPENDENCY_STATE.get("ready")), str(
            _LIVE2D_RUNTIME_DEPENDENCY_STATE.get("error") or ""
        )

    specs = _get_live2d_runtime_dependency_specs()
    error = ""
    ready = True
    try:
        for url, path in specs.values():
            if not force and path.exists() and path.stat().st_size > 0:
                continue
            _download_live2d_runtime_dependency(url, path)
        ready = _runtime_dependency_files_ready()
    except Exception as exc:
        ready = False
        error = f"{exc}"
        logger.warning("准备 Live2D 渲染依赖失败: %s", exc)

    _LIVE2D_RUNTIME_DEPENDENCY_STATE["primed"] = True
    _LIVE2D_RUNTIME_DEPENDENCY_STATE["ready"] = ready
    _LIVE2D_RUNTIME_DEPENDENCY_STATE["error"] = error
    return ready, error


def _get_live2d_runtime_dependency_state() -> tuple[bool, bool, str]:
    primed = bool(_LIVE2D_RUNTIME_DEPENDENCY_STATE.get("primed"))
    ready = bool(_LIVE2D_RUNTIME_DEPENDENCY_STATE.get("ready"))
    error = str(_LIVE2D_RUNTIME_DEPENDENCY_STATE.get("error") or "")
    if ready:
        return primed, True, ""
    if _runtime_dependency_files_ready():
        _LIVE2D_RUNTIME_DEPENDENCY_STATE["ready"] = True
        _LIVE2D_RUNTIME_DEPENDENCY_STATE["error"] = ""
        return primed, True, ""
    return primed, False, error


def _read_live2d_runtime_script_tag(path: Path) -> str:
    script_body = path.read_text(encoding="utf-8", errors="ignore")
    script_body = script_body.replace("</script", "<\\/script")
    return f"<script>\n{script_body}\n</script>"


def _build_live2d_runtime_script_tags() -> dict[str, str]:
    tags = {
        "pixi_js": f'<script src="{_PIXI_JS_CDN}"></script>',
        "live2d_cubism_core": f'<script src="{_LIVE2D_CUBISM_CORE_CDN}"></script>',
        "pixi_live2d_display": f'<script src="{_PIXI_LIVE2D_DISPLAY_CDN}"></script>',
    }
    cached_all = True
    for key, (_source_url, path) in _get_live2d_runtime_dependency_specs().items():
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            tags[key] = _read_live2d_runtime_script_tag(path)
        else:
            cached_all = False

    if cached_all:
        logger.info("Live2D 渲染脚本使用本地缓存内联加载")
    else:
        logger.info("Live2D 渲染脚本存在缺口，回退到外部脚本地址")
    return tags

_LIVE2D_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo Live2D</title>
    {{RUNTIME_ENV_SHIM}}
    {{PIXI_JS_TAG}}
    {{LIVE2D_CUBISM_CORE_TAG}}
    {{PIXI_LIVE2D_DISPLAY_TAG}}
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
        @keyframes live2d-message-glow {
            0%, 100% {
                filter: drop-shadow(0 14px 18px rgba(0, 0, 0, 0.24))
                    drop-shadow(0 0 0 rgba(255, 214, 132, 0));
            }
            50% {
                filter: drop-shadow(0 14px 18px rgba(0, 0, 0, 0.24))
                    drop-shadow(0 0 18px rgba(255, 214, 132, 0.62));
            }
        }
        @keyframes live2d-processing-glow {
            0%, 100% {
                filter: drop-shadow(0 14px 18px rgba(0, 0, 0, 0.24))
                    drop-shadow(0 0 6px rgba(124, 214, 255, 0.24));
            }
            50% {
                filter: drop-shadow(0 14px 18px rgba(0, 0, 0, 0.24))
                    drop-shadow(0 0 20px rgba(124, 214, 255, 0.58));
            }
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
            cursor: default;
        }
        .character {
            position: relative;
            width: min(92vw, 360px);
            height: min(92vh, 620px);
            transform-origin: center bottom;
            filter: drop-shadow(0 14px 18px rgba(0, 0, 0, 0.24));
            display: flex;
            align-items: flex-end;
            justify-content: center;
        }
        .character.has-message {
            animation: live2d-message-glow 1.8s ease-in-out infinite;
        }
        .character.processing {
            animation: live2d-processing-glow 1.45s ease-in-out infinite;
        }
        .character.failed {
            filter: drop-shadow(0 14px 18px rgba(0, 0, 0, 0.24))
                drop-shadow(0 0 14px rgba(255, 130, 130, 0.46));
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
            transform: scale(var(--live2d-preview-scale, 1));
            transform-origin: center bottom;
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
            white-space: pre-wrap;
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
            text-align: left;
            display: flex;
            align-items: flex-start;
            gap: 8px;
            z-index: 9;
            pointer-events: auto;
            background: rgba(20, 24, 31, 0.72);
            color: #edf2f7;
        }
        .live2d-resource-hint-text {
            flex: 1;
        }
        .live2d-resource-hint-close {
            border: 0;
            background: transparent;
            color: inherit;
            cursor: pointer;
            font-size: 14px;
            line-height: 1;
            padding: 0;
            opacity: 0.82;
        }
        .live2d-resource-hint-close:hover,
        .live2d-resource-hint-close:focus {
            opacity: 1;
            outline: none;
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
        .reply-bubble {
            position: absolute;
            left: 50%;
            top: 24px;
            transform: translateX(-50%);
            width: min(88%, 300px);
            padding: 10px 12px;
            border-radius: 16px 16px 16px 6px;
            background: rgba(20, 24, 31, 0.78);
            color: #fff7df;
            font-size: 12px;
            line-height: 1.45;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22);
            z-index: 14;
            pointer-events: auto;
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
        }
        .reply-bubble.proactive {
            background: rgba(79, 42, 24, 0.84);
            color: #ffe7c2;
        }
        .reply-bubble.hidden,
        .quick-input.hidden {
            display: none;
        }
        .quick-input {
            position: absolute;
            left: 50%;
            bottom: 18px;
            transform: translateX(-50%);
            width: min(88%, 306px);
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 7px;
            border-radius: 999px;
            background: rgba(20, 24, 31, 0.82);
            border: 1px solid rgba(255, 255, 255, 0.16);
            z-index: 15;
            pointer-events: auto;
        }
        .quick-input input {
            min-width: 0;
            flex: 1;
            border: 0;
            background: transparent;
            color: #fff7df;
            outline: none;
            font-size: 12px;
        }
        .quick-input button {
            border: 0;
            border-radius: 999px;
            padding: 5px 9px;
            background: rgba(134, 169, 255, 0.88);
            color: #101326;
            cursor: pointer;
            font-size: 12px;
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
         onpointerleave="handleStagePointerLeave(event)"
         onclick="handleStageClick(event)" oncontextmenu="showMenu(event)">
        <div class="character" id="character" aria-label="Yachiyo Live2D 角色舞台">
            <canvas class="live2d-canvas" id="live2d-canvas"></canvas>
            <img class="live2d-preview-fallback hidden" id="live2d-fallback-preview" src="{{PREVIEW_URL}}" alt="">
            <div class="live2d-resource-hint hidden" id="live2d-resource-hint">
                <span class="live2d-resource-hint-text" id="live2d-resource-hint-text"></span>
                <button
                    class="live2d-resource-hint-close"
                    id="live2d-resource-hint-close"
                    type="button"
                    onclick="dismissResourceHint(event)"
                    aria-label="关闭资源提示"
                >×</button>
            </div>
            <div class="live2d-loading hidden" id="live2d-loading">Live2D 加载中…</div>
            <div class="live2d-error hidden" id="live2d-error"></div>
        </div>
        <div class="reply-bubble hidden" id="reply-bubble" onclick="event.stopPropagation()">
            <span id="reply-bubble-text"></span>
        </div>
        <div class="quick-input hidden" id="quick-input" onclick="event.stopPropagation()">
            <input id="quick-input-text" type="text" placeholder="和八千代说点什么…" onkeydown="handleQuickInputKey(event)">
            <button type="button" onclick="sendQuickInput(event)">发送</button>
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
    const GLOBAL_POINTER_SYNC_INTERVAL_MS = 40;
    const CLICK_DRAG_THRESHOLD_PX = 6;
    let polling = null;
    let pollingIntervalMs = null;
    let globalPointerPolling = null;
    let toggling = false;
    let bootstrapped = false;
    let launcherPointerStart = null;
    let launcherClickSuppressed = false;
    let live2dApp = null;
    let live2dModel = null;
    let live2dModelUrl = '';
    let live2dScale = 1;
    let rendererLoadToken = 0;
    let lastReportedRendererEvent = '';
    let currentResourceHintKey = '';
    let dismissedResourceHintKey = '';
    let lastHitRegionPayload = '';
    let lastUIRegionsPayload = '';
    let currentHitRegion = null;
    let currentUIRegions = [];
    let launcherDragging = false;
    let currentLive2DView = null;
    let replyBubbleManuallyHidden = false;
    let lastReplyBubbleText = '';
    let defaultOpenBehaviorApplied = false;
    let live2dMouseFollowEnabled = true;
    let lastPointerLocalX = 0;
    let lastPointerLocalY = 0;
    let lastPointerInsideWindow = false;
    const HIT_MASK_MIN_COLS = 32;
    const HIT_MASK_MAX_COLS = 72;
    const HIT_MASK_MIN_ROWS = 44;
    const HIT_MASK_MAX_ROWS = 120;

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
        const textNode = document.getElementById('live2d-resource-hint-text');
        if (!resource) {
            currentResourceHintKey = '';
            node.className = 'live2d-resource-hint hidden';
            textNode.textContent = '';
            return;
        }

        const state = resource.state || '';
        const tone = (state === 'path_valid' || state === 'loaded') ? 'ok' : 'warn';
        const lines = [resource.status_label || ''];
        if (resource.help_text) lines.push(resource.help_text);
        currentResourceHintKey = [
            resource.state || '',
            resource.status_label || '',
            resource.help_text || '',
            resource.effective_model_path || '',
        ].join('|');
        textNode.textContent = lines.filter(Boolean).join(' ');
        if (dismissedResourceHintKey && dismissedResourceHintKey === currentResourceHintKey) {
            node.className = 'live2d-resource-hint hidden';
            return;
        }
        node.className = 'live2d-resource-hint ' + tone;
    }

    function dismissResourceHint(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        dismissedResourceHintKey = currentResourceHintKey || '__dismissed__';
        document.getElementById('live2d-resource-hint').classList.add('hidden');
        reportUIRegions();
    }

    function showFallback() {
        document.getElementById('live2d-fallback-preview').classList.remove('hidden');
        setTimeout(reportFallbackHitRegion, 0);
    }

    function hideFallback() {
        document.getElementById('live2d-fallback-preview').classList.add('hidden');
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

    function normalizedRegionFromRect(rect, kind) {
        const viewportWidth = Math.max(window.innerWidth || 1, 1);
        const viewportHeight = Math.max(window.innerHeight || 1, 1);
        const left = Math.max(0, Math.min(viewportWidth, rect.left));
        const top = Math.max(0, Math.min(viewportHeight, rect.top));
        const right = Math.max(left, Math.min(viewportWidth, rect.right));
        const bottom = Math.max(top, Math.min(viewportHeight, rect.bottom));
        return {
            kind: kind || 'ellipse',
            x: left / viewportWidth,
            y: top / viewportHeight,
            width: (right - left) / viewportWidth,
            height: (bottom - top) / viewportHeight,
        };
    }

    function alphaMaskGridSize(rect) {
        const width = Math.max(1, rect.right - rect.left);
        const height = Math.max(1, rect.bottom - rect.top);
        const cols = Math.max(HIT_MASK_MIN_COLS, Math.min(HIT_MASK_MAX_COLS, Math.round(width / 8)));
        const rows = Math.max(
            HIT_MASK_MIN_ROWS,
            Math.min(HIT_MASK_MAX_ROWS, Math.round((height / Math.max(width, 1)) * cols)),
        );
        return {cols, rows};
    }

    function containedImageRect(image) {
        const rect = image.getBoundingClientRect();
        const naturalWidth = Number(image.naturalWidth || rect.width || 1);
        const naturalHeight = Number(image.naturalHeight || rect.height || 1);
        const scale = Math.min(rect.width / naturalWidth, rect.height / naturalHeight);
        const width = naturalWidth * scale;
        const height = naturalHeight * scale;
        return {
            left: rect.left + (rect.width - width) / 2,
            top: rect.top + (rect.height - height) / 2,
            right: rect.left + (rect.width + width) / 2,
            bottom: rect.top + (rect.height + height) / 2,
        };
    }

    function trimMaskRegion(maskBits, cols, rows, rect) {
        let minCol = cols;
        let minRow = rows;
        let maxCol = -1;
        let maxRow = -1;
        for (let row = 0; row < rows; row += 1) {
            for (let col = 0; col < cols; col += 1) {
                if (maskBits[(row * cols) + col] !== '1') continue;
                if (col < minCol) minCol = col;
                if (row < minRow) minRow = row;
                if (col > maxCol) maxCol = col;
                if (row > maxRow) maxRow = row;
            }
        }
        if (maxCol < minCol || maxRow < minRow) return null;

        const cellWidth = (rect.right - rect.left) / cols;
        const cellHeight = (rect.bottom - rect.top) / rows;
        let trimmedMask = '';
        for (let row = minRow; row <= maxRow; row += 1) {
            for (let col = minCol; col <= maxCol; col += 1) {
                trimmedMask += maskBits[(row * cols) + col];
            }
        }
        return {
            kind: 'alpha_mask',
            x: (rect.left + (minCol * cellWidth)) / Math.max(window.innerWidth || 1, 1),
            y: (rect.top + (minRow * cellHeight)) / Math.max(window.innerHeight || 1, 1),
            width: ((maxCol - minCol + 1) * cellWidth) / Math.max(window.innerWidth || 1, 1),
            height: ((maxRow - minRow + 1) * cellHeight) / Math.max(window.innerHeight || 1, 1),
            cols: maxCol - minCol + 1,
            rows: maxRow - minRow + 1,
            mask: trimmedMask,
        };
    }

    function buildAlphaMaskRegion(drawToMask) {
        try {
            const {rect, draw} = drawToMask();
            const width = Math.max(1, rect.right - rect.left);
            const height = Math.max(1, rect.bottom - rect.top);
            if (width <= 1 || height <= 1) return null;
            const {cols, rows} = alphaMaskGridSize(rect);
            const canvas = document.createElement('canvas');
            canvas.width = cols;
            canvas.height = rows;
            const ctx = canvas.getContext('2d', {willReadFrequently: true});
            if (!ctx) return null;
            ctx.clearRect(0, 0, cols, rows);
            draw(ctx, cols, rows);
            const imageData = ctx.getImageData(0, 0, cols, rows).data;
            const bits = new Array(cols * rows).fill('0');
            for (let row = 0; row < rows; row += 1) {
                for (let col = 0; col < cols; col += 1) {
                    const alpha = imageData[((row * cols) + col) * 4 + 3];
                    if (alpha >= 48) bits[(row * cols) + col] = '1';
                }
            }
            return trimMaskRegion(bits, cols, rows, rect);
        } catch (error) {
            return null;
        }
    }

    function clampRectToViewport(rect) {
        const viewportWidth = Math.max(window.innerWidth || 1, 1);
        const viewportHeight = Math.max(window.innerHeight || 1, 1);
        const left = Math.max(0, Math.min(viewportWidth, rect.left));
        const top = Math.max(0, Math.min(viewportHeight, rect.top));
        const right = Math.max(left, Math.min(viewportWidth, rect.right));
        const bottom = Math.max(top, Math.min(viewportHeight, rect.bottom));
        return {left, top, right, bottom};
    }

    function getLive2DModelViewportRect() {
        if (!live2dModel) return null;
        try {
            const bounds = live2dModel.getBounds();
            if (!bounds || !Number.isFinite(bounds.x) || !Number.isFinite(bounds.y)) return null;
            const characterRect = getCharacter().getBoundingClientRect();
            const rect = clampRectToViewport({
                left: characterRect.left + bounds.x,
                top: characterRect.top + bounds.y,
                right: characterRect.left + bounds.x + bounds.width,
                bottom: characterRect.top + bounds.y + bounds.height,
            });
            if (rect.right - rect.left <= 1 || rect.bottom - rect.top <= 1) return null;
            return rect;
        } catch (error) {
            return null;
        }
    }

    function sendHitRegion(region) {
        if (!region || region.width <= 0 || region.height <= 0) return;
        currentHitRegion = region;
        const payload = JSON.stringify(region);
        if (payload === lastHitRegionPayload) return;
        lastHitRegionPayload = payload;
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.update_hit_region) {
                window.pywebview.api.update_hit_region(region);
            }
        } catch (error) {}
    }

    function sendUIRegions(regions) {
        const normalized = Array.isArray(regions) ? regions.filter(function(region) {
            return region && region.width > 0 && region.height > 0;
        }) : [];
        currentUIRegions = normalized;
        const payload = JSON.stringify(normalized);
        if (payload === lastUIRegionsPayload) return;
        lastUIRegionsPayload = payload;
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.update_ui_regions) {
                window.pywebview.api.update_ui_regions(normalized);
            }
        } catch (error) {}
    }

    function hitRegionContainsLocalPoint(region, localX, localY) {
        if (!region) return false;
        const viewportWidth = Math.max(window.innerWidth || 1, 1);
        const viewportHeight = Math.max(window.innerHeight || 1, 1);
        const left = Number(region.x || 0) * viewportWidth;
        const top = Number(region.y || 0) * viewportHeight;
        const width = Number(region.width || 0) * viewportWidth;
        const height = Number(region.height || 0) * viewportHeight;
        if (width <= 0 || height <= 0) return false;
        if (localX < left || localX > left + width || localY < top || localY > top + height) return false;

        if (region.kind === 'alpha_mask') {
            const cols = Math.max(1, Number(region.cols || 0));
            const rows = Math.max(1, Number(region.rows || 0));
            const mask = String(region.mask || '');
            if (mask.length < cols * rows) return false;
            const relX = (localX - left) / width;
            const relY = (localY - top) / height;
            const col = Math.min(cols - 1, Math.max(0, Math.floor(relX * cols)));
            const row = Math.min(rows - 1, Math.max(0, Math.floor(relY * rows)));
            return mask[(row * cols) + col] === '1';
        }

        const centerX = left + (width / 2);
        const centerY = top + (height / 2);
        const radiusX = width / 2;
        const radiusY = height / 2;
        if (region.kind === 'rect') return true;
        if (radiusX <= 0 || radiusY <= 0) return false;
        const u = (localX - centerX) / radiusX;
        const v = (localY - centerY) / radiusY;
        return (u * u) + (v * v) <= 1;
    }

    function elementRegion(element, kind) {
        if (!element) return null;
        const rect = element.getBoundingClientRect();
        if (rect.width <= 1 || rect.height <= 1) return null;
        return normalizedRegionFromRect(rect, kind || 'rect');
    }

    function reportUIRegions() {
        const closeButton = document.getElementById('live2d-resource-hint-close');
        const replyBubble = document.getElementById('reply-bubble');
        const quickInput = document.getElementById('quick-input');
        const regions = [];
        const closeRegion = elementRegion(closeButton, 'rect');
        if (closeRegion) regions.push(closeRegion);
        if (replyBubble && !replyBubble.classList.contains('hidden')) {
            const replyRegion = elementRegion(replyBubble, 'rect');
            if (replyRegion) regions.push(replyRegion);
        }
        if (quickInput && !quickInput.classList.contains('hidden')) {
            const inputRegion = elementRegion(quickInput, 'rect');
            if (inputRegion) regions.push(inputRegion);
        }
        sendUIRegions(regions);
    }

    function reportFallbackHitRegion() {
        const fallback = document.getElementById('live2d-fallback-preview');
        if (!fallback || fallback.classList.contains('hidden')) return;
        const imageRect = containedImageRect(fallback);
        const region = buildAlphaMaskRegion(function() {
            return {
                rect: imageRect,
                draw: function(ctx, cols, rows) {
                    const naturalWidth = Number(fallback.naturalWidth || cols || 1);
                    const naturalHeight = Number(fallback.naturalHeight || rows || 1);
                    ctx.drawImage(fallback, 0, 0, naturalWidth, naturalHeight, 0, 0, cols, rows);
                },
            };
        });
        sendHitRegion(region || normalizedRegionFromRect(imageRect, 'live2d'));
    }

    function reportLive2DModelHitRegion() {
        if (!live2dModel || !live2dApp) {
            reportFallbackHitRegion();
            return;
        }
        const liveCanvas = getCanvas();
        const canvasRect = liveCanvas.getBoundingClientRect();
        const modelRect = getLive2DModelViewportRect() || canvasRect;
        const sourceLeft = Math.max(0, ((modelRect.left - canvasRect.left) / Math.max(canvasRect.width || 1, 1)) * liveCanvas.width);
        const sourceTop = Math.max(0, ((modelRect.top - canvasRect.top) / Math.max(canvasRect.height || 1, 1)) * liveCanvas.height);
        const sourceWidth = Math.max(1, ((modelRect.right - modelRect.left) / Math.max(canvasRect.width || 1, 1)) * liveCanvas.width);
        const sourceHeight = Math.max(1, ((modelRect.bottom - modelRect.top) / Math.max(canvasRect.height || 1, 1)) * liveCanvas.height);
        const region = buildAlphaMaskRegion(function() {
            return {
                rect: modelRect,
                draw: function(ctx, cols, rows) {
                    ctx.drawImage(
                        liveCanvas,
                        sourceLeft,
                        sourceTop,
                        Math.min(sourceWidth, Math.max(1, liveCanvas.width - sourceLeft)),
                        Math.min(sourceHeight, Math.max(1, liveCanvas.height - sourceTop)),
                        0,
                        0,
                        cols,
                        rows,
                    );
                },
            };
        });
        if (region) sendHitRegion(region);
        else reportFallbackHitRegion();
    }

    function stageCenterPoint() {
        const rect = document.getElementById('stage').getBoundingClientRect();
        return {
            x: rect.width / 2,
            y: rect.height * 0.44,
        };
    }

    function focusLive2DAtLocal(localX, localY, immediate) {
        if (!live2dMouseFollowEnabled || !live2dModel || typeof live2dModel.focus !== 'function') return;
        try {
            live2dModel.focus(localX, localY, !!immediate);
        } catch (error) {}
    }

    function updateLive2DFocus(event, immediate) {
        if (!event) {
            const point = stageCenterPoint();
            focusLive2DAtLocal(point.x, point.y, immediate);
            return;
        }
        focusLive2DAtLocal(event.clientX, event.clientY, immediate);
    }

    function resetLive2DFocus() {
        updateLive2DFocus(null, true);
    }

    function handleGlobalPointer(localX, localY, insideWindow) {
        lastPointerLocalX = Number(localX || 0);
        lastPointerLocalY = Number(localY || 0);
        lastPointerInsideWindow = !!insideWindow;
        focusLive2DAtLocal(lastPointerLocalX, lastPointerLocalY, false);
    }

    function handleStagePointerLeave(event) {
        if (event) {
            launcherPointerStart = null;
            launcherClickSuppressed = false;
            setDraggingState(false);
        }
        if (!live2dMouseFollowEnabled) resetLive2DFocus();
    }

    function compactDetail(detail, limit) {
        const max = Number(limit || 220);
        const text = String(detail || '').replace(/\s+/g, ' ').trim();
        if (text.length > max) return text.slice(0, max - 1) + '…';
        return text;
    }

    function formatErrorDetail(error) {
        if (!error) return '';
        if (typeof error === 'string') return error;
        if (error.stack) return String(error.stack);
        if (error.message) return String(error.message);
        try {
            return JSON.stringify(error);
        } catch (jsonError) {
            return String(error);
        }
    }

    async function reportClientEvent(level, event, detail) {
        try {
            if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.report_client_event) return;
            await window.pywebview.api.report_client_event(
                String(level || 'info'),
                String(event || 'client.event'),
                compactDetail(detail || '', 360),
            );
        } catch (error) {}
    }

    function getRendererDiagnostics() {
        const live2dNamespace = window.PIXI && window.PIXI.live2d;
        const live2dModelCtor = getLive2DModelCtor();
        return {
            hasPixi: !!window.PIXI,
            hasPixiApplication: !!(window.PIXI && window.PIXI.Application),
            hasPixiLive2D: !!live2dNamespace,
            hasLive2DModel: !!live2dModelCtor,
            hasCubismCore: !!window.Live2DCubismCore,
        };
    }

    function getLive2DModelCtor() {
        const live2dNamespace = window.PIXI && window.PIXI.live2d;
        if (!live2dNamespace) return null;
        return (
            live2dNamespace.Live2DModel
            || (live2dNamespace.default && live2dNamespace.default.Live2DModel)
            || (window.PIXI && window.PIXI.Live2DModel)
            || window.Live2DModel
            || null
        );
    }

    function formatRendererDiagnostics() {
        const diagnostics = getRendererDiagnostics();
        return Object.entries(diagnostics)
            .map(function(entry) { return entry[0] + '=' + (entry[1] ? '1' : '0'); })
            .join(' ');
    }

    function reportRendererEvent(level, event, detail) {
        const payload = String(event || '') + '|' + compactDetail(detail || '', 360);
        if (payload === lastReportedRendererEvent) return;
        lastReportedRendererEvent = payload;
        reportClientEvent(level, event, detail);
    }

    function rendererAvailable() {
        const diagnostics = getRendererDiagnostics();
        return !!(
            diagnostics.hasPixi
            && diagnostics.hasPixiApplication
            && diagnostics.hasPixiLive2D
            && diagnostics.hasLive2DModel
            && diagnostics.hasCubismCore
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
        window.requestAnimationFrame(reportLive2DModelHitRegion);
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
            reportRendererEvent('info', 'renderer.disabled', renderer.reason || 'renderer disabled');
            return;
        }

        if (!rendererAvailable()) {
            destroyLive2DRenderer();
            hideLoading();
            showFallback();
            const detail = formatRendererDiagnostics();
            showError('Live2D 渲染依赖未加载，已回退到静态预览\n' + detail);
            reportRendererEvent('warning', 'renderer.dependencies_missing', detail);
            return;
        }

        if (live2dModel && live2dModelUrl === renderer.model_url) {
            fitLive2DModel();
            hideFallback();
            hideError();
            hideLoading();
            return;
        }

        hideError();
        setLoading('Live2D 模型加载中…');
        const currentToken = ++rendererLoadToken;
        reportRendererEvent('info', 'renderer.loading_model', 'model_url=' + renderer.model_url);

        try {
            if (!live2dModel || live2dModelUrl !== renderer.model_url) {
                destroyLive2DRenderer();
                const app = ensurePixiApp();
                const Live2DModelCtor = getLive2DModelCtor();
                if (!Live2DModelCtor || typeof Live2DModelCtor.from !== 'function') {
                    throw new Error('Live2DModel.from 不可用');
                }
                const model = await Live2DModelCtor.from(renderer.model_url, {
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
            reportRendererEvent('info', 'renderer.model_loaded', 'model_url=' + renderer.model_url);
        } catch (error) {
            destroyLive2DRenderer();
            showFallback();
            const detail = compactDetail(formatErrorDetail(error), 240) || 'unknown error';
            showError('Live2D 模型加载失败，已回退到静态预览\n' + detail);
            reportRendererEvent(
                'error',
                'renderer.model_load_failed',
                'model_url=' + renderer.model_url + ' error=' + detail,
            );
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
        updateLive2DFocus(event, false);
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

    function latestAssistantText(chat) {
        if (chat.latest_reply) return chat.latest_reply;
        const messages = chat.messages || [];
        for (let i = messages.length - 1; i >= 0; i -= 1) {
            if (messages[i].role === 'assistant' && messages[i].content) return messages[i].content;
        }
        return '';
    }

    function setReplyBubbleVisible(visible, extraClass) {
        const node = document.getElementById('reply-bubble');
        node.classList.toggle('hidden', !visible);
        node.classList.toggle('proactive', extraClass === 'proactive');
        reportUIRegions();
    }

    function updateReplyBubble(live2d, chat, proactive, notification, forceLatest) {
        const node = document.getElementById('reply-bubble');
        const textNode = document.getElementById('reply-bubble-text');
        const proactiveAttention = proactive && proactive.has_attention;
        const hasUnread = notification && notification.has_unread;
        const text = proactiveAttention
            ? (proactive.message || '有新的主动桌面观察结果')
            : chat.is_processing
                ? '正在思考回复…'
                : (hasUnread || forceLatest)
                    ? (latestAssistantText(chat) || '')
                    : '';
        if (text && text !== lastReplyBubbleText) {
            lastReplyBubbleText = text;
            replyBubbleManuallyHidden = false;
        }
        textNode.textContent = text || '';
        const visible = !!live2d.show_reply_bubble && !!text && !replyBubbleManuallyHidden;
        setReplyBubbleVisible(visible, proactiveAttention ? 'proactive' : '');
        return node;
    }

    function setQuickInputVisible(visible) {
        const live2d = currentLive2DView && currentLive2DView.live2d ? currentLive2DView.live2d : {};
        const node = document.getElementById('quick-input');
        const normalized = !!visible && live2d.enable_quick_input !== false;
        node.classList.toggle('hidden', !normalized);
        if (normalized) {
            const input = document.getElementById('quick-input-text');
            setTimeout(function() { try { input.focus({preventScroll: true}); } catch (error) { input.focus(); } }, 0);
        }
        reportUIRegions();
    }

    function applyDefaultOpenBehavior(live2d) {
        if (defaultOpenBehaviorApplied) return;
        defaultOpenBehaviorApplied = true;
        const behavior = live2d.default_open_behavior || 'reply_bubble';
        if (behavior === 'chat_input') {
            replyBubbleManuallyHidden = true;
            setReplyBubbleVisible(false, '');
            setQuickInputVisible(true);
        } else if (behavior === 'stage') {
            replyBubbleManuallyHidden = true;
            setReplyBubbleVisible(false, '');
            setQuickInputVisible(false);
        } else {
            replyBubbleManuallyHidden = false;
            setQuickInputVisible(false);
        }
    }

    function toggleReplyBubble() {
        const node = document.getElementById('reply-bubble');
        const currentlyVisible = !node.classList.contains('hidden');
        replyBubbleManuallyHidden = currentlyVisible;
        if (!currentlyVisible) {
            replyBubbleManuallyHidden = false;
            updateReplyBubble(
                (currentLive2DView && currentLive2DView.live2d) || {},
                (currentLive2DView && currentLive2DView.chat) || {},
                (currentLive2DView && currentLive2DView.proactive) || {},
                (currentLive2DView && currentLive2DView.notification) || {},
                true,
            );
        } else {
            setReplyBubbleVisible(false, '');
        }
        acknowledgeProactive();
        acknowledgeNotification();
    }

    function handleQuickInputKey(event) {
        if (event.key === 'Enter') sendQuickInput(event);
        if (event.key === 'Escape') setQuickInputVisible(false);
    }

    async function sendQuickInput(event) {
        if (event) {
            event.preventDefault();
            event.stopPropagation();
        }
        const input = document.getElementById('quick-input-text');
        const text = input.value.trim();
        if (!text || !window.pywebview || !window.pywebview.api) return;
        const result = await window.pywebview.api.send_quick_message(text);
        if (result && result.ok) input.value = '';
        await refreshLive2D();
    }

    async function acknowledgeProactive() {
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.acknowledge_proactive) {
                await window.pywebview.api.acknowledge_proactive();
            }
        } catch (error) {}
    }

    async function acknowledgeNotification() {
        try {
            if (window.pywebview && window.pywebview.api && window.pywebview.api.acknowledge_notification) {
                await window.pywebview.api.acknowledge_notification();
            }
        } catch (error) {}
    }

    function renderLive2D(view) {
        currentLive2DView = view;
        const live2d = view.live2d || {};
        const chat = view.chat || {};
        const proactive = view.proactive || {};
        const notification = view.notification || {};
        const resource = live2d.resource || {};
        const character = document.getElementById('character');
        const scale = Math.max(0.4, Math.min(2.0, Number(live2d.scale || 1)));
        live2dScale = scale;
        live2dMouseFollowEnabled = !!(
            live2d.mouse_follow_enabled
            ?? (live2d.renderer && live2d.renderer.mouse_follow_enabled)
            ?? true
        );
        character.style.setProperty('--live2d-preview-scale', String(scale));
        const hasAttention = !!notification.has_unread;
        const unreadStatus = notification.latest_message ? notification.latest_message.status : '';
        const characterClasses = ['character'];
        if (chat.is_processing) characterClasses.push('processing');
        else if (hasAttention && unreadStatus === 'failed') characterClasses.push('failed');
        else if (hasAttention) characterClasses.push('has-message');
        character.className = characterClasses.join(' ');

        const messageHint = proactive.has_attention
            ? '，有新的桌面观察结果'
            : chat.is_processing
            ? '，正在回复'
            : hasAttention
                ? '，有新消息'
                : '';
        document.getElementById('stage').title =
            ((resource.status_label || 'Yachiyo Live2D') + messageHint + '，点击行为：' + (live2d.click_action || 'open_chat'));

        renderResourceHint(resource);
        updateReplyBubble(live2d, chat, proactive, notification, false);
        applyDefaultOpenBehavior(live2d);
        reportUIRegions();

        ensureLive2DRenderer(view);
        if (!live2dMouseFollowEnabled) resetLive2DFocus();

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

    async function refreshGlobalPointer() {
        try {
            if (!window.pywebview || !window.pywebview.api || !window.pywebview.api.get_pointer_state) return;
            const state = await window.pywebview.api.get_pointer_state();
            if (!state || !state.ok) return;
            handleGlobalPointer(state.x, state.y, state.inside);
        } catch (error) {}
    }

    function startGlobalPointerPolling() {
        if (globalPointerPolling) return;
        globalPointerPolling = setInterval(refreshGlobalPointer, GLOBAL_POINTER_SYNC_INTERVAL_MS);
        refreshGlobalPointer();
    }

    function stopGlobalPointerPolling() {
        if (!globalPointerPolling) return;
        clearInterval(globalPointerPolling);
        globalPointerPolling = null;
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

    async function handleStageClick(event) {
        const live2d = currentLive2DView && currentLive2DView.live2d ? currentLive2DView.live2d : {};
        const action = live2d.click_action || 'open_chat';
        if (action === 'toggle_reply') {
            if (shouldIgnoreLauncherClick(event)) return;
            if (isMenuVisible()) {
                hideMenu();
                if (event) event.stopPropagation();
                return;
            }
            toggleReplyBubble();
            return;
        }
        if (action === 'focus_stage') {
            if (shouldIgnoreLauncherClick(event)) return;
            hideMenu();
            await focusLauncherWindow();
            return;
        }
        await toggleChat(event);
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
        reportRendererEvent('info', 'bootstrap', formatRendererDiagnostics());
        refreshLive2D();
        startGlobalPointerPolling();
        startIdlePolling();
    }

    window.addEventListener('error', function(event) {
        const location = [event.filename || '', event.lineno || 0, event.colno || 0]
            .filter(Boolean)
            .join(':');
        const detail = compactDetail([
            event.message || 'window error',
            location,
            formatErrorDetail(event.error),
        ].filter(Boolean).join(' | '), 360);
        reportClientEvent('error', 'window.error', detail);
    });
    window.addEventListener('unhandledrejection', function(event) {
        const detail = compactDetail(formatErrorDetail(event.reason), 360) || 'promise rejected';
        reportClientEvent('error', 'window.unhandledrejection', detail);
    });

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
    window.addEventListener('beforeunload', stopGlobalPointerPolling);
    window.addEventListener('resize', function() {
        fitLive2DModel();
        reportFallbackHitRegion();
        reportUIRegions();
    });
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
    try:
        from apps.bridge.server import get_live2d_asset_token

        token = get_live2d_asset_token()
    except Exception:
        token = ""
    suffix = f"?{urlencode({'token': token})}" if token else ""
    return f"http://{host}:{port}/live2d/assets/{quote(rel_path, safe='/')}{suffix}"


def _resolve_live2d_preview_uri(config: "AppConfig") -> str:
    return data_uri(_resolve_live2d_preview_path(config))


def _render_live2d_html(config: "AppConfig") -> str:
    runtime_tags = _build_live2d_runtime_script_tags()
    return (
        _LIVE2D_HTML
        .replace("{{PREVIEW_URL}}", _resolve_live2d_preview_uri(config))
        .replace("{{RUNTIME_ENV_SHIM}}", _LIVE2D_RUNTIME_ENV_SHIM)
        .replace("{{PIXI_JS_TAG}}", runtime_tags["pixi_js"])
        .replace("{{LIVE2D_CUBISM_CORE_TAG}}", runtime_tags["live2d_cubism_core"])
        .replace("{{PIXI_LIVE2D_DISPLAY_TAG}}", runtime_tags["pixi_live2d_display"])
    )


def _clamp_float(value: Any, lower: float, upper: float) -> float:
    number = float(value)
    return max(lower, min(upper, number))


class Live2DWindowAPI:
    """Live2D 模式 WebView API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)
        self._notification = LauncherNotificationTracker()
        self._proactive = ProactiveDesktopService(runtime, config.live2d_mode)
        self._tts = TTSService(config.tts)
        self._last_tts_reply = ""
        self._live2d_window: Any = None
        self._last_client_event: dict[str, str] = {}
        self._context_menu_open = False
        self._pointer_dragging = False
        self._hit_region: dict[str, object] | None = None
        self._ui_regions: list[dict[str, object]] = []
        self._last_pointer_state: dict[str, object] = {"x": 0.0, "y": 0.0, "inside": False, "updated_at": 0.0}

    def get_live2d_view(self) -> Dict[str, Any]:
        live2d = self._config.live2d_mode
        resource = live2d.resource_info()
        chat = self._chat_bridge.get_conversation_overview(summary_count=3, session_limit=3)
        proactive = self._proactive.get_state()
        notification = self._notification.update(
            chat,
            external_attention=bool(proactive.get("has_attention")),
        )
        tts_status = self._maybe_trigger_tts(chat)
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
        deps_primed, deps_ready, deps_error = _get_live2d_runtime_dependency_state()
        renderer_enabled = (
            bool(model_url)
            and bridge_state == "running"
            and self._config.bridge_enabled
            and resource.state.value in {"path_valid", "loaded"}
            and (not deps_primed or deps_ready)
        )
        if resource.state.value not in {"path_valid", "loaded"}:
            renderer_reason = resource.help_text or resource.status_label
        elif deps_primed and not deps_ready:
            renderer_reason = f"Live2D 渲染依赖准备失败：{deps_error or '请稍后重试'}"
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
                "mouse_follow_enabled": live2d.mouse_follow_enabled,
                "proactive_enabled": live2d.proactive_enabled,
                "proactive_desktop_watch_enabled": live2d.proactive_desktop_watch_enabled,
                "proactive_interval_seconds": live2d.proactive_interval_seconds,
                "preview_url": data_uri(preview_path),
                "click_action": live2d.click_action,
                "default_open_behavior": live2d.default_open_behavior,
                "tts": tts_status,
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
                    "mouse_follow_enabled": live2d.mouse_follow_enabled,
                    "idle_motion_group": live2d.idle_motion_group,
                    "enable_expressions": live2d.enable_expressions,
                    "enable_physics": live2d.enable_physics,
                },
            },
            "proactive": proactive,
            "notification": notification,
            "tts": tts_status,
            "bridge_label": bridge_label_map.get(bridge_state, "Bridge 启动中"),
            "executor_label": executor_label,
        }

    def _maybe_trigger_tts(self, chat: Dict[str, Any]) -> Dict[str, Any]:
        if not self._config.tts.enabled or self._config.tts.provider == "none":
            return self._tts.get_status()
        latest_reply = str(chat.get("latest_reply_full") or chat.get("latest_reply") or "").strip()
        if not latest_reply:
            return self._tts.get_status()
        if latest_reply == self._last_tts_reply:
            return self._tts.get_status()
        status = self._tts.speak_async(latest_reply)
        if status.get("scheduled"):
            self._last_tts_reply = latest_reply
        return status

    def send_quick_message(self, text: str) -> Dict[str, Any]:
        return self._chat_bridge.send_quick_message(text)

    def toggle_chat(self) -> Dict[str, Any]:
        from apps.shell.chat_window import is_chat_window_open, toggle_chat_window

        self._proactive.acknowledge()
        self._notification.acknowledge()
        was_open = is_chat_window_open()
        open_after_toggle = toggle_chat_window(self._runtime)
        return {"ok": was_open or open_after_toggle, "open": open_after_toggle}

    def open_chat(self) -> Dict[str, Any]:
        from apps.shell.chat_window import open_chat_window

        self._proactive.acknowledge()
        self._notification.acknowledge()
        return {"ok": open_chat_window(self._runtime)}

    def acknowledge_proactive(self) -> Dict[str, Any]:
        self._proactive.acknowledge()
        return {"ok": True}

    def acknowledge_notification(self) -> Dict[str, Any]:
        self._notification.acknowledge()
        return {"ok": True}

    def open_main_window(self) -> Dict[str, Any]:
        from apps.shell.window import open_main_window

        return {"ok": open_main_window(self._runtime, self._config)}

    def open_settings(self) -> Dict[str, Any]:
        from apps.shell.settings import open_mode_settings_window

        return {"ok": open_mode_settings_window(self._config, "live2d")}

    def set_context_menu_open(self, is_open: bool) -> Dict[str, Any]:
        self._context_menu_open = bool(is_open)
        return {"ok": True}

    def set_dragging(self, is_dragging: bool) -> Dict[str, Any]:
        self._pointer_dragging = bool(is_dragging)
        return {"ok": True}

    def update_hit_region(self, region: dict[str, Any]) -> Dict[str, Any]:
        try:
            kind = str(region.get("kind") or "ellipse")
            if kind not in {"alpha_mask", "ellipse", "live2d", "model", "rect"}:
                kind = "alpha_mask"
            width = _clamp_float(region.get("width"), 0.0, 1.0)
            height = _clamp_float(region.get("height"), 0.0, 1.0)
            if width <= 0 or height <= 0:
                return {"ok": False, "error": "empty hit region"}
            sanitized: dict[str, object] = {
                "kind": kind,
                "x": _clamp_float(region.get("x"), 0.0, 1.0),
                "y": _clamp_float(region.get("y"), 0.0, 1.0),
                "width": width,
                "height": height,
            }
            if kind == "alpha_mask":
                cols = max(1, min(128, int(region.get("cols", 0))))
                rows = max(1, min(160, int(region.get("rows", 0))))
                mask = str(region.get("mask") or "")
                if len(mask) < cols * rows:
                    return {"ok": False, "error": "invalid alpha mask"}
                sanitized["cols"] = cols
                sanitized["rows"] = rows
                sanitized["mask"] = mask[: cols * rows]
            self._hit_region = sanitized
            return {"ok": True}
        except Exception as exc:
            logger.debug("更新 Live2D 命中区域失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def update_ui_regions(self, regions: list[dict[str, Any]]) -> Dict[str, Any]:
        try:
            sanitized_regions: list[dict[str, object]] = []
            for region in regions or []:
                kind = str(region.get("kind") or "rect")
                if kind not in {"alpha_mask", "ellipse", "live2d", "model", "rect"}:
                    kind = "rect"
                width = _clamp_float(region.get("width"), 0.0, 1.0)
                height = _clamp_float(region.get("height"), 0.0, 1.0)
                if width <= 0 or height <= 0:
                    continue
                sanitized_regions.append(
                    {
                        "kind": kind,
                        "x": _clamp_float(region.get("x"), 0.0, 1.0),
                        "y": _clamp_float(region.get("y"), 0.0, 1.0),
                        "width": width,
                        "height": height,
                    }
                )
            self._ui_regions = sanitized_regions
            return {"ok": True}
        except Exception as exc:
            logger.debug("更新 Live2D UI 命中区域失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def is_pointer_interactive(self, width: float, height: float, x: float, y: float) -> bool:
        if self._context_menu_open or self._pointer_dragging:
            return True
        try:
            from apps.shell.native_window import _region_hit_test, live2d_visual_hit_test

            for region in self._ui_regions:
                if _region_hit_test(width, height, x, y, region):
                    return True

            return live2d_visual_hit_test(width, height, x, y, self._hit_region)
        except Exception:
            return True

    def report_client_event(self, level: str = "info", event: str = "client.event", detail: str = "") -> Dict[str, Any]:
        normalized_level = str(level or "info").lower()
        normalized_event = _compact_client_detail(event, limit=80) or "client.event"
        normalized_detail = _compact_client_detail(detail, limit=360)
        self._last_client_event = {
            "level": normalized_level,
            "event": normalized_event,
            "detail": normalized_detail,
        }

        message = f"Live2D 前端事件: {normalized_event}"
        if normalized_detail:
            message = f"{message} | {normalized_detail}"

        if normalized_level in {"error", "critical"}:
            logger.error(message)
        elif normalized_level == "warning":
            logger.warning(message)
        else:
            logger.debug(message)
        return {"ok": True}

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

    def observe_pointer(self, width: float, height: float, x: float, y: float, inside: bool) -> None:
        self._last_pointer_state = {
            "x": round(float(x), 2),
            "y": round(float(y), 2),
            "inside": bool(inside),
            "updated_at": round(time.monotonic(), 4),
        }

    def get_pointer_state(self) -> Dict[str, Any]:
        state = dict(self._last_pointer_state)
        state["ok"] = True
        return state

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
        _prime_live2d_runtime_dependencies()
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
            from apps.shell.native_window import schedule_macos_pointer_passthrough

            schedule_macos_pointer_passthrough(
                title="Hermes-Yachiyo Live2D",
                hit_test=api.is_pointer_interactive,
                pointer_observer=api.observe_pointer,
                delay_seconds=0.12,
                interval_seconds=0.016,
                focus_on_hover=False,
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
