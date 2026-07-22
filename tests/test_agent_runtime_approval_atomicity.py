"""Crash consistency regressions for approved tool resume projection."""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from functools import partial
from typing import Any

import pytest

import apps.shell.agent.runtime.main_chat_model_loop as main_chat_model_loop_module
from apps.shell.agent.runtime.approval_lifecycle import ApprovalCoordinator
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from tests.test_agent_runtime import (
    FakeDefaultProfileService,
    make_service as make_runtime_service,
)


def make_service(tmp_path):
    """Keep approval-transaction tests independent from intent routing.

    These fixtures deliberately exercise the legacy model-authored tool-call
    seam so they can inject crashes around approval storage transitions.  The
    initial semantic planner is covered separately and would consume the
    fixture's first fake model response before the approval under test exists.
    """

    service = make_runtime_service(tmp_path)
    service.main_chat_model_loop._resolve_initial_model_plan = None
    service.main_chat_model_loop._continue_custom_api_agent = partial(
        service.main_chat_model_loop._continue_custom_api_agent,
        start_iteration=1,
    )
    service.custom_api_agent_loop._max_tool_iterations = 3
    return service


_TERMINAL_COMMANDS_BY_GOAL = {
    "Run one approved terminal command": ("printf approval-atomic",),
    "Approve safely": ("printf none-tool",),
    "Reject one terminal command": ("printf reject-atomic",),
    "Reject safely": ("printf none-projection",),
    "Cancel during rejection": ("printf terminal-race",),
    "Run two approved terminal commands": (
        "touch generation-one-executed",
        "touch generation-two-executed",
    ),
    "Run two approved commands with a CAS race": (
        "touch cas-generation-one-executed",
        "touch cas-generation-two-executed",
    ),
    "Run the approved command once": ("touch cancelled-after-claim-executed",),
}


def _terminal_goal_contract(
    *,
    original_goal: str,
    commands: tuple[str, ...],
) -> GoalContract:
    target: dict[str, Any] = (
        {"kind": "local_compute", "command": commands[0]}
        if len(commands) == 1
        else {"kind": "local_compute_batch", "commands": list(commands)}
    )
    return GoalContract(
        contract_id="goal-contract-approval-atomicity-fixture",
        original_goal=original_goal,
        intent_kind="code_task",
        criteria=(
            GoalCriterion(
                criterion_id="goal-criterion-approval-atomicity-fixture",
                description="Run only the exact terminal command fixture",
                effectful=True,
                required_capabilities=("terminal.execution",),
                expected={"target": target},
                source_step_ids=("run-approved-terminal-command",),
            ),
        ),
    )


def _verified_terminal_result(command: str, *, stdout: str) -> dict[str, Any]:
    return {
        "ok": True,
        "stdout": stdout,
        "postcondition_verified": True,
        "data": {
            "target": {
                "kind": "local_compute",
                "command": command,
            },
            "postcondition_verified": True,
        },
    }


@pytest.fixture(autouse=True)
def _runtime_owned_terminal_contract_fixtures(monkeypatch):
    real_compiler = main_chat_model_loop_module.planned_goal_contract_payload

    def compile_goal_contract(
        user_goal: str,
        *,
        allowed_tools: list[str],
        **kwargs: Any,
    ) -> dict[str, Any]:
        commands = _TERMINAL_COMMANDS_BY_GOAL.get(user_goal)
        if commands is None:
            return real_compiler(
                user_goal,
                allowed_tools=allowed_tools,
                **kwargs,
            )
        assert "terminal.run" in allowed_tools
        return _terminal_goal_contract(
            original_goal=user_goal,
            commands=commands,
        ).to_payload()

    monkeypatch.setattr(
        main_chat_model_loop_module,
        "planned_goal_contract_payload",
        compile_goal_contract,
    )


