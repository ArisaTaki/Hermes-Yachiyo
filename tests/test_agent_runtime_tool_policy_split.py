"""Tests for tool descriptor and policy gate code split out of agent_runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS,
    KNOWN_AGENT_TOOLS,
    MEMORY_KINDS,
    MEMORY_SCOPES,
    MEMORY_TOOL_NAMES,
    TOOL_DESCRIPTORS,
    TOOL_FUNCTION_NAMES,
    TOOL_NAME_ALIASES,
    PolicyGate,
    RuntimePolicyCompiler,
    ToolDescriptor,
    ToolDescriptorRegistry,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_tool_policy_classes_and_constants_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.ToolDescriptor is ToolDescriptor
    assert agent_runtime.ToolDescriptorRegistry is ToolDescriptorRegistry
    assert agent_runtime.PolicyGate is PolicyGate
    assert agent_runtime.TOOL_DESCRIPTORS is TOOL_DESCRIPTORS
    assert agent_runtime._TOOL_FUNCTION_NAMES is TOOL_FUNCTION_NAMES
    assert agent_runtime._TOOL_NAME_ALIASES is TOOL_NAME_ALIASES
    assert agent_runtime._KNOWN_AGENT_TOOLS is KNOWN_AGENT_TOOLS
    assert agent_runtime._HIGH_RISK_AGENT_TOOLS is HIGH_RISK_AGENT_TOOLS
    assert agent_runtime._MEMORY_TOOL_NAMES is MEMORY_TOOL_NAMES
    assert agent_runtime._FUTURE_TASK_TOOL_NAMES is FUTURE_TASK_TOOL_NAMES
    assert agent_runtime._MEMORY_SCOPES is MEMORY_SCOPES
    assert agent_runtime._MEMORY_KINDS is MEMORY_KINDS
    assert agent_runtime.RuntimePolicyCompiler is RuntimePolicyCompiler


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


def test_runtime_policy_compiler_projects_tool_workspace_and_agent_runtime() -> None:
    compiler = RuntimePolicyCompiler()

    tool_policy = compiler.compile_tool_policy(
        "coding",
        {
            "allowed_tools": [
                " workspace.read ",
                "terminal.run",
                "terminal.run",
                "unknown.tool",
            ],
            "approval_required": {"workspace.write_patch": True, "memory.add": True},
        },
    )
    assert tool_policy == {
        "allowed_tools": ["workspace.read", "terminal.run"],
        "approval_required": {"terminal.run": True, "memory.add": True},
    }

    workspace_policy = compiler.compile_workspace_policy(
        {
            "default_workdir": " /tmp/project ",
            "readable_scopes": "., docs",
            "writable_scopes": ["", "src", None],
        }
    )
    assert workspace_policy == {
        "default_workdir": "/tmp/project",
        "readable_scopes": [".", "docs"],
        "writable_scopes": ["src"],
    }

    runtime = compiler.compile_agent_runtime(
        {
            "category": "research",
            "tool_policy": {"allowed_tools": ["workspace.read"]},
            "workspace_policy": {"readable_scopes": "notes"},
            "skill_ids": ["skill-1"],
        }
    )
    assert runtime["runtime"] == "oha_agent"
    assert runtime["tool_policy"]["allowed_tools"] == ["skill.read", "workspace.read"]
    assert runtime["workspace_policy"]["readable_scopes"] == ["notes"]
    assert runtime["progress_events"] == [
        "agent.run.started",
        "agent.runtime.compiled",
        "agent.model.response",
        "agent.tool.call",
        "agent.artifact.write",
        "agent.run.completed",
        "agent.run.failed",
    ]


def test_native_runtime_uses_split_runtime_policy_compiler(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runtime_policy, RuntimePolicyCompiler)
        assert service._compile_tool_policy(
            "custom",
            {"allowed_tools": "workspace.read"},
        ) == {
            "allowed_tools": ["workspace.read"],
            "approval_required": {},
        }
    finally:
        service.close()


def test_tool_payload_validation_rejects_sensitive_values_before_persistence() -> None:
    with pytest.raises(AgentRuntimeError, match="sensitive|敏感"):
        ToolDescriptorRegistry.validate_payload(
            "artifact.write",
            {
                "path": "notes.md",
                "content": "OPENAI_API_KEY=sk-testsecret123456",
            },
        )
