"""Workflow run creation helpers for the shared runtime surface."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkflowRunStart:
    run: dict[str, Any]
    root_group: bool
    existing: bool = False


class RuntimeWorkflowRunStarter:
    """Creates Workflow Run rows while preserving legacy idempotency semantics."""

    def __init__(
        self,
        *,
        get_run_group: Callable[[str], dict[str, Any]],
        insert_run_group: Callable[..., dict[str, Any]],
        insert_run: Callable[..., dict[str, Any]],
        run_by_client_request_id: Callable[[str], dict[str, Any] | None],
        client_request_id_from_payload: Callable[[dict[str, Any]], str],
    ) -> None:
        self._get_run_group = get_run_group
        self._insert_run_group = insert_run_group
        self._insert_run = insert_run
        self._run_by_client_request_id = run_by_client_request_id
        self._client_request_id_from_payload = client_request_id_from_payload

    def start_sync(
        self,
        payload: dict[str, Any],
        *,
        workflow: dict[str, Any],
        workflow_id: str,
        lock: AbstractContextManager[Any],
    ) -> WorkflowRunStart:
        client_request_id = self._client_request_id_from_payload(payload)
        existing = self._run_by_client_request_id(client_request_id)
        if existing is not None:
            return WorkflowRunStart(existing, root_group=False, existing=True)
        with lock:
            existing = self._run_by_client_request_id(client_request_id)
            if existing is not None:
                return WorkflowRunStart(existing, root_group=False, existing=True)
            return self._insert_new_run(
                payload,
                workflow=workflow,
                workflow_id=workflow_id,
                client_request_id=client_request_id,
            )

    def start_async(
        self,
        payload: dict[str, Any],
        *,
        workflow: dict[str, Any],
        workflow_id: str,
    ) -> WorkflowRunStart:
        return self._insert_new_run(
            payload,
            workflow=workflow,
            workflow_id=workflow_id,
            client_request_id="",
        )

    def _insert_new_run(
        self,
        payload: dict[str, Any],
        *,
        workflow: dict[str, Any],
        workflow_id: str,
        client_request_id: str,
    ) -> WorkflowRunStart:
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        run_group_id = str(payload.get("run_group_id") or "").strip()
        root_group = False
        if run_group_id:
            self._get_run_group(run_group_id)
        else:
            group = self._insert_run_group(
                title=f"{workflow['name']}: {user_goal[:80]}",
                source=str(payload.get("source") or "workflow"),
                workspace_dir="",
            )
            run_group_id = group["run_group_id"]
            root_group = True
        run = self._insert_run(
            kind="workflow_run",
            runnable_id=workflow_id,
            user_goal=user_goal,
            run_group_id=run_group_id,
            client_request_id=client_request_id,
        )
        return WorkflowRunStart(run, root_group=root_group)


class RuntimeWorkflowRunCoordinator:
    """Coordinates synchronous Workflow Run validation, projection, and continuation."""

    def __init__(
        self,
        *,
        get_workflow: Callable[[str], dict[str, Any]],
        validate_workflow: Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]],
        validate_workflow_agent_nodes: Callable[[list[dict[str, Any]]], None],
        validate_workflow_subworkflow_nodes: Callable[..., None],
        validate_workflow_runnable_steps: Callable[[list[dict[str, Any]]], None],
        validate_workflow_agent_run_readiness: Callable[[list[dict[str, Any]]], None],
        starter: RuntimeWorkflowRunStarter,
        start_projector: Any,
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        continue_workflow_run: Callable[..., dict[str, Any]],
        lock: AbstractContextManager[Any],
        error_type: type[Exception],
    ) -> None:
        self._get_workflow = get_workflow
        self._validate_workflow = validate_workflow
        self._validate_workflow_agent_nodes = validate_workflow_agent_nodes
        self._validate_workflow_subworkflow_nodes = validate_workflow_subworkflow_nodes
        self._validate_workflow_runnable_steps = validate_workflow_runnable_steps
        self._validate_workflow_agent_run_readiness = validate_workflow_agent_run_readiness
        self._starter = starter
        self._start_projector = start_projector
        self._append_run_event = append_run_event
        self._continue_workflow_run = continue_workflow_run
        self._lock = lock
        self._error_type = error_type

    def create_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(payload.get("workflow_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not workflow_id:
            raise self._error_type("缺少 workflow_id")
        if not user_goal:
            raise self._error_type("运行目标不能为空")
        workflow = self._get_workflow(workflow_id)
        if not workflow.get("enabled", True):
            raise self._error_type("Workflow 已停用")
        nodes = workflow["nodes"]
        self._validate_workflow(nodes, workflow["edges"])
        self._validate_workflow_agent_nodes(nodes)
        self._validate_workflow_subworkflow_nodes(nodes, parent_workflow_id=workflow_id)
        self._validate_workflow_runnable_steps(nodes)
        self._validate_workflow_agent_run_readiness(nodes)
        start = self._starter.start_sync(
            payload,
            workflow=workflow,
            workflow_id=workflow_id,
            lock=self._lock,
        )
        if start.existing:
            return start.run
        run = start.run
        timeline, started_payload = self._start_projector.started_projection(workflow_id, workflow)
        self._append_run_event(
            run["run_id"],
            "workflow.run.started",
            started_payload,
        )
        return self._continue_workflow_run(
            run,
            workflow,
            context=user_goal,
            timeline=timeline,
            artifacts=[],
            start_index=0,
            root_group=start.root_group,
        )
