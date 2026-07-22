"""Tests for Run control facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_control_facade import RuntimeRunControlFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_run_control_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunControlFacadeMixin is RuntimeRunControlFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeRunControlFacadeMixin)
    for method_name in (
        "cancel_run",
        "_cancel_workflow_run_projection",
        "_cancel_run_once",
        "_tool_approval_resume_context",
        "approve_run_approval",
        "_approve_run_approval_once",
        "_resume_approved_tool_run",
        "_project_agent_approval_resume_running",
        "_project_agent_approval_resume_completed",
        "_project_main_chat_approval_resume_completed",
        "_project_approval_resume_required",
        "_project_approval_resume_failed",
        "_approve_main_chat_run_approval",
        "_approve_workflow_run_approval",
        "_project_cancelled_workflow_group_if_root",
        "_project_child_run_transition",
        "_project_agent_run_group_if_root",
        "reject_run_approval",
        "timeout_run_approval",
        "_update_agent_run_group_if_root",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_run_control_facade_methods_available_after_split(tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []

    class _RunCancellationCoordinator:
        @staticmethod
        def cancel(run_id: str) -> dict[str, Any]:
            calls.append(("cancel", run_id))
            return {"run_id": run_id, "status": "cancelled"}

    class _WorkflowCancellation:
        @staticmethod
        def project_cancelled_workflow_run(
            run_id: str,
            run: dict[str, Any],
            timeline: list[dict[str, Any]],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
            calls.append(("workflow-cancel", run_id, run, timeline))
            return timeline, [{"artifact_id": "artifact-1"}], "cancelled"

    class _RunCancellation:
        @staticmethod
        def cancel_once(run_id: str) -> dict[str, Any]:
            calls.append(("cancel-once", run_id))
            return {"run_id": run_id, "status": "cancelled"}

    class _ToolApprovalResume:
        @staticmethod
        def context(
            run: dict[str, Any],
            pending: dict[str, Any],
            *,
            runtime: dict[str, Any],
            skills: list[dict[str, Any]] | None = None,
        ) -> dict[str, Any]:
            calls.append(("context", run, pending, runtime, skills))
            return {"run_id": run["run_id"], "pending": pending}

        @staticmethod
        def approve_main_chat_run(run: dict[str, Any]) -> dict[str, Any]:
            calls.append(("approve-main-chat", run))
            return {"run_id": run["run_id"], "status": "completed"}

    class _ApprovalExecution:
        @staticmethod
        def approve_run_approval(run_id: str) -> dict[str, Any]:
            calls.append(("approve", run_id))
            return {"run_id": run_id, "status": "completed"}

    class _ApprovalResumeDispatcher:
        @staticmethod
        def approve_once(run: dict[str, Any]) -> dict[str, Any]:
            calls.append(("approve-once", run))
            return {"run_id": run["run_id"], "status": "completed"}

    class _ApprovalResume:
        @staticmethod
        def resume_approved_tool_run(**kwargs: Any) -> dict[str, Any]:
            calls.append(("resume-tool", kwargs))
            return {"run_id": kwargs["run_id"], "status": "completed"}

    class _ApprovalResumeProjection:
        @staticmethod
        def project_agent_running(running: dict[str, Any]) -> dict[str, Any]:
            calls.append(("project-agent-running", running))
            return {"status": "running", **running}

        @staticmethod
        def project_agent_completed(context: Any, result_text: str) -> dict[str, Any]:
            calls.append(("project-agent-completed", context, result_text))
            return {"status": "completed", "result": result_text}

        @staticmethod
        def project_main_chat_completed(context: Any, result_text: str) -> dict[str, Any]:
            calls.append(("project-main-completed", context, result_text))
            return {"status": "completed", "result": result_text}

        @staticmethod
        def project_required(context: Any, pending_approval: dict[str, Any]) -> dict[str, Any]:
            calls.append(("project-required", context, pending_approval))
            return {"status": "approval_required", "pending_approval": pending_approval}

        @staticmethod
        def project_failed(context: Any, safe_error: str) -> dict[str, Any]:
            calls.append(("project-failed", context, safe_error))
            return {"status": "failed", "error": safe_error}

    class _WorkflowApprovalExecution:
        @staticmethod
        def approve_workflow_run(run: dict[str, Any]) -> dict[str, Any]:
            calls.append(("approve-workflow", run))
            return {"run_id": run["run_id"], "status": "completed"}

    class _RunTransitionProjection:
        @staticmethod
        def project_cancelled_workflow_group_if_root(run: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
            calls.append(("project-cancelled-group", run, result))
            return {"projected": "cancelled", **result}

        @staticmethod
        def project_child_run_transition(result: dict[str, Any]) -> dict[str, Any]:
            calls.append(("project-child", result))
            return {"projected": "child", **result}

        @staticmethod
        def project_agent_run_group_if_root(result: dict[str, Any]) -> dict[str, Any]:
            calls.append(("project-agent-group", result))
            return {"projected": "agent", **result}

    class _ApprovalTransitions:
        @staticmethod
        def reject(run_id: str, reason: str) -> dict[str, Any]:
            calls.append(("reject", run_id, reason))
            return {"run_id": run_id, "status": "rejected", "reason": reason}

        @staticmethod
        def timeout(run_id: str, reason: str) -> dict[str, Any]:
            calls.append(("timeout", run_id, reason))
            return {"run_id": run_id, "status": "cancelled", "reason": reason}

    class _AgentRunGroupProjection:
        @staticmethod
        def update_if_root(run: dict[str, Any]) -> None:
            calls.append(("update-agent-group", run))

    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        service.run_cancellation_coordinator = _RunCancellationCoordinator()
        service.workflow_cancellation = _WorkflowCancellation()
        service.run_cancellation = _RunCancellation()
        service.tool_approval_resume = _ToolApprovalResume()
        service.approval_execution = _ApprovalExecution()
        service.approval_resume_dispatcher = _ApprovalResumeDispatcher()
        service.approval_resume = _ApprovalResume()
        service.approval_resume_projection = _ApprovalResumeProjection()
        service.workflow_approval_execution = _WorkflowApprovalExecution()
        service.run_transition_projection = _RunTransitionProjection()
        service.approval_transitions = _ApprovalTransitions()
        service.agent_run_group_projection = _AgentRunGroupProjection()

        run = {"run_id": "run-1", "kind": "agent_run"}
        pending = {"approval_id": "approval-1", "tool": "terminal.run"}
        context = {"run_id": "run-1"}
        timeline = [{"event": "workflow.run.started"}]

        assert service.cancel_run("run-1") == {"run_id": "run-1", "status": "cancelled"}
        assert service._cancel_workflow_run_projection("run-1", run, timeline) == (
            timeline,
            [{"artifact_id": "artifact-1"}],
            "cancelled",
        )
        assert service._cancel_run_once("run-1") == {"run_id": "run-1", "status": "cancelled"}
        assert service._tool_approval_resume_context(
            run,
            pending,
            runtime={"runtime": "oha_agent"},
            skills=[],
        ) == {"run_id": "run-1", "pending": pending}
        assert service.approve_run_approval("run-1") == {"run_id": "run-1", "status": "completed"}
        assert service._approve_run_approval_once(run) == {"run_id": "run-1", "status": "completed"}
        assert service._resume_approved_tool_run(
            run_id="run-1",
            pending=pending,
            resume_context=context,
            agent={"agent_id": "agent-1"},
            resumed_detail="resumed",
            running_result="running",
            project_completed=lambda *_args: {"status": "completed"},
        ) == {"run_id": "run-1", "status": "completed"}
        assert service._project_agent_approval_resume_running({"run_id": "run-1"}) == {
            "status": "running",
            "run_id": "run-1",
        }
        assert service._project_agent_approval_resume_completed(context, "done") == {
            "status": "completed",
            "result": "done",
        }
        assert service._project_main_chat_approval_resume_completed(context, "done") == {
            "status": "completed",
            "result": "done",
        }
        assert service._project_approval_resume_required(context, pending) == {
            "status": "approval_required",
            "pending_approval": pending,
        }
        assert service._project_approval_resume_failed(context, "safe error") == {
            "status": "failed",
            "error": "safe error",
        }
        assert service._approve_main_chat_run_approval(run) == {"run_id": "run-1", "status": "completed"}
        assert service._approve_workflow_run_approval(run) == {"run_id": "run-1", "status": "completed"}
        assert service._project_cancelled_workflow_group_if_root(run, {"run_id": "run-1"}) == {
            "projected": "cancelled",
            "run_id": "run-1",
        }
        assert service._project_child_run_transition({"run_id": "run-1"}) == {
            "projected": "child",
            "run_id": "run-1",
        }
        assert service._project_agent_run_group_if_root({"run_id": "run-1"}) == {
            "projected": "agent",
            "run_id": "run-1",
        }
        assert service.reject_run_approval("run-1", "no") == {
            "run_id": "run-1",
            "status": "rejected",
            "reason": "no",
        }
        assert service.timeout_run_approval("run-1") == {
            "run_id": "run-1",
            "status": "cancelled",
            "reason": "approval_wait_timeout",
        }
        service._update_agent_run_group_if_root(run)

        resume_calls = [item[1] for item in calls if item[0] == "resume-tool"]
        assert ("cancel", "run-1") in calls
        assert resume_calls
        assert resume_calls[0]["project_required"] == service._project_approval_resume_required
        assert resume_calls[0]["project_failed"] == service._project_approval_resume_failed
        assert resume_calls[0]["get_current_run"] == service.get_run
        assert ("reject", "run-1", "no") in calls
        assert ("timeout", "run-1", "approval_wait_timeout") in calls
        assert ("update-agent-group", run) in calls
    finally:
        service.close()


def test_run_control_facade_forwards_nonempty_approval_generation_ids() -> None:
    calls: list[tuple[str, str]] = []

    class _ApprovalExecution:
        @staticmethod
        def approve_run_approval(run_id: str, *, expected_approval_id: str) -> dict[str, Any]:
            calls.append(("approve", expected_approval_id))
            return {"run_id": run_id}

    class _ApprovalResumeDispatcher:
        @staticmethod
        def approve_once(run: dict[str, Any], *, expected_approval_id: str) -> dict[str, Any]:
            calls.append(("approve-once", expected_approval_id))
            return run

    class _ToolApprovalResume:
        @staticmethod
        def approve_main_chat_run(run: dict[str, Any], *, expected_approval_id: str) -> dict[str, Any]:
            calls.append(("approve-main", expected_approval_id))
            return run

    class _WorkflowApprovalExecution:
        @staticmethod
        def approve_workflow_run(run: dict[str, Any], *, expected_approval_id: str) -> dict[str, Any]:
            calls.append(("approve-workflow", expected_approval_id))
            return run

    class _ApprovalTransitions:
        @staticmethod
        def reject(
            run_id: str,
            reason: str,
            *,
            expected_approval_id: str,
        ) -> dict[str, Any]:
            calls.append(("reject", expected_approval_id))
            return {"run_id": run_id, "reason": reason}

        @staticmethod
        def timeout(
            run_id: str,
            reason: str,
            *,
            expected_approval_id: str,
        ) -> dict[str, Any]:
            calls.append(("timeout", expected_approval_id))
            return {"run_id": run_id, "reason": reason}

    class _ApprovalResume:
        @staticmethod
        def resume_approved_tool_run(**kwargs: Any) -> dict[str, Any]:
            calls.append(("resume", kwargs["expected_approval_id"]))
            return {"run_id": kwargs["run_id"]}

    class _Service(RuntimeRunControlFacadeMixin):
        approval_execution = _ApprovalExecution()
        approval_resume_dispatcher = _ApprovalResumeDispatcher()
        tool_approval_resume = _ToolApprovalResume()
        workflow_approval_execution = _WorkflowApprovalExecution()
        approval_transitions = _ApprovalTransitions()
        approval_resume = _ApprovalResume()

        @staticmethod
        def get_run(run_id: str) -> dict[str, Any]:
            return {"run_id": run_id}

        @staticmethod
        def _project_approval_resume_required(*_args: Any) -> dict[str, Any]:
            return {}

        @staticmethod
        def _project_approval_resume_failed(*_args: Any) -> dict[str, Any]:
            return {}

    service = _Service()
    run = {
        "run_id": "run-1",
        "pending_approval": {"approval_id": "approval-from-run"},
    }

    service.approve_run_approval("run-1", " approval-explicit ")
    service._approve_run_approval_once(run)
    service._approve_main_chat_run_approval(run)
    service._approve_workflow_run_approval(run)
    service.reject_run_approval("run-1", "no", "approval-reject")
    service.timeout_run_approval("run-1", expected_approval_id="approval-timeout")
    service._resume_approved_tool_run(
        run_id="run-1",
        pending=run["pending_approval"],
        resume_context={"run_id": "run-1"},
        agent={"agent_id": "agent-1"},
        resumed_detail="resumed",
        running_result="running",
        project_completed=lambda *_args: {},
        expected_approval_id="approval-resume",
    )

    assert calls == [
        ("approve", "approval-explicit"),
        ("approve-once", "approval-from-run"),
        ("approve-main", "approval-from-run"),
        ("approve-workflow", "approval-from-run"),
        ("reject", "approval-reject"),
        ("timeout", "approval-timeout"),
        ("resume", "approval-resume"),
    ]
