"""Tests for tool descriptor and policy gate code split out of agent_runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.policy import (
    MEMORY_KINDS,
    MEMORY_SCOPES,
    TOOL_DESCRIPTORS,
    TOOL_FUNCTION_NAMES,
    TOOL_NAME_ALIASES,
    PolicyGate,
    ToolDescriptor,
    ToolDescriptorRegistry,
)


def test_tool_policy_classes_and_constants_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.ToolDescriptor is ToolDescriptor
    assert agent_runtime.ToolDescriptorRegistry is ToolDescriptorRegistry
    assert agent_runtime.PolicyGate is PolicyGate
    assert agent_runtime.TOOL_DESCRIPTORS is TOOL_DESCRIPTORS
    assert agent_runtime._TOOL_FUNCTION_NAMES is TOOL_FUNCTION_NAMES
    assert agent_runtime._TOOL_NAME_ALIASES is TOOL_NAME_ALIASES
    assert agent_runtime._MEMORY_SCOPES is MEMORY_SCOPES
    assert agent_runtime._MEMORY_KINDS is MEMORY_KINDS


def test_model_tool_schema_uses_function_aliases_and_strict_parameters() -> None:
    schemas = ToolDescriptorRegistry.model_tool_schemas(
        ["workspace.read", "workspace.write_patch", "unknown.tool"]
    )

    function_names = [schema["function"]["name"] for schema in schemas]
    assert function_names == ["workspace_read", "workspace_write_patch"]
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["parameters"]["additionalProperties"] is False

    write_patch = schemas[1]["function"]["parameters"]
    assert write_patch["required"] == ["path"]
    assert set(write_patch["properties"]) == {
        "path",
        "patch",
        "expected_sha256",
        "base_sha256",
    }


def test_tool_payload_validation_rejects_unknown_and_undeclared_fields() -> None:
    with pytest.raises(AgentRuntimeError):
        ToolDescriptorRegistry.validate_payload("unknown.tool", {})

    with pytest.raises(AgentRuntimeError, match="undeclared|未声明"):
        ToolDescriptorRegistry.validate_payload(
            "workspace.read",
            {"path": "README.md", "extra": "nope"},
        )


def test_write_patch_payload_validation_requires_patch_and_matching_hash_aliases() -> None:
    with pytest.raises(AgentRuntimeError, match="patch"):
        ToolDescriptorRegistry.validate_payload("workspace.write_patch", {"path": "a.txt"})

    valid_hash = "a" * 64
    ToolDescriptorRegistry.validate_payload(
        "workspace.write_patch",
        {"path": "a.txt", "patch": "--- a\n+++ b\n", "expected_sha256": valid_hash},
    )

    with pytest.raises(AgentRuntimeError, match="64"):
        ToolDescriptorRegistry.validate_payload(
            "workspace.write_patch",
            {"path": "a.txt", "patch": "--- a\n+++ b\n", "expected_sha256": "bad"},
        )

    with pytest.raises(AgentRuntimeError, match="expected_sha256"):
        ToolDescriptorRegistry.validate_payload(
            "workspace.write_patch",
            {
                "path": "a.txt",
                "patch": "--- a\n+++ b\n",
                "expected_sha256": valid_hash,
                "base_sha256": "b" * 64,
            },
        )


def test_memory_payload_validation_rejects_invalid_scope_and_kind() -> None:
    with pytest.raises(AgentRuntimeError, match="scope"):
        ToolDescriptorRegistry.validate_payload(
            "memory.add",
            {"content": "remember this", "scope": "team"},
        )

    with pytest.raises(AgentRuntimeError, match="kind"):
        ToolDescriptorRegistry.validate_payload(
            "memory.add",
            {"content": "remember this", "kind": "credential"},
        )


def test_policy_gate_normalizes_allowed_tool_entries() -> None:
    assert PolicyGate.allows_tool("terminal.run", [" workspace.read ", "terminal.run"])
    assert not PolicyGate.allows_tool("terminal.run", ["workspace.read"])


def test_tool_payload_validation_rejects_sensitive_values_before_persistence() -> None:
    with pytest.raises(AgentRuntimeError, match="sensitive|敏感"):
        ToolDescriptorRegistry.validate_payload(
            "artifact.write",
            {
                "path": "notes.md",
                "content": "OPENAI_API_KEY=sk-testsecret123456",
            },
        )