def test_tool_approval_timeout_rolls_back_terminal_row_when_cancel_event_is_fenced() -> None:
    run = {
        "run_id": "run-timeout-atomic",
        "status": "approval_required",
        "updated_at": "version-1",
        "result": "waiting",
        "timeline": [],
        "pending_approval": {"approval_id": "approval-timeout"},
    }
    events: list[str] = []

    @contextmanager
    def transaction_scope():
        run_snapshot = deepcopy(run)
        event_snapshot = list(events)
        try:
            yield
        except BaseException:
            run.clear()
            run.update(run_snapshot)
            events[:] = event_snapshot
            raise

    def update_run(_run_id: str, **fields: Any) -> dict[str, Any] | None:
        if fields.pop("expected_status") != run["status"]:
            return None
        if fields.pop("expected_approval_id") != "approval-timeout":
            return None
        run.update(fields)
        run["updated_at"] = "version-2"
        return dict(run)

    def append_run_event(
        _run_id: str,
        event_type: str,
        _payload: dict[str, Any],
        *,
        expected_status: str,
        expected_updated_at: str,
    ) -> dict[str, Any] | None:
        assert expected_status == "cancelled"
        assert expected_updated_at == "version-2"
        events.append(event_type)
        if event_type == "agent.run.cancelled":
            return None
        return {"event_type": event_type}

    coordinator = ApprovalCoordinator(
        timeline_factory=lambda event, detail, **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=append_run_event,
        update_run=update_run,
        transaction_scope=transaction_scope,
    )

    with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
        coordinator.timeout_tool_run(
            run["run_id"],
            timeline=[],
            reason="approval_wait_timeout",
            tool_name="terminal.run",
            input_preview={"command": "printf timeout"},
            expected_approval_id="approval-timeout",
        )

    assert run["status"] == "approval_required"
    assert run["updated_at"] == "version-1"
    assert run["pending_approval"]["approval_id"] == "approval-timeout"
    assert events == []


def test_tool_approval_claim_and_resume_projection_roll_back_together_after_crash(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    model_calls: list[list[dict[str, Any]]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        if len(model_calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_atomic_approval",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf approval-atomic"}),
                        },
                    }
                ],
            }
        return {"content": "approval retry completed"}

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )

    first_service = make_service(tmp_path)
    first_tool_calls: list[str] = []
    captured_timeline: list[dict[str, Any]] | None = None
    try:
        run = first_service.start_main_chat_run(
            task_id="task-approval-atomic-crash",
            session_id="session-approval-atomic-crash",
            user_goal="Run one approved terminal command",
        )
        waiting = first_service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run it"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        original_project = first_service.approval_resume._approve_tool_run

        def crash_after_run_and_event_projection(*args, **kwargs):
            nonlocal captured_timeline
            captured_timeline = kwargs["timeline"]
            projected = original_project(*args, **kwargs)
            assert projected is not None
            assert projected["status"] == "running"
            raise RuntimeError("injected approval projection crash")

        monkeypatch.setattr(
            first_service.approval_resume,
            "_approve_tool_run",
            crash_after_run_and_event_projection,
        )
        monkeypatch.setattr(
            first_service.approval_resume,
            "_call_agent_tool",
            lambda *_args, **_kwargs: first_tool_calls.append("called") or {"ok": True},
        )

        with pytest.raises(RuntimeError, match="injected approval projection crash"):
            first_service.approve_run_approval(run["run_id"], approval_id)

        assert captured_timeline == waiting["timeline"]
        assert first_tool_calls == []
        assert first_service.get_run(run["run_id"])["status"] == "approval_required"
    finally:
        # Model process death: close storage without the graceful shutdown sweep,
        # which intentionally cancels active runs.
        first_service._conn.close()
        first_service._credential_store.close()
        first_service._closed = True

    retry_tool_calls: list[str] = []
    reopened_service = make_service(tmp_path)
    try:
        recovered = reopened_service.get_run(run["run_id"])
        assert recovered["status"] == "approval_required"
        assert recovered["pending_approval"]["approval_id"] == approval_id
        recovered_event_types = [
            event["event_type"]
            for event in reopened_service.list_run_events(run["run_id"])["events"]
        ]
        assert not {
            "agent.tool.approval_approved",
            "tool.approved",
            "approval.approved",
        }.intersection(recovered_event_types)

        monkeypatch.setattr(
            reopened_service.approval_resume,
            "_call_agent_tool",
            lambda *_args, **_kwargs: retry_tool_calls.append("called")
            or _verified_terminal_result(
                "printf approval-atomic",
                stdout="approval-atomic",
            ),
        )
        retried = reopened_service.approve_run_approval(run["run_id"], approval_id)

        assert retried["status"] == "failed"
        assert "工具循环超过上限" in retried["result"]
        assert retry_tool_calls == ["called"]
        assert len(model_calls) == 2
        event_types = [
            event["event_type"]
            for event in reopened_service.list_run_events(run["run_id"])["events"]
        ]
        assert event_types.count("agent.tool.approval_approved") == 1
        assert event_types.count("tool.approved") == 1
        assert event_types.count("approval.approved") == 1
    finally:
        reopened_service.close()


