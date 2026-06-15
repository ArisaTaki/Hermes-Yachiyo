"""Workflow node handoffs, child executions, and artifact write projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.tool_brokers import write_artifact_with_tool_broker
from packages.security import redact_sensitive_text


def _redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def _tool_input_preview(value: Any, *, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(key): _tool_input_preview(item, limit=limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_tool_input_preview(item, limit=limit) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = _redact_secrets(value)
    if len(text) > limit:
        return f"{text[:limit]}... [truncated]"
    return text


@dataclass(frozen=True)
class WorkflowNodePortBundle:
    """Ports used by legacy Workflow node projection helpers."""

    workflow_agent_for_node: Any | None = None
    workflow_node_task: Any | None = None
    workflow_child_goal: Any | None = None
    insert_run: Any | None = None
    execute_agent_run: Any | None = None
    workflow_child_artifact_refs: Any | None = None
    workflow_for_node: Any | None = None
    workflow_run_started_projection: Any | None = None
    append_run_event: Any | None = None
    continue_workflow_run: Any | None = None
    default_workspace_policy: Any | None = None
    workflow_artifacts_dir: Any | None = None
    workflow_artifact_path: Any | None = None
    workflow_artifact_write: Any | None = None
    tool_brokers: Any | None = None


def _port_callback(
    ports: WorkflowNodePortBundle | None,
    name: str,
    engine: Any,
    legacy_name: str,
) -> Any:
    callback = getattr(ports, name) if ports is not None else None
    if callback is not None:
        return callback
    return getattr(engine, legacy_name)


def _port_source(
    ports: WorkflowNodePortBundle | None,
    name: str,
    fallback: Any,
) -> Any:
    source = getattr(ports, name) if ports is not None else None
    return fallback if source is None else source


@dataclass(frozen=True)
class WorkflowAgentNodeHandoff:
    """Child Agent run payload derived from a Workflow agent node."""

    agent: dict[str, Any]
    agent_id: str
    node_id: str
    node_kind: str
    node_label: str
    step_task: str
    child_goal: str
    upstream: str
    node_info_extra: dict[str, str] | None = None

    @classmethod
    def from_agent(
        cls,
        node: dict[str, Any],
        *,
        agent: dict[str, Any],
        label: str,
        kind: str,
        step_task: str,
        child_goal: str,
        context: str,
        has_agent_upstream: bool,
        node_info_extra: dict[str, str] | None = None,
    ) -> "WorkflowAgentNodeHandoff":
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        agent_id = str(agent.get("agent_id") or data.get("agent_id") or data.get("agentId") or "")
        return cls(
            agent=agent,
            agent_id=agent_id,
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            node_label=label,
            step_task=step_task,
            child_goal=child_goal,
            upstream=context if has_agent_upstream else "",
            node_info_extra=dict(node_info_extra or {}),
        )

    @classmethod
    def from_node(
        cls,
        engine: Any,
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        workflow_goal: str,
        context: str,
        has_agent_upstream: bool,
        node_info_extra: dict[str, str] | None = None,
        ports: WorkflowNodePortBundle | None = None,
    ) -> "WorkflowAgentNodeHandoff":
        workflow_agent_for_node = _port_callback(
            ports,
            "workflow_agent_for_node",
            engine,
            "_workflow_agent_for_node",
        )
        workflow_node_task = _port_callback(
            ports,
            "workflow_node_task",
            engine,
            "_workflow_node_task",
        )
        workflow_child_goal = _port_callback(
            ports,
            "workflow_child_goal",
            engine,
            "_workflow_child_goal",
        )
        agent = workflow_agent_for_node(node)
        step_task = workflow_node_task(node)
        return cls.from_agent(
            node,
            agent=agent,
            label=label,
            kind=kind,
            step_task=step_task,
            child_goal=workflow_child_goal(workflow_goal, step_task),
            context=context,
            has_agent_upstream=has_agent_upstream,
            node_info_extra=node_info_extra,
        )

    def node_info(self) -> dict[str, str]:
        info = {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.node_label,
        }
        info.update(dict(self.node_info_extra or {}))
        return info

    def agent_event_payload(self, child_run: dict[str, Any], *, artifact_count: int) -> dict[str, Any]:
        return {
            **self.node_info(),
            "workflow_node_task": self.step_task,
            "child_run_id": str(child_run.get("run_id") or ""),
            "status": str(child_run.get("status") or ""),
            "result": _tool_input_preview(child_run.get("result") or "", limit=1800),
            "artifact_count": artifact_count,
        }

    def status_event_payload(self, child_run: dict[str, Any]) -> dict[str, Any]:
        return {
            **self.node_info(),
            "child_run_id": str(child_run.get("run_id") or ""),
            "status": str(child_run.get("status") or ""),
        }


@dataclass(frozen=True)
class WorkflowAgentNodeExecution:
    """Executed child Agent result for a Workflow agent node."""

    handoff: WorkflowAgentNodeHandoff
    child_run: dict[str, Any]
    next_context: str
    artifact_count: int

    @classmethod
    def from_child_run(
        cls,
        handoff: WorkflowAgentNodeHandoff,
        child_run: dict[str, Any],
        *,
        artifact_count: int,
    ) -> "WorkflowAgentNodeExecution":
        return cls(
            handoff=handoff,
            child_run=child_run,
            next_context=str(child_run.get("result") or ""),
            artifact_count=artifact_count,
        )

    @classmethod
    def from_handoff(
        cls,
        engine: Any,
        handoff: WorkflowAgentNodeHandoff,
        *,
        run_group_id: str,
        ports: WorkflowNodePortBundle | None = None,
    ) -> "WorkflowAgentNodeExecution":
        insert_run = _port_callback(ports, "insert_run", engine, "_insert_run")
        execute_agent_run = _port_callback(
            ports,
            "execute_agent_run",
            engine,
            "_execute_agent_run",
        )
        workflow_child_artifact_refs = _port_callback(
            ports,
            "workflow_child_artifact_refs",
            engine,
            "_workflow_child_artifact_refs",
        )
        child = insert_run(
            kind="agent_run",
            runnable_id=handoff.agent_id,
            user_goal=handoff.child_goal,
            run_group_id=run_group_id,
        )
        child = execute_agent_run(
            child["run_id"],
            handoff.agent,
            handoff.child_goal,
            upstream=handoff.upstream,
        )
        return cls.from_child_run(
            handoff,
            child,
            artifact_count=len(workflow_child_artifact_refs(child, handoff.node_label)),
        )

    @property
    def status(self) -> str:
        return str(self.child_run.get("status") or "")

    def agent_event_payload(self) -> dict[str, Any]:
        return self.handoff.agent_event_payload(self.child_run, artifact_count=self.artifact_count)

    def status_event_payload(self) -> dict[str, Any]:
        return self.handoff.status_event_payload(self.child_run)


@dataclass(frozen=True)
class WorkflowSubworkflowNodeExecution:
    """Executed child Workflow result for a Workflow node."""

    child_workflow: dict[str, Any]
    workflow_id: str
    node_id: str
    node_kind: str
    node_label: str
    step_task: str
    child_goal: str
    child_run: dict[str, Any]
    artifact_count: int

    @classmethod
    def from_child_run(
        cls,
        node: dict[str, Any],
        *,
        child_workflow: dict[str, Any],
        child_run: dict[str, Any],
        label: str,
        kind: str,
        step_task: str,
        child_goal: str,
        artifact_count: int,
    ) -> "WorkflowSubworkflowNodeExecution":
        return cls(
            child_workflow=child_workflow,
            workflow_id=str(child_workflow.get("workflow_id") or ""),
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            node_label=label,
            step_task=step_task,
            child_goal=child_goal,
            child_run=child_run,
            artifact_count=artifact_count,
        )

    @classmethod
    def from_node(
        cls,
        engine: Any,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        workflow_goal: str,
        run_group_id: str,
        ports: WorkflowNodePortBundle | None = None,
    ) -> "WorkflowSubworkflowNodeExecution":
        workflow_for_node = _port_callback(
            ports,
            "workflow_for_node",
            engine,
            "_workflow_for_node",
        )
        workflow_node_task = _port_callback(
            ports,
            "workflow_node_task",
            engine,
            "_workflow_node_task",
        )
        workflow_child_goal = _port_callback(
            ports,
            "workflow_child_goal",
            engine,
            "_workflow_child_goal",
        )
        insert_run = _port_callback(ports, "insert_run", engine, "_insert_run")
        workflow_run_started_projection = (
            ports.workflow_run_started_projection
            if ports is not None and ports.workflow_run_started_projection is not None
            else engine.workflow_run_start_projector.started_projection
        )
        append_run_event = _port_callback(ports, "append_run_event", engine, "append_run_event")
        continue_workflow_run = _port_callback(
            ports,
            "continue_workflow_run",
            engine,
            "_continue_workflow_run",
        )
        workflow_child_artifact_refs = _port_callback(
            ports,
            "workflow_child_artifact_refs",
            engine,
            "_workflow_child_artifact_refs",
        )
        child_workflow = workflow_for_node(node)
        workflow_id = str(child_workflow.get("workflow_id") or "")
        step_task = workflow_node_task(node)
        child_goal = workflow_child_goal(workflow_goal, step_task)
        child = insert_run(
            kind="workflow_run",
            runnable_id=workflow_id,
            user_goal=child_goal,
            run_group_id=run_group_id,
        )
        child_timeline, started_payload = workflow_run_started_projection(
            workflow_id,
            child_workflow,
        )
        append_run_event(child["run_id"], "workflow.run.started", started_payload)
        child = continue_workflow_run(
            child,
            child_workflow,
            context=child_goal,
            timeline=child_timeline,
            artifacts=[],
            start_index=0,
            root_group=False,
        )
        return cls.from_child_run(
            node,
            child_workflow=child_workflow,
            child_run=child,
            label=label,
            kind=kind,
            step_task=step_task,
            child_goal=child_goal,
            artifact_count=len(workflow_child_artifact_refs(child, label)),
        )

    @property
    def status(self) -> str:
        return str(self.child_run.get("status") or "")

    @property
    def next_context(self) -> str:
        return str(self.child_run.get("result") or "")

    def node_info(self) -> dict[str, str]:
        return {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.node_label,
        }

    def event_payload(self) -> dict[str, Any]:
        return {
            **self.node_info(),
            "workflow_node_task": self.step_task,
            "child_workflow_id": self.workflow_id,
            "child_workflow_name": str(self.child_workflow.get("name") or self.workflow_id),
            "child_run_id": str(self.child_run.get("run_id") or ""),
            "status": self.status,
            "result": _tool_input_preview(self.next_context, limit=1800),
            "artifact_count": self.artifact_count,
        }

    def status_event_payload(self) -> dict[str, Any]:
        return {
            **self.node_info(),
            "child_workflow_id": self.workflow_id,
            "child_run_id": str(self.child_run.get("run_id") or ""),
            "status": self.status,
        }


@dataclass(frozen=True)
class WorkflowArtifactNodeWrite:
    """Artifact write result for a Workflow artifact node."""

    node_id: str
    node_kind: str
    node_label: str
    artifact: dict[str, Any]
    node_info_extra: dict[str, str] | None = None

    @staticmethod
    def configured_path(node: dict[str, Any]) -> str:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        return str(data.get("artifact_path") or data.get("artifactPath") or "")

    @classmethod
    def from_artifact(
        cls,
        node: dict[str, Any],
        artifact: dict[str, Any],
        *,
        label: str,
        kind: str,
        node_info_extra: dict[str, str] | None = None,
    ) -> "WorkflowArtifactNodeWrite":
        return cls(
            node_id=str(node.get("id") or ""),
            node_kind=kind,
            node_label=label,
            artifact=artifact,
            node_info_extra=dict(node_info_extra or {}),
        )

    @classmethod
    def from_node(
        cls,
        engine: Any,
        run: dict[str, Any],
        node: dict[str, Any],
        *,
        label: str,
        kind: str,
        context: str,
        artifacts: list[dict[str, Any]],
        node_info_extra: dict[str, str] | None = None,
        ports: WorkflowNodePortBundle | None = None,
    ) -> "WorkflowArtifactNodeWrite":
        workflow_artifact_path = _port_callback(
            ports,
            "workflow_artifact_path",
            engine,
            "_workflow_artifact_path",
        )
        workflow_artifact_write = _port_source(ports, "workflow_artifact_write", None)
        artifact_path = workflow_artifact_path(
            label,
            artifacts,
            cls.configured_path(node),
        )
        if workflow_artifact_write is None:
            default_workspace_policy = _port_callback(
                ports,
                "default_workspace_policy",
                engine,
                "_default_workspace_policy",
            )
            artifacts_dir = (
                ports.workflow_artifacts_dir
                if ports is not None and ports.workflow_artifacts_dir is not None
                else engine.workflow_artifacts_dir
            )
            artifacts_dir = artifacts_dir() if callable(artifacts_dir) else artifacts_dir
            artifact = write_artifact_with_tool_broker(
                tool_brokers=_port_source(
                    ports,
                    "tool_brokers",
                    getattr(engine, "tool_brokers", None),
                ),
                run_id=str(run.get("run_id") or ""),
                workspace_policy=default_workspace_policy(),
                artifacts_dir=artifacts_dir,
                artifact_path=artifact_path,
                content=context,
            )
        else:
            artifact = workflow_artifact_write(run, artifact_path, context)
        return cls.from_artifact(
            node,
            artifact,
            label=label,
            kind=kind,
            node_info_extra=dict(node_info_extra or {}),
        )

    def artifact_record(self) -> dict[str, Any]:
        return {
            "kind": "workflow_artifact",
            "workflow_node_id": self.node_id,
            "workflow_node_label": self.node_label,
            **self.artifact,
        }

    def event_payload(self) -> dict[str, Any]:
        return {
            "workflow_node_id": self.node_id,
            "workflow_node_kind": self.node_kind,
            "workflow_node_label": self.node_label,
            "status": "completed",
            "artifact": self.artifact,
            **dict(self.node_info_extra or {}),
        }

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.node.artifact",
            self.node_label,
            **self.event_payload(),
        )
