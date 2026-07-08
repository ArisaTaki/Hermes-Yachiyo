"""Loopback HTTP provider for isolated desktop-session control tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Iterable, Mapping
from http.server import ThreadingHTTPServer
from typing import Any

from apps.shell.agent.runtime.controlled_desktop_provider import (
    CONTROLLED_DESKTOP_PROVIDER_TOOLS,
    KEYBOARD_MOUSE_CONTROL_TOOLS,
    ControlledDesktopProvider,
    _sorted_tools,
    _string_list,
)
from apps.shell.agent.runtime.headless_desktop_provider import (
    DEFAULT_HOST,
    DEFAULT_PROVIDER_KIND,
    build_headless_desktop_provider_server,
)

ISOLATED_DESKTOP_PROVIDER_VERSION = "0.1.0"
DEFAULT_ISOLATED_PROVIDER_ID = "local-isolated-desktop"
DEFAULT_ISOLATED_PORT = 19093
DEFAULT_ISOLATED_SESSION_ID = "oha-yachiyo-isolated-session"
ISOLATED_BACKEND_KIND = "loopback_session_harness"


class IsolatedDesktopProvider(ControlledDesktopProvider):
    """Executes desktop-control tools in an isolated provider session contract.

    This harness intentionally does not mutate the user's real foreground session. It
    records isolated-session state so Runtime can route, approve, replay, and debug the
    provider boundary before a real virtual desktop backend is attached.
    """

    def __init__(
        self,
        *,
        provider_id: str = DEFAULT_ISOLATED_PROVIDER_ID,
        provider_kind: str = DEFAULT_PROVIDER_KIND,
        session_id: str = DEFAULT_ISOLATED_SESSION_ID,
        supported_tools: Iterable[str] | None = None,
        require_approval_for_input: bool = True,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            provider_kind=provider_kind,
            supported_tools=supported_tools or CONTROLLED_DESKTOP_PROVIDER_TOOLS,
            require_approval_for_input=require_approval_for_input,
        )
        self.session_id = str(session_id or DEFAULT_ISOLATED_SESSION_ID).strip()
        self._session_lock = threading.RLock()
        self._active_app = ""
        self._opened_apps: dict[str, dict[str, Any]] = {}
        self._events: list[dict[str, Any]] = []
        self._text_buffers: dict[str, str] = {}
        self._focused_targets: dict[str, str] = {}
        self._media_states: dict[str, str] = {}

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ready",
            "version": ISOLATED_DESKTOP_PROVIDER_VERSION,
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "supported_tools": list(self.supported_tools),
            "capabilities": [
                "desktop_discovery",
                "foreground_mutation",
                "foreground_input",
                "keyboard_mouse_capture",
                "sandbox_control",
                "isolated_desktop",
                "sandbox_desktop_session",
                "permission_diagnostics",
            ],
            "blocking_conditions": [],
            "execution_mode": "isolated_desktop",
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "isolated_session_id": self.session_id,
            **_isolated_backend_status(),
            "requires_real_sandbox_for": [],
            "approval_required_tools": _sorted_tools(KEYBOARD_MOUSE_CONTROL_TOOLS),
        }

    def manifest(self, *, base_url: str = "") -> dict[str, Any]:
        payload = dict(super().manifest(base_url=base_url))
        payload.update(
            {
                "version": ISOLATED_DESKTOP_PROVIDER_VERSION,
                "provider_id": self.provider_id,
                "provider_kind": self.provider_kind,
                "execution_mode": "isolated_desktop",
                "foreground_mutation_supported": True,
                "keyboard_mouse_capture_supported": True,
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "isolated_session_id": self.session_id,
                **_isolated_backend_status(),
                "requires_real_sandbox_for": [],
                "capabilities": self.status()["capabilities"],
                "supported_tools": list(self.supported_tools),
                "default_bind": {"host": DEFAULT_HOST, "port": DEFAULT_ISOLATED_PORT},
                "entrypoint": {
                    "script": "scripts/run_isolated_desktop_provider.py",
                    "module": "apps.shell.agent.runtime.isolated_desktop_provider",
                    "args": [
                        "--host",
                        DEFAULT_HOST,
                        "--port",
                        str(DEFAULT_ISOLATED_PORT),
                    ],
                },
                "safety": {
                    "loopback_default": True,
                    "remote_default_allowed": False,
                    "foreground_mutation_tools_supported": True,
                    "keyboard_mouse_capture_supported": True,
                    "desktop_session_kind": "isolated_desktop",
                    "desktop_session_isolated": True,
                    "foreground_takeover_required": False,
                    **_isolated_backend_status(),
                    "requires_runtime_approval": True,
                    "approval_required_tools": _sorted_tools(
                        KEYBOARD_MOUSE_CONTROL_TOOLS
                    ),
                },
            }
        )
        return payload

    def _dispatch(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._session_lock:
            return self._dispatch_isolated(tool_name, payload)

    def _dispatch_isolated(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if tool_name in {"desktop.permissions", "desktop.permission_preflight"}:
            return self._result(
                tool_name,
                "Isolated desktop provider permissions are ready.",
                permissions={"isolated_desktop": True, "keyboard_mouse_capture": True},
            )
        if tool_name in {"desktop.running_apps", "desktop.list_apps"}:
            return self._list_apps(tool_name, payload)
        if tool_name in {"desktop.active_window", "desktop.windows", "desktop.list_windows"}:
            return self._window_result(tool_name, payload)
        if tool_name == "desktop.inspect_app":
            return self._inspect_app(tool_name, payload)
        if tool_name in {"desktop.ui_elements", "desktop.read_ui"}:
            return self._read_ui(tool_name, payload)
        if tool_name == "desktop.verify":
            return self._verify(tool_name, payload)
        if tool_name == "app.status":
            app_name = str(payload.get("app_name") or self._active_app or "").strip()
            return self._result(
                tool_name,
                f"Checked isolated app status: {app_name or 'none'}.",
                app_name=app_name,
                running=bool(app_name and app_name in self._opened_apps),
            )
        if tool_name in {"app.open", "desktop.open_app"}:
            return self._open_app(tool_name, payload)
        if tool_name in {"app.focus", "desktop.focus_app"}:
            return self._focus_app(tool_name, payload)
        if tool_name == "app.focus_window":
            return self._focus_app(tool_name, payload)
        if tool_name == "media.music_app_open_and_play":
            return self._music_app_open_and_play(tool_name, payload)
        if tool_name == "media.music_app_control":
            return self._music_app_control(tool_name, payload)
        compound = self._compound_action(tool_name, payload)
        if compound is not None:
            return compound
        if tool_name in self.supported_tools:
            return self._record_input_action(tool_name, payload)
        return self._unsupported_tool(tool_name, payload)

    def _open_app(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or "Untitled App"
        app = {
            "name": app_name,
            "app_name": app_name,
            "running": True,
            "source": "isolated_desktop_provider",
        }
        self._opened_apps[app_name] = app
        self._active_app = app_name
        self._text_buffers.setdefault(app_name, "")
        self._focused_targets.setdefault(app_name, "Search")
        self._events.append({"tool": tool_name, "app_name": app_name})
        return self._result(
            tool_name,
            f"Opened {app_name} inside isolated desktop session.",
            app_name=app_name,
            running=True,
        )

    def _focus_app(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or self._active_app
        if app_name and app_name not in self._opened_apps:
            self._opened_apps[app_name] = {
                "name": app_name,
                "app_name": app_name,
                "running": True,
                "source": "isolated_desktop_provider",
            }
        self._active_app = app_name
        if app_name:
            self._text_buffers.setdefault(app_name, "")
            self._focused_targets.setdefault(app_name, "Search")
        self._events.append({"tool": tool_name, "app_name": app_name})
        return self._result(
            tool_name,
            f"Focused {app_name or 'isolated desktop'} inside isolated session.",
            app_name=app_name,
            focused=True,
        )

    def _music_app_open_and_play(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or "Music"
        self._open_app("app.open", {"app_name": app_name})
        self._media_states[app_name] = "playing"
        event = {
            "tool": tool_name,
            "app_name": app_name,
            "control": "play",
            "isolated_playback_state": "playing",
            "real_desktop_mutated": False,
        }
        self._events.append(event)
        return self._result(
            tool_name,
            f"Recorded isolated playback start for {app_name}.",
            app_name=app_name,
            open_ok=True,
            focus_ok=True,
            playback_ok=True,
            control="play",
            player_state="playing",
            isolated_playback_state="playing",
            playback_state_unverified=False,
            real_desktop_mutated=False,
            isolated_event=event,
            event_count=len(self._events),
        )

    def _music_app_control(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or self._active_app or "Music"
        if app_name not in self._opened_apps:
            self._open_app("app.open", {"app_name": app_name})
        control = _isolated_music_control_action(payload.get("action"))
        current = self._media_states.get(app_name, "stopped")
        next_state = _isolated_music_next_state(current, control)
        self._media_states[app_name] = next_state
        event = {
            "tool": tool_name,
            "app_name": app_name,
            "control": control,
            "isolated_playback_state": next_state,
            "real_desktop_mutated": False,
        }
        self._events.append(event)
        return self._result(
            tool_name,
            f"Recorded isolated {control} media control for {app_name}.",
            app_name=app_name,
            control=control,
            player_state=next_state,
            isolated_playback_state=next_state,
            playback_state_unverified=False,
            real_desktop_mutated=False,
            isolated_event=event,
            event_count=len(self._events),
        )

    def _window_result(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or self._active_app
        windows = []
        if app_name:
            windows.append(
                {
                    "app_name": app_name,
                    "title": f"{app_name} - isolated",
                    "focused": app_name == self._active_app,
                }
            )
        return self._result(
            tool_name,
            f"Listed isolated windows for {app_name or 'active session'}.",
            app_name=app_name,
            windows=windows,
            active_window=windows[0] if windows else {},
        )

    def _read_ui(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or self._active_app
        if app_name and app_name not in self._opened_apps:
            self._opened_apps[app_name] = {
                "name": app_name,
                "app_name": app_name,
                "running": True,
                "source": "isolated_desktop_provider",
            }
            self._text_buffers.setdefault(app_name, "")
            self._focused_targets.setdefault(app_name, "Search")
        elements = self._ui_elements_for_app(app_name)
        return self._result(
            tool_name,
            f"Read isolated desktop UI for {app_name or 'active session'}.",
            elements=elements,
            active_app=app_name or self._active_app,
            focused_target=self._focused_targets.get(app_name or self._active_app, ""),
            text_buffer=self._text_buffers.get(app_name or self._active_app, ""),
            event_count=len(self._events),
        )

    def _inspect_app(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or "Untitled App"
        open_if_needed = _isolated_bool(payload.get("open_if_needed"), default=True)
        focus = _isolated_bool(payload.get("focus"), default=True)
        role_filter = str(payload.get("role_filter") or "").strip()
        limit = _isolated_limit(payload.get("limit"), default=80)
        before_running = app_name in self._opened_apps
        discovery = self._list_apps("desktop.list_apps", {"query": app_name, "limit": 10})
        open_result: dict[str, Any] | None = None
        if open_if_needed and not before_running:
            open_result = self._open_app("app.open", {"app_name": app_name})
        running = app_name in self._opened_apps
        focus_result: dict[str, Any] | None = None
        if focus and running:
            focus_result = self._focus_app("app.focus", {"app_name": app_name})
        focused = self._active_app == app_name
        elements = self._filtered_ui_elements(app_name, role_filter=role_filter, limit=limit)
        windows = [
            {
                "app_name": app_name,
                "title": f"{app_name} - isolated",
                "focused": focused,
            }
        ] if running else []
        active_window = windows[0] if focused and windows else {}
        control_like_count = sum(
            1
            for element in elements
            if str(element.get("role") or "").strip() in {"button", "text_field"}
        )
        ready_for_foreground_action = bool(focused and control_like_count > 0)
        checks = {
            "discovered_app": bool(app_name),
            "open_ok": open_result is None or open_result.get("ok") is True,
            "status_running": running,
            "focus_verified": focused if focus else True,
            "windows_query_ok": True,
            "ui_query_ok": True,
            "named_ui_elements_nonempty": bool(elements),
            "control_like_ui_visible": control_like_count > 0,
            "ready_for_foreground_action": ready_for_foreground_action,
        }
        ui_result = self._result(
            "desktop.ui_elements",
            f"Read isolated desktop UI for {app_name}.",
            elements=elements,
            active_app=app_name,
            focused_target=self._focused_targets.get(app_name, ""),
            text_buffer=self._text_buffers.get(app_name, ""),
            count=len(elements),
            control_like_count=control_like_count,
            inspection_level="control" if control_like_count else "empty",
            visibility_limited=False,
            visibility_status="visible" if elements else "empty",
        )
        windows_result = self._result(
            "desktop.windows",
            f"Listed isolated windows for {app_name}.",
            app_name=app_name,
            windows=windows,
            active_window=active_window,
            count=len(windows),
            window_visibility_status="visible" if windows else "not_running",
        )
        active_window_result = (
            self._result(
                "desktop.active_window",
                f"Active isolated window is {app_name}.",
                app_name=app_name,
                frontmost_app=app_name,
                title=active_window.get("title", ""),
                active_window=active_window,
            )
            if active_window
            else None
        )
        data = {
            "app_name": app_name,
            "requested_app_name": app_name,
            "discovered_app_name": app_name,
            "app_found": bool(app_name),
            "open_if_needed": open_if_needed,
            "focus_requested": focus,
            "running": running,
            "focus_verified": focused if focus else True,
            "window_count": len(windows),
            "ui_element_count": len(elements),
            "inspection_level": "control" if control_like_count else "empty",
            "visibility_limited": False,
            "visibility_status": "visible" if elements else "empty",
            "control_like_count": control_like_count,
            "ready_for_foreground_action": ready_for_foreground_action,
            "recommended_tools": _isolated_inspect_recommended_tools(
                running=running,
                ready_for_foreground_action=ready_for_foreground_action,
            ),
            "recovery_actions": [],
            "checks": checks,
            "discovery": discovery,
            "before_status": self._result(
                "app.status",
                f"Checked isolated app status: {app_name}.",
                app_name=app_name,
                running=before_running,
            ),
            "open_result": open_result,
            "after_status": self._result(
                "app.status",
                f"Checked isolated app status: {app_name}.",
                app_name=app_name,
                running=running,
            ),
            "focus_result": focus_result,
            "active_window": active_window_result,
            "windows": windows_result,
            "ui_elements": ui_result,
        }
        return {
            "ok": bool(app_name),
            "tool": tool_name,
            "action": tool_name,
            "summary": (
                f"Inspected {app_name} inside isolated desktop session."
                if app_name
                else "No isolated app name was provided."
            ),
            "data": {
                **data,
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "isolated_session_id": self.session_id,
            },
            "permission_error": False,
            "fallback_used": False,
            "recommended_tools": data["recommended_tools"],
            "recovery_actions": data["recovery_actions"],
        }

    def _verify(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or self._active_app
        expected_text = str(payload.get("expected_text") or "").strip()
        expected_target = str(payload.get("target") or "").strip()
        buffer_app = app_name or self._active_app
        text_buffer = self._text_buffers.get(buffer_app, "")
        active_matches = not app_name or app_name == self._active_app
        text_matches = not expected_text or expected_text in text_buffer
        target_matches = (
            not expected_target
            or expected_target == self._focused_targets.get(buffer_app, "")
        )
        verification_passed = active_matches and text_matches and target_matches
        return self._result(
            tool_name,
            "Verified isolated desktop session.",
            active_app=self._active_app,
            expected_app_name=app_name,
            expected_text=expected_text,
            expected_target=expected_target,
            text_buffer=text_buffer,
            active_app_matches=active_matches,
            expected_text_found=text_matches,
            expected_target_focused=target_matches,
            verification_passed=verification_passed,
            event_count=len(self._events),
            last_event=self._events[-1] if self._events else {},
        )

    def _list_apps(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        query = str(payload.get("query") or "").strip()
        running_only = tool_name == "desktop.running_apps"
        records = list(self._opened_apps.values())
        if not running_only:
            for record in self._discovered_app_records(query):
                app_name = str(record.get("app_name") or record.get("name") or "").strip()
                if app_name and app_name not in {
                    str(item.get("app_name") or item.get("name") or "").strip()
                    for item in records
                }:
                    records.append(record)
        matches = [
            record
            for record in records
            if not query or _isolated_app_record_matches(record, query)
        ]
        return self._result(
            tool_name,
            "Listed isolated desktop apps.",
            apps=records,
            matches=matches,
            query=query,
            running_only=running_only,
        )

    def _discovered_app_records(self, query: str) -> list[dict[str, Any]]:
        clean_query = str(query or "").strip()
        if not clean_query:
            return []
        running = clean_query in self._opened_apps
        return [
            {
                "name": clean_query,
                "app_name": clean_query,
                "display_name": clean_query,
                "running": running,
                "source": "isolated_desktop_provider_discovery",
                "selection_source": "desktop.list_apps",
                "query": clean_query,
                "isolated_discovery": True,
            }
        ]

    def _resolve_app_name(self, payload: Mapping[str, Any]) -> str:
        raw_name = str(payload.get("app_name") or payload.get("name") or "").strip()
        query = str(payload.get("query") or "").strip()
        selection_source = str(payload.get("selection_source") or "").strip()
        if raw_name and not _isolated_selected_placeholder(raw_name):
            return raw_name
        if selection_source in {"desktop.list_apps", "desktop.running_apps"} and query:
            return query
        if query:
            return query
        return ""

    def _compound_action(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        is_compound = tool_name.startswith("app.open_and_") or tool_name.startswith(
            "app.focus_and_"
        )
        if not is_compound:
            return None
        app_name = self._resolve_app_name(payload) or self._active_app
        if tool_name.startswith("app.open_and_"):
            self._open_app("app.open", {"app_name": app_name})
        else:
            self._focus_app("app.focus", {"app_name": app_name})
        action_tool = _compound_action_tool(tool_name)
        action_payload = dict(payload)
        action_payload["app_name"] = app_name or self._active_app
        action_result = self._record_input_action(action_tool, action_payload)
        action_result["action"] = tool_name
        action_result["summary"] = (
            f"Executed {tool_name} inside isolated desktop session."
        )
        action_result["data"]["compound_action_tool"] = action_tool
        return action_result

    def _ui_elements_for_app(self, app_name: str) -> list[dict[str, Any]]:
        if not app_name:
            return []
        text_value = self._text_buffers.get(app_name, "")
        focused_target = self._focused_targets.get(app_name, "")
        return [
            {
                "id": f"{app_name}:search",
                "app_name": app_name,
                "role": "text_field",
                "title": "Search",
                "label": "Search",
                "value": text_value,
                "focused": focused_target == "Search",
            },
            {
                "id": f"{app_name}:primary-action",
                "app_name": app_name,
                "role": "button",
                "title": "Open",
                "label": "Open",
                "focused": focused_target == "Open",
            },
            {
                "id": f"{app_name}:content",
                "app_name": app_name,
                "role": "group",
                "title": f"{app_name} Content",
                "label": f"{app_name} Content",
                "value": text_value,
                "focused": focused_target == f"{app_name} Content",
            },
            {
                "id": f"{app_name}:playback",
                "app_name": app_name,
                "role": "status",
                "title": "Playback",
                "label": "Playback",
                "value": self._media_states.get(app_name, "stopped"),
                "focused": False,
            },
        ]

    def _filtered_ui_elements(
        self,
        app_name: str,
        *,
        role_filter: str = "",
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        elements = self._ui_elements_for_app(app_name)
        clean_filter = str(role_filter or "").strip().casefold()
        if clean_filter:
            elements = [
                element
                for element in elements
                if clean_filter
                in str(
                    element.get("role")
                    or element.get("title")
                    or element.get("label")
                    or ""
                ).casefold()
            ]
        return elements[: max(1, int(limit or 80))]

    def _record_input_action(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        app_name = self._resolve_app_name(payload) or self._active_app
        target = str(payload.get("target") or payload.get("role_filter") or "").strip()
        if target:
            self._focused_targets[app_name or self._active_app] = target
        if tool_name in {
            "desktop.safe_type_text",
            "desktop.type_text",
            "desktop.type",
            "desktop.type_into_ui_element",
        }:
            text = str(payload.get("text") or "")
            buffer_app = app_name or self._active_app or "Isolated Desktop"
            self._text_buffers[buffer_app] = (
                self._text_buffers.get(buffer_app, "") + text
            )
            if not self._active_app:
                self._active_app = buffer_app
        if tool_name in {
            "desktop.click_ui_element",
            "desktop.safe_click",
            "desktop.click",
        }:
            buffer_app = app_name or self._active_app
            if target and buffer_app:
                self._focused_targets[buffer_app] = target
        event = {
            "tool": tool_name,
            "input": dict(payload),
            "app_name": app_name,
            "target": target,
            "text_buffer": self._text_buffers.get(app_name or self._active_app, ""),
        }
        self._events.append(event)
        return self._result(
            tool_name,
            f"Executed {tool_name} inside isolated desktop session.",
            isolated_event=event,
            event_count=len(self._events),
        )

    def _result(self, action: str, summary: str, **data: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "action": action,
            "summary": summary,
            "data": {
                **data,
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "isolated_session_id": self.session_id,
            },
        }

    def _with_provider_context(
        self,
        result: dict[str, Any],
        *,
        tool_name: str,
        approved: bool,
        route: Mapping[str, Any] | None,
        tool_request: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload = super()._with_provider_context(
            result,
            tool_name=tool_name,
            approved=approved,
            route=route,
            tool_request=tool_request,
        )
        payload["isolated_desktop_provider"] = {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "version": ISOLATED_DESKTOP_PROVIDER_VERSION,
            "execution_mode": "isolated_desktop",
            "approved": bool(approved),
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "isolated_session_id": self.session_id,
            **_isolated_backend_status(),
        }
        payload["controlled_desktop_provider"].update(
            {
                "version": ISOLATED_DESKTOP_PROVIDER_VERSION,
                "execution_mode": "isolated_desktop",
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                **_isolated_backend_status(),
            }
        )
        return payload


def _compound_action_tool(tool_name: str) -> str:
    suffix = tool_name.removeprefix("app.open_and_").removeprefix("app.focus_and_")
    return {
        "safe_type_text": "desktop.safe_type_text",
        "safe_shortcut": "desktop.safe_shortcut",
        "safe_key": "desktop.safe_key",
        "hotkey": "desktop.hotkey",
        "safe_scroll": "desktop.safe_scroll",
        "safe_click": "desktop.safe_click",
        "click_ui_element": "desktop.click_ui_element",
        "type_into_ui_element": "desktop.type_into_ui_element",
    }.get(suffix, f"desktop.{suffix}")


def _isolated_music_control_action(value: Any) -> str:
    clean = str(value or "").strip().lower()
    return clean if clean in {"toggle", "play", "pause", "next", "previous"} else "play"


def _isolated_music_next_state(current: str, control: str) -> str:
    clean_current = str(current or "").strip().lower()
    clean_control = str(control or "").strip().lower()
    if clean_control == "play":
        return "playing"
    if clean_control == "pause":
        return "paused"
    if clean_control == "toggle":
        return "paused" if clean_current == "playing" else "playing"
    if clean_control in {"next", "previous"}:
        return "playing" if clean_current == "playing" else clean_current or "stopped"
    return clean_current or "stopped"


def _isolated_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    clean = str(value).strip().lower()
    if clean in {"1", "true", "yes", "on"}:
        return True
    if clean in {"0", "false", "no", "off"}:
        return False
    return default


def _isolated_limit(value: Any, *, default: int) -> int:
    try:
        return max(1, min(200, int(value or default)))
    except (TypeError, ValueError):
        return default


def _isolated_inspect_recommended_tools(
    *,
    running: bool,
    ready_for_foreground_action: bool,
) -> list[str]:
    tools = ["desktop.read_ui", "desktop.ui_elements", "desktop.verify"]
    if not running:
        tools.insert(0, "app.open")
    if ready_for_foreground_action:
        tools.extend(["app.focus_and_click_ui_element", "app.focus_and_type_into_ui_element"])
    return _sorted_tools(tools)


def _isolated_selected_placeholder(value: str) -> bool:
    clean = str(value or "").strip().lower()
    return clean.startswith("<selected ") and "desktop." in clean


def _isolated_app_record_matches(record: Mapping[str, Any], query: str) -> bool:
    clean_query = str(query or "").strip().lower()
    if not clean_query:
        return True
    for key in ("app_name", "name", "display_name", "query"):
        value = str(record.get(key) or "").strip().lower()
        if value and (clean_query in value or value in clean_query):
            return True
    return False


def _isolated_backend_status() -> dict[str, Any]:
    return {
        "desktop_backend_kind": ISOLATED_BACKEND_KIND,
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
    }


def build_isolated_desktop_provider_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_ISOLATED_PORT,
    token: str = "",
    provider: IsolatedDesktopProvider | None = None,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    return build_headless_desktop_provider_server(
        host=host,
        port=port,
        token=token,
        provider=provider or IsolatedDesktopProvider(),
        quiet=quiet,
    )


def serve_isolated_desktop_provider(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_ISOLATED_PORT,
    token: str = "",
    provider_id: str = DEFAULT_ISOLATED_PROVIDER_ID,
    provider_kind: str = DEFAULT_PROVIDER_KIND,
    session_id: str = DEFAULT_ISOLATED_SESSION_ID,
    supported_tools: Iterable[str] | None = None,
    require_approval_for_input: bool = True,
    quiet: bool = False,
) -> None:
    provider = IsolatedDesktopProvider(
        provider_id=provider_id,
        provider_kind=provider_kind,
        session_id=session_id,
        supported_tools=supported_tools,
        require_approval_for_input=require_approval_for_input,
    )
    server = build_isolated_desktop_provider_server(
        host=host,
        port=port,
        token=token,
        provider=provider,
        quiet=quiet,
    )
    actual_host, actual_port = server.server_address
    print(
        json.dumps(
            {
                "ok": True,
                "provider_id": provider.provider_id,
                "provider_kind": provider.provider_kind,
                "url": f"http://{actual_host}:{actual_port}",
                "status_url": f"http://{actual_host}:{actual_port}/status",
                "execute_url": f"http://{actual_host}:{actual_port}/tools/execute",
                "supported_tools": provider.supported_tools,
                "keyboard_mouse_capture_supported": True,
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                **_isolated_backend_status(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    provider = IsolatedDesktopProvider(
        provider_id=args.provider_id,
        provider_kind=args.provider_kind,
        session_id=args.session_id,
        supported_tools=args.tool,
        require_approval_for_input=not args.allow_unapproved_input,
    )
    if args.manifest:
        print(json.dumps(provider.manifest(), ensure_ascii=False, sort_keys=True))
        return 0
    serve_isolated_desktop_provider(
        host=args.host,
        port=args.port,
        token=args.token or os.getenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN", ""),
        provider_id=args.provider_id,
        provider_kind=args.provider_kind,
        session_id=args.session_id,
        supported_tools=args.tool,
        require_approval_for_input=not args.allow_unapproved_input,
        quiet=args.quiet,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_ISOLATED_PORT)
    parser.add_argument("--token", default="")
    parser.add_argument("--provider-id", default=DEFAULT_ISOLATED_PROVIDER_ID)
    parser.add_argument("--provider-kind", default=DEFAULT_PROVIDER_KIND)
    parser.add_argument("--session-id", default=DEFAULT_ISOLATED_SESSION_ID)
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--allow-unapproved-input", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
