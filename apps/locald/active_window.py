"""活动窗口适配器

macOS 使用 osascript (AppleScript)，后续可扩展跨平台支持。
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone

from packages.protocol.schemas import ActiveWindowResponse

logger = logging.getLogger(__name__)


async def get_active_window() -> ActiveWindowResponse:
    """获取当前活动窗口信息"""
    # macOS: 通过 AppleScript 获取前台应用信息
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set appPID to unix id of frontApp
        try
            set winTitle to name of front window of frontApp
        on error
            set winTitle to "(无窗口标题)"
        end try
        return appName & "|" & appPID & "|" & winTitle
    end tell
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(f"osascript 失败: {result.stderr.strip()}")

        parts = result.stdout.strip().split("|", 2)
        app_name = parts[0] if len(parts) > 0 else "unknown"
        pid = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        title = parts[2] if len(parts) > 2 else ""

        return ActiveWindowResponse(
            title=title,
            app_name=app_name,
            pid=pid,
            queried_at=datetime.now(timezone.utc),
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("获取活动窗口超时")