def test_tool_approval_claim_rolls_back_when_run_projection_returns_none(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    model_calls: list[str] = []

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        model_calls.append("called")
        if len(model_calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_none_tool_projection",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf none-tool"}),
                        },
                    }
                ],
            }
        return {"content": "tool projection retry completed"}

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )
    service = make_service(tmp_path)
    tool_calls: list[str] = []
    try:
        run = service.start_main_chat_run(
            task_id="task-approval-none-tool-projection",
            session_id="session-approval-none-tool-projection",
            user_goal="Approve safely",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run it"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        original_projection = service.approval_resume._approve_tool_run
        monkeypatch.setattr(
            service.approval_resume,
            "_approve_tool_run",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            service.approval_resume,
            "_call_agent_tool",
            lambda *_args, **_kwargs: tool_calls.append("called")
            or _verified_terminal_result(
                "printf none-tool",
                stdout="none-tool",
            ),
        )

        conflicted = service.approve_run_approval(waiting["run_id"], approval_id)

        assert conflicted["status"] == "approval_required"
        assert conflicted["pending_approval"]["approval_id"] == approval_id
        assert tool_calls == []
        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        assert approval_row["status"] == "pending"

        monkeypatch.setattr(
            service.approval_resume,
            "_approve_tool_run",
            original_projection,
        )
        retried = service.approve_run_approval(waiting["run_id"], approval_id)

        assert retried["status"] == "failed"
        assert "工具循环超过上限" in retried["result"]
        assert tool_calls == ["called"]
        assert len(model_calls) == 2
    finally:
        service.close()


def _create_terminal_approval_agent_run(service: Any) -> dict[str, Any]:
    agent = service.create_agent(
        {
            "name": "Atomic Approval Agent",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "test-placeholder",
            },
            "tool_policy": {"allowed_tools": ["terminal.run"]},
        }
    )
    return service.create_agent_run(
        {
            "agent_id": agent["agent_id"],
            "user_goal": "Run `printf atomic` in terminal",
        }
    )


@pytest.mark.parametrize("transition", ["reject", "timeout"])
def test_native_agent_approval_cancel_group_event_failure_rolls_back_claim_run_and_events(
    tmp_path,
    monkeypatch,
    transition: str,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call-{transition}-atomic",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf atomic"}),
                    },
                }
            ],
        },
    )
    service = make_service(tmp_path)
    try:
        waiting = _create_terminal_approval_agent_run(service)
        assert waiting["status"] == "approval_required"
        approval_id = waiting["pending_approval"]["approval_id"]
        before_run = service.get_run(waiting["run_id"])
        before_group = service.get_run_group(waiting["run_group_id"])
        before_events = service.list_run_events(
            waiting["run_id"],
            include_internal=True,
        )["events"]
        original_append = service.append_run_event

        def fail_group_cancel_event(
            run_id: str,
            event_type: str,
            payload: dict[str, Any],
            **kwargs: Any,
        ) -> Any:
            if event_type == "group.run.cancelled":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        monkeypatch.setattr(service, "append_run_event", fail_group_cancel_event)

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_event_fence_mismatch",
        ):
            if transition == "reject":
                service.reject_run_approval(
                    waiting["run_id"],
                    "not now",
                    approval_id,
                )
            else:
                service.timeout_run_approval(
                    waiting["run_id"],
                    expected_approval_id=approval_id,
                )

        assert service.get_run(waiting["run_id"]) == before_run
        assert service.get_run_group(waiting["run_group_id"]) == before_group
        assert service.list_run_events(
            waiting["run_id"],
            include_internal=True,
        )["events"] == before_events
        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE run_id=? AND approval_id=?",
            (waiting["run_id"], approval_id),
        ).fetchone()
        assert approval_row["status"] == "pending"
    finally:
        service.close()


