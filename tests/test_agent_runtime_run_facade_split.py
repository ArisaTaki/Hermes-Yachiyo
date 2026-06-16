"""Tests for Run and GroupRun facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
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
