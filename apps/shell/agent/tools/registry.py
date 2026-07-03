"""ToolBroker dispatch registry.

This keeps tool-name routing separate from the concrete broker operations while
preserving the legacy ToolBroker.call surface.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote_plus

from apps.shell.agent.runtime.errors import AgentRuntimeError

ToolDispatchHandler = Callable[[Any, dict[str, Any], bool], dict[str, Any]]


def _skill_read(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.skill_read(
        str(payload.get("skill_id") or ""),
        str(payload.get("name") or ""),
    )


def _memory_add(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.memory_add(
        str(payload.get("content") or ""),
        kind=str(payload.get("kind") or ""),
        scope=str(payload.get("scope") or ""),
    )


def _memory_replace(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.memory_replace(
        str(payload.get("content") or ""),
        memory_id=str(payload.get("memory_id") or ""),
        old_content=str(payload.get("old_content") or ""),
        kind=str(payload.get("kind") or ""),
        scope=str(payload.get("scope") or ""),
    )


def _memory_remove(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.memory_remove(
        memory_id=str(payload.get("memory_id") or ""),
        content=str(payload.get("content") or ""),
        reason=str(payload.get("reason") or ""),
    )


def _future_task_schedule(
    broker: Any, payload: dict[str, Any], _approved: bool
) -> dict[str, Any]:
    return broker.future_task_schedule(
        title=str(payload.get("title") or ""),
        prompt=str(payload.get("prompt") or ""),
        delay_seconds=payload.get("delay_seconds"),
        scheduled_at_epoch=payload.get("scheduled_at_epoch"),
        cron=str(payload.get("cron") or ""),
        runnable_id=str(payload.get("runnable_id") or ""),
        runnable_name=str(payload.get("runnable_name") or ""),
    )


def _future_task_list(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.future_task_list(
        include_finished=bool(payload.get("include_finished", True)),
        limit=int(payload.get("limit") or 100),
    )


def _future_task_cancel(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.future_task_cancel(
        str(payload.get("future_task_id") or ""),
        reason=str(payload.get("reason") or ""),
    )


def _workspace_list(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.workspace_list(
        str(payload.get("path") or "."),
        pattern=str(payload.get("pattern") or ""),
        file_type=str(payload.get("file_type") or ""),
        include_metadata=_payload_bool(payload.get("include_metadata")),
    )


def _payload_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _workspace_read(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.workspace_read(str(payload.get("path") or ""))


def _workspace_write_patch(
    broker: Any, payload: dict[str, Any], approved: bool
) -> dict[str, Any]:
    return broker.workspace_write_patch(
        str(payload.get("path") or ""),
        str(payload.get("content") or ""),
        patch=str(payload.get("patch") or ""),
        expected_sha256=str(payload.get("expected_sha256") or payload.get("base_sha256") or ""),
        approved=approved,
    )


def _file_organize(broker: Any, payload: dict[str, Any], approved: bool) -> dict[str, Any]:
    return broker.file_organize(
        str(payload.get("path") or "."),
        operation=str(payload.get("operation") or "organize"),
        file_type=str(payload.get("file_type") or ""),
        pattern=str(payload.get("pattern") or ""),
        destination=str(payload.get("destination") or ""),
        conflict_strategy=str(payload.get("conflict_strategy") or "keep_both"),
        limit=payload.get("limit", 200),
        approved=approved,
    )


def _terminal_run(broker: Any, payload: dict[str, Any], approved: bool) -> dict[str, Any]:
    return broker.terminal_run(
        str(payload.get("command") or ""),
        approved=approved,
        timeout_seconds=int(payload.get("timeout_seconds") or 30),
        shell=bool(payload.get("shell", False)),
    )


def _artifact_write(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.artifact_write(
        str(payload.get("path") or ""),
        str(payload.get("content") or ""),
    )


def _data_analyze(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    raw_artifact_paths = payload.get("artifact_paths")
    raw_requested_outputs = payload.get("requested_outputs")
    raw_artifact_manifest = payload.get("artifact_manifest")
    return broker.data_analyze(
        str(payload.get("path") or ""),
        content=str(payload.get("content") or ""),
        display_path=str(payload.get("display_path") or ""),
        artifact_path=str(payload.get("artifact_path") or "analysis-report.md"),
        artifact_paths=list(raw_artifact_paths) if isinstance(raw_artifact_paths, list) else None,
        max_rows=int(payload.get("max_rows") or 1000),
        source_kind=str(payload.get("source_kind") or ""),
        requested_outputs=(
            list(raw_requested_outputs)
            if isinstance(raw_requested_outputs, list)
            else None
        ),
        artifact_manifest=(
            [dict(item) for item in raw_artifact_manifest if isinstance(item, dict)]
            if isinstance(raw_artifact_manifest, list)
            else None
        ),
    )


def _screen_capture(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.screen_capture(reason=str(payload.get("reason") or ""))


def _desktop_active_window(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_active_window()


def _desktop_permissions(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_permissions()


def _desktop_running_apps(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_running_apps()


def _desktop_list_apps(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_list_apps(
        query=str(payload.get("query") or ""),
        limit=payload.get("limit", 200),
    )


def _with_alias_action(result: dict[str, Any], action: str) -> dict[str, Any]:
    return {**result, "action": action}


def _desktop_open_app(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return _with_alias_action(_app_open(broker, payload, _approved), "desktop.open_app")


def _desktop_focus_app(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return _with_alias_action(_app_focus(broker, payload, _approved), "desktop.focus_app")


def _desktop_verify(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    app_name = str(payload.get("app_name") or "").strip()
    if app_name:
        result = broker.desktop_inspect_app(
            app_name,
            open_if_needed=False,
            focus=False,
            role_filter=str(payload.get("role_filter") or ""),
            limit=payload.get("limit", 80),
        )
        return {
            **result,
            "action": "desktop.verify",
            "summary": result.get("summary") or f"Verified desktop app: {app_name}",
        }
    result = broker.desktop_active_window()
    return {
        **result,
        "action": "desktop.verify",
        "summary": result.get("summary") or "Verified active desktop window",
    }


def _desktop_windows(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_windows(str(payload.get("app_name") or ""))


def _desktop_list_windows(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return _with_alias_action(_desktop_windows(broker, payload, _approved), "desktop.list_windows")


def _desktop_ui_elements(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_ui_elements(
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
        app_name=str(payload.get("app_name") or ""),
    )


def _desktop_read_ui(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return _with_alias_action(_desktop_ui_elements(broker, payload, _approved), "desktop.read_ui")


def _desktop_inspect_app(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_inspect_app(
        str(payload.get("app_name") or ""),
        open_if_needed=payload.get("open_if_needed", True),
        focus=payload.get("focus", True),
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
    )


def _desktop_click_ui_element(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_click_ui_element(
        str(payload.get("target") or ""),
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
        click_count=payload.get("click_count", 1),
    )


def _desktop_type_into_ui_element(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_type_into_ui_element(
        str(payload.get("target") or ""),
        str(payload.get("text") or ""),
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
    )


def _app_status(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_status(str(payload.get("app_name") or ""))


def _app_open(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_open(str(payload.get("app_name") or ""))


def _app_focus(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_focus(str(payload.get("app_name") or ""))


def _app_focus_window(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_focus_window(
        str(payload.get("app_name") or ""),
        str(payload.get("title_contains") or ""),
    )


def _app_open_and_safe_type_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_open_and_safe_type_text(
        str(payload.get("app_name") or ""),
        str(payload.get("text") or ""),
    )


def _app_focus_and_safe_type_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_focus_and_safe_type_text(
        str(payload.get("app_name") or ""),
        str(payload.get("text") or ""),
    )


def _app_open_and_safe_shortcut(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_open_and_safe_shortcut(
        str(payload.get("app_name") or ""),
        str(payload.get("action") or ""),
    )


def _app_focus_and_safe_shortcut(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_focus_and_safe_shortcut(
        str(payload.get("app_name") or ""),
        str(payload.get("action") or ""),
    )


def _app_open_and_safe_key(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_open_and_safe_key(
        str(payload.get("app_name") or ""),
        str(payload.get("action") or ""),
        repeat_count=payload.get("repeat_count", 1),
    )


def _app_focus_and_safe_key(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_focus_and_safe_key(
        str(payload.get("app_name") or ""),
        str(payload.get("action") or ""),
        repeat_count=payload.get("repeat_count", 1),
    )


def _app_open_and_hotkey(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    modifiers = payload.get("modifiers")
    return broker.app_open_and_hotkey(
        str(payload.get("app_name") or ""),
        str(payload.get("key") or ""),
        modifiers=modifiers if isinstance(modifiers, list) else [],
    )


def _app_focus_and_hotkey(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    modifiers = payload.get("modifiers")
    return broker.app_focus_and_hotkey(
        str(payload.get("app_name") or ""),
        str(payload.get("key") or ""),
        modifiers=modifiers if isinstance(modifiers, list) else [],
    )


def _app_open_and_safe_scroll(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_open_and_safe_scroll(
        str(payload.get("app_name") or ""),
        str(payload.get("direction") or ""),
        pages=payload.get("pages", 1),
    )


def _app_focus_and_safe_scroll(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_focus_and_safe_scroll(
        str(payload.get("app_name") or ""),
        str(payload.get("direction") or ""),
        pages=payload.get("pages", 1),
    )


def _app_open_and_safe_click(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_open_and_safe_click(
        str(payload.get("app_name") or ""),
        payload.get("x"),
        payload.get("y"),
    )


def _app_focus_and_safe_click(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_focus_and_safe_click(
        str(payload.get("app_name") or ""),
        payload.get("x"),
        payload.get("y"),
    )


def _app_open_and_click_ui_element(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_open_and_click_ui_element(
        str(payload.get("app_name") or ""),
        str(payload.get("target") or ""),
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
        click_count=payload.get("click_count", 1),
    )


def _app_focus_and_click_ui_element(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_focus_and_click_ui_element(
        str(payload.get("app_name") or ""),
        str(payload.get("target") or ""),
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
        click_count=payload.get("click_count", 1),
    )


def _app_open_and_type_into_ui_element(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_open_and_type_into_ui_element(
        str(payload.get("app_name") or ""),
        str(payload.get("target") or ""),
        str(payload.get("text") or ""),
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
    )


def _app_focus_and_type_into_ui_element(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.app_focus_and_type_into_ui_element(
        str(payload.get("app_name") or ""),
        str(payload.get("target") or ""),
        str(payload.get("text") or ""),
        role_filter=str(payload.get("role_filter") or ""),
        limit=payload.get("limit", 80),
    )


def _app_show(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_show(str(payload.get("app_name") or ""))


def _app_hide(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_hide(str(payload.get("app_name") or ""))


def _app_minimize(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_minimize(str(payload.get("app_name") or ""))


def _app_quit(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.app_quit(str(payload.get("app_name") or ""))


def _desktop_reveal_path(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_reveal_path(str(payload.get("path") or ""))


def _desktop_open_path(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_open_path(str(payload.get("path") or ""))


def _desktop_open_path_with_app(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_open_path_with_app(
        str(payload.get("path") or ""),
        str(payload.get("app_name") or ""),
    )


def _media_apple_music_play(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_apple_music_play(str(payload.get("query") or ""))


def _media_apple_music_status(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_apple_music_status()


def _media_apple_music_open_and_play(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_apple_music_open_and_play()


def _media_apple_music_control(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_apple_music_control(str(payload.get("action") or ""))


def _media_music_app_open_and_play(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_music_app_open_and_play(str(payload.get("app_name") or ""))


def _media_music_app_control(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_music_app_control(
        str(payload.get("app_name") or ""),
        str(payload.get("action") or ""),
    )


def _media_system_control(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_system_control(str(payload.get("action") or ""))


def _system_settings_open(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.system_settings_open(str(payload.get("target") or ""))


def _system_volume(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.system_volume(
        str(payload.get("action") or ""),
        level=payload.get("level"),
        step=payload.get("step"),
    )


def _system_brightness(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.system_brightness(
        str(payload.get("action") or ""),
        step=payload.get("step"),
    )


def _system_display_sleep(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.system_display_sleep()


def _system_screen_saver_start(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.system_screen_saver_start()


def _clipboard_write(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.clipboard_write(str(payload.get("text") or ""))


def _clipboard_read(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.clipboard_read(max_chars=payload.get("max_chars", 2000))


def _notes_create(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.notes_create(
        str(payload.get("body") or ""),
        title=str(payload.get("title") or ""),
        folder_name=str(payload.get("folder_name") or ""),
    )


def _reminders_create(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.reminders_create(
        str(payload.get("title") or ""),
        due_at=payload.get("due_at"),
        list_name=str(payload.get("list_name") or ""),
    )


def _calendar_create_event(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.calendar_create_event(
        str(payload.get("title") or ""),
        start_at=payload.get("start_at"),
        end_at=payload.get("end_at"),
        calendar_name=str(payload.get("calendar_name") or ""),
    )


def _desktop_safe_shortcut(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_safe_shortcut(str(payload.get("action") or ""))


def _desktop_close_window(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_close_window()


def _desktop_quit_app(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_quit_app()


def _desktop_minimize_window(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_minimize_window()


def _desktop_hide_app(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_hide_app()


def _desktop_show_all_apps(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_show_all_apps()


def _desktop_hotkey(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    modifiers = payload.get("modifiers")
    return broker.desktop_hotkey(
        str(payload.get("key") or ""),
        modifiers=modifiers if isinstance(modifiers, list) else [],
    )


def _desktop_shortcut(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return _with_alias_action(_desktop_hotkey(broker, payload, _approved), "desktop.shortcut")


def _desktop_submit_foreground(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_submit_foreground(str(payload.get("action") or "submit"))


def _desktop_search_submit(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_search_submit()


def _desktop_type_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_type_text(str(payload.get("text") or ""))


def _desktop_type(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return _with_alias_action(_desktop_type_text(broker, payload, _approved), "desktop.type")


def _desktop_safe_type_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_safe_type_text(str(payload.get("text") or ""))


def _desktop_safe_key(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_safe_key(
        str(payload.get("action") or ""),
        repeat_count=payload.get("repeat_count", 1),
    )


def _desktop_click(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_click(
        payload.get("x"),
        payload.get("y"),
        click_count=payload.get("click_count", 1),
    )


def _desktop_safe_click(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_safe_click(payload.get("x"), payload.get("y"))


def _desktop_safe_scroll(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_safe_scroll(
        str(payload.get("direction") or ""),
        pages=payload.get("pages", 1),
    )


def _browser_open_url(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.browser_open_url(str(payload.get("url") or ""))


def _browser_search(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    query = str(payload.get("query") or "").strip()
    return broker.browser_open_url(f"https://www.google.com/search?q={quote_plus(query)}")


def _browser_open(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return _browser_open_url(broker, payload, _approved)


def _browser_open_url_and_extract_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.browser_open_url_and_extract_text(
        str(payload.get("url") or ""),
        selector=str(payload.get("selector") or ""),
    )


def _browser_open_url_and_screenshot(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.browser_open_url_and_screenshot(
        str(payload.get("url") or ""),
        reason=str(payload.get("reason") or ""),
    )


def _browser_current_page(
    broker: Any,
    _payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.browser_current_page()


def _browser_click(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.browser_click(
        str(payload.get("selector") or ""),
        fallback_x=payload.get("fallback_x"),
        fallback_y=payload.get("fallback_y"),
        click_count=payload.get("click_count", 1),
    )


def _browser_type_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.browser_type_text(
        str(payload.get("selector") or ""),
        str(payload.get("text") or ""),
        fallback_x=payload.get("fallback_x"),
        fallback_y=payload.get("fallback_y"),
    )


def _browser_extract_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.browser_extract_text(str(payload.get("selector") or ""))


def _browser_extract(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return _browser_extract_text(broker, payload, _approved)


def _browser_screenshot(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.browser_screenshot(reason=str(payload.get("reason") or ""))


TOOL_DISPATCH_REGISTRY: dict[str, ToolDispatchHandler] = {
    "skill.read": _skill_read,
    "memory.add": _memory_add,
    "memory.replace": _memory_replace,
    "memory.remove": _memory_remove,
    "future_task.schedule": _future_task_schedule,
    "future_task.list": _future_task_list,
    "future_task.cancel": _future_task_cancel,
    "workspace.list": _workspace_list,
    "workspace.read": _workspace_read,
    "workspace.write_patch": _workspace_write_patch,
    "fs.find_files": _workspace_list,
    "fs.read_file": _workspace_read,
    "file.search": _workspace_list,
    "file.read": _workspace_read,
    "file.organize": _file_organize,
    "terminal.run": _terminal_run,
    "artifact.write": _artifact_write,
    "data.analyze": _data_analyze,
    "screen.capture": _screen_capture,
    "desktop.permissions": _desktop_permissions,
    "desktop.active_window": _desktop_active_window,
    "desktop.running_apps": _desktop_running_apps,
    "desktop.list_apps": _desktop_list_apps,
    "desktop.open_app": _desktop_open_app,
    "desktop.focus_app": _desktop_focus_app,
    "desktop.list_windows": _desktop_list_windows,
    "desktop.read_ui": _desktop_read_ui,
    "desktop.windows": _desktop_windows,
    "desktop.ui_elements": _desktop_ui_elements,
    "desktop.inspect_app": _desktop_inspect_app,
    "desktop.click_ui_element": _desktop_click_ui_element,
    "desktop.type_into_ui_element": _desktop_type_into_ui_element,
    "app.status": _app_status,
    "app.open": _app_open,
    "app.focus": _app_focus,
    "app.focus_window": _app_focus_window,
    "app.open_and_safe_type_text": _app_open_and_safe_type_text,
    "app.focus_and_safe_type_text": _app_focus_and_safe_type_text,
    "app.open_and_safe_shortcut": _app_open_and_safe_shortcut,
    "app.focus_and_safe_shortcut": _app_focus_and_safe_shortcut,
    "app.open_and_safe_key": _app_open_and_safe_key,
    "app.focus_and_safe_key": _app_focus_and_safe_key,
    "app.open_and_hotkey": _app_open_and_hotkey,
    "app.focus_and_hotkey": _app_focus_and_hotkey,
    "app.open_and_safe_scroll": _app_open_and_safe_scroll,
    "app.focus_and_safe_scroll": _app_focus_and_safe_scroll,
    "app.open_and_safe_click": _app_open_and_safe_click,
    "app.focus_and_safe_click": _app_focus_and_safe_click,
    "app.open_and_click_ui_element": _app_open_and_click_ui_element,
    "app.focus_and_click_ui_element": _app_focus_and_click_ui_element,
    "app.open_and_type_into_ui_element": _app_open_and_type_into_ui_element,
    "app.focus_and_type_into_ui_element": _app_focus_and_type_into_ui_element,
    "app.show": _app_show,
    "app.hide": _app_hide,
    "app.minimize": _app_minimize,
    "app.quit": _app_quit,
    "desktop.reveal_path": _desktop_reveal_path,
    "desktop.open_path": _desktop_open_path,
    "desktop.open_path_with_app": _desktop_open_path_with_app,
    "app.open_path_with_app": _desktop_open_path_with_app,
    "media.apple_music_play": _media_apple_music_play,
    "media.apple_music_status": _media_apple_music_status,
    "media.apple_music_open_and_play": _media_apple_music_open_and_play,
    "media.apple_music_control": _media_apple_music_control,
    "media.music_app_open_and_play": _media_music_app_open_and_play,
    "media.music_app_control": _media_music_app_control,
    "media.system_control": _media_system_control,
    "system.settings_open": _system_settings_open,
    "system.volume": _system_volume,
    "system.brightness": _system_brightness,
    "system.display_sleep": _system_display_sleep,
    "system.screen_saver_start": _system_screen_saver_start,
    "clipboard.write": _clipboard_write,
    "clipboard.read": _clipboard_read,
    "notes.create": _notes_create,
    "reminders.create": _reminders_create,
    "calendar.create_event": _calendar_create_event,
    "desktop.safe_shortcut": _desktop_safe_shortcut,
    "desktop.hide_app": _desktop_hide_app,
    "desktop.show_all_apps": _desktop_show_all_apps,
    "desktop.minimize_window": _desktop_minimize_window,
    "desktop.close_window": _desktop_close_window,
    "desktop.quit_app": _desktop_quit_app,
    "desktop.hotkey": _desktop_hotkey,
    "desktop.shortcut": _desktop_shortcut,
    "desktop.submit_foreground": _desktop_submit_foreground,
    "desktop.search_submit": _desktop_search_submit,
    "desktop.safe_key": _desktop_safe_key,
    "desktop.safe_type_text": _desktop_safe_type_text,
    "desktop.safe_click": _desktop_safe_click,
    "desktop.safe_scroll": _desktop_safe_scroll,
    "desktop.type_text": _desktop_type_text,
    "desktop.type": _desktop_type,
    "desktop.click": _desktop_click,
    "desktop.verify": _desktop_verify,
    "browser.search": _browser_search,
    "browser.open": _browser_open,
    "browser.open_url": _browser_open_url,
    "browser.open_url_and_extract_text": _browser_open_url_and_extract_text,
    "browser.open_url_and_screenshot": _browser_open_url_and_screenshot,
    "browser.current_page": _browser_current_page,
    "browser.click": _browser_click,
    "browser.type_text": _browser_type_text,
    "browser.extract": _browser_extract,
    "browser.extract_text": _browser_extract_text,
    "browser.screenshot": _browser_screenshot,
}


def dispatch_tool_call(
    broker: Any,
    name: str,
    payload: dict[str, Any],
    *,
    approved: bool = False,
) -> dict[str, Any]:
    handler = TOOL_DISPATCH_REGISTRY.get(name)
    if handler is None:
        raise AgentRuntimeError(f"未知工具：{name}")
    return handler(broker, payload, approved)


__all__ = ["TOOL_DISPATCH_REGISTRY", "dispatch_tool_call"]
