"""Provider adapter boundary for routed desktop execution."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from typing import Any, Protocol
from urllib import error as urlerror
from urllib.parse import urlparse
from urllib.request import Request

from apps.core.tls import urlopen_with_bundled_ca
from packages.security import redact_api_error_text


class DesktopExecutionProviderAdapter(Protocol):
    """Executes desktop tools in a non-default provider such as a sandbox."""

    provider_kind: str

    def can_execute(
        self,
        tool_name: str,
        route: Mapping[str, Any],
        tool_request: Mapping[str, Any],
    ) -> bool:
        ...

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        ...


_DEFAULT_PROVIDER_KINDS = {"", "none", "tool_native", "native", "process"}
_PROVIDER_ROUTE_READY_STATUSES = {"ready", "sandbox_ready", "provider_ready"}
_DEFAULT_EXECUTE_PATH = "/tools/execute"
_DEFAULT_STATUS_PATH = "/status"
_PROVIDER_URL_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL",
)
_PROVIDER_EXECUTE_URL_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL",
)
_PROVIDER_TOKEN_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_TOKEN",
)
_PROVIDER_STATUS_URL_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_STATUS_URL",
)
LOCAL_DESKTOP_PROVIDER_ID = "local-native-desktop"
LOCAL_DESKTOP_PROVIDER_KIND = "local_desktop"
LOCAL_DESKTOP_PROVIDER_TOOLS = (
    "desktop.permissions",
    "desktop.permission_preflight",
    "desktop.active_window",
    "desktop.running_apps",
    "desktop.list_apps",
    "desktop.windows",
    "desktop.list_windows",
    "desktop.ui_elements",
    "desktop.read_ui",
    "desktop.inspect_app",
    "desktop.verify",
    "app.status",
    "app.open",
    "desktop.open_app",
    "app.focus",
    "desktop.focus_app",
    "app.focus_window",
    "app.show",
    "app.hide",
    "app.minimize",
    "desktop.hide_app",
    "desktop.show_all_apps",
    "desktop.minimize_window",
    "desktop.reveal_path",
    "desktop.open_path",
    "desktop.open_path_with_app",
    "app.open_path_with_app",
    "system.settings_open",
    "media.apple_music_play",
    "media.apple_music_status",
    "media.apple_music_open_and_play",
    "media.apple_music_control",
    "media.music_app_open_and_play",
    "media.music_app_control",
)


class DesktopExecutionProviderRegistry:
    """Registry of optional desktop execution provider adapters."""

    def __init__(
        self,
        adapters: Iterable[DesktopExecutionProviderAdapter] | None = None,
    ) -> None:
        self._adapters: dict[str, list[DesktopExecutionProviderAdapter]] = {}
        for adapter in adapters or ():
            self.register(adapter)

    def register(self, adapter: DesktopExecutionProviderAdapter) -> None:
        provider_kind = _clean_provider_kind(getattr(adapter, "provider_kind", ""))
        if not provider_kind:
            raise ValueError("desktop execution provider adapter requires provider_kind")
        self._adapters.setdefault(provider_kind, []).append(adapter)

    def adapter_for(
        self,
        provider_kind: str,
        tool_name: str,
        route: Mapping[str, Any],
        tool_request: Mapping[str, Any],
    ) -> DesktopExecutionProviderAdapter | None:
        clean_provider_kind = _clean_provider_kind(provider_kind)
        for adapter in self._adapters.get(clean_provider_kind, []):
            can_execute = getattr(adapter, "can_execute", None)
            if callable(can_execute) and not can_execute(tool_name, route, tool_request):
                continue
            return adapter
        return None

    def execute_if_routed(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any] | None:
        route = desktop_execution_route_payload(tool_request)
        if not desktop_execution_route_requires_provider(route):
            return None

        provider_kind = _route_provider_kind(route)
        adapter = self.adapter_for(provider_kind, tool_name, route, tool_request)
        if adapter is None:
            return desktop_execution_provider_unavailable_result(
                tool_name,
                route=route,
                tool_request=tool_request,
            )

        result = adapter.execute(
            tool_name,
            payload,
            tool_request=tool_request,
            route=route,
            broker=broker,
            approved=approved,
        )
        return _with_desktop_provider_context(
            dict(result) if isinstance(result, Mapping) else {"ok": True, "result": result},
            tool_name=tool_name,
            route=route,
            tool_request=tool_request,
            adapter_registered=True,
        )


class HttpDesktopExecutionProviderAdapter:
    """Calls a local sandbox/headless desktop provider over HTTP."""

    def __init__(
        self,
        *,
        provider_kind: str = "sandbox_desktop",
        provider_id: str = "",
        base_url: str = "",
        execute_url: str = "",
        status_url: str = "",
        token: str = "",
        supported_tools: Iterable[str] | None = None,
        timeout: float = 20.0,
        urlopen: Any | None = None,
    ) -> None:
        self.provider_kind = _clean_provider_kind(provider_kind) or "sandbox_desktop"
        self.provider_id = str(provider_id or "").strip()
        self.base_url = _clean_base_url(base_url)
        self.execute_url = str(execute_url or "").strip() or _join_url(
            self.base_url,
            _DEFAULT_EXECUTE_PATH,
        )
        self.status_url = str(status_url or "").strip() or _join_url(
            self.base_url,
            _DEFAULT_STATUS_PATH,
        )
        self.token = str(token or "").strip()
        self.supported_tools = _string_list(supported_tools)
        self.timeout = max(0.1, float(timeout or 20.0))
        self._urlopen = urlopen or urlopen_with_bundled_ca

    def can_execute(
        self,
        tool_name: str,
        route: Mapping[str, Any],
        tool_request: Mapping[str, Any],
    ) -> bool:
        selected_provider_id = str(route.get("selected_provider_id") or "").strip()
        if (
            self.provider_id
            and selected_provider_id
            and selected_provider_id != self.provider_id
        ):
            return False
        if self.supported_tools and tool_name not in self.supported_tools:
            return False
        provider_supported_tools = _string_list(
            sandbox_provider_payload(tool_request).get("supported_tools")
        )
        return not provider_supported_tools or tool_name in provider_supported_tools

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        request_payload = {
            "tool": tool_name,
            "input": dict(payload),
            "approved": bool(approved),
            "route": dict(route),
            "tool_request": dict(tool_request),
            "provider": {
                "provider_kind": self.provider_kind,
                "provider_id": self.provider_id,
            },
        }
        request = Request(
            self.execute_url,
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                status_code = int(
                    getattr(response, "status", 0) or response.getcode() or 0
                )
                raw_body = response.read()
        except (OSError, urlerror.URLError, TimeoutError) as exc:
            return self._transport_failure(tool_name, exc)
        except Exception as exc:
            return self._transport_failure(tool_name, exc)

        try:
            decoded = (
                raw_body.decode("utf-8")
                if isinstance(raw_body, bytes)
                else str(raw_body or "")
            )
            response_payload = json.loads(decoded) if decoded.strip() else {}
        except (TypeError, ValueError) as exc:
            return self._transport_failure(tool_name, exc, status_code=status_code)

        result = (
            response_payload.get("result")
            if isinstance(response_payload, Mapping)
            and isinstance(response_payload.get("result"), Mapping)
            else response_payload
        )
        if not isinstance(result, Mapping):
            result = {"ok": True, "content": result}
        tool_result = dict(result)
        tool_result.setdefault("ok", 200 <= status_code < 400 if status_code else True)
        tool_result.setdefault("tool", tool_name)
        tool_result.setdefault(
            "desktop_execution_provider_transport",
            self._transport_metadata(status_code=status_code),
        )
        return tool_result

    def health(self) -> dict[str, Any]:
        if not self.status_url:
            return self._health_payload(
                ok=False,
                checked=False,
                status="status_endpoint_missing",
                blocking_conditions=["desktop_execution_provider_status_endpoint_missing"],
            )
        request = Request(
            self.status_url,
            headers=self._headers(),
            method="GET",
        )
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                status_code = int(
                    getattr(response, "status", 0) or response.getcode() or 0
                )
                raw_body = response.read()
        except (OSError, urlerror.URLError, TimeoutError) as exc:
            return self._health_payload(
                ok=False,
                checked=True,
                status="unreachable",
                blocking_conditions=["desktop_execution_provider_unreachable"],
                error=redact_api_error_text(exc),
            )
        except Exception as exc:
            return self._health_payload(
                ok=False,
                checked=True,
                status="unreachable",
                blocking_conditions=["desktop_execution_provider_unreachable"],
                error=redact_api_error_text(exc),
            )

        response_payload, parse_error = _json_payload_from_bytes(raw_body)
        if parse_error:
            return self._health_payload(
                ok=False,
                checked=True,
                status="invalid_response",
                blocking_conditions=["desktop_execution_provider_invalid_status_response"],
                status_code=status_code,
                error=parse_error,
            )
        remote_ok = not (
            isinstance(response_payload, Mapping) and response_payload.get("ok") is False
        )
        ok = 200 <= status_code < 400 and remote_ok
        provider_payload = dict(response_payload) if isinstance(response_payload, Mapping) else {}
        supported_tools = _string_list(
            provider_payload.get("supported_tools")
            or provider_payload.get("tools")
            or self.supported_tools
        )
        return self._health_payload(
            ok=ok,
            checked=True,
            status=str(provider_payload.get("status") or ("healthy" if ok else "unhealthy")),
            blocking_conditions=(
                []
                if ok
                else _string_list(provider_payload.get("blocking_conditions"))
                or ["desktop_execution_provider_unhealthy"]
            ),
            status_code=status_code,
            provider_version=str(provider_payload.get("version") or ""),
            supported_tools=supported_tools,
            capabilities=_string_list(provider_payload.get("capabilities")),
        )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Oha-Yachiyo-Desktop-Provider/1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def configured_status(self, *, probe_health: bool = False) -> dict[str, Any]:
        health = self.health() if probe_health else self._health_payload(
            ok=False,
            checked=False,
            status="not_checked",
            blocking_conditions=[],
            supported_tools=self.supported_tools,
        )
        return {
            "configured": True,
            "available": bool(health.get("ok")) if probe_health else True,
            "adapter_ready": bool(health.get("ok")) if probe_health else True,
            "provider_kind": self.provider_kind,
            "provider_id": self.provider_id,
            "status": (
                "available"
                if (not probe_health or bool(health.get("ok")))
                else "provider_unhealthy"
            ),
            "reason": (
                "Desktop execution provider is configured and healthy."
                if bool(health.get("ok"))
                else (
                    "Desktop execution provider is configured; health has not been checked."
                    if not probe_health
                    else "Desktop execution provider is configured but health check failed."
                )
            ),
            "blocking_conditions": (
                []
                if (not probe_health or bool(health.get("ok")))
                else _string_list(health.get("blocking_conditions"))
                or ["desktop_execution_provider_unhealthy"]
            ),
            "supported_tools": _string_list(health.get("supported_tools"))
            or self.supported_tools,
            "health": health,
            "endpoint_origin": _url_origin(urlparse(self.execute_url)),
            "endpoint_path": urlparse(self.execute_url).path or _DEFAULT_EXECUTE_PATH,
            "status_endpoint_path": urlparse(self.status_url).path or _DEFAULT_STATUS_PATH,
            "source": "runtime_env",
        }

    def _transport_failure(
        self,
        tool_name: str,
        exc: Exception,
        *,
        status_code: int = 0,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "action": tool_name,
            "status": "provider_transport_failed",
            "error": "desktop_execution_provider_transport_failed",
            "summary": "Desktop execution provider request failed.",
            "blocked_by_desktop_execution_provider": True,
            "blocking_condition": "desktop_execution_provider_transport_failed",
            "blocking_conditions": ["desktop_execution_provider_transport_failed"],
            "retryable": True,
            "desktop_execution_provider_transport": self._transport_metadata(
                status_code=status_code,
                error=redact_api_error_text(exc),
            ),
            "hint": (
                "Check that the sandbox/headless desktop provider is running on a "
                "local endpoint, then retry the routed tool call."
            ),
        }

    def _transport_metadata(
        self,
        *,
        status_code: int = 0,
        error: str = "",
    ) -> dict[str, Any]:
        parsed = urlparse(self.execute_url)
        payload: dict[str, Any] = {
            "provider_kind": self.provider_kind,
            "provider_id": self.provider_id,
            "endpoint_origin": _url_origin(parsed),
            "endpoint_path": parsed.path or _DEFAULT_EXECUTE_PATH,
        }
        if status_code:
            payload["status_code"] = status_code
        if error:
            payload["error"] = error
        return payload

    def _health_payload(
        self,
        *,
        ok: bool,
        checked: bool,
        status: str,
        blocking_conditions: Iterable[str],
        status_code: int = 0,
        error: str = "",
        provider_version: str = "",
        supported_tools: Iterable[str] | None = None,
        capabilities: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        parsed = urlparse(self.status_url)
        payload: dict[str, Any] = {
            "ok": bool(ok),
            "checked": bool(checked),
            "status": str(status or ""),
            "provider_kind": self.provider_kind,
            "provider_id": self.provider_id,
            "endpoint_origin": _url_origin(parsed),
            "endpoint_path": parsed.path or _DEFAULT_STATUS_PATH,
            "blocking_conditions": _string_list(blocking_conditions),
            "supported_tools": _string_list(supported_tools),
            "capabilities": _string_list(capabilities),
        }
        if status_code:
            payload["status_code"] = status_code
        if error:
            payload["error"] = error
        if provider_version:
            payload["provider_version"] = provider_version
        return payload


class LocalDesktopExecutionProviderAdapter:
    """Routes low-risk desktop actions through the local structured tool broker."""

    provider_kind = LOCAL_DESKTOP_PROVIDER_KIND

    def __init__(
        self,
        *,
        provider_id: str = LOCAL_DESKTOP_PROVIDER_ID,
        supported_tools: Iterable[str] | None = None,
    ) -> None:
        self.provider_id = str(provider_id or LOCAL_DESKTOP_PROVIDER_ID).strip()
        self.supported_tools = _string_list(supported_tools) or list(
            LOCAL_DESKTOP_PROVIDER_TOOLS
        )

    def can_execute(
        self,
        tool_name: str,
        route: Mapping[str, Any],
        tool_request: Mapping[str, Any],
    ) -> bool:
        selected_provider_id = str(route.get("selected_provider_id") or "").strip()
        if (
            self.provider_id
            and selected_provider_id
            and selected_provider_id != self.provider_id
        ):
            return False
        if tool_name not in self.supported_tools:
            return False
        provider_supported_tools = _string_list(
            sandbox_provider_payload(tool_request).get("supported_tools")
        )
        return not provider_supported_tools or tool_name in provider_supported_tools

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        call = getattr(broker, "call", None)
        if not callable(call):
            return self._failure(
                tool_name,
                "local_desktop_provider_broker_unavailable",
                "Local desktop provider could not access the runtime tool broker.",
                retryable=False,
            )
        try:
            result = call(tool_name, dict(payload), approved=approved)
        except Exception as exc:
            return self._failure(
                tool_name,
                "local_desktop_provider_tool_failed",
                "Local desktop provider tool execution failed.",
                error=redact_api_error_text(exc),
            )
        tool_result = (
            dict(result)
            if isinstance(result, Mapping)
            else {"ok": True, "content": result}
        )
        tool_result.setdefault("tool", tool_name)
        tool_result.setdefault("action", tool_name)
        tool_result.setdefault(
            "local_desktop_provider",
            {
                "provider_id": self.provider_id,
                "provider_kind": self.provider_kind,
                "approved": bool(approved),
                "supported_tools": list(self.supported_tools),
            },
        )
        return tool_result

    def _failure(
        self,
        tool_name: str,
        status: str,
        summary: str,
        *,
        error: str = "",
        retryable: bool = True,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "tool": tool_name,
            "action": tool_name,
            "status": status,
            "error": error or status,
            "summary": summary,
            "blocked_by_desktop_execution_provider": True,
            "blocking_condition": status,
            "blocking_conditions": [status],
            "retryable": retryable,
            "desktop_execution_provider_transport": {
                "provider_kind": self.provider_kind,
                "provider_id": self.provider_id,
                "transport": "local_broker",
            },
        }


def default_desktop_execution_provider_registry() -> DesktopExecutionProviderRegistry:
    return desktop_execution_provider_registry_from_env()


def desktop_execution_provider_registry_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    urlopen: Any | None = None,
) -> DesktopExecutionProviderRegistry:
    adapter = _http_desktop_execution_provider_adapter_from_env(
        environ,
        urlopen=urlopen,
    )
    local_adapter = LocalDesktopExecutionProviderAdapter()
    if adapter is None:
        return DesktopExecutionProviderRegistry([local_adapter])
    return DesktopExecutionProviderRegistry([adapter, local_adapter])


def local_desktop_execution_provider_status(
    *,
    supported_tools: Iterable[str] | None = None,
) -> dict[str, Any]:
    tools = _string_list(supported_tools) or list(LOCAL_DESKTOP_PROVIDER_TOOLS)
    blockers: list[str] = []
    return {
        "configured": True,
        "available": True,
        "adapter_ready": True,
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "status": "available",
        "reason": (
            "Local desktop provider is available for low-risk discovery, app launch, "
            "focus, and media control tools."
        ),
        "blocking_conditions": blockers,
        "supported_tools": tools,
        "health": {
            "ok": True,
            "checked": True,
            "status": "ready",
            "blocking_conditions": blockers,
            "supported_tools": tools,
            "capabilities": [
                "desktop_discovery",
                "app_launch",
                "foreground_activation",
                "media_control",
                "no_keyboard_mouse_capture",
            ],
        },
        "source": "runtime_local",
        "foreground_mutation_supported": True,
        "keyboard_mouse_capture_supported": False,
    }


def desktop_execution_provider_status_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    probe_health: bool = False,
    urlopen: Any | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    provider_url = _first_env_value(env, _PROVIDER_URL_ENV_KEYS)
    execute_url = _first_env_value(env, _PROVIDER_EXECUTE_URL_ENV_KEYS)
    if not provider_url and not execute_url:
        return {
            "configured": False,
            "available": False,
            "adapter_ready": False,
            "provider_kind": "sandbox_desktop",
            "provider_id": "",
            "status": "provider_required",
            "reason": "No desktop execution provider endpoint is configured.",
            "blocking_conditions": ["sandbox_desktop_provider_required"],
            "supported_tools": [],
            "health": {
                "ok": False,
                "checked": False,
                "status": "not_configured",
                "blocking_conditions": ["sandbox_desktop_provider_required"],
                "supported_tools": [],
                "capabilities": [],
            },
            "source": "runtime_env",
        }
    clean_execute_url = _provider_execute_url(env)
    if (
        not _truthy_env_value(env, "OHA_YACHIYO_DESKTOP_PROVIDER_ALLOW_REMOTE")
        and not _is_loopback_url(clean_execute_url)
    ):
        return {
            "configured": True,
            "available": False,
            "adapter_ready": False,
            "provider_kind": _provider_kind_from_env(env),
            "provider_id": _first_env_value(env, ("OHA_YACHIYO_DESKTOP_PROVIDER_ID",)),
            "status": "remote_provider_blocked",
            "reason": "Desktop execution provider endpoint is not loopback-local.",
            "blocking_conditions": ["desktop_execution_provider_remote_blocked"],
            "supported_tools": [],
            "health": {
                "ok": False,
                "checked": False,
                "status": "remote_provider_blocked",
                "blocking_conditions": ["desktop_execution_provider_remote_blocked"],
                "supported_tools": [],
                "capabilities": [],
            },
            "source": "runtime_env",
        }
    adapter = _http_desktop_execution_provider_adapter_from_env(
        env,
        urlopen=urlopen,
    )
    if adapter is None:
        return {
            "configured": True,
            "available": False,
            "adapter_ready": False,
            "provider_kind": _provider_kind_from_env(env),
            "provider_id": _first_env_value(env, ("OHA_YACHIYO_DESKTOP_PROVIDER_ID",)),
            "status": "provider_adapter_unavailable",
            "reason": "Desktop execution provider adapter could not be configured.",
            "blocking_conditions": ["desktop_execution_provider_adapter_unavailable"],
            "supported_tools": [],
            "health": {
                "ok": False,
                "checked": False,
                "status": "provider_adapter_unavailable",
                "blocking_conditions": ["desktop_execution_provider_adapter_unavailable"],
                "supported_tools": [],
                "capabilities": [],
            },
            "source": "runtime_env",
        }
    return adapter.configured_status(probe_health=probe_health)


def desktop_execution_route_payload(tool_request: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(tool_request, Mapping):
        return {}
    for key in ("desktop_execution_route", "desktop_route"):
        value = tool_request.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    metadata = tool_request.get("metadata")
    if isinstance(metadata, Mapping) and metadata is not tool_request:
        return desktop_execution_route_payload(metadata)
    return {}


def sandbox_provider_payload(tool_request: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(tool_request, Mapping):
        return {}
    for key in ("sandbox_provider", "sandbox_desktop_provider", "desktop_sandbox_provider"):
        value = tool_request.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    metadata = tool_request.get("metadata")
    if isinstance(metadata, Mapping) and metadata is not tool_request:
        return sandbox_provider_payload(metadata)
    return {}


def desktop_execution_route_allows_provider_execution(
    route: Mapping[str, Any] | Any,
) -> bool:
    if not isinstance(route, Mapping) or not bool(route.get("can_execute")):
        return False
    if str(route.get("status") or "").strip() not in _PROVIDER_ROUTE_READY_STATUSES:
        return False
    return desktop_execution_route_requires_provider(route)


def desktop_execution_route_requires_provider(route: Mapping[str, Any] | Any) -> bool:
    if not isinstance(route, Mapping) or not bool(route.get("can_execute")):
        return False
    provider_kind = _route_provider_kind(route)
    if not provider_kind or provider_kind in _DEFAULT_PROVIDER_KINDS:
        return False
    if bool(route.get("provider_execution_required")):
        return True
    if provider_kind == "sandbox_desktop":
        return True
    if bool(route.get("sandbox_required")):
        return True
    if str(route.get("status") or "").strip() == "sandbox_ready":
        return True
    requested_mode = str(route.get("requested_mode") or "").strip().lower().replace("-", "_")
    return requested_mode == "sandbox_preferred"


def desktop_execution_provider_unavailable_result(
    tool_name: str,
    *,
    route: Mapping[str, Any],
    tool_request: Mapping[str, Any],
) -> dict[str, Any]:
    blocking_conditions = ["desktop_execution_provider_unavailable"]
    route_blockers = [
        str(item).strip()
        for item in route.get("blocking_conditions", [])
        if str(item or "").strip()
    ]
    for blocker in route_blockers:
        if blocker not in blocking_conditions:
            blocking_conditions.append(blocker)
    return _with_desktop_provider_context(
        {
            "ok": False,
            "tool": tool_name,
            "action": tool_name,
            "status": "provider_unavailable",
            "error": "desktop_execution_provider_unavailable",
            "summary": (
                "Desktop execution provider route was selected, but no adapter is "
                "registered in this runtime."
            ),
            "blocked_by_desktop_execution_provider": True,
            "blocking_condition": blocking_conditions[0],
            "blocking_conditions": blocking_conditions,
            "hint": (
                "Continue in supervised_live or configure a sandbox/headless desktop "
                "execution provider adapter."
            ),
        },
        tool_name=tool_name,
        route=route,
        tool_request=tool_request,
        adapter_registered=False,
    )


def _with_desktop_provider_context(
    result: dict[str, Any],
    *,
    tool_name: str,
    route: Mapping[str, Any],
    tool_request: Mapping[str, Any],
    adapter_registered: bool,
) -> dict[str, Any]:
    provider_kind = _route_provider_kind(route)
    provider_context = {
        "provider_kind": provider_kind,
        "provider_id": str(route.get("selected_provider_id") or "").strip(),
        "adapter_registered": adapter_registered,
        "route_id": str(route.get("route_id") or "").strip(),
    }
    result.setdefault("tool", tool_name)
    result["desktop_execution_provider_routed"] = True
    result["desktop_execution_provider"] = provider_context
    result["desktop_execution_route"] = dict(route)
    sandbox_provider = sandbox_provider_payload(tool_request)
    if sandbox_provider:
        result["sandbox_provider"] = sandbox_provider
    return result


def _route_provider_kind(route: Mapping[str, Any]) -> str:
    return _clean_provider_kind(route.get("selected_provider_kind") or route.get("provider_kind"))


def _clean_provider_kind(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _http_desktop_execution_provider_adapter_from_env(
    environ: Mapping[str, str] | None = None,
    *,
    urlopen: Any | None = None,
) -> HttpDesktopExecutionProviderAdapter | None:
    env = os.environ if environ is None else environ
    provider_url = _first_env_value(env, _PROVIDER_URL_ENV_KEYS)
    execute_url = _first_env_value(env, _PROVIDER_EXECUTE_URL_ENV_KEYS)
    if not provider_url and not execute_url:
        return None
    clean_execute_url = _provider_execute_url(env)
    allow_remote = _truthy_env_value(env, "OHA_YACHIYO_DESKTOP_PROVIDER_ALLOW_REMOTE")
    if not allow_remote and not _is_loopback_url(clean_execute_url):
        return None
    status_url = _first_env_value(env, _PROVIDER_STATUS_URL_ENV_KEYS) or _join_url(
        _clean_base_url(provider_url),
        _DEFAULT_STATUS_PATH,
    )
    if status_url and not allow_remote and not _is_loopback_url(status_url):
        return None
    return HttpDesktopExecutionProviderAdapter(
        provider_kind=_provider_kind_from_env(env),
        provider_id=_first_env_value(env, ("OHA_YACHIYO_DESKTOP_PROVIDER_ID",)),
        base_url=provider_url,
        execute_url=clean_execute_url,
        status_url=status_url,
        token=_first_env_value(env, _PROVIDER_TOKEN_ENV_KEYS),
        supported_tools=_string_list(
            _first_env_value(env, ("OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",))
        ),
        timeout=_float_env_value(
            env,
            "OHA_YACHIYO_DESKTOP_PROVIDER_TIMEOUT_SECONDS",
            20.0,
        ),
        urlopen=urlopen,
    )


def _provider_execute_url(env: Mapping[str, str]) -> str:
    provider_url = _first_env_value(env, _PROVIDER_URL_ENV_KEYS)
    execute_url = _first_env_value(env, _PROVIDER_EXECUTE_URL_ENV_KEYS)
    return str(execute_url or "").strip() or _join_url(
        _clean_base_url(provider_url),
        _DEFAULT_EXECUTE_PATH,
    )


def _provider_kind_from_env(env: Mapping[str, str]) -> str:
    return _clean_provider_kind(
        _first_env_value(env, ("OHA_YACHIYO_DESKTOP_PROVIDER_KIND",))
        or "sandbox_desktop"
    )


def _first_env_value(env: Mapping[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        value = str(env.get(key) or "").strip()
        if value:
            return value
    return ""


def _float_env_value(env: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(str(env.get(key) or "").strip() or default)
    except (TypeError, ValueError):
        return default


def _truthy_env_value(env: Mapping[str, str], key: str) -> bool:
    return str(env.get(key) or "").strip().lower() in {"1", "true", "yes", "on"}


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


def _clean_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _join_url(base_url: str, path: str) -> str:
    clean_base = _clean_base_url(base_url)
    if not clean_base:
        return ""
    clean_path = "/" + str(path or "").strip().lstrip("/")
    return f"{clean_base}{clean_path}"


def _is_loopback_url(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def _url_origin(parsed: Any) -> str:
    host = parsed.hostname or ""
    if not host:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def _json_payload_from_bytes(raw_body: Any) -> tuple[Any, str]:
    try:
        decoded = (
            raw_body.decode("utf-8")
            if isinstance(raw_body, bytes)
            else str(raw_body or "")
        )
        return (json.loads(decoded) if decoded.strip() else {}, "")
    except (TypeError, ValueError) as exc:
        return {}, redact_api_error_text(exc)