def test_native_agent_approval_resume_group_failure_event_rolls_back_terminal_projection(
    tmp_path,
    monkeypatch,
) -> None:
    model_calls = 0

    def fake_chat(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal model_calls
        model_calls += 1
        return {"content": "approved command complete"}

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )
    service = make_service(tmp_path)
    try:
        waiting = _create_terminal_approval_agent_run(service)
        approval_id = waiting["pending_approval"]["approval_id"]
        original_append = service.append_run_event

        def fail_group_failure_event(
            run_id: str,
            event_type: str,
            payload: dict[str, Any],
            **kwargs: Any,
        ) -> Any:
            if event_type == "group.run.failed":
                return None
            return original_append(run_id, event_type, payload, **kwargs)

        monkeypatch.setattr(service, "append_run_event", fail_group_failure_event)
        monkeypatch.setattr(
            service.approval_resume,
            "_call_agent_tool",
            lambda *_args, **_kwargs: {
                "ok": True,
                "stdout": "atomic",
                "summary": "atomic",
            },
        )

        with pytest.raises(
            AgentRuntimeError,
            match="run_group_event_fence_mismatch",
        ):
            service.approve_run_approval(waiting["run_id"], approval_id)

        stored = service.get_run(waiting["run_id"])
        stored_group = service.get_run_group(waiting["run_group_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(
                waiting["run_id"],
                include_internal=True,
            )["events"]
        ]
        assert stored["status"] == "running"
        assert stored_group["status"] == "running"
        assert "agent.run.failed" not in event_types
        assert "run.failed" not in event_types
        assert "group.run.failed" not in event_types
        assert event_types.count("agent.tool.executed_after_claim") == 1
        assert model_calls == 2
        internal_events = service.list_run_events(
            waiting["run_id"],
            include_internal=True,
        )["events"]
        assert not any(
            event["event_type"] in {"agent.tool.call", "agent.tool.outcome"}
            and (
                event["payload"].get("approval_id") == approval_id
                or event["payload"].get("approved") is True
            )
            for event in internal_events
        )
        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE run_id=? AND approval_id=?",
            (waiting["run_id"], approval_id),
        ).fetchone()
        assert approval_row["status"] == "approved"
    finally:
        service.close()


def test_workflow_approval_claim_and_node_projection_roll_back_together_after_crash(
    tmp_path,
    monkeypatch,
) -> None:
    first_service = make_service(tmp_path)
    continuation_calls: list[str] = []
    try:
        workflow = first_service.create_workflow(
            {
                "name": "Atomic Workflow Approval",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {"label": "Review", "criteria": "Approve artifact"},
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
        waiting = first_service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Create one approved artifact",
            }
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        original_projection = first_service.workflow_continuation._approve_workflow_node
        original_continue = first_service.workflow_continuation.continue_run

        def crash_after_node_projection(*args, **kwargs):
            projected = original_projection(*args, **kwargs)
            assert projected is not None
            assert projected["status"] == "running"
            raise RuntimeError("injected workflow approval projection crash")

        def track_continuation(*args, **kwargs):
            continuation_calls.append("continued")
            return original_continue(*args, **kwargs)

        monkeypatch.setattr(
            first_service.workflow_continuation,
            "_approve_workflow_node",
            crash_after_node_projection,
        )
        monkeypatch.setattr(
            first_service.workflow_continuation,
            "continue_run",
            track_continuation,
        )

        with pytest.raises(
            RuntimeError,
            match="injected workflow approval projection crash",
        ):
            first_service.approve_run_approval(waiting["run_id"], approval_id)

        assert continuation_calls == []
    finally:
        first_service._conn.close()
        first_service._credential_store.close()
        first_service._closed = True

    reopened_service = make_service(tmp_path)
    try:
        recovered = reopened_service.get_run(waiting["run_id"])
        assert recovered["status"] == "approval_required"
        assert recovered["pending_approval"]["approval_id"] == approval_id
        recovered_event_types = [
            event["event_type"]
            for event in reopened_service.list_run_events(waiting["run_id"])["events"]
        ]
        assert "workflow.node.approval_approved" not in recovered_event_types
        assert "approval.approved" not in recovered_event_types

        retried = reopened_service.approve_run_approval(waiting["run_id"], approval_id)

        assert retried["status"] == "completed"
        assert retried["pending_approval"] == {}
        assert any(
            artifact.get("kind") == "workflow_artifact"
            for artifact in retried["artifacts"]
        )
    finally:
        reopened_service.close()


def test_tool_approval_rejection_claim_and_projection_roll_back_together_after_crash(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_atomic_reject",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf reject-atomic"}),
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )
    first_service = make_service(tmp_path)
    try:
        run = first_service.start_main_chat_run(
            task_id="task-approval-reject-atomic-crash",
            session_id="session-approval-reject-atomic-crash",
            user_goal="Reject one terminal command",
        )
        waiting = first_service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run it"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        original_projection = first_service.approvals.reject_tool_run

        def crash_after_rejection_projection(*args, **kwargs):
            projected = original_projection(*args, **kwargs)
            assert projected is not None
            assert projected["status"] == "cancelled"
            raise RuntimeError("injected approval rejection projection crash")

        monkeypatch.setattr(
            first_service.approvals,
            "reject_tool_run",
            crash_after_rejection_projection,
        )

        with pytest.raises(
            RuntimeError,
            match="injected approval rejection projection crash",
        ):
            first_service.reject_run_approval(
                waiting["run_id"],
                "not now",
                approval_id,
            )
    finally:
        first_service._conn.close()
        first_service._credential_store.close()
        first_service._closed = True

    reopened_service = make_service(tmp_path)
    try:
        recovered = reopened_service.get_run(waiting["run_id"])
        assert recovered["status"] == "approval_required"
        assert recovered["pending_approval"]["approval_id"] == approval_id
        recovered_event_types = [
            event["event_type"]
            for event in reopened_service.list_run_events(waiting["run_id"])["events"]
        ]
        assert not {
            "agent.tool.approval_rejected",
            "tool.rejected",
            "approval.rejected",
            "agent.run.cancelled",
            "run.cancelled",
        }.intersection(recovered_event_types)

        retried = reopened_service.reject_run_approval(
            waiting["run_id"],
            "not now",
            approval_id,
        )

        assert retried["status"] == "cancelled"
        assert retried["pending_approval"] == {}
        event_types = [
            event["event_type"]
            for event in reopened_service.list_run_events(waiting["run_id"])["events"]
        ]
        assert event_types.count("agent.tool.approval_rejected") == 1
        assert event_types.count("tool.rejected") == 1
        assert event_types.count("approval.rejected") == 1
    finally:
        reopened_service.close()


