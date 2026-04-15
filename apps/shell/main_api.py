"""主界面 WebView API

为正常模式主窗口提供 JavaScript 可调用的 API。
通过 Core Runtime 获取数据，不直接访问 Bridge。
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from apps.installer.workspace_init import get_workspace_status
from apps.shell.config import ModelSummary, save_config
from apps.shell.effect_policy import build_effects_summary
from apps.shell.integration_status import get_integration_snapshot

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


def _serialize_summary(summary: Optional[ModelSummary]) -> Dict[str, Any]:
    """将 ModelSummary 转为 JSON 安全字典，None 时返回空摘要。"""
    if summary is None:
        return {"available": False}
    return {
        "available": not summary.is_empty(),
        "model3_json": summary.model3_json,
        "moc3_file": summary.moc3_file,
        "found_in_subdir": summary.found_in_subdir,
        "subdir_name": summary.subdir_name,
        "extra_moc3_count": summary.extra_moc3_count,
        # 主候选绝对路径 — 供未来 Live2DRenderer 消费
        "primary_model3_json_abs": summary.primary_model3_json_abs,
        "primary_moc3_abs": summary.primary_moc3_abs,
        "renderer_entry": summary.renderer_entry,  # 推荐入口（model3.json 优先）
    }


class MainWindowAPI:
    """正常模式主窗口 API"""
    
    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        # 记录 bridge 启动时的配置快照，用于检测配置漂移
        self._bridge_boot_config = {
            "enabled": config.bridge_enabled,
            "host": config.bridge_host,
            "port": config.bridge_port,
        }

    def _bridge_status(self) -> str:
        """组合 config.bridge_enabled 与实际运行状态，返回四状态字符串。"""
        snap = get_integration_snapshot(self._config, self._bridge_boot_config)
        return snap.bridge.state

    def _get_snapshot(self):
        """获取集成服务统一快照。"""
        return get_integration_snapshot(self._config, self._bridge_boot_config)
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表盘数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            snap = self._get_snapshot()

            hermes_info = status.get("hermes", {})
            
            return {
                "app": {
                    "version": status.get("version", "0.1.0"),
                    "running": status.get("running", False),
                    "uptime_seconds": round(status.get("uptime_seconds", 0), 1),
                },
                "hermes": {
                    "status": hermes_info.get("install_status", "unknown"),
                    "version": hermes_info.get("version"),
                    "platform": hermes_info.get("platform", "unknown"),
                    "ready": self._runtime.is_hermes_ready(),
                    "readiness_level": hermes_info.get("readiness_level", "unknown"),
                    "limited_tools": hermes_info.get("limited_tools", []),
                    "doctor_issues_count": hermes_info.get("doctor_issues_count", 0),
                },
                "workspace": {
                    "path": workspace.get("workspace_path", ""),
                    "initialized": workspace.get("initialized", False),
                    "created_at": workspace.get("created_at"),
                },
                "tasks": status.get("task_counts", {}),
                "bridge": snap.bridge.to_dashboard_dict(),
                "integrations": {
                    "astrbot": snap.astrbot.to_dict(),
                    "hapi": snap.hapi.to_dict(),
                },
            }
        except Exception as e:
            logger.error("获取仪表盘数据失败: %s", e)
            return {"error": str(e)}

    def get_settings_data(self) -> Dict[str, Any]:
        """获取设置页数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            snap = self._get_snapshot()
            hermes_info = status.get("hermes", {})

            return {
                "hermes": {
                    "status": hermes_info.get("install_status", "unknown"),
                    "version": hermes_info.get("version"),
                    "platform": hermes_info.get("platform", "unknown"),
                    "command_exists": hermes_info.get("command_exists", False),
                    "hermes_home": hermes_info.get("hermes_home", ""),
                    "ready": self._runtime.is_hermes_ready(),
                    "readiness_level": hermes_info.get("readiness_level", "unknown"),
                    "limited_tools": hermes_info.get("limited_tools", []),
                    "doctor_issues_count": hermes_info.get("doctor_issues_count", 0),
                },
                "workspace": {
                    "path": workspace.get("workspace_path", ""),
                    "initialized": workspace.get("initialized", False),
                    "created_at": workspace.get("created_at"),
                    "dirs": workspace.get("dirs", {}),
                },
                "display": {
                    "current_mode": self._config.display_mode,
                    "available_modes": [
                        {"id": "window", "name": "窗口模式", "available": True},
                        {"id": "bubble", "name": "气泡模式", "available": True},
                        {"id": "live2d", "name": "Live2D 模式", "available": False},
                    ],
                },
                "live2d": {
                    "model_state": self._config.live2d.validate().value,
                    "model_configured": self._config.live2d.is_model_configured(),
                    "model_name": self._config.live2d.model_name or "",
                    "model_path": self._config.live2d.model_path or "",
                    "idle_motion_group": self._config.live2d.idle_motion_group,
                    "enable_expressions": self._config.live2d.enable_expressions,
                    "enable_physics": self._config.live2d.enable_physics,
                    "window_on_top": self._config.live2d.window_on_top,
                    "renderer_available": False,
                    "summary": _serialize_summary(self._config.live2d.scan()),
                },
                "bridge": snap.bridge.to_dict(),
                "integrations": {
                    "astrbot": snap.astrbot.to_dict(),
                    "hapi": snap.hapi.to_dict(),
                },
                "app": {
                    "version": status.get("version", "0.1.0"),
                    "log_level": self._config.log_level,
                    "start_minimized": self._config.start_minimized,
                    "tray_enabled": self._config.tray_enabled,
                },
            }
        except Exception as e:
            logger.error("获取设置数据失败: %s", e)
            return {"error": str(e)}

    # ------ 可编辑配置项白名单 ------
    _EDITABLE_FIELDS: Dict[str, type] = {
        "display_mode": str,
        "bridge_enabled": bool,
        "bridge_host": str,
        "bridge_port": int,
        "tray_enabled": bool,
    }
    # Live2D 嵌套字段白名单（key 格式：live2d.<field_name>）
    _EDITABLE_LIVE2D_FIELDS: Dict[str, type] = {
        "model_name":         str,
        "model_path":         str,
        "idle_motion_group":  str,
        "enable_expressions": bool,
        "enable_physics":     bool,
        "window_on_top":      bool,
    }
    _VALID_DISPLAY_MODES = {"window", "bubble", "live2d"}

    def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """修改配置项并持久化。

        支持顶层字段（如 display_mode）和嵌套 live2d 字段（如 live2d.model_name）。
        仅允许修改白名单内的字段，返回最终生效的值。
        """
        if not isinstance(changes, dict):
            return {"ok": False, "error": "参数格式错误"}

        applied: Dict[str, Any] = {}
        errors: list[str] = []

        for key, value in changes.items():
            # --- 嵌套 live2d.* 字段 ---
            if key.startswith("live2d."):
                sub_key = key[len("live2d."):]
                if sub_key not in self._EDITABLE_LIVE2D_FIELDS:
                    errors.append(f"不支持修改: {key}")
                    continue
                expected = self._EDITABLE_LIVE2D_FIELDS[sub_key]
                if not isinstance(value, expected):
                    errors.append(f"{key} 类型错误，期望 {expected.__name__}")
                    continue
                setattr(self._config.live2d, sub_key, value)
                applied[key] = value
                continue

            # --- 顶层字段 ---
            if key not in self._EDITABLE_FIELDS:
                errors.append(f"不支持修改: {key}")
                continue

            expected = self._EDITABLE_FIELDS[key]
            if expected is int and isinstance(value, float) and value == int(value):
                value = int(value)
            if not isinstance(value, expected):
                errors.append(f"{key} 类型错误，期望 {expected.__name__}")
                continue

            if key == "display_mode" and value not in self._VALID_DISPLAY_MODES:
                errors.append(f"无效的显示模式: {value}")
                continue
            if key == "bridge_port":
                if not (1024 <= value <= 65535):
                    errors.append("bridge_port 须在 1024-65535 之间")
                    continue

            setattr(self._config, key, value)
            applied[key] = value

        if applied:
            try:
                save_config(self._config)
                logger.info("配置已保存: %s", applied)
            except Exception as e:
                logger.error("配置保存失败: %s", e)
                return {"ok": False, "error": f"保存失败: {e}", "applied": applied}

        result: Dict[str, Any] = {"ok": True, "applied": applied, "errors": errors}
        if applied:
            result["app_state"] = self._current_app_state()
            result["effects"] = build_effects_summary(list(applied.keys()))
            if any(k.startswith("live2d.") for k in applied):
                result["live2d_state"] = {
                    "model_state": self._config.live2d.validate().value,
                    "model_name": self._config.live2d.model_name or "",
                    "model_path": self._config.live2d.model_path or "",
                    "idle_motion_group": self._config.live2d.idle_motion_group,
                    "summary": _serialize_summary(self._config.live2d.scan()),
                }
        return result

    def _current_app_state(self) -> Dict[str, Any]:
        """返回当前可编辑配置的最新状态快照，供保存后即时刷新 UI。

        包含 bridge 完整状态（含配置漂移检测和差异明细）以及集成服务状态。
        """
        snap = self._get_snapshot()
        return {
            "display_mode": self._config.display_mode,
            "bridge": snap.bridge.to_dashboard_dict(),
            "tray_enabled": self._config.tray_enabled,
            "integrations": {
                "astrbot": snap.astrbot.to_dict(),
                "hapi": snap.hapi.to_dict(),
            },
        }

    def restart_bridge(self) -> Dict[str, Any]:
        """重启 Bridge 并用当前已保存的配置重新对齐。

        操作流程：
          1. 检查 bridge_enabled
          2. 调用 server.restart_bridge() 停止旧实例 + 启动新线程
          3. 刷新 _bridge_boot_config（重新对齐）
          4. 返回最新 app_state 供前端刷新
        """
        from apps.bridge.server import restart_bridge as _restart

        if not self._config.bridge_enabled:
            return {
                "ok": False,
                "error": "Bridge 未启用，请先在设置中启用 Bridge",
                "app_state": self._current_app_state(),
            }

        host = self._config.bridge_host
        port = self._config.bridge_port

        try:
            result = _restart(host=host, port=port)
        except Exception as exc:
            logger.error("Bridge 重启异常: %s", exc)
            return {
                "ok": False,
                "error": f"Bridge 重启失败: {exc}",
                "app_state": self._current_app_state(),
            }

        if result.get("ok"):
            # 重启成功 → 刷新 boot_config 使 config_dirty 归零
            self._bridge_boot_config = {
                "enabled": self._config.bridge_enabled,
                "host": host,
                "port": port,
            }
            logger.info("Bridge 重启成功，boot_config 已刷新")
        else:
            logger.warning("Bridge 重启失败: %s", result.get("error"))

        return {
            "ok": result.get("ok", False),
            "error": result.get("error"),
            "pending": result.get("pending", False),
            "app_state": self._current_app_state(),
        }
