"""Tests for Workflow Run creation split out of the legacy runtime."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_group_attachments import (
    RUN_GROUP_ATTACHMENT_PAYLOAD_KEY,
    issue_run_group_child_attachment,
)
from apps.shell.agent.runtime.workflow_runs import (
    RuntimeWorkflowRunAsyncCoordinator,
    RuntimeWorkflowRunCoordinator,
    RuntimeWorkflowRunStarter,
    WorkflowRunStart,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class _ImmediateThread:
    def __init__(self, *, target: Any, name: str, daemon: bool) -> None:
        self._target = target
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        self._target()


def _starter(
    state: dict[str, Any],
    *,
    client_request_id_from_payload=lambda payload: str(payload.get("client_run_id") or ""),
) -> RuntimeWorkflowRunStarter:
    def get_run_group(run_group_id: str) -> dict[str, Any]:
        state.setdefault("validated_groups", []).append(run_group_id)
        return state.get("group_records", {}).get(
            run_group_id,
            {
                "run_group_id": run_group_id,
                "status": "running",
                "child_run_ids": ["parent-run-1"],
            },
        )

    def insert_run_group(**kwargs: Any) -> dict[str, Any]:
        run_group_id = f"group-{len(state.setdefault('groups', [])) + 1}"
        group = {"run_group_id": run_group_id, **kwargs}
        state["groups"].append(group)
        return group

    def insert_run(**kwargs: Any) -> dict[str, Any]:
        run = {"run_id": f"run-{len(state.setdefault('runs', [])) + 1}", **kwargs}
        state["runs"].append(run)
        client_request_id = str(kwargs.get("client_request_id") or "")
        if client_request_id:
            state.setdefault("by_client", {})[client_request_id] = {**run, "idempotent": True}
        return run

    def get_run(run_id: str) -> dict[str, Any]:
        return state.get("run_records", {}).get(
            run_id,
            {
                "run_id": run_id,
                "run_group_id": "group-existing",
                "kind": "workflow_run",
            },
        )

    return RuntimeWorkflowRunStarter(
        get_run_group=get_run_group,
        get_run=get_run,
        insert_run_group=insert_run_group,
        insert_run=insert_run,
        run_by_client_request_id=lambda value: state.setdefault("by_client", {}).get(value),
        client_request_id_from_payload=client_request_id_from_payload,
    )


def test_workflow_run_starter_creates_root_group_and_preserves_idempotency() -> None:
    state: dict[str, Any] = {}
    starter = _starter(state)
    workflow = {"workflow_id": "workflow-1", "name": "Runner Flow"}
    payload = {"workflow_id": "workflow-1", "user_goal": "Finish", "client_run_id": "client-1"}

    first = starter.start_sync(payload, workflow=workflow, workflow_id="workflow-1", lock=threading.RLock())
    second = starter.start_sync(payload, workflow=workflow, workflow_id="workflow-1", lock=threading.RLock())

    assert first.existing is False
    assert first.root_group is True
    assert first.run["kind"] == "workflow_run"
    assert first.run["runnable_id"] == "workflow-1"
    assert first.run["run_group_id"] == "group-1"
    assert first.run["project_root_group"] is True
    assert first.run["client_request_id"] == "client-1"
    assert state["groups"] == [
        {
            "run_group_id": "group-1",
            "title": "Runner Flow: Finish",
            "source": "workflow",
            "workspace_dir": "",
        }
    ]
    assert second.existing is True
    assert second.run["idempotent"] is True
    assert second.run["run_id"] == first.run["run_id"]
    assert len(state["runs"]) == 1


def test_workflow_run_starter_rejects_existing_group_without_internal_lineage() -> None:
    state: dict[str, Any] = {}
    starter = _starter(state)

    with pytest.raises(RuntimeError, match="run_group_attachment_authority_required"):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Run in group",
                "run_group_id": "group-existing",
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )

    assert state.get("runs") is None


def test_workflow_run_starter_does_not_trust_metadata_lineage() -> None:
    state: dict[str, Any] = {}
    starter = _starter(state)
    nested_marker = issue_run_group_child_attachment(
        run_group_id="group-existing",
        parent_run_id="parent-run-1",
        workflow_run_id="parent-run-1",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity="workflow-node:child-1",
    )

    with pytest.raises(RuntimeError, match="run_group_attachment_authority_required"):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Run with metadata lineage",
                "run_group_id": "group-existing",
                "metadata": {RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: nested_marker},
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )

    assert state.get("runs") is None


def test_workflow_run_starter_rejects_terminal_parent_group() -> None:
    state: dict[str, Any] = {
        "group_records": {
            "group-terminal": {
                "run_group_id": "group-terminal",
                "status": "completed",
                "child_run_ids": ["parent-run-1"],
            }
        }
    }
    starter = _starter(state)
    attachment = issue_run_group_child_attachment(
        run_group_id="group-terminal",
        parent_run_id="parent-run-1",
        workflow_run_id="parent-run-1",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity="workflow-node:child-1",
    )

    with pytest.raises(RuntimeError, match="run_group_attachment_group_not_active"):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Run in terminal group",
                "run_group_id": "group-terminal",
                "client_run_id": attachment.child_identity,
                RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: attachment,
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )

    assert state.get("runs") is None


def test_workflow_run_starter_rejects_forged_parent_lineage() -> None:
    state: dict[str, Any] = {
        "group_records": {
            "group-active": {
                "run_group_id": "group-active",
                "status": "running",
                "child_run_ids": ["real-parent-run"],
            }
        }
    }
    starter = _starter(state)
    forged = issue_run_group_child_attachment(
        run_group_id="group-active",
        parent_run_id="forged-parent-run",
        workflow_run_id="forged-parent-run",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity="workflow-node:child-1",
    )

    with pytest.raises(RuntimeError, match="run_group_attachment_parent_not_member"):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Run with forged parent",
                "run_group_id": "group-active",
                "client_run_id": forged.child_identity,
                RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: forged,
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )

    assert state.get("runs") is None


def test_workflow_run_starter_rejects_parent_row_from_unrelated_group() -> None:
    state: dict[str, Any] = {
        "group_records": {
            "group-active": {
                "run_group_id": "group-active",
                "status": "running",
                "child_run_ids": ["parent-run-1"],
            }
        },
        "run_records": {
            "parent-run-1": {
                "run_id": "parent-run-1",
                "run_group_id": "group-unrelated",
                "kind": "workflow_run",
            }
        },
    }
    starter = _starter(state)
    attachment = issue_run_group_child_attachment(
        run_group_id="group-active",
        parent_run_id="parent-run-1",
        workflow_run_id="parent-run-1",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity="workflow-node:child-1",
    )

    with pytest.raises(RuntimeError, match="run_group_attachment_parent_group_mismatch"):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Run with unrelated parent",
                "run_group_id": "group-active",
                "client_run_id": attachment.child_identity,
                RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: attachment,
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )

    assert state.get("runs") is None


def test_workflow_run_starter_rejects_child_runnable_mismatch() -> None:
    state: dict[str, Any] = {
        "group_records": {
            "group-active": {
                "run_group_id": "group-active",
                "status": "running",
                "child_run_ids": ["parent-run-1"],
            }
        },
        "run_records": {
            "parent-run-1": {
                "run_id": "parent-run-1",
                "run_group_id": "group-active",
                "kind": "workflow_run",
            }
        },
    }
    starter = _starter(state)
    wrong_child = issue_run_group_child_attachment(
        run_group_id="group-active",
        parent_run_id="parent-run-1",
        workflow_run_id="parent-run-1",
        child_kind="workflow_run",
        child_runnable_id="workflow-other",
        child_identity="workflow-node:child-1",
    )

    with pytest.raises(RuntimeError, match="run_group_attachment_child_identity_mismatch"):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Run with wrong child identity",
                "run_group_id": "group-active",
                "client_run_id": wrong_child.child_identity,
                RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: wrong_child,
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )

    assert state.get("runs") is None


def test_workflow_run_starter_rejects_marker_replay_for_another_child_identity() -> None:
    state: dict[str, Any] = {
        "group_records": {
            "group-active": {
                "run_group_id": "group-active",
                "status": "running",
                "child_run_ids": ["parent-run-1"],
            }
        },
        "run_records": {
            "parent-run-1": {
                "run_id": "parent-run-1",
                "run_group_id": "group-active",
                "kind": "workflow_run",
            }
        },
    }
    starter = _starter(state)
    first_child_marker = issue_run_group_child_attachment(
        run_group_id="group-active",
        parent_run_id="parent-run-1",
        workflow_run_id="parent-run-1",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity="workflow-node:1:workflow-1",
    )

    with pytest.raises(RuntimeError, match="run_group_attachment_child_identity_mismatch"):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Replay marker for second child",
                "run_group_id": "group-active",
                "client_run_id": "workflow-node:2:workflow-1",
                RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: first_child_marker,
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )

    assert state.get("runs") is None


def test_workflow_run_starter_accepts_authorized_nested_child() -> None:
    state: dict[str, Any] = {
        "group_records": {
            "group-active": {
                "run_group_id": "group-active",
                "status": "running",
                "child_run_ids": ["parent-run-1"],
            }
        },
        "run_records": {
            "parent-run-1": {
                "run_id": "parent-run-1",
                "run_group_id": "group-active",
                "kind": "workflow_run",
            }
        },
    }
    starter = _starter(state)
    attachment = issue_run_group_child_attachment(
        run_group_id="group-active",
        parent_run_id="parent-run-1",
        workflow_run_id="parent-run-1",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity="workflow-node:child-1",
    )

    start = starter.start_sync(
        {
            "workflow_id": "workflow-1",
            "user_goal": "Run authorized child",
            "run_group_id": "group-active",
            "client_run_id": attachment.child_identity,
            RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: attachment,
        },
        workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
        workflow_id="workflow-1",
        lock=threading.RLock(),
    )

    assert start.root_group is False
    assert start.run["run_group_id"] == "group-active"
    assert start.run["project_root_group"] is False


def test_workflow_run_starter_revalidates_attachment_on_group_idempotency_hit() -> None:
    existing = {
        "run_id": "existing-workflow-child",
        "kind": "workflow_run",
        "runnable_id": "workflow-1",
        "user_goal": "Run authorized child",
        "run_group_id": "group-active",
        "client_request_id": "workflow-node:child-1",
        "idempotent": True,
    }
    state: dict[str, Any] = {
        "by_client": {existing["client_request_id"]: existing},
        "group_records": {
            "group-active": {
                "run_group_id": "group-active",
                "status": "running",
                "child_run_ids": [
                    "parent-run-1",
                    "other-workflow-member",
                    "existing-workflow-child",
                ],
            }
        },
        "run_records": {
            "parent-run-1": {
                "run_id": "parent-run-1",
                "run_group_id": "group-active",
                "kind": "workflow_run",
            },
            "other-workflow-member": {
                "run_id": "other-workflow-member",
                "run_group_id": "group-active",
                "kind": "workflow_run",
            },
        },
    }
    starter = _starter(state)
    replayed_with_forged_parent = issue_run_group_child_attachment(
        run_group_id="group-active",
        parent_run_id="other-workflow-member",
        workflow_run_id="other-workflow-member",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity=str(existing["client_request_id"]),
    )

    with pytest.raises(
        RuntimeError,
        match="run_group_attachment_existing_parent_mismatch",
    ):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": existing["user_goal"],
                "run_group_id": "group-active",
                "client_run_id": existing["client_request_id"],
                RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: replayed_with_forged_parent,
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )


def test_workflow_run_starter_rejects_idempotent_child_outside_group_membership() -> None:
    existing = {
        "run_id": "existing-workflow-child",
        "kind": "workflow_run",
        "runnable_id": "workflow-1",
        "user_goal": "Run authorized child",
        "run_group_id": "group-active",
        "client_request_id": "workflow-node:child-1",
        "idempotent": True,
    }
    state: dict[str, Any] = {
        "by_client": {existing["client_request_id"]: existing},
        "group_records": {
            "group-active": {
                "run_group_id": "group-active",
                "status": "running",
                "child_run_ids": ["parent-run-1"],
            }
        },
        "run_records": {
            "parent-run-1": {
                "run_id": "parent-run-1",
                "run_group_id": "group-active",
                "kind": "workflow_run",
            }
        },
    }
    starter = _starter(state)
    marker = issue_run_group_child_attachment(
        run_group_id="group-active",
        parent_run_id="parent-run-1",
        workflow_run_id="parent-run-1",
        child_kind="workflow_run",
        child_runnable_id="workflow-1",
        child_identity=str(existing["client_request_id"]),
    )

    with pytest.raises(
        RuntimeError,
        match="run_group_attachment_existing_child_not_member",
    ):
        starter.start_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": existing["user_goal"],
                "run_group_id": "group-active",
                "client_run_id": existing["client_request_id"],
                RUN_GROUP_ATTACHMENT_PAYLOAD_KEY: marker,
            },
            workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
            workflow_id="workflow-1",
            lock=threading.RLock(),
        )


def test_workflow_run_starter_async_preserves_legacy_non_idempotent_behavior() -> None:
    state: dict[str, Any] = {}

    def unexpected_client_request_id(_payload: dict[str, Any]) -> str:
        raise AssertionError("async workflow runs should not consult client request id")

    starter = _starter(state, client_request_id_from_payload=unexpected_client_request_id)
    start = starter.start_async(
        {"workflow_id": "workflow-1", "user_goal": "Run later", "client_run_id": "ignored-client-id"},
        workflow={"workflow_id": "workflow-1", "name": "Runner Flow"},
        workflow_id="workflow-1",
    )

    assert start.root_group is True
    assert start.run["client_request_id"] == ""
    assert len(state["runs"]) == 1


def test_workflow_run_coordinator_validates_projects_and_continues() -> None:
    calls: list[tuple[str, Any]] = []
    workflow = {
        "workflow_id": "workflow-1",
        "name": "Flow",
        "enabled": True,
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
    }

    class _Starter:
        def start_sync(
            self,
            payload: dict[str, Any],
            *,
            workflow: dict[str, Any],
            workflow_id: str,
            lock: Any,
        ) -> WorkflowRunStart:
            calls.append(("start", payload, workflow_id, lock))
            return WorkflowRunStart({"run_id": "run-1"}, root_group=True)

    class _Projector:
        @staticmethod
        def started_projection(
            workflow_id: str,
            workflow: dict[str, Any],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            calls.append(("project", workflow_id, workflow["name"]))
            return [{"event": "workflow.run.started"}], {"workflow_id": workflow_id}

    coordinator = RuntimeWorkflowRunCoordinator(
        get_workflow=lambda workflow_id: calls.append(("workflow", workflow_id)) or workflow,
        validate_workflow=lambda nodes, edges: calls.append(("validate", nodes, edges)) or {"ok": True},
        validate_workflow_agent_nodes=lambda nodes: calls.append(("agent_nodes", nodes)),
        validate_workflow_subworkflow_nodes=lambda nodes, **kwargs: calls.append(("subworkflows", nodes, kwargs)),
        validate_workflow_runnable_steps=lambda nodes: calls.append(("runnable_steps", nodes)),
        validate_workflow_agent_run_readiness=lambda nodes: calls.append(("readiness", nodes)),
        starter=_Starter(),  # type: ignore[arg-type]
        start_projector=_Projector(),
        append_run_event=lambda run_id, event_type, payload: calls.append(("event", run_id, event_type, payload)),
        continue_workflow_run=lambda run, workflow, **kwargs: calls.append(("continue", run["run_id"], kwargs))
        or {"run_id": run["run_id"], "status": "completed"},
        lock=object(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = coordinator.create_sync({"workflow_id": "workflow-1", "user_goal": "Ship"})

    assert result == {"run_id": "run-1", "status": "completed"}
    assert calls[0] == ("workflow", "workflow-1")
    assert calls[1][0] == "validate"
    assert calls[7][0] == "project"
    assert calls[8] == ("event", "run-1", "workflow.run.started", {"workflow_id": "workflow-1"})
    assert calls[9][0] == "continue"
    assert calls[9][2]["root_group"] is True
    assert calls[9][2]["start_node_id"] == ""


def test_workflow_run_coordinator_continues_from_requested_start_node() -> None:
    calls: list[tuple[str, Any]] = []
    workflow = {
        "workflow_id": "workflow-1",
        "name": "Flow",
        "enabled": True,
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "ship", "type": "agent"},
        ],
        "edges": [{"source": "start", "target": "ship"}],
    }

    class _Starter:
        def start_sync(
            self,
            payload: dict[str, Any],
            *,
            workflow: dict[str, Any],
            workflow_id: str,
            lock: Any,
        ) -> WorkflowRunStart:
            calls.append(("start", payload, workflow_id, lock))
            return WorkflowRunStart({"run_id": "run-1"}, root_group=True)

    class _Projector:
        @staticmethod
        def started_projection(
            workflow_id: str,
            workflow: dict[str, Any],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            return [{"event": "workflow.run.started"}], {"workflow_id": workflow_id}

    coordinator = RuntimeWorkflowRunCoordinator(
        get_workflow=lambda _workflow_id: workflow,
        validate_workflow=lambda _nodes, _edges: {"ok": True},
        validate_workflow_agent_nodes=lambda _nodes: None,
        validate_workflow_subworkflow_nodes=lambda _nodes, **_kwargs: None,
        validate_workflow_runnable_steps=lambda _nodes: None,
        validate_workflow_agent_run_readiness=lambda _nodes: None,
        starter=_Starter(),  # type: ignore[arg-type]
        start_projector=_Projector(),
        append_run_event=lambda *_args, **_kwargs: None,
        continue_workflow_run=lambda run, workflow, **kwargs: calls.append(
            ("continue", run["run_id"], kwargs)
        )
        or {"run_id": run["run_id"], "status": "completed"},
        lock=object(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = coordinator.create_sync(
        {
            "workflow_id": "workflow-1",
            "user_goal": "Ship",
            "start_node_id": "ship",
        }
    )

    assert result == {"run_id": "run-1", "status": "completed"}
    assert calls[0][0] == "start"
    assert calls[1] == (
        "continue",
        "run-1",
        {
            "context": "Ship",
            "timeline": [{"event": "workflow.run.started"}],
            "artifacts": [],
            "start_index": 0,
            "root_group": True,
            "start_node_id": "ship",
        },
    )


def test_workflow_run_coordinator_forwards_execution_payload_to_continuation() -> None:
    calls: list[tuple[str, Any]] = []
    workflow = {
        "workflow_id": "workflow-1",
        "name": "Flow",
        "enabled": True,
        "nodes": [{"id": "start", "type": "start"}, {"id": "agent", "type": "agent"}],
        "edges": [{"source": "start", "target": "agent"}],
    }
    envelope = {
        "decision_id": "decision-workflow",
        "plan_id": "plan-workflow",
        "requests": [{"request_id": "request-open", "tool": "app.open"}],
    }

    class _Starter:
        def start_sync(
            self,
            payload: dict[str, Any],
            *,
            workflow: dict[str, Any],
            workflow_id: str,
            lock: Any,
        ) -> WorkflowRunStart:
            return WorkflowRunStart({"run_id": "run-1"}, root_group=True)

    class _Projector:
        @staticmethod
        def started_projection(
            workflow_id: str,
            workflow: dict[str, Any],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            return [{"event": "workflow.run.started"}], {"workflow_id": workflow_id}

    coordinator = RuntimeWorkflowRunCoordinator(
        get_workflow=lambda _workflow_id: workflow,
        validate_workflow=lambda _nodes, _edges: {"ok": True},
        validate_workflow_agent_nodes=lambda _nodes: None,
        validate_workflow_subworkflow_nodes=lambda _nodes, **_kwargs: None,
        validate_workflow_runnable_steps=lambda _nodes: None,
        validate_workflow_agent_run_readiness=lambda _nodes: None,
        starter=_Starter(),  # type: ignore[arg-type]
        start_projector=_Projector(),
        append_run_event=lambda *_args, **_kwargs: None,
        continue_workflow_run=lambda run, workflow, **kwargs: calls.append(
            ("continue", run["run_id"], kwargs)
        )
        or {"run_id": run["run_id"], "status": "completed"},
        lock=object(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = coordinator.create_sync(
        {
            "workflow_id": "workflow-1",
            "user_goal": "Open Music",
            "runtime_execution_envelope": envelope,
            "metadata": {"yachiyo_execution_envelope": envelope},
            "direct_tool_requests": [{"tool": "app.open", "input": {"app_name": "Music"}}],
            "daily_desktop_planning_context": "Open Music from workflow plan",
        }
    )

    continue_kwargs = calls[0][2]
    assert result == {"run_id": "run-1", "status": "completed"}
    assert continue_kwargs["runtime_execution_envelope"] is envelope
    assert continue_kwargs["runtime_execution_metadata"] == {
        "yachiyo_execution_envelope": envelope,
    }
    assert continue_kwargs["direct_tool_requests"] == [
        {"tool": "app.open", "input": {"app_name": "Music"}},
    ]
    assert continue_kwargs["daily_desktop_planning_context"] == (
        "Open Music from workflow plan"
    )


def test_workflow_run_coordinator_rejects_unknown_requested_start_node() -> None:
    workflow = {
        "workflow_id": "workflow-1",
        "name": "Flow",
        "enabled": True,
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
    }

    class _Starter:
        def start_sync(self, *_args: Any, **_kwargs: Any) -> WorkflowRunStart:
            raise AssertionError("unknown start node should not create a run")

    coordinator = RuntimeWorkflowRunCoordinator(
        get_workflow=lambda _workflow_id: workflow,
        validate_workflow=lambda _nodes, _edges: {"ok": True},
        validate_workflow_agent_nodes=lambda _nodes: None,
        validate_workflow_subworkflow_nodes=lambda _nodes, **_kwargs: None,
        validate_workflow_runnable_steps=lambda _nodes: None,
        validate_workflow_agent_run_readiness=lambda _nodes: None,
        starter=_Starter(),  # type: ignore[arg-type]
        start_projector=object(),
        append_run_event=lambda *_args, **_kwargs: None,
        continue_workflow_run=lambda *_args, **_kwargs: pytest.fail("should not continue"),
        lock=object(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    with pytest.raises(agent_runtime.AgentRuntimeError, match="Workflow 重跑节点不存在"):
        coordinator.create_sync(
            {
                "workflow_id": "workflow-1",
                "user_goal": "Ship",
                "start_node_id": "missing",
            }
        )


def test_workflow_run_coordinator_returns_existing_idempotent_run_without_projection() -> None:
    class _Starter:
        def start_sync(
            self,
            payload: dict[str, Any],
            *,
            workflow: dict[str, Any],
            workflow_id: str,
            lock: Any,
        ) -> WorkflowRunStart:
            return WorkflowRunStart({"run_id": "existing", "idempotent": True}, root_group=False, existing=True)

    coordinator = RuntimeWorkflowRunCoordinator(
        get_workflow=lambda workflow_id: {
            "workflow_id": workflow_id,
            "name": "Flow",
            "enabled": True,
            "nodes": [{"id": "start", "type": "start"}],
            "edges": [],
        },
        validate_workflow=lambda _nodes, _edges: {"ok": True},
        validate_workflow_agent_nodes=lambda _nodes: None,
        validate_workflow_subworkflow_nodes=lambda _nodes, **_kwargs: None,
        validate_workflow_runnable_steps=lambda _nodes: None,
        validate_workflow_agent_run_readiness=lambda _nodes: None,
        starter=_Starter(),  # type: ignore[arg-type]
        start_projector=object(),
        append_run_event=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not append")),
        continue_workflow_run=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not continue")),
        lock=object(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    assert coordinator.create_sync({"workflow_id": "workflow-1", "user_goal": "Ship"}) == {
        "run_id": "existing",
        "idempotent": True,
    }


def test_workflow_run_async_coordinator_returns_processing_and_completes_in_background() -> None:
    completions: list[dict[str, Any]] = []
    calls: list[tuple[str, Any]] = []
    workflow = {
        "workflow_id": "workflow-1",
        "name": "Flow",
        "enabled": True,
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
    }

    class _Starter:
        def start_async(
            self,
            payload: dict[str, Any],
            *,
            workflow: dict[str, Any],
            workflow_id: str,
        ) -> WorkflowRunStart:
            calls.append(("start", payload, workflow_id))
            return WorkflowRunStart({"run_id": "run-async", "kind": "workflow_run"}, root_group=True)

    class _Projector:
        @staticmethod
        def started_projection(
            workflow_id: str,
            workflow: dict[str, Any],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            calls.append(("project", workflow_id, workflow["name"]))
            return [{"event": "workflow.run.started"}], {"workflow_id": workflow_id}

    coordinator = RuntimeWorkflowRunAsyncCoordinator(
        get_workflow=lambda workflow_id: calls.append(("workflow", workflow_id)) or workflow,
        validate_workflow=lambda nodes, edges: calls.append(("validate", nodes, edges)) or {"ok": True},
        validate_workflow_agent_nodes=lambda nodes: calls.append(("agent_nodes", nodes)),
        validate_workflow_subworkflow_nodes=lambda nodes, **kwargs: calls.append(("subworkflows", nodes, kwargs)),
        validate_workflow_runnable_steps=lambda nodes: calls.append(("runnable_steps", nodes)),
        validate_workflow_agent_run_readiness=lambda nodes: calls.append(("readiness", nodes)),
        starter=_Starter(),  # type: ignore[arg-type]
        start_projector=_Projector(),
        append_run_event=lambda run_id, event_type, payload: calls.append(("event", run_id, event_type, payload)),
        update_run=lambda run_id, **kwargs: calls.append(("update", run_id, kwargs))
        or {"run_id": run_id, "status": kwargs["status"], "timeline": kwargs["timeline"]},
        continue_workflow_run=lambda run, workflow, **kwargs: calls.append(("continue", run["run_id"], kwargs))
        or {"run_id": run["run_id"], "status": "completed"},
        project_background_failure=lambda *_args, **_kwargs: {},
        resolve_runnable=lambda **kwargs: {"id": kwargs["runnable_id"], "kind": "workflow"},
        error_type=agent_runtime.AgentRuntimeError,
        thread_factory=_ImmediateThread,
    )

    result = coordinator.create_async({"workflow_id": "workflow-1", "user_goal": "Ship"}, on_complete=completions.append)

    assert result["status"] == "processing"
    assert result["workflow_run_id"] == "run-async"
    assert result["runnable"] == {"id": "workflow-1", "kind": "workflow"}
    assert calls[0] == ("workflow", "workflow-1")
    assert calls[7][0] == "project"
    assert calls[8] == ("event", "run-async", "workflow.run.started", {"workflow_id": "workflow-1"})
    assert calls[9][0] == "update"
    assert calls[10][0] == "continue"
    assert calls[10][2]["root_group"] is True
    assert completions == [{"run_id": "run-async", "status": "completed"}]


def test_workflow_run_async_coordinator_projects_background_failure() -> None:
    completions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    workflow = {
        "workflow_id": "workflow-1",
        "name": "Flow",
        "enabled": True,
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
    }

    class _Starter:
        def start_async(
            self,
            payload: dict[str, Any],
            *,
            workflow: dict[str, Any],
            workflow_id: str,
        ) -> WorkflowRunStart:
            return WorkflowRunStart({"run_id": "run-fail", "kind": "workflow_run"}, root_group=False)

    class _Projector:
        @staticmethod
        def started_projection(
            workflow_id: str,
            workflow: dict[str, Any],
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            return [{"event": "workflow.run.started"}], {"workflow_id": workflow_id}

    def fail_continue(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("workflow failure")

    def project_background_failure(run: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        failure = {
            "run_id": run["run_id"],
            "status": "failed",
            "error": str(kwargs["error"]),
            "timeline": kwargs["timeline"],
            "root_group": kwargs["root_group"],
        }
        failures.append(failure)
        return failure

    coordinator = RuntimeWorkflowRunAsyncCoordinator(
        get_workflow=lambda _workflow_id: workflow,
        validate_workflow=lambda _nodes, _edges: {"ok": True},
        validate_workflow_agent_nodes=lambda _nodes: None,
        validate_workflow_subworkflow_nodes=lambda _nodes, **_kwargs: None,
        validate_workflow_runnable_steps=lambda _nodes: None,
        validate_workflow_agent_run_readiness=lambda _nodes: None,
        starter=_Starter(),  # type: ignore[arg-type]
        start_projector=_Projector(),
        append_run_event=lambda *_args, **_kwargs: None,
        update_run=lambda run_id, **kwargs: {"run_id": run_id, "status": kwargs["status"]},
        continue_workflow_run=fail_continue,
        project_background_failure=project_background_failure,
        resolve_runnable=lambda **kwargs: {"id": kwargs["runnable_id"]},
        error_type=agent_runtime.AgentRuntimeError,
        thread_factory=_ImmediateThread,
    )

    result = coordinator.create_async({"workflow_id": "workflow-1", "user_goal": "Ship"}, on_complete=completions.append)

    assert result["status"] == "processing"
    assert failures == [
        {
            "run_id": "run-fail",
            "status": "failed",
            "error": "workflow failure",
            "timeline": [{"event": "workflow.run.started"}],
            "root_group": False,
        }
    ]
    assert completions == failures


def test_native_runtime_uses_split_workflow_run_starter_and_keeps_sync_idempotency(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeWorkflowRunStarter is RuntimeWorkflowRunStarter
        assert agent_runtime.RuntimeWorkflowRunCoordinator is RuntimeWorkflowRunCoordinator
        assert agent_runtime.RuntimeWorkflowRunAsyncCoordinator is RuntimeWorkflowRunAsyncCoordinator
        assert isinstance(service.workflow_run_starter, RuntimeWorkflowRunStarter)
        assert isinstance(service.workflow_run_coordinator, RuntimeWorkflowRunCoordinator)
        assert isinstance(service.workflow_run_async_coordinator, RuntimeWorkflowRunAsyncCoordinator)
        workflow = service.create_workflow(
            {
                "name": "Starter Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "artifact", "type": "artifact", "data": {"label": "Report"}},
                ],
                "edges": [{"source": "start", "target": "artifact"}],
            }
        )

        first = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Ship workflow",
                "client_run_id": "workflow-client-1",
            }
        )
        second = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Ship workflow",
                "client_run_id": "workflow-client-1",
            }
        )

        assert first["status"] == "completed"
        assert second["idempotent"] is True
        assert second["run_id"] == first["run_id"]
        rows = service._conn.execute(
            "SELECT run_id FROM runs WHERE client_request_id='workflow-client-1'"
        ).fetchall()
        assert len(rows) == 1
    finally:
        service.close()
