"""Agent Run outcome projection helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeAgentRunOutcomeProjector:
    """Projects Agent Run completion and failure into events, timeline, and run state."""

    def __init__(
        self,
        *,
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        runtime_task_model_events: Any,
        runtime_agent_timeline: Any,
        runtime_agent_run_events: Any,
        update_run: Callable[..., dict[str, Any]],
        model_output_metadata: Callable[[Any], dict[str, Any]],
        redact_secrets: Callable[[Any], str],
    ) -> None:
        self._append_run_event = append_run_event
        self._runtime_task_model_events = runtime_task_model_events
        self._runtime_agent_timeline = runtime_agent_timeline
        self._runtime_agent_run_events = runtime_agent_run_events
        self._update_run = update_run
        self._model_output_metadata = model_output_metadata
        self._redact_secrets = redact_secrets

    def completed(
        self,
        run_id: str,
        result: Any,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result_text = str(result)
        self._append_run_event(
            run_id,
            "model.output.completed",
            self._runtime_task_model_events.model_output_completed_payload(
                result_text,
                truncated=bool(getattr(result, "output_truncated", False)),
                metadata=self._model_output_metadata(result),
            ),
        )
        timeline.append(self._runtime_agent_timeline.completed())
        self._runtime_agent_run_events.completed(run_id, result_text)
        return self._update_run(
            run_id,
            status="completed",
            result=result_text,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )

    def failed(
        self,
        run_id: str,
        exc: Exception,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        safe_error = self._redact_secrets(exc)
        timeline.append(self._runtime_agent_timeline.failed(safe_error))
        self._runtime_agent_run_events.failed(run_id, safe_error)
        return self._update_run(
            run_id,
            status="failed",
            result=safe_error,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )
