"""用户配置读写"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".hermes-yachiyo"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# 合法的 display_mode 值，与 DisplayMode 枚举保持同步
DisplayModeValue = Literal["window", "bubble", "live2d"]


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


def load_config() -> AppConfig:
    """从磁盘加载配置，不存在则返回默认值"""
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            return AppConfig(**{k: v for k, v in data.items() if k in AppConfig.__dataclass_fields__})
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
