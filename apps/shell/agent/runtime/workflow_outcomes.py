"""Workflow child outcome projections for replayable Run timelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.security import redact_api_error_text, redact_sensitive_text


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


class WorkflowChildOutcomeCoordinator:
    """Projects child Agent Run outcomes into a parent Workflow timeline."""

    @staticmethod
    def child_artifact_refs(child_run: dict[str, Any], label: str) -> list[dict[str, Any]]:
        child_run_id = str(child_run.get("run_id") or "")
        if not child_run_id:
            return []
        refs: list[dict[str, Any]] = []
        for artifact in child_run.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            artifact_kind = str(artifact.get("kind") or "").strip()
            if artifact_kind == "context":
                continue
            path = str(artifact.get("path") or "").strip()
            if not path:
                continue
            refs.append(
                {
                    "kind": "workflow_child_artifact",
                    "path": path,
                    "source_run_id": child_run_id,
                    "source_run_kind": str(child_run.get("kind") or ""),
                    "source_runnable_id": str(child_run.get("runnable_id") or ""),
                    "source_runnable_name": str(child_run.get("runnable_name") or child_run.get("runnable_id") or ""),
                    "workflow_step_label": label,
                    "artifact_kind": artifact_kind,
                }
            )
        return refs

    @staticmethod
    def child_node_context(
        timeline: list[dict[str, Any]],
        child_run: dict[str, Any],
    ) -> tuple[str, dict[str, str]]:
        child_run_id = str(child_run.get("run_id") or "")
        child_label = str(child_run.get("runnable_name") or child_run.get("runnable_id") or "Run")
        child_node_info: dict[str, str] = {}
        for event in timeline:
            if (
                isinstance(event, dict)
                and event.get("event") in {"workflow.node.agent", "workflow.node.workflow"}
                and str(event.get("child_run_id") or "") == child_run_id
            ):
                child_label = str(event.get("detail") or child_label).strip() or child_label
                node_id = str(event.get("workflow_node_id") or "").strip()
                if node_id:
                    child_node_info = {
                        "workflow_node_id": node_id,
                        "workflow_node_kind": str(event.get("workflow_node_kind") or "agent"),
                        "workflow_node_label": str(event.get("workflow_node_label") or child_label),
                    }
                    for key in (
                        "workflow_parent_node_id",
                        "workflow_parent_node_kind",
                        "workflow_parent_node_label",
                        "workflow_parallel_branch_entry_node_id",
                        "workflow_parallel_branch_label",
                        "workflow_parent_node_context",
                    ):
                        value = str(event.get(key) or "")
                        if value:
                            child_node_info[key] = value
                break
        return child_label, child_node_info

    def merge_child_run_outcome(
        self,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        child_run: dict[str, Any],
        label: str,
    ) -> None:
        child_run_id = str(child_run.get("run_id") or "")
        if not child_run_id:
            return
        child_status = str(child_run.get("status") or "")
        child_result = str(child_run.get("result") or "")
        child_artifacts = self.child_artifact_refs(child_run, label)
        for event in timeline:
            if not isinstance(event, dict):
                continue
            if event.get("event") not in {"workflow.node.agent", "workflow.node.workflow"}:
                continue
            if str(event.get("child_run_id") or "") != child_run_id:
                continue
            event["status"] = child_status
            event["result"] = _tool_input_preview(child_result, limit=1800)
            if str(event.get("workflow_parent_node_id") or ""):
                event["workflow_node_context"] = child_result
            event["artifact_count"] = len(child_artifacts)
        existing_refs = {
            (
                str(item.get("kind") or ""),
                str(item.get("source_run_id") or ""),
                str(item.get("path") or ""),
            )
            for item in artifacts
            if isinstance(item, dict)
        }
        for artifact in child_artifacts:
            key = (
                str(artifact.get("kind") or ""),
                str(artifact.get("source_run_id") or ""),
                str(artifact.get("path") or ""),
            )
            if key not in existing_refs:
                artifacts.append(artifact)
                existing_refs.add(key)


@dataclass(frozen=True)
class WorkflowChildRunProjection:
    """Replay payload snapshot for projecting child Run state into a Workflow."""

    child_run_id: str
    status: str
    result_preview: Any
    artifact_count: int
    node_info: dict[str, str]

    @classmethod
    def from_child_run(
        cls,
        child_run: dict[str, Any],
        child_node_info: dict[str, str],
        artifacts: list[dict[str, Any]],
    ) -> "WorkflowChildRunProjection | None":
        child_run_id = str(child_run.get("run_id") or "")
        if not child_run_id:
            return None
        status = str(child_run.get("status") or "")
        return cls(
            child_run_id=child_run_id,
            status=status,
            result_preview=_tool_input_preview(child_run.get("result") or status, limit=1800),
            artifact_count=sum(
                1
                for artifact in artifacts
                if isinstance(artifact, dict)
                and artifact.get("kind") == "workflow_child_artifact"
                and str(artifact.get("source_run_id") or "") == child_run_id
            ),
            node_info=dict(child_node_info),
        )

    def agent_event_payload(self) -> dict[str, Any]:
        return {
            "child_run_id": self.child_run_id,
            "status": self.status,
            "result": self.result_preview,
            "artifact_count": self.artifact_count,
            **self.node_info,
        }

    def status_event_payload(self, status: str | None = None) -> dict[str, Any]:
        return {
            "child_run_id": self.child_run_id,
            "status": self.status if status is None else status,
            **self.node_info,
        }


@dataclass(frozen=True)
class WorkflowChildStatusProjection:
    """Status payload for projecting child Run transitions into a parent Workflow."""

    child_run_id: str
    status: str
    result_preview: Any
    node_info: dict[str, str]
    projection: WorkflowChildRunProjection | None = None

    @classmethod
    def from_child_run(
        cls,
        child_run: dict[str, Any],
        child_node_info: dict[str, str],
        artifacts: list[dict[str, Any]],
    ) -> "WorkflowChildStatusProjection":
        projection = WorkflowChildRunProjection.from_child_run(child_run, child_node_info, artifacts)
        child_status = str(child_run.get("status") or "")
        if projection is not None:
            return cls(
                child_run_id=projection.child_run_id,
                status=projection.status,
                result_preview=projection.result_preview,
                node_info=dict(projection.node_info),
                projection=projection,
            )
        return cls(
            child_run_id=str(child_run.get("run_id") or ""),
            status=child_status,
            result_preview=_tool_input_preview(child_run.get("result") or child_status, limit=1800),
            node_info=dict(child_node_info),
        )

    def status_event_payload(self, status: str | None = None) -> dict[str, Any]:
        if self.projection is not None:
            return self.projection.status_event_payload(status)
        return {
            "child_run_id": self.child_run_id,
            "status": self.status if status is None else status,
            **self.node_info,
        }

    def result_event_payload(self, status: str | None = None) -> dict[str, Any]:
        return {
            **self.status_event_payload(status),
            "result": self.result_preview,
        }


@dataclass(frozen=True)
class WorkflowParentResumeFailureProjection:
    """Failure projection when a parent Workflow cannot resume after a child update."""

    safe_error: str
    event_payload: dict[str, Any]

    @classmethod
    def from_error(
        cls,
        error: Any,
        *,
        child_run_id: str,
        child_status: str,
        child_node_info: dict[str, str],
    ) -> "WorkflowParentResumeFailureProjection":
        event_payload: dict[str, Any] = {
            "status": "failed",
            **{
                key: redact_api_error_text(value)
                for key, value in child_node_info.items()
            },
        }
        if child_run_id:
            event_payload["child_run_id"] = child_run_id
        if child_status:
            event_payload["child_run_status"] = child_status
        return cls(
            safe_error=redact_api_error_text(error),
            event_payload=event_payload,
        )

    def timeline_event(self, timeline_factory: Any) -> dict[str, Any]:
        return timeline_factory(
            "workflow.run.failed",
            self.safe_error,
            **self.event_payload,
        )

    def update_fields(
        self,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "status": "failed",
            "result": self.safe_error,
            "timeline": timeline,
            "artifacts": artifacts,
        }
