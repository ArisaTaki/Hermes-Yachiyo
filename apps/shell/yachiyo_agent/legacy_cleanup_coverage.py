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


@dataclass(frozen=True)
class LegacyDesktopPlannerContract:
    planner_intents: tuple[str, ...]
    planner_capabilities: tuple[str, ...]
    planner_tools: tuple[str, ...]


def _samples(area: str, *prompts: str) -> tuple[LegacyDesktopMigrationSample, ...]:
    return tuple(LegacyDesktopMigrationSample(prompt, area) for prompt in prompts)


def _fallback_contract(
    fallback_id: str,
    title: str,
    reason: str,
    example_prompts: list[str],
    required_before_delete: list[str],
) -> dict[str, Any]:
    return {
        "fallback_id": fallback_id,
        "title": title,
        "reason": reason,
        "owner": "runtime_planner",
        "planner_owner": "runtime_planner",
        "legacy_boundary": "legacy_daily_desktop_intent",
        "status": "planner_covered_compat_cleanup_pending",
        "planner_coverage_status": "planner_covered",
        "cleanup_blocker": "legacy_response_shape_compatibility",
        "example_prompts": example_prompts,
        "planner_evidence_prompts": example_prompts,
        "required_before_delete": required_before_delete,
    }


AREA_PLANNER_CONTRACTS: dict[str, LegacyDesktopPlannerContract] = {
    "app_launch": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.app_control"),
        (
            "desktop.list_apps",
            "app.open",
            "app.focus",
            "desktop.active_window",
            "desktop.verify",
        ),
    ),
    "app_management": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.app_control"),
        (
            "desktop.list_apps",
            "desktop.running_apps",
            "desktop.list_windows",
            "app.show",
            "app.quit",
            "app.status",
            "desktop.show_all_apps",
        ),
    ),
    "app_new_item": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "desktop.inspect_app",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ),
    ),
    "app_search": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "desktop.inspect_app",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ),
    ),
    "context_transfer": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation", "desktop.app_control"),
        (
            "desktop.list_apps",
            "desktop.safe_shortcut",
            "app.focus_and_safe_shortcut",
            "app.focus",
            "app.open",
            "desktop.ui_elements",
        ),
    ),
    "desktop_discovery": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery",),
        (
            "desktop.permissions",
            "desktop.active_window",
            "desktop.running_apps",
            "desktop.list_apps",
            "screen.capture",
            "desktop.windows",
        ),
    ),
    "desktop_shortcut": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.app_control", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ),
    ),
    "desktop_window": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.app_control", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "app.focus",
            "desktop.close_window",
            "desktop.active_window",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ),
    ),
    "file_access": LegacyDesktopPlannerContract(
        ("file_access",),
        ("file.desktop_access",),
        ("desktop.open_path", "desktop.reveal_path"),
    ),
    "file_search": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.app_control", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.ui_elements",
        ),
    ),
    "finder_location": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "desktop.inspect_app",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "desktop.ui_elements",
        ),
    ),
    "foreground_search": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.ui_operation",),
        ("desktop.search_submit", "desktop.safe_shortcut", "desktop.safe_type_text"),
    ),
    "foreground_shortcut": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "desktop.inspect_app",
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ),
    ),
    "hotkey": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        (
            "desktop.list_apps",
            "desktop.safe_shortcut",
            "app.focus_and_hotkey",
            "app.open_and_hotkey",
            "desktop.ui_elements",
        ),
    ),
    "low_level_desktop": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        ("desktop.safe_click", "desktop.safe_type_text", "desktop.ui_elements"),
    ),
    "note_capture": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        ("desktop.safe_shortcut", "desktop.ui_elements"),
    ),
    "schedule_calendar": LegacyDesktopPlannerContract(
        ("schedule",),
        ("browser.research", "schedule.reminder"),
        ("desktop.safe_shortcut", "desktop.list_apps", "app.open_and_safe_shortcut"),
    ),
    "schedule_reminder": LegacyDesktopPlannerContract(
        ("schedule",),
        ("browser.research", "schedule.reminder"),
        ("desktop.safe_shortcut", "desktop.list_apps", "app.open_and_safe_shortcut"),
    ),
    "system_settings": LegacyDesktopPlannerContract(
        ("system_control",),
        ("system.control",),
        ("system.settings_open",),
    ),
    "ui_targeting": LegacyDesktopPlannerContract(
        ("desktop_operation",),
        ("desktop.app_discovery", "desktop.ui_operation"),
        ("desktop.list_apps", "desktop.inspect_app", "desktop.ui_elements"),
    ),
}


