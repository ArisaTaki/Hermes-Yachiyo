"""WebView API 处理

为安装引导窗口提供 JavaScript 可调用的 API。
"""

import logging
import os
import sys
from typing import Dict

from apps.installer.workspace_init import initialize_yachiyo_workspace

logger = logging.getLogger(__name__)


class InstallerWebViewAPI:
    """安装引导 WebView API"""
    
    def initialize_workspace(self) -> Dict[str, any]:
        """初始化 Yachiyo 工作空间
        
        Returns:
            Dict: {"success": bool, "error": str, "created_items": List[str]}
        """
        try:
            logger.info("开始 Yachiyo 工作空间初始化")
            
            success, error, created_items = initialize_yachiyo_workspace()
            
            if success:
                logger.info("工作空间初始化成功: %s 项目创建", len(created_items))
                return {
                    "success": True,
                    "error": None,
                    "created_items": created_items
                }
            else:
                logger.error("工作空间初始化失败: %s", error)
                return {
                    "success": False,
                    "error": error,
                    "created_items": created_items
                }
                
        except Exception as e:
            logger.error("初始化过程异常: %s", e)
            return {
                "success": False,
                "error": f"初始化异常: {e}",
                "created_items": []
            }
    
    def restart_app(self) -> None:
        """重启应用
        
        这个方法会退出当前进程，依赖外部重新启动。
        在生产环境中，可能需要更复杂的重启逻辑。
        """
        logger.info("正在重启应用...")
        try:
            # 延迟退出，确保响应返回给前端
            import threading
            import time
            
            def delayed_exit():
                time.sleep(1)  # 给前端 1 秒时间接收响应
                os._exit(0)    # 强制退出，依赖外部重启
            
            threading.Thread(target=delayed_exit, daemon=True).start()
            
        except Exception as e:
            logger.error("重启失败: %s", e)