"""Artifact public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import ArtifactContentSnapshot, ArtifactSnapshot


def artifact_snapshot_from_payload(
    payload: Mapping[str, Any] | ArtifactSnapshot,
    *,
    run_id: str = "",
) -> ArtifactSnapshot:
    if isinstance(payload, ArtifactSnapshot):
        return _redacted_artifact_snapshot(payload)

    path = _optional_text(payload.get("path") or payload.get("artifact_path"))
    source_run_id = _optional_text(payload.get("source_run_id")) or _optional_text(run_id)
    artifact_id = _text(payload.get("artifact_id") or payload.get("id"))
    if not artifact_id:
        artifact_owner = source_run_id or run_id or "artifact"
        artifact_name = path or payload.get("kind") or "result"
        artifact_id = f"{artifact_owner}:{artifact_name}"

    title = _text(payload.get("title") or payload.get("label") or path or "Artifact")
    return ArtifactSnapshot(
        artifact_id=artifact_id,
        run_id=_optional_text(run_id),
        source_run_id=source_run_id,
        source_tool=_optional_text(payload.get("source_tool") or payload.get("tool")),
        source_runnable_id=_optional_text(
            payload.get("source_runnable_id")
            or payload.get("source_agent_id")
            or payload.get("member_agent_id")
        ),
        source_runnable_name=_optional_text(
            payload.get("source_runnable_name")
            or payload.get("source_agent_name")
            or payload.get("member_agent_name")
        ),
        workflow_id=_optional_text(payload.get("workflow_id")),
        workflow_run_id=_optional_text(payload.get("workflow_run_id")),
        workflow_node_id=_optional_text(payload.get("workflow_node_id")),
        workflow_node_label=_optional_text(
            payload.get("workflow_node_label") or payload.get("workflow_step_label")
        ),
        group_id=_optional_text(payload.get("group_id")),
        group_run_id=_optional_text(payload.get("group_run_id") or payload.get("run_group_id")),
        core_id=_optional_text(payload.get("core_id")),
        workspace_id=_optional_text(payload.get("workspace_id")),
        task_id=_optional_text(payload.get("task_id")),
        title=title,
        kind=_text(payload.get("kind") or "artifact"),
        planned_kind=_optional_text(payload.get("planned_kind")),
        source_kind=_optional_text(payload.get("source_kind")),
        requested_outputs=_optional_text_list(payload.get("requested_outputs")),
        manifest_index=_optional_int(payload.get("manifest_index")),
        path=path,
        mime_type=_optional_text(payload.get("mime_type") or payload.get("content_type")),
        size_bytes=_optional_int(payload.get("size_bytes") or payload.get("bytes")),
        preview_text=_optional_text(payload.get("preview_text") or payload.get("content_preview")),
        url=_optional_text(payload.get("url")),
        created_at=_text(payload.get("created_at")),
    )


def artifact_snapshots_from_payloads(
    payloads: Any,
    *,
    run_id: str = "",
) -> list[ArtifactSnapshot]:
    if not isinstance(payloads, list):
        return []
    return [artifact_snapshot_from_payload(item, run_id=run_id) for item in payloads]


def artifact_content_snapshot_from_payload(
    payload: Mapping[str, Any] | ArtifactContentSnapshot,
    *,
    run_id: str = "",
    task_id: str = "",
    path: str = "",
) -> ArtifactContentSnapshot:
    if isinstance(payload, ArtifactContentSnapshot):
        return _redacted_artifact_content_snapshot(payload)

    artifact_path = _text(payload.get("path") or path)
    return ArtifactContentSnapshot(
        ok=bool(payload.get("ok", True)),
        run_id=_optional_text(payload.get("run_id") or run_id),
        task_id=_optional_text(payload.get("task_id") or task_id),
        path=artifact_path,
        content=_text(payload.get("content")),
        mime_type=_optional_text(payload.get("mime_type") or payload.get("content_type")),
        truncated=bool(payload.get("truncated")),
    )


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result = [_text(item) for item in value if _text(item)]
    return result or None


def _redacted_artifact_snapshot(snapshot: ArtifactSnapshot) -> ArtifactSnapshot:
    return snapshot.model_copy(
        update={
            "artifact_id": _text(snapshot.artifact_id),
            "run_id": _optional_text(snapshot.run_id),
            "source_run_id": _optional_text(snapshot.source_run_id),
            "source_tool": _optional_text(snapshot.source_tool),
            "source_runnable_id": _optional_text(snapshot.source_runnable_id),
            "source_runnable_name": _optional_text(snapshot.source_runnable_name),
            "workflow_id": _optional_text(snapshot.workflow_id),
            "workflow_run_id": _optional_text(snapshot.workflow_run_id),
            "workflow_node_id": _optional_text(snapshot.workflow_node_id),
            "workflow_node_label": _optional_text(snapshot.workflow_node_label),
            "group_id": _optional_text(snapshot.group_id),
            "group_run_id": _optional_text(snapshot.group_run_id),
            "core_id": _optional_text(snapshot.core_id),
            "workspace_id": _optional_text(snapshot.workspace_id),
            "task_id": _optional_text(snapshot.task_id),
            "title": _text(snapshot.title),
            "kind": _text(snapshot.kind),
            "planned_kind": _optional_text(snapshot.planned_kind),
            "source_kind": _optional_text(snapshot.source_kind),
            "requested_outputs": _optional_text_list(snapshot.requested_outputs),
            "manifest_index": _optional_int(snapshot.manifest_index),
            "path": _optional_text(snapshot.path),
            "mime_type": _optional_text(snapshot.mime_type),
            "preview_text": _optional_text(snapshot.preview_text),
            "url": _optional_text(snapshot.url),
            "created_at": _text(snapshot.created_at),
        }
    )


def _redacted_artifact_content_snapshot(
    snapshot: ArtifactContentSnapshot,
) -> ArtifactContentSnapshot:
    return snapshot.model_copy(
        update={
            "run_id": _optional_text(snapshot.run_id),
            "task_id": _optional_text(snapshot.task_id),
            "path": _text(snapshot.path),
            "content": _text(snapshot.content),
            "mime_type": _optional_text(snapshot.mime_type),
        }
    )
