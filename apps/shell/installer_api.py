"""WebView API 处理

为安装引导窗口提供 JavaScript 可调用的 API。
"""

import asyncio
import logging
import os
import threading
from typing import Any, Dict

from apps.installer.workspace_init import initialize_yachiyo_workspace

logger = logging.getLogger(__name__)


class InstallerWebViewAPI:
    """安装引导 WebView API"""

    def initialize_workspace(self) -> Dict[str, Any]:
        """初始化 Yachiyo 工作空间"""
        try:
            logger.info("开始 Yachiyo 工作空间初始化")
            success, error, created_items = initialize_yachiyo_workspace()
            if success:
                logger.info("工作空间初始化成功: %s 项目创建", len(created_items))
                return {"success": True, "error": None, "created_items": created_items}
            else:
                logger.error("工作空间初始化失败: %s", error)
                return {"success": False, "error": error, "created_items": created_items}
        except Exception as exc:
            logger.error("初始化过程异常: %s", exc)
            return {"success": False, "error": f"初始化异常: {exc}", "created_items": []}

    def install_hermes(self) -> Dict[str, Any]:
        """触发 Hermes Agent 安装。

        在后台线程中运行安装脚本（blocking），通过轮询 get_install_progress() 获取进度。
        安装完成后，前端应调用 recheck_status() 确认最终状态。

        Returns:
            {"started": bool, "error": str | None}
        """
        if _install_state["running"]:
            return {"started": False, "error": "安装已在进行中"}

        _install_state["running"] = True
        _install_state["lines"] = []
        _install_state["result"] = None

        def _run():
            from apps.installer.hermes_install import run_hermes_install

            def _on_line(line: str) -> None:
                _install_state["lines"].append(line)

            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    run_hermes_install(on_output=_on_line)
                )
            except Exception as exc:
                from apps.installer.hermes_install import InstallResult
                result = InstallResult(
                    success=False,
                    message=f"安装过程异常: {exc}",
                    returncode=-1,
                )
            finally:
                loop.close()

            _install_state["result"] = result
            _install_state["running"] = False
            logger.info(
                "Hermes 安装完成: success=%s, message=%s",
                result.success,
                result.message,
            )

        t = threading.Thread(target=_run, daemon=True, name="hermes-installer")
        t.start()
        logger.info("Hermes 安装线程已启动")
        return {"started": True, "error": None}

    def get_install_progress(self) -> Dict[str, Any]:
        """获取当前安装进度（供前端轮询）。

        Returns:
            {
                "running": bool,
                "lines": List[str],       # 安装输出行（最近 50 行）
                "success": bool | None,   # None 表示仍在进行中
                "message": str,
            }
        """
        result = _install_state.get("result")
        return {
            "running": _install_state["running"],
            "lines": list(_install_state["lines"])[-50:],
            "success": result.success if result is not None else None,
            "message": result.message if result is not None else "",
        }

    def recheck_status(self) -> Dict[str, Any]:
        """重新检测 Hermes 安装状态。

        安装完成后调用，让前端决定下一步流程。

        Returns:
            {"status": str, "message": str, "ready": bool}
        """
        from apps.installer.hermes_check import check_hermes_installation

        info = check_hermes_installation()
        from packages.protocol.enums import HermesInstallStatus
        return {
            "status": info.status.value,
            "message": info.error_message or "",
            "ready": info.status == HermesInstallStatus.READY,
            "needs_init": info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED,
        }

    def restart_app(self) -> None:
        """重启应用（退出当前进程，依赖外部重启）"""
        logger.info("正在重启应用...")
        def _delayed():
            import time
            time.sleep(0.8)
            os._exit(0)
        threading.Thread(target=_delayed, daemon=True).start()


# 安装进度共享状态（简单字典，单次安装生命周期内使用）
_install_state: Dict[str, Any] = {
    "running": False,
    "lines": [],
    "result": None,
}