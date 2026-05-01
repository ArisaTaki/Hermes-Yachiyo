"""Hermes Agent 安装引导

提供安装指导和建议，不包含复杂的自动安装逻辑。
专注于给用户明确的手动安装步骤。
"""

import logging
from typing import Any, Dict, List

from packages.protocol.enums import HermesInstallStatus, Platform
from packages.protocol.install import HermesInstallInfo

logger = logging.getLogger(__name__)


class HermesInstallGuide:
    """Hermes Agent 安装引导"""

    @staticmethod
    def get_install_instructions(install_info: HermesInstallInfo) -> Dict[str, Any]:
        """根据检测结果提供安装指导
        
        Args:
            install_info: Hermes 安装检测结果
            
        Returns:
            包含安装指导信息的字典
        """
        if install_info.status == HermesInstallStatus.READY:
            return {
                "status": "ready",
                "message": "Hermes Agent 已正确安装并配置",
                "actions": []
            }
        
        elif install_info.status == HermesInstallStatus.WSL2_REQUIRED:
            return HermesInstallGuide._get_wsl2_instructions()
        
        elif install_info.status == HermesInstallStatus.PLATFORM_UNSUPPORTED:
            return HermesInstallGuide._get_unsupported_platform_instructions(install_info.platform)
        
        elif install_info.status == HermesInstallStatus.NOT_INSTALLED:
            return HermesInstallGuide._get_install_instructions_for_platform(install_info.platform)
        
        elif install_info.status == HermesInstallStatus.INCOMPATIBLE_VERSION:
            return HermesInstallGuide._get_upgrade_instructions(install_info)
        
        elif install_info.status == HermesInstallStatus.INSTALLED_NEEDS_SETUP:
            return {
                "status": "needs_setup",
                "message": "Hermes Agent 已安装，需要完成初始配置",
                "actions": [
                    "Hermes Agent 安装成功，但尚未完成初始配置。",
                    "请在本页的模型配置向导中填写 Provider、模型、Base URL 和 API Key。",
                    "如果需要 Hermes 原生高级配置，也可以打开终端运行：",
                    "  hermes setup",
                    "完成后回到此窗口点击「重新检测」按钮继续。",
                ],
            }

        elif install_info.status == HermesInstallStatus.SETUP_IN_PROGRESS:
            return {
                "status": "setup_in_progress",
                "message": "Hermes Agent 配置进行中",
                "actions": [
                    "hermes setup 正在终端中运行。",
                    "请在终端中完成交互式配置。",
                    "完成后回到此窗口点击「重新检测」按钮继续。",
                ],
            }

        elif install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED:
            return HermesInstallGuide._get_workspace_init_instructions(install_info)
        
        else:
            return {
                "status": "unknown",
                "message": "未知的安装状态",
                "actions": ["请检查系统环境并重新运行检测"]
            }

    @staticmethod
    def _get_wsl2_instructions() -> Dict[str, Any]:
        """WSL2 安装指导"""
        return {
            "status": "wsl2_required", 
            "message": "Windows 用户需要使用 WSL2 运行 Hermes Agent",
            "actions": [
                "1. 安装 WSL2：https://docs.microsoft.com/zh-cn/windows/wsl/install",
                "2. 在 WSL2 中安装 Ubuntu 或其他 Linux 发行版",
                "3. 在 WSL2 Linux 环境中安装 Hermes Agent",
                "4. 在 WSL2 中运行 Hermes-Yachiyo"
            ],
            "links": [
                {
                    "title": "WSL2 安装指南",
                    "url": "https://docs.microsoft.com/zh-cn/windows/wsl/install"
                }
            ]
        }

    @staticmethod
    def _get_unsupported_platform_instructions(platform: Platform) -> Dict[str, Any]:
        """不支持平台的指导"""
        return {
            "status": "unsupported",
            "message": f"当前平台 {platform} 暂不支持",
            "actions": [
                "支持的平台：macOS, Linux, Windows (通过 WSL2)",
                "请在支持的平台上运行 Hermes-Yachiyo"
            ]
        }

    @staticmethod
    def _get_install_instructions_for_platform(platform: Platform) -> Dict[str, Any]:
        """不同平台的 Hermes Agent 安装指导"""
        base_info: Dict[str, Any] = {
            "status": "install_required",
            "message": "需要安装 Hermes Agent"
        }
        
        if platform == Platform.MACOS:
            base_info.update({
                "actions": [
                    "第 1 步 - 准备 macOS 基础工具（第一次使用推荐先做）:",
                    "  xcode-select --install",
                    "  /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"",
                    "  brew update",
                    "  brew install git curl",
                    "",
                    "第 2 步 - 使用官方安装脚本安装 Hermes Agent:",
                    "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup",
                    "",
                    "如果已经安装过 Homebrew、git 和 curl，可以直接从第 2 步开始。",
                    "",
                    "备选方式 - 下载二进制文件:",
                    "  访问 https://github.com/NousResearch/hermes-agent/releases",
                    "  下载 macOS 版本并添加到 PATH"
                ],
                "links": [
                    {
                        "title": "Hermes Agent 发布页",
                        "url": "https://github.com/NousResearch/hermes-agent/releases"
                    }
                ]
            })
        
        elif platform in [Platform.LINUX, Platform.WINDOWS_WSL2]:
            base_info.update({
                "actions": [
                    "方式1 - 使用官方安装脚本:",
                    "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup",
                    "",
                    "方式2 - 下载二进制文件:",
                    "  访问 https://github.com/NousResearch/hermes-agent/releases",
                    "  下载 Linux 版本并添加到 PATH"
                ],
                "links": [
                    {
                        "title": "Hermes Agent 安装文档",
                        "url": "https://github.com/NousResearch/hermes-agent#installation"
                    }
                ]
            })
        
        return base_info

    @staticmethod
    def _get_upgrade_instructions(install_info: HermesInstallInfo) -> Dict[str, Any]:
        """版本升级指导"""
        current_version = "未知"
        if install_info.version_info and install_info.version_info.version:
            current_version = install_info.version_info.version
        
        return {
            "status": "upgrade_required",
            "message": f"需要升级 Hermes Agent (当前版本: {current_version})",
            "actions": [
                "请升级到最新版本的 Hermes Agent",
                "重新运行官方安装脚本:",
                "curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- --skip-setup",
                "或下载最新二进制文件并替换",
                "升级完成后重新启动 Hermes-Yachiyo"
            ]
        }

    @staticmethod
    def _get_workspace_init_instructions(install_info: HermesInstallInfo) -> Dict[str, Any]:
        """Yachiyo 工作空间初始化指导 - Hermes 已安装，需要初始化 Yachiyo 工作空间"""
        hermes_home = install_info.hermes_home or "~/.hermes"
        yachiyo_workspace = f"{hermes_home}/yachiyo"
        
        return {
            "status": "workspace_init_required",
            "message": "Hermes Agent 已安装并可用，需要初始化 Yachiyo 工作空间",
            "actions": [
                "🎯 自动初始化（推荐）",
                "   点击下方\"自动初始化\"按钮，系统将自动创建工作空间",
                "",
                "📁 手动初始化步骤",
                "1. 创建 Yachiyo 工作空间目录",
                f"   mkdir -p {yachiyo_workspace}",
                "",
                "2. 初始化基础结构",
                f"   cd {yachiyo_workspace}",
                "   mkdir -p projects configs logs cache templates",
                "",
                "3. 创建初始化标记",
                "   touch .yachiyo_init",
                "",
                "4. 验证初始化",
                f"   ls -la {yachiyo_workspace}",
                "",
                "5. 重新启动 Hermes-Yachiyo",
                "   工作空间初始化完成后，应用将进入正常模式"
            ],
            "auto_setup_available": True,
            "can_initialize": True
        }


