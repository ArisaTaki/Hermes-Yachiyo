"""Trusted capability lookup for runtime tool decisions."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.policy import TOOL_DESCRIPTORS
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY
from apps.shell.yachiyo_agent.capability_registry import CAPABILITY_DEFINITIONS


@dataclass(frozen=True)
class ToolCapabilityBinding:
    """Explicit execution authority granted to one registered tool adapter."""

    tool_name: str
    capability_ids: tuple[str, ...]
    action_ids: tuple[str, ...] = ()


_REGISTERED_TOOL_CAPABILITY_BINDINGS: dict[str, ToolCapabilityBinding] = {}


def _canonical_tool_names(tool_names: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(name for value in tool_names if (name := str(value or "").strip())))


def _canonical_ids(values: Iterable[str] | str) -> tuple[str, ...]:
    source = (values,) if isinstance(values, str) else values
    return tuple(
        dict.fromkeys(
            clean
            for value in source
            if (clean := str(value or "").strip())
        )
    )


def _registered_tool_adapter_exists(tool_name: str) -> bool:
    return tool_name in TOOL_DESCRIPTORS and tool_name in TOOL_DISPATCH_REGISTRY


def register_tool_capability_binding(
    tool_name: str,
    *,
    capability_ids: Iterable[str] | str,
    action_ids: Iterable[str] | str = (),
) -> ToolCapabilityBinding:
    """Grant explicit capability authority to an already registered adapter.

    A schema and dispatch handler are prerequisites, so a name or dynamic
    prefix alone can never become execution authority. Action IDs are optional,
    but every declared action must belong to one of the named capabilities.
    """

    canonical_tool = str(tool_name or "").strip()
    if not canonical_tool:
        raise AgentRuntimeError("工具名不能为空")
    if not _registered_tool_adapter_exists(canonical_tool):
        raise AgentRuntimeError(
            f"工具能力绑定需要已注册的 schema 和 dispatch：{canonical_tool}"
        )
    if canonical_tool in _REGISTERED_TOOL_CAPABILITY_BINDINGS:
        raise AgentRuntimeError(f"工具能力已绑定：{canonical_tool}")

    clean_capability_ids = _canonical_ids(capability_ids)
    if not clean_capability_ids:
        raise AgentRuntimeError("工具能力绑定至少需要一个 capability_id")
    definitions = {
        definition.capability_id: definition
        for definition in CAPABILITY_DEFINITIONS
    }
    unknown_capability_ids = tuple(
        capability_id
        for capability_id in clean_capability_ids
        if capability_id not in definitions
    )
    if unknown_capability_ids:
        raise AgentRuntimeError(
            "未知 capability_id：" + ", ".join(unknown_capability_ids)
        )

    clean_action_ids = _canonical_ids(action_ids)
    allowed_action_ids = frozenset(
        action_id
        for capability_id in clean_capability_ids
        for action_id in (
            *definitions[capability_id].discovery_actions,
            *definitions[capability_id].execution_actions,
        )
    )
    invalid_action_ids = tuple(
        action_id
        for action_id in clean_action_ids
        if action_id not in allowed_action_ids
    )
    if invalid_action_ids:
        raise AgentRuntimeError(
            "action_id 未由所绑定的 capability 声明："
            + ", ".join(invalid_action_ids)
        )

    binding = ToolCapabilityBinding(
        tool_name=canonical_tool,
        capability_ids=clean_capability_ids,
        action_ids=clean_action_ids,
    )
    _REGISTERED_TOOL_CAPABILITY_BINDINGS[canonical_tool] = binding
    return binding


def unregister_tool_capability_binding(
    tool_name: str,
) -> ToolCapabilityBinding | None:
    """Revoke a tool's explicit runtime capability authority."""

    return _REGISTERED_TOOL_CAPABILITY_BINDINGS.pop(
        str(tool_name or "").strip(),
        None,
    )


def clear_registered_tool_capability_bindings() -> tuple[ToolCapabilityBinding, ...]:
    """Revoke all explicit bindings and return an immutable snapshot."""

    removed = tuple(_REGISTERED_TOOL_CAPABILITY_BINDINGS.values())
    _REGISTERED_TOOL_CAPABILITY_BINDINGS.clear()
    return removed


def capability_ids_for_tool(tool_name: str) -> tuple[str, ...]:
    """Return explicitly declared capabilities for a registered tool adapter.

    Dynamic prefix classification in the planner registry is intentionally not
    an execution authority. A tool must have a concrete schema, dispatch
    handler, and an explicit membership in a capability definition before it
    can satisfy a recovery plan.
    """

    canonical_tool = str(tool_name or "").strip()
    if not canonical_tool or not _registered_tool_adapter_exists(canonical_tool):
        return ()
    static_capability_ids = tuple(
        definition.capability_id
        for definition in CAPABILITY_DEFINITIONS
        if canonical_tool in definition.tools
    )
    binding = _REGISTERED_TOOL_CAPABILITY_BINDINGS.get(canonical_tool)
    return tuple(
        dict.fromkeys(
            (
                *static_capability_ids,
                *(binding.capability_ids if binding is not None else ()),
            )
        )
    )


def action_ids_for_tool(tool_name: str) -> tuple[str, ...]:
    """Return explicitly bound action IDs for an available tool adapter."""

    canonical_tool = str(tool_name or "").strip()
    if not canonical_tool or not _registered_tool_adapter_exists(canonical_tool):
        return ()
    binding = _REGISTERED_TOOL_CAPABILITY_BINDINGS.get(canonical_tool)
    return binding.action_ids if binding is not None else ()


def registered_tool_names_for_capability(capability_id: str) -> tuple[str, ...]:
    """Return available explicitly-bound adapters for one capability."""

    clean_capability_id = str(capability_id or "").strip()
    if not clean_capability_id:
        return ()
    return tuple(
        sorted(
            tool_name
            for tool_name, binding in _REGISTERED_TOOL_CAPABILITY_BINDINGS.items()
            if clean_capability_id in binding.capability_ids
            and _registered_tool_adapter_exists(tool_name)
        )
    )


def available_capability_ids(tool_names: Iterable[str]) -> frozenset[str]:
    """Return capabilities backed by at least one currently allowed adapter."""

    return frozenset(
        capability_id
        for tool_name in _canonical_tool_names(tool_names)
        for capability_id in capability_ids_for_tool(tool_name)
    )


def known_capability_ids() -> frozenset[str]:
    """Return every capability declared by the trusted registry."""

    return frozenset(definition.capability_id for definition in CAPABILITY_DEFINITIONS)


__all__ = [
    "ToolCapabilityBinding",
    "action_ids_for_tool",
    "available_capability_ids",
    "capability_ids_for_tool",
    "clear_registered_tool_capability_bindings",
    "known_capability_ids",
    "register_tool_capability_binding",
    "registered_tool_names_for_capability",
    "unregister_tool_capability_binding",
]