def test_workflow_approval_timeout_claim_and_projection_roll_back_together_after_crash(
    tmp_path,
    monkeypatch,
) -> None:
    first_service = make_service(tmp_path)
    try:
        workflow = first_service.create_workflow(
            {
                "name": "Atomic Workflow Timeout",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {"label": "Review", "criteria": "Respond in time"},
                    },
                ],
                "edges": [{"source": "start", "target": "gate"}],
            }
        )
        waiting = first_service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Wait for one approval",
            }
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        original_projection = first_service.approvals.timeout_workflow_node

        def crash_after_timeout_projection(*args, **kwargs):
            projected = original_projection(*args, **kwargs)
            assert projected is not None
            assert projected["status"] == "cancelled"
            raise RuntimeError("injected workflow timeout projection crash")

        monkeypatch.setattr(
            first_service.approvals,
            "timeout_workflow_node",
            crash_after_timeout_projection,
        )

        with pytest.raises(
            RuntimeError,
            match="injected workflow timeout projection crash",
        ):
            first_service.timeout_run_approval(
                waiting["run_id"],
                "approval_wait_timeout",
                approval_id,
            )
    finally:
        first_service._conn.close()
        first_service._credential_store.close()
        first_service._closed = True

    reopened_service = make_service(tmp_path)
    try:
        recovered = reopened_service.get_run(waiting["run_id"])
        assert recovered["status"] == "approval_required"
        assert recovered["pending_approval"]["approval_id"] == approval_id
        assert reopened_service.get_run_group(waiting["run_group_id"])["status"] == (
            "approval_required"
        )
        recovered_event_types = [
            event["event_type"]
            for event in reopened_service.list_run_events(waiting["run_id"])["events"]
        ]
        assert "approval.timeout" not in recovered_event_types
        assert "workflow.run.cancelled" not in recovered_event_types

        retried = reopened_service.timeout_run_approval(
            waiting["run_id"],
            "approval_wait_timeout",
            approval_id,
        )

        assert retried["status"] == "cancelled"
        assert retried["pending_approval"] == {}
        assert reopened_service.get_run_group(waiting["run_group_id"])["status"] == (
            "cancelled"
        )
        event_types = [
            event["event_type"]
            for event in reopened_service.list_run_events(waiting["run_id"])["events"]
        ]
        assert event_types.count("approval.timeout") == 1
        assert event_types.count("workflow.run.cancelled") == 1
    finally:
        reopened_service.close()


