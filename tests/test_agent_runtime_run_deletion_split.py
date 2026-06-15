"""Tests for run deletion orchestration split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_deletion import RuntimeRunDeletionService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_run_deletion_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunDeletionService is RuntimeRunDeletionService


def test_runtime_run_deletion_service_deletes_terminal_run_and_updates_group_membership() -> None:
    run = {
        "run_id": "run-agent",
        "kind": "agent_run",
        "status": "completed",
        "run_group_id": "group-1",
    }
    deleted_targets: list[list[str]] = []
    removed_members: list[tuple[str, set[str]]] = []
    commits: list[bool] = []

    service = RuntimeRunDeletionService(
        get_run=lambda _run_id: run,
        group_runs=lambda _run_group_id: pytest.fail("plain run should not load group runs"),
        delete_run_rows=lambda targets, **kwargs: deleted_targets.append(
            [str(item["run_id"]) for item in targets]
        )
        or [str(item["run_id"]) for item in targets],
        delete_artifacts=lambda *_args, **_kwargs: None,
        delete_group=lambda _run_group_id: pytest.fail("plain run should not delete group"),
        remove_group_run_ids=lambda run_group_id, deleted_ids: removed_members.append(
            (run_group_id, deleted_ids)
        ),
        commit=lambda: commits.append(True),
        is_active_run_status=lambda status: status not in {"completed", "failed", "cancelled"},
        error_type=AgentRuntimeError,
    )

    result = service.delete("run-agent")

    assert result == {
        "ok": True,
        "deleted_run_ids": ["run-agent"],
        "deleted_run_count": 1,
    }
    assert deleted_targets == [["run-agent"]]
    assert removed_members == [("group-1", {"run-agent"})]
    assert commits == [True]


def test_runtime_run_deletion_service_deletes_completed_workflow_group() -> None:
    parent = {
        "run_id": "run-workflow",
        "kind": "workflow_run",
        "status": "completed",
        "run_group_id": "group-1",
    }
    child = {
        "run_id": "run-child",
        "kind": "agent_run",
        "status": "completed",
        "run_group_id": "group-1",
    }
    deleted_groups: list[str] = []
    removed_members: list[tuple[str, set[str]]] = []

    service = RuntimeRunDeletionService(
        get_run=lambda _run_id: parent,
        group_runs=lambda _run_group_id: [parent, child],
        delete_run_rows=lambda targets, **_kwargs: [str(item["run_id"]) for item in targets],
        delete_artifacts=lambda *_args, **_kwargs: None,
        delete_group=lambda run_group_id: deleted_groups.append(run_group_id),
        remove_group_run_ids=lambda run_group_id, deleted_ids: removed_members.append(
            (run_group_id, deleted_ids)
        ),
        commit=lambda: None,
        is_active_run_status=lambda status: status not in {"completed", "failed", "cancelled"},
        error_type=AgentRuntimeError,
    )

    result = service.delete("run-workflow")

    assert result == {
        "ok": True,
        "deleted_run_ids": ["run-workflow", "run-child"],
        "deleted_run_count": 2,
    }
    assert deleted_groups == ["group-1"]
    assert removed_members == []


@pytest.mark.parametrize(
    ("run", "group_runs", "message"),
    [
        (
            {"run_id": "run-active", "kind": "agent_run", "status": "running"},
            [],
            "Run 仍在进行中或待审批，取消或完成后才能删除",
        ),
        (
            {
                "run_id": "run-workflow",
                "kind": "workflow_run",
                "status": "completed",
                "run_group_id": "group-1",
            },
            [
                {"run_id": "run-workflow", "status": "completed"},
                {"run_id": "run-child", "status": "approval_required"},
            ],
            "这个 Workflow Run 仍有进行中或待审批的子 Run，取消或完成后才能删除",
        ),
    ],
)
def test_runtime_run_deletion_service_rejects_active_deletions(
    run: dict[str, Any],
    group_runs: list[dict[str, Any]],
    message: str,
) -> None:
    service = RuntimeRunDeletionService(
        get_run=lambda _run_id: run,
        group_runs=lambda _run_group_id: group_runs,
        delete_run_rows=lambda *_args, **_kwargs: pytest.fail(
            "invalid deletion should not delete rows"
        ),
        delete_artifacts=lambda *_args, **_kwargs: None,
        delete_group=lambda _run_group_id: pytest.fail(
            "invalid deletion should not delete groups"
        ),
        remove_group_run_ids=lambda *_args: pytest.fail(
            "invalid deletion should not update group members"
        ),
        commit=lambda: pytest.fail("invalid deletion should not commit"),
        is_active_run_status=lambda status: status not in {"completed", "failed", "cancelled"},
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match=message):
        service.delete(str(run["run_id"]))


def test_native_runtime_installs_run_deletion_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.run_deletion, RuntimeRunDeletionService)
    finally:
        service.close()
