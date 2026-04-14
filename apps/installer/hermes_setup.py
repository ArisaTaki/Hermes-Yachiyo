"""Hermes Agent 环境设置

负责 HERMES_HOME 规划、环境变量配置、目录结构初始化。
"""

import logging
import os
import shutil
from pathlib import Path
from typing import Tuple

from packages.protocol.install import HermesSetupRequest, HermesSetupResponse

logger = logging.getLogger(__name__)


class HermesEnvironmentSetup:
    """Hermes Agent 环境设置"""

    @staticmethod
    def get_default_hermes_home() -> str:
        """获取默认的 HERMES_HOME 路径"""
        home_dir = Path.home()
        return str(home_dir / ".hermes")

    @staticmethod
    def get_hermes_yachiyo_workspace() -> str:
        """获取 Hermes-Yachiyo 专用工作空间路径
        
        在 HERMES_HOME 下创建 yachiyo 子目录，避免与其他 Hermes 应用冲突
        """
        hermes_home = HermesEnvironmentSetup.get_effective_hermes_home()
        return str(Path(hermes_home) / "yachiyo")

    @staticmethod
    def get_effective_hermes_home() -> str:
        """获取当前有效的 HERMES_HOME 路径"""
        # 优先使用环境变量
        hermes_home = os.getenv("HERMES_HOME")
        if hermes_home:
            return hermes_home
        
        # 使用默认路径
        return HermesEnvironmentSetup.get_default_hermes_home()

    @staticmethod
    def validate_hermes_home(hermes_home: str) -> Tuple[bool, str]:
        """验证 HERMES_HOME 路径是否有效
        
        Args:
            hermes_home: 要验证的路径
            
        Returns:
            (is_valid, error_message)
        """
        try:
            path = Path(hermes_home)
            
            # 检查路径是否为绝对路径
            if not path.is_absolute():
                return False, "HERMES_HOME 必须是绝对路径"
            
            # 检查父目录是否存在且可写
            parent = path.parent
            if not parent.exists():
                return False, f"父目录不存在: {parent}"
            
            if not os.access(parent, os.W_OK):
                return False, f"没有写入权限: {parent}"
            
            # 检查目标路径
            if path.exists():
                if not path.is_dir():
                    return False, f"路径已存在但不是目录: {path}"
                
                if not os.access(path, os.W_OK):
                    return False, f"没有写入权限: {path}"
            
            return True, ""
        
        except Exception as e:
            return False, f"路径验证失败: {str(e)}"

    @staticmethod
    def create_hermes_directories(hermes_home: str) -> Tuple[bool, str]:
        """创建 Hermes 相关目录结构
        
        Args:
            hermes_home: HERMES_HOME 路径
            
        Returns:
            (success, message)
        """
        try:
            base_path = Path(hermes_home)
            yachiyo_path = base_path / "yachiyo"
            
            # 创建目录结构
            directories = [
                base_path,
                yachiyo_path,
                yachiyo_path / "logs",
                yachiyo_path / "memory",
                yachiyo_path / "tasks",
                yachiyo_path / "config",
            ]
            
            for directory in directories:
                directory.mkdir(parents=True, exist_ok=True)
                logger.info(f"创建目录: {directory}")
            
            # 创建简单的配置文件
            config_file = yachiyo_path / "config" / "hermes_yachiyo.toml"
            if not config_file.exists():
                config_content = """# Hermes-Yachiyo 配置文件
[hermes]
# Hermes Agent 相关配置
workspace = "yachiyo"

[yachiyo]
# Yachiyo 应用配置
version = "0.1.0"
"""
                config_file.write_text(config_content, encoding="utf-8")
            
            return True, f"HERMES_HOME 环境已设置: {hermes_home}"
        
        except Exception as e:
            logger.error(f"创建目录结构失败: {e}")
            return False, f"创建目录结构失败: {str(e)}"

    @staticmethod
    def setup_environment_variables(hermes_home: str, persistent: bool = True) -> Tuple[bool, str]:
        """设置环境变量
        
        Args:
            hermes_home: HERMES_HOME 路径
            persistent: 是否持久化到 shell 配置文件
            
        Returns:
            (success, message)
        """
        try:
            # 设置当前会话的环境变量
            os.environ["HERMES_HOME"] = hermes_home
            
            if not persistent:
                return True, "环境变量已设置（仅当前会话）"
            
            # 持久化到 shell 配置文件
            home_dir = Path.home()
            shell_configs = [
                home_dir / ".bashrc",
                home_dir / ".zshrc", 
                home_dir / ".profile"
            ]
            
            env_line = f'export HERMES_HOME="{hermes_home}"\n'
            
            for config_file in shell_configs:
                if config_file.exists():
                    try:
                        # 检查是否已经存在 HERMES_HOME 设置
                        content = config_file.read_text(encoding="utf-8")
                        if "HERMES_HOME" in content:
                            logger.info(f"HERMES_HOME 已在 {config_file} 中存在")
                            continue
                        
                        # 添加环境变量
                        with config_file.open("a", encoding="utf-8") as f:
                            f.write(f"\n# Hermes-Yachiyo 设置\n")
                            f.write(env_line)
                        
                        logger.info(f"已添加 HERMES_HOME 到 {config_file}")
                        
                    except Exception as e:
                        logger.warning(f"写入 {config_file} 失败: {e}")
                        continue
            
            return True, "环境变量已设置并持久化"
        
        except Exception as e:
            logger.error(f"设置环境变量失败: {e}")
            return False, f"设置环境变量失败: {str(e)}"

    @staticmethod
    def setup_hermes_environment(request: HermesSetupRequest) -> HermesSetupResponse:
        """完整的 Hermes 环境设置流程
        
        Args:
            request: 设置请求
            
        Returns:
            设置响应
        """
        # 确定 HERMES_HOME 路径
        hermes_home = request.hermes_home
        if not hermes_home:
            hermes_home = HermesEnvironmentSetup.get_default_hermes_home()
        
        # 验证路径
        is_valid, error_msg = HermesEnvironmentSetup.validate_hermes_home(hermes_home)
        if not is_valid:
            return HermesSetupResponse(
                success=False,
                hermes_home=hermes_home,
                message=f"HERMES_HOME 路径无效: {error_msg}"
            )
        
        # 创建目录结构
        create_success, create_msg = HermesEnvironmentSetup.create_hermes_directories(hermes_home)
        if not create_success:
            return HermesSetupResponse(
                success=False,
                hermes_home=hermes_home,
                message=create_msg
            )
        
        # 设置环境变量
        env_success, env_msg = HermesEnvironmentSetup.setup_environment_variables(
            hermes_home, 
            persistent=request.auto_setup
        )
        if not env_success:
            return HermesSetupResponse(
                success=False,
                hermes_home=hermes_home,
                message=env_msg
            )
        
        # 成功响应
        restart_required = request.auto_setup and not os.getenv("HERMES_HOME")
        
        return HermesSetupResponse(
            success=True,
            hermes_home=hermes_home,
            message=f"Hermes 环境设置完成。{env_msg}",
            restart_required=restart_required
        )