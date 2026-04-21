"""集成服务状态统一产出

Bridge / AstrBot / Hapi 的运行时状态从这里集中获取，
Control Center / Bubble / Live2D / Settings 只消费此模块的结果，不各自拼装。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from apps.bridge.server import get_bridge_state

if TYPE_CHECKING:
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


# ── Bridge 状态 ────────────────────────────────────────────────────────────────

@dataclass
class BridgeStatus:
    """Bridge 运行时状态快照。"""

    # 四状态：disabled / enabled_not_started / running / failed
    state: str
    # 当前配置（已保存到 config.json 的值）
    saved_enabled: bool
    saved_host: str
    saved_port: int
    # 启动时使用的配置（运行时实际生效的值）
    boot_enabled: bool
    boot_host: str
    boot_port: int
    # 配置漂移
    config_dirty: bool
    # 差异明细（仅 config_dirty=True 时有内容）
    drift_details: list[str] = field(default_factory=list)

    @property
    def saved_url(self) -> str:
        return f"http://{self.saved_host}:{self.saved_port}"

    @property
    def boot_url(self) -> str:
        return f"http://{self.boot_host}:{self.boot_port}"

    def to_dict(self) -> dict[str, Any]:
        """生成前端可消费的完整 bridge 状态。"""
        return {
            "state": self.state,
            "enabled": self.saved_enabled,
            "host": self.saved_host,
            "port": self.saved_port,
            "url": self.saved_url,
            "config_dirty": self.config_dirty,
            "drift_details": self.drift_details,
            "boot_config": {
                "enabled": self.boot_enabled,
                "host": self.boot_host,
                "port": self.boot_port,
                "url": self.boot_url,
            },
        }

    def to_dashboard_dict(self) -> dict[str, Any]:
        """仪表盘简化版（向后兼容 running 字段名）。"""
        d = self.to_dict()
        d["running"] = self.state
        return d


def get_bridge_status(config: "AppConfig", boot_config: dict[str, Any]) -> BridgeStatus:
    """计算 Bridge 当前运行状态。

    Args:
        config: 当前已保存的 AppConfig
        boot_config: bridge 启动时快照 {"enabled": bool, "host": str, "port": int}
    """
    # 四状态计算
    if not config.bridge_enabled:
        state = "disabled"
    else:
        raw = get_bridge_state()
        if raw == "running":
            state = "running"
        elif raw == "failed":
            state = "failed"
        else:
            state = "enabled_not_started"

    # 配置漂移检测
    drift: list[str] = []
    if config.bridge_enabled != boot_config["enabled"]:
        old = "启用" if boot_config["enabled"] else "禁用"
        new = "启用" if config.bridge_enabled else "禁用"
        drift.append(f"启用状态: {old} → {new}")
    if config.bridge_host != boot_config["host"]:
        drift.append(f"地址: {boot_config['host']} → {config.bridge_host}")
    if config.bridge_port != boot_config["port"]:
        drift.append(f"端口: {boot_config['port']} → {config.bridge_port}")

    return BridgeStatus(
        state=state,
        saved_enabled=config.bridge_enabled,
        saved_host=config.bridge_host,
        saved_port=config.bridge_port,
        boot_enabled=boot_config["enabled"],
        boot_host=boot_config["host"],
        boot_port=boot_config["port"],
        config_dirty=len(drift) > 0,
        drift_details=drift,
    )


# ── AstrBot 接入状态 ───────────────────────────────────────────────────────────

# AstrBot 接入四状态
ASTRBOT_STATES = {
    "not_configured":             ("⚪ 未配置", "需在 AstrBot 中安装并配置 Hermes-Yachiyo 插件"),
    "configured_not_connected":   ("⏳ 已配置但未连接", "AstrBot 插件已配置，但尚未建立连接"),
    "connected":                  ("✅ 已连接", "AstrBot 正在通过 Bridge 转发 QQ 消息"),
    "unknown":                    ("❓ 状态未知", "无法确定 AstrBot 连接状态"),
}


@dataclass
class AstrBotStatus:
    """AstrBot 接入状态快照。"""

    # 四状态
    state: str
    # 前置条件
    bridge_ready: bool
    bridge_state: str
    # 展示信息
    label: str
    description: str
    # 为什么不可用
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.state,
            "label": self.label,
            "description": self.description,
            "bridge_ready": self.bridge_ready,
            "blockers": self.blockers,
        }


def get_astrbot_status(bridge_status: BridgeStatus) -> AstrBotStatus:
    """计算 AstrBot 接入状态。

    当前阶段为占位逻辑：
    - bridge 未就绪 → configured_not_connected（有 blocker）
    - bridge 就绪 → not_configured（等待用户配置 AstrBot 插件）
    - 未来接入真实健康检查后，可升级为 connected

    Args:
        bridge_status: 当前 Bridge 状态快照
    """
    bridge_ready = bridge_status.state == "running"
    blockers: list[str] = []

    if bridge_status.state == "disabled":
        blockers.append("Bridge 未启用，AstrBot 无法连接")
        state = "not_configured"
    elif bridge_status.state == "failed":
        blockers.append("Bridge 异常退出，AstrBot 无法连接")
        state = "configured_not_connected"
    elif bridge_status.state == "enabled_not_started":
        blockers.append("Bridge 尚未启动完成")
        state = "configured_not_connected"
    else:
        # bridge running — 当前阶段仍为占位，标记为 not_configured
        state = "not_configured"

    # bridge 配置漂移时，AstrBot 可能使用旧地址
    if bridge_status.config_dirty and bridge_ready:
        blockers.append("Bridge 配置已修改但尚未重启，AstrBot 可能使用旧地址")

    label, description = ASTRBOT_STATES[state]
    return AstrBotStatus(
        state=state,
        bridge_ready=bridge_ready,
        bridge_state=bridge_status.state,
        label=label,
        description=description,
        blockers=blockers,
    )


# ── Hapi 接入状态 ──────────────────────────────────────────────────────────────

HAPI_STATES = {
    "not_configured":           ("⚪ 未配置", "Hapi / Codex 执行后端尚未接入"),
    "configured_not_connected": ("⏳ 已配置但未连接", "Hapi 已配置但无法访问"),
    "connected":                ("✅ 已连接", "Hapi 正在提供 Codex CLI 执行服务"),
    "unknown":                  ("❓ 状态未知", "无法确定 Hapi 连接状态"),
}


@dataclass
class HapiStatus:
    """Hapi 接入状态快照。"""

    state: str
    label: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.state,
            "label": self.label,
            "description": self.description,
        }


def get_hapi_status() -> HapiStatus:
    """计算 Hapi 接入状态（当前为占位）。"""
    state = "not_configured"
    label, description = HAPI_STATES[state]
    return HapiStatus(state=state, label=label, description=description)


# ── 统一快照 ───────────────────────────────────────────────────────────────────

@dataclass
class IntegrationSnapshot:
    """全部集成服务的状态快照，一次获取，多处消费。"""

    bridge: BridgeStatus
    astrbot: AstrBotStatus
    hapi: HapiStatus

    def to_dict(self) -> dict[str, Any]:
        return {
            "bridge": self.bridge.to_dict(),
            "astrbot": self.astrbot.to_dict(),
            "hapi": self.hapi.to_dict(),
        }


def get_integration_snapshot(
    config: "AppConfig",
    boot_config: dict[str, Any],
) -> IntegrationSnapshot:
    """一次性获取所有集成服务状态。"""
    bridge = get_bridge_status(config, boot_config)
    astrbot = get_astrbot_status(bridge)
    hapi = get_hapi_status()
    return IntegrationSnapshot(bridge=bridge, astrbot=astrbot, hapi=hapi)
