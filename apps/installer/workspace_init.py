"""Yachiyo 工作空间初始化

在 Hermes Agent 已安装的基础上，初始化 Yachiyo 工作空间。
不涉及 Hermes 官方配置，只管理 Yachiyo 应用层的工作空间。
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


class YachiyoWorkspaceInitializer:
    """Yachiyo 工作空间初始化器"""
    
    def __init__(self, hermes_home: str = None):
        """初始化器
        
        Args:
            hermes_home: Hermes home 路径，默认从环境变量或 ~/.hermes
        """
        if hermes_home:
            self.hermes_home = hermes_home
        else:
            # 优先环境变量，否则使用默认路径
            self.hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
        
        self.yachiyo_workspace = os.path.join(self.hermes_home, "yachiyo")
    
    def check_prerequisites(self) -> Tuple[bool, str]:
        """检查初始化前提条件
        
        Returns:
            Tuple[bool, str]: (是否满足前提条件, 错误信息)
        """
        try:
            # 1. 检查 Hermes home 是否存在（如果设置了 HERMES_HOME）
            hermes_home_env = os.getenv("HERMES_HOME")
            if hermes_home_env and not os.path.exists(hermes_home_env):
                return False, f"HERMES_HOME 目录不存在: {hermes_home_env}"
            
            # 2. 确保父目录存在或可创建
            try:
                os.makedirs(self.hermes_home, exist_ok=True)
            except PermissionError:
                return False, f"无法创建或访问 Hermes home: {self.hermes_home}"
            
            # 3. 检查工作空间是否已存在
            if os.path.exists(self.yachiyo_workspace):
                init_file = os.path.join(self.yachiyo_workspace, ".yachiyo_init")
                if os.path.exists(init_file):
                    return False, "Yachiyo 工作空间已初始化"
                else:
                    logger.info("发现未完成初始化的工作空间目录，将继续初始化")
            
            return True, ""
            
        except Exception as e:
            logger.error("前提条件检查失败: %s", e)
            return False, f"检查失败: {e}"
    
    def create_workspace_structure(self) -> Tuple[bool, str]:
        """创建工作空间目录结构
        
        Returns:
            Tuple[bool, str]: (是否成功, 错误信息)
        """
        try:
            # 创建主工作空间目录
            os.makedirs(self.yachiyo_workspace, exist_ok=True)
            
            # 创建子目录结构
            subdirs = [
                "projects",    # 项目配置和数据
                "configs",     # Yachiyo 应用配置
                "logs",        # Yachiyo 应用日志
                "cache",       # 临时缓存
                "templates"    # 配置模板
            ]
            
            created_dirs = []
            for subdir in subdirs:
                dir_path = os.path.join(self.yachiyo_workspace, subdir)
                os.makedirs(dir_path, exist_ok=True)
                created_dirs.append(subdir)
                logger.debug("创建目录: %s", dir_path)
            
            logger.info("成功创建工作空间目录结构: %s", ", ".join(created_dirs))
            return True, ""
            
        except Exception as e:
            logger.error("创建目录结构失败: %s", e)
            return False, f"创建失败: {e}"
    
    def create_default_configs(self) -> Tuple[bool, str]:
        """创建默认配置文件
        
        Returns:
            Tuple[bool, str]: (是否成功, 错误信息)  
        """
        try:
            configs_dir = os.path.join(self.yachiyo_workspace, "configs")
            
            # 1. 创建主配置文件
            main_config = {
                "version": "1.0.0",
                "workspace_path": self.yachiyo_workspace,
                "hermes_home": self.hermes_home,
                "created_at": "2026-04-14T08:22:47Z",
                "settings": {
                    "auto_start": False,
                    "log_level": "INFO",
                    "max_log_files": 10
                }
            }
            
            config_file = os.path.join(configs_dir, "yachiyo.json")
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(main_config, f, indent=2, ensure_ascii=False)
            
            # 2. 创建环境配置文件
            env_config = {
                "development": {
                    "debug": True,
                    "bridge_port": 8080
                },
                "production": {
                    "debug": False,
                    "bridge_port": 8080
                }
            }
            
            env_file = os.path.join(configs_dir, "environments.json")
            with open(env_file, "w", encoding="utf-8") as f:
                json.dump(env_config, f, indent=2, ensure_ascii=False)
            
            # 3. 创建项目模板配置
            project_template = {
                "name": "default",
                "description": "Default project template for Yachiyo",
                "structure": {
                    "commands": [],
                    "integrations": []
                }
            }
            
            template_file = os.path.join(self.yachiyo_workspace, "templates", "default.json")
            with open(template_file, "w", encoding="utf-8") as f:
                json.dump(project_template, f, indent=2, ensure_ascii=False)
            
            logger.info("成功创建默认配置文件")
            return True, ""
            
        except Exception as e:
            logger.error("创建配置文件失败: %s", e)
            return False, f"配置创建失败: {e}"
    
    def create_init_marker(self) -> Tuple[bool, str]:
        """创建初始化标记文件
        
        Returns:
            Tuple[bool, str]: (是否成功, 错误信息)
        """
        try:
            init_file = os.path.join(self.yachiyo_workspace, ".yachiyo_init")
            init_data = {
                "initialized_at": "2026-04-14T08:22:47Z",
                "version": "1.0.0",
                "workspace_path": self.yachiyo_workspace,
                "hermes_home": self.hermes_home
            }
            
            with open(init_file, "w", encoding="utf-8") as f:
                json.dump(init_data, f, indent=2, ensure_ascii=False)
            
            logger.info("创建初始化标记文件: %s", init_file)
            return True, ""
            
        except Exception as e:
            logger.error("创建标记文件失败: %s", e)
            return False, f"标记文件创建失败: {e}"
    
    def initialize_workspace(self) -> Tuple[bool, str, List[str]]:
        """执行完整工作空间初始化
        
        Returns:
            Tuple[bool, str, List[str]]: (是否成功, 错误信息, 创建的文件列表)
        """
        created_items = []
        
        try:
            # 1. 检查前提条件
            prereq_ok, prereq_error = self.check_prerequisites()
            if not prereq_ok:
                return False, prereq_error, created_items
            
            # 2. 创建目录结构
            dirs_ok, dirs_error = self.create_workspace_structure()
            if not dirs_ok:
                return False, dirs_error, created_items
            created_items.append(f"工作空间目录: {self.yachiyo_workspace}")
            
            # 3. 创建配置文件
            config_ok, config_error = self.create_default_configs()
            if not config_ok:
                return False, config_error, created_items
            created_items.extend([
                "configs/yachiyo.json",
                "configs/environments.json", 
                "templates/default.json"
            ])
            
            # 4. 创建初始化标记
            marker_ok, marker_error = self.create_init_marker()
            if not marker_ok:
                return False, marker_error, created_items
            created_items.append(".yachiyo_init")
            
            logger.info("Yachiyo 工作空间初始化完成: %s", self.yachiyo_workspace)
            return True, "", created_items
            
        except Exception as e:
            logger.error("工作空间初始化失败: %s", e)
            return False, f"初始化失败: {e}", created_items


def initialize_yachiyo_workspace(hermes_home: str = None) -> Tuple[bool, str, List[str]]:
    """便捷函数：初始化 Yachiyo 工作空间
    
    Args:
        hermes_home: Hermes home 路径，默认自动检测
        
    Returns:
        Tuple[bool, str, List[str]]: (是否成功, 错误信息, 创建的文件列表)
    """
    initializer = YachiyoWorkspaceInitializer(hermes_home)
    return initializer.initialize_workspace()


def get_workspace_status(hermes_home: str = None) -> Dict[str, any]:
    """获取工作空间状态信息
    
    Args:
        hermes_home: Hermes home 路径，默认自动检测
        
    Returns:
        工作空间状态信息字典
    """
    if hermes_home:
        workspace_path = os.path.join(hermes_home, "yachiyo")
    else:
        hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
        workspace_path = os.path.join(hermes_home, "yachiyo")
    
    status = {
        "hermes_home": hermes_home,
        "workspace_path": workspace_path,
        "exists": os.path.exists(workspace_path),
        "initialized": False,
        "init_file_exists": False,
        "created_at": None
    }
    
    if status["exists"]:
        init_file = os.path.join(workspace_path, ".yachiyo_init")
        status["init_file_exists"] = os.path.exists(init_file)
        
        if status["init_file_exists"]:
            status["initialized"] = True
            try:
                with open(init_file, "r", encoding="utf-8") as f:
                    init_data = json.load(f)
                    status["created_at"] = init_data.get("initialized_at")
            except Exception:
                pass
    
    return status