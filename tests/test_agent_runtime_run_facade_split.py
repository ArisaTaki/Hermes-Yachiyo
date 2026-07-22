"""Tests for Run and GroupRun facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_facade import RUNTIME_UNSET, RuntimeRunFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_run_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunFacadeMixin is RuntimeRunFacadeMixin
    assert agent_runtime._UNSET is RUNTIME_UNSET
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeRunFacadeMixin)
    assert "_insert_run" not in agent_runtime.NativeRunEngine.__dict__
    assert "_update_run" not in agent_runtime.NativeRunEngine.__dict__
    assert "_update_run_group" not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_run_facade_methods_available_after_split(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Facade Group", source="workflow")
        first = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-facade",
            user_goal="Ship workflow",
            run_group_id=group["run_group_id"],
        )
        second = service._insert_run(
            kind="agent_run",
            runnable_id="agent-facade",
            user_goal="Ship workflow",
            run_group_id=group["run_group_id"],
        )
        with_pending = service._update_run(
            first["run_id"],
            pending_approval={"tool": "terminal.run", "approval_id": "approval-1"},
        )
        preserved_pending = service._update_run(first["run_id"], status="running")
        service._update_run_group(group["run_group_id"], status="completed", summary="done")
        service._update_run_group(group["run_group_id"], status="completed", summary="done")

        events = service.list_run_events(first["run_id"])["events"]
        group_events = [
            event
            for event in events
            if str(event.get("event_type") or "").startswith("group.run.")
        ]

        assert service.runs._unset_sentinel is RUNTIME_UNSET
        assert with_pending["pending_approval"]["approval_id"] == "approval-1"
        assert preserved_pending["pending_approval"]["approval_id"] == "approval-1"
        assert service._run_by_client_request_id("missing") is None
        assert service._terminal_run_or_none(first["run_id"]) is None
        assert [event["event_type"] for event in group_events] == [
            "group.run.started",
            "group.run.completed",
        ]
        assert group_events[-1]["payload"]["child_run_ids"] == [
            first["run_id"],
            second["run_id"],
        ]
    finally:
        service.close()


def test_native_run_group_terminal_guard_is_idempotent_and_fail_closed(
    tmp_path: Path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-terminal-group.db",
        workspace_dir=tmp_path / "runtime-terminal-group",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Terminal guard", source="workflow")
        run = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-terminal-guard",
            user_goal="guard terminal group",
            run_group_id=group["run_group_id"],
        )
        completed = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="winner",
        )
        assert completed is not None
        before_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]

        repeated = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="winner",
        )

        assert repeated == completed
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
        for status, summary in (
            ("completed", "different summary"),
            ("failed", "winner"),
            ("running", "winner"),
        ):
            with pytest.raises(
                AgentRuntimeError,
                match="run_group_terminal_outcome_conflict",
            ):
                service._update_run_group(
                    group["run_group_id"],
                    status=status,
                    summary=summary,
                )
        assert service.get_run_group(group["run_group_id"]) == completed
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


@pytest.mark.parametrize(
    "tampered_payload",
    [
        {"group_run_id": "group-forged"},
        {"status": "failed"},
        {"summary": "stale summary"},
        {"child_run_ids": []},
        {"child_run_ids": ["", "run-extra"]},
        {"child_run_ids": ["run-duplicated", "run-duplicated"], "participant_count": 2},
    ],
)
def test_native_run_group_terminal_marker_requires_exact_authoritative_payload(
    tmp_path: Path,
    tampered_payload: dict[str, object],
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-terminal-marker.db",
        workspace_dir=tmp_path / "runtime-terminal-marker",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Terminal marker", source="workflow")
        first = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-terminal-marker",
            user_goal="record the authoritative terminal marker",
            run_group_id=group["run_group_id"],
        )
        second = service._insert_run(
            kind="agent_run",
            runnable_id="agent-terminal-marker",
            user_goal="record the authoritative terminal marker",
            run_group_id=group["run_group_id"],
        )
        child_run_ids = [first["run_id"], second["run_id"]]
        canonical_payload = {
            "child_run_ids": child_run_ids,
            "group_run_id": group["run_group_id"],
            "participant_count": 2,
            "run_group_id": group["run_group_id"],
            "status": "completed",
            "summary": "winner",
        }
        service.append_run_event(
            first["run_id"],
            "group.run.completed",
            {**canonical_payload, **tampered_payload},
        )

        service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="winner",
        )

        terminal_events = [
            event
            for event in service.list_run_events(
                first["run_id"],
                include_internal=True,
            )["events"]
            if event["event_type"] == "group.run.completed"
        ]
        assert len(terminal_events) == 2
        authoritative = terminal_events[-1]["payload"]
        assert authoritative["run_group_id"] == group["run_group_id"]
        assert authoritative["group_run_id"] == group["run_group_id"]
        assert authoritative["status"] == "completed"
        assert authoritative["summary"] == "winner"
        assert authoritative["child_run_ids"] == child_run_ids
        assert authoritative["participant_count"] == len(child_run_ids)
    finally:
        service.close()


def test_native_run_group_idempotent_terminal_update_repairs_stale_marker(
    tmp_path: Path,
) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-terminal-marker-repair.db",
        workspace_dir=tmp_path / "runtime-terminal-marker-repair",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = service._insert_run_group(title="Repair terminal marker", source="workflow")
        run = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-terminal-marker-repair",
            user_goal="repair the canonical terminal marker",
            run_group_id=group["run_group_id"],
        )
        service.append_run_event(
            run["run_id"],
            "group.run.completed",
            {
                "child_run_ids": [run["run_id"]],
                "group_run_id": group["run_group_id"],
                "participant_count": 1,
                "run_group_id": group["run_group_id"],
                "status": "completed",
                "summary": "stale summary",
            },
        )
        service._conn.execute(
            "UPDATE run_groups SET status='completed', summary='winner' "
            "WHERE run_group_id=?",
            (group["run_group_id"],),
        )
        service._conn.commit()

        service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="winner",
        )

        terminal_events = [
            event
            for event in service.list_run_events(run["run_id"])["events"]
            if event["event_type"] == "group.run.completed"
        ]
        assert len(terminal_events) == 2
        assert terminal_events[-1]["payload"]["summary"] == "winner"
    finally:
        service.close()
