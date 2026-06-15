"""Run request parsing helpers shared by Agent and Workflow starts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class RuntimeRunRequestParser:
    """Normalizes run-start request fields before persistence."""

    def __init__(
        self,
        *,
        contains_sensitive_text: Callable[[Any], bool],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._contains_sensitive_text = contains_sensitive_text
        self._error_type = error_type

    def client_request_id_from_payload(self, payload: dict[str, Any]) -> str:
        client_request_id = str(
            payload.get("client_run_id")
            or payload.get("client_request_id")
            or payload.get("idempotency_key")
            or ""
        ).strip()[:128]
        if self._contains_sensitive_text(client_request_id):
            raise self._error_type("client_run_id/idempotency_key 不能包含 API key、token 或其他敏感值")
        return client_request_id
