"""Runtime support compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.budget import (
    check_context_budget as _runtime_check_context_budget,
    limit_model_output as _runtime_limit_model_output,
    limit_tool_result as _runtime_limit_tool_result,
)
from apps.shell.agent.runtime.clock import utc_now_iso as _now
from apps.shell.agent.runtime.events import redact_json_value as _redact_json_value, redact_secrets
from apps.shell.agent.runtime.timeline import runtime_timeline_event as _runtime_timeline_event


class RuntimeSupportFacadeMixin:
    """Keeps legacy support helpers while delegating to split runtime services."""

    @staticmethod
    def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return _runtime_timeline_event(
            event,
            detail,
            now=_now,
            redact_detail=redact_secrets,
            redact_payload=_redact_json_value,
            **extra,
        )

    def _run_budget(self, run_id: str, timeline: list[dict[str, Any]]) -> Any:
        return self.runtime_run_budget(run_id, timeline)

    @staticmethod
    def _check_context_budget(budget: Any, messages: list[dict[str, Any]]) -> None:
        _runtime_check_context_budget(budget, messages, redact_json_value=_redact_json_value)

    def _limit_model_output(self, value: Any) -> tuple[str, bool]:
        return _runtime_limit_model_output(value, limits=self.runtime_limits, redact_text=redact_secrets)

    def _limit_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return _runtime_limit_tool_result(result, limits=self.runtime_limits, redact_json_value=_redact_json_value)
