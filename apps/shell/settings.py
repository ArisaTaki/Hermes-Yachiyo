"""模式设置窗口。

该窗口只负责单一模式的设置，不再混合所有模式字段。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from apps.shell.mode_catalog import get_mode_descriptor
from apps.shell.mode_settings import apply_settings_changes, serialize_mode_window_data

if TYPE_CHECKING:
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


class ModeSettingsAPI:
    """单模式设置窗口 API。"""

    def __init__(self, config: "AppConfig", mode_id: str) -> None:
        self._config = config
        self._mode_id = mode_id

    def get_mode_settings(self) -> dict[str, Any]:
        return serialize_mode_window_data(self._config, self._mode_id)

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        result = apply_settings_changes(self._config, changes)
        if result.get("ok"):
            result["settings"] = serialize_mode_window_data(self._config, self._mode_id)
        return result


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
</style>
</head>
<body>
    <h2 id="mode-title">模式设置</h2>
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
            <span class="label">渲染入口预留</span>
            <span class="value" id="live2d-entry" style="font-size:0.78em;word-break:break-all;">—</span>
        </div>
    </div>

    <div class="section">
        <h3>设置项</h3>
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

function selectRow(key, label, value, options) {
    const opts = options.map(function(opt) {
        const selected = opt.value === value ? ' selected' : '';
        return '<option value="' + escapeHtml(opt.value) + '"' + selected + '>' + escapeHtml(opt.label) + '</option>';
    }).join('');
    return '<div class="row"><span class="label">' + label + '</span>'
        + '<select class="select" onchange="saveField(\\'' + key + '\\', this.value)">' + opts + '</select></div>';
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
    if (currentMode !== 'live2d') {
        stateRow.style.display = 'none';
        entryRow.style.display = 'none';
        return;
    }
    stateRow.style.display = 'flex';
    entryRow.style.display = 'flex';
    const labels = {
        not_configured: ['⚪ 未配置', ''],
        path_invalid: ['❌ 路径不存在', 'warn'],
        path_not_live2d: ['⚠️ 目录无模型文件', 'warn'],
        path_valid: ['✅ 模型目录就绪 · 渲染器待实现', 'ok'],
        loaded: ['✅ 已加载', 'ok'],
    };
    const info = labels[cfg.model_state] || [cfg.model_state || '—', ''];
    const stateEl = document.getElementById('live2d-state');
    stateEl.textContent = info[0];
    stateEl.className = 'value' + (info[1] ? ' ' + info[1] : '');
    document.getElementById('live2d-entry').textContent = (cfg.summary && cfg.summary.renderer_entry) || '—';
}

function renderForm(mode, cfg) {
    const form = document.getElementById('mode-form');
    let html = '';

    if (mode === 'window') {
        html += inputRow('window_mode.width', '窗口宽度', cfg.width, 'number');
        html += inputRow('window_mode.height', '窗口高度', cfg.height, 'number');
        html += inputRow('window_mode.recent_sessions_limit', '最近会话条数', cfg.recent_sessions_limit, 'number');
        html += inputRow('window_mode.recent_messages_limit', '最近消息条数', cfg.recent_messages_limit, 'number');
        html += boolRow('window_mode.open_chat_on_start', '启动即打开聊天窗口', cfg.open_chat_on_start);
        html += boolRow('window_mode.show_runtime_panel', '显示运行状态卡', cfg.show_runtime_panel);
        html += boolRow('window_mode.show_mode_overview', '显示模式概览', cfg.show_mode_overview);
    } else if (mode === 'bubble') {
        html += inputRow('bubble_mode.width', '气泡宽度', cfg.width, 'number');
        html += inputRow('bubble_mode.height', '气泡高度', cfg.height, 'number');
        html += inputRow('bubble_mode.position_x', '位置 X', cfg.position_x, 'number');
        html += inputRow('bubble_mode.position_y', '位置 Y', cfg.position_y, 'number');
        html += boolRow('bubble_mode.always_on_top', '窗口置顶', cfg.always_on_top);
        html += boolRow('bubble_mode.edge_snap', '靠边吸附', cfg.edge_snap);
        html += boolRow('bubble_mode.expanded_on_start', '启动默认展开', cfg.expanded_on_start);
        html += selectRow('bubble_mode.expand_trigger', '展开方式', cfg.expand_trigger, [
            { value: 'click', label: '点击切换' },
            { value: 'hover', label: '悬停展开（占位）' },
        ]);
        html += selectRow('bubble_mode.default_display', '默认展示内容', cfg.default_display, [
            { value: 'icon', label: '仅图标' },
            { value: 'summary', label: '摘要' },
            { value: 'recent_reply', label: '最近回复' },
        ]);
        html += inputRow('bubble_mode.summary_count', '摘要条数', cfg.summary_count, 'number');
        html += boolRow('bubble_mode.show_unread_dot', '显示未读点', cfg.show_unread_dot);
        html += boolRow('bubble_mode.auto_hide', '自动隐藏', cfg.auto_hide);
        html += inputRow('bubble_mode.opacity', '透明度', cfg.opacity, 'number', '0.01');
    } else if (mode === 'live2d') {
        html += inputRow('live2d_mode.model_name', '模型名称', cfg.model_name);
        html += inputRow('live2d_mode.model_path', '模型路径', cfg.model_path);
        html += inputRow('live2d_mode.width', '窗口宽度', cfg.width, 'number');
        html += inputRow('live2d_mode.height', '窗口高度', cfg.height, 'number');
        html += inputRow('live2d_mode.position_x', '位置 X', cfg.position_x, 'number');
        html += inputRow('live2d_mode.position_y', '位置 Y', cfg.position_y, 'number');
        html += boolRow('live2d_mode.window_on_top', '窗口置顶', cfg.window_on_top);
        html += boolRow('live2d_mode.show_reply_bubble', '显示回复气泡', cfg.show_reply_bubble);
        html += selectRow('live2d_mode.default_open_behavior', '默认打开行为', cfg.default_open_behavior, [
            { value: 'stage', label: '角色舞台' },
            { value: 'reply_bubble', label: '回复气泡' },
            { value: 'chat_input', label: '输入入口' },
        ]);
        html += selectRow('live2d_mode.click_action', '点击行为', cfg.click_action, [
            { value: 'open_chat', label: '打开聊天窗口' },
            { value: 'focus_stage', label: '聚焦角色舞台' },
            { value: 'toggle_reply', label: '切换回复气泡' },
        ]);
        html += boolRow('live2d_mode.auto_open_chat_window', '自动打开聊天窗口', cfg.auto_open_chat_window);
        html += boolRow('live2d_mode.enable_quick_input', '启用最小输入入口', cfg.enable_quick_input);
        html += inputRow('live2d_mode.idle_motion_group', '待机动作组', cfg.idle_motion_group);
        html += boolRow('live2d_mode.enable_expressions', '启用表情系统', cfg.enable_expressions);
        html += boolRow('live2d_mode.enable_physics', '启用物理模拟', cfg.enable_physics);
    }

    form.innerHTML = html;
    renderLive2DInfo(cfg);
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
        hint.textContent = '✓ 已保存';
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
    webview.create_window(
        title=f"Hermes-Yachiyo — {descriptor.settings_title}",
        html=_SETTINGS_HTML,
        width=520,
        height=620,
        resizable=True,
        js_api=ModeSettingsAPI(config, descriptor.id),
    )
    return True
