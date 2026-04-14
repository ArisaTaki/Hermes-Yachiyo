"""主界面 WebView API

为正常模式主窗口提供 JavaScript 可调用的 API。
通过 Core Runtime 获取数据，不直接访问 Bridge。
"""

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.installer.workspace_init import get_workspace_status

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


class MainWindowAPI:
    """正常模式主窗口 API"""
    
    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """获取仪表盘数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            
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
                },
                "workspace": {
                    "path": workspace.get("workspace_path", ""),
                    "initialized": workspace.get("initialized", False),
                    "created_at": workspace.get("created_at"),
                },
                "tasks": status.get("task_counts", {}),
            }
        except Exception as e:
            logger.error("获取仪表盘数据失败: %s", e)
            return {"error": str(e)}

    def get_settings_data(self) -> Dict[str, Any]:
        """获取设置页数据"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            hermes_info = status.get("hermes", {})

            return {
                "hermes": {
                    "status": hermes_info.get("install_status", "unknown"),
                    "version": hermes_info.get("version"),
                    "platform": hermes_info.get("platform", "unknown"),
                    "command_exists": hermes_info.get("command_exists", False),
                    "hermes_home": hermes_info.get("hermes_home", ""),
                    "ready": self._runtime.is_hermes_ready(),
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
                        {"id": "bubble", "name": "气泡模式", "available": False},
                        {"id": "live2d", "name": "Live2D 模式", "available": False},
                    ],
                },
                "bridge": {
                    "host": self._config.bridge_host,
                    "port": self._config.bridge_port,
                    "url": f"http://{self._config.bridge_host}:{self._config.bridge_port}",
                },
                "integrations": {
                    "astrbot": {
                        "name": "AstrBot / QQ",
                        "status": "not_configured",
                        "description": "QQ 消息桥接（即将推出）",
                    },
                    "hapi": {
                        "name": "Hapi / Codex",
                        "status": "not_configured",
                        "description": "Codex CLI 执行后端（即将推出）",
                    },
                },
                "app": {
                    "version": status.get("version", "0.1.0"),
                    "log_level": self._config.log_level,
                    "start_minimized": self._config.start_minimized,
                },
            }
        except Exception as e:
            logger.error("获取设置数据失败: %s", e)
            return {"error": str(e)}
