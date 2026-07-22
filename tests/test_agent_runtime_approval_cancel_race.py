"""Deterministic approval-resume versus cancellation race regressions."""

from __future__ import annotations

import json
from functools import partial
from typing import Any

from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalPauseProjection
from tests.test_agent_runtime import (
    FakeDefaultProfileService,
    make_service as make_runtime_service,
)


def make_service(tmp_path):
    """Keep approval race fixtures focused on the approval transition seam."""

    service = make_runtime_service(tmp_path)
    service.main_chat_model_loop._resolve_initial_model_plan = None
    service.main_chat_model_loop._continue_custom_api_agent = partial(
        service.main_chat_model_loop._continue_custom_api_agent,
        start_iteration=1,
    )
    return service


def _terminal_goal_contract(*, original_goal: str, command: str) -> GoalContract:
    return GoalContract(
        contract_id="goal-contract-approval-cancel-race",
        original_goal=original_goal,
        intent_kind="code_task",
        criteria=(
            GoalCriterion(
                criterion_id="goal-criterion-approval-cancel-race",
                description="Run the exact command approved by the user",
                effectful=True,
                required_capabilities=("terminal.execution",),
                expected={
                    "target": {
                        "kind": "local_compute",
                        "command": command,
                    },
                },
                source_step_ids=("run-approved-terminal-command",),
            ),
        ),
    )


def _waiting_terminal_run(service: Any, monkeypatch: Any) -> tuple[dict[str, Any], list[Any]]:
    original_goal = "Run a terminal command"
    command = "printf approval-cancel-race"
    goal_contract = _terminal_goal_contract(
        original_goal=original_goal,
        command=command,
    )
    monkeypatch.setattr(
        "apps.shell.agent.runtime.main_chat_model_loop.planned_goal_contract_payload",
        lambda goal, *, allowed_tools: (
            goal_contract.to_payload()
            if goal == original_goal and "terminal.run" in allowed_tools
            else {}
        ),
    )
    model_calls: list[Any] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        if len(model_calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_cancel_race",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps(
                                {"command": command}
                            ),
                        },
                    }
                ],
            }
        return {"content": "must not revive a cancelled run"}

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )
    run = service.start_main_chat_run(
        task_id="task-approval-cancel-race",
        session_id="session-approval-cancel-race",
        user_goal=original_goal,
    )
    waiting = service.execute_main_chat_model_loop(
        run["run_id"],
        [{"role": "user", "content": "Run it"}],
        tool_policy={"allowed_tools": ["terminal.run"]},
    )
    assert waiting["status"] == "approval_required"
    assert waiting["pending_approval"]["approval_id"]
    return waiting, model_calls


def test_cancel_after_approval_row_claim_wins_before_resume_projection(
    tmp_path,
    monkeypatch,
) -> None:
    service = make_service(tmp_path)
    tool_calls: list[str] = []
    try:
        waiting, model_calls = _waiting_terminal_run(service, monkeypatch)
        run_id = waiting["run_id"]
        approval_id = waiting["pending_approval"]["approval_id"]
        original_claim = service.approval_resume._claim_pending_approval

        def claim_then_cancel(
            claimed_run_id: str,
            pending: dict[str, Any],
            *,
            expected_approval_id: str,
        ) -> bool:
            claimed = original_claim(
                claimed_run_id,
                pending,
                expected_approval_id=expected_approval_id,
            )
            assert claimed is True
            cancelled = service.cancel_run(claimed_run_id)
            assert cancelled["status"] == "cancelled"
            return claimed

        monkeypatch.setattr(
            service.approval_resume,
            "_claim_pending_approval",
            claim_then_cancel,
        )
        monkeypatch.setattr(
            service.approval_resume,
            "_call_agent_tool",
            lambda *_args, **_kwargs: tool_calls.append("called") or {"ok": True},
        )

        result = service.approve_run_approval(run_id, approval_id)

        assert result["status"] == "cancelled"
        assert service.get_run(run_id)["status"] == "cancelled"
        assert tool_calls == []
        assert len(model_calls) == 1
        assert not any(
            event.get("event") in {
                "agent.tool.approval_approved",
                "agent.run.resumed",
            }
            for event in service.get_run(run_id)["timeline"]
        )
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run_id)["events"]
        ]
        assert "agent.tool.approval_approved" not in event_types
        assert "agent.run.resumed" not in event_types
    finally:
        service.close()


