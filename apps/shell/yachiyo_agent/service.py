"""Chat/Bubble/Live2D-facing Yachiyo Agent facade."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .adapters import readiness_snapshot_from_payload
from .artifacts import artifact_content_snapshot_from_payload
from .chat_runnables import chat_runnable_catalog_from_payloads
from .contracts import (
    AgentTaskSnapshot,
    ApprovalDecision,
    ArtifactContentSnapshot,
    ChatRunnableCatalogSnapshot,
    PlannerDecisionSnapshot,
    PublicRunEvent,
    ReadinessSnapshot,
    RunEventPageSnapshot,
    RunTimelineSnapshot,
    StartChatTaskRequest,
)
from .events import public_run_event_from_payload, public_run_event_page_from_payload
from .planner_projection import planner_enriched_chat_request
from .ports import ChatTaskStarter, RuntimePort
from .runtime_planner import RuntimePlanner
from .run_snapshots import run_timeline_snapshot_from_payload
from .task_cards import agent_task_snapshot_from_payload, agent_task_snapshots_from_payloads


class YachiyoAgentService:
    """Facade for everyday Yachiyo Agent tasks."""

    def __init__(
        self,
        runtime_port: RuntimePort,
        chat_task_starter: ChatTaskStarter | None = None,
    ) -> None:
        self._runtime_port = runtime_port
        self._chat_task_starter = chat_task_starter

    def readiness(self) -> ReadinessSnapshot:
        return readiness_snapshot_from_payload(self._runtime_port.readiness())

    def list_runnable_catalog(self) -> ChatRunnableCatalogSnapshot:
        payload = self._runtime_port.list_runnable_catalog()
        return chat_runnable_catalog_from_payloads(
            _payload_items(payload, "agents"),
            _payload_items(payload, "workflows"),
        )

    def plan_chat_task(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlannerDecisionSnapshot:
        port_planner = getattr(self._runtime_port, "plan_chat_task", None)
        if callable(port_planner):
            payload = port_planner(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata or {},
            )
            if payload is not None:
                return PlannerDecisionSnapshot.model_validate(payload)
        return RuntimePlanner().decision(
            prompt,
            allowed_tools=allowed_tools,
            metadata=metadata,
        )

    def start_chat_task(
        self,
        request: StartChatTaskRequest | Mapping[str, Any],
    ) -> AgentTaskSnapshot:
        payload = planner_enriched_chat_request(_request_payload(request))
        if self._chat_task_starter is not None:
            chat_payload = self._chat_task_starter.start_chat_task(payload)
            if chat_payload is not None:
                return agent_task_snapshot_from_payload(chat_payload)
        return agent_task_snapshot_from_payload(self._runtime_port.start_chat_task(payload))

    def get_task_snapshot(self, task_id: str) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(self._runtime_port.get_task_snapshot(task_id))

    def get_task_timeline(self, task_id: str) -> RunTimelineSnapshot:
        return _chat_timeline_snapshot_from_payload(self._runtime_port.get_task_timeline(task_id))

    def get_task_event_stream(self, task_id: str) -> Iterable[PublicRunEvent]:
        raw_events = self._runtime_port.get_task_event_stream(task_id)
        run_id = _payload_run_id(raw_events) or task_id
        for event in _payload_items(raw_events, "events"):
            yield public_run_event_from_payload(event, run_id=run_id)

    def get_task_event_page(
        self,
        task_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> RunEventPageSnapshot:
        clean_after_sequence = max(0, int(after_sequence or 0))
        clean_limit = max(1, min(500, int(limit or 200)))
        port_event_page = getattr(self._runtime_port, "get_task_event_page", None)
        if callable(port_event_page):
            raw_page = port_event_page(
                task_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            page = public_run_event_page_from_payload(
                raw_page,
                run_id=task_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            return page.model_copy(update={"events": _chat_visible_events(page.events)})

        events = _chat_visible_events(list(self.get_task_event_stream(task_id)))
        filtered_events = [
            event
            for event in events
            if int(event.sequence or 0) > clean_after_sequence
        ]
        page = filtered_events[:clean_limit]
        next_after_sequence = max(
            [int(event.sequence or 0) for event in page] or [clean_after_sequence]
        )
        run_id = events[0].run_id if events else task_id
        return RunEventPageSnapshot(
            run_id=run_id,
            after_sequence=clean_after_sequence,
            limit=clean_limit,
            next_after_sequence=next_after_sequence,
            has_more=len(filtered_events) > clean_limit,
            events=page,
        )

    def read_task_artifact(self, task_id: str, artifact_path: str) -> ArtifactContentSnapshot:
        return artifact_content_snapshot_from_payload(
            self._runtime_port.read_task_artifact(task_id, artifact_path),
            task_id=task_id,
            path=artifact_path,
        )

    def list_recent_tasks(self, conversation_id: str | None = None) -> list[AgentTaskSnapshot]:
        return agent_task_snapshots_from_payloads(
            self._runtime_port.list_recent_tasks(conversation_id)
        )

    def approve(
        self,
        task_id: str,
        decision: ApprovalDecision | Mapping[str, Any] | None = None,
    ) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(
            self._runtime_port.approve(task_id, _optional_request_payload(decision))
        )

    def reject(
        self,
        task_id: str,
        decision: ApprovalDecision | Mapping[str, Any] | str | None = None,
    ) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(
            self._runtime_port.reject(task_id, _rejection_payload(decision))
        )

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


def _rejection_payload(
    request: ApprovalDecision | Mapping[str, Any] | str | None,
) -> dict[str, Any] | None:
    if request is None:
        return None
    if isinstance(request, str):
        return {"approved": False, "reason": request}
    payload = _optional_request_payload(request)
    if payload is not None:
        payload.setdefault("approved", False)
    return payload


def _payload_items(payload: Any, key: str) -> list[dict[str, Any]]:
    items = payload.get(key) if isinstance(payload, Mapping) else payload
    if isinstance(items, list):
        return [dict(item) for item in items if isinstance(item, Mapping)]
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes)):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _payload_run_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("run_id") or "").strip()


def _chat_timeline_snapshot_from_payload(payload: Mapping[str, Any]) -> RunTimelineSnapshot:
    timeline = run_timeline_snapshot_from_payload(payload)
    visible_events = _chat_visible_events(timeline.events)
    clean_payload = dict(payload)
    clean_payload.pop("run_events", None)
    clean_payload.pop("recent_events", None)
    clean_payload.pop("timeline", None)
    clean_payload["events"] = [event.model_dump() for event in visible_events]
    return run_timeline_snapshot_from_payload(clean_payload)


def _chat_visible_events(events: list[PublicRunEvent]) -> list[PublicRunEvent]:
    return [
        event
        for event in events
        if event.visibility == "user" and event.sensitivity == "public"
    ]
