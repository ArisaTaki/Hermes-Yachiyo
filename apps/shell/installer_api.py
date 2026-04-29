"""WebView API 处理

为安装引导窗口提供 JavaScript 可调用的 API。
"""

import asyncio
import logging
import os
import threading
import time
from typing import Any, Dict

from apps.installer.workspace_init import initialize_yachiyo_workspace

logger = logging.getLogger(__name__)
INSTALL_LOG_MAX_LINES = 4000


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

    def get_backup_status(self) -> Dict[str, Any]:
        """获取可导入的 Hermes-Yachiyo 备份状态。"""
        try:
            from apps.installer.backup import get_backup_status

            return {"success": True, **get_backup_status()}
        except Exception as exc:
            logger.error("读取备份状态失败: %s", exc)
            return {"success": False, "error": str(exc), "has_backup": False}

    def import_backup(self) -> Dict[str, Any]:
        """导入最近一次保存的 Hermes-Yachiyo 备份。"""
        try:
            from apps.installer.backup import import_backup

            result = import_backup()
            return result.to_dict()
        except Exception as exc:
            logger.error("导入备份失败: %s", exc)
            return {"ok": False, "errors": [str(exc)]}

    def install_hermes(self) -> Dict[str, Any]:
        """触发 Hermes Agent 安装。

        在后台线程中运行安装脚本（blocking），通过轮询 get_install_progress() 获取进度。
        安装完成后，前端应调用 recheck_status() 确认最终状态。

        Returns:
            {"started": bool, "error": str | None}
        """
        _normalize_install_state()
        if _install_state["running"]:
            return {"started": False, "error": "安装已在进行中"}

        _install_state["running"] = True
        _install_state["lines"] = []
        _install_state["line_count"] = 0
        _install_state["truncated"] = False
        _install_state["result"] = None
        _install_state["setup_triggered"] = False
        _install_state["setup_terminal_opened"] = False
        _install_state["started_at"] = time.time()
        _install_state["finished_at"] = None
        _install_state["last_line_at"] = time.time()
        _install_state["thread"] = None

        def _run():
            from apps.installer.hermes_install import run_hermes_install

            def _on_line(line: str) -> None:
                _install_state["last_line_at"] = time.time()
                # 检测特殊标记：安装脚本触发了 hermes setup
                if line == "__SETUP_TRIGGERED__":
                    _install_state["setup_triggered"] = True
                    return  # 不加入 lines，只设置标志
                _append_install_line(line)

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
            _install_state["finished_at"] = time.time()
            logger.info(
                "Hermes 安装完成: success=%s, message=%s",
                result.success,
                result.message,
            )

        t = threading.Thread(target=_run, daemon=True, name="hermes-installer")
        _install_state["thread"] = t
        t.start()
        logger.info("Hermes 安装线程已启动")
        return {"started": True, "error": None}

    def get_install_progress(self) -> Dict[str, Any]:
        """获取当前安装进度（供前端轮询）。

        Returns:
            {
                "running": bool,
                "lines": List[str],       # 安装输出行（保留较长窗口）
                "success": bool | None,   # None 表示仍在进行中
                "message": str,
                "setup_triggered": bool,  # True 表示检测到 setup TUI，需打开终端
            }
        """
        _normalize_install_state()
        result = _install_state.get("result")
        lines = list(_install_state["lines"])
        return {
            "running": _install_state["running"],
            "lines": lines,
            "line_count": _install_state.get("line_count", len(lines)),
            "truncated": bool(_install_state.get("truncated", False)),
            "omitted_count": max(0, int(_install_state.get("line_count", len(lines))) - len(lines)),
            "success": result.success if result is not None else None,
            "message": result.message if result is not None else "",
            "setup_triggered": _install_state.get("setup_triggered", False),
            "started_at": _install_state.get("started_at"),
            "finished_at": _install_state.get("finished_at"),
            "last_line_at": _install_state.get("last_line_at"),
        }

    def recheck_status(self) -> Dict[str, Any]:
        """重新检测 Hermes 安装状态。

        安装完成后调用，使用安装后感知策略（登录 Shell + 常见路径扫描），
        避免因当前进程 PATH 未刷新而误判"仍未安装"。

        Returns:
            {
                "status": str,
                "message": str,
                "ready": bool,
                "needs_init": bool,
                "needs_env_refresh": bool,   # True → 找到 hermes 但需重启以刷新 PATH
            }
        """
        from apps.installer.hermes_check import check_hermes_installation_post_install
        from packages.protocol.enums import HermesInstallStatus

        info, needs_env_refresh = check_hermes_installation_post_install()
        return {
            "status": info.status.value,
            "message": info.error_message or "",
            "ready": info.status == HermesInstallStatus.READY,
            "needs_init": info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED,
            "needs_env_refresh": needs_env_refresh,
        }

    def restart_app(self) -> None:
        """重启应用：先启动新进程，再退出当前进程。

        使用 sys.executable + sys.argv 重新启动，确保应用以相同参数重新加载。
        若无法自动重启（路径异常等），仅退出当前进程并在日志中给出提示。
        """
        logger.info("正在重启应用...")

        def _delayed() -> None:
            import subprocess
            import sys
            import time

            time.sleep(0.8)
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

        threading.Thread(target=_delayed, daemon=True).start()

    def open_hermes_setup_terminal(self) -> Dict[str, Any]:
        """在系统终端中打开 ``hermes setup`` 交互式配置。

        在启动前先检测是否已有 hermes setup 进程在运行，避免重复启动。

        macOS: 使用 ``open -a Terminal`` 或 osascript 在 Terminal.app 中执行。
        Linux: 尝试 gnome-terminal / xterm / x-terminal-emulator。

        Returns:
            {"success": bool, "error": str | None, "already_running": bool}
        """
        import platform as _platform
        import subprocess

        from apps.installer.hermes_check import is_hermes_setup_running

        # 先检测是否已有 setup 进程在运行
        if is_hermes_setup_running():
            logger.info("hermes setup 进程已在运行，跳过重复启动")
            return {
                "success": True,
                "error": None,
                "already_running": True,
            }

        system = _platform.system()

        try:
            if system == "Darwin":
                from apps.shell.terminal import open_terminal_command

                success, error = open_terminal_command("hermes setup")
                if not success:
                    return {"success": False, "error": error, "already_running": False}
            elif system == "Linux":
                # Linux: 按优先级尝试常见终端模拟器
                for terminal_cmd in [
                    ["gnome-terminal", "--", "hermes", "setup"],
                    ["xfce4-terminal", "-e", "hermes setup"],
                    ["konsole", "-e", "hermes", "setup"],
                    ["x-terminal-emulator", "-e", "hermes setup"],
                    ["xterm", "-e", "hermes setup"],
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
                        "error": "未找到可用的终端模拟器，请手动打开终端运行 hermes setup",
                    }
            else:
                return {
                    "success": False,
                    "error": f"当前平台 ({system}) 不支持自动打开终端，请手动运行 hermes setup",
                }

            logger.info("已在系统终端中启动 hermes setup")
            return {"success": True, "error": None, "already_running": False}

        except Exception as exc:
            logger.error("打开终端执行 hermes setup 失败: %s", exc)
            return {"success": False, "error": str(exc), "already_running": False}

    def check_setup_process(self) -> Dict[str, Any]:
        """检查 hermes setup 进程是否正在运行。

        供前端轮询使用，用于更新 UI 状态。

        Returns:
            {"running": bool}
        """
        from apps.installer.hermes_check import is_hermes_setup_running

        return {"running": is_hermes_setup_running()}


