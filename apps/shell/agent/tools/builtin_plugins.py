"""Built-in restricted tool-only plugins.

These plugins are an allowlisted Phase 10 install source. They do not load
third-party code or bypass ToolBroker registration, policy, timeline, or
approval gates.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.plugins import (
    RestrictedPluginInstallState,
    RestrictedPluginTool,
    RestrictedToolPlugin,
)


def builtin_restricted_tool_plugin(plugin_id: str) -> RestrictedToolPlugin:
    clean_plugin_id = str(plugin_id or "").strip().lower()
    factory = _BUILTIN_PLUGIN_FACTORIES.get(clean_plugin_id)
    if factory is None:
        raise AgentRuntimeError(f"未知受限工具插件：{plugin_id}")
    return factory()


def list_builtin_restricted_tool_plugin_ids() -> list[str]:
    return sorted(_BUILTIN_PLUGIN_FACTORIES)


def restricted_tool_plugin_payload(
    plugin: RestrictedToolPlugin,
    *,
    enabled: bool,
) -> dict[str, Any]:
    plugin_id = str(plugin.plugin_id or "").strip().lower()
    tools = [
        {
            "tool_name": _plugin_tool_name(plugin_id, str(tool.tool_id or "").strip().lower()),
            "tool_id": str(tool.tool_id or "").strip().lower(),
            "function_name": _function_name(plugin_id, str(tool.tool_id or "").strip().lower()),
            "risk_level": tool.risk_level,
            "enabled": enabled,
        }
        for tool in plugin.tools
    ]
    return {
        "plugin_id": plugin_id,
        "enabled": enabled,
        "tool_names": [tool["tool_name"] for tool in tools],
        "tools": tools,
        "skill_docs": str(plugin.skill_docs or ""),
        "source": "restricted_tool_plugin",
    }


def restricted_tool_plugin_state_payload(
    state: RestrictedPluginInstallState | Mapping[str, Any],
) -> dict[str, Any]:
    plugin_id = str(_field_value(state, "plugin_id") or "").strip().lower()
    enabled = bool(_field_value(state, "enabled"))
    skill_docs = str(_field_value(state, "skill_docs") or "")
    tool_names = [
        str(tool_name or "").strip()
        for tool_name in (_field_value(state, "tool_names") or ())
        if str(tool_name or "").strip()
    ]
    try:
        plugin = builtin_restricted_tool_plugin(plugin_id)
    except AgentRuntimeError:
        return {
            "plugin_id": plugin_id,
            "enabled": enabled,
            "tool_names": tool_names,
            "tools": [],
            "skill_docs": skill_docs,
            "source": "restricted_tool_plugin",
        }

    payload = restricted_tool_plugin_payload(plugin, enabled=enabled)
    if tool_names:
        payload["tool_names"] = tool_names
    if skill_docs:
        payload["skill_docs"] = skill_docs
    return payload


def _notes_echo(payload: Mapping[str, Any], _context: Any) -> Mapping[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise AgentRuntimeError("notes.echo 需要 text")
    return {
        "ok": True,
        "action": "notes.echo",
        "summary": f"Echoed {len(text)} characters through a restricted plugin.",
        "text": text,
        "data": {"text": text},
    }


def _notes_plugin() -> RestrictedToolPlugin:
    return RestrictedToolPlugin(
        plugin_id="notes",
        tools=(
            RestrictedPluginTool(
                tool_id="echo",
                description="Echo text through the built-in restricted notes plugin.",
                properties={"text": {"type": "string"}},
                required=("text",),
                risk_level="medium",
                execute=_notes_echo,
            ),
        ),
        skill_docs=(
            "Use notes.echo for restricted plugin smoke tests and short "
            "Agent Desk note round-trips."
        ),
    )


def _function_name(plugin_id: str, tool_id: str) -> str:
    return f"plugin_{plugin_id.replace('-', '_')}_{tool_id.replace('-', '_')}"


def _plugin_tool_name(plugin_id: str, tool_id: str) -> str:
    return f"plugin.{plugin_id}.{tool_id}"


def _field_value(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name)
    return getattr(value, field_name, None)


_BUILTIN_PLUGIN_FACTORIES = {
    "notes": _notes_plugin,
}


__all__ = [
    "builtin_restricted_tool_plugin",
    "list_builtin_restricted_tool_plugin_ids",
    "restricted_tool_plugin_payload",
    "restricted_tool_plugin_state_payload",
]
