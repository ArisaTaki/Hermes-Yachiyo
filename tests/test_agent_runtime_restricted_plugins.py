"""Native runtime coverage for restricted tool-only plugins."""

from __future__ import annotations

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.plugins import clear_restricted_tool_plugins
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY, dispatch_tool_call
from apps.shell.agent_runtime import NativeRunEngine
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort
from apps.shell.yachiyo_agent.studio_service import AgentStudioService


@pytest.fixture(autouse=True)
def _clear_plugin_tools():
    clear_restricted_tool_plugins()
    yield
    clear_restricted_tool_plugins()


def test_native_runtime_installs_restricted_plugin_through_studio_port(tmp_path) -> None:
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    service = AgentStudioService(LegacyStudioPort(runtime))
    tool_name = "plugin.notes.echo"
    try:
        installed = service.install_restricted_tool_plugin(
            {"plugin_id": "notes", "enabled": False}
        )
        catalog_after_disabled_install = service.list_tool_catalog()

        assert installed.plugin_id == "notes"
        assert installed.enabled is False
        assert installed.tool_names == [tool_name]
        assert installed.tools[0].risk_level == "medium"
        assert tool_name not in TOOL_DISPATCH_REGISTRY
        assert tool_name not in {
            tool.tool_name for tool in catalog_after_disabled_install.tools
        }
        assert catalog_after_disabled_install.plugins[0].tools[0].tool_name == tool_name
        assert catalog_after_disabled_install.plugins[0].enabled is False

        enabled = service.update_restricted_tool_plugin("notes", {"enabled": True})
        catalog_after_enable = service.list_tool_catalog()

        assert enabled.enabled is True
        assert tool_name in TOOL_DISPATCH_REGISTRY
        assert tool_name in {tool.tool_name for tool in catalog_after_enable.tools}
        assert catalog_after_enable.plugins[0].tools[0].enabled is True

        broker = ToolBroker(
            {"default_workdir": str(tmp_path)},
            tmp_path / "artifacts",
        )
        result = dispatch_tool_call(
            broker,
            tool_name,
            {"text": "Desk note"},
            approved=False,
        )
        assert result["ok"] is True
        assert result["tool"] == tool_name
        assert result["plugin_id"] == "notes"
        assert result["risk_level"] == "medium"
        assert result["text"] == "Desk note"

        disabled = service.update_restricted_tool_plugin("notes", {"enabled": False})
        assert disabled.enabled is False
        assert tool_name not in TOOL_DISPATCH_REGISTRY

        removed = service.uninstall_restricted_tool_plugin("notes")
        assert removed.plugin_id == "notes"
        assert removed.enabled is False
        assert service.list_restricted_tool_plugins() == []
        assert tool_name not in {
            tool.tool_name for tool in service.list_tool_catalog().tools
        }
    finally:
        runtime.close()


def test_native_runtime_rejects_unknown_restricted_plugin(tmp_path) -> None:
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    service = AgentStudioService(LegacyStudioPort(runtime))
    try:
        with pytest.raises(AgentRuntimeError):
            service.install_restricted_tool_plugin({"plugin_id": "unknown"})
    finally:
        runtime.close()


def test_native_runtime_close_unregisters_restricted_plugins(tmp_path) -> None:
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    tool_name = "plugin.notes.echo"

    runtime.install_restricted_tool_plugin({"plugin_id": "notes", "enabled": True})
    assert tool_name in TOOL_DISPATCH_REGISTRY

    runtime.close()

    assert tool_name not in TOOL_DISPATCH_REGISTRY
