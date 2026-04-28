"""主界面 WebView API

为 Control Center 主控台提供 JavaScript 可调用的 API。
通过 Core Runtime 获取数据，不直接访问 Bridge。
集成 ChatAPI 提供聊天功能。
"""

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from apps.installer.workspace_init import get_workspace_status
from apps.shell.chat_api import ChatAPI
from apps.shell.chat_bridge import ChatBridge
from apps.shell.config import ModelSummary, save_config
from apps.shell.effect_policy import build_effects_summary
from apps.shell.integration_status import get_integration_snapshot
from apps.shell.mode_catalog import list_mode_options
from apps.shell.mode_settings import (
    apply_settings_changes,
    build_display_settings,
    serialize_mode_settings,
)

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
    """Control Center 主控台 API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_api = ChatAPI(runtime)
        self._chat_bridge = ChatBridge(runtime)
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
                "modes": {
                    "current": self._config.display_mode,
                    "items": list_mode_options(),
                },
                "chat": self._chat_bridge.get_conversation_overview(
                    summary_count=self._config.window_mode.recent_messages_limit,
                    session_limit=self._config.window_mode.recent_sessions_limit,
                ),
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
                    **build_display_settings(self._config),
                },
                "mode_settings": serialize_mode_settings(self._config),
                "assistant": {
                    "persona_prompt": self._config.assistant.persona_prompt,
                    "user_address": self._config.assistant.user_address,
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
                "backup": {
                    "auto_cleanup_enabled": self._config.backup.auto_cleanup_enabled,
                    "retention_count": self._config.backup.retention_count,
                },
            }
        except Exception as e:
            logger.error("获取设置数据失败: %s", e)
            return {"error": str(e)}

    def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """修改配置项并持久化。"""
        previous_display_mode = self._config.display_mode
        result = apply_settings_changes(self._config, changes)
        if result.get("ok"):
            applied = result.get("applied", {})
            if applied:
                logger.info("配置已保存: %s", applied)
                result["app_state"] = self._current_app_state()
                if "effects" not in result:
                    result["effects"] = build_effects_summary(list(applied.keys()))
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

    def _current_app_state(self) -> Dict[str, Any]:
        """返回当前可编辑配置的最新状态快照，供保存后即时刷新 UI。

        包含 bridge 完整状态（含配置漂移检测和差异明细）以及集成服务状态。
        """
        snap = self._get_snapshot()
        return {
            "display_mode": self._config.display_mode,
            "mode_settings": serialize_mode_settings(self._config),
            "assistant": {
                "persona_prompt": self._config.assistant.persona_prompt,
                "user_address": self._config.assistant.user_address,
            },
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

    def open_terminal_command(self, cmd: str) -> Dict[str, Any]:
        """在系统终端中执行指定命令（交互式，需要用户参与）。

        macOS：通过 osascript 在 Terminal.app 新窗口中运行。
        Linux：按优先级尝试 gnome-terminal / xfce4-terminal / xterm。

        Args:
            cmd: 要在终端中运行的命令字符串，如 "hermes setup"

        Returns:
            {"success": bool, "error": str | None}
        """
        import platform as _platform
        import subprocess

        system = _platform.system()
        logger.info("open_terminal_command: system=%s cmd=%r", system, cmd)

        try:
            if system == "Darwin":
                # Terminal.app AppleScript：不使用 "make new document"（会报错 -2710）
                # 直接 do script "cmd" 会在新窗口中执行
                script = (
                    'tell application "Terminal"\n'
                    "    activate\n"
                    f'    do script "{cmd}"\n'
                    "end tell"
                )
                subprocess.Popen(
                    ["osascript", "-e", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif system == "Linux":
                for terminal_cmd in [
                    ["gnome-terminal", "--", "bash", "-c", cmd],
                    ["xfce4-terminal", "-e", cmd],
                    ["konsole", "-e", cmd],
                    ["x-terminal-emulator", "-e", cmd],
                    ["xterm", "-e", cmd],
                ]:
                    try:
                        subprocess.Popen(
                            terminal_cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        break
                    except FileNotFoundError:
                        continue
                else:
                    return {
                        "success": False,
                        "error": "未找到可用的终端模拟器，请手动打开终端",
                    }
            else:
                return {
                    "success": False,
                    "error": f"当前平台（{system}）不支持自动打开终端，请手动运行：{cmd}",
                }

            logger.info("已在系统终端中启动命令: %r", cmd)
            return {"success": True, "error": None}

        except Exception as exc:
            logger.error("open_terminal_command 失败: %s", exc)
            return {"success": False, "error": str(exc)}

    def recheck_hermes(self) -> Dict[str, Any]:
        """重新检测 Hermes 安装 / 就绪状态，并刷新仪表盘数据。

        用于用户完成 hermes setup / hermes doctor 后手动触发重新检测。

        Returns:
            get_dashboard_data() 的最新结果（包含 hermes.readiness_level 等字段）
        """
        logger.info("手动触发 Hermes 就绪状态重检...")
        executor_refresh = {
            "updated": False,
            "executor": "unknown",
            "previous_executor": None,
            "reason": "refresh_failed",
        }
        try:
            self._runtime.refresh_hermes_installation()
            executor_refresh = self._runtime.refresh_task_runner_executor()
        except Exception as exc:
            logger.warning("重新检测 Hermes 状态失败: %s", exc)

        data = self.get_dashboard_data()
        data["executor_refresh"] = executor_refresh
        return data

    # ──────────────────────────────────────────────────────────────────────────
    # 聊天 API（委托 ChatAPI）
    # ──────────────────────────────────────────────────────────────────────────

    def send_message(self, text: str) -> Dict[str, Any]:
        """发送用户消息"""
        return self._chat_api.send_message(text)

    def get_messages(self, limit: int = 50) -> Dict[str, Any]:
        """获取消息列表"""
        return self._chat_api.get_messages(limit)

    def get_session_info(self) -> Dict[str, Any]:
        """获取会话元信息"""
        return self._chat_api.get_session_info()

    def clear_session(self) -> Dict[str, Any]:
        """清空会话"""
        return self._chat_api.clear_session()

    def get_executor_info(self) -> Dict[str, Any]:
        """获取当前执行器信息"""
        runner = self._runtime.task_runner
        if runner is None:
            return {"executor": "none", "available": False}
        return {
            "executor": runner.executor.name,
            "available": True,
        }

    def open_chat(self) -> Dict[str, Any]:
        """打开独立聊天窗口"""
        from apps.shell.chat_window import open_chat_window
        ok = open_chat_window(self._runtime)
        return {"ok": ok}

    def open_mode_settings(self, mode_id: str) -> Dict[str, Any]:
        """打开指定模式的独立设置窗口。"""
        from apps.shell.settings import open_mode_settings_window

        ok = open_mode_settings_window(config=self._config, mode_id=mode_id)
        return {"ok": ok, "mode_id": mode_id}

    def quit_app(self) -> Dict[str, Any]:
        """执行退出前清理；主窗口由前端随后关闭。"""
        try:
            from apps.shell.window import request_app_exit
            request_app_exit()
            return {"ok": True}
        except Exception as exc:
            logger.error("退出应用失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_uninstall_preview(
        self,
        scope: str = "yachiyo_only",
        keep_config: bool = True,
    ) -> Dict[str, Any]:
        """生成卸载预览，不修改文件系统。"""
        try:
            from apps.installer.uninstall import build_uninstall_plan

            plan = build_uninstall_plan(scope, keep_config_snapshot=bool(keep_config))
            return {"ok": True, "plan": plan.to_dict()}
        except Exception as exc:
            logger.error("生成卸载预览失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def run_uninstall(
        self,
        scope: str = "yachiyo_only",
        keep_config: bool = True,
        confirm_text: str = "",
    ) -> Dict[str, Any]:
        """执行 Hermes-Yachiyo 卸载，并在成功后安排应用退出。"""
        try:
            from apps.installer.uninstall import execute_uninstall

            result = execute_uninstall(
                scope,
                keep_config_snapshot=bool(keep_config),
                confirm_text=confirm_text,
            )
            payload = result.to_dict()
            if result.ok:
                try:
                    from apps.shell.window import request_app_exit

                    request_app_exit()
                    payload["exit_scheduled"] = True
                except Exception as exc:
                    logger.error("卸载后退出应用失败: %s", exc)
                    payload["exit_scheduled"] = False
                    payload["exit_error"] = str(exc)
            return payload
        except Exception as exc:
            logger.error("执行卸载失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def get_backup_status(self) -> Dict[str, Any]:
        """获取 Hermes-Yachiyo 备份状态。"""
        try:
            from apps.installer.backup import get_backup_status

            return {"ok": True, **get_backup_status()}
        except Exception as exc:
            logger.error("读取备份状态失败: %s", exc)
            return {"ok": False, "error": str(exc), "has_backup": False}

    def create_backup(self, overwrite_latest: bool = False) -> Dict[str, Any]:
        """主动生成 Hermes-Yachiyo 本地资料备份。"""
        try:
            from apps.installer.backup import create_backup, get_backup_status

            backup = create_backup(
                source_context="manual_overwrite" if overwrite_latest else "manual",
                auto_cleanup=self._config.backup.auto_cleanup_enabled,
                retention_count=self._config.backup.retention_count,
                overwrite_latest=bool(overwrite_latest),
            )
            return {
                "ok": True,
                "backup": backup.to_dict(),
                "backup_path": backup.path,
                "backup_path_display": backup.display_path,
                "status": get_backup_status(),
            }
        except Exception as exc:
            logger.error("创建备份失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def update_backup_settings(
        self,
        auto_cleanup_enabled: bool = True,
        retention_count: int = 10,
    ) -> Dict[str, Any]:
        """更新备份保留策略。"""
        try:
            count = int(retention_count)
            if count < 1 or count > 100:
                return {"ok": False, "error": "保留份数须在 1-100 之间"}
            self._config.backup.auto_cleanup_enabled = bool(auto_cleanup_enabled)
            self._config.backup.retention_count = count
            save_config(self._config)
            return {
                "ok": True,
                "backup": {
                    "auto_cleanup_enabled": self._config.backup.auto_cleanup_enabled,
                    "retention_count": self._config.backup.retention_count,
                },
            }
        except Exception as exc:
            logger.error("保存备份设置失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def restore_backup(self, backup_path: str = "") -> Dict[str, Any]:
        """恢复最近或指定版本备份，并安排应用重启。"""
        try:
            from apps.installer.backup import import_backup

            result = import_backup(backup_path or None)
            payload = result.to_dict()
            if result.ok:
                try:
                    from apps.shell.window import request_app_restart

                    request_app_restart()
                    payload["restart_scheduled"] = True
                except Exception as exc:
                    logger.error("恢复备份后重启失败: %s", exc)
                    payload["restart_scheduled"] = False
                    payload["restart_error"] = str(exc)
            return payload
        except Exception as exc:
            logger.error("恢复备份失败: %s", exc)
            return {"ok": False, "errors": [str(exc)]}

    def delete_backup(self, backup_path: str) -> Dict[str, Any]:
        """删除指定备份。"""
        try:
            from apps.installer.backup import delete_backup, get_backup_status

            deleted = delete_backup(backup_path)
            return {"ok": True, "deleted": deleted.to_dict(), "status": get_backup_status()}
        except Exception as exc:
            logger.error("删除备份失败: %s", exc)
            return {"ok": False, "error": str(exc)}

    def open_backup_location(self, backup_path: str = "") -> Dict[str, Any]:
        """在系统文件管理器中打开备份位置。"""
        import platform
        import subprocess
        from pathlib import Path

        try:
            from apps.installer.backup import default_backup_root

            target = Path(backup_path).expanduser() if backup_path else default_backup_root()
            if not target.exists():
                target = target.parent if backup_path else target
            system = platform.system()
            if system == "Darwin":
                command = ["open", "-R", str(target)] if target.is_file() else ["open", str(target)]
            elif system == "Linux":
                command = ["xdg-open", str(target.parent if target.is_file() else target)]
            else:
                return {"ok": False, "error": f"当前平台不支持自动打开位置: {system}"}
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True}
        except Exception as exc:
            logger.error("打开备份位置失败: %s", exc)
            return {"ok": False, "error": str(exc)}
