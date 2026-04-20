"""Live2D 模式骨架

当前状态：预留骨架，尚未接入 Live2D SDK / 运行时。
窗口展示角色占位区域 + 聊天界面 + 打开主窗口 / 设置入口。
共享 ChatSession，三模式消息互通。

后续接入 Live2D 时的扩展点：
  1. Live2DRenderer（在 apps/shell/modes/live2d_renderer.py 中实现）
     - 加载 .moc3 模型文件
     - 管理动作系统（idle / react / speak）
     - 驱动 WebGL canvas 渲染

  2. CharacterController（角色状态机）
     - 响应 RuntimeState（任务运行中 → 工作动作；空闲 → idle 动作）
     - 接受语音/文字触发的表情切换

  3. Live2DWindowAPI.load_model(model_path)
     - 由设置页调用，切换当前角色模型

  4. 窗口尺寸策略
     - Live2D 角色窗口通常为竖版全透明（chromeless）
     - 等待 pywebview 支持透明窗口后再实现

架构边界：
  - apps/shell/modes/live2d.py       → 本文件：模式入口 + API + HTML骨架
  - apps/shell/modes/live2d_renderer → 未来：渲染引擎封装（当前不存在）
  - apps/core/runtime.py             → 提供任务状态驱动角色动作的数据
  - apps/shell/startup.py            → 模式选择（不感知 Live2D 内部细节）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.bridge.server import get_bridge_state
from apps.installer.workspace_init import get_workspace_status
from apps.shell.chat_bridge import ChatBridge
from apps.shell.main_api import _serialize_summary

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

# ── HTML 骨架 ─────────────────────────────────────────────────────────────────

_LIVE2D_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo — Live2D 模式</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* ── 角色区（未来放 Live2D canvas）── */
        .character-stage {
            height: 180px;
            flex-shrink: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            position: relative;
            background: linear-gradient(180deg, #12122a 0%, #1a1a3e 100%);
        }
        .character-placeholder {
            font-size: 4em;
            opacity: 0.6;
            animation: float 3s ease-in-out infinite;
        }
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50%       { transform: translateY(-6px); }
        }
        .stage-label {
            font-size: 0.7em;
            color: #555;
            letter-spacing: 0.1em;
            margin-top: 4px;
        }
        .dev-badge {
            position: absolute;
            top: 8px;
            right: 8px;
            background: #2a1a2e;
            border: 1px solid #6a2a6a;
            color: #cc88cc;
            font-size: 0.65em;
            padding: 2px 6px;
            border-radius: 8px;
        }

        /* ── 聊天区 ── */
        .chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            padding: 10px;
            min-height: 0;
        }
        .chat-messages {
            flex: 1;
            overflow-y: auto;
            background: #12122a;
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 10px;
            font-size: 0.88em;
        }
        .chat-msg {
            margin-bottom: 8px;
            padding: 8px 10px;
            border-radius: 8px;
            line-height: 1.5;
        }
        .chat-msg.user {
            background: #3a4a7a;
            margin-left: 30px;
            border-left: 3px solid #6495ed;
        }
        .chat-msg.assistant {
            background: #2a3a3a;
            margin-right: 30px;
            border-left: 3px solid #90ee90;
        }
        .chat-msg.system {
            background: #2a2a3a;
            text-align: center;
            color: #666;
            font-size: 0.85em;
        }
        .chat-msg .role { font-size: 0.72em; color: #888; margin-bottom: 2px; }
        .chat-msg .content { color: #ddd; white-space: pre-wrap; word-break: break-word; }
        .chat-msg.pending .content { color: #aaa; }
        .chat-msg.processing .content { color: #aaa; }
        .chat-msg.error .content { color: #ffaaaa; }
        @keyframes thinking-dot {
            0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-1px); }
        }
        .thinking { display: inline-flex; align-items: center; gap: 2px; }
        .thinking .dot {
            animation: thinking-dot 1.2s ease-in-out infinite;
            display: inline-block;
        }
        .thinking .dot:nth-child(2) {
            animation-delay: 0.15s;
        }
        .thinking .dot:nth-child(3) {
            animation-delay: 0.3s;
        }
        .chat-input-row {
            display: flex;
            gap: 8px;
            flex-shrink: 0;
        }
        .chat-input {
            flex: 1;
            background: #2d2d54;
            color: #e0e0e0;
            border: 1px solid #444;
            border-radius: 6px;
            padding: 10px 12px;
            font-size: 0.9em;
            outline: none;
        }
        .chat-input:focus { border-color: #6495ed; }
        .chat-input::placeholder { color: #555; }
        .chat-send {
            background: #4a6a9a;
            border: none;
            color: #fff;
            padding: 10px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9em;
        }
        .chat-send:hover { background: #5a7aaa; }
        .chat-send:disabled { background: #3a3a5a; color: #666; cursor: not-allowed; }

        /* ── 状态条 ── */
        .status-bar {
            background: #12122a;
            border-top: 1px solid #2a2a4a;
            padding: 6px 12px;
            display: flex;
            gap: 10px;
            font-size: 0.75em;
            align-items: center;
            flex-shrink: 0;
        }
        .status-chip {
            background: #2d2d54;
            border-radius: 10px;
            padding: 2px 8px;
            color: #888;
        }
        .status-chip.ok { color: #90ee90; }
        .status-chip.warn { color: #ffd700; }
        .spacer { flex: 1; }

        /* ── 底部工具栏 ── */
        .toolbar {
            background: #0e0e22;
            border-top: 1px solid #222244;
            padding: 8px 12px;
            display: flex;
            gap: 8px;
            align-items: center;
            flex-shrink: 0;
        }
        .btn {
            background: #2d2d54;
            border: 1px solid #444;
            color: #ccc;
            padding: 6px 12px;
            border-radius: 5px;
            font-size: 0.8em;
            cursor: pointer;
        }
        .btn:hover { background: #3a3a6a; border-color: #6495ed; color: #fff; }
        .btn.primary { border-color: #6495ed; color: #6495ed; }
    </style>
</head>
<body>
    <!-- 角色舞台区 -->
    <div class="character-stage">
        <div class="dev-badge">骨架 · 待接入 Live2D</div>
        <div class="character-placeholder" id="char-icon">🎤</div>
        <div class="stage-label" id="stage-label">LIVE2D · 角色模型待加载</div>
    </div>

    <!-- 聊天入口 -->
    <div class="chat-area">
        <div class="chat-messages" id="chat-messages">
            <div style="text-align:center;color:#555;padding:15px 8px;font-size:0.85em;">发送消息开始对话 ✨</div>
        </div>
        <div class="chat-input-row">
            <input type="text" class="chat-input" id="msg-input"
                   placeholder="输入消息…"
                   onkeypress="if(event.key==='Enter') sendMsg()">
            <button class="chat-send" id="send-btn" onclick="sendMsg()">发送</button>
        </div>
    </div>

    <!-- 状态条 -->
    <div class="status-bar">
        <span class="status-chip" id="chip-hermes">Hermes …</span>
        <span class="status-chip" id="chip-executor">—</span>
        <span class="spacer"></span>
        <span class="status-chip" style="color:#9988cc;">live2d</span>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
        <button class="btn primary" onclick="openMainWindow()">🖥 主窗口</button>
        <button class="btn primary" onclick="openChat()">💬 对话</button>
        <button class="btn" onclick="openSettings()">⚙ 设置</button>
    </div>

    <script>
    const ACTIVE_POLL_INTERVAL_MS = 1200;
    const IDLE_POLL_INTERVAL_MS = 5000;
    let polling = null;
    let pollingIntervalMs = null;
    let statusPolling = null;
    let sending = false;

    function escapeHtml(t) {
        const d = document.createElement('div');
        d.textContent = t;
        return d.innerHTML;
    }

    async function sendMsg() {
        if (sending) return;
        const input = document.getElementById('msg-input');
        const text = (input.value || '').trim();
        if (!text) return;
        sending = true;
        document.getElementById('send-btn').disabled = true;
        input.disabled = true;
        try {
            if (!window.pywebview || !window.pywebview.api) throw new Error('API 不可用');
            const r = await window.pywebview.api.send_quick_message(text);
            if (!r.ok) throw new Error(r.error || '发送失败');
            input.value = '';
            await refreshMessages();
            startActivePolling();
        } catch(e) {
            console.error('send error:', e);
        } finally {
            sending = false;
            document.getElementById('send-btn').disabled = false;
            input.disabled = false;
            input.focus();
        }
    }

    async function refreshMessages() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const r = await window.pywebview.api.get_recent_summary(3);
            if (!r.ok) return;

            const container = document.getElementById('chat-messages');
            if (r.empty || !r.messages || r.messages.length === 0) {
                container.innerHTML = '<div style="text-align:center;color:#555;padding:15px 8px;font-size:0.85em;">发送消息开始对话 ✨</div>';
                startIdlePolling();
                return;
            }

            let html = '';
            for (const m of r.messages) {
                const label = m.role === 'user' ? '你' : (m.role === 'assistant' ? 'Yachiyo' : '系统');
                const sc = m.status === 'failed' ? 'error'
                         : m.status === 'processing' ? 'processing'
                         : m.status === 'pending' ? 'pending' : '';
                let content;
                if (m.status === 'processing' && m.role === 'assistant') {
                    content = m.content ? escapeHtml(m.content) : renderThinking();
                } else {
                    content = escapeHtml(m.content);
                }
                html += '<div class="chat-msg ' + m.role + ' ' + sc + '">';
                html += '<div class="role">' + label + '</div>';
                html += '<div class="content">' + content + '</div>';
                html += '</div>';
            }
            container.innerHTML = html;
            container.scrollTop = container.scrollHeight;

            // 更新角色图标（处理中显示工作状态）
            const icon = document.getElementById('char-icon');
            if (icon) icon.textContent = r.is_processing ? '⚡' : '🎤';

            if (r.is_processing) {
                startActivePolling();
            } else {
                startIdlePolling();
            }
        } catch(e) {}
    }

    function renderThinking() {
        return '<span class="thinking" aria-label="正在思考">'
             + '<span class="dot" aria-hidden="true">.</span>'
             + '<span class="dot" aria-hidden="true">.</span>'
             + '<span class="dot" aria-hidden="true">.</span>'
             + '</span>';
    }

    function setPollingInterval(intervalMs) {
        if (polling && pollingIntervalMs === intervalMs) return;
        stopPolling();
        pollingIntervalMs = intervalMs;
        polling = setInterval(refreshMessages, intervalMs);
    }

    function startActivePolling() {
        setPollingInterval(ACTIVE_POLL_INTERVAL_MS);
    }

    function startIdlePolling() {
        setPollingInterval(IDLE_POLL_INTERVAL_MS);
    }

    function stopPolling() {
        if (polling) { clearInterval(polling); polling = null; }
        pollingIntervalMs = null;
    }

    async function openChat() {
        try {
            if (window.pywebview && window.pywebview.api)
                await window.pywebview.api.open_chat();
        } catch(e) { console.error('openChat error:', e); }
    }

    async function refreshStatus() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const d = await window.pywebview.api.get_live2d_status();
            if (d.error) return;

            const hChip = document.getElementById('chip-hermes');
            hChip.textContent = d.hermes.ready ? '✅ Hermes' : '⚠️ Hermes';
            hChip.className = 'status-chip ' + (d.hermes.ready ? 'ok' : 'warn');

            const ex = await window.pywebview.api.get_executor_info();
            document.getElementById('chip-executor').textContent = ex.executor === 'HermesExecutor' ? '🚀 Hermes' : '🔬 模拟';

            const label = document.getElementById('stage-label');
            const modelState = d.model.state || 'not_configured';
            const stateLabels = {
                'not_configured':  'LIVE2D · 角色模型未配置',
                'path_invalid':    'LIVE2D · 模型路径不存在',
                'path_not_live2d': 'LIVE2D · 目录无模型文件',
                'path_valid':      'LIVE2D · 模型就绪: ' + (d.model.name || ''),
                'loaded':          d.model.name || 'LIVE2D',
            };
            label.textContent = stateLabels[modelState] || 'LIVE2D';
        } catch(e) {}
    }

    async function openMainWindow() {
        try {
            if (window.pywebview && window.pywebview.api)
                await window.pywebview.api.open_main_window();
        } catch(e) {}
    }

    async function openSettings() {
        try {
            if (window.pywebview && window.pywebview.api)
                await window.pywebview.api.open_settings();
        } catch(e) {}
    }

    function bootstrap() {
        refreshStatus();
        refreshMessages();
        startIdlePolling();
        if (!statusPolling) {
            statusPolling = setInterval(refreshStatus, 10000);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        setTimeout(bootstrap, 500);
    });
    window.addEventListener('pywebviewready', bootstrap);
    </script>
</body>
</html>
"""