PLANNER_OWNED_LEGACY_ENTRYPOINTS: tuple[dict[str, Any], ...] = (
    {
        "entrypoint_id": "media_playback_facade",
        "title": "Legacy media playback facade",
        "tools": ["media.music_app_open_and_play", "media.apple_music_play", "media.apple_music_status"],
        "example_prompts": ["能帮我播放 Apple Music 吗", "打开 Spotify 搜索 Taylor Swift 并播放"],
    },
    {
        "entrypoint_id": "simple_app_facade",
        "title": "Legacy app open/focus/status facade",
        "tools": ["app.open", "app.focus", "app.status"],
        "example_prompts": ["可以帮我打开 Word 吗", "切到 Slack", "Chrome 开着吗"],
    },
    {
        "entrypoint_id": "file_access_facade",
        "title": "Legacy local file access facade",
        "tools": ["desktop.open_path", "desktop.reveal_path"],
        "example_prompts": ["打开下载目录里的最新文件", "显示当前选中文件"],
    },
    {
        "entrypoint_id": "browser_navigation_facade",
        "title": "Legacy browser navigation facade",
        "tools": ["browser.open_url"],
        "example_prompts": ["打开 GitHub 首页", "上 B 站"],
    },
    {
        "entrypoint_id": "safe_app_action_facade",
        "title": "Legacy app-scoped safe action facade",
        "tools": [
            "app.focus_and_safe_key",
            "app.focus_and_safe_scroll",
            "app.focus_and_safe_shortcut",
            "app.open_and_safe_shortcut",
        ],
        "example_prompts": ["Chrome 新建无痕窗口", "在 Slack 里按 Tab", "Slack 新建消息"],
    },
    {
        "entrypoint_id": "spotlight_search_facade",
        "title": "Legacy Spotlight search facade",
        "tools": ["desktop.safe_shortcut", "desktop.safe_type_text", "desktop.search_submit"],
        "example_prompts": ["Spotlight 搜索 yachiyo", "打开聚焦搜索 yachiyo", "提交当前搜索"],
    },
    {
        "entrypoint_id": "finder_item_shortcut_facade",
        "title": "Legacy Finder selected-item shortcut facade",
        "tools": ["app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"],
        "example_prompts": ["Finder 重命名选中文件", "Finder 上一级目录", "打开 Finder 复制选中文件"],
    },
    {
        "entrypoint_id": "browser_app_search_facade",
        "title": "Legacy browser and app search facade",
        "tools": ["app.focus", "app.focus_and_safe_shortcut", "browser.open_url"],
        "example_prompts": ["Chrome 搜索 OpenAI", "Chrome 新建标签页搜索 OpenAI", "微信打开搜索"],
    },
    {
        "entrypoint_id": "context_transfer_search_box_facade",
        "title": "Legacy context-transfer search-box facade",
        "tools": [
            "desktop.safe_shortcut",
            "desktop.click_ui_element",
            "app.focus_and_click_ui_element",
            "app.open_and_click_ui_element",
        ],
        "example_prompts": [
            "把当前页面内容输入到搜索框",
            "把当前网页链接输入到 Slack 搜索框",
            "打开 Slack 搜索框输入选中的内容",
        ],
    },
    {
        "entrypoint_id": "semantic_ui_targeting_facade",
        "title": "Legacy semantic UI targeting facade",
        "tools": [
            "app.focus_and_click_ui_element",
            "app.open_and_click_ui_element",
            "desktop.click_ui_element",
            "desktop.type_into_ui_element",
        ],
        "example_prompts": [
            "Chrome 点登录",
            "在 Linear 上的创建按钮点击",
            "Can you type hello into the search field?",
        ],
    },
)


REMAINING_FALLBACK_CONTRACTS: tuple[dict[str, Any], ...] = ()


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
    *_samples("foreground_search", "提交当前搜索", "Spotlight 搜索 yachiyo", "打开聚焦搜索 yachiyo"),
    *_samples("hotkey", "复制选中文本", "微信按回车", "打开 Slack 后按回车"),
    *_samples(
        "foreground_shortcut",
        "打开微信然后全选复制",
        "切到下一个应用",
        "Chrome 最大化",
        "go back one page",
        "Finder 新建文件夹",
        "Finder 重命名选中文件",
        "Finder 上一级目录",
        "打开 Finder 复制选中文件",
    ),
)


