#!/usr/bin/env python3
"""Smoke-test runtime approval resume orchestration without real providers."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.runtime.approval_execution import RuntimeApprovalExecutionService
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext

RUN_ID = "run-runtime-approval-smoke"
TOOL_NAME = "terminal.run"
APPROVAL_ID = "approval-runtime-terminal"


def _timeline(event: str, detail: str = "", **payload: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **payload}


def _context(*, remaining_requests: list[dict[str, Any]] | None = None) -> ToolApprovalResumeContext:
    return ToolApprovalResumeContext(
        run_id=RUN_ID,
        timeline=[
            {
                "event": "agent.tool.approval_required",
                "detail": TOOL_NAME,
                "approval_id": APPROVAL_ID,
            }
        ],
        artifacts=[{"path": "approval/context.md", "kind": "markdown"}],
        broker=SimpleNamespace(name="broker"),
        allowed_tools=[TOOL_NAME, "artifact.write"],
        budget=SimpleNamespace(name="budget"),
        messages=[{"role": "user", "content": "Run the approved command"}],
        tool_request={"tool": TOOL_NAME, "input": {"command": "printf ok"}},
        tool_name=TOOL_NAME,
        input_preview={"command": "printf ok"},
        remaining_requests=remaining_requests
        if remaining_requests is not None
        else [{"tool": "artifact.write", "input": {"path": "approval/result.md"}}],
        next_iteration=4,
    )


def _coordinator(
    *,
    mode: str,
    calls: list[dict[str, Any]],
    claim_result: bool = True,
) -> ApprovalResumeCoordinator:
    def claim_pending_approval(run_id: str, pending: dict[str, Any]) -> bool:
        calls.append(
            {
                "name": "claim_pending_approval",
                "run_id": run_id,
                "approval_id": pending.get("approval_id"),
                "result": claim_result,
            }
        )
        return claim_result

    def approve_tool_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        calls.append(
            {
                "name": "approve_tool_run",
                "run_id": run_id,
                "tool": kwargs.get("tool_name"),
                "resumed_detail": kwargs.get("resumed_detail"),
                "running_result": kwargs.get("running_result"),
            }
        )
        return {
            "run_id": run_id,
            "status": "running",
            "result": kwargs.get("running_result"),
        }

    def call_agent_tool(
        tool_request: dict[str, Any],
        allowed_tools: list[str],
        broker: Any,
        timeline: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(
            {
                "name": "call_agent_tool",
                "tool": tool_request.get("tool"),
                "approved": kwargs.get("approved"),
                "run_id": kwargs.get("run_id"),
                "allowed": list(allowed_tools),
                "broker": getattr(broker, "name", ""),
            }
        )
        if mode == "fatal":
            return {"ok": False, "stderr": "denied"}
        timeline.append(
            {
                "event": "agent.tool.completed",
                "detail": tool_request.get("tool"),
                "result": {"ok": True, "stdout": "ok"},
            }
        )
        return {"ok": True, "stdout": "ok"}

    def fatal_tool_failure_detail(
        _tool_name: str,
        _tool_request: dict[str, Any],
        tool_result: Any,
    ) -> str:
        calls.append({"name": "fatal_tool_failure_detail", "fatal": mode == "fatal"})
        if mode == "fatal" and isinstance(tool_result, dict):
            return "terminal.run failed fatally"
        return ""

    def append_tool_result_message(
        messages: list[dict[str, Any]],
        _tool_request: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> None:
        calls.append({"name": "append_tool_result_message", "ok": tool_result.get("ok")})
        messages.append({"role": "tool", "content": json.dumps(tool_result, sort_keys=True)})

    def run_tool_requests(
        remaining_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        calls.append(
            {
                "name": "run_tool_requests",
                "remaining_tools": [item.get("tool") for item in remaining_requests],
                "next_iteration": kwargs.get("next_iteration"),
                "run_id": kwargs.get("run_id"),
            }
        )
        if remaining_requests:
            timeline.append(
                {
                    "event": "agent.tool.completed",
                    "detail": "artifact.write",
                    "result": {"ok": True, "path": "approval/result.md"},
                }
            )
            artifacts.append({"path": "approval/result.md", "kind": "markdown"})

    def continue_custom_api_agent(
        agent: dict[str, Any],
        user_goal: str,
        broker: Any,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        **kwargs: Any,
    ) -> str:
        calls.append(
            {
                "name": "continue_custom_api_agent",
                "agent_id": agent.get("agent_id"),
                "user_goal": user_goal,
                "broker": getattr(broker, "name", ""),
                "timeline_events": [item.get("event") for item in timeline],
                "artifact_paths": [item.get("path") for item in artifacts],
                "start_iteration": kwargs.get("start_iteration"),
                "run_id": kwargs.get("run_id"),
            }
        )
        if mode == "required":
            raise AgentApprovalRequired(
                {
                    "tool": "artifact.write",
                    "approval_id": "approval-next-artifact",
                }
            )
        return "resumed model output"

    return ApprovalResumeCoordinator(
        call_agent_tool=call_agent_tool,
        fatal_tool_failure_detail=fatal_tool_failure_detail,
        append_tool_result_message=append_tool_result_message,
        run_tool_requests=run_tool_requests,
        timeline_factory=_timeline,
        claim_pending_approval=claim_pending_approval,
        approve_tool_run=approve_tool_run,
        continue_custom_api_agent=continue_custom_api_agent,
    )


def _run_resume_mode(mode: str) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    context = _context()
    coordinator = _coordinator(mode=mode, calls=calls)

    def project_running(running: dict[str, Any]) -> dict[str, Any]:
        calls.append({"name": "project_running", "status": running.get("status")})
        return {**running, "projected_running": True}

    def project_completed(
        completed_context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        calls.append({"name": "project_completed", "result_text": result_text})
        return {
            "status": "completed",
            "result": result_text,
            "timeline_events": [item.get("event") for item in completed_context.timeline],
            "artifact_paths": [item.get("path") for item in completed_context.artifacts],
            "message_roles": [item.get("role") for item in completed_context.messages],
        }

    def prepare_required(pending: dict[str, Any]) -> dict[str, Any]:
        calls.append({"name": "prepare_required", "tool": pending.get("tool")})
        return {**pending, "resume_kind": "runtime_approval_resume_smoke"}

    def project_required(
        required_context: ToolApprovalResumeContext,
        pending: dict[str, Any],
    ) -> dict[str, Any]:
        calls.append({"name": "project_required", "tool": pending.get("tool")})
        return {
            "status": "approval_required",
            "pending_approval": pending,
            "timeline_events": [item.get("event") for item in required_context.timeline],
        }

    def project_failed(
        failed_context: ToolApprovalResumeContext,
        safe_error: str,
    ) -> dict[str, Any]:
        calls.append({"name": "project_failed", "safe_error": safe_error})
        return {
            "status": "failed",
            "error": safe_error,
            "timeline_events": [item.get("event") for item in failed_context.timeline],
        }

    def project_result(result: dict[str, Any]) -> dict[str, Any]:
        calls.append({"name": "project_result", "status": result.get("status")})
        return {**result, "finalized": True}

    result = coordinator.resume_approved_tool_run(
        run_id=RUN_ID,
        pending={"tool": TOOL_NAME, "approval_id": APPROVAL_ID},
        context=context,
        agent={"agent_id": "agent-runtime-smoke"},
        resumed_detail="Agent resumed after approval",
        running_result="已批准，Agent 正在继续执行",
        project_completed=project_completed,
        project_required=project_required,
        project_failed=project_failed,
        get_current_run=lambda run_id: {"run_id": run_id, "status": "approval_required"},
        project_running=project_running,
        prepare_required=prepare_required,
        project_result=project_result,
        redact_error=lambda exc: f"safe {type(exc).__name__}",
    )
    return {
        "ok": _resume_mode_ok(mode, result, calls),
        "mode": mode,
        "result": result,
        "call_order": [call["name"] for call in calls],
        "calls": calls,
    }


def _resume_mode_ok(mode: str, result: dict[str, Any], calls: list[dict[str, Any]]) -> bool:
    names = [call["name"] for call in calls]
    if mode == "completed":
        return (
            result.get("status") == "completed"
            and result.get("finalized") is True
            and result.get("result") == "resumed model output"
            and "continue_custom_api_agent" in names
            and "run_tool_requests" in names
            and any(call.get("approved") is True for call in calls if call["name"] == "call_agent_tool")
        )
    if mode == "required":
        return (
            result.get("status") == "approval_required"
            and result.get("pending_approval", {}).get("resume_kind")
            == "runtime_approval_resume_smoke"
            and names[-2:] == ["project_required", "project_result"]
        )
    if mode == "fatal":
        return (
            result.get("status") == "failed"
            and result.get("error") == "safe AgentRuntimeError"
            and "agent.tool.failed" in result.get("timeline_events", [])
            and "continue_custom_api_agent" not in names
            and "run_tool_requests" not in names
        )
    return False


def _duplicate_claim_evidence() -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    context = _context(remaining_requests=[])
    coordinator = _coordinator(mode="completed", calls=calls, claim_result=False)
    result = coordinator.resume_approved_tool_run(
        run_id=RUN_ID,
        pending={"tool": TOOL_NAME, "approval_id": APPROVAL_ID},
        context=context,
        agent={"agent_id": "agent-runtime-smoke"},
        resumed_detail="Agent resumed after approval",
        running_result="已批准，Agent 正在继续执行",
        project_completed=lambda *_args: {"status": "unexpected"},
        project_required=lambda *_args: {"status": "unexpected"},
        project_failed=lambda *_args: {"status": "unexpected"},
        get_current_run=lambda run_id: calls.append({"name": "get_current_run", "run_id": run_id})
        or {"run_id": run_id, "status": "approval_required"},
    )
    call_order = [call["name"] for call in calls]
    return {
        "ok": result == {"run_id": RUN_ID, "status": "approval_required"}
        and call_order == ["claim_pending_approval", "get_current_run"],
        "result": result,
        "call_order": call_order,
        "calls": calls,
    }


def _execution_gate_evidence() -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    execution_in_progress: set[str] = set()
    lock = threading.RLock()
    state = {"run": {"run_id": RUN_ID, "kind": "agent_run", "status": "approval_required"}}

    def get_run(run_id: str) -> dict[str, Any]:
        calls.append({"name": "get_run", "run_id": run_id, "status": state["run"]["status"]})
        return dict(state["run"])

    def approve_once(run: dict[str, Any]) -> dict[str, Any]:
        calls.append({"name": "approve_once", "run_id": run["run_id"]})
        return {**run, "status": "completed"}

    service = RuntimeApprovalExecutionService(
        execution_lock=lock,
        execution_in_progress=execution_in_progress,
        get_run=get_run,
        approve_once=approve_once,
    )
    completed = service.approve_run_approval(RUN_ID)
    state["run"] = {"run_id": RUN_ID, "kind": "agent_run", "status": "completed"}
    already_completed = service.approve_run_approval(RUN_ID)
    state["run"] = {"run_id": RUN_ID, "kind": "agent_run", "status": "approval_required"}
    execution_in_progress.add(RUN_ID)
    duplicate = service.approve_run_approval(RUN_ID)
    execution_in_progress.discard(RUN_ID)
    call_order = [call["name"] for call in calls]
    return {
        "ok": completed.get("status") == "completed"
        and already_completed.get("status") == "completed"
        and duplicate.get("status") == "approval_required"
        and call_order == ["get_run", "approve_once", "get_run", "get_run"]
        and not execution_in_progress,
        "completed": completed,
        "already_completed": already_completed,
        "duplicate": duplicate,
        "call_order": call_order,
        "calls": calls,
    }


def run_smoke() -> dict[str, Any]:
    completed = _run_resume_mode("completed")
    required = _run_resume_mode("required")
    fatal = _run_resume_mode("fatal")
    duplicate = _duplicate_claim_evidence()
    execution_gate = _execution_gate_evidence()
    return {
        "ok": all(
            item["ok"]
            for item in (completed, required, fatal, duplicate, execution_gate)
        ),
        "mode": "runtime_approval_resume_smoke",
        "completed": completed,
        "required": required,
        "fatal": fatal,
        "duplicate_claim": duplicate,
        "execution_gate": execution_gate,
    }


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description=__doc__)


def main(argv: Sequence[str] | None = None) -> int:
    _parser().parse_args(argv)
    evidence = run_smoke()
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