def test_tool_approval_transition_rolls_back_claim_when_projection_returns_none(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_none_projection",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf none-projection"}),
                    },
                }
            ],
        },
    )
    service = make_service(tmp_path)
    try:
        run = service.start_main_chat_run(
            task_id="task-approval-none-projection",
            session_id="session-approval-none-projection",
            user_goal="Reject safely",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run it"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        original_projection = service.approvals.reject_tool_run
        monkeypatch.setattr(
            service.approvals,
            "reject_tool_run",
            lambda *_args, **_kwargs: None,
        )

        conflicted = service.reject_run_approval(
            waiting["run_id"],
            "not now",
            approval_id,
        )

        assert conflicted["status"] == "approval_required"
        assert conflicted["pending_approval"]["approval_id"] == approval_id
        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        assert approval_row["status"] == "pending"
        assert "agent.tool.approval_rejected" not in [
            event["event_type"]
            for event in service.list_run_events(waiting["run_id"])["events"]
        ]

        monkeypatch.setattr(
            service.approvals,
            "reject_tool_run",
            original_projection,
        )
        retried = service.reject_run_approval(
            waiting["run_id"],
            "not now",
            approval_id,
        )

        assert retried["status"] == "cancelled"
    finally:
        service.close()


def test_tool_approval_rejection_preserves_terminal_race_without_reprojection(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal_race",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf terminal-race"}),
                    },
                }
            ],
        },
    )
    service = make_service(tmp_path)
    post_commit_projections: list[str] = []
    try:
        run = service.start_main_chat_run(
            task_id="task-approval-terminal-race",
            session_id="session-approval-terminal-race",
            user_goal="Cancel during rejection",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run it"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        original_claim = service.approval_transitions._claim_pending_rejection

        def claim_then_cancel(*args, **kwargs):
            claimed = original_claim(*args, **kwargs)
            assert claimed is True
            cancelled = service.cancel_run(waiting["run_id"])
            assert cancelled["status"] == "cancelled"
            return claimed

        monkeypatch.setattr(
            service.approval_transitions,
            "_claim_pending_rejection",
            claim_then_cancel,
        )
        monkeypatch.setattr(
            service.approval_transitions,
            "_project_child_run_transition",
            lambda result: post_commit_projections.append("projected") or result,
        )

        result = service.reject_run_approval(
            waiting["run_id"],
            "not now",
            approval_id,
        )

        assert result["status"] == "cancelled"
        assert service.get_run(waiting["run_id"])["status"] == "cancelled"
        assert post_commit_projections == []
        assert "agent.tool.approval_rejected" not in [
            event["event_type"]
            for event in service.list_run_events(waiting["run_id"])["events"]
        ]
        approval_row = service._conn.execute(
            "SELECT status FROM run_approvals WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        assert approval_row["status"] == "rejected"
    finally:
        service.close()


def test_next_approval_generation_projection_is_atomic_after_first_tool_executes(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    model_calls: list[list[dict[str, Any]]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        if len(model_calls) != 1:
            raise AssertionError("model must wait for the second approval generation")
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_atomic_generation_one",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps(
                            {"command": "touch generation-one-executed"}
                        ),
                    },
                },
                {
                    "id": "call_atomic_generation_two",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps(
                            {"command": "touch generation-two-executed"}
                        ),
                    },
                },
            ],
        }

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    second_generation_id = ""
    captured_timeline: list[dict[str, Any]] | None = None
    try:
        run = service.start_main_chat_run(
            task_id="task-next-approval-generation-atomic",
            session_id="session-next-approval-generation-atomic",
            user_goal="Run two approved terminal commands",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run both commands"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
            workspace_policy={
                "default_workdir": str(workdir),
                "readable_scopes": ["."],
            },
        )
        first_generation_id = waiting["pending_approval"]["approval_id"]
        original_project_required = service.approval_resume_projection.project_required

        def crash_after_next_generation_projection(context, pending_approval):
            nonlocal captured_timeline, second_generation_id
            captured_timeline = context.timeline
            second_generation_id = str(pending_approval.get("approval_id") or "")
            projected = original_project_required(context, pending_approval)
            assert projected["status"] == "approval_required"
            raise RuntimeError("injected next approval generation projection crash")

        monkeypatch.setattr(
            service.approval_resume_projection,
            "project_required",
            crash_after_next_generation_projection,
        )

        with pytest.raises(
            RuntimeError,
            match="injected next approval generation projection crash",
        ):
            service.approve_run_approval(run["run_id"], first_generation_id)

        assert second_generation_id
        assert second_generation_id != first_generation_id
        assert len(model_calls) == 1
        assert (workdir / "generation-one-executed").exists()
        assert not (workdir / "generation-two-executed").exists()

        recovered = service.get_run(run["run_id"])
        assert recovered["status"] == "running"
        assert recovered["pending_approval"] == {}
        approval_rows = service._conn.execute(
            "SELECT approval_id, status FROM run_approvals WHERE run_id=? ORDER BY approval_id",
            (run["run_id"],),
        ).fetchall()
        assert [(row["approval_id"], row["status"]) for row in approval_rows] == [
            (first_generation_id, "approved")
        ]
        approval_required_events = [
            event
            for event in service.list_run_events(run["run_id"])["events"]
            if event["event_type"] == "agent.tool.approval_required"
        ]
        assert len(approval_required_events) == 1
        assert captured_timeline is not None
        projected_ids = [
            str((event.get("pending_approval") or {}).get("approval_id") or "")
            for event in captured_timeline
            if event.get("event") == "agent.tool.approval_required"
        ]
        assert second_generation_id not in projected_ids
    finally:
        service.close()


