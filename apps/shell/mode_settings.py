"""模式设置序列化与更新逻辑。"""

from __future__ import annotations

import logging
from typing import Any

from apps.shell.config import (
    AppConfig,
    BubbleModeConfig,
    Live2DModeConfig,
    ModelSummary,
    WindowModeConfig,
    save_config,
)
from apps.shell.effect_policy import build_effects_summary
from apps.shell.mode_catalog import get_mode_descriptor, list_mode_options

logger = logging.getLogger(__name__)


def _serialize_summary(summary: ModelSummary | None) -> dict[str, Any]:
    if summary is None:
        return {"available": False}
    return {
        "available": not summary.is_empty(),
        "model3_json": summary.model3_json,
        "moc3_file": summary.moc3_file,
        "found_in_subdir": summary.found_in_subdir,
        "subdir_name": summary.subdir_name,
        "extra_moc3_count": summary.extra_moc3_count,
        "primary_model3_json_abs": summary.primary_model3_json_abs,
        "primary_moc3_abs": summary.primary_moc3_abs,
        "renderer_entry": summary.renderer_entry,
    }

_TOP_LEVEL_FIELDS: dict[str, type] = {
    "display_mode": str,
    "bridge_enabled": bool,
    "bridge_host": str,
    "bridge_port": int,
    "tray_enabled": bool,
}

_MODE_FIELDS: dict[str, dict[str, type]] = {
    "window_mode": {
        "width": int,
        "height": int,
        "recent_sessions_limit": int,
        "recent_messages_limit": int,
        "open_chat_on_start": bool,
        "show_runtime_panel": bool,
        "show_mode_overview": bool,
    },
    "bubble_mode": {
        "width": int,
        "height": int,
        "position_x": int,
        "position_y": int,
        "always_on_top": bool,
        "edge_snap": bool,
        "expanded_on_start": bool,
        "expand_trigger": str,
        "default_display": str,
        "show_unread_dot": bool,
        "auto_hide": bool,
        "opacity": float,
        "summary_count": int,
    },
    "live2d_mode": {
        "model_name": str,
        "model_path": str,
        "width": int,
        "height": int,
        "position_x": int,
        "position_y": int,
        "window_on_top": bool,
        "show_reply_bubble": bool,
        "default_open_behavior": str,
        "click_action": str,
        "auto_open_chat_window": bool,
        "enable_quick_input": bool,
        "idle_motion_group": str,
        "enable_expressions": bool,
        "enable_physics": bool,
    },
}

_MODE_KEY_ALIASES = {
    "live2d": "live2d_mode",
    "bubble": "bubble_mode",
    "window": "window_mode",
}


def _coerce_numeric(expected: type, value: Any) -> Any:
    if expected is int and isinstance(value, float) and value == int(value):
        return int(value)
    if expected is float and isinstance(value, int):
        return float(value)
    return value


def _validate_field(key: str, value: Any) -> str | None:
    if key == "display_mode" and value not in {"window", "bubble", "live2d"}:
        return f"无效的显示模式: {value}"
    if key == "bridge_port" and not (1024 <= value <= 65535):
        return "bridge_port 须在 1024-65535 之间"
    if key.endswith(".width") or key.endswith(".height"):
        if value < 240:
            return f"{key} 不能小于 240"
    if key.endswith(".recent_sessions_limit") and not (1 <= value <= 10):
        return "recent_sessions_limit 须在 1-10 之间"
    if key.endswith(".recent_messages_limit") and not (1 <= value <= 10):
        return "recent_messages_limit 须在 1-10 之间"
    if key.endswith(".summary_count") and not (1 <= value <= 3):
        return "summary_count 须在 1-3 之间"
    if key.endswith(".opacity") and not (0.2 <= value <= 1.0):
        return "opacity 须在 0.2-1.0 之间"
    if key.endswith(".expand_trigger") and value not in {"click", "hover"}:
        return "expand_trigger 仅支持 click / hover"
    if key.endswith(".default_display") and value not in {"icon", "summary", "recent_reply"}:
        return "default_display 仅支持 icon / summary / recent_reply"
    if key.endswith(".default_open_behavior") and value not in {"stage", "reply_bubble", "chat_input"}:
        return "default_open_behavior 仅支持 stage / reply_bubble / chat_input"
    if key.endswith(".click_action") and value not in {"focus_stage", "open_chat", "toggle_reply"}:
        return "click_action 仅支持 focus_stage / open_chat / toggle_reply"
    return None


def _mode_object(config: AppConfig, mode_key: str) -> WindowModeConfig | BubbleModeConfig | Live2DModeConfig:
    return getattr(config, mode_key)


def serialize_window_mode(config: AppConfig) -> dict[str, Any]:
    mode = config.window_mode
    return {
        "id": "window",
        "title": get_mode_descriptor("window").settings_title,
        "summary": f"{mode.width}×{mode.height} · 最近会话 {mode.recent_sessions_limit} 条 · 最近消息 {mode.recent_messages_limit} 条",
        "config": {
            "width": mode.width,
            "height": mode.height,
            "recent_sessions_limit": mode.recent_sessions_limit,
            "recent_messages_limit": mode.recent_messages_limit,
            "open_chat_on_start": mode.open_chat_on_start,
            "show_runtime_panel": mode.show_runtime_panel,
            "show_mode_overview": mode.show_mode_overview,
        },
    }


