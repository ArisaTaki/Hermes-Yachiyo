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
            return self._result(
                tool_name,
                "Listed isolated desktop apps.",
                apps=list(self._opened_apps.values()),
                matches=list(self._opened_apps.values()),
            )
        if tool_name in {"desktop.active_window", "desktop.windows", "desktop.list_windows"}:
            return self._window_result(tool_name, payload)
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
        compound = self._compound_action(tool_name, payload)
        if compound is not None:
            return compound
        if tool_name in self.supported_tools:
            return self._record_input_action(tool_name, payload)
        return self._unsupported_tool(tool_name, payload)

    def _open_app(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = str(payload.get("app_name") or "").strip() or "Untitled App"
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
        app_name = str(payload.get("app_name") or self._active_app or "").strip()
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

    def _window_result(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = str(payload.get("app_name") or self._active_app or "").strip()
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
        app_name = str(payload.get("app_name") or self._active_app or "").strip()
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

    def _verify(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = str(payload.get("app_name") or self._active_app or "").strip()
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
        app_name = str(payload.get("app_name") or self._active_app or "").strip()
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
        ]

    def _record_input_action(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        app_name = str(payload.get("app_name") or self._active_app or "").strip()
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
        }
        payload["controlled_desktop_provider"].update(
            {
                "version": ISOLATED_DESKTOP_PROVIDER_VERSION,
                "execution_mode": "isolated_desktop",
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
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