def test_next_approval_generation_cas_loss_discards_projection_timeline(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    model_calls: list[list[dict[str, Any]]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        if len(model_calls) != 1:
            raise AssertionError("model must wait while the next approval CAS is lost")
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_cas_generation_one",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps(
                            {"command": "touch cas-generation-one-executed"}
                        ),
                    },
                },
                {
                    "id": "call_cas_generation_two",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps(
                            {"command": "touch cas-generation-two-executed"}
                        ),
                    },
                },
            ],
        }

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    captured_context: Any = None
    second_generation_id = ""
    try:
        run = service.start_main_chat_run(
            task_id="task-next-approval-generation-cas",
            session_id="session-next-approval-generation-cas",
            user_goal="Run two approved commands with a CAS race",
        )
        waiting = service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run both commands"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
            workspace_policy={
                "default_workdir": str(workdir),
                "readable_scopes": ["."],
            },
        )
        first_generation_id = waiting["pending_approval"]["approval_id"]
        original_project_required = service.approval_resume_projection.project_required

        def capture_lost_projection(context, pending_approval):
            nonlocal captured_context, second_generation_id
            captured_context = context
            second_generation_id = str(pending_approval.get("approval_id") or "")
            return original_project_required(context, pending_approval)

        monkeypatch.setattr(
            service.approval_resume_projection,
            "project_required",
            capture_lost_projection,
        )
        monkeypatch.setattr(
            service.approval_resume_projection,
            "_update_run",
            lambda *_args, **_kwargs: None,
        )

        result = service.approve_run_approval(run["run_id"], first_generation_id)

        assert result["status"] == "running"
        assert result["pending_approval"] == {}
        assert second_generation_id
        assert second_generation_id != first_generation_id
        assert len(model_calls) == 1
        assert (workdir / "cas-generation-one-executed").exists()
        assert not (workdir / "cas-generation-two-executed").exists()
        assert captured_context is not None
        assert second_generation_id not in [
            str((event.get("pending_approval") or {}).get("approval_id") or "")
            for event in captured_context.timeline
            if event.get("event") == "agent.tool.approval_required"
        ]

        persisted_events = service.list_run_events(run["run_id"])["events"]
        canonical_approval_events = [
            event
            for event in persisted_events
            if event["event_type"] == "agent.tool.approval_required"
        ]
        assert len(canonical_approval_events) == 1
        # The losing continuation is tentative: neither its canonical event
        # nor the runtime alias emitted while discovering the next approval
        # may survive the authoritative projection CAS loss.
        assert not any(
            event["event_type"] == "agent.tool.call"
            and (event["payload"].get("input_preview") or {}).get("command")
            == "touch cas-generation-two-executed"
            and (event["payload"].get("result") or {}).get("approval_required")
            is True
            for event in persisted_events
        )
        internal_events = service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        receipts = [
            event
            for event in internal_events
            if event["event_type"] == "agent.tool.executed_after_claim"
        ]
        assert len(receipts) == 1
        assert receipts[0]["payload"]["approval_id"] == first_generation_id
        assert receipts[0]["payload"]["tool_call_id"] == "call_cas_generation_one"
        assert receipts[0]["payload"]["completion_evidence"] is False
        assert receipts[0]["payload"]["goal_evidence"] is False
        approval_rows = service._conn.execute(
            "SELECT approval_id, status FROM run_approvals WHERE run_id=? ORDER BY approval_id",
            (run["run_id"],),
        ).fetchall()
        assert [(row["approval_id"], row["status"]) for row in approval_rows] == [
            (first_generation_id, "approved")
        ]
    finally:
        service.close()


