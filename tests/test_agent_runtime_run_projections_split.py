"""Tests for run projection coordinators split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.agent.runtime.run_projections import (
    AgentRunGroupProjectionCoordinator,
    ApprovalResumeProjectionCoordinator,
    RunProjectionCoordinator,
)
from apps.shell.credential_store import MemoryCredentialStore


def test_run_projection_coordinators_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RunProjectionCoordinator is RunProjectionCoordinator
    assert (
        agent_runtime.AgentRunGroupProjectionCoordinator
        is AgentRunGroupProjectionCoordinator
    )
    assert (
        agent_runtime.ApprovalResumeProjectionCoordinator
        is ApprovalResumeProjectionCoordinator
    )


def test_native_runtime_installs_agent_run_group_projection_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(
            service.agent_run_group_projection,
            AgentRunGroupProjectionCoordinator,
        )
        assert callable(service.agent_run_group_projection._get_run_group)
        assert callable(service.agent_run_group_projection._update_run_group)
    finally:
        service.close()


def test_agent_run_group_projection_updates_only_root_agent_groups() -> None:
    updates: list[dict[str, object]] = []
    groups = {
        "agent-group": {
            "run_group_id": "agent-group",
            "source": "agent",
            "child_run_ids": ["agent-run"],
        },
        "delegation-group": {
            "run_group_id": "delegation-group",
            "source": "delegation",
            "child_run_ids": ["delegation-run"],
        },
        "workflow-root-group": {
            "run_group_id": "workflow-root-group",
            "source": "workflow",
            "child_run_ids": ["workflow-root-run"],
        },
        "workflow-child-group": {
            "run_group_id": "workflow-child-group",
            "source": "workflow",
            "child_run_ids": ["workflow-root-run", "workflow-child-run"],
        },
    }
    coordinator = AgentRunGroupProjectionCoordinator(
        get_run_group=lambda run_group_id: groups[run_group_id],
        update_run_group=lambda run_group_id, **kwargs: updates.append(
            {"run_group_id": run_group_id, **kwargs}
        ),
    )

    coordinator.update_if_root({"run_id": "no-group-run", "status": "completed"})
    coordinator.update_if_root(
        {
            "run_id": "missing-group-run",
            "run_group_id": "missing-group",
            "status": "failed",
            "result": "missing",
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "agent-run",
            "run_group_id": "agent-group",
            "status": "completed",
            "result": "agent done",
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "delegation-run",
            "run_group_id": "delegation-group",
            "status": "failed",
            "result": "delegation failed",
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "workflow-root-run",
            "run_group_id": "workflow-root-group",
            "status": "cancelled",
            "result": "workflow cancelled",
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "workflow-child-run",
            "run_group_id": "workflow-child-group",
            "status": "completed",
            "result": "child done",
        }
    )

    assert updates == [
        {
            "run_group_id": "agent-group",
            "status": "completed",
            "summary": "agent done",
        },
        {
            "run_group_id": "delegation-group",
            "status": "failed",
            "summary": "delegation failed",
        },
        {
            "run_group_id": "workflow-root-group",
            "status": "cancelled",
            "summary": "workflow cancelled",
        },
    ]