# 安装进度共享状态（简单字典，单次安装生命周期内使用）
_install_state: Dict[str, Any] = {
    "running": False,
    "lines": [],
    "line_count": 0,
    "truncated": False,
    "result": None,
    "setup_triggered": False,  # True 表示检测到 hermes setup TUI，需打开终端
    "setup_terminal_opened": False,  # True 表示已自动打开过终端
    "started_at": None,
    "finished_at": None,
    "last_line_at": None,
    "thread": None,
}


def _append_install_line(line: str) -> None:
    _install_state["line_count"] = int(_install_state.get("line_count", 0)) + 1
    _install_state["lines"].append(line)
    if len(_install_state["lines"]) > INSTALL_LOG_MAX_LINES:
        del _install_state["lines"][: len(_install_state["lines"]) - INSTALL_LOG_MAX_LINES]
        _install_state["truncated"] = True


def _normalize_install_state() -> None:
    """防止安装线程异常退出后 UI 一直停留在 running 状态。"""
    if not _install_state.get("running"):
        return
    thread = _install_state.get("thread")
    if thread is None or getattr(thread, "is_alive", lambda: False)():
        return
    if _install_state.get("result") is None:
        from apps.installer.hermes_install import InstallResult

        _install_state["result"] = InstallResult(
            success=False,
            message="安装线程已结束但未返回结果，请查看日志后重试",
            returncode=-1,
        )
    _install_state["running"] = False
    _install_state["finished_at"] = time.time()
