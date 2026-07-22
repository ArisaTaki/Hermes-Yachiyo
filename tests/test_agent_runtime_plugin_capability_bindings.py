"""Fail-closed capability authority for restricted plugin tools."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_capabilities import (
    action_ids_for_tool,
    available_capability_ids,
    capability_ids_for_tool,
    clear_registered_tool_capability_bindings,
    register_tool_capability_binding,
    registered_tool_names_for_capability,
    unregister_tool_capability_binding,
)
from apps.shell.agent.tools.plugins import (
    RestrictedPluginTool,
    RestrictedToolPlugin,
    RestrictedToolPluginManager,
    clear_restricted_tool_plugins,
    register_restricted_tool_plugin,
    unregister_restricted_tool_plugin,
)
from apps.shell.agent.tools.policy import (
    KNOWN_AGENT_TOOLS,
    TOOL_DESCRIPTORS,
    TOOL_FUNCTION_NAMES,
    TOOL_NAME_ALIASES,
    ToolDescriptor,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY


@pytest.fixture(autouse=True)
def _clear_plugin_capability_authority():
    clear_restricted_tool_plugins()
    clear_registered_tool_capability_bindings()
    yield
    clear_restricted_tool_plugins()
    clear_registered_tool_capability_bindings()


def _execute(payload, _context):
    return {"ok": True, "payload": dict(payload)}


def _tool(
    tool_id: str,
    *,
    capability_ids: tuple[str, ...] = (),
    action_ids: tuple[str, ...] = (),
) -> RestrictedPluginTool:
    return RestrictedPluginTool(
        tool_id=tool_id,
        description=f"Restricted {tool_id} test tool.",
        properties={},
        execute=_execute,
        capability_ids=capability_ids,
        action_ids=action_ids,
    )


def test_restricted_plugin_gets_only_explicit_capability_and_action_authority() -> None:
    tool_name = "plugin.notes.capture"

    register_restricted_tool_plugin(
        RestrictedToolPlugin(
            plugin_id="notes",
            tools=(
                _tool(
                    "capture",
                    capability_ids=("information.capture",),
                    action_ids=("create_note",),
                ),
            ),
        )
    )

    assert capability_ids_for_tool(tool_name) == ("information.capture",)
    assert action_ids_for_tool(tool_name) == ("create_note",)
    assert available_capability_ids([tool_name]) == frozenset({"information.capture"})
    assert registered_tool_names_for_capability("information.capture") == (tool_name,)
    assert isinstance(registered_tool_names_for_capability("information.capture"), tuple)

    unregister_restricted_tool_plugin("notes")

    assert capability_ids_for_tool(tool_name) == ()
    assert action_ids_for_tool(tool_name) == ()
    assert registered_tool_names_for_capability("information.capture") == ()


def test_disabled_or_uninstalled_plugin_has_no_capability_authority() -> None:
    tool_name = "plugin.notes.capture"
    manager = RestrictedToolPluginManager()
    plugin = RestrictedToolPlugin(
        plugin_id="notes",
        tools=(
            _tool(
                "capture",
                capability_ids=("information.capture",),
                action_ids=("create_note",),
            ),
        ),
    )

    assert manager.install(plugin, enabled=True).enabled is True
    assert capability_ids_for_tool(tool_name) == ("information.capture",)

    assert manager.disable("notes").enabled is False
    assert capability_ids_for_tool(tool_name) == ()
    assert registered_tool_names_for_capability("information.capture") == ()

    assert manager.enable("notes").enabled is True
    assert capability_ids_for_tool(tool_name) == ("information.capture",)

    assert manager.uninstall("notes").enabled is False
    assert capability_ids_for_tool(tool_name) == ()
    assert registered_tool_names_for_capability("information.capture") == ()


def test_default_plugin_and_dynamic_prefix_do_not_gain_implicit_authority(
    monkeypatch,
) -> None:
    register_restricted_tool_plugin(
        RestrictedToolPlugin(
            plugin_id="notes",
            tools=(_tool("echo"),),
        )
    )
    assert capability_ids_for_tool("plugin.notes.echo") == ()
    assert action_ids_for_tool("plugin.notes.echo") == ()

    prefix_only_tool = "media.dynamic_probe"
    monkeypatch.setitem(
        TOOL_DESCRIPTORS,
        prefix_only_tool,
        ToolDescriptor(
            name=prefix_only_tool,
            description="Prefix-only probe.",
            properties={},
        ),
    )
    monkeypatch.setitem(
        TOOL_DISPATCH_REGISTRY,
        prefix_only_tool,
        lambda _broker, _payload, _approved: {"ok": True},
    )

    assert capability_ids_for_tool(prefix_only_tool) == ()
    assert action_ids_for_tool(prefix_only_tool) == ()


@pytest.mark.parametrize(
    ("capability_ids", "action_ids", "message"),
    [
        (("unknown.capability",), (), "\u672a\u77e5 capability_id"),
        (("information.capture",), ("play",), "action_id"),
        ((), ("create_note",), "capability_id"),
    ],
)
def test_invalid_plugin_binding_rolls_back_every_registry_mutation(
    capability_ids,
    action_ids,
    message,
) -> None:
    first_tool = "plugin.notes.capture"
    invalid_tool = "plugin.notes.invalid"

    with pytest.raises(AgentRuntimeError, match=message):
        register_restricted_tool_plugin(
            RestrictedToolPlugin(
                plugin_id="notes",
                tools=(
                    _tool(
                        "capture",
                        capability_ids=("information.capture",),
                        action_ids=("create_note",),
                    ),
                    _tool(
                        "invalid",
                        capability_ids=capability_ids,
                        action_ids=action_ids,
                    ),
                ),
            )
        )

    for tool_name in (first_tool, invalid_tool):
        function_name = tool_name.replace(".", "_")
        assert tool_name not in TOOL_DESCRIPTORS
        assert tool_name not in TOOL_DISPATCH_REGISTRY
        assert tool_name not in KNOWN_AGENT_TOOLS
        assert tool_name not in TOOL_FUNCTION_NAMES
        assert function_name not in TOOL_NAME_ALIASES
        assert capability_ids_for_tool(tool_name) == ()
        assert action_ids_for_tool(tool_name) == ()
    assert registered_tool_names_for_capability("information.capture") == ()


def test_direct_binding_requires_schema_and_dispatch_and_returns_frozen_snapshots(
    monkeypatch,
) -> None:
    tool_name = "plugin.notes.direct"
    with pytest.raises(AgentRuntimeError, match="schema.*dispatch"):
        register_tool_capability_binding(
            tool_name,
            capability_ids=("information.capture",),
        )

    monkeypatch.setitem(
        TOOL_DESCRIPTORS,
        tool_name,
        ToolDescriptor(name=tool_name, description="Direct probe.", properties={}),
    )
    with pytest.raises(AgentRuntimeError, match="schema.*dispatch"):
        register_tool_capability_binding(
            tool_name,
            capability_ids=("information.capture",),
        )

    monkeypatch.setitem(
        TOOL_DISPATCH_REGISTRY,
        tool_name,
        lambda _broker, _payload, _approved: {"ok": True},
    )
    binding = register_tool_capability_binding(
        tool_name,
        capability_ids=("information.capture", "information.capture"),
        action_ids=("read_ui", "create_note", "read_ui"),
    )

    assert binding.capability_ids == ("information.capture",)
    assert binding.action_ids == ("read_ui", "create_note")
    with pytest.raises(FrozenInstanceError):
        binding.tool_name = "plugin.notes.changed"  # type: ignore[misc]

    removed = unregister_tool_capability_binding(tool_name)
    assert removed is binding
    assert capability_ids_for_tool(tool_name) == ()

    second = register_tool_capability_binding(
        tool_name,
        capability_ids="information.capture",
        action_ids="create_note",
    )
    cleared = clear_registered_tool_capability_bindings()
    assert cleared == (second,)
    assert isinstance(cleared, tuple)
    assert capability_ids_for_tool(tool_name) == ()


def test_static_tool_capability_membership_is_unchanged() -> None:
    assert capability_ids_for_tool("media.apple_music_play") == ("media.playback",)
    assert action_ids_for_tool("media.apple_music_play") == ()
