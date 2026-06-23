"""Structured desktop execution helpers for Agent tools."""

from __future__ import annotations

import math
import platform
import subprocess
from pathlib import Path
from typing import Any

_COMMON_FOLDER_TARGETS = {
    "desktop": "Desktop",
    "desktopfolder": "Desktop",
    "桌面": "Desktop",
    "桌面文件夹": "Desktop",
    "downloads": "Downloads",
    "downloadsfolder": "Downloads",
    "下载": "Downloads",
    "下载文件夹": "Downloads",
    "documents": "Documents",
    "documentsfolder": "Documents",
    "文档": "Documents",
    "文档文件夹": "Documents",
    "文稿": "Documents",
    "文稿文件夹": "Documents",
    "home": "",
    "homefolder": "",
    "主目录": "",
    "用户文件夹": "",
}

_PRIVACY_SECURITY_URLS = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy",
    "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
)

_SYSTEM_SETTINGS_TARGETS = {
    "privacysecurity": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "privacyandsecurity": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "securityprivacy": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "securityandprivacy": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "隐私与安全性": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "隐私和安全性": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "隐私安全": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "安全性与隐私": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "安全与隐私": ("Privacy & Security", _PRIVACY_SECURITY_URLS),
    "accessibility": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "assistive": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "辅助功能": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "无障碍": (
        "Accessibility Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",),
    ),
    "screenrecording": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "screencapture": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "屏幕录制": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "屏幕录像": (
        "Screen Recording Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",),
    ),
    "automation": (
        "Automation Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",),
    ),
    "appleevents": (
        "Automation Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",),
    ),
    "自动化": (
        "Automation Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",),
    ),
    "fulldiskaccess": (
        "Full Disk Access",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",),
    ),
    "完全磁盘访问": (
        "Full Disk Access",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",),
    ),
    "filesandfolders": (
        "Files and Folders Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ApplicationData",),
    ),
    "文件和文件夹": (
        "Files and Folders Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ApplicationData",),
    ),
    "inputmonitoring": (
        "Input Monitoring Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",),
    ),
    "输入监控": (
        "Input Monitoring Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",),
    ),
    "microphone": (
        "Microphone Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",),
    ),
    "麦克风": (
        "Microphone Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",),
    ),
    "camera": (
        "Camera Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",),
    ),
    "摄像头": (
        "Camera Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",),
    ),
    "相机": (
        "Camera Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",),
    ),
    "locationservices": (
        "Location Services Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices",),
    ),
    "定位服务": (
        "Location Services Permission",
        ("x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices",),
    ),
}


def screen_capture(target_path: Path) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("screen.capture")
    from apps.locald.screenshot import capture_screenshot_to_file

    try:
        metadata = capture_screenshot_to_file(target_path)
    except Exception as exc:
        return _error("screen.capture", exc)
    return {
        "ok": True,
        "action": "screen.capture",
        "summary": (
            f"Captured screen {metadata.get('width', 0)}x{metadata.get('height', 0)} "
            f"{str(metadata.get('format') or 'png').upper()}"
        ),
        "data": metadata,
        "permission_error": False,
        "fallback_used": False,
    }


