"""Workflow run start projections."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.serialization import json_dump_compact as _json_dump
from apps.shell.agent.runtime.serialization import json_load as _json_load


class WorkflowRunStartProjector:
    """Builds the initial replay projection for a Workflow Run."""

    def __init__(
        self,
        *,
        timeline_factory: Any,
        path_snapshot: Any,
        runtime_snapshot: Any,
    ) -> None:
        self._timeline = timeline_factory
        self._path_snapshot = path_snapshot
        self._runtime_snapshot = runtime_snapshot

    def started_projection(
        self,
        workflow_id: str,
        workflow: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        workflow_path = self._path_snapshot(workflow)
        timeline = [
            self._timeline(
                "workflow.run.started",
                workflow["name"],
                workflow_path=workflow_path,
                workflow_snapshot=self._runtime_snapshot(workflow),
            )
        ]
        event_payload = {
            "workflow_id": workflow_id,
            "workflow_name": workflow["name"],
            "workflow_path": _json_load(_json_dump(workflow_path), []),
        }
        return timeline, event_payload
