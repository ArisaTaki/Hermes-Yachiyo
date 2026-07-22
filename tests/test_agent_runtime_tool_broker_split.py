"""Tests for ToolBroker split out of the legacy agent_runtime module."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.tools import broker as broker_module
from apps.shell.agent.tools import terminal as terminal_module
from apps.shell.agent.tools import workspace as workspace_module
from apps.shell.agent.tools.broker import ToolBroker, cancel_terminal_process_groups
from apps.shell.agent.tools.foreground_lock import ForegroundActionLock


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


def test_tool_broker_mints_exact_app_lifecycle_receipts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    broker = ToolBroker({}, tmp_path / "artifacts")
    monkeypatch.setattr(
        broker_module.desktop,
        "app_show",
        lambda app_name: {
            "ok": True,
            "action": "app.show",
            "data": {"app_name": app_name, "show_status": "shown"},
        },
    )
    monkeypatch.setattr(
        broker_module.desktop,
        "app_hide",
        lambda app_name: {
            "ok": True,
            "action": "app.hide",
            "data": {"app_name": app_name, "hide_status": "hidden"},
        },
    )
    monkeypatch.setattr(
        broker_module.desktop,
        "app_minimize",
        lambda app_name: {
            "ok": True,
            "action": "app.minimize",
            "data": {
                "app_name": app_name,
                "minimize_status": "minimized",
                "window_count": 1,
            },
        },
    )

    for result in (
        broker.app_show("Slack"),
        broker.app_hide("Slack"),
        broker.app_minimize("Slack"),
    ):
        assert result["postcondition_verified"] is True
        assert result["data"]["postcondition_verified"] is True


def test_tool_broker_rejects_mismatched_app_lifecycle_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    broker = ToolBroker({}, tmp_path / "artifacts")
    monkeypatch.setattr(
        broker_module.desktop,
        "app_show",
        lambda _app_name: {
            "ok": True,
            "action": "app.show",
            "data": {"app_name": "Discord", "show_status": "shown"},
        },
    )

    result = broker.app_show("Slack")

    assert "postcondition_verified" not in result
    assert "postcondition_verified" not in result["data"]


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


def test_tool_broker_policy_map_cannot_preapprove_terminal_run(
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
        approvals={"terminal.run": True},
    )

    result = broker.call("terminal.run", {"command": "echo no"})

    assert result["approval_required"] is True
    assert result["tool"] == "terminal.run"


def test_tool_broker_policy_approval_blocks_foreground_tool_until_approved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": []},
        tmp_path / "artifacts",
        approvals={"desktop.type_text": True},
    )
    monkeypatch.setattr(
        broker_module.desktop,
        "desktop_type_text",
        lambda text: calls.append(text) or {"ok": True, "text": text},
    )

    approval = broker.call("desktop.type_text", {"text": "hello"})
    approved = broker.call("desktop.type_text", {"text": "hello"}, approved=True)

    assert approval == {
        "ok": False,
        "approval_required": True,
        "tool": "desktop.type_text",
        "policy_reason": "当前工具策略要求人工确认后再执行。",
    }
    assert approved == {"ok": True, "text": "hello"}
    assert calls == ["hello"]


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
    assert result["postcondition_verified"] is True
    assert result["mode"] == "patch"
    assert result["sha256_before"] != result["sha256_after"]
    assert target.read_text(encoding="utf-8") == "hi\n"


def test_tool_broker_workspace_list_filters_files_by_pattern_and_type(tmp_path: Path) -> None:
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "Screen Shot 1.png").write_text("png", encoding="utf-8")
    (workdir / "receipt.pdf").write_text("pdf", encoding="utf-8")
    (workdir / "sales.csv").write_text("region,revenue\nEast,10\n", encoding="utf-8")
    (workdir / "notes.txt").write_text("text", encoding="utf-8")
    (workdir / "nested").mkdir()
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        },
        tmp_path / "artifacts",
    )

    screenshots = broker.workspace_list(
        ".",
        pattern="*.{png,jpg,jpeg,heic,gif,webp}",
        file_type="screenshot",
    )
    invoices = broker.workspace_list(".", file_type="invoice")
    csv_files = broker.workspace_list(".", file_type="csv")
    structured_data = broker.workspace_list(
        ".",
        pattern="*.{csv,tsv,xlsx,json,jsonl}",
    )

    assert screenshots["ok"] is True
    assert screenshots["entries"] == [{"name": "Screen Shot 1.png", "type": "file"}]
    assert screenshots["filter"] == {
        "pattern": "*.{png,jpg,jpeg,heic,gif,webp}",
        "file_type": "screenshot",
        "expanded_patterns": ["*.png", "*.jpg", "*.jpeg", "*.heic", "*.gif", "*.webp"],
    }
    assert screenshots["matched_count"] == 1
    assert screenshots["total_entries"] == 5
    assert invoices["entries"] == [{"name": "receipt.pdf", "type": "file"}]
    assert invoices["filter"]["file_type"] == "invoice"
    assert csv_files["entries"] == [{"name": "sales.csv", "type": "file"}]
    assert csv_files["filter"]["expanded_patterns"] == ["*.csv"]
    assert structured_data["entries"] == [{"name": "sales.csv", "type": "file"}]
    assert structured_data["filter"]["expanded_patterns"] == [
        "*.csv",
        "*.tsv",
        "*.xlsx",
        "*.json",
        "*.jsonl",
    ]


def test_tool_broker_file_organize_requires_approval_and_moves_matching_files(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "home"
    downloads = workdir / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "june-invoice.pdf").write_text("invoice", encoding="utf-8")
    (downloads / "notes.txt").write_text("notes", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["Downloads"],
        },
        tmp_path / "artifacts",
        approvals={"file.organize": True},
    )

    approval = broker.call(
        "file.organize",
        {
            "path": "Downloads",
            "operation": "organize",
            "file_type": "invoice",
            "destination": "Invoices",
        },
    )

    assert approval["approval_required"] is True
    assert approval["tool"] == "file.organize"
    assert (downloads / "june-invoice.pdf").exists()
    assert not (downloads / "Invoices").exists()
    result = broker.call(
        "file.organize",
        {
            "path": "Downloads",
            "operation": "organize",
            "file_type": "invoice",
            "destination": "Invoices",
        },
        approved=True,
    )
    assert result["ok"] is True
    assert result["moved"] == [
        {
            "from": "Downloads/june-invoice.pdf",
            "to": "Downloads/Invoices/june-invoice.pdf",
        }
    ]
    assert result["matched_count"] == 1
    assert result["moved_count"] == 1
    assert (downloads / "Invoices" / "june-invoice.pdf").exists()
    assert (downloads / "notes.txt").exists()


def test_tool_broker_file_organize_rejects_paths_outside_writable_scope(
    tmp_path: Path,
) -> None:
    workdir = tmp_path / "home"
    downloads = workdir / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "june-invoice.pdf").write_text("invoice", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["Documents"],
        },
        tmp_path / "artifacts",
    )

    try:
        broker.file_organize("Downloads", operation="organize", approved=True)
    except Exception as exc:
        assert "工作区范围" in str(exc)
    else:
        raise AssertionError("file_organize should reject source outside writable scopes")
    assert (downloads / "june-invoice.pdf").exists()


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
    assert result["postcondition_verified"] is True
    assert "sk-toolbrokersecret123456" not in content
    assert "api_key=[redacted]" in content


def test_tool_broker_foreground_lock_blocks_concurrent_foreground_actions(
    tmp_path: Path,
) -> None:
    foreground_lock = ForegroundActionLock()
    first_broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": []},
        tmp_path / "artifacts-1",
        foreground_lock=foreground_lock,
        foreground_lock_owner="group-run-1:run-1",
    )
    second_broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": []},
        tmp_path / "artifacts-2",
        foreground_lock=foreground_lock,
        foreground_lock_owner="group-run-1:run-2",
    )
    lease = foreground_lock.acquire(
        holder=first_broker.foreground_lock_owner,
        tool_name="desktop.type_text",
    )
    try:
        result = second_broker.desktop_type_text("hello")
    finally:
        lease.release()

    assert result == {
        "ok": False,
        "tool": "desktop.type_text",
        "action": "foreground_lock",
        "foreground_lock_busy": True,
        "locked_by": "group-run-1:run-1",
        "summary": "Foreground desktop action is already locked by another run.",
    }


def test_tool_broker_foreground_lock_releases_after_action(tmp_path: Path, monkeypatch) -> None:
    foreground_lock = ForegroundActionLock()
    broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": []},
        tmp_path / "artifacts",
        foreground_lock=foreground_lock,
        foreground_lock_owner="workflow-run-1:node-a",
    )
    monkeypatch.setattr(
        broker_module.desktop,
        "desktop_type_text",
        lambda text: {"ok": True, "text": text},
    )

    result = broker.call("desktop.type_text", {"text": "hello"})
    next_lease = foreground_lock.acquire(
        holder="workflow-run-1:node-b",
        tool_name="desktop.hotkey",
    )
    try:
        assert result == {
            "ok": True,
            "text": "hello",
            "foreground_lock": {
                "holder": "workflow-run-1:node-a",
                "tool": "desktop.type_text",
            },
        }
        assert next_lease.acquired is True
        assert foreground_lock.owner == "workflow-run-1:node-b"
    finally:
        next_lease.release()


def test_tool_broker_desktop_click_uses_foreground_lock(tmp_path: Path, monkeypatch) -> None:
    foreground_lock = ForegroundActionLock()
    broker = ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": []},
        tmp_path / "artifacts",
        foreground_lock=foreground_lock,
        foreground_lock_owner="group-run-1:run-1",
    )
    monkeypatch.setattr(
        broker_module.desktop,
        "desktop_click",
        lambda x, y, *, click_count=1: {
            "ok": True,
            "data": {"x": x, "y": y, "click_count": click_count},
        },
    )

    result = broker.call("desktop.click", {"x": 12, "y": 34, "click_count": 2})
    next_lease = foreground_lock.acquire(
        holder="group-run-1:run-2",
        tool_name="desktop.type_text",
    )
    try:
        assert result == {
            "ok": True,
            "data": {"x": 12, "y": 34, "click_count": 2},
            "foreground_lock": {
                "holder": "group-run-1:run-1",
                "tool": "desktop.click",
            },
        }
        assert next_lease.acquired is True
    finally:
        next_lease.release()
