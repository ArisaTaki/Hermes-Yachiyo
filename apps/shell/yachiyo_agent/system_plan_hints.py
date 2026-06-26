"""System-control hints for the Yachiyo runtime planner."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def system_control_hint(prompt: str) -> dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        return {}
    settings_payload = _settings_open_payload(text)
    if settings_payload:
        return {"kind": "settings_open", **settings_payload}
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
        "settings_open": "system.settings_open",
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


def _settings_open_payload(text: str) -> dict[str, Any]:
    target = _settings_target(text)
    if not target:
        return {}
    return {
        "payload": {"target": target},
        "inspect_ui": _settings_inspect_ui_request(text),
    }


def _settings_target(text: str) -> str:
    lowered = text.lower()
    if not re.search(
        r"(?:打开|启动|开启|拉起|显示|前往|进入|去|修复|修一下|修下|处理|解决|"
        r"\bopen\b|\blaunch\b|\bshow\b|\bgo\s+to\b|\bfix\b|\brepair\b|\bresolve\b)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return ""

    target_patterns: tuple[tuple[str, str], ...] = (
        (r"(?:辅助功能|无障碍|\baccessibility\b|\bassistive\b)", "辅助功能权限"),
        (r"(?:屏幕录制|屏幕录像|\bscreen\s+recording\b|\bscreen\s+capture\b)", "屏幕录制权限"),
        (r"(?:自动化|\bautomation\b|\bapple\s*events?\b)", "自动化权限"),
        (r"(?:完全磁盘访问|\bfull\s+disk\s+access\b)", "完全磁盘访问"),
        (r"(?:输入监控|\binput\s+monitoring\b)", "输入监控"),
        (r"(?:文件和文件夹|文件与文件夹|\bfiles?\s+and\s+folders?\b)", "文件和文件夹"),
        (r"(?:摄像头|相机|\bcamera\b)", "摄像头"),
        (r"(?:麦克风|\bmicrophone\b)", "麦克风"),
        (r"(?:定位服务|定位权限|位置服务|\blocation\s+services?\b|\blocation\b)", "定位服务"),
        (
            r"(?:桌面权限|桌面执行权限|本地工具权限|\bdesktop\s+permissions?\b|"
            r"\blocal\s+tool\s+permissions?\b)",
            "隐私与安全性",
        ),
        (r"(?:隐私与安全性|隐私和安全性|隐私.*安全|隐私|\bprivacy\b|\bsecurity\b)", "隐私与安全性"),
        (r"(?:wi-?fi|无线网络|无线局域网)", "Wi-Fi"),
        (r"(?:蓝牙|\bbluetooth\b)", "蓝牙"),
        (r"(?:网络|\bnetwork\b)", "网络"),
        (r"(?:显示器|显示设置|\bdisplays?\b|\bdisplay\s+settings?\b)", "显示器"),
        (r"(?:声音设置|音频设置|\bsound\s+settings?\b|\baudio\s+settings?\b)", "声音"),
        (r"(?:键盘设置|\bkeyboard\s+settings?\b)", "键盘"),
        (r"(?:通知设置|\bnotifications?\s+settings?\b)", "通知"),
        (r"(?:电池设置|电池|\bbattery\s+settings?\b|\bbattery\b)", "电池"),
        (r"(?:鼠标设置|鼠标|\bmouse\s+settings?\b|\bmouse\b)", "鼠标"),
        (r"(?:触控板设置|触控板|\btrackpad\s+settings?\b|\btrackpad\b)", "触控板"),
        (
            r"(?:打印机(?:与|和)?扫描仪设置|打印机设置|打印机|"
            r"\bprinters?(?:\s+(?:and|&)\s+scanners?)?\s+settings?\b|\bprinters?\b)",
            "打印机与扫描仪",
        ),
        (r"(?:专注模式设置|专注模式|\bfocus\s+settings?\b|\bfocus\b)", "专注模式"),
        (r"(?:墙纸设置|壁纸设置|墙纸|壁纸|\bwallpaper\s+settings?\b|\bwallpaper\b)", "墙纸"),
        (
            r"(?:桌面(?:与|和)程序坞设置|桌面(?:与|和)程序坞|程序坞设置|程序坞|"
            r"\bdesktop\s+(?:and|&)\s+dock\s+settings?\b|\bdock\s+settings?\b)",
            "桌面与程序坞",
        ),
        (
            r"(?:屏幕保护程序设置|屏幕保护设置|屏幕保护程序|屏幕保护|"
            r"\bscreen\s+saver\s+settings?\b|\bscreensaver\s+settings?\b)",
            "屏幕保护程序",
        ),
        (r"(?:siri(?:\s+settings?)?|siri设置)", "Siri"),
        (
            r"(?:语言(?:与|和)地区设置|语言(?:与|和)地区|"
            r"\blanguage\s+(?:and|&)\s+region\s+settings?\b)",
            "语言与地区",
        ),
        (
            r"(?:日期(?:与|和)时间设置|日期(?:与|和)时间|"
            r"\bdate\s+(?:and|&)\s+time\s+settings?\b)",
            "日期与时间",
        ),
        (r"(?:软件更新|\bsoftware\s+updates?\b|\bsoftware\s+update\s+settings?\b)", "软件更新"),
        (r"(?:储存空间设置|存储空间设置|储存空间|存储空间|\bstorage\s+settings?\b|\bstorage\b)", "储存空间"),
        (r"(?:登录项设置|登录项|\blogin\s+items?\s+settings?\b|\blogin\s+items?\b)", "登录项"),
        (
            r"(?:用户(?:与|和)群组设置|用户(?:与|和)群组|"
            r"\busers?\s+(?:and|&)\s+groups?\s+settings?\b)",
            "用户与群组",
        ),
        (
            r"(?:系统设置|系统偏好|系统偏好设置|设置|偏好|"
            r"system\s+settings?|system\s+preferences?|settings?|preferences?)",
            "系统设置",
        ),
    )
    for pattern, target in target_patterns:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return target
    return ""


def _settings_inspect_ui_request(text: str) -> bool:
    return bool(
        re.search(
            r"(?:看看|看下|查看|检查|有哪些|有什么|有啥|选项|按钮|控件|界面|"
            r"\binspect\b|\bread\b|\bshow\b|\boptions?\b|\bbuttons?\b|\bcontrols?\b)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _volume_payload(text: str) -> dict[str, Any]:
    lowered = text.lower()
    has_volume_context = _contains_any(text, ["音量", "声音", "volume", "sound"])
    level_match = re.search(r"(?P<level>\d{1,3})\s*%?", text)
    if _contains_any(text, ["取消静音", "解除静音", "恢复声音"]) or re.search(r"\bunmute\b", lowered):
        return {"action": "unmute"}
    if _contains_any(text, ["静音", "关闭声音", "关掉声音", "别出声"]) or re.search(r"\bmute\b", lowered):
        return {"action": "mute"}
    if has_volume_context and _contains_any(text, ["一半", "半"]):
        return {"action": "set", "level": 50}
    if has_volume_context and _contains_any(text, ["最大", "满格", "拉满"]):
        return {"action": "set", "level": 100}
    if level_match and has_volume_context:
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
