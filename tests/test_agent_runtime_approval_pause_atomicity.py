"""Atomic approval-pause projection regressions."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalPauseProjection
from apps.shell.credential_store import MemoryCredentialStore


def _service(tmp_path, *, name: str = "pause") -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / f"agent-runtime-{name}.db",
        workspace_dir=tmp_path / f"runtime-{name}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )


def _pending(approval_id: str = "approval-pause") -> dict[str, object]:
    return {
        "approval_id": approval_id,
        "tool": "terminal.run",
        "input_preview": {"command": "printf ok"},
    }


def _workflow_projection() -> WorkflowApprovalPauseProjection:
    return WorkflowApprovalPauseProjection.from_criteria(
        {"id": "approval-gate", "type": "approval"},
        label="Human Gate",
        kind="approval",
        criteria="Review output",
        context="Draft ready",
        next_index=2,
        next_node_id="report",
    )


def test_agent_approval_pause_event_failure_rolls_back_run_and_local_timeline(
    tmp_path,
) -> None:
    service = _service(tmp_path, name="agent-event-fault")
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-pause",
            user_goal="Run an approved command",
        )
        timeline = list(run.get("timeline") or [])
        pause = service.approval_pause

        def fail_event(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("injected approval event failure")

        pause._append_run_event = fail_event

        with pytest.raises(RuntimeError, match="injected approval event failure"):
            pause.project_tool_required(
                run["run_id"],
                pending_approval=_pending(),
                timeline=timeline,
                artifacts=[],
            )

        persisted = service.get_run(run["run_id"])
        assert persisted["status"] == "running"
        assert persisted["pending_approval"] == {}
        assert persisted["timeline"] == []
        assert timeline == []
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_main_chat_approval_pause_event_failure_rolls_back_pending_projection(
    tmp_path,
) -> None:
    service = _service(tmp_path, name="main-chat-event-fault")
    try:
        run = service.start_main_chat_run(
            task_id="task-main-chat-pause-fault",
            session_id="session-main-chat-pause-fault",
            user_goal="Open Notes after approval",
        )
        initial_timeline = list(run.get("timeline") or [])
        local_timeline = list(initial_timeline)
        pause = service.main_chat_model_loop._approval_pause

        def fail_event(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("injected main chat approval event failure")

        pause._append_run_event = fail_event

        with pytest.raises(RuntimeError, match="main chat approval event failure"):
            pause.project_tool_required(
                run["run_id"],
                pending_approval=_pending("approval-main-chat-fault"),
                timeline=local_timeline,
                artifacts=[],
            )

        persisted = service.get_run(run["run_id"])
        assert persisted["status"] == "running"
        assert persisted["pending_approval"] == {}
        assert persisted["timeline"] == initial_timeline
        assert local_timeline == initial_timeline
        assert not any(
            event["event_type"] == "agent.tool.approval_required"
            for event in service.list_run_events(run["run_id"])["events"]
        )
    finally:
        service.close()


def test_root_agent_approval_pause_group_event_failure_rolls_back_every_fact(
    tmp_path,
) -> None:
    service = _service(tmp_path, name="agent-group-event-fault")
    try:
        group = service._insert_run_group(
            title="Approval pause root",
            source="agent",
        )
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-pause-root",
            user_goal="Run an approved command",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        timeline = list(run.get("timeline") or [])
        pause = service.approval_pause
        append_event = pause._append_run_event

        def fail_group_event(
            run_id: str,
            event_type: str,
            payload: dict[str, object],
            **kwargs: object,
        ) -> object:
            if event_type == "group.run.approval_required":
                raise RuntimeError("injected group approval event failure")
            return append_event(run_id, event_type, payload, **kwargs)

        pause._append_run_event = fail_group_event

        with pytest.raises(RuntimeError, match="group approval event failure"):
            pause.project_tool_required(
                run["run_id"],
                pending_approval=_pending("approval-root-event-fault"),
                timeline=timeline,
                artifacts=[],
            )

        persisted = service.get_run(run["run_id"])
        persisted_group = service.get_run_group(group["run_group_id"])
        assert persisted["status"] == "running"
        assert persisted["pending_approval"] == {}
        assert persisted_group["status"] == "running"
        assert timeline == []
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_agent_approval_pause_internal_trace_failure_rolls_back_public_fact(
    tmp_path,
) -> None:
    service = _service(tmp_path, name="agent-internal-trace-fault")
    try:
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-traced-pause",
            user_goal="Run a planned approved action",
        )
        pause = service.approval_pause
        append_event = pause._append_run_event

        def fail_internal_trace(
            run_id: str,
            event_type: str,
            payload: dict[str, object],
            **kwargs: object,
        ) -> object:
            if event_type == "agent.tool.approval_trace":
                raise RuntimeError("injected internal approval trace failure")
            return append_event(run_id, event_type, payload, **kwargs)

        pause._append_run_event = fail_internal_trace
        pending = {
            **_pending("approval-internal-trace-fault"),
            "plan_id": "private-plan",
            "step_id": "private-step",
            "tool_request": {
                "tool": "terminal.run",
                "input": {"command": "printf ok"},
                "plan_id": "private-plan",
                "step_id": "private-step",
            },
        }

        with pytest.raises(RuntimeError, match="internal approval trace failure"):
            pause.project_tool_required(
                run["run_id"],
                pending_approval=pending,
                timeline=[],
                artifacts=[],
            )

        persisted = service.get_run(run["run_id"])
        assert persisted["status"] == "running"
        assert persisted["pending_approval"] == {}
        assert service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"] == []
    finally:
        service.close()


def test_root_workflow_approval_pause_group_event_failure_rolls_back_every_fact(
    tmp_path,
) -> None:
    service = _service(tmp_path, name="workflow-group-event-fault")
    try:
        group = service._insert_run_group(
            title="Workflow approval pause root",
            source="workflow",
        )
        run = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-pause-root",
            user_goal="Prepare a gated report",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        timeline = list(run.get("timeline") or [])
        pause = service.workflow_continuation._approval_pause
        append_event = pause._append_run_event

        def fail_group_event(
            run_id: str,
            event_type: str,
            payload: dict[str, object],
            **kwargs: object,
        ) -> object:
            if event_type == "group.run.approval_required":
                raise RuntimeError("injected workflow group approval event failure")
            return append_event(run_id, event_type, payload, **kwargs)

        pause._append_run_event = fail_group_event

        with pytest.raises(RuntimeError, match="workflow group approval event failure"):
            pause.pause(
                run,
                _workflow_projection(),
                run_group_id=group["run_group_id"],
                timeline=timeline,
                artifacts=[],
                root_group=True,
            )

        persisted = service.get_run(run["run_id"])
        persisted_group = service.get_run_group(group["run_group_id"])
        assert persisted["status"] == "running"
        assert persisted["pending_approval"] == {}
        assert persisted_group["status"] == "running"
        assert timeline == []
        assert [
            event
            for event in service.list_run_events(run["run_id"])["events"]
            if event["event_type"].endswith("approval_required")
        ] == []
    finally:
        service.close()


def test_workflow_child_pause_cannot_project_group_from_caller_root_hint(
    tmp_path,
) -> None:
    service = _service(tmp_path, name="workflow-child-authority")
    try:
        group = service._insert_run_group(
            title="Parent-owned workflow group",
            source="workflow",
        )
        child = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-child",
            user_goal="Child gated step",
            run_group_id=group["run_group_id"],
            project_root_group=False,
        )

        result = service.workflow_continuation._approval_pause.pause(
            child,
            _workflow_projection(),
            run_group_id=group["run_group_id"],
            timeline=[],
            artifacts=[],
            root_group=True,
        )

        assert result["status"] == "approval_required"
        assert service.get_run_group(group["run_group_id"])["status"] == "running"
        event_types = [
            event["event_type"]
            for event in service.list_run_events(child["run_id"])["events"]
        ]
        assert event_types.count("workflow.node.approval_required") == 1
        assert "group.run.approval_required" not in event_types
    finally:
        service.close()


def test_owned_root_group_missing_rolls_back_agent_approval_pause(tmp_path) -> None:
    service = _service(tmp_path, name="agent-owned-group-missing")
    try:
        group = service._insert_run_group(
            title="Missing approval root",
            source="agent",
        )
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-missing-root",
            user_goal="Run an approved command",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        pause = service.approval_pause
        pause._get_run_group = lambda _run_group_id: (_ for _ in ()).throw(
            KeyError("missing injected root group")
        )

        with pytest.raises(AgentRuntimeError, match="approval_pause_root_group_missing"):
            pause.project_tool_required(
                run["run_id"],
                pending_approval=_pending("approval-missing-group"),
                timeline=[],
                artifacts=[],
            )

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"])["status"] == "running"
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_root_group_cas_loss_rolls_back_agent_approval_pause(tmp_path) -> None:
    service = _service(tmp_path, name="agent-group-cas-loss")
    try:
        group = service._insert_run_group(
            title="CAS approval root",
            source="agent",
        )
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-cas-root",
            user_goal="Run an approved command",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        pause = service.approval_pause
        pause._update_run_group = lambda *_args, **_kwargs: None

        with pytest.raises(AgentRuntimeError, match="run_group_projection_cas_lost"):
            pause.project_tool_required(
                run["run_id"],
                pending_approval=_pending("approval-group-cas-loss"),
                timeline=[],
                artifacts=[],
            )

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"])["status"] == "running"
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_agent_approval_pause_run_cas_loser_writes_no_event_or_group(tmp_path) -> None:
    service = _service(tmp_path, name="agent-run-cas-loss")
    try:
        group = service._insert_run_group(
            title="Run CAS approval root",
            source="agent",
        )
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-run-cas-root",
            user_goal="Run an approved command",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        pause = service.approval_pause
        pause._update_run = lambda *_args, **_kwargs: None
        timeline: list[dict[str, object]] = []

        result = pause.project_tool_required(
            run["run_id"],
            pending_approval=_pending("approval-run-cas-loss"),
            timeline=timeline,
            artifacts=[],
        )

        assert result["status"] == "running"
        assert timeline == []
        assert service.get_run_group(group["run_group_id"])["status"] == "running"
        assert service.list_run_events(run["run_id"])["events"] == []
    finally:
        service.close()


def test_terminal_owned_group_conflict_cannot_be_overwritten_by_pause(tmp_path) -> None:
    service = _service(tmp_path, name="agent-terminal-group-conflict")
    try:
        group = service._insert_run_group(
            title="Terminal approval root",
            source="agent",
        )
        run = service._insert_run(
            kind="agent_run",
            runnable_id="agent-terminal-group-root",
            user_goal="Run an approved command",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        completed_group = service._update_run_group(
            group["run_group_id"],
            status="completed",
            summary="another terminal winner",
        )
        assert completed_group is not None

        with pytest.raises(AgentRuntimeError, match="terminal_outcome_conflict"):
            service.approval_pause.project_tool_required(
                run["run_id"],
                pending_approval=_pending("approval-after-terminal-group"),
                timeline=[],
                artifacts=[],
            )

        assert service.get_run(run["run_id"])["status"] == "running"
        assert service.get_run_group(group["run_group_id"])["status"] == "completed"
        approval_events = [
            event
            for event in service.list_run_events(run["run_id"])["events"]
            if event["event_type"].endswith("approval_required")
        ]
        assert approval_events == []
    finally:
        service.close()


def test_two_connections_commit_one_root_agent_approval_pause_winner(
    tmp_path,
) -> None:
    db_path = tmp_path / "agent-runtime-two-connection.db"
    workspace_dir = tmp_path / "runtime-two-connection"
    credential_store = MemoryCredentialStore()
    first = AgentRuntimeService(
        db_path=db_path,
        workspace_dir=workspace_dir,
        credential_store=credential_store,
        seed_templates=False,
    )
    second = AgentRuntimeService(
        db_path=db_path,
        workspace_dir=workspace_dir,
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        group = first._insert_run_group(
            title="Concurrent approval root",
            source="agent",
        )
        run = first._insert_run(
            kind="agent_run",
            runnable_id="agent-concurrent-root",
            user_goal="Run an approved command",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        barrier = threading.Barrier(2)
        timelines: list[list[dict[str, object]]] = [[], []]

        def project(
            service: AgentRuntimeService,
            timeline: list[dict[str, object]],
        ) -> dict[str, object]:
            barrier.wait(timeout=5)
            return service.approval_pause.project_tool_required(
                run["run_id"],
                pending_approval=_pending("approval-concurrent-winner"),
                timeline=timeline,
                artifacts=[],
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(project, first, timelines[0]),
                executor.submit(project, second, timelines[1]),
            ]
            results = [future.result(timeout=10) for future in futures]

        assert [result["status"] for result in results] == [
            "approval_required",
            "approval_required",
        ]
        assert sorted(len(timeline) for timeline in timelines) == [0, 1]
        persisted = first.get_run(run["run_id"])
        persisted_group = first.get_run_group(group["run_group_id"])
        assert persisted["status"] == "approval_required"
        assert persisted_group["status"] == "approval_required"
        event_types = [
            event["event_type"]
            for event in first.list_run_events(run["run_id"])["events"]
        ]
        assert event_types.count("agent.tool.approval_required") == 1
        assert event_types.count("group.run.approval_required") == 1
    finally:
        second.close()
        first.close()