def migrated_daily_desktop_prompts() -> tuple[str, ...]:
    return tuple(sample.prompt for sample in MIGRATED_DAILY_DESKTOP_SAMPLES)


def legacy_daily_desktop_cleanup_sample_contracts() -> tuple[dict[str, Any], ...]:
    return tuple(_sample_contract(sample) for sample in MIGRATED_DAILY_DESKTOP_SAMPLES)


def legacy_daily_desktop_cleanup_area_contracts() -> tuple[dict[str, Any], ...]:
    area_counts: dict[str, int] = {}
    for sample in MIGRATED_DAILY_DESKTOP_SAMPLES:
        area_counts[sample.area] = area_counts.get(sample.area, 0) + 1
    return tuple(
        {
            "area": area,
            "sample_count": count,
            "planner_intents": list(contract.planner_intents),
            "planner_capabilities": list(contract.planner_capabilities),
            "planner_tools": list(contract.planner_tools),
        }
        for area, count in sorted(area_counts.items())
        for contract in (AREA_PLANNER_CONTRACTS[area],)
    )


def legacy_daily_desktop_cleanup_coverage() -> dict[str, Any]:
    areas: dict[str, int] = {}
    for sample in MIGRATED_DAILY_DESKTOP_SAMPLES:
        areas[sample.area] = areas.get(sample.area, 0) + 1
    area_contracts = legacy_daily_desktop_cleanup_area_contracts()
    sample_contracts = legacy_daily_desktop_cleanup_sample_contracts()
    planner_covered_fallback_count = sum(
        1
        for contract in REMAINING_FALLBACK_CONTRACTS
        if contract.get("planner_coverage_status") == "planner_covered"
    )
    compatibility_cleanup_pending_count = sum(
        1
        for contract in REMAINING_FALLBACK_CONTRACTS
        if contract.get("cleanup_blocker") == "legacy_response_shape_compatibility"
    )
    cleanup_readiness = (
        "legacy_fallbacks_eliminated"
        if not REMAINING_FALLBACK_CONTRACTS
        else "planner_covered_compat_cleanup_pending"
    )
    return {
        "legacy_boundary": "legacy_daily_desktop_intent",
        "planner_owner": "runtime_planner",
        "total_samples": len(MIGRATED_DAILY_DESKTOP_SAMPLES),
        "cleanup_readiness": cleanup_readiness,
        "remaining_fallback_count": len(REMAINING_FALLBACK_CONTRACTS),
        "planner_covered_fallback_count": planner_covered_fallback_count,
        "compatibility_cleanup_pending_count": compatibility_cleanup_pending_count,
        "areas": dict(sorted(areas.items())),
        "prompts": migrated_daily_desktop_prompts(),
        "covered_intents": _sorted_unique(
            intent
            for contract in area_contracts
            for intent in contract["planner_intents"]
        ),
        "covered_capabilities": _sorted_unique(
            capability
            for contract in area_contracts
            for capability in contract["planner_capabilities"]
        ),
        "covered_tools": _sorted_unique(
            tool
            for contract in area_contracts
            for tool in contract["planner_tools"]
        ),
        "area_contracts": area_contracts,
        "sample_contracts": sample_contracts,
        "planner_owned_entrypoints": PLANNER_OWNED_LEGACY_ENTRYPOINTS,
        "remaining_fallback_contracts": REMAINING_FALLBACK_CONTRACTS,
    }


def _sample_contract(sample: LegacyDesktopMigrationSample) -> dict[str, Any]:
    contract = AREA_PLANNER_CONTRACTS[sample.area]
    return {
        "prompt": sample.prompt,
        "area": sample.area,
        "planner_owner": sample.planner_owner,
        "legacy_boundary": sample.legacy_boundary,
        "cleanup_status": "planner_covered",
        "planner_intents": list(contract.planner_intents),
        "planner_capabilities": list(contract.planner_capabilities),
        "planner_tools": list(contract.planner_tools),
    }


def _sorted_unique(values: Any) -> list[str]:
    return sorted({str(value) for value in values if str(value)})