def test_cancel_at_last_active_check_prevents_external_tool_call(
    tmp_path,
    monkeypatch,
) -> None:
    service = make_service(tmp_path)
    tool_calls: list[str] = []
    try:
        waiting, model_calls = _waiting_terminal_run(service, monkeypatch)
        run_id = waiting["run_id"]
        approval_id = waiting["pending_approval"]["approval_id"]
        original_active_check = service.run_approvals.assert_approval_resume_active

        def cancel_then_check(active_run_id: str, expected_approval_id: str) -> None:
            cancelled = service.cancel_run(active_run_id)
            assert cancelled["status"] == "cancelled"
            original_active_check(active_run_id, expected_approval_id)

        monkeypatch.setattr(
            service.tool_approval_resume,
            "_assert_approval_resume_active",
            cancel_then_check,
            raising=False,
        )
        monkeypatch.setattr(
            service.approval_resume,
            "_call_agent_tool",
            lambda *_args, **_kwargs: tool_calls.append("called") or {"ok": True},
        )

        result = service.approve_run_approval(run_id, approval_id)

        assert result["status"] == "cancelled"
        assert service.get_run(run_id)["status"] == "cancelled"
        assert tool_calls == []
        assert len(model_calls) == 1
    finally:
        service.close()


def test_cancel_during_external_tool_cannot_be_revived_by_later_projection(
    tmp_path,
    monkeypatch,
) -> None:
    service = make_service(tmp_path)
    tool_calls: list[str] = []
    try:
        waiting, model_calls = _waiting_terminal_run(service, monkeypatch)
        run_id = waiting["run_id"]
        approval_id = waiting["pending_approval"]["approval_id"]

        def cancel_during_tool(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            tool_calls.append("called")
            cancelled = service.cancel_run(run_id)
            assert cancelled["status"] == "cancelled"
            return {"ok": True, "summary": "external effect may already have happened"}

        monkeypatch.setattr(
            service.approval_resume,
            "_call_agent_tool",
            cancel_during_tool,
        )

        result = service.approve_run_approval(run_id, approval_id)

        assert result["status"] == "cancelled"
        assert service.get_run(run_id)["status"] == "cancelled"
        assert tool_calls == ["called"]
        assert len(model_calls) == 1
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run_id)["events"]
        ]
        assert {"agent.run.cancelled", "run.cancelled"}.intersection(event_types)
        assert "agent.run.failed" not in event_types
        assert "model.output.completed" not in event_types
        internal_events = service.list_run_events(
            run_id,
            include_internal=True,
        )["events"]
        receipts = [
            event
            for event in internal_events
            if event["event_type"] == "agent.tool.executed_after_claim"
        ]
        assert len(receipts) == 1
        assert receipts[0]["payload"]["approval_id"] == approval_id
        assert receipts[0]["payload"]["completion_evidence"] is False
        assert receipts[0]["payload"]["goal_evidence"] is False
        assert not any(
            event["event_type"] == "agent.tool.outcome"
            and event["payload"].get("approved") is True
            for event in internal_events
        )
    finally:
        service.close()


