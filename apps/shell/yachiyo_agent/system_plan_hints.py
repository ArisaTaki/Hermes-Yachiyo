"""System-control hints for the Yachiyo runtime planner."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def system_control_hint(prompt: str) -> dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        return {}
    volume_payload = _volume_payload(text)
    if volume_payload:
        return {"kind": "volume", "payload": volume_payload}
    brightness_payload = _brightness_payload(text)
    if brightness_payload:
        return {"kind": "brightness", "payload": brightness_payload}
    if _display_sleep_request(text):
        return {"kind": "display_sleep", "payload": {}}
    if _screen_saver_request(text):
        return {"kind": "screen_saver", "payload": {}}
    return {}


def system_tool_preview(
    inputs: Mapping[str, Any],
    allowed: set[str] | None,
) -> tuple[str | None, dict[str, Any]]:
    kind = str(inputs.get("kind") or "").strip()
    payload = dict(inputs.get("payload") or {})
    tool_by_kind = {
        "volume": "system.volume",
        "brightness": "system.brightness",
        "display_sleep": "system.display_sleep",
        "screen_saver": "system.screen_saver_start",
    }
    tool_name = tool_by_kind.get(kind)
    if not tool_name:
        return None, {}
    if allowed is not None and tool_name not in allowed:
        return None, payload
    return tool_name, payload


def _volume_payload(text: str) -> dict[str, Any]:
    lowered = text.lower()
    level_match = re.search(r"(?P<level>\d{1,3})\s*%?", text)
    if _contains_any(text, ["取消静音", "解除静音", "恢复声音"]) or re.search(r"\bunmute\b", lowered):
        return {"action": "unmute"}
    if _contains_any(text, ["静音", "关闭声音", "关掉声音", "别出声"]) or re.search(r"\bmute\b", lowered):
        return {"action": "mute"}
    if _contains_any(text, ["一半", "半"]):
        return {"action": "set", "level": 50}
    if _contains_any(text, ["最大", "满格", "拉满"]):
        return {"action": "set", "level": 100}
    if level_match and _contains_any(text, ["音量", "声音", "volume", "sound"]):
        level = int(level_match.group("level"))
        if 0 <= level <= 100:
            return {"action": "set", "level": level}
    if _contains_any(text, ["调大", "调高", "提高", "大声", "volume up", "louder"]):
        return {"action": "up"}
    if _contains_any(text, ["调小", "调低", "降低", "小声", "volume down", "quieter"]):
        return {"action": "down"}
    if _contains_any(text, ["查看音量", "读取音量", "当前音量", "音量多少", "volume status"]):
        return {"action": "status"}
    return {}


def _brightness_payload(text: str) -> dict[str, Any]:
    lowered = text.lower()
    if _contains_any(text, ["设置", "设为", "设成", "%", "百分之"]):
        return {}
    if _contains_any(text, ["调亮", "亮一点", "亮点", "太暗", "brightness up", "brighter"]):
        return {"action": "up", "step": _brightness_step(text)}
    if _contains_any(text, ["调暗", "暗一点", "暗点", "太亮", "brightness down", "dimmer"]):
        return {"action": "down", "step": _brightness_step(text)}
    if re.search(r"\bincrease\s+(?:the\s+)?brightness\b", lowered):
        return {"action": "up", "step": _brightness_step(text)}
    if re.search(r"\bdecrease\s+(?:the\s+)?brightness\b", lowered):
        return {"action": "down", "step": _brightness_step(text)}
    return {}


def _display_sleep_request(text: str) -> bool:
    lowered = text.lower()
    if _contains_any(text, ["电脑睡眠", "整机睡眠", "关机", "重启", "shutdown", "restart"]):
        return False
    return _contains_any(text, ["关闭屏幕", "关掉屏幕", "息屏", "显示器睡眠", "turn off the display", "display sleep"])


def _screen_saver_request(text: str) -> bool:
    lowered = text.lower()
    if _contains_any(text, ["设置", "设定", "preferences", "settings"]):
        return False
    return _contains_any(text, ["启动屏幕保护程序", "打开屏保", "开启屏保", "start screen saver", "screensaver"])


def _brightness_step(text: str) -> int:
    match = re.search(r"(\d+)", text)
    if match:
        count = int(match.group(1))
        if 1 <= count <= 10:
            return count
    if _contains_any(text, ["一点点", "稍微", "slightly"]):
        return 1
    if _contains_any(text, ["很多", "大幅", "much"]):
        return 4
    return 2


def _contains_any(text: str, terms: tuple[str, ...] | list[str]) -> bool:
    lowered = text.lower()
    return any(str(term).lower() in lowered for term in terms)
