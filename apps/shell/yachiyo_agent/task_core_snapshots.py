"""Task core projection helpers for Chat and Agent Studio snapshots."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_json_value

from .contracts import (
    PublicRunEvent,
    TaskCheckpointSnapshot,
    TaskCoreSnapshot,
    TaskTodoItemSnapshot,
    TaskWorkspaceItemSnapshot,
    TaskWorkspaceSnapshot,
)


def task_core_snapshot_from_payload(
    payload: Mapping[str, Any],
    *,
    events: Iterable[PublicRunEvent] | None = None,
) -> TaskCoreSnapshot | None:
    """Project the DeepAgent-style task core from planner metadata or events."""
    for candidate in _task_core_candidates(payload, events or []):
        snapshot = _task_core_snapshot_from_candidate(candidate)
        if snapshot is not None:
            return _task_core_with_event_progress(snapshot, events or [])
    return None


def _task_core_candidates(
    payload: Mapping[str, Any],
    events: Iterable[PublicRunEvent],
) -> Iterable[Any]:
    yield payload.get("task_core")
    yield payload.get("planner_task_core")

    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        yield metadata.get("yachiyo_task_core")
        yield metadata.get("task_core")

    yield _task_core_from_plan(payload.get("plan"))
    yield _task_core_from_plan(payload.get("runtime_plan"))

    planner_decision = payload.get("planner_decision")
    if isinstance(planner_decision, Mapping):
        yield _task_core_from_plan(planner_decision.get("plan"))

    for event_payload in _raw_public_event_payloads(payload):
        yield event_payload.get("task_core")
        yield _task_core_from_plan(event_payload.get("plan"))
        yield _task_core_from_plan(event_payload.get("runtime_plan"))

    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        event_payload = event.payload
        yield event_payload.get("task_core")
        yield _task_core_from_plan(event_payload.get("plan"))
        yield _task_core_from_plan(event_payload.get("runtime_plan"))


def _task_core_from_plan(plan: Any) -> Any:
    if not isinstance(plan, Mapping):
        return None
    return plan.get("task_core")


def _raw_public_event_payloads(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for key in ("events", "run_events", "timeline"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, Mapping):
                continue
            if _raw_event_is_private(item):
                continue
            event_payload = item.get("payload")
            if isinstance(event_payload, Mapping):
                yield event_payload
            else:
                yield {
                    str(raw_key): raw_value
                    for raw_key, raw_value in item.items()
                    if raw_key
                    not in {
                        "event_id",
                        "run_id",
                        "sequence",
                        "schema_version",
                        "event_type",
                        "event",
                        "title",
                        "detail",
                        "actor",
                        "visibility",
                        "sensitivity",
                        "created_at",
                    }
                }


def _raw_event_is_private(event: Mapping[str, Any]) -> bool:
    return (
        str(event.get("visibility") or "").strip() == "internal"
        or str(event.get("sensitivity") or "").strip() == "secret"
    )


def _task_core_snapshot_from_candidate(candidate: Any) -> TaskCoreSnapshot | None:
    if isinstance(candidate, TaskCoreSnapshot):
        return candidate
    if not isinstance(candidate, Mapping):
        return None
    redacted = redact_json_value(dict(candidate))
    if not isinstance(redacted, Mapping):
        return None
    try:
        return TaskCoreSnapshot.model_validate(redacted)
    except ValueError:
        return None


def _task_core_with_event_progress(
    snapshot: TaskCoreSnapshot,
    events: Iterable[PublicRunEvent],
) -> TaskCoreSnapshot:
    event_list = list(events)
    if not event_list:
        return snapshot
    progress_by_step, progress_by_tool = _runtime_progress_by_step(event_list)
    progress_by_artifact_path = _runtime_progress_by_artifact_path(event_list)
    if not progress_by_step and not progress_by_tool and not progress_by_artifact_path:
        return snapshot

    updated_workspace = _workspace_with_progress(
        snapshot.workspace,
        progress_by_step,
        progress_by_tool,
        progress_by_artifact_path,
    )
    updated_todos = [
        _todo_with_progress(todo, progress_by_step, progress_by_tool)
        for todo in snapshot.todos
    ]
    todo_status_by_step = {
        str(todo.step_id or "").strip(): str(todo.status or "").strip()
        for todo in updated_todos
        if str(todo.step_id or "").strip()
    }
    updated_checkpoints = [
        _checkpoint_with_progress(checkpoint, todo_status_by_step, progress_by_step)
        for checkpoint in snapshot.checkpoints
    ]
    return snapshot.model_copy(
        update={
            "workspace": updated_workspace,
            "todos": updated_todos,
            "checkpoints": updated_checkpoints,
        }
    )


def _runtime_progress_by_step(
    events: Iterable[PublicRunEvent],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_step: dict[str, dict[str, Any]] = {}
    by_tool: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        progress = _runtime_progress_from_event(event.event_type, payload)
        if not progress:
            continue
        step_ids = _event_step_ids(payload)
        tool_name = _event_tool_name(payload)
        for step_id in step_ids:
            by_step[step_id] = progress
        if tool_name:
            by_tool[tool_name] = progress
    return by_step, by_tool


def _runtime_progress_by_artifact_path(
    events: Iterable[PublicRunEvent],
) -> dict[str, dict[str, Any]]:
    by_path: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.visibility != "user" or event.sensitivity != "public":
            continue
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        progress = _runtime_progress_from_event(event.event_type, payload)
        if not progress:
            continue
        if not _event_can_update_artifact_path(event.event_type, payload):
            continue
        for path in _event_artifact_paths(payload):
            by_path[path] = progress
    return by_path


def _runtime_progress_from_event(
    event_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    event_name = str(event_type or "").strip()
    status = str(
        payload.get("status")
        or payload.get("run_status")
        or payload.get("tool_status")
        or ""
    ).strip().lower()
    result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    result_ok = result.get("ok") if isinstance(result, Mapping) else None
    if (
        "approval_required" in event_name
        or status in {"approval_required", "waiting_approval", "requires_approval"}
    ):
        return {
            "todo_status": "blocked",
            "checkpoint_status": "waiting_approval",
            "runtime_status": status or "approval_required",
            "event_type": event_name,
        }
    if (
        result_ok is True
        or status in {"completed", "complete", "success", "succeeded", "ok"}
        or event_name.endswith(".completed")
    ):
        return {
            "todo_status": "completed",
            "checkpoint_status": "completed",
            "runtime_status": status or "completed",
            "event_type": event_name,
        }
    if (
        result_ok is False
        or status in {"failed", "failure", "error", "unavailable", "cancelled", "rejected"}
        or event_name.endswith(".failed")
    ):
        return {
            "todo_status": "blocked",
            "checkpoint_status": "blocked",
            "runtime_status": status or "failed",
            "event_type": event_name,
        }
    if status in {"running", "started", "in_progress"} or event_name in {
        "agent.tool.call",
        "tool.call",
    }:
        return {
            "todo_status": "in_progress",
            "checkpoint_status": "ready",
            "runtime_status": status or "in_progress",
            "event_type": event_name,
        }
    return {}


def _workspace_with_progress(
    workspace: TaskWorkspaceSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
    progress_by_artifact_path: Mapping[str, Mapping[str, Any]],
) -> TaskWorkspaceSnapshot:
    updated_items = [
        _workspace_item_with_progress(
            item,
            progress_by_step,
            progress_by_tool,
            progress_by_artifact_path,
        )
        for item in workspace.items
    ]
    return workspace.model_copy(update={"items": updated_items})


def _workspace_item_with_progress(
    item: TaskWorkspaceItemSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
    progress_by_artifact_path: Mapping[str, Mapping[str, Any]],
) -> TaskWorkspaceItemSnapshot:
    progress = _workspace_item_progress(
        item,
        progress_by_step,
        progress_by_tool,
        progress_by_artifact_path,
    )
    if not progress:
        return item
    metadata = {
        **dict(item.metadata or {}),
        "runtime_status": str(progress.get("runtime_status") or ""),
        "runtime_event_type": str(progress.get("event_type") or ""),
    }
    return item.model_copy(
        update={
            "status": _workspace_item_status_from_progress(progress, item.status),
            "metadata": metadata,
        }
    )


def _workspace_item_progress(
    item: TaskWorkspaceItemSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
    progress_by_artifact_path: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    source_step_id = str(
        item.source_step_id or (item.metadata or {}).get("source_step_id") or ""
    ).strip()
    if source_step_id and source_step_id in progress_by_step:
        return progress_by_step[source_step_id]

    if str(item.kind or "").strip() == "artifact":
        for path in _workspace_item_path_candidates(item):
            progress = progress_by_artifact_path.get(path)
            if progress:
                return progress

    tool_name = str((item.metadata or {}).get("tool_name") or "").strip()
    if tool_name and tool_name in progress_by_tool:
        return progress_by_tool[tool_name]
    return {}


def _workspace_item_status_from_progress(
    progress: Mapping[str, Any],
    fallback: Any,
) -> str:
    status = str(progress.get("todo_status") or "").strip()
    if status in {"completed", "blocked", "in_progress", "pending", "skipped"}:
        return status
    checkpoint_status = str(progress.get("checkpoint_status") or "").strip()
    if checkpoint_status == "completed":
        return "completed"
    if checkpoint_status in {"blocked", "waiting_approval"}:
        return "blocked"
    if checkpoint_status == "ready":
        return "in_progress"
    return str(fallback or "planned")


def _todo_with_progress(
    todo: TaskTodoItemSnapshot,
    progress_by_step: Mapping[str, Mapping[str, Any]],
    progress_by_tool: Mapping[str, Mapping[str, Any]],
) -> TaskTodoItemSnapshot:
    progress = progress_by_step.get(str(todo.step_id or "").strip()) or progress_by_tool.get(
        str(todo.tool_name or "").strip()
    )
    if not progress:
        return todo
    metadata = {
        **dict(todo.metadata or {}),
        "runtime_status": str(progress.get("runtime_status") or ""),
        "runtime_event_type": str(progress.get("event_type") or ""),
    }
    return todo.model_copy(
        update={
            "status": str(progress.get("todo_status") or todo.status),
            "metadata": metadata,
        }
    )


def _checkpoint_with_progress(
    checkpoint: TaskCheckpointSnapshot,
    todo_status_by_step: Mapping[str, str],
    progress_by_step: Mapping[str, Mapping[str, Any]],
) -> TaskCheckpointSnapshot:
    step_id = str(checkpoint.after_step_id or "").strip()
    if not step_id:
        return checkpoint
    progress = progress_by_step.get(step_id) or {}
    checkpoint_status = str(progress.get("checkpoint_status") or "").strip()
    if not checkpoint_status:
        todo_status = todo_status_by_step.get(step_id)
        checkpoint_status = (
            "completed"
            if todo_status == "completed"
            else ("blocked" if todo_status == "blocked" else "")
        )
    if not checkpoint_status:
        return checkpoint
    payload = {
        **dict(checkpoint.payload or {}),
        "runtime_status": str(progress.get("runtime_status") or checkpoint_status),
        "runtime_event_type": str(progress.get("event_type") or ""),
    }
    return checkpoint.model_copy(
        update={
            "status": checkpoint_status,
            "payload": payload,
        }
    )


def _workspace_item_path_candidates(item: TaskWorkspaceItemSnapshot) -> list[str]:
    candidates: list[str] = []
    for value in (
        item.path,
        item.title,
        (item.metadata or {}).get("planned_artifact"),
        (item.metadata or {}).get("artifact_path"),
    ):
        clean = str(value or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)
    return candidates


def _event_artifact_paths(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    _extend_artifact_paths(values, payload)
    result = payload.get("result")
    if isinstance(result, Mapping):
        _extend_artifact_paths(values, result)
        data = result.get("data")
        if isinstance(data, Mapping):
            _extend_artifact_paths(values, data)
    return values


def _event_can_update_artifact_path(event_type: str, payload: Mapping[str, Any]) -> bool:
    event_name = str(event_type or "").strip()
    if "artifact" in event_name:
        return True
    tool_name = _event_tool_name(payload)
    if tool_name == "artifact.write":
        return True
    result = payload.get("result")
    payloads: list[Mapping[str, Any]] = [payload]
    if isinstance(result, Mapping):
        payloads.append(result)
        data = result.get("data")
        if isinstance(data, Mapping):
            payloads.append(data)
    return any(
        any(key in item for key in ("artifact_path", "artifact_paths", "artifact_manifest"))
        for item in payloads
    )


def _extend_artifact_paths(values: list[str], payload: Mapping[str, Any]) -> None:
    for key in ("artifact_path", "path"):
        clean = str(payload.get(key) or "").strip()
        if clean and clean not in values:
            values.append(clean)
    for key in ("artifact_paths", "paths"):
        raw_paths = payload.get(key)
        if not isinstance(raw_paths, list):
            continue
        for path in raw_paths:
            clean = str(path or "").strip()
            if clean and clean not in values:
                values.append(clean)
    artifact_manifest = payload.get("artifact_manifest")
    if isinstance(artifact_manifest, list):
        for item in artifact_manifest:
            if not isinstance(item, Mapping):
                continue
            clean = str(item.get("path") or "").strip()
            if clean and clean not in values:
                values.append(clean)


def _event_step_ids(payload: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("step_id", "planner_step_id", "source_step_id"):
        clean = str(payload.get(key) or "").strip()
        if clean and clean not in values:
            values.append(clean)
    return values


def _event_tool_name(payload: Mapping[str, Any]) -> str:
    return str(payload.get("tool_name") or payload.get("tool") or "").strip()
