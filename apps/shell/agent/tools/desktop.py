"""Structured desktop execution helpers for Agent tools."""

from __future__ import annotations

import math
import platform
import subprocess
from pathlib import Path
from typing import Any


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
        return _failed("app.open", result)
    return {
        "ok": True,
        "action": "app.open",
        "summary": f"Opened {clean_name}",
        "data": {"app_name": clean_name},
        "permission_error": False,
        "fallback_used": False,
    }


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
        return _with_permission_metadata(
            "app.focus",
            {**result, "action": "app.focus", "summary": "app.focus failed"},
        )
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


def _clean_required(value: str, field: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field} is required")
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
