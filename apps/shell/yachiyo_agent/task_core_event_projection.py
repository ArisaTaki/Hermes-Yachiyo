"""Task-core event projections shared by planner previews and run events."""

from __future__ import annotations

from typing import Any

from .contracts import TaskCoreSnapshot


def task_core_initial_progress_event_payloads(
    task_core: TaskCoreSnapshot | None,
    *,
    source: str = "",
    decision_id: str = "",
    plan_id: str = "",
) -> list[tuple[str, dict[str, Any]]]:
    if task_core is None:
        return []
    base_payload = {
        "source": str(source or "").strip(),
        "decision_id": str(decision_id or "").strip(),
        "plan_id": str(plan_id or "").strip(),
        "core_id": task_core.core_id,
        "workspace_id": task_core.workspace.workspace_id,
        "runtime_status": "planned",
    }
    return [
        *_task_core_workspace_item_event_payloads(task_core, base_payload),
        *_task_core_todo_event_payloads(task_core, base_payload),
        *_task_core_checkpoint_event_payloads(task_core, base_payload),
    ]


def task_core_initial_progress_preview_events(
    task_core: TaskCoreSnapshot | None,
) -> list[dict[str, Any]]:
    return [
        {
            "event_type": event_type,
            "detail": task_core_progress_event_detail(event_type, payload),
            "payload": payload,
        }
        for event_type, payload in task_core_initial_progress_event_payloads(task_core)
    ]


def task_core_progress_event_detail(
    event_type: str,
    payload: dict[str, Any],
) -> str:
    if event_type == "agent.task.todo.updated":
        todo = payload.get("todo") if isinstance(payload.get("todo"), dict) else {}
        return str(
            todo.get("title")
            or payload.get("todo_id")
            or payload.get("step_id")
            or ""
        ).strip()
    if event_type == "agent.task.workspace_item.updated":
        workspace_item = (
            payload.get("workspace_item")
            if isinstance(payload.get("workspace_item"), dict)
            else {}
        )
        return str(
            workspace_item.get("title")
            or payload.get("workspace_item_id")
            or payload.get("step_id")
            or ""
        ).strip()
    if event_type == "agent.task.checkpoint.updated":
        checkpoint = (
            payload.get("checkpoint")
            if isinstance(payload.get("checkpoint"), dict)
            else {}
        )
        return str(
            checkpoint.get("title")
            or payload.get("checkpoint_id")
            or payload.get("step_id")
            or ""
        ).strip()
    return str(event_type or "").strip()


def _task_core_workspace_item_event_payloads(
    task_core: TaskCoreSnapshot,
    base_payload: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    payloads: list[tuple[str, dict[str, Any]]] = []
    for item in task_core.workspace.items:
        item_payload = item.model_dump(mode="json")
        status = str(item_payload.get("status") or "planned").strip() or "planned"
        payloads.append(
            (
                "agent.task.workspace_item.updated",
                {
                    **base_payload,
                    "workspace_item_id": str(
                        item_payload.get("item_id") or ""
                    ).strip(),
                    "step_id": str(item_payload.get("source_step_id") or "").strip(),
                    "status": status,
                    "previous_status": "",
                    "workspace_item": item_payload,
                },
            )
        )
    return payloads


def _task_core_todo_event_payloads(
    task_core: TaskCoreSnapshot,
    base_payload: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    payloads: list[tuple[str, dict[str, Any]]] = []
    for todo in task_core.todos:
        todo_payload = todo.model_dump(mode="json")
        status = str(todo_payload.get("status") or "pending").strip() or "pending"
        payloads.append(
            (
                "agent.task.todo.updated",
                {
                    **base_payload,
                    "todo_id": str(todo_payload.get("todo_id") or "").strip(),
                    "step_id": str(todo_payload.get("step_id") or "").strip(),
                    "tool": str(todo_payload.get("tool_name") or "").strip(),
                    "status": status,
                    "previous_status": "",
                    "todo": todo_payload,
                },
            )
        )
    return payloads


def _task_core_checkpoint_event_payloads(
    task_core: TaskCoreSnapshot,
    base_payload: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    payloads: list[tuple[str, dict[str, Any]]] = []
    for checkpoint in task_core.checkpoints:
        checkpoint_payload = checkpoint.model_dump(mode="json")
        status = str(checkpoint_payload.get("status") or "planned").strip() or "planned"
        payloads.append(
            (
                "agent.task.checkpoint.updated",
                {
                    **base_payload,
                    "checkpoint_id": str(
                        checkpoint_payload.get("checkpoint_id") or ""
                    ).strip(),
                    "step_id": str(checkpoint_payload.get("after_step_id") or "").strip(),
                    "status": status,
                    "previous_status": "",
                    "checkpoint": checkpoint_payload,
                },
            )
        )
    return payloads
