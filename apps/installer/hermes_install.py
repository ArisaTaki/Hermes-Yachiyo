"""Hermes Agent 安装引导

提供安装指导和建议，不包含复杂的自动安装逻辑。
专注于给用户明确的手动安装步骤。
"""

import logging
from typing import Dict, List

from packages.protocol.enums import HermesInstallStatus, Platform
from packages.protocol.install import HermesInstallInfo

logger = logging.getLogger(__name__)


class HermesInstallGuide:
    """Hermes Agent 安装引导"""

    @staticmethod
    def get_install_instructions(install_info: HermesInstallInfo) -> Dict[str, any]:
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
        
        elif install_info.status == HermesInstallStatus.INSTALLED_NOT_INITIALIZED:
            return HermesInstallGuide._get_workspace_init_instructions(install_info)
        
        else:
            return {
                "status": "unknown",
                "message": "未知的安装状态",
                "actions": ["请检查系统环境并重新运行检测"]
            }

    @staticmethod
    def _get_wsl2_instructions() -> Dict[str, any]:
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
    def _get_unsupported_platform_instructions(platform: Platform) -> Dict[str, any]:
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
    def _get_install_instructions_for_platform(platform: Platform) -> Dict[str, any]:
        """不同平台的 Hermes Agent 安装指导"""
        base_info = {
            "status": "install_required",
            "message": "需要安装 Hermes Agent"
        }
        
        if platform == Platform.MACOS:
            base_info.update({
                "actions": [
                    "方式1 - 使用官方安装脚本 (推荐):",
                    "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash",
                    "",
                    "方式2 - 下载二进制文件:",
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
                    "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash",
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
    def _get_upgrade_instructions(install_info: HermesInstallInfo) -> Dict[str, any]:
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
                "curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash",
                "或下载最新二进制文件并替换",
                "升级完成后重新启动 Hermes-Yachiyo"
            ]
        }

    @staticmethod
    def _get_workspace_init_instructions(install_info: HermesInstallInfo) -> Dict[str, any]:
        """Yachiyo 工作空间初始化指导 - Hermes 已安装，需要初始化 Yachiyo 工作空间"""
        hermes_home = install_info.hermes_home or "~/.hermes"
        yachiyo_workspace = f"{hermes_home}/yachiyo"
        
        return {
            "status": "workspace_init_required",
            "message": "Hermes Agent 已安装并可用，需要初始化 Yachiyo 工作空间",
            "actions": [
                "1. 创建 Yachiyo 工作空间目录",
                f"   mkdir -p {yachiyo_workspace}",
                "",
                "2. 初始化工作空间结构",
                f"   cd {yachiyo_workspace}",
                "   touch .yachiyo_init",
                "",
                "3. 创建项目配置（可选）",
                "   mkdir -p projects configs logs",
                "",
                "4. 验证初始化",
                f"   ls -la {yachiyo_workspace}",
                "",
                "5. 重新启动 Hermes-Yachiyo",
                "   工作空间初始化完成后，应用将进入正常模式"
            ],
            "auto_setup_available": True
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