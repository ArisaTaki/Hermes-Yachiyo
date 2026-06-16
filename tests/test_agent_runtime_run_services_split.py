"""Tests for Run repository service setup split out of the legacy runtime."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.runtime.agent_runs import RuntimeAgentRunStarter
from apps.shell.agent.runtime.approval_snapshots import ApprovalSnapshotBuilder
from apps.shell.agent.runtime.run_projections import RunProjectionCoordinator
from apps.shell.agent.runtime.run_services import (
    RuntimeRunLayerSetup,
    RuntimeRunServiceBundle,
    build_runtime_run_layer_setup,
    build_runtime_run_services,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeTaskRunLinks:
    def sync_projection(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def test_runtime_run_service_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunServiceBundle is RuntimeRunServiceBundle
    assert agent_runtime.RuntimeRunLayerSetup is RuntimeRunLayerSetup
    assert agent_runtime._build_runtime_run_layer_setup is build_runtime_run_layer_setup


def test_build_runtime_run_services_wires_repositories_and_projections(tmp_path) -> None:
    conn = object()
    db_lock = object()
    task_run_links = FakeTaskRunLinks()

    bundle = build_runtime_run_services(
        conn=conn,
        db_lock=db_lock,
        ensure_row_factory=lambda: None,
        row_to_run_group=lambda row: dict(row) if isinstance(row, dict) else {},
        row_to_run=lambda row: dict(row) if isinstance(row, dict) else {},
        now=lambda: "2026-06-15T10:00:00Z",
        json_dump=lambda _value: "{}",
        json_load=lambda _value, default: default,
        redact_secrets=lambda value: str(value),
        redact_json_value=lambda value: value,
        contains_sensitive_text=lambda _value: False,
        error_type=agent_runtime.AgentRuntimeError,
        unset_sentinel=object(),
        agent_artifacts_dir=tmp_path / "agent-artifacts",
        workflow_artifacts_dir=tmp_path / "workflow-artifacts",
        get_run=lambda run_id: {"run_id": run_id},
        safe_rel_path=lambda value: str(value),
        is_within=lambda _path, _root: True,
        read_text=lambda path: Path(path).read_text(encoding="utf-8"),
        task_run_links=task_run_links,
        accepting_runs=lambda: True,
        append_run_to_group=lambda _group_id, _run_id: None,
        get_run_group=lambda run_group_id: {"run_group_id": run_group_id},
        insert_run_group=lambda **kwargs: {"run_group_id": "group-1", **kwargs},
        insert_run=lambda **kwargs: {"run_id": "run-1", **kwargs},
        run_by_client_request_id=lambda _client_request_id: None,
        client_request_id_from_payload=lambda payload: str(payload.get("client_request_id") or ""),
        agent_workspace_dir=lambda agent_id: tmp_path / "workspaces" / agent_id,
    )

    assert isinstance(bundle, RuntimeRunServiceBundle)
    assert isinstance(bundle.approval_snapshots, ApprovalSnapshotBuilder)
    assert isinstance(bundle.run_groups, RunGroupRepository)
    assert isinstance(bundle.run_approvals, ApprovalRepository)
    assert isinstance(bundle.run_artifacts, RunArtifactRepository)
    assert isinstance(bundle.run_projections, RunProjectionCoordinator)
    assert isinstance(bundle.runs, RunRepository)
    assert isinstance(bundle.run_events, RunEventRepository)
    assert isinstance(bundle.agent_run_starter, RuntimeAgentRunStarter)
    assert bundle.run_groups._conn is conn
    assert bundle.run_approvals._conn is conn
    assert bundle.run_approvals._db_lock is db_lock
    assert bundle.run_artifacts._conn is conn
    assert bundle.run_projections._run_artifacts is bundle.run_artifacts
    assert bundle.run_projections._run_approvals is bundle.run_approvals
    assert bundle.run_projections._task_run_links is task_run_links
    assert bundle.runs._sync_projections.__self__ is bundle.run_projections
    assert bundle.run_events._sync_event_cursor.__self__ is bundle.run_projections


def test_build_runtime_run_layer_setup_wires_services_and_sync_coordinator(tmp_path) -> None:
    conn = object()
    db_lock = threading.RLock()
    task_run_links = FakeTaskRunLinks()
    executed: list[tuple[str, str]] = []

    setup = build_runtime_run_layer_setup(
        conn=conn,
        db_lock=db_lock,
        ensure_row_factory=lambda: None,
        row_to_run_group=lambda row: dict(row) if isinstance(row, dict) else {},
        row_to_run=lambda row: dict(row) if isinstance(row, dict) else {},
        agent_artifacts_dir=tmp_path / "agent-artifacts",
        workflow_artifacts_dir=tmp_path / "workflow-artifacts",
        get_run=lambda run_id: {"run_id": run_id},
        task_run_links=task_run_links,
        accepting_runs=lambda: True,
        append_run_to_group=lambda _group_id, _run_id: None,
        get_run_group=lambda run_group_id: {"run_group_id": run_group_id},
        insert_run_group=lambda **kwargs: {"run_group_id": "group-1", **kwargs},
        insert_run=lambda **kwargs: {"run_id": "run-1", **kwargs},
        run_by_client_request_id=lambda _client_request_id: None,
        client_request_id_from_payload=lambda payload: str(payload.get("client_request_id") or ""),
        agent_workspace_dir=lambda agent: str(tmp_path / "workspaces" / agent["agent_id"]),
        get_agent_private=lambda agent_id: {"agent_id": agent_id, "name": "Agent"},
        validate_agent_run_readiness=lambda _agent: None,
        execute_agent_run=lambda run_id, _agent, user_goal, **_kwargs: executed.append((run_id, user_goal))
        or {"run_id": run_id, "status": "completed"},
        project_agent_run_group_if_root=lambda result: {**result, "projected": True},
    )

    assert isinstance(setup, RuntimeRunLayerSetup)
    assert isinstance(setup.run_services, RuntimeRunServiceBundle)
    assert setup.agent_run_coordinator._starter is setup.run_services.agent_run_starter
    assert setup.agent_run_coordinator._lock is db_lock
    result = setup.agent_run_coordinator.create_sync(
        {"agent_id": "agent-1", "user_goal": "do work"}
    )
    assert result == {"run_id": "run-1", "status": "completed", "projected": True}
    assert executed == [("run-1", "do work")]


def test_native_runtime_installs_run_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.approval_snapshots, ApprovalSnapshotBuilder)
        assert isinstance(service.run_groups, RunGroupRepository)
        assert isinstance(service.run_approvals, ApprovalRepository)
        assert isinstance(service.run_artifacts, RunArtifactRepository)
        assert isinstance(service.run_projections, RunProjectionCoordinator)
        assert isinstance(service.runs, RunRepository)
        assert isinstance(service.run_events, RunEventRepository)
        assert isinstance(service.agent_run_starter, RuntimeAgentRunStarter)
        assert service.run_groups._conn is service._conn
        assert service.run_approvals._conn is service._conn
        assert service.run_artifacts._conn is service._conn
        assert service.run_projections._task_run_links is service.task_run_links
        assert service.runs._sync_projections.__self__ is service.run_projections
        assert service.run_events._sync_event_cursor.__self__ is service.run_projections
    finally:
        service.close()


def test_run_event_repository_pages_with_replay_metadata(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-1",
            user_goal="Replay page metadata",
        )
        service.append_run_event(run["run_id"], "agent.started", {})
        service.append_run_event(run["run_id"], "agent.tool.call", {"tool": "workspace.read"})
        service.append_run_event(run["run_id"], "agent.completed", {})

        first_page = service.list_run_events(run["run_id"], after_sequence=0, limit=2)
        second_page = service.list_run_events(
            run["run_id"],
            after_sequence=first_page["next_after_sequence"],
            limit=2,
        )

        assert [event["sequence"] for event in first_page["events"]] == [1, 2]
        assert first_page["next_after_sequence"] == 2
        assert first_page["has_more"] is True
        assert [event["sequence"] for event in second_page["events"]] == [3]
        assert second_page["next_after_sequence"] == 3
        assert second_page["has_more"] is False
    finally:
        service.close()
