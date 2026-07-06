"""Provider adapter boundary for routed desktop execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol


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


def default_desktop_execution_provider_registry() -> DesktopExecutionProviderRegistry:
    return DesktopExecutionProviderRegistry()


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
