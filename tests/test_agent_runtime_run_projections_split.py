"""Tests for run projection coordinators split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.agent.runtime.errors import AgentRuntimeError
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

    coordinator.update_if_root(
        {
            "run_id": "no-group-run",
            "status": "completed",
            "project_root_group": True,
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "missing-group-run",
            "run_group_id": "missing-group",
            "status": "failed",
            "result": "missing",
            "project_root_group": True,
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "agent-run",
            "run_group_id": "agent-group",
            "status": "completed",
            "result": "agent done",
            "project_root_group": True,
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "delegation-run",
            "run_group_id": "delegation-group",
            "status": "failed",
            "result": "delegation failed",
            "project_root_group": True,
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "workflow-root-run",
            "run_group_id": "workflow-root-group",
            "status": "cancelled",
            "result": "workflow cancelled",
            "project_root_group": True,
        }
    )
    coordinator.update_if_root(
        {
            "run_id": "workflow-child-run",
            "run_group_id": "workflow-child-group",
            "status": "completed",
            "result": "child done",
            "project_root_group": False,
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


def test_agent_run_group_projection_is_idempotent_for_same_terminal_winner() -> None:
    updates: list[dict[str, object]] = []
    group = {
        "run_group_id": "agent-group",
        "source": "agent",
        "child_run_ids": ["agent-run"],
        "status": "completed",
        "summary": "done",
        "updated_at": "version-2",
    }
    coordinator = AgentRunGroupProjectionCoordinator(
        get_run_group=lambda _run_group_id: dict(group),
        update_run_group=lambda run_group_id, **kwargs: updates.append(
            {"run_group_id": run_group_id, **kwargs}
        ),
    )

    coordinator.update_if_root(
        {
            "run_id": "agent-run",
            "run_group_id": "agent-group",
            "status": "completed",
            "result": "done",
            "project_root_group": True,
        }
    )

    assert updates == []


def test_agent_run_group_projection_rejects_different_terminal_winner() -> None:
    coordinator = AgentRunGroupProjectionCoordinator(
        get_run_group=lambda _run_group_id: {
            "run_group_id": "agent-group",
            "source": "agent",
            "child_run_ids": ["agent-run"],
            "status": "failed",
            "summary": "other winner",
            "updated_at": "version-2",
        },
        update_run_group=lambda _run_group_id, **_kwargs: pytest.fail(
            "terminal winner must not be overwritten"
        ),
    )

    with pytest.raises(AgentRuntimeError, match="run_group_terminal_outcome_conflict"):
        coordinator.update_if_root(
            {
                "run_id": "agent-run",
                "run_group_id": "agent-group",
                "status": "completed",
                "result": "done",
                "project_root_group": True,
            }
        )


def test_agent_run_group_projection_fails_closed_when_group_cas_is_lost() -> None:
    reads = 0

    def get_run_group(_run_group_id: str) -> dict[str, object]:
        nonlocal reads
        reads += 1
        return {
            "run_group_id": "agent-group",
            "source": "agent",
            "child_run_ids": ["agent-run"],
            "status": "running" if reads == 1 else "failed",
            "summary": "" if reads == 1 else "other winner",
            "updated_at": f"version-{reads}",
        }

    coordinator = AgentRunGroupProjectionCoordinator(
        get_run_group=get_run_group,
        update_run_group=lambda _run_group_id, **_kwargs: None,
    )

    with pytest.raises(AgentRuntimeError, match="run_group_terminal_outcome_conflict"):
        coordinator.update_if_root(
            {
                "run_id": "agent-run",
                "run_group_id": "agent-group",
                "status": "completed",
                "result": "done",
                "project_root_group": True,
            }
        )