def test_cancel_after_workflow_approval_claim_wins_before_resume_projection(
    tmp_path,
    monkeypatch,
) -> None:
    service = make_service(tmp_path)
    try:
        workflow = service.create_workflow(
            {
                "name": "Workflow approval cancellation race",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {"label": "Human Gate", "criteria": "Review first"},
                    },
                    {
                        "id": "summary",
                        "type": "artifact",
                        "data": {"label": "Summary"},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "summary"},
                ],
            }
        )
        waiting = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Do not resume after cancellation",
            }
        )
        assert waiting["status"] == "approval_required"
        run_id = waiting["run_id"]
        approval_id = waiting["pending_approval"]["approval_id"]
        original_claim = service.workflow_approval_resume._claim_pending_approval

        def claim_then_cancel(
            claimed_run_id: str,
            pending: dict[str, Any],
            *,
            expected_approval_id: str,
        ) -> bool:
            claimed = original_claim(
                claimed_run_id,
                pending,
                expected_approval_id=expected_approval_id,
            )
            assert claimed is True
            cancelled = service.cancel_run(claimed_run_id)
            assert cancelled["status"] == "cancelled"
            return claimed

        monkeypatch.setattr(
            service.workflow_approval_resume,
            "_claim_pending_approval",
            claim_then_cancel,
        )

        result = service.approve_run_approval(run_id, approval_id)

        assert result["status"] == "cancelled"
        current = service.get_run(run_id)
        assert current["status"] == "cancelled"
        assert not any(
            event.get("event")
            in {
                "workflow.node.approval_approved",
                "workflow.run.completed",
            }
            for event in current["timeline"]
        )
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run_id)["events"]
        ]
        assert "workflow.node.approval_approved" not in event_types
        assert "workflow.run.completed" not in event_types
    finally:
        service.close()


def test_cancel_after_workflow_approval_cas_fences_downstream_continuation(
    tmp_path,
    monkeypatch,
) -> None:
    service = make_service(tmp_path)
    artifact_writes: list[str] = []
    try:
        workflow = service.create_workflow(
            {
                "name": "Workflow continuation cancellation race",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {"label": "Human Gate", "criteria": "Review first"},
                    },
                    {
                        "id": "summary",
                        "type": "artifact",
                        "data": {"label": "Summary"},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "summary"},
                ],
            }
        )
        waiting = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Stop before downstream workflow effects",
            }
        )
        run_id = waiting["run_id"]
        approval_id = waiting["pending_approval"]["approval_id"]
        original_approve = service.workflow_continuation._approve_workflow_node_callback
        original_artifact_write = (
            service.workflow_continuation._workflow_artifact_write_callback
        )
        assert callable(original_approve)
        assert callable(original_artifact_write)

        def approve_then_cancel(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            running = original_approve(*args, **kwargs)
            assert running is not None
            assert running["status"] == "running"
            cancelled = service.cancel_run(run_id)
            assert cancelled["status"] == "cancelled"
            return running

        def record_artifact_write(*args: Any, **kwargs: Any) -> dict[str, Any]:
            artifact_writes.append("called")
            return original_artifact_write(*args, **kwargs)

        monkeypatch.setattr(
            service.workflow_continuation,
            "_approve_workflow_node_callback",
            approve_then_cancel,
        )
        monkeypatch.setattr(
            service.workflow_continuation,
            "_workflow_artifact_write_callback",
            record_artifact_write,
        )

        result = service.approve_run_approval(run_id, approval_id)

        assert result["status"] == "cancelled"
        current = service.get_run(run_id)
        assert current["status"] == "cancelled"
        assert service.get_run_group(waiting["run_group_id"])["status"] == "cancelled"
        assert artifact_writes == []
        assert not any(
            event.get("event")
            in {
                "workflow.node.artifact",
                "workflow.run.completed",
            }
            for event in current["timeline"]
        )
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run_id)["events"]
        ]
        assert "workflow.node.artifact" not in event_types
        assert "workflow.run.completed" not in event_types
    finally:
        service.close()


