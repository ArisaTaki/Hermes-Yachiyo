"""Native Agent capability resolution backed by ModelProfile defaults."""

from __future__ import annotations

from typing import Any

from apps.shell.model_capabilities import lookup_model_supports_vision
from apps.shell.model_profiles import get_model_profile_service


def get_native_image_input_capability() -> dict[str, Any]:
    service = get_model_profile_service()
    defaults = service.get_defaults()
    chat = _available_profile(service, str(defaults.get("chat") or ""))
    vision = _available_profile(service, str(defaults.get("vision") or ""))

    if chat is None:
        return _payload(
            can_attach=False,
            route="blocked",
            reason="请先配置并选择默认对话模型。",
        )

    supports_vision = lookup_model_supports_vision(
        str(chat.get("provider") or ""),
        str(chat.get("model") or ""),
    )
    if supports_vision is True:
        return _payload(
            can_attach=True,
            route="native_chat",
            reason="图片将直接发送给默认对话模型。",
            profile=chat,
            supports_vision=True,
        )
    if vision is not None:
        return _payload(
            can_attach=True,
            route="vision_text",
            reason="图片将先由默认图片识别模型分析，再交给默认对话模型。",
            profile=vision,
            supports_vision=True,
        )
    if supports_vision is False:
        return _payload(
            can_attach=False,
            route="blocked",
            reason="默认对话模型不支持图片输入，请配置默认图片识别模型。",
            profile=chat,
            supports_vision=False,
        )
    return _payload(
        can_attach=True,
        route="native_chat",
        reason="尚未确认默认对话模型的图片能力，将尝试直接发送图片。",
        profile=chat,
        supports_vision=None,
    )


def _available_profile(service: Any, profile_id: str) -> dict[str, Any] | None:
    if not profile_id:
        return None
    try:
        profile = service.get_profile(profile_id)
    except KeyError:
        return None
    if not profile.get("enabled", True) or str(profile.get("status") or "") != "available":
        return None
    return profile


def _payload(
    *,
    can_attach: bool,
    route: str,
    reason: str,
    profile: dict[str, Any] | None = None,
    supports_vision: bool | None = None,
) -> dict[str, Any]:
    profile = profile or {}
    return {
        "can_attach_images": can_attach,
        "mode": "native",
        "route": route,
        "supports_native_vision": supports_vision,
        "requires_vision_pipeline": route == "vision_text",
        "native_disabled": False,
        "provider": str(profile.get("provider") or ""),
        "model": str(profile.get("model") or ""),
        "profile_id": str(profile.get("profile_id") or ""),
        "label": "Native Agent 图片输入" if can_attach else "图片不可用",
        "reason": reason,
    }
