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


def _samples(area: str, *prompts: str) -> tuple[LegacyDesktopMigrationSample, ...]:
    return tuple(LegacyDesktopMigrationSample(prompt, area) for prompt in prompts)


MIGRATED_DAILY_DESKTOP_SAMPLES: tuple[LegacyDesktopMigrationSample, ...] = (
    *_samples("desktop_window", "微信关闭窗口", "切到下一个窗口"),
    *_samples("desktop_shortcut", "在 VS Code 里执行命令 Format Document"),
    *_samples(
        "context_transfer",
        "把当前网页链接粘贴到 Slack",
        "在 Slack 粘贴当前网页链接",
        "复制当前网页内容",
        "把选中的内容填到当前输入框",
        "把当前网页链接输入到地址栏",
        "把当前页面内容输入到搜索框",
        "把当前网页链接输入到 Slack 搜索框",
        "把当前页面内容输入到 Slack 搜索框",
        "打开 Slack 搜索框输入选中的内容",
        "把剪贴板内容粘贴到当前输入框",
    ),
    *_samples("file_search", "Finder look for Downloads"),
    *_samples("app_search", "微信打开搜索"),
    *_samples("ui_targeting", "Chrome 点登录", "Slack 点搜索", "微信点搜索", "在 Linear 上的创建按钮点击"),
    *_samples("schedule_reminder", "把当前网页链接加入提醒事项"),
    *_samples("schedule_calendar", "把当前网页链接加入日历"),
    *_samples("note_capture", "创建备忘录"),
    *_samples(
        "app_new_item",
        "打开备忘录新建备忘录",
        "打开提醒事项新建提醒",
        "Calendar new meeting",
        "Outlook 新建邮件",
    ),
    *_samples("finder_location", "打开隔空投送", "Finder 打开网络", "打开最近使用"),
    *_samples("system_settings", "打开网络"),
    *_samples("file_access", "打开下载目录里的最新文件", "显示当前选中文件"),
    *_samples(
        "desktop_discovery",
        "需要什么权限",
        "当前窗口是什么",
        "当前有哪些 App 在运行",
        "show installed apps",
        "截取当前屏幕",
        "显示 Slack 窗口列表",
    ),
    *_samples("app_launch", "打开 PixelForge", "打开微信", "切到 Slack"),
    *_samples(
        "app_management",
        "你能帮我显示Finder吗",
        "Could you quit Slack please?",
        "Chrome 开着吗",
        "显示所有隐藏应用",
    ),
    *_samples("low_level_desktop", "点击坐标 120, 240", "输入 hello"),
    *_samples("foreground_search", "提交当前搜索", "Spotlight 搜索 yachiyo"),
    *_samples("hotkey", "复制选中文本", "微信按回车", "打开 Slack 后按回车"),
    *_samples(
        "foreground_shortcut",
        "打开微信然后全选复制",
        "切到下一个应用",
        "Chrome 最大化",
        "go back one page",
        "Finder 新建文件夹",
    ),
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
