"""主窗口管理

MVP 实现：使用 pywebview 展示本地状态页或安装引导页。
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
    from packages.protocol.install import HermesInstallInfo

from packages.protocol.enums import HermesInstallStatus

logger = logging.getLogger(__name__)

# 正常状态页 HTML
_STATUS_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 24px;
            line-height: 1.6;
        }
        .header {
            text-align: center;
            padding-bottom: 20px;
            border-bottom: 1px solid #333;
            margin-bottom: 20px;
        }
        .header h1 { color: #6495ed; font-size: 1.6em; margin-bottom: 4px; }
        .header .subtitle { color: #888; font-size: 0.9em; }
        .header .run-badge {
            display: inline-block;
            background: #1e3a1e;
            color: #90ee90;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 0.85em;
            margin-top: 8px;
        }
        .cards { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
        .card {
            background: #2d2d54;
            border-radius: 8px;
            padding: 16px;
        }
        .card h3 { color: #6495ed; font-size: 0.95em; margin-bottom: 10px; }
        .card .row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.9em; }
        .card .row .label { color: #999; }
        .card .row .value { color: #e0e0e0; }
        .card .row .value.ok { color: #90ee90; }
        .card .row .value.warn { color: #ffd700; }
        .modes {
            background: #2d2d54;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
        }
        .modes h3 { color: #6495ed; font-size: 0.95em; margin-bottom: 12px; }
        .mode-list { display: flex; gap: 12px; }
        .mode-btn {
            flex: 1;
            background: #3a3a6a;
            border: 1px solid #555;
            color: #ccc;
            padding: 12px;
            border-radius: 6px;
            cursor: pointer;
            text-align: center;
            transition: border-color 0.2s;
        }
        .mode-btn:hover { border-color: #6495ed; color: #fff; }
        .mode-btn.active { border-color: #6495ed; color: #fff; background: #4a4a8a; }
        .mode-btn .icon { font-size: 1.4em; display: block; margin-bottom: 4px; }
        .mode-btn .name { font-size: 0.85em; }
        .mode-btn .desc { font-size: 0.75em; color: #888; margin-top: 2px; }
        .footer {
            text-align: center;
            color: #555;
            font-size: 0.8em;
            padding-top: 12px;
            border-top: 1px solid #333;
        }
        /* 设置面板 */
        .settings-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        .settings-header h3 { color: #6495ed; font-size: 1.1em; }
        .settings-close {
            color: #888;
            cursor: pointer;
            font-size: 0.85em;
            padding: 4px 10px;
            border-radius: 4px;
            transition: background 0.2s;
        }
        .settings-close:hover { background: #3a3a6a; color: #fff; }
        .settings-section {
            background: #2d2d54;
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 12px;
        }
        .settings-section h4 {
            color: #ffd700;
            font-size: 0.85em;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1px solid #3a3a6a;
        }
        .settings-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 3px 0;
            font-size: 0.85em;
        }
        .settings-row .label { color: #999; }
        .settings-row .value { color: #e0e0e0; }
        .settings-row .value.ok { color: #90ee90; }
        .settings-row .value.warn { color: #ffd700; }
        .settings-modes { margin-top: 8px; }
        .settings-mode-item {
            display: inline-block;
            font-size: 0.8em;
            margin-right: 10px;
            color: #ccc;
        }
        .tag {
            display: inline-block;
            font-size: 0.75em;
            padding: 1px 6px;
            border-radius: 3px;
            background: #3a3a6a;
            color: #888;
        }
        .tag.ok { background: #1e3a1e; color: #90ee90; }
        .tag.active-tag { background: #2a2a5a; color: #6495ed; }
        /* 可编辑控件 */
        .s-select {
            background: #3a3a6a; color: #e0e0e0; border: 1px solid #555;
            border-radius: 4px; padding: 3px 8px; font-size: 0.85em;
            cursor: pointer; outline: none;
        }
        .s-select:focus { border-color: #6495ed; }
        .s-input {
            background: #3a3a6a; color: #e0e0e0; border: 1px solid #555;
            border-radius: 4px; padding: 3px 8px; font-size: 0.85em;
            width: 160px; outline: none;
        }
        .s-input:focus { border-color: #6495ed; }
        .s-toggle {
            position: relative; display: inline-block; width: 38px; height: 20px;
            cursor: pointer;
        }
        .s-toggle input { opacity: 0; width: 0; height: 0; }
        .s-toggle .slider {
            position: absolute; top: 0; left: 0; right: 0; bottom: 0;
            background: #555; border-radius: 10px; transition: background 0.2s;
        }
        .s-toggle .slider::before {
            content: ""; position: absolute; height: 14px; width: 14px;
            left: 3px; bottom: 3px; background: #e0e0e0;
            border-radius: 50%; transition: transform 0.2s;
        }
        .s-toggle input:checked + .slider { background: #6495ed; }
        .s-toggle input:checked + .slider::before { transform: translateX(18px); }
        .save-hint {
            text-align: right; font-size: 0.8em; color: #888;
            margin-top: 6px; min-height: 1.2em;
        }
        .save-hint.ok { color: #90ee90; }
        .save-hint.err { color: #ff6b6b; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Hermes-Yachiyo</h1>
        <div class="subtitle">桌面优先本地个人 Agent</div>
        <div class="run-badge" id="run-badge">● 运行中</div>
    </div>

    <div class="cards">
        <div class="card">
            <h3>Hermes Agent</h3>
            <div class="row"><span class="label">状态</span><span class="value" id="hermes-status">检测中…</span></div>
            <div class="row"><span class="label">版本</span><span class="value" id="hermes-version">—</span></div>
            <div class="row"><span class="label">平台</span><span class="value" id="hermes-platform">—</span></div>
        </div>
        <div class="card">
            <h3>Yachiyo 工作空间</h3>
            <div class="row"><span class="label">状态</span><span class="value" id="ws-status">检测中…</span></div>
            <div class="row"><span class="label">路径</span><span class="value" id="ws-path" style="font-size:0.8em;">—</span></div>
            <div class="row"><span class="label">创建时间</span><span class="value" id="ws-created">—</span></div>
        </div>
        <div class="card">
            <h3>运行信息</h3>
            <div class="row"><span class="label">运行时间</span><span class="value" id="app-uptime">—</span></div>
            <div class="row"><span class="label">版本</span><span class="value" id="app-version">—</span></div>
            <div class="row"><span class="label">Bridge</span><span class="value" id="bridge-enabled">—</span></div>
            <div class="row"><span class="label">Bridge 地址</span><span class="value" id="bridge-addr" style="font-size:0.8em;">—</span></div>
        </div>
        <div class="card">
            <h3>任务统计</h3>
            <div class="row"><span class="label">等待中</span><span class="value" id="task-pending">0</span></div>
            <div class="row"><span class="label">运行中</span><span class="value" id="task-running">0</span></div>
            <div class="row"><span class="label">已完成</span><span class="value" id="task-completed">0</span></div>
        </div>
        <div class="card" style="grid-column: span 2;">
            <h3>集成服务</h3>
            <div class="row"><span class="label">AstrBot / QQ</span><span class="value" id="int-astrbot">—</span></div>
            <div class="row"><span class="label">Hapi / Codex</span><span class="value" id="int-hapi">—</span></div>
        </div>
    </div>

    <div class="modes">
        <h3>显示模式</h3>
        <div class="mode-list">
            <div class="mode-btn active" id="mode-window">
                <span class="icon">🖥️</span>
                <span class="name">窗口模式</span>
                <span class="desc">标准窗口</span>
            </div>
            <div class="mode-btn" id="mode-bubble">
                <span class="icon">💬</span>
                <span class="name">气泡模式</span>
                <span class="desc">即将推出</span>
            </div>
            <div class="mode-btn" id="mode-live2d">
                <span class="icon">🎭</span>
                <span class="name">Live2D</span>
                <span class="desc">即将推出</span>
            </div>
            <div class="mode-btn" id="mode-settings" onclick="toggleSettings()">
                <span class="icon">⚙️</span>
                <span class="name">设置</span>
                <span class="desc">应用配置</span>
            </div>
        </div>
    </div>

    <!-- 设置面板（默认隐藏） -->
    <div id="settings-panel" style="display:none;">
        <div class="settings-header">
            <h3>⚙️ 应用设置</h3>
            <span class="settings-close" onclick="toggleSettings()">✕ 返回</span>
        </div>

        <div class="settings-section">
            <h4>Hermes Agent</h4>
            <div class="settings-row"><span class="label">安装状态</span><span class="value" id="s-hermes-status">—</span></div>
            <div class="settings-row"><span class="label">版本</span><span class="value" id="s-hermes-version">—</span></div>
            <div class="settings-row"><span class="label">平台</span><span class="value" id="s-hermes-platform">—</span></div>
            <div class="settings-row"><span class="label">命令可用</span><span class="value" id="s-hermes-cmd">—</span></div>
            <div class="settings-row"><span class="label">Hermes Home</span><span class="value" id="s-hermes-home" style="font-size:0.8em;">—</span></div>
        </div>

        <div class="settings-section">
            <h4>Yachiyo 工作空间</h4>
            <div class="settings-row"><span class="label">初始化状态</span><span class="value" id="s-ws-status">—</span></div>
            <div class="settings-row"><span class="label">路径</span><span class="value" id="s-ws-path" style="font-size:0.8em;">—</span></div>
            <div class="settings-row"><span class="label">创建时间</span><span class="value" id="s-ws-created">—</span></div>
        </div>

        <div class="settings-section">
            <h4>显示模式</h4>
            <div class="settings-row"><span class="label">当前模式</span>
                <select class="s-select" id="s-display-mode" onchange="onSettingChange('display_mode', this.value)">
                    <option value="window">窗口模式</option>
                    <option value="bubble" disabled>气泡模式（即将推出）</option>
                    <option value="live2d" disabled>Live2D 模式（即将推出）</option>
                </select>
            </div>
            <div id="s-display-modes" class="settings-modes"></div>
        </div>

        <div class="settings-section">
            <h4>Bridge / 内部通信</h4>
            <div class="settings-row"><span class="label">启用</span>
                <label class="s-toggle"><input type="checkbox" id="s-bridge-enabled" onchange="onSettingChange('bridge_enabled', this.checked)"><span class="slider"></span></label>
            </div>
            <div class="settings-row"><span class="label">地址</span>
                <input class="s-input" id="s-bridge-host" value="" placeholder="127.0.0.1" onchange="onSettingChange('bridge_host', this.value)">
            </div>
            <div class="settings-row"><span class="label">端口</span>
                <input class="s-input" id="s-bridge-port" type="number" min="1024" max="65535" value="" onchange="onSettingChange('bridge_port', parseInt(this.value))">
            </div>
            <div class="settings-row"><span class="label">完整地址</span><span class="value" id="s-bridge-url">—</span></div>
        </div>

        <div class="settings-section">
            <h4>集成服务</h4>
            <div class="settings-row"><span class="label" id="s-int-astrbot-name">AstrBot / QQ</span><span class="value" id="s-int-astrbot-status">—</span></div>
            <div class="settings-row"><span class="label" id="s-int-hapi-name">Hapi / Codex</span><span class="value" id="s-int-hapi-status">—</span></div>
        </div>

        <div class="settings-section">
            <h4>应用</h4>
            <div class="settings-row"><span class="label">版本</span><span class="value" id="s-app-version">—</span></div>
            <div class="settings-row"><span class="label">日志级别</span><span class="value" id="s-app-loglevel">—</span></div>
            <div class="settings-row"><span class="label">系统托盘</span>
                <label class="s-toggle"><input type="checkbox" id="s-tray-enabled" onchange="onSettingChange('tray_enabled', this.checked)"><span class="slider"></span></label>
            </div>
            <div class="settings-row"><span class="label">启动最小化</span><span class="value" id="s-app-minimized">—</span></div>
        </div>
        <div class="save-hint" id="save-hint"></div>
    </div>

    <div class="footer" id="main-footer">
        Bridge API: http://{{HOST}}:{{PORT}} · Hermes-Yachiyo v0.1.0
    </div>

    <script>
    let settingsOpen = false;

    function toggleSettings() {
        settingsOpen = !settingsOpen;
        document.getElementById('settings-panel').style.display = settingsOpen ? 'block' : 'none';
        // 隐藏/显示仪表盘区域
        document.querySelector('.cards').style.display = settingsOpen ? 'none' : 'grid';
        document.querySelector('.modes').style.display = settingsOpen ? 'none' : 'block';
        // 高亮设置按钮
        document.getElementById('mode-settings').classList.toggle('active', settingsOpen);
        document.getElementById('mode-window').classList.toggle('active', !settingsOpen);
        if (settingsOpen) refreshSettings();
    }

    async function refreshSettings() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const d = await window.pywebview.api.get_settings_data();
            if (d.error) return;

            // Hermes
            const hsEl = document.getElementById('s-hermes-status');
            hsEl.textContent = d.hermes.ready ? '✅ 已就绪' : '⚠️ ' + d.hermes.status;
            hsEl.className = 'value ' + (d.hermes.ready ? 'ok' : 'warn');
            document.getElementById('s-hermes-version').textContent = d.hermes.version || '未知';
            document.getElementById('s-hermes-platform').textContent = d.hermes.platform;
            document.getElementById('s-hermes-cmd').textContent = d.hermes.command_exists ? '✅ 是' : '❌ 否';
            document.getElementById('s-hermes-home').textContent = d.hermes.hermes_home || '~/.hermes (默认)';

            // Workspace
            const wsEl = document.getElementById('s-ws-status');
            wsEl.textContent = d.workspace.initialized ? '✅ 已初始化' : '⚠️ 未初始化';
            wsEl.className = 'value ' + (d.workspace.initialized ? 'ok' : 'warn');
            document.getElementById('s-ws-path').textContent = d.workspace.path || '—';
            document.getElementById('s-ws-created').textContent = d.workspace.created_at || '—';

            // Display
            document.getElementById('s-display-mode').value = d.display.current_mode;
            const modesDiv = document.getElementById('s-display-modes');
            modesDiv.innerHTML = d.display.available_modes.map(function(m) {
                const tag = m.available ? '<span class="tag ok">可用</span>' : '<span class="tag">即将推出</span>';
                const active = m.id === d.display.current_mode ? ' <span class="tag active-tag">当前</span>' : '';
                return '<div class="settings-mode-item">' + m.name + ' ' + tag + active + '</div>';
            }).join('');

            // Bridge
            document.getElementById('s-bridge-enabled').checked = d.bridge.enabled;
            document.getElementById('s-bridge-host').value = d.bridge.host;
            document.getElementById('s-bridge-port').value = d.bridge.port;
            document.getElementById('s-bridge-url').textContent = d.bridge.url;

            // Integrations
            const statusLabels = {'not_configured': '⏳ 未配置', 'connected': '✅ 已连接', 'error': '❌ 错误'};
            document.getElementById('s-int-astrbot-status').textContent = statusLabels[d.integrations.astrbot.status] || d.integrations.astrbot.status;
            document.getElementById('s-int-hapi-status').textContent = statusLabels[d.integrations.hapi.status] || d.integrations.hapi.status;

            // App
            document.getElementById('s-app-version').textContent = 'v' + d.app.version;
            document.getElementById('s-app-loglevel').textContent = d.app.log_level;
            document.getElementById('s-tray-enabled').checked = d.app.tray_enabled;
            document.getElementById('s-app-minimized').textContent = d.app.start_minimized ? '是' : '否';
        } catch(e) {}
    }
    async function onSettingChange(key, value) {
        const hint = document.getElementById('save-hint');
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const changes = {};
            changes[key] = value;
            const res = await window.pywebview.api.update_settings(changes);
            if (res.ok) {
                hint.textContent = '✓ 已保存';
                hint.className = 'save-hint ok';
                // 刷新设置面板以反映新值
                refreshSettings();
            } else {
                hint.textContent = '✗ ' + (res.error || res.errors.join('; '));
                hint.className = 'save-hint err';
            }
        } catch(e) {
            hint.textContent = '✗ 保存失败';
            hint.className = 'save-hint err';
        }
        setTimeout(function(){ hint.textContent = ''; hint.className = 'save-hint'; }, 3000);
    }

    async function refreshDashboard() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const data = await window.pywebview.api.get_dashboard_data();
            if (data.error) return;

            // Hermes
            const hs = document.getElementById('hermes-status');
            if (data.hermes.ready) {
                hs.textContent = '✅ 已就绪';
                hs.className = 'value ok';
            } else {
                hs.textContent = '⚠️ ' + data.hermes.status;
                hs.className = 'value warn';
            }
            document.getElementById('hermes-version').textContent = data.hermes.version || '未知';
            document.getElementById('hermes-platform').textContent = data.hermes.platform;

            // Workspace
            const ws = document.getElementById('ws-status');
            if (data.workspace.initialized) {
                ws.textContent = '✅ 已初始化';
                ws.className = 'value ok';
            } else {
                ws.textContent = '⚠️ 未初始化';
                ws.className = 'value warn';
            }
            document.getElementById('ws-path').textContent = data.workspace.path || '—';
            document.getElementById('ws-created').textContent = data.workspace.created_at || '—';

            // App
            const uptime = data.app.uptime_seconds;
            const min = Math.floor(uptime / 60);
            const sec = Math.floor(uptime % 60);
            document.getElementById('app-uptime').textContent = min > 0 ? min + '分' + sec + '秒' : sec + '秒';
            document.getElementById('app-version').textContent = 'v' + data.app.version;

            // Bridge
            const brEl = document.getElementById('bridge-enabled');
            brEl.textContent = data.bridge.enabled ? '✅ 已启用' : '❌ 已禁用';
            brEl.className = 'value ' + (data.bridge.enabled ? 'ok' : 'warn');
            document.getElementById('bridge-addr').textContent = data.bridge.url;

            // Tasks
            document.getElementById('task-pending').textContent = data.tasks.pending || 0;
            document.getElementById('task-running').textContent = data.tasks.running || 0;
            document.getElementById('task-completed').textContent = data.tasks.completed || 0;

            // Integrations
            const intLabels = {'not_connected': '⏳ 未接入', 'connected': '✅ 已连接', 'error': '❌ 错误'};
            document.getElementById('int-astrbot').textContent = intLabels[data.integrations.astrbot.status] || data.integrations.astrbot.status;
            document.getElementById('int-hapi').textContent = intLabels[data.integrations.hapi.status] || data.integrations.hapi.status;
        } catch(e) {}
    }

    // 首次加载和定时刷新
    document.addEventListener('DOMContentLoaded', function() {
        // pywebview ready 后刷新数据
        if (window.pywebview) {
            refreshDashboard();
        }
        setInterval(refreshDashboard, 5000);
    });

    // pywebview ready 事件
    window.addEventListener('pywebviewready', function() {
        refreshDashboard();
    });
    </script>
</body>
</html>
"""

