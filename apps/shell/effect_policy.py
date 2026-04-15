"""设置生效策略定义

集中管理每个可编辑配置项的生效方式，供 update_settings() 返回给前端。
前端根据 effect 类型显示对应提示，用户明确知道哪些改动已生效、哪些需要重启。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class EffectType(StrEnum):
    """设置变更的生效方式。"""

    IMMEDIATE = "immediate"
    """已即时反映到 UI 和内存配置，当前运行时已生效。"""

    REQUIRES_MODE_RESTART = "requires_mode_restart"
    """已保存，需重启当前显示模式后生效（如切换 display_mode）。"""

    REQUIRES_BRIDGE_RESTART = "requires_bridge_restart"
    """已保存，需重启 Bridge 服务后生效（如修改 host/port）。"""

    REQUIRES_APP_RESTART = "requires_app_restart"
    """已保存，需重启整个应用后生效（如托盘开关）。"""


# 每个可编辑字段 → 生效方式 + 前端提示文案
# key 格式与 update_settings() 接收的 key 格式一致
_FIELD_POLICIES: dict[str, tuple[EffectType, str]] = {
    # 顶层字段
    "display_mode":    (EffectType.REQUIRES_MODE_RESTART,
                        "显示模式将在下次启动时生效"),
    "bridge_enabled":  (EffectType.REQUIRES_BRIDGE_RESTART,
                        "Bridge 开关变更需重启 Bridge 后生效"),
    "bridge_host":     (EffectType.REQUIRES_BRIDGE_RESTART,
                        "Bridge 地址变更需重启 Bridge 后生效"),
    "bridge_port":     (EffectType.REQUIRES_BRIDGE_RESTART,
                        "Bridge 端口变更需重启 Bridge 后生效"),
    "tray_enabled":    (EffectType.REQUIRES_APP_RESTART,
                        "托盘设置将在下次启动时生效"),
    # Live2D 嵌套字段
    "live2d.model_name":         (EffectType.IMMEDIATE,
                                  "模型名称已更新"),
    "live2d.model_path":         (EffectType.IMMEDIATE,
                                  "模型路径已更新，已重新校验"),
    "live2d.idle_motion_group":  (EffectType.IMMEDIATE,
                                  "待机动作组已更新"),
    "live2d.enable_expressions": (EffectType.IMMEDIATE,
                                  "表情系统设置已更新"),
    "live2d.enable_physics":     (EffectType.IMMEDIATE,
                                  "物理模拟设置已更新"),
    "live2d.window_on_top":      (EffectType.REQUIRES_MODE_RESTART,
                                  "窗口置顶将在重启 Live2D 模式后生效"),
}


def get_effect(key: str) -> tuple[EffectType, str]:
    """获取指定字段的生效策略。未登记字段返回 IMMEDIATE。"""
    return _FIELD_POLICIES.get(key, (EffectType.IMMEDIATE, "已更新"))


def build_effects_summary(applied_keys: list[str]) -> dict[str, Any]:
    """根据已应用的字段列表，生成统一的生效结果摘要。

    Returns:
        {
          "effects": [
            {"key": "bridge_host", "effect": "requires_bridge_restart", "message": "..."},
            ...
          ],
          "has_immediate": True,
          "has_restart_mode": False,
          "has_restart_bridge": True,
          "has_restart_app": False,
          "hint": "部分配置需重启 Bridge 后生效"
        }
    """
    effects: list[dict[str, str]] = []
    types_seen: set[EffectType] = set()

    for key in applied_keys:
        effect_type, message = get_effect(key)
        effects.append({
            "key": key,
            "effect": effect_type.value,
            "message": message,
        })
        types_seen.add(effect_type)

    # 生成综合提示（优先级：app > bridge > mode > immediate）
    hint = _build_hint(types_seen)

    return {
        "effects": effects,
        "has_immediate": EffectType.IMMEDIATE in types_seen,
        "has_restart_mode": EffectType.REQUIRES_MODE_RESTART in types_seen,
        "has_restart_bridge": EffectType.REQUIRES_BRIDGE_RESTART in types_seen,
        "has_restart_app": EffectType.REQUIRES_APP_RESTART in types_seen,
        "hint": hint,
    }


def _build_hint(types_seen: set[EffectType]) -> str:
    """根据本次涉及的 effect 类型集合，生成一句用户友好的综合提示。"""
    parts: list[str] = []
    if EffectType.REQUIRES_APP_RESTART in types_seen:
        parts.append("重启应用")
    if EffectType.REQUIRES_BRIDGE_RESTART in types_seen:
        parts.append("重启 Bridge")
    if EffectType.REQUIRES_MODE_RESTART in types_seen:
        parts.append("重启显示模式")

    if not parts:
        return "已即时生效"

    only_deferred = EffectType.IMMEDIATE not in types_seen
    prefix = "需" if only_deferred else "部分配置需"
    return prefix + "、".join(parts) + "后生效"
