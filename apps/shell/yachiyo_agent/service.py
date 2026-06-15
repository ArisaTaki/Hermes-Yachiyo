"""Chat/Bubble/Live2D-facing Yachiyo Agent facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .adapters import readiness_snapshot_from_payload
from .contracts import (
    AgentTaskSnapshot,
    ApprovalDecision,
    ReadinessSnapshot,
    StartChatTaskRequest,
)
from .ports import RuntimePort
from .task_cards import agent_task_snapshot_from_payload, agent_task_snapshots_from_payloads


class YachiyoAgentService:
    """Facade for everyday Yachiyo Agent tasks."""

    def __init__(self, runtime_port: RuntimePort) -> None:
        self._runtime_port = runtime_port

    def readiness(self) -> ReadinessSnapshot:
        return readiness_snapshot_from_payload(self._runtime_port.readiness())

    def start_chat_task(
        self,
        request: StartChatTaskRequest | Mapping[str, Any],
    ) -> AgentTaskSnapshot:
        payload = _request_payload(request)
        return agent_task_snapshot_from_payload(self._runtime_port.start_chat_task(payload))

    def get_task_snapshot(self, task_id: str) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(self._runtime_port.get_task_snapshot(task_id))

    def list_recent_tasks(self, conversation_id: str | None = None) -> list[AgentTaskSnapshot]:
        return agent_task_snapshots_from_payloads(
            self._runtime_port.list_recent_tasks(conversation_id)
        )

    def approve(
        self,
        approval_id: str,
        decision: ApprovalDecision | Mapping[str, Any] | None = None,
    ) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(
            self._runtime_port.approve(approval_id, _optional_request_payload(decision))
        )

    def reject(self, approval_id: str, reason: str | None = None) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(self._runtime_port.reject(approval_id, reason))

    def cancel(self, task_id: str) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(self._runtime_port.cancel(task_id))


def _request_payload(request: StartChatTaskRequest | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(request, StartChatTaskRequest):
        return request.model_dump(exclude_none=True)
    return dict(request)


def _optional_request_payload(
    request: ApprovalDecision | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if request is None:
        return None
    if isinstance(request, ApprovalDecision):
        return request.model_dump(exclude_none=True)
    return dict(request)
