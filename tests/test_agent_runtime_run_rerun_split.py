"""Tests for run rerun orchestration split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_rerun import RuntimeRunRerunService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_run_rerun_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunRerunService is RuntimeRunRerunService


def test_runtime_run_rerun_service_reruns_agent_and_records_replay_event() -> None:
    original = {
        "run_id": "run-original",
        "kind": "agent_run",
        "status": "completed",
        "runnable_id": "agent-1",
        "runnable_name": "Research",
        "user_goal": "Summarize notes",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:02Z",
    }
    created_requests: list[dict[str, Any]] = []
    appended_events: list[tuple[str, str, dict[str, Any]]] = []
    updated_runs: list[dict[str, Any]] = []

    def create_agent_run(payload: dict[str, Any]) -> dict[str, Any]:
        created_requests.append(payload)
        return {
            "run_id": "run-rerun",
            "kind": "agent_run",
            "status": "completed",
            "timeline": [{"event": "agent.run.completed", "detail": "Done"}],
        }

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        updated_runs.append({"run_id": run_id, **kwargs})
        return {
            "run_id": run_id,
            "kind": "agent_run",
            "status": "completed",
            **kwargs,
        }

    service = RuntimeRunRerunService(
        get_run=lambda _run_id: original,
        create_agent_run=create_agent_run,
        create_workflow_run=lambda _payload: pytest.fail("agent rerun should not create workflow"),
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        resolve_runnable=lambda **kwargs: {"id": kwargs["runnable_id"], "kind": "agent"},
        final_statuses={"completed", "failed", "cancelled"},
        error_type=AgentRuntimeError,
    )

    result = service.rerun("run-original")

    assert created_requests == [
        {"agent_id": "agent-1", "user_goal": "Summarize notes", "source": "rerun"}
    ]
    assert appended_events == [
        (
            "run-rerun",
            "run.rerun.started",
            {
                "rerun_of_run_id": "run-original",
                "rerun_of_kind": "agent_run",
                "rerun_of_status": "completed",
                "rerun_of_runnable_id": "agent-1",
                "rerun_of_runnable_name": "Research",
                "original_created_at": "2026-01-01T00:00:00Z",
                "original_updated_at": "2026-01-01T00:00:02Z",
                "input_preview": {
                    "original_run_id": "run-original",
                    "original_status": "completed",
                    "original_target": "Research",
                    "original_goal": "Summarize notes",
                },
            },
        )
    ]
    assert updated_runs[0]["timeline"][0]["event"] == "run.rerun.started"
    assert updated_runs[0]["timeline"][0]["rerun_of_run_id"] == "run-original"
    assert updated_runs[0]["timeline"][1] == {"event": "agent.run.completed", "detail": "Done"}
    assert result["agent_run_id"] == "run-rerun"
    assert result["runnable"] == {"id": "agent-1", "kind": "agent"}


def test_runtime_run_rerun_service_reruns_workflow() -> None:
    original = {
        "run_id": "workflow-original",
        "kind": "workflow_run",
        "status": "failed",
        "runnable_id": "workflow-1",
        "runnable_name": "",
        "user_goal": "Run the workflow",
    }
    created_requests: list[dict[str, Any]] = []

    def create_workflow_run(payload: dict[str, Any]) -> dict[str, Any]:
        created_requests.append(payload)
        return {
            "run_id": "workflow-rerun",
            "kind": "workflow_run",
            "status": "completed",
            "timeline": [],
        }

    service = RuntimeRunRerunService(
        get_run=lambda _run_id: original,
        create_agent_run=lambda _payload: pytest.fail("workflow rerun should not create agent"),
        create_workflow_run=create_workflow_run,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda *_args: None,
        update_run=lambda run_id, **kwargs: {
            "run_id": run_id,
            "kind": "workflow_run",
            **kwargs,
        },
        resolve_runnable=lambda **kwargs: {"id": kwargs["runnable_id"], "kind": "workflow"},
        final_statuses={"completed", "failed", "cancelled"},
        error_type=AgentRuntimeError,
    )

    result = service.rerun("workflow-original")

    assert created_requests == [
        {"workflow_id": "workflow-1", "user_goal": "Run the workflow", "source": "rerun"}
    ]
    assert result["workflow_run_id"] == "workflow-rerun"
    assert result["runnable"] == {"id": "workflow-1", "kind": "workflow"}
    assert result["timeline"][0]["input_preview"]["original_target"] == "workflow-1"


def test_runtime_run_rerun_service_reruns_workflow_branch_from_target_node() -> None:
    original = {
        "run_id": "workflow-original",
        "kind": "workflow_run",
        "status": "failed",
        "runnable_id": "workflow-1",
        "runnable_name": "Review flow",
        "user_goal": "Run the workflow",
    }
    created_requests: list[dict[str, Any]] = []
    appended_events: list[tuple[str, str, dict[str, Any]]] = []

    def create_workflow_run(payload: dict[str, Any]) -> dict[str, Any]:
        created_requests.append(payload)
        return {
            "run_id": "workflow-rerun",
            "kind": "workflow_run",
            "status": "completed",
            "timeline": [],
        }

    service = RuntimeRunRerunService(
        get_run=lambda _run_id: original,
        create_agent_run=lambda _payload: pytest.fail("workflow rerun should not create agent"),
        create_workflow_run=create_workflow_run,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: appended_events.append(
            (run_id, event_type, payload)
        ),
        update_run=lambda run_id, **kwargs: {
            "run_id": run_id,
            "kind": "workflow_run",
            **kwargs,
        },
        resolve_runnable=lambda **kwargs: {"id": kwargs["runnable_id"], "kind": "workflow"},
        final_statuses={"completed", "failed", "cancelled"},
        error_type=AgentRuntimeError,
    )

    result = service.rerun(
        "workflow-original",
        {
            "scope": "workflow_branch",
            "workflow_node_id": "route",
            "workflow_node_label": "Route",
            "workflow_edge_branch": "true",
            "workflow_node_selected_target": "ship",
            "reason": "Retry selected branch",
        },
    )

    assert created_requests == [
        {
            "workflow_id": "workflow-1",
            "user_goal": "Run the workflow",
            "source": "rerun",
            "start_node_id": "ship",
            "rerun_scope": "workflow_branch",
            "workflow_node_id": "route",
            "workflow_node_label": "Route",
            "workflow_edge_branch": "true",
            "workflow_node_selected_target": "ship",
        }
    ]
    assert appended_events[0][0] == "workflow-rerun"
    assert appended_events[0][1] == "run.rerun.started"
    assert appended_events[0][2]["rerun_scope"] == "workflow_branch"
    assert appended_events[0][2]["workflow_node_id"] == "route"
    assert appended_events[0][2]["workflow_edge_branch"] == "true"
    assert appended_events[0][2]["workflow_node_selected_target"] == "ship"
    assert appended_events[0][2]["workflow_start_node_id"] == "ship"
    assert appended_events[0][2]["input_preview"]["workflow_start_node_id"] == "ship"
    assert result["workflow_run_id"] == "workflow-rerun"


@pytest.mark.parametrize(
    ("run", "message"),
    [
        (
            {"run_id": "run-active", "kind": "agent_run", "status": "running"},
            "当前 Run 还在进行中，不能重跑",
        ),
        (
            {"run_id": "run-no-goal", "kind": "agent_run", "status": "completed"},
            "原 Run 没有记录任务目标，无法重跑",
        ),
        (
            {
                "run_id": "run-main-chat",
                "kind": "main_chat_run",
                "status": "completed",
                "user_goal": "Chat",
            },
            "不支持重跑这个 Run 类型",
        ),
    ],
)
def test_runtime_run_rerun_service_rejects_invalid_reruns(
    run: dict[str, Any],
    message: str,
) -> None:
    service = RuntimeRunRerunService(
        get_run=lambda _run_id: run,
        create_agent_run=lambda _payload: pytest.fail("invalid rerun should not create agent"),
        create_workflow_run=lambda _payload: pytest.fail(
            "invalid rerun should not create workflow"
        ),
        timeline_factory=lambda *_args, **_kwargs: {},
        append_run_event=lambda *_args, **_kwargs: pytest.fail(
            "invalid rerun should not append events"
        ),
        update_run=lambda *_args, **_kwargs: pytest.fail("invalid rerun should not update"),
        resolve_runnable=lambda **_kwargs: None,
        final_statuses={"completed", "failed", "cancelled"},
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match=message):
        service.rerun(str(run["run_id"]))


def test_native_runtime_installs_run_rerun_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.run_rerun, RuntimeRunRerunService)
    finally:
        service.close()