def get_platform_specific_suggestions(platform: Platform) -> List[str]:
    """获取平台特定的建议"""
    if platform == Platform.MACOS:
        return [
            "建议使用官方安装脚本安装 Hermes Agent",
            "确保 Xcode Command Line Tools 已安装"
        ]
    
    elif platform in [Platform.LINUX, Platform.WINDOWS_WSL2]:
        return [
            "确保有 sudo 权限以安装 Hermes Agent",
            "建议使用官方安装脚本"
        ]
    
    elif platform == Platform.WINDOWS_NATIVE:
        return [
            "Windows 用户需要使用 WSL2",
            "不支持在原生 Windows 中直接运行"
        ]
    
    return []

# ── 真实安装执行 ────────────────────────────────────────────────────────────────

import asyncio
import dataclasses
import re
import subprocess

# 官方安装脚本 URL
HERMES_INSTALL_SCRIPT_URL = (
    "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh"
)
HERMES_INSTALL_TIMEOUT_SECONDS = 900.0
_ANSI_CONTROL_RE = re.compile(
    r"(?:\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\)|\x1B[()][A-Za-z0-9])"
)


def clean_terminal_line(line: str) -> str:
    """Remove terminal control sequences while keeping readable output."""
    return _ANSI_CONTROL_RE.sub("", line).replace("\r", "").rstrip()


