"""Handler 共享格式化工具

提供统一的状态标签、时间格式化等工具函数。
"""

from __future__ import annotations

import re

# 完整标签（含文字）
STATUS_LABEL: dict[str, str] = {
    "pending":   "⏳ 等待中",
    "running":   "🔄 运行中",
    "completed": "✅ 已完成",
    "cancelled": "🚫 已取消",
    "failed":    "❌ 已失败",
}

# 仅图标（用于列表紧凑展示）
STATUS_ICON: dict[str, str] = {
    "pending":   "⏳",
    "running":   "🔄",
    "completed": "✅",
    "cancelled": "🚫",
    "failed":    "❌",
}


def fmt_status(status: str) -> str:
    """status 枚举值 → 带图标中文标签"""
    return STATUS_LABEL.get(status, f"❓ {status}")


def fmt_status_icon(status: str) -> str:
    """status 枚举值 → 仅图标"""
    return STATUS_ICON.get(status, "❓")


def fmt_uptime(seconds: float) -> str:
    """秒数 → 人类可读运行时长（如 '2h 3m 5s' / '5m 3s' / '3s'）"""
    secs = int(seconds)
    mins, secs = divmod(secs, 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}h {mins}m {secs}s"
    if mins:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def fmt_dt(dt_str: str) -> str:
    """ISO 8601 字符串 → 短格式 'MM-DD HH:MM:SS'"""
    if not dt_str:
        return "—"
    try:
        m = re.match(r"\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})", str(dt_str))
        if m:
            return f"{m.group(1)} {m.group(2)}"
    except Exception:
        pass
    return str(dt_str)[:19]
