"""RunTimeline metadata public snapshot helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import PublicRunEvent, RunTimelineChildSnapshot


def timeline_child_snapshots_from_payloads(payloads: Any) -> list[RunTimelineChildSnapshot]:
    if not isinstance(payloads, list):
        return []
    children: list[RunTimelineChildSnapshot] = []
    for item in payloads:
        if isinstance(item, Mapping):
            children.append(timeline_child_snapshot_from_payload(item))
        else:
            children.append(RunTimelineChildSnapshot(run_id=_text(item)))
    return children


def timeline_child_snapshot_from_payload(payload: Mapping[str, Any]) -> RunTimelineChildSnapshot:
    kind = _optional_text(payload.get("kind"))
    runnable_id = _optional_text(payload.get("runnable_id"))
    return RunTimelineChildSnapshot(
        run_id=_text(payload.get("run_id")),
        title=_optional_text(payload.get("title") or payload.get("user_goal")),
        status=_text(payload.get("status")),
        kind=kind,
        parent_run_id=_optional_text(payload.get("parent_run_id")),
        group_run_id=_optional_text(payload.get("group_run_id") or payload.get("run_group_id")),
        run_group_id=_optional_text(payload.get("run_group_id") or payload.get("group_run_id")),
        workflow_run_id=_optional_text(payload.get("workflow_run_id")),
        workflow_node_id=_optional_text(payload.get("workflow_node_id")),
        workflow_node_label=_optional_text(payload.get("workflow_node_label")),
        agent_id=_optional_text(
            payload.get("agent_id")
            or payload.get("member_agent_id")
            or (runnable_id if kind == "agent_run" else "")
        ),
        workflow_id=_optional_text(
            payload.get("workflow_id")
            or (runnable_id if kind == "workflow_run" else "")
        ),
    )


def run_timeline_rerun_provenance_from_payload(
    payload: Mapping[str, Any],
    events: list[PublicRunEvent],
) -> dict[str, str | None]:
    keys = (
        "rerun_of_run_id",
        "rerun_of_kind",
        "rerun_of_status",
        "rerun_of_runnable_id",
        "rerun_of_runnable_name",
    )
    direct = {key: _optional_text(payload.get(key)) for key in keys}
    direct["rerun_original_created_at"] = _optional_text(
        payload.get("rerun_original_created_at") or payload.get("original_created_at")
    )
    direct["rerun_original_updated_at"] = _optional_text(
        payload.get("rerun_original_updated_at") or payload.get("original_updated_at")
    )
    if direct.get("rerun_of_run_id"):
        return direct
    event = next((item for item in events if item.event_type == "run.rerun.started"), None)
    if event is None:
        return direct
    source = event.payload
    return {
        **{key: _optional_text(source.get(key)) for key in keys},
        "rerun_original_created_at": _optional_text(source.get("original_created_at")),
        "rerun_original_updated_at": _optional_text(source.get("original_updated_at")),
    }


def run_timeline_agent_id_from_payload(payload: Mapping[str, Any]) -> str:
    if _text(payload.get("kind")) == "agent_run":
        return _text(payload.get("runnable_id"))
    return ""


def workflow_run_id_from_payload(payload: Mapping[str, Any], run_id: str) -> str | None:
    explicit = _optional_text(payload.get("workflow_run_id"))
    if explicit:
        return explicit
    if _text(payload.get("kind")) == "workflow_run":
        return run_id or None
    return None


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