def active_window() -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.active_window")
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set appPID to unix id of frontApp
        try
            set winTitle to name of front window of frontApp
        on error
            set winTitle to ""
        end try
        return appName & "|" & appPID & "|" & winTitle
    end tell
    """
    result = _run_osascript(script)
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.active_window",
            {**result, "action": "desktop.active_window", "summary": "desktop.active_window failed"},
        )
    parts = str(result.get("stdout") or "").strip().split("|", 2)
    app_name = parts[0] if len(parts) > 0 else ""
    pid_text = parts[1] if len(parts) > 1 else ""
    title = parts[2] if len(parts) > 2 else ""
    return {
        "ok": True,
        "action": "desktop.active_window",
        "summary": f"Active window: {app_name}{f' - {title}' if title else ''}",
        "data": {
            "app_name": app_name,
            "pid": int(pid_text) if pid_text.isdigit() else None,
            "title": title,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def app_open(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.open")
    clean_name = _clean_required(app_name, "app_name")
    settings_target = _system_settings_target(clean_name)
    if settings_target is not None:
        return _open_system_settings_target(clean_name, settings_target)
    folder_path = _common_folder_path(clean_name)
    if folder_path is not None:
        return _open_common_folder(clean_name, folder_path)
    try:
        result = subprocess.run(
            ["open", "-a", clean_name],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("app.open", exc)
    if result.returncode != 0:
        return _app_open_failed(clean_name, result)
    verification = _app_running_verification(clean_name)
    return {
        "ok": True,
        "action": "app.open",
        "summary": f"Opened {clean_name}",
        "data": {"app_name": clean_name, **verification},
        "permission_error": False,
        "fallback_used": False,
    }


def reveal_path(path: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.reveal_path")
    clean_path = _clean_required(path, "path")
    target = _expanded_local_path(clean_path)
    if not target.exists():
        return {
            "ok": False,
            "action": "desktop.reveal_path",
            "summary": "desktop.reveal_path failed",
            "error": f"Path not found: {clean_path}",
            "error_code": "path_not_found",
            "data": {
                "path": clean_path,
                "expanded_path": str(target),
                "open_target": "finder_reveal",
                "exists": False,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    try:
        result = subprocess.run(
            ["open", "-R", str(target)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("desktop.reveal_path", exc)
    if result.returncode != 0:
        payload = _failed("desktop.reveal_path", result)
        payload["data"] = {
            "path": clean_path,
            "expanded_path": str(target),
            "open_target": "finder_reveal",
            "exists": True,
            "is_dir": target.is_dir(),
        }
        return payload
    return {
        "ok": True,
        "action": "desktop.reveal_path",
        "summary": f"Revealed {target.name or str(target)} in Finder",
        "data": {
            "path": clean_path,
            "expanded_path": str(target),
            "open_target": "finder_reveal",
            "exists": True,
            "is_dir": target.is_dir(),
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _open_common_folder(label: str, folder_path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["open", str(folder_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("app.open", exc)
    if result.returncode != 0:
        payload = _failed("app.open", result)
        payload["data"] = {
            "app_name": label,
            "path": str(folder_path),
            "open_target": "folder",
        }
        return payload
    return {
        "ok": True,
        "action": "app.open",
        "summary": f"Opened {folder_path.name or 'Home'}",
        "data": {
            "app_name": label,
            "path": str(folder_path),
            "open_target": "folder",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _open_system_settings_target(
    label: str,
    target: tuple[str, tuple[str, ...]],
) -> dict[str, Any]:
    settings_label, urls = target
    errors: list[str] = []
    for index, url in enumerate(urls):
        try:
            result = subprocess.run(
                ["open", url],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:
            return _error("app.open", exc)
        if result.returncode == 0:
            return {
                "ok": True,
                "action": "app.open",
                "summary": f"Opened System Settings: {settings_label}",
                "data": {
                    "app_name": label,
                    "open_target": "system_settings",
                    "settings_label": settings_label,
                    "settings_url": url,
                    "fallback_used": index > 0,
                },
                "permission_error": False,
                "fallback_used": index > 0,
            }
        error = "\n".join(
            part.strip()
            for part in (result.stderr, result.stdout)
            if isinstance(part, str) and part.strip()
        )
        errors.append(error or f"{url}: exit code {result.returncode}")
    payload = _failed("app.open", result)
    payload["data"] = {
        "app_name": label,
        "open_target": "system_settings",
        "settings_label": settings_label,
        "attempted_urls": list(urls),
        "settings_errors": errors,
    }
    return payload


def _system_settings_target(value: str) -> tuple[str, tuple[str, ...]] | None:
    variants = _system_settings_alias_variants(value)
    for variant in variants:
        target = _SYSTEM_SETTINGS_TARGETS.get(variant)
        if target is not None:
            return target
    return None


def _system_settings_alias_variants(value: str) -> list[str]:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("&", "and")
    normalized = normalized.replace("-", " ").replace("_", " ")
    normalized = normalized.replace("设置的", " ")
    variants = [_compact_alias(normalized)]
    simplified = _strip_system_settings_noise(normalized)
    simplified_compact = _compact_alias(simplified)
    if simplified_compact and simplified_compact not in variants:
        variants.append(simplified_compact)
    return [variant for variant in variants if variant]


def _strip_system_settings_noise(value: str) -> str:
    return (
        str(value or "")
        .replace("系统设置", " ")
        .replace("设置", " ")
        .replace("权限", " ")
        .replace("页面", " ")
        .replace("面板", " ")
        .replace("settings", " ")
        .replace("setting", " ")
        .replace("preferences", " ")
        .replace("preference", " ")
        .replace("permissions", " ")
        .replace("permission", " ")
        .replace("pane", " ")
        .replace("page", " ")
    )


def _compact_alias(value: str) -> str:
    return "".join(str(value or "").strip().split())


def _expanded_local_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve(strict=False)


def _common_folder_path(value: str) -> Path | None:
    compact = "".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())
    if compact not in _COMMON_FOLDER_TARGETS:
        return None
    folder_name = _COMMON_FOLDER_TARGETS[compact]
    return Path.home() / folder_name if folder_name else Path.home()


def app_focus(app_name: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("app.focus")
    clean_name = _clean_required(app_name, "app_name")
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            tell application appName to activate
            return "focused|" & appName
        end run
        """,
        [clean_name],
    )
    if not result["ok"]:
        fallback = app_open(clean_name)
        if fallback.get("ok"):
            fallback_data = fallback.get("data") if isinstance(fallback.get("data"), dict) else {}
            return {
                "ok": True,
                "action": "app.focus",
                "summary": f"Focused {clean_name} via app.open fallback",
                "data": {
                    "app_name": clean_name,
                    **fallback_data,
                    "focus_fallback": "app.open",
                },
                "permission_error": False,
                "fallback_used": True,
                "fallback_result": fallback,
            }
        payload = _with_permission_metadata(
            "app.focus",
            {**result, "action": "app.focus", "summary": "app.focus failed"},
        )
        payload["fallback_used"] = bool(fallback.get("ok"))
        payload["fallback_result"] = fallback
        return payload
    return {
        "ok": True,
        "action": "app.focus",
        "summary": f"Focused {clean_name}",
        "data": {"app_name": clean_name},
        "permission_error": False,
        "fallback_used": False,
    }