# 安装引导页 HTML
_INSTALLER_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo - Hermes Agent 安装引导</title>
    <style>
        body {
            font-family: -apple-system, "Helvetica Neue", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 20px;
            margin: 0;
            line-height: 1.6;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        h1 { color: #6495ed; text-align: center; margin-bottom: 0.5em; }
        h2 { color: #ffd700; margin-top: 2em; }
        .status {
            background: #2d2d54;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #ff6b6b;
            margin: 20px 0;
        }
        .status.warning {
            border-left-color: #ffd700;
        }
        .status.info {
            border-left-color: #6495ed;
        }
        .platform { color: #90ee90; font-weight: bold; }
        .install-steps {
            background: #2d2d54;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
        }
        .step {
            margin: 10px 0;
            padding: 8px 0;
        }
        code {
            background: #0d1117;
            color: #58a6ff;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: 'Monaco', 'Consolas', monospace;
        }
        .code-block {
            background: #0d1117;
            color: #58a6ff;
            padding: 15px;
            border-radius: 4px;
            font-family: 'Monaco', 'Consolas', monospace;
            white-space: pre-line;
            margin: 10px 0;
            overflow-x: auto;
        }
        .links {
            margin-top: 20px;
        }
        a {
            color: #58a6ff;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .footer {
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #444;
            color: #888;
            font-size: 0.9em;
        }
        .init-button {
            background: #6495ed;
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 1.1em;
            margin: 20px 0;
            transition: background-color 0.3s;
        }
        .init-button:hover {
            background: #5a7fd8;
        }
        .init-section {
            background: #2d2d54;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid #6495ed;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Hermes-Yachiyo</h1>
        
        <div class="status {status_class}">
            <strong>状态：</strong>{status_message}<br>
            <strong>平台：</strong><span class="platform">{platform}</span><br>
            {error_info}
        </div>

        <h2>{main_title}</h2>
        <p>Hermes-Yachiyo 需要 <a href="https://github.com/NousResearch/hermes-agent" target="_blank">Hermes Agent</a> 作为底层运行时。</p>
        
        <div class="install-steps">
            <h3>{steps_title}</h3>
            {install_steps}
        </div>

        {init_section}

        {suggestions_section}

        <div class="links">
            <h3>相关链接：</h3>
            <ul>
                <li><a href="https://github.com/NousResearch/hermes-agent" target="_blank">Hermes Agent 官方仓库</a></li>
                <li><a href="https://github.com/NousResearch/hermes-agent/releases" target="_blank">发布页面</a></li>
                <li><a href="https://github.com/NousResearch/hermes-agent#installation" target="_blank">安装文档</a></li>
            </ul>
        </div>

        <div class="footer">
            安装完成后，重新启动 Hermes-Yachiyo 即可正常使用。
        </div>
    </div>
</body>
</html>
"""


def create_main_window(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """创建并显示主窗口（阻塞主线程）- 正常模式"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，以无窗口模式运行")
        _print_console_dashboard(runtime, config)
        import threading
        threading.Event().wait()
        return

    from apps.shell.main_api import MainWindowAPI
    api = MainWindowAPI(runtime, config)

    html = _STATUS_HTML.replace("{{HOST}}", config.bridge_host).replace("{{PORT}}", str(config.bridge_port))

    webview.create_window(
        title="Hermes-Yachiyo",
        html=html,
        width=560,
        height=520,
        resizable=True,
    )
    webview.start(api=api, debug=False)


def create_installer_window(install_info: "HermesInstallInfo", config: "AppConfig") -> None:
    """创建并显示安装引导窗口（阻塞主线程）- 安装引导模式"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，显示控制台安装信息")
        _print_console_install_info(install_info)
        # 无窗口模式下保持主线程活跃
        import threading

        threading.Event().wait()
        return

    html = _generate_installer_html(install_info)
    
    # 如果是工作空间初始化模式，启用 API
    api = None
    if install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED:
        from apps.shell.installer_api import InstallerWebViewAPI
        api = InstallerWebViewAPI()

    webview.create_window(
        title="Hermes-Yachiyo - Hermes Agent 安装引导",
        html=html,
        width=800,
        height=600,
        resizable=True,
    )
    webview.start(api=api, debug=False)


def _generate_installer_html(install_info: "HermesInstallInfo") -> str:
    """生成安装引导页面的 HTML 内容"""
    from apps.installer.hermes_install import HermesInstallGuide
    from packages.protocol.enums import HermesInstallStatus

    # 获取安装指导
    guidance = HermesInstallGuide.get_install_instructions(install_info)
    
    # 状态样式和消息
    status_mapping = {
        HermesInstallStatus.NOT_INSTALLED: ("warning", "Hermes Agent 未安装"),
        HermesInstallStatus.INSTALLED_NOT_INITIALIZED: ("info", "Hermes Agent 已安装，需要初始化 Yachiyo 工作空间"),
        HermesInstallStatus.INCOMPATIBLE_VERSION: ("warning", "Hermes Agent 版本不兼容"),
        HermesInstallStatus.PLATFORM_UNSUPPORTED: ("", "平台不支持"),
        HermesInstallStatus.WSL2_REQUIRED: ("info", "需要 WSL2 环境"),
    }
    
    status_class, status_message = status_mapping.get(
        install_info.status, 
        ("", f"状态: {install_info.status}")
    )
    
    # 错误信息
    error_info = ""
    if install_info.error_message:
        error_info = f"<strong>详情：</strong>{install_info.error_message}"
    
    # 根据状态确定主标题和步骤内容
    if install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED:
        main_title = "初始化 Yachiyo 工作空间"
        steps_title = "初始化步骤："
    else:
        main_title = "安装 Hermes Agent"
        steps_title = "安装步骤："
    
    # 安装/配置步骤
    install_steps = ""
    if "actions" in guidance:
        steps_html = []
        for i, action in enumerate(guidance["actions"], 1):
            if action.startswith("  "):
                # 缩进的命令或说明
                steps_html.append(f'<div class="code-block">{action.strip()}</div>')
            elif action.strip() == "":
                # 空行
                steps_html.append('<br>')
            else:
                # 普通步骤
                steps_html.append(f'<div class="step">{action}</div>')
        install_steps = "\n".join(steps_html)
    
    # 初始化按钮区域
    init_section = ""
    if install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED and guidance.get("can_initialize", False):
        init_section = f"""
        <div class="init-section">
            <h3>🚀 快速初始化</h3>
            <p>系统可以自动为您创建 Yachiyo 工作空间，包括必要的目录结构和配置文件。</p>
            <button class="init-button" onclick="initializeWorkspace()">自动初始化工作空间</button>
            <div id="init-status" style="margin-top: 10px; color: #888;"></div>
        </div>
        <script>
        async function initializeWorkspace() {{
            const button = document.querySelector('.init-button');
            const status = document.getElementById('init-status');
            
            button.disabled = true;
            button.textContent = '正在初始化...';
            status.textContent = '正在创建工作空间，请稍候...';
            status.style.color = '#6495ed';
            
            try {{
                // 调用 WebView 初始化功能（如果支持的话）
                if (window.pywebview && window.pywebview.api && window.pywebview.api.initialize_workspace) {{
                    const result = await window.pywebview.api.initialize_workspace();
                    if (result.success) {{
                        status.textContent = '✅ 初始化成功！正在重启应用...';
                        status.style.color = '#90ee90';
                        // 延迟重启，让用户看到成功消息
                        setTimeout(() => {{
                            if (window.pywebview && window.pywebview.api && window.pywebview.api.restart_app) {{
                                window.pywebview.api.restart_app();
                            }} else {{
                                status.textContent = '请手动重启 Hermes-Yachiyo 以继续';
                            }}
                        }}, 2000);
                    }} else {{
                        throw new Error(result.error || '初始化失败');
                    }}
                }} else {{
                    throw new Error('自动初始化功能不可用，请手动执行初始化步骤');
                }}
            }} catch (error) {{
                button.disabled = false;
                button.textContent = '重新尝试初始化';
                status.textContent = '❌ ' + error.message;
                status.style.color = '#ff6b6b';
            }}
        }}
        </script>
        """
    
    # 建议部分
    suggestions_section = ""
    if install_info.suggestions:
        suggestions_html = []
        for suggestion in install_info.suggestions:
            suggestions_html.append(f'<li>{suggestion}</li>')
        suggestions_section = f"""
        <div class="install-steps">
            <h3>建议：</h3>
            <ul>{"".join(suggestions_html)}</ul>
        </div>
        """
    
    return _INSTALLER_HTML.format(
        main_title=main_title,
        steps_title=steps_title,
        status_class=status_class,
        status_message=status_message,
        platform=install_info.platform,
        error_info=error_info,
        install_steps=install_steps,
        init_section=init_section,
        suggestions_section=suggestions_section,
    )


def _print_console_dashboard(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """在控制台显示仪表盘信息（无 pywebview 时的备选方案）"""
    status = runtime.get_status()
    print("\n" + "=" * 60)
    print("Hermes-Yachiyo - 正常模式（控制台）")
    print("=" * 60)
    print(f"Hermes 状态: {status.get('hermes_status', '未知')}")
    print(f"Bridge 地址: http://{config.bridge_host}:{config.bridge_port}")
    print(f"显示模式: {config.display_mode}")
    print("=" * 60)


def _print_console_install_info(install_info: "HermesInstallInfo") -> None:
    """在控制台显示安装信息（无 pywebview 时的备选方案）"""
    print("\n" + "="*60)
    print("Hermes-Yachiyo - Hermes Agent 安装引导")
    print("="*60)
    print(f"状态: {install_info.status}")
    print(f"平台: {install_info.platform}")
    
    if install_info.error_message:
        print(f"错误: {install_info.error_message}")
    
    if install_info.suggestions:
        print("\n建议:")
        for suggestion in install_info.suggestions:
            print(f"  - {suggestion}")
    
    print("\n相关链接:")
    print("  - Hermes Agent 官方仓库: https://github.com/NousResearch/hermes-agent")
    print("  - 发布页面: https://github.com/NousResearch/hermes-agent/releases")
    
    print("\n安装完成后，重新启动 Hermes-Yachiyo 即可正常使用。")
    print("="*60)
