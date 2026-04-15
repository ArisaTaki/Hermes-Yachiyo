"""AstrBot 插件配置"""

from __future__ import annotations

from dataclasses import dataclass, field

# 默认后端地址
DEFAULT_HERMES_URL = "http://127.0.0.1:8420"
DEFAULT_HAPI_URL = "http://127.0.0.1:8430"


@dataclass
class PluginConfig:
    """插件运行时配置。

    可由 AstrBot 宿主注入，也可直接用默认值实例化。
    """

    # Hermes-Yachiyo Bridge 地址
    hermes_url: str = DEFAULT_HERMES_URL
    # Hapi（Codex 执行后端）地址
    hapi_url: str = DEFAULT_HAPI_URL
    # 允许使用命令的发送者 QQ 号列表；空列表 = 不限制
    allowed_senders: list[str] = field(default_factory=list)
    # HTTP 超时（秒）
    timeout: float = 10.0