def apple_music_play(query: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.apple_music_play")
    clean_query = _clean_required(query, "query")
    result = _run_osascript(
        """
        on run argv
            set queryText to item 1 of argv
            tell application "Music"
                activate
                try
                    set matches to (search library playlist 1 for queryText)
                    if (count of matches) is 0 then
                        return "not_found|" & queryText & "|"
                    end if
                    set trackRef to item 1 of matches
                    play trackRef
                    set trackName to name of trackRef
                    set artistName to artist of trackRef
                    return "played|" & trackName & "|" & artistName
                on error errMsg number errNum
                    return "error|" & errNum & "|" & errMsg
                end try
            end tell
        end run
        """,
        [clean_query],
    )
    if not result["ok"]:
        fallback = app_open("Music")
        return {
            **_with_permission_metadata(
                "media.apple_music_play",
                {
                    **result,
                    "action": "media.apple_music_play",
                    "summary": "media.apple_music_play failed",
                },
            ),
            "action": "media.apple_music_play",
            "fallback_used": bool(fallback.get("ok")),
            "fallback_result": fallback,
        }
    status, first, second = _split_status(result.get("stdout"))
    if status == "played":
        detail = f"{first}{f' - {second}' if second else ''}"
        return {
            "ok": True,
            "action": "media.apple_music_play",
            "summary": f"Playing {detail}",
            "data": {"query": clean_query, "track": first, "artist": second},
            "permission_error": False,
            "fallback_used": False,
        }
    fallback = app_open("Music")
    payload = {
        "ok": False,
        "action": "media.apple_music_play",
        "summary": f"Could not directly play {clean_query}; opened Music for manual search.",
        "error": second or first or "Music did not return a playable track",
        "data": {"query": clean_query, "status": status},
        "permission_error": status == "error" and _looks_like_permission_error(f"{first}\n{second}"),
        "fallback_used": bool(fallback.get("ok")),
        "fallback_result": fallback,
    }
    return _with_permission_metadata("media.apple_music_play", payload)


def apple_music_control(action: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("media.apple_music_control")
    clean_action = _clean_music_control_action(action)
    result = _run_osascript(
        """
        on run argv
            set controlAction to item 1 of argv
            tell application "Music"
                try
                    if controlAction is "toggle" then
                        playpause
                    else if controlAction is "play" then
                        play
                    else if controlAction is "pause" then
                        pause
                    else if controlAction is "next" then
                        next track
                    else if controlAction is "previous" then
                        previous track
                    else
                        return "error|-1|unsupported_control"
                    end if
                    delay 0.1
                    set stateText to player state as text
                    try
                        set trackName to name of current track
                        set artistName to artist of current track
                    on error
                        set trackName to ""
                        set artistName to ""
                    end try
                    return "controlled|" & controlAction & "|" & stateText & "|" & trackName & "|" & artistName
                on error errMsg number errNum
                    return "error|" & errNum & "|" & errMsg
                end try
            end tell
        end run
        """,
        [clean_action],
    )
    if not result["ok"]:
        fallback = app_open("Music")
        return {
            **_with_permission_metadata(
                "media.apple_music_control",
                {
                    **result,
                    "action": "media.apple_music_control",
                    "summary": "media.apple_music_control failed",
                },
            ),
            "action": "media.apple_music_control",
            "fallback_used": bool(fallback.get("ok")),
            "fallback_result": fallback,
        }
    parts = str(result.get("stdout") or "").strip().split("|", 4)
    while len(parts) < 5:
        parts.append("")
    status, first, second, third, fourth = parts
    if status == "controlled":
        return {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": f"Apple Music {first} executed",
            "data": {
                "control": first or clean_action,
                "player_state": second,
                "track": third,
                "artist": fourth,
            },
            "permission_error": False,
            "fallback_used": False,
        }
    fallback = app_open("Music")
    payload = {
        "ok": False,
        "action": "media.apple_music_control",
        "summary": f"Could not control Apple Music with action {clean_action}; opened Music.",
        "error": second or first or "Music did not accept the control action",
        "data": {"control": clean_action, "status": status},
        "permission_error": status == "error" and _looks_like_permission_error(f"{first}\n{second}"),
        "fallback_used": bool(fallback.get("ok")),
        "fallback_result": fallback,
    }
    return _with_permission_metadata("media.apple_music_control", payload)


def desktop_type_text(text: str) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.type_text")
    clean_text = _clean_required(text, "text")
    result = _run_osascript(
        """
        on run argv
            set textToType to item 1 of argv
            tell application "System Events" to keystroke textToType
            return "typed"
        end run
        """,
        [clean_text],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.type_text",
            {**result, "action": "desktop.type_text", "summary": "desktop.type_text failed"},
        )
    return {
        "ok": True,
        "action": "desktop.type_text",
        "summary": "Typed text into the foreground app",
        "data": {"character_count": len(clean_text)},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_click(x: Any, y: Any, *, click_count: Any = 1) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.click")
    clean_x = _clean_coordinate(x, "x")
    clean_y = _clean_coordinate(y, "y")
    clean_count = _clean_click_count(click_count)
    result = _run_osascript(
        """
        on run argv
            set xCoord to item 1 of argv as integer
            set yCoord to item 2 of argv as integer
            set clickCount to item 3 of argv as integer
            repeat clickCount times
                tell application "System Events" to click at {xCoord, yCoord}
                delay 0.05
            end repeat
            return "clicked"
        end run
        """,
        [str(clean_x), str(clean_y), str(clean_count)],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.click",
            {**result, "action": "desktop.click", "summary": "desktop.click failed"},
        )
    return {
        "ok": True,
        "action": "desktop.click",
        "summary": f"Clicked foreground desktop at ({clean_x}, {clean_y})",
        "data": {"x": clean_x, "y": clean_y, "click_count": clean_count},
        "permission_error": False,
        "fallback_used": False,
    }


def desktop_hotkey(key: str, modifiers: list[str] | None = None) -> dict[str, Any]:
    if _desktop_platform() != "macos":
        return _unsupported("desktop.hotkey")
    clean_key = _clean_required(key, "key")
    clean_modifiers = _clean_modifiers(modifiers or [])
    modifier_clause = ""
    if clean_modifiers:
        modifier_clause = " using {" + ", ".join(f"{item} down" for item in clean_modifiers) + "}"
    result = _run_osascript(
        f"""
        on run argv
            set keyName to item 1 of argv
            tell application "System Events" to keystroke keyName{modifier_clause}
            return "hotkey"
        end run
        """,
        [clean_key],
    )
    if not result["ok"]:
        return _with_permission_metadata(
            "desktop.hotkey",
            {**result, "action": "desktop.hotkey", "summary": "desktop.hotkey failed"},
        )
    return {
        "ok": True,
        "action": "desktop.hotkey",
        "summary": f"Pressed hotkey { '+'.join([*clean_modifiers, clean_key]) }",
        "data": {"key": clean_key, "modifiers": clean_modifiers},
        "permission_error": False,
        "fallback_used": False,
    }


def _run_osascript(script: str, args: list[str] | None = None) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script, *(args or [])],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return _error("osascript", exc)
    if result.returncode != 0:
        return _failed("osascript", result)
    return {
        "ok": True,
        "stdout": str(result.stdout or "").strip(),
        "stderr": str(result.stderr or "").strip(),
    }


def _desktop_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Windows":
        return "windows"
    if system == "Linux":
        return "linux"
    return str(system or "unknown").lower()


def _unsupported(action: str) -> dict[str, Any]:
    return {
        "ok": False,
        "action": action,
        "summary": f"{action} is not supported on this platform yet.",
        "error": "unsupported_platform",
        "data": {"platform": _desktop_platform()},
        "permission_error": False,
        "fallback_used": False,
    }


def _error(action: str, exc: Exception) -> dict[str, Any]:
    payload = {
        "ok": False,
        "action": action,
        "summary": f"{action} failed",
        "error": str(exc),
        "data": {},
        "permission_error": _looks_like_permission_error(str(exc)),
        "fallback_used": False,
    }
    return _with_permission_metadata(action, payload)


def _failed(action: str, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output = "\n".join(
        part.strip()
        for part in (result.stderr, result.stdout)
        if isinstance(part, str) and part.strip()
    )
    payload = {
        "ok": False,
        "action": action,
        "summary": f"{action} failed",
        "error": output or f"exit code {result.returncode}",
        "data": {},
        "returncode": result.returncode,
        "permission_error": _looks_like_permission_error(output),
        "fallback_used": False,
    }
    return _with_permission_metadata(action, payload)


def _app_open_failed(app_name: str, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    payload = _failed("app.open", result)
    payload["data"] = {"app_name": app_name}
    error = str(payload.get("error") or "")
    if _looks_like_app_not_found(error):
        payload["error_code"] = "app_not_found"
        payload["recovery_hints"] = [
            (
                "确认应用已安装，或换用 macOS 里的精确应用名，例如 "
                "Google Chrome、Safari、Music、Visual Studio Code。"
            )
        ]
    return payload


def _app_running_verification(app_name: str) -> dict[str, Any]:
    result = _run_osascript(
        """
        on run argv
            set appName to item 1 of argv
            if application appName is running then
                return "running"
            end if
            return "not_running"
        end run
        """,
        [app_name],
    )
    if result.get("ok"):
        status = str(result.get("stdout") or "").strip()
        return {
            "launch_verified": status == "running",
            "launch_status": status or "unknown",
        }
    return {
        "launch_verified": None,
        "launch_status": "unknown",
        "launch_verification_error": str(result.get("error") or result.get("stderr") or ""),
    }


def _looks_like_app_not_found(value: Any) -> bool:
    normalized = str(value or "").lower()
    return any(
        marker in normalized
        for marker in (
            "application not found",
            "unable to find application",
            "was not found",
            "can't find application",
            "can’t find application",
            "does not exist",
        )
    )


def _clean_required(value: str, field: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field} is required")
    return clean


def _clean_music_control_action(value: str) -> str:
    aliases = {
        "toggle": "toggle",
        "playpause": "toggle",
        "play_pause": "toggle",
        "pause": "pause",
        "play": "play",
        "resume": "play",
        "next": "next",
        "next_track": "next",
        "previous": "previous",
        "prev": "previous",
        "previous_track": "previous",
    }
    clean = aliases.get(str(value or "").strip().lower())
    if not clean:
        raise ValueError("action must be one of toggle, play, pause, next, or previous")
    return clean


def _clean_coordinate(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative screen coordinate")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative screen coordinate") from exc
    if not math.isfinite(coordinate) or coordinate < 0 or coordinate > 100000:
        raise ValueError(f"{field} must be a non-negative screen coordinate")
    return int(round(coordinate))


def _clean_click_count(value: Any) -> int:
    if value in (None, ""):
        return 1
    if isinstance(value, bool):
        raise ValueError("click_count must be an integer from 1 to 3")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("click_count must be an integer from 1 to 3") from exc
    if count < 1 or count > 3:
        raise ValueError("click_count must be an integer from 1 to 3")
    return count


def _clean_modifiers(modifiers: list[str]) -> list[str]:
    aliases = {
        "cmd": "command",
        "command": "command",
        "shift": "shift",
        "option": "option",
        "alt": "option",
        "control": "control",
        "ctrl": "control",
    }
    clean: list[str] = []
    for modifier in modifiers:
        name = aliases.get(str(modifier or "").strip().lower())
        if name and name not in clean:
            clean.append(name)
    return clean


def _split_status(value: Any) -> tuple[str, str, str]:
    parts = str(value or "").strip().split("|", 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1], parts[2]


def _looks_like_permission_error(value: Any) -> bool:
    if value.__class__.__name__ == "ScreenCapturePermissionError":
        return True
    normalized = str(value or "").lower()
    return any(
        marker in normalized
        for marker in (
            "not authorized",
            "not allowed",
            "not permitted",
            "accessibility",
            "automation",
            "privacy",
            "screen capture",
            "screen recording",
            "tcc",
        )
    )


def _with_permission_metadata(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("permission_error"):
        return payload
    missing_permissions = _missing_permissions_for_action(action)
    permission_targets = _permission_targets_for_action(action)
    if missing_permissions:
        payload["missing_permissions"] = missing_permissions
    if permission_targets:
        payload["permission_targets"] = permission_targets
    recovery_hints = _permission_recovery_hints_for_targets(permission_targets)
    if recovery_hints:
        payload["recovery_hints"] = recovery_hints
    return payload


def _missing_permissions_for_action(action: str) -> list[str]:
    return {
        "screen.capture": ["screen_recording"],
        "desktop.active_window": ["automation_or_accessibility"],
        "app.focus": ["automation"],
        "media.apple_music_play": ["music_app", "automation"],
        "media.apple_music_control": ["music_app", "automation"],
        "desktop.click": ["accessibility"],
        "desktop.type_text": ["accessibility"],
        "desktop.hotkey": ["accessibility"],
        "osascript": ["automation"],
    }.get(action, [])


def _permission_targets_for_action(action: str) -> list[str]:
    return {
        "screen.capture": ["screen_recording"],
        "desktop.active_window": ["automation", "accessibility"],
        "app.focus": ["automation"],
        "media.apple_music_play": ["music_app", "automation"],
        "media.apple_music_control": ["music_app", "automation"],
        "desktop.click": ["accessibility"],
        "desktop.type_text": ["accessibility"],
        "desktop.hotkey": ["accessibility"],
        "osascript": ["automation"],
    }.get(action, [])


def _permission_recovery_hints_for_targets(targets: list[str]) -> list[str]:
    hints_by_target = {
        "accessibility": (
            "Grant Accessibility permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Accessibility."
        ),
        "automation": (
            "Grant Automation permission so Oha-Yachiyo can control System Events "
            "or the target app in macOS System Settings > Privacy & Security > Automation."
        ),
        "music_app": (
            "Open Music.app once, confirm the track exists in the local library, "
            "and allow Automation when macOS asks for Music control."
        ),
        "screen_recording": (
            "Grant Screen Recording permission to Oha-Yachiyo or the current terminal "
            "in macOS System Settings > Privacy & Security > Screen Recording."
        ),
    }
    hints: list[str] = []
    for target in targets:
        hint = hints_by_target.get(str(target or "").strip())
        if hint and hint not in hints:
            hints.append(hint)
    return hints