def test_cancel_after_workflow_continuation_fence_does_not_revive_root_group(
    tmp_path,
    monkeypatch,
) -> None:
    service = make_service(tmp_path)
    artifact_writes: list[str] = []
    try:
        workflow = service.create_workflow(
            {
                "name": "Workflow root group cancellation race",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {"label": "Human Gate", "criteria": "Review first"},
                    },
                    {
                        "id": "summary",
                        "type": "artifact",
                        "data": {"label": "Summary"},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "summary"},
                ],
            }
        )
        waiting = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Keep the root group cancelled",
            }
        )
        run_id = waiting["run_id"]
        approval_id = waiting["pending_approval"]["approval_id"]
        original_fence = service.workflow_continuation._advance_continuation_fence
        original_artifact_write = (
            service.workflow_continuation._workflow_artifact_write_callback
        )
        fence_calls = 0
        assert callable(original_artifact_write)

        def fence_then_cancel(
            run: dict[str, Any],
            *,
            expected_updated_at: str,
        ) -> dict[str, Any] | None:
            nonlocal fence_calls
            fence_calls += 1
            fenced = original_fence(
                run,
                expected_updated_at=expected_updated_at,
            )
            if fence_calls == 1:
                assert fenced is not None
                assert fenced["status"] == "running"
                cancelled = service.cancel_run(run_id)
                assert cancelled["status"] == "cancelled"
            return fenced

        def record_artifact_write(*args: Any, **kwargs: Any) -> dict[str, Any]:
            artifact_writes.append("called")
            return original_artifact_write(*args, **kwargs)

        monkeypatch.setattr(
            service.workflow_continuation,
            "_advance_continuation_fence",
            fence_then_cancel,
        )
        monkeypatch.setattr(
            service.workflow_continuation,
            "_workflow_artifact_write_callback",
            record_artifact_write,
        )

        result = service.approve_run_approval(run_id, approval_id)

        assert fence_calls >= 2
        assert result["status"] == "cancelled"
        assert service.get_run(run_id)["status"] == "cancelled"
        assert service.get_run_group(waiting["run_group_id"])["status"] == "cancelled"
        assert artifact_writes == []
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run_id)["events"]
        ]
        assert "workflow.node.artifact" not in event_types
        assert "workflow.run.completed" not in event_types
    finally:
        service.close()


def test_cancel_after_workflow_pause_cas_fences_production_event_callback(
    tmp_path,
) -> None:
    service = make_service(tmp_path)
    competing_service = make_service(tmp_path)
    try:
        group = service._insert_run_group(
            title="Workflow pause cancellation race",
            source="workflow",
        )
        run = service._insert_run(
            kind="workflow_run",
            runnable_id="workflow-pause-race",
            user_goal="Cancel around approval pause",
            run_group_id=group["run_group_id"],
            project_root_group=True,
        )
        projection = WorkflowApprovalPauseProjection.from_criteria(
            {"id": "gate", "type": "approval"},
            label="Human Gate",
            kind="approval",
            criteria="Review first",
            context="Draft ready",
            next_index=1,
        )
        paused = service.workflow_continuation._approval_pause.pause(
            run,
            projection,
            run_group_id=group["run_group_id"],
            timeline=[],
            artifacts=[],
            root_group=True,
        )
        assert paused["status"] == "approval_required"
        cancelled = competing_service.cancel_run(run["run_id"])

        result = service.get_run(run["run_id"])
        assert cancelled["status"] == "cancelled"
        assert result["status"] == "cancelled"
        assert service.get_run_group(group["run_group_id"])["status"] == "cancelled"
        events = service.list_run_events(run["run_id"], include_internal=True)["events"]
        event_types = [event["event_type"] for event in events]
        cancelled_index = event_types.index("workflow.run.cancelled")
        stale_types = {
            "workflow.node.approval_required",
            "workflow.paused_for_approval",
            "approval.required",
        }
        assert not any(
            event_type in stale_types
            for event_type in event_types[cancelled_index + 1 :]
        )
    finally:
        competing_service.close()
        service.close()
