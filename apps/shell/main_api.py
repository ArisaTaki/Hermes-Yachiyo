"""主界面 WebView API

为正常模式主窗口提供 JavaScript 可调用的 API。
通过 Core Runtime 获取数据，不直接访问 Bridge。
"""

import logging
from typing import TYPE_CHECKING, Dict

from apps.installer.workspace_init import get_workspace_status

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

logger = logging.getLogger(__name__)


class MainWindowAPI:
    """正常模式主窗口 API"""
    
    def __init__(self, runtime: "HermesRuntime") -> None:
        self._runtime = runtime
    
    def get_dashboard_data(self) -> Dict[str, any]:
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
