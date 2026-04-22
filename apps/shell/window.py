"""主控台与安装窗口管理

MVP 实现：使用 pywebview 展示本地状态页或安装引导页。
这只是桌面壳原型方案，后续允许迁移到更完整的桌面壳技术。
pywebview 的使用不影响 core / bridge / protocol 的长期边界。
"""

from __future__ import annotations

import logging
import threading
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

_EXIT_DELAY_SECONDS = 0.1
_EXIT_FORCE_DELAY_SECONDS = 0.7
_RESTART_DELAY_SECONDS = 0.8
_exit_timer: threading.Timer | None = None
_force_exit_timer: threading.Timer | None = None
_exit_timer_lock = threading.Lock()
_restart_timer: threading.Timer | None = None
_restart_timer_lock = threading.Lock()

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
        .control-actions {
            background: #2d2d54;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
        }
        .control-actions h3 { color: #6495ed; font-size: 0.95em; margin-bottom: 12px; }
        .action-list { display: flex; gap: 12px; }
        .action-btn {
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
        .action-btn:hover { border-color: #6495ed; color: #fff; }
        .action-btn.active { border-color: #6495ed; color: #fff; background: #4a4a8a; }
        .action-btn .icon { font-size: 1.4em; display: block; margin-bottom: 4px; }
        .action-btn .name { font-size: 0.85em; }
        .action-btn .desc { font-size: 0.75em; color: #888; margin-top: 2px; }
        /* 会话中心面板样式 */
        .chat-panel {
            background: #2d2d54;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
        }
        .chat-panel h3 { color: #6495ed; font-size: 0.95em; margin-bottom: 0; }
        .chat-panel .status-line {
            font-size: 0.8em;
            color: #a5aed4;
        }
        .recent-messages {
            margin-top: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .recent-msg {
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 0.84em;
            line-height: 1.5;
            background: #242447;
            color: #d8def6;
        }
        .recent-msg.user { border-left: 3px solid #6495ed; }
        .recent-msg.assistant { border-left: 3px solid #90ee90; }
        .recent-msg.system { border-left: 3px solid #888; color: #b2b2c4; }
        .recent-msg.processing { color: #ffd700; }
        .recent-msg.failed { color: #ffaaaa; }
        .recent-sessions {
            margin-top: 12px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .session-pill {
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 0.76em;
            color: #c8cff3;
            background: #242447;
        }
        .session-pill.current {
            border: 1px solid #6495ed;
            color: #ffffff;
        }
        .empty-state {
            color: #777;
            text-align: center;
            font-size: 0.82em;
            padding: 16px 8px;
        }
        .mode-settings-list {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin-top: 8px;
        }
        .mode-settings-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            border-radius: 8px;
            background: #242447;
        }
        .mode-settings-item .meta {
            min-width: 0;
            flex: 1;
        }
        .mode-settings-item .meta .title {
            color: #eef2ff;
            font-size: 0.86em;
            margin-bottom: 4px;
        }
        .mode-settings-item .meta .desc {
            color: #9ba3cf;
            font-size: 0.78em;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .mode-settings-open {
            background: #3a4f92;
            border: 1px solid #6495ed;
            color: #fff;
            padding: 6px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.82em;
        }
        .chat-send-btn {
            background: #4a6a9a;
            border: none;
            color: #fff;
            padding: 10px 18px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9em;
            transition: background 0.2s;
        }
        .chat-send-btn:hover { background: #5a7aaa; }
        .app-exit-btn {
            background: transparent;
            border: 1px solid #66404a;
            color: #c98a96;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.86em;
        }
        .app-exit-btn:hover { border-color: #dd6b7a; color: #ffb1bd; background: #2d242e; }
        .exit-dialog-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(8, 8, 16, 0.55);
            display: none;
            align-items: center;
            justify-content: center;
            padding: 24px;
            z-index: 20;
        }
        .exit-dialog-backdrop.visible { display: flex; }
        .exit-dialog {
            background: #252548;
            border: 1px solid #56568a;
            border-radius: 8px;
            max-width: 360px;
            padding: 18px;
            box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
        }
        .exit-dialog h3 { color: #ffb1bd; font-size: 1.05em; margin-bottom: 8px; }
        .exit-dialog p { color: #c8c8d8; font-size: 0.9em; margin-bottom: 14px; }
        .exit-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
        .exit-dialog-actions button {
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.88em;
            padding: 7px 12px;
        }
        .exit-cancel-btn { background: #33335c; border: 1px solid #55557a; color: #ddd; }
        .exit-confirm-btn { background: #53303a; border: 1px solid #b85a6a; color: #ffd3da; }
        .exit-confirm-btn:disabled { cursor: wait; opacity: 0.65; }
        .exit-dialog-error {
            color: #ffaaaa;
            font-size: 0.82em;
            min-height: 1.2em;
            margin-bottom: 10px;
        }
        .executor { color: #6a9a6a; }
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
        .effect-hints {
            margin-top: 8px; padding: 8px 10px; border-radius: 6px;
            font-size: 0.82em; line-height: 1.6;
            background: #1a1a2e; border: 1px solid #3a3a5a;
            display: none;
        }
        .effect-hints.visible { display: block; }
        .effect-hint-row { display: flex; align-items: center; gap: 6px; }
        .effect-hint-row .icon { flex-shrink: 0; }
        .effect-hint-immediate { color: #90ee90; }
        .effect-hint-mode { color: #ffd700; }
        .effect-hint-bridge { color: #ffa07a; }
        .effect-hint-app { color: #ff8c8c; }
        .bridge-dirty-hint {
            margin-top: 4px; padding: 4px 8px; border-radius: 4px;
            font-size: 0.78em; color: #ffa07a; background: #2a1a1a;
            border: 1px solid #553322; display: none;
        }
        .bridge-dirty-hint.visible { display: block; }
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
            <div class="row" id="hermes-limited-row" style="display:none;"><span class="label" style="font-size:0.82em;color:#cc8844;">受限工具</span><span class="value warn" id="hermes-limited" style="font-size:0.8em;">—</span></div>
            <div class="row" id="hermes-doctor-row" style="display:none;"><span class="label" style="font-size:0.82em;color:#cc8844;">诊断提示</span><span class="value warn" id="hermes-doctor" style="font-size:0.8em;">—</span></div>
            <!-- 补全能力入口：doctor 发现问题或受限工具时显示 -->
            <div id="hermes-enhance-row" style="display:none;margin-top:10px;">
                <button onclick="toggleHermesEnhancePanel()" id="hermes-enhance-btn"
                    style="width:100%;padding:6px 0;background:#2a3a5a;border:1px solid #4a6a9a;
                           border-radius:5px;color:#9ab4d8;font-size:0.84em;cursor:pointer;">
                    🔧 检测 / 补全 Hermes 能力
                </button>
            </div>
            <!-- inline 操作面板 -->
            <div id="hermes-enhance-panel" style="display:none;margin-top:8px;padding:10px;
                background:#1a2a3a;border-radius:6px;border-left:3px solid #cc8844;">
                <div style="color:#cc8844;font-size:0.82em;margin-bottom:8px;">
                    当前检测到部分工具或配置仍受限，可能影响消息平台、图像生成、搜索等能力。
                    完成以下操作可解锁更多能力：
                </div>
                <div style="display:flex;flex-direction:column;gap:6px;">
                    <button onclick="openHermesCmd('hermes setup')"
                        style="padding:5px 10px;background:#1e3a1e;border:1px solid #4a7a4a;
                               border-radius:4px;color:#90ee90;font-size:0.82em;cursor:pointer;text-align:left;">
                        ▶ 运行 <code>hermes setup</code> — 配置模型/API 密钥/工具开关
                    </button>
                    <button onclick="openHermesCmd('hermes doctor')"
                        style="padding:5px 10px;background:#2a2a1e;border:1px solid #7a7a4a;
                               border-radius:4px;color:#d4d490;font-size:0.82em;cursor:pointer;text-align:left;">
                        🔍 运行 <code>hermes doctor</code> — 查看能力诊断详情
                    </button>
                    <button onclick="recheckHermes()"
                        style="padding:5px 10px;background:#2a1e3a;border:1px solid #6a4a9a;
                               border-radius:4px;color:#b090d8;font-size:0.82em;cursor:pointer;text-align:left;">
                        🔄 重新检测 Hermes 状态
                    </button>
                </div>
                <div id="hermes-enhance-status" style="margin-top:8px;font-size:0.8em;min-height:1em;"></div>
            </div>
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
            <div class="row" id="int-astrbot-desc-row" style="display:none;"><span class="label" style="font-size:0.78em;color:#777;">说明</span><span class="value" id="int-astrbot-desc" style="font-size:0.78em;color:#888;">—</span></div>
            <div class="row" id="int-astrbot-blocker-row" style="display:none;"><span class="label" style="font-size:0.78em;color:#cc8844;">前置条件</span><span class="value" id="int-astrbot-blocker" style="font-size:0.78em;color:#cc8844;">—</span></div>
            <div class="row"><span class="label">Hapi / Codex</span><span class="value" id="int-hapi">—</span></div>
        </div>
    </div>

    <div class="control-actions">
        <h3>主控台</h3>
        <div class="action-list">
            <div class="action-btn" onclick="openChat()">
                <span class="icon">💬</span>
                <span class="name">打开对话</span>
                <span class="desc">Chat Window</span>
            </div>
            <div class="action-btn" id="action-bubble" onclick="openModeSettings('bubble')">
                <span class="icon">💬</span>
                <span class="name">Bubble 设置</span>
                <span class="desc">悬浮入口</span>
            </div>
            <div class="action-btn" id="action-live2d" onclick="openModeSettings('live2d')">
                <span class="icon">🎭</span>
                <span class="name">Live2D 设置</span>
                <span class="desc">角色入口</span>
            </div>
            <div class="action-btn" id="action-settings" onclick="toggleSettings()">
                <span class="icon">⚙️</span>
                <span class="name">应用设置</span>
                <span class="desc">全局配置</span>
            </div>
        </div>
    </div>

    <!-- 会话中心 -->
    <div class="chat-panel" id="chat-panel">
        <div style="display:flex;align-items:center;justify-content:space-between;">
            <h3>💬 会话中心</h3>
            <span class="executor" id="chat-executor" style="font-size:0.8em;">—</span>
        </div>
        <div class="status-line" id="chat-status" style="margin-top:8px;">正在读取当前会话状态…</div>
        <div id="chat-summary-list" class="recent-messages">
            <div class="empty-state">暂无消息。打开聊天窗口开始完整对话。</div>
        </div>
        <div id="chat-session-list" class="recent-sessions"></div>
        <div style="margin-top:12px;">
            <button class="chat-send-btn" onclick="openChat()" style="width:100%;padding:14px;font-size:1em;">
                打开 Chat Window
            </button>
        </div>
        <div style="margin-top:10px;text-align:right;">
            <button class="app-exit-btn" onclick="quitApp()">退出应用</button>
        </div>
    </div>

    <div class="exit-dialog-backdrop" id="exit-dialog" role="dialog" aria-modal="true">
        <div class="exit-dialog">
            <h3>退出 Hermes-Yachiyo？</h3>
            <p>退出会关闭主界面、对话窗口并停止后台服务。是否继续？</p>
            <div class="exit-dialog-error" id="exit-dialog-error"></div>
            <div class="exit-dialog-actions">
                <button class="exit-cancel-btn" onclick="hideExitDialog()">取消</button>
                <button class="exit-confirm-btn" id="exit-confirm-btn" onclick="confirmQuitApp()">退出</button>
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
            <div class="settings-row"><span class="label">能力就绪</span><span class="value" id="s-hermes-readiness">—</span></div>
            <div class="settings-row" id="s-hermes-limited-row" style="display:none;"><span class="label" style="color:#cc8844;">受限工具</span><span class="value warn" id="s-hermes-limited" style="font-size:0.8em;">—</span></div>
            <div class="settings-row" id="s-hermes-doctor-row" style="display:none;"><span class="label" style="color:#cc8844;">诊断提示</span><span class="value warn" id="s-hermes-doctor" style="font-size:0.8em;">—</span></div>
            <div class="settings-row"><span class="label">版本</span><span class="value" id="s-hermes-version">—</span></div>
            <div class="settings-row"><span class="label">平台</span><span class="value" id="s-hermes-platform">—</span></div>
            <div class="settings-row"><span class="label">命令可用</span><span class="value" id="s-hermes-cmd">—</span></div>
            <div class="settings-row"><span class="label">Hermes Home</span><span class="value" id="s-hermes-home" style="font-size:0.8em;">—</span></div>
            <!-- 补全能力操作区：非完整就绪或 doctor 有诊断时显示 -->
            <div id="s-hermes-enhance-section" style="display:none;margin-top:12px;padding:10px;
                 background:#1a2a3a;border-radius:6px;border-left:3px solid #cc8844;">
                <div style="color:#cc8844;font-size:0.82em;margin-bottom:8px;">
                    <b>检测到部分工具或配置仍受限。</b>
                    完成以下配置可解锁更多 Hermes 能力：
                </div>
                <div style="display:flex;flex-direction:column;gap:6px;">
                    <button onclick="openHermesCmd('hermes setup')"
                        style="padding:5px 10px;background:#1e3a1e;border:1px solid #4a7a4a;
                               border-radius:4px;color:#90ee90;font-size:0.82em;cursor:pointer;text-align:left;">
                        ▶ 运行 <code>hermes setup</code> — 配置模型 / API 密钥 / 工具开关
                    </button>
                    <button onclick="openHermesCmd('hermes doctor')"
                        style="padding:5px 10px;background:#2a2a1e;border:1px solid #7a7a4a;
                               border-radius:4px;color:#d4d490;font-size:0.82em;cursor:pointer;text-align:left;">
                        🔍 运行 <code>hermes doctor</code> — 查看能力诊断详情
                    </button>
                    <button onclick="recheckHermes()"
                        style="padding:5px 10px;background:#2a1e3a;border:1px solid #6a4a9a;
                               border-radius:4px;color:#b090d8;font-size:0.82em;cursor:pointer;text-align:left;">
                        🔄 重新检测 Hermes 状态
                    </button>
                </div>
                <div id="s-hermes-enhance-status" style="margin-top:8px;font-size:0.8em;min-height:1em;"></div>
            </div>
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
                    <option value="bubble">气泡模式</option>
                    <option value="live2d">Live2D 模式</option>
                </select>
            </div>
            <div id="s-display-modes" class="settings-modes"></div>
        </div>

        <div class="settings-section">
            <h4>模式设置</h4>
            <div class="mode-settings-list">
                <div class="mode-settings-item">
                    <div class="meta">
                        <div class="title">💬 Bubble Mode</div>
                        <div class="desc" id="s-bubble-summary">读取中…</div>
                    </div>
                    <button class="mode-settings-open" onclick="openModeSettings('bubble')">打开</button>
                </div>
                <div class="mode-settings-item">
                    <div class="meta">
                        <div class="title">🎭 Live2D Mode</div>
                        <div class="desc" id="s-live2d-summary">读取中…</div>
                    </div>
                    <button class="mode-settings-open" onclick="openModeSettings('live2d')">打开</button>
                </div>
            </div>
        </div>

        <div class="settings-section">
            <h4>Bridge / 内部通信</h4>
            <div class="settings-row"><span class="label">运行状态</span><span class="value" id="s-bridge-state">—</span></div>
            <div class="settings-row"><span class="label">启用</span>
                <label class="s-toggle"><input type="checkbox" id="s-bridge-enabled" onchange="onSettingChange('bridge_enabled', this.checked)"><span class="slider"></span></label>
            </div>
            <div class="settings-row"><span class="label">地址</span>
                <input class="s-input" id="s-bridge-host" value="" placeholder="127.0.0.1" onchange="onSettingChange('bridge_host', this.value)">
            </div>
            <div class="settings-row"><span class="label">端口</span>
                <input class="s-input" id="s-bridge-port" type="number" min="1024" max="65535" value="" onchange="onSettingChange('bridge_port', parseInt(this.value))">
            </div>
            <div class="settings-row"><span class="label">保存地址</span><span class="value" id="s-bridge-url">—</span></div>
            <div class="settings-row" id="s-bridge-boot-row" style="display:none;"><span class="label" style="color:#888;font-size:0.82em;">运行地址</span><span class="value" id="s-bridge-boot-url" style="font-size:0.82em;color:#888;">—</span></div>
            <div class="bridge-dirty-hint" id="bridge-dirty-hint">⚠️ Bridge 配置已修改，需重启 Bridge 后生效</div>
            <div class="bridge-drift-details" id="bridge-drift-details" style="display:none;font-size:0.78em;color:#cc8844;padding:4px 8px;"></div>
            <div id="bridge-restart-row" style="display:none;padding:6px 8px;">
                <button id="bridge-restart-btn" onclick="restartBridge()" style="background:#4a90d9;color:#fff;border:none;border-radius:4px;padding:5px 14px;cursor:pointer;font-size:0.85em;">🔄 应用配置并重启 Bridge</button>
                <span id="bridge-restart-msg" style="font-size:0.8em;margin-left:8px;"></span>
            </div>
        </div>

        <div class="settings-section">
            <h4>集成服务</h4>
            <div class="settings-row"><span class="label">AstrBot / QQ</span><span class="value" id="s-int-astrbot-status">—</span></div>
            <div class="settings-row" id="s-int-astrbot-desc-row" style="display:none;"><span class="label" style="font-size:0.78em;color:#777;">说明</span><span class="value" id="s-int-astrbot-desc" style="font-size:0.78em;color:#888;">—</span></div>
            <div class="settings-row" id="s-int-astrbot-blocker-row" style="display:none;"><span class="label" style="font-size:0.78em;color:#cc8844;">前置条件</span><span class="value" id="s-int-astrbot-blocker" style="font-size:0.78em;color:#cc8844;">—</span></div>
            <div class="settings-row"><span class="label">Hapi / Codex</span><span class="value" id="s-int-hapi-status">—</span></div>
            <div class="settings-row" style="border-top:1px solid #3a3a5a;margin-top:4px;padding-top:6px;">
                <span class="label" style="color:#666;font-size:0.78em;">AstrBot 是什么？</span>
                <span class="value" style="color:#666;font-size:0.75em;">通过 QQ 远程控制 Yachiyo 的桥接入口，依赖 Bridge 运行</span>
            </div>
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
        <div class="effect-hints" id="effect-hints"></div>
    </div>

    <div class="footer" id="main-footer">
        Bridge API: http://{{HOST}}:{{PORT}} · Hermes-Yachiyo v0.1.0
    </div>

    <script>
    let settingsOpen = false;
    let hermesAutoRecheckStarted = false;

    function escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = value || '';
        return div.innerHTML;
    }

    function toggleSettings() {
        settingsOpen = !settingsOpen;
        document.getElementById('settings-panel').style.display = settingsOpen ? 'block' : 'none';
        // 隐藏/显示仪表盘区域
        document.querySelector('.cards').style.display = settingsOpen ? 'none' : 'grid';
        document.querySelector('.control-actions').style.display = settingsOpen ? 'none' : 'block';
        document.getElementById('chat-panel').style.display = settingsOpen ? 'none' : 'block';
        // 高亮设置按钮
        document.getElementById('action-settings').classList.toggle('active', settingsOpen);
        if (settingsOpen) refreshSettings();
    }

    // ── 聊天功能 ────────────────────────────────────────────────────────────────

    async function openChat() {
        try {
            if (!window.pywebview || !window.pywebview.api) throw new Error('WebView API 不可用');
            await window.pywebview.api.open_chat();
        } catch(e) {
            console.error('openChat error:', e);
        }
    }

    async function openModeSettings(modeId) {
        try {
            if (!window.pywebview || !window.pywebview.api) throw new Error('WebView API 不可用');
            await window.pywebview.api.open_mode_settings(modeId);
        } catch(e) {
            console.error('openModeSettings error:', e);
        }
    }

    function quitApp() {
        const dialog = document.getElementById('exit-dialog');
        const err = document.getElementById('exit-dialog-error');
        const btn = document.getElementById('exit-confirm-btn');
        if (err) err.textContent = '';
        if (btn) {
            btn.disabled = false;
            btn.textContent = '退出';
        }
        if (dialog) dialog.classList.add('visible');
    }

    function hideExitDialog() {
        const dialog = document.getElementById('exit-dialog');
        if (dialog) dialog.classList.remove('visible');
    }

    async function confirmQuitApp() {
        const btn = document.getElementById('exit-confirm-btn');
        const err = document.getElementById('exit-dialog-error');
        if (btn) {
            btn.disabled = true;
            btn.textContent = '正在退出...';
        }
        if (err) err.textContent = '';
        try {
            if (window.pywebview && window.pywebview.api) {
                const r = await window.pywebview.api.quit_app();
                if (r && r.ok === false) throw new Error(r.error || '退出失败');
            } else {
                window.close();
            }
        } catch(e) {
            console.error('quitApp error:', e);
            if (err) err.textContent = e.message || '退出失败';
            if (btn) {
                btn.disabled = false;
                btn.textContent = '退出';
            }
        }
    }

    async function loadExecutorInfo() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const r = await window.pywebview.api.get_executor_info();
            const el = document.getElementById('chat-executor');
            if (el && r.executor) {
                el.textContent = r.executor === 'HermesExecutor' ? '🚀 Hermes' : '🔬 模拟';
            }
        } catch(e) {}
    }

    // ── Hermes 能力补全操作 ────────────────────────────────────────────────────

    function getHermesLimitedTools(hermes) {
        return (hermes && hermes.limited_tools) || [];
    }

    function getHermesIssueCount(hermes) {
        return Number((hermes && hermes.doctor_issues_count) || 0);
    }

    function hasHermesDiagnostics(hermes) {
        return getHermesLimitedTools(hermes).length > 0 || getHermesIssueCount(hermes) > 0;
    }

    function isHermesReadinessUnknown(hermes) {
        return hermes && (!hermes.readiness_level || hermes.readiness_level === 'unknown');
    }

    function formatHermesDiagnostics(hermes) {
        const tools = getHermesLimitedTools(hermes);
        const issueCount = getHermesIssueCount(hermes);
        const parts = [];
        if (tools.length > 0) parts.push(tools.length + ' 个工具受限：' + tools.join('、'));
        if (issueCount > 0) parts.push('doctor 报告 ' + issueCount + ' 个 issue');
        return parts.length > 0 ? parts.join('；') : '未发现额外工具限制';
    }

    function shouldShowHermesEnhance(hermes) {
        if (!hermes) return false;
        if (hermes.readiness_level === 'full_ready' && !hasHermesDiagnostics(hermes)) return false;
        return !!hermes.ready || hermes.readiness_level === 'basic_ready' || hasHermesDiagnostics(hermes);
    }

    function maybeAutoRecheckHermes(hermes) {
        if (!hermes || !hermes.ready || !isHermesReadinessUnknown(hermes) || hermesAutoRecheckStarted) return;
        hermesAutoRecheckStarted = true;
        setTimeout(function() { recheckHermes(); }, 120);
    }

    function renderHermesLimited(rowId, valueId, hermes, includeIssueHint) {
        const row = document.getElementById(rowId);
        const value = document.getElementById(valueId);
        if (!row || !value) return;
        const tools = getHermesLimitedTools(hermes);
        if (tools.length > 0) {
            row.style.display = 'flex';
            const issueHint = includeIssueHint && getHermesIssueCount(hermes) > 0
                ? ' — 运行 hermes setup 可补全'
                : '';
            value.textContent = tools.join('、') + issueHint;
        } else {
            row.style.display = 'none';
        }
    }

    function renderHermesDiagnostics(rowId, valueId, hermes) {
        const row = document.getElementById(rowId);
        const value = document.getElementById(valueId);
        if (!row || !value) return;
        if (hasHermesDiagnostics(hermes)) {
            row.style.display = 'flex';
            value.textContent = formatHermesDiagnostics(hermes);
        } else if (hermes && hermes.ready && isHermesReadinessUnknown(hermes)) {
            row.style.display = 'flex';
            value.textContent = '能力诊断尚未运行，正在重新检测；也可展开补全入口手动运行 hermes doctor';
        } else {
            row.style.display = 'none';
        }
    }

    function toggleHermesEnhancePanel() {
        const panel = document.getElementById('hermes-enhance-panel');
        const btn = document.getElementById('hermes-enhance-btn');
        if (!panel) return;
        const visible = panel.style.display !== 'none';
        panel.style.display = visible ? 'none' : 'block';
        if (btn) btn.textContent = visible ? '🔧 检测 / 补全 Hermes 能力' : '🔼 收起';
    }

    async function openHermesCmd(cmd) {
        // 状态提示元素（仪表盘或设置页，两者共用同一函数）
        const statusIds = ['hermes-enhance-status', 's-hermes-enhance-status'];
        function setStatus(msg) {
            statusIds.forEach(function(id) {
                const el = document.getElementById(id);
                if (el) el.innerHTML = msg;
            });
        }
        setStatus('<span style="color:#9ab4d8">⏳ 正在打开终端...</span>');
        try {
            if (!window.pywebview || !window.pywebview.api) throw new Error('WebView API 不可用');
            const r = await window.pywebview.api.open_terminal_command(cmd);
            if (r.success) {
                setStatus('<span style="color:#90ee90">✅ 终端已打开，请在终端中完成操作，完成后点击「重新检测」。</span>');
            } else {
                setStatus('<span style="color:#ff6b6b">❌ ' + (r.error || '无法打开终端') + '<br><span style="color:#888;font-size:0.88em;">请手动打开终端运行：' + cmd + '</span></span>');
            }
        } catch(e) {
            setStatus('<span style="color:#ff6b6b">❌ ' + e.message + '</span>');
        }
    }

    async function recheckHermes() {
        const statusIds = ['hermes-enhance-status', 's-hermes-enhance-status'];
        function setStatus(msg) {
            statusIds.forEach(function(id) {
                const el = document.getElementById(id);
                if (el) el.innerHTML = msg;
            });
        }
        setStatus('<span style="color:#9ab4d8">⏳ 正在重新检测 Hermes 状态...</span>');
        try {
            if (!window.pywebview || !window.pywebview.api) throw new Error('WebView API 不可用');
            const data = await window.pywebview.api.recheck_hermes();
            if (data.error) throw new Error(data.error);
            // 刷新仪表盘（直接用返回的最新数据）
            const rl = data.hermes ? data.hermes.readiness_level : 'unknown';
            const hs = document.getElementById('hermes-status');
            const hermes = data.hermes || {};
            if (hs) {
                if (rl === 'full_ready') { hs.textContent = '✅ 完整就绪'; hs.className = 'value ok'; }
                else if (rl === 'basic_ready') { hs.textContent = '⚠️ 基础可用 · 部分工具受限'; hs.className = 'value warn'; }
                else { hs.textContent = hermes.ready ? '✅ 已就绪' : '⚠️ ' + (hermes.status || ''); hs.className = hermes.ready ? 'value ok' : 'value warn'; }
            }
            renderHermesLimited('hermes-limited-row', 'hermes-limited', hermes, false);
            renderHermesDiagnostics('hermes-doctor-row', 'hermes-doctor', hermes);
            renderHermesLimited('s-hermes-limited-row', 's-hermes-limited', hermes, true);
            renderHermesDiagnostics('s-hermes-doctor-row', 's-hermes-doctor', hermes);
            const enhRow = document.getElementById('hermes-enhance-row');
            if (enhRow) enhRow.style.display = shouldShowHermesEnhance(hermes) ? 'block' : 'none';
            const sEnhSec = document.getElementById('s-hermes-enhance-section');
            if (sEnhSec) sEnhSec.style.display = shouldShowHermesEnhance(hermes) ? 'block' : 'none';
            if (rl === 'full_ready') {
                setStatus('<span style="color:#90ee90">✅ Hermes 已完整就绪！受限工具已补全。</span>');
                // 补全后隐藏操作面板
                const panel = document.getElementById('hermes-enhance-panel');
                if (panel) panel.style.display = 'none';
            } else if (shouldShowHermesEnhance(hermes)) {
                setStatus('<span style="color:#ffd700">⚠️ ' + formatHermesDiagnostics(hermes) + '。可继续运行 hermes setup 或 hermes doctor 完善配置。</span>');
            } else {
                setStatus('<span style="color:#9ab4d8">重检完成。当前状态：' + (rl || '未知') + '</span>');
            }
        } catch(e) {
            setStatus('<span style="color:#ff6b6b">❌ 检测失败：' + e.message + '</span>');
        }
    }

    async function refreshSettings() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const d = await window.pywebview.api.get_settings_data();
            if (d.error) return;

            // Hermes Agent — 按 readiness_level 分级显示
            const hsEl = document.getElementById('s-hermes-status');
            const srl = d.hermes.readiness_level;
            if (srl === 'full_ready') {
                hsEl.textContent = '✅ 完整就绪'; hsEl.className = 'value ok';
            } else if (srl === 'basic_ready') {
                hsEl.textContent = '⚠️ 基础可用'; hsEl.className = 'value warn';
            } else if (d.hermes.ready) {
                hsEl.textContent = '✅ 已就绪'; hsEl.className = 'value ok';
            } else {
                hsEl.textContent = '⚠️ ' + d.hermes.status; hsEl.className = 'value warn';
            }
            // 能力就绪行
            const rlEl = document.getElementById('s-hermes-readiness');
            if (rlEl) {
                const rlLabels = {
                    full_ready: '✅ 完整就绪',
                    basic_ready: '⚠️ 基础可用（部分工具受限）',
                    unknown: '—'
                };
                rlEl.textContent = rlLabels[srl] || (d.hermes.ready ? '✅ 已就绪' : '—');
                rlEl.className = 'value' + (srl === 'full_ready' ? ' ok' : srl === 'basic_ready' ? ' warn' : '');
            }
            renderHermesLimited('s-hermes-limited-row', 's-hermes-limited', d.hermes, true);
            renderHermesDiagnostics('s-hermes-doctor-row', 's-hermes-doctor', d.hermes);
            document.getElementById('s-hermes-version').textContent = d.hermes.version || '未知';
            document.getElementById('s-hermes-platform').textContent = d.hermes.platform;
            document.getElementById('s-hermes-cmd').textContent = d.hermes.command_exists ? '✅ 是' : '❌ 否';
            document.getElementById('s-hermes-home').textContent = d.hermes.hermes_home || '~/.hermes (默认)';
            // 设置页补全能力区：doctor 发现问题或受限工具时显示
            const sEnhSec = document.getElementById('s-hermes-enhance-section');
            if (sEnhSec) sEnhSec.style.display = shouldShowHermesEnhance(d.hermes) ? 'block' : 'none';
            maybeAutoRecheckHermes(d.hermes);

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
                const tag = m.available ? '<span class="tag ok">可用</span>' : '<span class="tag">不可用</span>';
                const active = m.id === d.display.current_mode ? ' <span class="tag active-tag">当前</span>' : '';
                return '<div class="settings-mode-item">' + m.icon + ' ' + m.name + ' ' + tag + active + '</div>';
            }).join('');

            // Mode settings summary
            if (d.mode_settings) {
                document.getElementById('s-bubble-summary').textContent = d.mode_settings.bubble.summary;
                document.getElementById('s-live2d-summary').textContent = d.mode_settings.live2d.summary;
            }

            // Bridge
            const bridgeStateLabels = {
                'disabled': '⛔ 已禁用', 'enabled_not_started': '⏳ 启动中',
                'running': '✅ 运行中', 'failed': '❌ 异常退出'
            };
            const bsEl = document.getElementById('s-bridge-state');
            bsEl.textContent = bridgeStateLabels[d.bridge.state] || d.bridge.state;
            bsEl.className = 'value' + (d.bridge.state === 'running' ? ' ok' : d.bridge.state === 'failed' ? ' warn' : '');
            document.getElementById('s-bridge-enabled').checked = d.bridge.enabled;
            const bhEl = document.getElementById('s-bridge-host');
            if (document.activeElement !== bhEl) bhEl.value = d.bridge.host;
            const bpEl = document.getElementById('s-bridge-port');
            if (document.activeElement !== bpEl) bpEl.value = d.bridge.port;
            document.getElementById('s-bridge-url').textContent = d.bridge.url;
            // 运行地址 vs 保存地址
            const bootRow = document.getElementById('s-bridge-boot-row');
            const bootUrlEl = document.getElementById('s-bridge-boot-url');
            if (d.bridge.config_dirty && d.bridge.boot_config) {
                bootRow.style.display = 'flex';
                bootUrlEl.textContent = d.bridge.boot_config.url;
            } else {
                bootRow.style.display = 'none';
            }
            // 漂移提示
            document.getElementById('bridge-dirty-hint').classList.toggle('visible', !!d.bridge.config_dirty);
            const driftEl = document.getElementById('bridge-drift-details');
            if (d.bridge.config_dirty && d.bridge.drift_details && d.bridge.drift_details.length > 0) {
                driftEl.innerHTML = d.bridge.drift_details.join('<br>');
                driftEl.style.display = 'block';
            } else {
                driftEl.style.display = 'none';
            }
            // 重启按钮：仅 config_dirty 且 bridge 已启用时显示
            const restartRow = document.getElementById('bridge-restart-row');
            if (restartRow) restartRow.style.display = (d.bridge.config_dirty && d.bridge.enabled) ? 'block' : 'none';

            // Integrations — AstrBot
            const abStatusLabels = {
                'not_configured': '⚪ 未配置', 'configured_not_connected': '⏳ 已配置但未连接',
                'connected': '✅ 已连接', 'unknown': '❓ 状态未知'
            };
            const abData = d.integrations.astrbot || {};
            document.getElementById('s-int-astrbot-status').textContent = abData.label || abStatusLabels[abData.status] || abData.status || '—';
            const abDescRow = document.getElementById('s-int-astrbot-desc-row');
            const abDescEl = document.getElementById('s-int-astrbot-desc');
            if (abData.description) {
                abDescRow.style.display = 'flex'; abDescEl.textContent = abData.description;
            } else { abDescRow.style.display = 'none'; }
            const abBlockRow = document.getElementById('s-int-astrbot-blocker-row');
            const abBlockEl = document.getElementById('s-int-astrbot-blocker');
            if (abData.blockers && abData.blockers.length > 0) {
                abBlockRow.style.display = 'flex'; abBlockEl.textContent = abData.blockers.join('；');
            } else { abBlockRow.style.display = 'none'; }

            // Integrations — Hapi
            const hapiData = d.integrations.hapi || {};
            document.getElementById('s-int-hapi-status').textContent = hapiData.label || abStatusLabels[hapiData.status] || hapiData.status || '—';

            // App
            document.getElementById('s-app-version').textContent = 'v' + d.app.version;
            document.getElementById('s-app-loglevel').textContent = d.app.log_level;
            document.getElementById('s-tray-enabled').checked = d.app.tray_enabled;
            document.getElementById('s-app-minimized').textContent = d.app.start_minimized ? '是' : '否';
        } catch(e) {}
    }

    // 用 app_state 快照直接刷新设置面板和仪表盘（无需额外 API round-trip）
    function applyAppState(state) {
        if (!state) return;
        // 设置面板：显示模式下拉
        const modeEl = document.getElementById('s-display-mode');
        if (modeEl) modeEl.value = state.display_mode;
        if (state.mode_settings) {
            const bubbleSummary = document.getElementById('s-bubble-summary');
            const live2dSummary = document.getElementById('s-live2d-summary');
            if (bubbleSummary) bubbleSummary.textContent = state.mode_settings.bubble.summary;
            if (live2dSummary) live2dSummary.textContent = state.mode_settings.live2d.summary;
        }
        // 设置面板：Bridge
        if (state.bridge) {
            const bridgeStateLabels = {
                'disabled': '⛔ 已禁用', 'enabled_not_started': '⏳ 启动中',
                'running': '✅ 运行中', 'failed': '❌ 异常退出'
            };
            const bsEl = document.getElementById('s-bridge-state');
            if (bsEl) {
                const bs = state.bridge.state || state.bridge.running;
                bsEl.textContent = bridgeStateLabels[bs] || bs;
                bsEl.className = 'value' + (bs === 'running' ? ' ok' : bs === 'failed' ? ' warn' : '');
            }
            const beEl = document.getElementById('s-bridge-enabled');
            if (beEl) beEl.checked = state.bridge.enabled;
            const bhEl = document.getElementById('s-bridge-host');
            if (bhEl && document.activeElement !== bhEl) bhEl.value = state.bridge.host;
            const bpEl = document.getElementById('s-bridge-port');
            if (bpEl && document.activeElement !== bpEl) bpEl.value = state.bridge.port;
            const buEl = document.getElementById('s-bridge-url');
            if (buEl) buEl.textContent = state.bridge.url;
            // 运行地址 vs 保存地址
            const bootRow = document.getElementById('s-bridge-boot-row');
            const bootUrlEl = document.getElementById('s-bridge-boot-url');
            if (bootRow && bootUrlEl) {
                if (state.bridge.config_dirty && state.bridge.boot_config) {
                    bootRow.style.display = 'flex';
                    bootUrlEl.textContent = state.bridge.boot_config.url;
                } else { bootRow.style.display = 'none'; }
            }
            // 漂移提示 + 差异明细
            const dirtyEl = document.getElementById('bridge-dirty-hint');
            if (dirtyEl) dirtyEl.classList.toggle('visible', !!state.bridge.config_dirty);
            const driftEl = document.getElementById('bridge-drift-details');
            if (driftEl) {
                if (state.bridge.config_dirty && state.bridge.drift_details && state.bridge.drift_details.length > 0) {
                    driftEl.innerHTML = state.bridge.drift_details.join('<br>');
                    driftEl.style.display = 'block';
                } else { driftEl.style.display = 'none'; }
            }
            // 重启按钮
            const restartRow = document.getElementById('bridge-restart-row');
            if (restartRow) restartRow.style.display = (state.bridge.config_dirty && state.bridge.enabled) ? 'block' : 'none';
        }
        // 设置面板：托盘
        const trayEl = document.getElementById('s-tray-enabled');
        if (trayEl) trayEl.checked = !!state.tray_enabled;

        // 仪表盘：Bridge 状态卡
        if (state.bridge) {
            const bridgeLabels = {
                'disabled': '⛔ 已禁用', 'enabled_not_started': '⏳ 启动中',
                'running': '✅ 运行中', 'failed': '❌ 异常退出'
            };
            const brState = state.bridge.running || state.bridge.state;
            const brEl = document.getElementById('bridge-enabled');
            if (brEl) {
                brEl.textContent = bridgeLabels[brState] || brState;
                brEl.className = 'value ' + (brState === 'running' ? 'ok' : brState === 'failed' ? 'warn' : '');
            }
            const baEl = document.getElementById('bridge-addr');
            if (baEl) baEl.textContent = brState !== 'disabled' ? state.bridge.url : '—';
        }

        // 仪表盘：集成服务卡
        if (state.integrations) {
            const abData = state.integrations.astrbot || {};
            const abEl = document.getElementById('int-astrbot');
            if (abEl) abEl.textContent = abData.label || '—';
            const abDescRow = document.getElementById('int-astrbot-desc-row');
            const abDescEl = document.getElementById('int-astrbot-desc');
            if (abDescRow && abDescEl && abData.description) {
                abDescRow.style.display = 'flex'; abDescEl.textContent = abData.description;
            } else if (abDescRow) { abDescRow.style.display = 'none'; }
            const abBlockRow = document.getElementById('int-astrbot-blocker-row');
            const abBlockEl = document.getElementById('int-astrbot-blocker');
            if (abBlockRow && abBlockEl && abData.blockers && abData.blockers.length > 0) {
                abBlockRow.style.display = 'flex'; abBlockEl.textContent = abData.blockers.join('；');
            } else if (abBlockRow) { abBlockRow.style.display = 'none'; }

            const hapiData = state.integrations.hapi || {};
            const hapiEl = document.getElementById('int-hapi');
            if (hapiEl) hapiEl.textContent = hapiData.label || '—';
        }
    }

    function showEffectHints(effects) {
        const box = document.getElementById('effect-hints');
        if (!box || !effects || !effects.effects) { if (box) box.classList.remove('visible'); return; }
        const iconMap = {
            'immediate': ['✓', 'effect-hint-immediate'],
            'requires_mode_restart': ['🔄', 'effect-hint-mode'],
            'requires_bridge_restart': ['🔌', 'effect-hint-bridge'],
            'requires_app_restart': ['⚡', 'effect-hint-app'],
        };
        let html = '';
        for (const e of effects.effects) {
            const [icon, cls] = iconMap[e.effect] || ['•', ''];
            html += '<div class="effect-hint-row ' + cls + '"><span class="icon">' + icon + '</span><span>' + e.message + '</span></div>';
        }
        box.innerHTML = html;
        box.classList.add('visible');
        setTimeout(function() { box.classList.remove('visible'); }, 5000);
    }

    async function onSettingChange(key, value) {
        const hint = document.getElementById('save-hint');
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const changes = {};
            changes[key] = value;
            const res = await window.pywebview.api.update_settings(changes);
            if (res.ok) {
                hint.textContent = res.restart_scheduled ? '✓ 已保存，正在重启应用…' : '✓ 已保存';
                hint.className = 'save-hint ok';
                if (res.app_state) {
                    applyAppState(res.app_state);
                    if (key === 'display_mode' && !res.restart_scheduled) {
                        refreshSettings();
                    }
                } else {
                    refreshSettings();
                }
                showEffectHints(res.effects);
            } else {
                const errMsg = res.error || (Array.isArray(res.errors) ? res.errors.join('; ') : '保存失败');
                hint.textContent = '✗ ' + errMsg;
                hint.className = 'save-hint err';
            }
        } catch(e) {
            hint.textContent = '✗ 保存失败';
            hint.className = 'save-hint err';
        }
        setTimeout(function(){ hint.textContent = ''; hint.className = 'save-hint'; }, 3000);
    }

    async function restartBridge() {
        const btn = document.getElementById('bridge-restart-btn');
        const msg = document.getElementById('bridge-restart-msg');
        if (btn) { btn.disabled = true; btn.textContent = '⏳ 重启中…'; }
        if (msg) { msg.textContent = ''; msg.style.color = ''; }
        try {
            const result = await window.pywebview.api.restart_bridge();
            if (result.ok) {
                if (msg) { msg.textContent = '✅ Bridge 已重启'; msg.style.color = '#66bb6a'; }
                if (result.app_state) applyAppState(result.app_state);
                refreshDashboard();
                // 稍后隐藏重启行（因为 config_dirty 应该已消除）
                setTimeout(function(){
                    const row = document.getElementById('bridge-restart-row');
                    if (row) row.style.display = 'none';
                    if (msg) msg.textContent = '';
                }, 2000);
            } else {
                if (msg) { msg.textContent = '❌ ' + (result.error || '重启失败'); msg.style.color = '#ef5350'; }
            }
        } catch(e) {
            if (msg) { msg.textContent = '❌ 操作异常'; msg.style.color = '#ef5350'; }
        }
        if (btn) { btn.disabled = false; btn.textContent = '🔄 应用配置并重启 Bridge'; }
    }

    async function refreshDashboard() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const data = await window.pywebview.api.get_dashboard_data();
            if (data.error) return;

            // Hermes Agent — 按 readiness_level 分级显示
            const hs = document.getElementById('hermes-status');
            const rl = data.hermes.readiness_level;
            if (rl === 'full_ready') {
                hs.textContent = '✅ 完整就绪';
                hs.className = 'value ok';
            } else if (rl === 'basic_ready') {
                hs.textContent = '⚠️ 基础可用 · 部分工具受限';
                hs.className = 'value warn';
            } else if (data.hermes.ready) {
                hs.textContent = '✅ 已就绪';
                hs.className = 'value ok';
            } else {
                hs.textContent = '⚠️ ' + data.hermes.status;
                hs.className = 'value warn';
            }
            document.getElementById('hermes-version').textContent = data.hermes.version || '未知';
            document.getElementById('hermes-platform').textContent = data.hermes.platform;
            renderHermesLimited('hermes-limited-row', 'hermes-limited', data.hermes, false);
            renderHermesDiagnostics('hermes-doctor-row', 'hermes-doctor', data.hermes);
            // 补全能力入口：doctor 发现问题或受限工具时显示
            const enhRow = document.getElementById('hermes-enhance-row');
            if (enhRow) enhRow.style.display = shouldShowHermesEnhance(data.hermes) ? 'block' : 'none';
            maybeAutoRecheckHermes(data.hermes);

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
            const bridgeLabels = {
                'disabled': '⛔ 已禁用',
                'enabled_not_started': '⏳ 启动中',
                'running': '✅ 运行中',
                'failed': '❌ 异常退出'
            };
            const brEl = document.getElementById('bridge-enabled');
            brEl.textContent = bridgeLabels[data.bridge.running] || data.bridge.running;
            brEl.className = 'value ' + (data.bridge.running === 'running' ? 'ok' : data.bridge.running === 'failed' ? 'warn' : '');
            document.getElementById('bridge-addr').textContent = data.bridge.running !== 'disabled' ? data.bridge.url : '—';

            // Tasks
            document.getElementById('task-pending').textContent = data.tasks.pending || 0;
            document.getElementById('task-running').textContent = data.tasks.running || 0;
            document.getElementById('task-completed').textContent = data.tasks.completed || 0;

            // Display modes
            const currentMode = (data.modes && data.modes.current) || 'bubble';
            ['bubble', 'live2d'].forEach(function(modeId) {
                const el = document.getElementById('action-' + modeId);
                if (el) el.classList.toggle('active', currentMode === modeId && !settingsOpen);
            });

            // Chat overview
            const chat = data.chat || {};
            const statusEl = document.getElementById('chat-status');
            if (statusEl) {
                statusEl.textContent = chat.status_label
                    ? ('当前会话：' + chat.status_label)
                    : '当前会话状态未知';
            }
            const summaryList = document.getElementById('chat-summary-list');
            if (summaryList) {
                if (chat.empty || !chat.messages || chat.messages.length === 0) {
                    summaryList.innerHTML = '<div class="empty-state">暂无消息。打开聊天窗口开始完整对话。</div>';
                } else {
                    summaryList.innerHTML = chat.messages.map(function(msg) {
                        const statusClass = msg.status ? ' ' + msg.status : '';
                        return '<div class="recent-msg ' + msg.role + statusClass + '">' + escapeHtml(msg.content || '…') + '</div>';
                    }).join('');
                }
            }
            const sessionList = document.getElementById('chat-session-list');
            if (sessionList) {
                const sessions = chat.recent_sessions || [];
                sessionList.innerHTML = sessions.map(function(session) {
                    const current = session.is_current ? ' current' : '';
                    return '<span class="session-pill' + current + '">' + escapeHtml(session.title) + '</span>';
                }).join('');
            }

            // Integrations
            const abData = data.integrations.astrbot || {};
            const abEl = document.getElementById('int-astrbot');
            abEl.textContent = abData.label || '—';
            abEl.className = 'value' + (abData.status === 'connected' ? ' ok' : '');
            const abDescRow = document.getElementById('int-astrbot-desc-row');
            const abDescEl = document.getElementById('int-astrbot-desc');
            if (abDescRow && abDescEl && abData.description) {
                abDescRow.style.display = 'flex'; abDescEl.textContent = abData.description;
            } else if (abDescRow) { abDescRow.style.display = 'none'; }
            const abBlockRow = document.getElementById('int-astrbot-blocker-row');
            const abBlockEl = document.getElementById('int-astrbot-blocker');
            if (abBlockRow && abBlockEl && abData.blockers && abData.blockers.length > 0) {
                abBlockRow.style.display = 'flex'; abBlockEl.textContent = abData.blockers.join('；');
            } else if (abBlockRow) { abBlockRow.style.display = 'none'; }
            const hapiData = data.integrations.hapi || {};
            document.getElementById('int-hapi').textContent = hapiData.label || '—';
        } catch(e) {}
    }

    // 首次加载和定时刷新
    document.addEventListener('DOMContentLoaded', function() {
        // pywebview ready 后刷新数据
        if (window.pywebview) {
            refreshDashboard();
            loadExecutorInfo();
        }
        setInterval(refreshDashboard, 5000);
    });

    // pywebview ready 事件
    window.addEventListener('pywebviewready', function() {
        refreshDashboard();
        loadExecutorInfo();
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


def open_main_window(
    runtime: "HermesRuntime",
    config: "AppConfig",
    *,
    bind_exit: bool = False,
) -> bool:
    """在当前 webview 会话中打开主控台窗口。"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，无法打开主控台窗口")
        return False

    from apps.shell.main_api import MainWindowAPI
    api = MainWindowAPI(runtime, config)

    html = _STATUS_HTML.replace("{{HOST}}", config.bridge_host).replace("{{PORT}}", str(config.bridge_port))
    window_config = config.window_mode

    window = webview.create_window(
        title="Hermes-Yachiyo Control Center",
        html=html,
        width=window_config.width,
        height=window_config.height,
        resizable=True,
        js_api=api,
    )
    if bind_exit:
        _bind_main_window_exit(window)
    return True


def create_main_window(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """创建并显示主控台窗口（阻塞主线程）。"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，以无窗口模式运行")
        _print_console_dashboard(runtime, config)
        import threading
        threading.Event().wait()
        return

    open_main_window(runtime, config, bind_exit=True)
    if config.window_mode.open_chat_on_start:
        try:
            from apps.shell.chat_window import open_chat_window

            open_chat_window(runtime)
        except Exception as exc:
            logger.warning("启动时打开 Chat Window 失败: %s", exc)
    webview.start(debug=False)


def bind_app_window_exit(app_window: object, *, label: str = "窗口"):
    """应用主入口窗口关闭时同步关闭附属窗口。

    不在 pywebview closing 回调里弹确认框，避免 macOS WebView 关闭事件重入卡死。
    显式退出确认由页面内的 quitApp() 完成。
    """
    closing = False

    def _on_closing() -> bool:
        nonlocal closing
        if closing:
            return True

        closing = True
        logger.info("%s关闭，正在关闭附属窗口", label)
        _close_auxiliary_windows(app_window)
        return True

    app_window.events.closing += _on_closing
    return _on_closing


def _bind_main_window_exit(main_window: object):
    """主窗口关闭时同步关闭附属窗口。"""
    return bind_app_window_exit(main_window, label="主窗口")


def request_app_exit() -> None:
    """由页面内退出按钮触发的完整退出流程。

    实际窗口销毁延迟到 API 回调返回后执行，避免 macOS WebView 卡在等待
    JavaScript promise 返回的状态。若 pywebview 销毁阻塞，短延迟后直接退出进程，
    避免留下白屏窗口。
    """
    global _exit_timer, _force_exit_timer
    with _exit_timer_lock:
        if _exit_timer is not None and _exit_timer.is_alive():
            return
        _exit_timer = threading.Timer(_EXIT_DELAY_SECONDS, _destroy_all_windows_for_exit)
        _exit_timer.daemon = True
        _exit_timer.start()
        _force_exit_timer = threading.Timer(_EXIT_FORCE_DELAY_SECONDS, _force_app_exit)
        _force_exit_timer.daemon = True
        _force_exit_timer.start()


def request_app_restart() -> None:
    """延迟重启应用，确保 WebView API 调用可以先正常返回。"""
    global _restart_timer
    with _restart_timer_lock:
        if _restart_timer is not None and _restart_timer.is_alive():
            return
        _restart_timer = threading.Timer(_RESTART_DELAY_SECONDS, _restart_process)
        _restart_timer.daemon = True
        _restart_timer.start()


def _restart_process() -> None:
    """启动新进程并退出当前进程。"""
    import os
    import subprocess
    import sys

    logger.info("正在重启 Hermes-Yachiyo 以应用显示模式变更")
    try:
        subprocess.Popen(
            [sys.executable] + sys.argv,
            close_fds=True,
            start_new_session=True,
        )
        logger.info("新进程已启动（%s %s）", sys.executable, sys.argv)
    except Exception as exc:
        logger.warning("自动重启失败，请手动重启应用: %s", exc)
    finally:
        os._exit(0)


def _process_exit(code: int = 0) -> None:
    """立即结束当前进程。封装为函数以便测试替换。"""
    import os

    os._exit(code)


def _force_app_exit() -> None:
    """兜底退出，防止 pywebview 窗口销毁在平台侧卡住。"""
    logger.info("强制退出 Hermes-Yachiyo")
    _process_exit(0)


def _destroy_all_windows_for_exit() -> None:
    """关闭聊天窗口及所有 pywebview 窗口。"""
    _close_auxiliary_windows(main_window=None)

    webview_module = globals().get("webview")
    if webview_module is None:
        return

    for window in list(getattr(webview_module, "windows", []) or []):
        try:
            window.destroy()
        except Exception as exc:
            logger.debug("关闭窗口失败: %s", exc)


def _close_auxiliary_windows(main_window: object | None) -> None:
    """关闭聊天窗口及其他非主窗口的 pywebview 窗口。"""
    try:
        from apps.shell.chat_window import close_chat_window
        close_chat_window()
    except Exception as exc:
        logger.warning("关闭聊天窗口时发生异常: %s", exc)

    webview_module = globals().get("webview")
    if webview_module is None:
        return

    if main_window is None:
        return

    for window in list(getattr(webview_module, "windows", []) or []):
        if window is main_window:
            continue
        try:
            window.destroy()
        except Exception as exc:
            logger.debug("关闭附属窗口失败: %s", exc)


def create_installer_window(install_info: "HermesInstallInfo", config: "AppConfig") -> None:
    """创建并显示安装引导/初始化向导窗口（阻塞主线程）"""
    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，显示控制台安装信息")
        _print_console_install_info(install_info)
        # 无窗口模式下保持主线程活跃
        import threading

        threading.Event().wait()
        return

    html = _generate_installer_html(install_info)

    # 始终提供 API：安装按钮和初始化按钮都依赖 pywebview.api
    from apps.shell.installer_api import InstallerWebViewAPI
    api = InstallerWebViewAPI()

    is_init_mode = install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED
    is_setup_mode = install_info.status in (
        HermesInstallStatus.INSTALLED_NEEDS_SETUP,
        HermesInstallStatus.SETUP_IN_PROGRESS,
    )
    if is_init_mode:
        window_title = "Hermes-Yachiyo - 初始化工作空间"
    elif is_setup_mode:
        window_title = "Hermes-Yachiyo - 配置 Hermes Agent"
    else:
        window_title = "Hermes-Yachiyo - 安装 Hermes Agent"

    webview.create_window(
        title=window_title,
        html=html,
        width=800,
        height=600,
        resizable=True,
        js_api=api,
    )
    webview.start(debug=False)


def _generate_installer_html(install_info: "HermesInstallInfo") -> str:
    """生成安装引导页面的 HTML 内容"""
    from apps.installer.hermes_install import HermesInstallGuide
    from packages.protocol.enums import HermesInstallStatus

    # 获取安装指导
    guidance = HermesInstallGuide.get_install_instructions(install_info)
    
    # 状态样式和消息
    status_mapping = {
        HermesInstallStatus.NOT_INSTALLED: ("warning", "Hermes Agent 未安装"),
        HermesInstallStatus.INSTALLED_NEEDS_SETUP: ("info", "Hermes Agent 已安装，需要完成初始配置"),
        HermesInstallStatus.SETUP_IN_PROGRESS: ("info", "Hermes Agent 配置中，请在终端中完成配置"),
        HermesInstallStatus.INSTALLED_NOT_INITIALIZED: ("info", "Hermes Agent 已安装，需要初始化 Yachiyo 工作空间"),
        HermesInstallStatus.INITIALIZING: ("info", "正在初始化 Yachiyo 工作空间..."),
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
    if install_info.status == HermesInstallStatus.INSTALLED_NEEDS_SETUP:
        main_title = "配置 Hermes Agent"
        steps_title = "配置说明："
    elif install_info.status == HermesInstallStatus.SETUP_IN_PROGRESS:
        main_title = "配置 Hermes Agent"
        steps_title = "配置进行中："
    elif install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED:
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
    
    # 安装按钮区域（NOT_INSTALLED 状态）
    install_section = ""
    if install_info.status == HermesInstallStatus.NOT_INSTALLED:
        install_section = """
        <div class="init-section">
            <h3>🚀 一键安装 Hermes Agent</h3>
            <p>点击下方按钮，系统将自动运行官方安装脚本。<br>
               需要网络连接，网络较慢时最多会等待 15 分钟。</p>
            <button class="init-button" id="install-btn" onclick="startInstall()">安装 Hermes Agent</button>
            <div id="install-progress" style="display:none; margin-top:12px;">
                <div style="color:#6495ed; margin-bottom:6px;">⏳ 安装中，请稍候...</div>
                <pre id="install-log" style="background:#111;padding:10px;border-radius:6px;
                     max-height:200px;overflow-y:auto;font-size:11px;color:#aaa;white-space:pre-wrap;"></pre>
            </div>
            <div id="install-result" style="margin-top:10px;"></div>
        </div>
        <script>
        let _pollTimer = null;

        async function startInstall() {
            const btn = document.getElementById('install-btn');
            const progress = document.getElementById('install-progress');
            const result = document.getElementById('install-result');
            btn.disabled = true;
            btn.textContent = '安装中...';
            progress.style.display = 'block';
            result.textContent = '';

            try {
                if (!window.pywebview || !window.pywebview.api) {
                    throw new Error('WebView API 不可用');
                }
                const resp = await window.pywebview.api.install_hermes();
                if (!resp.started) {
                    throw new Error(resp.error || '无法启动安装');
                }
                // 开始轮询进度
                _pollTimer = setInterval(pollProgress, 1500);
            } catch (err) {
                btn.disabled = false;
                btn.textContent = '重新安装';
                result.innerHTML = '<span style="color:#ff6b6b">❌ ' + err.message + '</span>';
            }
        }

        let _setupTerminalOpened = false;  // 防止重复打开终端

        async function pollProgress() {
            try {
                const p = await window.pywebview.api.get_install_progress();
                const log = document.getElementById('install-log');
                if (p.lines && p.lines.length > 0) {
                    log.textContent = p.lines.join('\\n');
                    log.scrollTop = log.scrollHeight;
                }

                // 检测到 setup TUI，自动打开终端（只执行一次）
                if (p.setup_triggered && !_setupTerminalOpened) {
                    _setupTerminalOpened = true;
                    // 自动打开终端
                    try {
                        await window.pywebview.api.open_hermes_setup_terminal();
                    } catch (e) {
                        // 打开失败也继续，显示手动提示
                    }
                    // 显示配置引导 UI（含重新检测按钮）
                    showSetupWaitingUI();
                }

                if (!p.running) {
                    clearInterval(_pollTimer);
                    _pollTimer = null;
                    // 如果之前触发了 setup，现在安装进程结束了，也显示重检按钮
                    if (_setupTerminalOpened) {
                        showSetupWaitingUI();
                    } else if (p.success) {
                        await recheckAfterInstall();
                    } else {
                        const btn = document.getElementById('install-btn');
                        const result = document.getElementById('install-result');
                        btn.disabled = false;
                        btn.textContent = '重新安装';
                        result.innerHTML = '<span style="color:#ff6b6b">❌ 安装失败：' + (p.message || '未知错误') + '</span>';
                    }
                }
            } catch (err) {
                // 轮询异常，继续等待
            }
        }

        function showSetupWaitingUI() {
            // 隐藏安装按钮，显示配置引导
            const installBtn = document.getElementById('install-btn');
            if (installBtn) installBtn.style.display = 'none';

            const result = document.getElementById('install-result');
            result.innerHTML = `
                <div style="padding:16px; background:#1a2a3a; border-radius:8px; border-left:4px solid #ffd700;">
                    <div style="color:#ffd700; font-size:1.05em; margin-bottom:8px;">⚙️ 请在终端中完成 Hermes 配置</div>
                    <div style="color:#ccc; margin-bottom:12px;">
                        配置向导已在新的终端窗口中打开。<br>
                        <span style="color:#aaa; font-size:0.9em;">完成后点击下方按钮继续。</span>
                    </div>
                    <div style="display:flex; gap:12px; flex-wrap:wrap;">
                        <button onclick="recheckAfterSetupFromInstall()"
                                id="setup-recheck-btn"
                                style="padding:10px 20px; background:#2d5a2d; border:1px solid #4a8a4a;
                                       color:#90ee90; border-radius:6px; cursor:pointer; font-size:0.95em;">
                            ✅ 我已完成配置，继续
                        </button>
                        <button onclick="reopenSetupTerminal()"
                                style="padding:10px 16px; background:#2a2a4a; border:1px solid #6495ed;
                                       color:#6495ed; border-radius:6px; cursor:pointer; font-size:0.9em;">
                            🔄 重新打开终端
                        </button>
                    </div>
                </div>`;
        }

        async function reopenSetupTerminal() {
            try {
                await window.pywebview.api.open_hermes_setup_terminal();
            } catch (e) {
                alert('无法打开终端，请手动运行：hermes setup');
            }
        }

        async function recheckAfterSetupFromInstall() {
            const btn = document.getElementById('setup-recheck-btn');
            if (btn) { btn.disabled = true; btn.textContent = '检测中...'; }

            try {
                const s = await window.pywebview.api.recheck_status();
                const result = document.getElementById('install-result');

                if (s.ready) {
                    result.innerHTML = '<span style="color:#90ee90">✅ 配置完成！正在进入主界面...</span>';
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                } else if (s.needs_init) {
                    result.innerHTML = '<span style="color:#ffd700">✅ Hermes 已配置，正在进入工作空间初始化...</span>';
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                } else if (s.status === 'installed_needs_setup' || s.status === 'setup_in_progress') {
                    if (btn) { btn.disabled = false; btn.textContent = '✅ 我已完成配置，继续'; }
                    result.innerHTML = `
                        <div style="padding:16px; background:#3a2a1a; border-radius:8px; border-left:4px solid #ffd700;">
                            <div style="color:#ffd700; margin-bottom:8px;">⚠️ Hermes 配置尚未完成</div>
                            <div style="color:#ccc; margin-bottom:12px;">
                                请确认已在终端中完成 <code>hermes setup</code>，然后再次点击「继续」。
                            </div>
                            <div style="display:flex; gap:12px; flex-wrap:wrap;">
                                <button onclick="recheckAfterSetupFromInstall()"
                                        id="setup-recheck-btn"
                                        style="padding:10px 20px; background:#2d5a2d; border:1px solid #4a8a4a;
                                               color:#90ee90; border-radius:6px; cursor:pointer; font-size:0.95em;">
                                    ✅ 我已完成配置，继续
                                </button>
                                <button onclick="reopenSetupTerminal()"
                                        style="padding:10px 16px; background:#2a2a4a; border:1px solid #6495ed;
                                               color:#6495ed; border-radius:6px; cursor:pointer; font-size:0.9em;">
                                    🔄 重新打开终端
                                </button>
                            </div>
                        </div>`;
                } else {
                    if (btn) { btn.disabled = false; btn.textContent = '✅ 我已完成配置，继续'; }
                    result.innerHTML =
                        '<span style="color:#ff6b6b">⚠️ 检测异常：' + s.status +
                        (s.message ? '（' + s.message + '）' : '') + '</span>';
                }
            } catch (err) {
                if (btn) { btn.disabled = false; btn.textContent = '✅ 我已完成配置，继续'; }
                const result = document.getElementById('install-result');
                result.innerHTML = '<span style="color:#ff6b6b">⚠️ 检测失败：' + err.message + '</span>';
            }
        }

        async function recheckAfterInstall() {
            const result = document.getElementById('install-result');
            result.innerHTML = '<span style="color:#6495ed">⏳ 正在验证安装结果...</span>';
            try {
                const s = await window.pywebview.api.recheck_status();

                // needs_env_refresh 仅作提示：应用内 PATH 已修复，但用户 Shell 仍需手动 reload
                const shellNote = s.needs_env_refresh
                    ? '<br><span style="color:#888;font-size:0.88em">提示：打开新终端或执行 source ~/.bashrc 后，Shell 中也可直接使用 hermes 命令</span>'
                    : '';

                if (s.ready) {
                    result.innerHTML = '<span style="color:#90ee90">✅ 安装成功！正在进入主界面...</span>' + shellNote;
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                } else if (s.needs_init) {
                    result.innerHTML = '<span style="color:#ffd700">✅ Hermes 已安装，正在进入初始化向导...</span>' + shellNote;
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                } else if (s.status === 'installed_needs_setup' || s.status === 'setup_in_progress') {
                    // 安装成功，但 hermes setup 尚未完成
                    // 不重启——直接在当前页面渲染配置引导 UI，避免用户混淆
                    showPostInstallSetupUI(shellNote);
                } else if (s.needs_env_refresh) {
                    // PATH 已注入但完整检测仍未通过（版本不兼容等边缘情况）
                    // 重启后用刷新后的环境重新走完整检测流程
                    result.innerHTML =
                        '<span style="color:#ffd700">✅ Hermes 安装完成，正在重启以完成初始化...</span>' +
                        (s.message ? '<br><span style="color:#aaa">' + s.message + '</span>' : '');
                    setTimeout(() => window.pywebview.api.restart_app(), 2000);
                } else {
                    result.innerHTML =
                        '<span style="color:#ff6b6b">⚠️ 安装后检测异常：' + s.status +
                        (s.message ? '（' + s.message + '）' : '') + '</span>';
                    document.getElementById('install-btn').disabled = false;
                    document.getElementById('install-btn').textContent = '重新安装';
                }
            } catch (err) {
                result.innerHTML = '<span style="color:#ff6b6b">⚠️ 无法重新检测状态：' + err.message + '</span>';
            }
        }

        // 安装成功后检测到 installed_needs_setup / setup_in_progress 时，
        // 在当前页面内直接渲染配置引导区块，不重启应用。
        function showPostInstallSetupUI(shellNote) {
            // 隐藏安装进度区域和安装按钮，只保留配置引导
            const progress = document.getElementById('install-progress');
            const installBtn = document.getElementById('install-btn');
            if (progress) progress.style.display = 'none';
            if (installBtn) installBtn.style.display = 'none';

            const result = document.getElementById('install-result');
            result.innerHTML = `
                <div style="padding:20px; background:#1a2a1a; border-radius:8px; border-left:4px solid #90ee90; margin-bottom:12px;">
                    <div style="color:#90ee90; font-size:1.05em; margin-bottom:8px;">✅ Hermes 已成功安装</div>
                    <div style="color:#ccc; margin-bottom:16px;">
                        现在需要完成初次配置，让 Hermes 了解您的偏好与工具设置。<br>
                        <span style="color:#aaa; font-size:0.9em;">配置过程在独立终端中进行，完成后回到此窗口点击「重新检测」。</span>
                    </div>
                    ${shellNote || ''}
                    <div style="display:flex; gap:12px; flex-wrap:wrap; margin-top:12px;">
                        <button onclick="openPostInstallSetup()"
                                id="post-install-setup-btn"
                                style="padding:10px 20px; background:#2d5a2d; border:1px solid #4a8a4a;
                                       color:#90ee90; border-radius:6px; cursor:pointer; font-size:0.95em;">
                            ▶ 开始配置 Hermes
                        </button>
                        <button onclick="recheckAfterPostInstallSetup()"
                                id="post-install-recheck-btn"
                                style="padding:10px 20px; background:#2a2a4a; border:1px solid #6495ed;
                                       color:#6495ed; border-radius:6px; cursor:pointer; font-size:0.95em;">
                            🔄 已完成配置，重新检测
                        </button>
                    </div>
                    <div id="post-install-hint" style="margin-top:12px;"></div>
                </div>`;
        }

        async function openPostInstallSetup() {
            const btn = document.getElementById('post-install-setup-btn');
            const hint = document.getElementById('post-install-hint');
            if (btn) { btn.disabled = true; btn.textContent = '正在打开终端...'; }
            if (hint) hint.innerHTML = '';

            try {
                if (!window.pywebview || !window.pywebview.api) {
                    throw new Error('WebView API 不可用');
                }
                const resp = await window.pywebview.api.open_hermes_setup_terminal();
                if (resp && resp.success) {
                    if (hint) hint.innerHTML =
                        '<span style="color:#90ee90">✅ 终端已打开，请在终端中完成 Hermes 配置。</span><br>' +
                        '<span style="color:#aaa; font-size:0.88em;">完成后点击「已完成配置，重新检测」按钮继续。</span>';
                    if (btn) btn.style.display = 'none';
                } else {
                    throw new Error((resp && resp.error) || '无法打开终端');
                }
            } catch (err) {
                if (btn) { btn.disabled = false; btn.textContent = '▶ 开始配置 Hermes'; }
                if (hint) hint.innerHTML =
                    '<span style="color:#ff6b6b">❌ ' + err.message + '</span><br>' +
                    '<span style="color:#aaa; font-size:0.88em;">您也可以手动打开终端并运行：hermes setup</span>';
            }
        }

        async function recheckAfterPostInstallSetup() {
            const btn = document.getElementById('post-install-recheck-btn');
            const hint = document.getElementById('post-install-hint');
            if (btn) { btn.disabled = true; btn.textContent = '检测中...'; }
            if (hint) hint.innerHTML = '<span style="color:#6495ed">⏳ 正在检测 Hermes 配置状态...</span>';

            try {
                const s = await window.pywebview.api.recheck_status();
                if (s.ready) {
                    if (hint) hint.innerHTML = '<span style="color:#90ee90">✅ 配置完成！正在进入主界面...</span>';
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                } else if (s.needs_init) {
                    if (hint) hint.innerHTML = '<span style="color:#ffd700">✅ Hermes 配置完成，正在进入工作空间初始化...</span>';
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                } else if (s.status === 'installed_needs_setup' || s.status === 'setup_in_progress') {
                    if (btn) { btn.disabled = false; btn.textContent = '🔄 已完成配置，重新检测'; }
                    if (hint) hint.innerHTML =
                        '<span style="color:#ffd700">⚠️ Hermes 配置尚未完成。</span><br>' +
                        '<span style="color:#aaa; font-size:0.88em;">请确认已在终端中完成 hermes setup，然后再次点击「重新检测」。</span>';
                } else {
                    if (btn) { btn.disabled = false; btn.textContent = '🔄 已完成配置，重新检测'; }
                    if (hint) hint.innerHTML =
                        '<span style="color:#ff6b6b">⚠️ 检测异常：' + s.status +
                        (s.message ? '（' + s.message + '）' : '') + '</span>';
                }
            } catch (err) {
                if (btn) { btn.disabled = false; btn.textContent = '🔄 已完成配置，重新检测'; }
                if (hint) hint.innerHTML = '<span style="color:#ff6b6b">⚠️ 检测失败：' + err.message + '</span>';
            }
        }
        </script>
        """

    # 初始化按钮区域（INSTALLED_NOT_INITIALIZED 状态）
    init_section = ""

    # setup 引导区域（INSTALLED_NEEDS_SETUP 或 SETUP_IN_PROGRESS 状态）
    if install_info.status in (
        HermesInstallStatus.INSTALLED_NEEDS_SETUP,
        HermesInstallStatus.SETUP_IN_PROGRESS,
    ):
        is_already_running = install_info.status == HermesInstallStatus.SETUP_IN_PROGRESS
        initial_display_setup = "none" if is_already_running else "inline-block"
        initial_display_running = "block" if is_already_running else "none"
        initial_btn_disabled = "disabled" if is_already_running else ""
        init_section = f"""
        <div class="init-section">
            <h3>⚙️ 配置 Hermes Agent</h3>
            <p>Hermes Agent 已成功安装，但需要完成初始配置才能正常使用。<br>
               点击下方按钮将自动打开终端，运行 <code>hermes setup</code> 交互式配置向导。</p>
            <p style="color:#888;font-size:0.88em;margin-top:8px;">
                配置过程需要在终端中完成。完成后请回到此窗口点击「重新检测」。</p>
            <div style="display:flex; gap:12px; margin-top:16px; flex-wrap:wrap;">
                <button class="init-button" id="setup-btn" onclick="openSetupTerminal()"
                        style="margin:0; display:{initial_display_setup};" {initial_btn_disabled}>
                    开始配置 Hermes
                </button>
                <button class="init-button" id="recheck-btn" onclick="recheckAfterSetup()"
                        style="margin:0; background:#3a3a6a; border:1px solid #6495ed;">
                    我已完成配置，重新检测
                </button>
            </div>
            <div id="setup-running-hint" style="display:{initial_display_running};
                 margin-top:12px; padding:10px; background:#1e3a1e; border-radius:6px; border-left:3px solid #90ee90;">
                <span style="color:#90ee90;">⏳ 配置终端已打开，请在终端中完成 Hermes 配置。</span><br>
                <span style="color:#888;font-size:0.88em;">完成后回到此窗口，点击「我已完成配置，重新检测」按钮继续。</span>
            </div>
            <div id="setup-status" style="margin-top:12px;"></div>
        </div>
        <script>
        let _setupPollTimer = null;

        async function openSetupTerminal() {{
            const btn = document.getElementById('setup-btn');
            const status = document.getElementById('setup-status');
            const hint = document.getElementById('setup-running-hint');
            btn.disabled = true;
            btn.textContent = '正在打开终端...';
            status.innerHTML = '';

            try {{
                if (!window.pywebview || !window.pywebview.api) {{
                    throw new Error('WebView API 不可用');
                }}
                const resp = await window.pywebview.api.open_hermes_setup_terminal();
                if (resp.success) {{
                    if (resp.already_running) {{
                        btn.style.display = 'none';
                        hint.style.display = 'block';
                        hint.innerHTML =
                            '<span style="color:#ffd700;">⚠️ 配置终端已打开，请勿重复启动。</span><br>' +
                            '<span style="color:#888;font-size:0.88em;">请在已打开的终端中完成 Hermes 配置，然后点击「重新检测」。</span>';
                    }} else {{
                        btn.style.display = 'none';
                        hint.style.display = 'block';
                        startSetupPolling();
                    }}
                }} else {{
                    throw new Error(resp.error || '无法打开终端');
                }}
            }} catch (err) {{
                btn.disabled = false;
                btn.textContent = '开始配置 Hermes';
                btn.style.display = 'inline-block';
                status.innerHTML =
                    '<span style="color:#ff6b6b">❌ ' + err.message + '</span>' +
                    '<br><span style="color:#888;font-size:0.88em;">您也可以手动打开终端并运行 hermes setup</span>';
            }}
        }}

        function startSetupPolling() {{
            // 每 3 秒检测 setup 进程是否仍在运行
            if (_setupPollTimer) return;
            _setupPollTimer = setInterval(async function() {{
                try {{
                    const p = await window.pywebview.api.check_setup_process();
                    const hint = document.getElementById('setup-running-hint');
                    const btn = document.getElementById('setup-btn');
                    if (!p.running) {{
                        // setup 进程结束，更新 UI
                        clearInterval(_setupPollTimer);
                        _setupPollTimer = null;
                        hint.innerHTML =
                            '<span style="color:#ffd700;">💡 配置终端已关闭。</span><br>' +
                            '<span style="color:#888;font-size:0.88em;">如果已完成配置，请点击「重新检测」；如需重新配置，可再次点击下方按钮。</span>';
                        btn.disabled = false;
                        btn.textContent = '重新打开配置终端';
                        btn.style.display = 'inline-block';
                    }}
                }} catch(e) {{}}
            }}, 3000);
        }}

        async function recheckAfterSetup() {{
            const btn = document.getElementById('recheck-btn');
            const status = document.getElementById('setup-status');
            btn.disabled = true;
            btn.textContent = '检测中...';
            status.innerHTML = '<span style="color:#6495ed">⏳ 正在检测 Hermes 配置状态...</span>';

            try {{
                const s = await window.pywebview.api.recheck_status();
                if (s.ready) {{
                    status.innerHTML = '<span style="color:#90ee90">✅ 配置完成！正在进入主界面...</span>';
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                }} else if (s.needs_init) {{
                    status.innerHTML = '<span style="color:#ffd700">✅ Hermes 配置完成，正在进入工作空间初始化...</span>';
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                }} else if (s.status === 'installed_needs_setup' || s.status === 'setup_in_progress') {{
                    btn.disabled = false;
                    btn.textContent = '我已完成配置，重新检测';
                    status.innerHTML =
                        '<span style="color:#ffd700">⚠️ Hermes 配置尚未完成。</span>' +
                        '<br><span style="color:#888;">请确认已在终端中完成 hermes setup，然后再次点击「重新检测」。</span>';
                }} else {{
                    btn.disabled = false;
                    btn.textContent = '我已完成配置，重新检测';
                    status.innerHTML =
                        '<span style="color:#ff6b6b">⚠️ 检测异常：' + s.status +
                        (s.message ? '（' + s.message + '）' : '') + '</span>';
                }}
            }} catch (err) {{
                btn.disabled = false;
                btn.textContent = '我已完成配置，重新检测';
                status.innerHTML = '<span style="color:#ff6b6b">❌ 检测失败：' + err.message + '</span>';
            }}
        }}

        // 如果页面加载时 setup 已在运行，立即开始轮询
        document.addEventListener('DOMContentLoaded', function() {{
            const hint = document.getElementById('setup-running-hint');
            if (hint && hint.style.display !== 'none') {{
                startSetupPolling();
            }}
        }});
        </script>
        """

    elif install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED and guidance.get("can_initialize", False):
        init_section = """
        <div class="init-section">
            <h3>🚀 快速初始化</h3>
            <p>点击下方按钮，系统将自动创建 Yachiyo 工作空间（目录结构 + 默认配置）。<br>
               初始化完成后会自动进入主界面。</p>
            <button class="init-button" id="init-btn" onclick="initializeWorkspace()">初始化工作空间</button>
            <div id="init-progress" style="display:none; margin-top:12px;">
                <pre id="init-log" style="background:#111;padding:10px;border-radius:6px;
                     max-height:150px;overflow-y:auto;font-size:11px;color:#aaa;white-space:pre-wrap;"></pre>
            </div>
            <div id="init-status" style="margin-top:10px;"></div>
        </div>
        <script>
        function appendInitLog(line) {
            const log = document.getElementById('init-log');
            log.textContent += line + '\\n';
            log.scrollTop = log.scrollHeight;
        }

        async function initializeWorkspace() {
            const btn = document.getElementById('init-btn');
            const progress = document.getElementById('init-progress');
            const status = document.getElementById('init-status');

            btn.disabled = true;
            btn.textContent = '初始化中...';
            progress.style.display = 'block';
            status.innerHTML = '';

            appendInitLog('▶ 开始初始化 Yachiyo 工作空间...');

            try {
                if (!window.pywebview || !window.pywebview.api) {
                    throw new Error('WebView API 不可用');
                }

                appendInitLog('  正在创建目录结构...');
                const result = await window.pywebview.api.initialize_workspace();

                if (result.success) {
                    if (result.created_items && result.created_items.length > 0) {
                        result.created_items.forEach(item => appendInitLog('  ✓ ' + item));
                    }
                    appendInitLog('✅ 工作空间初始化完成');
                    status.innerHTML = '<span style="color:#90ee90">✅ 初始化成功！正在进入主界面...</span>';
                    setTimeout(() => window.pywebview.api.restart_app(), 1500);
                } else {
                    throw new Error(result.error || '初始化失败');
                }
            } catch (err) {
                appendInitLog('❌ 错误：' + err.message);
                btn.disabled = false;
                btn.textContent = '重新尝试初始化';
                status.innerHTML = '<span style="color:#ff6b6b">❌ ' + err.message + '</span>';
            }
        }
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
    
    return (
        _INSTALLER_HTML
        .replace("{status_class}", status_class)
        .replace("{status_message}", status_message)
        .replace("{platform}", str(install_info.platform))
        .replace("{error_info}", error_info)
        .replace("{main_title}", main_title)
        .replace("{steps_title}", steps_title)
        .replace("{install_steps}", install_steps)
        .replace("{init_section}", init_section + install_section)
        .replace("{suggestions_section}", suggestions_section)
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