# ── WebView API ───────────────────────────────────────────────────────────────

class Live2DWindowAPI:
    """Live2D 模式 WebView API。

    当前职责：
      - 提供状态数据给前端（get_live2d_status）
      - 提供打开独立聊天窗口的入口（open_chat）
      - 提供打开主窗口 / 设置页的入口

    说明：
      - 当前类不直接提供 send_message / get_messages / clear_session
        这类聊天消息读写接口；聊天交互由独立聊天窗口承载。

    未来扩展点（接入 Live2D 时新增方法）：
      - load_model(model_path: str) → 加载角色模型
      - play_motion(group: str, index: int) → 播放动作
      - set_expression(expression_id: str) → 切换表情
    """

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)

    def get_live2d_status(self) -> Dict[str, Any]:
        """返回当前运行状态，供前端状态条和图标切换使用。"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            hermes_info = status.get("hermes", {})
            task_counts = status.get("task_counts", {})

            return {
                "hermes": {
                    "status": hermes_info.get("install_status", "unknown"),
                    "ready": self._runtime.is_hermes_ready(),
                },
                "tasks": {
                    "running": task_counts.get("running", 0),
                    "pending": task_counts.get("pending", 0),
                    "total": sum(task_counts.values()),
                },
                "workspace": {
                    "initialized": workspace.get("initialized", False),
                },
                # 角色模型状态：从配置读取，渲染器就绪后改为从 Live2DRenderer 动态获取
                "model": {
                    "loaded": False,        # TODO: Live2DRenderer.is_loaded()（当前渲染器未实现）
                    "state": self._config.live2d.validate().value,
                    "configured": self._config.live2d.is_model_configured(),
                    "name": self._config.live2d.model_name or "",
                    "path": self._config.live2d.model_path or "",
                    "idle_motion_group": self._config.live2d.idle_motion_group,
                    "expressions_enabled": self._config.live2d.enable_expressions,
                    "physics_enabled": self._config.live2d.enable_physics,
                    "available_motions": [],  # TODO: Live2DRenderer.list_motions()
                    "summary": _serialize_summary(self._config.live2d.scan()),
                },
                "bridge": {
                    "running": get_bridge_state(),
                    "addr": f"{self._config.bridge_host}:{self._config.bridge_port}",
                },
            }
        except Exception as exc:
            logger.error("获取 Live2D 状态失败: %s", exc)
            return {"error": str(exc)}

    # ── 聊天摘要与快捷发送 ──────────────────────────────────────────────────

    def send_quick_message(self, text: str) -> Dict[str, Any]:
        """快捷发消息到统一 ChatSession"""
        return self._chat_bridge.send_quick_message(text)

    def get_recent_summary(self, count: int = 3) -> Dict[str, Any]:
        """获取最近 N 条消息摘要"""
        return self._chat_bridge.get_recent_summary(count)

    # ── 窗口操作 ────────────────────────────────────────────────────────────

    def get_executor_info(self) -> Dict[str, Any]:
        runner = self._runtime.task_runner
        if runner is None:
            return {"executor": "none", "available": False}
        return {"executor": runner.executor.name, "available": True}

    def open_chat(self) -> Dict[str, Any]:
        """打开独立聊天窗口"""
        from apps.shell.chat_window import open_chat_window
        ok = open_chat_window(self._runtime)
        return {"ok": ok}

    def open_main_window(self) -> None:
        """在当前会话中打开完整主窗口仪表盘。"""
        try:
            import webview  # type: ignore[import]
            from apps.shell.main_api import MainWindowAPI
            from apps.shell.window import _STATUS_HTML

            html = _STATUS_HTML.replace("{{HOST}}", self._config.bridge_host).replace(
                "{{PORT}}", str(self._config.bridge_port)
            )
            api = MainWindowAPI(self._runtime, self._config)
            webview.create_window(
                title="Hermes-Yachiyo — 主窗口",
                html=html,
                width=560,
                height=620,
                resizable=True,
                js_api=api,
            )
        except Exception as exc:
            logger.error("打开主窗口失败: %s", exc)

    def get_live2d_state(self) -> Dict[str, Any]:
        """返回当前 Live2D 配置的校验状态与摘要。

        保存后立即调用可获得最新校验结果，无需重新打开设置页。
        """
        from apps.shell.main_api import _serialize_summary

        state = self._config.live2d.validate()
        summary = self._config.live2d.scan()
        return {
            "model_state": state.value,
            "model_name": self._config.live2d.model_name or "",
            "model_path": self._config.live2d.model_path or "",
            "idle_motion_group": self._config.live2d.idle_motion_group,
            "summary": _serialize_summary(summary),
        }

    def update_settings(self, changes: dict) -> dict:
        """保存配置变更，供设置页调用。支持 live2d.* 前缀的嵌套字段。"""
        from apps.shell.config import save_config
        from apps.shell.effect_policy import build_effects_summary

        _EDITABLE_LIVE2D_FIELDS: dict[str, type] = {
            "model_name": str,
            "model_path": str,
            "idle_motion_group": str,
            "enable_expressions": bool,
            "enable_physics": bool,
            "window_on_top": bool,
        }

        applied: dict[str, object] = {}
        errors: list[str] = []

        for key, value in changes.items():
            prefix, _, sub_key = key.partition(".")
            if prefix == "live2d" and sub_key:
                if sub_key not in _EDITABLE_LIVE2D_FIELDS:
                    errors.append(f"不可编辑字段: {key}")
                    continue
                expected = _EDITABLE_LIVE2D_FIELDS[sub_key]
                if not isinstance(value, expected):
                    errors.append(f"类型错误: {key} 期望 {expected.__name__}")
                    continue
                setattr(self._config.live2d, sub_key, value)
                applied[key] = value
            else:
                errors.append(f"不支持的字段: {key}")

        if applied:
            try:
                save_config(self._config)
            except Exception as exc:
                logger.error("设置保存失败: %s", exc)
                return {"ok": False, "error": str(exc), "applied": applied}

        live2d_state = self.get_live2d_state() if applied else None
        result: dict = {"ok": True, "applied": applied}
        if applied:
            result["effects"] = build_effects_summary(list(applied.keys()))
        if live2d_state is not None:
            result["live2d_state"] = live2d_state
        if errors:
            result["errors"] = errors
        return result

    def open_settings(self) -> None:
        """打开设置页，传入当前 API 实例以支持保存操作。"""
        try:
            import webview  # type: ignore[import]
            from apps.shell.settings import build_settings_html

            webview.create_window(
                title="Hermes-Yachiyo — 设置",
                html=build_settings_html(self._config),
                width=520,
                height=480,
                resizable=False,
                js_api=self,
            )
        except Exception as exc:
            logger.error("打开设置页失败: %s", exc)


# ── 模式入口 ──────────────────────────────────────────────────────────────────

def run(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """Live2D 模式入口（阻塞主线程）。

    当前为骨架实现：角色舞台区展示占位动画 + 聊天界面。
    等待 Live2DRenderer 实现后替换 .character-placeholder。
    """
    logger.info("启动 Live2D 模式（骨架实现，含聊天）")
    try:
        import webview  # type: ignore[import]

        api = Live2DWindowAPI(runtime, config)
        webview.create_window(
            title="Hermes-Yachiyo",
            html=_LIVE2D_HTML,
            width=400,
            height=640,  # 增加高度以容纳聊天区域
            resizable=True,
            js_api=api,
        )
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，Live2D 模式无法展示")
