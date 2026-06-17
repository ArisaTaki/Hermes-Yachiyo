"""Artifact public snapshots derived from replayable RunEvents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .artifacts import artifact_snapshot_from_payload
from .contracts import ArtifactSnapshot, PublicRunEvent


def artifact_snapshots_from_events(events: list[PublicRunEvent]) -> list[ArtifactSnapshot]:
    artifacts = []
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        artifact_payload = artifact_payload_from_event(event)
        if artifact_payload:
            artifacts.append(
                artifact_snapshot_from_payload(artifact_payload, run_id=event.run_id)
            )
    return artifacts


def artifact_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    if event.event_type in {"artifact.created", "agent.artifact.write"}:
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else payload
        if event.event_type == "agent.artifact.write":
            artifact_payload.setdefault("kind", "agent_artifact")
            if event.detail:
                artifact_payload.setdefault("path", event.detail)
        elif payload.get("workflow_node_id") or payload.get("workflow_node_label"):
            artifact_payload.setdefault("kind", payload.get("kind") or "workflow_artifact")
            artifact_payload.setdefault(
                "title",
                payload.get("title")
                or payload.get("workflow_node_label")
                or artifact_payload.get("path")
                or artifact_payload.get("artifact_path")
                or "Workflow Artifact",
            )
            artifact_payload.setdefault("workflow_id", payload.get("workflow_id"))
            artifact_payload.setdefault("workflow_run_id", payload.get("workflow_run_id") or event.run_id)
            artifact_payload.setdefault("workflow_node_id", payload.get("workflow_node_id"))
            artifact_payload.setdefault("workflow_node_label", payload.get("workflow_node_label"))
        elif payload.get("group_id") or payload.get("group_run_id") or payload.get("run_group_id"):
            artifact_payload.setdefault("kind", "group_artifact")
            artifact_payload.setdefault("group_id", payload.get("group_id"))
            artifact_payload.setdefault(
                "group_run_id",
                payload.get("group_run_id") or payload.get("run_group_id") or event.run_id,
            )
            if payload.get("member_agent_name"):
                artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))
            if payload.get("member_agent_id"):
                artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
            if payload.get("member_agent_name") and not artifact_payload.get("title"):
                artifact_path = _text(artifact_payload.get("path") or artifact_payload.get("artifact_path"))
                artifact_payload["title"] = (
                    f"{payload['member_agent_name']} / {artifact_path or 'Artifact'}"
                )
    elif event.event_type in {"group.artifact.created", "group.shared_artifact.created"}:
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else payload
        artifact_payload.setdefault("kind", "group_artifact")
        artifact_payload.setdefault("group_id", payload.get("group_id"))
        artifact_payload.setdefault(
            "group_run_id",
            payload.get("group_run_id") or payload.get("run_group_id") or event.run_id,
        )
        if payload.get("member_agent_name"):
            artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))
        if payload.get("member_agent_id"):
            artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
        if payload.get("member_agent_name") and not artifact_payload.get("title"):
            artifact_path = _text(artifact_payload.get("path") or artifact_payload.get("artifact_path"))
            artifact_payload["title"] = (
                f"{payload['member_agent_name']} / {artifact_path or 'Artifact'}"
            )
    elif event.event_type == "workflow.node.artifact":
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else {}
        artifact_payload.setdefault("path", payload.get("artifact_path") or payload.get("path") or event.detail)
        artifact_payload.setdefault("kind", payload.get("kind") or "workflow_artifact")
        artifact_payload.setdefault(
            "title",
            payload.get("title")
            or payload.get("workflow_node_label")
            or artifact_payload.get("path")
            or "Workflow Artifact",
        )
        artifact_payload.setdefault("workflow_id", payload.get("workflow_id"))
        artifact_payload.setdefault("workflow_run_id", payload.get("workflow_run_id") or event.run_id)
        artifact_payload.setdefault("workflow_node_id", payload.get("workflow_node_id"))
        artifact_payload.setdefault("workflow_node_label", payload.get("workflow_node_label"))
        for key in (
            "artifact_id",
            "id",
            "size_bytes",
            "bytes",
            "mime_type",
            "content_type",
            "preview_text",
            "content_preview",
            "url",
        ):
            if payload.get(key) is not None:
                artifact_payload.setdefault(key, payload.get(key))
        if not (
            artifact_payload.get("path")
            or artifact_payload.get("artifact_id")
            or artifact_payload.get("id")
        ):
            return {}
    else:
        return {}
    _merge_artifact_trace_context(artifact_payload, payload)
    artifact_payload.setdefault("source_run_id", event.run_id)
    artifact_payload.setdefault("run_id", event.run_id)
    artifact_payload.setdefault("created_at", event.created_at)
    return artifact_payload


def merge_artifact_snapshot_lists(*artifact_lists: list[ArtifactSnapshot]) -> list[ArtifactSnapshot]:
    by_key = {}
    ordered_keys = []
    for artifacts in artifact_lists:
        for artifact in artifacts or []:
            key = artifact.artifact_id or artifact.path or artifact.title
            if not key:
                continue
            if key not in by_key:
                by_key[key] = artifact
                ordered_keys.append(key)
            else:
                by_key[key] = merge_artifact_snapshots(by_key[key], artifact)
    return [by_key[key] for key in ordered_keys]


def merge_artifact_snapshots(
    current: ArtifactSnapshot,
    next_artifact: ArtifactSnapshot,
) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        artifact_id=current.artifact_id or next_artifact.artifact_id,
        run_id=current.run_id or next_artifact.run_id,
        source_run_id=current.source_run_id or next_artifact.source_run_id,
        source_tool=current.source_tool or next_artifact.source_tool,
        source_runnable_id=current.source_runnable_id or next_artifact.source_runnable_id,
        source_runnable_name=current.source_runnable_name or next_artifact.source_runnable_name,
        workflow_id=current.workflow_id or next_artifact.workflow_id,
        workflow_run_id=current.workflow_run_id or next_artifact.workflow_run_id,
        workflow_node_id=current.workflow_node_id or next_artifact.workflow_node_id,
        workflow_node_label=current.workflow_node_label or next_artifact.workflow_node_label,
        group_id=current.group_id or next_artifact.group_id,
        group_run_id=current.group_run_id or next_artifact.group_run_id,
        title=current.title or next_artifact.title,
        kind=current.kind or next_artifact.kind,
        path=current.path or next_artifact.path,
        mime_type=current.mime_type or next_artifact.mime_type,
        size_bytes=current.size_bytes if current.size_bytes is not None else next_artifact.size_bytes,
        preview_text=current.preview_text or next_artifact.preview_text,
        url=current.url or next_artifact.url,
        created_at=current.created_at or next_artifact.created_at,
    )


def _merge_artifact_trace_context(
    artifact_payload: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    for key in (
        "group_id",
        "group_run_id",
        "run_group_id",
        "source_tool",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        if payload.get(key):
            artifact_payload.setdefault(key, payload.get(key))
    if payload.get("member_agent_id"):
        artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
    if payload.get("member_agent_name"):
        artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()
