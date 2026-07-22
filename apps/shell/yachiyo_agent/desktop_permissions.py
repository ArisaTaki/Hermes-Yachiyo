"""Best-effort desktop execution permission probes for public readiness."""

from __future__ import annotations

import json
import platform
import shutil
import socket
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PERMISSION_PROBE_CACHE_TTL_SECONDS = 30.0

_PERMISSION_CACHE: tuple[str, float, dict[str, list[str]]] | None = None
_RUNTIME_BLOCKER_CACHE: tuple[str, float, dict[str, list[str]]] | None = None


def desktop_permission_missing_by_capability(
    *,
    platform_name: str | None = None,
    use_cache: bool = True,
) -> dict[str, list[str]]:
    """Return stable missing-permission tokens keyed by desktop capability id."""

    global _PERMISSION_CACHE

    platform_id = _desktop_platform(platform_name)
    if platform_id != "macos":
        return {"desktop_execution": ["unsupported_platform"]}

    now = time.monotonic()
    if use_cache and _PERMISSION_CACHE is not None:
        cache_platform, cache_time, cached = _PERMISSION_CACHE
        if cache_platform == platform_id and now - cache_time <= PERMISSION_PROBE_CACHE_TTL_SECONDS:
            return _copy_missing(cached)

    missing: dict[str, list[str]] = {}
    _probe_screen_capture(missing)
    _probe_active_window(missing)
    _probe_app_control(missing)
    _probe_foreground_activation(missing)
    _probe_media_control(missing)
    _probe_foreground_input(missing)
    _probe_browser_control(missing)

    if use_cache:
        _PERMISSION_CACHE = (platform_id, now, _copy_missing(missing))
    return _copy_missing(missing)


def cached_desktop_permission_missing_by_capability(
    *,
    platform_name: str | None = None,
) -> dict[str, list[str]]:
    """Return cached permission diagnostics without running fresh probes."""

    platform_id = _desktop_platform(platform_name)
    if platform_id != "macos" or _PERMISSION_CACHE is None:
        return {}
    cache_platform, cache_time, cached = _PERMISSION_CACHE
    if cache_platform != platform_id:
        return {}
    if time.monotonic() - cache_time > PERMISSION_PROBE_CACHE_TTL_SECONDS:
        return {}
    return _copy_missing(cached)


def desktop_runtime_blocking_conditions_by_capability(
    *,
    platform_name: str | None = None,
    use_cache: bool = True,
) -> dict[str, list[str]]:
    """Return non-permission runtime blockers keyed by desktop capability id."""

    global _RUNTIME_BLOCKER_CACHE

    platform_id = _desktop_platform(platform_name)
    if platform_id != "macos":
        return {}

    now = time.monotonic()
    if use_cache and _RUNTIME_BLOCKER_CACHE is not None:
        cache_platform, cache_time, cached = _RUNTIME_BLOCKER_CACHE
        if cache_platform == platform_id and now - cache_time <= PERMISSION_PROBE_CACHE_TTL_SECONDS:
            return _copy_missing(cached)

    blocking: dict[str, list[str]] = {}
    screen_capture_result = _check_screen_capture_permission()
    if _macos_desktop_session_locked():
        for capability_id in (
            "desktop_execution",
            "active_window",
            "app_control",
            "media_control",
            "foreground_activation",
            "foreground_input",
        ):
            _add_missing(blocking, capability_id, "desktop_session_locked")
    else:
        result = _check_foreground_activation()
        if not result.get("verified") and not result.get("permission_denied"):
            _add_missing(
                blocking,
                "foreground_activation",
                "foreground_focus_unavailable",
            )
    if _screen_capture_blank(screen_capture_result):
        for capability_id in (
            "desktop_execution",
            "screen_capture",
            "active_window",
            "foreground_activation",
            "foreground_input",
        ):
            _add_missing(blocking, capability_id, "screen_capture_blank")

    if use_cache:
        _RUNTIME_BLOCKER_CACHE = (platform_id, now, _copy_missing(blocking))
    return _copy_missing(blocking)


def cached_desktop_runtime_blocking_conditions_by_capability(
    *,
    platform_name: str | None = None,
) -> dict[str, list[str]]:
    """Return cached runtime desktop blockers without running fresh probes."""

    platform_id = _desktop_platform(platform_name)
    if platform_id != "macos" or _RUNTIME_BLOCKER_CACHE is None:
        return {}
    cache_platform, cache_time, cached = _RUNTIME_BLOCKER_CACHE
    if cache_platform != platform_id:
        return {}
    if time.monotonic() - cache_time > PERMISSION_PROBE_CACHE_TTL_SECONDS:
        return {}
    return _copy_missing(cached)


