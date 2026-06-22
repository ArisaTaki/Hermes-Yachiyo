"""Runtime facade for restricted tool-only plugin installs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.tools.builtin_plugins import (
    builtin_restricted_tool_plugin,
    restricted_tool_plugin_state_payload,
)
from apps.shell.agent.tools.plugins import RestrictedToolPluginManager


class RuntimeRestrictedPluginFacadeMixin:
    """Installs allowlisted restricted tool-only plugins into ToolBroker."""

    def _install_runtime_restricted_plugins(self) -> None:
        self.restricted_tool_plugin_manager = RestrictedToolPluginManager()

    def list_restricted_tool_plugins(self) -> dict[str, Any]:
        return {
            "ok": True,
            "plugins": [
                restricted_tool_plugin_state_payload(state)
                for state in self.restricted_tool_plugin_manager.list_installed()
            ],
        }

    def install_restricted_tool_plugin(self, request: Mapping[str, Any]) -> dict[str, Any]:
        plugin_id = str(request.get("plugin_id") or "").strip()
        enabled = bool(request.get("enabled", True))
        plugin = builtin_restricted_tool_plugin(plugin_id)
        state = self.restricted_tool_plugin_manager.install(plugin, enabled=enabled)
        return restricted_tool_plugin_state_payload(state)

    def update_restricted_tool_plugin(
        self,
        plugin_id: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        if "enabled" not in request:
            return restricted_tool_plugin_state_payload(
                self.restricted_tool_plugin_manager.state(plugin_id)
            )
        if bool(request.get("enabled")):
            state = self.restricted_tool_plugin_manager.enable(plugin_id)
        else:
            state = self.restricted_tool_plugin_manager.disable(plugin_id)
        return restricted_tool_plugin_state_payload(state)

    def uninstall_restricted_tool_plugin(self, plugin_id: str) -> dict[str, Any]:
        state = self.restricted_tool_plugin_manager.uninstall(plugin_id)
        return restricted_tool_plugin_state_payload(state)

    def _shutdown_restricted_tool_plugins(self) -> None:
        manager = getattr(self, "restricted_tool_plugin_manager", None)
        if manager is None:
            return
        for state in list(manager.list_installed()):
            try:
                manager.uninstall(state.plugin_id)
            except Exception:
                continue


__all__ = ["RuntimeRestrictedPluginFacadeMixin"]
