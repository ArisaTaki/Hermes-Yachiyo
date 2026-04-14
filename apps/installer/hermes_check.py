"""Hermes Agent 安装检测

检测 Hermes Agent 是否已安装，版本是否兼容，平台是否支持。
"""

import logging
import os
import platform
import subprocess
from typing import Tuple

from packages.protocol.enums import HermesInstallStatus, Platform
from packages.protocol.install import HermesInstallInfo, HermesVersionInfo

logger = logging.getLogger(__name__)

# Hermes 最低要求版本（示例）
HERMES_MIN_VERSION = "0.8.0"

# 支持的平台映射
PLATFORM_MAPPING = {
    "Darwin": Platform.MACOS,
    "Linux": Platform.LINUX,
    "Windows": Platform.WINDOWS_NATIVE,  # 需要检测是否在 WSL2
}


def detect_platform() -> Platform:
    """检测当前运行平台"""
    sys_platform = platform.system()
    
    if sys_platform == "Windows":
        # 检测是否在 WSL2 环境中
        if _is_wsl2():
            return Platform.WINDOWS_WSL2
        return Platform.WINDOWS_NATIVE
    
    return PLATFORM_MAPPING.get(sys_platform, Platform.WINDOWS_NATIVE)


def _is_wsl2() -> bool:
    """检测是否在 WSL2 环境中运行"""
    try:
        # 检查 /proc/version 是否包含 WSL2 标识
        if os.path.exists("/proc/version"):
            with open("/proc/version", "r") as f:
                content = f.read()
                return "WSL2" in content or "microsoft" in content.lower()
    except Exception:
        pass
    
    # 检查环境变量
    return os.getenv("WSL_DISTRO_NAME") is not None


def check_hermes_command() -> Tuple[bool, str | None]:
    """检查 hermes 命令是否存在且可执行
    
    Returns:
        (exists, error_message)
    """
    try:
        result = subprocess.run(
            ["hermes", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return True, None
        else:
            return False, f"hermes 命令执行失败: {result.stderr.strip()}"
    except FileNotFoundError:
        return False, "hermes 命令未找到，请确认已安装 Hermes Agent"
    except subprocess.TimeoutExpired:
        return False, "hermes 命令执行超时"
    except Exception as e:
        return False, f"检查 hermes 命令时出错: {str(e)}"


def get_hermes_version() -> HermesVersionInfo | None:
    """获取 Hermes Agent 版本信息"""
    try:
        result = subprocess.run(
            ["hermes", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return None
        
        version_text = result.stdout.strip()
        # 解析版本信息（格式可能是 "hermes 1.2.3" 或包含更多信息）
        version_info = HermesVersionInfo()
        
        # 简单解析版本号
        parts = version_text.split()
        for part in parts:
            if part[0].isdigit() and "." in part:
                version_info.version = part
                break
        
        return version_info
    except Exception as e:
        logger.warning("获取 Hermes 版本信息失败: %s", e)
        return None


def is_version_compatible(version: str) -> bool:
    """检查版本是否兼容（简单字符串比较）"""
    try:
        # 简单的版本比较（实际应该用 packaging.version）
        return version >= HERMES_MIN_VERSION
    except Exception:
        return False


def get_hermes_home() -> str:
    """获取 HERMES_HOME 路径（当前或推荐）"""
    # 1. 检查环境变量
    hermes_home = os.getenv("HERMES_HOME")
    if hermes_home and os.path.exists(hermes_home):
        return hermes_home
    
    # 2. 默认路径策略
    home_dir = os.path.expanduser("~")
    default_hermes_home = os.path.join(home_dir, ".hermes")
    
    return default_hermes_home


def check_hermes_installation() -> HermesInstallInfo:
    """完整的 Hermes Agent 安装检测
    
    Returns:
        HermesInstallInfo: 详细的检测结果
    """
    install_info = HermesInstallInfo(
        status=HermesInstallStatus.NOT_CHECKED,
        platform=detect_platform()
    )
    
    # 1. 平台支持检查
    if install_info.platform == Platform.WINDOWS_NATIVE:
        install_info.status = HermesInstallStatus.WSL2_REQUIRED
        install_info.suggestions = [
            "Windows 用户需要使用 WSL2 运行 Hermes Agent",
            "请安装 WSL2 并在 Linux 环境中运行 Hermes-Yachiyo"
        ]
        return install_info
    
    if install_info.platform not in [Platform.MACOS, Platform.LINUX, Platform.WINDOWS_WSL2]:
        install_info.status = HermesInstallStatus.PLATFORM_UNSUPPORTED
        install_info.error_message = f"不支持的平台: {install_info.platform}"
        return install_info
    
    # 2. 命令存在检查
    command_exists, error_message = check_hermes_command()
    install_info.command_exists = command_exists
    
    if not command_exists:
        install_info.status = HermesInstallStatus.NOT_INSTALLED
        install_info.error_message = error_message
        install_info.suggestions = [
            "请安装 Hermes Agent: https://github.com/hermesagent/hermes",
            "确保 hermes 命令在 PATH 环境变量中"
        ]
        return install_info
    
    # 3. 版本兼容性检查
    version_info = get_hermes_version()
    install_info.version_info = version_info
    
    if not version_info or not version_info.version:
        install_info.status = HermesInstallStatus.INCOMPATIBLE_VERSION
        install_info.error_message = "无法获取 Hermes 版本信息"
        install_info.suggestions = [
            "请检查 Hermes Agent 安装是否完整",
            f"建议使用 Hermes Agent {HERMES_MIN_VERSION}+ 版本"
        ]
        return install_info
    
    if not is_version_compatible(version_info.version):
        install_info.status = HermesInstallStatus.INCOMPATIBLE_VERSION
        install_info.error_message = f"Hermes 版本 {version_info.version} 不兼容，需要 {HERMES_MIN_VERSION}+"
        install_info.suggestions = [
            f"请升级 Hermes Agent 到 {HERMES_MIN_VERSION}+ 版本"
        ]
        return install_info
    
    # 4. HERMES_HOME 检查
    hermes_home = get_hermes_home()
    install_info.hermes_home = hermes_home
    
    if not os.getenv("HERMES_HOME"):
        install_info.status = HermesInstallStatus.SETUP_REQUIRED
        install_info.suggestions = [
            f"建议设置 HERMES_HOME 环境变量: {hermes_home}",
            "运行 Hermes 环境设置以完成配置"
        ]
    else:
        install_info.status = HermesInstallStatus.INSTALLED
    
    return install_info