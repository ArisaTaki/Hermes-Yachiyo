"""Tests for approval service setup split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_lifecycle import (
    ApprovalCoordinator,
    ApprovalPauseProjectionCoordinator,
)
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.approval_services import (
    RuntimeApprovalServiceBundle,
    build_runtime_approval_services,
)
from apps.shell.agent.runtime.approval_snapshots import ApprovalSnapshotBuilder
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_approval_service_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeApprovalServiceBundle is RuntimeApprovalServiceBundle


def test_build_runtime_approval_services_wires_pause_approve_and_resume() -> None:
    snapshots = ApprovalSnapshotBuilder()

    def timeline_factory(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {"event": event, "detail": detail, **extra}

    bundle = build_runtime_approval_services(
        timeline_factory=timeline_factory,
        append_run_event=lambda _run_id, _event_type, _payload: None,
        update_run=lambda run_id, **kwargs: {"run_id": run_id, **kwargs},
        get_run=lambda run_id: {
            "run_id": run_id,
            "status": "running",
            "pending_approval": {},
            "updated_at": "2026-07-11T10:00:00+00:00",
        },
        snapshots=snapshots,
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True},
        fatal_tool_failure_detail=lambda *_args, **_kwargs: "",
        append_tool_result_message=lambda *_args, **_kwargs: None,
        run_tool_requests=lambda *_args, **_kwargs: None,
        claim_pending_approval=lambda *_args, **_kwargs: True,
        continue_custom_api_agent=lambda *_args, **_kwargs: "done",
    )

    assert isinstance(bundle, RuntimeApprovalServiceBundle)
    assert isinstance(bundle.approval_pause, ApprovalPauseProjectionCoordinator)
    assert isinstance(bundle.approvals, ApprovalCoordinator)
    assert isinstance(bundle.approval_resume, ApprovalResumeCoordinator)
    assert bundle.approval_pause._snapshots is snapshots
    assert bundle.approval_resume._approve_tool_run.__self__ is bundle.approvals
    assert bundle.approval_resume._timeline is timeline_factory


def test_native_runtime_installs_approval_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.approval_pause, ApprovalPauseProjectionCoordinator)
        assert isinstance(service.approvals, ApprovalCoordinator)
        assert isinstance(service.approval_resume, ApprovalResumeCoordinator)
        assert service.approval_pause._snapshots is service.approval_snapshots
        assert service.approval_resume._approve_tool_run.__self__ is service.approvals
        assert service.approval_resume._claim_pending_approval.__self__ is service.run_approvals
        assert service.approval_resume._continue_custom_api_agent.__self__ is service
    finally:
        service.close()