def test_cross_connection_cancel_after_tool_side_effect_keeps_only_audit_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: FakeDefaultProfileService(),
    )
    model_calls: list[list[dict[str, Any]]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        model_calls.append(messages)
        if len(model_calls) != 1:
            raise AssertionError("cancelled approval resume must not continue the model")
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_cancel_after_claim",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps(
                            {"command": "touch cancelled-after-claim-executed"}
                        ),
                    },
                }
            ],
        }

    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        fake_chat,
    )
    first_service = make_service(tmp_path)
    second_service = None
    workdir = tmp_path / "repo-cancel-after-claim"
    workdir.mkdir()
    try:
        run = first_service.start_main_chat_run(
            task_id="task-cancel-after-claim",
            session_id="session-cancel-after-claim",
            user_goal="Run the approved command once",
        )
        waiting = first_service.execute_main_chat_model_loop(
            run["run_id"],
            [{"role": "user", "content": "Run it"}],
            tool_policy={"allowed_tools": ["terminal.run"]},
            workspace_policy={
                "default_workdir": str(workdir),
                "readable_scopes": ["."],
            },
        )
        approval_id = waiting["pending_approval"]["approval_id"]
        second_service = make_service(tmp_path)
        original_call = first_service.approval_resume._call_agent_tool

        def execute_then_cancel(*args, **kwargs):
            result = original_call(*args, **kwargs)
            cancelled = second_service.cancel_run(run["run_id"])
            assert cancelled["status"] == "cancelled"
            return result

        monkeypatch.setattr(
            first_service.approval_resume,
            "_call_agent_tool",
            execute_then_cancel,
        )

        result = first_service.approve_run_approval(run["run_id"], approval_id)

        assert result["status"] == "cancelled"
        assert first_service.get_run(run["run_id"])["status"] == "cancelled"
        assert (workdir / "cancelled-after-claim-executed").exists()
        assert len(model_calls) == 1
        terminal_timeline = first_service.get_run(run["run_id"])["timeline"]
        assert not any(
            event.get("event")
            in {
                "agent.desktop.intent_completed",
                "agent.run.completed",
                "agent.tool.approval_required",
                "model.output.ready",
            }
            and event not in waiting["timeline"]
            for event in terminal_timeline
        )
        internal_events = first_service.list_run_events(
            run["run_id"],
            include_internal=True,
        )["events"]
        receipts = [
            event
            for event in internal_events
            if event["event_type"] == "agent.tool.executed_after_claim"
        ]
        assert len(receipts) == 1
        receipt = receipts[0]["payload"]
        assert receipt["approval_id"] == approval_id
        assert receipt["tool_call_id"] == "call_cancel_after_claim"
        assert receipt["completion_evidence"] is False
        assert receipt["goal_evidence"] is False
        completion_ghosts = [
            event["event_type"]
            for event in internal_events
            if event["event_type"]
            in {
                "agent.desktop.intent_completed",
                "agent.run.completed",
                "model.output.completed",
            }
            or (
                event["event_type"] == "agent.tool.outcome"
                and (
                    event["payload"].get("approved") is True
                    or event["payload"].get("approval_id") == approval_id
                )
            )
        ]
        assert completion_ghosts == []
    finally:
        if second_service is not None:
            second_service.close()
        first_service.close()
