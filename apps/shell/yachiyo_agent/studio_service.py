"""Agent Studio-facing facade for agents, groups, workflows, and timelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .adapters import agent_definition_snapshot_from_payload
from .contracts import (
    AgentDefinitionSnapshot,
    AgentGroupSnapshot,
    GroupRunSnapshot,
    PublicRunEvent,
    RunTimelineSnapshot,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    StartAgentRunRequest,
    StartGroupRunRequest,
    StartWorkflowRunRequest,
    WorkflowSnapshot,
)
from .events import public_run_event_from_payload
from .groups import agent_group_snapshot_from_payload, group_run_snapshot_from_payload
from .ports import StudioPort
from .timelines import run_timeline_snapshot_from_payload
from .workflows import workflow_snapshot_from_payload


class AgentStudioService:
    """Facade for Agent Studio, groups, workflows, and runtime debugging."""

    def __init__(self, studio_port: StudioPort) -> None:
        self._studio_port = studio_port

    def list_agents(self) -> list[AgentDefinitionSnapshot]:
        return [
            agent_definition_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_agents(), "agents")
        ]

    def get_agent(self, agent_id: str) -> AgentDefinitionSnapshot:
        return agent_definition_snapshot_from_payload(self._studio_port.get_agent(agent_id))

    def save_agent(
        self,
        request: SaveAgentRequest | Mapping[str, Any],
    ) -> AgentDefinitionSnapshot:
        return agent_definition_snapshot_from_payload(
            self._studio_port.save_agent(_request_payload(request))
        )

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        return dict(self._studio_port.delete_agent(agent_id))

    def start_agent_run(
        self,
        request: StartAgentRunRequest | Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        return run_timeline_snapshot_from_payload(
            self._studio_port.start_agent_run(_request_payload(request))
        )

    def list_groups(self) -> list[AgentGroupSnapshot]:
        return [
            agent_group_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_groups(), "groups")
        ]

    def get_group(self, group_id: str) -> AgentGroupSnapshot:
        return agent_group_snapshot_from_payload(self._studio_port.get_group(group_id))

    def save_group(
        self,
        request: SaveAgentGroupRequest | Mapping[str, Any],
    ) -> AgentGroupSnapshot:
        return agent_group_snapshot_from_payload(
            self._studio_port.save_group(_request_payload(request))
        )

    def start_group_run(
        self,
        request: StartGroupRunRequest | Mapping[str, Any],
    ) -> GroupRunSnapshot:
        return group_run_snapshot_from_payload(
            self._studio_port.start_group_run(_request_payload(request))
        )

    def list_group_runs(self, limit: int = 50) -> list[GroupRunSnapshot]:
        return [
            group_run_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_group_runs(limit), "group_runs")
        ]

    def get_group_run(self, group_run_id: str) -> GroupRunSnapshot:
        return group_run_snapshot_from_payload(self._studio_port.get_group_run(group_run_id))

    def list_workflows(self) -> list[WorkflowSnapshot]:
        return [
            workflow_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_workflows(), "workflows")
        ]

    def get_workflow(self, workflow_id: str) -> WorkflowSnapshot:
        return workflow_snapshot_from_payload(self._studio_port.get_workflow(workflow_id))

    def save_workflow(
        self,
        request: SaveWorkflowRequest | Mapping[str, Any],
    ) -> WorkflowSnapshot:
        return workflow_snapshot_from_payload(
            self._studio_port.save_workflow(_request_payload(request))
        )

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return dict(self._studio_port.delete_workflow(workflow_id))

    def start_workflow_run(
        self,
        request: StartWorkflowRunRequest | Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        return run_timeline_snapshot_from_payload(
            self._studio_port.start_workflow_run(_request_payload(request))
        )

    def list_run_timelines(self, limit: int = 50) -> list[RunTimelineSnapshot]:
        return [
            run_timeline_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_run_timelines(limit), "runs")
        ]

    def get_run_timeline(self, run_id: str) -> RunTimelineSnapshot:
        return run_timeline_snapshot_from_payload(self._studio_port.get_run_timeline(run_id))

    def rerun_run(self, run_id: str) -> RunTimelineSnapshot:
        return run_timeline_snapshot_from_payload(self._studio_port.rerun_run(run_id))

    def cancel_run(self, run_id: str) -> RunTimelineSnapshot:
        return run_timeline_snapshot_from_payload(self._studio_port.cancel_run(run_id))

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return dict(self._studio_port.delete_run(run_id))

    def approve_run_approval(self, run_id: str) -> RunTimelineSnapshot:
        return run_timeline_snapshot_from_payload(self._studio_port.approve_run_approval(run_id))

    def reject_run_approval(self, run_id: str, reason: str | None = None) -> RunTimelineSnapshot:
        return run_timeline_snapshot_from_payload(
            self._studio_port.reject_run_approval(run_id, reason or "")
        )

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return dict(self._studio_port.read_run_artifact(run_id, artifact_path))

    def get_run_event_stream(self, run_id: str) -> Iterable[PublicRunEvent]:
        raw_events = self._studio_port.get_run_event_stream(run_id)
        for event in _payload_items(raw_events, "events"):
            yield public_run_event_from_payload(event, run_id=run_id)


def _request_payload(request: Any) -> dict[str, Any]:
    if hasattr(request, "model_dump"):
        return request.model_dump(exclude_none=True, by_alias=True)
    return dict(request)


def _payload_items(payload: Any, key: str) -> list[dict[str, Any]]:
    items = payload.get(key) if isinstance(payload, Mapping) else payload
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes, Mapping)):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]
