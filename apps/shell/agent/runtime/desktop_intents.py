"""Conservative daily desktop intent planner for Chat entrypoints."""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote_plus, urlparse

from apps.shell.agent.runtime.app_aliases import (
    APP_ALIASES as _APP_ALIASES,
    BROWSER_APP_NAMES as _BROWSER_APP_NAMES,
    BROWSER_INTERNAL_PAGE_PATHS as _BROWSER_INTERNAL_PAGE_PATHS,
    BROWSER_INTERNAL_PAGE_SCHEMES as _BROWSER_INTERNAL_PAGE_SCHEMES,
    COMMUNICATION_APP_NAMES as _COMMUNICATION_APP_NAMES,
    EMAIL_APP_NAMES as _EMAIL_APP_NAMES,
    compact_app_alias as _compact_app_alias,
    known_app_followup_aliases as _shared_known_app_followup_aliases,
)
from apps.shell.agent.runtime.desktop_recovery_metadata import (
    daily_desktop_metadata_tool_request as _recovery_metadata_tool_request,
    daily_desktop_recovery_prompt as _recovery_prompt,
)
from apps.shell.agent.runtime.hotkeys import parse_hotkey_combo
from apps.shell.agent.runtime.media_apps import (
    compact_music_app_name,
    is_known_music_app_compact,
    known_music_app_name,
)
from apps.shell.agent.runtime.path_aliases import common_desktop_path_alias
from apps.shell.agent.runtime.web_destinations import (
    browser_only_web_destination_url,
    known_web_destination_url,
)

_TERMINAL_COMMAND_HEADS = {
    "awk",
    "brew",
    "cat",
    "cargo",
    "curl",
    "date",
    "df",
    "du",
    "echo",
    "find",
    "git",
    "go",
    "grep",
    "ifconfig",
    "ls",
    "make",
    "netstat",
    "node",
    "npm",
    "pnpm",
    "ps",
    "pwd",
    "pytest",
    "python",
    "python3",
    "rg",
    "ruby",
    "sed",
    "sw_vers",
    "uname",
    "uv",
    "whoami",
    "yarn",
}

_APP_STATUS_PATTERNS = (
    r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:看看|查看|检查|确认)?\s*"
    r"(?P<app>[^。！？!?，,]+?)\s*(?:开没开|开了没|开着没|打开没|打开了没|启动没|启动了没)"
    r"\s*(?:吗|嘛|呢)?$",
    r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:看看|查看|检查|确认)?\s*"
    r"(?P<app>[^。！？!?，,]+?)\s*(?:是否|有没有|是不是)?\s*"
    r"(?:开着|打开着|打开了|开了吗|打开了吗|在运行|正在运行|运行|运行着|启动了|启动着)\s*(?:吗|嘛|呢)?$",
    r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:看看|查看|检查|确认)(?:一下|下)?\s*"
    r"(?P<app>[^。！？!?，,]+?)\s*(?:是否|有没有|有无)(?:已经)?\s*"
    r"(?:打开|开启)\s*(?:了|吗|嘛|呢)?$",
    r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:看看|查看|检查|确认)(?:一下|下)?\s*"
    r"(?P<app>[^。！？!?，,]+?)\s*(?:是否|有没有|是不是)?\s*"
    r"(?:开没开|开了没|开着没|打开没|打开了没|开着|打开着|打开了|在运行|正在运行|运行|运行着|启动了|启动着)",
    r"(?:is|check if|whether|see if|verify(?: that)?|confirm(?: that)?)\s+"
    r"(?P<app>[^.!?]+?)\s+(?:is\s+)?(?:running|open)",
    r"(?:check|see)\s+whether\s+(?P<app>[^.!?]+?)\s+(?:is\s+)?(?:running|open)",
    r"(?P<app>[^.!?]+?)\s+(?:running|open)\?",
)


def daily_desktop_intent_tool_request(
    context: str,
    allowed_tools: list[str],
) -> dict[str, Any] | None:
    """Return a structured desktop tool request for clear daily Chat intents."""

    requests = daily_desktop_intent_tool_requests(context, allowed_tools)
    return requests[0] if requests else None


def daily_desktop_intent_tool_requests(
    context: str,
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    """Return structured desktop tool requests for clear daily Chat intents."""

    allowed = {str(tool or "").strip() for tool in allowed_tools}
    if _system_screen_saver_start_request(context):
        if "system.screen_saver_start" in allowed:
            return [_request("system.screen_saver_start", {})]
        return []
    direct_safe_shortcut = _desktop_safe_shortcut_action(context)
    if direct_safe_shortcut and "desktop.safe_shortcut" in allowed:
        return [_request("desktop.safe_shortcut", {"action": direct_safe_shortcut})]
    spotlight_search_sequence = _spotlight_search_tool_requests(context)
    if spotlight_search_sequence:
        if all(str(request.get("tool") or "") in allowed for request in spotlight_search_sequence):
            return spotlight_search_sequence
        return []
    app_command_palette_sequence = _app_command_palette_tool_requests(context)
    if app_command_palette_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in app_command_palette_sequence
        ):
            return app_command_palette_sequence
        return []
    finder_special_location = _finder_special_location_tool_request(context)
    if finder_special_location:
        if str(finder_special_location.get("tool") or "") in allowed:
            return [finder_special_location]
        return []
    known_app_alias = _known_open_app_alias_name(context)
    if known_app_alias:
        if "app.open" in allowed:
            return [_request("app.open", {"app_name": known_app_alias})]
        return []
    app_scoped_low_risk_action = _app_scoped_low_risk_foreground_action_tool_request(context)
    if app_scoped_low_risk_action:
        low_risk_tool = str(app_scoped_low_risk_action.get("tool") or "")
        if low_risk_tool in allowed:
            return [app_scoped_low_risk_action]
        if _app_scoped_low_risk_action_should_not_fallback(app_scoped_low_risk_action):
            return []
    system_settings_target = _direct_system_settings_tool_target(context)
    if system_settings_target and "system.settings_open" in allowed:
        return [_request("system.settings_open", {"target": system_settings_target})]
    if _is_desktop_permissions_request(context):
        if "desktop.permissions" in allowed:
            return [_request("desktop.permissions", {})]
        return []
    direct_volume_payload = _system_volume_request(context)
    if direct_volume_payload is not None:
        if "system.volume" in allowed:
            return [_request("system.volume", direct_volume_payload)]
        return []
    app_scoped_hotkey = _app_scoped_hotkey_tool_request(context)
    if app_scoped_hotkey:
        if str(app_scoped_hotkey.get("tool") or "") in allowed:
            return [app_scoped_hotkey]
        return []
    sequence = _prefer_system_settings_open_sequence(
        daily_desktop_intent_sequence_candidates(context),
        allowed,
    )
    selected_text_read_sequence = _selected_text_read_tool_requests(context)
    if selected_text_read_sequence and all(
        str(request.get("tool") or "") in allowed for request in selected_text_read_sequence
    ):
        return selected_text_read_sequence
    communication_selected_text_sequence = _communication_selected_text_tool_requests(context)
    if communication_selected_text_sequence and all(
        str(request.get("tool") or "") in allowed for request in communication_selected_text_sequence
    ):
        return communication_selected_text_sequence
    communication_current_page_link_sequence = _communication_current_page_link_tool_requests(context)
    if communication_current_page_link_sequence and all(
        str(request.get("tool") or "") in allowed for request in communication_current_page_link_sequence
    ):
        return communication_current_page_link_sequence
    communication_current_content_sequence = _communication_current_content_tool_requests(context)
    if communication_current_content_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in communication_current_content_sequence
        ):
            return communication_current_content_sequence
        return []
    communication_paste_sequence = _communication_paste_tool_requests(context)
    if communication_paste_sequence and all(
        str(request.get("tool") or "") in allowed for request in communication_paste_sequence
    ):
        return communication_paste_sequence
    communication_compose_sequence = _communication_compose_tool_requests(context)
    if communication_compose_sequence and all(
        str(request.get("tool") or "") in allowed for request in communication_compose_sequence
    ):
        return communication_compose_sequence
    selected_text_to_note_sequence = _selected_text_to_note_tool_requests(context)
    if selected_text_to_note_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in selected_text_to_note_sequence
        ):
            return selected_text_to_note_sequence
        return []
    current_page_link_to_note_sequence = _current_page_link_to_note_tool_requests(context)
    if current_page_link_to_note_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in current_page_link_to_note_sequence
        ):
            return current_page_link_to_note_sequence
        return []
    current_content_to_note_sequence = _current_content_to_note_tool_requests(context)
    if current_content_to_note_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in current_content_to_note_sequence
        ):
            return current_content_to_note_sequence
        return []
    current_content_copy_sequence = _current_content_copy_to_clipboard_tool_requests(context)
    if current_content_copy_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in current_content_copy_sequence
        ):
            return current_content_copy_sequence
        return []
    dynamic_source_to_reminder_sequence = _dynamic_source_to_reminder_tool_requests(context)
    if dynamic_source_to_reminder_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in dynamic_source_to_reminder_sequence
        ):
            return dynamic_source_to_reminder_sequence
        return []
    dynamic_source_to_calendar_sequence = _dynamic_source_to_calendar_tool_requests(context)
    if dynamic_source_to_calendar_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in dynamic_source_to_calendar_sequence
        ):
            return dynamic_source_to_calendar_sequence
        return []
    dynamic_source_search_sequence = _browser_dynamic_source_search_tool_requests(context)
    if dynamic_source_search_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in dynamic_source_search_sequence
        ):
            return dynamic_source_search_sequence
        return []
    dynamic_source_open_sequence = _browser_dynamic_source_open_tool_requests(context)
    if dynamic_source_open_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in dynamic_source_open_sequence
        ):
            return dynamic_source_open_sequence
        return []
    if _current_content_foreground_paste_request(context):
        return []
    dynamic_source_ui_sequence = _dynamic_source_to_ui_element_tool_requests(context)
    if dynamic_source_ui_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in dynamic_source_ui_sequence
        ):
            return dynamic_source_ui_sequence
        return []
    if _current_content_foreground_input_request(context):
        return []
    dynamic_source_paste_sequence = _dynamic_source_paste_tool_requests(context)
    if dynamic_source_paste_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in dynamic_source_paste_sequence
        ):
            return dynamic_source_paste_sequence
        return []
    clipboard_to_note_sequence = _clipboard_to_note_tool_requests(context)
    if clipboard_to_note_sequence and all(
        str(request.get("tool") or "") in allowed for request in clipboard_to_note_sequence
    ):
        return clipboard_to_note_sequence
    app_search_navigation_sequence = _app_open_or_focus_search_navigation_tool_requests(context)
    if app_search_navigation_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in app_search_navigation_sequence
        ):
            return app_search_navigation_sequence
        return []
    english_app_search_sequence = _english_app_scoped_search_tool_requests(context)
    if english_app_search_sequence and all(
        str(request.get("tool") or "") in allowed for request in english_app_search_sequence
    ):
        return english_app_search_sequence
    browser_shortcut_search_sequence = _app_open_or_focus_browser_shortcut_search_tool_requests(context)
    if browser_shortcut_search_sequence and all(
        str(request.get("tool") or "") in allowed for request in browser_shortcut_search_sequence
    ):
        return browser_shortcut_search_sequence
    app_browser_search_sequence = _app_open_or_focus_browser_search_tool_requests(context)
    if app_browser_search_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_browser_search_sequence
    ):
        return app_browser_search_sequence
    site_search_sequence = _browser_site_search_tool_requests(context)
    if site_search_sequence:
        if all(str(request.get("tool") or "") in allowed for request in site_search_sequence):
            return site_search_sequence
        return []
    browser_search_click_sequence = _browser_search_then_click_tool_requests(context)
    if browser_search_click_sequence and all(
        str(request.get("tool") or "") in allowed for request in browser_search_click_sequence
    ):
        return browser_search_click_sequence
    current_page_link_copy_sequence = _browser_current_page_link_copy_tool_requests(context)
    if current_page_link_copy_sequence and all(
        str(request.get("tool") or "") in allowed for request in current_page_link_copy_sequence
    ):
        return current_page_link_copy_sequence
    direct_clipboard_text = _clipboard_write_text(context)
    if direct_clipboard_text:
        if "clipboard.write" in allowed:
            return [_request("clipboard.write", {"text": direct_clipboard_text})]
        return []
    if _is_quit_current_app_request(context) and "desktop.quit_app" in allowed:
        return [_request("desktop.quit_app", {})]
    system_hotkey = _system_desktop_hotkey_request(context)
    if system_hotkey and "desktop.hotkey" in allowed:
        return [_request("desktop.hotkey", system_hotkey)]
    direct_hotkey = _desktop_hotkey(context)
    if direct_hotkey and not _desktop_safe_key(context) and "desktop.hotkey" in allowed:
        return [_request("desktop.hotkey", direct_hotkey)]
    finder_safe_action = _app_open_or_focus_foreground_action_request(context)
    if (
        finder_safe_action
        and str(finder_safe_action.get("tool") or "") in {
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
        }
    ):
        finder_input = (
            finder_safe_action.get("input") if isinstance(finder_safe_action.get("input"), dict) else {}
        )
        if (
            finder_input.get("app_name") == "Finder"
            and finder_input.get("action")
            in {
                "finder_quick_look",
                "finder_get_info",
                "new_folder",
                "rename_selected",
                "parent_folder",
                "copy",
            }
            and str(finder_safe_action.get("tool") or "") in allowed
        ):
            return [
                _request(
                    str(finder_safe_action.get("tool") or ""),
                    dict(finder_input),
                )
            ]
    app_close_window_sequence = _app_open_or_focus_close_window_tool_requests(context)
    if app_close_window_sequence:
        if all(str(request.get("tool") or "") in allowed for request in app_close_window_sequence):
            return app_close_window_sequence
        return []
    app_window_management_sequence = _app_open_or_focus_window_management_tool_requests(context)
    if app_window_management_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in app_window_management_sequence
        ):
            return app_window_management_sequence
        return []
    app_find_open_first_sequence = _app_open_or_focus_find_open_first_tool_requests(context)
    if app_find_open_first_sequence:
        if all(
            str(request.get("tool") or "") in allowed for request in app_find_open_first_sequence
        ):
            return app_find_open_first_sequence
        return []
    click_type_sequence = _app_open_or_focus_click_type_tool_requests(context)
    if click_type_sequence:
        if all(str(request.get("tool") or "") in allowed for request in click_type_sequence):
            return click_type_sequence
        return []
    app_prefix_click_type_sequence = _app_prefix_click_type_tool_requests(context)
    if app_prefix_click_type_sequence:
        if all(
            str(request.get("tool") or "") in allowed for request in app_prefix_click_type_sequence
        ):
            return app_prefix_click_type_sequence
        return []
    app_click_submit_sequence = _app_open_or_focus_click_submit_tool_requests(context)
    if app_click_submit_sequence:
        if all(
            str(request.get("tool") or "") in allowed for request in app_click_submit_sequence
        ):
            return app_click_submit_sequence
        return []
    if (
        sequence
        and _should_prioritize_foreground_sequence(sequence)
        and all(str(request.get("tool") or "") in allowed for request in sequence)
    ):
        return sequence
    address_bar_url = _browser_address_bar_url(context)
    if address_bar_url and "browser.open_url" in allowed:
        return [_request("browser.open_url", {"url": address_bar_url})]
    if _is_apple_music_status_request(context):
        if "media.apple_music_status" in allowed:
            return [_request("media.apple_music_status", {})]
        return []
    generic_music_play_app = _music_app_generic_play_open_name(context)
    if generic_music_play_app:
        if generic_music_play_app == "Music":
            if "media.music_app_open_and_play" in allowed:
                return [
                    _request(
                        "media.music_app_open_and_play",
                        {"app_name": generic_music_play_app},
                    )
                ]
            if "media.apple_music_open_and_play" in allowed:
                return [_request("media.apple_music_open_and_play", {})]
            if "media.apple_music_control" in allowed:
                return [_request("media.apple_music_control", {"action": "play"})]
            return []
        if "media.music_app_open_and_play" in allowed:
            return [
                _request(
                    "media.music_app_open_and_play",
                    {"app_name": generic_music_play_app},
                )
            ]
        return []
    apple_music_search_play = _apple_music_search_play_query(context)
    music_app_search_play_sequence = _music_app_search_play_tool_requests(context)
    if music_app_search_play_sequence and all(
        str(request.get("tool") or "") in allowed for request in music_app_search_play_sequence
    ):
        return music_app_search_play_sequence
    if apple_music_search_play and "media.apple_music_play" in allowed:
        return [_request("media.apple_music_play", {"query": apple_music_search_play})]
    music_app_control = _music_app_control_request(context)
    if music_app_control:
        if str(music_app_control.get("tool") or "") in allowed:
            return [music_app_control]
        return []
    apple_music_prefix_control = _apple_music_prefix_control_action(context)
    if apple_music_prefix_control and "media.apple_music_control" in allowed:
        return [_request("media.apple_music_control", {"action": apple_music_prefix_control})]
    system_media_control = _system_media_control_request(context)
    if system_media_control and str(system_media_control.get("tool") or "") in allowed:
        return [system_media_control]
    if _is_apple_music_open_and_play_request(context):
        if "media.music_app_open_and_play" in allowed:
            return [_request("media.music_app_open_and_play", {"app_name": "Music"})]
        if "media.apple_music_open_and_play" in allowed:
            return [_request("media.apple_music_open_and_play", {})]
        if "media.apple_music_control" in allowed:
            return [_request("media.apple_music_control", {"action": "play"})]
        return []
    dynamic_source_find_sequence = _dynamic_source_find_tool_requests(context)
    if dynamic_source_find_sequence:
        if all(
            str(request.get("tool") or "") in allowed
            for request in dynamic_source_find_sequence
        ):
            return dynamic_source_find_sequence
        return []
    foreground_find_sequence = _foreground_find_text_tool_requests(context)
    if foreground_find_sequence and all(
        str(request.get("tool") or "") in allowed for request in foreground_find_sequence
    ):
        return foreground_find_sequence
    app_find_sequence = _app_open_or_focus_find_text_tool_requests(context)
    if app_find_sequence and all(str(request.get("tool") or "") in allowed for request in app_find_sequence):
        return app_find_sequence
    app_status_name = _app_status_name(context)
    if app_status_name and "app.status" in allowed:
        return [_request("app.status", {"app_name": app_status_name})]
    if _is_installed_apps_request(context):
        if "desktop.list_apps" in allowed:
            return [_request("desktop.list_apps", {})]
        return []
    if _is_running_apps_request(context):
        if "desktop.running_apps" in allowed:
            return [_request("desktop.running_apps", {})]
        return []
    browser_open_request = _browser_open_url_tool_request(context, allowed)
    if browser_open_request:
        return [browser_open_request]
    browser_internal_page_sequence = _browser_internal_page_tool_requests(context)
    if browser_internal_page_sequence and all(
        str(request.get("tool") or "") in allowed
        for request in browser_internal_page_sequence
    ):
        return browser_internal_page_sequence
    schedule_create_request = _schedule_create_tool_request(context)
    if schedule_create_request and str(schedule_create_request.get("tool") or "") in allowed:
        return [schedule_create_request]
    notes_create_request = _notes_create_tool_request(context)
    if notes_create_request and str(notes_create_request.get("tool") or "") in allowed:
        return [notes_create_request]
    notes_create_type_sequence = _notes_create_and_type_tool_requests(context)
    if notes_create_type_sequence and all(
        str(request.get("tool") or "") in allowed for request in notes_create_type_sequence
    ):
        return notes_create_type_sequence
    reminders_create_type_sequence = _reminders_create_and_type_tool_requests(context)
    if reminders_create_type_sequence and all(
        str(request.get("tool") or "") in allowed for request in reminders_create_type_sequence
    ):
        return reminders_create_type_sequence
    app_scoped_postposed_click = _app_scoped_postposed_click_ui_element_request(context)
    if app_scoped_postposed_click:
        click_app_name = str(app_scoped_postposed_click.get("app_name") or "").strip()
        if click_app_name not in _BROWSER_APP_NAMES:
            if "app.focus_and_click_ui_element" in allowed:
                return [_request("app.focus_and_click_ui_element", app_scoped_postposed_click)]
            return []
    elif _looks_like_app_scoped_postposed_click(context):
        return []
    app_direct_search_sequence = _app_direct_search_type_tool_requests(context)
    if app_direct_search_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_direct_search_sequence
    ):
        return app_direct_search_sequence
    app_submit_foreground_sequence = _app_open_or_focus_submit_foreground_tool_requests(context)
    if app_submit_foreground_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_submit_foreground_sequence
    ):
        return app_submit_foreground_sequence
    foreground_click_search_type_sequence = _foreground_click_search_type_tool_requests(context)
    if foreground_click_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in foreground_click_search_type_sequence):
        return foreground_click_search_type_sequence
    app_scoped_search_type_sequence = _app_scoped_search_type_tool_requests(context)
    if app_scoped_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in app_scoped_search_type_sequence):
        return app_scoped_search_type_sequence
    app_search_type_sequence = _app_open_or_focus_search_type_tool_requests(context)
    if app_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in app_search_type_sequence):
        return app_search_type_sequence
    app_type_into_ui_element_sequence = _app_open_or_focus_type_into_ui_element_tool_requests(context)
    if app_type_into_ui_element_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_type_into_ui_element_sequence
    ):
        return app_type_into_ui_element_sequence
    click_type_sequence = _app_open_or_focus_click_type_tool_requests(context)
    if click_type_sequence:
        if all(str(request.get("tool") or "") in allowed for request in click_type_sequence):
            return click_type_sequence
        return []
    app_prefix_click_type_sequence = _app_prefix_click_type_tool_requests(context)
    if app_prefix_click_type_sequence:
        if all(
            str(request.get("tool") or "") in allowed for request in app_prefix_click_type_sequence
        ):
            return app_prefix_click_type_sequence
        return []
    app_browser_action_sequence = _app_open_or_focus_browser_action_tool_requests(context)
    if app_browser_action_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_browser_action_sequence
    ):
        return app_browser_action_sequence
    app_prefix_browser_action_sequence = _app_prefix_browser_action_tool_requests(context)
    if app_prefix_browser_action_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_prefix_browser_action_sequence
    ):
        return app_prefix_browser_action_sequence
    app_prefix_safe_type_text_sequence = _app_prefix_safe_type_text_tool_requests(context)
    if app_prefix_safe_type_text_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_prefix_safe_type_text_sequence
    ):
        return app_prefix_safe_type_text_sequence
    app_prefix_click_ui_element = _app_prefix_click_ui_element_tool_request(context)
    if app_prefix_click_ui_element and str(app_prefix_click_ui_element.get("tool") or "") in allowed:
        return [app_prefix_click_ui_element]
    app_scoped_low_risk_action = _app_scoped_low_risk_foreground_action_tool_request(context)
    if app_scoped_low_risk_action:
        low_risk_tool = str(app_scoped_low_risk_action.get("tool") or "")
        if low_risk_tool in allowed:
            return [app_scoped_low_risk_action]
        if _app_scoped_low_risk_action_should_not_fallback(app_scoped_low_risk_action):
            return []
    app_scoped_hotkey = _app_scoped_hotkey_tool_request(context)
    if app_scoped_hotkey:
        if str(app_scoped_hotkey.get("tool") or "") in allowed:
            return [app_scoped_hotkey]
        return []
    app_prefix_foreground_action = _app_prefix_foreground_action_tool_request(context)
    if app_prefix_foreground_action and str(app_prefix_foreground_action.get("tool") or "") in allowed:
        return [app_prefix_foreground_action]
    foreground_safe_key = _desktop_safe_key(context)
    if foreground_safe_key and "desktop.safe_key" in allowed:
        return [_request("desktop.safe_key", foreground_safe_key)]
    desktop_path_request = _desktop_path_tool_request(context)
    if desktop_path_request and str(desktop_path_request.get("tool") or "") in allowed:
        return [desktop_path_request]
    shortcut_type_sequence = _app_open_or_focus_shortcut_type_tool_requests(context)
    if shortcut_type_sequence and all(str(request.get("tool") or "") in allowed for request in shortcut_type_sequence):
        return shortcut_type_sequence
    shortcut_sequence = _app_open_or_focus_safe_shortcut_sequence_tool_requests(context)
    if shortcut_sequence and all(str(request.get("tool") or "") in allowed for request in shortcut_sequence):
        return shortcut_sequence
    app_prefix_shortcut_sequence = _app_prefix_safe_shortcut_sequence_tool_requests(context)
    if app_prefix_shortcut_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_prefix_shortcut_sequence
    ):
        return app_prefix_shortcut_sequence
    foreground_shortcut_sequence = _foreground_safe_shortcut_sequence_tool_requests(context)
    if foreground_shortcut_sequence and all(str(request.get("tool") or "") in allowed for request in foreground_shortcut_sequence):
        return foreground_shortcut_sequence
    app_shortcut = _app_scoped_safe_shortcut_tool_request(context)
    if app_shortcut and str(app_shortcut.get("tool") or "") in allowed:
        return [app_shortcut]
    app_preposed_observe_sequence = _prefer_system_settings_open_sequence(
        _app_preposed_observe_tool_requests(context),
        allowed,
    )
    if app_preposed_observe_sequence and all(str(request.get("tool") or "") in allowed for request in app_preposed_observe_sequence):
        return app_preposed_observe_sequence
    app_observe_sequence = _prefer_system_settings_open_sequence(
        _app_open_or_focus_observe_tool_requests(context),
        allowed,
    )
    if app_observe_sequence and all(str(request.get("tool") or "") in allowed for request in app_observe_sequence):
        return app_observe_sequence
    app_prefix_observe_sequence = _prefer_system_settings_open_sequence(
        _app_prefix_observe_tool_requests(context),
        allowed,
    )
    if app_prefix_observe_sequence and all(str(request.get("tool") or "") in allowed for request in app_prefix_observe_sequence):
        return app_prefix_observe_sequence
    app_ui_elements = _prefer_system_settings_open_sequence(
        _app_scoped_ui_elements_tool_requests(context),
        allowed,
    )
    if app_ui_elements and all(str(request.get("tool") or "") in allowed for request in app_ui_elements):
        return app_ui_elements
    app_screen_capture_sequence = _prefer_system_settings_open_sequence(
        _app_open_or_focus_screen_capture_tool_requests(context),
        allowed,
    )
    if app_screen_capture_sequence and all(str(request.get("tool") or "") in allowed for request in app_screen_capture_sequence):
        return app_screen_capture_sequence
    foreground_type_into_ui_element = (
        None
        if (
            _app_scoped_type_into_ui_element_request(context)
            or _app_open_or_focus_click_type_tool_requests(context)
            or _app_prefix_click_type_tool_requests(context)
        )
        else _desktop_type_into_ui_element(context)
    )
    if foreground_type_into_ui_element and "desktop.type_into_ui_element" in allowed:
        foreground_type_sequence = [_request("desktop.type_into_ui_element", foreground_type_into_ui_element)]
        if _typed_text_has_return_followup(
            context,
            str(foreground_type_into_ui_element.get("target") or ""),
        ):
            foreground_type_sequence.append(
                _request("desktop.hotkey", {"key": "return", "modifiers": []})
            )
        elif _typed_text_has_submit_followup(context):
            foreground_type_sequence.append(
                _request("desktop.submit_foreground", {"action": "send"})
            )
        if all(str(request.get("tool") or "") in allowed for request in foreground_type_sequence):
            return foreground_type_sequence
    foreground_search_type_sequence = _foreground_search_type_tool_requests(context)
    if foreground_search_type_sequence and all(str(request.get("tool") or "") in allowed for request in foreground_search_type_sequence):
        return foreground_search_type_sequence
    if sequence and all(str(request.get("tool") or "") in allowed for request in sequence):
        return sequence
    app_open_or_focus_safe_type_text_sequence = _app_open_or_focus_safe_type_text_tool_requests(context)
    if app_open_or_focus_safe_type_text_sequence and all(
        str(request.get("tool") or "") in allowed
        for request in app_open_or_focus_safe_type_text_sequence
    ):
        return app_open_or_focus_safe_type_text_sequence
    app_find_sequence = _app_open_or_focus_find_text_tool_requests(context)
    if app_find_sequence and all(str(request.get("tool") or "") in allowed for request in app_find_sequence):
        return app_find_sequence
    app_safe_key = _app_prefix_safe_key_tool_request(context)
    if app_safe_key and str(app_safe_key.get("tool") or "") in allowed:
        return [app_safe_key]
    app_open_or_focus_safe_key = _app_open_or_focus_safe_key_tool_request(context)
    if app_open_or_focus_safe_key and str(app_open_or_focus_safe_key.get("tool") or "") in allowed:
        return [app_open_or_focus_safe_key]
    app_safe_click = _app_prefix_safe_click_tool_request(context)
    if app_safe_click and str(app_safe_click.get("tool") or "") in allowed:
        return [app_safe_click]
    app_safe_type_text_sequence = _app_prefix_safe_type_text_tool_requests(context)
    if app_safe_type_text_sequence and all(
        str(request.get("tool") or "") in allowed for request in app_safe_type_text_sequence
    ):
        return app_safe_type_text_sequence
    app_window_management = _app_prefix_window_management_tool_request(context)
    if app_window_management and str(app_window_management.get("tool") or "") in allowed:
        return [app_window_management]
    app_scoped_ui_action = _app_scoped_ui_action_tool_request(context)
    if app_scoped_ui_action:
        if str(app_scoped_ui_action.get("tool") or "") in allowed:
            return [app_scoped_ui_action]
        return []
    for request in daily_desktop_intent_candidates(context):
        if str(request.get("tool") or "") in allowed:
            return [request]
    return []


def daily_desktop_entrypoint_tool_requests(
    context: str,
    allowed_tools: list[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic desktop requests for Chat/Bubble/Live2D entrypoints."""

    direct_request = daily_desktop_metadata_tool_request(metadata, allowed_tools)
    if direct_request:
        return [direct_request]
    planning_context = daily_desktop_recovery_prompt(metadata) or context
    return daily_desktop_intent_tool_requests(planning_context, allowed_tools)


def daily_desktop_intent_sequence_candidates(context: str) -> list[dict[str, Any]]:
    """Return ordered foreground desktop tool requests for explicit multi-step intents."""

    text = _clean_text(context)
    if (
        not text
        or _looks_like_negative_request(text)
        or _is_desktop_permissions_request(text)
        or _looks_like_explanation_request(text)
    ):
        return []
    clauses = _split_daily_desktop_sequence(text)
    if len(clauses) < 2:
        return []
    requests: list[dict[str, Any]] = []
    for clause in clauses[:5]:
        stripped_clause = _strip_sequence_clause_prefix(clause)
        handled_input_followup, input_followup_requests = _typed_input_followup_requests(
            stripped_clause,
            requests,
        )
        if handled_input_followup:
            requests.extend(input_followup_requests)
            continue
        search_type_requests = (
            _app_direct_search_type_tool_requests(stripped_clause)
            or _app_scoped_search_type_tool_requests(stripped_clause)
            or _app_open_or_focus_search_type_tool_requests(stripped_clause)
            or _foreground_search_type_tool_requests(stripped_clause)
        )
        if search_type_requests:
            requests.extend(search_type_requests)
            continue
        request = _first_daily_desktop_candidate(stripped_clause)
        if request is None:
            find_requests = _app_context_find_text_requests(stripped_clause, requests)
            if find_requests:
                requests.extend(find_requests)
                continue
            click_requests = _app_context_click_ui_element_requests(stripped_clause, requests)
            if not click_requests:
                return []
            requests.extend(click_requests)
            continue
        requests.append(request)
    if len(requests) < 2:
        return []
    requests = _coalesce_app_foreground_sequence(requests)
    if not requests:
        return []
    if not _is_foreground_desktop_sequence(requests):
        return []
    return requests


def _should_prioritize_foreground_sequence(requests: list[dict[str, Any]]) -> bool:
    if (
        _is_browser_url_safe_type_sequence(requests)
        or _is_browser_address_bar_type_sequence(requests)
        or _is_foreground_address_bar_type_sequence(requests)
        or _is_foreground_url_safe_type_sequence(requests)
        or _is_inline_click_type_sequence(requests)
    ):
        return False
    tools = {str(request.get("tool") or "") for request in requests}
    priority_tools = {
        "desktop.hotkey",
        "desktop.submit_foreground",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
    }
    return bool(tools & priority_tools)


def _is_browser_url_safe_type_sequence(requests: list[dict[str, Any]]) -> bool:
    if len(requests) != 2:
        return False
    first, second = requests
    first_tool = str(first.get("tool") or "")
    if first_tool not in {"app.open_and_safe_type_text", "app.focus_and_safe_type_text"}:
        return False
    first_input = first.get("input") if isinstance(first.get("input"), dict) else {}
    app_name = str(first_input.get("app_name") or "").strip()
    typed_text = str(first_input.get("text") or "").strip()
    if app_name not in _BROWSER_APP_NAMES or not _browser_address_bar_target_url(typed_text):
        return False
    second_tool = str(second.get("tool") or "")
    second_input = second.get("input") if isinstance(second.get("input"), dict) else {}
    return second_tool == "desktop.hotkey" and second_input == {"key": "return", "modifiers": []}


def _is_browser_address_bar_type_sequence(requests: list[dict[str, Any]]) -> bool:
    if len(requests) != 1:
        return False
    request = requests[0]
    tool = str(request.get("tool") or "")
    if tool not in {"app.open_and_type_into_ui_element", "app.focus_and_type_into_ui_element"}:
        return False
    payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    app_name = str(payload.get("app_name") or "").strip()
    target = str(payload.get("target") or "").strip()
    typed_text = str(payload.get("text") or "").strip()
    return (
        app_name in _BROWSER_APP_NAMES
        and bool(re.search(r"(?:地址|address)", target, flags=re.IGNORECASE))
        and bool(_browser_address_bar_target_url(typed_text))
    )


def _is_foreground_address_bar_type_sequence(requests: list[dict[str, Any]]) -> bool:
    if len(requests) not in {1, 2}:
        return False
    first = requests[0]
    if str(first.get("tool") or "") != "desktop.type_into_ui_element":
        return False
    payload = first.get("input") if isinstance(first.get("input"), dict) else {}
    target = str(payload.get("target") or "").strip()
    typed_text = str(payload.get("text") or "").strip()
    if not (
        re.search(r"(?:地址|address)", target, flags=re.IGNORECASE)
        and _browser_address_bar_target_url(typed_text)
    ):
        return False
    if len(requests) == 1:
        return True
    second = requests[1]
    second_input = second.get("input") if isinstance(second.get("input"), dict) else {}
    return str(second.get("tool") or "") == "desktop.hotkey" and second_input == {
        "key": "return",
        "modifiers": [],
    }


def _is_foreground_url_safe_type_sequence(requests: list[dict[str, Any]]) -> bool:
    if len(requests) != 2:
        return False
    first, second = requests
    if str(first.get("tool") or "") != "desktop.safe_type_text":
        return False
    first_input = first.get("input") if isinstance(first.get("input"), dict) else {}
    typed_text = str(first_input.get("text") or "").strip()
    if not typed_text or not _browser_address_bar_url(f"type {typed_text}"):
        return False
    second_input = second.get("input") if isinstance(second.get("input"), dict) else {}
    return str(second.get("tool") or "") == "desktop.hotkey" and second_input == {
        "key": "return",
        "modifiers": [],
    }


def _is_inline_click_type_sequence(requests: list[dict[str, Any]]) -> bool:
    click_tools = {
        "desktop.click_ui_element",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
    }
    for request in requests:
        if str(request.get("tool") or "") not in click_tools:
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        target = str(payload.get("target") or "").strip()
        if re.search(
            r"(?:输入|填写|键入|打入|填入|写入|写|打字|打上|打).+|"
            r"\b(?:type|enter|input|fill)\b.+",
            target,
            flags=re.IGNORECASE,
        ):
            return True
    return False


_BROWSER_SEARCH_INPUT_SELECTOR = (
    'input[type="search"], input[name="q"], textarea[name="q"], '
    'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
    'input[aria-label*="search" i], input[placeholder*="search" i]'
)

_BROWSER_TEXT_INPUT_SELECTOR = (
    'input:not([type]), input[type="text"], input[type="search"], '
    'textarea, [contenteditable="true"]'
)

_FOREGROUND_SEQUENCE_TOOLS = {
    "app.open",
    "app.focus",
    "app.show",
    "app.open_and_safe_type_text",
    "app.focus_and_safe_type_text",
    "app.open_and_safe_shortcut",
    "app.focus_and_safe_shortcut",
    "app.open_and_safe_key",
    "app.focus_and_safe_key",
    "app.open_and_hotkey",
    "app.focus_and_hotkey",
    "app.open_and_safe_scroll",
    "app.focus_and_safe_scroll",
    "app.open_and_safe_click",
    "app.focus_and_safe_click",
    "app.open_and_click_ui_element",
    "app.focus_and_click_ui_element",
    "app.open_and_type_into_ui_element",
    "app.focus_and_type_into_ui_element",
    "desktop.hide_app",
    "desktop.show_all_apps",
    "desktop.minimize_window",
    "desktop.safe_click",
    "desktop.safe_key",
    "desktop.safe_scroll",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.click",
    "desktop.close_window",
    "desktop.hotkey",
    "desktop.submit_foreground",
    "desktop.type_text",
    "screen.capture",
}

_APP_SEQUENCE_CONTEXT_TOOLS = {
    "app.open",
    "app.focus",
    "app.show",
    "app.open_and_safe_type_text",
    "app.focus_and_safe_type_text",
    "app.open_and_safe_shortcut",
    "app.focus_and_safe_shortcut",
    "app.open_and_safe_key",
    "app.focus_and_safe_key",
    "app.open_and_hotkey",
    "app.focus_and_hotkey",
    "app.open_and_safe_scroll",
    "app.focus_and_safe_scroll",
    "app.open_and_safe_click",
    "app.focus_and_safe_click",
    "app.open_and_click_ui_element",
    "app.focus_and_click_ui_element",
    "app.open_and_type_into_ui_element",
    "app.focus_and_type_into_ui_element",
}

_FOREGROUND_ACTION_TOOLS = {
    "desktop.click",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.close_window",
    "desktop.quit_app",
    "desktop.hotkey",
    "desktop.submit_foreground",
    "desktop.safe_click",
    "desktop.safe_key",
    "desktop.safe_scroll",
    "desktop.safe_shortcut",
    "desktop.safe_type_text",
    "desktop.search_submit",
    "desktop.type_text",
}


def daily_desktop_metadata_tool_request(
    metadata: Mapping[str, Any] | None,
    allowed_tools: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return an exact daily desktop request carried by trusted UI metadata."""

    return _recovery_metadata_tool_request(metadata, allowed_tools)


def daily_desktop_recovery_prompt(metadata: Mapping[str, Any] | None) -> str:
    """Build a deterministic low-risk prompt from a structured recovery action."""

    return _recovery_prompt(metadata)


def _split_daily_desktop_sequence(text: str) -> list[str]:
    coordinate_comma = "__YACHIYO_COORD_COMMA__"
    protected_text = re.sub(
        r"(?P<x>\d+(?:\.\d+)?)\s*[,，]\s*(?P<y>\d+(?:\.\d+)?)",
        lambda match: f"{match.group('x')}{coordinate_comma}{match.group('y')}",
        str(text or "").strip(),
    )
    parts = re.split(
        r"(?:[，,；;。]\s*|\s+(?:and then|then)\s+|"
        r"\s+and\s+(?=(?:press|type|enter|click|scroll|send|submit|confirm|"
        r"paste|copy|search|find|look\s+up)\b)|"
        r"(?:然后|接着|之后|随后|并且|并|后(?!退))\s*)",
        protected_text,
        flags=re.IGNORECASE,
    )
    return [
        _strip_query(part.replace(coordinate_comma, ", "))
        for part in parts
        if _strip_query(part.replace(coordinate_comma, ", "))
    ]


def _strip_sequence_clause_prefix(text: str) -> str:
    return re.sub(
        r"^(?:再|然后|接着|之后|随后|并且|并|后(?!退)|and then|then)\s*",
        "",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _first_daily_desktop_candidate(text: str) -> dict[str, Any] | None:
    app_shortcut = _app_scoped_safe_shortcut_tool_request(text)
    if app_shortcut and str(app_shortcut.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_shortcut
    app_safe_key = _app_prefix_safe_key_tool_request(text)
    if app_safe_key and str(app_safe_key.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_safe_key
    app_open_or_focus_safe_key = _app_open_or_focus_safe_key_tool_request(text)
    if (
        app_open_or_focus_safe_key
        and str(app_open_or_focus_safe_key.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS
    ):
        return app_open_or_focus_safe_key
    app_safe_click = _app_prefix_safe_click_tool_request(text)
    if app_safe_click and str(app_safe_click.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_safe_click
    app_safe_type_text = _app_prefix_safe_type_text_tool_request(text)
    if app_safe_type_text and str(app_safe_type_text.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_safe_type_text
    app_ui_action = _app_scoped_ui_action_tool_request(text)
    if app_ui_action and str(app_ui_action.get("tool") or "") in _FOREGROUND_SEQUENCE_TOOLS:
        return app_ui_action
    for request in daily_desktop_intent_candidates(text):
        tool = str(request.get("tool") or "")
        if tool in _FOREGROUND_SEQUENCE_TOOLS:
            return request
    return None


def _desktop_path_tool_request(text: str) -> dict[str, Any] | None:
    open_path = _desktop_open_path(text)
    if open_path:
        return _request("desktop.open_path", {"path": open_path})
    reveal_path = _desktop_reveal_path(text)
    if reveal_path:
        return _request("desktop.reveal_path", {"path": reveal_path})
    return None


def _browser_open_url_tool_request(text: str, allowed: set[str]) -> dict[str, Any] | None:
    if _looks_like_explanation_request(text):
        return None
    new_tab_search_url = _browser_new_tab_search_url(text)
    if new_tab_search_url and "browser.open_url" in allowed:
        return _request("browser.open_url", {"url": new_tab_search_url})
    browser_summary_request = _is_browser_summary_request(text)
    open_extract_payload = _browser_open_url_and_extract_text_request(text)
    if open_extract_payload and "browser.open_url_and_extract_text" in allowed:
        return _request(
            "browser.open_url_and_extract_text",
            open_extract_payload,
            presentation="summary" if browser_summary_request else "",
        )
    open_screenshot_payload = _browser_open_url_and_screenshot_request(text)
    if open_screenshot_payload and "browser.open_url_and_screenshot" in allowed:
        return _request("browser.open_url_and_screenshot", open_screenshot_payload)
    browser_open_target_url = _browser_open_target_url(text)
    if browser_open_target_url and "browser.open_url" in allowed:
        return _request("browser.open_url", {"url": browser_open_target_url})
    return None


def _browser_internal_page_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _app_open_or_focus_browser_followup_match(text)
    if not parsed:
        return []
    mode, _raw_app, app_name, followup = parsed
    scheme = _BROWSER_INTERNAL_PAGE_SCHEMES.get(app_name)
    if not scheme:
        return []
    path = _browser_internal_page_path(followup)
    if not path:
        return []
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "focus_address_bar"},
        ),
        _request("desktop.safe_type_text", {"text": f"{scheme}://{path}/"}),
        _request("desktop.search_submit", {}),
    ]


def _browser_internal_page_path(value: str) -> str:
    phrase = _strip_query(value)
    phrase = re.sub(
        r"^(?:打开|开启|查看|看看|显示|进入|启动|拉起|open|show|view|go\s+to)\s*",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"\s*(?:一下|下|页面|页|page|panel|pane|manager|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)$",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    compact = re.sub(r"[\s._/-]+", "", phrase.lower())
    mapping = {
        "下载": "downloads",
        "下载内容": "downloads",
        "下载列表": "downloads",
        "下载记录": "downloads",
        "下载管理": "downloads",
        "downloads": "downloads",
        "download": "downloads",
        "downloadslist": "downloads",
        "downloadhistory": "downloads",
        "downloadmanager": "downloads",
        "书签": "bookmarks",
        "书签栏": "bookmarks",
        "书签页面": "bookmarks",
        "书签管理": "bookmarks",
        "书签管理器": "bookmarks",
        "bookmarks": "bookmarks",
        "bookmark": "bookmarks",
        "bookmarkmanager": "bookmarks",
        "扩展": "extensions",
        "扩展程序": "extensions",
        "扩展页面": "extensions",
        "扩展管理": "extensions",
        "扩展管理器": "extensions",
        "插件": "extensions",
        "插件管理": "extensions",
        "extensions": "extensions",
        "extension": "extensions",
        "extensionmanager": "extensions",
    }
    return _BROWSER_INTERNAL_PAGE_PATHS.get(mapping.get(compact, ""), "")


def _coalesce_app_foreground_sequence(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    coalesced: list[dict[str, Any]] = []
    index = 0
    while index < len(requests):
        current = requests[index]
        next_request = requests[index + 1] if index + 1 < len(requests) else None
        composite = _app_foreground_sequence_composite(current, next_request)
        if composite:
            coalesced.append(composite)
            index += 2
            continue
        coalesced.append(current)
        index += 1
    return coalesced


def _app_foreground_sequence_composite(
    app_request: dict[str, Any],
    action_request: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not action_request:
        return None
    app_tool = str(app_request.get("tool") or "")
    if app_tool not in {"app.open", "app.focus"}:
        return None
    action_tool = str(action_request.get("tool") or "")
    app_input = app_request.get("input") if isinstance(app_request.get("input"), dict) else {}
    action_input = action_request.get("input") if isinstance(action_request.get("input"), dict) else {}
    app_name = str(app_input.get("app_name") or "").strip()
    if not app_name:
        return None
    mode = "open" if app_tool == "app.open" else "focus"
    if action_tool == "desktop.safe_type_text":
        text = str(action_input.get("text") or "").strip()
        if text:
            return _request(
                f"app.{mode}_and_safe_type_text",
                {"app_name": app_name, "text": text},
            )
    if action_tool == "desktop.safe_shortcut":
        action = str(action_input.get("action") or "").strip()
        if action:
            return _request(
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": action},
            )
    if action_tool == "desktop.safe_key":
        action = str(action_input.get("action") or "").strip()
        repeat_count = action_input.get("repeat_count", 1)
        if action:
            return _request(
                f"app.{mode}_and_safe_key",
                {"app_name": app_name, "action": action, "repeat_count": repeat_count},
            )
    if action_tool == "desktop.hotkey":
        key = str(action_input.get("key") or "").strip()
        modifiers = action_input.get("modifiers")
        if key:
            return _request(
                f"app.{mode}_and_hotkey",
                {
                    "app_name": app_name,
                    "key": key,
                    "modifiers": modifiers if isinstance(modifiers, list) else [],
                },
            )
    if action_tool == "desktop.safe_scroll":
        direction = str(action_input.get("direction") or "").strip()
        pages = action_input.get("pages", 1)
        if direction:
            return _request(
                f"app.{mode}_and_safe_scroll",
                {"app_name": app_name, "direction": direction, "pages": pages},
            )
    if action_tool == "desktop.safe_click":
        if action_input.get("x") is not None and action_input.get("y") is not None:
            return _request(
                f"app.{mode}_and_safe_click",
                {"app_name": app_name, "x": action_input.get("x"), "y": action_input.get("y")},
            )
    if action_tool == "desktop.click_ui_element":
        target = str(action_input.get("target") or "").strip()
        if target:
            return _request(
                f"app.{mode}_and_click_ui_element",
                {
                    "app_name": app_name,
                    "target": target,
                    "role_filter": action_input.get("role_filter", ""),
                    "limit": action_input.get("limit", 80),
                    "click_count": action_input.get("click_count", 1),
                },
            )
    if action_tool == "desktop.type_into_ui_element":
        target = str(action_input.get("target") or "").strip()
        text = str(action_input.get("text") or "").strip()
        if target and text:
            return _request(
                f"app.{mode}_and_type_into_ui_element",
                {
                    "app_name": app_name,
                    "target": target,
                    "text": text,
                    "role_filter": action_input.get("role_filter", ""),
                    "limit": action_input.get("limit", 80),
                },
            )
    return None


def _is_foreground_desktop_sequence(requests: list[dict[str, Any]]) -> bool:
    tools = [str(request.get("tool") or "") for request in requests]
    if not tools or any(tool not in _FOREGROUND_SEQUENCE_TOOLS for tool in tools):
        return False
    if tools[0] == "screen.capture":
        return all(tool in _FOREGROUND_ACTION_TOOLS for tool in tools[1:])
    if tools[0] in _APP_SEQUENCE_CONTEXT_TOOLS:
        return all(tool in _FOREGROUND_ACTION_TOOLS for tool in tools[1:])
    return all(tool in _FOREGROUND_ACTION_TOOLS for tool in tools)


def _app_context_find_text_requests(
    text: str,
    previous_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _latest_sequence_app_context_is_browser(previous_requests):
        return []
    if not _latest_sequence_app_context_name(previous_requests):
        return []
    query = _desktop_find_query(text)
    if not query:
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "find"}),
        _request("desktop.safe_type_text", {"text": query}),
    ]


def _app_context_click_ui_element_requests(
    text: str,
    previous_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _latest_sequence_app_context_name(previous_requests):
        return []
    click_payload = _desktop_click_ui_element(text, require_context=False)
    if not click_payload:
        return []
    return [_request("desktop.click_ui_element", click_payload)]


def _typed_input_followup_requests(
    text: str,
    previous_requests: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    input_request = _latest_sequence_typed_input_request(previous_requests)
    if input_request is not None and _is_input_return_followup(text, input_request):
        return True, [_request("desktop.hotkey", {"key": "return", "modifiers": []})]
    search_text_request = _latest_sequence_search_text_request(previous_requests)
    if search_text_request is not None and _is_input_return_followup(
        text,
        {"input": {"target": "搜索"}},
    ):
        return True, [_request("desktop.search_submit", {})]
    if input_request is None:
        return False, []
    submit_action = _external_submit_followup_action(text)
    if submit_action:
        return True, [_request("desktop.submit_foreground", {"action": submit_action})]
    return False, []


def _latest_sequence_typed_input_request(
    requests: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for request in reversed(requests):
        tool = str(request.get("tool") or "").strip()
        if tool in {
            "desktop.type_into_ui_element",
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
        }:
            return request
        if tool not in {"app.open", "app.focus"}:
            break
    return None


def _latest_sequence_search_text_request(
    requests: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(requests) < 2:
        return None
    text_request = requests[-1]
    text_tool = str(text_request.get("tool") or "").strip()
    if text_tool != "desktop.safe_type_text":
        return None
    shortcut_request = requests[-2]
    shortcut_tool = str(shortcut_request.get("tool") or "").strip()
    if shortcut_tool not in {
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
    }:
        return None
    shortcut_input = (
        shortcut_request.get("input") if isinstance(shortcut_request.get("input"), dict) else {}
    )
    if str(shortcut_input.get("action") or "").strip() != "find":
        return None
    return text_request


def _is_input_return_followup(text: str, input_request: dict[str, Any]) -> bool:
    hotkey = _desktop_hotkey(text)
    if hotkey == {"key": "return", "modifiers": []}:
        return True
    phrase = _normalize_named_hotkey_phrase(text)
    if phrase in {"确认", "确定", "回车", "enter", "return"}:
        return True
    if phrase not in {"搜索", "查找", "检索", "访问", "打开", "search", "find", "go", "visit", "open"}:
        return False
    payload = input_request.get("input") if isinstance(input_request.get("input"), dict) else {}
    target = str(payload.get("target") or "").strip().lower()
    return bool(
        re.search(
            r"(?:搜索|查找|检索|地址|网址|url|search|find|query|address)",
            target,
            flags=re.IGNORECASE,
        )
    )


def _external_submit_followup_action(text: str) -> str:
    return _submit_foreground_action_for_phrase(_normalize_submit_foreground_phrase(text))


def _desktop_search_submit_request(text: str) -> bool:
    phrase = _normalize_submit_foreground_phrase(text)
    return phrase in {
        "提交搜索",
        "提交当前搜索",
        "搜索提交",
        "确认搜索",
        "确定搜索",
        "回车搜索",
        "按回车搜索",
        "按下回车搜索",
        "开始搜索",
        "执行搜索",
        "提交查找",
        "确认查找",
        "确定查找",
        "回车查找",
        "按回车查找",
        "submitsearch",
        "submitcurrentsearch",
        "confirmsearch",
        "runsearch",
        "startsearch",
        "pressentertosearch",
        "hitentertosearch",
        "submitfind",
        "confirmfind",
        "pressentertofind",
    }


def _desktop_submit_foreground_action(text: str) -> str:
    return _submit_foreground_action_for_phrase(_normalize_submit_foreground_phrase(text))


def _normalize_submit_foreground_phrase(text: str) -> str:
    phrase = _strip_query(text)
    phrase = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?\s*",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"\s*(?:一下|下|一次|可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)$",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[\s._-]+", "", phrase.lower())


def _submit_foreground_action_for_phrase(phrase: str) -> str:
    for candidate in _submit_foreground_phrase_candidates(phrase):
        return_key_action = _submit_foreground_action_from_return_key_phrase(candidate)
        if return_key_action:
            return return_key_action
        if candidate in {
            "发送",
            "发出",
            "发送当前内容",
            "发送当前输入",
            "发送当前文本",
            "发送当前消息",
            "发送消息",
            "把消息发出",
            "当前内容发送",
            "当前输入发送",
            "当前文本发送",
            "当前消息发送",
            "消息发送",
            "确认发送",
            "send",
            "sendcurrentcontent",
            "sendthecurrentcontent",
            "sendcurrentinput",
            "sendcurrenttext",
            "sendmessage",
            "sendcurrentmessage",
            "sendthecurrentmessage",
            "sendcurrentchatmessage",
            "post",
        }:
            return "send"
        if candidate in {
            "提交",
            "提交当前内容",
            "提交当前输入",
            "提交当前文本",
            "提交当前表单",
            "提交表单",
            "当前内容提交",
            "当前输入提交",
            "当前文本提交",
            "当前表单提交",
            "表单提交",
            "submit",
            "submitcurrentcontent",
            "submitthecurrentcontent",
            "submitcurrentinput",
            "submitcurrenttext",
            "submitcurrentform",
            "submitthecurrentform",
            "submitform",
        }:
            return "submit"
        if candidate in {
            "确认当前内容",
            "确认当前输入",
            "确认当前文本",
            "确认当前对话框",
            "确认当前弹窗",
            "确认当前操作",
            "确认操作",
            "确认",
            "确定",
            "confirm",
            "confirmcurrentcontent",
            "confirmthecurrentcontent",
            "confirmcurrentinput",
            "confirmcurrenttext",
            "confirmcurrentdialog",
            "confirmthecurrentdialog",
        }:
            return "confirm"
    return ""


def _submit_foreground_phrase_candidates(phrase: str) -> list[str]:
    compact = str(phrase or "").strip()
    if not compact:
        return []
    candidates = [compact]
    scopes = (
        "当前输入框",
        "当前文本框",
        "当前输入栏",
        "当前消息框",
        "当前聊天框",
        "前台输入框",
        "前台文本框",
        "前台输入栏",
        "前台消息框",
        "前台聊天框",
        "当前内容",
        "当前输入",
        "当前文本",
        "当前消息",
        "当前表单",
        "前台内容",
        "前台输入",
        "前台文本",
        "前台消息",
        "前台表单",
        "前台",
        "currentinput",
        "currentfield",
        "currenttextfield",
        "currenttextbox",
        "currentcontent",
        "currenttext",
        "currentmessage",
        "currentchatmessage",
        "currentform",
        "foregroundinput",
        "foregroundfield",
        "foregroundtextfield",
        "foregroundtextbox",
        "foregroundcontent",
        "foregroundtext",
        "foregroundmessage",
        "foregroundchatmessage",
        "foregroundform",
        "activeinput",
        "activefield",
        "activetextfield",
        "activetextbox",
    )
    for scope in scopes:
        if compact.startswith(scope):
            candidates.append(compact[len(scope) :])
        if compact.endswith(scope):
            candidates.append(compact[: -len(scope)])
    return list(dict.fromkeys(candidate for candidate in candidates if candidate))


def _submit_foreground_action_from_return_key_phrase(phrase: str) -> str:
    return_key = r"(?:按|按下|敲|敲下)?(?:一下|下)?(?:回车|enter|return)(?:键)?"
    english_prefix = r"(?:press|hit)(?:enter|return)to"
    if re.fullmatch(rf"(?:{return_key})(?:发送|发出)", phrase) or re.fullmatch(
        rf"{english_prefix}(?:send|post)",
        phrase,
    ):
        return "send"
    if re.fullmatch(rf"(?:{return_key})(?:提交)", phrase) or re.fullmatch(
        rf"{english_prefix}submit",
        phrase,
    ):
        return "submit"
    if re.fullmatch(rf"(?:{return_key})(?:确认|确定)", phrase) or re.fullmatch(
        rf"{english_prefix}(?:confirm|ok)",
        phrase,
    ):
        return "confirm"
    return ""


def _latest_sequence_app_context_is_browser(requests: list[dict[str, Any]]) -> bool:
    app_name = _latest_sequence_app_context_name(requests)
    return bool(app_name and app_name in _BROWSER_APP_NAMES)


def _latest_sequence_app_context_name(requests: list[dict[str, Any]]) -> str:
    for request in reversed(requests):
        tool = str(request.get("tool") or "").strip()
        if tool not in _APP_SEQUENCE_CONTEXT_TOOLS:
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        app_name = str(payload.get("app_name") or "").strip()
        if app_name:
            return app_name
    return ""


def _desktop_find_query(text: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在(?:当前|前台)?(?:窗口|应用|app)?(?:里|中|内|上)?\s*)?"
        r"(?:搜索(?!框|栏|输入框)|搜一下|搜(?!索(?:$|框|栏|输入框)|框|栏)|查找(?!框)|查一下|查查|检索)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:find|search)\s+(?:for\s+)?(?P<query>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_search_query(match.group("query"))
        if query:
            return query
    return ""


def _spotlight_search_tool_requests(text: str) -> list[dict[str, Any]]:
    query = _spotlight_search_query(text)
    if not query:
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "spotlight_search"}),
        _request("desktop.safe_type_text", {"text": query}),
    ]


def _spotlight_search_query(text: str) -> str:
    if _looks_like_explanation_request(text):
        return ""
    raw = _clean_text(text)
    if not raw:
        return ""
    compact = re.sub(r"\s+", "", raw).lower()
    if compact in {
        "聚焦搜索",
        "打开聚焦搜索",
        "显示聚焦搜索",
        "spotlight",
        "打开spotlight",
        "显示spotlight",
        "spotlightsearch",
        "openspotlight",
        "showspotlight",
        "openspotlightsearch",
        "showspotlightsearch",
    }:
        return ""
    target = r"(?:spotlight|聚焦搜索|聚焦|系统搜索)"
    patterns = (
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:use\s+)?(?:spotlight|system\s+search)\s+(?:to\s+)?"
        r"(?:search|find|look\s+for)\s+(?P<query>[^.!?]+)$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:open|launch|start|show)\s+(?:spotlight|system\s+search)\s+"
        r"(?:and\s+)?(?:search|find|look\s+for)\s+(?P<query>[^.!?]+)$",
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:用|使用)?\s*{target}\s*"
        r"(?:搜索|搜一下|搜|查找|查一下|查查|检索)?\s*(?P<query>[^。！？!?]+)$",
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|开启|显示|唤起)\s*{target}\s*"
        r"(?:搜索|搜一下|搜|查找|查一下|查查|检索)?\s*(?P<query>[^。！？!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_search_query(match.group("query"))
        query = re.sub(
            r"^(?:搜索|搜一下|搜|查找|查一下|查查|检索|search|find|look\s+for)\s*",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()
        if _valid_spotlight_search_query(query):
            return query
    return ""


def _valid_spotlight_search_query(query: str) -> bool:
    if not query:
        return False
    if len(query) > 160:
        return False
    if re.search(
        r"(?:然后|并且|并|再|接着|之后|and\s+then|then|and)\s*"
        r"(?:发送|提交|点击|点|打开|播放|删除|关机|重启|"
        r"send|submit|click|open|play|delete|shutdown|restart)",
        query,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _desktop_foreground_find_query(text: str) -> str:
    if _desktop_type_into_ui_element(text):
        return ""
    patterns = (
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:search|find)\s+(?:the\s+)?(?:current|this|active|foreground)\s+"
        r"(?:page|web\s*page|window|app|application|ui|interface)\s+for\s+"
        r"(?P<query_current_en>[^.!?]+)$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:search|find)\s+(?P<query_on_current_en>[^.!?]+?)\s+"
        r"(?:in|on)\s+(?:the\s+)?(?:current|this|active|foreground)\s+"
        r"(?:page|web\s*page|window|app|application|ui|interface)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在\s*)?(?:(?:当前|前台|这个|该)\s*)?"
        r"(?:页面|网页|页内|页面内|窗口|应用|app)(?:里|中|内|上)?\s*"
        r"(?:查找|搜索(?!框)|搜一下|找一下|打开查找(?:框)?(?:并输入|输入)?)\s*"
        r"(?P<query>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在(?:当前|前台)?(?:页面|网页|窗口|应用|app)?(?:里|中|内|上)?\s*)?"
        r"(?:(?:页面|网页|页内|页面内)\s*)?"
        r"(?:查找|找一下|打开查找(?:框)?(?:并输入|输入)?|\bfind\b(?:\s+in\s+page)?)\s*"
        r"(?P<query>[^。！？!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        query = _strip_search_query(
            groups.get("query")
            or groups.get("query_current_en")
            or groups.get("query_on_current_en")
            or ""
        )
        if query:
            return query
    return ""


def daily_desktop_intent_candidates(context: str) -> list[dict[str, Any]]:
    """Return ordered desktop tool candidates before policy filtering."""

    text = _clean_text(context)
    if not text or _looks_like_negative_request(text):
        return []

    candidates: list[dict[str, Any]] = []
    if _is_desktop_permissions_request(text):
        candidates.append(_request("desktop.permissions", {}))
        return candidates

    if _looks_like_explanation_request(text):
        return []

    if _looks_like_project_or_design_request(text):
        return []

    safe_shortcut_action = _desktop_safe_shortcut_action(text)
    if safe_shortcut_action:
        candidates.append(_request("desktop.safe_shortcut", {"action": safe_shortcut_action}))

    candidates.extend(_spotlight_search_tool_requests(text))

    volume_payload = _system_volume_request(text)
    if volume_payload is not None:
        candidates.append(_request("system.volume", volume_payload))

    if _is_quit_current_app_request(text):
        candidates.append(_request("desktop.quit_app", {}))

    system_hotkey = _system_desktop_hotkey_request(text)
    if system_hotkey:
        candidates.append(_request("desktop.hotkey", system_hotkey))

    finder_special_location = _finder_special_location_tool_request(text)
    if finder_special_location:
        candidates.append(finder_special_location)

    known_app_alias = _known_open_app_alias_name(text)
    if known_app_alias:
        candidates.append(_request("app.open", {"app_name": known_app_alias}))

    app_foreground_payload = _app_open_or_focus_foreground_action_request(text)
    if app_foreground_payload:
        candidates.append(
            _request(
                str(app_foreground_payload["tool"]),
                dict(app_foreground_payload["input"]),
            )
        )

    app_prefix_safe_scroll = _app_prefix_safe_scroll_tool_request(text)
    if app_prefix_safe_scroll:
        candidates.append(app_prefix_safe_scroll)

    app_prefix_safe_key = _app_prefix_safe_key_tool_request(text)
    if app_prefix_safe_key:
        candidates.append(app_prefix_safe_key)

    apple_music_prefix_control = _apple_music_prefix_control_action(text)
    if apple_music_prefix_control:
        candidates.append(
            _request("media.apple_music_control", {"action": apple_music_prefix_control})
        )

    app_prefix_safe_click = _app_prefix_safe_click_tool_request(text)
    if app_prefix_safe_click:
        candidates.append(app_prefix_safe_click)

    app_prefix_safe_type_text = _app_prefix_safe_type_text_tool_request(text)
    if app_prefix_safe_type_text:
        candidates.append(app_prefix_safe_type_text)

    app_prefix_window_management = _app_prefix_window_management_tool_request(text)
    if app_prefix_window_management:
        candidates.append(app_prefix_window_management)

    safe_scroll = _desktop_safe_scroll(text)
    if safe_scroll:
        candidates.append(_request("desktop.safe_scroll", safe_scroll))

    safe_key = _desktop_safe_key(text)
    if safe_key:
        candidates.append(_request("desktop.safe_key", safe_key))

    browser_summary_request = _is_browser_summary_request(text)
    open_extract_payload = _browser_open_url_and_extract_text_request(text)
    if open_extract_payload:
        candidates.append(
            _request(
                "browser.open_url_and_extract_text",
                open_extract_payload,
                presentation="summary" if browser_summary_request else "",
            )
        )

    open_screenshot_payload = _browser_open_url_and_screenshot_request(text)
    if open_screenshot_payload:
        candidates.append(_request("browser.open_url_and_screenshot", open_screenshot_payload))

    browser_open_target_url = _browser_open_target_url(text)
    if browser_open_target_url:
        candidates.append(_request("browser.open_url", {"url": browser_open_target_url}))

    if _is_browser_extract_text_request(text) and not browser_open_target_url:
        candidates.append(
            _request(
                "browser.extract_text",
                {},
                presentation="summary" if browser_summary_request else "",
            )
        )

    if _is_browser_screenshot_request(text) and not browser_open_target_url:
        candidates.append(
            _request("browser.screenshot", {"reason": "user asked to capture the browser page"})
        )

    browser_click_payload = _browser_click_request(text)
    if browser_click_payload:
        candidates.append(_request("browser.click", browser_click_payload))

    browser_type_text_payload = _browser_type_text_request(text)
    if browser_type_text_payload:
        candidates.append(_request("browser.type_text", browser_type_text_payload))

    if _is_browser_current_page_request(text):
        candidates.append(_request("browser.current_page", {}))

    brightness_payload = _system_brightness_request(text)
    if brightness_payload is not None:
        candidates.append(_request("system.brightness", brightness_payload))

    if _system_display_sleep_request(text):
        candidates.append(_request("system.display_sleep", {}))

    if _system_screen_saver_start_request(text):
        candidates.append(_request("system.screen_saver_start", {}))

    if _clipboard_read_request(text):
        candidates.append(_request("clipboard.read", {}))

    clipboard_text = _clipboard_write_text(text)
    if clipboard_text:
        candidates.append(_request("clipboard.write", {"text": clipboard_text}))

    schedule_create = _schedule_create_tool_request(text)
    if schedule_create:
        candidates.append(schedule_create)

    notes_create = _notes_create_tool_request(text)
    if notes_create:
        candidates.append(notes_create)

    if _is_installed_apps_request(text):
        candidates.append(_request("desktop.list_apps", {}))

    if _is_running_apps_request(text):
        candidates.append(_request("desktop.running_apps", {}))

    ui_elements_payload = _desktop_ui_elements_request(text)
    if ui_elements_payload is not None:
        candidates.append(_request("desktop.ui_elements", ui_elements_payload))

    windows_payload = _desktop_windows_request(text)
    if windows_payload is not None:
        candidates.append(_request("desktop.windows", windows_payload))

    open_path = _desktop_open_path(text)
    if open_path:
        candidates.append(_request("desktop.open_path", {"path": open_path}))

    reveal_path = _desktop_reveal_path(text)
    if reveal_path:
        candidates.append(_request("desktop.reveal_path", {"path": reveal_path}))

    app_status_name = _app_status_name(text)
    if app_status_name:
        candidates.append(_request("app.status", {"app_name": app_status_name}))

    system_settings_target = _direct_system_settings_tool_target(text)
    if system_settings_target:
        candidates.append(_request("system.settings_open", {"target": system_settings_target}))

    if _is_apple_music_status_request(text):
        candidates.append(_request("media.apple_music_status", {}))

    apple_music_search_play = _apple_music_search_play_query(text)
    music_app_open_and_play = _music_app_open_and_play_app_name(text)
    if music_app_open_and_play:
        candidates.append(
            _request("media.music_app_open_and_play", {"app_name": music_app_open_and_play})
        )

    if apple_music_search_play:
        candidates.append(_request("media.apple_music_play", {"query": apple_music_search_play}))

    music_app_control = _music_app_control_request(text)
    if music_app_control:
        candidates.append(music_app_control)

    system_media_control = _system_media_control_request(text)
    if system_media_control:
        candidates.append(system_media_control)

    if _is_apple_music_open_and_play_request(text):
        candidates.append(_request("media.music_app_open_and_play", {"app_name": "Music"}))
        candidates.append(_request("media.apple_music_open_and_play", {}))
        candidates.append(_request("media.apple_music_control", {"action": "play"}))

    music_control = _music_control_action(text)
    if music_control:
        candidates.append(_request("media.apple_music_control", {"action": music_control}))

    if _is_show_all_apps_request(text):
        candidates.append(_request("desktop.show_all_apps", {}))

    if _is_hide_current_app_request(text):
        candidates.append(_request("desktop.hide_app", {}))

    if _is_minimize_current_app_request(text):
        candidates.append(_request("desktop.minimize_window", {}))

    if _is_minimize_current_window_request(text):
        candidates.append(_request("desktop.minimize_window", {}))

    if _is_close_current_window_request(text):
        candidates.append(_request("desktop.close_window", {}))

    app_show_or_open_name = _app_show_or_open_name(text)
    if app_show_or_open_name:
        candidates.append(_request("app.show", {"app_name": app_show_or_open_name}))

    focus_window_payload = _app_focus_window_payload(text)
    if focus_window_payload:
        candidates.append(_request("app.focus_window", focus_window_payload))

    app_quit_name = _app_quit_name(text)
    if app_quit_name:
        candidates.append(_request("app.quit", {"app_name": app_quit_name}))

    app_show_name = _app_show_name(text)
    if app_show_name:
        candidates.append(_request("app.show", {"app_name": app_show_name}))

    app_hide_name = _app_hide_name(text)
    if app_hide_name:
        candidates.append(_request("app.hide", {"app_name": app_hide_name}))

    app_minimize_name = _app_minimize_name(text)
    if app_minimize_name:
        candidates.append(_request("app.minimize", {"app_name": app_minimize_name}))

    if _desktop_search_submit_request(text):
        candidates.append(_request("desktop.search_submit", {}))

    type_into_ui_element = _desktop_type_into_ui_element(text)
    if type_into_ui_element:
        candidates.append(_request("desktop.type_into_ui_element", type_into_ui_element))

    if not safe_shortcut_action and not _looks_like_app_status_request(text):
        search_url = _browser_search_url(text)
        if search_url:
            candidates.append(_request("browser.open_url", {"url": search_url}))

    music = _music_query(text)
    if music:
        candidates.append(_request("media.apple_music_play", {"query": music}))

    terminal_run_payload = _terminal_run_payload(text)
    if terminal_run_payload:
        candidates.append(_request("terminal.run", terminal_run_payload))

    app_focus_name = _app_focus_name(text)
    if app_focus_name:
        candidates.append(_request("app.focus", {"app_name": app_focus_name}))

    app_name = _app_open_name(text)
    if app_name:
        candidates.append(_request("app.open", {"app_name": app_name}))

    safe_type_text = _desktop_safe_type_text(text)
    if safe_type_text:
        candidates.append(_request("desktop.safe_type_text", {"text": safe_type_text}))

    click_ui_element = _desktop_click_ui_element(text)
    if click_ui_element:
        candidates.append(_request("desktop.click_ui_element", click_ui_element))

    submit_action = _desktop_submit_foreground_action(text)
    if submit_action:
        candidates.append(_request("desktop.submit_foreground", {"action": submit_action}))

    hotkey = _desktop_hotkey(text)
    if hotkey:
        candidates.append(_request("desktop.hotkey", hotkey))

    type_text = _desktop_type_text(text)
    if type_text:
        candidates.append(_request("desktop.type_text", {"text": type_text}))

    safe_click = _desktop_safe_click(text)
    if safe_click:
        candidates.append(_request("desktop.safe_click", safe_click))

    click = _desktop_click(text)
    if click:
        candidates.append(_request("desktop.click", click))

    if _is_screen_capture_request(text) or (
        _is_visual_inspection_followup(text)
        and not _is_active_window_request(text)
        and not _is_bare_visual_inspection_request(text)
    ):
        candidates.append(_request("screen.capture", {"reason": "user asked to capture the screen"}))

    if _is_active_window_request(text):
        candidates.append(_request("desktop.active_window", {}))

    return candidates


def _request(tool: str, payload: dict[str, Any], *, presentation: str = "") -> dict[str, Any]:
    request = {"protocol": "json_fallback", "tool": tool, "input": payload}
    clean_presentation = str(presentation or "").strip()
    if clean_presentation:
        request["presentation"] = clean_presentation
    return request


def _prefer_system_settings_open_sequence(
    requests: list[dict[str, Any]],
    allowed: set[str],
) -> list[dict[str, Any]]:
    if "system.settings_open" not in allowed:
        return requests
    preferred: list[dict[str, Any]] = []
    changed = False
    for request in requests:
        tool = str(request.get("tool") or "")
        payload = request.get("input")
        if (
            tool == "app.open"
            and isinstance(payload, Mapping)
            and payload.get("app_name") == "System Settings"
        ):
            preferred.append(_request("system.settings_open", {"target": "系统设置"}))
            changed = True
            continue
        preferred.append(request)
    return preferred if changed else requests


def _clean_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(
        r"^\s*(?:你|您)?\s*(?:能否|可否)\s*帮我",
        "帮我",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _looks_like_explanation_request(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "怎么",
            "如何",
            "教程",
            "说明",
            "解释",
            "how to",
            "explain",
            "tutorial",
        )
    )


def _looks_like_negative_request(text: str) -> bool:
    return bool(
        re.search(
            r"(?:不要|不用|无需|不需要|别).{0,12}"
            r"(?:执行|操作|调用|真的|实际|播放|截图|截屏|读取|查看|"
            r"输入|打字|打|敲入|键入|点击|点|单击|双击|按键|快捷键|网页|"
            r"关闭|关掉|退出|隐藏|收起|最小化|切换|切到|切回|聚焦|激活|置前|显示|还原)",
            text,
        )
        or re.search(
            r"(?:不要|不用|无需|不需要|别)\s*(?:把|将)?[^。！？!?，,]{0,24}"
            r"(?:打开|启动|运行|拉起|开启|访问|浏览|前往|切换|切到|切回|聚焦|激活|置前|显示|还原)",
            text,
        )
        or re.search(
            r"(?:do not|don't|without|no need to).{0,24}"
            r"(?:execute|perform|call|play|capture|inspect|type|click|press|hotkey|"
            r"screenshot|read|close|quit|hide|minimi[sz]e|open|launch|start|visit|browse)",
            text.lower(),
        )
    )


def _is_desktop_permissions_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(
        r"(?:打开|启动|开启|拉起).{0,8}"
        r"(?:桌面权限|桌面执行权限|本地工具权限|需要的权限|缺少的权限|权限设置|权限页面)",
        text,
    ) or re.search(
        r"\b(?:open|launch|show)\s+(?:desktop|missing|required|permission|permissions)"
        r".{0,24}(?:settings|page|pane)\b",
        lowered,
    ):
        return False
    if re.search(
        r"(?:检查|诊断|查看|看看|确认).{0,12}"
        r"(?:桌面执行|本地工具|自动化|辅助功能|屏幕录制|权限).{0,12}"
        r"(?:权限|状态|问题)?",
        text,
    ):
        return True
    if re.search(
        r"(?:权限诊断|桌面权限|桌面执行权限|本地工具权限|自动化权限状态|辅助功能权限状态|"
        r"屏幕录制权限状态)",
        text,
    ):
        return True
    if re.search(
        r"(?:你|八千代|yachiyo)?\s*(?:需要|缺少|要)\s*(?:什么|哪些|哪个|啥).{0,12}权限",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:为什么|为何|为啥|怎么(?:回事)?).{0,24}"
        r"(?:不能|无法|没法|不会).{0,24}"
        r"(?:控制|操作|执行|打开|启动|播放|点击|输入|截图|截屏|"
        r"读取窗口|读取屏幕|读取界面|读屏幕|查看屏幕|观察屏幕|观察界面)",
        text,
    ):
        return True
    return bool(
        re.search(
            r"\b(?:check|diagnose|inspect|read)\s+(?:desktop|macos|mac|automation|"
            r"accessibility|screen recording)\s+permissions?\b",
            lowered,
        )
        or re.search(
            r"\bwhy\s+can(?:not|'t)\s+(?:you|yachiyo|the agent).{0,40}"
            r"(?:control|operate|open apps?|launch apps?|play music|click|type|"
            r"capture the screen|read windows?)",
            lowered,
        )
    )


def _browser_open_url(text: str) -> str:
    url_token = (
        r"(?:https?://[^\s。！？!?，,]+|www\.[^\s。！？!?，,]+|"
        r"localhost(?::\d+)?(?:/[^\s。！？!?，,]*)?|"
        r"(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/[^\s。！？!?，,]*)?|"
        r"[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?:/[^\s。！？!?，,]*)?)"
    )
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|访问|浏览|前往|去)\s*"
        rf"(?:网页|网站|网址|链接|本地|local)?\s*(?P<url>{url_token})",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?:网页|网站|网址|链接|本地|local)?\s*(?P<url>{url_token})"
        rf"\s*(?:打开|访问|浏览|前往|打开一下|访问一下|浏览一下)",
        rf"(?:open|visit|browse|go to)\s+(?P<url>{url_token})",
        rf"^(?P<url>{url_token})$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if _url_match_inside_local_path(text, match.start("url")):
            continue
        url = _normalize_url(match.group("url"))
        if url:
            return url
    return ""


def _browser_composite_open_url(text: str) -> str:
    browser_name = (
        r"(?:浏览器|chrome|google\s*chrome|谷歌(?:浏览器)?|safari|firefox|火狐(?:浏览器)?|"
        r"edge(?:浏览器)?|microsoft\s*edge|arc(?:浏览器)?|brave(?:浏览器)?|browser)"
    )
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?(?:打开|访问|浏览|前往|去)\s*(?P<target>[^。！？!?，,]+)",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在|用)?\s*{browser_name}\s*(?:里|中|内|上)?\s*"
        rf"(?:打开|访问|浏览|前往|去)\s*(?P<target>[^。！？!?，,]+)",
        rf"(?:open|launch|start)\s+{browser_name}\s+(?:and\s+)?"
        rf"(?:open|visit|browse|go to)\s+(?P<target>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        url = _browser_target_url(match.group("target"))
        if url:
            return url
    return ""


def _browser_address_bar_url(text: str) -> str:
    browser_name = (
        r"(?:浏览器|chrome|google\s*chrome|谷歌(?:浏览器)?|safari|firefox|火狐(?:浏览器)?|"
        r"edge(?:浏览器)?|microsoft\s*edge|arc(?:浏览器)?|brave(?:浏览器)?|browser)"
    )
    patterns = (
        r"(?:press|hit)\s+(?:command|cmd|⌘)\s*\+?\s*l\s*(?:,?\s*(?:and\s+then|then|and))?\s*"
        r"(?:type|enter|input)\s+(?P<target>[^!?]+?)\s*"
        r"(?:,?\s*(?:and\s+then|then|and))?\s*(?:press|hit)?\s*(?:enter|return)\s*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:按|敲|使用)\s*(?:command|cmd|⌘|Command|Cmd)\s*\+?\s*l\s*"
        r"(?:[，,；;。]?\s*(?:并|然后|后|之后|再)\s*)?"
        r"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)\s*"
        r"(?:[，,；;。]?\s*(?:并|然后|后|之后|再)?\s*(?:按)?(?:回车|enter|return))\s*$",
        r"(?:type|enter|input)\s+(?P<target>[^!?]+?)\s+"
        r"(?:in|into)\s+(?:the\s+)?(?:address\s+bar|url\s+bar|omnibox)"
        r"(?:\s+(?:(?:and\s+then|then|and)\s*)?(?:(?:press|hit)\s*)?(?:enter|return))?\s*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在)?(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?\s*"
        r"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        r"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        r"\s*(?:到|进|在)\s*(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?"
        r"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:open|launch|start)\s+{browser_name}\s+(?:and\s+)?"
        rf"(?:type|enter|input)\s+(?P<target>[^!?]+?)\s+"
        rf"(?:in|into)\s+(?:the\s+)?(?:address\s+bar|url\s+bar|omnibox)"
        rf"(?:\s+(?:and\s+)?(?:press|hit)\s+(?:enter|return))?\s*$",
        rf"(?:open|launch|start)\s+{browser_name}\s+(?:and\s+)?"
        rf"(?:type|enter|input)\s+(?P<target>[^!?]+?)"
        rf"(?:\s+(?:and\s+)?(?:press|hit)\s+(?:enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"[，,；;。]?\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?"
        rf"(?:在)?(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?\s*"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后|并)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"[，,；;。]?\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"\s*(?:到|进|在)\s*(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?"
        rf"(?:\s*(?:再|然后|并)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|启动|运行|拉起|开启)\s*{browser_name}\s*"
        rf"[，,；;。]?\s*"
        rf"(?:(?:并|然后|后|之后|再)\s*)?"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在|给|向)?\s*{browser_name}\s*(?:的|里|中|内|上)?\s*"
        rf"(?:地址栏|网址栏|url栏|omnibox)(?:里|中|内)?\s*"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))?\s*$",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在|给|向)\s*{browser_name}\s*(?:里|中|内|上)?\s*"
        rf"(?:输入|键入|填入)\s*(?P<target>[^。！？!?，,]+?)"
        rf"(?:\s*(?:再|然后)?\s*(?:按)?(?:回车|enter|return))\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        target = _strip_browser_address_bar_target(match.group("target"))
        url = _browser_address_bar_target_url(target)
        if url:
            return url
    return ""


def _strip_browser_address_bar_target(value: str) -> str:
    target = _strip_query(value)
    target = re.sub(
        r"\s+(?:(?:and\s+then|then|and)\s*)?(?:(?:press|hit)\s*)?(?:enter|return)\s*$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(
        r"\s*(?:再|然后|并)?\s*(?:按)?(?:回车|enter|return)\s*$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    target = re.sub(
        r"\s+(?:并|再|然后|and\s+then|then|and)$",
        "",
        target,
        flags=re.IGNORECASE,
    )
    return _strip_query(target)


def _browser_address_bar_target_url(target: str) -> str:
    clean_target = _strip_browser_address_bar_target(target)
    if not clean_target:
        return ""
    url = _browser_target_url(clean_target)
    if url:
        return url
    return f"https://www.google.com/search?q={quote_plus(clean_target)}"


def _browser_open_target_url(text: str) -> str:
    return (
        _browser_composite_open_url(text)
        or _browser_address_bar_url(text)
        or _browser_open_url(text)
        or _browser_search_url(text)
        or _browser_named_site_url(text)
    )


def _browser_open_url_and_extract_text_request(text: str) -> dict[str, str] | None:
    if not _is_browser_open_followup_extract_text_request(text):
        return None
    url = _browser_open_target_url(text) or _explicit_browser_url_in_text(text)
    if not url:
        return None
    return {"url": url}


def _browser_open_url_and_screenshot_request(text: str) -> dict[str, str] | None:
    if not _is_browser_open_followup_screenshot_request(text):
        return None
    url = _browser_open_target_url(text) or _explicit_browser_url_in_text(text)
    if not url:
        return None
    return {
        "url": url,
        "reason": "user asked to capture the browser page after opening a URL",
    }


def _is_browser_open_followup_extract_text_request(text: str) -> bool:
    explicit_url = _explicit_browser_url_in_text(text)
    if not (_browser_open_target_url(text) or explicit_url):
        return False
    lowered = text.lower()
    return bool(
        _is_browser_extract_text_request(text)
        or (
            explicit_url
            and (
                re.search(r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取|查看|看看|看一下|看下|总结|摘要|概括)", text)
                or re.search(r"\b(?:read|extract|get|summari[sz]e)\b", lowered)
            )
        )
        or re.search(
            r"(?:并且|并|然后|之后|后|再)\s*"
            r"(?:读取|读一下|读下|读一读|提取|抓取|获取|总结|摘要|概括)"
            r"(?:一下|下|它|网页|页面|网站|正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:打开|访问|浏览|前往|去).{0,80}"
            r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取|查看|看看|看一下|看下|总结|摘要|概括)"
            r"(?:一下|下|它|网页|页面|网站|正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"\b(?:and|then)\s+(?:read|extract|get|summari[sz]e)"
            r"(?:\s+(?:the\s+)?(?:page|webpage|website|site|text|content))?\b",
            lowered,
        )
    )


def _is_browser_open_followup_screenshot_request(text: str) -> bool:
    explicit_url = _explicit_browser_url_in_text(text)
    if not (_browser_open_target_url(text) or explicit_url):
        return False
    lowered = text.lower()
    return bool(
        _is_browser_screenshot_request(text)
        or (
            explicit_url
            and (
                re.search(r"(?:截图|截屏|屏幕截图|抓屏|截一下|截个图|截取)", text)
                or re.search(r"\b(?:screenshot|capture)\b", lowered)
            )
        )
        or re.search(
            r"(?:打开|访问|浏览|前往|去).{0,80}"
            r"(?:截图|截屏|屏幕截图|抓屏|截一下|截个图|截取)",
            text,
        )
        or re.search(
            r"(?:并且|并|然后|之后|后|再)\s*"
            r"(?:截图|截屏|屏幕截图|抓屏|截一下|截个图|截取)"
            r"(?:一下|下|搜索结果|结果|网页|页面|网站)?",
            text,
        )
        or re.search(
            r"\b(?:open|visit|browse|go to)\b.{0,80}"
            r"(?:take\s+a\s+screenshot|screenshot|capture)",
            lowered,
        )
        or re.search(
            r"\b(?:and|then)\s+(?:take\s+a\s+screenshot|screenshot|capture)"
            r"(?:\s+(?:the\s+)?(?:search\s+)?(?:results?|page|webpage|website|site))?\b",
            lowered,
        )
    )


def _explicit_browser_url_in_text(text: str) -> str:
    url_token = (
        r"(?:https?://[^\s。！？!?，,]+|www\.[^\s。！？!?，,]+|"
        r"localhost(?::\d+)?(?:/[^\s。！？!?，,]*)?|"
        r"(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/[^\s。！？!?，,]*)?|"
        r"[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}(?:/[^\s。！？!?，,]*)?)"
    )
    for match in re.finditer(rf"(?P<url>{url_token})", text, flags=re.IGNORECASE):
        if _url_match_inside_local_path(text, match.start("url")):
            continue
        url = _normalize_url(match.group("url"))
        if url:
            return url
    return ""


def _browser_target_url(value: str) -> str:
    target = _strip_browser_followup(_strip_query(value))
    target = re.sub(r"^(?:一下|下|这个|那个)\s*", "", target)
    return (
        _normalize_url(target)
        or _normalize_site_name(target)
        or _normalize_browser_site_name(target)
    )


def _url_match_inside_local_path(text: str, start: int) -> bool:
    if start <= 0:
        return False
    previous = text[start - 1]
    return previous in {"/", "~", "."}


def _normalize_url(value: str) -> str:
    candidate = str(value or "").strip(" 「」『』“”\"'`，,。.!?？！？ ")
    if not candidate:
        return ""
    if re.search(r"\s", candidate):
        return ""
    lowered = candidate.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
        return ""
    if lowered.startswith("www."):
        return f"https://{candidate}"
    if lowered.startswith("localhost"):
        return f"http://{candidate}"
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/[^\s]*)?", candidate):
        host = candidate.split("/", 1)[0].split(":", 1)[0]
        octets = [int(part) for part in host.split(".")]
        if all(0 <= part <= 255 for part in octets):
            return f"http://{candidate}"
        return ""
    domain_pattern = (
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
        r"(?::\d{1,5})?(?:/[^\s]*)?"
    )
    if re.fullmatch(domain_pattern, candidate):
        return f"https://{candidate}"
    return ""


def _browser_named_site_url(text: str) -> str:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)\s*)?"
        r"(?:打开|访问|浏览|前往|去|上)\s*(?P<site>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<site>[^。！？!?，,]+?)\s*(?:打开|访问|浏览|前往)"
        r"(?:一下|下)?(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"(?:open|visit|browse|go to)\s+(?P<site>[^.!?]+)"
        r"\s+(?:in|with|using)\s+(?:browser|chrome|google|safari)",
        r"(?:open|visit|browse|go to)\s+(?P<site>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_site = match.group("site")
        site = _normalize_site_name(raw_site)
        if not site and _has_browser_open_context(text):
            site = _normalize_browser_site_name(raw_site)
        if site:
            return site
    return ""


def _normalize_site_name(value: str) -> str:
    site = _strip_browser_followup(_strip_query(value))
    for candidate in (site, _strip_polite_suffix(site)):
        url = known_web_destination_url(candidate)
        if url:
            return url
    return ""


def _has_browser_open_context(text: str) -> bool:
    return bool(re.search(r"(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)", text, flags=re.IGNORECASE))


def _normalize_browser_site_name(value: str) -> str:
    site = _strip_polite_suffix(_strip_browser_followup(_strip_query(value)))
    return browser_only_web_destination_url(site)


def _explicit_browser_search_url(text: str) -> str:
    if _looks_like_explicit_text_input_target(text):
        return ""
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:打开|启动|运行|拉起|开启|开|用|在)\s*)?"
        r"(?P<engine>浏览器|chrome|google\s*chrome|google|谷歌|百度|baidu|safari)\s*"
        r"(?:里|中|上|内)?\s*"
        r"(?:搜索|搜一下|搜(?!索)|查一下|查查|查(?!看|找)|检索|谷歌一下|google\s+一下)\s*"
        r"(?P<query>[^。！？!?]+)",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:(?:open|launch|start|use)\s+)?"
        r"(?P<engine_en>chrome|google\s*chrome|browser|safari|firefox|edge|arc|brave|google|baidu)\s+"
        r"(?:and\s+)?(?:search|google|look\s+up)\s+(?:for\s+)?(?P<query_en>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        query = _strip_search_query(groups.get("query") or groups.get("query_en") or "")
        if not query:
            continue
        engine = str(groups.get("engine") or groups.get("engine_en") or "").strip().lower()
        if engine in {"百度", "baidu"}:
            return f"https://www.baidu.com/s?wd={quote_plus(query)}"
        return f"https://www.google.com/search?q={quote_plus(query)}"
    return ""


def _looks_like_search_request(text: str) -> bool:
    if _looks_like_explicit_text_input_target(text):
        return False
    lowered = text.lower()
    return bool(
        _explicit_browser_search_url(text)
        or re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)\s*)?"
            r"(?:里|中|上|内)?\s*"
            r"(?:搜索|搜一下|搜(?!索)|查一下|查查|查(?!看|找)|检索|百度一下|谷歌一下|google\s+一下)\s*",
            text,
        )
        or re.search(r"^(?:search|google|look up)\b\s+", lowered)
    )


def _browser_search_url(text: str) -> str:
    explicit_url = _explicit_browser_search_url(text)
    if explicit_url:
        return explicit_url
    app_followup = _app_open_or_focus_known_app_followup_match(text)
    if app_followup:
        if app_followup[2] not in _BROWSER_APP_NAMES:
            return ""
        if _desktop_safe_shortcut_action(app_followup[3]):
            return ""
        if _looks_like_known_app_followup(app_followup[3]) and not _looks_like_search_request(app_followup[3]):
            return ""
    app_prefix = _known_app_prefix_split(text)
    if app_prefix:
        if app_prefix[1] not in _BROWSER_APP_NAMES:
            return ""
        if _desktop_safe_shortcut_action(app_prefix[2]):
            return ""
        if _looks_like_known_app_followup(app_prefix[2]) and not _looks_like_search_request(app_prefix[2]):
            return ""
    if _app_direct_search_type_tool_requests(text) or _app_scoped_search_type_tool_requests(text):
        return ""
    if (
        _looks_like_click_command(text)
        or _desktop_click_ui_element(text)
        or _desktop_type_into_ui_element(text)
        or _browser_type_text_request(text) is not None
    ):
        return ""
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开)?\s*"
        r"(?P<engine>百度|baidu)\s*(?:搜索|搜一下|搜(?!索)|查一下|查查|检索)\s*(?P<query>[^。！？!?]+)",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<engine>百度|baidu)\s+(?P<query>[^。！？!?]+)",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<engine>百度|baidu)\s*一下\s*(?P<query>[^。！？!?]+)",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:search|google|look\s+up)\s+(?:in|on|with|using\s+)?"
        r"(?P<engine_en_app>chrome|google\s+chrome|browser|safari|firefox|edge|arc|brave|google|baidu)\s+"
        r"(?:for\s+)?(?P<query_en_app>[^.!?]+)",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:search|google|look\s+up)\s+(?:for\s+)?(?P<query_en_app_suffix>[^.!?]+?)\s+"
        r"(?:in|on|with|using)\s+"
        r"(?P<engine_en_app_suffix>chrome|google\s+chrome|browser|safari|firefox|edge|arc|brave|google|baidu)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:打开|启动|运行|拉起|开启|用|在)\s*(?P<engine>浏览器|chrome|google|谷歌|百度|baidu|safari)\s*)?"
        r"(?:里|中|上|内)?\s*"
        r"(?:[，,；;。]?\s*(?:并且|并|然后|之后|后|再)?\s*)?"
        r"(?:搜索|搜一下|搜(?!索)|查一下|查查|查(?!看|找)|检索|谷歌一下|google\s+一下)\s*(?P<query>[^。！？!?]+)",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:search|google|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        query = _strip_search_query(
            groups.get("query")
            or groups.get("query_en_app")
            or groups.get("query_en_app_suffix")
            or ""
        )
        if query:
            engine = str(
                groups.get("engine")
                or groups.get("engine_en_app")
                or groups.get("engine_en_app_suffix")
                or ""
            ).strip().lower()
            if engine in {"百度", "baidu"}:
                return f"https://www.baidu.com/s?wd={quote_plus(query)}"
            return f"https://www.google.com/search?q={quote_plus(query)}"
    return ""


def _browser_new_tab_search_url(text: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:用|在)?\s*(?P<engine>浏览器|chrome|google|谷歌|百度|baidu|safari)\s*)?"
        r"(?:打开|新建|开)\s*(?:一个|个)?\s*(?:新标签页?|新\s*tab|new\s+tab)\s*"
        r"(?:并|然后|再|后)?\s*(?:搜索|搜一下|搜(?!索)|查找|查一下|查查|检索)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:用|在)?\s*(?P<engine2>浏览器|chrome|google|谷歌|百度|baidu|safari)\s*)?"
        r"(?:新标签页?|新\s*tab|new\s+tab)\s*"
        r"(?:搜索|搜一下|搜(?!索)|查找|查一下|查查|检索)\s*(?P<query2>[^。！？!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        query = _strip_search_query(match.groupdict().get("query") or match.groupdict().get("query2") or "")
        if not query:
            continue
        engine = str(match.groupdict().get("engine") or match.groupdict().get("engine2") or "").strip().lower()
        if engine in {"百度", "baidu"}:
            return f"https://www.baidu.com/s?wd={quote_plus(query)}"
        return f"https://www.google.com/search?q={quote_plus(query)}"
    return ""


def _browser_search_then_click_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _browser_search_then_click(text)
    if not parsed:
        return []
    query, engine, index = parsed
    url = _browser_search_url_for_query(query, engine)
    return [
        _request("browser.open_url", {"url": url}),
        _request(
            "browser.click",
            {"selector": f"search-result={index}", "click_count": 1},
        ),
    ]


def _browser_site_search_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _browser_site_search(text)
    if not parsed:
        return []
    url, click_index = parsed
    requests = [_request("browser.open_url", {"url": url})]
    if click_index:
        requests.append(
            _request(
                "browser.click",
                {"selector": f"search-result={click_index}", "click_count": 1},
            )
        )
    return requests


def _browser_site_search(text: str) -> tuple[str, int] | None:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:打开|访问|浏览|前往|去|在|用)\s*)?"
        r"(?P<site>youtube|yt|youtube\s*music|bilibili|b站|哔哩哔哩)\s*"
        r"(?:里|中|上|内|里面)?\s*"
        r"(?:搜索|搜一下|搜|查找|查一下|查查|检索|找一下|找下|找)\s*"
        r"(?P<query>[^。！？!?，,]+?)\s*"
        r"(?P<tail>(?:(?:并且|并|然后|之后|随后|再|后)\s*)?"
        r"(?:播放|播(?!放)|放|打开|点击|点一下|点|进入|访问)\s*"
        r"(?:搜索结果|结果|链接)?(?:中|里|里的|的)?\s*"
        r"(?:第?一个|第一条|首个|第1个|第1条|1|它|这个|视频)?"
        r"(?:搜索结果|结果|链接|视频|条目)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*)?$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?(?:please\s+)?"
        r"(?:(?:open|visit|browse|go\s+to)\s+)?"
        r"(?P<site_en>youtube|yt|youtube\s*music|bilibili)\s+"
        r"(?:and\s+)?(?:search|find|look\s+up)\s+(?:for\s+)?"
        r"(?P<query_en>[^.!?]+?)\s*"
        r"(?P<tail_en>(?:(?:and|then)\s+)?"
        r"(?:play|start\s+playing|open|click|visit)\s*"
        r"(?:(?:the\s+)?(?:first|1st)\s+)?(?:result|link|video|it|this)?)?[.!?]*$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?(?:please\s+)?"
        r"(?:search|find|look\s+up)\s+"
        r"(?P<site_en_prefix>youtube|yt|youtube\s*music|bilibili)\s+"
        r"(?:for\s+)?(?P<query_en_prefix>[^.!?]+?)\s*"
        r"(?P<tail_en_prefix>(?:(?:and|then)\s+)?"
        r"(?:play|start\s+playing|open|click|visit)\s*"
        r"(?:(?:the\s+)?(?:first|1st)\s+)?(?:result|link|video|it|this)?)?[.!?]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, _clean_text(text), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        site = (
            groups.get("site")
            or groups.get("site_en")
            or groups.get("site_en_prefix")
            or ""
        )
        query = _strip_site_search_query(
            groups.get("query")
            or groups.get("query_en")
            or groups.get("query_en_prefix")
            or ""
        )
        url = _browser_site_search_url(site, query)
        if not url:
            continue
        tail = (
            groups.get("tail")
            or groups.get("tail_en")
            or groups.get("tail_en_prefix")
            or ""
        )
        return url, 1 if _site_search_tail_requests_first_result(tail) else 0
    return None


def _browser_site_search_url(site: str, query: str) -> str:
    clean_query = _strip_site_search_query(query)
    if not clean_query:
        return ""
    base_url = _normalize_site_name(site)
    if base_url == "https://www.youtube.com":
        return f"https://www.youtube.com/results?search_query={quote_plus(clean_query)}"
    if base_url == "https://music.youtube.com":
        return f"https://music.youtube.com/search?q={quote_plus(clean_query)}"
    if base_url == "https://www.bilibili.com":
        return f"https://search.bilibili.com/all?keyword={quote_plus(clean_query)}"
    return ""


def _strip_site_search_query(value: str) -> str:
    query = _strip_search_query(value)
    query = re.sub(
        r"\s*(?:并且|并|然后|之后|随后|再|后)\s*"
        r"(?:播放|播(?!放)|放|打开|点击|点一下|点|进入|访问)\s*"
        r"(?:搜索结果|结果|链接)?(?:中|里|里的|的)?\s*"
        r"(?:第?一个|第一条|首个|第1个|第1条|1|它|这个|视频)?"
        r"(?:搜索结果|结果|链接|视频|条目)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s+(?:and|then)\s+"
        r"(?:play|start\s+playing|open|click|visit)\s*"
        r"(?:(?:the\s+)?(?:first|1st)\s+)?(?:result|link|video|it|this)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    return _strip_query(query)


def _site_search_tail_requests_first_result(value: str) -> bool:
    tail = str(value or "").strip()
    return bool(
        re.search(r"(?:播放|播(?!放)|放|打开|点击|点一下|点|进入|访问)", tail)
        or re.search(r"\b(?:play|start\s+playing|open|click|visit)\b", tail, flags=re.IGNORECASE)
    )


def _browser_search_then_click(text: str) -> tuple[str, str, int] | None:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<engine_baidu>百度|baidu)\s*一下\s*"
        r"(?P<query_baidu>.+?)\s*"
        r"(?:然后|并且|并|之后|随后|再|后)\s*"
        r"(?:点击|点一下|点按|单击|点|打开|进入|访问)\s*"
        r"(?:搜索结果|结果|链接)?(?:中|里|里的|的)?\s*"
        r"(?P<rank_baidu>第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:打开|启动|运行|拉起|开启)\s*(?:浏览器|chrome|google\s*chrome|谷歌|谷歌浏览器|safari)\s*)?"
        r"(?:(?:用|在)\s*(?P<engine>浏览器|chrome|google|谷歌|百度|baidu|safari)\s*)?"
        r"(?:里|中|上|内)?\s*"
        r"(?:搜索|搜一下|搜(?!索)|查一下|查查|查(?!看|找)|检索|谷歌一下|google\s+一下)\s*"
        r"(?P<query>.+?)\s*"
        r"(?:然后|并且|并|之后|随后|再|后)\s*"
        r"(?:点击|点一下|点按|单击|点|打开|进入|访问)\s*"
        r"(?:搜索结果|结果|链接)?(?:中|里|里的|的)?\s*"
        r"(?P<rank>第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)?$",
        r"^(?:please\s+)?(?:(?:open|launch|start)\s+(?:chrome|browser|safari)\s+(?:and\s+)?)?"
        r"(?:(?P<engine_en>google|search|look\s+up)\s+)"
        r"(?P<query_en>.+?)\s+(?:and|then)\s+"
        r"(?:open|click|visit)\s+(?:the\s+)?(?P<rank_en>first|1st)\s+(?:result|link)$",
    )
    for pattern in patterns:
        match = re.search(pattern, _clean_text(text), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        query = _strip_search_query(
            groups.get("query") or groups.get("query_baidu") or groups.get("query_en") or ""
        )
        if not query:
            continue
        engine = str(
            groups.get("engine") or groups.get("engine_baidu") or groups.get("engine_en") or ""
        ).strip().lower()
        rank = groups.get("rank") or groups.get("rank_baidu") or groups.get("rank_en") or ""
        index = _browser_search_result_rank_index(rank)
        if index:
            return query, engine, index
    return None


def _browser_search_url_for_query(query: str, engine: str) -> str:
    if engine in {"百度", "baidu"}:
        return f"https://www.baidu.com/s?wd={quote_plus(query)}"
    return f"https://www.google.com/search?q={quote_plus(query)}"


def _browser_search_result_rank_index(value: str) -> int:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    if compact in {"第一个", "第一条", "首个", "第1个", "第1条", "1", "first", "1st"}:
        return 1
    return 0


def _looks_like_click_command(text: str) -> bool:
    return bool(
        re.match(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:(?:双击)|点击|点一下|点按|单击|点|按一下|按)\s*\S+",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(r"^(?:double\s+click|click|press|tap)\s+\S+", text, flags=re.IGNORECASE)
    )


def _browser_click_request(text: str) -> dict[str, Any] | None:
    rank_match = re.search(
        r"(?:点击|点一下|点按|单击|打开|进入|访问)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?P<rank>第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)$",
        text,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:click|open|visit|press)\s+(?:the\s+)?"
        r"(?P<rank_en>first|1st|second|2nd|third|3rd)\s+"
        r"(?:search\s+)?(?:result|link)\b",
        text,
        flags=re.IGNORECASE,
    )
    if rank_match:
        rank = rank_match.groupdict().get("rank") or rank_match.groupdict().get("rank_en") or ""
        index = _browser_search_result_rank_index(rank)
        if index:
            return {"selector": f"search-result={index}", "click_count": 1}
    if not _has_browser_page_context(text):
        return None
    point = _browser_click_point(text)
    if point:
        return {
            "selector": f"point={point['x']},{point['y']}",
            "fallback_x": point["x"],
            "fallback_y": point["y"],
            "click_count": point["click_count"],
        }
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:点击|点一下|点按|单击|点)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?P<label>[^。！？!?，,]+?)\s*(?:按钮|链接|元素)?$",
        r"\b(?:click|press)\s+(?:the\s+)?(?P<label>[^.!?]+?)"
        r"(?:\s+(?:button|link|element))?"
        r"(?:\s+(?:on|in)\s+(?:the\s+)?(?:current\s+)?(?:page|browser))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        label = _strip_browser_element_label(match.group("label"))
        if not label or _looks_like_click_coordinate_label(label):
            continue
        return {"selector": _browser_selector_from_label(label), "click_count": 1}
    return None


def _browser_click_point(text: str) -> dict[str, Any] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|click)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)(?:上|里|中|内|的|上的)?\s*"
        r"(?:坐标|位置|coordinate|point)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double2>双击|double\s+click)|点击|点一下|点按|单击|click)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?:坐标|位置|coordinate|point)\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        return {
            "x": _number_value(match.group("x")),
            "y": _number_value(match.group("y")),
            "click_count": 2 if groups.get("double") or groups.get("double2") else 1,
        }
    return None


def _browser_type_text_request(text: str) -> dict[str, Any] | None:
    if not _has_browser_page_context(text):
        return None
    point = _browser_type_text_point(text)
    if point:
        return {
            "selector": f"point={point['x']},{point['y']}",
            "text": point["text"],
            "fallback_x": point["x"],
            "fallback_y": point["y"],
        }
    patterns = (
        r"\b(?:type|enter|fill)\s+(?P<text>[^.!?]+?)\s+"
        r"(?:into|in)\s+(?:the\s+)?(?:current|this)?\s*"
        r"(?:web\s*page|webpage|page|browser)\s+(?P<target>[^.!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前)?(?:网页|页面|浏览器|当前页)"
        r"(?:上|里|中|内)?(?:的)?\s*(?P<target>[^。！？!?，,]*?)"
        r"(?:输入|填写|键入|打入|填入)\s*(?P<text>[^。！？!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:填写|填入|输入)\s*(?:当前)?(?:网页|页面|浏览器|当前页)?(?:的)?"
        r"(?P<target>[^。！？!?，,]+?)\s*(?:为|成|:|：)\s*(?P<text>[^。！？!?]+)$",
        r"\b(?:type|enter|fill)\s+(?P<text>[^.!?]+?)\s+"
        r"(?:into|in)\s+(?P<target>[^.!?]+?)\s+"
        r"(?:on|in)\s+(?:the\s+)?(?:current\s+)?(?:page|browser)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = _strip_typed_text(match.group("text"))
        if not typed_text:
            continue
        target = _strip_browser_element_label(match.group("target"))
        return {
            "selector": _browser_input_selector_from_target(target),
            "text": typed_text,
        }
    return None


def _browser_type_text_point(text: str) -> dict[str, Any] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前)?(?:网页|页面|浏览器|当前页)"
        r"(?:上|里|中|内|的|上的)?\s*(?:坐标|位置|coordinate|point)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)\s*"
        r"(?:输入|填写|键入|打入|填入|type|enter|fill)\s*(?P<text>[^。！？!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:输入|填写|键入|打入|填入|type|enter|fill)\s*(?P<text>[^。！？!?]+?)\s*"
        r"(?:到|在|进|into|in)\s*(?:当前)?(?:网页|页面|浏览器|当前页)?"
        r"(?:上|里|中|内|的|上的)?\s*(?:坐标|位置|coordinate|point)\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = _strip_typed_text(match.group("text"))
        if not typed_text:
            continue
        return {
            "x": _number_value(match.group("x")),
            "y": _number_value(match.group("y")),
            "text": typed_text,
        }
    return None


def _has_browser_page_context(text: str) -> bool:
    return bool(
        re.search(r"(?:网页|页面|浏览器|当前页)", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:browser|page|webpage|web\s+page)\b", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:search\s+)?(?:result|link)s?\b", text, flags=re.IGNORECASE)
    )


def _strip_browser_element_label(value: str) -> str:
    label = _strip_query(value)
    label = re.sub(r"^(?:当前)?(?:网页|页面|浏览器|当前页)(?:上的|上|里|中|内|的)?\s*", "", label)
    label = re.sub(r"^(?:的|上的|上|里|中|内)\s*", "", label)
    label = re.sub(r"\s*(?:按钮|链接|元素|button|link|element|field|input|box)$", "", label, flags=re.IGNORECASE)
    return _strip_query(label)


def _looks_like_click_coordinate_label(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?\s*(?:,|，|\s)\s*\d+(?:\.\d+)?", str(value or "").strip()))


def _browser_selector_from_label(label: str) -> str:
    clean = str(label or "").strip()
    if _looks_like_css_selector(clean):
        return clean
    return f"text={clean}"


def _browser_input_selector_from_target(target: str) -> str:
    clean = str(target or "").strip()
    if _looks_like_css_selector(clean):
        return clean
    lowered = clean.lower()
    if re.search(r"(?:搜索|查找|search|query|q)", lowered):
        return _BROWSER_SEARCH_INPUT_SELECTOR
    if re.search(r"(?:密码|password)", lowered):
        return 'input[type="password"]'
    if re.search(r"(?:邮箱|邮件|email|e-mail)", lowered):
        return 'input[type="email"], input[name*="email" i], input[autocomplete="email"]'
    if re.search(r"(?:用户名|账号|账户|user|username|login)", lowered):
        return 'input[name*="user" i], input[autocomplete="username"], input[type="text"]'
    return _BROWSER_TEXT_INPUT_SELECTOR


def _looks_like_css_selector(value: str) -> bool:
    stripped = str(value or "").strip()
    return bool(
        stripped.startswith(("#", ".", "["))
        or re.match(r"^(?:button|a|input|textarea|select|form|div|span|\\*)\\b", stripped, flags=re.IGNORECASE)
    )


def _strip_search_query(value: str) -> str:
    query = _strip_query(value)
    query = re.sub(r"^(?:一下|这个|那个)\s*", "", query)
    query = re.sub(r"^下(?:\s+|$)", "", query)
    query = re.sub(
        r"\s*(?:并且|并|然后|之后|后|再|接着)\s*"
        r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取|查看|看看|看一下|看下|"
        r"总结|摘要|概括|截图|截屏|屏幕截图|抓屏|截一下|截个图)"
        r"(?:一下|下|搜索结果|结果|网页|页面|网站|正文|文字|文本|内容)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s+(?:and\s+then|then|and)\s+"
        r"(?:read|extract|get|summari[sz]e|take\s+a\s+screenshot|screenshot|capture)"
        r"(?:\s+(?:the\s+)?(?:search\s+)?(?:results?|page|webpage|website|site|text|content))?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s*(?:用|在)\s*(?:浏览器|chrome|google|谷歌|百度|safari)(?:里|中|上|内)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s*(?:in|on|with|using)\s+(?:browser|chrome|google\s+chrome|google|safari)$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    return _strip_query(query)


def _browser_current_page_link_copy_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _is_browser_current_page_link_copy_request(text):
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "copy_current_page_link"}),
    ]


def _is_browser_current_page_link_copy_request(text: str) -> bool:
    clean = str(text or "").strip()
    lowered = clean.lower()
    return bool(
        re.search(
            r"(?:复制|拷贝).{0,8}(?:当前|现在|前台|这个|这页|本页).{0,8}"
            r"(?:网页|网站|页面|页|浏览器|标签页)?(?:链接|网址|url|URL|地址)",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:复制|拷贝).{0,8}(?:链接|网址|url|URL|地址).{0,8}"
            r"(?:当前|现在|前台|这个|这页|本页).{0,8}(?:网页|网站|页面|页|浏览器|标签页)?",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:把|将)?\s*(?:当前|现在|前台|这个|这页|本页).{0,8}"
            r"(?:网页|网站|页面|页|浏览器|标签页)?(?:链接|网址|url|URL|地址)\s*"
            r"(?:复制|拷贝)(?:一下|下)?(?:给我)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:把|将)?\s*(?:当前|现在|前台|这个|这页|本页).{0,8}"
            r"(?:网页|网站|页面|页|浏览器|标签页)?(?:链接|网址|url|URL|地址).{0,12}"
            r"(?:复制|拷贝|放(?:到|进|入)?|写入|保存(?:到|进)?).{0,8}"
            r"(?:剪贴板|粘贴板|clipboard)(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bcopy\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)\s+)?(?:url|link|address)\b",
            lowered,
        )
        or re.search(
            r"\bcopy\s+(?:the\s+)?(?:url|link|address)\s+"
            r"(?:of|from|for)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:browser\s+)?(?:page|tab)\b",
            lowered,
        )
    )


def _is_browser_current_page_request(text: str) -> bool:
    lowered = text.lower()
    if _looks_like_browser_tab_audio_request(text):
        return False
    if _is_browser_current_page_link_copy_request(text):
        return False
    if re.search(r"(?:刷新|重新加载|reload|refresh)", text, flags=re.IGNORECASE):
        return False
    if re.search(r"(?:总结|摘要|概括|summari[sz]e|summary)", text, flags=re.IGNORECASE):
        return False
    if re.search(
        r"(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作|"
        r"buttons?|controls?|ui elements?|text fields?|inputs?)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    if _is_browser_current_page_link_read_request(text):
        return True
    return bool(
        re.search(
            r"(?:当前|现在|前台).{0,8}(?:网页|网站|页面|页|浏览器|标签页).{0,8}"
            r"(?:是什么|是啥|哪个|地址|标题|url)?",
            text,
        )
        or re.search(
            r"(?:这是|这|当前打开的是).{0,4}(?:哪个|什么).{0,4}(?:网页|网站|页面|页|标签页)",
            text,
        )
        or re.search(
            r"(?:看一下|看看|看下|查看).{0,8}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)",
            text,
        )
        or "current page" in lowered
        or "current browser tab" in lowered
        or "active browser tab" in lowered
        or re.search(
            r"\b(?:what|which)\s+(?:page|site|website|tab)\s+(?:am\s+i|are\s+we)\s+on\b",
            lowered,
        )
        or re.search(
            r"\b(?:what|which)\s+(?:page|site|website|tab)\s+is\s+(?:open|active|current)\b",
            lowered,
        )
        or re.search(r"\bwhat(?:'s|\s+is)\s+(?:the\s+)?current\s+(?:url|page|tab)\b", lowered)
    )


def _is_browser_extract_text_request(text: str) -> bool:
    lowered = text.lower()
    if _is_browser_current_page_link_read_request(text):
        return False
    return bool(
        re.search(
            r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取).{0,10}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页).{0,10}(?:正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:看看|看一下|看下|查看).{0,10}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,10}(?:正文|文字|文本|内容)",
            text,
        )
        or re.search(
            r"(?:把|将)?\s*(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,8}(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取)"
            r"(?:正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:总结|摘要|概括).{0,10}"
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,10}(?:正文|文字|文本|内容)?",
            text,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|该)?(?:网页|网站|页面|页|浏览器|标签页)"
            r".{0,10}(?:总结|摘要|概括|讲了什么|说了什么|内容是什么)",
            text,
        )
        or "extract text from the current page" in lowered
        or "extract text from this page" in lowered
        or re.search(
            r"\bextract\s+(?:the\s+)?(?:current\s+|this\s+)?"
            r"(?:page|webpage|web\s+page)(?:\s+(?:text|content|body))?\b",
            lowered,
        )
        or re.search(
            r"\bextract\s+(?:the\s+)?(?:page|webpage|web\s+page)\s+"
            r"(?:text|content|body)\b",
            lowered,
        )
        or "read the current page" in lowered
        or "read current page" in lowered
        or "read current webpage" in lowered
        or "read the current webpage" in lowered
        or "read current web page" in lowered
        or "read the current web page" in lowered
        or "read this page" in lowered
        or "read the page" in lowered
        or "summarize current page" in lowered
        or "summarize the current page" in lowered
        or "summarize current webpage" in lowered
        or "summarize the current webpage" in lowered
        or "summarise current page" in lowered
        or "summarise the current page" in lowered
        or "summarise current webpage" in lowered
        or "summarise the current webpage" in lowered
        or "summarize this page" in lowered
        or "summarise this page" in lowered
        or "what is this page about" in lowered
        or "what's this page about" in lowered
    )


def _is_browser_current_page_link_read_request(text: str) -> bool:
    clean = str(text or "").strip()
    lowered = clean.lower()
    if _is_browser_current_page_link_copy_request(clean):
        return False
    return bool(
        re.search(
            r"(?:读取|读一下|读下|查看|看一下|看看|获取|告诉我|给我).{0,8}"
            r"(?:当前|现在|前台|这个|这页|本页).{0,8}"
            r"(?:网页|网站|页面|页|浏览器|标签页)?(?:链接|网址|url|URL|地址)",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|前台|这个|这页|本页).{0,8}"
            r"(?:网页|网站|页面|页|浏览器|标签页)?(?:链接|网址|url|URL|地址).{0,8}"
            r"(?:是什么|是啥|多少|哪个|告诉我|给我|查看|看一下|看看|读取|读一下|读下|获取)?",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:what(?:'s|\s+is)|read|show|get|tell\s+me)\s+"
            r"(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)\s+)?(?:url|link|address)\b",
            lowered,
        )
        or re.search(
            r"\b(?:what(?:'s|\s+is)|read|show|get|tell\s+me)\s+"
            r"(?:the\s+)?(?:url|link|address)\s+"
            r"(?:of|from|for)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:browser\s+)?(?:page|tab)\b",
            lowered,
        )
    )


def _is_browser_summary_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(r"(?:总结|摘要|概括|讲了什么|说了什么|内容是什么)", text)
        or re.search(r"\bsummari[sz]e\b", lowered)
        or "what is this page about" in lowered
        or "what's this page about" in lowered
    )


def _is_browser_screenshot_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|前台)?(?:网页|网站|页面|页|浏览器).{0,8}"
            r"(?:截图|截屏|屏幕截图|抓屏|截一下|截个图)",
            text,
        )
        or re.search(
            r"(?:截取|截图|截屏|截一下|截个图|截|抓屏).{0,8}(?:当前|现在|前台)?(?:网页|网站|页面|页|浏览器)",
            text,
        )
        or "browser screenshot" in lowered
        or "page screenshot" in lowered
        or "screenshot the current page" in lowered
        or "screenshot current webpage" in lowered
        or "screenshot the current webpage" in lowered
        or "screenshot this page" in lowered
        or "screenshot the page" in lowered
        or re.search(r"\btake\s+(?:a\s+)?screenshot\s+of\s+(?:this|the|current)\s+page\b", lowered)
    )


def _system_volume_request(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    if _looks_like_browser_tab_audio_request(text):
        return None
    if re.search(
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*"
        r"(?:调|调到|调至|调成|设到|设成|设置到|到)?\s*(?:一半|半)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        text,
    ):
        return {"action": "set", "level": 50}
    if re.search(
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*"
        r"(?:调满|调到最大|调至最大|调成最大|开到最大|拉满|最大|满格)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        text,
    ):
        return {"action": "set", "level": 100}
    level_patterns = (
        r"(?:设置|设定)(?:系统)?(?:音量|声音)\s*(?:为|到|成)?\s*"
        r"(?P<level>\d{1,3})(?:\s*%|百分之)?",
        r"(?:调到|调至|调成|设为|设到|设成|设置为|设置到)\s*(?P<level>\d{1,3})(?:\s*%|百分之)?\s*"
        r"(?:系统)?(?:音量|声音)",
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*(?:调到|调至|设为|设置为|设置到)\s*"
        r"(?P<level>\d{1,3})(?:\s*%|百分之)?",
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*(?:调到|调至|设为|设置为|设置到)\s*"
        r"百分之\s*(?P<level>\d{1,3})",
        r"(?:系统)?(?:音量|声音)\s*(?:设成|设到|调成)\s*(?P<level>\d{1,3})(?:\s*%|百分之)?",
        r"(?:音量|声音)\s*(?P<level>\d{1,3})\s*%",
        r"\b(?:volume|sound)\s+(?P<level>\d{1,3})\s*%?\b",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:把|将)?(?:系统)?(?:音量|声音)\s*(?:到|调到|调至|设为|设置到)?\s*"
        r"(?P<level>\d{1,3})(?:\s*%|百分之)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        r"\b(?:set|turn)\s+(?:the\s+)?(?:system\s+)?(?:volume|sound)\s+(?:to\s+)?"
        r"(?P<level>\d{1,3})\s*%?\b",
    )
    for pattern in level_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        level = _percentage_value(match.group("level"))
        if level is not None:
            return {"action": "set", "level": level}
    if re.search(r"(?:取消静音|解除静音|取消(?:系统)?静音|恢复声音)", text) or re.search(
        r"(?:把|将)?(?:系统)?(?:声音|音量)\s*(?:打开|开一下|开下|开起来)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        text,
    ) or re.search(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|开启)"
        r"(?:系统)?(?:声音|音量)(?!设置)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        text,
    ) or re.search(
        r"\bunmute(?:\s+(?:system\s+)?volume)?\b|\bturn\s+(?:the\s+)?sound\s+on\b",
        lowered,
    ):
        return {"action": "unmute"}
    if re.search(
        r"(?:静音|设为静音|开启静音|关闭声音|关掉声音|把声音关掉|把音量关掉|"
        r"把声音关了|把音量关了|声音关掉|音量关掉|声音关了|音量关了|别出声)",
        text,
    ) or re.search(
        r"\bmute(?:\s+(?:system\s+)?volume)?\b|\bturn\s+(?:the\s+)?sound\s+off\b",
        lowered,
    ):
        return {"action": "mute"}
    if re.search(
        r"(?:调大|调高|加大|提高|增大|升高|放大).{0,4}(?:音量|声音)|"
        r"(?:音量|声音).{0,4}(?:大一点|大点|高一点|高点|加一点|加点|调大|调高|提高|放大)|"
        r"(?:大声一点|大声点|声音大点|声音大一点|音量大点|音量大一点|大点声|大一点声)",
        text,
    ) or re.search(
        r"\b(?:turn|raise|increase)\s+(?:up\s+)?(?:the\s+)?(?:system\s+)?volume\b|"
        r"\bvolume\s+up\b|"
        r"\bsound\s+up\b|"
        r"\b(?:louder|make\s+it\s+louder|turn\s+it\s+up|turn\s+(?:the\s+)?sound\s+up)\b",
        lowered,
    ):
        return {"action": "up"}
    if re.search(
        r"(?:调小|调低|降低|减小|小声|缩小).{0,4}(?:音量|声音)|"
        r"(?:音量|声音).{0,4}(?:小一点|小点|低一点|低点|减一点|减点|调小|调低|降低|缩小)|"
        r"(?:小声一点|小声点|声音小点|声音小一点|音量小点|音量小一点|小点声|小一点声)",
        text,
    ) or re.search(
        r"\b(?:turn|lower|decrease)\s+(?:down\s+)?(?:the\s+)?(?:system\s+)?volume\b|"
        r"\bvolume\s+down\b|"
        r"\bsound\s+down\b|"
        r"\b(?:quieter|make\s+it\s+quieter|turn\s+it\s+down|turn\s+(?:the\s+)?sound\s+down)\b",
        lowered,
    ):
        return {"action": "down"}
    if (
        re.search(
            r"(?:查看|看看|看下|读取|显示|告诉我).{0,8}"
            r"(?:当前|现在|系统)?(?:音量|声音)(?!设置)(?:大小|级别|状态)?",
            text,
        )
        or re.search(r"(?:当前|现在|系统)?(?:音量|声音).{0,6}(?:多少|是多少|状态)", text)
        or re.search(
            r"\b(?:check|show|read|tell\s+me)\s+(?:the\s+)?(?:current\s+)?"
            r"(?:system\s+)?(?:volume|sound)(?:\s+(?:level|status))?\b",
            lowered,
        )
        or re.search(
            r"\b(?:current\s+)?(?:system\s+)?volume(?:\s+level|\s+status)?\??$",
            lowered,
        )
    ):
        return {"action": "status"}
    return None


def _looks_like_browser_tab_audio_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:标签页|页签|浏览器标签|当前标签|这个标签).{0,8}"
            r"(?:静音|取消静音|解除静音|声音|音量)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:静音|取消静音|解除静音|关闭声音|打开声音).{0,8}"
            r"(?:标签页|页签|浏览器标签|当前标签|这个标签)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:mute|unmute)\s+(?:the\s+)?(?:current\s+|this\s+)?tab\b",
            lowered,
        )
        or re.search(
            r"\b(?:current\s+|this\s+)?tab\s+(?:audio|sound|volume)\b",
            lowered,
        )
    )


def _system_brightness_request(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    count = r"(?P<count>\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|seven|eight|nine|ten)"
    suffix = r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$"
    exact_or_settings = r"(?:设置|设为|设成|调到|调至|百分之|\d+\s*%|亮度设置|显示器设置)"
    if re.search(exact_or_settings, text, flags=re.IGNORECASE):
        return None
    up_patterns = (
        rf"^(?:再|稍微|略微)?(?:调亮(?:一点点|一点|点|一些|些)?|亮一点点|亮一点|亮点|亮一些|亮些)(?:\s*{count}\s*(?:次|下|格))?",
        rf"(?:亮度|屏幕|显示器).{{0,6}}(?:调高|提高|调亮|变亮|大一点|大点|亮一点|亮点|亮一些|亮些|亮一点点)(?:\s*{count}\s*(?:次|下|格))?",
        rf"(?:调高|提高|调亮|增大|加大).{{0,6}}(?:亮度|屏幕|显示器)(?:\s*{count}\s*(?:次|下|格))?",
        rf"(?:屏幕|显示器)?(?:太暗|有点暗|太黑|看不清)",
        rf"\b(?:brightness\s+up|increase\s+(?:the\s+)?brightness|brighten\s+(?:the\s+)?(?:screen|display)|make\s+(?:the\s+)?(?:screen|display)\s+brighter)\b",
    )
    down_patterns = (
        rf"^(?:再|稍微|略微)?(?:调暗(?:一点点|一点|点|一些|些)?|暗一点点|暗一点|暗点|暗一些|暗些)(?:\s*{count}\s*(?:次|下|格))?",
        rf"(?:亮度|屏幕|显示器).{{0,6}}(?:调低|降低|调暗|变暗|小一点|小点|暗一点|暗点|暗一些|暗些|暗一点点)(?:\s*{count}\s*(?:次|下|格))?",
        rf"(?:调低|降低|调暗|减小).{{0,6}}(?:亮度|屏幕|显示器)(?:\s*{count}\s*(?:次|下|格))?",
        rf"(?:屏幕|显示器)?(?:太亮|有点亮|刺眼|晃眼)",
        rf"\b(?:brightness\s+down|decrease\s+(?:the\s+)?brightness|dim\s+(?:the\s+)?(?:screen|display)|make\s+(?:the\s+)?(?:screen|display)\s+dimmer)\b",
    )
    for pattern in up_patterns:
        match = re.search(pattern + suffix, text, flags=re.IGNORECASE) or re.search(
            pattern,
            lowered,
            flags=re.IGNORECASE,
        )
        if match:
            return {"action": "up", "step": _brightness_step_count(match)}
    for pattern in down_patterns:
        match = re.search(pattern + suffix, text, flags=re.IGNORECASE) or re.search(
            pattern,
            lowered,
            flags=re.IGNORECASE,
        )
        if match:
            return {"action": "down", "step": _brightness_step_count(match)}
    return None


def _brightness_step_count(match: re.Match[str]) -> int:
    groups = match.groupdict() if hasattr(match, "groupdict") else {}
    raw_count = str(groups.get("count") or "").strip().lower()
    if raw_count:
        if raw_count.isdigit():
            count = int(raw_count)
        else:
            count = _SCROLL_PAGE_COUNTS.get(raw_count, 0)
        if 1 <= count <= 10:
            return count
    value = str(match.group(0) or "")
    if re.search(r"(?:一点点|稍微|slightly|a little)", value, flags=re.IGNORECASE):
        return 1
    if re.search(r"(?:一些|多一点|多点|很多|大幅|明显|much|lot)", value, flags=re.IGNORECASE):
        return 4
    return 2


def _system_display_sleep_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(
        r"(?:电脑|主机|mac|macbook|机器|整机).{0,6}(?:睡眠|休眠|关机|重启)|"
        r"\b(?:sleep|shut\s*down|restart|reboot)\s+(?:my\s+|the\s+)?(?:mac|macbook|computer|machine)\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        return False
    suffix = r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$"
    chinese_patterns = (
        r"(?:把|将|让)?(?:屏幕|显示器|显示屏)\s*(?:睡眠|休眠|息屏|黑屏|关闭|关掉|关了|熄灭|灭掉)",
        r"(?:关闭|关掉|关了|睡眠|休眠|息屏|熄灭|灭掉)(?:一下|下)?(?:屏幕|显示器|显示屏)",
        r"(?:屏幕|显示器|显示屏)(?:关一下|关下|睡一下|休眠一下|息屏一下|黑一下)",
        r"(?:息屏|熄屏|黑屏)(?:一下|下)?",
    )
    english_patterns = (
        r"\b(?:turn|switch)\s+off\s+(?:the\s+)?(?:display|screen|monitor)\b",
        r"\b(?:sleep|blank)\s+(?:the\s+)?(?:display|screen|monitor)\b",
        r"\bput\s+(?:the\s+)?(?:display|screen|monitor)\s+to\s+sleep\b",
        r"\bdisplay\s+sleep\b|\bscreen\s+sleep\b",
    )
    return any(
        re.search(pattern + suffix, text, flags=re.IGNORECASE)
        or re.search(pattern, lowered, flags=re.IGNORECASE)
        for pattern in (*chinese_patterns, *english_patterns)
    )


def _system_screen_saver_start_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(
        r"(?:设置|设定|配置|偏好|面板|页面|settings?|preferences?|pane|page)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return False
    suffix = r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$"
    chinese_patterns = (
        r"(?:启动|打开|开启|运行|显示|进入)(?:一下|下)?(?:屏幕保护程序|屏幕保护|屏保)",
        r"(?:让|把)?(?:屏幕保护程序|屏幕保护|屏保)(?:启动|打开|开启|运行|显示|出来|跑起来)",
    )
    english_patterns = (
        r"\b(?:start|open|launch|turn\s+on|show|run)\s+(?:the\s+)?(?:screen\s*saver|screensaver)\b",
        r"\b(?:screen\s*saver|screensaver)\s+(?:start|open|launch|turn\s+on|show|run)\b",
    )
    return any(
        re.search(pattern + suffix, text, flags=re.IGNORECASE)
        or re.search(pattern, lowered, flags=re.IGNORECASE)
        for pattern in (*chinese_patterns, *english_patterns)
    )


def _clipboard_write_text(text: str) -> str:
    if _clipboard_to_note_request(text):
        return ""
    patterns = (
        r"(?:把|将)?\s*(?:这段话|这段文字|这段文本|以下内容|下面内容|内容)?\s*"
        r"(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)\s*[:：]\s*(?P<text>.+)$",
        r"(?:复制|拷贝)(?:一下|下)?\s*(?:以下|下面)?(?:内容|这段话|这段文字|这段文本)?\s*[:：]\s*"
        r"(?P<text>.+)$",
        r"(?:写入|放入|放进|保存到)\s*(?:系统)?(?:剪贴板|粘贴板)\s+(?P<text>.+)$",
        r"(?:把|将)\s*(?P<text>.+?)\s*(?:复制|拷贝|写入|放到|放进|保存到)(?:一下|下)?\s*(?:到|进|至)?\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)",
        r"(?:复制|拷贝|写入)(?:一下|下)?\s*(?P<text>.+?)\s*(?:到|进|至)\s*"
        r"(?:系统)?(?:剪贴板|粘贴板)",
        r"(?:系统)?(?:剪贴板|粘贴板)\s*(?:写入|放入|放进|保存|保存为)\s*(?P<text>.+)$",
        r"(?:设置|设定|set)\s*(?:系统)?(?:剪贴板|粘贴板|clipboard)\s*(?:为|成|to)\s*(?P<text>.+)$",
        r"(?:复制|拷贝|写入)(?:到|进|至)?\s*(?:系统)?(?:剪贴板|粘贴板)\s*[:：]\s*"
        r"(?P<text>.+)$",
        r"\b(?:copy|write|put)\s+(?P<text>.+?)\s+(?:to|into)\s+(?:the\s+)?"
        r"(?:system\s+)?clipboard\b",
        r"\b(?:copy|write)\s+(?:to\s+)?(?:the\s+)?(?:system\s+)?clipboard\s*[:：]\s*"
        r"(?P<text>.+)$",
        r"(?:把|将)\s*(?P<text>[^。！？!?，,\n]+?)\s*(?:复制|拷贝)(?:一下|下)?\s*(?:吧|给我)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        cleaned = _normalize_clipboard_text(match.group("text"))
        if cleaned:
            return cleaned
    return ""


def _clipboard_to_note_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _clipboard_to_note_request(text):
        return []
    return [
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Notes", "action": "new_note"},
        ),
        _request("desktop.safe_shortcut", {"action": "paste"}),
    ]


def _clipboard_to_note_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    clipboard_source = r"(?:当前|系统|这个|这份|我的)?(?:剪贴板|粘贴板)(?:内容)?"
    note_target = r"(?:备忘录|笔记|note)"
    return bool(
        re.search(
            rf"^(?:把|将)?\s*{clipboard_source}\s*"
            rf"(?:写进|写入|记到|记入|保存到|存到|放到|放进|加到|加入|添加到|新建成|创建成)\s*"
            rf"{note_target}(?:里|中|上)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*{clipboard_source}\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*{note_target}$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*{note_target}(?:里|中|上)?\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*{clipboard_source}$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:paste|put|save|write|add)\s+(?:the\s+)?clipboard(?:\s+contents?)?\s+"
            r"(?:into|to|in)\s+(?:a\s+)?(?:new\s+)?note$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?note\s+"
            r"(?:from|with|using)\s+(?:the\s+)?clipboard(?:\s+contents?)?$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _selected_text_to_note_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _selected_text_to_note_request(text):
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "copy"}),
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Notes", "action": "new_note"},
        ),
        _request("desktop.safe_shortcut", {"action": "paste"}),
    ]


def _selected_text_to_note_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    selected_text_source = (
        r"(?:当前|现在|这个|这段)?(?:选中|选择|高亮)(?:的)?"
        r"(?:内容|文字|文本|选区)?|"
        r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)"
    )
    note_target = r"(?:备忘录|笔记|note)"
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{selected_text_source})\s*"
            rf"(?:写进|写入|记到|记入|保存到|存到|放到|放进|加到|加入|添加到|新建成|创建成)\s*"
            rf"{note_target}(?:里|中|上)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{selected_text_source})\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*{note_target}$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*{note_target}(?:里|中|上)?\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{selected_text_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:paste|put|save|write|add)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)\s+"
            r"(?:into|to|in)\s+(?:a\s+)?(?:new\s+)?note$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?note\s+"
            r"(?:from|with|using)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _current_page_link_to_note_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _current_page_link_to_note_request(text):
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "copy_current_page_link"}),
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Notes", "action": "new_note"},
        ),
        _request("desktop.safe_shortcut", {"action": "paste"}),
    ]


def _current_page_link_to_note_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    current_page_link_source = _communication_current_page_link_source_pattern()
    current_page_source = (
        r"(?:当前|现在|前台|这个|这页|本页).{0,8}"
        r"(?:网页|网站|页面|页|浏览器|标签页)|"
        r"(?:current|active|this)\s+(?:(?:browser\s+)?(?:page|tab))"
    )
    source = rf"(?:{current_page_link_source}|{current_page_source})"
    note_target = r"(?:备忘录|笔记|note)"
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{source})\s*"
            rf"(?:写进|写入|记到|记入|保存到|存到|放到|放进|加到|加入|添加到|新建成|创建成)\s*"
            rf"{note_target}(?:里|中|上)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{source})\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*{note_target}$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*{note_target}(?:里|中|上)?\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:paste|put|save|write|add)\s+(?:the\s+)?"
            r"(?:current|active|this)\s+(?:(?:browser\s+)?(?:page|tab)\s+)?"
            r"(?:url|link|address)?\s*(?:into|to|in)\s+(?:a\s+)?(?:new\s+)?note$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?note\s+"
            r"(?:from|with|using)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)\s+)?(?:url|link|address)?$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _current_content_to_note_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _current_content_to_note_request(text):
        return []
    return [
        *_current_content_copy_tool_requests(),
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Notes", "action": "new_note"},
        ),
        _request("desktop.safe_shortcut", {"action": "paste"}),
    ]


def _current_content_to_note_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    if _current_page_link_to_note_request(clean):
        return False
    current_content_source = _current_content_source_pattern()
    note_target = r"(?:备忘录|笔记|note)"
    return bool(
        re.search(
            rf"^(?:把|将|复制|拷贝)?\s*(?:{current_content_source})\s*"
            rf"(?:写进|写入|记到|记入|保存到|存到|放到|放进|加到|加入|添加到|"
            rf"复制到|复制进|拷贝到|拷贝进|copy\s+to|copy\s+into|"
            rf"新建成|创建成|到|至)\s*{note_target}(?:里|中|上)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{current_content_source})\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*{note_target}$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*{note_target}(?:里|中|上)?\s*"
            rf"(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{current_content_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:paste|put|save|write|add|copy)\s+(?:the\s+)?"
            r"(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)|window|app|application)"
            r"(?:\s+(?:content|contents|text|body))?\s+"
            r"(?:into|to|in)\s+(?:a\s+)?(?:new\s+)?note$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add)\s+(?:a\s+)?(?:new\s+)?note\s+"
            r"(?:from|with|using)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)|window|app|application)"
            r"(?:\s+(?:content|contents|text|body))?$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _current_content_copy_tool_requests() -> list[dict[str, Any]]:
    return [
        _request("desktop.safe_shortcut", {"action": "select_all"}),
        _request("desktop.safe_shortcut", {"action": "copy"}),
    ]


def _current_content_copy_to_clipboard_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _current_content_copy_to_clipboard_request(text):
        return []
    return _current_content_copy_tool_requests()


def _current_content_copy_to_clipboard_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean or _is_browser_current_page_link_copy_request(clean):
        return False
    current_content_source = _current_content_source_pattern()
    clipboard_target = r"(?:剪贴板|粘贴板|clipboard)"
    return bool(
        re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            rf"(?:{current_content_source})\s*(?:复制|拷贝|copy)"
            rf"(?:\s*(?:到|进|至)\s*(?:系统)?{clipboard_target}(?:里|中)?)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:复制|拷贝|copy)\s*(?:{current_content_source})"
            rf"(?:\s*(?:到|进|至)\s*(?:系统)?{clipboard_target}(?:里|中)?)?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:copy)\s+(?:the\s+)?(?:{current_content_source})"
            rf"(?:\s+(?:to|into)\s+(?:the\s+)?(?:system\s+)?clipboard)?$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _current_content_source_pattern() -> str:
    return (
        r"(?:当前|现在|前台|这个|这页|本页).{0,8}"
        r"(?:网页|网站|页面|页|窗口|应用|app|浏览器|标签页)"
        r"(?:内容|正文|文字|文本)?|"
        r"(?:current|active|this)\s+"
        r"(?:(?:browser\s+)?(?:page|tab)|window|app|application)"
        r"(?:\s+(?:content|contents|text|body))?"
    )


def _dynamic_source_to_reminder_tool_requests(text: str) -> list[dict[str, Any]]:
    source = _dynamic_source_to_reminder_request(text)
    if not source:
        return []
    requests: list[dict[str, Any]] = []
    if source == "selected_text":
        requests.append(_request("desktop.safe_shortcut", {"action": "copy"}))
    elif source == "current_page_link":
        requests.append(
            _request("desktop.safe_shortcut", {"action": "copy_current_page_link"})
        )
    elif source == "current_content":
        requests.extend(_current_content_copy_tool_requests())
    requests.extend(
        [
            _request(
                "app.open_and_safe_shortcut",
                {"app_name": "Reminders", "action": "new_reminder"},
            ),
            _request("desktop.safe_shortcut", {"action": "paste"}),
        ]
    )
    return requests


def _dynamic_source_to_reminder_request(text: str) -> str:
    clean = _strip_query(text)
    if not clean:
        return ""
    if _selected_text_to_reminder_request(clean):
        return "selected_text"
    if _clipboard_to_reminder_request(clean):
        return "clipboard"
    if _current_page_link_to_reminder_request(clean):
        return "current_page_link"
    if _current_content_to_reminder_request(clean):
        return "current_content"
    return ""


def _selected_text_to_reminder_request(text: str) -> bool:
    selected_text_source = _selected_text_source_pattern()
    reminder_target = _reminder_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{selected_text_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{reminder_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{selected_text_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{reminder_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{reminder_target})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{selected_text_source})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
            r"(?:from|with|using)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)\s+"
            r"(?:to|into|in)\s+reminders?$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _clipboard_to_reminder_request(text: str) -> bool:
    clipboard_source = _clipboard_source_pattern()
    reminder_target = _reminder_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{clipboard_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{reminder_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{clipboard_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{reminder_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{reminder_target})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{clipboard_source})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
            r"(?:from|with|using)\s+(?:the\s+)?"
            r"(?:clipboard(?:\s+contents?)?|the\s+clipboard(?:\s+contents?)?)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?"
            r"(?:clipboard(?:\s+contents?)?|the\s+clipboard(?:\s+contents?)?)\s+"
            r"(?:to|into|in)\s+reminders?$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _current_page_link_to_reminder_request(text: str) -> bool:
    current_page_link_source = _communication_current_page_link_source_pattern()
    reminder_target = _reminder_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{current_page_link_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{reminder_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{current_page_link_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{reminder_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{reminder_target})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{current_page_link_source})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
            r"(?:from|with|using)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)\s+)?(?:url|link|address)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)\s+)?(?:url|link|address)\s+"
            r"(?:to|into|in)\s+reminders?$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _current_content_to_reminder_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean or _current_page_link_to_reminder_request(clean):
        return False
    current_content_source = _current_content_source_pattern()
    reminder_target = _reminder_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{current_content_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{reminder_target})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{current_content_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{reminder_target})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{reminder_target})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{current_content_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
            r"(?:from|with|using)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)|window|app|application)"
            r"(?:\s+(?:content|contents|text|body))?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)|window|app|application)"
            r"(?:\s+(?:content|contents|text|body))?\s+"
            r"(?:to|into|in)\s+reminders?$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _reminder_target_pattern() -> str:
    return r"(?:提醒事项|提醒|reminder|reminders)"


def _dynamic_source_to_calendar_tool_requests(text: str) -> list[dict[str, Any]]:
    source = _dynamic_source_to_calendar_request(text)
    if not source:
        return []
    requests: list[dict[str, Any]] = []
    if source == "selected_text":
        requests.append(_request("desktop.safe_shortcut", {"action": "copy"}))
    elif source == "current_page_link":
        requests.append(
            _request("desktop.safe_shortcut", {"action": "copy_current_page_link"})
        )
    elif source == "current_content":
        requests.extend(_current_content_copy_tool_requests())
    requests.extend(
        [
            _request(
                "app.open_and_safe_shortcut",
                {"app_name": "Calendar", "action": "new_event"},
            ),
            _request("desktop.safe_shortcut", {"action": "paste"}),
        ]
    )
    return requests


def _dynamic_source_to_calendar_request(text: str) -> str:
    clean = _strip_query(text)
    if not clean:
        return ""
    if _selected_text_to_calendar_request(clean):
        return "selected_text"
    if _clipboard_to_calendar_request(clean):
        return "clipboard"
    if _current_page_link_to_calendar_request(clean):
        return "current_page_link"
    if _current_content_to_calendar_request(clean):
        return "current_content"
    return ""


def _selected_text_to_calendar_request(text: str) -> bool:
    selected_text_source = _selected_text_source_pattern()
    calendar_target = _calendar_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{selected_text_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{calendar_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{selected_text_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{calendar_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{calendar_target})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{selected_text_source})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?"
            r"(?:calendar\s+event|event)\s+(?:from|with|using)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)\s+"
            r"(?:to|into|in)\s+(?:the\s+)?calendar$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _clipboard_to_calendar_request(text: str) -> bool:
    clipboard_source = _clipboard_source_pattern()
    calendar_target = _calendar_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{clipboard_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{calendar_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{clipboard_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{calendar_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{calendar_target})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{clipboard_source})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?"
            r"(?:calendar\s+event|event)\s+(?:from|with|using)\s+(?:the\s+)?"
            r"(?:clipboard(?:\s+contents?)?|the\s+clipboard(?:\s+contents?)?)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?"
            r"(?:clipboard(?:\s+contents?)?|the\s+clipboard(?:\s+contents?)?)\s+"
            r"(?:to|into|in)\s+(?:the\s+)?calendar$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _current_page_link_to_calendar_request(text: str) -> bool:
    current_page_link_source = _communication_current_page_link_source_pattern()
    calendar_target = _calendar_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{current_page_link_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{calendar_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{current_page_link_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{calendar_target})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{calendar_target})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{current_page_link_source})$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?"
            r"(?:calendar\s+event|event)\s+(?:from|with|using)\s+(?:the\s+)?"
            r"(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)\s+)?(?:url|link|address)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)\s+)?(?:url|link|address)\s+"
            r"(?:to|into|in)\s+(?:the\s+)?calendar$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _current_content_to_calendar_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean or _current_page_link_to_calendar_request(clean):
        return False
    current_content_source = _current_content_source_pattern()
    calendar_target = _calendar_target_pattern()
    return bool(
        re.search(
            rf"^(?:把|将)?\s*(?:{current_content_source})\s*"
            rf"(?:新建成|创建成|设成|设置成|加入|加到|添加到|新增到|放到|放进|"
            rf"保存到|存到)\s*(?:{calendar_target})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:用|拿)\s*(?:{current_content_source})\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:{calendar_target})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:在|到)?\s*(?:{calendar_target})(?:里|中|上)?\s*"
            rf"(?:新建|创建|添加|新增|设置)\s*(?:一个|一条|一项|新的?)?\s*"
            rf"(?:来自|根据|使用|用)?\s*(?:{current_content_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:create|make|add|set)\s+(?:a\s+)?(?:new\s+)?"
            r"(?:calendar\s+event|event)\s+(?:from|with|using)\s+(?:the\s+)?"
            r"(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)|window|app|application)"
            r"(?:\s+(?:content|contents|text|body))?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:add|save|put)\s+(?:the\s+)?(?:current|active|this)\s+"
            r"(?:(?:browser\s+)?(?:page|tab)|window|app|application)"
            r"(?:\s+(?:content|contents|text|body))?\s+"
            r"(?:to|into|in)\s+(?:the\s+)?calendar$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _calendar_target_pattern() -> str:
    return r"(?:日历事件|日历日程|日程|日历|事件|calendar\s+event|calendar|event)"


def _browser_dynamic_source_search_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _browser_dynamic_source_search_request(text)
    if not parsed:
        return []
    source, app_name = parsed
    requests: list[dict[str, Any]] = []
    if source == "selected_text":
        requests.append(_request("desktop.safe_shortcut", {"action": "copy"}))
    requests.extend(
        [
            _request(
                "app.open_and_safe_shortcut",
                {"app_name": app_name, "action": "focus_address_bar"},
            ),
            _request("desktop.safe_shortcut", {"action": "paste"}),
            _request("desktop.search_submit", {}),
        ]
    )
    return requests


def _browser_dynamic_source_open_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _browser_dynamic_source_open_request(text)
    if not parsed:
        return []
    source, app_name = parsed
    requests: list[dict[str, Any]] = []
    if source == "selected_text":
        requests.append(_request("desktop.safe_shortcut", {"action": "copy"}))
    requests.extend(
        [
            _request(
                "app.open_and_safe_shortcut",
                {"app_name": app_name, "action": "focus_address_bar"},
            ),
            _request("desktop.safe_shortcut", {"action": "paste"}),
            _request("desktop.search_submit", {}),
        ]
    )
    return requests


def _dynamic_source_paste_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _dynamic_source_paste_request(text)
    if not parsed:
        return []
    source, shortcut_tool, shortcut_input, should_submit = parsed
    requests: list[dict[str, Any]] = []
    if source == "selected_text":
        requests.append(_request("desktop.safe_shortcut", {"action": "copy"}))
    elif source == "current_page_link":
        requests.append(
            _request("desktop.safe_shortcut", {"action": "copy_current_page_link"})
        )
    elif source == "current_content":
        requests.extend(_current_content_copy_tool_requests())
    requests.append(_request(shortcut_tool, shortcut_input))
    if should_submit:
        requests.append(_request("desktop.submit_foreground", {"action": "send"}))
    return requests


def _dynamic_source_to_ui_element_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _dynamic_source_to_ui_element_request(text)
    if not parsed:
        return []
    source, click_request = parsed
    requests = _dynamic_source_copy_tool_requests(source)
    if click_request:
        requests.append(click_request)
    requests.append(_request("desktop.safe_shortcut", {"action": "paste"}))
    return requests


def _dynamic_source_copy_tool_requests(source: str) -> list[dict[str, Any]]:
    if source == "selected_text":
        return [_request("desktop.safe_shortcut", {"action": "copy"})]
    if source == "current_page_link":
        return [_request("desktop.safe_shortcut", {"action": "copy_current_page_link"})]
    if source == "current_content":
        return _current_content_copy_tool_requests()
    return []


def _dynamic_source_to_ui_element_request(
    text: str,
) -> tuple[str, dict[str, Any] | None] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    return _dynamic_source_to_app_ui_element_request(
        clean
    ) or _dynamic_source_to_foreground_ui_element_request(clean)


def _dynamic_source_to_app_ui_element_request(
    text: str,
) -> tuple[str, dict[str, Any] | None] | None:
    app_followup = _dynamic_source_ui_app_followup_request(text)
    if app_followup:
        mode, app_name, source, raw_target = app_followup
        click_request = _dynamic_source_ui_click_request(
            f"app.{mode}_and_click_ui_element",
            raw_target,
            app_name=app_name,
        )
        if click_request:
            return source, click_request
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<source>.+?)\s*(?:输入|填写|填入|填|键入|打入|写入|写|粘贴|贴上|贴入)"
        r"\s*(?:到|进|在)\s*(?P<target>[^。！？!?，,\n]+)$",
        r"^(?:paste|put|copy|type|enter|input)\s+(?:the\s+)?(?P<source>.+?)\s+"
        r"(?:into|to|in|on)\s+(?:the\s+)?(?P<target>[^.!?\n]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        source = _dynamic_paste_source_kind(match.group("source"))
        app_target = _dynamic_source_ui_app_target(match.group("target"))
        if not source or not app_target:
            continue
        app_name, raw_target = app_target
        click_request = _dynamic_source_ui_click_request(
            "app.focus_and_click_ui_element",
            raw_target,
            app_name=app_name,
        )
        if click_request:
            return source, click_request
    return None


def _dynamic_source_ui_app_followup_request(
    text: str,
) -> tuple[str, str, str, str] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None

    mode = "focus"
    body = stripped
    prefix_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "open",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
                r"^(?:please\s+)?(?:open|launch|start)\s+",
            ),
        ),
        (
            "focus",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:切换到|切到|切回|回到|聚焦|激活|置前|在|用|通过|到)\s*",
                r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up|in|on|with|using)\s+",
            ),
        ),
    )
    for candidate_mode, patterns in prefix_patterns:
        for pattern in patterns:
            match = re.search(pattern, stripped, flags=re.IGNORECASE)
            if not match:
                continue
            mode = candidate_mode
            body = stripped[match.end() :].strip()
            break
        else:
            continue
        break

    split = _known_app_prefix_split(body)
    if not split:
        return None
    _raw_app, app_name, followup = split
    parsed = _dynamic_source_ui_followup(followup)
    if not parsed:
        return None
    source, raw_target = parsed
    return mode, app_name, source, raw_target


def _dynamic_source_ui_followup(value: str) -> tuple[str, str] | None:
    clean = _strip_query(value)
    target = _dynamic_source_ui_target_pattern()
    patterns = (
        rf"^(?P<target>{target})(?:里|中|内|上)?\s*"
        rf"(?:输入|填写|填入|填|键入|打入|写入|写|粘贴|贴上|贴入)\s*(?P<source>.+)$",
        rf"^(?:把|将)?\s*(?P<source>.+?)\s*"
        rf"(?:输入|填写|填入|填|键入|打入|写入|写|粘贴|贴上|贴入)"
        rf"\s*(?:到|进|在)\s*(?P<target2>{target})$",
        rf"^(?:paste|put|copy|type|enter|input)\s+(?:the\s+)?(?P<source_en>.+?)\s+"
        rf"(?:into|to|in|on)\s+(?:the\s+)?(?P<target_en>{target})$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        source = _dynamic_paste_source_kind(
            groups.get("source") or groups.get("source_en") or ""
        )
        raw_target = (
            groups.get("target")
            or groups.get("target2")
            or groups.get("target_en")
            or ""
        )
        if source and raw_target:
            return source, raw_target
    return None


def _dynamic_source_to_foreground_ui_element_request(
    text: str,
) -> tuple[str, dict[str, Any] | None] | None:
    clean = _strip_query(text)
    target = _dynamic_source_ui_target_pattern()
    patterns = (
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?P<source>.+?)\s*"
        rf"(?:输入|填写|填入|填|键入|打入|写入|写|粘贴|贴上|贴入)"
        rf"\s*(?:到|进|在)\s*(?P<target>{target})$",
        rf"^(?:paste|put|copy|type|enter|input)\s+(?:the\s+)?(?P<source_en>.+?)\s+"
        rf"(?:into|to|in|on)\s+(?:the\s+)?(?P<target_en>{target})$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        source = _dynamic_paste_source_kind(
            match.groupdict().get("source") or match.groupdict().get("source_en") or ""
        )
        raw_target = (
            match.groupdict().get("target")
            or match.groupdict().get("target_en")
            or ""
        )
        if not source or not raw_target:
            continue
        if _dynamic_source_ui_target_is_foreground_input(raw_target):
            if source == "current_content":
                continue
            return source, None
        click_request = _dynamic_source_ui_click_request(
            "desktop.click_ui_element",
            raw_target,
        )
        if click_request:
            return source, click_request
    return None


def _dynamic_source_ui_app_target(value: str) -> tuple[str, str] | None:
    split = _known_app_prefix_split(_strip_query(value))
    if not split:
        return None
    _raw_app, app_name, followup = split
    if not _dynamic_source_ui_target_kind(followup):
        return None
    return app_name, followup


def _dynamic_source_ui_click_request(
    tool: str,
    raw_target: str,
    *,
    app_name: str = "",
) -> dict[str, Any] | None:
    target = _strip_desktop_ui_input_target(raw_target)
    if not target or _dynamic_source_ui_target_is_foreground_input(raw_target):
        return None
    role_filter = _desktop_ui_element_role_filter(raw_target) or "text"
    payload: dict[str, Any] = {
        "target": target,
        "role_filter": role_filter,
        "limit": 80,
        "click_count": 1,
    }
    if app_name:
        payload = {"app_name": app_name, **payload}
    return _request(tool, payload)


def _current_content_foreground_input_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    current_content_source = _current_content_source_pattern()
    target = _dynamic_source_ui_foreground_input_pattern()
    return bool(
        re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            rf"(?:{current_content_source})\s*"
            rf"(?:输入|填写|填入|填|键入|打入|写入|写|粘贴|贴上|贴入)"
            rf"\s*(?:到|进|在)\s*(?:{target})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:paste|put|copy|type|enter|input)\s+(?:the\s+)?"
            rf"(?:{current_content_source})\s+(?:into|to|in|on)\s+(?:the\s+)?(?:{target})$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_source_ui_target_pattern() -> str:
    return (
        r"(?:当前输入框|当前文本框|当前输入栏|输入框|文本框|输入栏|"
        r"搜索框|搜索栏|搜索输入框|消息框|聊天框|地址栏|"
        r"current\s+input|current\s+text\s*field|current\s+field|input|"
        r"text\s*field|textbox|field|search\s+field|search\s+box|search\s+bar|"
        r"message\s+field|message\s+box|chat\s+box|address\s+bar)"
    )


def _dynamic_source_ui_foreground_input_pattern() -> str:
    return (
        r"(?:当前输入框|当前文本框|当前输入栏|输入框|文本框|输入栏|"
        r"current\s+input|current\s+text\s*field|current\s+field|input|"
        r"text\s*field|textbox|field)"
    )


def _dynamic_source_ui_target_kind(value: str) -> str:
    clean = _strip_query(value)
    if re.fullmatch(
        rf"(?:{_dynamic_source_ui_target_pattern()})",
        clean,
        flags=re.IGNORECASE,
    ):
        return "text"
    return ""


def _dynamic_source_ui_target_is_foreground_input(value: str) -> bool:
    clean = _strip_query(value)
    return bool(
        re.fullmatch(
            rf"(?:{_dynamic_source_ui_foreground_input_pattern()})",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_source_paste_request(
    text: str,
) -> tuple[str, str, dict[str, Any], bool] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    return _dynamic_source_paste_request_for_app_scope(
        clean
    ) or _dynamic_source_paste_request_for_foreground_scope(clean)


def _current_content_foreground_paste_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    current_content_source = _current_content_source_pattern()
    target = _dynamic_paste_foreground_target_pattern()
    return bool(
        re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            rf"(?:{current_content_source})\s*(?:复制|拷贝)?\s*"
            rf"(?:(?:并|然后|再)\s*)?(?:粘贴|贴上|贴入)"
            rf"(?:\s*(?:到|进|在)\s*(?:{target}))?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:paste|copy)\s+(?:the\s+)?(?:{current_content_source})\s+"
            rf"(?:into|to|in|on)\s+(?:the\s+)?(?:{target})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:paste|copy)\s+(?:the\s+)?(?:{current_content_source})\s+"
            rf"(?:the\s+)?(?:{target})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:copy\s+)?(?:the\s+)?(?:{current_content_source})\s+"
            rf"(?:and\s+then\s+|and\s+)?paste\s+(?:{target})?$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_source_paste_request_for_app_scope(
    text: str,
) -> tuple[str, str, dict[str, Any], bool] | None:
    clean = _strip_query(text)
    app_followup = _dynamic_source_paste_app_followup_request(clean)
    if app_followup:
        mode, app_name, source, should_submit = app_followup
        return (
            source,
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "paste"},
            should_submit,
        )
    prefix_match = _app_open_or_focus_known_app_followup_match(clean)
    if prefix_match:
        mode, _raw_app, app_name, followup = prefix_match
        parsed = _dynamic_source_paste_followup_source(followup)
        if parsed:
            source, should_submit = parsed
            return (
                source,
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": "paste"},
                should_submit,
            )
    split = _known_app_prefix_split(clean)
    if split:
        _raw_app, app_name, followup = split
        parsed = _dynamic_source_paste_followup_source(followup)
        if parsed:
            source, should_submit = parsed
            return (
                source,
                "app.focus_and_safe_shortcut",
                {"app_name": app_name, "action": "paste"},
                should_submit,
            )
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<source>.+?)\s*(?:复制|拷贝)?\s*"
        r"(?:(?:并|然后|再)\s*)?(?:粘贴|贴上|贴入)\s*(?:到|进|在)?\s*"
        r"(?P<target>[^。！？!?，,\n]+?)(?P<tail>(?:\s*(?:并|然后|再)\s*(?:发送|发出|提交))?)$",
        r"^(?:paste|copy)\s+(?:the\s+)?(?P<source>.+?)\s+"
        r"(?:into|to|in|on)\s+(?:the\s+)?(?P<target>[^.!?\n]+?)"
        r"(?P<tail>(?:\s+(?:and\s+then|then|and)\s*(?:send|submit|post))?)$",
        r"^(?:copy\s+)?(?:the\s+)?(?P<source>.+?)\s+"
        r"(?:and\s+then\s+|and\s+)?paste\s+"
        r"(?:into|to|in|on)\s+(?:the\s+)?(?P<target>[^.!?\n]+?)"
        r"(?P<tail>(?:\s+(?:and\s+then|then|and)\s*(?:send|submit|post))?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        source = _dynamic_paste_source_kind(match.group("source"))
        app_name = _dynamic_paste_target_app_name(match.group("target"))
        if not source or not app_name:
            continue
        return (
            source,
            "app.focus_and_safe_shortcut",
            {"app_name": app_name, "action": "paste"},
            _dynamic_paste_has_submit_intent(match.group("tail")),
        )
    return None


def _dynamic_source_paste_app_followup_request(
    text: str,
) -> tuple[str, str, str, bool] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None

    mode = "focus"
    body = stripped
    prefix_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "open",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
                r"^(?:please\s+)?(?:open|launch|start)\s+",
            ),
        ),
        (
            "focus",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:切换到|切到|切回|回到|聚焦|激活|置前|在|用|通过|到)\s*",
                r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up|in|on|with|using)\s+",
            ),
        ),
    )
    for candidate_mode, patterns in prefix_patterns:
        for pattern in patterns:
            match = re.search(pattern, stripped, flags=re.IGNORECASE)
            if not match:
                continue
            mode = candidate_mode
            body = stripped[match.end() :].strip()
            break
        else:
            continue
        break

    split = _known_app_prefix_split(body)
    if not split:
        return None
    _raw_app, app_name, followup = split
    parsed = _dynamic_source_paste_followup_source(followup)
    if not parsed:
        return None
    source, should_submit = parsed
    return mode, app_name, source, should_submit


def _dynamic_source_paste_request_for_foreground_scope(
    text: str,
) -> tuple[str, str, dict[str, Any], bool] | None:
    clean = _strip_query(text)
    target = _dynamic_paste_foreground_target_pattern()
    patterns = (
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?P<source>.+?)\s*(?:复制|拷贝)?\s*"
        rf"(?:(?:并|然后|再)\s*)?(?:粘贴|贴上|贴入)"
        rf"(?:\s*(?:到|进|在)\s*(?P<target>{target}))?"
        rf"(?P<tail>\s*(?:(?:并|然后|再)\s*(?:发送|发出|提交))?)$",
        rf"^(?:paste|copy)\s+(?:the\s+)?(?P<source>.+?)\s+"
        rf"(?:into|to|in|on)\s+(?:the\s+)?(?P<target>{target})"
        rf"(?P<tail>(?:\s+(?:and\s+then|then|and)\s*(?:send|submit|post))?)$",
        rf"^(?:paste|copy)\s+(?:the\s+)?(?P<source>.+?)\s+(?P<target>{target})"
        rf"(?P<tail>(?:\s+(?:and\s+then|then|and)\s*(?:send|submit|post))?)$",
        rf"^(?:copy\s+)?(?:the\s+)?(?P<source>.+?)\s+"
        rf"(?:and\s+then\s+|and\s+)?paste\s+(?P<target>{target})"
        rf"(?P<tail>(?:\s+(?:and\s+then|then|and)\s*(?:send|submit|post))?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        source = _dynamic_paste_source_kind(match.group("source"))
        if not source or source == "current_content":
            continue
        raw_target = str(match.groupdict().get("target") or "").strip()
        if raw_target and not _dynamic_paste_target_is_foreground(raw_target):
            continue
        return (
            source,
            "desktop.safe_shortcut",
            {"action": "paste"},
            _dynamic_paste_has_submit_intent(match.group("tail")),
        )
    return None


def _dynamic_source_paste_followup_source(value: str) -> tuple[str, bool] | None:
    clean = _strip_query(value)
    patterns = (
        r"^(?:把|将)?\s*(?P<source>.+?)\s*(?:复制|拷贝)?\s*"
        r"(?:(?:并|然后|再)\s*)?(?:粘贴|贴上|贴入)"
        r"(?P<tail>\s*(?:(?:并|然后|再)\s*(?:发送|发出|提交))?)$",
        r"^(?:粘贴|贴上|贴入)\s*(?P<source>.+?)"
        r"(?P<tail>\s*(?:(?:并|然后|再)\s*(?:发送|发出|提交))?)$",
        r"^(?:paste|copy)\s+(?:the\s+)?(?P<source>.+?)"
        r"(?P<tail>(?:\s+(?:and\s+then|then|and)\s*(?:send|submit|post))?)$",
        r"^(?:copy\s+)?(?:the\s+)?(?P<source>.+?)\s+"
        r"(?:and\s+then\s+|and\s+)?paste"
        r"(?P<tail>(?:\s+(?:and\s+then|then|and)\s*(?:send|submit|post))?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        source = _dynamic_paste_source_kind(match.group("source"))
        if source:
            return source, _dynamic_paste_has_submit_intent(match.group("tail"))
    return None


def _dynamic_paste_source_kind(value: str) -> str:
    clean = _strip_query(value)
    selected_text_source = _selected_text_source_pattern()
    clipboard_source = _clipboard_source_pattern()
    current_page_link_source = _communication_current_page_link_source_pattern()
    current_content_source = _current_content_source_pattern()
    if re.fullmatch(rf"(?:{selected_text_source})", clean, flags=re.IGNORECASE):
        return "selected_text"
    if re.fullmatch(rf"(?:{clipboard_source})", clean, flags=re.IGNORECASE):
        return "clipboard"
    if re.fullmatch(rf"(?:{current_page_link_source})", clean, flags=re.IGNORECASE):
        return "current_page_link"
    if re.fullmatch(rf"(?:{current_content_source})", clean, flags=re.IGNORECASE):
        return "current_content"
    return ""


def _dynamic_paste_target_app_name(value: str) -> str:
    target = _strip_query(value)
    target = re.sub(
        r"\s*(?:当前|这个)?(?:输入框|文本框|输入栏|窗口|应用|app)$",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip()
    target = re.sub(
        r"\s*(?:current|active|this)?\s*(?:input|text\s*field|textbox|field|window|app|application)$",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip()
    if not target or _dynamic_paste_target_is_foreground(target):
        return ""
    if not _is_known_app_reference(target):
        return ""
    return _normalize_app_name(target)


def _dynamic_paste_target_is_foreground(value: str) -> bool:
    clean = _strip_query(value)
    if not clean:
        return False
    return bool(
        re.fullmatch(
            rf"(?:{_dynamic_paste_foreground_target_pattern()})",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_paste_foreground_target_pattern() -> str:
    return (
        r"(?:这(?:里)?|当前|前台|当前输入框|输入框|当前文本框|文本框|"
        r"当前输入栏|输入栏|当前窗口|前台窗口|"
        r"here|current\s+input|input|current\s+text\s*field|text\s*field|"
        r"textbox|current\s+field|field|current\s+window|foreground|frontmost)"
    )


def _dynamic_paste_has_submit_intent(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        re.search(r"(?:并|然后|再)\s*(?:发送|发出|提交)$", text, flags=re.IGNORECASE)
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:send|submit|post)$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_source_find_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _dynamic_source_find_request(text)
    if not parsed:
        return []
    source, shortcut_tool, shortcut_input = parsed
    requests: list[dict[str, Any]] = []
    if source == "selected_text":
        requests.append(_request("desktop.safe_shortcut", {"action": "copy"}))
    requests.extend(
        [
            _request(shortcut_tool, shortcut_input),
            _request("desktop.safe_shortcut", {"action": "paste"}),
        ]
    )
    return requests


def _dynamic_source_find_request(text: str) -> tuple[str, str, dict[str, Any]] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    return _dynamic_find_request_for_app_scope(
        clean
    ) or _dynamic_find_request_for_foreground_scope(clean)


def _dynamic_find_request_for_app_scope(
    text: str,
) -> tuple[str, str, dict[str, Any]] | None:
    clean = _strip_query(text)
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到)\s*(?P<app>[^。！？!?，,\n]+?)(?:里|中|内|上|里面)\s*"
        r"(?:查找|搜索(?!框)|搜一下|找一下|找|检索)\s*(?P<source>.+)$",
        r"^(?:find|search)\s+(?:for\s+)?(?P<source>.+?)\s+"
        r"(?:in|on|inside|within)\s+(?:the\s+)?(?P<app>[^.!?\n]+)$",
        r"^(?:find|search)\s+(?:in|inside|within)\s+(?:the\s+)?(?P<app>[^.!?\n]+?)\s+"
        r"(?:for|using)\s+(?:the\s+)?(?P<source>.+)$",
        r"^(?:find|search)\s+(?P<app>[^.!?\n]+?)\s+for\s+(?:the\s+)?(?P<source>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        source = _dynamic_find_source_kind(match.group("source"))
        if (
            not source
            or not raw_app
            or _dynamic_find_scope_is_foreground(raw_app)
            or _looks_like_window_target(raw_app)
            or _looks_like_common_path_target(raw_app)
        ):
            continue
        app_name = _normalize_app_name(raw_app)
        if not app_name:
            continue
        return (
            source,
            "app.focus_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        )
    return None


def _dynamic_find_request_for_foreground_scope(
    text: str,
) -> tuple[str, str, dict[str, Any]] | None:
    clean = _strip_query(text)
    scope = _dynamic_find_foreground_scope_pattern()
    patterns = (
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在\s*)?(?P<scope>{scope})(?:里|中|内|上|里面)?\s*"
        rf"(?:查找|搜索(?!框)|搜一下|找一下|找|检索)\s*(?P<source>.+)$",
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:用|拿)?\s*(?P<source>.+?)\s*"
        rf"(?:查找|搜索(?!框)|搜一下|找一下|找|检索)\s*"
        rf"(?P<scope>{scope})(?:里|中|内|上|里面)?$",
        rf"^(?:find|search)\s+(?:for\s+)?(?P<source>.+?)\s+"
        rf"(?:in|on|inside|within)\s+(?:the\s+)?(?P<scope>{scope})$",
        rf"^(?:find|search)\s+(?:the\s+)?(?P<scope>{scope})\s+"
        rf"(?:for|using)\s+(?:the\s+)?(?P<source>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        source = _dynamic_find_source_kind(match.group("source"))
        if source and _dynamic_find_scope_is_foreground(match.group("scope")):
            return (
                source,
                "desktop.safe_shortcut",
                {"action": "find"},
            )
    return None


def _dynamic_find_source_kind(value: str) -> str:
    clean = _strip_query(value)
    selected_text_source = _selected_text_source_pattern()
    clipboard_source = _clipboard_source_pattern()
    if re.fullmatch(rf"(?:{selected_text_source})", clean, flags=re.IGNORECASE):
        return "selected_text"
    if re.fullmatch(rf"(?:{clipboard_source})", clean, flags=re.IGNORECASE):
        return "clipboard"
    return ""


def _dynamic_find_scope_is_foreground(value: str) -> bool:
    clean = _strip_query(value)
    if not clean:
        return False
    return bool(
        re.fullmatch(
            rf"(?:{_dynamic_find_foreground_scope_pattern()})",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_find_foreground_scope_pattern() -> str:
    return (
        r"(?:(?:当前|前台|这个|该)?(?:页面|网页|页内|页面内|标签页|窗口|应用|app)|"
        r"(?:(?:current|this|active|foreground)\s+)?"
        r"(?:(?:browser\s+)?(?:page|web\s*page|tab)|window|app|application|ui|interface))"
    )


def _browser_dynamic_source_open_request(text: str) -> tuple[str, str] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    app_name = _browser_dynamic_open_app_name(clean)
    if _selected_text_browser_open_request(clean):
        return "selected_text", app_name
    if _clipboard_browser_open_request(clean):
        return "clipboard", app_name
    return None


def _browser_dynamic_open_app_name(text: str) -> str:
    app_name = _browser_dynamic_search_app_name(text)
    if app_name != "Google Chrome":
        return app_name
    match = re.search(
        r"\b(?:in|with|using|via)\s+"
        r"(?P<app>chrome|google|google\s*chrome|safari|firefox|edge|arc|brave)\b",
        _strip_query(text),
        flags=re.IGNORECASE,
    )
    if match:
        normalized = _normalize_app_name(match.group("app"))
        if normalized in _BROWSER_APP_NAMES:
            return normalized
    return app_name


def _selected_text_browser_open_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    selected_url_source = _selected_url_source_pattern()
    browser_app_pattern = _browser_app_reference_pattern()
    return bool(
        re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:(?:用|在|通过)\s*{browser_app_pattern}\s*(?:里|中|上|内|里面)?\s*)?"
            rf"(?:打开|访问|浏览|跳转到|进入)\s*(?:{selected_url_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:把|将)?\s*(?:{selected_url_source})\s*"
            rf"(?:用|在|通过)?\s*(?:{browser_app_pattern})?\s*"
            rf"(?:打开|访问|浏览|跳转到|进入)$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:open|visit|go\s+to|browse)\s+(?:the\s+)?"
            rf"(?:{selected_url_source})(?:\s+(?:in|with|using|via)\s+"
            rf"{browser_app_pattern})?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:open|visit|go\s+to|browse)\s+(?:{browser_app_pattern})\s+"
            rf"(?:with\s+)?(?:the\s+)?(?:{selected_url_source})$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _clipboard_browser_open_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    clipboard_url_source = _clipboard_url_source_pattern()
    browser_app_pattern = _browser_app_reference_pattern()
    return bool(
        re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:(?:用|在|通过)\s*{browser_app_pattern}\s*(?:里|中|上|内|里面)?\s*)?"
            rf"(?:打开|访问|浏览|跳转到|进入)\s*(?:{clipboard_url_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:把|将)?\s*(?:{clipboard_url_source})\s*"
            rf"(?:用|在|通过)?\s*(?:{browser_app_pattern})?\s*"
            rf"(?:打开|访问|浏览|跳转到|进入)$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:open|visit|go\s+to|browse)\s+(?:the\s+)?"
            rf"(?:{clipboard_url_source})(?:\s+(?:in|with|using|via)\s+"
            rf"{browser_app_pattern})?$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:open|visit|go\s+to|browse)\s+(?:{browser_app_pattern})\s+"
            rf"(?:with\s+)?(?:the\s+)?(?:{clipboard_url_source})$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _browser_dynamic_source_search_request(text: str) -> tuple[str, str] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    app_name = _browser_dynamic_search_app_name(clean)
    if _selected_text_browser_search_request(clean):
        return "selected_text", app_name
    if _clipboard_browser_search_request(clean):
        return "clipboard", app_name
    return None


def _browser_dynamic_search_app_name(text: str) -> str:
    match = re.search(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:用|在|通过)\s*"
        r"(?P<app>浏览器|chrome|google|google\s*chrome|谷歌|谷歌浏览器|百度|safari|firefox|edge|arc|brave)"
        r"\s*(?:里|中|上|内|里面)?",
        _strip_query(text),
        flags=re.IGNORECASE,
    )
    if match:
        app_name = _normalize_app_name(match.group("app"))
        if app_name in _BROWSER_APP_NAMES:
            return app_name
    return "Google Chrome"


def _selected_text_browser_search_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    selected_text_source = _selected_text_source_pattern()
    return bool(
        re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:(?:用|在|通过)\s*"
            rf"(?:浏览器|chrome|google|google\s*chrome|谷歌|谷歌浏览器|百度|safari|firefox|edge|arc|brave)"
            rf"\s*(?:里|中|上|内|里面)?\s*)?"
            rf"(?:搜索|搜一下|搜|检索|查一下|查查|查|google|谷歌一下|百度一下)\s*"
            rf"(?:{selected_text_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:把|将)?\s*(?:{selected_text_source})\s*"
            rf"(?:拿去|用来|去|帮我)?\s*"
            rf"(?:搜索|搜一下|搜|检索|查一下|查查|查|google|谷歌一下|百度一下)$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:search|google|look\s+up)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:search|google|look\s+up)\s+(?:with|using)\s+(?:the\s+)?"
            r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _clipboard_browser_search_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    clipboard_source = _clipboard_source_pattern()
    return bool(
        re.search(
            rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:(?:用|在|通过)\s*"
            rf"(?:浏览器|chrome|google|google\s*chrome|谷歌|谷歌浏览器|百度|safari|firefox|edge|arc|brave)"
            rf"\s*(?:里|中|上|内|里面)?\s*)?"
            rf"(?:搜索|搜一下|搜|检索|查一下|查查|查|google|谷歌一下|百度一下)\s*"
            rf"(?:{clipboard_source})$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"^(?:把|将)?\s*(?:{clipboard_source})\s*"
            rf"(?:拿去|用来|去|帮我)?\s*"
            rf"(?:搜索|搜一下|搜|检索|查一下|查查|查|google|谷歌一下|百度一下)$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:search|google|look\s+up)\s+(?:the\s+)?"
            r"(?:clipboard\s+contents?|the\s+clipboard(?:\s+contents?)?)$",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:search|google|look\s+up)\s+(?:with|using|from)\s+(?:the\s+)?"
            r"(?:clipboard\s+contents?|the\s+clipboard(?:\s+contents?)?)$",
            clean,
            flags=re.IGNORECASE,
        )
    )


def _selected_text_source_pattern() -> str:
    return (
        r"(?:当前|现在|这个|这段)?(?:选中|选择|高亮)(?:的)?"
        r"(?:内容|文字|文本|选区)?|"
        r"(?:selected\s+text|highlighted\s+text|selection|current\s+selection)"
    )


def _clipboard_source_pattern() -> str:
    return (
        r"(?:当前|系统|这个|这份|我的)?(?:剪贴板|粘贴板)(?:内容)?|"
        r"(?:the\s+)?clipboard\s+contents?|the\s+clipboard"
    )


def _selected_url_source_pattern() -> str:
    return (
        r"(?:当前|现在|这个|这段)?(?:选中|选择|高亮)(?:的)?"
        r"(?:链接|网址|url|URL|地址|内容|文字|文本)|"
        r"(?:selected|highlighted)\s+(?:link|url|URL|address|text)|"
        r"current\s+selection"
    )


def _clipboard_url_source_pattern() -> str:
    return (
        r"(?:当前|系统|这个|这份|我的)?(?:剪贴板|粘贴板)"
        r"(?:里|里面|内容里|内容里的|里的)?(?:的)?(?:链接|网址|url|URL|地址|内容)|"
        r"(?:the\s+)?clipboard\s+(?:link|url|URL|address|contents?)"
    )


def _browser_app_reference_pattern() -> str:
    return (
        r"(?:浏览器|browser|chrome|google|google\s*chrome|谷歌|谷歌浏览器|百度|"
        r"safari|firefox|edge|arc|brave)"
    )


def _looks_like_postposed_clipboard_copy_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:把|将)\s*[^。！？!?，,\n]+?\s*(?:复制|拷贝)(?:一下|下)?\s*(?:吧|给我)?$",
            str(text or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _clipboard_read_request(text: str) -> bool:
    if (
        _clipboard_to_note_request(text)
        or _selected_text_to_note_request(text)
        or _current_page_link_to_note_request(text)
        or _current_content_to_note_request(text)
    ):
        return False
    if _clipboard_write_text(text):
        return False
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:读取|读一下|读下|读一读|查看|看看|看一下|看下|显示|告诉我).{0,8}"
            r"(?:系统)?(?:剪贴板|粘贴板|clipboard).{0,8}(?:内容|里|里面|是什么|有啥|有什么|给我)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:系统)?(?:剪贴板|粘贴板|clipboard).{0,8}"
            r"(?:内容|里|里面|是什么|有啥|有什么|读取|读一下|读下|读一读|读给我|查看|看看|看一下|看下|显示)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|show|display|check|tell\s+me)\s+(?:the\s+)?"
            r"(?:(?:system|my)\s+)?clipboard(?:\s+contents?)?\b",
            lowered,
        )
        or re.search(
            r"\b(?:what(?:'s| is)|what)\s+(?:is\s+)?(?:on|in)\s+(?:the\s+|my\s+)?"
            r"(?:system\s+)?clipboard\b",
            lowered,
        )
    )


def _selected_text_read_tool_requests(text: str) -> list[dict[str, Any]]:
    if not _selected_text_read_request(text):
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "copy"}),
        _request("clipboard.read", {}),
    ]


def _selected_text_read_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean or _clipboard_write_text(clean):
        return False
    explicit_copy_read = _selected_text_copy_then_read_clipboard_request(clean)
    if _clipboard_read_request(clean) and not explicit_copy_read:
        return False
    lowered = clean.lower()
    return bool(
        explicit_copy_read
        or re.search(
            r"(?:复制|拷贝).{0,12}(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区)?.{0,16}"
            r"(?:读|读取|查看|看看|显示).{0,12}(?:剪贴板|粘贴板)",
            clean,
        )
        or re.search(
            r"(?:读|读取|查看|看看|看一下|看下|显示|告诉我).{0,12}"
            r"(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区)",
            clean,
        )
        or re.search(
            r"(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区).{0,12}"
            r"(?:是什么|是啥|有啥|有什么|读|读取|查看|看看|看一下|看下|显示|告诉我)",
            clean,
        )
        or re.search(
            r"(?:我|当前|现在)?(?:选中|选取|高亮|选择)(?:了|的)?"
            r"(?:内容|文字|文本|这段|这部分|选区)?\s*(?:是什么|是啥|有啥|有什么)",
            clean,
        )
        or re.search(
            r"(?:我|当前|现在)?(?:选中|选取|高亮|选择)(?:了|的)?\s*(?:什么|啥)",
            clean,
        )
        or re.search(
            r"(?:选中|选取|高亮|选择).{0,12}(?:内容|文字|文本|这段|这部分|选区)?"
            r".{0,8}(?:复制|拷贝)(?:给|给我|给我看|出来)",
            clean,
        )
        or re.search(
            r"\b(?:read|show|display|check|tell\s+me)\s+(?:the\s+)?"
            r"(?:selected|highlighted)\s+(?:text|content|selection)\b",
            lowered,
        )
        or re.search(
            r"\bwhat(?:'s| is)\s+(?:the\s+)?"
            r"(?:selected|highlighted)\s+(?:text|content|selection)\b",
            lowered,
        )
    )


def _selected_text_copy_then_read_clipboard_request(text: str) -> bool:
    clean = _strip_query(text)
    lowered = clean.lower()
    return bool(
        re.search(
            r"(?:复制|拷贝).{0,12}(?:选中|选取|高亮|选择).{0,12}"
            r"(?:内容|文字|文本|这段|这部分|选区)?.{0,16}"
            r"(?:读|读取|查看|看看|显示).{0,12}(?:剪贴板|粘贴板)",
            clean,
        )
        or re.search(
            r"(?:选中|选取|高亮|选择).{0,12}(?:内容|文字|文本|这段|这部分|选区)?"
            r".{0,16}(?:复制|拷贝).{0,16}(?:读|读取|查看|看看|显示).{0,12}(?:剪贴板|粘贴板)",
            clean,
        )
        or re.search(
            r"\bcopy\s+(?:the\s+)?(?:selected|highlighted)\s+"
            r"(?:text|content|selection)\s+(?:and|then)\s+"
            r"(?:read|show|display|check)\s+(?:the\s+)?(?:system\s+)?clipboard\b",
            lowered,
        )
    )


def _normalize_clipboard_text(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^(?:一下|下|这个|那个)\s*", "", text)
    text = text.strip(" 「」『』“”\"'`")
    compact = re.sub(r"[\s._-]+", "", text.lower())
    generic_sources = {
        "",
        "这段",
        "这段文字",
        "这段文本",
        "这个",
        "这个文本",
        "这个内容",
        "那个",
        "那个内容",
        "它",
        "当前",
        "当前内容",
        "当前文字",
        "当前文本",
        "当前窗口",
        "当前窗口内容",
        "当前页面",
        "当前页面内容",
        "当前网页",
        "当前网页内容",
        "当前网址",
        "当前链接",
        "当前页面链接",
        "当前网页链接",
        "当前选中",
        "当前选中内容",
        "当前选中文字",
        "当前选中文本",
        "选中",
        "选中内容",
        "选中文字",
        "选中文本",
        "选区",
        "选择内容",
        "高亮内容",
        "窗口内容",
        "页面内容",
        "网页内容",
        "文件",
        "这个文件",
        "text",
        "thistext",
        "selectedtext",
        "selectedcontent",
        "selection",
        "currentselection",
        "currenttext",
        "currentcontent",
        "currentpage",
        "currenturl",
        "currentlink",
        "this",
        "it",
    }
    if compact in generic_sources:
        return ""
    if re.fullmatch(
        r"(?:当前|现在|这个|该)?(?:窗口|界面|屏幕|页面|网页|应用|app|ui)(?:内容|文字|文本|选区)?",
        compact,
    ):
        return ""
    if re.fullmatch(
        r"(?:当前|现在|这个|该)?(?:选中|选取|高亮|选择)(?:的)?(?:内容|文字|文本|选区)?",
        compact,
    ):
        return ""
    return text


def _is_running_apps_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(r"\bopen\s+(?:the\s+)?applications?\s+(?:folder|directory)\b", lowered):
        return False
    return bool(
        re.search(
            r"(?:现在|当前|桌面|电脑|系统|前台|后台)?.{0,8}"
            r"(?:开了|打开了|运行着|正在运行|在运行|启动了).{0,8}"
            r"(?:哪些|什么|什么样的|几个)?.{0,4}(?:应用|app|软件|程序)",
            text,
        )
        or re.search(
            r"(?:列出|列一下|列下|查看|看看|显示|读取).{0,8}"
            r"(?:正在运行|在运行|打开|已打开|运行中).{0,8}(?:应用|app|软件|程序)",
            text,
        )
        or re.search(
            r"(?:现在|当前|桌面|电脑|系统|前台|后台)?.{0,8}"
            r"(?:有哪些|有哪|什么|哪些|几个).{0,4}(?:应用|app|软件|程序).{0,8}"
            r"(?:正在运行|在运行|运行中|打开|已打开|开着|启动着)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:what|which|list|show|read)\s+(?:apps?|applications?|programs?)\s+"
            r"(?:are\s+)?(?:running|open)\b",
            lowered,
        )
        or re.search(r"\b(?:running|open)\s+(?:apps?|applications?|programs?)\b", lowered)
    )


def _is_installed_apps_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(r"\bopen\s+(?:the\s+)?applications?\s+(?:folder|directory)\b", lowered):
        return False
    return bool(
        re.search(
            r"(?:列出|列一下|列下|查看|看看|显示|读取|找一下|找出).{0,8}"
            r"(?:已安装|装了|安装了|可用|可以打开|能打开).{0,8}"
            r"(?:应用|app|软件|程序)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:有哪些|有哪|哪些|什么).{0,8}"
            r"(?:已安装|装了|安装了|可用|可以打开|能打开).{0,8}"
            r"(?:应用|app|软件|程序)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:应用|app|软件|程序).{0,8}"
            r"(?:已安装|装了|安装了|可用|可以打开|能打开)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:list|show|find|read)\s+(?:installed|available)\s+"
            r"(?:apps?|applications?|programs?)\b",
            lowered,
        )
        or re.search(r"\b(?:installed|available)\s+(?:apps?|applications?|programs?)\b", lowered)
    )


def _app_status_name(text: str) -> str:
    if not _looks_like_app_status_request(text):
        return ""
    for pattern in _APP_STATUS_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        app_name = _normalize_app_name(raw_app)
        if not app_name or _looks_like_generic_app_open_target(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        return app_name
    return ""


def _looks_like_schedule_creation_request(text: str) -> bool:
    raw = str(text or "").strip()
    lowered = raw.lower()
    return bool(
        re.search(r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?提醒我", raw)
        or re.search(r"(?:新建|创建|添加|新增|设置|设定).{0,8}(?:提醒事项|提醒)", raw)
        or re.search(r"(?:提醒事项|reminders?).{0,12}(?:新建|创建|添加|新增|设置|设定|加)", lowered)
        or re.search(r"(?:新建|创建|添加|新增|设置|设定).{0,8}(?:日历事件|日程|日历日程)", raw)
        or re.search(
            r"(?:日历|calendar).{0,12}(?:新建|创建|添加|新增|设置|设定).{0,8}"
            r"(?:日程|事件|event)",
            lowered,
        )
        or re.search(
            r"\b(?:remind me|create (?:a )?reminder|add (?:a )?reminder|"
            r"create (?:a )?calendar event|add (?:a )?calendar event)\b",
            lowered,
        )
    )


def _desktop_windows_request(text: str) -> dict[str, str] | None:
    if _is_active_window_request(text):
        return None
    if _is_current_ui_text_request(text):
        return None
    known_no_space_match = re.search(
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取)"
        r"(?P<app>[^。！？!?，,\s]+?)\s*(?:的)?\s*(?:窗口|windows?)$",
        text,
        flags=re.IGNORECASE,
    )
    if known_no_space_match:
        raw_app = _strip_window_scope_app_prefix(known_no_space_match.group("app"))
        app_name = _normalize_app_name(raw_app)
        if app_name and _is_known_app_reference(raw_app):
            return {"app_name": app_name}
    app_patterns = (
        r"(?:list|show|read)\s+(?:open\s+)?windows\s+(?:in|for|of)\s+(?P<app>[^.!?]+)",
        r"(?:what|which)\s+(?:open\s+)?windows\s+(?:are\s+)?(?:open\s+)?"
        r"(?:in|for|of)\s+(?P<app>[^.!?]+)",
        r"(?:what|which)\s+windows\s+does\s+(?P<app>[^.!?]+?)\s+have",
        r"(?:list|show|read)\s+(?P<app>[^.!?]+?)\s+windows",
        r"(?P<app>[^.!?]+?)\s+windows\?",
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*(?:窗口|windows?)\s*(?:列表|清单|list)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:列出|查看|看看|看一下|看下|显示|读取)\s+"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有|打开了|开了|正在显示)?"
        r"(?:哪些|什么|几个|多少).{0,4}(?:窗口|window)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:列出|查看|看看|看一下|看下|显示|读取)\s+"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*(?:窗口|windows?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:列出|查看|看看|显示|读取)\s+"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:窗口|windows?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有|打开了|开了|正在显示)?"
        r"(?:哪些|什么|几个|多少).{0,4}(?:窗口|window)",
    )
    for pattern in app_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_window_scope_app_prefix(match.group("app"))
        if _looks_like_generic_window_scope(raw_app):
            return {}
        app_name = _normalize_app_name(raw_app)
        if app_name and not _looks_like_generic_app_open_target(raw_app):
            return {"app_name": app_name}
    if _is_general_windows_request(text):
        return {}
    return None


def _desktop_ui_elements_request(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    if not (
        _is_current_ui_text_request(text)
        or _is_ui_elements_location_request(text)
        or re.search(
            r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取|查看|看看|看一下|识别)"
            r".{0,12}(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)"
            r".{0,12}(?:文字|文本|内容|正文)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|inspect|show|extract)\b.{0,16}\b"
            r"(?:current|this|active|foreground)\s+(?:window|ui|interface|screen)\b"
            r".{0,16}\b(?:text|content)\b",
            lowered,
        )
        or re.search(
            r"(?:当前|现在|这个|前台)?(?:窗口|界面|屏幕|应用|app)?"
            r".{0,10}(?:有哪些|有什么|列出|列一下|显示|查看|看看|看一下|读取|识别)"
            r".{0,10}(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:控件|按钮|输入框|文本框|元素|选项|ui|可点击|可操作)"
            r".{0,10}(?:有哪些|有什么|列表|列一下|显示|查看|看看|看一下|读取|识别)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:list|show|read|inspect)\b.{0,24}\b(?:ui elements|buttons|text fields|controls)\b",
            lowered,
        )
        or re.search(r"\b(?:what|which)\b.{0,24}\b(?:buttons|controls|ui elements)\b", lowered)
        or re.search(r"\b(?:visible|shown|available)\s+(?:buttons|controls|ui elements|text fields)\b", lowered)
        or re.search(r"\b(?:inspect|list|show|read)\s+(?:the\s+)?(?:current\s+)?(?:ui|interface)\b", lowered)
        or re.search(r"\bwhat\s+can\s+i\s+(?:click|press|use)\b", lowered)
    ):
        return None
    role_filter = ""
    if _is_current_ui_text_request(text) or re.search(
        r"(?:文字|文本|正文|content|text)", text, flags=re.IGNORECASE
    ):
        role_filter = "text"
    elif re.search(r"(?:按钮|button)", text, flags=re.IGNORECASE):
        role_filter = "button"
    elif re.search(r"(?:输入框|文本框|输入栏|text field|textbox|input)", text, flags=re.IGNORECASE):
        role_filter = "text"
    elif re.search(r"(?:菜单|menu)", text, flags=re.IGNORECASE):
        role_filter = "menu"
    elif re.search(r"(?:复选框|checkbox)", text, flags=re.IGNORECASE):
        role_filter = "checkbox"
    return {"role_filter": role_filter, "limit": 80}


def _is_ui_elements_location_request(text: str) -> bool:
    lowered = text.lower()
    if re.search(
        r"(?:双击|点击|点一下|点按|单击|按一下|按下|"
        r"\b(?:double\s+click|click|press|tap)\b)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    ui_kind = (
        r"按钮|控件|输入框|文本框|输入栏|元素|选项|菜单项|菜单|复选框|"
        r"button|control|ui element|text field|textbox|input|menu item|menu|checkbox"
    )
    return bool(
        re.search(
            rf"(?:{ui_kind}).{{0,16}}(?:在哪|在哪里|哪儿|哪里|位置|坐标|可见|看得到|能看到|有吗|有没有)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"(?:在哪|在哪里|哪儿|哪里|位置|坐标|可见|看得到|能看到|有哪些|有什么|哪些).{{0,16}}(?:{ui_kind})",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bwhere\s+(?:is|are)\b.{0,32}\b"
            r"(?:button|control|ui element|text field|textbox|input|menu item|menu|checkbox)\b",
            lowered,
        )
        or re.search(
            r"\b(?:can|could)\s+you\s+(?:see|find|locate)\b.{0,32}\b"
            r"(?:button|control|ui element|text field|textbox|input|menu item|menu|checkbox)\b",
            lowered,
        )
    )


def _is_current_ui_text_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)"
            r".{0,8}(?:文字|文本|内容|正文)"
            r".{0,8}(?:是什么|是啥|有哪些|有什么|读取|读一下|查看|看看|识别)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:读取|阅读|读一下|读下|读一读|读|查看|看看|识别|提取|抓取|获取)"
            r".{0,8}(?:当前|现在|这个|前台|该)?(?:窗口|界面|屏幕|应用|app|ui)"
            r".{0,8}(?:文字|文本|内容|正文)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bread\b.{0,16}\b"
            r"(?:current|this|active|foreground)\s+(?:window|ui|interface|screen)\b"
            r"(?:.{0,16}\b(?:text|content)\b)?",
            lowered,
        )
        or re.search(
            r"\b(?:inspect|show|extract)\b.{0,16}\b"
            r"(?:current|this|active|foreground)\s+(?:window|ui|interface|screen)\b"
            r".{0,16}\b(?:text|content)\b",
            lowered,
        )
    )


def _app_scoped_ui_elements_tool_requests(text: str) -> list[dict[str, Any]]:
    ui_payload = _desktop_ui_elements_request(text)
    if ui_payload is None:
        return []
    if _is_current_ui_elements_request(text):
        return []
    app_name = _desktop_ui_elements_app_name(text)
    if not app_name:
        return []
    return [
        _request("app.focus", {"app_name": app_name}),
        _request("desktop.ui_elements", ui_payload),
    ]


def _is_current_ui_elements_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:你|您)?\s*(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|可以|能)?(?:直接)?"
            r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)?\s*"
            r"(?:当前|现在|这个|前台|该)\s*(?:应用|app|界面|窗口|屏幕)?\s*"
            r"(?:有哪些|有什么|有啥|有哪个|有哪几个|列出|列一下|显示|查看|看看|看一下|读取|识别|的)?\s*"
            r"(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:list|show|read|inspect|what|which)\b.{0,24}\b"
            r"(?:current|frontmost|foreground|this)\s+"
            r"(?:app|application|window|interface|screen|ui)\b",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
            r"(?:list|show|read|inspect)\s+(?:the\s+)?(?:visible|shown|available)\s+"
            r"(?:buttons|controls|ui elements|text fields)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _desktop_ui_elements_app_name(text: str) -> str:
    patterns = (
        r"\b(?:list|show|read|inspect)\s+(?:the\s+)?"
        r"(?:ui\s+elements|buttons|text\s+fields|controls)\s+(?:in|on|for|of)\s+(?P<app>[^.!?]+)",
        r"\b(?:what|which)\s+(?:buttons|controls|ui\s+elements|text\s+fields)\s+"
        r"(?:are\s+)?(?:visible|shown|available|there)?\s*(?:in|on|for|of)\s+(?P<app>[^.!?]+)",
        r"\bwhat\s+can\s+i\s+(?:click|press|use)\s+(?:in|on)\s+(?P<app>[^.!?]+)",
        r"\b(?:list|show|read|inspect)\s+(?P<app>[^.!?]+?)\s+"
        r"(?:ui\s+elements|buttons|text\s+fields|controls)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有哪些|有什么|有啥|有哪个|有哪几个)"
        r".{0,6}(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:列出|查看|看看|看一下|看下|显示|读取|识别)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:有哪些|有什么|有啥|有哪个|有哪几个)"
        r".{0,6}(?:控件|按钮|输入框|文本框|元素|ui|可点击|可操作)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        if _looks_like_generic_ui_scope(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name and not _looks_like_generic_app_open_target(raw_app):
            return app_name
    return ""


def _app_scoped_ui_action_tool_request(text: str) -> dict[str, Any] | None:
    click_payload = _app_scoped_click_ui_element_request(text)
    if click_payload:
        return _request("app.focus_and_click_ui_element", click_payload)
    type_payload = _app_scoped_type_into_ui_element_request(text)
    if type_payload:
        return _request("app.focus_and_type_into_ui_element", type_payload)
    return None


def _app_scoped_low_risk_foreground_action_tool_request(text: str) -> dict[str, Any] | None:
    for mode, raw_app, app_name, followup in _app_scoped_foreground_action_matches(text):
        if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
            continue
        if _known_music_app_name(raw_app) and _music_control_followup_action(followup):
            continue
        shortcut_action = (
            _finder_safe_shortcut_action(app_name, followup)
            or _app_command_or_preferences_shortcut_action(app_name, followup)
            or _app_default_new_shortcut_action(app_name, followup)
            or _app_followup_full_screen_shortcut_action(followup)
            or _desktop_safe_shortcut_action(followup)
        )
        if shortcut_action:
            return _request(
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": shortcut_action},
            )
        safe_scroll = _desktop_safe_scroll(followup)
        if safe_scroll:
            return _request(
                f"app.{mode}_and_safe_scroll",
                {"app_name": app_name, **safe_scroll},
            )
        safe_key = _app_followup_safe_key(followup) or _desktop_safe_key(f"按{followup}")
        if safe_key:
            return _request(
                f"app.{mode}_and_safe_key",
                {"app_name": app_name, **safe_key},
            )
    return None


def _app_command_palette_tool_requests(text: str) -> list[dict[str, Any]]:
    for mode, raw_app, app_name, followup in _app_scoped_foreground_action_matches(text):
        if (
            not app_name
            or _looks_like_window_target(raw_app)
            or _looks_like_common_path_target(raw_app)
        ):
            continue
        parsed = _app_command_palette_followup(app_name, followup)
        if not parsed:
            continue
        shortcut_action, typed_text, followup_requests = parsed
        requests = [
            _request(
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": shortcut_action},
            ),
            _request("desktop.safe_type_text", {"text": typed_text}),
        ]
        requests.extend(followup_requests)
        return requests
    return []


def _app_command_palette_followup(
    app_name: str,
    followup: str,
) -> tuple[str, str, list[dict[str, Any]]] | None:
    shortcut_action = _app_command_or_preferences_shortcut_action(app_name, "命令面板")
    if not shortcut_action:
        return None
    parsed = _command_palette_followup_text_and_actions(followup)
    if not parsed:
        return None
    command_text, followup_requests = parsed
    if not command_text:
        return None
    return shortcut_action, command_text, followup_requests


def _command_palette_followup_text_and_actions(
    value: str,
) -> tuple[str, list[dict[str, Any]]] | None:
    text = _strip_query(value)
    if not text:
        return None
    if _is_bare_command_palette_open_followup(text):
        return None
    palette = r"(?:命令面板|指令面板|命令\s*palette|command\s+palette)"
    type_verb = r"(?:输入|打字|键入|敲入|打入|打上|搜索|查找|找|type|enter|search|find)"
    run_verb = r"(?:执行|运行|打开|启动|run|execute|open|launch)"
    patterns: tuple[tuple[str, bool], ...] = (
        (
            rf"^(?:打开|调出|唤起|显示|open|show)?\s*{palette}"
            rf"\s*(?:(?:并且|并|然后|之后|后(?!退)|再|and\s+then|and|then)\s*)?"
            rf"{type_verb}\s*(?P<text>[^。！？!?]+)$",
            False,
        ),
        (
            rf"^{palette}"
            rf"\s*(?:(?:里|中|内|上|里面|里边|in|from|with)\s*)?"
            rf"{type_verb}\s*(?P<text>[^。！？!?]+)$",
            False,
        ),
        (
            rf"^(?:打开|调出|唤起|显示|open|show)?\s*{palette}"
            rf"\s*(?:(?:并且|并|然后|之后|后(?!退)|再|and\s+then|and|then)\s*)?"
            rf"{run_verb}\s*(?:命令|指令|command)?\s*(?P<text>[^。！？!?]+)$",
            True,
        ),
        (
            rf"^(?:{run_verb})\s*(?:命令|指令|command)?\s*(?P<text>[^。！？!?]+)$",
            True,
        ),
        (
            rf"^{palette}\s+(?:run|execute|open|launch)\s+(?P<text>[^.!?]+)$",
            True,
        ),
    )
    for pattern, default_submit in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_text = str(match.group("text") or "").strip()
        command_text = _strip_command_palette_typed_text(raw_text)
        if command_text:
            return (
                command_text,
                _command_palette_typed_text_followup_requests(
                    raw_text,
                    default_submit=default_submit,
                ),
            )
    return None


def _is_bare_command_palette_open_followup(value: str) -> bool:
    phrase = _normalize_named_hotkey_phrase(value)
    return phrase in {
        "命令面板",
        "打开命令面板",
        "指令面板",
        "打开指令面板",
        "命令palette",
        "commandpalette",
        "opencommandpalette",
        "showcommandpalette",
    }


def _strip_command_palette_typed_text(value: str) -> str:
    text = _strip_typed_text(value)
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?:(?:按一下|按下|按|发送|触发)\s*)?"
        r"(?:esc|escape|tab|home|end|page\s*up|page\s*down|pageup|pagedown|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|arrow\s+up|arrow\s+down|"
        r"arrow\s+left|arrow\s+right|up|down|left|right|"
        r"退出|取消|制表键|制表|向上箭头|往上箭头|朝上箭头|向下箭头|往下箭头|朝下箭头|"
        r"向左箭头|往左箭头|朝左箭头|向右箭头|往右箭头|朝右箭头|"
        r"上箭头|下箭头|左箭头|右箭头|上方向键|下方向键|左方向键|右方向键|"
        r"向上键|向下键|向左键|向右键|上|下|左|右|"
        r"上一页键|下一页键|上一页|下一页|home\s*键|end\s*键)"
        r"(?:\s*(?:\d+|[一二两三四五六七八九十])\s*(?:次|下))?"
        r"(?:\s*(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?:按|敲|执行|确认)?(?:回车|enter|return|确认|确定))?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and\s+then|then|and)\s*"
        r"(?:(?:press|hit|send)\s+)?(?:the\s+)?"
        r"(?:esc|escape|tab|home|end|page\s*up|page\s*down|pageup|pagedown|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|arrow\s+up|arrow\s+down|"
        r"arrow\s+left|arrow\s+right|up|down|left|right)"
        r"(?:\s+\d+\s*(?:times?)?)?"
        r"(?:\s+(?:and\s+then|then|and)\s*(?:(?:press|hit)\s*)?"
        r"(?:enter|return|confirm|ok))?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?:选择|选中|打开|点击|点一下|点按|单击|点|进入|访问|执行|确认)?\s*"
        r"(?:搜索结果|结果|命令|指令|条目|项目)?(?:中|里|里的|的)?\s*"
        r"(?:第?一个|第一条|首个|第1个|第1条|1)\s*"
        r"(?:搜索结果|结果|命令|指令|条目|项目)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and\s+then|then|and)\s*"
        r"(?:select|choose|open|click|run|execute|confirm)\s+"
        r"(?:the\s+)?(?:first|1st)\s+(?:result|item|command|match)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|后(?!退)|再|接着)\s*"
        r"(?:按|敲|执行|确认)?(?:回车|enter|return|确认|确定)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and\s+then|then|and)\s*(?:(?:press|hit)\s*)?"
        r"(?:enter|return|confirm|ok)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return _strip_query(text)


def _command_palette_typed_text_followup_requests(
    value: str,
    *,
    default_submit: bool,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    safe_key = _command_palette_safe_key_followup(value)
    if safe_key:
        requests.append(_request("desktop.safe_key", safe_key))
    if (
        default_submit
        or _command_palette_text_has_submit_followup(value)
        or _command_palette_text_selects_first_result(value)
    ):
        requests.append(_request("desktop.submit_foreground", {"action": "confirm"}))
    return requests


def _command_palette_safe_key_followup(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    patterns = (
        r"(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?P<key_cn>(?:(?:按一下|按下|按|发送|触发)\s*)?"
        r"(?:esc|escape|tab|home|end|page\s*up|page\s*down|pageup|pagedown|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|arrow\s+up|arrow\s+down|"
        r"arrow\s+left|arrow\s+right|up|down|left|right|"
        r"退出|取消|制表键|制表|向上箭头|往上箭头|朝上箭头|向下箭头|往下箭头|朝下箭头|"
        r"向左箭头|往左箭头|朝左箭头|向右箭头|往右箭头|朝右箭头|"
        r"上箭头|下箭头|左箭头|右箭头|上方向键|下方向键|左方向键|右方向键|"
        r"向上键|向下键|向左键|向右键|上|下|左|右|"
        r"上一页键|下一页键|上一页|下一页|home\s*键|end\s*键)"
        r"(?:\s*(?:\d+|[一二两三四五六七八九十])\s*(?:次|下))?)"
        r"(?:\s*(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?:按|敲|执行|确认)?(?:回车|enter|return|确认|确定))?$",
        r"(?:and\s+then|then|and)\s*"
        r"(?P<key_en>(?:(?:press|hit|send)\s+)?(?:the\s+)?"
        r"(?:esc|escape|tab|home|end|page\s*up|page\s*down|pageup|pagedown|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|arrow\s+up|arrow\s+down|"
        r"arrow\s+left|arrow\s+right|up|down|left|right)"
        r"(?:\s+\d+\s*(?:times?)?)?)"
        r"(?:\s+(?:and\s+then|then|and)\s*(?:(?:press|hit)\s*)?"
        r"(?:enter|return|confirm|ok))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        key_phrase = str(
            match.groupdict().get("key_cn") or match.groupdict().get("key_en") or ""
        ).strip()
        payload = _desktop_safe_key(key_phrase)
        if payload:
            return payload
    return None


def _command_palette_text_has_submit_followup(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        re.search(
            r"(?:并且|并|然后|之后|后(?!退)|再|接着)\s*"
            r"(?:按|敲|执行|确认)?(?:回车|enter|return|确认|确定)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:(?:press|hit)\s*)?"
            r"(?:enter|return|confirm|ok)$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _command_palette_text_selects_first_result(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        re.search(
            r"(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
            r"(?:选择|选中|打开|点击|点一下|点按|单击|点|进入|访问|执行|确认)\s*"
            r"(?:搜索结果|结果|命令|指令|条目|项目)?(?:中|里|里的|的)?\s*"
            r"(?:第?一个|第一条|首个|第1个|第1条|1)\s*"
            r"(?:搜索结果|结果|命令|指令|条目|项目)?$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*"
            r"(?:select|choose|open|click|run|execute|confirm)\s+"
            r"(?:the\s+)?(?:first|1st)\s+(?:result|item|command|match)$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_command_palette_followup(value: str) -> bool:
    text = _strip_query(value)
    if not text:
        return False
    return bool(
        re.search(
            r"(?:命令面板|指令面板|命令\s*palette|command\s+palette)",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^(?:执行|运行|run|execute)\s*(?:命令|指令|command)?\s+\S+",
            text,
            flags=re.IGNORECASE,
        )
    )


def _app_scoped_low_risk_action_should_not_fallback(request: dict[str, Any]) -> bool:
    tool = str(request.get("tool") or "")
    if tool.endswith("_and_safe_key") or tool.endswith("_and_safe_scroll"):
        return True
    if not tool.endswith("_and_safe_shortcut"):
        return False
    payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    return str(payload.get("action") or "") in {
        "command_palette",
        "obsidian_command_palette",
        "preferences",
    }


def _app_scoped_hotkey_tool_request(text: str) -> dict[str, Any] | None:
    for mode, raw_app, app_name, followup in _app_scoped_foreground_action_matches(text):
        if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
            continue
        if _known_music_app_name(raw_app) and _music_control_followup_action(followup):
            continue
        if not _looks_like_press_key_without_ui_kind(followup):
            continue
        hotkey = _desktop_hotkey(followup)
        if not hotkey:
            continue
        return _request(f"app.{mode}_and_hotkey", {"app_name": app_name, **hotkey})
    return None


def _app_scoped_foreground_action_matches(text: str) -> list[tuple[str, str, str, str]]:
    clean = _strip_query(text)
    if not clean:
        return []
    candidates: list[tuple[str, str]] = []
    patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?(?P<body>.+)$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<body>.+)$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|到|给|向|用|通过)\s*(?P<body>.+)$",
        ),
        (
            "open",
            r"^(?:please\s+)?(?:open|launch|start)\s+(?P<body>.+)$",
        ),
        (
            "focus",
            r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up|in|on|with|using)\s+(?P<body>.+)$",
        ),
    )
    for mode, pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        candidates.append((mode, _strip_query(match.group("body"))))
    candidates.append(("focus", clean))

    matches: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for mode, body in candidates:
        split = _known_app_prefix_split(body)
        if not split:
            continue
        raw_app, app_name, followup = split
        if not raw_app or not app_name or not followup:
            continue
        item = (mode, raw_app, app_name, followup)
        if item not in seen:
            seen.add(item)
            matches.append(item)
    return matches


def _looks_like_press_key_without_ui_kind(value: str) -> bool:
    text = _strip_query(value)
    if re.search(
        r"(?:按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框|"
        r"button|control|element|field|input|menu|checkbox)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    return bool(
        re.match(
            r"^(?:按一下|按下|按|发送|触发)\s*",
            text,
            flags=re.IGNORECASE,
        )
    )


def _app_scoped_safe_shortcut_tool_request(text: str) -> dict[str, Any] | None:
    shortcut = _app_scoped_safe_shortcut_request(text)
    if not shortcut:
        return None
    mode = str(shortcut.pop("mode"))
    return _request(f"app.{mode}_and_safe_shortcut", shortcut)


def _app_prefix_safe_scroll_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    safe_scroll = _desktop_safe_scroll(followup)
    if not safe_scroll:
        return None
    return _request(
        "app.focus_and_safe_scroll",
        {"app_name": app_name, **safe_scroll},
    )


def _app_prefix_safe_key_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    if _known_music_app_name(raw_app) and _music_control_followup_action(followup):
        return None
    safe_key = _app_followup_safe_key(followup)
    if not safe_key:
        return None
    return _request(
        "app.focus_and_safe_key",
        {"app_name": app_name, **safe_key},
    )


def _app_open_or_focus_safe_key_tool_request(text: str) -> dict[str, Any] | None:
    payload = _app_open_or_focus_foreground_action_request(text)
    if not payload:
        return None
    tool = str(payload.get("tool") or "").strip()
    if tool not in {"app.open_and_safe_key", "app.focus_and_safe_key"}:
        return None
    raw_input = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    return _request(tool, dict(raw_input))


def _app_prefix_safe_click_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    safe_click = _desktop_safe_click(followup)
    if not safe_click:
        return None
    return _request(
        "app.focus_and_safe_click",
        {"app_name": app_name, **safe_click},
    )


def _app_prefix_click_ui_element_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    if (
        _app_followup_safe_key(followup)
        or _desktop_safe_shortcut_action(followup)
        or _desktop_hotkey(followup)
    ):
        return None
    click_payload = _desktop_click_ui_element(followup, require_context=False)
    if not click_payload:
        return None
    return _request(
        "app.focus_and_click_ui_element",
        {"app_name": app_name, **click_payload},
    )


def _app_open_or_focus_click_submit_tool_requests(text: str) -> list[dict[str, Any]]:
    matches: list[tuple[str, str, str, str]] = []
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        matches.append(shorthand_match)
    direct_split = _known_app_prefix_split(text)
    if direct_split:
        raw_app, app_name, followup = direct_split
        matches.append(("focus", raw_app, app_name, followup))
    scoped_split = _known_app_prefix_split(_strip_app_search_scope_prefix(text))
    if scoped_split:
        raw_app, app_name, followup = scoped_split
        matches.append(("focus", raw_app, app_name, followup))
    for mode, raw_app, app_name, followup in matches:
        if (
            not app_name
            or app_name in _BROWSER_APP_NAMES
            or _looks_like_window_target(raw_app)
            or _looks_like_common_path_target(raw_app)
        ):
            continue
        parsed = _click_ui_element_followup_and_submit_action(followup)
        if not parsed:
            continue
        clean_followup, submit_action = parsed
        click_payload = _desktop_click_ui_element(clean_followup, require_context=False)
        if not click_payload:
            continue
        return [
            _request(
                f"app.{mode}_and_click_ui_element",
                {"app_name": app_name, **click_payload},
            ),
            _request("desktop.submit_foreground", {"action": submit_action}),
        ]
    return []


def _click_ui_element_followup_and_submit_action(value: str) -> tuple[str, str] | None:
    text = _strip_query(value)
    if not text:
        return None
    patterns = (
        r"^(?P<body>.+?)\s*(?:然后|并且|并|之后|随后|再|接着)\s*"
        r"(?P<submit>(?:(?:按|按下|敲|敲下)\s*)?(?:回车|enter|return)(?:键)?"
        r"(?:\s*(?:确认|确定|提交|发送|发出))?|确认|确定|发送|发出|提交)$",
        r"^(?P<body_en>.+?)\s+(?:and\s+then|then|and)\s*"
        r"(?P<submit_en>(?:(?:press|hit)\s*)?(?:enter|return)"
        r"(?:\s+to\s+(?:confirm|ok|submit|send|post))?|confirm|ok|send|submit|post)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        body = str(match.groupdict().get("body") or match.groupdict().get("body_en") or "").strip()
        submit_text = str(
            match.groupdict().get("submit") or match.groupdict().get("submit_en") or ""
        ).strip()
        submit_action = _desktop_submit_foreground_action(submit_text)
        if not submit_action and _looks_like_bare_return_submit_phrase(submit_text):
            submit_action = "confirm"
        if body and submit_action:
            return _strip_query(body), submit_action
    return None


def _looks_like_bare_return_submit_phrase(value: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    return compact in {
        "回车",
        "按回车",
        "按下回车",
        "敲回车",
        "敲下回车",
        "enter",
        "return",
        "pressenter",
        "hitenter",
        "pressreturn",
        "hitreturn",
    }


def _app_prefix_safe_type_text_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    if (
        _app_followup_safe_key(followup)
        or _desktop_safe_shortcut_action(followup)
        or _desktop_hotkey(followup)
    ):
        return None
    typed_text = _app_followup_safe_type_text(followup)
    if not typed_text:
        return None
    return _request(
        "app.focus_and_safe_type_text",
        {"app_name": app_name, "text": typed_text},
    )


def _app_prefix_safe_type_text_tool_requests(text: str) -> list[dict[str, Any]]:
    request = _app_prefix_safe_type_text_tool_request(text)
    if not request:
        return []
    split = _known_app_prefix_split(text)
    if not split:
        return [request]
    _raw_app, _app_name, followup = split
    return _safe_type_text_followup_tool_requests(request, followup)


def _app_prefix_window_management_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    if _is_app_prefix_hide_followup(followup):
        return _request("app.hide", {"app_name": app_name})
    if _is_app_prefix_minimize_followup(followup):
        return _request("app.minimize", {"app_name": app_name})
    return None


def _app_open_or_focus_window_management_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _app_open_or_focus_window_management_request(text)
    if not parsed:
        return []
    mode, app_name, action = parsed
    action_tool = {
        "hide": "app.hide",
        "minimize": "app.minimize",
        "show": "app.show",
    }.get(action)
    if not action_tool:
        return []
    if action == "show":
        return [_request(action_tool, {"app_name": app_name})]
    return [
        _request(f"app.{mode}", {"app_name": app_name}),
        _request(action_tool, {"app_name": app_name}),
    ]


def _app_open_or_focus_window_management_request(text: str) -> tuple[str, str, str] | None:
    patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?"
            r"(?P<app>[^。！？!?，,]+?)\s*(?:起来)?\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*"
            r"(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
        ),
        (
            "open",
            r"^(?:please\s+)?(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+"
            r"(?:(?:and\s+then|and|then)\s+)(?P<followup>.+)$",
        ),
        (
            "focus",
            r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up)\s+"
            r"(?P<app>[^.!?]+?)\s+(?:(?:and\s+then|and|then)\s+)(?P<followup>.+)$",
        ),
    )
    for mode, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        followup = _strip_known_app_followup_prefix(match.group("followup"))
        if (
            not raw_app
            or not followup
            or _looks_like_window_target(raw_app)
            or _looks_like_common_path_target(raw_app)
            or _looks_like_current_app_scope(raw_app)
            or _looks_like_generic_app_open_target(raw_app)
        ):
            continue
        app_name = _normalize_app_name(raw_app)
        action = _app_window_management_followup_action(followup)
        if app_name and action:
            return mode, app_name, action
    return None


def _app_window_management_followup_action(value: str) -> str:
    if _is_app_prefix_hide_followup(value):
        return "hide"
    if _is_app_prefix_minimize_followup(value):
        return "minimize"
    if _is_app_prefix_show_followup(value):
        return "show"
    return ""


def _is_app_prefix_show_followup(value: str) -> bool:
    text = _strip_query(value)
    if not text:
        return False
    return bool(
        re.fullmatch(
            r"(?:显示|显示一下|显示出来|调出来|叫出来|还原|恢复|取消隐藏|"
            r"show(?:\s+(?:it|this\s+app))?|restore(?:\s+(?:it|this\s+app))?|"
            r"unhide(?:\s+(?:it|this\s+app))?)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _app_open_or_focus_close_window_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _app_open_or_focus_close_window_request(text)
    if not parsed:
        return []
    mode, app_name = parsed
    return [
        _request(f"app.{mode}", {"app_name": app_name}),
        _request("desktop.close_window", {}),
    ]


def _app_open_or_focus_close_window_request(text: str) -> tuple[str, str] | None:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, raw_app, app_name, followup = shorthand_match
        if (
            _app_followup_close_window_request(followup)
            and not _looks_like_window_target(raw_app)
            and not _looks_like_common_path_target(raw_app)
        ):
            return mode, app_name

    prefix_split = _known_app_prefix_split(text)
    if prefix_split:
        raw_app, app_name, followup = prefix_split
        if (
            _app_followup_close_window_request(followup)
            and not _looks_like_window_target(raw_app)
            and not _looks_like_common_path_target(raw_app)
        ):
            return "focus", app_name

    preposed = _app_preposed_close_window_request(text)
    if preposed:
        return preposed
    return None


def _app_preposed_close_window_request(text: str) -> tuple[str, str] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*"
        r"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)\s*"
        r"(?:关闭|关掉|关上|关(?:一下|下|了)?)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:关闭|关掉|关上|关(?:一下|下|了)?)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:的)?\s*"
        r"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)$",
        r"^(?:please\s+)?(?:close|dismiss)\s+(?P<app>[^.!?]+?)\s+window$",
    )
    for pattern in patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        if (
            not raw_app
            or _looks_like_window_target(raw_app)
            or _looks_like_current_app_scope(raw_app)
            or _looks_like_common_path_target(raw_app)
            or _normalize_site_name(raw_app)
            or _looks_like_composite_action_target(raw_app)
        ):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return "focus", app_name
    return None


def _app_followup_close_window_request(value: str) -> bool:
    text = _strip_query(value)
    if not text:
        return False
    return bool(
        _is_close_current_window_request(text)
        or re.fullmatch(
            r"(?:关闭|关掉|关上|关(?:一下|下|了)?)\s*(?:窗口|window)",
            text,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            r"(?:close|dismiss)\s+(?:the\s+)?window",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_app_prefix_hide_followup(value: str) -> bool:
    text = _strip_query(value)
    if not text:
        return False
    return bool(
        re.fullmatch(
            r"(?:隐藏|隐藏一下|隐藏下|藏起来|收起|收起来|收一下|收下|hide(?:\s+(?:it|this\s+app))?)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_app_prefix_minimize_followup(value: str) -> bool:
    text = _strip_query(value)
    if not text:
        return False
    return bool(
        re.fullmatch(
            r"(?:最小化|最小化一下|最小化下|窗口最小化|把窗口最小化|最小化窗口|minimi[sz]e(?:\s+(?:it|this\s+window))?)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _app_followup_safe_key(value: str) -> dict[str, Any] | None:
    safe_key = _desktop_safe_key(value)
    if safe_key:
        return safe_key
    text = _strip_query(value)
    if not _looks_like_bare_safe_key_followup(text):
        return None
    return _desktop_safe_key(f"按{text}")


def _looks_like_bare_safe_key_followup(value: str) -> bool:
    count = r"(?:\d+|[一二两三四五六七八九十])\s*(?:次|下)\s*"
    key = (
        r"(?:esc|escape|tab|home|end|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|"
        r"arrow\s+up|arrow\s+down|arrow\s+left|arrow\s+right|"
        r"制表键|制表|向上箭头|往上箭头|朝上箭头|向下箭头|往下箭头|朝下箭头|"
        r"向左箭头|往左箭头|朝左箭头|向右箭头|往右箭头|朝右箭头|"
        r"上箭头|下箭头|左箭头|右箭头|向上键|向下键|向左键|向右键|"
        r"上一页键|下一页键|home\s*键|end\s*键)"
    )
    return bool(
        re.fullmatch(
            rf"(?:{count})?{key}(?:\s*(?:键|一下|下))?",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _app_scoped_safe_shortcut_request(text: str) -> dict[str, Any] | None:
    if _looks_like_postposed_clipboard_copy_request(text):
        return None
    postposed_open = _app_postposed_open_followup_match(text)
    if postposed_open:
        mode, _raw_app, app_name, followup = postposed_open
        action = (
            _finder_safe_shortcut_action(app_name, followup)
            or _app_command_or_preferences_shortcut_action(app_name, followup)
            or _desktop_safe_shortcut_action(followup)
        )
        if action:
            return {"mode": mode, "app_name": app_name, "action": action}

    prefix_split = _known_app_prefix_split(text)
    if prefix_split:
        raw_app, app_name, followup = prefix_split
        if not _looks_like_window_target(raw_app) and not _looks_like_common_path_target(raw_app):
            action = (
                _finder_safe_shortcut_action(app_name, followup)
                or _app_command_or_preferences_shortcut_action(app_name, followup)
                or _app_followup_full_screen_shortcut_action(followup)
                or _desktop_safe_shortcut_action(followup)
            )
            if action:
                return {"mode": "focus", "app_name": app_name, "action": action}

    shortcut_pattern = (
        r"(?:复制(?:一下|下)?(?:选中(?:的)?(?:内容|文字))?|"
        r"(?:把|将)?(?:剪贴板|粘贴板)(?:内容)?粘贴(?:一下|下)?|"
        r"(?:当前输入框|当前文本框|当前输入栏|前台|当前窗口|前台输入框|前台文本框|前台输入栏)"
        r"粘贴(?:一下|下)?|"
        r"粘贴(?:一下|下)?(?:(?:到|进|在)?(?:这(?:里)?|当前输入框|输入框|当前窗口|前台))?|"
        r"全选|撤销|重做|"
        r"(?:浏览器|网页|当前网页|当前页)刷新(?:一下|下)?|"
        r"刷新(?:一下|下)?(?:页面|当前页|当前网页|网页)?|返回上一页|回到上一页|"
        r"重新打开(?:(?:刚刚|刚|最近|上次|上个|上一个)关闭的|关闭的)标签页|"
        r"恢复(?:(?:刚刚|刚|最近|上次|上个|上一个)关闭的|关闭的)标签页|"
        r"网页后退(?:一下|下|一次)?|浏览器后退(?:一下|下|一次)?|"
        r"后退一页|后退(?:一下|下|一次)?|前进一页|"
        r"网页前进(?:一下|下|一次)?|浏览器前进(?:一下|下|一次)?|"
        r"前进(?:一下|下|一次)?|"
        r"查找(?:一下|下)?|打开查找(?:框)?(?:一下|下)?|"
        r"打开搜索框(?:一下|下)?|页面(?:内|里)?查找(?:一下|下)?|"
        r"当前页查找(?:一下|下)?|"
        r"命令面板|打开命令面板|指令面板|打开指令面板|命令 palette|command\s+palette|"
        r"偏好设置|打开偏好设置|应用设置|打开应用设置|设置|打开设置|preferences?|settings?|"
        r"新建标签页|新标签页|打开新标签页|开新标签页|开一个新标签页|"
        r"新建窗口|新窗口|打开新窗口|开新窗口|开一个新窗口|"
        r"新建文档|新文档|新建文件|新文件|开新文档|开一个新文档|开新文件|开一个新文件|"
        r"新建表格|新表格|新建工作簿|新工作簿|"
        r"新建演示文稿|新演示文稿|新建幻灯片|新幻灯片|新建ppt|新ppt|"
        r"新建笔记|新建一个笔记|新建一条笔记|新建一篇笔记|新笔记|"
        r"新建备忘录|新建一个备忘录|新建一条备忘录|新建一篇备忘录|新备忘录|"
        r"新建日程|新建一个日程|新建一条日程|新建日历事件|新建一个日历事件|新日程|"
        r"新建事件|新建一个事件|新事件|"
        r"关闭(?:当前|这个|浏览器)?标签页|关掉(?:当前|这个|浏览器)?标签页|"
        r"切(?:换)?到(?:下一个|下个|下一|上一个|上个|上一)标签页|"
        r"(?:下一个|下个|下一|上一个|上个|上一)标签页|"
        r"最大化(?:一下|下)?|(?:窗口|当前窗口)?全屏(?:一下|下)?|进入全屏(?:模式)?(?:一下|下)?|"
        r"copy|paste|select\s+all|undo|redo|refresh|reload|reopen\s+(?:the\s+)?(?:last\s+)?closed\s+tab|"
        r"restore\s+(?:the\s+)?(?:last\s+)?closed\s+tab|close\s+(?:the\s+)?(?:current\s+)?tab|"
        r"(?:switch\s+to\s+)?next\s+tab|(?:switch\s+to\s+)?previous\s+tab|"
        r"go\s+back|back|"
        r"go\s+forward|forward|find|maximize|fullscreen|full\s+screen|enter\s+full\s+screen|"
        r"new\s+tab|new\s+window|new\s+document|"
        r"new\s+file|new\s+workbook|new\s+spreadsheet|new\s+presentation|new\s+slide|"
        r"new\s+note|new\s+event|new\s+calendar\s+event|"
        r"make\s+a\s+new\s+document|create\s+a\s+new\s+document|"
        r"make\s+a\s+new\s+file|create\s+a\s+new\s+file|"
        r"make\s+a\s+new\s+workbook|create\s+a\s+new\s+workbook|"
        r"make\s+a\s+new\s+spreadsheet|create\s+a\s+new\s+spreadsheet|"
        r"make\s+a\s+new\s+presentation|create\s+a\s+new\s+presentation|"
        r"make\s+a\s+new\s+note|create\s+a\s+new\s+note|"
        r"make\s+a\s+new\s+event|create\s+a\s+new\s+event|"
        r"make\s+a\s+new\s+calendar\s+event|create\s+a\s+new\s+calendar\s+event)"
    )
    patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
            rf"(?:起来)?\s*(?:(?:并|然后|后|之后|再)\s*)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "open",
            rf"^(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+"
            rf"(?:(?:and\s+then|then|and)\s+)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)\s*"
            rf"(?:(?:并|然后|后|之后|再)\s*)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            rf"^(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+?)\s+"
            rf"(?:(?:and\s+then|then|and)\s+)?(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<app>[^。！？!?，,\s]+?)\s*(?:的|里|中|内|上)?\s*"
            rf"(?:起来)?\s*(?P<action>{shortcut_pattern})$",
        ),
        (
            "focus",
            rf"^(?P<app>[^.!?]+?)\s+(?P<action>{shortcut_pattern})$",
        ),
    )
    for mode, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if re.search(r"(?:剪贴板|粘贴板|clipboard)", raw_app, flags=re.IGNORECASE):
            continue
        if re.sub(r"[\s._-]+", "", str(raw_app or "").strip().lower()) in {"switchto", "switch"}:
            continue
        raw_app_compact = re.sub(r"[\s._-]+", "", str(raw_app or "").strip().lower())
        raw_action = str(match.group("action") or "")
        if raw_app_compact in {"把", "将"} and re.search(
            r"(?:剪贴板|粘贴板|clipboard)",
            raw_action,
            flags=re.IGNORECASE,
        ):
            continue
        if mode == "focus" and re.match(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|运行|拉起|开启|开)",
            text,
        ):
            continue
        app_name = _normalize_app_scoped_ui_action_app(raw_app)
        if not app_name and mode == "open":
            compact = re.sub(r"[\s._-]+", "", _strip_app_name(raw_app).lower())
            if compact in _APP_ALIASES:
                app_name = _normalize_app_name(raw_app)
        action = (
            _finder_safe_shortcut_action(app_name, match.group("action"))
            or _app_command_or_preferences_shortcut_action(app_name, match.group("action"))
            or _app_followup_full_screen_shortcut_action(match.group("action"))
            or _desktop_safe_shortcut_action(match.group("action"))
        )
        if app_name and action:
            return {"mode": mode, "app_name": app_name, "action": action}
    return None


def _app_followup_full_screen_shortcut_action(value: str) -> str:
    text = _strip_query(value)
    if not text:
        return ""
    lowered = text.lower()
    if re.search(r"(?:音量|声音|volume|sound|图片|image|photo|字号|font|zoom)", lowered):
        return ""
    if re.fullmatch(
        r"(?:最大化|全屏|进入全屏|进入全屏模式|窗口最大化|窗口全屏|当前窗口最大化|当前窗口全屏)"
        r"(?:一下|下)?",
        text,
        flags=re.IGNORECASE,
    ):
        return "toggle_full_screen"
    if re.fullmatch(
        r"(?:maximize|fullscreen|full\s*screen|enter\s+full\s*screen)(?:\s+(?:window|app|application))?",
        lowered,
        flags=re.IGNORECASE,
    ):
        return "toggle_full_screen"
    return ""


def _finder_safe_shortcut_action(app_name: str, followup: str) -> str:
    return (
        _finder_quick_look_shortcut_action(app_name, followup)
        or _finder_new_folder_shortcut_action(app_name, followup)
        or _finder_rename_selected_shortcut_action(app_name, followup)
        or _finder_parent_folder_shortcut_action(app_name, followup)
        or _finder_get_info_shortcut_action(app_name, followup)
        or _finder_copy_selected_shortcut_action(app_name, followup)
        or _finder_special_location_shortcut_action(app_name, followup)
    )


def _finder_special_location_tool_request(text: str) -> dict[str, Any] | None:
    action = _finder_special_location_shortcut_action("Finder", text)
    if not action:
        return None
    phrase = _normalize_named_hotkey_phrase(text)
    if action == "finder_network" and phrase in {
        "网络",
        "打开网络",
        "启动网络",
        "显示网络",
        "network",
        "opennetwork",
        "launchnetwork",
        "shownetwork",
    }:
        return None
    open_prefixes = (
        "打开finder",
        "启动finder",
        "显示finder",
        "openfinder",
        "launchfinder",
        "showfinder",
    )
    focus_finder = phrase.startswith("finder") and not phrase.startswith(open_prefixes)
    tool = "app.focus_and_safe_shortcut" if focus_finder else "app.open_and_safe_shortcut"
    return _request(tool, {"app_name": "Finder", "action": action})


def _finder_special_location_shortcut_action(app_name: str, followup: str) -> str:
    if str(app_name or "").strip() != "Finder":
        return ""
    phrase = _normalize_named_hotkey_phrase(followup)
    variants = {phrase}
    for prefix in (
        "打开finder里的",
        "打开finder的",
        "启动finder里的",
        "显示finder里的",
        "openfinder",
        "launchfinder",
        "showfinder",
        "finder打开",
        "finder显示",
        "finderopen",
        "findershow",
        "finder里的",
        "finder的",
        "finder",
        "打开",
        "启动",
        "显示",
        "open",
        "launch",
        "show",
    ):
        if phrase.startswith(prefix):
            stripped = phrase[len(prefix) :].strip()
            if stripped:
                variants.add(stripped)
    if variants & {"隔空投送", "airdrop"}:
        return "finder_airdrop"
    if variants & {"网络位置", "网络", "networklocation", "network"}:
        return "finder_network"
    if variants & {
        "最近使用",
        "最近项目",
        "最近使用项目",
        "最近",
        "recents",
        "recentitems",
        "recentfiles",
    }:
        return "finder_recents"
    return ""


def _finder_quick_look_shortcut_action(app_name: str, followup: str) -> str:
    if str(app_name or "").strip() != "Finder":
        return ""
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "空格",
        "空格键",
        "按空格",
        "按空格键",
        "按一下空格",
        "按一下空格键",
        "按下空格",
        "敲空格",
        "敲一下空格",
        "space",
        "pressspace",
        "hitspace",
        "quicklook",
        "preview",
        "快速查看",
        "快速预览",
        "预览",
        "预览选中项",
        "预览选中文件",
        "快速查看选中项",
        "快速查看选中文件",
    }:
        return "finder_quick_look"
    return ""


def _finder_get_info_shortcut_action(app_name: str, followup: str) -> str:
    if str(app_name or "").strip() != "Finder":
        return ""
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "显示简介",
        "查看简介",
        "打开简介",
        "显示文件简介",
        "查看文件简介",
        "打开文件简介",
        "显示选中文件简介",
        "查看选中文件简介",
        "显示选中项简介",
        "查看选中项简介",
        "getinfo",
        "showinfo",
        "fileinfo",
        "showfileinfo",
        "getfileinfo",
        "getselectedinfo",
        "showselectedinfo",
    }:
        return "finder_get_info"
    return ""


def _finder_new_folder_shortcut_action(app_name: str, followup: str) -> str:
    if str(app_name or "").strip() != "Finder":
        return ""
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "新建文件夹",
        "新文件夹",
        "新建一个文件夹",
        "创建文件夹",
        "创建一个文件夹",
        "新建目录",
        "新目录",
        "创建目录",
        "创建一个目录",
        "newfolder",
        "makeanewfolder",
        "createanewfolder",
        "makenewfolder",
        "createnewfolder",
        "newdirectory",
        "makeanewdirectory",
        "createanewdirectory",
        "makenewdirectory",
        "createnewdirectory",
    }:
        return "new_folder"
    return ""


def _finder_rename_selected_shortcut_action(app_name: str, followup: str) -> str:
    if str(app_name or "").strip() != "Finder":
        return ""
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "重命名",
        "重命名选中项",
        "重命名选中文件",
        "重命名选中的文件",
        "重命名当前选中项",
        "重命名当前选中文件",
        "重命名当前选中的文件",
        "重命名所选文件",
        "重命名所选项目",
        "rename",
        "renameitem",
        "renameselected",
        "renameselecteditem",
        "renameselectedfile",
        "renamecurrentselection",
    }:
        return "rename_selected"
    return ""


def _finder_parent_folder_shortcut_action(app_name: str, followup: str) -> str:
    if str(app_name or "").strip() != "Finder":
        return ""
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "上一级",
        "上一级文件夹",
        "上一级目录",
        "打开上一级",
        "打开上一级文件夹",
        "打开上一级目录",
        "回到上一级",
        "回到上一级文件夹",
        "回到上一级目录",
        "回到上级目录",
        "返回上一级",
        "返回上一级文件夹",
        "返回上一级目录",
        "父文件夹",
        "父目录",
        "parentfolder",
        "openparentfolder",
        "goparentfolder",
        "gouponefolder",
        "uponefolder",
        "enclosingfolder",
        "openenclosingfolder",
    }:
        return "parent_folder"
    return ""


def _finder_copy_selected_shortcut_action(app_name: str, followup: str) -> str:
    if str(app_name or "").strip() != "Finder":
        return ""
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "复制选中项",
        "复制选中文件",
        "复制选中的文件",
        "复制当前选中项",
        "复制当前选中文件",
        "复制当前选中的文件",
        "复制所选文件",
        "复制所选项目",
        "copyselected",
        "copyselecteditem",
        "copyselectedfile",
        "copycurrentselection",
    }:
        return "copy"
    return ""


def _app_scoped_click_ui_element_request(text: str) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    text = _strip_query(text)
    postposed_payload = _app_scoped_postposed_click_ui_element_request(text)
    if postposed_payload:
        return postposed_payload
    if _looks_like_app_scoped_postposed_click(text):
        return None
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到|切到|切换到|聚焦|激活)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:里|中|内|上|的)?\s*"
        r"(?:(?P<double>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<label>[^。！？!?，,]+?)"
        r"(?P<kind>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double2>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<app2>[^。！？!?，,]+?)\s*的\s*"
        r"(?P<label2>[^。！？!?，,]+?)"
        r"(?P<kind2>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double3>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<app3>[^。！？!?，,\s]+)\s+"
        r"(?P<label3>[^。！？!?，,]+?)"
        r"(?P<kind3>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?P<verb_en>double\s+click|click|press|tap)\s+"
        r"(?:the\s+)?(?P<label_en>[^.!?]+?)"
        r"(?:\s+(?P<kind_en>button|control|element|field|input|text field|textbox|menu item|menu|checkbox))?"
        r"\s+(?:in|on)\s+(?:the\s+)?(?P<app_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _normalize_app_scoped_ui_action_app(
            groups.get("app")
            or groups.get("app2")
            or groups.get("app3")
            or groups.get("app_en")
            or ""
        )
        label = _strip_app_scoped_ui_action_target(
            groups.get("label")
            or groups.get("label2")
            or groups.get("label3")
            or groups.get("label_en")
            or ""
        )
        kind = (
            groups.get("kind")
            or groups.get("kind2")
            or groups.get("kind3")
            or groups.get("kind_en")
            or ""
        )
        verb = str(groups.get("verb_en") or "").strip().lower()
        if not app_name or not label or _looks_like_click_coordinate_label(label):
            continue
        role_filter = _desktop_ui_element_role_filter(kind)
        if not role_filter and verb == "press":
            role_filter = "button"
        return {
            "app_name": app_name,
            "target": label,
            "role_filter": role_filter,
            "limit": 80,
            "click_count": (
                2
                if (
                    groups.get("double")
                    or groups.get("double2")
                    or groups.get("double3")
                    or verb == "double click"
                )
                else 1
            ),
        }
    return None


def _app_scoped_postposed_click_ui_element_request(text: str) -> dict[str, Any] | None:
    for body in _app_scoped_postposed_click_bodies(text):
        split = _known_app_prefix_split(body)
        if not split:
            continue
        raw_app, app_name, followup = split
        if (
            not app_name
            or _looks_like_window_target(raw_app)
            or _looks_like_common_path_target(raw_app)
        ):
            continue
        payload = _postposed_click_ui_element_payload(followup)
        if payload:
            return {"app_name": app_name, **payload}
    return None


def _app_scoped_postposed_click_bodies(text: str) -> list[str]:
    clean = _strip_query(text)
    if not clean:
        return []
    bodies: list[str] = []
    scoped_match = re.search(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到|切到|切换到|聚焦|激活)\s*(?P<body>.+)$",
        clean,
        flags=re.IGNORECASE,
    )
    if scoped_match:
        bodies.append(_strip_query(scoped_match.group("body")))
    bodies.append(clean)
    return [body for index, body in enumerate(bodies) if body and body not in bodies[:index]]


def _postposed_click_ui_element_payload(followup: str) -> dict[str, Any] | None:
    clean = re.sub(
        r"^(?:里面|里边|里的|中的|内的|上的|里|中|内|上|的)\s*",
        "",
        _strip_query(followup),
    )
    match = re.search(
        r"^(?P<label>[^。！？!?，,]+?)"
        r"(?P<kind>按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)\s*"
        r"(?P<verb>双击|点击|点一下|点按|单击|点|按一下|按)"
        r"(?:一下|一次)?$",
        clean,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    label = _strip_app_scoped_ui_action_target(match.group("label") or "")
    if not label or _looks_like_click_coordinate_label(label):
        return None
    kind = str(match.group("kind") or "")
    verb = str(match.group("verb") or "").strip()
    return {
        "target": label,
        "role_filter": _desktop_ui_element_role_filter(kind),
        "limit": 80,
        "click_count": 2 if verb == "双击" else 1,
    }


def _looks_like_app_scoped_postposed_click(text: str) -> bool:
    kind = r"(?:按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框)"
    verb = r"(?:双击|点击|点一下|点按|单击|点|按一下|按)"
    return any(
        (
            (split := _known_app_prefix_split(body)) is not None
            and _postposed_click_ui_element_payload(split[2]) is not None
        )
        or bool(
            re.search(
                rf"^.+?(?:里面|里边|里的|中的|内的|上的|里|中|内|上|的)\s*"
                rf"[^。！？!?，,]+?{kind}\s*{verb}(?:一下|一次)?$",
                body,
                flags=re.IGNORECASE,
            )
        )
        for body in _app_scoped_postposed_click_bodies(text)
    )


def _app_scoped_type_into_ui_element_request(text: str) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    text = _strip_query(text)
    target_pattern = (
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search\s+field|search\s+box|search\s+bar|message\s+field|message\s+box|"
        r"chat\s+box|address\s+bar|text\s+field|textbox|input|field|"
        r"[^。！？!?，,]+?(?:输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"text\s+field|textbox|input|field|search\s+field|search\s+box|search\s+bar|"
        r"message\s+field|message\s+box|chat\s+box|address\s+bar))"
    )
    bare_target_pattern = (
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search\s+field|search\s+box|search\s+bar|message\s+field|message\s+box|"
        r"chat\s+box|address\s+bar|text\s+field|textbox|input|field)"
    )
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|给|向)\s*(?P<app>[^。！？!?，,]+)\s*(?:的|里|中|内|上)?\s*"
        rf"(?P<target>{target_pattern})(?:里|中|内|上)?\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?P<text>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<text2>[^。！？!?，,]+?)\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?:到|进|在)\s*"
        r"(?P<app2>[^。！？!?，,]+)\s*(?:的|里|中|内|上)?\s*"
        rf"(?P<target2>{target_pattern})$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<app3>[^。！？!?，,\s]+?)\s*(?:的|里|中|内|上)?\s*"
        rf"(?P<target3>{bare_target_pattern})(?:里|中|内|上)?\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?P<text3>[^。！？!?]+)$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:type|enter|input)\s+(?P<text_en>[^.!?]+?)\s+"
        r"(?:into|in|to)\s+(?:the\s+)?"
        rf"(?P<target_en>{target_pattern})\s+"
        r"(?:in|on)\s+(?:the\s+)?(?P<app_en>[^.!?]+)$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:type|enter|input)\s+(?P<text_en2>[^.!?]+?)\s+"
        r"(?:into|in|to)\s+(?:the\s+)?(?P<app_en2>[^.!?]+?)\s+"
        rf"(?P<target_en2>{target_pattern})$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"fill\s+(?:the\s+)?(?P<target_en3>[^.!?]+?)\s+"
        r"(?:in|on)\s+(?:the\s+)?(?P<app_en3>[^.!?]+?)\s+"
        r"with\s+(?P<text_en3>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _normalize_app_scoped_ui_action_app(
            groups.get("app")
            or groups.get("app2")
            or groups.get("app3")
            or groups.get("app_en")
            or groups.get("app_en2")
            or groups.get("app_en3")
            or ""
        )
        raw_target = (
            groups.get("target")
            or groups.get("target2")
            or groups.get("target3")
            or groups.get("target_en")
            or groups.get("target_en2")
            or groups.get("target_en3")
            or ""
        )
        typed_text = _strip_typed_text(
            groups.get("text")
            or groups.get("text2")
            or groups.get("text3")
            or groups.get("text_en")
            or groups.get("text_en2")
            or groups.get("text_en3")
            or ""
        )
        target = _strip_desktop_ui_input_target(raw_target)
        if not app_name or not target or not typed_text:
            continue
        return {
            "app_name": app_name,
            "target": target,
            "text": typed_text,
            "role_filter": _desktop_ui_element_role_filter(raw_target),
            "limit": 80,
        }
    return None


def _normalize_app_scoped_ui_action_app(value: str) -> str:
    raw_app = _strip_app_name(value)
    if not raw_app:
        return ""
    if re.match(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启|开|切换到|切到|切回|回到|聚焦|激活|置前)",
        raw_app,
        flags=re.IGNORECASE,
    ):
        return ""
    compact = re.sub(r"[\s._-]+", "", raw_app.lower())
    if compact in {
        "在",
        "给",
        "向",
        "到",
        "当前",
        "在当前",
        "前台",
        "在前台",
        "这个",
        "该",
        "current",
        "foreground",
        "active",
        "currentwindow",
        "foregroundwindow",
        "activewindow",
        "currentapp",
        "foregroundapp",
        "activeapp",
        "能否",
        "能不能",
        "可以",
        "帮我",
        "请",
        "麻烦",
        "点",
        "点击",
        "点一下",
        "按",
        "按下",
        "click",
        "press",
        "cmd",
        "command",
        "ctrl",
        "control",
        "shift",
        "option",
        "alt",
        "fn",
        "enter",
        "return",
        "tab",
        "esc",
        "escape",
        "页面",
        "网页",
        "当前页",
        "当前页面",
        "当前网页",
        "浏览器",
        "browser",
        "page",
        "currentpage",
        "go",
        "make",
        "makea",
        "create",
        "createa",
    }:
        return ""
    if re.fullmatch(r"\d+(?:\.\d+)?", raw_app):
        return ""
    if _looks_like_generic_ui_scope(raw_app) or _looks_like_generic_app_open_target(raw_app):
        return ""
    if _looks_like_click_coordinate_label(raw_app) or re.search(
        r"(?:坐标|位置|coordinate|point|\d+\s*(?:,|，|\s)\s*\d+)",
        raw_app,
        flags=re.IGNORECASE,
    ):
        return ""
    if compact not in _APP_ALIASES and re.search(
        r"(?:按钮|控件|元素|输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"搜索|消息|聊天|地址|"
        r"\bbutton\b|\bcontrol\b|\belement\b|\bfield\b|\binput\b|\bbox\b|\bbar\b|"
        r"\bsearch\b|\bmessage\b|\bchat\b|\baddress\b)",
        raw_app,
        flags=re.IGNORECASE,
    ):
        return ""
    app_name = _normalize_app_name(raw_app)
    if not app_name or _looks_like_local_path(raw_app) or _normalize_site_name(raw_app):
        return ""
    return app_name


def _strip_app_scoped_ui_action_target(value: str) -> str:
    target = _strip_desktop_ui_element_label(value)
    target = re.sub(r"^(?:the|a|an)\s+", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:visible|shown|available)\s+", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:可见|看得到|能看到)(?:的)?\s*", "", target)
    target = re.sub(r"^的\s*", "", target)
    return _strip_query(target)


def _looks_like_generic_ui_scope(value: str) -> bool:
    if _looks_like_generic_window_scope(value):
        return True
    scope_value = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以|直接|列出|查看|看看|看一下|看下|显示|读取|识别)\s*",
        "",
        str(value or "").strip().lower(),
    )
    compact = re.sub(r"[\s._-]+", "", scope_value)
    return compact in {
        "当前",
        "现在",
        "这个",
        "前台",
        "该",
        "当前应用",
        "当前app",
        "当前界面",
        "当前窗口",
        "当前屏幕",
        "当前页面",
        "当前网页",
        "当前应用有哪些",
        "当前app有哪些",
        "当前应用界面",
        "前台应用",
        "前台app",
        "前台界面",
        "前台窗口",
        "前台页面",
        "前台网页",
        "这个应用",
        "这个app",
        "这个界面",
        "这个窗口",
        "这个页面",
        "这个网页",
        "该应用",
        "该app",
        "该页面",
        "该网页",
        "thecurrent",
        "thecurrentapp",
        "currentapplication",
        "currentapp",
        "currentwindow",
        "currentinterface",
        "current",
        "this",
        "foreground",
        "frontmost",
        "visible",
        "shown",
        "available",
        "thevisible",
        "thevisiblebuttons",
        "visiblebuttons",
        "shownbuttons",
        "availablebuttons",
        "可见",
        "可见的",
        "看得到",
        "能看到",
        "thisapp",
        "thiswindow",
    } or (
        compact.startswith(
            (
                "当前",
                "现在",
                "这个",
                "前台",
                "该",
                "当前应用",
                "当前app",
                "当前界面",
                "当前页面",
                "当前网页",
                "前台应用",
                "前台app",
                "前台界面",
                "前台页面",
                "前台网页",
                "这个应用",
                "这个app",
                "这个界面",
                "这个页面",
                "这个网页",
                "该应用",
                "该app",
                "该页面",
                "该网页",
            )
        )
        and any(marker in compact for marker in ("有哪些", "有什么", "有啥", "有哪个", "有哪几个"))
    )


def _is_general_windows_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:列出|列一下|列下|查看|看看|显示|读取).{0,8}"
            r"(?:当前|现在|桌面|打开|已打开|所有)?.{0,8}(?:窗口|windows?)",
            text,
        )
        or re.search(r"(?:窗口|windows?)\s*(?:列表|清单|list)$", text, flags=re.IGNORECASE)
        or re.search(r"(?:当前|现在|桌面|所有|全部)?(?:窗口|windows?).{0,8}(?:列出|列一下|列下|列表|清单)", text)
        or re.search(r"(?:打开|已打开|现在|当前|桌面|所有).{0,8}(?:有哪些|什么|几个|多少).{0,4}(?:窗口)", text)
        or re.search(r"\b(?:list|show|read|what|which)\s+(?:open\s+)?windows\b", lowered)
        or re.search(r"\bopen\s+windows\b", lowered)
    )


def _strip_window_scope_app_prefix(value: str) -> str:
    text = _strip_query(value)
    stripped = re.sub(
        r"^(?:显示|查看|看看|看一下|看下|列出|列一下|列下|读取)\s*",
        "",
        text,
    ).strip()
    stripped = re.sub(
        r"^(?:show|list|read)\s+",
        "",
        stripped,
        flags=re.IGNORECASE,
    ).strip()
    return stripped or text


def _looks_like_generic_window_scope(value: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    compact = re.sub(
        r"^(?:显示|查看|看看|看一下|看下|列出|列一下|列下|读取|show|list|read)",
        "",
        compact,
        flags=re.IGNORECASE,
    )
    return compact in {
        "",
        "当前",
        "当前应用",
        "当前app",
        "当前软件",
        "前台",
        "前台应用",
        "前台app",
        "前台软件",
        "现在",
        "桌面",
        "系统",
        "所有",
        "全部",
        "打开",
        "打开的",
        "已打开",
        "已打开的",
        "有",
        "有哪",
        "有哪些",
        "看看",
        "查看",
        "看一下",
        "看下",
        "列出",
        "列一下",
        "列下",
        "显示",
        "读取",
        "open",
        "all",
        "current",
        "currentapp",
        "foreground",
        "foregroundapp",
        "desktop",
        "windows",
    }


def _looks_like_app_status_request(text: str) -> bool:
    if _is_running_apps_request(text):
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _APP_STATUS_PATTERNS)


def _desktop_open_path(text: str) -> str:
    original_text = str(text or "").strip()
    if _downloads_folder_open_path_request(original_text):
        return "~/Downloads"
    if _finder_selection_reveal_path_request(original_text):
        return ""
    if _finder_selection_open_path_request(original_text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(original_text):
        return ""
    if _latest_screenshot_open_path_request(original_text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(original_text):
        return ""
    if _latest_desktop_item_open_path_request(original_text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(original_text):
        return ""
    if _latest_download_open_path_request(original_text):
        return "latest_download"
    text = _strip_finder_path_prefix(original_text)
    if _downloads_folder_open_path_request(text):
        return "~/Downloads"
    if _finder_selection_reveal_path_request(text):
        return ""
    if _finder_selection_open_path_request(text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(text):
        return ""
    if _latest_screenshot_open_path_request(text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(text):
        return ""
    if _latest_desktop_item_open_path_request(text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(text):
        return ""
    if _latest_download_open_path_request(text):
        return "latest_download"
    if text != original_text:
        path = _normalize_reveal_path(text)
        if path:
            return path
    if re.search(r"\bin\s+(?:the\s+)?finder\b", text, flags=re.IGNORECASE):
        return ""
    path_token = r"(?:~|/|\./|\../)[^。！？!?，,]+"
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?P<path>{path_token})\s*(?:打开|开启|拉起来|拉起)(?:一下|下)?",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:打开|开启|拉起来|拉起)\s*(?:一下\s*)?(?P<path>{path_token})",
        rf"\bopen\s+(?P<path>{path_token})\b",
        r"\bopen\s+(?P<path>[^.!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<path>[^。！？!?，,]+?)\s*(?:打开|开启|拉起来|拉起)(?:一下|下)?"
        r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|开启|拉起来|拉起)\s*(?:一下\s*)?(?P<path>[^。！？!?，,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        path = _normalize_reveal_path(match.group("path"))
        if path:
            return path
    return ""


def _desktop_reveal_path(text: str) -> str:
    original_text = str(text or "").strip()
    if _finder_selection_reveal_path_request(original_text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(original_text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(original_text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(original_text):
        return "latest_download"
    text = _strip_finder_path_prefix(original_text)
    if _finder_selection_reveal_path_request(text):
        return "finder_selection"
    if _latest_screenshot_reveal_path_request(text):
        return "latest_screenshot"
    if _latest_desktop_item_reveal_path_request(text):
        return "latest_desktop_item"
    if _latest_download_reveal_path_request(text):
        return "latest_download"
    path_token = r"(?:~|/|\./|\../)[^。！？!?，,]+"
    patterns = (
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        rf"(?P<path>{path_token})\s*(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示出来|显示一下|显示|定位|找一下|找到)",
        rf"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示出来|显示一下|显示|定位|找一下|找到|打开)\s*(?P<path>{path_token})",
        rf"(?:show|reveal|locate|open)\s+(?P<path>{path_token})(?:\s+in\s+(?:the\s+)?finder)?",
        rf"(?P<path>{path_token})\s*(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        rf"(?:显示出来|显示一下|显示|定位|找一下|找到|reveal|show)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"在\s*(?:finder|访达)\s*(?:中|里|内)?\s*"
        r"(?:显示出来|显示一下|显示|定位|找一下|找到|打开)\s*(?P<path>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<path>[^。！？!?，,]+?)\s*(?:在\s*(?:finder|访达)\s*(?:中|里|内)?\s*)?"
        r"(?:显示出来|显示一下|显示|定位|找一下|找到)(?:一下|下)?"
        r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|显示出来|显示一下|显示|定位|找一下|找到)\s*(?P<path>[^。！？!?，,]+)",
        r"(?:show|reveal|locate|open)\s+(?P<path>[^.!?]+?)\s+in\s+(?:the\s+)?finder",
        r"(?:show|reveal|locate)\s+(?P<path>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        path = _normalize_reveal_path(match.group("path"))
        if path:
            return path
    return ""


def _latest_screenshot_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,12}(?:最近|最新|刚刚|刚才|上一张|上一个).{0,8}"
            r"(?:截图|截屏|屏幕截图|屏幕快照)",
            text,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent|last)\s+"
            r"(?:screenshot|screen\s+shot)\b",
            lowered,
        )
    )


def _latest_screenshot_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示出来|显示|定位|找一下|找到|打开).{0,12}"
            r"(?:最近|最新|刚刚|刚才|上一张|上一个).{0,8}(?:截图|截屏|屏幕截图|屏幕快照)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示出来|显示|定位|找一下|找到).{0,12}"
            r"(?:最近|最新|刚刚|刚才|上一张|上一个).{0,8}(?:截图|截屏|屏幕截图|屏幕快照)",
            text,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?"
            r"(?:latest|newest|most\s+recent|recent|last)\s+"
            r"(?:screenshot|screen\s+shot)(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _latest_desktop_item_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,12}(?:桌面).{0,8}(?:最近|最新|刚刚|刚才).{0,8}"
            r"(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"(?:桌面).{0,8}(?:最近|最新|刚刚|刚才).{0,8}"
            r"(?:文件|项目|内容|东西).{0,12}(?:打开|开启)",
            text,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:desktop\s+)?(?:file|item)\b",
            lowered,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:file|item)\s+on\s+(?:the\s+)?desktop\b",
            lowered,
        )
    )


def _latest_desktop_item_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示出来|显示|定位|找一下|找到|打开).{0,12}"
            r"(?:桌面).{0,8}(?:最近|最新|刚刚|刚才).{0,8}(?:文件|项目|内容|东西)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示出来|显示|定位|找一下|找到).{0,12}(?:桌面).{0,8}"
            r"(?:最近|最新|刚刚|刚才).{0,8}(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?"
            r"(?:latest|newest|most\s+recent|recent)\s+(?:desktop\s+)?(?:file|item)"
            r"(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?"
            r"(?:latest|newest|most\s+recent|recent)\s+(?:file|item)\s+on\s+"
            r"(?:the\s+)?desktop(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _finder_selection_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,10}(?:当前)?(?:选中|选定|选择)的?.{0,10}"
            r"(?:finder|访达)?\s*(?:文件|项目|条目)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前)?(?:选中|选定|选择)的?.{0,10}(?:finder|访达)?\s*"
            r"(?:文件|项目|条目).{0,10}(?:打开|开启)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:currently\s+)?selected\s+(?:finder\s+)?(?:file|item)\b",
            lowered,
        )
        or re.search(
            r"\b(?:currently\s+)?selected\s+(?:finder\s+)?(?:file|item).{0,20}\bopen\b",
            lowered,
        )
    )


def _finder_selection_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示出来|显示|定位|找一下|找到).{0,10}"
            r"(?:当前)?(?:选中|选定|选择)的?.{0,6}(?:文件|项目|条目)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示出来|显示|定位|找一下|找到).{0,10}"
            r"(?:当前)?(?:选中|选定|选择)的?.{0,12}(?:finder|访达)?\s*(?:文件|项目|条目)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前)?(?:选中|选定)的?.{0,12}(?:finder|访达)?\s*(?:文件|项目|条目).{0,10}"
            r"(?:显示出来|显示|定位|找一下|找到)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:currently\s+)?selected\s+"
            r"(?:finder\s+)?(?:file|item)(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _latest_download_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:打开|开启).{0,12}(?:最近|最新|刚刚|刚才|最后|最后一个|上一个).{0,8}(?:下载|下载的).{0,8}(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"(?:打开|开启).{0,12}(?:下载|下载目录|下载文件夹).{0,8}"
            r"(?:最近|最新|刚刚|刚才|最后|最后一个|上一个).{0,8}(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:download|downloaded\s+(?:file|item))\b",
            lowered,
        )
    )


def _downloads_folder_open_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if re.search(r"(?:finder|访达)", text, flags=re.IGNORECASE) and re.search(
        r"(?:显示出来|显示|定位|找一下|找到|show|reveal|locate)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|开启|查看|看看|进入)\s*"
            r"(?:下载|下载列表|下载记录|下载页面|下载文件夹|下载目录|我的下载)"
            r"(?:文件夹|目录|列表|记录|页面)?"
            r"(?:\s*(?:并|然后|后|之后|再)\s*(?:排序|排列|看看|查看))?"
            r"(?:一下|下|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            text,
        )
        or re.search(
            r"\b(?:open|view)\s+(?:the\s+)?downloads"
            r"(?:\s+(?:folder|directory|list|page))?\b",
            lowered,
        )
    )


def _latest_download_reveal_path_request(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    return bool(
        re.search(
            r"(?:finder|访达).{0,12}(?:显示出来|显示|定位|找一下|找到|打开).{0,12}"
            r"(?:最近|最新|刚刚|刚才).{0,8}(?:下载|下载的).{0,8}(?:文件|项目|内容|东西)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:显示出来|显示|定位|找一下|找到).{0,12}"
            r"(?:最近|最新|刚刚|刚才).{0,8}(?:下载|下载的).{0,8}(?:文件|项目|内容|东西)?",
            text,
        )
        or re.search(
            r"\b(?:show|reveal|locate)\s+(?:the\s+)?(?:latest|newest|most\s+recent|recent)\s+"
            r"(?:download|downloaded\s+(?:file|item))(?:\s+in\s+(?:the\s+)?finder)?\b",
            lowered,
        )
    )


def _strip_finder_path_prefix(text: str) -> str:
    return re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:打开|启动|运行|拉起|开启)\s*(?:finder|访达|文件管理器|文件浏览器)|"
        r"(?:open|launch|start)\s+(?:the\s+)?(?:finder|file\s+manager|file\s+browser))"
        r"(?:\s*(?:里的|中的|内的|里|中|内))?\s*"
        r"(?:(?:并|然后|后|之后|再)|(?:,?\s*(?:and\s+then|and|then)))?\s*"
        r"(?:(?:看看|看一下|看下|查看|检查|打开|开启|进入)\s*)?",
        "",
        text,
        flags=re.IGNORECASE,
    )


def _normalize_reveal_path(value: str) -> str:
    target = _strip_polite_suffix(_strip_query(value))
    target = re.sub(r"\s+in\s+(?:the\s+)?finder$", "", target, flags=re.IGNORECASE)
    target = re.sub(r"^(?:一下|下(?!载)|这个|那个)\s*", "", target)
    if _looks_like_local_path(target):
        return target
    common_path = common_desktop_path_alias(target)
    if common_path:
        return common_path
    target = re.sub(r"\s*(?:文件夹|目录|路径|folder|directory|path)$", "", target, flags=re.IGNORECASE)
    target = _strip_polite_suffix(_strip_query(target))
    if not target:
        return ""
    common_path = common_desktop_path_alias(target)
    if common_path:
        return common_path
    return ""


def _looks_like_local_path(value: str) -> bool:
    return bool(re.match(r"^(?:~|/|\./|\../)", str(value or "").strip()))


def _app_open_or_focus_foreground_action_request(text: str) -> dict[str, Any] | None:
    open_match = _app_foreground_action_match(
        text,
        (
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
            r"(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and|then)\s+(?P<followup>.+)$",
        ),
    )
    if open_match:
        return _app_foreground_action_request_from_match("open", open_match)

    focus_match = _app_foreground_action_match(
        text,
        (
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
            r"(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+?)\s+"
            r"(?:and|then)\s+(?P<followup>.+)$",
        ),
    )
    if focus_match:
        return _app_foreground_action_request_from_match("focus", focus_match)

    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, _raw_app, app_name, followup = shorthand_match
        return _app_foreground_action_request(mode, app_name, followup)
    return None


def _app_open_or_focus_safe_type_text_tool_requests(text: str) -> list[dict[str, Any]]:
    payload = _app_open_or_focus_foreground_action_request(text)
    if not payload:
        return []
    tool = str(payload.get("tool") or "")
    if tool not in {"app.open_and_safe_type_text", "app.focus_and_safe_type_text"}:
        return []
    payload_input = payload.get("input") if isinstance(payload.get("input"), dict) else {}
    request = _request(tool, dict(payload_input))
    followup = _app_open_or_focus_foreground_action_followup(text)
    if not followup:
        return [request]
    return _safe_type_text_followup_tool_requests(request, followup)


def _app_open_or_focus_foreground_action_followup(text: str) -> str:
    open_match = _app_foreground_action_match(
        text,
        (
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
            r"(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and|then)\s+(?P<followup>.+)$",
        ),
    )
    if open_match:
        _raw_app, followup = open_match
        return followup
    focus_match = _app_foreground_action_match(
        text,
        (
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
            r"(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+?)\s+"
            r"(?:and|then)\s+(?P<followup>.+)$",
        ),
    )
    if focus_match:
        _raw_app, followup = focus_match
        return followup
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        _mode, _raw_app, _app_name, followup = shorthand_match
        return followup
    return ""


def _safe_type_text_followup_tool_requests(
    request: dict[str, Any],
    followup: str,
) -> list[dict[str, Any]]:
    requests = [request]
    if _typed_text_has_return_followup(followup, ""):
        requests.append(_request("desktop.hotkey", {"key": "return", "modifiers": []}))
    elif _typed_text_has_submit_followup(followup) or _safe_type_text_followup_has_send_intent(followup):
        requests.append(_request("desktop.submit_foreground", {"action": "send"}))
    return requests


def _safe_type_text_followup_has_send_intent(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(
        re.match(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:发送|发出|发|说)\s*(?:消息|信息|message)?\s*\S+",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(r"^(?:send|say)\s+\S+", text, flags=re.IGNORECASE)
    )


def _communication_selected_text_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _communication_selected_text_request(text)
    if not parsed:
        return []
    mode, app_name, recipient = parsed
    return [
        _request("desktop.safe_shortcut", {"action": "copy"}),
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": recipient}),
        _request("desktop.search_submit", {}),
        _request("desktop.safe_shortcut", {"action": "paste"}),
        _request("desktop.submit_foreground", {"action": "send"}),
    ]


def _communication_selected_text_request(text: str) -> tuple[str, str, str] | None:
    app_followup = _communication_app_followup_request(text)
    if app_followup:
        mode, app_name, followup = app_followup
        recipient = _communication_selected_text_recipient(followup)
        if recipient:
            return mode, app_name, recipient
    return _communication_selected_text_postposed_request(text)


def _communication_selected_text_recipient(text: str) -> str:
    followup = _strip_query(text)
    if not followup or _looks_like_explicit_text_input_target(followup):
        return ""
    selected_text_source = (
        r"(?:当前)?(?:选中|选择)(?:的)?(?:内容|文字|文本)?|"
        r"(?:selected\s+text|selection|current\s+selection)"
    )
    patterns = (
        rf"^(?:给|向)\s*(?P<recipient_to>.+?)\s*(?:发送|发出|发)\s*"
        rf"(?:{selected_text_source})$",
        rf"^(?:发送|发出|发)\s*(?:{selected_text_source})\s*(?:给|向)\s*"
        rf"(?P<recipient_send>.+)$",
        rf"^(?:send|message)\s+(?:the\s+)?(?:{selected_text_source})\s+to\s+"
        rf"(?P<recipient_selected_to>.+)$",
        rf"^(?:send|message)\s+(?P<recipient_with_selected>.+?)\s+"
        rf"(?:with\s+)?(?:the\s+)?(?:{selected_text_source})$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        recipient = _strip_communication_piece(
            groups.get("recipient_to")
            or groups.get("recipient_send")
            or groups.get("recipient_selected_to")
            or groups.get("recipient_with_selected")
            or ""
        )
        if recipient:
            return recipient
    return ""


def _communication_selected_text_postposed_request(text: str) -> tuple[str, str, str] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    selected_text_source = (
        r"(?:当前)?(?:选中|选择)(?:的)?(?:内容|文字|文本)?|"
        r"(?:selected\s+text|selection|current\s+selection)"
    )
    patterns = (
        rf"^(?:把|将)?\s*(?:复制|拷贝|copy)?\s*(?:{selected_text_source})\s*"
        rf"(?:(?:并|然后|再)\s*)?"
        rf"(?:发送|发出|发|分享|转发)\s*(?:给|到|至|向)\s*(?P<target>.+)$",
        rf"^(?:send|share|forward|message)\s+(?:the\s+)?(?:{selected_text_source})\s+to\s+"
        rf"(?P<target>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        target = _strip_query(match.group("target"))
        split = _known_app_prefix_split(target)
        if not split:
            continue
        _raw_app, app_name, followup = split
        if app_name not in _COMMUNICATION_APP_NAMES:
            continue
        recipient = _strip_communication_piece(followup)
        if recipient:
            return "focus", app_name, recipient
    return None


def _communication_current_page_link_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _communication_current_page_link_request(text)
    if not parsed:
        return []
    mode, app_name, recipient = parsed
    return [
        *_browser_current_page_link_copy_tool_requests("复制当前网页链接"),
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": recipient}),
        _request("desktop.search_submit", {}),
        _request("desktop.safe_shortcut", {"action": "paste"}),
        _request("desktop.submit_foreground", {"action": "send"}),
    ]


def _communication_current_page_link_request(text: str) -> tuple[str, str, str] | None:
    app_followup = _communication_app_followup_request(text)
    if app_followup:
        mode, app_name, followup = app_followup
        recipient = _communication_current_page_link_recipient(followup)
        if recipient:
            return mode, app_name, recipient
    return _communication_current_page_link_postposed_request(text)


def _communication_current_page_link_recipient(text: str) -> str:
    followup = _strip_query(text)
    if not followup or _looks_like_explicit_text_input_target(followup):
        return ""
    current_page_link_source = _communication_current_page_link_source_pattern()
    patterns = (
        rf"^(?:给|向)\s*(?P<recipient_to>.+?)\s*(?:发送|发出|发|分享|转发)\s*"
        rf"(?:{current_page_link_source})$",
        rf"^(?:发送|发出|发|分享|转发)\s*(?:{current_page_link_source})\s*(?:给|向)\s*"
        rf"(?P<recipient_send>.+)$",
        rf"^(?:send|share|forward|message)\s+(?:the\s+)?(?:{current_page_link_source})\s+to\s+"
        rf"(?P<recipient_link_to>.+)$",
        rf"^(?:send|share|forward|message)\s+(?P<recipient_with_link>.+?)\s+"
        rf"(?:with\s+)?(?:the\s+)?(?:{current_page_link_source})$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        recipient = _strip_communication_piece(
            groups.get("recipient_to")
            or groups.get("recipient_send")
            or groups.get("recipient_link_to")
            or groups.get("recipient_with_link")
            or ""
        )
        if recipient:
            return recipient
    return ""


def _communication_current_page_link_postposed_request(text: str) -> tuple[str, str, str] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    current_page_link_source = _communication_current_page_link_source_pattern()
    patterns = (
        rf"^(?:把|将)?\s*(?:复制|拷贝|copy)?\s*(?:{current_page_link_source})\s*"
        rf"(?:(?:并|然后|再)\s*)?"
        rf"(?:发送|发出|发|分享|转发)\s*(?:给|到|至|向)\s*(?P<target>.+)$",
        rf"^(?:send|share|forward)\s+(?:the\s+)?(?:{current_page_link_source})\s+to\s+"
        rf"(?P<target>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        target = _strip_query(match.group("target"))
        split = _known_app_prefix_split(target)
        if not split:
            continue
        _raw_app, app_name, followup = split
        if app_name not in _COMMUNICATION_APP_NAMES:
            continue
        recipient = _strip_communication_piece(followup)
        if recipient:
            return "focus", app_name, recipient
    return None


def _communication_current_page_link_source_pattern() -> str:
    return (
        r"(?:当前|现在|前台|这个|这页|本页).{0,8}"
        r"(?:网页|网站|页面|页|浏览器|标签页)?(?:链接|网址|url|URL|地址)|"
        r"(?:current|active|this)\s+(?:(?:browser\s+)?(?:page|tab)\s+)?"
        r"(?:url|link|address)"
    )


def _communication_current_content_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _communication_current_content_request(text)
    if not parsed:
        return []
    mode, app_name, recipient = parsed
    return [
        *_current_content_copy_tool_requests(),
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": recipient}),
        _request("desktop.search_submit", {}),
        _request("desktop.safe_shortcut", {"action": "paste"}),
        _request("desktop.submit_foreground", {"action": "send"}),
    ]


def _communication_current_content_request(text: str) -> tuple[str, str, str] | None:
    app_followup = _communication_app_followup_request(text)
    if app_followup:
        mode, app_name, followup = app_followup
        recipient = _communication_current_content_recipient(followup)
        if recipient:
            return mode, app_name, recipient
    return _communication_current_content_postposed_request(text)


def _communication_current_content_recipient(text: str) -> str:
    followup = _strip_query(text)
    if not followup or _looks_like_explicit_text_input_target(followup):
        return ""
    current_content_source = _current_content_source_pattern()
    patterns = (
        rf"^(?:给|向)\s*(?P<recipient_to>.+?)\s*(?:发送|发出|发|分享|转发)\s*"
        rf"(?:{current_content_source})$",
        rf"^(?:发送|发出|发|分享|转发)\s*(?:{current_content_source})\s*(?:给|向)\s*"
        rf"(?P<recipient_send>.+)$",
        rf"^(?:send|share|forward|message)\s+(?:the\s+)?(?:{current_content_source})\s+to\s+"
        rf"(?P<recipient_content_to>.+)$",
        rf"^(?:send|share|forward|message)\s+(?P<recipient_with_content>.+?)\s+"
        rf"(?:with\s+)?(?:the\s+)?(?:{current_content_source})$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        recipient = _strip_communication_piece(
            groups.get("recipient_to")
            or groups.get("recipient_send")
            or groups.get("recipient_content_to")
            or groups.get("recipient_with_content")
            or ""
        )
        if recipient:
            return recipient
    return ""


def _communication_current_content_postposed_request(text: str) -> tuple[str, str, str] | None:
    clean = _strip_query(text)
    if not clean or _communication_current_page_link_request(clean):
        return None
    current_content_source = _current_content_source_pattern()
    patterns = (
        rf"^(?:把|将)?\s*(?:复制|拷贝|copy)?\s*(?:{current_content_source})\s*"
        rf"(?:(?:并|然后|再)\s*)?"
        rf"(?:发送|发出|发|分享|转发)\s*(?:给|到|至|向)\s*(?P<target>.+)$",
        rf"^(?:send|share|forward|message)\s+(?:the\s+)?(?:{current_content_source})\s+to\s+"
        rf"(?P<target>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        target = _strip_query(match.group("target"))
        split = _known_app_prefix_split(target)
        if not split:
            continue
        _raw_app, app_name, followup = split
        if app_name not in _COMMUNICATION_APP_NAMES:
            continue
        recipient = _strip_communication_piece(followup)
        if recipient:
            return "focus", app_name, recipient
    return None


def _communication_paste_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _communication_paste_request(text)
    if not parsed:
        return []
    mode, app_name, recipient, should_submit = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": recipient}),
        _request("desktop.search_submit", {}),
        _request("desktop.safe_shortcut", {"action": "paste"}),
    ]
    if should_submit:
        requests.append(_request("desktop.submit_foreground", {"action": "send"}))
    return requests


def _communication_paste_request(text: str) -> tuple[str, str, str, bool] | None:
    app_followup = _communication_app_followup_request(text)
    if app_followup:
        mode, app_name, followup = app_followup
        parsed = _communication_paste_recipient(followup)
        if parsed:
            recipient, should_submit = parsed
            return mode, app_name, recipient, should_submit
    return _communication_paste_postposed_request(text)


def _communication_app_followup_request(text: str) -> tuple[str, str, str] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None

    mode = "focus"
    body = stripped
    prefix_patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
        ),
        (
            "open",
            r"^(?:please\s+)?(?:open|launch|start)\s+",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*",
        ),
        (
            "focus",
            r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up)\s+",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|用|通过|到)\s*",
        ),
        (
            "focus",
            r"^(?:please\s+)?(?:in|on|with|using)\s+",
        ),
    )
    for candidate_mode, pattern in prefix_patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            mode = candidate_mode
            body = stripped[match.end() :].strip()
            break

    split = _known_app_prefix_split(body)
    if not split:
        return None
    _raw_app, app_name, followup = split
    if app_name not in _COMMUNICATION_APP_NAMES:
        return None
    return mode, app_name, followup


def _communication_paste_recipient(text: str) -> tuple[str, bool] | None:
    followup = _strip_query(text)
    if not followup or _looks_like_explicit_text_input_target(followup):
        return None
    patterns = (
        r"^(?:搜索|搜一下|搜|查找|查一下|检索|找一下|找)\s*"
        r"(?P<recipient_search>.+?)\s*"
        r"(?:(?:然后|并且|并|之后|后|再|接着)\s*)?"
        r"(?:把|将)?(?:剪贴板|粘贴板)?(?:内容)?\s*(?:粘贴|贴上)(?P<tail_search>.*)$",
        r"^(?:给|向)\s*(?P<recipient_to>.+?)\s*"
        r"(?:把|将)?(?:剪贴板|粘贴板)?(?:内容)?\s*(?:粘贴|贴上)(?P<tail_to>.*)$",
        r"^(?:发给|发送给)\s*(?P<recipient_send_to>.+?)\s*"
        r"(?:剪贴板|粘贴板)(?:内容)?(?P<tail_send_to>.*)$",
        r"^(?:发送|发出|发)\s*(?:剪贴板|粘贴板)(?:内容)?\s*(?:给|向)\s*"
        r"(?P<recipient_send_clipboard>.+)$",
        r"^(?:把|将)?(?:剪贴板|粘贴板)(?:内容)?\s*(?:发送|发出|发)\s*(?:给|向)\s*"
        r"(?P<recipient_clipboard_send>.+)$",
        r"^(?:find|search(?:\s+for)?)\s+(?P<recipient_find>.+?)\s+"
        r"(?:paste(?:\s+(?:the\s+)?clipboard(?:\s+contents?)?)?)(?P<tail_find>.*)$",
        r"^(?:send|message)\s+(?:the\s+)?clipboard(?:\s+contents?)?\s+to\s+"
        r"(?P<recipient_clipboard_to>.+)$",
        r"^(?:send|message)\s+(?P<recipient_with_clipboard>.+?)\s+"
        r"(?:with\s+)?(?:the\s+)?clipboard(?:\s+contents?)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        recipient = _strip_communication_piece(
            groups.get("recipient_search")
            or groups.get("recipient_to")
            or groups.get("recipient_send_to")
            or groups.get("recipient_send_clipboard")
            or groups.get("recipient_clipboard_send")
            or groups.get("recipient_find")
            or groups.get("recipient_clipboard_to")
            or groups.get("recipient_with_clipboard")
            or ""
        )
        if not recipient:
            continue
        should_submit = _communication_paste_has_submit_intent(followup)
        return recipient, should_submit
    return None


def _communication_paste_postposed_request(text: str) -> tuple[str, str, str, bool] | None:
    clean = _strip_query(text)
    if not clean:
        return None
    clipboard_source = _communication_clipboard_source_pattern()
    patterns = (
        rf"^(?:把|将)?\s*(?:{clipboard_source})\s*"
        rf"(?:(?:然后|并且|并|之后|后|再|接着)\s*)?"
        rf"(?:发送|发出|发|分享|转发)\s*(?:给|到|至|向)?\s*(?P<target>.+)$",
        rf"^(?:read|send|share|forward|message)\s+(?:the\s+)?(?:{clipboard_source})\s+"
        rf"(?:and\s+then\s+|then\s+)?(?:send\s+)?to\s+(?P<target>.+)$",
        rf"^(?:send|share|forward|message)\s+(?:the\s+)?(?:{clipboard_source})\s+to\s+"
        rf"(?P<target>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        target = _strip_query(match.group("target"))
        split = _known_app_prefix_split(target)
        if not split:
            continue
        _raw_app, app_name, followup = split
        if app_name not in _COMMUNICATION_APP_NAMES:
            continue
        recipient = _strip_communication_piece(followup)
        if recipient:
            return "focus", app_name, recipient, True
    return None


def _communication_clipboard_source_pattern() -> str:
    return (
        r"(?:(?:读取|读一下|读取一下)\s*)?"
        r"(?:当前|系统|这个|这份|我的)?(?:剪贴板|粘贴板)(?:内容)?|"
        r"(?:(?:current|system|my)\s+)?clipboard(?:\s+contents?)?"
    )


def _communication_paste_has_submit_intent(value: str) -> bool:
    text = str(value or "").strip()
    return bool(
        re.search(r"(?:发送|发出|发|提交)$", text, flags=re.IGNORECASE)
        or re.search(r"(?:并且|并|然后|之后|后|再|接着)\s*(?:发送|发出|发|提交)$", text)
        or re.search(r"(?:and\s+then|then|and)\s*(?:send|submit|post)$", text, flags=re.IGNORECASE)
        or re.search(r"^(?:发给|发送给|发送|发出|发)", text)
        or re.search(r"^(?:send|message)\s+", text, flags=re.IGNORECASE)
    )


def _communication_compose_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _communication_compose_request(text)
    if not parsed:
        return []
    mode, app_name, recipient, message, should_submit = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": recipient}),
        _request("desktop.search_submit", {}),
        _request("desktop.safe_type_text", {"text": message}),
    ]
    if should_submit:
        requests.append(_request("desktop.submit_foreground", {"action": "send"}))
    return requests


def _communication_compose_request(text: str) -> tuple[str, str, str, str, bool] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None

    mode = "focus"
    body = stripped
    prefix_patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
        ),
        (
            "open",
            r"^(?:please\s+)?(?:open|launch|start)\s+",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*",
        ),
        (
            "focus",
            r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up)\s+",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|用|通过|到)\s*",
        ),
        (
            "focus",
            r"^(?:please\s+)?(?:in|on|with|using)\s+",
        ),
    )
    for candidate_mode, pattern in prefix_patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if match:
            mode = candidate_mode
            body = stripped[match.end() :].strip()
            break

    split = _known_app_prefix_split(body)
    if not split:
        return None
    _raw_app, app_name, followup = split
    if app_name not in _COMMUNICATION_APP_NAMES:
        return None

    parsed = _communication_recipient_message(followup)
    if not parsed:
        return None
    recipient, message, should_submit = parsed
    return mode, app_name, recipient, message, should_submit


def _communication_recipient_message(text: str) -> tuple[str, str, bool] | None:
    followup = _strip_query(text)
    if not followup:
        return None
    if _looks_like_explicit_text_input_target(followup):
        return None
    patterns = (
        r"^(?:搜索|搜一下|搜|查找|查一下|检索|找一下|找|find|search)\s*"
        r"(?P<recipient_search>.+?)\s*"
        r"(?:(?:然后|并且|并|之后|后|再|接着|and\s+then|then|and)\s*)?"
        r"(?P<verb_search>输入|打字|键入|敲入|打入|写入|写|发送|发出|发|"
        r"type|enter|input|send)\s*(?P<message_search>.+)$",
        r"^(?P<verb>发送|发出|发|send)\s*(?:消息|信息|message)?\s*"
        r"(?:给|向|to)\s*(?P<recipient>.+?)\s*"
        r"(?:说|内容是|内容为|:|：)\s*(?P<message>.+)$",
        r"^(?P<verb_tail>发送|发出|发|send)\s*(?:消息|信息|message)?\s*"
        r"(?:给|向|to)\s*(?P<recipient_message_tail>.+)$",
        r"^(?:给|向|to)\s*(?P<recipient>.+?)\s*"
        r"(?P<verb>发送|发出|发|send)\s*(?:消息|信息|message)?\s*"
        r"(?:(?:说|内容是|内容为|:|：)\s*)?(?P<message>.+)$",
        r"^(?:给|向)\s*(?P<recipient>.+?)\s*"
        r"(?P<verb>发送|发出|发|send)\s*(?P<message>.+)$",
        r"^(?:给|向|to)\s*(?P<recipient_say>.+?)\s*"
        r"(?P<verb_say>说|告诉|留言|say|tell|message)\s*(?P<message_say>.+)$",
        r"^(?:搜索|搜一下|搜|查找|查一下|检索|找一下|找|find|search)\s*"
        r"(?P<recipient>.+?)\s*"
        r"(?:然后|并且|并|之后|后|再|接着|and\s+then|then|and)\s*"
        r"(?P<verb>输入|打字|键入|敲入|打入|写入|写|发送|发出|发|"
        r"type|enter|input|send)\s*(?P<message>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        recipient_tail = str(groups.get("recipient_message_tail") or "").strip()
        if recipient_tail:
            split_tail = _split_communication_implicit_recipient_message(recipient_tail)
            if not split_tail:
                continue
            recipient, raw_message = split_tail
        else:
            recipient = _strip_communication_piece(
                groups.get("recipient")
                or groups.get("recipient_search")
                or groups.get("recipient_say")
                or ""
            )
            raw_message = str(
                groups.get("message")
                or groups.get("message_search")
                or groups.get("message_say")
                or ""
            ).strip()
        message = _strip_typed_text(raw_message)
        verb = str(
            groups.get("verb")
            or groups.get("verb_search")
            or groups.get("verb_tail")
            or groups.get("verb_say")
            or ""
        ).strip().lower()
        should_submit = bool(
            re.search(r"^(?:发送|发出|发|send)$", verb, flags=re.IGNORECASE)
            or _communication_message_has_submit_suffix(raw_message)
            or bool(groups.get("verb_say"))
        )
        if recipient and message:
            return recipient, message, should_submit
    return None


def _split_communication_implicit_recipient_message(value: str) -> tuple[str, str] | None:
    text = _strip_query(value)
    explicit = re.search(
        r"^(?P<recipient>.+?)\s*(?:说|内容是|内容为|:|：)\s*(?P<message>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if explicit:
        recipient = _strip_communication_piece(explicit.group("recipient"))
        message = _strip_typed_text(explicit.group("message"))
        return (recipient, message) if recipient and message else None
    greeting_pattern = (
        r"hello\b.*|hi\b.*|hey\b.*|thanks\b.*|thank\s+you\b.*|ok\b.*|okay\b.*"
    )
    spaced = re.search(
        rf"^(?P<recipient>.+?)\s+(?P<message>{greeting_pattern})$",
        text,
        flags=re.IGNORECASE,
    )
    if spaced:
        recipient = _strip_communication_piece(spaced.group("recipient"))
        message = _strip_typed_text(spaced.group("message"))
        return (recipient, message) if recipient and message else None
    compact = re.search(
        r"^(?P<recipient>.+?)(?P<message>"
        r"你好.*|您好.*|在吗.*|早上好.*|中午好.*|下午好.*|晚上好.*|"
        r"晚安.*|早安.*|谢谢.*|辛苦了.*|收到.*|好的.*|测试(?:一下)?"
        r")$",
        text,
        flags=re.IGNORECASE,
    )
    if compact:
        recipient = _strip_communication_piece(compact.group("recipient"))
        message = _strip_typed_text(compact.group("message"))
        return (recipient, message) if recipient and message else None
    return None


def _strip_communication_piece(value: str) -> str:
    text = _strip_query(value)
    text = re.sub(r"\s*(?:聊天|会话|对话|chat|conversation)$", "", text, flags=re.IGNORECASE)
    return text.strip(" 「」『』“”\"'`")


def _communication_message_has_submit_suffix(value: str) -> bool:
    return bool(
        re.search(
            r"(?:然后|并且|并|再|接着)\s*(?:发送|发出|提交)$",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:send|submit|post)$",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _app_open_or_focus_find_text_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if _desktop_type_into_ui_element(followup):
        return []
    if _app_find_shortcut_followup(followup):
        return [
            _request(
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": "find"},
            )
        ]
    if app_name not in _BROWSER_APP_NAMES:
        parsed = _app_search_query_from_followup(followup)
        if parsed is not None:
            query, submit_return = parsed
            requests = [
                _request(
                    f"app.{mode}_and_safe_shortcut",
                    {"app_name": app_name, "action": "find"},
                ),
                _request("desktop.safe_type_text", {"text": query}),
            ]
            if submit_return:
                requests.append(_request("desktop.search_submit", {}))
            return requests
    query = (
        _desktop_foreground_find_query(followup)
        if app_name in _BROWSER_APP_NAMES
        else _desktop_find_query(followup)
    )
    if not query:
        return []
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": query}),
    ]


def _app_open_or_focus_find_open_first_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, raw_app, app_name, followup = shorthand_match
    else:
        split = _known_app_prefix_split(_strip_app_search_scope_prefix(text))
        if not split:
            return []
        raw_app, app_name, followup = split
        mode = "focus"
    if (
        not app_name
        or app_name in _BROWSER_APP_NAMES
        or _looks_like_window_target(raw_app)
        or _looks_like_common_path_target(raw_app)
    ):
        return []
    parsed = _find_then_open_first_result(followup)
    if not parsed:
        return []
    query, target, click_count = parsed
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": query}),
        _request("desktop.search_submit", {}),
        _request(
            "desktop.click_ui_element",
            {
                "target": target,
                "role_filter": "",
                "limit": 80,
                "click_count": click_count,
            },
        ),
    ]


def _find_then_open_first_result(value: str) -> tuple[str, str, int] | None:
    patterns = (
        r"^(?:搜索|搜一下|搜|查找|查一下|查查|检索|找一下|找)\s*"
        r"(?P<query>.+?)\s*"
        r"(?:然后|并且|并|之后|随后|再|后)\s*"
        r"(?P<verb>打开|进入|访问|点击|点一下|点按|单击|点|选择|选中|选取)\s*"
        r"(?:搜索结果|结果|条目|文件|项目)?(?:中|里|里的|的)?\s*"
        r"(?P<rank>第?一个|第一条|首个|第1个|第1条|1)\s*"
        r"(?:搜索结果|结果|条目|文件|项目)?$",
        r"^(?:find|search)\s+(?:for\s+)?(?P<query_en>.+?)\s+"
        r"(?:and|then)\s+(?P<verb_en>open|click|visit|select|choose)\s+"
        r"(?:the\s+)?(?P<rank_en>first|1st)\s+(?:result|item|file)$",
    )
    for pattern in patterns:
        match = re.search(pattern, _strip_query(value), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        query = _strip_search_query(groups.get("query") or groups.get("query_en") or "")
        if not query:
            continue
        target = _first_result_target_label(groups.get("rank") or groups.get("rank_en") or "")
        if not target:
            continue
        verb = str(groups.get("verb") or groups.get("verb_en") or "").strip().lower()
        click_count = (
            1
            if re.search(r"^(?:点击|点一下|点按|单击|点|选择|选中|选取|click|select|choose)$", verb)
            else 2
        )
        return query, target, click_count
    return None


def _app_open_or_focus_search_navigation_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, raw_app, app_name, followup = shorthand_match
    else:
        split = _known_app_prefix_split(_strip_app_search_scope_prefix(text))
        if not split:
            return []
        raw_app, app_name, followup = split
        mode = "focus"
    if (
        not app_name
        or app_name in _BROWSER_APP_NAMES
        or _looks_like_window_target(raw_app)
        or _looks_like_common_path_target(raw_app)
    ):
        return []
    parsed = _app_search_navigation_followup(followup)
    if not parsed:
        return []
    query, safe_key, should_submit = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": query}),
        _request("desktop.safe_key", safe_key),
    ]
    if should_submit:
        requests.append(_request("desktop.submit_foreground", {"action": "confirm"}))
    return requests


def _app_search_navigation_followup(
    value: str,
) -> tuple[str, dict[str, Any], bool] | None:
    followup = _strip_query(value)
    patterns = (
        r"^(?:搜索(?!框|栏)|搜一下|搜(?!索(?:$|框|栏)|框|栏)|查找(?!框)|"
        r"查一下|查查|检索|找一下|找下(?!载)|找找|找)\s*"
        r"(?P<query>.+?)\s*"
        r"(?:然后|并且|并|之后|随后|再|后(?!退)|接着)\s*"
        r"(?P<tail>.+)$",
        r"^(?:find|search|look\s+for)\s+(?:for\s+)?(?P<query_en>.+?)\s+"
        r"(?:and\s+then|then|and)\s+(?P<tail_en>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        raw_query = str(match.groupdict().get("query") or match.groupdict().get("query_en") or "")
        raw_tail = str(match.groupdict().get("tail") or match.groupdict().get("tail_en") or "")
        query = _strip_search_query(raw_query)
        key_text, should_submit = _app_search_navigation_key_and_submit(raw_tail)
        if not query or not key_text:
            continue
        safe_key = _desktop_safe_key(key_text) or _desktop_safe_key(f"按{key_text}")
        if safe_key:
            return query, safe_key, should_submit
    return None


def _app_search_navigation_key_and_submit(value: str) -> tuple[str, bool]:
    tail = _strip_query(value)
    if not tail:
        return "", False
    should_submit = _app_search_navigation_tail_has_submit(tail)
    key_text = re.sub(
        r"\s+(?:and\s+then|then|and)\s*(?:(?:press|hit)\s*)?"
        r"(?:enter|return|confirm|ok)$",
        "",
        tail,
        flags=re.IGNORECASE,
    )
    key_text = re.sub(
        r"\s*(?:然后|并且|并|之后|随后|再|接着)?\s*"
        r"(?:按|敲|执行|确认)?(?:回车|enter|return|确认|确定)$",
        "",
        key_text,
        flags=re.IGNORECASE,
    )
    key_text = _strip_query(key_text)
    if key_text == tail and _desktop_safe_key(key_text) is None:
        return "", False
    return key_text, should_submit


def _app_search_navigation_tail_has_submit(value: str) -> bool:
    tail = str(value or "").strip()
    return bool(
        re.search(
            r"(?:然后|并且|并|之后|随后|再|接着)?\s*"
            r"(?:按|敲|执行|确认)?(?:回车|enter|return|确认|确定)$",
            tail,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:(?:press|hit)\s*)?"
            r"(?:enter|return|confirm|ok)$",
            tail,
            flags=re.IGNORECASE,
        )
    )


def _first_result_target_label(value: str) -> str:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    if compact in {"第一个", "第一条", "首个", "第1个", "第1条", "1"}:
        return "第一个结果"
    if compact in {"first", "1st"}:
        return "first result"
    return ""


def _app_open_or_focus_type_into_ui_element_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if _click_ui_element_then_type(followup):
        return []
    payload = _desktop_type_into_ui_element(followup)
    if not payload:
        return []
    requests = [
        _request(
            f"app.{mode}_and_type_into_ui_element",
            {"app_name": app_name, **payload},
        )
    ]
    if _typed_text_has_return_followup(followup, str(payload.get("target") or "")):
        requests.append(_request("desktop.hotkey", {"key": "return", "modifiers": []}))
    elif _typed_text_has_submit_followup(followup):
        requests.append(_request("desktop.submit_foreground", {"action": "send"}))
    return requests


def _foreground_find_text_tool_requests(text: str) -> list[dict[str, Any]]:
    query = _desktop_foreground_find_query(text)
    if not query:
        return []
    return [
        _request("desktop.safe_shortcut", {"action": "find"}),
        _request("desktop.safe_type_text", {"text": query}),
    ]


def _app_open_or_focus_browser_shortcut_search_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _app_open_or_focus_browser_shortcut_search(text)
    if not parsed:
        return []
    mode, app_name, shortcut_action, url = parsed
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": shortcut_action},
        ),
        _request("browser.open_url", {"url": url}),
    ]


def _app_open_or_focus_browser_shortcut_search(text: str) -> tuple[str, str, str, str] | None:
    match = _app_open_or_focus_browser_followup_match(text)
    if not match:
        return None
    mode, raw_app, app_name, followup = match
    if (
        app_name not in _BROWSER_APP_NAMES
        or _looks_like_generic_browser_app_reference(raw_app)
        or _looks_like_window_target(raw_app)
        or _looks_like_common_path_target(raw_app)
    ):
        return None
    parsed = _browser_shortcut_search_action_and_url(followup)
    if not parsed:
        return None
    shortcut_action, url = parsed
    return mode, app_name, shortcut_action, url


def _app_open_or_focus_browser_followup_match(text: str) -> tuple[str, str, str, str] | None:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match and shorthand_match[2] in _BROWSER_APP_NAMES:
        return shorthand_match
    prefix_split = _known_app_prefix_split(text)
    if prefix_split and prefix_split[1] in _BROWSER_APP_NAMES:
        raw_app, app_name, followup = prefix_split
        return "focus", raw_app, app_name, followup
    stripped = _strip_query(text)
    prefix_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "open",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
                r"^(?:please\s+)?(?:open|launch|start)\s+",
            ),
        ),
        (
            "focus",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*",
                r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up)\s+",
            ),
        ),
    )
    for mode, patterns in prefix_patterns:
        for pattern in patterns:
            match = re.search(pattern, stripped, flags=re.IGNORECASE)
            if not match:
                continue
            split = _known_app_prefix_split(stripped[match.end() :].strip())
            if split and split[1] in _BROWSER_APP_NAMES:
                raw_app, app_name, followup = split
                return mode, raw_app, app_name, followup
    return None


def _browser_shortcut_search_action_and_url(value: str) -> tuple[str, str] | None:
    action_pattern = (
        r"新建标签页|新标签页|打开新标签页|开新标签页|开一个新标签页|"
        r"新建窗口|新窗口|打开新窗口|开新窗口|开一个新窗口|"
        r"new\s+tab|new\s+window"
    )
    pattern = (
        rf"^(?P<action>{action_pattern})\s*"
        r"(?:(?:并且|并|然后|接着|之后|随后|后(?!退)|再|and\s+then|and|then)\s*)?"
        r"(?P<search>"
        r"(?:百度一下|谷歌一下|google\s+一下|搜索|搜一下|搜(?!索)|查一下|查查|查(?!看|找)|检索|"
        r"search|google|look\s+up)\s*.+)$"
    )
    match = re.search(pattern, _strip_query(value), flags=re.IGNORECASE)
    if not match:
        return None
    shortcut_action = _desktop_safe_shortcut_action(match.group("action"))
    search_url = _browser_search_url(match.group("search"))
    if not shortcut_action or not search_url:
        return None
    if shortcut_action not in {"new_tab", "new_window"}:
        return None
    return shortcut_action, search_url


def _app_open_or_focus_shortcut_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    parsed = _safe_shortcut_then_type(followup)
    if not parsed:
        return []
    shortcut_action, typed_text, submit_return = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": shortcut_action},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_return:
        requests.append(_request("desktop.hotkey", {"key": "return", "modifiers": []}))
    return requests


def _app_open_or_focus_safe_shortcut_sequence_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    actions = _safe_shortcut_action_sequence(followup)
    if len(actions) < 2:
        return []
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": actions[0]},
        ),
        *[_request("desktop.safe_shortcut", {"action": action}) for action in actions[1:]],
    ]


def _app_prefix_safe_shortcut_sequence_tool_requests(text: str) -> list[dict[str, Any]]:
    split = _known_app_prefix_split(text)
    if not split:
        return []
    _raw_app, app_name, followup = split
    if app_name not in _BROWSER_APP_NAMES:
        return []
    actions = _safe_shortcut_action_sequence(followup)
    if len(actions) < 2:
        return []
    return [
        _request(
            "app.focus_and_safe_shortcut",
            {"app_name": app_name, "action": actions[0]},
        ),
        *[_request("desktop.safe_shortcut", {"action": action}) for action in actions[1:]],
    ]


def _foreground_safe_shortcut_sequence_tool_requests(text: str) -> list[dict[str, Any]]:
    actions = _safe_shortcut_action_sequence(text)
    if len(actions) < 2:
        return []
    return [_request("desktop.safe_shortcut", {"action": action}) for action in actions]


def _app_open_or_focus_screen_capture_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if not _is_screen_capture_request(followup):
        return []
    return [
        _request(f"app.{mode}", {"app_name": app_name}),
        _request("screen.capture", {"reason": "user asked to capture the screen"}),
    ]


def _app_open_or_focus_browser_search_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _app_open_or_focus_browser_search(text)
    if not parsed:
        return []
    mode, app_name, url, click_index = parsed
    requests = [
        _request(f"app.{mode}", {"app_name": app_name}),
        _request("browser.open_url", {"url": url}),
    ]
    if click_index:
        requests.append(
            _request(
                "browser.click",
                {"selector": f"search-result={click_index}", "click_count": 1},
            )
        )
    return requests


def _app_open_or_focus_browser_search(text: str) -> tuple[str, str, str, int] | None:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, raw_app, app_name, followup = shorthand_match
    else:
        scoped_match = _app_scoped_browser_search_match(text)
        if scoped_match:
            mode, raw_app, app_name, followup = scoped_match
        else:
            split = _known_app_prefix_split(text)
            if not split:
                return None
            raw_app, app_name, followup = split
            mode = "focus"
    if (
        app_name not in _BROWSER_APP_NAMES
        or _looks_like_generic_browser_app_reference(raw_app)
        or _looks_like_window_target(raw_app)
        or _looks_like_common_path_target(raw_app)
    ):
        return None
    if _desktop_safe_shortcut_action(followup):
        return None
    parsed_click = _browser_search_then_click(followup)
    if parsed_click:
        query, engine, index = parsed_click
        return mode, app_name, _browser_search_url_for_query(query, engine), index
    search_url = _browser_search_url(followup)
    if search_url:
        return mode, app_name, search_url, 0
    return None


def _app_scoped_browser_search_match(text: str) -> tuple[str, str, str, str] | None:
    match = re.search(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)\s*"
        r"(?P<app>浏览器|chrome|google\s*chrome|谷歌|谷歌浏览器|safari|firefox|edge|arc|brave)"
        r"\s*(?:里|中|上|内|里面)?\s*(?P<followup>.+)$",
        _strip_query(text),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    raw_app = _strip_query(match.group("app"))
    app_name = _normalize_app_name(raw_app)
    followup = _strip_query(match.group("followup"))
    if app_name not in _BROWSER_APP_NAMES:
        return None
    if not (_browser_search_then_click(followup) or _browser_search_url(followup)):
        return None
    return "focus", raw_app, app_name, followup


def _looks_like_generic_browser_app_reference(value: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", _strip_query(value).lower())
    return compact in {"浏览器", "browser", "webbrowser"}


def _app_open_or_focus_observe_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    return _app_observe_tool_requests(mode, app_name, followup)


def _app_preposed_observe_tool_requests(text: str) -> list[dict[str, Any]]:
    stripped_text = _strip_query(text)
    if _looks_like_app_status_request(stripped_text):
        return []
    match = re.search(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<action>看看|看一下|看下|看一眼|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?)\s*"
        r"(?P<target>[^。！？!?，,]+)$",
        stripped_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return []
    split = _known_app_prefix_split(match.group("target"))
    if not split:
        return []
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return []
    if (
        _desktop_windows_request(match.group("target")) is not None
        or _desktop_windows_request(_strip_query(text)) is not None
    ):
        return []
    action_followup = f"{match.group('action')} {followup}".strip()
    return _app_observe_tool_requests("focus", app_name, action_followup, include_windows=False)


def _app_prefix_observe_tool_requests(text: str) -> list[dict[str, Any]]:
    split = _known_app_prefix_split(text)
    if not split:
        return []
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return []
    return _app_observe_tool_requests("focus", app_name, followup, include_windows=False)


def _app_observe_tool_requests(
    mode: str,
    app_name: str,
    followup: str,
    *,
    include_windows: bool = True,
) -> list[dict[str, Any]]:
    app_request = _request(f"app.{mode}", {"app_name": app_name})

    if app_name in _BROWSER_APP_NAMES:
        if _is_browser_extract_text_request(followup):
            return [app_request, _request("browser.extract_text", {})]
        if _is_browser_screenshot_request(followup):
            return [
                app_request,
                _request("browser.screenshot", {"reason": "user asked to capture the browser page"}),
            ]
        if _is_browser_current_page_request(followup):
            return [app_request, _request("browser.current_page", {})]

    ui_payload = _desktop_ui_elements_request(followup)
    if ui_payload is not None:
        return [app_request, _request("desktop.ui_elements", ui_payload)]

    windows_payload = _desktop_windows_request(followup) if include_windows else None
    if windows_payload is not None:
        scoped_windows = dict(windows_payload)
        scoped_windows.setdefault("app_name", app_name)
        return [app_request, _request("desktop.windows", scoped_windows)]

    if _is_active_window_request(followup):
        return [app_request, _request("desktop.active_window", {})]

    if (
        _is_screen_capture_request(followup)
        or _is_visual_inspection_followup(followup)
        or _is_app_visual_inspection_followup(followup)
    ):
        return [
            app_request,
            _request("screen.capture", {"reason": "user asked to capture the screen"}),
        ]

    return []


def _app_open_or_focus_click_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    parsed = _click_ui_element_then_type(followup)
    if not parsed:
        return []
    click_payload, typed_text, submit_action = parsed
    if _is_search_ui_input_click(click_payload):
        requests = [
            _request(
                f"app.{mode}_and_safe_shortcut",
                {"app_name": app_name, "action": "find"},
            ),
            _request("desktop.safe_type_text", {"text": typed_text}),
        ]
        if submit_action:
            requests.append(_request("desktop.search_submit", {}))
        return requests
    requests = [
        _request(
            f"app.{mode}_and_click_ui_element",
            {"app_name": app_name, **click_payload},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_action:
        requests.append(_request("desktop.submit_foreground", {"action": submit_action}))
    return requests


def _app_open_or_focus_submit_foreground_tool_requests(text: str) -> list[dict[str, Any]]:
    matches: list[tuple[str, str, str, str]] = []
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        matches.append(shorthand_match)
    split = _known_app_prefix_split(text)
    if split:
        raw_app, app_name, followup = split
        matches.append(("focus", raw_app, app_name, followup))
    matches.extend(_app_scoped_foreground_action_matches(text))

    seen: set[tuple[str, str, str, str]] = set()
    for mode, raw_app, app_name, followup in matches:
        item = (mode, raw_app, app_name, followup)
        if item in seen:
            continue
        seen.add(item)
        if (
            not app_name
            or _looks_like_window_target(raw_app)
            or _looks_like_common_path_target(raw_app)
        ):
            continue
        submit_action = _desktop_submit_foreground_action(followup)
        if not submit_action:
            continue
        return [
            _request(f"app.{mode}", {"app_name": app_name}),
            _request("desktop.submit_foreground", {"action": submit_action}),
        ]
    return []


def _app_open_or_focus_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if app_name not in _BROWSER_APP_NAMES and _looks_like_explicit_text_input_target(followup):
        return []
    if _looks_like_explicit_text_input_target(followup) and _typed_text_has_return_followup(
        followup,
        "搜索",
    ):
        return []
    payload = _desktop_type_into_ui_element(followup)
    if not _is_search_text_input_payload(payload):
        return []
    return _search_type_requests(
        payload,
        followup,
        shortcut_tool=f"app.{mode}_and_safe_shortcut",
        shortcut_input={"app_name": app_name, "action": "find"},
    )


def _app_direct_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if shorthand_match:
        mode, _raw_app, app_name, followup = shorthand_match
    else:
        scoped_text = _strip_app_search_scope_prefix(text)
        split = _known_app_prefix_split(scoped_text)
        if not split:
            return []
        _raw_app, app_name, followup = split
        mode = "focus"
    if not app_name or app_name in _BROWSER_APP_NAMES:
        return []
    if _looks_like_explicit_text_input_target(followup):
        return []
    parsed = _app_search_query_from_followup(followup)
    if parsed is None:
        return []
    typed_text, submit_return = parsed
    requests = [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_return:
        requests.append(_request("desktop.search_submit", {}))
    return requests


def _english_app_scoped_search_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _english_app_scoped_search(text)
    if not parsed:
        return []
    app_name, query = parsed
    return [
        _request(
            "app.focus_and_safe_shortcut",
            {"app_name": app_name, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": query}),
    ]


def _english_app_scoped_search(text: str) -> tuple[str, str] | None:
    clean = _strip_query(text)
    patterns = (
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:search|find|look\s+for)\s+(?P<app>[^.!?]+?)\s+"
        r"(?:for|with|about)\s+(?P<query>[^.!?]+)$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:search|find|look\s+for)\s+(?P<query>[^.!?]+?)\s+"
        r"(?:in|inside|on|with|using)\s+(?P<app>[^.!?]+)$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:search|find|look\s+for)\s+(?:in|inside|on|with|using)\s+"
        r"(?P<app>[^.!?]+?)\s+(?:for|about)?\s*(?P<query>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        app_name = _normalize_app_name(raw_app)
        if (
            not app_name
            or not _is_known_local_app_name(raw_app, app_name)
            or app_name in _BROWSER_APP_NAMES
            or (
                app_name == "Music"
                and re.search(
                    r"\b(?:play|start\s+playing)\b|(?:播放|播|放)",
                    clean,
                    flags=re.IGNORECASE,
                )
            )
            or _looks_like_generic_app_open_target(raw_app)
            or _normalize_site_name(raw_app)
        ):
            continue
        query = _strip_search_query(match.group("query"))
        if query:
            return app_name, query
    return None


def _is_known_local_app_name(raw_app: str, app_name: str) -> bool:
    known_compacts = {
        _compact_app_alias(alias)
        for alias in _APP_ALIASES
    } | {
        _compact_app_alias(name)
        for name in _APP_ALIASES.values()
    }
    return (
        _compact_app_alias(raw_app) in known_compacts
        or _compact_app_alias(app_name) in known_compacts
    )


def _music_app_search_play_tool_requests(text: str) -> list[dict[str, Any]]:
    named_play_match = _non_apple_music_named_play_match(text)
    if named_play_match:
        mode, _raw_app, music_app, query = named_play_match
    else:
        shorthand_match = _app_open_or_focus_known_app_followup_match(text)
        if shorthand_match:
            mode, raw_app, app_name, followup = shorthand_match
        else:
            split = _known_app_prefix_split(text)
            if not split:
                return []
            raw_app, app_name, followup = split
            mode = "focus"
        music_app = _known_music_app_name(raw_app) or _known_music_app_name(app_name)
        if not music_app or music_app == "Music":
            return []
        query = _music_app_search_play_query_from_followup(followup)
    if not query:
        return []
    return [
        _request(
            f"app.{mode}_and_safe_shortcut",
            {"app_name": music_app, "action": "find"},
        ),
        _request("desktop.safe_type_text", {"text": query}),
        _request("desktop.search_submit", {}),
        _request("media.music_app_open_and_play", {"app_name": music_app}),
    ]

def _music_app_search_play_query_from_followup(value: str) -> str:
    followup = _strip_query(value)
    patterns = (
        r"^(?:搜索|搜一下|搜|查找|查一下|查查|检索|找一下|找下|找找|找)\s*"
        r"(?P<query>[^。！？!?]+?)\s*"
        r"(?:(?:并且|并|然后|之后|后|再|接着)\s*)?"
        r"(?:播放|播(?!放)|放)(?:一下)?(?:它|这个|这首|这首歌|该歌曲|该曲目)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:开始)?(?:播放|播(?!放)|放)(?:一下)?\s*(?P<play_query>[^。！？!?]+?)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query_en>[^.!?]+?)\s+"
        r"(?:and\s+|then\s+)?(?:play|start\s+playing)"
        r"(?:\s+(?:it|that|this|the\s+(?:song|track)))?[.!?]*$",
        r"^(?:play|start\s+playing)\s+(?P<play_query_en>[^.!?]+?)[.!?]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        raw_query = next((value for value in match.groupdict().values() if value), "")
        query = _strip_music_query_context(raw_query)
        if query and _is_specific_music_query(query):
            return query
    return ""


def _app_prefix_click_type_tool_requests(text: str) -> list[dict[str, Any]]:
    split = _known_app_prefix_split(text)
    if not split:
        split = _known_app_prefix_split(_strip_app_search_scope_prefix(text))
    if not split:
        return []
    raw_app, app_name, followup = split
    if (
        not app_name
        or _looks_like_window_target(raw_app)
        or _looks_like_common_path_target(raw_app)
    ):
        return []
    parsed = _click_ui_element_then_type(followup)
    if not parsed:
        return []
    click_payload, typed_text, submit_action = parsed
    if _is_search_ui_input_click(click_payload):
        requests = [
            _request(
                "app.focus_and_safe_shortcut",
                {"app_name": app_name, "action": "find"},
            ),
            _request("desktop.safe_type_text", {"text": typed_text}),
        ]
        if submit_action:
            requests.append(_request("desktop.search_submit", {}))
        return requests
    requests = [
        _request(
            "app.focus_and_click_ui_element",
            {"app_name": app_name, **click_payload},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_action:
        requests.append(_request("desktop.submit_foreground", {"action": submit_action}))
    return requests


def _strip_app_search_scope_prefix(text: str) -> str:
    return re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在|用|通过|到)\s*",
        "",
        _strip_query(text),
        flags=re.IGNORECASE,
    ).strip()


def _looks_like_explicit_text_input_target(value: str) -> bool:
    return bool(
        re.search(
            r"(?:搜索框|搜索栏|输入框|文本框|地址栏|search\s+(?:box|field|input)|address\s+bar)",
            str(value or ""),
            flags=re.IGNORECASE,
        )
    )


def _app_search_query_from_followup(value: str) -> tuple[str, bool] | None:
    followup = _strip_query(value)
    patterns = (
        r"^(?:搜索(?!框|栏)|搜一下|搜(?!索(?:$|框|栏)|框|栏)|查找(?!框)|查一下|查查|检索|找一下|找下(?!载)|找找|找)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:find|search|look\s+for)\s+(?:for\s+)?(?P<query>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        raw_query = match.group("query")
        if re.search(
            r"(?:然后|并且|并|再|接着|and\s+then|then|and)\s*"
            r"(?:输入|打字|键入|敲入|发送|提交|点击|点|打开|播放|写入|写|粘贴|选择|选中|选取|"
            r"(?:type|enter\s+text|send|submit|click|open|play|write|paste|select|choose)\b)",
            raw_query,
            flags=re.IGNORECASE,
        ):
            return None
        submit_return = _typed_text_has_return_followup(raw_query, "搜索")
        query = re.sub(
            r"\s*(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?"
            r"(?:回车|确认|确定|搜索|查找|检索)$",
            "",
            raw_query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\s*(?:and\s+then|then|and)\s*(?:press\s+)?(?:enter|return|search|find|go)$",
            "",
            query,
            flags=re.IGNORECASE,
        )
        query = _strip_search_query(query)
        if query:
            return query, submit_return
    return None


def _app_find_shortcut_followup(value: str) -> bool:
    return _normalize_named_hotkey_phrase(value) in {
        "查找",
        "打开查找",
        "查找框",
        "打开查找框",
        "搜索",
        "搜索框",
        "搜索栏",
        "搜索输入框",
        "打开搜索",
        "打开搜索框",
        "打开搜索栏",
        "打开搜索输入框",
        "search",
        "find",
        "openfind",
        "openfindbox",
    }


def _app_open_or_focus_browser_action_tool_requests(text: str) -> list[dict[str, Any]]:
    shorthand_match = _app_open_or_focus_known_app_followup_match(text)
    if not shorthand_match:
        return []
    mode, _raw_app, app_name, followup = shorthand_match
    if app_name not in _BROWSER_APP_NAMES:
        return []
    if _app_followup_safe_key(followup):
        return []
    if _app_followup_safe_type_text(followup):
        return []
    app_request = _request(f"app.{mode}", {"app_name": app_name})
    browser_followup = _browser_context_followup(followup)

    click_payload = _browser_click_request(browser_followup)
    if click_payload:
        return [app_request, _request("browser.click", click_payload)]

    type_payload = _browser_type_text_request(browser_followup)
    if type_payload:
        requests = [app_request, _request("browser.type_text", type_payload)]
        selector = str(type_payload.get("selector") or "")
        if _browser_type_text_should_submit(browser_followup, selector):
            requests.append(_request("desktop.search_submit", {}))
        return requests

    return []


def _app_prefix_browser_action_tool_requests(text: str) -> list[dict[str, Any]]:
    split = _known_app_prefix_split(text)
    if not split:
        return []
    raw_app, app_name, followup = split
    if (
        app_name not in _BROWSER_APP_NAMES
        or _looks_like_window_target(raw_app)
        or _looks_like_common_path_target(raw_app)
    ):
        return []
    if _app_followup_safe_key(followup):
        return []
    if _app_followup_safe_type_text(followup):
        return []
    app_request = _request("app.focus", {"app_name": app_name})
    browser_followup = _browser_context_followup(followup)

    click_payload = _browser_click_request(browser_followup)
    if click_payload:
        return [app_request, _request("browser.click", click_payload)]

    type_payload = _browser_type_text_request(browser_followup)
    if type_payload:
        requests = [app_request, _request("browser.type_text", type_payload)]
        selector = str(type_payload.get("selector") or "")
        if _browser_type_text_should_submit(browser_followup, selector):
            requests.append(_request("desktop.search_submit", {}))
        return requests

    return []


def _app_prefix_foreground_action_tool_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    if app_name in _BROWSER_APP_NAMES and _app_prefix_browser_action_tool_requests(text):
        return None
    request = _app_foreground_action_request("focus", app_name, followup)
    if not request:
        return None
    return _request(str(request["tool"]), dict(request["input"]))


def _browser_context_followup(value: str) -> str:
    followup = _strip_query(value)
    if _has_browser_page_context(followup):
        return followup
    return f"网页{followup}"


def _browser_type_text_should_submit(source_text: str, selector: str) -> bool:
    if not _typed_text_has_return_followup(source_text, "搜索"):
        return False
    return bool(
        re.search(r"(?:search|输入|搜索|query|name=\"q\")", selector, flags=re.IGNORECASE)
    )


def _app_scoped_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    request = _app_scoped_ui_action_tool_request(text)
    if not isinstance(request, dict):
        return []
    tool = str(request.get("tool") or "").strip()
    if tool not in {"app.open_and_type_into_ui_element", "app.focus_and_type_into_ui_element"}:
        return []
    payload = request.get("input") if isinstance(request.get("input"), dict) else {}
    if not _is_search_text_input_payload(payload):
        return []
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name:
        return []
    if app_name not in _BROWSER_APP_NAMES and _looks_like_explicit_text_input_target(text):
        return []
    mode = "open" if tool.startswith("app.open") else "focus"
    return _search_type_requests(
        payload,
        text,
        shortcut_tool=f"app.{mode}_and_safe_shortcut",
        shortcut_input={"app_name": app_name, "action": "find"},
    )


def _foreground_click_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    parsed = _click_ui_element_then_type(text)
    if not parsed:
        return []
    click_payload, typed_text, submit_action = parsed
    if not _is_search_ui_input_click(click_payload):
        return []
    requests = [
        _request("desktop.safe_shortcut", {"action": "find"}),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if submit_action:
        requests.append(_request("desktop.search_submit", {}))
    return requests


def _foreground_search_type_tool_requests(text: str) -> list[dict[str, Any]]:
    payload = _desktop_type_into_ui_element(text)
    if not _is_search_text_input_payload(payload):
        return []
    return _search_type_requests(
        payload,
        text,
        shortcut_tool="desktop.safe_shortcut",
        shortcut_input={"action": "find"},
    )


def _search_type_requests(
    payload: dict[str, Any] | None,
    source_text: str,
    *,
    shortcut_tool: str,
    shortcut_input: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    typed_text = str(payload.get("text") or "").strip()
    target = str(payload.get("target") or "").strip()
    if not typed_text or not target:
        return []
    requests = [
        _request(shortcut_tool, shortcut_input),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]
    if _typed_text_has_return_followup(source_text, target):
        requests.append(_request("desktop.search_submit", {}))
    return requests


def _notes_create_and_type_tool_requests(text: str) -> list[dict[str, Any]]:
    typed_text = _notes_create_and_type_text(text)
    if not typed_text:
        return []
    return [
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Notes", "action": "new_note"},
        ),
        _request("desktop.safe_type_text", {"text": typed_text}),
    ]


def _notes_create_tool_request(text: str) -> dict[str, Any] | None:
    body = _notes_create_and_type_text(text)
    if not body:
        return None
    return _request("notes.create", {"body": body})


def _schedule_create_tool_request(text: str) -> dict[str, Any] | None:
    reminder_payload = _reminder_create_payload(text)
    if reminder_payload:
        return _request("reminders.create", reminder_payload)
    calendar_payload = _calendar_event_create_payload(text)
    if calendar_payload:
        return _request("calendar.create_event", calendar_payload)
    return None


def _reminder_create_payload(value: str) -> dict[str, Any] | None:
    body = _reminder_create_body(value)
    if not body:
        return None
    scheduled = _extract_schedule_datetime_and_title(body)
    if scheduled:
        due, title = scheduled
        if title:
            return {"title": title, "due_at": _local_datetime_text(due)}
    day_only = _extract_reminder_date_only_datetime_and_title(body)
    if day_only:
        due, title = day_only
        if title:
            return {"title": title, "due_at": _local_datetime_text(due)}
    title = _reminders_create_and_type_text(value)
    if title:
        return {"title": title}
    clean_body = _strip_schedule_title(body)
    if clean_body and not _looks_like_reminder_title_with_due_time(clean_body):
        return {"title": clean_body}
    return None


def _calendar_event_create_payload(value: str) -> dict[str, Any] | None:
    body = _calendar_event_create_body(value)
    if not body:
        return None
    scheduled = _extract_schedule_datetime_and_title(body)
    if not scheduled:
        return None
    start, title = scheduled
    if not title:
        return None
    end = start + timedelta(hours=1)
    return {
        "title": title,
        "start_at": _local_datetime_text(start),
        "end_at": _local_datetime_text(end),
    }


def _reminder_create_body(value: str) -> str:
    text = str(value or "").strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<body_time_first>[^。！？!?]+?)\s*提醒我\s*(?P<body_time_after>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?提醒我\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒|reminder)\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<body_prefixed>[^。！？!?]+?)\s*(?:的)?(?:提醒事项|提醒|reminder)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:设|设置|定|订)\s*(?:个|一个|一条|一项|新的?)?\s*"
        r"(?P<body_set>[^。！？!?]+?)\s*(?:的)?(?:提醒事项|提醒)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:提醒事项|reminders?)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:新建|创建|添加|新增|加)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒)?\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<body_to_reminders>[^。！？!?]+?)\s*"
        r"(?:加到|添加到|新增到|放到|加入)\s*(?:提醒事项|提醒|reminders?)$",
        r"^(?:please\s+)?remind me\s+(?P<body>[^.!?]+)$",
        r"^(?:please\s+)?(?:create|add|make|set)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
        r"(?:called|named|for|to)?\s*(?P<body>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            groups = match.groupdict()
            if groups.get("body_time_first") and groups.get("body_time_after"):
                return _strip_query(f"{groups['body_time_first']} {groups['body_time_after']}")
            body = _strip_query(
                groups.get("body")
                or groups.get("body_prefixed")
                or groups.get("body_set")
                or groups.get("body_to_reminders")
                or ""
            )
            return "" if _is_blank_reminder_item_label(body) else body
    return ""


def _calendar_event_create_body(value: str) -> str:
    text = str(value or "").strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日历事件|日程|日历日程|calendar event)\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日历|calendar)\s+"
        r"(?P<body_calendar_short>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?P<body_prefixed>[^。！？!?]+?)\s*(?:的)?(?:日历事件|日程|日历日程|calendar event)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)?\s*(?:日历|calendar)\s*"
        r"(?:上|里|中|内)?\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:加|新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日程|事件|event)?\s*[:：]?\s*(?P<body>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<time_first>[^。！？!?]+?)\s*(?:帮我)?\s*(?:在)?\s*"
        r"(?:日历|calendar)\s*(?:上|里|中|内)?\s*"
        r"(?:加|新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日程|事件|event)?\s*(?P<title_after_calendar>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?P<time_first_event>[^。！？!?]+?)\s*(?:帮我)?\s*"
        r"(?:新建|创建|添加|新增|安排)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:日历事件|日程|日历日程|calendar event)\s*(?P<title_after_event>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<body_to_calendar>[^。！？!?]+?)\s*"
        r"(?:加到|添加到|新增到|放到|加入)\s*(?:日历|calendar)$",
        r"^(?:please\s+)?(?:create|add|make)\s+(?:a\s+)?(?:new\s+)?calendar event\s+"
        r"(?:called|named|for)?\s*(?P<body>[^.!?]+)$",
        r"^(?:please\s+)?(?:schedule|add|create|make)\s+(?P<body_to_calendar_en>[^.!?]+?)\s+"
        r"(?:to|on|in)\s+(?:the\s+)?calendar$",
        r"^(?:please\s+)?schedule\s+(?P<body_scheduled_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            groups = match.groupdict()
            if groups.get("time_first") and groups.get("title_after_calendar"):
                return _strip_query(f"{groups['time_first']} {groups['title_after_calendar']}")
            if groups.get("time_first_event") and groups.get("title_after_event"):
                return _strip_query(f"{groups['time_first_event']} {groups['title_after_event']}")
            return _strip_query(
                groups.get("body")
                or groups.get("body_calendar_short")
                or groups.get("body_prefixed")
                or groups.get("body_to_calendar")
                or groups.get("body_to_calendar_en")
                or groups.get("body_scheduled_en")
                or ""
            )
    return ""


_SCHEDULE_TIME_PATTERNS = (
    re.compile(
        r"(?P<full>"
        r"(?:(?:今天|今日|今晚|明天|明日|明晚|后天)\s*)?"
        r"(?:(?:上午|早上|下午|晚上|今晚|中午|凌晨)\s*)?"
        r"(?P<hour>\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*点"
        r"(?:(?P<half>半)|(?P<minute>\d{1,2}|[零一二两三四五六七八九十]{1,3})\s*分?)?"
        r")"
    ),
    re.compile(
        r"(?P<full>"
        r"(?:(?:今天|今日|今晚|明天|明日|明晚|后天)\s*)?"
        r"(?:(?:上午|早上|下午|晚上|今晚|中午|凌晨)\s*)?"
        r"(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{1,2})"
        r")"
    ),
    re.compile(
        r"(?P<full>\b(?P<day_en>today|tomorrow|tonight)\b\s*(?:at\s*)?"
        r"(?P<hour_en>\d{1,2})(?:[:.](?P<minute_en>\d{2}))?\s*"
        r"(?P<ampm_en>a\.?m\.?|p\.?m\.?)?\b)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?P<full>\b(?:at\s*)?(?P<hour_en>\d{1,2})(?:[:.](?P<minute_en>\d{2}))?\s*"
        r"(?P<ampm_en>a\.?m\.?|p\.?m\.?)\s*"
        r"(?P<day_en>today|tomorrow|tonight)\b)",
        flags=re.IGNORECASE,
    ),
)


def _extract_schedule_datetime_and_title(value: str) -> tuple[datetime, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in _SCHEDULE_TIME_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        scheduled = _datetime_from_schedule_match(match)
        if scheduled is None:
            continue
        title = _strip_schedule_title(f"{text[: match.start()]} {text[match.end() :]}")
        if title:
            return scheduled, title
    return None


def _datetime_from_schedule_match(match: re.Match[str]) -> datetime | None:
    groups = match.groupdict()
    if groups.get("hour_en"):
        hour = _parse_schedule_number(groups.get("hour_en"))
        if hour is None or hour < 0 or hour > 23:
            return None
        minute = _parse_schedule_number(groups.get("minute_en") or "0")
        if minute is None or minute < 0 or minute > 59:
            return None
        ampm = str(groups.get("ampm_en") or "").replace(".", "").lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        day = str(groups.get("day_en") or "").lower()
        if day == "tonight" and not ampm and hour < 12:
            hour += 12
        return _datetime_for_english_day_marker(day, hour, minute)

    full = str(match.group("full") or "")
    hour = _parse_schedule_number(match.group("hour"))
    if hour is None or hour < 0 or hour > 23:
        return None
    minute = 30 if match.groupdict().get("half") else _parse_schedule_number(match.groupdict().get("minute") or "0")
    if minute is None or minute < 0 or minute > 59:
        return None
    if any(marker in full for marker in ("下午", "晚上", "今晚", "明晚")) and hour < 12:
        hour += 12
    if "中午" in full and hour < 11:
        hour += 12
    if any(marker in full for marker in ("上午", "早上", "凌晨")) and hour == 12:
        hour = 0
    day_offset = 0
    if "后天" in full:
        day_offset = 2
    elif any(marker in full for marker in ("明天", "明日", "明晚")):
        day_offset = 1
    target_date = date.today() + timedelta(days=day_offset)
    return datetime.combine(target_date, time(hour=hour, minute=minute))


def _extract_reminder_date_only_datetime_and_title(value: str) -> tuple[datetime, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    patterns = (
        r"^(?P<day_cn>今天|今日|今晚|明天|明日|明晚|后天)\s*"
        r"(?:要|去|做|进行|参加|记得|提醒我)?\s*(?P<title_after_cn>[^。！？!?]+)$",
        r"^(?P<title_before_cn>[^。！？!?]+?)\s*(?P<day_cn_tail>今天|今日|今晚|明天|明日|明晚|后天)$",
        r"^(?P<day>today|tomorrow|tonight)\b\s*(?:to\s+)?(?P<title_after>[^.!?]+)$",
        r"^(?P<title_before>[^.!?]+?)\s+\b(?P<day>today|tomorrow|tonight)\b$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        title = _strip_schedule_title(
            groups.get("title_after_cn")
            or groups.get("title_before_cn")
            or groups.get("title_after")
            or groups.get("title_before")
            or ""
        )
        if not title:
            continue
        day_cn = groups.get("day_cn") or groups.get("day_cn_tail")
        if day_cn:
            return _datetime_for_chinese_day_marker(day_cn), title
        day = str(groups.get("day") or "").lower()
        hour = 20 if day == "tonight" else 9
        return _datetime_for_english_day_marker(day, hour, 0), title
    return None


def _datetime_for_chinese_day_marker(day: str) -> datetime:
    marker = str(day or "")
    day_offset = 2 if marker == "后天" else 1 if marker in {"明天", "明日", "明晚"} else 0
    hour = 20 if marker in {"今晚", "明晚"} else 9
    target_date = date.today() + timedelta(days=day_offset)
    return datetime.combine(target_date, time(hour=hour, minute=0))


def _datetime_for_english_day_marker(day: str, hour: int, minute: int) -> datetime:
    marker = str(day or "").lower()
    day_offset = 1 if marker == "tomorrow" else 0
    target_date = date.today() + timedelta(days=day_offset)
    return datetime.combine(target_date, time(hour=hour, minute=minute))


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_schedule_number(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[text]
    if text == "十":
        return 10
    if text.startswith("十"):
        tail = text[1:]
        return 10 + _CHINESE_DIGITS.get(tail, 0)
    if "十" in text:
        head, _, tail = text.partition("十")
        head_value = _CHINESE_DIGITS.get(head)
        if head_value is None:
            return None
        return head_value * 10 + (_CHINESE_DIGITS.get(tail, 0) if tail else 0)
    return None


def _strip_schedule_title(value: str) -> str:
    title = _strip_typed_text(str(value or ""))
    title = re.sub(r"^(?:在|于|到时候|的时候|时|要|去|做|进行|参加|记得|提醒我)\s*", "", title)
    title = re.sub(r"^(?:to|for|about|that|please)\s+", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*(?:的时候|时|在|于)$", "", title).strip()
    return _strip_typed_text(title)


def _local_datetime_text(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def _reminders_create_and_type_tool_requests(text: str) -> list[dict[str, Any]]:
    title = _reminders_create_and_type_text(text)
    if not title:
        return []
    return [
        _request(
            "app.open_and_safe_shortcut",
            {"app_name": "Reminders", "action": "new_reminder"},
        ),
        _request("desktop.safe_type_text", {"text": title}),
    ]


def _reminders_create_and_type_text(value: str) -> str:
    text = str(value or "").strip()
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒|reminder)\s*[:：]?\s*(?P<title>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:提醒事项|reminders?)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:新建|创建|添加|新增|加)\s*(?:一个|一条|一项|新的?)?\s*"
        r"(?:提醒事项|提醒)?\s*[:：]?\s*(?P<title_open>[^。！？!?]+)$",
        r"^(?:please\s+)?(?:create|add|make)\s+(?:a\s+)?(?:new\s+)?reminder\s+"
        r"(?:called|named|for|to)?\s*(?P<title_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        title = _strip_typed_text(
            groups.get("title") or groups.get("title_open") or groups.get("title_en") or ""
        )
        if _is_blank_reminder_item_label(title):
            continue
        if _looks_like_reminder_title_with_due_time(title):
            continue
        if title:
            return title
    return ""


def _is_blank_reminder_item_label(value: str) -> bool:
    return _normalize_named_hotkey_phrase(value) in {
        "提醒",
        "提醒事项",
        "reminder",
        "reminders",
    }


def _looks_like_reminder_title_with_due_time(value: str) -> bool:
    return bool(
        re.search(
            r"(?:今天|明天|后天|上午|下午|晚上|今晚|早上|中午|凌晨|"
            r"\d{1,2}\s*(?:点|:|：)|半小时后|一小时后|[一二两三四五六七八九十]+点)",
            str(value or ""),
        )
        or re.search(r"\b(?:today|tomorrow|tonight|am|pm|a\.m\.|p\.m\.)\b", str(value or ""), flags=re.IGNORECASE)
    )


def _notes_create_and_type_text(value: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)\s*[:：]\s*(?P<text_short_colon>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|到)?\s*(?:备忘录|笔记|note)(?:里|中|上)?\s*"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)?\s*(?P<text_note_create_in_app>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)\s+"
        r"(?!(?:输入|打字|键入|敲入|打入|打上|写入|写下|写上|写|记录|记下|记一下|记上|打)(?:\s|$))"
        r"(?P<text_short>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|到)?\s*(?:备忘录|笔记|note)(?:里|中|上)?\s*"
        r"(?:记一下|记下|记录一下|记录|记上|写下|写入|写)\s*"
        r"(?P<text_note_prefixed>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:记一下|记下|记录一下|记录|记上)\s*(?P<text_memory>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|开|打开)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:(?:新建|创建|添加)\s*(?:一个|一条|一篇|新的?)?\s*(?:备忘录|笔记|note)?\s*)?"
        r"(?:输入|打字|键入|敲入|打入|打上|写入|写下|写上|写|记录|记下|记一下|记上|打)\s*"
        r"(?P<text>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)\s*"
        r"(?:内容|正文)?(?:是|为|:|：)\s*"
        r"(?P<text_content>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:新建|创建|添加|新增)\s*(?:一个|一条|一篇|新的?)?\s*"
        r"(?:备忘录|笔记|note)"
        r"(?P<text_short_inline>[^。！？!?\s][^。！？!?]*)$",
        r"^(?:please\s+)?(?:create|make|open)\s+(?:a\s+)?(?:new\s+)?note\s+"
        r"(?:and\s+)?(?:type|write|enter|record|with|saying)\s+(?P<text_en>[^.!?]+)$",
        r"^(?:please\s+)?(?:add|make|create|take|write|record)\s+(?:a\s+)?(?:new\s+)?note"
        r"(?:\s+(?:to|that\s+says|saying|with))?\s+(?P<text_en_direct>[^.!?]+)$",
        r"^(?:please\s+)?(?:note\s+down|take\s+(?:a\s+)?note(?:\s+of)?)\s+"
        r"(?P<text_en_memory>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, str(value or "").strip(), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        typed_text = _strip_typed_text(
            groups.get("text")
            or groups.get("text_en")
            or groups.get("text_short_colon")
            or groups.get("text_short")
            or groups.get("text_short_inline")
            or groups.get("text_note_create_in_app")
            or groups.get("text_note_prefixed")
            or groups.get("text_memory")
            or groups.get("text_content")
            or groups.get("text_en_direct")
            or groups.get("text_en_memory")
            or ""
        )
        if typed_text:
            return typed_text
    return ""


def _is_search_text_input_payload(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    target = str(payload.get("target") or "").strip()
    role_filter = str(payload.get("role_filter") or "").strip()
    if not str(payload.get("text") or "").strip():
        return False
    if not re.search(r"(?:搜索|查找|检索|search|find|query)", target, flags=re.IGNORECASE):
        return False
    return not role_filter or bool(
        re.search(r"(?:text|field|input|search|输入|文本|搜索)", role_filter, flags=re.IGNORECASE)
    )


def _app_foreground_action_match(
    text: str,
    patterns: tuple[str, ...],
) -> tuple[str, str] | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        followup = _strip_app_foreground_followup_prefix(_strip_query(match.group("followup")))
        if raw_app and followup:
            return raw_app, followup
    return None


def _app_foreground_action_request_from_match(
    mode: str,
    match: tuple[str, str],
) -> dict[str, Any] | None:
    raw_app, followup = match
    if _looks_like_window_target(raw_app) or _looks_like_common_path_target(raw_app):
        return None
    app_name = _normalize_app_name(raw_app)
    if not app_name or _looks_like_generic_app_open_target(raw_app):
        return None
    return _app_foreground_action_request(mode, app_name, followup)


def _app_foreground_action_request(
    mode: str,
    app_name: str,
    followup: str,
) -> dict[str, Any] | None:
    finder_action = _finder_safe_shortcut_action(app_name, followup)
    if finder_action:
        return {
            "tool": f"app.{mode}_and_safe_shortcut",
            "input": {"app_name": app_name, "action": finder_action},
        }
    shortcut_action = (
        _app_command_or_preferences_shortcut_action(app_name, followup)
        or _app_default_new_shortcut_action(app_name, followup)
        or _app_followup_full_screen_shortcut_action(followup)
        or _desktop_safe_shortcut_action(followup)
    )
    if shortcut_action:
        return {
            "tool": f"app.{mode}_and_safe_shortcut",
            "input": {"app_name": app_name, "action": shortcut_action},
        }
    safe_scroll = _desktop_safe_scroll(followup)
    if safe_scroll:
        return {
            "tool": f"app.{mode}_and_safe_scroll",
            "input": {"app_name": app_name, **safe_scroll},
        }
    safe_key = _app_followup_safe_key(followup)
    if safe_key:
        return {
            "tool": f"app.{mode}_and_safe_key",
            "input": {"app_name": app_name, **safe_key},
        }
    safe_click = _desktop_safe_click(followup)
    if safe_click:
        return {
            "tool": f"app.{mode}_and_safe_click",
            "input": {"app_name": app_name, **safe_click},
        }
    hotkey = _desktop_hotkey(followup)
    if hotkey:
        return {
            "tool": f"app.{mode}_and_hotkey",
            "input": {"app_name": app_name, **hotkey},
        }
    click_ui_element = _desktop_click_ui_element(followup, require_context=False)
    if click_ui_element:
        return {
            "tool": f"app.{mode}_and_click_ui_element",
            "input": {"app_name": app_name, **click_ui_element},
        }
    type_into_ui_element = _desktop_type_into_ui_element(followup)
    if type_into_ui_element:
        return {
            "tool": f"app.{mode}_and_type_into_ui_element",
            "input": {"app_name": app_name, **type_into_ui_element},
        }
    typed_text = _app_followup_safe_type_text(followup)
    if typed_text:
        return {
            "tool": f"app.{mode}_and_safe_type_text",
            "input": {"app_name": app_name, "text": typed_text},
        }
    return None


def _app_open_or_focus_known_app_followup_match(text: str) -> tuple[str, str, str, str] | None:
    stripped = _strip_query(text)
    prefix_patterns: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "open",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:打开|启动|运行|拉起|开启|开(?!了|着|没|吗))\s*(?:一下\s*)?",
                r"^(?:please\s+)?(?:open|launch|start)\s+",
            ),
        ),
        (
            "focus",
            (
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*",
                r"^(?:please\s+)?(?:focus|activate|switch\s+to|bring\s+up)\s+",
            ),
        ),
    )
    for mode, patterns in prefix_patterns:
        for pattern in patterns:
            match = re.search(pattern, stripped, flags=re.IGNORECASE)
            if not match:
                continue
            remainder = stripped[match.end() :].strip()
            split = _known_app_followup_split(remainder)
            if split:
                raw_app, app_name, followup = split
                return mode, raw_app, app_name, followup
    postposed_open = _app_postposed_open_followup_match(stripped)
    if postposed_open:
        return postposed_open
    return None


def _app_postposed_open_followup_match(text: str) -> tuple[str, str, str, str] | None:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:打开起来|启动起来|运行起来|拉起来|拉起|开启起来|开起来|打开|启动|运行|开启|开(?!了|着|没|吗))\s*(?:一下|下)?\s*"
        r"(?:并且|并|然后|之后|后(?!退)|再)\s*(?P<followup>.+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:打开起来|启动起来|运行起来|拉起来|拉起|开启起来|开起来|打开|启动|运行|开启|开(?!了|着|没|吗))\s*(?:一下|下)?\s*"
        r"(?P<followup>.+)$",
        r"^(?:please\s+)?(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+"
        r"(?:and|then)\s+(?P<followup>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        followup = _strip_known_app_followup_prefix(match.group("followup"))
        app_name = _normalize_app_name(raw_app)
        if (
            not raw_app
            or not app_name
            or not followup
            or _looks_like_foreground_ui_input_open_prefix(raw_app, followup)
            or _looks_like_window_target(raw_app)
            or _looks_like_common_path_target(raw_app)
            or _looks_like_generic_app_open_target(raw_app)
            or not (
                _looks_like_known_app_followup(followup)
                or _app_command_or_preferences_shortcut_action(app_name, followup)
                or _app_default_new_shortcut_action(app_name, followup)
                or _app_followup_full_screen_shortcut_action(followup)
            )
        ):
            continue
        mode = "focus" if _app_find_shortcut_followup(followup) else "open"
        return mode, raw_app, app_name, followup
    return None


def _looks_like_foreground_ui_input_open_prefix(raw_app: str, followup: str) -> bool:
    compact = re.sub(r"[\s._-]+", "", str(raw_app or "").strip().lower())
    if compact not in {"打", "开", "打开"}:
        return False
    return bool(
        re.match(
            r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
            r"search\s+field|search\s+box|search\s+bar|message\s+field|message\s+box|"
            r"chat\s+box|address\s+bar|text\s+field|textbox|input|field)",
            str(followup or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _known_app_followup_split(value: str) -> tuple[str, str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    for alias, app_name in _known_app_followup_aliases():
        split = _split_compact_app_prefix(text, alias)
        if not split:
            continue
        raw_app, followup = split
        followup = _strip_known_app_followup_prefix(followup)
        if followup and (
            _looks_like_known_app_followup(followup)
            or _finder_safe_shortcut_action(app_name, followup)
            or _app_command_or_preferences_shortcut_action(app_name, followup)
            or _app_default_new_shortcut_action(app_name, followup)
            or _app_followup_full_screen_shortcut_action(followup)
        ):
            return raw_app, app_name, followup
    return None


def _app_default_new_shortcut_action(app_name: str, followup: str) -> str:
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "新建消息",
        "新消息",
        "创建消息",
        "创建一条消息",
        "写消息",
        "写新消息",
        "撰写消息",
        "新建聊天",
        "新聊天",
        "创建聊天",
        "新建会话",
        "新会话",
        "compose",
        "composemessage",
        "newmessage",
        "newchat",
        "newconversation",
        "startconversation",
    }:
        return "new_message" if app_name in _COMMUNICATION_APP_NAMES else ""
    if phrase in {
        "新建邮件",
        "新邮件",
        "创建邮件",
        "创建一封邮件",
        "写邮件",
        "写新邮件",
        "撰写邮件",
        "撰写新邮件",
        "发邮件",
        "发送邮件",
        "composeemail",
        "composemail",
        "newemail",
        "newmail",
        "createemail",
        "createmail",
        "writeemail",
        "writemail",
    }:
        return "new_message" if app_name in _EMAIL_APP_NAMES else ""
    if phrase in {
        "新建会议",
        "新会议",
        "创建会议",
        "创建一个会议",
        "添加会议",
        "添加一个会议",
        "安排会议",
        "安排一个会议",
        "newmeeting",
        "createmeeting",
        "schedulemeeting",
        "makeameeting",
    }:
        return "new_event" if app_name == "Calendar" else ""
    if phrase not in {
        "新建",
        "新建一个",
        "新建一条",
        "新建一项",
        "新建一篇",
        "创建",
        "创建一个",
        "创建一条",
        "创建一项",
        "创建一篇",
        "新增",
        "新增一个",
        "新增一条",
        "新增一项",
        "新增一篇",
        "添加",
        "添加一个",
        "添加一条",
        "添加一项",
        "添加一篇",
        "new",
        "newitem",
        "create",
        "createitem",
        "make",
        "makeitem",
    }:
        return ""
    return {
        "Notes": "new_note",
        "Reminders": "new_reminder",
        "Calendar": "new_event",
    }.get(app_name, "")


def _app_command_or_preferences_shortcut_action(app_name: str, followup: str) -> str:
    clean_app_name = str(app_name or "").strip()
    phrase = _normalize_named_hotkey_phrase(followup)
    if phrase in {
        "命令面板",
        "打开命令面板",
        "指令面板",
        "打开指令面板",
        "命令palette",
        "commandpalette",
        "opencommandpalette",
        "showcommandpalette",
    }:
        if clean_app_name == "Obsidian":
            return "obsidian_command_palette"
        if clean_app_name in {"Visual Studio Code", "Cursor"}:
            return "command_palette"
        return ""
    if phrase in {
        "偏好设置",
        "打开偏好设置",
        "应用偏好设置",
        "打开应用偏好设置",
        "应用设置",
        "打开应用设置",
        "设置",
        "打开设置",
        "preferences",
        "openpreferences",
        "settings",
        "opensettings",
        "appsettings",
        "openappsettings",
    }:
        if clean_app_name and clean_app_name != "System Settings":
            return "preferences"
    return ""


def _known_app_prefix_split(value: str) -> tuple[str, str, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    for alias, app_name in _known_app_followup_aliases():
        split = _split_compact_app_prefix(text, alias)
        if not split:
            continue
        raw_app, followup = split
        followup = _strip_known_app_followup_prefix(followup)
        if raw_app and followup:
            return raw_app, app_name, followup
    return None


def _known_app_followup_aliases() -> list[tuple[str, str]]:
    return _shared_known_app_followup_aliases()


def _split_compact_app_prefix(value: str, alias: str) -> tuple[str, str] | None:
    compact_alias = _compact_app_alias(alias)
    if not compact_alias:
        return None
    consumed = 0
    end_index = 0
    for index, char in enumerate(value):
        if re.fullmatch(r"[\s._-]", char):
            continue
        if consumed >= len(compact_alias):
            break
        if char.lower() != compact_alias[consumed]:
            return None
        consumed += 1
        end_index = index + 1
    if consumed != len(compact_alias):
        return None
    raw_app = value[:end_index].strip()
    followup = value[end_index:].strip()
    if not raw_app or not followup:
        return None
    separator = value[end_index : end_index + 1]
    if (
        re.search(r"[A-Za-z0-9]$", raw_app)
        and re.match(r"[A-Za-z0-9]", followup)
        and not re.fullmatch(r"[\s._-]", separator or "")
    ):
        return None
    return raw_app, followup


def _strip_known_app_followup_prefix(value: str) -> str:
    followup = _strip_app_foreground_followup_prefix(_strip_query(value))
    followup = re.sub(r"^(?:起来)\s*", "", followup, flags=re.IGNORECASE).strip()
    followup = _strip_app_foreground_followup_prefix(followup)
    followup = re.sub(
        r"^(?:在|到)\s*",
        "",
        followup,
        flags=re.IGNORECASE,
    )
    followup = re.sub(
        r"^(?:应用|app|软件|程序)?(?:里|中|内|上(?!滑|滚|翻|一页|一级)|的|里面|界面里|界面中)\s*",
        "",
        followup,
        flags=re.IGNORECASE,
    )
    return followup.strip()


def _looks_like_known_app_followup(value: str) -> bool:
    followup = str(value or "").strip()
    if not followup:
        return False
    return bool(
        _desktop_safe_shortcut_action(followup)
        or _app_followup_full_screen_shortcut_action(followup)
        or _desktop_safe_scroll(followup)
        or _desktop_safe_click(followup)
        or _desktop_click_ui_element(followup, require_context=False)
        or _desktop_type_into_ui_element(followup)
        or _desktop_safe_key(followup)
        or _desktop_hotkey(followup)
        or _desktop_submit_foreground_action(followup)
        or _app_followup_safe_type_text(followup)
        or _app_find_shortcut_followup(followup)
        or _looks_like_command_palette_followup(followup)
        or _app_search_query_from_followup(followup) is not None
        or _desktop_find_query(followup)
        or _browser_click_request(_browser_context_followup(followup)) is not None
        or _browser_type_text_request(_browser_context_followup(followup)) is not None
        or _browser_search_then_click(followup) is not None
        or bool(_browser_search_url(followup))
        or _desktop_ui_elements_request(followup) is not None
        or _desktop_windows_request(followup) is not None
        or _is_active_window_request(followup)
        or _app_followup_close_window_request(followup)
        or _is_browser_extract_text_request(followup)
        or _is_browser_screenshot_request(followup)
        or _is_browser_current_page_request(followup)
        or _is_screen_capture_request(followup)
        or _is_visual_inspection_followup(followup)
        or _is_app_visual_inspection_followup(followup)
        or _safe_shortcut_then_type(followup) is not None
        or bool(_safe_shortcut_action_sequence(followup))
    )


def _is_visual_inspection_followup(value: str) -> bool:
    followup = str(value or "").strip()
    if not followup:
        return False
    lowered = followup.lower()
    return bool(
        re.search(
            r"^(?:看看|看一下|看下|看一眼|查看|读取|读一下|读下|读一读|阅读(?:一下|下)?|观察(?:一下|下)?|识别(?:一下|下)?)\s*"
            r"(?:当前|这个|该)?(?:界面|画面|窗口|屏幕|桌面|应用|app)(?:上|里|中|内)?"
            r"(?:内容|状态|情况)?$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:当前|这个|该|现在)?(?:界面|画面|窗口|屏幕|桌面|应用|app)"
            r"(?:上|里|中|内)?(?:内容|状态|情况)?.{0,4}"
            r"(?:是什么|是啥|有什么|有啥|有哪些|看到什么|长什么样|怎么样)$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:当前|这个|该|现在)?(?:界面|画面|窗口|屏幕|桌面|应用|app)"
            r"(?:上|里|中|内)?$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:你|你现在|现在)?(?:能)?(?:看见|看到|观察到|识别到)"
            r"(?:什么|啥|哪些内容|什么内容)?$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:看看|看一下|看下|查看|读取|读一下|读下|读一读|阅读(?:一下|下)?|观察(?:一下|下)?|识别(?:一下|下)?|看一眼)$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.search(r"\b(?:look at|inspect|view|read)\s+(?:the\s+)?(?:screen|window|ui|interface)\b", lowered)
    )


def _is_bare_visual_inspection_request(value: str) -> bool:
    text = _strip_query(value)
    return bool(
        re.fullmatch(
            r"(?:看看|看一下|看下|看一眼|查看|读取|读一下|读下|读一读|阅读(?:一下|下)?|观察(?:一下|下)?|识别(?:一下|下)?)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_app_visual_inspection_followup(value: str) -> bool:
    followup = _strip_query(value)
    if not followup:
        return False
    return bool(
        re.match(
            r"^(?:看看|看一下|看下|看一眼|查看|检查|读取|读一下|读下|读一读|阅读(?:一下|下)?|观察(?:一下|下)?|识别(?:一下|下)?|看)\s*"
            r"[^。！？!?]{0,40}$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^(?:look\s+at|check|read|view|inspect)\s+(?:my\s+|the\s+)?"
            r"(?:messages?|unread\s+messages?|notifications?|inbox|chats?)$",
            followup,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_possible_app_followup(value: str) -> bool:
    followup = str(value or "").strip()
    if not followup:
        return False
    return bool(
        re.match(
            r"^(?:在|向|给)?(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?"
            r"(?:上|里|中|内|的|里的|中的)?\s*"
            r"(?:输入|填写|键入|打入|填入|写入|写|打字|打上|打|"
            r"搜索|搜一下|搜|查找|查一下|查查|检索|"
            r"点击|点一下|点按|单击|点|按一下|按|双击|"
            r"发送|发出|提交|确认|确定|"
            r"新建|开新|保存|复制|粘贴|全选|撤销|重做|"
            r"滚动|上滑|下滑|向上滚动|向下滚动|向左滚动|向右滚动)",
            followup,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^(?:type|enter|input|fill|search|find|click|press|tap|send|submit|"
            r"save|copy|paste|undo|redo|scroll|new)\b",
            followup,
            flags=re.IGNORECASE,
        )
        or re.match(
            r"^(?:看看|看一下|看下|查看|看|读取|观察|检查)\s*[^。！？!?]*$",
            followup,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            r"(?:蓝牙|bluetooth|wi-?fi|无线网络|网络|声音|音量|显示器|显示|屏幕|"
            r"电池|键盘|鼠标|触控板|trackpad|通知|隐私|安全性|隐私与安全性|"
            r"辅助功能|壁纸|桌面与程序坞|通用|icloud|apple\s*id)(?:设置|偏好)?",
            followup,
            flags=re.IGNORECASE,
        )
    )


def _app_followup_safe_type_text(value: str) -> str:
    typed_text = _desktop_safe_type_text(value)
    if typed_text:
        return typed_text
    text = str(value or "").strip()
    if not text or re.search(r"(?:剪贴板|粘贴板|clipboard)", text, flags=re.IGNORECASE):
        return ""
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:发送|发出|发|说)\s*(?:消息|信息|message)?\s*(?P<send_text>[^。！？!?]+)$",
        r"^(?:send|say)\s+(?P<send_text_en>[^.!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在(?:当前|前台)?(?:窗口|应用|app)?(?:里|中|内|上)?\s*)?"
        r"(?:写入|写下|写上|写|记录|记下|记一下|记上)\s*(?P<text>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<text2>[^。！？!?]+?)\s*"
        r"(?:写入|写下|写上|写|记录|记下|记一下|记上)(?:进去|到当前窗口|到前台)?$",
        r"^(?:write|record|note\s+down)\s+(?P<text_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        typed_text = _strip_typed_text(
            groups.get("send_text")
            or groups.get("send_text_en")
            or groups.get("text")
            or groups.get("text2")
            or groups.get("text_en")
            or ""
        )
        if typed_text:
            return typed_text
    return ""


def _safe_shortcut_then_type(value: str) -> tuple[str, str, bool] | None:
    action_pattern = (
        r"新建标签页|新标签页|打开新标签页|开新标签页|开一个新标签页|"
        r"新建窗口|新窗口|打开新窗口|开新窗口|开一个新窗口|"
        r"新建文档|新文档|新建文件|新文件|开新文档|开一个新文档|开新文件|开一个新文件|"
        r"新建表格|新表格|新建工作簿|新工作簿|"
        r"新建演示文稿|新演示文稿|新建幻灯片|新幻灯片|新建ppt|新ppt|"
        r"新建笔记|新建一个笔记|新建一条笔记|新建一篇笔记|新笔记|"
        r"新建备忘录|新建一个备忘录|新建一条备忘录|新建一篇备忘录|新备忘录|"
        r"新建提醒事项|新建一个提醒事项|新建一条提醒事项|新建一项提醒事项|新建提醒|新提醒|"
        r"新建日程|新建一个日程|新建一条日程|新建日历事件|新建一个日历事件|新日程|"
        r"新建事件|新建一个事件|新事件|"
        r"new\s+tab|new\s+window|new\s+document|new\s+file|new\s+note|"
        r"new\s+reminder|new\s+event|new\s+calendar\s+event|"
        r"make\s+a\s+new\s+document|create\s+a\s+new\s+document|"
        r"make\s+a\s+new\s+file|create\s+a\s+new\s+file|"
        r"make\s+a\s+new\s+note|create\s+a\s+new\s+note|"
        r"make\s+a\s+new\s+event|create\s+a\s+new\s+event|"
        r"make\s+a\s+new\s+calendar\s+event|create\s+a\s+new\s+calendar\s+event|"
        r"make\s+a\s+new\s+reminder|create\s+a\s+new\s+reminder"
    )
    pattern = (
        rf"^(?P<action>{action_pattern})\s*"
        r"(?:(?:并且|并|然后|之后|后|再|and|then)\s*)?"
        r"(?:输入|打字|键入|敲入|打入|打上|写入|写|打|type|enter text)\s*"
        r"(?P<text>[^。！？!?]+)$"
    )
    match = re.search(pattern, str(value or "").strip(), flags=re.IGNORECASE)
    if not match:
        return None
    action = _desktop_safe_shortcut_action(match.group("action"))
    raw_text = match.group("text")
    typed_text = _strip_typed_text(raw_text)
    if not action or not typed_text:
        return None
    return action, typed_text, _typed_text_has_return_followup(raw_text, "")


def _safe_shortcut_action_sequence(value: str) -> list[str]:
    text = _strip_query(value)
    if not text:
        return []
    compact = _normalize_named_hotkey_phrase(text)
    compact_sequences = {
        "全选复制": ["select_all", "copy"],
        "全选并复制": ["select_all", "copy"],
        "全选后复制": ["select_all", "copy"],
        "全选再复制": ["select_all", "copy"],
        "选择全部并复制": ["select_all", "copy"],
        "选择全部后复制": ["select_all", "copy"],
        "复制当前窗口": ["select_all", "copy"],
        "复制当前窗口内容": ["select_all", "copy"],
        "复制当前页面": ["select_all", "copy"],
        "复制当前页面内容": ["select_all", "copy"],
        "copycurrentwindow": ["select_all", "copy"],
        "copycurrentwindowcontents": ["select_all", "copy"],
        "copycurrentpage": ["select_all", "copy"],
        "copycurrentpagecontents": ["select_all", "copy"],
    }
    if compact in compact_sequences:
        return compact_sequences[compact]
    parts = re.split(
        r"(?:[，,；;。]\s*|(?:然后|接着|之后|随后|并且|并|再|后(?!退))\s*|"
        r"\s+(?:and\s+then|then|and)\s+)",
        text,
        flags=re.IGNORECASE,
    )
    actions: list[str] = []
    for part in parts:
        clause = _strip_sequence_clause_prefix(part)
        if not clause:
            continue
        action = _desktop_safe_shortcut_action(clause)
        if not action:
            return []
        actions.append(action)
    return actions if len(actions) >= 2 else []


def _click_ui_element_then_type(value: str) -> tuple[dict[str, Any], str, str] | None:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<label>[^。！？!?，,]+?)(?:里|中|内|上)?\s*"
        r"(?:输入(?!框|栏)|填写|键入|打入|填入|写入|写|打字|打上|打)\s*"
        r"(?P<text>[^。！？!?]+)$",
        r"^(?:(?P<double_en>double\s+click)|click|press|tap)\s+"
        r"(?:the\s+)?(?P<label_en>[^.!?]+?)\s+"
        r"(?:and\s+)?(?:type|enter|input|fill)\s+(?P<text_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, str(value or "").strip(), flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_label = groups.get("label") or groups.get("label_en") or ""
        raw_text = groups.get("text") or groups.get("text_en") or ""
        clean_label = _strip_click_type_label(raw_label)
        target = _strip_desktop_ui_element_label(clean_label) or _strip_desktop_ui_input_target(clean_label)
        typed_text = _strip_typed_text(raw_text)
        if not target or not typed_text:
            continue
        return (
            {
                "target": target,
                "role_filter": _desktop_ui_element_role_filter(raw_label),
                "limit": 80,
                "click_count": 2 if groups.get("double") or groups.get("double_en") else 1,
            },
            typed_text,
            _click_type_submit_action(raw_text, clean_label),
        )
    return None


def _strip_click_type_label(value: str) -> str:
    label = _strip_query(value)
    label = re.sub(
        r"\s*(?:然后|并且|并|之后|随后|再|接着)$",
        "",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(
        r"\s+(?:and\s+then|then|and)$",
        "",
        label,
        flags=re.IGNORECASE,
    )
    return _strip_query(label)


def _click_type_submit_action(raw_text: str, target: str) -> str:
    if _typed_text_has_submit_followup(raw_text) or _safe_type_text_followup_has_send_intent(raw_text):
        return "send"
    if not _typed_text_has_return_followup(raw_text, target):
        return ""
    return "confirm"


def _is_search_ui_input_click(payload: dict[str, Any]) -> bool:
    target = str(payload.get("target") or "").strip()
    role_filter = str(payload.get("role_filter") or "").strip()
    click_count = payload.get("click_count", 1)
    if click_count != 1:
        return False
    if not re.search(r"(?:搜索|查找|检索|search|find|query)", target, flags=re.IGNORECASE):
        return False
    return not role_filter or bool(
        re.search(r"(?:text|field|input|search|输入|文本|搜索)", role_filter, flags=re.IGNORECASE)
    )


def _typed_text_has_return_followup(raw_text: str, target: str) -> bool:
    text = str(raw_text or "").strip()
    if not text:
        return False
    if re.search(
        r"(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?(?:回车|确认|确定)$",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:and\s+then|then|and)\s*(?:press\s+)?(?:enter|return)$",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if target and re.search(r"\s+(?:回车|确认|确定)$", text, flags=re.IGNORECASE):
        return True
    target_text = str(target or "")
    if not re.search(r"(?:搜索|查找|检索|search|find|query)", target_text, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?(?:搜索|查找|检索)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:press\s+)?(?:search|find|go)$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _typed_text_has_submit_followup(raw_text: str) -> bool:
    text = str(raw_text or "").strip()
    return bool(
        re.search(
            r"(?:然后|并且|并|再|接着)\s*(?:发送|发出|提交)$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:and\s+then|then|and)\s*(?:send|submit)$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _app_focus_name(text: str) -> str:
    if _looks_like_finder_destructive_file_request(text):
        return ""
    patterns = (
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:并|然后|后|之后|再)\s*(?:切换到|切到|切回|回到|聚焦|激活|置前|显示|还原)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来|这边|过来))?",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:到|切到|切换到|带到|放到|回到)\s*(?:前台|前面|最前面|最前)",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:切换到|切到|切回|回到|聚焦|激活|置前|带到|带回|移到|放到|切过来|切一下|切下)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来|这边|过来))?",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:到|回到)\s*(?:前台|前面|最前面|最前)",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:切换到|切到|切回|回到|聚焦|激活|置前)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来))?",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:切换到|切到|切回|回到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:切一下|切下)\s*(?P<app>[^。！？!?，,]+)",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:switch back to|go back to|return to)\s+(?P<app>[^.!?]+)",
        r"(?:focus|activate|switch to|bring up)\s+(?P<app>[^.!?]+)",
        r"bring\s+(?P<app>[^.!?]+?)\s+to\s+(?:the\s+)?(?:front|foreground)",
        r"bring\s+(?P<app>[^.!?]+?)\s+up",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_window_target(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_open_target(raw_app):
            continue
        if _looks_like_foreground_text_input_phrase(raw_app):
            continue
        if _is_next_foreground_focus_request(raw_app) or _is_previous_foreground_focus_request(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_show_or_open_name(text: str) -> str:
    if _is_show_all_apps_request(text):
        return ""
    if _desktop_reveal_path(text) or _desktop_open_path(text):
        return ""
    patterns = (
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:并|然后|后|之后|再)\s*(?:切换到|切到|切回|回到|聚焦|激活|置前|显示|还原)"
        r"(?:\s*(?:前台|前面|最前面|最前|前台来|这边|过来))?",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:到|切到|切换到|带到|放到|回到)\s*(?:前台|前面|最前面|最前)",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?"
        r"(?:切换到|切到|切回|回到|聚焦|激活|置前|显示|还原)\s*(?P<app>[^。！？!?，,]+?)"
        r"\s*(?:，|,)?\s*(?:如果|要是)?(?:没|没有|未)(?:打开|启动|运行|开|在运行)"
        r".*(?:打开|启动|运行|拉起|开启)",
        r"(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and\s+)?"
        r"(?:focus|activate|show|bring(?:\s+to\s+front)?)",
        r"(?:focus|activate|switch to|show)\s+(?P<app>[^.!?]+?)\s*,?\s*"
        r"(?:open|launch|start)\s+(?:it\s+)?(?:if\s+(?:needed|not\s+open|closed))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_browser_navigation_followup(text[match.end() :]) and _browser_app_name(raw_app):
            continue
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_screen_observation_target(raw_app):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_generic_app_open_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_focus_window_payload(text: str) -> dict[str, str] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:切换到|切到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)"
        r"\s*的\s*(?:标题(?:包含|为)?|名为|叫)?\s*"
        r"(?P<title>[^。！？!?，,]+?)\s*(?:窗口|window)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:切换到|切到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,]+?)"
        r"\s*(?:标题(?:包含|为)?|名为|叫)\s*"
        r"(?P<title>[^。！？!?，,]+?)\s*(?:窗口|window)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:切换到|切到|聚焦|激活|置前)\s*(?P<app>[^。！？!?，,\s]+?)"
        r"\s+(?P<title>[^。！？!?，,]+?)\s*(?:窗口|window)$",
        r"\b(?:focus|activate|switch to)\s+(?P<app>.+?)\s+window\s+"
        r"(?:(?:titled|called|matching|containing)\s+)?(?P<title>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        raw_title = match.group("title")
        if _looks_like_local_path(_strip_app_name(raw_app)) or _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        title = _strip_window_title(raw_title)
        if app_name and title:
            return {"app_name": app_name, "title_contains": title}
    return None


def _app_quit_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:退出|关闭|关掉|结束|终止)(?:一下|下|掉)?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:退出|关闭|关掉|结束|终止)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:quit|close|exit|shut down|terminate)\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_show_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
        or _desktop_reveal_path(text)
        or _is_show_all_apps_request(text)
    ):
        return ""
    patterns = (
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:显示出来|显示一下|显示(?!器)|调出来|叫出来|还原一下|还原|恢复|取消隐藏)",
        r"(?:把|将)\s*(?P<app>[^。！？!?，,]+?)\s*(?:显示出来|调出来|叫出来|还原|恢复|取消隐藏)",
        r"^(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:显示(?!器)|调出|调出来|叫出|叫出来|还原|恢复|取消隐藏)\s*(?P<app>[^。！？!?，,]+)",
        r"\b(?:show|unhide|restore)\s+(?P<app>[^.!?]+)",
        r"\bbring\s+back\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_browser_navigation_followup(text[match.end() :]) and _browser_app_name(raw_app):
            continue
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_screen_observation_target(raw_app):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_hide_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:隐藏|收起|藏起来|藏起)(?:一下|下)?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:隐藏|收起|藏起)\s*(?P<app>[^。！？!?，,]+)",
        r"\bhide\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_browser_navigation_followup(text[match.end() :]) and _browser_app_name(raw_app):
            continue
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _app_minimize_name(text: str) -> str:
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
    ):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:最小化)(?:一下|下)?",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:最小化)\s*(?P<app>[^。！？!?，,]+)",
        r"\bminimi[sz]e\s+(?P<app>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _looks_like_current_app_scope(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        if _looks_like_generic_app_quit_target(raw_app):
            continue
        app_name = _normalize_app_name(raw_app)
        if app_name:
            return app_name
    return ""


def _terminal_run_payload(text: str) -> dict[str, Any] | None:
    stripped = _strip_query(text)
    if not stripped:
        return None
    terminal_patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:terminal|终端|命令行)\s*"
        r"(?:(?:并且|并|然后|之后|后|再)\s*)?"
        r"(?:运行|执行|跑|run|execute)\s*(?:一下\s*)?(?:命令|指令|command)?\s*[:：]?\s*"
        r"(?P<command>.+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)\s*(?:terminal|终端|命令行|shell)\s*(?:里|中|内|上)?\s*"
        r"(?:运行|执行|跑|run|execute)\s*(?:一下\s*)?(?:命令|指令|command)?\s*[:：]?\s*"
        r"(?P<command>.+)$",
        r"^(?:please\s+)?(?:run|execute)\s+(?P<command>.+?)\s+"
        r"(?:in|with|from)\s+(?:the\s+)?(?:terminal|shell)$",
        r"^(?:terminal|shell)\s+(?:run|execute)\s+(?P<command>.+)$",
    )
    for pattern in terminal_patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        payload = _terminal_run_payload_from_command(match.group("command"), terminal_context=True)
        if payload:
            return payload
    generic_patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:运行|执行|跑)\s*(?:一下\s*)?(?:命令|指令)?\s*[:：]?\s*(?P<command>.+)$",
        r"^(?:please\s+)?(?:run|execute)\s+(?P<command>.+)$",
    )
    for pattern in generic_patterns:
        match = re.search(pattern, stripped, flags=re.IGNORECASE)
        if not match:
            continue
        payload = _terminal_run_payload_from_command(match.group("command"), terminal_context=False)
        if payload:
            return payload
    return None


def _terminal_run_payload_from_command(
    value: str,
    *,
    terminal_context: bool,
) -> dict[str, Any] | None:
    command = _strip_terminal_command(value)
    if not _looks_like_terminal_command(command, terminal_context=terminal_context):
        return None
    payload: dict[str, Any] = {"command": command}
    if _terminal_command_requires_shell(command):
        payload["shell"] = True
    return payload


def _strip_terminal_command(value: str) -> str:
    command = _strip_query(value)
    command = re.sub(r"^(?:命令|指令|command)\s*[:：]?\s*", "", command, flags=re.IGNORECASE)
    command = command.strip()
    for left, right in (("```", "```"), ("`", "`"), ("“", "”"), ("\"", "\""), ("'", "'")):
        if command.startswith(left) and command.endswith(right) and len(command) > len(left) + len(right):
            return command[len(left) : -len(right)].strip()
    return command


def _looks_like_terminal_command(command: str, *, terminal_context: bool) -> bool:
    if not command or len(command) > 400:
        return False
    parts = _terminal_command_parts(command)
    head = str(parts[0] if parts else "").strip()
    if not head:
        return False
    compact_head = re.sub(r"[\s._-]+", "", head.lower())
    if compact_head in _APP_ALIASES and len(parts) <= 1:
        return False
    if re.search(r"[\u4e00-\u9fff]", head):
        return False
    if re.match(r"^(?:一个|一条|某个|这个|那个)?(?:会|能|可以)?(?:失败|成功)?(?:的)?(?:命令|指令|脚本|代码|任务)", command):
        return False
    normalized_head = head.lower()
    if normalized_head.startswith(("./", "../", "/")):
        return True
    if normalized_head in _TERMINAL_COMMAND_HEADS:
        return True
    return bool(terminal_context and re.fullmatch(r"[A-Za-z0-9_./+-]+", head))


def _terminal_command_parts(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _terminal_command_requires_shell(command: str) -> bool:
    return bool(re.search(r"(?:&&|\|\||[|;&<>]|\$\(|`)", command))


def _app_open_name(text: str) -> str:
    if _looks_like_finder_destructive_file_request(text):
        return ""
    media_app = _media_app_open_name(text)
    if media_app:
        return media_app
    known_app_alias = _known_open_app_alias_name(text)
    if known_app_alias:
        return known_app_alias
    permission_settings = _permission_settings_open_name(text)
    if permission_settings:
        return permission_settings
    system_settings_target = _system_settings_open_name(text)
    if system_settings_target:
        return system_settings_target
    if (
        _looks_like_search_request(text)
        or _is_running_apps_request(text)
        or _looks_like_app_status_request(text)
        or _looks_like_schedule_creation_request(text)
        or _desktop_safe_shortcut_action(text)
    ):
        return ""

    patterns = (
        r"^\s*(?:你)?(?:帮我|请|麻烦)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?P<verb>打开|启动|运行|拉起来|拉起|开启|开)\s*(?:了|起来)"
        r"(?:吧|嘛|呢)?[?？。！!]*$",
        r"^\s*(?:你)?(?:帮我|请|麻烦)(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?P<verb>打开|启动|运行|拉起来|拉起|开启|开)\s*(?:了|起来)"
        r"(?:吧|嘛|呢)?[?？。！!]*$",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?P<verb>打开起来|启动起来|运行起来|拉起来|拉起|开启起来|开起来|打开|启动|运行|开启|开)\s*(?:一下|下)?"
        r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"^\s*(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?P<verb>打开|启动|运行|拉起来|拉起|开启|开(?!了|着|没|吗))\s*(?:一下|下)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:起来)?(?=\s*(?:并|然后|之后|再|如果|要是|$|[?？。！!]))",
        r"^\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?P<verb>open|launch|start)\s+"
        r"(?P<app>[^.!?]+?)(?=\s*(?:\b(?:and|then|if)\b|$|[.!?]))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_browser_navigation_followup(text[match.end() :]) and _browser_app_name(raw_app):
            continue
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if match.group("verb") == "拉起" and _looks_like_common_path_target(f"下{raw_app}"):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        finder_app_name = _generic_finder_open_app_name(raw_app)
        if finder_app_name:
            return finder_app_name
        browser_app_name = _generic_browser_open_app_name(raw_app)
        if browser_app_name:
            return browser_app_name
        app_name = _normalize_app_name(raw_app)
        if _looks_like_generic_app_open_target(raw_app):
            continue
        if app_name:
            return app_name
    return ""


def _known_open_app_alias_name(text: str) -> str:
    patterns = (
        r"^\s*(?:你)?(?:帮我|请|麻烦)?(?:直接)?(?:把|将)\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?P<verb>打开|启动|运行|拉起来|拉起|开启|开)\s*(?:了|起来)"
        r"(?:吧|嘛|呢)?[?？。！!]*$",
        r"^\s*(?:你)?(?:帮我|请|麻烦)(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?P<verb>打开|启动|运行|拉起来|拉起|开启|开)\s*(?:了|起来)"
        r"(?:吧|嘛|呢)?[?？。！!]*$",
        r"(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?:把|将)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*"
        r"(?P<verb>打开起来|启动起来|运行起来|拉起来|拉起|开启起来|开起来|打开|启动|运行|开启|开)\s*(?:一下|下)?"
        r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
        r"^\s*(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?(?:直接)?(?P<verb>打开|启动|运行|拉起来|拉起|开启|开(?!了|着|没|吗))\s*(?:一下|下)?\s*"
        r"(?P<app>[^。！？!?，,]+?)\s*(?:起来)?(?=\s*(?:并|然后|之后|再|如果|要是|$|[?？。！!]))",
        r"^\s*(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?P<verb>open|launch|start)\s+"
        r"(?P<app>[^.!?]+?)(?=\s*(?:\b(?:and|then|if)\b|$|[.!?]))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        if _strip_query(text[match.end() :]):
            continue
        raw_app = match.group("app")
        if _looks_like_browser_navigation_followup(text[match.end() :]) and _browser_app_name(raw_app):
            continue
        if _looks_like_local_path(_strip_app_name(raw_app)):
            continue
        if _looks_like_common_path_target(raw_app):
            continue
        if _normalize_site_name(raw_app):
            continue
        if _looks_like_composite_action_target(raw_app):
            continue
        app_name = _known_app_alias_name(raw_app, strip_followup=False)
        if app_name and app_name != "System Settings":
            return app_name
    return ""


def _looks_like_browser_navigation_followup(value: str) -> bool:
    return bool(
        re.match(
            r"\s*(?:并|然后|之后|再)\s*(?:打开|访问|浏览|前往|去|搜索|搜)\s*\S+",
            str(value or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _browser_app_name(value: str) -> str:
    app_name = _generic_browser_open_app_name(value) or _normalize_app_name(value)
    return app_name if app_name in _BROWSER_APP_NAMES else ""


def _system_settings_open_name(text: str) -> str:
    lowered = text.lower()
    if not re.search(
        r"(?:打开|启动|开启|拉起|显示|前往|进入|open|launch|show|go\s+to)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return ""
    if not re.search(
        r"(?:系统设置|系统偏好|设置|偏好|settings?|preferences?|pane|page|面板|页面|权限|permission)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return ""
    return _system_settings_target_name(text)


def _system_settings_tool_target(text: str) -> str:
    return _permission_settings_open_name(text) or _system_settings_open_name(text)


def _direct_system_settings_tool_target(text: str) -> str:
    cleaned = _clean_text(text)
    if (
        not cleaned
        or _looks_like_negative_request(cleaned)
        or _is_desktop_permissions_request(cleaned)
        or _looks_like_explanation_request(cleaned)
        or _looks_like_project_or_design_request(cleaned)
    ):
        return ""
    if re.search(r"(?:看看|看下|查看|检查|有哪些|有什么|选项|按钮|控件|界面)", cleaned):
        return ""
    if _known_open_app_alias_name(cleaned):
        return ""
    return _system_settings_tool_target(cleaned) or _bare_system_settings_open_name(cleaned)


def _bare_system_settings_open_name(text: str) -> str:
    lowered = text.lower()
    open_prefix = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|开启|拉起|显示|前往|进入|去|open|launch|show|go\s+to)\s*"
    )
    suffix = (
        r"\s*(?:设置|权限|settings?|permissions?|pane|page|面板|页面)?"
        r"\s*(?:一下|下)?(?:吧|吗|嘛|呢)?[?？。！!]*$"
    )
    target_patterns = (
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
        (r"(?:siri(?:\s+settings?)?|Siri设置|siri设置)", "Siri"),
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
        (r"(?:隐私与安全性|隐私和安全性|隐私.*安全|隐私|\bprivacy\b|\bsecurity\b)", "隐私与安全性"),
        (r"(?:定位服务|定位|位置服务|\blocation\s+services?\b|\blocation\b)", "定位服务"),
    )
    for pattern, target in target_patterns:
        if re.search(open_prefix + pattern + suffix, lowered, flags=re.IGNORECASE):
            return target
    return ""


def _system_settings_target_name(text: str) -> str:
    lowered = text.lower()
    if re.search(r"(?:蓝牙|\bbluetooth\b)", lowered):
        return "蓝牙"
    if re.search(r"(?:wi-?fi|无线网络|无线局域网)", lowered):
        return "Wi-Fi"
    if re.search(r"(?:网络|\bnetwork\b)", lowered):
        return "网络"
    if re.search(r"(?:辅助功能|无障碍|\baccessibility\b|\bassistive\b)", lowered):
        return "辅助功能权限"
    if re.search(r"(?:屏幕录制|屏幕录像|\bscreen\s+recording\b|\bscreen\s+capture\b)", lowered):
        return "屏幕录制权限"
    if re.search(r"(?:自动化|\bautomation\b|\bapple\s*events?\b)", lowered):
        return "自动化权限"
    if re.search(r"(?:完全磁盘访问|\bfull\s+disk\s+access\b)", lowered):
        return "完全磁盘访问"
    if re.search(r"(?:文件和文件夹|文件与文件夹|\bfiles?\s+and\s+folders?\b)", lowered):
        return "文件和文件夹"
    if re.search(r"(?:输入监控|\binput\s+monitoring\b)", lowered):
        return "输入监控"
    if re.search(r"(?:麦克风|\bmicrophone\b)", lowered):
        return "麦克风"
    if re.search(r"(?:摄像头|相机|\bcamera\b)", lowered):
        return "摄像头"
    if re.search(r"(?:定位服务|定位权限|位置服务|\blocation\s+services?\b|\blocation\b)", lowered):
        return "定位服务"
    if re.search(
        r"(?:隐私与安全性|隐私和安全性|隐私.*安全|系统隐私设置|隐私设置|安全隐私设置|"
        r"桌面权限|桌面执行权限|本地工具权限|\bprivacy\b|\bsecurity\b|"
        r"\bdesktop\s+permissions?\b|\blocal\s+tool\s+permissions?\b)",
        lowered,
    ):
        return "隐私与安全性"
    if re.search(r"(?:显示器|显示设置|\bdisplays?\b|\bdisplay\s+settings?\b)", lowered):
        return "显示器"
    if re.search(r"(?:声音设置|音频设置|\bsound\s+settings?\b|\baudio\s+settings?\b)", lowered):
        return "声音"
    if re.search(r"(?:键盘设置|\bkeyboard\s+settings?\b)", lowered):
        return "键盘"
    if re.search(r"(?:通知设置|\bnotifications?\s+settings?\b)", lowered):
        return "通知"
    if re.search(r"(?:电池设置|电池|\bbattery\s+settings?\b|\bbattery\b)", lowered):
        return "电池"
    if re.search(r"(?:鼠标设置|鼠标|\bmouse\s+settings?\b|\bmouse\b)", lowered):
        return "鼠标"
    if re.search(r"(?:触控板设置|触控板|\btrackpad\s+settings?\b|\btrackpad\b)", lowered):
        return "触控板"
    if re.search(
        r"(?:打印机(?:与|和)?扫描仪设置|打印机设置|打印机|"
        r"\bprinters?(?:\s+(?:and|&)\s+scanners?)?\s+settings?\b|\bprinters?\b)",
        lowered,
    ):
        return "打印机与扫描仪"
    if re.search(r"(?:专注模式设置|专注模式|\bfocus\s+settings?\b|\bfocus\b)", lowered):
        return "专注模式"
    if re.search(r"(?:墙纸设置|壁纸设置|墙纸|壁纸|\bwallpaper\s+settings?\b|\bwallpaper\b)", lowered):
        return "墙纸"
    if re.search(
        r"(?:桌面(?:与|和)程序坞设置|桌面(?:与|和)程序坞|程序坞设置|程序坞|"
        r"\bdesktop\s+(?:and|&)\s+dock\s+settings?\b|\bdock\s+settings?\b)",
        lowered,
    ):
        return "桌面与程序坞"
    if re.search(
        r"(?:屏幕保护程序设置|屏幕保护设置|屏幕保护程序|屏幕保护|"
        r"\bscreen\s+saver\s+settings?\b|\bscreensaver\s+settings?\b)",
        lowered,
    ):
        return "屏幕保护程序"
    if re.search(r"(?:siri(?:\s+settings?)?|Siri设置|siri设置)", lowered):
        return "Siri"
    if re.search(
        r"(?:语言(?:与|和)地区设置|语言(?:与|和)地区|"
        r"\blanguage\s+(?:and|&)\s+region\s+settings?\b)",
        lowered,
    ):
        return "语言与地区"
    if re.search(
        r"(?:日期(?:与|和)时间设置|日期(?:与|和)时间|"
        r"\bdate\s+(?:and|&)\s+time\s+settings?\b)",
        lowered,
    ):
        return "日期与时间"
    if re.search(r"(?:软件更新|\bsoftware\s+updates?\b|\bsoftware\s+update\s+settings?\b)", lowered):
        return "软件更新"
    if re.search(r"(?:储存空间设置|存储空间设置|储存空间|存储空间|\bstorage\s+settings?\b|\bstorage\b)", lowered):
        return "储存空间"
    if re.search(r"(?:登录项设置|登录项|\blogin\s+items?\s+settings?\b|\blogin\s+items?\b)", lowered):
        return "登录项"
    if re.search(
        r"(?:用户(?:与|和)群组设置|用户(?:与|和)群组|"
        r"\busers?\s+(?:and|&)\s+groups?\s+settings?\b)",
        lowered,
    ):
        return "用户与群组"
    if re.search(
        r"(?:系统设置|系统偏好|系统偏好设置|设置|偏好|system\s+settings?|system\s+preferences?|settings?|preferences?)",
        lowered,
    ):
        return "系统设置"
    return ""


def _permission_settings_open_name(text: str) -> str:
    lowered = text.lower()
    if re.search(
        r"(?:桌面(?:与|和)程序坞|程序坞|\bdesktop\s+(?:and|&)\s+dock\b|\bdock\s+settings?\b)",
        lowered,
    ):
        return ""
    if re.search(
        r"(?:打开|启动|开启|拉起|显示|前往|进入|去|修复|修一下|修下|处理|解决).{0,20}"
        r"(?:桌面权限|桌面执行权限|本地工具权限|需要的权限|缺少的权限|权限设置|权限页面|"
        r"屏幕录制|辅助功能|自动化|输入监控|完全磁盘访问|文件和文件夹|摄像头|相机|麦克风|"
        r"定位服务|定位权限|位置服务|隐私与安全性|隐私.*安全)",
        text,
    ):
        return _permission_settings_target_name(text) or "隐私与安全性"
    if re.search(
        r"\b(?:open|launch|show|fix|repair|resolve)\s+(?:desktop|missing|required|permission|permissions)"
        r".{0,24}(?:settings|page|pane)\b",
        lowered,
    ):
        return _permission_settings_target_name(text) or "隐私与安全性"
    english_target = _permission_settings_target_name(text)
    if english_target and re.search(
        r"\b(?:open|launch|show|go\s+to|fix|repair|resolve)\b.{0,24}"
        r"(?:privacy|security|accessibility|automation|screen\s+recording|screen\s+capture|"
        r"full\s+disk\s+access|input\s+monitoring|camera|microphone|files?\s+and\s+folders?|"
        r"location\s+services?|location)"
        r".{0,24}(?:settings|permissions?|pane|page)?\b",
        lowered,
    ):
        return english_target
    return ""


def _permission_settings_target_name(text: str) -> str:
    lowered = text.lower()
    if re.search(r"(?:辅助功能|无障碍|\baccessibility\b|\bassistive\b)", lowered):
        return "辅助功能权限"
    if re.search(r"(?:屏幕录制|屏幕录像|\bscreen\s+recording\b|\bscreen\s+capture\b)", lowered):
        return "屏幕录制权限"
    if re.search(r"(?:自动化|\bautomation\b|\bapple\s*events?\b)", lowered):
        return "自动化权限"
    if re.search(r"(?:完全磁盘访问|\bfull\s+disk\s+access\b)", lowered):
        return "完全磁盘访问"
    if re.search(r"(?:文件和文件夹|文件与文件夹|\bfiles?\s+and\s+folders?\b)", lowered):
        return "文件和文件夹"
    if re.search(r"(?:输入监控|\binput\s+monitoring\b)", lowered):
        return "输入监控"
    if re.search(r"(?:麦克风|\bmicrophone\b)", lowered):
        return "麦克风"
    if re.search(r"(?:摄像头|相机|\bcamera\b)", lowered):
        return "摄像头"
    if re.search(r"(?:定位服务|定位权限|位置服务|\blocation\s+services?\b|\blocation\b)", lowered):
        return "定位服务"
    if re.search(
        r"(?:隐私与安全性|隐私和安全性|隐私.*安全|系统隐私设置|隐私设置|安全隐私设置|"
        r"桌面权限|桌面执行权限|本地工具权限|\bprivacy\b|\bsecurity\b|"
        r"\bdesktop\s+permissions?\b|\blocal\s+tool\s+permissions?\b)",
        lowered,
    ):
        return "隐私与安全性"
    return ""


def _media_app_open_name(text: str) -> str:
    lowered = text.lower()
    if not re.search(r"(?:播放|放|打开|启动|运行|open|launch|start|play)", lowered):
        return ""
    named_play_app = _non_apple_music_named_play_app_name(text)
    if named_play_app:
        return named_play_app
    generic_play_app = _music_app_generic_play_open_name(text)
    if generic_play_app:
        return generic_play_app
    for pattern in (
        r"^(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:播放一下|播一下|放一下|播放|播|放|打开|启动|运行)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?P<app>[^.!?]+?)\s+(?:play|start|open|launch)[.!?]*$",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _known_music_app_name(match.group("app"))
        if app_name:
            return app_name
    for pattern in (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:播放|放|打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+)",
        r"(?:open|launch|start|play)\s+(?P<app>[^.!?]+)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _known_music_app_name(match.group("app"))
        if app_name:
            return app_name
    if re.search(r"apple\s*music", lowered):
        return "Music"
    if re.search(r"(?:播放|放|打开|启动|运行)\s*(?:一下\s*)?(?:音乐|music)(?:应用|app|软件|程序)?\s*$", lowered):
        return "Music"
    if re.search(r"(?:open|launch|start|play)\s+music(?:\s+app)?\s*$", lowered):
        return "Music"
    return ""


def _music_app_open_and_play_app_name(text: str) -> str:
    named_app = _non_apple_music_named_play_app_name(text)
    if named_app:
        return named_app
    app_name = _music_app_generic_play_open_name(text)
    if app_name and app_name != "Music":
        return app_name
    return ""


def _non_apple_music_named_play_app_name(text: str) -> str:
    match = _non_apple_music_named_play_match(text)
    return match[2] if match else ""


def _non_apple_music_named_play_match(text: str) -> tuple[str, str, str, str] | None:
    patterns: tuple[tuple[str, str], ...] = (
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:让|叫)\s*"
            r"(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:播放|播(?!放)|放)\s*(?P<query>[^。！？!?，,]+)$",
        ),
        (
            "focus",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|用|通过)\s*(?P<app>[^。！？!?，,]+?)\s*(?:里|中|上|内)?\s*"
            r"(?:播放|播(?!放)|放)\s*(?P<query>[^。！？!?，,]+)$",
        ),
        (
            "open",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+?)\s*"
            r"(?:(?:并|然后|后|之后|再)\s*)?(?:开始)?(?:播放|播(?!放)|放)\s*(?P<query>[^。！？!?，,]+)$",
        ),
        (
            "focus",
            r"^(?P<app>[^。！？!?，,]+?)\s*(?:播放|播(?!放)|放)\s*(?P<query>[^。！？!?，,]+)$",
        ),
        (
            "focus",
            r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
            r"(?:play|start\s+playing)\s+(?P<query>[^.!?]+?)\s+"
            r"(?:in|on|with|using)\s+(?P<app>[^.!?]+)$",
        ),
        (
            "open",
            r"^(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and\s+)?"
            r"(?:play|start\s+playing)\s+(?P<query>[^.!?]+)$",
        ),
        (
            "focus",
            r"^(?P<app>[^.!?]+?)\s+(?:play|start\s+playing)\s+(?P<query>[^.!?]+)$",
        ),
    )
    for mode, pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = _strip_query(match.group("app"))
        app_name = _known_music_app_name(raw_app)
        query = _strip_music_query_context(match.group("query"))
        if app_name and app_name != "Music" and query and _is_specific_music_query(query):
            return mode, raw_app, app_name, query
    return None


def _known_music_app_name(value: str) -> str:
    known_name = known_music_app_name(value)
    if known_name:
        return known_name
    app_name = _normalize_app_name(value)
    raw_compact = compact_music_app_name(_strip_app_name(value))
    app_compact = compact_music_app_name(app_name)
    if is_known_music_app_compact(raw_compact) or is_known_music_app_compact(app_compact):
        return app_name
    return ""


def _music_app_generic_play_open_name(text: str) -> str:
    if re.search(
        r"(?:搜索|搜一下|搜|查找|查一下|查查|检索|找一下|找下|找找|"
        r"\bsearch\b|\bfind\b|\blook\s+up\b)",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        return ""
    patterns = (
        r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:让|叫)?\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:随便|随机)?(?:开始)?"
        r"(?:(?:播放|播|放)(?:一下)?(?:音乐|music|歌|歌曲)?|"
        r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲|东西)?|"
        r"(?:来|放|播放|播)(?:个|一个)(?:东西)|"
        r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?|"
        r"(?:听听|听一下|听下|听))"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)\s*(?P<app>[^。！？!?，,]+?)\s*(?:里|中|上|内)?\s*"
        r"(?:随便|随机)?(?:开始)?"
        r"(?:(?:播放|播|放)(?:一下)?(?:音乐|music|歌|歌曲)?|"
        r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲|东西)?|"
        r"(?:来|放|播放|播)(?:个|一个)(?:东西)|"
        r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?|"
        r"(?:听听|听一下|听下|听))"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:给我|帮我|请|麻烦)?\s*(?:随便|随机)?"
        r"(?:(?:播放|播|放)(?:一下)?(?:音乐|music|歌|歌曲)?|"
        r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲|东西)?|"
        r"(?:来|放|播放|播)(?:个|一个)(?:东西)|"
        r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:把|将)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:一下)?\s*"
        r"(?:(?:并|然后|后|之后|再|接着)\s*)?(?:随便|随机)?(?:开始)?"
        r"(?:(?:播放|播|放)(?:一下)?(?:音乐|music|歌|歌曲)?|"
        r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲|东西)?|"
        r"(?:来|放|播放|播)(?:个|一个)(?:东西)|"
        r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:(?:并|然后|后|之后|再)\s*)?(?:随便|随机)?(?:开始)?"
        r"(?:(?:播放|播|放)(?:一下)?(?:音乐|music|歌|歌曲)?|"
        r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲|东西)?|"
        r"(?:来|放|播放|播)(?:个|一个)(?:东西)|"
        r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:play|start\s+playing)\s+(?:music|songs?|something)\s+"
        r"(?:in|on|with|using)\s+(?P<app>[^.!?]+)[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:open|launch|start)\s+(?P<app>[^.!?]+?)\s+(?:and\s+)?"
        r"(?:play|start\s+playing)(?:\s+(?:music|songs?|something|anything|a\s+song|a\s+track|some\s+music))?[.!?]*$",
        r"^(?P<app>[^.!?]+?)\s+"
        r"(?:play|start\s+playing)"
        r"(?:\s+(?:music|songs?|something|anything|a\s+song|a\s+track|some\s+music))?[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:play|start\s+playing)\s+(?P<app>[^.!?]+?)[.!?]*$",
        r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:播放|播|放)(?:一下|一个|个)?\s*(?P<app>[^。！？!?，,]+?)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _known_music_app_name(match.group("app"))
        if app_name:
            return app_name
    return ""


def _looks_like_finder_destructive_file_request(text: str) -> bool:
    split = _known_app_prefix_split(text)
    if not split:
        return False
    raw_app, app_name, followup = split
    if (app_name != "Finder" and _normalize_app_name(raw_app) != "Finder") or not followup:
        return False
    return bool(
        re.search(
            r"(?:删除|删掉|删了|移到废纸篓|移入废纸篓|扔到废纸篓|放到废纸篓|"
            r"移到垃圾桶|移入垃圾桶|扔到垃圾桶|放到垃圾桶|delete|trash|move\s+to\s+trash)",
            followup,
            flags=re.IGNORECASE,
        )
    )


def _normalize_app_name(value: str) -> str:
    app = _strip_app_name(value)
    if not app:
        return ""
    if _normalize_url(app):
        return ""
    known_alias = _known_app_alias_name(app)
    if known_alias:
        return known_alias
    return app


def _known_app_alias_name(value: str, *, strip_followup: bool = True) -> str:
    app = _strip_app_name(value) if strip_followup else _strip_app_alias_candidate(value)
    if not app:
        return ""
    candidates = [app]
    article_stripped = re.sub(r"^(?:a|an|the)\s+", "", app, flags=re.IGNORECASE).strip()
    if article_stripped and article_stripped != app:
        candidates.append(article_stripped)
    for candidate in candidates:
        compact = re.sub(r"[\s._-]+", "", candidate.lower())
        if compact in _APP_ALIASES:
            return _APP_ALIASES[compact]
    return ""


def _strip_app_alias_candidate(value: str) -> str:
    app = _strip_query(value)
    app = re.sub(r"^(?:一下|下(?!载)|这个|那个)\s*", "", app)
    app = re.sub(r"\s*(?:的|里|中|内|上|里面|里边|内里)$", "", app)
    app = re.sub(
        r"\s*(?:应用|app|软件|程序|客户端|桌面版|桌面客户端|client|desktop\s*app|desktop\s*client)$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = _strip_polite_suffix(app)
    return app.strip()


def _generic_browser_open_app_name(value: str) -> str:
    app = _strip_app_name(value)
    if not app:
        return ""
    compact = re.sub(r"[\s._-]+", "", app.lower())
    if compact in {
        "网页",
        "一个网页",
        "空白网页",
        "网站",
        "一个网站",
        "网址",
        "链接",
        "本地网页",
        "本地网站",
        "本地页面",
        "浏览器网页",
        "浏览器页面",
        "webpage",
        "awebpage",
        "website",
        "awebsite",
        "url",
        "link",
        "blankpage",
        "localpage",
        "browserpage",
    }:
        return "Google Chrome"
    return ""


def _generic_finder_open_app_name(value: str) -> str:
    app = _strip_app_name(value)
    if not app:
        return ""
    compact = re.sub(r"[\s._-]+", "", app.lower())
    if compact in {
        "文件夹",
        "一个文件夹",
        "文件浏览器",
        "文件管理器",
        "folder",
        "afolder",
        "filebrowser",
        "filemanager",
    }:
        return "Finder"
    return ""


def _strip_app_name(value: str) -> str:
    app = _strip_query(value)
    app = _strip_app_foreground_followup(app)
    app = re.sub(r"^(?:一下|下(?!载)|这个|那个)\s*", "", app)
    app = re.sub(r"\s*(?:的|里|中|内|上|里面|里边|内里)$", "", app)
    app = re.sub(
        r"\s*(?:应用|app|软件|程序|客户端|桌面版|桌面客户端|client|desktop\s*app|desktop\s*client)$",
        "",
        app,
        flags=re.IGNORECASE,
    )
    app = _strip_polite_suffix(app)
    return app.strip()


def _strip_app_foreground_followup(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|后|再)\s*"
        r"(?:输入|打字|键入|敲入|打入|打上|打|写入|写|复制|粘贴|全选|撤销|重做|"
        r"查找|打开查找|新建标签页|新标签页|打开新标签页|新建窗口|新窗口|打开新窗口|"
        r"刷新|返回上一页|回到上一页|后退|前进).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and|then)\s+"
        r"(?:type|enter text|copy|paste|select all|undo|redo|find|new tab|new window|"
        r"refresh|reload|go back|back|go forward|forward).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    known_split = _known_app_followup_split(text)
    if known_split:
        raw_app, _app_name, _followup = known_split
        if raw_app:
            return raw_app.strip()
    known_prefix = _known_app_prefix_split(text)
    if known_prefix:
        raw_app, _app_name, followup = known_prefix
        if raw_app and _looks_like_possible_app_followup(followup):
            return raw_app.strip()
    return text.strip()


def _strip_app_foreground_followup_prefix(value: str) -> str:
    return re.sub(
        r"^(?:并且|并|然后|之后|后(?!退)|再|and|then)\s*",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _looks_like_generic_app_open_target(value: str) -> bool:
    app = _strip_app_name(value)
    if not app:
        return True
    compact = re.sub(r"[\s._-]+", "", app.lower())
    if compact in _APP_ALIASES:
        return False
    if compact in {
        "窗口",
        "当前窗口",
        "这个窗口",
        "新窗口",
        "新建窗口",
        "标签页",
        "当前标签页",
        "这个标签页",
        "新标签页",
        "新建标签页",
        "window",
        "currentwindow",
        "thiswindow",
        "newwindow",
        "tab",
        "currenttab",
        "thistab",
        "newtab",
        "权限",
        "这个权限",
        "当前权限",
        "permission",
        "permissions",
        "thispermission",
        "currentpermission",
        "能否",
        "能不能",
        "可以",
        "帮我",
        "请",
        "麻烦",
        "本地",
        "local",
        "项目",
        "项目文件夹",
        "项目目录",
        "工作区",
        "当前项目",
        "当前仓库",
        "仓库目录",
        "project",
        "projectfolder",
        "workspace",
        "currentproject",
        "currentrepo",
        "repofolder",
    }:
        return True
    lowered = app.lower()
    if re.search(r"(?:命令|指令|脚本|代码|任务|测试)", lowered):
        return True
    if re.search(r"\b(?:command|shell|script|code|test)\b", lowered):
        return True
    if _looks_like_composite_action_target(app):
        return True
    if re.fullmatch(r"(?:一个|一条|某个|这个|那个).+", app):
        return True
    return False


def _looks_like_composite_action_target(value: str) -> bool:
    target = str(value or "").strip()
    if not target:
        return False
    return bool(
        re.search(
            r"(?:并|然后|之后|再|如果|要是).{0,24}"
            r"(?:打开|启动|运行|拉起|开启|访问|浏览|前往|搜索|搜|查|切换|切到|"
            r"聚焦|激活|置前|显示|还原|播放|放)",
            target,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:and|then|if)\b.{0,32}"
            r"\b(?:open|launch|start|visit|browse|search|focus|activate|show|play)\b",
            target,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_generic_app_quit_target(value: str) -> bool:
    app = _strip_app_name(value)
    if not app:
        return True
    compact = re.sub(r"[\s._-]+", "", app.lower())
    if compact in _APP_ALIASES:
        return False
    if compact in {
        "窗口",
        "当前窗口",
        "这个窗口",
        "当前页面",
        "这个页面",
        "标签页",
        "当前标签页",
        "window",
        "currentwindow",
        "thiswindow",
        "tab",
        "currenttab",
        "page",
        "currentpage",
    }:
        return True
    if re.search(r"(?:窗口|标签页|页面)", app):
        return True
    if re.search(r"\b(?:window|tab|page)\b", app.lower()):
        return True
    return _looks_like_generic_app_open_target(value)


def _looks_like_current_app_scope(value: str) -> bool:
    app = _strip_app_name(value).strip().lower()
    app = re.sub(r"^(?:the|an|a)\s+", "", app).strip()
    compact = re.sub(r"[\s._-]+", "", app.lower())
    return compact in {
        "当前",
        "现在",
        "前台",
        "这个",
        "该",
        "当前应用",
        "前台应用",
        "当前app",
        "前台app",
        "current",
        "foreground",
        "active",
        "this",
        "currentapp",
        "foregroundapp",
        "activeapp",
        "thisapp",
        "currentapplication",
        "foregroundapplication",
        "activeapplication",
        "thisapplication",
    }


def _looks_like_foreground_text_input_phrase(value: str) -> bool:
    text = _strip_query(value)
    return bool(
        re.match(
            r"^(?:输入|打字|键入|敲入|打入|打上|写入|写|打)(?:\s|$)",
            text,
            flags=re.IGNORECASE,
        )
        or re.match(r"^(?:type|enter|input|write)\s+", text, flags=re.IGNORECASE)
    )


def _looks_like_common_path_target(value: str) -> bool:
    app = _strip_app_name(value)
    return bool(common_desktop_path_alias(app))


def _looks_like_window_target(value: str) -> bool:
    text = str(value or "")
    return bool(re.search(r"(?:窗口|window)", text, flags=re.IGNORECASE))


def _strip_window_title(value: str) -> str:
    title = _strip_query(value)
    title = re.sub(r"^(?:标题|title|named|called|matching|containing)\s*", "", title, flags=re.IGNORECASE)
    return _strip_query(title)


def _apple_music_search_play_query(text: str) -> str:
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|运行|拉起|开启)\s*(?:一下\s*)?"
        r"(?:apple\s*music|music|苹果音乐|音乐)(?:应用|app|软件|程序)?\s*"
        r"(?:(?:并且|并|然后|之后|后|再|接着)\s*)?"
        r"(?:搜索|搜|查找|找|检索)(?:一下|下)?\s*(?P<query_open>[^。！？!?，,]+?)\s*"
        r"(?:(?:并且|并|然后|之后|后|再|接着)\s*)?"
        r"(?:播放|播|放)(?:一下)?(?:它|这个|这首|这首歌|该歌曲|该曲目)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)?\s*(?:apple\s*music|music|苹果音乐|音乐)"
        r"(?:应用|app|软件|程序)?(?:里|中|上|内|里面)?\s*"
        r"(?:搜索|搜|查找|找|检索)(?:一下|下)?\s*(?P<query>[^。！？!?，,]+?)\s*"
        r"(?:(?:并且|并|然后|之后|后|再|接着)\s*)?"
        r"(?:播放|播|放)(?:一下)?(?:它|这个|这首|这首歌|该歌曲|该曲目)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:搜索|搜|查找|找|检索)(?:一下|下)?\s*(?P<query2>[^。！？!?，,]+?)\s*"
        r"(?:在|用|通过)\s*(?:apple\s*music|music|苹果音乐|音乐)"
        r"(?:应用|app|软件|程序)?(?:里|中|上|内|里面)?\s*"
        r"(?:(?:并且|并|然后|之后|后|再|接着)\s*)?"
        r"(?:播放|播|放)(?:一下)?(?:它|这个|这首|这首歌|该歌曲|该曲目)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
        r"^(?:apple\s*music|music(?:\s+app)?)\s+"
        r"(?:search|find|look\s+up)\s+(?P<query3>[^.!?]+?)\s+"
        r"(?:and\s+)?(?:play|start\s+playing)(?:\s+(?:it|that|this|the\s+(?:song|track)))?[.!?]*$",
        r"^(?:apple\s*music|music(?:\s+app)?)\s+"
        r"(?:play|start\s+playing)\s+(?P<query_app_first>[^.!?]+?)[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:play|start\s+playing)\s+(?:(?:in|on|with|using)\s+)?"
        r"(?:apple\s*music|music)(?:\s+app)?\s+(?P<query_app_after>[^.!?]+?)[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:open|launch|start)\s+(?:apple\s*music|music)(?:\s+app)?\s+"
        r"(?:(?:and|then)\s+)?(?:search|find|look\s+up)\s+(?:for\s+)?"
        r"(?P<query_open_en>[^.!?]+?)\s+"
        r"(?:and\s+)?(?:play|start\s+playing)(?:\s+(?:it|that|this|the\s+(?:song|track)))?[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query4>[^.!?]+?)\s+"
        r"(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?\s+"
        r"(?:and\s+)?(?:play|start\s+playing)(?:\s+(?:it|that|this|the\s+(?:song|track)))?[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:search|find|look\s+up)\s+(?:in|on|with|using\s+)?"
        r"(?:apple\s*music|music)(?:\s+app)?\s+(?:for\s+)?(?P<query6>[^.!?]+?)\s+"
        r"(?:and\s+)?(?:play|start\s+playing)(?:\s+(?:it|that|this|the\s+(?:song|track)))?[.!?]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?\s+"
        r"(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query5>[^.!?]+?)\s+"
        r"(?:and\s+)?(?:play|start\s+playing)(?:\s+(?:it|that|this|the\s+(?:song|track)))?[.!?]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_query = next((value for value in match.groupdict().values() if value), "")
        query = _strip_music_query_context(raw_query)
        if query and _is_specific_music_query(query):
            return query
    return ""


def _music_query(text: str) -> str:
    if _looks_like_window_management_action(text):
        return ""
    if _is_apple_music_status_request(text):
        return ""
    if _looks_like_app_launch_pull_up_request(text):
        return ""
    if (
        _apple_music_search_play_query(text)
        or _looks_like_generic_music_play_request(text)
        or _looks_like_scoped_generic_music_play_request(text)
        or _music_app_generic_play_open_name(text)
        or _non_apple_music_named_play_app_name(text)
    ):
        return ""
    patterns = (
        r"(?:play|put(?:\s+on)?)\s+(?P<query>[^.!?]+?)\s+(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?",
        r"^(?:帮我|请|麻烦)?(?:直接)?(?!播放|播|放|来)"
        r"(?P<query_song_first>[^。！？!?，,]+?)\s*"
        r"(?:播放|播|放)(?:一下|下|一首|首)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        r"(?:帮我|请|麻烦)?(?:直接)?(?:来|播放|播|放)(?:点|点儿|些|一点|一点儿)\s*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?来(?:一首|首)?\s*(?P<query>[^。！？!?，,]+)",
        r"(?:我)?(?:想听|听)(?:一下|下)?\s*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?(?:播放(?!器)|播(?!放器)|放(?!器))(?:一下|一首|首)?\s*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?播放(?!器)[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?放(?!器)[一下\s]*(?P<query>[^。！？!?，,]+)",
        r"(?:帮我|请|麻烦)?(?:直接)?(?P<query>[^。！？!?，,]+?)\s*(?:播放一下|播一下|放一下|放一首|播放一首|来一首)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        r"(?:play)\s+(?P<query>[^.!?]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_query = next((value for value in match.groupdict().values() if value), "")
        query = _strip_music_query_context(raw_query)
        if query and _is_specific_music_query(query):
            return query
    return ""


def _is_apple_music_status_request(text: str) -> bool:
    clean = _strip_query(text)
    if not clean:
        return False
    lowered = clean.lower()
    return bool(
        re.search(
            r"(?:当前|现在|正在|此刻).{0,8}(?:播放|播|放).{0,8}"
            r"(?:什么|啥|哪首|哪一首|哪首歌|歌曲|歌|曲目)",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:apple\s*music|苹果音乐|音乐).{0,12}(?:当前|现在|正在|此刻).{0,8}"
            r"(?:播放|播|放).{0,8}(?:什么|啥|哪首|哪一首|哪首歌|歌曲|歌|曲目)",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|现在|正在|此刻).{0,8}(?:apple\s*music|苹果音乐|音乐).{0,8}"
            r"(?:播放|播|放).{0,8}(?:什么|啥|哪首|哪一首|哪首歌|歌曲|歌|曲目)",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:播放|播|放).{0,4}(?:状态|情况|进度)|(?:音乐|apple\s*music|苹果音乐).{0,8}"
            r"(?:状态|播放状态|播放情况|播放进度|在播状态)",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:看看|查看|查询|读一下|读下|告诉我).{0,8}"
            r"(?:apple\s*music|苹果音乐|音乐).{0,12}(?:当前|现在|正在)?"
            r".{0,8}(?:播放|播|放|状态)",
            clean,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:what(?:'s| is)|which song is|what song is)\s+"
            r"(?:currently\s+)?playing(?:\s+(?:in|on)\s+apple\s*music)?\b",
            lowered,
        )
        or re.search(
            r"\b(?:apple\s*music|music)\s+(?:status|playback status|now playing)\b",
            lowered,
        )
        or re.search(
            r"\bnow\s+playing(?:\s+(?:in|on)\s+apple\s*music)?\b",
            lowered,
        )
    )


def _looks_like_app_launch_pull_up_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?"
            r"(?:直接)?(?:把|将)?\s*[^。！？!?，,\n]+?\s*(?:拉起来|拉起)\s*(?:一下|下)?"
            r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
            str(text or "").strip(),
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?"
            r"(?:直接)?(?:拉起来|拉起)\s*(?:一下|下)?\s*[^。！？!?，,\n]+?"
            r"(?:吧|吗|嘛|呢)?[?？。！!]*$",
            str(text or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _strip_music_query_context(value: str) -> str:
    query = _strip_query(value)
    query = re.sub(
        r"\s*(?:并且|并|然后|之后|后|再|接着)\s*"
        r"(?:播放|播|放)(?:一下)?(?:它|这个|这首|这首歌|该歌曲|该曲目)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s+(?:and\s+)?(?:play|start\s+playing)"
        r"(?:\s+(?:it|that|this|the\s+(?:song|track)))?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s*(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(
        r"\s*(?:在|用|通过)\s*(?:apple\s*music|music|音乐)(?:里|中|上|内)?$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\s+(?:apple\s*music|music\s+app)$", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^apple\s*music(?:里|中|上|内)?(?:的)?\s*", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^(?:music|音乐)(?:里|中|上|内)(?:的)?\s*", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^(?:里|中|上|内|里面)(?:的)?\s*", "", query)
    query = re.sub(r"^(?:一个|个)\s*", "", query)
    query = re.sub(r"^some\s+", "", query)
    return _strip_polite_suffix(_strip_query(query))


def _is_specific_music_query(query: str) -> bool:
    normalized = re.sub(r"[\s._-]+", "", query.lower())
    if _known_music_app_name(query):
        return False
    return normalized not in {
        "下",
        "一下",
        "音乐",
        "music",
        "song",
        "songs",
        "歌曲",
        "首歌",
        "一首歌",
        "applemusic",
        "musicapp",
        "音乐app",
        "音乐应用",
        "音乐软件",
        "音乐播放器",
        "播放器",
        "什么",
        "啥",
        "状态",
        "播放状态",
        "播放进度",
        "在播状态",
        "进度",
        "播放",
        "播",
        "放",
        "当前播放状态",
        "正在播放什么",
        "正在播什么",
        "播放什么",
        "在播什么",
        "nowplaying",
        "whatisplaying",
        "whatplaying",
        "playbackstatus",
        "playingstatus",
        "歌",
        "点歌",
        "点儿歌",
        "些歌",
        "一点歌",
        "一点儿歌",
        "东西",
        "点东西",
        "个东西",
        "一个东西",
        "些东西",
        "一点东西",
        "一点儿东西",
        "点",
        "一点",
        "点儿",
        "个",
        "一个",
        "一首",
        "something",
        "anything",
        "track",
        "atrack",
        "sometrack",
        "音乐听",
        "音乐听听",
        "音乐听一下",
        "音乐听下",
        "歌听",
        "歌听听",
        "歌听一下",
        "歌听下",
        "听",
        "听听",
        "听一下",
        "听下",
    }


def _apple_music_prefix_control_action(text: str) -> str:
    split = _known_app_prefix_split(text)
    if not split:
        return ""
    raw_app, app_name, followup = split
    music_app = _known_music_app_name(raw_app) or _known_music_app_name(app_name)
    if music_app != "Music":
        return ""
    return _music_control_followup_action(followup)


def _music_control_followup_action(value: str) -> str:
    text = _strip_query(value)
    lowered = text.lower()
    if re.fullmatch(
        r"(?:下一首|下一曲|下首|切歌|换歌|跳过|跳过这首|跳过当前(?:这)?首|"
        r"跳过当前歌曲|下一首歌|换首歌)",
        text,
    ) or re.fullmatch(r"(?:next|skip)(?:\s+(?:song|track))?", lowered):
        return "next"
    if re.fullmatch(r"(?:上一首|上一曲|上首|回到上一首|上一首歌)", text) or re.fullmatch(
        r"(?:previous|prev|back)(?:\s+(?:song|track))?",
        lowered,
    ):
        return "previous"
    if re.fullmatch(
        r"(?:播放\s*/\s*暂停|暂停\s*/\s*播放|播放暂停|切换播放|切换暂停)",
        text,
    ) or re.fullmatch(r"(?:toggle|play\s*/\s*pause|playpause)", lowered):
        return "toggle"
    if re.fullmatch(r"(?:暂停|停一下|停止|停止播放|别放了|关掉|关了|停掉|停了)", text) or re.fullmatch(
        r"(?:pause|stop)",
        lowered,
    ):
        return "pause"
    if re.fullmatch(r"(?:继续|继续播放|恢复|恢复播放|接着|接着播放)", text) or re.fullmatch(
        r"(?:resume|continue)(?:\s+(?:music|song|track|playback|playing))?",
        lowered,
    ):
        return "play"
    return ""


def _music_app_control_request(text: str) -> dict[str, Any] | None:
    split = _known_app_prefix_split(text) or _known_music_app_causative_prefix_split(text)
    if not split:
        return None
    raw_app, app_name, followup = split
    music_app = _known_music_app_name(raw_app) or _known_music_app_name(app_name)
    if not music_app or music_app == "Music":
        return None
    action = next(
        (
            parsed
            for candidate in _music_app_control_followup_candidates(text, raw_app, followup)
            if (parsed := _music_control_action(candidate))
        ),
        "",
    )
    if not action:
        return None
    return _request("media.music_app_control", {"app_name": music_app, "action": action})


def _known_music_app_causative_prefix_split(value: str) -> tuple[str, str, str] | None:
    stripped = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:让|叫)\s*",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    )
    if stripped == str(value or "").strip():
        return None
    return _known_app_prefix_split(stripped)


def _system_media_control_request(text: str) -> dict[str, Any] | None:
    if _music_app_control_request(text):
        return None
    split = _known_app_prefix_split(text)
    if split:
        raw_app, app_name, _followup = split
        if (_known_music_app_name(raw_app) or _known_music_app_name(app_name)) == "Music":
            return None
    if re.search(r"(?:apple\s*music|苹果音乐)", str(text or ""), flags=re.IGNORECASE):
        return None
    action = _system_media_control_action(text)
    if not action:
        return None
    return _request("media.system_control", {"action": action})


def _system_media_control_action(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if re.search(r"\b(?:pause|stop)\s+(?:the\s+)?(?:current\s+)?(?:media|playback)\b", lowered):
        return "pause"
    if re.search(r"\b(?:resume|continue)\s+(?:the\s+)?(?:current\s+)?(?:media|playback)\b", lowered):
        return "play"
    if re.search(r"\b(?:next|skip)\s+(?:media\s+)?(?:track|song)\b|\bnext\s+media\b", lowered):
        return "next"
    if re.search(r"\b(?:previous|prev|back)\s+(?:media\s+)?(?:track|song)\b|\bprevious\s+media\b", lowered):
        return "previous"
    action = _music_control_action(text)
    if not action:
        return ""
    if action == "play" and not re.search(
        r"(?:继续|恢复|接着|当前|现在|正在播放|媒体|播放中|resume|continue|current\s+media|playback)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return ""
    return action


def _music_control_action(text: str) -> str:
    split = _known_app_prefix_split(text)
    if split:
        raw_app, app_name, followup = split
        music_app = _known_music_app_name(raw_app) or _known_music_app_name(app_name)
        if (
            music_app
            and music_app != "Music"
            and any(
                _looks_like_music_control_followup(candidate)
                for candidate in _music_app_control_followup_candidates(text, raw_app, followup)
            )
        ):
            return ""
    lowered = text.lower()
    if re.search(
        r"(?:下一首|下一曲|下首|切下一首|跳下一首|跳过这首|跳过当前(?:这)?首|"
        r"跳过当前歌曲|跳过这首歌|下一首歌|切歌|换一首|换首歌|换歌)",
        text,
    ) or re.search(
        r"\b(?:next|skip)\s+(?:this\s+|the\s+|current\s+)?(?:song|track)\b",
        lowered,
    ):
        return "next"
    if re.search(r"(?:上一首|上一曲|上首|切上一首|回到上一首|上一首歌)", text) or re.search(
        r"\b(?:previous|prev|back)\s+(?:song|track)\b",
        lowered,
    ):
        return "previous"
    if re.search(r"(?:播放\s*/\s*暂停|暂停\s*/\s*播放|播放暂停|切换播放|切换暂停)", text) or re.search(
        r"\b(?:toggle|play\s*/\s*pause|playpause)\b",
        lowered,
    ):
        return "toggle"
    if re.search(
        r"(?:暂停|停一下|停止播放|停止(?:一下|下)?(?:音乐|歌曲|歌)|先停一下)"
        r"(?:\s*(?:音乐|歌曲|歌|apple\s*music|music))?",
        lowered,
    ) or re.search(
        r"(?:别|不要|不用|先别)\s*(?:播放|播|放)(?:了|啦)?",
        lowered,
    ) or re.search(
        r"(?:关掉|关了|停掉|停了)\s*(?:音乐|歌曲|歌|apple\s*music|music)",
        lowered,
    ) or re.search(
        r"\bpause\s+(?:the\s+|my\s+)?(?:music|apple\s*music|song|track|playback)\b",
        lowered,
    ):
        return "pause"
    if re.search(
        r"(?:继续播放|恢复播放|接着播放|开始播放|"
        r"播放继续|"
        r"(?:继续|接着|恢复|开始)(?:播放|播|放)\s*|"
        r"(?:继续|接着|恢复|开始)(?:播放|播|放)?\s*(?:当前|现在|正在播放的)?(?:音乐|歌曲|歌|apple\s*music|music))"
        r"(?:\s*(?:当前|现在|正在播放的)?(?:音乐|歌曲|歌|apple\s*music|music))?",
        lowered,
    ) or re.search(
        r"\b(?:resume|continue|start|play)(?:\s+playing)?\s+"
        r"(?:the\s+|my\s+)?(?:music|apple\s*music|song|track|playback)\b",
        lowered,
    ):
        return "play"
    if _music_app_generic_play_open_name(text) == "Music":
        return "play"
    if _looks_like_scoped_generic_music_play_request(text):
        return "play"
    if re.search(
        r"^(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?\s*"
        r"(?:播放一下|播一下|放一下|播放|播|放|开始播放|继续播放)"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if re.search(
        r"^(?:音乐|歌曲|歌|music|songs?)\s*(?:播放|播|放)(?:一下|一首|首)?"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if re.search(
        r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?(?:播放|放)一下"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if re.search(
        r"^(?:能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?(?:播放|放)(?:一下)?"
        r"\s*(?:音乐|music|apple\s*music)(?:应用|app|软件|程序)?\s*"
        r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
        lowered,
    ):
        return "play"
    if _looks_like_generic_music_play_request(text):
        return "play"
    if re.fullmatch(r"(?:播放|放)(?:一下)?(?:音乐|music|apple\s*music)(?:应用|app|软件|程序)?", lowered):
        return "play"
    if re.fullmatch(r"(?:play|start)\s+(?:music|apple\s*music)(?:\s+app)?", lowered):
        return "play"
    return ""


def _music_app_control_followup_candidates(text: str, raw_app: str, followup: str) -> tuple[str, ...]:
    candidates = [_strip_query(followup)]
    source = str(text or "").strip()
    prefix = str(raw_app or "").strip()
    if prefix and source.lower().startswith(prefix.lower()):
        candidates.append(_strip_query(source[len(prefix) :]))
    return tuple(candidate for candidate in candidates if candidate)


def _looks_like_music_control_followup(value: str) -> bool:
    return bool(
        re.search(
            r"(?:暂停|停一下|停止|关掉|关了|继续|恢复|开始|播放|播|放|"
            r"下一首|下一曲|下首|跳过|切歌|换歌|上一首|上一曲|上首)",
            str(value or ""),
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:pause|stop|resume|continue|start|play|next|skip|previous|prev|back|toggle)\b",
            str(value or ""),
            flags=re.IGNORECASE,
        )
    )


def _is_apple_music_open_and_play_request(text: str) -> bool:
    lowered = text.lower()
    if _music_app_generic_play_open_name(text) == "Music":
        return True
    if _looks_like_generic_music_play_request(text):
        return True
    if _looks_like_scoped_generic_music_play_request(text):
        return True
    return bool(
        re.search(
            r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?"
            r"(?:播放|放)(?:一下)?\s*"
            r"(?:apple\s*music|music|苹果音乐|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:(?:里|中|上|内|里面)?(?:的)?(?:音乐|歌|歌曲)|听听|听一下|听下|听)?"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|能否|能不能|可以)?(?:帮我|请|麻烦)?(?:直接)?"
            r"(?:启动|打开|运行|拉起|开启)(?:一下)?\s*"
            r"(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:并|然后|后|之后|再)\s*(?:开始)?(?:播放|放一下|播放一下)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:apple\s*music|music|苹果音乐|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:播放一下|播一下|放一下|播放|播|放|开始播放|继续播放)"
            r"(?:听听|听一下|听下|听)?"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:apple\s*music|music|苹果音乐|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:随便|随机)?"
            r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)"
            r"(?:音乐|歌|歌曲|东西)?"
            r"(?:听听|听一下|听下|听)?"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:能不能帮我|可不可以帮我|可以帮我|能帮我|能否|能不能|可以)?"
            r"(?:帮我|请|麻烦)?(?:直接)?"
            r"(?:(?:打开|启动|运行|拉起|开启)(?:一下)?\s*)?"
            r"(?:apple\s*music|music|苹果音乐|音乐)(?:应用|app|软件|程序)?\s*"
            r"(?:听听|听一下|听下|听)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please)?[?？。！!]*$",
            lowered,
        )
        or re.fullmatch(r"(?:play|start)\s+(?:apple\s*music|music)(?:\s+app)?", lowered)
    )


def _looks_like_scoped_generic_music_play_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:你|您|我|咱|我们)?(?:能不能帮我|可不可以帮我|可以帮我|能帮我|能否|能不能|可以)?(?:帮我|请|麻烦|给我)?(?:直接)?"
            r"(?:用|在|通过)\s*(?:apple\s*music|music|音乐)(?:应用|app|软件|程序)?"
            r"(?:里|中|上|内|里面)?\s*"
            r"(?:随便|随机)?"
            r"(?:(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲)|"
            r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲|东西)?|"
            r"(?:来|放|播放|播)(?:个|一个)(?:东西)|"
            r"(?:来点|来些)(?:音乐|歌|歌曲|东西)|(?:放|播放|播)(?:一下)?(?:音乐|歌|歌曲)|"
            r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?|"
            r"(?:听|想听)(?:点|点儿|些|一点|一点儿|一首|首)?(?:音乐|歌|歌曲))"
            r"(?:听听|听一下|听下|听)?"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            lowered,
        )
        or re.fullmatch(
            r"(?:play|start(?:\s+playing)?)\s+"
            r"(?:(?:a\s+)?(?:song|track|music)|some\s+music|something|anything)?\s*"
            r"(?:in|on|with|using)\s+(?:apple\s*music|music)(?:\s+app)?",
            lowered,
        )
    )


def _looks_like_generic_music_play_request(text: str) -> bool:
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:你|您|我|咱|我们)?(?:能不能帮我|可不可以帮我|可以帮我|能帮我|能否|能不能|可以)?(?:帮我|请|麻烦|给我)?(?:直接)?"
            r"(?:随便|随机)?"
            r"(?:(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:音乐|歌|歌曲)|"
            r"(?:来|放|播放|播)(?:点|点儿|些|一点|一点儿)(?:东西)|"
            r"(?:来|放|播放|播)(?:个|一个)(?:东西)|"
            r"(?:来点|来些)(?:音乐|歌|歌曲|东西)|(?:放|播放|播)(?:一下)?(?:音乐|歌|歌曲)|"
            r"(?:来|放|播放|播)(?:一首|首)(?:歌|歌曲)?|"
            r"(?:听|想听)(?:点|点儿|些|一点|一点儿|一首|首)?(?:音乐|歌|歌曲))"
            r"(?:听听|听一下|听下|听)?"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            lowered,
        )
        or re.search(
            r"^(?:你|您|我|咱|我们)?(?:能不能帮我|可不可以帮我|可以帮我|能帮我|能否|能不能|可以)?(?:帮我|请|麻烦|给我)?(?:直接)?"
            r"(?:随便|随机)?(?:来|放|播放|播)(?:一首|首)"
            r"(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            lowered,
        )
        or re.fullmatch(
            r"(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
            r"(?:play|start|put\s+on)\s+(?:a\s+)?(?:song|track|music|some\s+music|something|anything)[.!?]*",
            lowered,
        )
        or re.fullmatch(
            r"(?:i\s+)?(?:want|wanna|would\s+like)(?:\s+to)?\s+"
            r"(?:(?:listen\s+to|hear|play)\s+)?(?:some\s+)?(?:music|songs?)",
            lowered,
        )
    )


def _looks_like_project_or_design_request(text: str) -> bool:
    value = str(text or "").strip()
    if len(value) < 160 and "\n" not in value:
        return False
    lowered = value.lower()
    has_project_terms = bool(
        re.search(
            r"(?:class=|css|html|ui|界面|设计|设计风格|功能|需求|要求|验收|生成一个新的|不要覆盖|保持现有功能)",
            lowered,
            flags=re.IGNORECASE,
        )
    )
    has_spec_shape = bool(
        re.search(r"(?:^|\n)\s*\d+[.、]", value)
        or re.search(r"(?:要求|需求|验收)\s*[：:]", value)
        or re.search(r"class\s*=", value, flags=re.IGNORECASE)
    )
    return has_project_terms and has_spec_shape


def _desktop_hotkey(text: str) -> dict[str, Any] | None:
    text = _strip_foreground_action_target(_strip_desktop_action_request_shell(text))
    system_hotkey = _system_desktop_hotkey_request(text)
    if system_hotkey:
        return system_hotkey
    named = _desktop_named_hotkey(text)
    if named:
        return named
    hotkey_part = (
        r"(?:command|cmd|shift|option|alt|control|ctrl|⌘|⇧|⌥|⌃|fn|"
        r"回车|确认|确定|换行|空格|退出|删除|退格|上箭头|下箭头|左箭头|右箭头|"
        r"enter|return|escape|esc|tab|space|delete|backspace|up|down|left|right|"
        r"[A-Za-z0-9])"
    )
    suffix = r"\s*(?:键|快捷键|热键|一下|下|一次|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$"
    patterns = (
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        rf"(?:按下|按|敲下|敲|发送|触发|快捷键|热键|组合键|按键)\s*(?:一下|下|一次)?\s*"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})+){suffix}",
        rf"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:按下|按|敲下|敲|发送|触发)\s*(?:一下|下|一次)?\s*"
        rf"(?P<combo>{hotkey_part}){suffix}",
        rf"^(?:press|hit|tap)\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)?"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})*)"
        rf"(?:\s+key)?\s*[.!?]*$",
        rf"^trigger\s+(?:the\s+)?(?:hotkey\s+|shortcut\s+)"
        rf"(?P<combo>{hotkey_part}(?:[+\-\s]+{hotkey_part})*)\s*[.!?]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_hotkey_combo(match.group("combo"))
        if parsed:
            return parsed
    return None


def _system_desktop_hotkey_request(text: str) -> dict[str, Any] | None:
    return None


def _is_maximize_current_window_request(text: str) -> bool:
    value = str(text or "").strip()
    lowered = value.lower()
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            r"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window|app|应用)\s*"
            r"(?:最大化|放大|全屏|进入全屏)(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:最大化|放大|全屏|进入全屏)\s*(?:当前|现在|前台|这个|该)?\s*(?:窗口|window|app|应用)"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:进入|切换到|打开)?\s*"
            r"全屏(?:模式)?(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?[?？。！!]*$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:maximize|fullscreen|full\s*screen|enter\s+full\s*screen)\s+"
            r"(?:the\s+)?(?:current|active|foreground|frontmost)?\s*"
            r"(?:window|app|application)\b",
            lowered,
        )
        or re.search(
            r"\b(?:make|put)\s+(?:the\s+)?(?:current|active|foreground|frontmost)\s+"
            r"(?:window|app|application)\s+(?:full\s*screen|maximized)\b",
            lowered,
        )
    )


def _looks_like_window_management_action(text: str) -> bool:
    value = str(text or "").strip()
    lowered = value.lower()
    return bool(
        _is_maximize_current_window_request(value)
        or _is_minimize_current_window_request(value)
        or re.search(
            r"(?:最大化|放大|全屏|进入全屏|分屏|贴靠|平铺|放左边|放右边|靠左|靠右)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:maximize|fullscreen|full\s*screen|tile|snap|left\s+half|right\s+half)\b",
            lowered,
        )
    )


def _desktop_named_hotkey(text: str) -> dict[str, Any] | None:
    phrase = _normalize_named_hotkey_phrase(text)
    mapping: dict[str, tuple[str, tuple[str, ...]]] = {
        "复制": ("c", ("command",)),
        "复制选中内容": ("c", ("command",)),
        "复制选中文字": ("c", ("command",)),
        "复制选中的文字": ("c", ("command",)),
        "复制当前选中内容": ("c", ("command",)),
        "复制当前选中文字": ("c", ("command",)),
        "copy": ("c", ("command",)),
        "copyselection": ("c", ("command",)),
        "copyselectedtext": ("c", ("command",)),
        "粘贴": ("v", ("command",)),
        "paste": ("v", ("command",)),
        "全选": ("a", ("command",)),
        "selectall": ("a", ("command",)),
        "撤销": ("z", ("command",)),
        "undo": ("z", ("command",)),
        "重做": ("z", ("command", "shift")),
        "redo": ("z", ("command", "shift")),
        "保存": ("s", ("command",)),
        "保存文档": ("s", ("command",)),
        "保存当前文档": ("s", ("command",)),
        "保存文件": ("s", ("command",)),
        "save": ("s", ("command",)),
        "savefile": ("s", ("command",)),
        "savedocument": ("s", ("command",)),
        "刷新": ("r", ("command",)),
        "浏览器刷新": ("r", ("command",)),
        "网页刷新": ("r", ("command",)),
        "当前网页刷新": ("r", ("command",)),
        "当前页刷新": ("r", ("command",)),
        "reload": ("r", ("command",)),
        "refresh": ("r", ("command",)),
        "重新打开关闭的标签页": ("t", ("command", "shift")),
        "重新打开上个关闭的标签页": ("t", ("command", "shift")),
        "恢复关闭的标签页": ("t", ("command", "shift")),
        "恢复上一个关闭的标签页": ("t", ("command", "shift")),
        "reopenclosedtab": ("t", ("command", "shift")),
        "reopentheclosedtab": ("t", ("command", "shift")),
        "reopenlastclosedtab": ("t", ("command", "shift")),
        "restoreclosedtab": ("t", ("command", "shift")),
        "下一个标签页": ("]", ("command", "shift")),
        "下个标签页": ("]", ("command", "shift")),
        "下一标签页": ("]", ("command", "shift")),
        "切到下一个标签页": ("]", ("command", "shift")),
        "切换到下一个标签页": ("]", ("command", "shift")),
        "nexttab": ("]", ("command", "shift")),
        "switchtonexttab": ("]", ("command", "shift")),
        "上一个标签页": ("[", ("command", "shift")),
        "上个标签页": ("[", ("command", "shift")),
        "上一标签页": ("[", ("command", "shift")),
        "切到上一个标签页": ("[", ("command", "shift")),
        "切换到上一个标签页": ("[", ("command", "shift")),
        "previoustab": ("[", ("command", "shift")),
        "switchtoprevioustab": ("[", ("command", "shift")),
        "查找": ("f", ("command",)),
        "打开查找": ("f", ("command",)),
        "打开查找框": ("f", ("command",)),
        "打开搜索框": ("f", ("command",)),
        "页面查找": ("f", ("command",)),
        "页面内查找": ("f", ("command",)),
        "页面里查找": ("f", ("command",)),
        "当前页查找": ("f", ("command",)),
        "find": ("f", ("command",)),
        "findinpage": ("f", ("command",)),
        "findonpage": ("f", ("command",)),
        "pagefind": ("f", ("command",)),
        "openfind": ("f", ("command",)),
        "openfindbox": ("f", ("command",)),
        "新建标签页": ("t", ("command",)),
        "新标签页": ("t", ("command",)),
        "打开新标签页": ("t", ("command",)),
        "newtab": ("t", ("command",)),
        "关闭标签页": ("w", ("command",)),
        "关闭当前标签页": ("w", ("command",)),
        "关闭浏览器标签页": ("w", ("command",)),
        "关闭这个标签页": ("w", ("command",)),
        "closecurrenttab": ("w", ("command",)),
        "closethecurrenttab": ("w", ("command",)),
        "closetab": ("w", ("command",)),
        "退出当前应用": ("q", ("command",)),
        "退出前台应用": ("q", ("command",)),
        "退出当前app": ("q", ("command",)),
        "关闭当前应用": ("q", ("command",)),
        "关闭前台应用": ("q", ("command",)),
        "关闭当前app": ("q", ("command",)),
        "关掉当前应用": ("q", ("command",)),
        "关掉当前app": ("q", ("command",)),
        "quitcurrentapp": ("q", ("command",)),
        "quitcurrentapplication": ("q", ("command",)),
        "closecurrentapp": ("q", ("command",)),
        "closecurrentapplication": ("q", ("command",)),
        "空格": ("space", ()),
        "space": ("space", ()),
        "回车": ("return", ()),
        "确认": ("return", ()),
        "确定": ("return", ()),
        "enter": ("return", ()),
        "return": ("return", ()),
    }
    combo = mapping.get(phrase)
    if combo is None:
        return None
    key, modifiers = combo
    return {"key": key, "modifiers": list(modifiers)}


def _desktop_safe_shortcut_action(text: str) -> str:
    hotkey_action = _safe_shortcut_action_from_hotkey(text)
    if hotkey_action:
        return hotkey_action
    if _is_maximize_current_window_request(text):
        return "toggle_full_screen"
    phrase = _normalize_named_hotkey_phrase(text)
    mapping = {
        "复制": "copy",
        "复制选中内容": "copy",
        "复制选中的内容": "copy",
        "复制选中文字": "copy",
        "复制选中的文字": "copy",
        "复制选中文本": "copy",
        "复制选中的文本": "copy",
        "复制当前选中内容": "copy",
        "复制当前选中的内容": "copy",
        "复制当前选中文字": "copy",
        "复制当前选中的文字": "copy",
        "复制当前选中文本": "copy",
        "复制当前选中的文本": "copy",
        "复制一下选中内容": "copy",
        "复制一下选中的内容": "copy",
        "复制一下选中文字": "copy",
        "复制一下选中的文字": "copy",
        "复制一下选中文本": "copy",
        "复制一下选中的文本": "copy",
        "复制这个": "copy",
        "复制这": "copy",
        "复制一下这个": "copy",
        "复制一下这": "copy",
        "这个复制": "copy",
        "把这个复制": "copy",
        "把这复制": "copy",
        "copy": "copy",
        "copythis": "copy",
        "copythat": "copy",
        "copyselection": "copy",
        "copycurrentselection": "copy",
        "copytheselection": "copy",
        "copyselectedtext": "copy",
        "粘贴": "paste",
        "粘贴剪贴板": "paste",
        "粘贴剪贴板内容": "paste",
        "剪贴板粘贴": "paste",
        "把剪贴板粘贴": "paste",
        "将剪贴板粘贴": "paste",
        "粘贴板粘贴": "paste",
        "把粘贴板粘贴": "paste",
        "将粘贴板粘贴": "paste",
        "剪贴板内容粘贴": "paste",
        "把剪贴板内容粘贴": "paste",
        "将剪贴板内容粘贴": "paste",
        "粘贴板内容粘贴": "paste",
        "把粘贴板内容粘贴": "paste",
        "将粘贴板内容粘贴": "paste",
        "当前输入框粘贴": "paste",
        "当前文本框粘贴": "paste",
        "当前输入栏粘贴": "paste",
        "前台粘贴": "paste",
        "当前窗口粘贴": "paste",
        "前台输入框粘贴": "paste",
        "前台文本框粘贴": "paste",
        "前台输入栏粘贴": "paste",
        "把剪贴板内容粘贴到当前输入框": "paste",
        "把剪贴板内容粘贴到输入框": "paste",
        "剪贴板内容粘贴到当前输入框": "paste",
        "剪贴板内容粘贴到输入框": "paste",
        "粘贴到这里": "paste",
        "粘贴到这": "paste",
        "粘贴在这里": "paste",
        "粘贴到当前输入框": "paste",
        "粘贴到输入框": "paste",
        "粘贴到当前窗口": "paste",
        "粘贴到前台": "paste",
        "粘贴进当前输入框": "paste",
        "粘贴进输入框": "paste",
        "粘贴进当前窗口": "paste",
        "粘贴进前台": "paste",
        "粘贴在当前输入框": "paste",
        "粘贴在输入框": "paste",
        "粘贴在当前窗口": "paste",
        "粘贴在前台": "paste",
        "paste": "paste",
        "pasteclipboard": "paste",
        "pasteclipboardcontents": "paste",
        "pasteintocurrentinput": "paste",
        "pasteintoinput": "paste",
        "pasteintocurrentwindow": "paste",
        "pasteintoforeground": "paste",
        "pasteincurrentinput": "paste",
        "pasteininput": "paste",
        "pasteincurrentwindow": "paste",
        "pasteinforeground": "paste",
        "全选": "select_all",
        "selectall": "select_all",
        "撤销": "undo",
        "undo": "undo",
        "重做": "redo",
        "redo": "redo",
        "刷新": "refresh",
        "浏览器刷新": "refresh",
        "网页刷新": "refresh",
        "当前网页刷新": "refresh",
        "当前页刷新": "refresh",
        "刷新一下页面": "refresh",
        "刷新下页面": "refresh",
        "刷新页面": "refresh",
        "刷新一下当前页": "refresh",
        "刷新下当前页": "refresh",
        "刷新当前页": "refresh",
        "刷新一下当前页面": "refresh",
        "刷新下当前页面": "refresh",
        "刷新当前页面": "refresh",
        "刷新一下当前网页": "refresh",
        "刷新下当前网页": "refresh",
        "刷新当前网页": "refresh",
        "刷新一下这个网页": "refresh",
        "刷新下这个网页": "refresh",
        "刷新这个网页": "refresh",
        "刷新一下这个页面": "refresh",
        "刷新下这个页面": "refresh",
        "刷新这个页面": "refresh",
        "刷新一下网页": "refresh",
        "刷新下网页": "refresh",
        "刷新网页": "refresh",
        "reload": "refresh",
        "reloadthecurrentpage": "refresh",
        "reloadpage": "refresh",
        "refresh": "refresh",
        "refreshthecurrentpage": "refresh",
        "refreshpage": "refresh",
        "重新打开关闭的标签页": "reopen_closed_tab",
        "重新打开刚关闭的标签页": "reopen_closed_tab",
        "重新打开刚刚关闭的标签页": "reopen_closed_tab",
        "重新打开刚才关闭的标签页": "reopen_closed_tab",
        "重新打开最近关闭的标签页": "reopen_closed_tab",
        "重新打开上次关闭的标签页": "reopen_closed_tab",
        "重新打开上个关闭的标签页": "reopen_closed_tab",
        "重新打开上一个关闭的标签页": "reopen_closed_tab",
        "恢复关闭的标签页": "reopen_closed_tab",
        "恢复刚关闭的标签页": "reopen_closed_tab",
        "恢复刚刚关闭的标签页": "reopen_closed_tab",
        "恢复刚才关闭的标签页": "reopen_closed_tab",
        "恢复最近关闭的标签页": "reopen_closed_tab",
        "恢复上次关闭的标签页": "reopen_closed_tab",
        "恢复上个关闭的标签页": "reopen_closed_tab",
        "恢复上一个关闭的标签页": "reopen_closed_tab",
        "reopenclosedtab": "reopen_closed_tab",
        "reopentheclosedtab": "reopen_closed_tab",
        "reopenlastclosedtab": "reopen_closed_tab",
        "reopenjustclosedtab": "reopen_closed_tab",
        "restoreclosedtab": "reopen_closed_tab",
        "restorejustclosedtab": "reopen_closed_tab",
        "关闭标签页": "close_tab",
        "关闭当前标签页": "close_tab",
        "关闭浏览器标签页": "close_tab",
        "关闭这个标签页": "close_tab",
        "关闭这个网页": "close_tab",
        "关闭当前网页": "close_tab",
        "关闭这个页面": "close_tab",
        "关闭当前页面": "close_tab",
        "把这个网页关掉": "close_tab",
        "把当前网页关掉": "close_tab",
        "把这个页面关掉": "close_tab",
        "把当前页面关掉": "close_tab",
        "把这个标签页关掉": "close_tab",
        "把当前标签页关掉": "close_tab",
        "关掉标签页": "close_tab",
        "关掉当前标签页": "close_tab",
        "关掉浏览器标签页": "close_tab",
        "关掉这个标签页": "close_tab",
        "关掉这个网页": "close_tab",
        "关掉当前网页": "close_tab",
        "关掉这个页面": "close_tab",
        "关掉当前页面": "close_tab",
        "closetab": "close_tab",
        "closecurrenttab": "close_tab",
        "closethecurrenttab": "close_tab",
        "closethistab": "close_tab",
        "closethispage": "close_tab",
        "下一个标签页": "next_tab",
        "下一个标签": "next_tab",
        "下个标签页": "next_tab",
        "下个标签": "next_tab",
        "下一标签页": "next_tab",
        "切到下一个标签页": "next_tab",
        "切换到下一个标签页": "next_tab",
        "nexttab": "next_tab",
        "switchtonexttab": "next_tab",
        "上一个标签页": "previous_tab",
        "上一个标签": "previous_tab",
        "上个标签页": "previous_tab",
        "上个标签": "previous_tab",
        "上一标签页": "previous_tab",
        "切到上一个标签页": "previous_tab",
        "切换到上一个标签页": "previous_tab",
        "previoustab": "previous_tab",
        "switchtoprevioustab": "previous_tab",
        "下一个窗口": "next_window",
        "下个窗口": "next_window",
        "下一窗口": "next_window",
        "切到下一个窗口": "next_window",
        "切换到下一个窗口": "next_window",
        "当前应用下一个窗口": "next_window",
        "nextwindow": "next_window",
        "switchnextwindow": "next_window",
        "switchtonextwindow": "next_window",
        "上一个窗口": "previous_window",
        "上个窗口": "previous_window",
        "上一窗口": "previous_window",
        "切到上一个窗口": "previous_window",
        "切换到上一个窗口": "previous_window",
        "当前应用上一个窗口": "previous_window",
        "previouswindow": "previous_window",
        "switchpreviouswindow": "previous_window",
        "switchtopreviouswindow": "previous_window",
        "切换到上一个应用": "switch_previous_app",
        "切换上一个应用": "switch_previous_app",
        "切到上一个应用": "switch_previous_app",
        "切回上一个应用": "switch_previous_app",
        "回到上一个应用": "switch_previous_app",
        "切换到上个应用": "switch_previous_app",
        "切到上个应用": "switch_previous_app",
        "切回上个应用": "switch_previous_app",
        "回到上个应用": "switch_previous_app",
        "切换到前一个应用": "switch_previous_app",
        "切到前一个应用": "switch_previous_app",
        "回到前一个应用": "switch_previous_app",
        "switchtopreviousapp": "switch_previous_app",
        "switchtopreviousapplication": "switch_previous_app",
        "switchtolastapp": "switch_previous_app",
        "switchtolastapplication": "switch_previous_app",
        "gobacktopreviousapp": "switch_previous_app",
        "returntopreviousapp": "switch_previous_app",
        "切换到下一个应用": "switch_next_app",
        "切换下一个应用": "switch_next_app",
        "切到下一个应用": "switch_next_app",
        "切去下一个应用": "switch_next_app",
        "跳到下一个应用": "switch_next_app",
        "转到下一个应用": "switch_next_app",
        "切换到下个应用": "switch_next_app",
        "切到下个应用": "switch_next_app",
        "切去下个应用": "switch_next_app",
        "跳到下个应用": "switch_next_app",
        "转到下个应用": "switch_next_app",
        "switchtonextapp": "switch_next_app",
        "switchtonextapplication": "switch_next_app",
        "gotonextapp": "switch_next_app",
        "movetonextapp": "switch_next_app",
        "隐藏其他应用": "hide_other_apps",
        "隐藏其它应用": "hide_other_apps",
        "隐藏所有其他应用": "hide_other_apps",
        "隐藏所有其它应用": "hide_other_apps",
        "只显示当前应用": "hide_other_apps",
        "只保留当前应用": "hide_other_apps",
        "只留下当前应用": "hide_other_apps",
        "hideotherapps": "hide_other_apps",
        "hideallotherapps": "hide_other_apps",
        "showonlycurrentapp": "hide_other_apps",
        "showonlycurrentapplication": "hide_other_apps",
        "当前窗口最大化": "toggle_full_screen",
        "当前窗口全屏": "toggle_full_screen",
        "最大化当前窗口": "toggle_full_screen",
        "全屏当前窗口": "toggle_full_screen",
        "进入全屏": "toggle_full_screen",
        "进入全屏模式": "toggle_full_screen",
        "退出全屏": "toggle_full_screen",
        "退出全屏模式": "toggle_full_screen",
        "离开全屏": "toggle_full_screen",
        "离开全屏模式": "toggle_full_screen",
        "maximizecurrentwindow": "toggle_full_screen",
        "maximizethecurrentwindow": "toggle_full_screen",
        "fullscreencurrentwindow": "toggle_full_screen",
        "enterfullscreen": "toggle_full_screen",
        "exitfullscreen": "toggle_full_screen",
        "leavefullscreen": "toggle_full_screen",
        "exitfullscreenmode": "toggle_full_screen",
        "leavefullscreenmode": "toggle_full_screen",
        "任务控制中心": "mission_control",
        "打开任务控制中心": "mission_control",
        "显示任务控制中心": "mission_control",
        "调度中心": "mission_control",
        "打开调度中心": "mission_control",
        "显示调度中心": "mission_control",
        "missioncontrol": "mission_control",
        "openmissioncontrol": "mission_control",
        "showmissioncontrol": "mission_control",
        "应用窗口": "application_windows",
        "显示应用窗口": "application_windows",
        "显示所有应用窗口": "application_windows",
        "显示当前应用窗口": "application_windows",
        "显示当前应用所有窗口": "application_windows",
        "显示当前应用的所有窗口": "application_windows",
        "显示前台应用窗口": "application_windows",
        "显示前台应用所有窗口": "application_windows",
        "显示前台应用的所有窗口": "application_windows",
        "应用窗口都显示": "application_windows",
        "当前应用窗口都显示": "application_windows",
        "前台应用窗口都显示": "application_windows",
        "所有应用窗口": "application_windows",
        "当前应用的所有窗口": "application_windows",
        "当前应用所有窗口": "application_windows",
        "前台应用的所有窗口": "application_windows",
        "前台应用所有窗口": "application_windows",
        "当前应用窗口": "application_windows",
        "前台应用窗口": "application_windows",
        "应用expose": "application_windows",
        "应用exposé": "application_windows",
        "appexpose": "application_windows",
        "showappexpose": "application_windows",
        "appwindows": "application_windows",
        "showappwindows": "application_windows",
        "applicationwindows": "application_windows",
        "showapplicationwindows": "application_windows",
        "showcurrentappwindows": "application_windows",
        "聚焦搜索": "spotlight_search",
        "打开聚焦搜索": "spotlight_search",
        "显示聚焦搜索": "spotlight_search",
        "spotlight": "spotlight_search",
        "打开spotlight": "spotlight_search",
        "显示spotlight": "spotlight_search",
        "spotlightsearch": "spotlight_search",
        "openspotlight": "spotlight_search",
        "showspotlight": "spotlight_search",
        "openspotlightsearch": "spotlight_search",
        "showspotlightsearch": "spotlight_search",
        "emoji面板": "emoji_picker",
        "表情面板": "emoji_picker",
        "打开emoji面板": "emoji_picker",
        "显示emoji面板": "emoji_picker",
        "打开表情面板": "emoji_picker",
        "显示表情面板": "emoji_picker",
        "emoji": "emoji_picker",
        "emojipicker": "emoji_picker",
        "showemoji": "emoji_picker",
        "openemoji": "emoji_picker",
        "showemojipicker": "emoji_picker",
        "openemojipicker": "emoji_picker",
        "选区截图": "screenshot_selection",
        "截图选区": "screenshot_selection",
        "截取选区": "screenshot_selection",
        "区域截图": "screenshot_selection",
        "选择区域截图": "screenshot_selection",
        "选取区域截图": "screenshot_selection",
        "框选截图": "screenshot_selection",
        "screenshotselection": "screenshot_selection",
        "screenshotselectedarea": "screenshot_selection",
        "selectedareascreenshot": "screenshot_selection",
        "regionscreenshot": "screenshot_selection",
        "captureselectedarea": "screenshot_selection",
        "capturearegion": "screenshot_selection",
        "capturearea": "screenshot_selection",
        "截图工具": "screenshot_toolbar",
        "打开截图工具": "screenshot_toolbar",
        "显示截图工具": "screenshot_toolbar",
        "启动截图工具": "screenshot_toolbar",
        "截图面板": "screenshot_toolbar",
        "打开截图面板": "screenshot_toolbar",
        "显示截图面板": "screenshot_toolbar",
        "启动截图面板": "screenshot_toolbar",
        "屏幕截图工具": "screenshot_toolbar",
        "打开屏幕截图工具": "screenshot_toolbar",
        "屏幕截图面板": "screenshot_toolbar",
        "打开屏幕截图面板": "screenshot_toolbar",
        "screenshottoolbar": "screenshot_toolbar",
        "openscreenshottoolbar": "screenshot_toolbar",
        "showscreenshottoolbar": "screenshot_toolbar",
        "launchscreenshottoolbar": "screenshot_toolbar",
        "screenshottool": "screenshot_toolbar",
        "openscreenshottool": "screenshot_toolbar",
        "screenshotpanel": "screenshot_toolbar",
        "openscreenshotpanel": "screenshot_toolbar",
        "screencapturetoolbar": "screenshot_toolbar",
        "openscreencapturetoolbar": "screenshot_toolbar",
        "screencapturetool": "screenshot_toolbar",
        "openscreencapturetool": "screenshot_toolbar",
        "screencapturepanel": "screenshot_toolbar",
        "openscreencapturepanel": "screenshot_toolbar",
        "录屏": "screenshot_toolbar",
        "屏幕录制": "screenshot_toolbar",
        "录屏工具": "screenshot_toolbar",
        "打开录屏工具": "screenshot_toolbar",
        "录屏面板": "screenshot_toolbar",
        "打开录屏面板": "screenshot_toolbar",
        "开始录屏": "screenshot_toolbar",
        "screenrecording": "screenshot_toolbar",
        "screenrecordingtoolbar": "screenshot_toolbar",
        "openscreenrecordingtoolbar": "screenshot_toolbar",
        "screenrecordingtool": "screenshot_toolbar",
        "openscreenrecordingtool": "screenshot_toolbar",
        "screenrecordingpanel": "screenshot_toolbar",
        "openscreenrecordingpanel": "screenshot_toolbar",
        "锁屏": "lock_screen",
        "锁一下屏": "lock_screen",
        "锁下屏": "lock_screen",
        "锁定屏幕": "lock_screen",
        "锁定电脑": "lock_screen",
        "锁定这台电脑": "lock_screen",
        "lockscreen": "lock_screen",
        "lockthescreen": "lock_screen",
        "lockthismac": "lock_screen",
        "强制退出窗口": "force_quit_dialog",
        "打开强制退出窗口": "force_quit_dialog",
        "显示强制退出窗口": "force_quit_dialog",
        "打开应用强制退出": "force_quit_dialog",
        "应用强制退出": "force_quit_dialog",
        "强制退出应用窗口": "force_quit_dialog",
        "forcequit": "force_quit_dialog",
        "forcequitapplications": "force_quit_dialog",
        "openforcequit": "force_quit_dialog",
        "openforcequitapplications": "force_quit_dialog",
        "showforcequit": "force_quit_dialog",
        "showforcequitapplications": "force_quit_dialog",
        "返回上一页": "browser_back",
        "回到上一页": "browser_back",
        "网页后退": "browser_back",
        "浏览器后退": "browser_back",
        "后退一页": "browser_back",
        "后退": "browser_back",
        "goback": "browser_back",
        "gobackonepage": "browser_back",
        "back": "browser_back",
        "backpage": "browser_back",
        "前进一页": "browser_forward",
        "前进下一页": "browser_forward",
        "前进到下一页": "browser_forward",
        "网页前进": "browser_forward",
        "浏览器前进": "browser_forward",
        "前进": "browser_forward",
        "goforward": "browser_forward",
        "goforwardonepage": "browser_forward",
        "forward": "browser_forward",
        "forwardpage": "browser_forward",
        "查找": "find",
        "打开查找": "find",
        "打开查找框": "find",
        "打开搜索": "find",
        "打开搜索框": "find",
        "打开搜索栏": "find",
        "打开搜索输入框": "find",
        "搜索框": "find",
        "搜索栏": "find",
        "搜索输入框": "find",
        "页面查找": "find",
        "页面内查找": "find",
        "页面里查找": "find",
        "当前页查找": "find",
        "find": "find",
        "findinpage": "find",
        "findonpage": "find",
        "pagefind": "find",
        "openfind": "find",
        "openfindbox": "find",
        "地址栏": "focus_address_bar",
        "聚焦地址栏": "focus_address_bar",
        "打开地址栏": "focus_address_bar",
        "选中地址栏": "focus_address_bar",
        "选择地址栏": "focus_address_bar",
        "浏览器地址栏": "focus_address_bar",
        "聚焦浏览器地址栏": "focus_address_bar",
        "focusaddressbar": "focus_address_bar",
        "selectaddressbar": "focus_address_bar",
        "openaddressbar": "focus_address_bar",
        "locationbar": "focus_address_bar",
        "focuslocationbar": "focus_address_bar",
        "新建标签": "new_tab",
        "新建标签页": "new_tab",
        "新标签页": "new_tab",
        "打开新标签页": "new_tab",
        "开新标签页": "new_tab",
        "新开标签页": "new_tab",
        "开一个新标签页": "new_tab",
        "新开一个标签页": "new_tab",
        "newtab": "new_tab",
        "opennewtab": "new_tab",
        "openanewtab": "new_tab",
        "新建无痕窗口": "new_private_window",
        "打开无痕窗口": "new_private_window",
        "新建隐身窗口": "new_private_window",
        "打开隐身窗口": "new_private_window",
        "新建隐私窗口": "new_private_window",
        "打开隐私窗口": "new_private_window",
        "新建私密窗口": "new_private_window",
        "打开私密窗口": "new_private_window",
        "新建浏览器无痕窗口": "new_private_window",
        "打开浏览器无痕窗口": "new_private_window",
        "无痕窗口": "new_private_window",
        "隐身窗口": "new_private_window",
        "隐私窗口": "new_private_window",
        "私密窗口": "new_private_window",
        "newprivatewindow": "new_private_window",
        "openprivatewindow": "new_private_window",
        "newincognitowindow": "new_private_window",
        "openincognitowindow": "new_private_window",
        "incognitowindow": "new_private_window",
        "新建窗口": "new_window",
        "新窗口": "new_window",
        "打开新窗口": "new_window",
        "打开一个新窗口": "new_window",
        "开新窗口": "new_window",
        "开一个新窗口": "new_window",
        "新建一个窗口": "new_window",
        "新建浏览器窗口": "new_window",
        "打开浏览器新窗口": "new_window",
        "打开一个浏览器窗口": "new_window",
        "newwindow": "new_window",
        "新建文档": "new_document",
        "新文档": "new_document",
        "新建文件": "new_document",
        "新文件": "new_document",
        "开新文档": "new_document",
        "开一个新文档": "new_document",
        "开新文件": "new_document",
        "开一个新文件": "new_document",
        "新建表格": "new_document",
        "新表格": "new_document",
        "新建工作簿": "new_document",
        "新工作簿": "new_document",
        "新建演示文稿": "new_document",
        "新演示文稿": "new_document",
        "新建幻灯片": "new_document",
        "新幻灯片": "new_document",
        "新建ppt": "new_document",
        "新ppt": "new_document",
        "newdocument": "new_document",
        "newfile": "new_document",
        "newworkbook": "new_document",
        "newspreadsheet": "new_document",
        "newpresentation": "new_document",
        "newslide": "new_document",
        "makeanewdocument": "new_document",
        "createanewdocument": "new_document",
        "makenewdocument": "new_document",
        "createnewdocument": "new_document",
        "makeanewfile": "new_document",
        "createanewfile": "new_document",
        "makenewfile": "new_document",
        "createnewfile": "new_document",
        "makeanewworkbook": "new_document",
        "createanewworkbook": "new_document",
        "makenewworkbook": "new_document",
        "createnewworkbook": "new_document",
        "makeanewspreadsheet": "new_document",
        "createanewspreadsheet": "new_document",
        "makenewspreadsheet": "new_document",
        "createnewspreadsheet": "new_document",
        "makeanewpresentation": "new_document",
        "createanewpresentation": "new_document",
        "makenewpresentation": "new_document",
        "createnewpresentation": "new_document",
        "新建笔记": "new_note",
        "新建一个笔记": "new_note",
        "新建一条笔记": "new_note",
        "新建一篇笔记": "new_note",
        "新笔记": "new_note",
        "新建备忘录": "new_note",
        "新建一个备忘录": "new_note",
        "新建一条备忘录": "new_note",
        "新建一篇备忘录": "new_note",
        "新备忘录": "new_note",
        "创建备忘录": "new_note",
        "创建一个备忘录": "new_note",
        "创建一条备忘录": "new_note",
        "创建一篇备忘录": "new_note",
        "新建提醒事项": "new_reminder",
        "新建一个提醒事项": "new_reminder",
        "新建一条提醒事项": "new_reminder",
        "新建一项提醒事项": "new_reminder",
        "新建提醒": "new_reminder",
        "新提醒": "new_reminder",
        "创建提醒事项": "new_reminder",
        "创建一个提醒事项": "new_reminder",
        "创建一条提醒事项": "new_reminder",
        "创建一项提醒事项": "new_reminder",
        "创建提醒": "new_reminder",
        "创建一个提醒": "new_reminder",
        "新建日程": "new_event",
        "新建一个日程": "new_event",
        "新建一条日程": "new_event",
        "新建日历事件": "new_event",
        "新建一个日历事件": "new_event",
        "新日程": "new_event",
        "创建日程": "new_event",
        "创建一个日程": "new_event",
        "创建一条日程": "new_event",
        "创建日历事件": "new_event",
        "创建一个日历事件": "new_event",
        "新建事件": "new_event",
        "新建一个事件": "new_event",
        "新事件": "new_event",
        "创建事件": "new_event",
        "创建一个事件": "new_event",
        "newnote": "new_note",
        "makeanewnote": "new_note",
        "createanewnote": "new_note",
        "makenewnote": "new_note",
        "createnewnote": "new_note",
        "newreminder": "new_reminder",
        "makeanewreminder": "new_reminder",
        "createanewreminder": "new_reminder",
        "makenewreminder": "new_reminder",
        "createnewreminder": "new_reminder",
        "newevent": "new_event",
        "newcalendarevent": "new_event",
        "makeanewevent": "new_event",
        "createanewevent": "new_event",
        "makenewevent": "new_event",
        "createnewevent": "new_event",
        "makeanewcalendarevent": "new_event",
        "createanewcalendarevent": "new_event",
        "makenewcalendarevent": "new_event",
        "createnewcalendarevent": "new_event",
        "加入书签": "bookmark_page",
        "添加书签": "bookmark_page",
        "收藏当前网页": "bookmark_page",
        "收藏当前页面": "bookmark_page",
        "把当前网页加入书签": "bookmark_page",
        "把当前页面加入书签": "bookmark_page",
        "将当前网页加入书签": "bookmark_page",
        "将当前页面加入书签": "bookmark_page",
        "bookmarkthispage": "bookmark_page",
        "bookmarkcurrentpage": "bookmark_page",
        "addbookmark": "bookmark_page",
        "addcurrentpagetobookmarks": "bookmark_page",
        "打开历史记录": "show_history",
        "显示历史记录": "show_history",
        "浏览器历史记录": "show_history",
        "打开浏览器历史记录": "show_history",
        "显示浏览器历史记录": "show_history",
        "历史记录": "show_history",
        "showhistory": "show_history",
        "openhistory": "show_history",
        "showbrowsinghistory": "show_history",
        "openbrowsinghistory": "show_history",
        "browsinghistory": "show_history",
        "打开开发者工具": "open_devtools",
        "显示开发者工具": "open_devtools",
        "开发者工具": "open_devtools",
        "当前网页开发者工具": "open_devtools",
        "当前页面开发者工具": "open_devtools",
        "打开当前网页开发者工具": "open_devtools",
        "打开当前页面开发者工具": "open_devtools",
        "当前网页的开发者工具": "open_devtools",
        "当前页面的开发者工具": "open_devtools",
        "打开当前网页的开发者工具": "open_devtools",
        "打开当前页面的开发者工具": "open_devtools",
        "打开开发工具": "open_devtools",
        "显示开发工具": "open_devtools",
        "开发工具": "open_devtools",
        "opendevtools": "open_devtools",
        "showdevtools": "open_devtools",
        "opendevelopertools": "open_devtools",
        "showdevelopertools": "open_devtools",
        "developertools": "open_devtools",
        "currentpagedevtools": "open_devtools",
        "opencurrentpagedevtools": "open_devtools",
        "currentpagedevelopertools": "open_devtools",
        "opencurrentpagedevelopertools": "open_devtools",
        "currentpageinspect": "open_devtools",
        "inspectcurrentpage": "open_devtools",
        "网页放大": "zoom_in",
        "页面放大": "zoom_in",
        "放大网页": "zoom_in",
        "放大页面": "zoom_in",
        "放大当前网页": "zoom_in",
        "放大当前页面": "zoom_in",
        "zoomin": "zoom_in",
        "zoominpage": "zoom_in",
        "zoominthispage": "zoom_in",
        "increasezoom": "zoom_in",
        "网页缩小": "zoom_out",
        "页面缩小": "zoom_out",
        "缩小网页": "zoom_out",
        "缩小页面": "zoom_out",
        "缩小当前网页": "zoom_out",
        "缩小当前页面": "zoom_out",
        "zoomout": "zoom_out",
        "zoomoutpage": "zoom_out",
        "zoomoutthispage": "zoom_out",
        "decreasezoom": "zoom_out",
        "实际大小": "reset_zoom",
        "重置缩放": "reset_zoom",
        "重置页面缩放": "reset_zoom",
        "网页缩放重置": "reset_zoom",
        "页面缩放重置": "reset_zoom",
        "恢复实际大小": "reset_zoom",
        "resetzoom": "reset_zoom",
        "resetpagezoom": "reset_zoom",
        "actualsize": "reset_zoom",
    }
    return mapping.get(phrase, "")


def _strip_desktop_action_request_shell(value: str) -> str:
    phrase = _strip_query(value)
    phrase = re.sub(
        r"^(?:你|您)?\s*"
        r"(?:(?:可不可以|可以|能不能|能否|能|要不要|想不想)?\s*帮我|帮我|请|麻烦|"
        r"能否|能不能|能(?!不能|否)|可以)?"
        r"(?:直接)?\s*",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"^(?:(?:can|could|would|will)\s+you\s+)?(?:please\s+)?",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"\s*(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please|for\s+me)$",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    return phrase.strip()


def _strip_foreground_action_target(value: str) -> str:
    phrase = _strip_query(value)
    phrase = re.sub(
        r"^(?:在|向|给)?\s*"
        r"(?:(?:当前|现在|这个|该)\s*(?:窗口|应用|app|界面|输入框)|前台|foreground|frontmost|"
        r"current\s+window|active\s+window)"
        r"(?:里|中|内|上)?\s*"
        r"(?=(?:按一下|按下|按|敲一下|敲下|敲|发送|触发)|(?:press|hit|tap)\b|"
        r"(?:回车|enter|return|tab|escape|esc|space|空格|退出|上箭头|下箭头|左箭头|右箭头))",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"\s+(?:in|on|to)\s+(?:the\s+)?"
        r"(?:current|active|foreground|frontmost)\s+"
        r"(?:window|app|application)$",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    return phrase.strip()


def _safe_shortcut_action_from_hotkey(text: str) -> str:
    phrase = _strip_foreground_action_target(_strip_desktop_action_request_shell(text))
    phrase = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:按一下|按下|按|执行|触发|发送|敲一下|敲下|敲)|(?:press|hit|tap|send|trigger))?\s*",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"\s*(?:一下|下|一次|键|快捷键|热键|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)$",
        "",
        phrase,
    ).strip()
    parsed = _parse_hotkey_combo(phrase)
    if not parsed:
        return ""
    key = str(parsed.get("key") or "").strip().lower()
    modifiers = frozenset(str(item).strip().lower() for item in parsed.get("modifiers") or [])
    if not key or not modifiers.issubset({"command", "shift", "option"}):
        return ""
    mapping = {
        ("c", frozenset({"command"})): "copy",
        ("v", frozenset({"command"})): "paste",
        ("a", frozenset({"command"})): "select_all",
        ("z", frozenset({"command"})): "undo",
        ("z", frozenset({"command", "shift"})): "redo",
        ("f", frozenset({"command"})): "find",
        ("l", frozenset({"command"})): "focus_address_bar",
        ("t", frozenset({"command"})): "new_tab",
        ("t", frozenset({"command", "shift"})): "reopen_closed_tab",
        ("n", frozenset({"command", "shift"})): "new_private_window",
        ("`", frozenset({"command"})): "next_window",
        ("`", frozenset({"command", "shift"})): "previous_window",
        ("w", frozenset({"command"})): "close_tab",
        ("n", frozenset({"command"})): "new_window",
        ("r", frozenset({"command"})): "refresh",
        ("d", frozenset({"command"})): "bookmark_page",
        ("y", frozenset({"command"})): "show_history",
        ("i", frozenset({"command", "option"})): "open_devtools",
        ("0", frozenset({"command"})): "reset_zoom",
        ("h", frozenset({"command", "option"})): "hide_other_apps",
    }
    return mapping.get((key, modifiers), "")


def _desktop_safe_key(text: str) -> dict[str, Any] | None:
    text = _strip_foreground_action_target(_strip_desktop_action_request_shell(text))
    if _is_show_desktop_request(text):
        return {"action": "show_desktop", "repeat_count": 1}
    if _is_next_foreground_focus_request(text):
        return {"action": "tab", "repeat_count": 1}
    if _is_previous_foreground_focus_request(text):
        return {"action": "shift_tab", "repeat_count": 1}
    count = r"(?P<{name}>\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|seven|eight|nine|ten)"
    key = (
        r"(?P<{name}>esc|escape|tab|home|end|page\s*up|page\s*down|pageup|pagedown|"
        r"up\s+arrow|down\s+arrow|left\s+arrow|right\s+arrow|arrow\s+up|arrow\s+down|"
        r"arrow\s+left|arrow\s+right|up|down|left|right|"
        r"退出|取消|制表键|制表|向上箭头|往上箭头|朝上箭头|向下箭头|往下箭头|朝下箭头|"
        r"向左箭头|往左箭头|朝左箭头|向右箭头|往右箭头|朝右箭头|"
        r"上箭头|下箭头|左箭头|右箭头|上方向键|下方向键|左方向键|右方向键|"
        r"向上键|向下键|向左键|向右键|上|下|左|右|"
        r"上一页键|下一页键|上一页|下一页|home\s*键|end\s*键)"
    )
    patterns = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:按一下|按下|按|发送|触发)\s*"
            rf"(?:{count.format(name='count_before')}\s*(?:次|下)\s*)?"
            rf"{key.format(name='key')}"
            rf"(?:\s*{count.format(name='count_after')}\s*(?:次|下))?"
            r"\s*(?:键)?(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            r"^(?:please\s+)?(?:press|send|hit)\s+(?:the\s+)?"
            rf"{key.format(name='key_en')}"
            rf"(?:\s+{count.format(name='count_en')}\s*(?:times?)?)?\s*$"
        ),
        (
            rf"^(?:please\s+)?{count.format(name='count_en_before')}\s*(?:times?\s+)?"
            r"(?:press|send|hit)\s+(?:the\s+)?"
            rf"{key.format(name='key_en_before')}\s*$"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_key = (
            groups.get("key")
            or groups.get("key_en")
            or groups.get("key_en_before")
            or ""
        )
        action = _safe_key_action(raw_key)
        repeat_count = _safe_key_repeat_count(
            groups.get("count_before")
            or groups.get("count_after")
            or groups.get("count_en")
            or groups.get("count_en_before")
        )
        if action and repeat_count:
            return {"action": action, "repeat_count": repeat_count}
    return None


def _is_show_desktop_request(text: str) -> bool:
    value = str(text or "").strip()
    lowered = value.lower()
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:显示|露出|查看|看看|看一下|切到|切换到|回到|返回到|回)\s*"
            r"(?:当前|现在)?(?:桌面|desktop)"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:show|reveal|switch\s+to|go\s+to)\s+(?:the\s+)?desktop\s*(?:please)?$",
            lowered,
        )
    )


def _is_next_foreground_focus_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|焦点到|focus\s+)?\s*"
            r"(?:下一个|下一项|下个|next)\s*"
            r"(?:输入框|文本框|输入栏|字段|控件|元素|项目|field|input|control|element)?"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:focus|move|go|jump|tab)\s+(?:to\s+)?(?:the\s+)?next\s+"
            r"(?:field|input|control|element)\s*$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _is_previous_foreground_focus_request(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:切到|切换到|跳到|跳转到|移到|移动到|聚焦到|焦点到|focus\s+)?\s*"
            r"(?:上一个|上一项|上个|previous|prev)\s*"
            r"(?:输入框|文本框|输入栏|字段|控件|元素|项目|field|input|control|element)?"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|嘛|吧|呢)?$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^\s*(?:focus|move|go|jump)\s+(?:to\s+)?(?:the\s+)?(?:previous|prev)\s+"
            r"(?:field|input|control|element)\s*$",
            text,
            flags=re.IGNORECASE,
        )
    )


def _safe_key_action(value: str) -> str:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    return {
        "esc": "escape",
        "escape": "escape",
        "退出": "escape",
        "取消": "escape",
        "tab": "tab",
        "制表": "tab",
        "制表键": "tab",
        "up": "arrow_up",
        "uparrow": "arrow_up",
        "arrowup": "arrow_up",
        "上": "arrow_up",
        "上箭头": "arrow_up",
        "上方向键": "arrow_up",
        "向上箭头": "arrow_up",
        "往上箭头": "arrow_up",
        "朝上箭头": "arrow_up",
        "向上键": "arrow_up",
        "down": "arrow_down",
        "downarrow": "arrow_down",
        "arrowdown": "arrow_down",
        "下": "arrow_down",
        "下箭头": "arrow_down",
        "下方向键": "arrow_down",
        "向下箭头": "arrow_down",
        "往下箭头": "arrow_down",
        "朝下箭头": "arrow_down",
        "向下键": "arrow_down",
        "left": "arrow_left",
        "leftarrow": "arrow_left",
        "arrowleft": "arrow_left",
        "左": "arrow_left",
        "左箭头": "arrow_left",
        "左方向键": "arrow_left",
        "向左箭头": "arrow_left",
        "往左箭头": "arrow_left",
        "朝左箭头": "arrow_left",
        "向左键": "arrow_left",
        "right": "arrow_right",
        "rightarrow": "arrow_right",
        "arrowright": "arrow_right",
        "右": "arrow_right",
        "右箭头": "arrow_right",
        "右方向键": "arrow_right",
        "向右箭头": "arrow_right",
        "往右箭头": "arrow_right",
        "朝右箭头": "arrow_right",
        "向右键": "arrow_right",
        "home": "home",
        "home键": "home",
        "end": "end",
        "end键": "end",
        "pageup": "page_up",
        "上一页键": "page_up",
        "上一页": "page_up",
        "pagedown": "page_down",
        "下一页键": "page_down",
        "下一页": "page_down",
    }.get(compact, "")


def _safe_key_repeat_count(value: str | None) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return 1
    if raw.isdigit():
        count = int(raw)
    else:
        count = _SCROLL_PAGE_COUNTS.get(raw, 0)
    return count if 1 <= count <= 20 else 0


_SCROLL_PAGE_COUNTS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _desktop_safe_scroll(text: str) -> dict[str, Any] | None:
    page_count = r"(?P<{name}>\d+|[一二两三四五六七八九十]|one|two|three|four|five|six|seven|eight|nine|ten)"
    zh_prefix = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|把|将)?\s*(?:当前|前台|这个|该)?"
        r"(?:窗口|界面|应用|app|网页|页面|屏幕)?(?:上|里|中|内)?\s*"
    )
    patterns = (
        (
            zh_prefix
            + r"(?:(?:滚动|滚|滑动|滑|翻页|翻|拉|跳|跳转|回)(?:到|至)|到)\s*"
            + r"(?P<direction_extent>页面底部|页面顶部|底部|底端|最底下|最下面|顶部|顶端|最上面|最上方)"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?:滚动|滚|滑动|滑|翻页|翻|拉)(?:到|至)?\s*"
            + r"(?P<direction_near>下面|下方|上面|上方)"
            + r"(?:一点|点|一些|一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?P<direction>向下|往下|朝下|下|向上|往上|朝上|上)"
            + r"(?:滚动|滚|滑动|滑|翻页|翻|拉)"
            + rf"(?:\s*{page_count.format(name='count')}\s*(?:页|屏|次))?"
            + r"(?:一点|点|一些|一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?P<direction_phrase>下滑|上滑|下滚|上滚|下翻|上翻|下一页|上一页)"
            + rf"(?:\s*{page_count.format(name='count_phrase')}\s*(?:页|屏|次))?"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            zh_prefix
            + r"(?:翻到|翻至|滚到|滚至|滑到|滑至|转到|转至|跳到|跳至|到)\s*"
            + r"(?P<direction_target>下一页|上一页)"
            + r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$"
        ),
        (
            r"^(?:please\s+)?(?:scroll|page)\s+"
            r"(?P<direction_en>down|up)"
            + rf"(?:\s+{page_count.format(name='count_en')}\s*(?:pages?|times?)?)?"
            + r"\s*$"
        ),
        (
            r"^(?:please\s+)?(?:scroll|page)\s+"
            r"(?:the\s+)?(?:current\s+)?(?:page|window|screen)\s+"
            r"(?P<direction_en_target>down|up)"
            + rf"(?:\s+{page_count.format(name='count_en_target')}\s*(?:pages?|times?)?)?"
            + r"\s*$"
        ),
        (
            rf"^(?:please\s+)?{page_count.format(name='count_en_prefix')}\s+"
            r"(?:pages?\s+)?(?:scroll|page)\s+(?P<direction_en_prefix>down|up)\s*$"
        ),
        (
            r"^(?:please\s+)?(?:scroll|page)\s+(?:to\s+)?(?:the\s+)?"
            r"(?P<direction_extent_en>bottom|top)\s*$"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        direction = (
            groups.get("direction_extent")
            or groups.get("direction_near")
            or groups.get("direction")
            or groups.get("direction_phrase")
            or groups.get("direction_target")
            or groups.get("direction_en")
            or groups.get("direction_en_target")
            or groups.get("direction_en_prefix")
            or groups.get("direction_extent_en")
            or ""
        )
        pages = (
            10
            if groups.get("direction_extent") or groups.get("direction_extent_en")
            else _scroll_page_count(
                groups.get("count")
                or groups.get("count_phrase")
                or groups.get("count_en")
                or groups.get("count_en_target")
                or groups.get("count_en_prefix")
            )
        )
        if direction and pages:
            return {
                "direction": "up" if _scroll_direction_is_up(direction) else "down",
                "pages": pages,
            }
    if re.search(
        zh_prefix + r"(?:滚动|滚|滑动|滑|翻页|翻|拉)(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        text,
        flags=re.IGNORECASE,
    ) or re.search(r"^(?:please\s+)?(?:scroll|page)(?:\s+(?:a\s+)?(?:little|bit))?\s*$", text, flags=re.IGNORECASE):
        return {"direction": "down", "pages": 1}
    return None


def _scroll_direction_is_up(value: str) -> bool:
    direction = str(value or "").strip().lower()
    return direction in {
        "向上",
        "往上",
        "朝上",
        "上",
        "上滑",
        "上滚",
        "上翻",
        "上一页",
        "上面",
        "上方",
        "页面顶部",
        "顶部",
        "顶端",
        "最上面",
        "最上方",
        "up",
        "top",
    }


def _scroll_page_count(value: str | None) -> int:
    raw = str(value or "").strip().lower()
    if not raw:
        return 1
    if raw.isdigit():
        count = int(raw)
    else:
        count = _SCROLL_PAGE_COUNTS.get(raw, 0)
    return count if 1 <= count <= 10 else 0


def _normalize_named_hotkey_phrase(text: str) -> str:
    phrase = _strip_desktop_action_request_shell(text)
    phrase = re.sub(
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:按一下|按下|按|执行|触发|发送)?\s*",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    phrase = re.sub(
        r"\s*(?:一下|下|一次|键|快捷键|热键|可以吗|好吗|好么|行吗|吗|嘛|吧|呢|please|for\s+me)$",
        "",
        phrase,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[\s._-]+", "", phrase.lower())


def _parse_hotkey_combo(value: str) -> dict[str, Any] | None:
    return parse_hotkey_combo(value)


def _desktop_type_text(text: str) -> str:
    if _browser_type_text_request(text) or _desktop_type_into_ui_element(text):
        return ""
    if _desktop_submit_foreground_action(text):
        return ""
    if _is_next_foreground_focus_request(text) or _is_previous_foreground_focus_request(text):
        return ""
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前|前台|这个|该)?(?:输入框|文本框|输入栏)"
        r"(?:里|中|内|上)?\s*(?:输入|打字|键入|敲入|打入|打上|填写|填入|写入|写)\s*"
        r"(?:文本|文字|内容)?\s*"
        r"(?P<current_input_text>.+)$",
        r"(?:type|enter|input|fill)\s+(?P<current_input_text_en>[^.!?]+?)\s+"
        r"(?:into|in|to)\s+(?:the\s+)?(?:current|foreground|active)\s+"
        r"(?:input|field|text\s+field|textbox)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在前台|向前台|给当前窗口)?"
        r"(?:输入|打字|键入|敲入|打入|打上)\s*(?:文本|文字|内容)?\s*(?P<text>.+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在前台|向前台|给当前窗口|在当前窗口)\s*(?:写入|写)\s*(?P<text>.+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在前台|向前台|给当前窗口|在当前窗口)?"
        r"打\s+(?P<text>.+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?把\s*(?P<text>.+?)\s*"
        r"(?:输入|打字|键入|敲入|打入|打上|打)\s*(?:进去|到当前窗口|到前台)?$",
        r"(?:type|enter text)\s+(?P<text>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        typed_text = _strip_typed_text(
            groups.get("current_input_text")
            or groups.get("current_input_text_en")
            or groups.get("text")
            or ""
        )
        if typed_text:
            return typed_text
    return ""


def _desktop_type_into_ui_element(text: str) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    text = _strip_query(text)
    bare_target_pattern = (
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search\s+field|search\s+box|search\s+bar|message\s+field|message\s+box|"
        r"chat\s+box|address\s+bar|text\s+field|textbox|input|field)"
    )
    target_pattern = (
        rf"(?:{bare_target_pattern}|[^。！？!?，,]+?(?:输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"text\s+field|textbox|input|field|search\s+field|search\s+box|search\s+bar|"
        r"message\s+field|message\s+box|chat\s+box|address\s+bar))"
    )
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?"
        r"(?:上|里|中|内|的|里的|中的)?\s*"
        r"(?:(?:打开|点开|点击|点一下|聚焦|选中)\s*)?"
        rf"(?P<target>{target_pattern})(?:里|中|内|上)?\s*"
        r"(?:输入|填写|键入|打入|填入|写入|写)\s*(?P<text>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:填写|填入|把|将)?\s*(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?"
        r"(?:上|里|中|内|的|里的|中的)?\s*"
        r"(?:(?:打开|点开|点击|点一下|聚焦|选中)\s*)?"
        rf"(?P<target2>{target_pattern})\s*(?:为|成|:|：)\s*(?P<text2>[^。！？!?]+)$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:type|enter|fill)\s+(?P<text_en>[^.!?]+?)\s+"
        r"(?:into|in)\s+(?:the\s+)?"
        rf"(?P<target_en>{target_pattern})"
        r"(?:\s+(?:in|on)\s+(?:the\s+)?(?:current|foreground)\s+(?:window|app|application|ui))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_target = groups.get("target") or groups.get("target2") or groups.get("target_en") or ""
        raw_text = groups.get("text") or groups.get("text2") or groups.get("text_en") or ""
        typed_text = _strip_typed_text(raw_text)
        target = _strip_desktop_ui_input_target(raw_target)
        if not target or not typed_text:
            continue
        if _is_current_foreground_input_target(raw_target, target, text):
            continue
        return {
            "target": target,
            "text": typed_text,
            "role_filter": _desktop_ui_element_role_filter(raw_target),
            "limit": 80,
        }
    return None


def _is_current_foreground_input_target(raw_target: str, target: str, text: str) -> bool:
    compact_raw = re.sub(r"[\s._-]+", "", _strip_query(raw_target).lower())
    compact_target = re.sub(r"[\s._-]+", "", _strip_query(target).lower())
    if compact_target in {
        "current",
        "foreground",
        "active",
        "当前",
        "前台",
        "这个",
        "该",
    }:
        return True
    if compact_raw in {
        "currentinput",
        "currentfield",
        "currenttextfield",
        "currenttextbox",
        "foregroundinput",
        "foregroundfield",
        "foregroundtextfield",
        "foregroundtextbox",
        "activeinput",
        "activefield",
        "activetextfield",
        "activetextbox",
        "当前输入框",
        "当前文本框",
        "当前输入栏",
        "前台输入框",
        "前台文本框",
        "前台输入栏",
    }:
        return True
    generic_target = compact_target in {
        "input",
        "field",
        "textfield",
        "textbox",
        "输入框",
        "文本框",
        "输入栏",
    }
    return bool(
        generic_target
        and re.search(
            r"(?:当前|前台|这个|该|\bcurrent\b|\bforeground\b|\bactive\b)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _desktop_safe_type_text(text: str) -> str:
    return _desktop_type_text(text)


def _strip_typed_text(value: str) -> str:
    text = _strip_query(value)
    text = re.sub(r"\s*(?:进去|到当前窗口|到前台|然后回车|并回车)$", "", text)
    text = re.sub(r"\s+(?:回车|确认|确定)$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\s*(?:然后|并且|并|再|接着)\s*(?:按|执行|开始)?"
        r"(?:回车|确认|确定|搜索|查找|检索|访问|打开|发送|发出|提交)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*(?:and\s+then|then|and)\s*(?:press\s+)?"
        r"(?:enter|return|search|find|go|visit|open|send|submit|post)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return _strip_query(text)


def _desktop_click(text: str) -> dict[str, Any] | None:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|点|click)\s*"
        r"(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|到)\s*(?:屏幕坐标|屏幕|坐标|位置)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)\s*"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|点|click)",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            break
    if not match:
        return None
    payload: dict[str, Any] = {
        "x": _number_value(match.group("x")),
        "y": _number_value(match.group("y")),
        "click_count": 2 if match.group("double") else 1,
    }
    return payload


def _desktop_safe_click(text: str) -> dict[str, Any] | None:
    payload = _desktop_click(text)
    if not payload or payload.get("click_count") != 1:
        return None
    return {"x": payload["x"], "y": payload["y"]}


def _desktop_click_ui_element(text: str, *, require_context: bool = True) -> dict[str, Any] | None:
    if _has_browser_page_context(text):
        return None
    text = _strip_query(text)
    if _is_ui_elements_location_request(text):
        return None
    if _desktop_submit_foreground_action(text):
        return None
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击)|点击|点一下|点按|单击|点|按一下|按)\s*"
        r"(?P<context>(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)?(?:上|里|中|内|的|里的|中的)?)\s*"
        r"(?P<label>[^。！？!?，,]+?)"
        r"(?P<kind>按钮|控件|元素|输入框|文本框|输入栏|搜索框|搜索栏|搜索输入框|菜单项|菜单|复选框)?"
        r"(?:一下|一次)?$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:(?P<double_en>double\s+click)|click|press|tap)\s+"
        r"(?:the\s+)?(?P<label_en>[^.!?]+?)"
        r"(?:\s+(?P<kind_en>button|control|element|field|input|text field|textbox|"
        r"search field|search box|search bar|menu item|menu|checkbox))?"
        r"(?:\s+(?:in|on)\s+(?:the\s+)?(?:current|foreground)\s+(?:window|app|application|ui))?$",
    )
    candidate_texts = [text]
    scoped_text = _strip_preposed_desktop_click_scope(text)
    if scoped_text and scoped_text not in candidate_texts:
        candidate_texts.append(scoped_text)
    for candidate_text in candidate_texts:
        for pattern in patterns:
            match = re.search(pattern, candidate_text, flags=re.IGNORECASE)
            if not match:
                continue
            groups = match.groupdict()
            raw_label = groups.get("label") or groups.get("label_en") or ""
            kind = groups.get("kind") or groups.get("kind_en") or ""
            context = groups.get("context") or ""
            label = _strip_desktop_ui_element_label(raw_label)
            if not label:
                label = _strip_desktop_ui_input_target(raw_label)
            has_short_label = _desktop_ui_click_has_short_label(label, text=candidate_text)
            if (
                require_context
                and not kind
                and not _desktop_ui_click_has_context(candidate_text, context)
                and not has_short_label
            ):
                continue
            if not label or _looks_like_click_coordinate_label(label):
                continue
            role_filter = _desktop_ui_element_role_filter(kind or candidate_text)
            if not role_filter and has_short_label:
                role_filter = "button"
            return {
                "target": label,
                "role_filter": role_filter,
                "limit": 80,
                "click_count": 2 if groups.get("double") or groups.get("double_en") else 1,
            }
    return None


def _strip_preposed_desktop_click_scope(text: str) -> str:
    stripped = _strip_query(text)
    if not stripped:
        return ""
    return _strip_query(
        re.sub(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|到)?\s*"
            r"(?:(?:当前|前台|这个|该)(?:窗口|界面|应用|app)?|"
            r"(?:current|foreground)\s+(?:window|app|application|ui))"
            r"(?:上|里|中|内|的|里的|中的)?\s*"
            r"(?=(?:双击|点击|点一下|点按|单击|点|按一下|按|"
            r"double\s+click|click|press|tap))",
            "",
            stripped,
            flags=re.IGNORECASE,
        )
    )


def _desktop_ui_click_has_context(text: str, context: str) -> bool:
    return bool(
        str(context or "").strip()
        or re.search(
            r"(?:当前|前台|界面|窗口|应用|控件|按钮|元素|输入框|文本框|输入栏|菜单|复选框)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:current|foreground)\s+(?:window|app|application|ui)\b"
            r"|\b(?:button|control|element|field|input|text field|textbox|menu item|menu|checkbox)\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _desktop_ui_click_has_short_label(label: str, *, text: str = "") -> bool:
    normalized = _strip_query(label)
    if not normalized or _looks_like_click_coordinate_label(normalized):
        return False
    compact = re.sub(r"\s+", " ", normalized).strip().lower()
    if _desktop_ui_click_short_label_is_key_like(compact) and re.search(
        r"^\s*(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:按一下|按下|按|press|hit|tap)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    if compact in {
        "it",
        "this",
        "that",
        "there",
        "here",
        "thing",
        "item",
        "这个",
        "那个",
        "这里",
        "那里",
        "它",
        "他",
        "她",
        "按钮",
        "控件",
        "元素",
    }:
        return False
    if len(normalized) > 48:
        return False
    if len([part for part in compact.split(" ") if part]) > 5:
        return False
    return True


def _desktop_ui_click_short_label_is_key_like(label: str) -> bool:
    compact = re.sub(r"\s+", " ", label).strip().lower()
    if not compact:
        return False
    key_phrase = re.sub(r"\s+key$", "", compact)
    if _parse_hotkey_combo(key_phrase):
        return True
    if re.search(r"(?:command|cmd|control|ctrl|shift|option|alt|fn|⌘|⇧|⌥|⌃|\+)", compact):
        return True
    return bool(
        re.search(r"(?:回车|确认|确定|enter|return)(?:\s+key)?(?:提交|发送|send|submit)?$", compact)
    )


def _strip_desktop_ui_element_label(value: str) -> str:
    label = _strip_query(value)
    label = re.sub(
        r"^(?:当前|前台|这个|该)?(?:窗口|界面|应用|app)(?:上|里|中|内|的|里的|中的)?\s*",
        "",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(r"^(?:visible|shown|available)\s+", "", label, flags=re.IGNORECASE)
    label = re.sub(r"^(?:可见|看得到|能看到)(?:的)?\s*", "", label)
    label = re.sub(
        r"\s*(?:按钮|控件|元素|输入框|文本框|输入栏|菜单项|菜单|复选框|"
        r"搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"button|control|element|field|input|text field|textbox|search field|search box|"
        r"search bar|message field|message box|chat box|address bar|menu item|menu|checkbox)$",
        "",
        label,
        flags=re.IGNORECASE,
    )
    return _strip_query(label)


def _strip_desktop_ui_input_target(value: str) -> str:
    target = _strip_desktop_ui_element_label(value)
    if target and target not in {"在", "向", "给"}:
        return target
    compact = _strip_query(value)
    compact = re.sub(r"^(?:在|向|给)\s*", "", compact)
    target = _strip_desktop_ui_element_label(compact)
    if target:
        return target
    fallback_targets = {
        "搜索框": "搜索",
        "搜索栏": "搜索",
        "消息框": "消息",
        "聊天框": "聊天",
        "地址栏": "地址",
        "search field": "search",
        "search box": "search",
        "search bar": "search",
        "message field": "message",
        "message box": "message",
        "chat box": "chat",
        "address bar": "address",
    }
    return fallback_targets.get(compact.lower(), compact)


def _desktop_ui_element_role_filter(value: str) -> str:
    lowered = str(value or "").lower()
    if re.search(r"(?:按钮|button)", lowered, flags=re.IGNORECASE):
        return "button"
    if re.search(
        r"(?:输入框|文本框|输入栏|搜索框|搜索栏|消息框|聊天框|地址栏|"
        r"text field|textbox|input|field|search field|search box|search bar|"
        r"message field|message box|chat box|address bar)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return "text"
    if re.search(r"(?:菜单项|菜单|menu item|menu)", lowered, flags=re.IGNORECASE):
        return "menu"
    if re.search(r"(?:复选框|checkbox)", lowered, flags=re.IGNORECASE):
        return "checkbox"
    return ""


def _is_close_current_window_request(text: str) -> bool:
    lowered = text.lower()
    close_verb = r"(?:关闭|关掉|关上|关(?:一下|下|了)?)(?:一下|下|掉|了)?"
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"{close_verb}\s*(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            rf"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)\s*{close_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:当前|现在|前台|这个|该)\s*(?:窗口|window)\s*{close_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:close|dismiss)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window\b",
            lowered,
        )
    )


def _is_quit_current_app_request(text: str) -> bool:
    text = _strip_desktop_action_request_shell(text)
    lowered = text.lower()
    quit_verb = r"(?:退出|关闭|关掉|结束|终止|关(?:一下|下|了)?)(?:一下|下|掉|了)?"
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"{quit_verb}\s*(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)(?:一下|下)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            rf"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)\s*{quit_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:当前|现在|前台|这个|该)\s*(?:应用|app|软件|程序)\s*{quit_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:quit|close|exit|terminate)\s+(?:the\s+)?"
            r"(?:current|foreground|active|this)\s+(?:app|application)\b",
            lowered,
        )
    )


def _is_minimize_current_window_request(text: str) -> bool:
    text = _strip_desktop_action_request_shell(text)
    lowered = text.lower()
    minimize_verb = r"(?:最小化|收起|收起来|隐藏)(?:一下|下)?"
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"{minimize_verb}\s*(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            rf"(?:当前|现在|前台|这个|该)?\s*(?:窗口|window)\s*{minimize_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:当前|现在|前台|这个|该)\s*(?:窗口|window)\s*{minimize_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:minimi[sz]e|hide)\s+(?:the\s+)?(?:current|foreground|active|this)\s+window\b",
            lowered,
        )
    )


def _is_hide_current_app_request(text: str) -> bool:
    text = _strip_desktop_action_request_shell(text)
    if _is_show_all_apps_request(text):
        return False
    lowered = text.lower()
    hide_verb = r"(?:隐藏|收起|藏起|藏起来)(?:一下|下|起来)?"
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"{hide_verb}\s*(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)(?:一下|下)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            rf"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)\s*{hide_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:当前|现在|前台|这个|该)\s*(?:应用|app|软件|程序)\s*{hide_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bhide\s+(?:the\s+)?(?:current|foreground|active|this)\s+"
            r"(?:app|application)\b",
            lowered,
        )
    )


def _is_show_all_apps_request(text: str) -> bool:
    text = _strip_desktop_action_request_shell(text)
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:(?:显示|还原|恢复|调出|叫出)\s*"
            r"(?:所有隐藏|全部隐藏|所有|全部|隐藏的|被隐藏的|藏起来的)\s*"
            r"(?:应用|app|软件|程序)(?:窗口)?|"
            r"取消隐藏\s*(?:所有|全部|隐藏的|被隐藏的|藏起来的)?\s*"
            r"(?:应用|app|软件|程序)(?:窗口)?)"
            r"(?:出来|一下|下)?[?？。！!]*$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)?\s*"
            r"(?:所有隐藏|全部隐藏|所有|全部|隐藏的|被隐藏的|藏起来的)\s*"
            r"(?:应用|app|软件|程序)(?:窗口)?\s*"
            r"(?:显示|还原|恢复|取消隐藏|调出来|叫出来)"
            r"(?:出来|一下|下)?[?？。！!]*$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:show|unhide|restore)\s+"
            r"(?:all\s+)?(?:hidden\s+)?(?:apps?|applications?)\b",
            lowered,
        )
        or re.search(
            r"\b(?:show|unhide|restore)\s+(?:all|hidden)\b",
            lowered,
        )
    )


def _is_minimize_current_app_request(text: str) -> bool:
    text = _strip_desktop_action_request_shell(text)
    lowered = text.lower()
    minimize_verb = r"(?:最小化|收起|收起来)(?:一下|下)?"
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"{minimize_verb}\s*(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)(?:一下|下)?",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            rf"(?:当前|现在|前台|这个|该)?\s*(?:应用|app|软件|程序)\s*{minimize_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:当前|现在|前台|这个|该)\s*(?:应用|app|软件|程序)\s*{minimize_verb}",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\bminimi[sz]e\s+(?:the\s+)?(?:current|foreground|active|this)\s+"
            r"(?:app|application)\b",
            lowered,
        )
    )


def _number_value(value: str) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _percentage_value(value: str) -> int | None:
    try:
        number = int(float(str(value or "").strip()))
    except (TypeError, ValueError):
        return None
    if number < 0 or number > 100:
        return None
    return number


def _strip_query(value: str) -> str:
    return str(value or "").strip(" 「」『』“”\"'`，,。.!?？！？ ")


def _strip_browser_followup(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|后|再)\s*"
        r"(?:读取|读一下|读下|读一读|提取|抓取|获取|查看|看看|看一下|"
        r"总结|摘要|概括|截取|截图|截屏|截一下|截个图|截|抓屏).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+"
        r"(?:读取|阅读|读一下|读下|读一读|读|提取|抓取|获取|查看|看看|看一下|看下|总结|摘要|概括)"
        r"(?:一下|下)?(?:网页|页面|网站|正文|文字|文本|内容)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:截取|截图|截屏|截一下|截个图|截|抓屏|屏幕截图)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and|then)\s+"
        r"(?:read|extract|get|summari[sz]e|take\s+a\s+screenshot|screenshot|capture).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip()


def _strip_polite_suffix(value: str) -> str:
    return re.sub(
        r"\s*(?:一下|一下儿|一下子|看一下|看下|看看|给我看一下|给我看下|给我看看|给我看|可以吗|好吗|好么|行吗|吗|嘛|吧|呢|帮我|给我|please|for\s+me)$",
        "",
        str(value or "").strip(),
        flags=re.IGNORECASE,
    ).strip()


def _is_screen_capture_request(text: str) -> bool:
    if _is_screenshot_tool_open_request(text):
        return False
    lowered = text.lower()
    return bool(
        re.search(r"(?:截(?:一下|下)图|截个?图|截个?屏|截图|截屏|屏幕截图|抓屏|拍屏)", text)
        or re.search(r"(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面).{0,8}(?:截图|截屏|截一下|截个图|抓屏|拍屏)", text)
        or re.search(r"(?:截取|截图|截屏|截一下|截个图|截|抓屏|拍屏).{0,8}(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面)", text)
        or re.search(r"(?:拍一下|拍下|拍一张|拍个).{0,8}(?:屏幕|桌面|界面|画面)", text)
        or re.search(r"(?:看一下|看看|看下|查看|读取|观察(?:一下|下)?|识别(?:一下|下)?).{0,12}(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面)", text)
        or re.search(r"(?:当前|现在|这个|我的|我现在的)?(?:屏幕|桌面|界面|画面).{0,8}(?:是什么|是啥|内容|画面|有什么|有啥)", text)
        or "take a screenshot" in lowered
        or "capture the screen" in lowered
        or "screen capture" in lowered
        or re.search(r"\bscreenshot\s+(?:my|the|this|current)?\s*(?:screen|desktop)?\b", lowered)
        or re.search(r"\b(?:look at|inspect|view|read|show me|show)\s+(?:my|the|this|current)?\s*(?:screen|desktop|interface|ui)\b", lowered)
        or re.search(r"\bwhat(?:'s| is)?\s+on\s+(?:my|the|this|current)?\s*(?:screen|desktop)\b", lowered)
    )


def _is_screenshot_tool_open_request(text: str) -> bool:
    phrase = _normalize_named_hotkey_phrase(text)
    if phrase in {
        "截图工具",
        "打开截图工具",
        "显示截图工具",
        "启动截图工具",
        "截图面板",
        "打开截图面板",
        "显示截图面板",
        "启动截图面板",
        "屏幕截图工具",
        "打开屏幕截图工具",
        "屏幕截图面板",
        "打开屏幕截图面板",
        "screenshottoolbar",
        "openscreenshottoolbar",
        "showscreenshottoolbar",
        "launchscreenshottoolbar",
        "screenshottool",
        "openscreenshottool",
        "screenshotpanel",
        "openscreenshotpanel",
        "screencapturetoolbar",
        "openscreencapturetoolbar",
        "screencapturetool",
        "openscreencapturetool",
        "screencapturepanel",
        "openscreencapturepanel",
    }:
        return True
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return bool(
        re.search(
            r"\b(?:open|show|launch)\s+(?:the\s+)?"
            r"(?:screenshot|screen\s+capture)\s+(?:toolbar|panel|tool)\b",
            lowered,
        )
    )


def _looks_like_screen_observation_target(value: str) -> bool:
    text = _strip_app_name(value).strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(
        r"^(?:帮我|给我|请|麻烦)?(?:看看|看一下|看下|显示|展示)?"
        r"(?:我)?(?:现在|当前|这个|该)?(?:的)?",
        "",
        compact,
    )
    if compact in {"屏幕", "桌面", "界面", "画面"}:
        return True

    lowered = text.lower()
    lowered = re.sub(r"\s+", " ", lowered).strip()
    for _ in range(3):
        next_lowered = re.sub(r"^(?:me|my|the|this|current)\s+", "", lowered).strip()
        if next_lowered == lowered:
            break
        lowered = next_lowered
    return bool(re.fullmatch(r"(?:screen|desktop|interface|ui)", lowered))


def _is_known_app_reference(value: str) -> bool:
    app = _strip_app_name(value)
    compact = _compact_app_alias(app)
    if not compact:
        return False
    return any(compact == _compact_app_alias(alias) for alias, _app_name in _known_app_followup_aliases())


def _is_active_window_app_check_request(text: str) -> bool:
    stripped = _strip_query(text)
    if not stripped:
        return False
    patterns = (
        r"^(?:当前|现在|前台|当前前台).{0,8}(?:是不是|是否是|是)\s*"
        r"(?P<app>[^。！？!?，,]+?)(?:里|中|内|上|里面)?$",
        r"^(?:我)?(?:现在|当前).{0,8}(?:是不是|是否是)?\s*在\s*"
        r"(?P<app>[^。！？!?，,]+?)(?:里|中|内|上|里面)?$",
        r"^(?P<app>[^。！？!?，,]+?)\s*(?:是不是|是否是|是)?(?:当前|现在)?"
        r"(?:前台|当前前台)(?:应用|app)?$",
        r"^am\s+i\s+(?:currently\s+)?(?:in|using|on)\s+(?P<app>[^.!?]+)$",
        r"^is\s+(?P<app>[^.!?]+?)\s+(?:the\s+)?(?:active|foreground|frontmost)"
        r"(?:\s+(?:app|application|window))?$",
        r"^is\s+(?:the\s+)?(?:active|foreground|frontmost)\s+(?:app|application|window)"
        r"\s+(?P<app>[^.!?]+)$",
    )
    return any(
        (match := re.search(pattern, stripped, flags=re.IGNORECASE))
        and _is_known_app_reference(match.group("app"))
        for pattern in patterns
    )


def _is_active_window_request(text: str) -> bool:
    if _is_running_apps_request(text):
        return False
    if _looks_like_window_management_action(text):
        return False
    if re.search(r"(?:关闭|关掉|退出|结束|close|quit|exit)", text, flags=re.IGNORECASE):
        return False
    if re.search(r"(?:哪些|几个|多少).{0,4}(?:窗口|windows?)", text, flags=re.IGNORECASE):
        return False
    if _is_current_window_observation_request(text):
        return True
    if re.search(
        r"(?:列出|列一下|列下|显示|查看|看看|看一下|看下|读取).{0,12}(?:窗口|windows?)|"
        r"(?:窗口|windows?).{0,8}(?:列表|清单|列出|列一下|列下)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    if _is_current_ui_text_request(text):
        return False
    lowered = text.lower()
    return bool(
        re.search(
            r"(?:当前|现在|前台).{0,8}(?:窗口|应用|app).{0,8}"
            r"(?:是什么|是啥|哪个|名字|标题)?",
            text,
        )
        or re.search(
            r"(?:当前|现在).{0,8}(?:用的是|正在用).{0,8}(?:哪个|什么).{0,4}(?:app|应用)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:我)?(?:当前|现在)?\s*(?:正在用|在用|用的是)\s*(?:哪个|什么).{0,4}(?:app|应用)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:(?:当前|现在)\s*)?前台\s*(?:窗口|应用|app)?\s*(?:是什么|是啥|哪个|什么)",
            text,
        )
        or "active window" in lowered
        or "foreground window" in lowered
        or "frontmost window" in lowered
        or "current window" in lowered
        or "current app" in lowered
        or re.search(r"\b(?:what|which)\s+(?:app|application)\s+is\s+(?:active|foreground|frontmost)\b", lowered)
        or re.search(r"\b(?:what|which)\s+(?:app|application)\s+am\s+i\s+using\b", lowered)
        or re.search(r"\bwhat(?:'s|\s+is)\s+(?:the\s+)?(?:active|foreground|frontmost)\s+(?:app|application)\b", lowered)
        or re.search(r"\b(?:what|which)\s+window\s+is\s+(?:active|current|foreground)\b", lowered)
        or _is_active_window_app_check_request(text)
    )


def _is_current_window_observation_request(text: str) -> bool:
    if re.search(
        r"(?:列表|清单|所有|全部|哪些|几个|多少|list|all|windows)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    lowered = text.lower()
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:查看|看看|看一下|看下|显示|读取)?\s*"
            r"(?:当前|现在|前台|这个|该)\s*(?:窗口|window)"
            r"\s*(?:是什么|是啥|哪个|什么|标题|名称|名字)?"
            r"(?:一下|下|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:show|read|inspect|look\s+at|check)\s+"
            r"(?:the\s+)?(?:current|active|foreground|frontmost|this)\s+window\b",
            lowered,
        )
    )


__all__ = [
    "daily_desktop_entrypoint_tool_requests",
    "daily_desktop_intent_candidates",
    "daily_desktop_intent_sequence_candidates",
    "daily_desktop_intent_tool_request",
    "daily_desktop_intent_tool_requests",
    "daily_desktop_recovery_prompt",
]
