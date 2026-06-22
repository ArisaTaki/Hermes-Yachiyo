"""Tests for approval and artifact repositories split out of agent_runtime."""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.runtime.events import redact_json_value


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _public_pending_approval(value: Any) -> dict[str, Any]:
    pending = value if isinstance(value, dict) else {}
    return {
        "approval_id": str(pending.get("approval_id") or ""),
        "tool": str(pending.get("tool") or ""),
        "input_preview": pending.get("input_preview") if isinstance(pending, dict) else {},
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def test_projection_repositories_remain_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.ApprovalRepository is ApprovalRepository
    assert agent_runtime.RunArtifactRepository is RunArtifactRepository


def test_approval_repository_claims_and_resolves_pending_approvals() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE run_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            tool TEXT NOT NULL DEFAULT '',
            input_preview_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL DEFAULT '{}',
            requested_at TEXT NOT NULL,
            resolved_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    now_values = iter(
        [
            "2026-06-14T10:00:00Z",
            "2026-06-14T10:00:01Z",
            "2026-06-14T10:00:02Z",
            "2026-06-14T10:00:03Z",
            "2026-06-14T10:00:04Z",
            "2026-06-14T10:00:05Z",
            "2026-06-14T10:00:06Z",
        ],
    )
    repo = ApprovalRepository(
        conn,
        threading.RLock(),
        now=lambda: next(now_values),
        json_dump=_json_dump,
        public_pending_approval=_public_pending_approval,
    )

    pending = {
        "approval_id": "approval-1",
        "tool": "terminal.run",
        "input_preview": {"command": "echo ok"},
    }
    repo.sync("run-1", status="approval_required", pending_approval=pending)
    conn.commit()
    row = conn.execute(
        "SELECT * FROM run_approvals WHERE approval_id=?",
        ("approval-1",),
    ).fetchone()
    assert row["status"] == "pending"
    assert _json_load(row["input_preview_json"], {}) == {"command": "echo ok"}

    assert repo.claim_pending_approval("run-1", pending) is True
    assert repo.claim_pending_approval("run-1", pending) is False
    row = conn.execute(
        "SELECT * FROM run_approvals WHERE approval_id=?",
        ("approval-1",),
    ).fetchone()
    assert row["status"] == "approved"

    repo.sync(
        "run-2",
        status="approval_required",
        pending_approval={**pending, "approval_id": "approval-2"},
    )
    repo.sync("run-2", status="cancelled", pending_approval={})
    row = conn.execute(
        "SELECT * FROM run_approvals WHERE approval_id=?",
        ("approval-2",),
    ).fetchone()
    assert row["status"] == "cancelled"


def test_artifact_repository_sync_read_and_delete_files(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE run_artifacts (
            artifact_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            source_run_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    agent_root = tmp_path / "agent"
    workflow_root = tmp_path / "workflow"
    run_dir = agent_root / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text("hello secret", encoding="utf-8")
    screenshot_bytes = b"\x89PNG\r\n\x1a\nfake-screenshot"
    screenshot_dir = run_dir / "screenshots"
    screenshot_dir.mkdir()
    (screenshot_dir / "current-screen.png").write_bytes(screenshot_bytes)

    repo = RunArtifactRepository(
        conn,
        agent_artifacts_dir=agent_root,
        workflow_artifacts_dir=workflow_root,
        get_run=lambda run_id: {"run_id": run_id, "kind": "agent_run"},
        now=lambda: "2026-06-14T10:00:00Z",
        json_dump=_json_dump,
        redact_json_value=redact_json_value,
        redact_secrets=lambda value: str(value).replace("secret", "[redacted]"),
        safe_rel_path=lambda value: str(value).strip(),
        is_within=_is_within,
        read_text=lambda path, limit: Path(path).read_text(encoding="utf-8")[:limit],
    )

    secret = "sk-artifact-secret123456"
    repo.sync("run-1", [{"kind": "report", "path": "report.md", "api_key": secret}])
    row = conn.execute("SELECT * FROM run_artifacts WHERE run_id=?", ("run-1",)).fetchone()
    assert row["artifact_id"] == "run-1:artifact:0"
    assert row["kind"] == "report"
    assert secret not in row["payload_json"]

    preview = repo.read("run-1", "report.md")
    assert preview["content"] == "hello [redacted]"
    assert preview["truncated"] is False

    screenshot_preview = repo.read("run-1", "screenshots/current-screen.png")
    assert screenshot_preview["mime_type"] == "image/png"
    assert screenshot_preview["content"].startswith("data:image/png;base64,")
    encoded_screenshot = screenshot_preview["content"].split(",", 1)[1]
    assert base64.b64decode(encoded_screenshot) == screenshot_bytes
    assert screenshot_preview["truncated"] is False

    repo.delete_files({"run_id": "run-1", "kind": "agent_run"})
    assert not run_dir.exists()
