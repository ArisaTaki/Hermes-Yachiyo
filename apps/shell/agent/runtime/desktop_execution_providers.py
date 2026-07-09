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
_PROVIDER_FOREGROUND_MUTATION_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_MUTATION_SUPPORTED",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_FOREGROUND_MUTATION_SUPPORTED",
)
_PROVIDER_KEYBOARD_MOUSE_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
)
_PROVIDER_REQUIRES_REAL_SANDBOX_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_SANDBOX_FOR",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_REQUIRES_REAL_SANDBOX_FOR",
)
_PROVIDER_SESSION_KIND_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_SESSION_KIND",
)
_PROVIDER_SESSION_ISOLATED_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_SESSION_ISOLATED",
)
_PROVIDER_FOREGROUND_TAKEOVER_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
)
_PROVIDER_BACKEND_KIND_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_BACKEND_KIND",
)
_PROVIDER_BACKEND_LOOPBACK_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK",
)
_PROVIDER_BACKEND_RELEASE_READY_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE",
)
_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_ENV_KEYS = (
    "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
    "OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
)
_SIMULATED_DESKTOP_PROVIDER_ALLOW_KEYS = (
    "allow_simulated_desktop_provider",
    "desktop_provider_allow_simulated_execution",
    "allow_loopback_desktop_provider_execution",
    "desktop_allow_loopback_provider_execution",
)
_SIMULATED_DESKTOP_PROVIDER_ENV_ALLOW_KEYS = (
    "OHA_YACHIYO_ALLOW_SIMULATED_DESKTOP_PROVIDER",
    "OHA_YACHIYO_DESKTOP_PROVIDER_ALLOW_SIMULATED_EXECUTION",
    "OHA_YACHIYO_ALLOW_LOOPBACK_DESKTOP_PROVIDER_EXECUTION",
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
KEYBOARD_MOUSE_CAPTURE_TOOL_NAMES = (
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
    "desktop.close_window",
    "desktop.quit_app",
)
LOCAL_DESKTOP_PROVIDER_REQUIRES_SANDBOX_TOOLS = KEYBOARD_MOUSE_CAPTURE_TOOL_NAMES


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
        adapter = self._matching_adapter(
            clean_provider_kind,
            tool_name,
            route,
            tool_request,
        )
        if adapter is not None:
            return adapter
        env_adapter = self._refresh_env_adapter(clean_provider_kind)
        if env_adapter is not None:
            return self._matching_adapter(
                clean_provider_kind,
                tool_name,
                route,
                tool_request,
            )
        return None

    def _matching_adapter(
        self,
        provider_kind: str,
        tool_name: str,
        route: Mapping[str, Any],
        tool_request: Mapping[str, Any],
    ) -> DesktopExecutionProviderAdapter | None:
        for adapter in self._adapters.get(provider_kind, []):
            can_execute = getattr(adapter, "can_execute", None)
            if callable(can_execute) and not can_execute(tool_name, route, tool_request):
                continue
            return adapter
        return None

    def _refresh_env_adapter(
        self,
        provider_kind: str,
    ) -> DesktopExecutionProviderAdapter | None:
        if provider_kind != "sandbox_desktop":
            return None
        adapter = _http_desktop_execution_provider_adapter_from_env()
        if adapter is None:
            return None
        if self._has_equivalent_adapter(provider_kind, adapter):
            return adapter
        self.register(adapter)
        return adapter

    def _has_equivalent_adapter(
        self,
        provider_kind: str,
        adapter: DesktopExecutionProviderAdapter,
    ) -> bool:
        provider_id = str(getattr(adapter, "provider_id", "") or "").strip()
        execute_url = str(getattr(adapter, "execute_url", "") or "").strip()
        for existing in self._adapters.get(provider_kind, []):
            existing_provider_id = str(
                getattr(existing, "provider_id", "") or ""
            ).strip()
            existing_execute_url = str(
                getattr(existing, "execute_url", "") or ""
            ).strip()
            if provider_id and provider_id != existing_provider_id:
                continue
            if execute_url and execute_url != existing_execute_url:
                continue
            if provider_id or execute_url:
                return True
        return False

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
        simulated_blockers = _simulated_desktop_provider_blockers(
            route,
            tool_request,
        )
        if simulated_blockers and not _simulated_desktop_provider_execution_allowed(
            route,
            tool_request,
        ):
            return desktop_execution_provider_simulated_backend_result(
                tool_name,
                route=route,
                tool_request=tool_request,
                blocking_conditions=simulated_blockers,
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
        foreground_mutation_supported: bool | None = None,
        keyboard_mouse_capture_supported: bool | None = None,
        requires_real_sandbox_for: Iterable[str] | None = None,
        desktop_session_kind: str = "",
        desktop_session_isolated: bool | None = None,
        foreground_takeover_required: bool | None = None,
        desktop_backend_kind: str = "",
        desktop_backend_is_loopback: bool | None = None,
        desktop_backend_ready_for_public_release: bool | None = None,
        requires_real_virtual_desktop_backend: bool | None = None,
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
        self.foreground_mutation_supported = foreground_mutation_supported
        self.keyboard_mouse_capture_supported = keyboard_mouse_capture_supported
        self.requires_real_sandbox_for = _string_list(requires_real_sandbox_for)
        self.desktop_session_kind = str(desktop_session_kind or "").strip()
        self.desktop_session_isolated = desktop_session_isolated
        self.foreground_takeover_required = foreground_takeover_required
        self.desktop_backend_kind = str(desktop_backend_kind or "").strip()
        self.desktop_backend_is_loopback = desktop_backend_is_loopback
        self.desktop_backend_ready_for_public_release = (
            desktop_backend_ready_for_public_release
        )
        self.requires_real_virtual_desktop_backend = (
            requires_real_virtual_desktop_backend
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
        capabilities = _string_list(provider_payload.get("capabilities"))
        foreground_mutation_supported = _provider_capability_bool(
            provider_payload,
            capabilities=capabilities,
            true_tokens=(
                "foreground_mutation",
                "foreground_control",
                "sandbox_foreground",
                "app_launch",
                "app_control",
            ),
            false_tokens=("no_foreground_mutation", "read_only_observation"),
            keys=(
                "foreground_mutation_supported",
                "foreground_mutation_tools_supported",
            ),
        )
        keyboard_mouse_capture_supported = _provider_capability_bool(
            provider_payload,
            capabilities=capabilities,
            true_tokens=(
                "keyboard_mouse_capture",
                "foreground_input",
                "desktop_control",
                "sandbox_control",
            ),
            false_tokens=(
                "no_keyboard_mouse_capture",
            ),
            keys=(
                "keyboard_mouse_capture_supported",
                "input_capture_supported",
            ),
        )
        desktop_session_kind = _provider_session_kind(provider_payload)
        desktop_session_isolated = _provider_capability_bool(
            provider_payload,
            capabilities=capabilities,
            true_tokens=(
                "isolated_desktop",
                "sandbox_desktop_session",
                "virtual_desktop",
            ),
            false_tokens=("user_foreground", "foreground_takeover"),
            keys=("desktop_session_isolated", "session_isolated"),
        )
        foreground_takeover_required = _provider_capability_bool(
            provider_payload,
            capabilities=capabilities,
            true_tokens=("user_foreground", "foreground_takeover"),
            false_tokens=(
                "isolated_desktop",
                "sandbox_desktop_session",
                "virtual_desktop",
            ),
            keys=(
                "foreground_takeover_required",
                "user_foreground_takeover_required",
            ),
        )
        backend_status = _provider_backend_status_fields(
            desktop_backend_kind=_first_mapping_value(
                provider_payload,
                "desktop_backend_kind",
                "backend_kind",
            ),
            desktop_backend_is_loopback=_optional_bool_value(
                _first_mapping_value(
                    provider_payload,
                    "desktop_backend_is_loopback",
                    "backend_is_loopback",
                )
            ),
            desktop_backend_ready_for_public_release=_optional_bool_value(
                _first_mapping_value(
                    provider_payload,
                    "desktop_backend_ready_for_public_release",
                    "backend_ready_for_public_release",
                )
            ),
            requires_real_virtual_desktop_backend=_optional_bool_value(
                _first_mapping_value(
                    provider_payload,
                    "requires_real_virtual_desktop_backend",
                    "real_virtual_desktop_backend_required",
                )
            ),
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
            capabilities=capabilities,
            foreground_mutation_supported=foreground_mutation_supported,
            keyboard_mouse_capture_supported=keyboard_mouse_capture_supported,
            requires_real_sandbox_for=_provider_requires_real_sandbox_for(
                provider_payload,
            ),
            desktop_session_kind=desktop_session_kind,
            desktop_session_isolated=desktop_session_isolated,
            foreground_takeover_required=foreground_takeover_required,
            **backend_status,
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
            foreground_mutation_supported=self.foreground_mutation_supported,
            keyboard_mouse_capture_supported=self.keyboard_mouse_capture_supported,
            requires_real_sandbox_for=self.requires_real_sandbox_for,
            desktop_session_kind=self.desktop_session_kind,
            desktop_session_isolated=self.desktop_session_isolated,
            foreground_takeover_required=self.foreground_takeover_required,
            desktop_backend_kind=self.desktop_backend_kind,
            desktop_backend_is_loopback=self.desktop_backend_is_loopback,
            desktop_backend_ready_for_public_release=(
                self.desktop_backend_ready_for_public_release
            ),
            requires_real_virtual_desktop_backend=(
                self.requires_real_virtual_desktop_backend
            ),
        )
        supported_tools = _string_list(health.get("supported_tools")) or self.supported_tools
        keyboard_mouse_capture_supported = _coalesce_optional_bool(
            health.get("keyboard_mouse_capture_supported"),
            self.keyboard_mouse_capture_supported,
        )
        if keyboard_mouse_capture_supported is None and _supports_keyboard_mouse_tool(
            supported_tools
        ):
            keyboard_mouse_capture_supported = True
        foreground_mutation_supported = _coalesce_optional_bool(
            health.get("foreground_mutation_supported"),
            self.foreground_mutation_supported,
        )
        if foreground_mutation_supported is None and keyboard_mouse_capture_supported:
            foreground_mutation_supported = True
        requires_real_sandbox_for = (
            _string_list(health.get("requires_real_sandbox_for"))
            or self.requires_real_sandbox_for
        )
        desktop_session_kind = (
            str(health.get("desktop_session_kind") or "").strip()
            or self.desktop_session_kind
        )
        desktop_session_isolated = _coalesce_optional_bool(
            health.get("desktop_session_isolated"),
            self.desktop_session_isolated,
        )
        foreground_takeover_required = _coalesce_optional_bool(
            health.get("foreground_takeover_required"),
            self.foreground_takeover_required,
        )
        backend_status = _provider_backend_status_fields(
            desktop_backend_kind=health.get("desktop_backend_kind")
            or self.desktop_backend_kind,
            desktop_backend_is_loopback=_optional_bool_value(
                health.get("desktop_backend_is_loopback")
            )
            if "desktop_backend_is_loopback" in health
            else self.desktop_backend_is_loopback,
            desktop_backend_ready_for_public_release=_optional_bool_value(
                health.get("desktop_backend_ready_for_public_release")
            )
            if "desktop_backend_ready_for_public_release" in health
            else self.desktop_backend_ready_for_public_release,
            requires_real_virtual_desktop_backend=_optional_bool_value(
                health.get("requires_real_virtual_desktop_backend")
            )
            if "requires_real_virtual_desktop_backend" in health
            else self.requires_real_virtual_desktop_backend,
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
            "supported_tools": supported_tools,
            "health": health,
            "endpoint_origin": _url_origin(urlparse(self.execute_url)),
            "endpoint_path": urlparse(self.execute_url).path or _DEFAULT_EXECUTE_PATH,
            "status_endpoint_path": urlparse(self.status_url).path or _DEFAULT_STATUS_PATH,
            "source": "runtime_env",
            **_provider_capability_status_fields(
                foreground_mutation_supported=foreground_mutation_supported,
                keyboard_mouse_capture_supported=keyboard_mouse_capture_supported,
                requires_real_sandbox_for=requires_real_sandbox_for,
                desktop_session_kind=desktop_session_kind,
                desktop_session_isolated=desktop_session_isolated,
                foreground_takeover_required=foreground_takeover_required,
            ),
            **backend_status,
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
        foreground_mutation_supported: bool | None = None,
        keyboard_mouse_capture_supported: bool | None = None,
        requires_real_sandbox_for: Iterable[str] | None = None,
        desktop_session_kind: str = "",
        desktop_session_isolated: bool | None = None,
        foreground_takeover_required: bool | None = None,
        desktop_backend_kind: Any = "",
        desktop_backend_is_loopback: bool | None = None,
        desktop_backend_ready_for_public_release: bool | None = None,
        requires_real_virtual_desktop_backend: bool | None = None,
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
            **_provider_capability_status_fields(
                foreground_mutation_supported=foreground_mutation_supported,
                keyboard_mouse_capture_supported=keyboard_mouse_capture_supported,
                requires_real_sandbox_for=requires_real_sandbox_for,
                desktop_session_kind=desktop_session_kind,
                desktop_session_isolated=desktop_session_isolated,
                foreground_takeover_required=foreground_takeover_required,
            ),
            **_provider_backend_status_fields(
                desktop_backend_kind=desktop_backend_kind,
                desktop_backend_is_loopback=desktop_backend_is_loopback,
                desktop_backend_ready_for_public_release=(
                    desktop_backend_ready_for_public_release
                ),
                requires_real_virtual_desktop_backend=(
                    requires_real_virtual_desktop_backend
                ),
            ),
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
            "desktop_session_kind": "user_foreground",
            "desktop_session_isolated": False,
            "foreground_takeover_required": True,
        },
        "source": "runtime_local",
        "foreground_mutation_supported": True,
        "keyboard_mouse_capture_supported": False,
        "desktop_session_kind": "user_foreground",
        "desktop_session_isolated": False,
        "foreground_takeover_required": True,
        "requires_real_sandbox_for": list(LOCAL_DESKTOP_PROVIDER_REQUIRES_SANDBOX_TOOLS),
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
    if provider_kind == LOCAL_DESKTOP_PROVIDER_KIND and not bool(
        route.get("sandbox_required")
    ):
        return False
    if bool(route.get("provider_execution_required")):
        return True
    if provider_kind == "sandbox_desktop":
        return True
    if bool(route.get("sandbox_required")):
        return True
    if str(route.get("status") or "").strip() in {"provider_ready", "sandbox_ready"}:
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
            "recommended_tools": ["desktop.provider_session.start"],
            "recovery_actions": _provider_unavailable_recovery_actions(
                tool_name,
                route=route,
                tool_request=tool_request,
            ),
        },
        tool_name=tool_name,
        route=route,
        tool_request=tool_request,
        adapter_registered=False,
    )


def desktop_execution_provider_simulated_backend_result(
    tool_name: str,
    *,
    route: Mapping[str, Any],
    tool_request: Mapping[str, Any],
    blocking_conditions: Iterable[str],
) -> dict[str, Any]:
    blockers = _unique_strings(blocking_conditions) or ["loopback_desktop_backend"]
    return _with_desktop_provider_context(
        {
            "ok": False,
            "tool": tool_name,
            "action": tool_name,
            "status": "real_virtual_desktop_provider_required",
            "error": "desktop_execution_provider_simulated_backend",
            "summary": (
                "Desktop provider execution was blocked because the selected "
                "provider reports a loopback or simulated backend."
            ),
            "blocked_by_desktop_execution_provider": True,
            "simulated_desktop_provider": True,
            "requires_real_virtual_desktop_backend": True,
            "blocking_condition": blockers[0],
            "blocking_conditions": blockers,
            "hint": (
                "Configure a real isolated virtual desktop provider before routing "
                "desktop app operations through this path."
            ),
            "recommended_tools": ["desktop.provider_session.start"],
            "recovery_actions": _real_virtual_provider_recovery_actions(
                tool_name,
                route=route,
                tool_request=tool_request,
                blocking_conditions=blockers,
            ),
        },
        tool_name=tool_name,
        route=route,
        tool_request=tool_request,
        adapter_registered=True,
    )


def _provider_unavailable_recovery_actions(
    tool_name: str,
    *,
    route: Mapping[str, Any],
    tool_request: Mapping[str, Any],
) -> list[dict[str, Any]]:
    clean_tool = str(tool_name or "").strip()
    if not clean_tool:
        return []
    sandbox_provider = sandbox_provider_payload(tool_request)
    provider_id = (
        str(route.get("selected_provider_id") or "").strip()
        or str(sandbox_provider.get("provider_id") or "").strip()
        or "local-isolated-desktop"
    )
    raw_input = (
        tool_request.get("input") if isinstance(tool_request.get("input"), Mapping) else {}
    )
    desktop_policy = (
        dict(tool_request.get("desktop_execution_policy"))
        if isinstance(tool_request.get("desktop_execution_policy"), Mapping)
        else {"mode": "sandbox_preferred"}
    )
    deferred_request = {
        "tool": clean_tool,
        "input": dict(raw_input),
        "desktop_execution_policy": {
            **desktop_policy,
            "mode": str(desktop_policy.get("mode") or "sandbox_preferred"),
            "prefer_isolated_desktop": True,
            "avoid_user_foreground_takeover": True,
            "source": "desktop_execution_provider_unavailable_recovery",
        },
        "planning_reason": "desktop_execution_provider_retry_after_session_start",
        "source": "desktop_execution_provider_unavailable_recovery",
    }
    for key in (
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "step_id",
        "planner_step_id",
        "capability_id",
        "target_capability_id",
        "runtime_stage",
        "runtime_role",
    ):
        value = str(tool_request.get(key) or "").strip()
        if value:
            deferred_request[key] = value
    return [
        {
            "label": "Start isolated desktop provider",
            "tool": "desktop.provider_session.start",
            "input": {
                "provider_id": provider_id,
                "tools": [clean_tool],
                "tool_names": [clean_tool],
                "reason": "desktop_execution_provider_unavailable",
                "diagnostic_route": "/yachiyo/studio/tools",
                "api_route": "/yachiyo/studio/tools/desktop-provider/session/start",
            },
            "permission_target": "isolated_desktop_provider",
            "risk_level": "medium",
            "approval_required": True,
            "approval_status": "pending",
            "planning_reason": "desktop_execution_provider_unavailable_recovery",
            "recovery_action_kind": "desktop_provider_session_start",
            "deferred_tool": clean_tool,
            "deferred_input": dict(raw_input),
            "deferred_continuation": [deferred_request],
            "metadata": {
                "runtime_retry_source": "desktop_provider_session",
                "runtime_replan_auto_start_eligible": False,
                "runtime_replan_auto_start_reason": "desktop_provider_session_start_requires_approval",
                "runtime_replan_auto_start_blockers": [
                    "approval_required",
                    "desktop_execution_provider_unavailable",
                ],
                "desktop_execution_route": dict(route),
                "sandbox_provider": dict(sandbox_provider),
                "sandbox_original_tool": clean_tool,
                "sandbox_original_input": dict(raw_input),
            },
        }
    ]


def _real_virtual_provider_recovery_actions(
    tool_name: str,
    *,
    route: Mapping[str, Any],
    tool_request: Mapping[str, Any],
    blocking_conditions: Iterable[str],
) -> list[dict[str, Any]]:
    clean_tool = str(tool_name or "").strip()
    if not clean_tool:
        return []
    sandbox_provider = sandbox_provider_payload(tool_request)
    provider_id = (
        str(route.get("selected_provider_id") or "").strip()
        or str(sandbox_provider.get("provider_id") or "").strip()
        or "real-virtual-desktop"
    )
    blockers = _unique_strings(blocking_conditions)
    raw_input = (
        tool_request.get("input") if isinstance(tool_request.get("input"), Mapping) else {}
    )
    desktop_policy = (
        dict(tool_request.get("desktop_execution_policy"))
        if isinstance(tool_request.get("desktop_execution_policy"), Mapping)
        else {"mode": "sandbox_preferred"}
    )
    deferred_request = {
        "tool": clean_tool,
        "input": dict(raw_input),
        "desktop_execution_policy": {
            **desktop_policy,
            "mode": str(desktop_policy.get("mode") or "sandbox_preferred"),
            "prefer_isolated_desktop": True,
            "avoid_user_foreground_takeover": True,
            "require_sandbox_for_keyboard_mouse": True,
            "source": "real_virtual_desktop_provider_recovery",
        },
        "planning_reason": "real_virtual_desktop_provider_retry_after_start",
        "source": "real_virtual_desktop_provider_recovery",
    }
    for key in (
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "step_id",
        "planner_step_id",
        "capability_id",
        "target_capability_id",
        "runtime_stage",
        "runtime_role",
    ):
        value = str(tool_request.get(key) or "").strip()
        if value:
            deferred_request[key] = value
    return [
        {
            "label": "Start real virtual desktop provider",
            "tool": "desktop.provider_session.start",
            "input": {
                "provider_id": provider_id,
                "tools": [clean_tool],
                "tool_names": [clean_tool],
                "requires_real_virtual_desktop_backend": True,
                "reason": "real_virtual_desktop_provider_required",
                "diagnostic_route": "/yachiyo/studio/tools",
                "api_route": "/yachiyo/studio/tools/desktop-provider/session/start",
            },
            "permission_target": "real_virtual_desktop_provider",
            "risk_level": "medium",
            "approval_required": True,
            "approval_status": "pending",
            "planning_reason": "real_virtual_desktop_provider_recovery",
            "recovery_action_kind": "desktop_provider_session_start",
            "deferred_tool": clean_tool,
            "deferred_input": dict(raw_input),
            "deferred_continuation": [deferred_request],
            "metadata": {
                "runtime_retry_source": "desktop_provider_session",
                "requires_real_virtual_desktop_backend": True,
                "runtime_replan_auto_start_eligible": False,
                "runtime_replan_auto_start_reason": "real_virtual_desktop_provider_requires_approval",
                "runtime_replan_auto_start_blockers": [
                    "approval_required",
                    *blockers,
                ],
                "desktop_execution_route": dict(route),
                "sandbox_provider": dict(sandbox_provider),
                "sandbox_original_tool": clean_tool,
                "sandbox_original_input": dict(raw_input),
            },
        }
    ]


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


def _simulated_desktop_provider_blockers(
    route: Mapping[str, Any],
    tool_request: Mapping[str, Any],
) -> list[str]:
    blockers: list[str] = []
    for source in (
        route,
        sandbox_provider_payload(tool_request),
        _mapping(tool_request.get("desktop_provider_session")),
    ):
        if not source:
            continue
        backend_kind = str(source.get("desktop_backend_kind") or "").strip()
        if backend_kind == "loopback_session_harness":
            blockers.append("loopback_desktop_backend")
        if _optional_bool_value(source.get("desktop_backend_is_loopback")) is True:
            blockers.append("loopback_desktop_backend")
        if (
            _optional_bool_value(source.get("requires_real_virtual_desktop_backend"))
            is True
        ):
            blockers.append("real_virtual_desktop_backend_required")
    return _unique_strings(blockers)


def _simulated_desktop_provider_execution_allowed(
    route: Mapping[str, Any],
    tool_request: Mapping[str, Any],
) -> bool:
    if _mapping_truthy(route, *_SIMULATED_DESKTOP_PROVIDER_ALLOW_KEYS):
        return True
    if _mapping_truthy(tool_request, *_SIMULATED_DESKTOP_PROVIDER_ALLOW_KEYS):
        return True
    metadata = tool_request.get("metadata")
    if isinstance(metadata, Mapping) and _mapping_truthy(
        metadata,
        *_SIMULATED_DESKTOP_PROVIDER_ALLOW_KEYS,
    ):
        return True
    sandbox_provider = sandbox_provider_payload(tool_request)
    if _mapping_truthy(sandbox_provider, *_SIMULATED_DESKTOP_PROVIDER_ALLOW_KEYS):
        return True
    env = os.environ
    return any(
        _truthy_env_value(env, key)
        for key in _SIMULATED_DESKTOP_PROVIDER_ENV_ALLOW_KEYS
    )


def _route_provider_kind(route: Mapping[str, Any]) -> str:
    return _clean_provider_kind(
        route.get("selected_provider_kind") or route.get("provider_kind")
    )


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
        foreground_mutation_supported=_optional_bool_env_value(
            env,
            _PROVIDER_FOREGROUND_MUTATION_ENV_KEYS,
        ),
        keyboard_mouse_capture_supported=_optional_bool_env_value(
            env,
            _PROVIDER_KEYBOARD_MOUSE_ENV_KEYS,
        ),
        requires_real_sandbox_for=_string_list(
            _first_env_value(env, _PROVIDER_REQUIRES_REAL_SANDBOX_ENV_KEYS)
        ),
        desktop_session_kind=_first_env_value(env, _PROVIDER_SESSION_KIND_ENV_KEYS),
        desktop_session_isolated=_optional_bool_env_value(
            env,
            _PROVIDER_SESSION_ISOLATED_ENV_KEYS,
        ),
        foreground_takeover_required=_optional_bool_env_value(
            env,
            _PROVIDER_FOREGROUND_TAKEOVER_ENV_KEYS,
        ),
        desktop_backend_kind=_first_env_value(env, _PROVIDER_BACKEND_KIND_ENV_KEYS),
        desktop_backend_is_loopback=_optional_bool_env_value(
            env,
            _PROVIDER_BACKEND_LOOPBACK_ENV_KEYS,
        ),
        desktop_backend_ready_for_public_release=_optional_bool_env_value(
            env,
            _PROVIDER_BACKEND_RELEASE_READY_ENV_KEYS,
        ),
        requires_real_virtual_desktop_backend=_optional_bool_env_value(
            env,
            _PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_ENV_KEYS,
        ),
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


def _provider_capability_status_fields(
    *,
    foreground_mutation_supported: bool | None = None,
    keyboard_mouse_capture_supported: bool | None = None,
    requires_real_sandbox_for: Iterable[str] | None = None,
    desktop_session_kind: str = "",
    desktop_session_isolated: bool | None = None,
    foreground_takeover_required: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if foreground_mutation_supported is not None:
        payload["foreground_mutation_supported"] = bool(foreground_mutation_supported)
    if keyboard_mouse_capture_supported is not None:
        payload["keyboard_mouse_capture_supported"] = bool(
            keyboard_mouse_capture_supported
        )
    sandbox_required_tools = _string_list(requires_real_sandbox_for)
    if sandbox_required_tools:
        payload["requires_real_sandbox_for"] = sandbox_required_tools
    clean_session_kind = str(desktop_session_kind or "").strip()
    if clean_session_kind:
        payload["desktop_session_kind"] = clean_session_kind
    if desktop_session_isolated is not None:
        payload["desktop_session_isolated"] = bool(desktop_session_isolated)
    if foreground_takeover_required is not None:
        payload["foreground_takeover_required"] = bool(foreground_takeover_required)
    return payload


def _provider_backend_status_fields(
    *,
    desktop_backend_kind: Any = "",
    desktop_backend_is_loopback: bool | None = None,
    desktop_backend_ready_for_public_release: bool | None = None,
    requires_real_virtual_desktop_backend: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    clean_backend_kind = str(desktop_backend_kind or "").strip()
    if clean_backend_kind:
        payload["desktop_backend_kind"] = clean_backend_kind
    if desktop_backend_is_loopback is not None:
        payload["desktop_backend_is_loopback"] = bool(desktop_backend_is_loopback)
    if desktop_backend_ready_for_public_release is not None:
        payload["desktop_backend_ready_for_public_release"] = bool(
            desktop_backend_ready_for_public_release
        )
    if requires_real_virtual_desktop_backend is not None:
        payload["requires_real_virtual_desktop_backend"] = bool(
            requires_real_virtual_desktop_backend
        )
    return payload


def _first_mapping_value(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _provider_capability_bool(
    provider_payload: Mapping[str, Any],
    *,
    capabilities: Iterable[str],
    true_tokens: Iterable[str],
    false_tokens: Iterable[str],
    keys: Iterable[str],
) -> bool | None:
    for key in keys:
        direct = _optional_bool_value(provider_payload.get(key))
        if direct is not None:
            return direct
    safety = provider_payload.get("safety")
    if isinstance(safety, Mapping):
        for key in keys:
            nested = _optional_bool_value(safety.get(key))
            if nested is not None:
                return nested
    capability_set = {
        str(capability or "").strip().lower()
        for capability in capabilities
        if str(capability or "").strip()
    }
    if any(token in capability_set for token in true_tokens):
        return True
    if any(token in capability_set for token in false_tokens):
        return False
    return None


def _provider_requires_real_sandbox_for(
    provider_payload: Mapping[str, Any],
) -> list[str]:
    direct = _string_list(provider_payload.get("requires_real_sandbox_for"))
    if direct:
        return direct
    safety = provider_payload.get("safety")
    if isinstance(safety, Mapping):
        return _string_list(safety.get("requires_real_sandbox_for"))
    return []


def _provider_session_kind(provider_payload: Mapping[str, Any]) -> str:
    for key in ("desktop_session_kind", "session_kind"):
        value = str(provider_payload.get(key) or "").strip()
        if value:
            return value
    safety = provider_payload.get("safety")
    if isinstance(safety, Mapping):
        for key in ("desktop_session_kind", "session_kind"):
            value = str(safety.get(key) or "").strip()
            if value:
                return value
    return ""


def _coalesce_optional_bool(*values: Any) -> bool | None:
    for value in values:
        parsed = _optional_bool_value(value)
        if parsed is not None:
            return parsed
    return None


def _optional_bool_env_value(
    env: Mapping[str, str],
    keys: Iterable[str],
) -> bool | None:
    for key in keys:
        if key in env and str(env.get(key) or "").strip():
            return _optional_bool_value(env.get(key))
    return None


def _optional_bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in {"1", "true", "yes", "on", "supported", "ready"}:
            return True
        if clean in {"0", "false", "no", "off", "unsupported", "blocked"}:
            return False
    return None


def _supports_keyboard_mouse_tool(tools: Iterable[str]) -> bool:
    capture_tools = set(KEYBOARD_MOUSE_CAPTURE_TOOL_NAMES)
    return any(str(tool or "").strip() in capture_tools for tool in tools)


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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_truthy(mapping: Mapping[str, Any] | None, *keys: str) -> bool:
    if not isinstance(mapping, Mapping):
        return False
    for key in keys:
        value = mapping.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return True
    nested = mapping.get("metadata")
    if isinstance(nested, Mapping) and nested is not mapping:
        return _mapping_truthy(nested, *keys)
    return False


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, Iterable) and not isinstance(
        value,
        (bytes, bytearray, Mapping),
    ):
        raw_items = value
    else:
        raw_items = []
    items: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in items:
            items.append(text)
    return items


def _unique_strings(values: Iterable[Any]) -> list[str]:
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
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
