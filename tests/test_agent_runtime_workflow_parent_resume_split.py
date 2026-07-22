"""Tests for workflow parent resume coordinator split out of the legacy runtime."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_parent_resume import WorkflowParentResumeCoordinator
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_workflow_parent_resume_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowParentResumeCoordinator is WorkflowParentResumeCoordinator


def test_parent_terminal_winner_blocks_late_child_approval_projection() -> None:
    parent = {
        "run_id": "workflow-parent-race",
        "run_group_id": "workflow-group-race",
        "status": "running",
        "result": "",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "2026-07-11T10:00:00+00:00",
    }
    child = {
        "run_id": "workflow-child-race",
        "status": "approval_required",
        "result": "waiting for desktop.open_app approval",
        "runnable_name": "Desktop child",
    }
    appended_events: list[tuple[str, str, dict[str, object]]] = []
    group_updates: list[tuple[str, dict[str, object]]] = []

    def update_run(_run_id: str, **fields: object):
        assert fields["expected_status"] == "running"
        assert fields["expected_updated_at"] == "2026-07-11T10:00:00+00:00"
        assert fields["expected_pending_approval_absent"] is True
        parent.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="2026-07-11T10:00:01+00:00",
        )
        return None

    coordinator = WorkflowParentResumeCoordinator(
        parent_runs_waiting_for_child=lambda _child: [dict(parent)],
        workflow_run_is_group_root=lambda _run: True,
        workflow_child_node_context=lambda _timeline, _child: (
            "Desktop child",
            {
                "workflow_node_id": "agent-node",
                "workflow_node_kind": "agent",
                "workflow_node_label": "Desktop child",
            },
        ),
        merge_workflow_child_run_outcome=lambda *_args: None,
        workflow_for_run_resume=lambda _run: {},
        workflow_resume_start_index=lambda *_args: None,
        continue_workflow_run=lambda run, _workflow, **_kwargs: run,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        update_run_group=lambda run_group_id, **fields: group_updates.append(
            (run_group_id, fields)
        ),
        get_run=lambda _run_id: dict(parent),
    )

    result = coordinator.resume_parent_after_child_update(dict(parent), child)

    assert result["status"] == "cancelled"
    assert result["result"] == "cancelled by user"
    assert appended_events == []
    assert group_updates == []


def test_parent_terminal_winner_blocks_stale_child_running_projection() -> None:
    parent = {
        "run_id": "workflow-parent-running-race",
        "run_group_id": "workflow-group-running-race",
        "status": "approval_required",
        "result": "waiting for child approval",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "2026-07-12T10:00:00+00:00",
    }
    child = {
        "run_id": "workflow-child-running-race",
        "status": "running",
        "result": "child resumed",
        "runnable_name": "Desktop child",
    }
    appended_events: list[tuple[str, str, dict[str, object]]] = []
    group_updates: list[tuple[str, dict[str, object]]] = []

    def update_run(_run_id: str, **fields: object):
        assert fields["expected_status"] == "approval_required"
        assert fields["expected_updated_at"] == "2026-07-12T10:00:00+00:00"
        assert fields["expected_pending_approval_absent"] is True
        parent.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="2026-07-12T10:00:01+00:00",
        )
        return None

    coordinator = WorkflowParentResumeCoordinator(
        parent_runs_waiting_for_child=lambda _child: [dict(parent)],
        workflow_run_is_group_root=lambda _run: True,
        workflow_child_node_context=lambda _timeline, _child: (
            "Desktop child",
            {
                "workflow_node_id": "agent-node",
                "workflow_node_kind": "agent",
                "workflow_node_label": "Desktop child",
            },
        ),
        merge_workflow_child_run_outcome=lambda *_args: None,
        workflow_for_run_resume=lambda _run: {},
        workflow_resume_start_index=lambda *_args: None,
        continue_workflow_run=lambda run, _workflow, **_kwargs: run,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        update_run_group=lambda run_group_id, **fields: group_updates.append(
            (run_group_id, fields)
        ),
        get_run=lambda _run_id: dict(parent),
    )

    coordinator.mark_child_running(child)

    assert parent["status"] == "cancelled"
    assert appended_events == []
    assert group_updates == []


def test_parent_terminal_winner_blocks_stale_child_failure_projection() -> None:
    parent = {
        "run_id": "workflow-parent-failure-race",
        "run_group_id": "workflow-group-failure-race",
        "status": "running",
        "result": "",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "parent-failure-version-1",
    }
    child = {
        "run_id": "workflow-child-failure-race",
        "status": "failed",
        "result": "child failed",
        "runnable_name": "Desktop child",
    }
    events: list[tuple[str, str, dict[str, object]]] = []
    groups: list[tuple[str, dict[str, object]]] = []

    def update_run(_run_id: str, **fields: object):
        assert fields["expected_status"] == "running"
        assert fields["expected_updated_at"] == "parent-failure-version-1"
        assert fields["expected_pending_approval_absent"] is True
        parent.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="parent-failure-version-2",
        )
        return None

    coordinator = WorkflowParentResumeCoordinator(
        parent_runs_waiting_for_child=lambda _child: [dict(parent)],
        workflow_run_is_group_root=lambda _run: True,
        workflow_child_node_context=lambda _timeline, _child: (
            "Desktop child",
            {"workflow_node_id": "agent-node", "workflow_node_kind": "agent"},
        ),
        merge_workflow_child_run_outcome=lambda *_args: None,
        workflow_for_run_resume=lambda _run: {},
        workflow_resume_start_index=lambda *_args: None,
        continue_workflow_run=lambda run, _workflow, **_kwargs: run,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        update_run_group=lambda run_group_id, **fields: groups.append(
            (run_group_id, fields)
        ),
        get_run=lambda _run_id: dict(parent),
    )

    result = coordinator.resume_parent_after_child_update(dict(parent), child)

    assert result["status"] == "cancelled"
    assert events == []
    assert groups == []


def test_parent_terminal_winner_blocks_stale_resume_exception_projection() -> None:
    parent = {
        "run_id": "workflow-parent-exception-race",
        "run_group_id": "workflow-group-exception-race",
        "status": "running",
        "result": "",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "parent-exception-version-1",
    }
    child = {
        "run_id": "workflow-child-exception-race",
        "status": "completed",
        "result": "child completed",
        "runnable_name": "Desktop child",
    }
    events: list[tuple[str, str, dict[str, object]]] = []
    groups: list[tuple[str, dict[str, object]]] = []

    def update_run(_run_id: str, **fields: object):
        assert fields["expected_status"] == "running"
        assert fields["expected_updated_at"] == "parent-exception-version-1"
        assert fields["expected_pending_approval_absent"] is True
        parent.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="parent-exception-version-2",
        )
        return None

    coordinator = WorkflowParentResumeCoordinator(
        parent_runs_waiting_for_child=lambda _child: [dict(parent)],
        workflow_run_is_group_root=lambda _run: True,
        workflow_child_node_context=lambda _timeline, _child: (
            "Desktop child",
            {"workflow_node_id": "agent-node", "workflow_node_kind": "agent"},
        ),
        merge_workflow_child_run_outcome=lambda *_args: None,
        workflow_for_run_resume=lambda _run: (_ for _ in ()).throw(
            RuntimeError("resume failed")
        ),
        workflow_resume_start_index=lambda *_args: None,
        continue_workflow_run=lambda run, _workflow, **_kwargs: run,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        update_run_group=lambda run_group_id, **fields: groups.append(
            (run_group_id, fields)
        ),
        get_run=lambda _run_id: dict(parent),
    )

    result = coordinator.resume_parent_after_child_update(dict(parent), child)

    assert result["status"] == "cancelled"
    assert events == []
    assert groups == []


def _native_parent_resume_fixture(tmp_path, *, child_status: str = "failed"):
    service = AgentRuntimeService(
        db_path=tmp_path / f"workflow-parent-{child_status}.db",
        workspace_dir=tmp_path / f"runtime-{child_status}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    group = service._insert_run_group(
        title="Atomic workflow parent",
        source="workflow",
    )
    parent = service._insert_run(
        kind="workflow_run",
        runnable_id="workflow-parent-atomic",
        user_goal="project child outcome atomically",
        run_group_id=group["run_group_id"],
    )
    child = service._insert_run(
        kind="agent_run",
        runnable_id="agent-child-atomic",
        user_goal="produce child outcome",
        run_group_id=group["run_group_id"],
    )
    parent_timeline = [
        {
            "event": "workflow.node.agent",
            "detail": "Atomic child",
            "child_run_id": child["run_id"],
            "status": "running",
            "workflow_node_id": "child-node",
            "workflow_node_kind": "agent",
            "workflow_node_label": "Atomic child",
        }
    ]
    parent = service._update_run(
        parent["run_id"],
        status="running",
        timeline=parent_timeline,
        pending_approval=None,
    )
    child = service._update_run(
        child["run_id"],
        status=child_status,
        result=("child completed" if child_status == "completed" else "child failed"),
        pending_approval=None,
    )
    assert parent is not None
    assert child is not None
    return service, parent, child, group


def _parent_resume_persistence_snapshot(
    service: AgentRuntimeService,
    parent: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return (
        service.get_run(parent["run_id"]),
        service.get_run_group(parent["run_group_id"]),
        service.list_run_events(parent["run_id"], include_internal=True)["events"],
    )


def _native_parent_nonterminal_fixture(
    tmp_path,
    *,
    parent_status: str,
    child_status: str,
):
    service = AgentRuntimeService(
        db_path=tmp_path / f"workflow-parent-{parent_status}-{child_status}.db",
        workspace_dir=tmp_path / f"runtime-{parent_status}-{child_status}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    group = service._insert_run_group(
        title="Nonterminal workflow parent",
        source="workflow",
    )
    parent = service._insert_run(
        kind="workflow_run",
        runnable_id="workflow-parent-nonterminal",
        user_goal="resume parent safely",
        run_group_id=group["run_group_id"],
        project_root_group=True,
    )
    child = service._insert_run(
        kind="agent_run",
        runnable_id="agent-child-nonterminal",
        user_goal="pause or complete child",
        run_group_id=group["run_group_id"],
        project_root_group=False,
    )
    timeline = [
        {
            "event": "workflow.node.agent",
            "detail": "Nonterminal child",
            "child_run_id": child["run_id"],
            "status": "running",
            "workflow_node_id": "child-node",
            "workflow_node_kind": "agent",
            "workflow_node_label": "Nonterminal child",
        }
    ]
    if parent_status == "approval_required":
        timeline.append(
            {
                "event": "workflow.run.approval_required",
                "detail": "Nonterminal child",
                "child_run_id": child["run_id"],
                "status": "approval_required",
                "workflow_node_id": "child-node",
                "workflow_node_kind": "agent",
                "workflow_node_label": "Nonterminal child",
            }
        )
    parent = service._update_run(
        parent["run_id"],
        status=parent_status,
        result=("waiting for child" if parent_status == "approval_required" else ""),
        timeline=timeline,
        pending_approval=None,
    )
    child = service._update_run(
        child["run_id"],
        status=child_status,
        result=f"child {child_status}",
        pending_approval=None,
    )
    projected_group = service._update_run_group(
        group["run_group_id"],
        status=parent_status,
        summary=("waiting for child" if parent_status == "approval_required" else ""),
    )
    assert parent is not None
    assert child is not None
    assert projected_group is not None
    return service, parent, child


@pytest.mark.parametrize(
    ("operation", "failed_alias"),
    (
        ("completed_resume", "workflow.resumed"),
        ("child_approval", "workflow.paused_for_approval"),
        ("child_approval_group_event", "group.run.approval_required"),
        ("child_running", "workflow.node.started"),
    ),
)
def test_native_parent_nonterminal_projection_rolls_back_on_alias_fault(
    tmp_path,
    operation: str,
    failed_alias: str,
) -> None:
    parent_status = (
        "running" if operation.startswith("child_approval") else "approval_required"
    )
    child_status = {
        "completed_resume": "completed",
        "child_approval": "approval_required",
        "child_approval_group_event": "approval_required",
        "child_running": "running",
    }[operation]
    service, parent, child = _native_parent_nonterminal_fixture(
        tmp_path,
        parent_status=parent_status,
        child_status=child_status,
    )
    try:
        before = _parent_resume_persistence_snapshot(service, parent)
        parent_input = deepcopy(parent)
        repository = service.runtime_events._repository
        original_append = repository.append

        def fail_alias(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == failed_alias:
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        repository.append = fail_alias

        with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
            if operation == "child_running":
                service.workflow_parent_resume.mark_child_running(child)
            else:
                service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert _parent_resume_persistence_snapshot(service, parent) == before
        assert parent == parent_input
    finally:
        service.close()


def test_native_parent_child_approval_rolls_back_on_owned_group_cas_loss(tmp_path) -> None:
    service, parent, child = _native_parent_nonterminal_fixture(
        tmp_path,
        parent_status="running",
        child_status="approval_required",
    )
    try:
        before = _parent_resume_persistence_snapshot(service, parent)
        service.workflow_parent_resume._approval_pause._update_run_group = (
            lambda *_args, **_kwargs: None
        )

        with pytest.raises(AgentRuntimeError, match="run_group_projection_cas_lost"):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert _parent_resume_persistence_snapshot(service, parent) == before
    finally:
        service.close()


def test_native_completed_child_resume_rolls_back_on_owned_group_cas_loss(
    tmp_path,
) -> None:
    service, parent, child = _native_parent_nonterminal_fixture(
        tmp_path,
        parent_status="approval_required",
        child_status="completed",
    )
    try:
        before = _parent_resume_persistence_snapshot(service, parent)
        service.workflow_parent_resume._update_run_group = lambda *_args, **_kwargs: None

        with pytest.raises(AgentRuntimeError, match="run_group_projection_cas_lost"):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert _parent_resume_persistence_snapshot(service, parent) == before
    finally:
        service.close()


def test_completed_child_next_approval_fault_preserves_running_resume_checkpoint(
    tmp_path,
) -> None:
    service, parent, child = _native_parent_nonterminal_fixture(
        tmp_path,
        parent_status="approval_required",
        child_status="completed",
    )
    try:
        workflow = {
            "workflow_id": "workflow-parent-next-approval",
            "name": "Parent next approval",
            "nodes": [
                {"id": "start", "type": "start", "data": {"label": "Start"}},
                {
                    "id": "gate",
                    "type": "approval",
                    "data": {"label": "Human Gate", "criteria": "Review"},
                },
            ],
            "edges": [{"source": "start", "target": "gate"}],
        }
        service.workflow_parent_resume._workflow_for_run_resume = lambda _run: workflow
        service.workflow_parent_resume._workflow_resume_start_index = (
            lambda _workflow, _run, _child_run_id: 1
        )
        repository = service.runtime_events._repository
        original_append = repository.append

        def fail_alias(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == "workflow.paused_for_approval":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        repository.append = fail_alias

        with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        checkpoint = service.get_run(parent["run_id"])
        assert checkpoint["status"] == "running"
        assert checkpoint["result"] == "child completed"
        assert checkpoint["pending_approval"] == {}
        assert any(
            event.get("event") == "workflow.run.resumed"
            for event in checkpoint["timeline"]
        )
        assert not any(
            event.get("event") in {
                "workflow.node.approval_required",
                "workflow.run.failed",
            }
            for event in checkpoint["timeline"]
        )
        assert service.get_run_group(parent["run_group_id"])["status"] == "running"
        event_types = [
            event["event_type"]
            for event in service.list_run_events(
                parent["run_id"],
                include_internal=True,
            )["events"]
        ]
        assert "workflow.run.resumed" in event_types
        assert "workflow.run.failed" not in event_types
        assert "workflow.node.approval_required" not in event_types

        repository.append = original_append
        retried = service.workflow_parent_resume.resume_parent_after_child_update(
            checkpoint,
            child,
        )

        assert retried["status"] == "approval_required"
        assert retried["pending_approval"]["tool"] == "workflow.approval"
        retried_event_types = [
            event["event_type"]
            for event in service.list_run_events(
                parent["run_id"],
                include_internal=True,
            )["events"]
        ]
        assert retried_event_types.count("workflow.run.resumed") == 1
        assert retried_event_types.count("workflow.node.approval_required") == 1
    finally:
        service.close()


def test_double_connection_terminal_winner_blocks_stale_parent_resume(tmp_path) -> None:
    service, parent, child = _native_parent_nonterminal_fixture(
        tmp_path,
        parent_status="running",
        child_status="approval_required",
    )
    peer = AgentRuntimeService(
        db_path=tmp_path / "workflow-parent-running-approval_required.db",
        workspace_dir=tmp_path / "runtime-peer",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        winner = peer._update_run(
            parent["run_id"],
            status="cancelled",
            result="cancelled by peer",
            pending_approval=None,
        )
        assert winner is not None
        before_group = service.get_run_group(parent["run_group_id"])
        before_events = service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"]

        result = service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert result["status"] == "cancelled"
        assert result["result"] == "cancelled by peer"
        assert service.get_run_group(parent["run_group_id"]) == before_group
        assert service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        peer.close()
        service.close()


def test_double_connection_newer_running_generation_blocks_stale_child_pause(
    tmp_path,
) -> None:
    service, parent, child = _native_parent_nonterminal_fixture(
        tmp_path,
        parent_status="running",
        child_status="approval_required",
    )
    peer = AgentRuntimeService(
        db_path=tmp_path / "workflow-parent-running-approval_required.db",
        workspace_dir=tmp_path / "runtime-peer-running-generation",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        parent_input = deepcopy(parent)
        peer_timeline = [
            *parent["timeline"],
            {
                "event": "workflow.peer.checkpoint",
                "detail": "newer continuation generation",
            },
        ]
        original_get_run = service.workflow_parent_resume._get_run
        first_read = True

        def stale_read_after_peer_wins(run_id: str) -> dict[str, Any]:
            nonlocal first_read
            if first_read:
                first_read = False
                winner = peer._update_run(
                    run_id,
                    status="running",
                    result="peer advanced continuation",
                    timeline=peer_timeline,
                    pending_approval=None,
                )
                assert winner is not None
                return deepcopy(parent)
            return original_get_run(run_id)

        service.workflow_parent_resume._get_run = stale_read_after_peer_wins
        before_group = service.get_run_group(parent["run_group_id"])
        before_events = service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"]

        result = service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert result["status"] == "running"
        assert result["result"] == "peer advanced continuation"
        assert result["timeline"] == peer_timeline
        assert service.get_run_group(parent["run_group_id"]) == before_group
        assert service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert parent == parent_input
    finally:
        peer.close()
        service.close()


@pytest.mark.parametrize(
    ("child_status", "failed_alias"),
    (("failed", "workflow.failed"), ("cancelled", "workflow.cancelled")),
)
def test_native_parent_terminal_child_rolls_back_when_workflow_alias_event_is_fenced(
    tmp_path,
    child_status: str,
    failed_alias: str,
) -> None:
    service, parent, child, _group = _native_parent_resume_fixture(
        tmp_path,
        child_status=child_status,
    )
    try:
        parent_input = deepcopy(parent)
        before = _parent_resume_persistence_snapshot(service, parent)
        repository = service.runtime_events._repository
        original_append = repository.append

        def fail_workflow_alias(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == failed_alias:
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        repository.append = fail_workflow_alias

        with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert _parent_resume_persistence_snapshot(service, parent) == before
        assert parent == parent_input
    finally:
        service.close()


def test_native_parent_resume_failure_fault_preserves_committed_resume_checkpoint(
    tmp_path,
) -> None:
    service, parent, child, _group = _native_parent_resume_fixture(
        tmp_path,
        child_status="completed",
    )
    try:
        parent_input = deepcopy(parent)
        before = _parent_resume_persistence_snapshot(service, parent)
        repository = service.runtime_events._repository
        original_append = repository.append
        original_workflow_for_resume = service.workflow_parent_resume._workflow_for_run_resume

        def fail_group_event(
            run_id: str,
            event_type: str,
            payload: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> dict[str, Any] | None:
            if event_type == "group.run.failed":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        repository.append = fail_group_event
        service.workflow_parent_resume._workflow_for_run_resume = (
            lambda _run: (_ for _ in ()).throw(RuntimeError("resume failed"))
        )

        with pytest.raises(AgentRuntimeError, match="run_group_event_fence_mismatch"):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        resumed_run, resumed_group, resumed_events = _parent_resume_persistence_snapshot(
            service,
            parent,
        )
        assert resumed_run["status"] == "running"
        assert resumed_run["result"] == "child completed"
        assert any(
            event.get("event") == "workflow.run.resumed"
            for event in resumed_run["timeline"]
        )
        assert resumed_group == before[1]
        resumed_event_types = [event["event_type"] for event in resumed_events]
        assert "workflow.run.resumed" in resumed_event_types
        assert "workflow.resumed" in resumed_event_types
        assert "workflow.run.failed" not in resumed_event_types
        assert "workflow.failed" not in resumed_event_types
        assert "group.run.failed" not in resumed_event_types
        assert parent == parent_input
        service.workflow_parent_resume._workflow_for_run_resume = original_workflow_for_resume
    finally:
        service.close()


def test_native_parent_child_failure_rolls_back_when_root_group_cas_is_lost(
    tmp_path,
) -> None:
    service, parent, child, _group = _native_parent_resume_fixture(tmp_path)
    try:
        before = _parent_resume_persistence_snapshot(service, parent)
        service.workflow_parent_resume._update_run_group = lambda *_args, **_kwargs: None

        with pytest.raises(AgentRuntimeError, match="run_group_projection_cas_lost"):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert _parent_resume_persistence_snapshot(service, parent) == before
    finally:
        service.close()


def test_native_parent_terminal_projection_fails_closed_when_root_group_is_missing(
    tmp_path,
) -> None:
    service, parent, child, _group = _native_parent_resume_fixture(tmp_path)
    try:
        before_run = service.get_run(parent["run_id"])
        before_events = service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"]
        service._conn.execute(
            "DELETE FROM run_groups WHERE run_group_id=?",
            (parent["run_group_id"],),
        )
        service._conn.commit()

        with pytest.raises(AgentRuntimeError, match="run_group_projection_missing"):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        after_run = service.get_run(parent["run_id"])
        for field in ("status", "result", "timeline", "artifacts", "updated_at"):
            assert after_run[field] == before_run[field]
        assert service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


def test_native_parent_terminal_projection_accepts_same_group_winner_idempotently(
    tmp_path,
) -> None:
    service, parent, child, _group = _native_parent_resume_fixture(tmp_path)
    try:
        same_group = service._update_run_group(
            parent["run_group_id"],
            status="failed",
            summary=str(child["result"]),
        )
        assert same_group is not None
        before_group_events = [
            event
            for event in service.list_run_events(
                parent["run_id"],
                include_internal=True,
            )["events"]
            if event["event_type"] == "group.run.failed"
        ]

        result = service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert result["status"] == "failed"
        assert result["result"] == child["result"]
        assert service.get_run_group(parent["run_group_id"]) == same_group
        after_group_events = [
            event
            for event in service.list_run_events(
                parent["run_id"],
                include_internal=True,
            )["events"]
            if event["event_type"] == "group.run.failed"
        ]
        assert after_group_events == before_group_events
    finally:
        service.close()


def test_native_parent_terminal_projection_rejects_different_group_winner(
    tmp_path,
) -> None:
    service, parent, child, _group = _native_parent_resume_fixture(tmp_path)
    try:
        winner_group = service._update_run_group(
            parent["run_group_id"],
            status="failed",
            summary="winner summary",
        )
        assert winner_group is not None
        before_run = service.get_run(parent["run_id"])
        before_events = service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"]

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_terminal_outcome_conflict",
        ):
            service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert service.get_run(parent["run_id"]) == before_run
        assert service.get_run_group(parent["run_group_id"]) == winner_group
        assert service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"] == before_events
    finally:
        service.close()


def test_native_parent_run_cas_loser_writes_no_events_or_group_projection(tmp_path) -> None:
    service, parent, child, _group = _native_parent_resume_fixture(tmp_path)
    try:
        before_run, before_group, before_events = _parent_resume_persistence_snapshot(
            service,
            parent,
        )
        original_update_run = service.workflow_parent_resume._update_run

        def lose_parent_cas(run_id: str, **_fields: Any) -> None:
            winner = original_update_run(
                run_id,
                status="cancelled",
                result="cancelled by winner",
                pending_approval=None,
            )
            assert winner is not None
            return None

        service.workflow_parent_resume._update_run = lose_parent_cas

        result = service.workflow_parent_resume.resume_parent_after_child_update(parent, child)

        assert result["status"] == "cancelled"
        assert result["result"] == "cancelled by winner"
        assert service.get_run_group(parent["run_group_id"]) == before_group
        assert service.list_run_events(
            parent["run_id"],
            include_internal=True,
        )["events"] == before_events
        assert service.get_run(parent["run_id"])["timeline"] == before_run["timeline"]
    finally:
        service.close()
