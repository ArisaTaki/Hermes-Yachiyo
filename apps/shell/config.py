"""用户配置读写"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".hermes-yachiyo"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# 合法的 display_mode 值，与 DisplayMode 枚举保持同步
DisplayModeValue = Literal["window", "bubble", "live2d"]


@dataclass
class Live2DConfig:
    """Live2D 模式配置骨架。

    当前字段为占位，等待 Live2DRenderer 实现后逐步填充。
    """

    model_name: str = ""              # 角色模型名（如 "hiyori"），空字符串表示未配置
    model_path: str = ""              # 模型目录路径（含 .moc3 文件），空字符串表示未配置
    idle_motion_group: str = "Idle"   # 待机动作组名（Live2D Cubism 约定）
    enable_expressions: bool = False  # 是否启用表情系统（等待渲染器支持）
    enable_physics: bool = False      # 是否启用物理模拟（等待渲染器支持）
    window_on_top: bool = True        # 角色窗口是否置顶

    def is_model_configured(self) -> bool:
        """是否已配置模型（名称和路径都不为空）。"""
        return bool(self.model_name and self.model_path)


@dataclass
class AppConfig:
    """应用配置"""

    bridge_host: str = "127.0.0.1"
    bridge_port: int = 8420
    bridge_enabled: bool = True
    display_mode: DisplayModeValue = "window"   # 合法值见 DisplayMode 枚举
    tray_enabled: bool = True
    start_minimized: bool = False
    log_level: str = "INFO"
    live2d: Live2DConfig = field(default_factory=Live2DConfig)


def load_config() -> AppConfig:
    """从磁盘加载配置，不存在则返回默认值"""
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            # 处理嵌套的 live2d 配置
            live2d_data = data.pop("live2d", {})
            live2d = Live2DConfig(**{
                k: v for k, v in live2d_data.items()
                if k in Live2DConfig.__dataclass_fields__
            }) if live2d_data else Live2DConfig()
            config = AppConfig(
                **{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__}
            )
            config.live2d = live2d
            return config
        except Exception:
            logger.warning("配置文件读取失败，使用默认配置")
    return AppConfig()


def save_config(config: AppConfig) -> None:
    """将配置写入磁盘"""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps(asdict(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
