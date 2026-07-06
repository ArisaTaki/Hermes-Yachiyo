"""Loopback HTTP provider for safe headless desktop discovery tools."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from apps.shell.agent.tools import desktop
from packages.security import redact_api_error_text

HEADLESS_DESKTOP_PROVIDER_VERSION = "0.1.0"
DEFAULT_PROVIDER_ID = "local-headless-desktop"
DEFAULT_PROVIDER_KIND = "sandbox_desktop"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19091

SAFE_HEADLESS_DESKTOP_TOOLS = (
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
)


class HeadlessDesktopProvider:
    """Executes read-only desktop discovery tools behind the provider contract."""

    def __init__(
        self,
        *,
        provider_id: str = DEFAULT_PROVIDER_ID,
        provider_kind: str = DEFAULT_PROVIDER_KIND,
        supported_tools: Iterable[str] | None = None,
    ) -> None:
        self.provider_id = str(provider_id or DEFAULT_PROVIDER_ID).strip()
        self.provider_kind = str(provider_kind or DEFAULT_PROVIDER_KIND).strip()
        self.supported_tools = _string_list(supported_tools) or list(
            SAFE_HEADLESS_DESKTOP_TOOLS
        )

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ready",
            "version": HEADLESS_DESKTOP_PROVIDER_VERSION,
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "supported_tools": list(self.supported_tools),
            "capabilities": [
                "desktop_discovery",
                "read_only_observation",
                "permission_diagnostics",
                "no_foreground_mutation",
            ],
            "blocking_conditions": [],
            "execution_mode": "headless_read_only",
            "foreground_mutation_supported": False,
            "keyboard_mouse_capture_supported": False,
            "desktop_session_kind": "headless_read_only",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "requires_real_sandbox_for": ["click", "type", "shortcut", "focus"],
        }

    def manifest(self, *, base_url: str = "") -> dict[str, Any]:
        endpoints = {
            "status": "/status",
            "health": "/health",
            "manifest": "/manifest",
            "execute": "/tools/execute",
        }
        return {
            "ok": True,
            "version": HEADLESS_DESKTOP_PROVIDER_VERSION,
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "execution_mode": "headless_read_only",
            "foreground_mutation_supported": False,
            "keyboard_mouse_capture_supported": False,
            "desktop_session_kind": "headless_read_only",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "requires_real_sandbox_for": ["click", "type", "shortcut", "focus"],
            "capabilities": [
                "desktop_discovery",
                "read_only_observation",
                "permission_diagnostics",
                "no_foreground_mutation",
            ],
            "supported_tools": list(self.supported_tools),
            "default_bind": {"host": DEFAULT_HOST, "port": DEFAULT_PORT},
            "endpoints": endpoints,
            "endpoint_urls": {
                key: _join_url(base_url, path) for key, path in endpoints.items()
            }
            if base_url
            else {},
            "environment": {
                "url": "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
                "token": "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN",
                "provider_id": "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
                "provider_kind": "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
                "tools": "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
            },
            "entrypoint": {
                "script": "scripts/run_headless_desktop_provider.py",
                "module": "apps.shell.agent.runtime.headless_desktop_provider",
                "args": ["--host", DEFAULT_HOST, "--port", str(DEFAULT_PORT)],
            },
            "safety": {
                "loopback_default": True,
                "remote_default_allowed": False,
                "foreground_mutation_tools_supported": False,
                "requires_real_sandbox_for": ["click", "type", "shortcut", "focus"],
            },
        }

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
        if clean_tool not in self.supported_tools:
            return self._unsupported_tool(clean_tool, clean_payload)
        try:
            result = self._dispatch(clean_tool, clean_payload)
        except Exception as exc:
            return {
                "ok": False,
                "tool": clean_tool,
                "action": clean_tool,
                "status": "provider_tool_failed",
                "error": redact_api_error_text(exc),
                "summary": "Headless desktop provider tool execution failed.",
                "blocking_condition": "desktop_provider_tool_failed",
                "blocking_conditions": ["desktop_provider_tool_failed"],
                "retryable": True,
            }
        return self._with_provider_context(
            result,
            tool_name=clean_tool,
            approved=approved,
            route=route,
            tool_request=tool_request,
        )

    def _dispatch(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        dispatch: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "desktop.permissions": lambda _payload: desktop.permissions(),
            "desktop.permission_preflight": lambda _payload: desktop.permission_preflight(),
            "desktop.active_window": lambda _payload: desktop.active_window(),
            "desktop.running_apps": lambda _payload: desktop.running_apps(),
            "desktop.list_apps": lambda value: desktop.list_apps(
                query=str(value.get("query") or ""),
                limit=value.get("limit", 200),
            ),
            "desktop.windows": lambda value: desktop.windows(
                str(value.get("app_name") or "")
            ),
            "desktop.list_windows": lambda value: {
                **desktop.windows(str(value.get("app_name") or "")),
                "action": "desktop.list_windows",
            },
            "desktop.ui_elements": lambda value: desktop.ui_elements(
                role_filter=str(value.get("role_filter") or ""),
                limit=value.get("limit", 80),
                app_name=str(value.get("app_name") or ""),
            ),
            "desktop.read_ui": lambda value: {
                **desktop.ui_elements(
                    role_filter=str(value.get("role_filter") or ""),
                    limit=value.get("limit", 80),
                    app_name=str(value.get("app_name") or ""),
                ),
                "action": "desktop.read_ui",
            },
            "desktop.verify": self._verify,
            "app.status": lambda value: desktop.app_status(
                str(value.get("app_name") or "")
            ),
        }
        return dispatch[tool_name](payload)

    def _verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        app_name = str(payload.get("app_name") or "").strip()
        if app_name:
            result = desktop.windows(app_name)
            return {
                **result,
                "action": "desktop.verify",
                "summary": result.get("summary") or f"Verified desktop app: {app_name}",
            }
        result = desktop.active_window()
        return {
            **result,
            "action": "desktop.verify",
            "summary": result.get("summary") or "Verified active desktop window",
        }

    def _unsupported_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "action": tool_name,
            "status": "tool_unsupported",
            "error": "desktop_provider_tool_unsupported",
            "summary": (
                "Headless desktop provider only supports read-only discovery tools."
            ),
            "blocked_by_desktop_execution_provider": True,
            "blocking_condition": "desktop_provider_tool_unsupported",
            "blocking_conditions": ["desktop_provider_tool_unsupported"],
            "supported_tools": list(self.supported_tools),
            "input_preview": payload,
            "hint": (
                "Use a real sandbox desktop provider for foreground input, clicking, "
                "typing, or app mutation."
            ),
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
        payload = dict(result) if isinstance(result, dict) else {"ok": True, "result": result}
        payload.setdefault("tool", tool_name)
        payload.setdefault("action", tool_name)
        payload["headless_desktop_provider"] = {
            "provider_id": self.provider_id,
            "provider_kind": self.provider_kind,
            "version": HEADLESS_DESKTOP_PROVIDER_VERSION,
            "execution_mode": "headless_read_only",
            "approved": bool(approved),
            "foreground_mutation_supported": False,
        }
        if isinstance(route, Mapping):
            payload["provider_route"] = dict(route)
        if isinstance(tool_request, Mapping):
            payload["provider_request_id"] = str(tool_request.get("request_id") or "")
        return payload


class HeadlessDesktopProviderRequestHandler(BaseHTTPRequestHandler):
    server_version = "OhaHeadlessDesktopProvider/0.1"

    def do_GET(self) -> None:
        path = _request_path(self.path)
        if path == "/manifest":
            if not self._authorized():
                return
            self._send_json(self._provider().manifest(base_url=_request_base_url(self)))
            return
        if path not in {"/status", "/health"}:
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return
        if not self._authorized():
            return
        self._send_json(self._provider().status())

    def do_POST(self) -> None:
        if self.path not in {"/tools/execute", "/execute"}:
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return
        if not self._authorized():
            return
        request_payload = self._read_json_payload()
        if not isinstance(request_payload, Mapping):
            self._send_json(
                {"ok": False, "error": "invalid_json_payload"},
                status=400,
            )
            return
        tool_name = str(request_payload.get("tool") or "").strip()
        tool_input = request_payload.get("input")
        result = self._provider().execute(
            tool_name,
            tool_input if isinstance(tool_input, Mapping) else {},
            approved=bool(request_payload.get("approved")),
            route=(
                request_payload.get("route")
                if isinstance(request_payload.get("route"), Mapping)
                else {}
            ),
            tool_request=(
                request_payload.get("tool_request")
                if isinstance(request_payload.get("tool_request"), Mapping)
                else {}
            ),
        )
        self._send_json({"ok": bool(result.get("ok")), "result": result})

    def log_message(self, format: str, *args: Any) -> None:
        if bool(getattr(self.server, "quiet", False)):
            return
        super().log_message(format, *args)

    def _authorized(self) -> bool:
        token = str(getattr(self.server, "token", "") or "").strip()
        if not token:
            return True
        bearer = str(self.headers.get("Authorization") or "").strip()
        header_token = str(self.headers.get("X-Oha-Desktop-Provider-Token") or "").strip()
        if bearer == f"Bearer {token}" or header_token == token:
            return True
        self._send_json({"ok": False, "error": "unauthorized"}, status=401)
        return False

    def _provider(self) -> HeadlessDesktopProvider:
        return getattr(self.server, "provider")

    def _read_json_payload(self) -> Any:
        try:
            length = max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (TypeError, ValueError):
            return None

    def _send_json(self, payload: Mapping[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_headless_desktop_provider_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str = "",
    provider: HeadlessDesktopProvider | None = None,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), HeadlessDesktopProviderRequestHandler)
    server.provider = provider or HeadlessDesktopProvider()  # type: ignore[attr-defined]
    server.token = str(token or "").strip()  # type: ignore[attr-defined]
    server.quiet = bool(quiet)  # type: ignore[attr-defined]
    return server


def serve_headless_desktop_provider(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    token: str = "",
    provider_id: str = DEFAULT_PROVIDER_ID,
    provider_kind: str = DEFAULT_PROVIDER_KIND,
    supported_tools: Iterable[str] | None = None,
    quiet: bool = False,
) -> None:
    provider = HeadlessDesktopProvider(
        provider_id=provider_id,
        provider_kind=provider_kind,
        supported_tools=supported_tools,
    )
    server = build_headless_desktop_provider_server(
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
    provider = HeadlessDesktopProvider(
        provider_id=args.provider_id,
        provider_kind=args.provider_kind,
        supported_tools=args.tool,
    )
    if args.manifest:
        print(json.dumps(provider.manifest(), ensure_ascii=False, sort_keys=True))
        return 0
    serve_headless_desktop_provider(
        host=args.host,
        port=args.port,
        token=args.token or os.getenv("OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN", ""),
        provider_id=args.provider_id,
        provider_kind=args.provider_kind,
        supported_tools=args.tool,
        quiet=args.quiet,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--token", default="")
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--provider-kind", default=DEFAULT_PROVIDER_KIND)
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser


def _request_path(raw_path: str) -> str:
    return urlparse(str(raw_path or "")).path or "/"


def _request_base_url(handler: BaseHTTPRequestHandler) -> str:
    host, port = handler.server.server_address[:2]
    return f"http://{host}:{port}"


def _join_url(base_url: str, path: str) -> str:
    clean_base = str(base_url or "").rstrip("/")
    if not clean_base:
        return ""
    clean_path = "/" + str(path or "").lstrip("/")
    return f"{clean_base}{clean_path}"


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
