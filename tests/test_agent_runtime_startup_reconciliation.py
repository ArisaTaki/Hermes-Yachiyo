"""Crash-safe startup reconciliation for persisted Agent Runtime runs."""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from apps.core.runtime import AppRuntime
from apps.shell.agent.runtime.clock import parse_iso_utc
from apps.shell.agent.runtime.runtime_instance_lock import (
    RuntimeProcessInstanceLock,
    runtime_instance_lock_path,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore

_CUTOFF = "2026-07-11T10:00:00+00:00"
_BEFORE_CUTOFF = "2026-07-11T09:00:00+00:00"


def _service(db_path: Path, workspace_dir: Path) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=db_path,
        workspace_dir=workspace_dir,
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )


def _set_run_fields(service: AgentRuntimeService, run_id: str, **fields: object) -> None:
    assignments = ", ".join(f"{name}=?" for name in fields)
    service._conn.execute(
        f"UPDATE runs SET {assignments} WHERE run_id=?",  # noqa: S608 - test-only fields
        (*fields.values(), run_id),
    )
    service._conn.commit()


@pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
def test_startup_reconciliation_is_explicit_and_terminal_runs_are_noops(
    tmp_path,
    terminal_status: str,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="terminal-agent",
            user_goal="already finished",
        )
        terminal = service._update_run(
            run["run_id"],
            status=terminal_status,
            result="done",
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            assert second_process.get_run(run["run_id"])["status"] == terminal_status

            report = second_process.reconcile_startup_runs(_CUTOFF)

            assert report["failed_run_ids"] == []
            assert second_process.get_run(run["run_id"]) == {
                **terminal,
                "created_at": _BEFORE_CUTOFF,
                "updated_at": _BEFORE_CUTOFF,
            }
            assert second_process.list_run_events(run["run_id"])["events"] == []
        finally:
            second_process.close()
    finally:
        service.close()


def test_startup_reconciliation_preserves_a_valid_pending_approval(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="approval-agent",
            user_goal="wait for the user",
        )
        pending = {
            "approval_id": "approval-valid",
            "tool": "desktop.open_app",
            "input_preview": {"app": "Notes"},
            "requested_at": _BEFORE_CUTOFF,
            "messages": [{"role": "user", "content": "Open Notes"}],
            "tool_request": {
                "tool": "desktop.open_app",
                "input": {"app": "Notes"},
            },
        }
        service._update_run(
            run["run_id"],
            status="approval_required",
            result="waiting",
            pending_approval=pending,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            report = second_process.reconcile_startup_runs(_CUTOFF)

            reconciled = second_process.get_run(run["run_id"])
            assert reconciled["status"] == "approval_required"
            assert reconciled["pending_approval"]["approval_id"] == "approval-valid"
            assert report["failed_run_ids"] == []
            assert report["preserved_approval_run_ids"] == [run["run_id"]]
            assert second_process.list_run_events(run["run_id"])["events"] == []
        finally:
            second_process.close()
    finally:
        service.close()


def test_preserved_approval_clears_stale_lease_before_resume_and_watchdog(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="approval-agent",
            user_goal="resume without inheriting the crashed executor lease",
            async_lease_generation=13,
            async_lease_owner_token="crashed-approval-owner",
            async_lease_expires_at="2026-07-11T10:30:00+00:00",
            async_lease_heartbeat_at="2026-07-11T10:20:00+00:00",
        )
        pending = {
            "approval_id": "approval-clear-stale-lease",
            "tool": "desktop.open_app",
            "input_preview": {"app": "Notes"},
            "messages": [{"role": "user", "content": "Open Notes"}],
            "tool_request": {
                "tool": "desktop.open_app",
                "input": {"app": "Notes"},
            },
        }
        service._update_run(
            run["run_id"],
            status="approval_required",
            result="waiting",
            pending_approval=pending,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        report = service.reconcile_startup_runs(
            _CUTOFF,
            observed_at="2026-07-11T10:31:00+00:00",
        )

        preserved = service.get_run(run["run_id"])
        lease = service._conn.execute(
            """
            SELECT async_lease_generation, async_lease_owner_token,
                   async_lease_expires_at, async_lease_heartbeat_at,
                   pending_approval_json, updated_at
              FROM runs
             WHERE run_id=?
            """,
            (run["run_id"],),
        ).fetchone()
        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE run_id=? AND approval_id=?",
            (run["run_id"], pending["approval_id"]),
        ).fetchone()
        assert report["preserved_approval_run_ids"] == [run["run_id"]]
        assert preserved["status"] == "approval_required"
        assert preserved["pending_approval"]["approval_id"] == pending["approval_id"]
        assert lease["async_lease_generation"] == 13
        assert lease["async_lease_owner_token"] == ""
        assert lease["async_lease_expires_at"] == ""
        assert lease["async_lease_heartbeat_at"] == ""
        assert lease["updated_at"] == _BEFORE_CUTOFF
        assert approval_row["status"] == "pending"

        private_pending = service.runs.pending_approval_private(run["run_id"])
        assert private_pending is not None
        assert service.run_approvals.claim_pending_approval(
            run["run_id"],
            private_pending,
            expected_approval_id=pending["approval_id"],
        ) is True
        resumed = service._update_run(
            run["run_id"],
            status="running",
            result="approved resume",
            pending_approval={},
            expected_status="approval_required",
            expected_approval_id=pending["approval_id"],
        )
        watchdog = service.reconcile_runtime_leases(
            "2026-07-11T12:00:00+00:00"
        )

        assert resumed is not None
        assert resumed["status"] == "running"
        assert watchdog["failed_run_ids"] == []
        assert service.get_run(run["run_id"])["status"] == "running"
    finally:
        service.close()


def test_startup_reconciliation_fails_an_invalid_pending_approval(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="approval-agent",
            user_goal="approval projection was lost",
        )
        service._update_run(
            run["run_id"],
            status="approval_required",
            result="waiting",
            pending_approval={
                "approval_id": "approval-missing-row",
                "tool": "desktop.open_app",
                "input_preview": {"app": "Notes"},
            },
        )
        service._conn.execute(
            "DELETE FROM run_approvals WHERE approval_id=?",
            ("approval-missing-row",),
        )
        service._conn.commit()
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            report = second_process.reconcile_startup_runs(_CUTOFF)

            reconciled = second_process.get_run(run["run_id"])
            assert reconciled["status"] == "failed"
            assert not reconciled["pending_approval"]
            assert report["failed_run_ids"] == [run["run_id"]]
            events = second_process.list_run_events(run["run_id"])["events"]
            assert [event["event_type"] for event in events] == [
                "run.recovery.interrupted",
                "agent.run.failed",
                "run.failed",
            ]
            assert events[0]["payload"]["reason_code"] == (
                "restart_approval_state_invalid"
            )
        finally:
            second_process.close()
    finally:
        service.close()


def test_startup_reconciliation_fails_an_already_claimed_approval(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="approval-agent",
            user_goal="approval was claimed before the crash",
        )
        service._update_run(
            run["run_id"],
            status="approval_required",
            result="waiting",
            pending_approval={
                "approval_id": "approval-claimed",
                "tool": "desktop.open_app",
                "input_preview": {"app": "Notes"},
            },
        )
        service._conn.execute(
            "UPDATE run_approvals SET status='approved' WHERE approval_id=?",
            ("approval-claimed",),
        )
        service._conn.commit()
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            second_process.reconcile_startup_runs(_CUTOFF)

            assert second_process.get_run(run["run_id"])["status"] == "failed"
            events = second_process.list_run_events(run["run_id"])["events"]
            recovery_event = next(
                event
                for event in events
                if event["event_type"] == "run.recovery.interrupted"
            )
            assert recovery_event["payload"]["reason_code"] == (
                "restart_approval_resume_interrupted"
            )
        finally:
            second_process.close()
    finally:
        service.close()


def test_startup_reconciliation_fails_a_pre_cutoff_active_run_without_a_lease(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="active-agent",
            user_goal="execution was interrupted",
        )
        service.link_task_run(
            task_id="task-startup-recovery",
            run_id=run["run_id"],
            session_id="session-startup-recovery",
        )
        service.append_run_event(
            run["run_id"],
            "agent.run.started",
            {"status": "running"},
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            report = second_process.reconcile_startup_runs(_CUTOFF)

            assert second_process.get_run(run["run_id"])["status"] == "failed"
            assert report["failed_run_ids"] == [run["run_id"]]
            events = second_process.list_run_events(run["run_id"])["events"]
            recovery_event = next(
                event
                for event in events
                if event["event_type"] == "run.recovery.interrupted"
            )
            assert recovery_event["payload"]["reason_code"] == (
                "restart_execution_interrupted"
            )
            task_link = second_process.get_task_run_link("task-startup-recovery")
            assert task_link["run_status"] == "failed"
            assert task_link["last_event_sequence"] == events[-1]["sequence"]
            assert report["terminal_tasks"]["task-startup-recovery"] == {
                "task_id": "task-startup-recovery",
                "run_id": run["run_id"],
                "session_id": "session-startup-recovery",
                "status": "failed",
                "result": second_process.get_run(run["run_id"])["result"],
                "updated_at": second_process.get_run(run["run_id"])["updated_at"],
            }
            assert second_process.get_task_run_projections(
                ["task-startup-recovery", "missing-task"],
            )["task-startup-recovery"]["status"] == "failed"
        finally:
            second_process.close()
    finally:
        service.close()


@pytest.mark.parametrize(
    ("kind", "expected_terminal_events"),
    [
        ("agent_run", ["agent.run.failed", "run.failed"]),
        ("workflow_run", ["workflow.run.failed", "workflow.failed"]),
        ("main_chat_run", ["task.failed", "run.failed"]),
    ],
)
def test_startup_reconciliation_writes_kind_specific_terminal_facts_and_cursor(
    tmp_path,
    kind: str,
    expected_terminal_events: list[str],
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind=kind,
            runnable_id=f"interrupted-{kind}",
            user_goal="recover with canonical terminal facts",
        )
        task_id = f"task-{kind}"
        service.link_task_run(
            task_id=task_id,
            run_id=run["run_id"],
            session_id="session-recovery-contract",
        )
        baseline = service.list_run_events(run["run_id"])["events"]
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        service.reconcile_startup_runs(_CUTOFF)

        events = service.list_run_events(run["run_id"])["events"]
        recovered = events[len(baseline) :]
        assert [event["event_type"] for event in recovered] == [
            "run.recovery.interrupted",
            *expected_terminal_events,
        ]
        assert recovered[0]["payload"]["reason_code"] == (
            "restart_dispatch_interrupted"
        )
        link = service.get_task_run_link(task_id)
        assert link["run_status"] == "failed"
        assert link["last_event_sequence"] == recovered[-1]["sequence"]
        if kind == "main_chat_run":
            task_failed = recovered[1]
            assert task_failed["payload"] == {
                "error": service.get_run(run["run_id"])["result"],
                "run_id": run["run_id"],
                "session_id": "session-recovery-contract",
                "status": "failed",
                "task_id": task_id,
            }
    finally:
        service.close()


@pytest.mark.parametrize(
    ("kind", "expected_terminal_events"),
    [
        ("agent_run", ["agent.run.failed", "run.failed"]),
        ("workflow_run", ["workflow.run.failed", "workflow.failed"]),
    ],
)
def test_startup_reconciliation_atomically_fails_explicit_root_run_group(
    tmp_path,
    kind: str,
    expected_terminal_events: list[str],
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title=f"Interrupted root {kind}",
            source="workflow" if kind == "workflow_run" else "agent",
        )
        run = service._insert_run(
            kind=kind,
            runnable_id=f"root-{kind}",
            user_goal="recover root group atomically",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        service.link_task_run(
            task_id=f"task-root-{kind}",
            run_id=run["run_id"],
            session_id="session-root-recovery",
        )
        baseline = service.list_run_events(run["run_id"])["events"]
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        restarted = _service(db_path, workspace_dir)
        try:
            restarted.reconcile_startup_runs(_CUTOFF)

            failed = restarted.get_run(run["run_id"])
            failed_group = restarted.get_run_group(group["run_group_id"])
            recovered = restarted.list_run_events(run["run_id"])["events"][
                len(baseline) :
            ]
            assert failed["status"] == "failed"
            assert failed_group["status"] == "failed"
            assert failed_group["summary"] == failed["result"]
            assert [event["event_type"] for event in recovered] == [
                "run.recovery.interrupted",
                *expected_terminal_events,
                "group.run.failed",
            ]
            assert recovered[-1]["payload"]["run_group_id"] == group["run_group_id"]
            assert restarted.get_task_run_link(f"task-root-{kind}")[
                "last_event_sequence"
            ] == recovered[-1]["sequence"]
        finally:
            restarted.close()
    finally:
        service.close()


def test_startup_reconciliation_does_not_project_group_run_child_as_root(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Interrupted GroupRun child",
            source="agent_group",
        )
        child = service._insert_run(
            kind="agent_run",
            runnable_id="group-member",
            user_goal="only the GroupRun owner may project the group",
            run_group_id=group["run_group_id"],
            project_root_group=False,
        )
        _set_run_fields(
            service,
            child["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        service.reconcile_startup_runs(_CUTOFF)

        assert service.get_run(child["run_id"])["status"] == "failed"
        assert service.get_run_group(group["run_group_id"])["status"] == "running"
        assert "group.run.failed" not in {
            event["event_type"]
            for event in service.list_run_events(child["run_id"])["events"]
        }
    finally:
        service.close()


@pytest.mark.parametrize("injected_event_type", ["run.failed", "group.run.failed"])
def test_startup_reconciliation_rolls_back_root_run_group_when_terminal_fact_fails(
    tmp_path,
    injected_event_type: str,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Recovery fault injection",
            source="agent",
        )
        run = service._insert_run(
            kind="agent_run",
            runnable_id="fault-injected-root",
            user_goal="rollback every recovery projection",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        service.link_task_run(
            task_id="task-recovery-fault",
            run_id=run["run_id"],
            session_id="session-recovery-fault",
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        service._conn.execute(
            f"""
            CREATE TRIGGER fail_recovery_terminal_fact
            BEFORE INSERT ON run_events
            WHEN NEW.event_type='{injected_event_type}'
            BEGIN
                SELECT RAISE(ABORT, 'injected recovery event failure');
            END
            """
        )
        service._conn.commit()
        baseline_events = service.list_run_events(run["run_id"])["events"]
        baseline_group = service.get_run_group(group["run_group_id"])

        with pytest.raises(Exception, match="injected recovery event failure"):
            service.reconcile_startup_runs(_CUTOFF)

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"]) == baseline_group
        assert service.list_run_events(run["run_id"])["events"] == baseline_events
        task_link = service.get_task_run_link("task-recovery-fault")
        assert task_link["run_status"] == "running"
        assert task_link["last_event_sequence"] == 0
    finally:
        service.close()


def test_startup_reconciliation_missing_owned_root_group_fails_closed(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(title="Missing root group", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="missing-root-group-agent",
            user_goal="do not publish a partial terminal outcome",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        service._conn.execute(
            "DELETE FROM run_groups WHERE run_group_id=?",
            (group["run_group_id"],),
        )
        service._conn.commit()

        with pytest.raises(RuntimeError, match="recovery_root_group_missing"):
            service.reconcile_startup_runs(_CUTOFF)

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_startup_reconciliation_root_missing_authoritative_membership_fails_closed(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(title="Missing root membership", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="missing-root-membership-agent",
            user_goal="do not infer root authority from the run row",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        service._conn.execute(
            "UPDATE run_groups SET child_run_ids_json='[]' WHERE run_group_id=?",
            (group["run_group_id"],),
        )
        service._conn.commit()
        baseline_group = service.get_run_group(group["run_group_id"])

        with pytest.raises(
            RuntimeError,
            match="recovery_root_group_owner_not_member",
        ):
            service.reconcile_startup_runs(_CUTOFF)

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"]) == baseline_group
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


@pytest.mark.parametrize(
    "tampered_payload",
    [
        {"status": "completed"},
        {"summary": "forged terminal summary"},
        {"child_run_ids": []},
        {
            "run_group_id": "group-unrelated",
            "group_run_id": "group-unrelated",
        },
    ],
)
def test_startup_reconciliation_conflicting_group_terminal_payload_fails_closed(
    tmp_path,
    tampered_payload: dict[str, Any],
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(title="Conflicting terminal fact", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="conflicting-terminal-agent",
            user_goal="preserve one canonical terminal fact",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        canonical_payload = {
            "run_group_id": group["run_group_id"],
            "group_run_id": group["run_group_id"],
            "status": "failed",
            "summary": (
                "应用重启后无法安全恢复此前执行；"
                "为避免重复操作，未自动重放工具，请重试。"
            ),
            "child_run_ids": [run["run_id"]],
        }
        service.append_run_event(
            run["run_id"],
            "group.run.failed",
            {**canonical_payload, **tampered_payload},
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        baseline_events = service.list_run_events(run["run_id"])["events"]
        baseline_group = service.get_run_group(group["run_group_id"])

        with pytest.raises(
            RuntimeError,
            match="recovery_root_group_terminal_event_conflict",
        ):
            service.reconcile_startup_runs(_CUTOFF)

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"]) == baseline_group
        assert service.list_run_events(run["run_id"])["events"] == baseline_events
    finally:
        service.close()


def test_startup_reconciliation_reuses_exact_group_terminal_payload(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(title="Exact terminal fact", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="exact-terminal-agent",
            user_goal="reuse only the exact terminal fact",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        recovery_summary = (
            "应用重启后无法安全恢复此前执行；"
            "为避免重复操作，未自动重放工具，请重试。"
        )
        service.append_run_event(
            run["run_id"],
            "group.run.failed",
            {
                "run_group_id": group["run_group_id"],
                "group_run_id": group["run_group_id"],
                "status": "failed",
                "summary": recovery_summary,
                "child_run_ids": [run["run_id"]],
            },
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        service.reconcile_startup_runs(_CUTOFF)

        terminal_events = [
            event
            for event in service.list_run_events(run["run_id"])["events"]
            if event["event_type"] == "group.run.failed"
        ]
        assert len(terminal_events) == 1
        assert terminal_events[0]["payload"]["summary"] == recovery_summary
        assert service.get_run(run["run_id"])["status"] == "failed"
        assert service.get_run_group(group["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_startup_reconciliation_terminal_root_group_winner_is_not_overwritten(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(title="Terminal winner", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="terminal-winner-agent",
            user_goal="preserve the existing group terminal winner",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        service._conn.execute(
            """
            UPDATE run_groups
               SET status='completed', summary='winner', updated_at=?
             WHERE run_group_id=?
            """,
            (_BEFORE_CUTOFF, group["run_group_id"]),
        )
        service._conn.commit()
        terminal_group = service.get_run_group(group["run_group_id"])

        with pytest.raises(
            RuntimeError,
            match="recovery_root_group_terminal_outcome_conflict",
        ):
            service.reconcile_startup_runs(_CUTOFF)

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"]) == terminal_group
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_startup_reconciliation_run_cas_loser_writes_no_facts_or_group_projection(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(title="CAS loser", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="cas-loser-agent",
            user_goal="a losing reconciler must publish nothing",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        service._conn.execute(
            f"""
            CREATE TRIGGER ignore_recovery_run_cas
            BEFORE UPDATE OF status ON runs
            WHEN OLD.run_id='{run["run_id"]}' AND NEW.status='failed'
            BEGIN
                SELECT RAISE(IGNORE);
            END
            """
        )
        service._conn.commit()
        baseline_group = service.get_run_group(group["run_group_id"])

        report = service.reconcile_startup_runs(_CUTOFF)

        assert report["failed_run_ids"] == []
        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"]) == baseline_group
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_startup_reconciliation_fails_and_clears_an_expired_lease_without_leaking_owner(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    owner_token = "private-owner-token-must-not-leak"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="leased-agent",
            user_goal="lease expired during a crash",
            async_lease_generation=7,
            async_lease_owner_token=owner_token,
            async_lease_expires_at="2026-07-11T10:30:00+00:00",
            async_lease_heartbeat_at="2026-07-11T10:20:00+00:00",
        )
        service.append_run_event(
            run["run_id"],
            "agent.run.started",
            {"status": "running"},
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            report = second_process.reconcile_startup_runs(
                _CUTOFF,
                observed_at="2026-07-11T10:31:00+00:00",
            )

            assert second_process.get_run(run["run_id"])["status"] == "failed"
            assert report["failed_run_ids"] == [run["run_id"]]
            lease = second_process._conn.execute(
                """
                SELECT async_lease_generation, async_lease_owner_token,
                       async_lease_expires_at, async_lease_heartbeat_at
                  FROM runs
                 WHERE run_id=?
                """,
                (run["run_id"],),
            ).fetchone()
            assert lease == {
                "async_lease_generation": 7,
                "async_lease_owner_token": "",
                "async_lease_expires_at": "",
                "async_lease_heartbeat_at": "",
            }
            event = next(
                event
                for event in second_process.list_run_events(run["run_id"])["events"]
                if event["event_type"] == "run.recovery.interrupted"
            )
            assert event["payload"]["reason_code"] == "restart_execution_lease_expired"
            assert event["payload"]["lease_generation"] == 7
            assert event["payload"]["recovered_at"] == "2026-07-11T10:31:00+00:00"
            assert "owner" not in str(event["payload"]).lower()
            assert owner_token not in str(event)
        finally:
            second_process.close()
    finally:
        service.close()


def test_startup_reconciliation_leaves_future_heartbeats_and_post_cutoff_runs_untouched(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        leased = service._insert_run(
            kind="agent_run",
            runnable_id="leased-agent",
            user_goal="heartbeat remains live",
            async_lease_generation=4,
            async_lease_owner_token="live-owner",
            async_lease_expires_at="2026-07-11T05:30:00-05:00",
            async_lease_heartbeat_at="2026-07-11T05:01:00-05:00",
        )
        _set_run_fields(
            service,
            leased["run_id"],
            created_at="2026-07-11T04:00:00-05:00",
            updated_at="2026-07-11T04:00:00-05:00",
        )
        post_cutoff = service._insert_run(
            kind="agent_run",
            runnable_id="new-agent",
            user_goal="started by the new process",
        )
        _set_run_fields(
            service,
            post_cutoff["run_id"],
            created_at="2026-07-11T05:05:00-05:00",
            updated_at="2026-07-11T05:05:00-05:00",
        )

        second_process = _service(db_path, workspace_dir)
        try:
            report = second_process.reconcile_startup_runs(_CUTOFF)

            assert second_process.get_run(leased["run_id"])["status"] == "running"
            assert second_process.get_run(post_cutoff["run_id"])["status"] == "running"
            assert report["failed_run_ids"] == []
            assert report["deferred_lease_run_ids"] == [leased["run_id"]]
            assert report["next_lease_expiry_at"] == "2026-07-11T10:30:00+00:00"
            assert second_process.list_run_events(leased["run_id"])["events"] == []
            assert second_process.list_run_events(post_cutoff["run_id"])["events"] == []
        finally:
            second_process.close()
    finally:
        service.close()


@pytest.mark.parametrize(
    ("owner_token", "expires_at", "expected_reason"),
    [
        ("owner-without-expiry", "", "restart_execution_lease_expired"),
        ("owner-with-bad-expiry", "not-an-iso-date", "restart_execution_lease_expired"),
        ("", "2026-07-11T10:30:00+00:00", "restart_dispatch_interrupted"),
    ],
)
def test_startup_reconciliation_fails_closed_for_incomplete_lease_identity(
    tmp_path,
    owner_token: str,
    expires_at: str,
    expected_reason: str,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="incomplete-lease-agent",
            user_goal="lease identity is incomplete",
            async_lease_generation=3,
            async_lease_owner_token=owner_token,
            async_lease_expires_at=expires_at,
            async_lease_heartbeat_at=_BEFORE_CUTOFF,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            second_process.reconcile_startup_runs(_CUTOFF)

            assert second_process.get_run(run["run_id"])["status"] == "failed"
            event = next(
                event
                for event in second_process.list_run_events(run["run_id"])["events"]
                if event["event_type"] == "run.recovery.interrupted"
            )
            assert event["payload"]["reason_code"] == expected_reason
        finally:
            second_process.close()
    finally:
        service.close()


def test_runtime_lease_watchdog_fails_only_expired_leased_running_runs(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        expired = service._insert_run(
            kind="agent_run",
            runnable_id="watchdog-expired",
            user_goal="expire under watchdog",
            async_lease_generation=6,
            async_lease_owner_token="expired-watchdog-owner",
            async_lease_expires_at="2026-07-11T10:59:00+00:00",
            async_lease_heartbeat_at="2026-07-11T10:58:00+00:00",
        )
        live = service._insert_run(
            kind="agent_run",
            runnable_id="watchdog-live",
            user_goal="remain live",
            async_lease_generation=7,
            async_lease_owner_token="live-watchdog-owner",
            async_lease_expires_at="2026-07-11T11:30:00+00:00",
            async_lease_heartbeat_at="2026-07-11T10:59:30+00:00",
        )
        unleased = service._insert_run(
            kind="agent_run",
            runnable_id="watchdog-unleased",
            user_goal="watchdog must ignore this run",
            async_lease_expires_at="2026-07-11T10:59:00+00:00",
        )
        service.link_task_run(
            task_id="task-watchdog-expired",
            run_id=expired["run_id"],
            session_id="session-watchdog",
        )
        service.link_task_run(
            task_id="task-watchdog-live",
            run_id=live["run_id"],
            session_id="session-watchdog",
        )

        report = service.reconcile_runtime_leases(
            "2026-07-11T11:00:00+00:00"
        )

        assert service.get_run(expired["run_id"])["status"] == "failed"
        assert service.get_run(live["run_id"])["status"] == "running"
        assert service.get_run(unleased["run_id"])["status"] == "running"
        assert report["failed_run_ids"] == [expired["run_id"]]
        assert report["deferred_lease_run_ids"] == [live["run_id"]]
        assert set(report["terminal_tasks"]) == {"task-watchdog-expired"}
        assert report["terminal_tasks"]["task-watchdog-expired"]["status"] == "failed"
        assert report["next_lease_expiry_at"] == "2026-07-11T11:30:00+00:00"
        event = next(
            event
            for event in service.list_run_events(expired["run_id"])["events"]
            if event["event_type"] == "run.recovery.interrupted"
        )
        assert event["payload"]["reason_code"] == "restart_execution_lease_expired"
        assert "owner" not in str(event["payload"]).lower()
    finally:
        service.close()


def test_startup_reconciliation_is_idempotent_across_concurrent_processes_and_retries(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    original_process = _service(db_path, workspace_dir)
    try:
        group = original_process._insert_run_group(
            title="Concurrent root recovery",
            source="agent",
        )
        run = original_process._insert_run(
            kind="agent_run",
            runnable_id="concurrent-agent",
            user_goal="recover once",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        original_process.append_run_event(
            run["run_id"],
            "agent.run.started",
            {"status": "running"},
        )
        _set_run_fields(
            original_process,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        processes = [
            _service(db_path, workspace_dir),
            _service(db_path, workspace_dir),
        ]
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                reports = list(
                    pool.map(
                        lambda process: process.reconcile_startup_runs(_CUTOFF),
                        processes,
                    )
                )

            retry_report = processes[0].reconcile_startup_runs(_CUTOFF)

            assert sum(
                report["failed_run_ids"] == [run["run_id"]] for report in reports
            ) == 1
            assert retry_report["failed_run_ids"] == []
            events = processes[0].list_run_events(run["run_id"])["events"]
            recovery_events = [
                event
                for event in events
                if event["event_type"] == "run.recovery.interrupted"
            ]
            assert len(recovery_events) == 1
            event_types = [event["event_type"] for event in events]
            assert event_types.count("agent.run.failed") == 1
            assert event_types.count("run.failed") == 1
            assert event_types.count("group.run.failed") == 1
            assert processes[0].get_run(run["run_id"])["status"] == "failed"
            assert processes[0].get_run_group(group["run_group_id"])["status"] == (
                "failed"
            )
        finally:
            for process in processes:
                process.close()
    finally:
        original_process.close()


def test_app_runtime_start_reconciles_before_starting_the_task_runner() -> None:
    calls: list[tuple[str, str]] = []

    class RuntimeService:
        def reconcile_startup_runs(
            self,
            cutoff: str,
            *,
            observed_at: str | None = None,
        ) -> dict[str, object]:
            assert parse_iso_utc(observed_at) is not None
            calls.append(("reconcile", cutoff))
            return {"failed_run_ids": []}

    runtime = object.__new__(AppRuntime)
    runtime._running = False
    runtime._start_time = None
    runtime.get_agent_runtime_service = lambda: RuntimeService()
    runtime._start_task_runner = lambda: calls.append(("task_runner", ""))

    runtime.start()

    assert [name for name, _value in calls] == ["reconcile", "task_runner"]
    assert parse_iso_utc(calls[0][1]) is not None
    assert runtime.running is True


def test_agent_runtime_service_construction_does_not_reconcile_runs(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    original_process = _service(db_path, workspace_dir)
    try:
        run = original_process._insert_run(
            kind="agent_run",
            runnable_id="construction-agent",
            user_goal="construction must be side-effect free",
        )
        _set_run_fields(
            original_process,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        second_process = _service(db_path, workspace_dir)
        try:
            assert second_process.get_run(run["run_id"])["status"] == "running"
            assert second_process.list_run_events(run["run_id"])["events"] == []
            assert runtime_instance_lock_path(db_path, workspace_dir).exists() is False
        finally:
            second_process.close()
    finally:
        original_process.close()


class _FakeTimer:
    def __init__(self, interval: float, callback: Callable[[], None]) -> None:
        self.interval = interval
        self._callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self._callback()


class _LifecycleProbeRLock:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.attempts: queue.Queue[str] = queue.Queue()
        self._owner: int | None = None

    def __enter__(self) -> "_LifecycleProbeRLock":
        self.attempts.put(threading.current_thread().name)
        self._lock.acquire()
        self._owner = threading.get_ident()
        return self

    def __exit__(self, *_args: object) -> None:
        assert self._owner == threading.get_ident()
        self._owner = None
        self._lock.release()

    def hold_for_test(self) -> None:
        self._lock.acquire()
        self._owner = threading.get_ident()

    def release_for_test(self) -> None:
        assert self._owner == threading.get_ident()
        self._owner = None
        self._lock.release()

    def held_by_current_thread(self) -> bool:
        return self._owner == threading.get_ident()


def _runtime_with_fake_startup_timers(
    service: Any,
) -> tuple[AppRuntime, list[_FakeTimer]]:
    timers: list[_FakeTimer] = []

    def timer_factory(interval: float, callback: Callable[[], None]) -> _FakeTimer:
        timer = _FakeTimer(interval, callback)
        timers.append(timer)
        return timer

    runtime = object.__new__(AppRuntime)
    runtime._running = False
    runtime._start_time = None
    runtime._startup_reconciliation_timer = None
    runtime._startup_reconciliation_generation = 0
    runtime._startup_reconciliation_timer_factory = timer_factory
    runtime.get_agent_runtime_service = lambda: service
    runtime._start_task_runner = lambda: None
    return runtime, timers


def test_app_runtime_quarantines_deterministic_startup_integrity_fault_until_repaired(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(title="Repairable root group", source="agent")
        run = service._insert_run(
            kind="agent_run",
            runnable_id="repairable-startup-agent",
            user_goal="fail closed until the persisted root is repaired",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )
        service._conn.execute(
            "UPDATE run_groups SET child_run_ids_json='[]' WHERE run_group_id=?",
            (group["run_group_id"],),
        )
        service._conn.commit()
        runner_calls: list[str] = []
        runtime, timers = _runtime_with_fake_startup_timers(service)
        runtime._start_task_runner = lambda: runner_calls.append("started")
        runtime._stop_native_runtime = lambda: None
        runtime._stop_activity_store = lambda: None

        with pytest.raises(
            RuntimeError,
            match=(
                "agent_runtime_startup_quarantined:"
                "recovery_root_group_owner_not_member"
            ),
        ):
            runtime.start()

        assert runtime.running is False
        assert runner_calls == []
        assert timers == []
        assert runtime.startup_reconciliation_diagnostic == {
            "code": "recovery_root_group_owner_not_member",
            "retryable": False,
            "status": "quarantined",
        }

        service._conn.execute(
            "UPDATE run_groups SET child_run_ids_json=? WHERE run_group_id=?",
            (f'["{run["run_id"]}"]', group["run_group_id"]),
        )
        service._conn.commit()

        runtime.start()

        assert runtime.running is True
        assert runner_calls == ["started"]
        assert runtime.startup_reconciliation_diagnostic == {}
        runtime.stop()
    finally:
        service.close()


def test_app_runtime_concurrent_starts_are_serialized_by_full_lifecycle_lock() -> None:
    lifecycle = _LifecycleProbeRLock()
    calls: list[str] = []

    class RuntimeService:
        def reconcile_startup_runs(
            self,
            _cutoff: str,
            *,
            observed_at: str | None = None,
        ) -> dict[str, object]:
            assert lifecycle.held_by_current_thread()
            calls.append("reconcile_startup")
            return {"failed_run_ids": []}

        def reconcile_runtime_leases(self, observed_at: str) -> dict[str, object]:
            assert parse_iso_utc(observed_at) is not None
            assert lifecycle.held_by_current_thread()
            calls.append("reconcile_leases")
            return {"failed_run_ids": [], "next_lease_expiry_at": ""}

    runtime, _timers = _runtime_with_fake_startup_timers(RuntimeService())
    runtime._lifecycle_lock = lifecycle
    runtime._start_task_runner = lambda: (
        calls.append("start_task_runner")
        if lifecycle.held_by_current_thread()
        else pytest.fail("TaskRunner start escaped lifecycle lock")
    )
    runtime._stop_task_runner = lambda: None
    runtime._stop_native_runtime = lambda: None
    runtime._stop_activity_store = lambda: None
    start_barrier = threading.Barrier(3)

    def concurrent_start() -> None:
        start_barrier.wait()
        runtime.start()

    lifecycle.hold_for_test()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(concurrent_start) for _index in range(2)]
            start_barrier.wait()
            attempted = {
                lifecycle.attempts.get(timeout=2),
                lifecycle.attempts.get(timeout=2),
            }
            assert attempted
            assert calls == []
            lifecycle.release_for_test()
            for future in futures:
                future.result(timeout=2)
    finally:
        if lifecycle.held_by_current_thread():
            lifecycle.release_for_test()

    assert calls == ["reconcile_startup", "reconcile_leases", "start_task_runner"]
    assert runtime.running is True
    runtime.stop()


def test_app_runtime_concurrent_start_stop_hold_lock_through_shutdown_callbacks() -> None:
    lifecycle = _LifecycleProbeRLock()
    callback_lock_ownership: list[tuple[str, bool]] = []

    class RuntimeService:
        def reconcile_startup_runs(
            self,
            _cutoff: str,
            *,
            observed_at: str | None = None,
        ) -> dict[str, object]:
            callback_lock_ownership.append(
                ("reconcile_startup", lifecycle.held_by_current_thread())
            )
            return {"failed_run_ids": []}

        def reconcile_runtime_leases(self, _observed_at: str) -> dict[str, object]:
            callback_lock_ownership.append(
                ("reconcile_leases", lifecycle.held_by_current_thread())
            )
            return {"failed_run_ids": [], "next_lease_expiry_at": ""}

    runtime, _timers = _runtime_with_fake_startup_timers(RuntimeService())
    runtime._lifecycle_lock = lifecycle
    runtime._start_task_runner = lambda: callback_lock_ownership.append(
        ("start_task_runner", lifecycle.held_by_current_thread())
    )
    runtime._stop_task_runner = lambda: callback_lock_ownership.append(
        ("stop_task_runner", lifecycle.held_by_current_thread())
    )
    runtime._stop_native_runtime = lambda: callback_lock_ownership.append(
        ("stop_native_runtime", lifecycle.held_by_current_thread())
    )
    runtime._stop_activity_store = lambda: callback_lock_ownership.append(
        ("stop_activity_store", lifecycle.held_by_current_thread())
    )
    runtime.start()
    lifecycle.attempts.get_nowait()
    before_concurrency = list(callback_lock_ownership)
    operation_barrier = threading.Barrier(3)

    def invoke(operation: Callable[[], None]) -> None:
        operation_barrier.wait()
        operation()

    lifecycle.hold_for_test()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            start_future = pool.submit(invoke, runtime.start)
            stop_future = pool.submit(invoke, runtime.stop)
            operation_barrier.wait()
            lifecycle.attempts.get(timeout=2)
            lifecycle.attempts.get(timeout=2)
            assert callback_lock_ownership == before_concurrency
            lifecycle.release_for_test()
            start_future.result(timeout=2)
            stop_future.result(timeout=2)
    finally:
        if lifecycle.held_by_current_thread():
            lifecycle.release_for_test()

    assert callback_lock_ownership
    assert all(owned for _callback, owned in callback_lock_ownership)
    if runtime.running:
        runtime.stop()


def test_app_runtime_reschedules_deferred_lease_reconciliation_after_heartbeat_renewal(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        now = datetime.now(timezone.utc)
        run = service._insert_run(
            kind="agent_run",
            runnable_id="timer-agent",
            user_goal="recover after the live lease expires",
            async_lease_generation=8,
            async_lease_owner_token="timer-owner",
            async_lease_expires_at=(now + timedelta(seconds=30)).isoformat(),
            async_lease_heartbeat_at=now.isoformat(),
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=(now - timedelta(minutes=5)).isoformat(),
            updated_at=(now - timedelta(minutes=5)).isoformat(),
        )
        runtime, timers = _runtime_with_fake_startup_timers(service)
        runtime._stop_task_runner = lambda: None
        runtime._stop_native_runtime = lambda: None
        runtime._stop_activity_store = lambda: None

        runtime.start()

        assert len(timers) == 1
        assert timers[0].started is True
        assert timers[0].daemon is True
        assert timers[0].interval > 0
        assert timers[0].interval <= 5.0

        renewed_at = datetime.now(timezone.utc)
        _set_run_fields(
            service,
            run["run_id"],
            async_lease_expires_at=(renewed_at + timedelta(seconds=60)).isoformat(),
            async_lease_heartbeat_at=renewed_at.isoformat(),
        )
        timers[0].fire()

        assert service.get_run(run["run_id"])["status"] == "running"
        assert len(timers) == 2
        assert timers[1].started is True
        assert timers[1].interval > 0
        assert timers[1].interval <= 5.0

        expired_at = datetime.now(timezone.utc)
        _set_run_fields(
            service,
            run["run_id"],
            async_lease_expires_at=(expired_at - timedelta(seconds=1)).isoformat(),
            async_lease_heartbeat_at=(expired_at - timedelta(seconds=2)).isoformat(),
        )
        timers[1].fire()

        assert service.get_run(run["run_id"])["status"] == "failed"
        assert len(timers) == 3
        assert timers[2].started is True
        runtime.stop()
        assert timers[2].cancelled is True
    finally:
        service.close()


def test_app_runtime_stop_cancels_and_fences_deferred_reconciliation(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        now = datetime.now(timezone.utc)
        run = service._insert_run(
            kind="agent_run",
            runnable_id="stopping-agent",
            user_goal="do not recover after stop",
            async_lease_generation=2,
            async_lease_owner_token="stopping-owner",
            async_lease_expires_at=(now + timedelta(seconds=30)).isoformat(),
            async_lease_heartbeat_at=now.isoformat(),
        )
        _set_run_fields(
            service,
            run["run_id"],
            created_at=(now - timedelta(minutes=5)).isoformat(),
            updated_at=(now - timedelta(minutes=5)).isoformat(),
        )
        runtime, timers = _runtime_with_fake_startup_timers(service)
        runtime._stop_task_runner = lambda: None
        runtime._stop_native_runtime = lambda: None
        runtime._stop_activity_store = lambda: None
        runtime.start()
        timer = timers[0]

        runtime.stop()

        assert timer.cancelled is True
        assert runtime.running is False
        timer.fire()
        assert len(timers) == 1
        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_app_runtime_deferred_reconciliation_uses_a_nonzero_minimum_delay() -> None:
    class LeaseReportService:
        def reconcile_startup_runs(
            self,
            _cutoff: str,
            *,
            observed_at: str | None = None,
        ) -> dict[str, object]:
            assert parse_iso_utc(observed_at) is not None
            return {
                "failed_run_ids": [],
                "deferred_lease_run_ids": ["run-raced-expiry"],
                "next_lease_expiry_at": "1970-01-01T00:00:00+00:00",
            }

    runtime, timers = _runtime_with_fake_startup_timers(LeaseReportService())

    runtime.start()

    assert len(timers) == 1
    assert timers[0].interval == pytest.approx(0.05)


def test_app_runtime_watchdog_discovers_post_start_leases_without_touching_unleased_runs(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        runtime, timers = _runtime_with_fake_startup_timers(service)
        runtime._stop_task_runner = lambda: None
        runtime._stop_native_runtime = lambda: None
        runtime._stop_activity_store = lambda: None
        runtime.start()
        assert len(timers) == 1

        now = datetime.now(timezone.utc)
        leased = service._insert_run(
            kind="agent_run",
            runnable_id="post-start-leased",
            user_goal="watch this lease",
            async_lease_generation=9,
            async_lease_owner_token="post-start-owner",
            async_lease_expires_at=(now + timedelta(seconds=60)).isoformat(),
            async_lease_heartbeat_at=now.isoformat(),
        )
        unleased = service._insert_run(
            kind="agent_run",
            runnable_id="post-start-unleased",
            user_goal="never touch this run",
        )

        timers[0].fire()

        assert service.get_run(leased["run_id"])["status"] == "running"
        assert service.get_run(unleased["run_id"])["status"] == "running"
        assert len(timers) == 2

        expired_at = datetime.now(timezone.utc)
        _set_run_fields(
            service,
            leased["run_id"],
            async_lease_expires_at=(expired_at - timedelta(seconds=1)).isoformat(),
            async_lease_heartbeat_at=(expired_at - timedelta(seconds=2)).isoformat(),
        )
        timers[1].fire()

        assert service.get_run(leased["run_id"])["status"] == "failed"
        assert service.get_run(unleased["run_id"])["status"] == "running"
        assert len(timers) == 3
        assert timers[2].started is True
        runtime.stop()
        assert timers[2].cancelled is True
    finally:
        service.close()


def test_app_runtime_watchdog_never_repeats_startup_sweep_after_child_approval(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Startup-preserved workflow",
            source="workflow",
        )
        parent = service._insert_run(
            kind="workflow_run",
            runnable_id="startup-parent",
            user_goal="wait for child approval",
            run_group_id=group["run_group_id"],
        )
        child = service._insert_run(
            kind="agent_run",
            runnable_id="startup-child",
            user_goal="request approval",
            run_group_id=group["run_group_id"],
        )
        pending = {
            "approval_id": "approval-startup-child",
            "tool": "desktop.open_app",
            "input_preview": {"app": "Notes"},
            "messages": [{"role": "user", "content": "Open Notes"}],
            "tool_request": {
                "tool": "desktop.open_app",
                "input": {"app": "Notes"},
            },
            "workflow_run_id": parent["run_id"],
        }
        service._update_run(parent["run_id"], status="running", timeline=[])
        service._update_run(
            child["run_id"],
            status="approval_required",
            pending_approval=pending,
        )
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        for run_id in (parent["run_id"], child["run_id"]):
            _set_run_fields(
                service,
                run_id,
                created_at=old_time,
                updated_at=old_time,
            )

        startup_calls: list[str] = []
        lease_calls: list[str] = []
        reconcile_startup_runs = service.reconcile_startup_runs
        reconcile_runtime_leases = service.reconcile_runtime_leases

        def counted_startup(
            cutoff: str,
            *,
            observed_at: str | None = None,
        ) -> dict[str, Any]:
            startup_calls.append(cutoff)
            return reconcile_startup_runs(cutoff, observed_at=observed_at)

        def counted_leases(observed_at: str) -> dict[str, Any]:
            lease_calls.append(observed_at)
            return reconcile_runtime_leases(observed_at)

        service.reconcile_startup_runs = counted_startup
        service.reconcile_runtime_leases = counted_leases
        runtime, timers = _runtime_with_fake_startup_timers(service)
        runtime._stop_task_runner = lambda: None
        runtime._stop_native_runtime = lambda: None
        runtime._stop_activity_store = lambda: None
        runtime.start()

        assert service.get_run(parent["run_id"])["status"] == "running"
        assert len(startup_calls) == 1
        assert len(lease_calls) == 1
        assert len(timers) == 1

        private_pending = service.runs.pending_approval_private(child["run_id"])
        assert private_pending is not None
        assert service.run_approvals.claim_pending_approval(
            child["run_id"],
            private_pending,
            expected_approval_id=pending["approval_id"],
        ) is True
        child_completed = service._update_run(
            child["run_id"],
            status="completed",
            result="approved child completed",
            pending_approval={},
            expected_status="approval_required",
            expected_approval_id=pending["approval_id"],
        )
        assert child_completed is not None

        timers[0].fire()

        assert len(startup_calls) == 1
        assert len(lease_calls) == 2
        assert service.get_run(parent["run_id"])["status"] == "running"
        assert not [
            event
            for event in service.list_run_events(parent["run_id"])["events"]
            if event["event_type"] == "run.recovery.interrupted"
        ]
        runtime.stop()
    finally:
        service.close()


def test_app_runtime_process_lock_blocks_second_runtime_until_first_stops(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    services = [
        _service(db_path, workspace_dir),
        _service(db_path, workspace_dir),
    ]
    runtimes: list[AppRuntime] = []
    runner_calls = [[], []]
    try:
        for index, service in enumerate(services):
            runtime, _timers = _runtime_with_fake_startup_timers(service)
            runtime._start_task_runner = (
                lambda target=runner_calls[index]: target.append("started")
            )
            runtime._stop_task_runner = lambda: None
            runtime._stop_native_runtime = lambda: None
            runtime._stop_activity_store = lambda: None
            runtimes.append(runtime)

        runtimes[0].start()
        orphan = services[0]._insert_run(
            kind="agent_run",
            runnable_id="second-runtime-orphan",
            user_goal="second runtime must not reconcile while lock is held",
        )
        _set_run_fields(
            services[0],
            orphan["run_id"],
            created_at=_BEFORE_CUTOFF,
            updated_at=_BEFORE_CUTOFF,
        )

        with pytest.raises(RuntimeError, match="runtime_instance_already_active"):
            runtimes[1].start()

        assert runtimes[1].running is False
        assert runner_calls == [["started"], []]
        assert services[1].get_run(orphan["run_id"])["status"] == "running"

        runtimes[0].stop()
        runtimes[0].stop()
        runtimes[1].start()

        assert runtimes[1].running is True
        assert runner_calls == [["started"], ["started"]]
        assert services[1].get_run(orphan["run_id"])["status"] == "failed"
    finally:
        for runtime in runtimes:
            if runtime.running:
                runtime.stop()
        for service in services:
            service.close()


def test_app_runtime_releases_process_lock_when_task_runner_start_fails(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    services = [
        _service(db_path, workspace_dir),
        _service(db_path, workspace_dir),
    ]
    runtimes: list[AppRuntime] = []
    try:
        failing, _failing_timers = _runtime_with_fake_startup_timers(services[0])

        def fail_task_runner_start() -> None:
            raise RuntimeError("task-runner-start-failed")

        failing._start_task_runner = fail_task_runner_start
        runtimes.append(failing)
        with pytest.raises(RuntimeError, match="task-runner-start-failed"):
            failing.start()
        assert failing.running is False

        replacement, _replacement_timers = _runtime_with_fake_startup_timers(
            services[1]
        )
        replacement._start_task_runner = lambda: None
        replacement._stop_task_runner = lambda: None
        replacement._stop_native_runtime = lambda: None
        replacement._stop_activity_store = lambda: None
        runtimes.append(replacement)

        replacement.start()

        assert replacement.running is True
    finally:
        for runtime in runtimes:
            if runtime.running:
                runtime.stop()
        for service in services:
            service.close()


def test_app_runtime_partial_task_runner_start_failure_unwinds_runner_state(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    runtime, timers = _runtime_with_fake_startup_timers(service)

    def partially_start_task_runner() -> None:
        runtime._task_runner = object()
        runtime._task_runner_thread = threading.Thread(target=lambda: None)
        runtime._task_runner_loop = None
        runtime._task_runner_loop_ready = threading.Event()
        raise RuntimeError("partial-task-runner-start-failed")

    runtime._start_task_runner = partially_start_task_runner
    try:
        with pytest.raises(RuntimeError, match="partial-task-runner-start-failed"):
            runtime.start()

        assert runtime.running is False
        assert runtime._task_runner is None
        assert runtime._task_runner_thread is None
        assert runtime._task_runner_loop is None
        assert runtime._runtime_instance_service is None
        assert len(timers) == 1
        assert timers[0].cancelled is True
    finally:
        service.close()


def test_runtime_process_lock_is_released_when_owner_process_dies(tmp_path) -> None:
    db_path = tmp_path / "process-owned-runtime.db"
    child_script = (
        "import time; "
        "from apps.shell.agent.runtime.runtime_instance_lock import "
        "RuntimeProcessInstanceLock; "
        f"lock=RuntimeProcessInstanceLock(db_path={str(db_path)!r}); "
        "assert lock.acquire(); print('locked', flush=True); time.sleep(60)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", child_script],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    contender = RuntimeProcessInstanceLock(db_path=db_path)
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "locked"
        assert contender.acquire() is False

        child.terminate()
        child.wait(timeout=5)

        assert contender.acquire() is True
    finally:
        contender.release()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_deferred_reconciliation_never_claims_runs_created_after_startup_cutoff(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        now = datetime.now(timezone.utc)
        old_run = service._insert_run(
            kind="agent_run",
            runnable_id="old-process-agent",
            user_goal="old lease will expire",
            async_lease_generation=5,
            async_lease_owner_token="old-process-owner",
            async_lease_expires_at=(now + timedelta(seconds=30)).isoformat(),
            async_lease_heartbeat_at=now.isoformat(),
        )
        _set_run_fields(
            service,
            old_run["run_id"],
            created_at=(now - timedelta(minutes=5)).isoformat(),
            updated_at=(now - timedelta(minutes=5)).isoformat(),
        )
        runtime, timers = _runtime_with_fake_startup_timers(service)
        runtime.start()

        new_run = service._insert_run(
            kind="agent_run",
            runnable_id="current-process-agent",
            user_goal="belongs to the current process",
        )
        observed_at = datetime.now(timezone.utc)
        _set_run_fields(
            service,
            old_run["run_id"],
            async_lease_expires_at=(observed_at - timedelta(seconds=1)).isoformat(),
            async_lease_heartbeat_at=(observed_at - timedelta(seconds=2)).isoformat(),
        )

        timers[0].fire()

        assert service.get_run(old_run["run_id"])["status"] == "failed"
        assert service.get_run(new_run["run_id"])["status"] == "running"
        assert service.list_run_events(new_run["run_id"])["events"] == []
    finally:
        service.close()


@pytest.mark.parametrize("parent_status", ["running", "approval_required"])
def test_startup_reconciliation_preserves_only_the_workflow_parent_waiting_on_valid_child_approval(
    tmp_path,
    parent_status: str,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Approval workflow",
            source="workflow",
        )
        group_id = group["run_group_id"]
        parent = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-parent",
            user_goal="wait for child approval",
            run_group_id=group_id,
            project_root_group=True,
        )
        child = service._insert_run(
            kind="agent_run",
            runnable_id="approval-child",
            user_goal="request approval",
            run_group_id=group_id,
        )
        sibling = service._insert_run(
            kind="agent_run",
            runnable_id="interrupted-sibling",
            user_goal="must not be preserved",
            run_group_id=group_id,
        )
        service._update_run(
            parent["run_id"],
            status=parent_status,
            timeline=[
                {
                    "time": _BEFORE_CUTOFF,
                    "event": "workflow.run.approval_required",
                    "child_run_id": child["run_id"],
                }
            ],
        )
        service._update_run(
            child["run_id"],
            status="approval_required",
            pending_approval={
                "approval_id": "approval-workflow-child",
                "tool": "desktop.open_app",
                "input_preview": {"app": "Notes"},
                "messages": [{"role": "user", "content": "Open Notes"}],
                "tool_request": {
                    "tool": "desktop.open_app",
                    "input": {"app": "Notes"},
                },
                "workflow_run_id": parent["run_id"],
            },
        )
        for run_id in (parent["run_id"], child["run_id"], sibling["run_id"]):
            _set_run_fields(
                service,
                run_id,
                created_at=_BEFORE_CUTOFF,
                updated_at=_BEFORE_CUTOFF,
            )

        second_process = _service(db_path, workspace_dir)
        try:
            second_process.reconcile_startup_runs(_CUTOFF)

            assert second_process.get_run(parent["run_id"])["status"] == parent_status
            assert second_process.get_run(child["run_id"])["status"] == (
                "approval_required"
            )
            assert second_process.get_run(sibling["run_id"])["status"] == "failed"
            assert second_process.get_run_group(group_id)["status"] == (
                "approval_required"
            )
            parent_recovery_events = [
                event
                for event in second_process.list_run_events(parent["run_id"])["events"]
                if event["event_type"] == "run.recovery.interrupted"
            ]
            assert parent_recovery_events == []
        finally:
            second_process.close()
    finally:
        service.close()


def test_startup_reconciliation_preserves_markerless_parent_from_private_child_relation(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Markerless approval workflow",
            source="workflow",
        )
        group_id = group["run_group_id"]
        parent = service._insert_run(
            kind="workflow_run",
            runnable_id="markerless-parent",
            user_goal="wait for durable child relation",
            run_group_id=group_id,
        )
        child = service._insert_run(
            kind="agent_run",
            runnable_id="markerless-child",
            user_goal="request approval before parent marker commits",
            run_group_id=group_id,
        )
        service._update_run(parent["run_id"], status="running", timeline=[])
        service._update_run(
            child["run_id"],
            status="approval_required",
            pending_approval={
                "approval_id": "approval-markerless-child",
                "tool": "desktop.open_app",
                "messages": [{"role": "user", "content": "Open Notes"}],
                "tool_request": {
                    "tool": "desktop.open_app",
                    "input": {"app": "Notes"},
                },
                "workflow_run_id": parent["run_id"],
            },
        )
        for run_id in (parent["run_id"], child["run_id"]):
            _set_run_fields(
                service,
                run_id,
                created_at=_BEFORE_CUTOFF,
                updated_at=_BEFORE_CUTOFF,
            )

        second_process = _service(db_path, workspace_dir)
        try:
            report = second_process.reconcile_startup_runs(_CUTOFF)

            assert second_process.get_run(parent["run_id"])["status"] == "running"
            assert report["preserved_workflow_parent_run_ids"] == [parent["run_id"]]
            parent_recovery_events = [
                event
                for event in second_process.list_run_events(parent["run_id"])["events"]
                if event["event_type"] == "run.recovery.interrupted"
            ]
            assert parent_recovery_events == []
        finally:
            second_process.close()
    finally:
        service.close()


def test_startup_reconciliation_does_not_preserve_markerless_parent_without_relation(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Unrelated approval workflow",
            source="workflow",
        )
        group_id = group["run_group_id"]
        parent = service._insert_run(
            kind="workflow_run",
            runnable_id="unrelated-parent",
            user_goal="must not infer a parent relation",
            run_group_id=group_id,
        )
        child = service._insert_run(
            kind="agent_run",
            runnable_id="unrelated-child",
            user_goal="approval has no parent relation",
            run_group_id=group_id,
        )
        service._update_run(parent["run_id"], status="running", timeline=[])
        service._update_run(
            child["run_id"],
            status="approval_required",
            pending_approval={
                "approval_id": "approval-unrelated-child",
                "tool": "desktop.open_app",
                "messages": [{"role": "user", "content": "Open Notes"}],
                "tool_request": {
                    "tool": "desktop.open_app",
                    "input": {"app": "Notes"},
                },
            },
        )
        for run_id in (parent["run_id"], child["run_id"]):
            _set_run_fields(
                service,
                run_id,
                created_at=_BEFORE_CUTOFF,
                updated_at=_BEFORE_CUTOFF,
            )

        second_process = _service(db_path, workspace_dir)
        try:
            second_process.reconcile_startup_runs(_CUTOFF)

            assert second_process.get_run(parent["run_id"])["status"] == "failed"
            assert second_process.get_run(child["run_id"])["status"] == (
                "approval_required"
            )
        finally:
            second_process.close()
    finally:
        service.close()


def test_startup_reconciliation_recomputes_failed_run_group_status(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Interrupted group",
            source="agent_group",
        )
        group_id = group["run_group_id"]
        runs = [
            service._insert_run(
                kind="agent_run",
                runnable_id=f"interrupted-agent-{index}",
                user_goal="fail closed",
                run_group_id=group_id,
                project_root_group=index == 0,
            )
            for index in range(2)
        ]
        for run in runs:
            _set_run_fields(
                service,
                run["run_id"],
                created_at=_BEFORE_CUTOFF,
                updated_at=_BEFORE_CUTOFF,
            )

        second_process = _service(db_path, workspace_dir)
        try:
            second_process.reconcile_startup_runs(_CUTOFF)

            assert {
                second_process.get_run(run["run_id"])["status"] for run in runs
            } == {"failed"}
            assert second_process.get_run_group(group_id)["status"] == "failed"
        finally:
            second_process.close()
    finally:
        service.close()


def test_later_startup_repairs_a_stale_active_group_with_terminal_runs(tmp_path) -> None:
    db_path = tmp_path / "agent-runtime.db"
    workspace_dir = tmp_path / "runtime"
    service = _service(db_path, workspace_dir)
    try:
        group = service._insert_run_group(
            title="Stale recovery projection",
            source="agent_group",
        )
        group_id = group["run_group_id"]
        runs = [
            service._insert_run(
                kind="agent_run",
                runnable_id=f"already-failed-agent-{index}",
                user_goal="terminal before this startup",
                run_group_id=group_id,
                project_root_group=index == 0,
            )
            for index in range(2)
        ]
        for run in runs:
            service._update_run(
                run["run_id"],
                status="failed",
                result="previous recovery failed closed",
            )
            _set_run_fields(
                service,
                run["run_id"],
                created_at=_BEFORE_CUTOFF,
                updated_at=_BEFORE_CUTOFF,
            )
        service._conn.execute(
            """
            UPDATE run_groups
               SET status='running', created_at=?, updated_at=?
             WHERE run_group_id=?
            """,
            (_BEFORE_CUTOFF, _BEFORE_CUTOFF, group_id),
        )
        service._conn.commit()

        second_process = _service(db_path, workspace_dir)
        try:
            second_process.reconcile_startup_runs(_CUTOFF)
            repaired = second_process.get_run_group(group_id)
            second_process.reconcile_startup_runs(
                _CUTOFF,
                observed_at="2026-07-11T10:05:00+00:00",
            )

            assert repaired["status"] == "failed"
            assert second_process.get_run_group(group_id)["updated_at"] == (
                repaired["updated_at"]
            )
        finally:
            second_process.close()
    finally:
        service.close()
