"""Yachiyo route facade construction helpers."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, Request

from apps.bridge.deps import get_runtime
from apps.shell.yachiyo_agent import (
    AgentStudioService,
    ChatTaskLifecycleProjector,
    YachiyoAgentService,
)
from apps.shell.yachiyo_agent.replan_continuation_results import (
    ReplanContinuationStartResult,
)
from apps.shell.yachiyo_agent.legacy_ports import (
    LegacyChatTaskStarter,
    LegacyRuntimePort,
    LegacyStudioPort,
)
from packages.security import redact_api_error_detail


def app_runtime_from_request(request: Request | None = None) -> Any:
    state = getattr(getattr(request, "app", None), "state", None)
    app_runtime = getattr(state, "runtime", None)
    if app_runtime is None:
        try:
            app_runtime = get_runtime()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Yachiyo runtime unavailable") from exc
    return app_runtime


def runtime_from_request(request: Request | None = None) -> Any:
    app_runtime = app_runtime_from_request(request)
    service = getattr(app_runtime, "agent_runtime_service", None)
    if service is not None:
        return service
    getter = getattr(app_runtime, "get_agent_runtime_service", None)
    if callable(getter):
        service = getter()
        if service is not None:
            return service
    raise HTTPException(status_code=503, detail="Yachiyo agent runtime unavailable")


def agent_service(request: Request | None = None) -> YachiyoAgentService:
    app_runtime = app_runtime_from_request(request)
    runtime = runtime_from_request(request)
    return YachiyoAgentService(
        LegacyRuntimePort(runtime),
        chat_task_starter=LegacyChatTaskStarter(app_runtime, runtime),
        task_lifecycle_projector=ChatTaskLifecycleProjector(app_runtime),
    )


def studio_service(request: Request | None = None) -> AgentStudioService:
    return AgentStudioService(LegacyStudioPort(runtime_from_request(request)))


def snapshot(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def replan_continuation_response(
    result: ReplanContinuationStartResult,
    *,
    item_key: Literal["task", "run"],
) -> dict[str, Any]:
    if result.item is not None:
        return {"started": True, item_key: snapshot(result.item)}

    response: dict[str, Any] = {
        "started": False,
        item_key: None,
        "reason": "no_auto_start_eligible_replan_continuation",
    }
    continuation = result.continuation
    if continuation is None:
        return response
    response.update(
        {
            "continuation": snapshot(continuation),
            "manual_start_available": True,
            "approval_required": continuation.approval_required,
            "auto_start_eligible": continuation.auto_start_eligible,
            "auto_start_reason": continuation.auto_start_reason
            or "manual_replan_continuation_required",
            "auto_start_blockers": list(continuation.auto_start_blockers),
            "replan_request_id": continuation.request_id,
            "action_id": continuation.action_id,
            "tool_name": continuation.tool_name,
        }
    )
    return response


def bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=redact_api_error_detail(exc))
