"""Chat-facing Yachiyo route handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import (
    PlanExecutionBody,
    RunReplanRecoveryActionBody,
    StartNextReplanContinuationBody,
    TaskApprovalRequest,
)
from apps.bridge.routes.yachiyo_services import (
    agent_service,
    app_runtime_from_request,
    bad_request,
    blocked_replan_continuation_response,
    snapshot,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import ApprovalDecision, StartChatTaskRequest


async def readiness(http_request: Request | None = None) -> dict[str, Any]:
    return snapshot(await asyncio.to_thread(agent_service(http_request).readiness))


async def list_runnables(http_request: Request | None = None) -> dict[str, Any]:
    return snapshot(await asyncio.to_thread(agent_service(http_request).list_runnable_catalog))


async def list_tasks(
    conversation_id: str | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    tasks = await asyncio.to_thread(
        agent_service(http_request).list_recent_tasks,
        conversation_id,
    )
    return {"tasks": [snapshot(task) for task in tasks]}


async def start_task(
    request: StartChatTaskRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(agent_service(http_request).start_chat_task, request)
        return snapshot(task_snapshot)
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise bad_request(exc) from exc


async def start_replan_recovery_action(
    task_id: str,
    request: RunReplanRecoveryActionBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(
            agent_service(http_request).start_replan_recovery_action,
            task_id,
            request.model_dump(exclude_none=True),
        )
        return snapshot(task_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc
    except (AgentRuntimeError, ValueError) as exc:
        raise bad_request(exc) from exc


async def start_next_replan_continuation(
    task_id: str,
    request: StartNextReplanContinuationBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        service = agent_service(http_request)
        payload = request.model_dump(exclude_none=True)
        task_snapshot = await asyncio.to_thread(
            service.start_next_replan_continuation,
            task_id,
            payload,
        )
        if task_snapshot is None:
            manual_payload = {
                **payload,
                "include_manual": True,
                "auto_start_only": False,
            }
            continuation = await asyncio.to_thread(
                service.plan_next_replan_continuation,
                task_id,
                manual_payload,
            )
            return {
                "started": False,
                "task": None,
                "reason": "no_auto_start_eligible_replan_continuation",
                **blocked_replan_continuation_response(continuation),
            }
        return {"started": True, "task": snapshot(task_snapshot)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc
    except (AgentRuntimeError, ValueError) as exc:
        raise bad_request(exc) from exc


async def plan_task_execution(
    request: PlanExecutionBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        envelope = await asyncio.to_thread(
            agent_service(http_request).plan_chat_execution,
            request.prompt,
            allowed_tools=request.allowed_tools,
            metadata=request.metadata,
            direct=request.direct,
        )
        return snapshot(envelope)
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise bad_request(exc) from exc


async def get_task(
    task_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(agent_service(http_request).get_task_snapshot, task_id)
        return snapshot(task_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


async def get_task_timeline(
    task_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_timeline = await asyncio.to_thread(
            agent_service(http_request).get_task_timeline,
            task_id,
        )
        return snapshot(task_timeline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


async def get_task_events(
    task_id: str,
    http_request: Request | None = None,
    after_sequence: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    try:
        task_events = await asyncio.to_thread(
            agent_service(http_request).get_task_event_page,
            task_id,
            after_sequence,
            limit,
        )
        return snapshot(task_events)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


async def read_task_artifact(
    task_id: str,
    artifact_path: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        artifact = await asyncio.to_thread(
            agent_service(http_request).read_task_artifact,
            task_id,
            artifact_path,
        )
        return snapshot(artifact)
    except (AgentRuntimeError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Artifact 不存在") from exc


async def approve_task(
    task_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    metadata = dict(request.metadata) if request is not None else {}
    if request is not None and request.approval_id:
        metadata.setdefault("approval_id", request.approval_id)
    decision = ApprovalDecision(
        approved=True,
        reason=request.reason if request is not None else None,
        metadata=metadata,
    )
    try:
        task_snapshot = await asyncio.to_thread(
            agent_service(http_request).approve,
            task_id,
            decision,
        )
        _sync_terminal_task_snapshot_to_chat(task_id, task_snapshot, http_request)
        return snapshot(task_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def reject_task(
    task_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    metadata = dict(request.metadata) if request is not None else {}
    if request is not None and request.approval_id:
        metadata.setdefault("approval_id", request.approval_id)
    decision = ApprovalDecision(
        approved=False,
        reason=request.reason if request is not None else None,
        metadata=metadata,
    )
    try:
        task_snapshot = await asyncio.to_thread(
            agent_service(http_request).reject,
            task_id,
            decision,
        )
        _sync_terminal_task_snapshot_to_chat(task_id, task_snapshot, http_request)
        return snapshot(task_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def cancel_task(
    task_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(agent_service(http_request).cancel, task_id)
        return snapshot(task_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


def _sync_terminal_task_snapshot_to_chat(
    task_id: str,
    task_snapshot: Any,
    http_request: Request | None,
) -> None:
    status = str(getattr(task_snapshot, "status", "") or "").strip()
    if status not in {"completed", "failed", "cancelled"}:
        return
    try:
        app_runtime = app_runtime_from_request(http_request)
    except Exception:
        return

    summary = str(getattr(task_snapshot, "summary", "") or "").strip()
    if not summary:
        summary = "任务已完成" if status == "completed" else "任务未完成"
    _sync_app_task_status(app_runtime, task_id, status, summary)
    _sync_chat_assistant_message(app_runtime, task_id, task_snapshot, status, summary)


def _sync_app_task_status(app_runtime: Any, task_id: str, status: str, summary: str) -> None:
    state = getattr(app_runtime, "state", None)
    update_task_status = getattr(state, "update_task_status", None)
    if not callable(update_task_status):
        return
    try:
        from packages.protocol.enums import TaskStatus

        if status == "completed":
            update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                result=summary,
                progress_label="已完成",
            )
        else:
            update_task_status(
                task_id,
                TaskStatus.FAILED,
                error=summary,
                progress_label="执行失败",
            )
    except Exception:
        return


def _sync_chat_assistant_message(
    app_runtime: Any,
    task_id: str,
    task_snapshot: Any,
    status: str,
    summary: str,
) -> None:
    session = _chat_session_for_task_snapshot(app_runtime, task_snapshot)
    upsert = getattr(session, "upsert_assistant_message", None)
    if session is None or not callable(upsert):
        return
    try:
        from apps.core.chat_session import MessageStatus

        assistant = session.get_assistant_message_for_task(task_id)
        metadata = dict(getattr(assistant, "metadata", {}) or {}) if assistant is not None else {}
        metadata["pending_approval"] = {}
        metadata["run_status"] = status
        metadata.pop("run_progress_title", None)
        metadata.pop("run_progress_detail", None)
        message_status = MessageStatus.COMPLETED if status == "completed" else MessageStatus.FAILED
        upsert(
            task_id=task_id,
            content=summary,
            status=message_status,
            error=None if status == "completed" else summary,
            metadata=metadata,
        )
    except Exception:
        return


def _chat_session_for_task_snapshot(app_runtime: Any, task_snapshot: Any) -> Any:
    conversation_id = str(getattr(task_snapshot, "conversation_id", "") or "").strip()
    current = getattr(app_runtime, "chat_session", None)
    if not conversation_id:
        return current
    if str(getattr(current, "session_id", "") or "") == conversation_id:
        return current
    try:
        from apps.core.chat_session import ChatSession
        from apps.core.chat_store import get_chat_store

        store = getattr(app_runtime, "store", None) or get_chat_store()
        session = ChatSession(session_id=conversation_id)
        session.attach_store(
            store,
            load_existing=True,
            fail_active_messages=False,
        )
        return session
    except Exception:
        return current
