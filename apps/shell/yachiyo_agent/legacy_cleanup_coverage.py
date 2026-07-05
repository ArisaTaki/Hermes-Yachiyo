"""Runtime Planner coverage used to bound legacy desktop cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LegacyDesktopMigrationSample:
    prompt: str
    area: str
    planner_owner: str = "runtime_planner"
    legacy_boundary: str = "legacy_daily_desktop_intent"


MIGRATED_DAILY_DESKTOP_SAMPLES: tuple[LegacyDesktopMigrationSample, ...] = (
    LegacyDesktopMigrationSample("微信关闭窗口", "desktop_window"),
    LegacyDesktopMigrationSample("在 VS Code 里执行命令 Format Document", "desktop_shortcut"),
    LegacyDesktopMigrationSample("把当前网页链接粘贴到 Slack", "context_transfer"),
    LegacyDesktopMigrationSample("在 Slack 粘贴当前网页链接", "context_transfer"),
    LegacyDesktopMigrationSample("复制当前网页内容", "context_transfer"),
    LegacyDesktopMigrationSample("把选中的内容填到当前输入框", "context_transfer"),
    LegacyDesktopMigrationSample("把当前网页链接输入到地址栏", "context_transfer"),
    LegacyDesktopMigrationSample("把当前页面内容输入到搜索框", "context_transfer"),
    LegacyDesktopMigrationSample("把当前网页链接输入到 Slack 搜索框", "context_transfer"),
    LegacyDesktopMigrationSample("把当前页面内容输入到 Slack 搜索框", "context_transfer"),
    LegacyDesktopMigrationSample("打开 Slack 搜索框输入选中的内容", "context_transfer"),
    LegacyDesktopMigrationSample("Finder look for Downloads", "file_search"),
    LegacyDesktopMigrationSample("微信打开搜索", "app_search"),
    LegacyDesktopMigrationSample("Chrome 点登录", "ui_targeting"),
    LegacyDesktopMigrationSample("把当前网页链接加入提醒事项", "schedule_reminder"),
    LegacyDesktopMigrationSample("把当前网页链接加入日历", "schedule_calendar"),
    LegacyDesktopMigrationSample("创建备忘录", "note_capture"),
)


def migrated_daily_desktop_prompts() -> tuple[str, ...]:
    return tuple(sample.prompt for sample in MIGRATED_DAILY_DESKTOP_SAMPLES)


def legacy_daily_desktop_cleanup_coverage() -> dict[str, Any]:
    areas: dict[str, int] = {}
    for sample in MIGRATED_DAILY_DESKTOP_SAMPLES:
        areas[sample.area] = areas.get(sample.area, 0) + 1
    return {
        "legacy_boundary": "legacy_daily_desktop_intent",
        "planner_owner": "runtime_planner",
        "total_samples": len(MIGRATED_DAILY_DESKTOP_SAMPLES),
        "areas": dict(sorted(areas.items())),
        "prompts": migrated_daily_desktop_prompts(),
    }
