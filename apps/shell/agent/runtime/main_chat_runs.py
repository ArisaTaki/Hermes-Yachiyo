"""Main chat run lifecycle helpers for the legacy runtime entrypoint."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable


class MainChatRunLifecycle:
    """Starts and completes daily Chat runs while preserving task projections."""

    def __init__(
        self,
        *,
        main_chat_agent_id: str,
        insert_run: Callable[..., dict[str, Any]],
        link_task_run: Callable[..., Any],
        get_run: Callable[[str], dict[str, Any]],
        update_run: Callable[..., dict[str, Any]],
        task_run_links: Any,
        task_events: Any,
        timeline_factory: Callable[..., dict[str, Any]],
        redact_secrets: Callable[[Any], str],
        final_statuses: set[str],
    ) -> None:
        self._main_chat_agent_id = main_chat_agent_id
        self._insert_run = insert_run
        self._link_task_run = link_task_run
        self._get_run = get_run
        self._update_run = update_run
        self._task_run_links = task_run_links
        self._task_events = task_events
        self._timeline = timeline_factory
        self._redact_secrets = redact_secrets
        self._final_statuses = final_statuses

    def start(
        self,
        *,
        task_id: str,
        session_id: str,
        user_goal: str,
        metadata: dict[str, Any] | None = None,
        runtime_execution_envelope: Any | None = None,
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        run = self._insert_run(
            kind="main_chat_run",
            runnable_id=self._main_chat_agent_id,
            user_goal=self._redact_secrets(user_goal),
        )
        self._link_task_run(task_id=task_id, run_id=run["run_id"], session_id=session_id)
        start_payload = _main_chat_start_payload(
            task_id=task_id,
            session_id=session_id,
            metadata=metadata,
            runtime_execution_envelope=runtime_execution_envelope,
            direct_tool_request=direct_tool_request,
            direct_tool_requests=direct_tool_requests,
        )
        timeline = [
            self._timeline(
                "run.started",
                "Native main chat run started",
                **start_payload,
            ),
            *[
                self._timeline(
                    event["event"],
                    event["detail"],
                    **event["payload"],
                )
                for event in _desktop_provider_session_timeline_events(
                    start_payload,
                    redact=self._redact_secrets,
                )
            ],
            self._timeline("task.created", str(task_id or ""), task_id=str(task_id or "")),
            self._timeline("task.started", str(task_id or ""), task_id=str(task_id or "")),
            self._timeline("task.linked", str(task_id or ""), task_id=str(task_id or "")),
        ]
        run = self._update_run(run["run_id"], timeline=timeline)
        self._task_events.started(
            run["run_id"],
            task_id=str(task_id or ""),
            session_id=str(session_id or ""),
        )
        return run

    def complete(self, run_id: str, result: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        terminal = run if str(run.get("status") or "").strip() in self._final_statuses else None
        if terminal is not None:
            return terminal
        safe_result = self._redact_secrets(result)
        timeline = [
            *[event for event in run.get("timeline") or [] if isinstance(event, dict)],
            self._timeline("run.completed", "Native main chat run completed"),
        ]
        completed = self._update_run(
            run_id,
            status="completed",
            result=safe_result,
            timeline=timeline,
            pending_approval=None,
        )
        link = self._task_run_links.for_run(run_id)
        self._task_events.completed(
            run_id,
            task_id=str((link or {}).get("task_id") or ""),
            session_id=str((link or {}).get("session_id") or ""),
            result=safe_result,
        )
        return completed

    def fail(self, run_id: str, error: Any) -> dict[str, Any]:
        run = self._get_run(run_id)
        terminal = run if str(run.get("status") or "").strip() in self._final_statuses else None
        if terminal is not None:
            return terminal
        safe_error = self._redact_secrets(error)
        timeline = [
            *[event for event in run.get("timeline") or [] if isinstance(event, dict)],
            self._timeline("run.failed", safe_error),
        ]
        failed = self._update_run(
            run_id,
            status="failed",
            result=safe_error,
            timeline=timeline,
            pending_approval=None,
        )
        link = self._task_run_links.for_run(run_id)
        self._task_events.failed(
            run_id,
            task_id=str((link or {}).get("task_id") or ""),
            session_id=str((link or {}).get("session_id") or ""),
            error=safe_error,
        )
        return failed


def _main_chat_start_payload(
    *,
    task_id: str,
    session_id: str,
    metadata: dict[str, Any] | None,
    runtime_execution_envelope: Any | None,
    direct_tool_request: dict[str, Any] | None,
    direct_tool_requests: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "task_id": str(task_id or ""),
        "session_id": str(session_id or ""),
    }
    metadata_payload = dict(metadata) if isinstance(metadata, Mapping) else {}
    envelope = _runtime_execution_envelope_payload(
        runtime_execution_envelope,
        metadata_payload,
    )
    if metadata_payload:
        payload["metadata"] = metadata_payload
    if envelope is not None:
        payload["runtime_execution_envelope"] = envelope
    if isinstance(direct_tool_request, Mapping):
        payload["direct_tool_request"] = dict(direct_tool_request)
    requests = _direct_tool_requests_payload(direct_tool_requests)
    if requests:
        payload["direct_tool_requests"] = requests
    return payload


def _runtime_execution_envelope_payload(
    runtime_execution_envelope: Any | None,
    metadata: Mapping[str, Any],
) -> dict[str, Any] | None:
    if isinstance(runtime_execution_envelope, Mapping):
        return dict(runtime_execution_envelope)
    for key in ("runtime_execution_envelope", "yachiyo_execution_envelope"):
        envelope = metadata.get(key)
        if isinstance(envelope, Mapping):
            return dict(envelope)
    return None


def _direct_tool_requests_payload(
    direct_tool_requests: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not isinstance(direct_tool_requests, list):
        return []
    return [dict(request) for request in direct_tool_requests if isinstance(request, Mapping)]


def _desktop_provider_session_timeline_events(
    start_payload: Mapping[str, Any],
    *,
    redact: Callable[[Any], str] = str,
) -> list[dict[str, Any]]:
    envelope = start_payload.get("runtime_execution_envelope")
    if not isinstance(envelope, Mapping):
        return []
    session = envelope.get("desktop_provider_session")
    if not isinstance(session, Mapping):
        return []
    if not _provider_session_is_observable(session):
        return []
    event_name, detail = _desktop_provider_session_event_name(session)
    payload = {
        "task_id": str(start_payload.get("task_id") or ""),
        "session_id": str(start_payload.get("session_id") or ""),
        "desktop_provider_session": _desktop_provider_session_event_payload(
            session,
            redact=redact,
        ),
    }
    return [{"event": event_name, "detail": detail, "payload": payload}]


def _provider_session_is_observable(session: Mapping[str, Any]) -> bool:
    return any(
        bool(session.get(key))
        for key in ("needed", "started", "running", "error", "reason")
    )


def _desktop_provider_session_event_name(
    session: Mapping[str, Any],
) -> tuple[str, str]:
    if session.get("ok") is False or str(session.get("status") or "") == "start_failed":
        return (
            "desktop.provider_session.failed",
            "Isolated desktop provider failed to start",
        )
    if bool(session.get("started")):
        return (
            "desktop.provider_session.started",
            "Isolated desktop provider started",
        )
    if bool(session.get("running")):
        return (
            "desktop.provider_session.ready",
            "Isolated desktop provider is ready",
        )
    return (
        "desktop.provider_session.required",
        "Isolated desktop provider is required",
    )


def _desktop_provider_session_event_payload(
    session: Mapping[str, Any],
    *,
    redact: Callable[[Any], str] = str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    session_mode = _desktop_provider_session_mode(session)
    for key in (
        "ok",
        "status",
        "running",
        "started",
        "needed",
        "auto_start",
        "provider_id",
        "url",
        "pid",
        "reason",
        "request_ids",
        "tool_names",
        "error",
        "source",
    ):
        value = session.get(key)
        if value not in (None, "", [], {}):
            if key == "error":
                value = redact(value)
            payload[key] = value
    if session_mode:
        payload["desktop_execution_session_mode"] = session_mode
        payload["desktop_execution_session_label"] = _desktop_provider_session_mode_label(
            session_mode
        )
    return payload


def _desktop_provider_session_mode(session: Mapping[str, Any]) -> str:
    status = str(session.get("status") or "").strip().lower()
    if session.get("ok") is False or status in {"start_failed", "failed"}:
        return "provider_failed"
    kind = str(session.get("desktop_session_kind") or "").strip().lower()
    if kind:
        return kind
    if session.get("desktop_session_isolated") is True:
        return "isolated_desktop"
    if session.get("foreground_takeover_required") is True:
        return "user_foreground"
    if session.get("needed") and not session.get("running"):
        return "provider_required"
    return ""


def _desktop_provider_session_mode_label(mode: str) -> str:
    return {
        "headless_read_only": "headless read-only desktop provider",
        "isolated_desktop": "isolated desktop provider",
        "provider_failed": "desktop provider failed",
        "provider_required": "desktop provider required",
        "provider_routed": "desktop provider routed",
        "sandbox_desktop": "sandbox desktop provider",
        "user_foreground": "real desktop foreground",
    }.get(mode, mode.replace("_", " "))
