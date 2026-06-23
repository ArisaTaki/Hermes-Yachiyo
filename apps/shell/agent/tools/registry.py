"""ToolBroker dispatch registry.

This keeps tool-name routing separate from the concrete broker operations while
preserving the legacy ToolBroker.call surface.
"""

from __future__ import annotations

from typing import Any, Callable

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
    return broker.workspace_list(str(payload.get("path") or "."))


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


def _desktop_windows(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_windows(str(payload.get("app_name") or ""))


def _desktop_ui_elements(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.desktop_ui_elements(
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


def _media_apple_music_play(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.media_apple_music_play(str(payload.get("query") or ""))


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


def _clipboard_write(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.clipboard_write(str(payload.get("text") or ""))


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


def _desktop_hotkey(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    modifiers = payload.get("modifiers")
    return broker.desktop_hotkey(
        str(payload.get("key") or ""),
        modifiers=modifiers if isinstance(modifiers, list) else [],
    )


def _desktop_type_text(
    broker: Any,
    payload: dict[str, Any],
    _approved: bool,
) -> dict[str, Any]:
    return broker.desktop_type_text(str(payload.get("text") or ""))


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
    "terminal.run": _terminal_run,
    "artifact.write": _artifact_write,
    "screen.capture": _screen_capture,
    "desktop.permissions": _desktop_permissions,
    "desktop.active_window": _desktop_active_window,
    "desktop.running_apps": _desktop_running_apps,
    "desktop.windows": _desktop_windows,
    "desktop.ui_elements": _desktop_ui_elements,
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
    "app.open_and_safe_scroll": _app_open_and_safe_scroll,
    "app.focus_and_safe_scroll": _app_focus_and_safe_scroll,
    "app.open_and_safe_click": _app_open_and_safe_click,
    "app.focus_and_safe_click": _app_focus_and_safe_click,
    "app.open_and_click_ui_element": _app_open_and_click_ui_element,
    "app.focus_and_click_ui_element": _app_focus_and_click_ui_element,
    "app.show": _app_show,
    "app.hide": _app_hide,
    "app.minimize": _app_minimize,
    "app.quit": _app_quit,
    "desktop.reveal_path": _desktop_reveal_path,
    "desktop.open_path": _desktop_open_path,
    "media.apple_music_play": _media_apple_music_play,
    "media.apple_music_open_and_play": _media_apple_music_open_and_play,
    "media.apple_music_control": _media_apple_music_control,
    "system.volume": _system_volume,
    "clipboard.write": _clipboard_write,
    "desktop.safe_shortcut": _desktop_safe_shortcut,
    "desktop.hide_app": _desktop_hide_app,
    "desktop.minimize_window": _desktop_minimize_window,
    "desktop.close_window": _desktop_close_window,
    "desktop.hotkey": _desktop_hotkey,
    "desktop.safe_key": _desktop_safe_key,
    "desktop.safe_type_text": _desktop_safe_type_text,
    "desktop.safe_click": _desktop_safe_click,
    "desktop.safe_scroll": _desktop_safe_scroll,
    "desktop.type_text": _desktop_type_text,
    "desktop.click": _desktop_click,
    "browser.open_url": _browser_open_url,
    "browser.open_url_and_extract_text": _browser_open_url_and_extract_text,
    "browser.open_url_and_screenshot": _browser_open_url_and_screenshot,
    "browser.current_page": _browser_current_page,
    "browser.click": _browser_click,
    "browser.type_text": _browser_type_text,
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
