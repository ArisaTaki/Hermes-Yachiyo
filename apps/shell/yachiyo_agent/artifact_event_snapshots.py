"""Artifact public snapshots derived from replayable RunEvents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .artifacts import artifact_snapshot_from_payload
from .contracts import ArtifactSnapshot, PublicRunEvent
from .event_context import run_event_context_payload


def artifact_snapshots_from_events(events: list[PublicRunEvent]) -> list[ArtifactSnapshot]:
    artifacts = []
    for event in events:
        if _public_run_event_is_secret(event):
            continue
        if event.event_type in {"tool.completed", "agent.tool.completed"}:
            artifact_payloads = artifact_payloads_from_tool_completed_event(event)
        else:
            artifact_payload = artifact_payload_from_event(event)
            artifact_payloads = [artifact_payload] if artifact_payload else []
        for artifact_payload in artifact_payloads:
            artifacts.append(
                artifact_snapshot_from_payload(artifact_payload, run_id=event.run_id)
            )
    return artifacts


def artifact_payloads_from_tool_completed_event(event: PublicRunEvent) -> list[dict[str, Any]]:
    payload = run_event_context_payload(event)
    result = payload.get("result")
    result_payload = dict(result) if isinstance(result, Mapping) else {}
    raw_artifacts = result_payload.get("artifacts")
    artifact_payloads: list[dict[str, Any]] = []
    if isinstance(raw_artifacts, list):
        artifact_payloads.extend(
            dict(artifact)
            for artifact in raw_artifacts
            if isinstance(artifact, Mapping)
        )
    else:
        artifact = result_payload.get("artifact")
        if isinstance(artifact, Mapping):
            artifact_payloads.append(dict(artifact))

    normalized: list[dict[str, Any]] = []
    for artifact_payload in artifact_payloads:
        artifact_payload.setdefault("kind", artifact_payload.get("kind") or "tool_artifact")
        artifact_payload.setdefault(
            "source_tool",
            payload.get("tool_name") or payload.get("tool") or event.detail,
        )
        artifact_payload.setdefault(
            "title",
            artifact_payload.get("title")
            or artifact_payload.get("path")
            or payload.get("tool_name")
            or payload.get("tool")
            or "Tool Artifact",
        )
        _finalize_event_artifact_payload(artifact_payload, payload, event)
        normalized.append(artifact_payload)
    return normalized


def artifact_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = run_event_context_payload(event)
    if event.event_type in {"tool.completed", "agent.tool.completed"}:
        payloads = artifact_payloads_from_tool_completed_event(event)
        return payloads[0] if payloads else {}
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
    elif event.event_type in {"tool.completed", "agent.tool.completed"}:
        result = payload.get("result")
        result_payload = dict(result) if isinstance(result, Mapping) else {}
        artifact = result_payload.get("artifact")
        if not isinstance(artifact, Mapping):
            return {}
        artifact_payload = dict(artifact)
        artifact_payload.setdefault("kind", artifact_payload.get("kind") or "tool_artifact")
        artifact_payload.setdefault("source_tool", payload.get("tool_name") or payload.get("tool") or event.detail)
        artifact_payload.setdefault(
            "title",
            artifact_payload.get("title")
            or artifact_payload.get("path")
            or payload.get("tool_name")
            or payload.get("tool")
            or "Tool Artifact",
        )
    else:
        return {}
    return _finalize_event_artifact_payload(artifact_payload, payload, event)


def _finalize_event_artifact_payload(
    artifact_payload: dict[str, Any],
    payload: dict[str, Any],
    event: PublicRunEvent,
) -> dict[str, Any]:
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
        planned_kind=current.planned_kind or next_artifact.planned_kind,
        source_kind=current.source_kind or next_artifact.source_kind,
        requested_outputs=current.requested_outputs or next_artifact.requested_outputs,
        manifest_index=(
            current.manifest_index
            if current.manifest_index is not None
            else next_artifact.manifest_index
        ),
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
