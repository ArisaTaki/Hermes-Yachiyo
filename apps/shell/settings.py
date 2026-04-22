"""设置窗口。

展示当前模式的专属设置。全局 Common 设置由 Control Center 承担。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apps.shell.assets import (
    LIVE2D_RELEASES_URL,
    find_default_live2d_model_dir,
    get_user_live2d_assets_dir,
    project_display_path,
)
from apps.shell.config import check_live2d_model_dir, scan_live2d_model_dir
from apps.shell.mode_catalog import get_mode_descriptor
from apps.shell.mode_settings import apply_settings_changes, serialize_mode_window_data

if TYPE_CHECKING:
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


def _find_importable_live2d_dir(root: Path) -> Path | None:
    """Return a valid Live2D model directory from a selected folder or extracted archive."""
    resolved_root = root.expanduser().resolve()
    if not resolved_root.exists() or not resolved_root.is_dir():
        return None
    if check_live2d_model_dir(resolved_root):
        summary = scan_live2d_model_dir(resolved_root)
        if summary.found_in_subdir and summary.subdir_name:
            return (resolved_root / summary.subdir_name).resolve()
        return resolved_root
    discovered = find_default_live2d_model_dir(check_live2d_model_dir, resolved_root)
    if discovered is None:
        return None
    summary = scan_live2d_model_dir(discovered)
    if summary.found_in_subdir and summary.subdir_name:
        return (discovered / summary.subdir_name).resolve()
    return discovered.resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _pick_import_target_dir(root: Path, preferred_name: str) -> Path:
    base_name = Path(preferred_name).name.strip() or "live2d-model"
    candidate = root / base_name
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        candidate = root / f"{base_name}-{suffix}"
        if not candidate.exists():
            return candidate
        suffix += 1


def _copy_live2d_model_dir(source_dir: Path, assets_root: Path | None = None) -> Path:
    """Copy a selected Live2D model directory into the default user asset root."""
    source_model_dir = _find_importable_live2d_dir(source_dir)
    if source_model_dir is None:
        raise ValueError("所选目录内未检测到有效的 Live2D 模型资源")

    target_root = (assets_root or get_user_live2d_assets_dir()).expanduser().resolve()
    target_root.mkdir(parents=True, exist_ok=True)

    if _is_relative_to(source_model_dir, target_root):
        return source_model_dir

    target_dir = _pick_import_target_dir(target_root, source_model_dir.name)
    shutil.copytree(source_model_dir, target_dir)
    return target_dir.resolve()


def _import_live2d_archive(archive_path: Path, assets_root: Path | None = None) -> Path:
    """Extract a downloaded archive and return the imported model directory path."""
    resolved_archive = archive_path.expanduser().resolve()
    if not resolved_archive.exists() or not resolved_archive.is_file():
        raise FileNotFoundError("未找到要导入的资源包文件")

    with tempfile.TemporaryDirectory(prefix="hermes-live2d-import-") as tmp_dir:
        try:
            shutil.unpack_archive(str(resolved_archive), tmp_dir)
        except (shutil.ReadError, ValueError) as exc:
            raise ValueError("所选文件不是可导入的压缩包") from exc

        source_dir = _find_importable_live2d_dir(Path(tmp_dir))
        if source_dir is None:
            raise ValueError("压缩包内未检测到有效的 Live2D 模型资源")

        return _copy_live2d_model_dir(source_dir, assets_root=assets_root)


def _open_path_in_file_manager(path: Path) -> None:
    resolved = path.expanduser().resolve()
    if sys.platform == "darwin":
        subprocess.run(["open", str(resolved)], check=False)
        return
    if sys.platform.startswith("win"):
        import os

        os.startfile(str(resolved))  # type: ignore[attr-defined]
        return
    subprocess.run(["xdg-open", str(resolved)], check=False)


class ModeSettingsAPI:
    """单模式设置窗口 API。"""

    def __init__(self, config: "AppConfig", mode_id: str) -> None:
        self._config = config
        self._mode_id = mode_id
        self._window: Any | None = None

    def bind_window(self, window: Any) -> None:
        self._window = window

    def get_mode_settings(self) -> dict[str, Any]:
        return serialize_mode_window_data(self._config, self._mode_id)

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        previous_display_mode = self._config.display_mode
        result = apply_settings_changes(self._config, changes)
        if result.get("ok"):
            result["settings"] = serialize_mode_window_data(self._config, self._mode_id)
            applied = result.get("applied", {})
            if (
                "display_mode" in applied
                and applied["display_mode"] != previous_display_mode
            ):
                try:
                    from apps.shell.window import request_app_restart

                    request_app_restart()
                    result["restart_scheduled"] = True
                    result["restart_reason"] = "display_mode_changed"
                except Exception as exc:
                    logger.error("显示模式变更后自动重启失败: %s", exc)
                    result["restart_scheduled"] = False
                    result["restart_error"] = str(exc)
        return result

    def _ensure_live2d_mode(self) -> None:
        if self._mode_id != "live2d":
            raise RuntimeError("当前窗口不是 Live2D 设置页")

    def _pick_dialog_path(
        self,
        dialog_type: int,
        *,
        directory: str,
        file_types: tuple[str, ...] = (),
    ) -> Path | None:
        if self._window is None:
            raise RuntimeError("设置窗口未绑定，无法打开文件对话框")
        selected = self._window.create_file_dialog(
            dialog_type,
            directory=directory,
            allow_multiple=False,
            file_types=file_types,
        )
        if not selected:
            return None
        return Path(selected[0]).expanduser()

    def _apply_live2d_model_path(self, model_path: Path, message: str) -> dict[str, Any]:
        result = apply_settings_changes(
            self._config,
            {"live2d_mode.model_path": str(model_path.expanduser().resolve())},
        )
        if not result.get("ok"):
            return result
        result["settings"] = serialize_mode_window_data(self._config, self._mode_id)
        result["message"] = message
        result["model_path_display"] = project_display_path(model_path)
        return result

    def choose_live2d_model_path(self) -> dict[str, Any]:
        self._ensure_live2d_mode()
        try:
            try:
                import webview  # type: ignore[import]

                folder_dialog = webview.FileDialog.FOLDER
            except Exception:
                folder_dialog = 20

            selected = self._pick_dialog_path(
                folder_dialog,
                directory=str(Path.home()),
            )
            if selected is None:
                return {"ok": False, "cancelled": True, "error": "已取消选择"}

            model_dir = _find_importable_live2d_dir(selected)
            if model_dir is None:
                return {"ok": False, "error": "所选目录内未检测到有效的 Live2D 模型资源"}

            return self._apply_live2d_model_path(model_dir, "已更新 Live2D 模型路径")
        except Exception as exc:
            logger.error("选择 Live2D 模型目录失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def import_live2d_archive(self) -> dict[str, Any]:
        self._ensure_live2d_mode()
        try:
            try:
                import webview  # type: ignore[import]

                open_dialog = webview.FileDialog.OPEN
            except Exception:
                open_dialog = 10

            selected = self._pick_dialog_path(
                open_dialog,
                directory=str(Path.home()),
                file_types=("Live2D 资源包 (*.zip)", "压缩包 (*.zip)"),
            )
            if selected is None:
                return {"ok": False, "cancelled": True, "error": "已取消选择"}

            imported_path = _import_live2d_archive(selected)
            return self._apply_live2d_model_path(imported_path, "已导入 Live2D 资源包")
        except Exception as exc:
            logger.error("导入 Live2D 资源包失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def open_live2d_assets_dir(self) -> dict[str, Any]:
        self._ensure_live2d_mode()
        try:
            assets_root = get_user_live2d_assets_dir().expanduser().resolve()
            assets_root.mkdir(parents=True, exist_ok=True)
            _open_path_in_file_manager(assets_root)
            return {
                "ok": True,
                "message": f"已打开默认导入目录：{project_display_path(assets_root)}",
                "settings": serialize_mode_window_data(self._config, self._mode_id),
            }
        except Exception as exc:
            logger.error("打开默认导入目录失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def open_live2d_releases(self) -> dict[str, Any]:
        self._ensure_live2d_mode()
        try:
            webbrowser.open(LIVE2D_RELEASES_URL)
            return {
                "ok": True,
                "message": "已打开 GitHub Releases 页面",
                "settings": serialize_mode_window_data(self._config, self._mode_id),
            }
        except Exception as exc:
            logger.error("打开 Releases 页面失败: %s", exc)
            return {"ok": False, "error": str(exc)}


_SETTINGS_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>Hermes-Yachiyo — 模式设置</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
    background: #161628; color: #e6e6f2;
    padding: 18px; line-height: 1.5;
}
h2 { color: #86a9ff; font-size: 1.15em; margin-bottom: 6px; }
.desc { color: #8f93b5; font-size: 0.86em; margin-bottom: 14px; }
.section {
    background: #21213a;
    border: 1px solid #333758;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 14px;
}
.section h3 { color: #86a9ff; font-size: 0.95em; margin-bottom: 10px; }
.summary {
    background: #18182c;
    border-radius: 8px;
    padding: 10px 12px;
    color: #afb4d8;
    font-size: 0.84em;
    margin-bottom: 10px;
}
.row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 6px 0;
    border-bottom: 1px solid #2e3250;
}
.row:last-child { border-bottom: none; }
.label { color: #9ca3c8; font-size: 0.9em; }
.value { color: #e6e6f2; font-size: 0.86em; }
.value.ok { color: #8fe3a3; }
.value.warn { color: #ffd36a; }
.input, .select {
    min-width: 130px;
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid #44496c;
    background: #141427;
    color: #eef1ff;
    font-size: 0.84em;
}
.toggle {
    width: 40px;
    height: 20px;
    position: relative;
    display: inline-block;
}
.toggle input { opacity: 0; width: 0; height: 0; }
.slider {
    position: absolute;
    inset: 0;
    background: #54597b;
    border-radius: 999px;
    transition: .2s;
}
.slider:before {
    content: "";
    position: absolute;
    width: 14px;
    height: 14px;
    left: 3px;
    bottom: 3px;
    background: #fff;
    border-radius: 50%;
    transition: .2s;
}
input:checked + .slider { background: #5e89ff; }
input:checked + .slider:before { transform: translateX(20px); }
.hint {
    min-height: 1.2em;
    font-size: 0.82em;
    color: #8fe3a3;
}
.hint.error { color: #ff9f9f; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    background: #161a2d;
    border: 1px solid #394067;
    color: #a9b1e6;
    font-size: 0.78em;
}
.action-group {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 8px;
}
.action-btn {
    border: 1px solid #4b5685;
    background: #1a2242;
    color: #eef1ff;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 0.8em;
    cursor: pointer;
}
.action-btn:hover,
.action-btn:focus {
    background: #26315c;
    outline: none;
}
.action-btn.secondary {
    background: #141427;
}
.action-btn.secondary:hover,
.action-btn.secondary:focus {
    background: #1e2140;
}
.note {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    background: #18182c;
    color: #c5cbef;
    font-size: 0.82em;
    line-height: 1.5;
}
.note.warn {
    background: #352612;
    color: #ffe5b2;
}
.note.ok {
    background: #153422;
    color: #d9ffe8;
}
</style>
</head>
<body>
    <h2 id="mode-title">设置</h2>
    <div class="desc" id="mode-desc">读取中…</div>
    <div class="section">
        <h3>模式概览</h3>
        <div class="summary" id="mode-summary">读取中…</div>
        <div class="row">
            <span class="label">模式</span>
            <span class="value" id="mode-name">—</span>
        </div>
        <div class="row" id="live2d-state-row" style="display:none;">
            <span class="label">模型状态</span>
            <span class="value" id="live2d-state">—</span>
        </div>
        <div class="row" id="live2d-entry-row" style="display:none;">
            <span class="label">模型入口</span>
            <span class="value" id="live2d-entry" style="font-size:0.78em;word-break:break-all;">—</span>
        </div>
        <div class="row" id="live2d-source-row" style="display:none;">
            <span class="label">资源来源</span>
            <span class="value" id="live2d-source">—</span>
        </div>
        <div class="row" id="live2d-effective-row" style="display:none;">
            <span class="label">当前生效路径</span>
            <span class="value" id="live2d-effective" style="font-size:0.78em;word-break:break-all;">—</span>
        </div>
        <div class="row" id="live2d-root-row" style="display:none;">
            <span class="label">默认导入目录</span>
            <span class="value" id="live2d-root" style="font-size:0.78em;word-break:break-all;">—</span>
        </div>
        <div class="row" id="live2d-release-row" style="display:none;">
            <span class="label">资源下载</span>
            <span class="value" id="live2d-release" style="font-size:0.78em;word-break:break-all;">—</span>
        </div>
        <div class="note" id="live2d-note" style="display:none;">—</div>
    </div>

    <div class="section">
        <h3 id="part-title">设置项</h3>
        <div id="mode-form"></div>
        <div class="hint" id="save-hint"></div>
    </div>

<script>
let currentMode = '';
let currentSettings = null;

function num(v, fallback) {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : fallback;
}

function boolRow(key, label, checked) {
    return '<div class="row"><span class="label">' + label + '</span>'
        + '<label class="toggle"><input type="checkbox" '
        + (checked ? 'checked ' : '')
        + 'onchange="saveField(\\'' + key + '\\', this.checked)"><span class="slider"></span></label></div>';
}

function inputRow(key, label, value, type='text', step='') {
    const stepAttr = step ? ' step="' + step + '"' : '';
    return '<div class="row"><span class="label">' + label + '</span>'
        + '<input class="input" type="' + type + '" value="' + escapeHtml(String(value ?? '')) + '"' + stepAttr
        + ' onchange="saveInput(\\'' + key + '\\', this)"></div>';
}

function valueRow(label, value) {
    return '<div class="row"><span class="label">' + label + '</span>'
        + '<span class="value" style="font-size:0.78em;word-break:break-all;">'
        + escapeHtml(String(value || '—')) + '</span></div>';
}

function actionButton(label, handler, kind='') {
    const kindClass = kind ? ' ' + kind : '';
    return '<button class="action-btn' + kindClass + '" type="button" onclick="' + handler + '()">'
        + escapeHtml(label) + '</button>';
}

function actionRow(label, buttons) {
    return '<div class="row"><span class="label">' + label + '</span>'
        + '<div class="action-group">' + buttons + '</div></div>';
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderLive2DInfo(cfg) {
    const stateRow = document.getElementById('live2d-state-row');
    const entryRow = document.getElementById('live2d-entry-row');
    const sourceRow = document.getElementById('live2d-source-row');
    const effectiveRow = document.getElementById('live2d-effective-row');
    const rootRow = document.getElementById('live2d-root-row');
    const releaseRow = document.getElementById('live2d-release-row');
    const noteEl = document.getElementById('live2d-note');
    if (currentMode !== 'live2d') {
        stateRow.style.display = 'none';
        entryRow.style.display = 'none';
        sourceRow.style.display = 'none';
        effectiveRow.style.display = 'none';
        rootRow.style.display = 'none';
        releaseRow.style.display = 'none';
        noteEl.style.display = 'none';
        return;
    }
    stateRow.style.display = 'flex';
    entryRow.style.display = 'flex';
    sourceRow.style.display = 'flex';
    effectiveRow.style.display = 'flex';
    rootRow.style.display = 'flex';
    releaseRow.style.display = 'flex';
    const labels = {
        not_configured: ['⚪ 未检测到资源', 'warn'],
        path_invalid: ['❌ 路径不存在', 'warn'],
        path_not_live2d: ['⚠️ 目录无有效模型文件', 'warn'],
        path_valid: ['✅ 资源已就绪', 'ok'],
        loaded: ['✅ 已加载', 'ok'],
    };
    const info = labels[cfg.model_state] || [cfg.model_state || '—', ''];
    const stateEl = document.getElementById('live2d-state');
    stateEl.textContent = info[0];
    stateEl.className = 'value' + (info[1] ? ' ' + info[1] : '');
    const entry = (cfg.summary && (cfg.summary.renderer_entry_display || cfg.summary.renderer_entry)) || '—';
    document.getElementById('live2d-entry').textContent = entry;
    document.getElementById('live2d-source').textContent = (cfg.resource && cfg.resource.source_label) || cfg.source_label || '—';
    document.getElementById('live2d-effective').textContent = (cfg.resource && cfg.resource.effective_model_path_display) || cfg.effective_model_path_display || '—';
    document.getElementById('live2d-root').textContent = (cfg.resource && cfg.resource.default_assets_root_display) || cfg.default_assets_root_display || '—';
    document.getElementById('live2d-release').textContent = (cfg.resource && cfg.resource.releases_url) || cfg.releases_url || '—';
    noteEl.textContent = (cfg.resource && cfg.resource.help_text) || cfg.help_text || '—';
    noteEl.className = 'note ' + (info[1] || '');
    noteEl.style.display = 'block';
}

function renderForm(mode, cfg) {
    const form = document.getElementById('mode-form');
    let html = '';

    if (mode === 'bubble') {
        html += inputRow('bubble_mode.width', '气泡宽度', cfg.width, 'number');
        html += inputRow('bubble_mode.height', '气泡高度', cfg.height, 'number');
        html += inputRow('bubble_mode.position_x', '位置 X', cfg.position_x, 'number');
        html += inputRow('bubble_mode.position_y', '位置 Y', cfg.position_y, 'number');
        html += boolRow('bubble_mode.always_on_top', '窗口置顶', cfg.always_on_top);
        html += boolRow('bubble_mode.edge_snap', '靠边吸附', cfg.edge_snap);
        html += inputRow('bubble_mode.summary_count', '状态摘要条数', cfg.summary_count, 'number');
        html += boolRow('bubble_mode.show_unread_dot', '显示未读点', cfg.show_unread_dot);
        html += inputRow('bubble_mode.opacity', '透明度', cfg.opacity, 'number', '0.01');
        html += valueRow('当前头像资源', cfg.avatar_path_display || cfg.avatar_path);
        html += inputRow('bubble_mode.avatar_path', '头像路径', cfg.avatar_path);
        html += boolRow('bubble_mode.proactive_enabled', '主动对话', cfg.proactive_enabled);
        html += boolRow('bubble_mode.proactive_desktop_watch_enabled', '定期桌面观察', cfg.proactive_desktop_watch_enabled);
        html += inputRow('bubble_mode.proactive_interval_seconds', '观察间隔秒', cfg.proactive_interval_seconds, 'number');
    } else if (mode === 'live2d') {
        html += actionRow('资源操作',
            actionButton('选择模型目录', 'chooseLive2DModelPath')
            + actionButton('导入资源包 ZIP', 'importLive2DArchive')
            + actionButton('打开导入目录', 'openLive2DAssetsDir', 'secondary')
            + actionButton('打开 Releases', 'openLive2DReleases', 'secondary')
        );
        html += inputRow('live2d_mode.model_name', '模型名称', cfg.model_name);
        html += valueRow('当前配置路径', cfg.model_path_display || cfg.model_path || '未填写');
        html += valueRow('当前生效路径', cfg.effective_model_path_display || '未检测到资源');
        html += inputRow('live2d_mode.model_path', '模型路径', cfg.model_path);
        html += inputRow('live2d_mode.width', '窗口宽度', cfg.width, 'number');
        html += inputRow('live2d_mode.height', '窗口高度', cfg.height, 'number');
        html += inputRow('live2d_mode.position_x', '位置 X', cfg.position_x, 'number');
        html += inputRow('live2d_mode.position_y', '位置 Y', cfg.position_y, 'number');
        html += inputRow('live2d_mode.scale', '角色缩放', cfg.scale, 'number', '0.01');
        html += boolRow('live2d_mode.window_on_top', '窗口置顶', cfg.window_on_top);
        html += boolRow('live2d_mode.show_on_all_spaces', 'macOS 所有桌面可见', cfg.show_on_all_spaces);
        html += boolRow('live2d_mode.auto_open_chat_window', '自动打开聊天窗口', cfg.auto_open_chat_window);
        html += inputRow('live2d_mode.idle_motion_group', '待机动作组', cfg.idle_motion_group);
        html += boolRow('live2d_mode.enable_expressions', '启用表情系统', cfg.enable_expressions);
        html += boolRow('live2d_mode.enable_physics', '启用物理模拟', cfg.enable_physics);
    }

    form.innerHTML = html;
    renderLive2DInfo(cfg);
}

async function runModeAction(methodName, successText) {
    const hint = document.getElementById('save-hint');
    try {
        if (!window.pywebview || !window.pywebview.api) throw new Error('pywebview API 未就绪');
        const action = window.pywebview.api[methodName];
        if (typeof action !== 'function') throw new Error('当前操作不可用');
        const result = await action();
        if (result && result.cancelled) return;
        if (!result || !result.ok) throw new Error((result && result.error) || '操作失败');
        if (result.settings) renderSettings(result.settings);
        hint.textContent = result.message || successText || '✓ 已完成';
        hint.className = 'hint';
    } catch (error) {
        hint.textContent = '✗ ' + error.message;
        hint.className = 'hint error';
    }
    setTimeout(function() {
        hint.textContent = '';
        hint.className = 'hint';
    }, 3000);
}

function chooseLive2DModelPath() {
    return runModeAction('choose_live2d_model_path', '✓ 已更新模型路径');
}

function importLive2DArchive() {
    return runModeAction('import_live2d_archive', '✓ 已导入资源包');
}

function openLive2DAssetsDir() {
    return runModeAction('open_live2d_assets_dir', '✓ 已打开默认导入目录');
}

function openLive2DReleases() {
    return runModeAction('open_live2d_releases', '✓ 已打开 Releases 页面');
}

function saveInput(key, input) {
    const value = input.type === 'number' && input.step === '0.01'
        ? num(input.value, 0)
        : (input.type === 'number' ? parseInt(input.value || '0', 10) : input.value);
    saveField(key, value);
}

async function saveField(key, value) {
    const hint = document.getElementById('save-hint');
    try {
        if (!window.pywebview || !window.pywebview.api) throw new Error('pywebview API 未就绪');
        const payload = {};
        payload[key] = value;
        const result = await window.pywebview.api.update_settings(payload);
        if (!result.ok) throw new Error(result.error || (result.errors || []).join('; ') || '保存失败');
        if (result.settings) renderSettings(result.settings);
        hint.textContent = result.restart_scheduled ? '✓ 已保存，正在重启应用…' : '✓ 已保存';
        hint.className = 'hint';
    } catch (error) {
        hint.textContent = '✗ ' + error.message;
        hint.className = 'hint error';
    }
    setTimeout(function() {
        hint.textContent = '';
        hint.className = 'hint';
    }, 3000);
}

function renderSettings(payload) {
    currentMode = payload.mode.id;
    currentSettings = payload.settings.config;
    document.getElementById('mode-title').textContent = payload.mode.settings_title;
    document.getElementById('mode-desc').textContent = payload.mode.settings_description;
    document.getElementById('mode-summary').textContent = payload.settings.summary;
    document.getElementById('mode-name').textContent = payload.mode.icon + ' ' + payload.mode.name;
    document.getElementById('part-title').textContent = '设置项';
    renderForm(payload.mode.id, payload.settings.config);
}

async function bootstrap() {
    if (!window.pywebview || !window.pywebview.api) return;
    const payload = await window.pywebview.api.get_mode_settings();
    renderSettings(payload);
}

document.addEventListener('DOMContentLoaded', function() { setTimeout(bootstrap, 200); });
window.addEventListener('pywebviewready', bootstrap);
</script>
</body>
</html>
"""


def open_mode_settings_window(config: "AppConfig", mode_id: str) -> bool:
    """打开单个模式的设置窗口。"""
    try:
        import webview  # type: ignore[import]
    except ImportError:
        logger.warning("pywebview 未安装，无法打开模式设置窗口")
        return False

    descriptor = get_mode_descriptor(mode_id)
    api = ModeSettingsAPI(config, descriptor.id)
    window = webview.create_window(
        title=f"Hermes-Yachiyo — {descriptor.settings_title}",
        html=_SETTINGS_HTML,
        width=520,
        height=620,
        resizable=True,
        js_api=api,
    )
    api.bind_window(window)
    return True
