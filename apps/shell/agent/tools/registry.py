"""ToolBroker dispatch registry.

This keeps tool-name routing separate from the concrete broker operations while
preserving the legacy ToolBroker.call surface.
"""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.errors import AgentRuntimeError

ToolDispatchHandler = Callable[[Any, dict[str, Any], bool], dict[str, Any]]


def _skill_read(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.skill_read(
        str(payload.get("skill_id") or ""),
        str(payload.get("name") or ""),
    )


def _memory_add(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.memory_add(
        str(payload.get("content") or ""),
        kind=str(payload.get("kind") or ""),
        scope=str(payload.get("scope") or ""),
    )


def _memory_replace(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.memory_replace(
        str(payload.get("content") or ""),
        memory_id=str(payload.get("memory_id") or ""),
        old_content=str(payload.get("old_content") or ""),
        kind=str(payload.get("kind") or ""),
        scope=str(payload.get("scope") or ""),
    )


def _memory_remove(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.memory_remove(
        memory_id=str(payload.get("memory_id") or ""),
        content=str(payload.get("content") or ""),
        reason=str(payload.get("reason") or ""),
    )


def _future_task_schedule(
    broker: Any, payload: dict[str, Any], _approved: bool
) -> dict[str, Any]:
    return broker.future_task_schedule(
        title=str(payload.get("title") or ""),
        prompt=str(payload.get("prompt") or ""),
        delay_seconds=payload.get("delay_seconds"),
        scheduled_at_epoch=payload.get("scheduled_at_epoch"),
        cron=str(payload.get("cron") or ""),
        runnable_id=str(payload.get("runnable_id") or ""),
        runnable_name=str(payload.get("runnable_name") or ""),
    )


def _future_task_list(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.future_task_list(
        include_finished=bool(payload.get("include_finished", True)),
        limit=int(payload.get("limit") or 100),
    )


def _future_task_cancel(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.future_task_cancel(
        str(payload.get("future_task_id") or ""),
        reason=str(payload.get("reason") or ""),
    )


def _workspace_list(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.workspace_list(str(payload.get("path") or "."))


def _workspace_read(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.workspace_read(str(payload.get("path") or ""))


def _workspace_write_patch(
    broker: Any, payload: dict[str, Any], approved: bool
) -> dict[str, Any]:
    return broker.workspace_write_patch(
        str(payload.get("path") or ""),
        str(payload.get("content") or ""),
        patch=str(payload.get("patch") or ""),
        expected_sha256=str(payload.get("expected_sha256") or payload.get("base_sha256") or ""),
        approved=approved,
    )


def _terminal_run(broker: Any, payload: dict[str, Any], approved: bool) -> dict[str, Any]:
    return broker.terminal_run(
        str(payload.get("command") or ""),
        approved=approved,
        timeout_seconds=int(payload.get("timeout_seconds") or 30),
        shell=bool(payload.get("shell", False)),
    )


def _artifact_write(broker: Any, payload: dict[str, Any], _approved: bool) -> dict[str, Any]:
    return broker.artifact_write(
        str(payload.get("path") or ""),
        str(payload.get("content") or ""),
    )


TOOL_DISPATCH_REGISTRY: dict[str, ToolDispatchHandler] = {
    "skill.read": _skill_read,
    "memory.add": _memory_add,
    "memory.replace": _memory_replace,
    "memory.remove": _memory_remove,
    "future_task.schedule": _future_task_schedule,
    "future_task.list": _future_task_list,
    "future_task.cancel": _future_task_cancel,
    "workspace.list": _workspace_list,
    "workspace.read": _workspace_read,
    "workspace.write_patch": _workspace_write_patch,
    "terminal.run": _terminal_run,
    "artifact.write": _artifact_write,
}


def dispatch_tool_call(
    broker: Any,
    name: str,
    payload: dict[str, Any],
    *,
    approved: bool = False,
) -> dict[str, Any]:
    handler = TOOL_DISPATCH_REGISTRY.get(name)
    if handler is None:
        raise AgentRuntimeError(f"未知工具：{name}")
    return handler(broker, payload, approved)


__all__ = ["TOOL_DISPATCH_REGISTRY", "dispatch_tool_call"]
