"""Restricted in-process plugin tools for Agent runtime.

Phase 10 deliberately supports tool-only plugins: a plugin can contribute a
schema, an execute handler, and risk metadata. Persistence, marketplace install,
and full-access plugins stay out of this boundary.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.policy import (
    HIGH_RISK_AGENT_TOOLS,
    KNOWN_AGENT_TOOLS,
    TOOL_DESCRIPTORS,
    TOOL_FUNCTION_NAMES,
    TOOL_NAME_ALIASES,
    ToolDescriptor,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY

PluginRiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class RestrictedPluginToolContext:
    tool_name: str
    plugin_id: str
    risk_level: PluginRiskLevel
    approved: bool
    workdir: Path
    artifact_root: Path
    workspace_policy: Mapping[str, Any]


PluginToolHandler = Callable[
    [Mapping[str, Any], RestrictedPluginToolContext],
    Mapping[str, Any],
]


@dataclass(frozen=True)
class RestrictedPluginTool:
    tool_id: str
    description: str
    properties: Mapping[str, Any]
    execute: PluginToolHandler
    required: tuple[str, ...] = ()
    risk_level: PluginRiskLevel = "low"


@dataclass(frozen=True)
class RestrictedToolPlugin:
    plugin_id: str
    tools: tuple[RestrictedPluginTool, ...]
    skill_docs: str = ""


@dataclass(frozen=True)
class RegisteredPluginTool:
    plugin_id: str
    tool_id: str
    name: str
    function_name: str
    risk_level: PluginRiskLevel
    execute: PluginToolHandler
    descriptor: ToolDescriptor
    skill_docs: str = ""


@dataclass
class _PluginRegistration:
    plugin_id: str
    tool_names: list[str] = field(default_factory=list)


_PLUGIN_TOOL_RISK_LEVELS: dict[str, PluginRiskLevel] = {}
_REGISTERED_PLUGIN_TOOLS: dict[str, RegisteredPluginTool] = {}
_PLUGIN_REGISTRATIONS: dict[str, _PluginRegistration] = {}


def register_restricted_tool_plugin(plugin: RestrictedToolPlugin) -> list[RegisteredPluginTool]:
    plugin_id = _validate_plugin_id(plugin.plugin_id)
    if plugin_id in _PLUGIN_REGISTRATIONS:
        raise AgentRuntimeError(f"插件已注册：{plugin_id}")
    if not plugin.tools:
        raise AgentRuntimeError("插件至少需要提供一个工具")

    registered: list[RegisteredPluginTool] = []
    try:
        for tool in plugin.tools:
            registered.append(_register_plugin_tool(plugin_id, tool, plugin.skill_docs))
    except Exception:
        for item in registered:
            _remove_plugin_tool(item.name)
        raise
    _PLUGIN_REGISTRATIONS[plugin_id] = _PluginRegistration(
        plugin_id=plugin_id,
        tool_names=[item.name for item in registered],
    )
    return registered


def unregister_restricted_tool_plugin(plugin_id: str) -> None:
    clean_plugin_id = _validate_plugin_id(plugin_id)
    registration = _PLUGIN_REGISTRATIONS.pop(clean_plugin_id, None)
    if registration is None:
        return
    for tool_name in registration.tool_names:
        _remove_plugin_tool(tool_name)


def clear_restricted_tool_plugins() -> None:
    for plugin_id in list(_PLUGIN_REGISTRATIONS):
        unregister_restricted_tool_plugin(plugin_id)


def list_restricted_plugin_tools() -> list[RegisteredPluginTool]:
    return list(_REGISTERED_PLUGIN_TOOLS.values())


def restricted_plugin_tool_risk(tool_name: str) -> PluginRiskLevel | None:
    return _PLUGIN_TOOL_RISK_LEVELS.get(str(tool_name or "").strip())


def call_restricted_plugin_tool(
    tool_name: str,
    broker: Any,
    payload: Mapping[str, Any],
    *,
    approved: bool = False,
) -> dict[str, Any]:
    registered = _REGISTERED_PLUGIN_TOOLS.get(str(tool_name or "").strip())
    if registered is None:
        raise AgentRuntimeError(f"未知插件工具：{tool_name}")
    if registered.risk_level == "high" and not approved:
        return {
            "ok": False,
            "approval_required": True,
            "tool": registered.name,
            "risk_level": registered.risk_level,
            "plugin_id": registered.plugin_id,
        }

    context = RestrictedPluginToolContext(
        tool_name=registered.name,
        plugin_id=registered.plugin_id,
        risk_level=registered.risk_level,
        approved=approved,
        workdir=broker.workdir,
        artifact_root=broker.artifact_root,
        workspace_policy=dict(getattr(broker, "workspace_policy", {}) or {}),
    )
    result = registered.execute(dict(payload), context)
    if not isinstance(result, Mapping):
        raise AgentRuntimeError(f"{registered.name} 插件工具必须返回对象")
    clean_result = dict(result)
    return {
        **clean_result,
        "ok": clean_result.get("ok") is not False,
        "tool": registered.name,
        "plugin_id": registered.plugin_id,
        "risk_level": registered.risk_level,
    }


def _register_plugin_tool(
    plugin_id: str,
    tool: RestrictedPluginTool,
    skill_docs: str,
) -> RegisteredPluginTool:
    tool_id = _validate_tool_id(tool.tool_id)
    risk_level = _validate_risk_level(tool.risk_level)
    if not callable(tool.execute):
        raise AgentRuntimeError("插件工具 execute 必须可调用")

    tool_name = f"plugin.{plugin_id}.{tool_id}"
    if tool_name in TOOL_DESCRIPTORS or tool_name in TOOL_DISPATCH_REGISTRY:
        raise AgentRuntimeError(f"工具已注册：{tool_name}")
    function_name = _function_name(plugin_id, tool_id)
    if function_name in TOOL_NAME_ALIASES:
        raise AgentRuntimeError(f"工具函数名已注册：{function_name}")

    descriptor = ToolDescriptor(
        name=tool_name,
        description=str(tool.description or "").strip() or f"Plugin tool {tool_name}",
        properties=dict(tool.properties or {}),
        required=tuple(str(item) for item in tool.required),
    )
    registered = RegisteredPluginTool(
        plugin_id=plugin_id,
        tool_id=tool_id,
        name=tool_name,
        function_name=function_name,
        risk_level=risk_level,
        execute=tool.execute,
        descriptor=descriptor,
        skill_docs=str(skill_docs or ""),
    )

    TOOL_FUNCTION_NAMES[tool_name] = function_name
    TOOL_NAME_ALIASES[function_name] = tool_name
    KNOWN_AGENT_TOOLS.add(tool_name)
    TOOL_DESCRIPTORS[tool_name] = descriptor
    TOOL_DISPATCH_REGISTRY[tool_name] = _plugin_dispatch(tool_name)
    _REGISTERED_PLUGIN_TOOLS[tool_name] = registered
    _PLUGIN_TOOL_RISK_LEVELS[tool_name] = risk_level
    if risk_level == "high":
        HIGH_RISK_AGENT_TOOLS.add(tool_name)
    return registered


def _plugin_dispatch(tool_name: str) -> Callable[[Any, dict[str, Any], bool], dict[str, Any]]:
    def dispatch(broker: Any, payload: dict[str, Any], approved: bool) -> dict[str, Any]:
        return call_restricted_plugin_tool(
            tool_name,
            broker,
            payload,
            approved=approved,
        )

    return dispatch


def _remove_plugin_tool(tool_name: str) -> None:
    registered = _REGISTERED_PLUGIN_TOOLS.pop(tool_name, None)
    if registered is None:
        return
    TOOL_DISPATCH_REGISTRY.pop(tool_name, None)
    TOOL_DESCRIPTORS.pop(tool_name, None)
    KNOWN_AGENT_TOOLS.discard(tool_name)
    HIGH_RISK_AGENT_TOOLS.discard(tool_name)
    _PLUGIN_TOOL_RISK_LEVELS.pop(tool_name, None)
    TOOL_NAME_ALIASES.pop(registered.function_name, None)
    TOOL_FUNCTION_NAMES.pop(tool_name, None)


def _validate_plugin_id(value: str) -> str:
    plugin_id = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", plugin_id):
        raise AgentRuntimeError("插件 id 必须是 2-64 位小写字母、数字、下划线或连字符")
    return plugin_id


def _validate_tool_id(value: str) -> str:
    tool_id = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", tool_id):
        raise AgentRuntimeError("插件工具 id 必须是 2-64 位小写字母、数字、下划线或连字符")
    return tool_id


def _validate_risk_level(value: str) -> PluginRiskLevel:
    risk = str(value or "low").strip().lower()
    if risk not in {"low", "medium", "high"}:
        raise AgentRuntimeError("插件工具 risk_level 必须是 low、medium 或 high")
    return risk  # type: ignore[return-value]


def _function_name(plugin_id: str, tool_id: str) -> str:
    safe_plugin_id = plugin_id.replace("-", "_")
    safe_tool_id = tool_id.replace("-", "_")
    return f"plugin_{safe_plugin_id}_{safe_tool_id}"


__all__ = [
    "PluginRiskLevel",
    "PluginToolHandler",
    "RegisteredPluginTool",
    "RestrictedPluginTool",
    "RestrictedPluginToolContext",
    "RestrictedToolPlugin",
    "call_restricted_plugin_tool",
    "clear_restricted_tool_plugins",
    "list_restricted_plugin_tools",
    "register_restricted_tool_plugin",
    "restricted_plugin_tool_risk",
    "unregister_restricted_tool_plugin",
]
