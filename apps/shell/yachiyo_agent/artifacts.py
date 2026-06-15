"""Artifact public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import ArtifactSnapshot


def artifact_snapshot_from_payload(
    payload: Mapping[str, Any] | ArtifactSnapshot,
    *,
    run_id: str = "",
) -> ArtifactSnapshot:
    if isinstance(payload, ArtifactSnapshot):
        return payload

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
        title=title,
        kind=_text(payload.get("kind") or "artifact"),
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


def _text(value: Any) -> str:
    return str(value or "").strip()


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
