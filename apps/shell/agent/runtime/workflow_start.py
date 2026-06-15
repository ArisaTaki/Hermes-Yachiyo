"""Workflow run start projections."""

from __future__ import annotations

import json
from typing import Any


def _json_load(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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
