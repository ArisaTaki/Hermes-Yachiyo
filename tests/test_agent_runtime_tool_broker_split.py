"""Tests for ToolBroker split out of the legacy agent_runtime module."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.tools import broker as broker_module
from apps.shell.agent.tools import terminal as terminal_module
from apps.shell.agent.tools import workspace as workspace_module
from apps.shell.agent.tools.broker import ToolBroker, cancel_terminal_process_groups


def test_tool_broker_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.ToolBroker is ToolBroker
    assert agent_runtime.cancel_terminal_process_groups is cancel_terminal_process_groups
    assert agent_runtime._TERMINAL_PROCESSES is terminal_module._TERMINAL_PROCESSES
    assert agent_runtime._TERMINAL_PROCESS_LOCK is terminal_module._TERMINAL_PROCESS_LOCK
    assert broker_module._TERMINAL_PROCESSES is terminal_module._TERMINAL_PROCESSES
    assert agent_runtime._safe_rel_path is workspace_module._safe_rel_path
    assert agent_runtime._is_within is workspace_module._is_within
    assert agent_runtime._read_text is workspace_module._read_text
    assert agent_runtime._sha256_file is workspace_module._sha256_file
    assert agent_runtime._atomic_write_text is workspace_module._atomic_write_text
    assert agent_runtime._apply_single_file_unified_diff is (
        workspace_module._apply_single_file_unified_diff
    )
    assert broker_module._safe_rel_path is workspace_module._safe_rel_path
    assert broker_module._apply_single_file_unified_diff is (
        workspace_module._apply_single_file_unified_diff
    )


def test_tool_broker_payload_approved_field_cannot_bypass_terminal_approval(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "repo"
    workdir.mkdir()
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    result = broker.call("terminal.run", {"command": "echo no", "approved": True})

    assert result["approval_required"] is True
    assert result["tool"] == "terminal.run"


def test_tool_broker_write_patch_keeps_workspace_scope_and_hash_reporting(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "repo"
    workdir.mkdir()
    target = workdir / "note.txt"
    target.write_text("hello\n", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    approval = broker.workspace_write_patch(
        "note.txt",
        patch="--- note.txt\n+++ note.txt\n@@ -1 +1 @@\n-hello\n+hi\n",
    )
    result = broker.workspace_write_patch(
        "note.txt",
        patch="--- note.txt\n+++ note.txt\n@@ -1 +1 @@\n-hello\n+hi\n",
        approved=True,
    )

    assert approval == {
        "ok": False,
        "approval_required": True,
        "tool": "workspace.write_patch",
    }
    assert result["ok"] is True
    assert result["mode"] == "patch"
    assert result["sha256_before"] != result["sha256_after"]
    assert target.read_text(encoding="utf-8") == "hi\n"


def test_tool_broker_artifact_write_redacts_secrets(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    broker = ToolBroker({}, artifact_root)

    result = broker.artifact_write(
        "reports/secret.md",
        "api_key=sk-toolbrokersecret123456\nsafe",
    )

    artifact_path = artifact_root / "reports" / "secret.md"
    content = artifact_path.read_text(encoding="utf-8")
    assert result["ok"] is True
    assert "sk-toolbrokersecret123456" not in content
    assert "api_key=[redacted]" in content