def desktop_permission_probe_cache_status(
    *,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Describe fresh cached diagnostics without performing any probes."""

    platform_id = _desktop_platform(platform_name)
    now = time.monotonic()

    def cache_is_fresh(cache: Any) -> bool:
        if cache is None:
            return False
        cache_platform, cache_time, _cached = cache
        return bool(
            cache_platform == platform_id
            and now - cache_time <= PERMISSION_PROBE_CACHE_TTL_SECONDS
        )

    permission_checked = platform_id == "macos" and cache_is_fresh(
        _PERMISSION_CACHE
    )
    runtime_blockers_checked = platform_id == "macos" and cache_is_fresh(
        _RUNTIME_BLOCKER_CACHE
    )
    checked = permission_checked and runtime_blockers_checked
    return {
        "checked": checked,
        "permission_checked": permission_checked,
        "runtime_blockers_checked": runtime_blockers_checked,
        "status": "cached" if checked else "not_checked",
    }


def cached_desktop_permission_diagnostics() -> dict[str, Any]:
    """Return a passive snapshot that never mistakes unknown state for ready."""

    status = desktop_permission_probe_cache_status()
    missing_permissions = cached_desktop_permission_missing_by_capability()
    blocking_conditions = (
        cached_desktop_runtime_blocking_conditions_by_capability()
    )
    if status.get("checked") is not True:
        blocking_conditions = {
            **blocking_conditions,
            "desktop_execution": _ordered_unique(
                [
                    *blocking_conditions.get("desktop_execution", []),
                    "desktop_permission_diagnostics_not_checked",
                ]
            ),
        }
    return {
        **status,
        "missing_permissions": missing_permissions,
        "blocking_conditions": blocking_conditions,
    }


def clear_desktop_permission_probe_cache() -> None:
    """Clear the readiness permission cache after explicit diagnostic changes."""

    global _PERMISSION_CACHE, _RUNTIME_BLOCKER_CACHE
    _PERMISSION_CACHE = None
    _RUNTIME_BLOCKER_CACHE = None


def _probe_screen_capture(missing: dict[str, list[str]]) -> None:
    result = _check_screen_capture_permission()
    if bool(result.get("allowed") or result.get("ok")):
        return
    if result.get("permission_denied"):
        _add_missing(missing, "screen_capture", "screen_recording")
    else:
        _add_missing(missing, "screen_capture", "screen_capture_probe_failed")


def _screen_capture_blank(result: Mapping[str, Any]) -> bool:
    if result.get("ok") is not True or result.get("allowed") is not True:
        return False
    return (
        result.get("blank_frame") is True
        or str(result.get("visibility_status") or "").strip() == "blank_black"
    )


def _probe_active_window(missing: dict[str, list[str]]) -> None:
    ok, _output = _run_osascript(
        """
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            return name of frontApp
        end tell
        """,
        timeout=3.0,
    )
    if not ok:
        _add_missing(missing, "active_window", "automation_or_accessibility")


def _probe_app_control(missing: dict[str, list[str]]) -> None:
    if not _command_exists("open"):
        _add_missing(missing, "app_control", "open_command")
    ok, _output = _run_osascript('id of application "Finder"', timeout=3.0)
    if not ok:
        _add_missing(missing, "app_control", "automation")
        return
    automation_ok, _automation_output = _run_osascript(
        'tell application "Finder" to return name',
        timeout=3.0,
    )
    if not automation_ok:
        _add_missing(missing, "app_control", "automation")


def _probe_media_control(missing: dict[str, list[str]]) -> None:
    ok, _output = _run_osascript('id of application "Music"', timeout=3.0)
    if not ok:
        _add_missing(missing, "media_control", "music_app")
        return
    automation_ok, _automation_output = _run_osascript(
        'tell application "Music" to return name',
        timeout=3.0,
    )
    if not automation_ok:
        _add_missing(missing, "media_control", "automation")


def _probe_foreground_activation(missing: dict[str, list[str]]) -> None:
    result = _check_foreground_activation()
    if result.get("verified"):
        return
    if result.get("permission_denied"):
        _add_missing(missing, "foreground_activation", "automation_or_accessibility")


def _probe_foreground_input(missing: dict[str, list[str]]) -> None:
    ok, output = _run_osascript(
        'tell application "System Events" to return UI elements enabled',
        timeout=3.0,
    )
    if not ok or str(output or "").strip().lower() not in {"true", "yes", "1"}:
        _add_missing(missing, "foreground_input", "accessibility")


def _probe_browser_control(missing: dict[str, list[str]]) -> None:
    cdp_url = _configured_browser_cdp_url()
    if not cdp_url or not _browser_cdp_reachable(cdp_url):
        _add_missing(missing, "browser_control", "chrome_cdp")


def _check_screen_capture_permission() -> Mapping[str, Any]:
    from apps.locald.screenshot import check_screen_capture_permission

    return check_screen_capture_permission(open_settings=False)


def _check_foreground_activation() -> dict[str, Any]:
    ok, output = _run_osascript(
        """
        set targetName to "Finder"
        set originalName to ""
        set originalBundleId to ""
        tell application "System Events"
            try
                set originalProc to first application process whose frontmost is true
                set originalName to name of originalProc
                try
                    set originalBundleId to bundle identifier of originalProc
                end try
            end try
        end tell
        tell application targetName to activate
        delay 0.2
        set targetFrontmost to false
        set frontName to ""
        tell application "System Events"
            try
                set targetProc to first application process whose name is targetName
                try
                    set frontmost of targetProc to true
                end try
                delay 0.1
                try
                    set targetFrontmost to frontmost of targetProc
                end try
            end try
            try
                set frontName to name of first application process whose frontmost is true
            end try
        end tell
        if originalName is not "" and originalName is not targetName then
            try
                tell application originalName to activate
            end try
        end if
        return "foreground_activation|" & targetName & "|" & (targetFrontmost as text) & "|" & frontName & "|" & originalName & "|" & originalBundleId
        """,
        timeout=4.0,
    )
    if not ok:
        return {
            "verified": False,
            "permission_denied": _looks_like_permission_error(output),
            "output": output,
        }
    parts = str(output or "").strip().split("|")
    if len(parts) < 4 or parts[0] != "foreground_activation":
        return {"verified": False, "output": output}
    target_name = parts[1].strip()
    target_frontmost = parts[2].strip().lower() in {"true", "yes", "1"}
    front_name = parts[3].strip()
    return {
        "verified": target_frontmost or front_name == target_name,
        "target_app": target_name,
        "frontmost_app": front_name,
        "original_app": parts[4].strip() if len(parts) > 4 else "",
        "original_bundle_id": parts[5].strip() if len(parts) > 5 else "",
        "output": output,
    }


def _run_osascript(script: str, *, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return False, str(exc)
    output = "\n".join(
        part.strip()
        for part in (result.stdout, result.stderr)
        if isinstance(part, str) and part.strip()
    )
    return result.returncode == 0, output


def _configured_browser_cdp_url() -> str:
    try:
        from apps.shell.agent.tools import browser
    except Exception:
        return ""
    return browser._configured_browser_cdp_url()


def _browser_cdp_reachable(raw_url: str) -> bool:
    parsed = urlparse(str(raw_url or "").strip())
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _env_value(name: str) -> str:
    try:
        import os

        return str(os.environ.get(name) or "").strip()
    except Exception:
        return ""


def _command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def _macos_desktop_session_locked() -> bool:
    if not _command_exists("ioreg"):
        return False
    try:
        result = subprocess.run(
            ["ioreg", "-n", "Root", "-d1"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except Exception:
        return False
    output = "\n".join(
        part.strip()
        for part in (result.stdout, result.stderr)
        if isinstance(part, str) and part.strip()
    )
    normalized = output.replace(" ", "").lower()
    return "cgssessionscreenislocked\"=yes" in normalized or "cgssessionscreenislocked=yes" in normalized


def _looks_like_permission_error(value: Any) -> bool:
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
            "tcc",
        )
    )


def _desktop_platform(platform_name: str | None = None) -> str:
    raw = str(platform_name or platform.system() or "").strip().lower()
    if raw in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    if raw.startswith("win"):
        return "windows"
    if raw == "linux":
        return "linux"
    return raw or "unknown"


def _add_missing(missing: dict[str, list[str]], capability_id: str, token: str) -> None:
    clean_token = str(token or "").strip()
    if not clean_token:
        return
    values = missing.setdefault(capability_id, [])
    if clean_token not in values:
        values.append(clean_token)


def _copy_missing(missing: Mapping[str, list[str]]) -> dict[str, list[str]]:
    return {str(key): list(values) for key, values in missing.items()}


def _ordered_unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values or []:
        clean = str(value or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result