@dataclasses.dataclass
class InstallResult:
    """hermes 安装执行结果"""

    success: bool
    message: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1

    def to_error_string(self) -> str:
        parts = [self.message] if self.message else []
        if self.returncode not in (-1, 0):
            parts.append(f"exit={self.returncode}")
        if self.stderr:
            parts.append(f"stderr: {self.stderr[:200]}")
        return " | ".join(parts) if parts else "安装失败"


def summarize_install_failure(output: str, returncode: int) -> str:
    """Return a user-facing summary for common installer failures."""
    normalized = output.lower()
    git_network_markers = (
        "rpc failed",
        "early eof",
        "fetch-pack",
        "invalid index-pack",
        "unexpected disconnect",
        "transfer closed with outstanding read data",
    )
    if any(marker in normalized for marker in git_network_markers):
        return (
            "从 GitHub 克隆 Hermes Agent 时网络传输中断。"
            "请检查网络或代理后重试；也可以改用 Releases 二进制安装。"
        )
    if "could not resolve host" in normalized or "failed to connect" in normalized:
        return "无法连接 GitHub 或安装脚本源，请检查网络、代理或 DNS 后重试。"
    return f"安装脚本执行失败（exit={returncode}），请查看上方安装日志中的错误详情"


async def run_hermes_install(
    on_output=None,
    timeout: float = HERMES_INSTALL_TIMEOUT_SECONDS,
) -> InstallResult:
    """运行 Hermes Agent 官方安装脚本。

    执行：下载官方 install.sh 后以 --skip-setup 运行。

    Args:
        on_output: 可选回调 (line: str) → None，实时接收安装输出行
        timeout:   安装超时秒数（默认 15 分钟）

    Returns:
        InstallResult（成功或失败均返回，不抛出）
    """
    from packages.protocol.enums import Platform
    from apps.installer.hermes_check import detect_platform, locate_hermes_binary

    platform = detect_platform()

    # Windows 原生环境不支持
    if platform.value == "windows_native":
        return InstallResult(
            success=False,
            message="Windows 原生环境不支持，请在 WSL2 中安装 Hermes Agent",
            returncode=-1,
        )

    logger.info("开始安装 Hermes Agent（脚本: %s）", HERMES_INSTALL_SCRIPT_URL)

    # 下载后执行：跳过官方交互式 setup，改由 Yachiyo 的 GUI 配置向导处理。
    install_script = (
        'install_script="$(mktemp -t hermes-agent-install.XXXXXX)" || exit 1\n'
        'trap \'rm -f "$install_script"\' EXIT\n'
        f'curl -fsSL {HERMES_INSTALL_SCRIPT_URL} -o "$install_script" || exit $?\n'
        'bash "$install_script" --skip-setup'
    )
    cmd = [
        "bash", "-c",
        install_script,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,   # 合并 stderr 到 stdout，方便实时展示
        )
    except FileNotFoundError:
        return InstallResult(
            success=False,
            message="bash 或 curl 命令未找到，无法执行安装脚本",
            returncode=-1,
        )
    except Exception as exc:
        return InstallResult(
            success=False,
            message=f"启动安装进程失败: {exc}",
            returncode=-1,
        )

    stdout_lines: list[str] = []

    # 实时读取输出，支持回调
    # 用列表包装布尔标志，允许嵌套函数修改（Python 闭包可变性）
    _tui_flag = [False]  # [0]: 是否已打印 TUI 通知行

    try:
        async def _read_output():
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                raw_line = line_bytes.decode(errors="replace").rstrip("\n")
                line = clean_terminal_line(raw_line)

                # 检测 hermes setup 的关键特征文字（而非泛化的 ANSI/TUI 字符）
                # 这些是 setup wizard 独有的文字，installer banner 不会触发
                setup_keywords = (
                    "Setup Wizard",
                    "How would you like to set up Hermes",
                    "Select by number, Enter to confirm",
                    "Quick setup",
                    "Full setup",
                    "configure your Hermes Agent",
                )
                is_setup_line = any(kw in line for kw in setup_keywords)

                if is_setup_line and not _tui_flag[0]:
                    _tui_flag[0] = True
                    # 发送特殊标记，让前端知道需要打开终端做 setup
                    if on_output is not None:
                        try:
                            on_output("__SETUP_TRIGGERED__")
                        except Exception:
                            pass
                    # 发送用户可见的通知
                    notice = (
                        "─── 检测到 Hermes 配置向导，正在打开终端窗口... ───"
                    )
                    stdout_lines.append(notice)
                    if on_output is not None:
                        try:
                            on_output(notice)
                        except Exception:
                            pass

                if not line:
                    continue
                stdout_lines.append(line)
                if on_output is not None:
                    try:
                        on_output(line)
                    except Exception:
                        pass

        await asyncio.wait_for(_read_output(), timeout=timeout)
        await proc.wait()

    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return InstallResult(
            success=False,
            message=f"安装超时（{timeout:.0f}s），进程已终止",
            stdout="\n".join(stdout_lines),
            returncode=-1,
        )

    rc = proc.returncode if proc.returncode is not None else -1
    combined_output = "\n".join(stdout_lines)

    if rc != 0:
        # 安装脚本非零退出时，先检查 hermes 命令是否已经可用。
        # 常见原因：当前 GUI 进程 PATH 尚未刷新，但 hermes 二进制本身已安装成功。
        try:
            hermes_path, needs_env_refresh = locate_hermes_binary()
            if hermes_path is None:
                raise FileNotFoundError("hermes executable not found after install")

            _check = subprocess.run(
                [hermes_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if _check.returncode == 0:
                logger.info(
                    "安装脚本返回 exit=%d，但 hermes 已可用 (%s, %s)，视为安装成功",
                    rc,
                    hermes_path,
                    _check.stdout.strip().splitlines()[0] if _check.stdout.strip() else "unknown version",
                )
                message = "Hermes Agent 安装完成（需要完成 hermes setup 配置）"
                if needs_env_refresh:
                    message = "Hermes Agent 安装完成（已修复当前应用 PATH，需要完成 hermes setup 配置）"
                return InstallResult(
                    success=True,
                    message=message,
                    stdout=combined_output,
                    returncode=0,
                )
        except Exception as _exc:
            logger.debug("安装后 hermes 可用性回退检查失败: %s", _exc)

        return InstallResult(
            success=False,
            message=summarize_install_failure(combined_output, rc),
            stdout=combined_output,
            returncode=rc,
        )

    logger.info("Hermes Agent 安装脚本执行成功")
    return InstallResult(
        success=True,
        message="Hermes Agent 安装完成",
        stdout=combined_output,
        returncode=rc,
    )
