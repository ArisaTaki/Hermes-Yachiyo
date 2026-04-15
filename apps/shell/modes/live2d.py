"""Live2D 模式骨架

当前状态：预留骨架，尚未接入 Live2D SDK / 运行时。
窗口展示角色占位区域 + 状态信息 + 打开主窗口 / 设置入口。

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
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            position: relative;
            background: linear-gradient(180deg, #12122a 0%, #1a1a3e 100%);
        }
        .character-placeholder {
            font-size: 5em;
            opacity: 0.6;
            margin-bottom: 8px;
            animation: float 3s ease-in-out infinite;
        }
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50%       { transform: translateY(-8px); }
        }
        .stage-label {
            font-size: 0.75em;
            color: #555;
            letter-spacing: 0.1em;
        }
        /* 未来 Live2D canvas 将替换 .character-placeholder */
        /* canvas#live2d { width: 100%; height: 100%; position: absolute; top:0; left:0; } */

        /* ── 状态条 ── */
        .status-bar {
            background: #12122a;
            border-top: 1px solid #2a2a4a;
            padding: 8px 14px;
            display: flex;
            gap: 12px;
            font-size: 0.78em;
            align-items: center;
        }
        .status-chip {
            background: #2d2d54;
            border-radius: 10px;
            padding: 2px 10px;
            color: #888;
            white-space: nowrap;
        }
        .status-chip.ok { color: #90ee90; }
        .status-chip.warn { color: #ffd700; }
        .spacer { flex: 1; }

        /* ── 底部工具栏 ── */
        .toolbar {
            background: #0e0e22;
            border-top: 1px solid #222244;
            padding: 8px 14px;
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .btn {
            background: #2d2d54;
            border: 1px solid #444;
            color: #ccc;
            padding: 6px 14px;
            border-radius: 5px;
            font-size: 0.82em;
            cursor: pointer;
            white-space: nowrap;
        }
        .btn:hover { background: #3a3a6a; border-color: #6495ed; color: #fff; }
        .btn.primary { border-color: #6495ed; color: #6495ed; }
        .btn.primary:hover { background: #4a4a8a; color: #fff; }

        /* ── 开发提示 ── */
        .dev-badge {
            position: absolute;
            top: 10px;
            right: 10px;
            background: #2a1a2e;
            border: 1px solid #6a2a6a;
            color: #cc88cc;
            font-size: 0.7em;
            padding: 3px 8px;
            border-radius: 10px;
        }
    </style>
</head>
<body>
    <!-- 角色舞台区 -->
    <div class="character-stage">
        <div class="dev-badge">骨架模式 · 待接入 Live2D</div>
        <div class="character-placeholder" id="char-icon">🎤</div>
        <div class="stage-label" id="stage-label">LIVE2D · 角色模型待加载</div>
    </div>

    <!-- 状态条 -->
    <div class="status-bar">
        <span class="status-chip" id="chip-hermes">Hermes …</span>
        <span class="status-chip" id="chip-task">任务 …</span>
        <span class="spacer"></span>
        <span class="status-chip" id="chip-mode" style="color:#9988cc;">live2d 模式</span>
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
        <button class="btn primary" onclick="openMainWindow()">🖥 主窗口</button>
        <button class="btn" onclick="openSettings()">⚙ 设置</button>
        <button class="btn" onclick="refreshStatus()">↺ 刷新</button>
    </div>

    <script>
    async function refreshStatus() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const d = await window.pywebview.api.get_live2d_status();
            if (d.error) return;

            const hChip = document.getElementById('chip-hermes');
            hChip.textContent = d.hermes.ready ? '✅ Hermes 就绪' : '⚠️ Hermes ' + d.hermes.status;
            hChip.className = 'status-chip ' + (d.hermes.ready ? 'ok' : 'warn');

            const tChip = document.getElementById('chip-task');
            const running = d.tasks.running || 0;
            tChip.textContent = running > 0 ? '▶ ' + running + ' 任务运行中' : '○ 无任务';
            tChip.className = 'status-chip ' + (running > 0 ? 'ok' : '');

            // 根据状态切换角色图标（未来由 Live2D 动作系统替换）
            const icon = document.getElementById('char-icon');
            icon.textContent = running > 0 ? '⚡' : '🎤';

            const label = document.getElementById('stage-label');
            const modelState = d.model.state || 'not_configured';
            const stateLabels = {
                'not_configured':  'LIVE2D · 角色模型未配置',
                'path_invalid':    'LIVE2D · 模型路径不存在: ' + (d.model.name || '未命名'),
                'path_not_live2d': 'LIVE2D · 目录无模型文件: ' + (d.model.name || '未命名'),
                'path_valid':      'LIVE2D · 模型就绪: ' + (d.model.name || '未命名') + ' · 渲染器待实现',
                'loaded':          d.model.name || 'LIVE2D · 模型已加载',
            };
            label.textContent = stateLabels[modelState] || 'LIVE2D · 状态未知';
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

    document.addEventListener('DOMContentLoaded', function() {
        if (window.pywebview) refreshStatus();
        setInterval(refreshStatus, 10000);
    });
    window.addEventListener('pywebviewready', function() { refreshStatus(); });
    </script>
</body>
</html>
"""


# ── WebView API ───────────────────────────────────────────────────────────────

class Live2DWindowAPI:
    """Live2D 模式 WebView API

    当前职责：
      - 提供状态数据给前端（get_live2d_status）
      - 提供打开主窗口 / 设置页的入口

    未来扩展点（接入 Live2D 时新增方法）：
      - load_model(model_path: str) → 加载角色模型
      - play_motion(group: str, index: int) → 播放动作
      - set_expression(expression_id: str) → 切换表情
    """

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config

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

    def open_main_window(self) -> None:
        """在当前会话中打开完整主窗口仪表盘。"""
        try:
            import webview  # type: ignore[import]
            from apps.shell.window import _STATUS_HTML

            html = _STATUS_HTML.replace("{{HOST}}", self._config.bridge_host).replace(
                "{{PORT}}", str(self._config.bridge_port)
            )
            webview.create_window(
                title="Hermes-Yachiyo — 主窗口",
                html=html,
                width=560,
                height=520,
                resizable=True,
            )
        except Exception as exc:
            logger.error("打开主窗口失败: %s", exc)

    def update_settings(self, changes: dict) -> dict:
        """保存配置变更，供设置页调用。支持 live2d.* 前缀的嵌套字段。"""
        from apps.shell.config import save_config

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

        return {"ok": True, "applied": applied, **({"errors": errors} if errors else {})}

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

    当前为骨架实现：角色舞台区展示占位动画，底部工具栏提供主窗口 / 设置入口。
    等待 Live2DRenderer 实现后替换 .character-placeholder。
    """
    logger.info("启动 Live2D 模式（骨架实现，角色模型未加载）")
    try:
        import webview  # type: ignore[import]

        api = Live2DWindowAPI(runtime, config)
        webview.create_window(
            title="Hermes-Yachiyo",
            html=_LIVE2D_HTML,
            width=380,
            height=560,
            resizable=True,
        )
        webview.start(api=api, debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，Live2D 模式无法展示")

