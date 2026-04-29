"""显示模式元数据定义。

显示模式只负责桌面常驻入口：
- bubble: 轻量常驻聊天模式
- live2d: 角色聊天壳

主控台是独立 Control Center，不参与 display mode 切换。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModeDescriptor:
    """单个模式的展示元数据。"""

    id: str
    name: str
    icon: str
    description: str
    settings_title: str
    settings_description: str
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "description": self.description,
            "settings_title": self.settings_title,
            "settings_description": self.settings_description,
            "available": self.available,
        }


_MODE_CATALOG: dict[str, ModeDescriptor] = {
    "bubble": ModeDescriptor(
        id="bubble",
        name="Bubble 模式",
        icon="💬",
        description="轻量常驻悬浮聊天模式，支持摘要、短输入与快速展开",
        settings_title="Bubble 设置",
        settings_description="控制气泡大小、置顶、展开方式、摘要内容与轻量外观偏好。",
    ),
    "live2d": ModeDescriptor(
        id="live2d",
        name="Live2D 模式",
        icon="🎭",
        description="角色聊天壳，支持 Live2D 模型加载、回复气泡、快捷输入和预览回退",
        settings_title="Live2D 设置",
        settings_description="控制角色窗口、模型路径、角色交互行为与聊天壳偏好。",
    ),
}


def list_mode_descriptors() -> list[ModeDescriptor]:
    """返回所有模式的元数据。"""
    return list(_MODE_CATALOG.values())


def list_mode_options() -> list[dict[str, Any]]:
    """返回适合直接给前端使用的模式列表。"""
    return [item.to_dict() for item in list_mode_descriptors()]


def get_mode_descriptor(mode_id: str) -> ModeDescriptor:
    """获取单个模式元数据，未知值回退为 bubble。"""
    return _MODE_CATALOG.get(mode_id, _MODE_CATALOG["bubble"])
