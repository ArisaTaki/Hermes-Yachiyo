"""Agent Run outcome projection helpers."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class RuntimeAgentRunOutcomeProjector:
    """Projects Agent Run completion and failure into events, timeline, and run state."""

    def __init__(
        self,
        *,
        append_run_event: Callable[..., Any],
        runtime_task_model_events: Any,
        runtime_agent_timeline: Any,
        runtime_agent_run_events: Any,
        get_run: Callable[[str], dict[str, Any]],
        update_run: Callable[..., dict[str, Any] | None],
        project_agent_run_group_if_root: Callable[[dict[str, Any]], Any] | None = None,
        model_output_metadata: Callable[[Any], dict[str, Any]],
        redact_secrets: Callable[[Any], str],
        transaction_scope: Callable[[], AbstractContextManager[Any]] | None = None,
    ) -> None:
        self._append_run_event = append_run_event
        self._runtime_task_model_events = runtime_task_model_events
        self._runtime_agent_timeline = runtime_agent_timeline
        self._runtime_agent_run_events = runtime_agent_run_events
        self._get_run = get_run
        self._update_run = update_run
        self._project_agent_run_group_if_root = project_agent_run_group_if_root
        self._model_output_metadata = model_output_metadata
        self._redact_secrets = redact_secrets
        self._transaction_scope = transaction_scope

    def completed(
        self,
        run_id: str,
        result: Any,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result_text = str(result)
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._get_run(run_id)
            if not _run_accepts_agent_outcome(current):
                return current
            next_timeline = [*timeline, self._runtime_agent_timeline.completed()]
            updated = self._update_run(
                run_id,
                status="completed",
                result=result_text,
                timeline=next_timeline,
                artifacts=artifacts,
                pending_approval=None,
                expected_status="running",
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if updated is None:
                return self._get_run(run_id)
            event_fence = _terminal_event_fence(updated, status="completed")
            _require_run_event(
                self._append_run_event(
                    run_id,
                    "model.output.completed",
                    self._runtime_task_model_events.model_output_completed_payload(
                        result_text,
                        truncated=bool(getattr(result, "output_truncated", False)),
                        metadata=self._model_output_metadata(result),
                    ),
                    **event_fence,
                )
            )
            _require_run_event(
                self._append_run_event(
                    run_id,
                    "agent.run.completed",
                    {"result": result_text},
                    **event_fence,
                )
            )
            self._project_root_run_group(updated)
        timeline[:] = next_timeline
        return updated

    def failed(
        self,
        run_id: str,
        exc: Exception,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        safe_error = self._redact_secrets(exc)
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._get_run(run_id)
            if not _run_accepts_agent_outcome(current):
                return current
            next_timeline = [*timeline, self._runtime_agent_timeline.failed(safe_error)]
            updated = self._update_run(
                run_id,
                status="failed",
                result=safe_error,
                timeline=next_timeline,
                artifacts=artifacts,
                pending_approval=None,
                expected_status="running",
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if updated is None:
                return self._get_run(run_id)
            _require_run_event(
                self._append_run_event(
                    run_id,
                    "agent.run.failed",
                    {"error": safe_error},
                    **_terminal_event_fence(updated, status="failed"),
                )
            )
            self._project_root_run_group(updated)
        timeline[:] = next_timeline
        return updated

    def _project_root_run_group(self, run: dict[str, Any]) -> None:
        if (
            run.get("project_root_group") is True
            and self._project_agent_run_group_if_root is not None
        ):
            self._project_agent_run_group_if_root(run)


def _run_accepts_agent_outcome(run: dict[str, Any]) -> bool:
    return (
        str(run.get("status") or "").strip().lower() == "running"
        and not run.get("pending_approval")
    )


def _terminal_event_fence(
    run: dict[str, Any],
    *,
    status: str,
) -> dict[str, str]:
    return {
        "expected_status": status,
        "expected_updated_at": str(run.get("updated_at") or ""),
    }


def _require_run_event(event: Any) -> None:
    if event is None:
        raise AgentRuntimeError("run_event_fence_mismatch")
