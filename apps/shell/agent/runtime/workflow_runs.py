"""Workflow run creation helpers for the shared runtime surface."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.run_group_attachments import (
    RUN_GROUP_ATTACHMENT_PAYLOAD_KEY,
    require_internal_run_group_attachment,
    validate_existing_run_group_child_attachment,
    validate_run_group_child_attachment,
)


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
        get_run: Callable[[str], dict[str, Any]],
        insert_run_group: Callable[..., dict[str, Any]],
        insert_run: Callable[..., dict[str, Any]],
        run_by_client_request_id: Callable[[str], dict[str, Any] | None],
        client_request_id_from_payload: Callable[[dict[str, Any]], str],
        run_group_attachment_transaction: Callable[[], AbstractContextManager[Any]]
        | None = None,
    ) -> None:
        self._get_run_group = get_run_group
        self._get_run = get_run
        self._insert_run_group = insert_run_group
        self._insert_run = insert_run
        self._run_by_client_request_id = run_by_client_request_id
        self._client_request_id_from_payload = client_request_id_from_payload
        self._run_group_attachment_transaction = run_group_attachment_transaction

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
            return self._existing_start(
                existing,
                payload=payload,
                workflow_id=workflow_id,
                client_request_id=client_request_id,
            )
        with lock:
            existing = self._run_by_client_request_id(client_request_id)
            if existing is not None:
                return self._existing_start(
                    existing,
                    payload=payload,
                    workflow_id=workflow_id,
                    client_request_id=client_request_id,
                )
            return self._insert_new_run(
                payload,
                workflow=workflow,
                workflow_id=workflow_id,
                client_request_id=client_request_id,
            )

    def _existing_start(
        self,
        existing: dict[str, Any],
        *,
        payload: dict[str, Any],
        workflow_id: str,
        client_request_id: str,
    ) -> WorkflowRunStart:
        run_group_id = str(payload.get("run_group_id") or "").strip()
        if not run_group_id:
            # Preserve legacy root Workflow idempotency semantics.  The
            # authority boundary applies only to attaching into an existing
            # RunGroup.
            return WorkflowRunStart(existing, root_group=False, existing=True)
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if (
            str(existing.get("kind") or "").strip() != "workflow_run"
            or str(existing.get("runnable_id") or "").strip() != workflow_id
            or str(existing.get("user_goal") or "").strip() != user_goal
        ):
            raise RuntimeError(
                "idempotency key conflict: existing run identity does not match request"
            )
        attachment_scope = (
            self._run_group_attachment_transaction()
            if self._run_group_attachment_transaction is not None
            else nullcontext()
        )
        with attachment_scope:
            group = self._get_run_group(run_group_id)
            validate_existing_run_group_child_attachment(
                payload.get(RUN_GROUP_ATTACHMENT_PAYLOAD_KEY),
                group=group,
                run_group_id=run_group_id,
                existing_child=existing,
                child_kind="workflow_run",
                child_runnable_id=workflow_id,
                expected_child_identity=client_request_id,
                get_run=self._get_run,
            )
        return WorkflowRunStart(existing, root_group=False, existing=True)

    def start_async(
        self,
        payload: dict[str, Any],
        *,
        workflow: dict[str, Any],
        workflow_id: str,
    ) -> WorkflowRunStart:
        client_request_id = (
            str(
                payload.get("client_run_id")
                or payload.get("client_request_id")
                or ""
            ).strip()
            if str(payload.get("run_group_id") or "").strip()
            else ""
        )
        return self._insert_new_run(
            payload,
            workflow=workflow,
            workflow_id=workflow_id,
            client_request_id=client_request_id,
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
        attachment_scope = (
            self._run_group_attachment_transaction()
            if run_group_id and self._run_group_attachment_transaction is not None
            else nullcontext()
        )
        with attachment_scope:
            if run_group_id:
                attachment = require_internal_run_group_attachment(
                    payload.get(RUN_GROUP_ATTACHMENT_PAYLOAD_KEY),
                )
                group = self._get_run_group(run_group_id)
                validate_run_group_child_attachment(
                    attachment,
                    group=group,
                    run_group_id=run_group_id,
                    child_kind="workflow_run",
                    child_runnable_id=workflow_id,
                    expected_child_identity=client_request_id,
                    get_run=self._get_run,
                )
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
                project_root_group=root_group,
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
        start_node_id = str(payload.get("start_node_id") or "").strip()
        if start_node_id and start_node_id not in {str(node.get("id") or "") for node in nodes}:
            raise self._error_type("Workflow 重跑节点不存在")
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
            start_node_id=start_node_id,
            **_workflow_execution_kwargs(payload, user_goal=user_goal),
        )


class RuntimeWorkflowRunAsyncCoordinator:
    """Starts Workflow Runs for background execution while preserving return shape."""

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
        update_run: Callable[..., dict[str, Any]],
        continue_workflow_run: Callable[..., dict[str, Any]],
        project_background_failure: Callable[..., dict[str, Any]],
        resolve_runnable: Callable[..., dict[str, Any] | None],
        error_type: type[Exception],
        thread_factory: Callable[..., Any] = threading.Thread,
        logger: logging.Logger | None = None,
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
        self._update_run = update_run
        self._continue_workflow_run = continue_workflow_run
        self._project_background_failure = project_background_failure
        self._resolve_runnable = resolve_runnable
        self._error_type = error_type
        self._thread_factory = thread_factory
        self._logger = logger or logging.getLogger(__name__)

    def create_async(
        self,
        payload: dict[str, Any],
        *,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
        deferred_execution_start_sink: Callable[[Callable[[], None]], None]
        | None = None,
    ) -> dict[str, Any]:
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
        start = self._starter.start_async(
            payload,
            workflow=workflow,
            workflow_id=workflow_id,
        )
        run = start.run
        timeline, started_payload = self._start_projector.started_projection(workflow_id, workflow)
        self._append_run_event(
            run["run_id"],
            "workflow.run.started",
            started_payload,
        )
        run = self._update_run(
            run["run_id"],
            status="running",
            timeline=timeline,
            artifacts=[],
            pending_approval=None,
        )
        result = {
            **run,
            "status": "processing",
            "workflow_run_id": run["run_id"],
            "runnable": self._resolve_runnable(runnable_id=workflow_id),
        }

        def execute_in_background() -> None:
            try:
                exec_result = self._continue_workflow_run(
                    run,
                    workflow,
                    context=user_goal,
                    timeline=list(timeline),
                    artifacts=[],
                    start_index=0,
                    root_group=start.root_group,
                    **_workflow_execution_kwargs(payload, user_goal=user_goal),
                )
                if on_complete:
                    on_complete(exec_result)
            except Exception as exc:
                self._logger.error("异步 Workflow Run 执行失败: %s", exc, exc_info=True)
                failed = self._project_background_failure(
                    run,
                    timeline=timeline,
                    error=exc,
                    root_group=start.root_group,
                )
                if on_complete:
                    on_complete(failed)

        thread = self._thread_factory(
            target=execute_in_background,
            name=f"workflow-run-{run['run_id'][:8]}",
            daemon=True,
        )
        activated = False

        def activate() -> None:
            nonlocal activated
            if activated:
                return
            activated = True
            thread.start()

        if deferred_execution_start_sink is not None:
            deferred_execution_start_sink(activate)
        else:
            activate()
        return result


def _workflow_execution_kwargs(
    payload: dict[str, Any],
    *,
    user_goal: str,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if payload.get("runtime_execution_envelope") is not None:
        kwargs["runtime_execution_envelope"] = payload.get("runtime_execution_envelope")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if metadata:
        kwargs["runtime_execution_metadata"] = dict(metadata)
    direct_tool_requests = payload.get("direct_tool_requests")
    if isinstance(direct_tool_requests, list):
        kwargs["direct_tool_requests"] = [
            dict(request)
            for request in direct_tool_requests
            if isinstance(request, dict)
        ]
    planning_context = str(payload.get("daily_desktop_planning_context") or "").strip()
    if planning_context:
        kwargs["daily_desktop_planning_context"] = planning_context
    elif kwargs:
        kwargs["daily_desktop_planning_context"] = user_goal
    return kwargs
