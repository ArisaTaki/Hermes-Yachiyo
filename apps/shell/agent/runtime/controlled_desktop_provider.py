"""Loopback HTTP provider for supervised desktop control tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from http.server import ThreadingHTTPServer
from typing import Any

from apps.shell.agent.runtime.headless_desktop_provider import (
    DEFAULT_HOST,
    DEFAULT_PROVIDER_KIND,
    HeadlessDesktopProvider,
    build_headless_desktop_provider_server,
)
from apps.shell.agent.tools import desktop
from packages.security import redact_api_error_text

CONTROLLED_DESKTOP_PROVIDER_VERSION = "0.1.0"
DEFAULT_CONTROLLED_PROVIDER_ID = "local-controlled-desktop"
DEFAULT_CONTROLLED_PORT = 19092

CONTROLLED_DESKTOP_PROVIDER_TOOLS = (
    "desktop.permissions",
    "desktop.permission_preflight",
    "desktop.active_window",
    "desktop.running_apps",
    "desktop.list_apps",
    "desktop.windows",
    "desktop.list_windows",
    "desktop.ui_elements",
    "desktop.read_ui",
    "desktop.verify",
    "app.status",
    "app.open",
    "desktop.open_app",
    "app.focus",
    "desktop.focus_app",
    "app.focus_window",
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
    "desktop.safe_shortcut",
    "desktop.safe_key",
    "desktop.safe_type_text",
    "desktop.safe_click",
    "desktop.safe_scroll",
    "desktop.search_submit",
    "desktop.click_ui_element",
    "desktop.type_into_ui_element",
    "desktop.shortcut",
    "desktop.hotkey",
    "desktop.submit_foreground",
    "desktop.type",
    "desktop.type_text",
    "desktop.click",
    "media.music_app_open_and_play",
    "media.music_app_control",
)

KEYBOARD_MOUSE_CONTROL_TOOLS = frozenset(
    tool
    for tool in CONTROLLED_DESKTOP_PROVIDER_TOOLS
    if tool.startswith("app.open_and_safe_")
    or tool.startswith("app.focus_and_safe_")
    or tool in {"app.open_and_hotkey", "app.focus_and_hotkey"}
    or tool.startswith("app.open_and_click_")
    or tool.startswith("app.focus_and_click_")
    or tool.startswith("app.open_and_type_")
    or tool.startswith("app.focus_and_type_")
    or tool.startswith("desktop.safe_")
    or tool
    in {
        "desktop.search_submit",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.shortcut",
        "desktop.hotkey",
        "desktop.submit_foreground",
        "desktop.type",
        "desktop.type_text",
        "desktop.click",
    }
)


class ControlledDesktopProvider(HeadlessDesktopProvider):
    """Executes supervised foreground-control tools behind the provider contract."""

    def __init__(
        self,
        *,
        provider_id: str = DEFAULT_CONTROLLED_PROVIDER_ID,
        provider_kind: str = DEFAULT_PROVIDER_KIND,
        supported_tools: Iterable[str] | None = None,
        require_approval_for_input: bool = True,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            provider_kind=provider_kind,
            supported_tools=supported_tools or CONTROLLED_DESKTOP_PROVIDER_TOOLS,
        )
        self.require_approval_for_input = bool(require_approval_for_input)
        self._foreground_lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ready",
            "version": CONTROLLED_DESKTOP_PROVIDER_VERSION,
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "supported_tools": list(self.supported_tools),
            "capabilities": [
                "desktop_discovery",
                "foreground_mutation",
                "foreground_input",
                "keyboard_mouse_capture",
                "sandbox_control",
                "permission_diagnostics",
            ],
            "blocking_conditions": [],
            "execution_mode": "controlled_desktop",
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
            "desktop_session_kind": "user_foreground",
            "desktop_session_isolated": False,
            "foreground_takeover_required": True,
            "requires_real_sandbox_for": [],
            "approval_required_tools": _sorted_tools(KEYBOARD_MOUSE_CONTROL_TOOLS),
        }

    def manifest(self, *, base_url: str = "") -> dict[str, Any]:
        payload = dict(super().manifest(base_url=base_url))
        payload.update(
            {
                "version": CONTROLLED_DESKTOP_PROVIDER_VERSION,
                "provider_id": self.provider_id,
                "provider_kind": self.provider_kind,
                "execution_mode": "controlled_desktop",
                "foreground_mutation_supported": True,
                "keyboard_mouse_capture_supported": True,
                "desktop_session_kind": "user_foreground",
                "desktop_session_isolated": False,
                "foreground_takeover_required": True,
                "requires_real_sandbox_for": [],
                "capabilities": self.status()["capabilities"],
                "supported_tools": list(self.supported_tools),
                "default_bind": {"host": DEFAULT_HOST, "port": DEFAULT_CONTROLLED_PORT},
                "environment": {
                    "url": "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
                    "token": "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN",
                    "provider_id": "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
                    "provider_kind": "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
                    "tools": "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
                    "keyboard_mouse_capture": (
                        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED"
                    ),
                    "foreground_mutation": (
                        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_MUTATION_SUPPORTED"
                    ),
                    "session_kind": "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
                    "session_isolated": (
                        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED"
                    ),
                    "foreground_takeover": (
                        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED"
                    ),
                },
                "entrypoint": {
                    "script": "scripts/run_controlled_desktop_provider.py",
                    "module": "apps.shell.agent.runtime.controlled_desktop_provider",
                    "args": [
                        "--host",
                        DEFAULT_HOST,
                        "--port",
                        str(DEFAULT_CONTROLLED_PORT),
                    ],
                },
                "safety": {
                    "loopback_default": True,
                    "remote_default_allowed": False,
                    "foreground_mutation_tools_supported": True,
                    "keyboard_mouse_capture_supported": True,
                    "desktop_session_kind": "user_foreground",
                    "desktop_session_isolated": False,
                    "foreground_takeover_required": True,
                    "requires_runtime_approval": True,
                    "approval_required_tools": _sorted_tools(
                        KEYBOARD_MOUSE_CONTROL_TOOLS
                    ),
                },
            }
        )
        return payload

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        approved: bool = False,
        route: Mapping[str, Any] | None = None,
        tool_request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_tool = str(tool_name or "").strip()
        clean_payload = dict(payload) if isinstance(payload, Mapping) else {}
        if (
            self.require_approval_for_input
            and clean_tool in KEYBOARD_MOUSE_CONTROL_TOOLS
            and not approved
        ):
            return self._approval_required_tool(clean_tool, clean_payload)
        return super().execute(
            clean_tool,
            clean_payload,
            approved=approved,
            route=route,
            tool_request=tool_request,
        )

    def _dispatch(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if tool_name in {
            "desktop.permissions",
            "desktop.permission_preflight",
            "desktop.active_window",
            "desktop.running_apps",
            "desktop.list_apps",
            "desktop.windows",
            "desktop.list_windows",
            "desktop.ui_elements",
            "desktop.read_ui",
            "desktop.verify",
            "app.status",
        }:
            return super()._dispatch(tool_name, payload)
        with self._foreground_lock:
            return self._dispatch_control_tool(tool_name, payload)

    def _dispatch_control_tool(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        dispatch: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "app.open": lambda value: desktop.app_open(str(value.get("app_name") or "")),
            "desktop.open_app": lambda value: _alias_action(
                desktop.app_open(str(value.get("app_name") or "")),
                "desktop.open_app",
            ),
            "app.focus": lambda value: desktop.app_focus(str(value.get("app_name") or "")),
            "desktop.focus_app": lambda value: _alias_action(
                desktop.app_focus(str(value.get("app_name") or "")),
                "desktop.focus_app",
            ),
            "app.focus_window": lambda value: desktop.app_focus_window(
                str(value.get("app_name") or ""),
                str(value.get("title_contains") or ""),
            ),
            "desktop.safe_type_text": lambda value: desktop.desktop_safe_type_text(
                str(value.get("text") or "")
            ),
            "desktop.type_text": lambda value: desktop.desktop_type_text(
                str(value.get("text") or "")
            ),
            "desktop.type": lambda value: _alias_action(
                desktop.desktop_type_text(str(value.get("text") or "")),
                "desktop.type",
            ),
            "desktop.safe_click": lambda value: desktop.desktop_safe_click(
                value.get("x"),
                value.get("y"),
            ),
            "desktop.click": lambda value: desktop.desktop_click(
                value.get("x"),
                value.get("y"),
                click_count=value.get("click_count", 1),
            ),
            "desktop.safe_scroll": lambda value: desktop.desktop_safe_scroll(
                str(value.get("direction") or ""),
                pages=value.get("pages", 1),
            ),
            "desktop.safe_shortcut": lambda value: desktop.desktop_safe_shortcut(
                str(value.get("action") or "")
            ),
            "desktop.safe_key": lambda value: desktop.desktop_safe_key(
                str(value.get("action") or ""),
                repeat_count=value.get("repeat_count", 1),
            ),
            "desktop.shortcut": lambda value: desktop.desktop_hotkey(
                str(value.get("key") or ""),
                _string_list(value.get("modifiers")),
            ),
            "desktop.hotkey": lambda value: desktop.desktop_hotkey(
                str(value.get("key") or ""),
                _string_list(value.get("modifiers")),
            ),
            "desktop.submit_foreground": lambda value: desktop.desktop_submit_foreground(
                str(value.get("action") or "submit")
            ),
            "desktop.search_submit": lambda _value: desktop.desktop_search_submit(),
            "desktop.click_ui_element": lambda value: desktop.click_ui_element(
                str(value.get("target") or ""),
                role_filter=str(value.get("role_filter") or ""),
                limit=value.get("limit", 80),
                click_count=value.get("click_count", 1),
                expected_app_name=str(value.get("expected_app_name") or ""),
            ),
            "desktop.type_into_ui_element": lambda value: desktop.type_into_ui_element(
                str(value.get("target") or ""),
                str(value.get("text") or ""),
                role_filter=str(value.get("role_filter") or ""),
                limit=value.get("limit", 80),
                expected_app_name=str(value.get("expected_app_name") or ""),
            ),
            "media.music_app_open_and_play": lambda value: desktop.music_app_open_and_play(
                str(value.get("app_name") or "")
            ),
            "media.music_app_control": lambda value: desktop.music_app_control(
                str(value.get("app_name") or ""),
                str(value.get("action") or ""),
            ),
        }
        app_dispatch = self._app_control_dispatch(tool_name, payload)
        if app_dispatch is not None:
            return app_dispatch
        if tool_name not in dispatch:
            return self._unsupported_tool(tool_name, payload)
        return dispatch[tool_name](payload)

    def _app_control_dispatch(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        app_name = str(payload.get("app_name") or "").strip()
        if tool_name == "app.open_and_safe_type_text":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="safe_type_text",
                action=lambda: desktop.desktop_safe_type_text(
                    str(payload.get("text") or "")
                ),
            )
        if tool_name == "app.focus_and_safe_type_text":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="safe_type_text",
                action=lambda: desktop.desktop_safe_type_text(
                    str(payload.get("text") or "")
                ),
            )
        if tool_name == "app.open_and_safe_shortcut":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="safe_shortcut",
                action=lambda: desktop.desktop_safe_shortcut(
                    str(payload.get("action") or "")
                ),
            )
        if tool_name == "app.focus_and_safe_shortcut":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="safe_shortcut",
                action=lambda: desktop.desktop_safe_shortcut(
                    str(payload.get("action") or "")
                ),
            )
        if tool_name == "app.open_and_safe_key":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="safe_key",
                action=lambda: desktop.desktop_safe_key(
                    str(payload.get("action") or ""),
                    repeat_count=payload.get("repeat_count", 1),
                ),
            )
        if tool_name == "app.focus_and_safe_key":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="safe_key",
                action=lambda: desktop.desktop_safe_key(
                    str(payload.get("action") or ""),
                    repeat_count=payload.get("repeat_count", 1),
                ),
            )
        if tool_name == "app.open_and_hotkey":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="hotkey",
                action=lambda: desktop.desktop_hotkey(
                    str(payload.get("key") or ""),
                    _string_list(payload.get("modifiers")),
                ),
            )
        if tool_name == "app.focus_and_hotkey":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="hotkey",
                action=lambda: desktop.desktop_hotkey(
                    str(payload.get("key") or ""),
                    _string_list(payload.get("modifiers")),
                ),
            )
        if tool_name == "app.open_and_safe_scroll":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="safe_scroll",
                action=lambda: desktop.desktop_safe_scroll(
                    str(payload.get("direction") or ""),
                    pages=payload.get("pages", 1),
                ),
            )
        if tool_name == "app.focus_and_safe_scroll":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="safe_scroll",
                action=lambda: desktop.desktop_safe_scroll(
                    str(payload.get("direction") or ""),
                    pages=payload.get("pages", 1),
                ),
            )
        if tool_name == "app.open_and_safe_click":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="safe_click",
                action=lambda: desktop.desktop_safe_click(
                    payload.get("x"),
                    payload.get("y"),
                ),
            )
        if tool_name == "app.focus_and_safe_click":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="safe_click",
                action=lambda: desktop.desktop_safe_click(
                    payload.get("x"),
                    payload.get("y"),
                ),
            )
        if tool_name == "app.open_and_click_ui_element":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="click_ui_element",
                action=lambda: desktop.click_ui_element(
                    str(payload.get("target") or ""),
                    role_filter=str(payload.get("role_filter") or ""),
                    limit=payload.get("limit", 80),
                    click_count=payload.get("click_count", 1),
                    expected_app_name=app_name,
                ),
            )
        if tool_name == "app.focus_and_click_ui_element":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="click_ui_element",
                action=lambda: desktop.click_ui_element(
                    str(payload.get("target") or ""),
                    role_filter=str(payload.get("role_filter") or ""),
                    limit=payload.get("limit", 80),
                    click_count=payload.get("click_count", 1),
                    expected_app_name=app_name,
                ),
            )
        if tool_name == "app.open_and_type_into_ui_element":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("open", "focus"),
                action_name="type_into_ui_element",
                action=lambda: desktop.type_into_ui_element(
                    str(payload.get("target") or ""),
                    str(payload.get("text") or ""),
                    role_filter=str(payload.get("role_filter") or ""),
                    limit=payload.get("limit", 80),
                    expected_app_name=app_name,
                ),
            )
        if tool_name == "app.focus_and_type_into_ui_element":
            return self._app_foreground_action(
                tool_name,
                app_name,
                setup=("focus",),
                action_name="type_into_ui_element",
                action=lambda: desktop.type_into_ui_element(
                    str(payload.get("target") or ""),
                    str(payload.get("text") or ""),
                    role_filter=str(payload.get("role_filter") or ""),
                    limit=payload.get("limit", 80),
                    expected_app_name=app_name,
                ),
            )
        return None

    def _app_foreground_action(
        self,
        tool_name: str,
        app_name: str,
        *,
        setup: tuple[str, ...],
        action_name: str,
        action: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        clean_app = str(app_name or "").strip()
        setup_results: dict[str, dict[str, Any]] = {}
        for step in setup:
            result = (
                desktop.app_open(clean_app)
                if step == "open"
                else desktop.app_focus(clean_app)
            )
            setup_results[step] = result
            if not result.get("ok"):
                return {
                    "ok": False,
                    "action": tool_name,
                    "summary": f"{tool_name} failed during {step}.",
                    "error": str(result.get("error") or f"{step}_failed"),
                    "data": {"app_name": clean_app, "failed_step": step},
                    "fallback_result": setup_results,
                }
        try:
            result = action()
        except Exception as exc:
            return {
                "ok": False,
                "action": tool_name,
                "summary": f"{tool_name} failed during {action_name}.",
                "error": redact_api_error_text(exc),
                "data": {"app_name": clean_app, "failed_step": action_name},
                "fallback_result": setup_results,
            }
        payload = dict(result)
        payload["action"] = tool_name
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        payload["data"] = {**data, "app_name": clean_app, "foreground_action": action_name}
        payload["fallback_result"] = {**setup_results, action_name: result}
        return payload

    def _approval_required_tool(
        self,
        tool_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "action": tool_name,
            "status": "provider_tool_approval_required",
            "error": "desktop_provider_tool_approval_required",
            "summary": "Controlled desktop provider requires Runtime approval for keyboard or mouse input.",
            "blocked_by_desktop_execution_provider": True,
            "blocking_condition": "desktop_provider_tool_approval_required",
            "blocking_conditions": ["desktop_provider_tool_approval_required"],
            "supported_tools": list(self.supported_tools),
            "input_preview": payload,
            "retryable": False,
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
        payload.pop("headless_desktop_provider", None)
        payload["controlled_desktop_provider"] = {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "version": CONTROLLED_DESKTOP_PROVIDER_VERSION,
            "execution_mode": "controlled_desktop",
            "approved": bool(approved),
            "foreground_mutation_supported": True,
            "keyboard_mouse_capture_supported": True,
        }
        return payload


def build_controlled_desktop_provider_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_CONTROLLED_PORT,
    token: str = "",
    provider: ControlledDesktopProvider | None = None,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    return build_headless_desktop_provider_server(
        host=host,
        port=port,
        token=token,
        provider=provider or ControlledDesktopProvider(),
        quiet=quiet,
    )


def serve_controlled_desktop_provider(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_CONTROLLED_PORT,
    token: str = "",
    provider_id: str = DEFAULT_CONTROLLED_PROVIDER_ID,
    provider_kind: str = DEFAULT_PROVIDER_KIND,
    supported_tools: Iterable[str] | None = None,
    require_approval_for_input: bool = True,
    quiet: bool = False,
) -> None:
    provider = ControlledDesktopProvider(
        provider_id=provider_id,
        provider_kind=provider_kind,
        supported_tools=supported_tools,
        require_approval_for_input=require_approval_for_input,
    )
    server = build_controlled_desktop_provider_server(
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
    provider = ControlledDesktopProvider(
        provider_id=args.provider_id,
        provider_kind=args.provider_kind,
        supported_tools=args.tool,
        require_approval_for_input=not args.allow_unapproved_input,
    )
    if args.manifest:
        print(json.dumps(provider.manifest(), ensure_ascii=False, sort_keys=True))
        return 0
    serve_controlled_desktop_provider(
        host=args.host,
        port=args.port,
        token=args.token or os.getenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN", ""),
        provider_id=args.provider_id,
        provider_kind=args.provider_kind,
        supported_tools=args.tool,
        require_approval_for_input=not args.allow_unapproved_input,
        quiet=args.quiet,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_CONTROLLED_PORT)
    parser.add_argument("--token", default="")
    parser.add_argument("--provider-id", default=DEFAULT_CONTROLLED_PROVIDER_ID)
    parser.add_argument("--provider-kind", default=DEFAULT_PROVIDER_KIND)
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--allow-unapproved-input", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def _alias_action(result: dict[str, Any], action: str) -> dict[str, Any]:
    payload = dict(result)
    payload["action"] = action
    return payload


def _sorted_tools(values: Iterable[str]) -> list[str]:
    return sorted({str(value or "").strip() for value in values if str(value or "").strip()})


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        raw_items = value
    else:
        raw_items = []
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