def serialize_bubble_mode(config: AppConfig) -> dict[str, Any]:
    mode = config.bubble_mode
    return {
        "id": "bubble",
        "title": get_mode_descriptor("bubble").settings_title,
        "summary": f"{mode.width}×{mode.height} · {mode.default_display} · 摘要 {mode.summary_count} 条",
        "config": {
            "width": mode.width,
            "height": mode.height,
            "position_x": mode.position_x,
            "position_y": mode.position_y,
            "always_on_top": mode.always_on_top,
            "edge_snap": mode.edge_snap,
            "expanded_on_start": mode.expanded_on_start,
            "expand_trigger": mode.expand_trigger,
            "default_display": mode.default_display,
            "show_unread_dot": mode.show_unread_dot,
            "auto_hide": mode.auto_hide,
            "opacity": mode.opacity,
            "summary_count": mode.summary_count,
        },
    }


def serialize_live2d_mode(config: AppConfig) -> dict[str, Any]:
    mode = config.live2d_mode
    model_state = mode.validate()
    summary = mode.scan()
    return {
        "id": "live2d",
        "title": get_mode_descriptor("live2d").settings_title,
        "summary": (
            f"{mode.width}×{mode.height} · "
            f"{mode.model_name or '未配置模型'} · "
            f"{'显示回复泡泡' if mode.show_reply_bubble else '角色壳模式'}"
        ),
        "config": {
            "model_state": model_state.value,
            "model_name": mode.model_name or "",
            "model_path": mode.model_path or "",
            "width": mode.width,
            "height": mode.height,
            "position_x": mode.position_x,
            "position_y": mode.position_y,
            "window_on_top": mode.window_on_top,
            "show_reply_bubble": mode.show_reply_bubble,
            "default_open_behavior": mode.default_open_behavior,
            "click_action": mode.click_action,
            "auto_open_chat_window": mode.auto_open_chat_window,
            "enable_quick_input": mode.enable_quick_input,
            "idle_motion_group": mode.idle_motion_group,
            "enable_expressions": mode.enable_expressions,
            "enable_physics": mode.enable_physics,
            "summary": _serialize_summary(summary),
        },
    }


def serialize_mode_settings(config: AppConfig) -> dict[str, Any]:
    return {
        "window": serialize_window_mode(config),
        "bubble": serialize_bubble_mode(config),
        "live2d": serialize_live2d_mode(config),
    }


def serialize_mode_window_data(config: AppConfig, mode_id: str) -> dict[str, Any]:
    descriptor = get_mode_descriptor(mode_id)
    payload = serialize_mode_settings(config)[descriptor.id]
    return {
        "mode": descriptor.to_dict(),
        "settings": payload,
    }


def build_display_settings(config: AppConfig) -> dict[str, Any]:
    return {
        "current_mode": config.display_mode,
        "available_modes": list_mode_options(),
    }


def apply_settings_changes(config: AppConfig, changes: dict[str, Any]) -> dict[str, Any]:
    """统一处理顶层设置与 mode config 设置。"""
    if not isinstance(changes, dict):
        return {"ok": False, "error": "参数格式错误"}

    applied: dict[str, Any] = {}
    errors: list[str] = []

    for raw_key, raw_value in changes.items():
        key = raw_key
        value = raw_value

        if "." in key:
            prefix, field_name = key.split(".", 1)
            mode_key = _MODE_KEY_ALIASES.get(prefix, prefix)
            field_specs = _MODE_FIELDS.get(mode_key)
            if field_specs is None or field_name not in field_specs:
                errors.append(f"不支持修改: {raw_key}")
                continue
            expected = field_specs[field_name]
            value = _coerce_numeric(expected, value)
            if not isinstance(value, expected):
                errors.append(f"{raw_key} 类型错误，期望 {expected.__name__}")
                continue
            validation_error = _validate_field(f"{mode_key}.{field_name}", value)
            if validation_error:
                errors.append(validation_error)
                continue
            setattr(_mode_object(config, mode_key), field_name, value)
            applied[f"{mode_key}.{field_name}"] = value
            continue

        if key not in _TOP_LEVEL_FIELDS:
            errors.append(f"不支持修改: {raw_key}")
            continue

        expected = _TOP_LEVEL_FIELDS[key]
        value = _coerce_numeric(expected, value)
        if not isinstance(value, expected):
            errors.append(f"{raw_key} 类型错误，期望 {expected.__name__}")
            continue
        validation_error = _validate_field(key, value)
        if validation_error:
            errors.append(validation_error)
            continue
        setattr(config, key, value)
        applied[key] = value

    if applied:
        try:
            save_config(config)
        except Exception as exc:
            logger.error("配置保存失败: %s", exc)
            return {"ok": False, "error": f"保存失败: {exc}", "applied": applied}

    if errors and not applied:
        return {
            "ok": False,
            "error": "；".join(errors),
            "applied": applied,
            "errors": errors,
        }

    result: dict[str, Any] = {"ok": True, "applied": applied, "errors": errors}
    if applied:
        result["effects"] = build_effects_summary(list(applied.keys()))
        result["mode_settings"] = serialize_mode_settings(config)
    return result
