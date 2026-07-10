"""Chat/Bubble/Live2D-facing Yachiyo Agent facade."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from inspect import Parameter, signature
from typing import Any

from apps.shell.agent.runtime.events import redact_json_value

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
    ReplanContinuationSnapshot,
    RuntimeExecutionEnvelopeSnapshot,
    RunEventPageSnapshot,
    RunTimelineSnapshot,
    StartChatTaskRequest,
)
from .events import public_run_event_page_from_payload
from .event_page_windows import (
    FIRST_PAGE_TASK_KEY_EVENT_TYPES,
    events_with_first_page_key_event_window,
    run_event_page_with_projected_events,
)
from .desktop_execution_policy import with_daily_entrypoint_desktop_execution_policy
from .planner_projection import planner_enriched_chat_request
from .ports import ChatTaskStarter, RuntimePort, TaskLifecycleProjector
from .replan_continuation_results import ReplanContinuationStartResult
from .runtime_execution import runtime_execution_envelope_from_decision
from .runtime_planner import RuntimePlanner
from .runtime_progress import ProgressEventScope, public_runtime_tool_result_events
from .run_snapshots import run_timeline_snapshot_from_payload
from .start_event_enrichment import start_payload_with_planner_events
from .task_cards import agent_task_snapshot_from_payload, agent_task_snapshots_from_payloads
from .task_core_snapshots import task_core_snapshot_from_payload
from .task_snapshots import _chat_task_tool_calls, run_events_from_payload
from .tool_call_snapshots import tool_call_snapshots_from_payloads


class YachiyoAgentService:
    """Facade for everyday Yachiyo Agent tasks."""

    def __init__(
        self,
        runtime_port: RuntimePort,
        chat_task_starter: ChatTaskStarter | None = None,
        task_lifecycle_projector: TaskLifecycleProjector | None = None,
    ) -> None:
        self._runtime_port = runtime_port
        self._chat_task_starter = chat_task_starter
        self._task_lifecycle_projector = task_lifecycle_projector

    def readiness(self) -> ReadinessSnapshot:
        return readiness_snapshot_from_payload(self._runtime_port.readiness())

    def list_runnable_catalog(self) -> ChatRunnableCatalogSnapshot:
        payload = self._runtime_port.list_runnable_catalog()
        group_payloads = _payload_items(payload, "groups")
        if not group_payloads:
            list_groups = getattr(self._runtime_port, "list_groups", None)
            if callable(list_groups):
                group_payloads = _payload_items(list_groups(), "groups")
        return chat_runnable_catalog_from_payloads(
            _payload_items(payload, "agents"),
            _payload_items(payload, "workflows"),
            group_payloads,
        )

    def plan_chat_task(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlannerDecisionSnapshot:
        planner_metadata = _daily_chat_metadata(metadata)
        port_planner = getattr(self._runtime_port, "plan_chat_task", None)
        if callable(port_planner):
            payload = port_planner(
                prompt,
                allowed_tools=allowed_tools,
                metadata=planner_metadata,
            )
            if payload is not None:
                return PlannerDecisionSnapshot.model_validate(payload)
        return RuntimePlanner().decision(
            prompt,
            allowed_tools=allowed_tools,
            metadata=planner_metadata,
        )

    def plan_chat_execution(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        direct: bool = False,
        full_plan: bool = True,
    ) -> RuntimeExecutionEnvelopeSnapshot:
        planner_metadata = _daily_chat_metadata(metadata)
        port_planner = getattr(self._runtime_port, "plan_chat_execution", None)
        if callable(port_planner):
            payload = (
                _port_chat_execution_payload(
                    port_planner,
                    prompt,
                    allowed_tools=allowed_tools,
                    metadata=planner_metadata,
                    direct=direct,
                    full_plan=full_plan,
                )
                if full_plan
                else port_planner(
                    prompt,
                    allowed_tools=allowed_tools,
                    metadata=planner_metadata,
                    direct=direct,
                )
            )
            if payload is not None:
                return RuntimeExecutionEnvelopeSnapshot.model_validate(payload)
        decision = self.plan_chat_task(
            prompt,
            allowed_tools=allowed_tools,
            metadata=planner_metadata,
        )
        envelope = runtime_execution_envelope_from_decision(
            decision,
            allowed_tools=allowed_tools,
            direct=direct,
            full_plan=full_plan,
            metadata=planner_metadata,
        )
        if envelope is None:
            raise ValueError("Unable to build Yachiyo chat execution plan")
        return envelope

    def project_tool_result_events(
        self,
        decision: PlannerDecisionSnapshot,
        *,
        tool_request: Mapping[str, Any],
        tool_event: Mapping[str, Any],
        event_scope: ProgressEventScope = "auto",
        run_id: str = "",
        task_id: str = "",
        after_sequence: int = 0,
        existing_timeline: list[Mapping[str, Any]] | None = None,
    ) -> list[PublicRunEvent]:
        return public_runtime_tool_result_events(
            decision,
            tool_request=tool_request,
            tool_event=tool_event,
            event_scope=event_scope,
            run_id=run_id,
            task_id=task_id,
            after_sequence=after_sequence,
            existing_timeline=existing_timeline,
        )

    def start_chat_task(
        self,
        request: StartChatTaskRequest | Mapping[str, Any],
    ) -> AgentTaskSnapshot:
        payload = planner_enriched_chat_request(_request_payload(request))
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
        if self._chat_task_starter is not None:
            chat_payload = self._chat_task_starter.start_chat_task(payload)
            if chat_payload is not None:
                return _task_with_request_metadata(
                    agent_task_snapshot_from_payload(
                        self._start_payload_with_planner_events(chat_payload, payload)
                    ),
                    metadata,
                )
        return _task_with_request_metadata(
            agent_task_snapshot_from_payload(
                self._start_payload_with_planner_events(
                    self._runtime_port.start_chat_task(payload),
                    payload,
                )
            ),
            metadata,
        )

    def start_replan_recovery_action(
        self,
        task_id: str,
        request: Mapping[str, Any],
    ) -> AgentTaskSnapshot:
        payload = _request_payload(request)
        continuation = self.plan_replan_recovery_action(task_id, payload)
        from .studio_service import _chat_start_payload_from_replan_continuation

        return self.start_chat_task(
            _chat_start_payload_from_replan_continuation(continuation)
        )

    def start_next_replan_continuation(
        self,
        task_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> AgentTaskSnapshot | None:
        payload = _request_payload(request or {})
        payload["auto_start_only"] = True
        continuation = self.plan_next_replan_continuation(task_id, payload)
        if continuation is None:
            return None
        from .studio_service import _chat_start_payload_from_replan_continuation

        return self.start_chat_task(
            _chat_start_payload_from_replan_continuation(continuation)
        )

    def start_next_replan_continuation_result(
        self,
        task_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> ReplanContinuationStartResult:
        payload = _request_payload(request or {})
        task = self.start_next_replan_continuation(task_id, payload)
        continuation = None
        if task is None:
            continuation = self.plan_next_replan_continuation(
                task_id,
                {
                    **payload,
                    "include_manual": True,
                    "auto_start_only": False,
                },
            )
        return ReplanContinuationStartResult(
            item=task,
            continuation=continuation,
        )

    def plan_next_replan_continuation(
        self,
        task_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> ReplanContinuationSnapshot | None:
        payload = _request_payload(request or {})
        source_task = self.get_task_timeline(task_id)
        from .studio_service import (
            _next_replan_recovery_action_continuation,
            _payload_allows_manual_replan_continuation,
        )

        return _next_replan_recovery_action_continuation(
            source_task,
            payload,
            source="yachiyo_chat_replan_auto_continuation",
            conversation_id=str(
                payload.get("conversation_id") or source_task.task_id or task_id
            ).strip(),
            auto_start_only=not _payload_allows_manual_replan_continuation(payload),
        )

    def plan_replan_recovery_action(
        self,
        task_id: str,
        request: Mapping[str, Any],
    ) -> ReplanContinuationSnapshot:
        payload = _request_payload(request)
        source_task = self.get_task_timeline(task_id)
        from .studio_service import (
            _find_replan_recovery_action,
            _replan_recovery_action_continuation,
            _replan_recovery_action_objective,
            _replan_recovery_task_context,
        )

        request_id = str(payload.get("request_id") or "").strip()
        recovery, action = _find_replan_recovery_action(
            getattr(source_task, "replan_recoveries", []),
            request_id=request_id,
            action_id=str(payload.get("action_id") or "").strip(),
        )
        objective = _replan_recovery_action_objective(action)
        task_context = _replan_recovery_task_context(source_task, recovery, action)
        return _replan_recovery_action_continuation(
            source_task,
            recovery,
            action,
            task_context=task_context,
            continue_to_model=bool(payload.get("continue_to_model", True)),
            source="yachiyo_chat_replan_recovery",
            title=str(payload.get("title") or action.label or objective).strip(),
            conversation_id=(
                str(payload.get("conversation_id") or source_task.task_id or task_id).strip()
            ),
            extra_metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
        )

    def get_task_snapshot(self, task_id: str) -> AgentTaskSnapshot:
        return agent_task_snapshot_from_payload(self._runtime_port.get_task_snapshot(task_id))

    def get_task_timeline(self, task_id: str) -> RunTimelineSnapshot:
        return _chat_timeline_snapshot_from_payload(
            _task_context_payload(self._runtime_port.get_task_timeline(task_id), task_id)
        )

    def get_task_event_stream(self, task_id: str) -> Iterable[PublicRunEvent]:
        raw_events = _task_context_payload(
            self._runtime_port.get_task_event_stream(task_id),
            task_id,
        )
        run_id = _payload_run_id(raw_events) or task_id
        yield from run_events_from_payload(raw_events, run_id=run_id, keys=("events",))

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
            raw_page = _task_context_payload(
                port_event_page(
                    task_id,
                    after_sequence=clean_after_sequence,
                    limit=clean_limit,
                ),
                task_id,
            )
            page = public_run_event_page_from_payload(
                raw_page,
                run_id=task_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            events = _chat_visible_events(page.events)
            port_event_stream = getattr(self._runtime_port, "get_task_event_stream", None)
            if clean_after_sequence == 0 and page.has_more and callable(port_event_stream):
                events = events_with_first_page_key_event_window(
                    events,
                    _chat_visible_events(list(self.get_task_event_stream(task_id))),
                    page=page,
                    event_types=FIRST_PAGE_TASK_KEY_EVENT_TYPES,
                )
            return run_event_page_with_projected_events(page, events)

        events = _chat_visible_events(list(self.get_task_event_stream(task_id)))
        filtered_events = [
            event
            for event in events
            if int(event.sequence or 0) > clean_after_sequence
        ]
        page_events = filtered_events[:clean_limit]
        next_after_sequence = max(
            [int(event.sequence or 0) for event in page_events] or [clean_after_sequence]
        )
        run_id = events[0].run_id if events else task_id
        page = RunEventPageSnapshot(
            run_id=run_id,
            after_sequence=clean_after_sequence,
            limit=clean_limit,
            next_after_sequence=next_after_sequence,
            has_more=len(filtered_events) > clean_limit,
            events=page_events,
        )
        if clean_after_sequence == 0 and page.has_more:
            page_events = events_with_first_page_key_event_window(
                page_events,
                events,
                page=page,
                event_types=FIRST_PAGE_TASK_KEY_EVENT_TYPES,
            )
        return run_event_page_with_projected_events(page, page_events)

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
        task = agent_task_snapshot_from_payload(
            self._runtime_port.approve(task_id, _optional_request_payload(decision))
        )
        return self._project_terminal_task(task_id, task)

    def reject(
        self,
        task_id: str,
        decision: ApprovalDecision | Mapping[str, Any] | str | None = None,
    ) -> AgentTaskSnapshot:
        task = agent_task_snapshot_from_payload(
            self._runtime_port.reject(task_id, _rejection_payload(decision))
        )
        return self._project_terminal_task(task_id, task)

    def cancel(self, task_id: str) -> AgentTaskSnapshot:
        task = agent_task_snapshot_from_payload(self._runtime_port.cancel(task_id))
        return self._project_terminal_task(task_id, task)

    def _project_terminal_task(
        self,
        task_id: str,
        task_snapshot: AgentTaskSnapshot,
    ) -> AgentTaskSnapshot:
        if (
            self._task_lifecycle_projector is None
            or task_snapshot.status not in {"completed", "failed", "cancelled"}
        ):
            return task_snapshot
        try:
            self._task_lifecycle_projector.project_terminal_task(task_id, task_snapshot)
        except Exception:
            pass
        return task_snapshot

    def _start_payload_with_planner_events(
        self,
        raw_payload: Mapping[str, Any],
        request_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return start_payload_with_planner_events(
            raw_payload,
            request_payload,
            plan_task=self.plan_chat_task,
            metadata_source="yachiyo_agent_service_start",
        )


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


def _task_with_request_metadata(
    task: AgentTaskSnapshot,
    metadata: Mapping[str, Any],
) -> AgentTaskSnapshot:
    if not metadata:
        return task
    redacted = redact_json_value(dict(metadata))
    if not isinstance(redacted, Mapping):
        return task
    merged = {**dict(redacted), **dict(task.metadata or {})}
    return task.model_copy(
        update={
            "metadata": merged,
            "task_core": task.task_core
            or task_core_snapshot_from_payload({"metadata": merged}),
        }
    )


def _daily_chat_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(metadata) if isinstance(metadata, Mapping) else {}
    return with_daily_entrypoint_desktop_execution_policy(
        payload,
        surface=_daily_chat_surface(payload),
    )


def _daily_chat_surface(metadata: Mapping[str, Any]) -> str:
    launcher_mode = str(metadata.get("launcher_mode") or "").strip()
    if launcher_mode in {"bubble", "live2d"}:
        return launcher_mode
    source = str(
        metadata.get("entrypoint_source")
        or metadata.get("source")
        or ""
    ).strip()
    if source == "launcher":
        return "launcher"
    return "chat"


def _payload_run_id(payload: Any) -> str:
    if not isinstance(payload, Mapping):
        return ""
    return str(payload.get("run_id") or "").strip()


def _port_chat_execution_payload(
    port_planner: Any,
    prompt: str,
    *,
    allowed_tools: Iterable[str] | None,
    metadata: Mapping[str, Any],
    direct: bool,
    full_plan: bool,
) -> Any:
    if not _callable_accepts_keyword(port_planner, "full_plan"):
        return None
    return port_planner(
        prompt,
        allowed_tools=allowed_tools,
        metadata=metadata,
        direct=direct,
        full_plan=full_plan,
    )


def _callable_accepts_keyword(callback: Any, keyword: str) -> bool:
    try:
        parameters = signature(callback).parameters
    except (TypeError, ValueError):
        return True
    if keyword in parameters:
        return True
    return any(
        parameter.kind == Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _task_context_payload(payload: Any, task_id: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {"task_id": task_id, "events": []}
    clean_payload = dict(payload)
    clean_payload.setdefault("task_id", task_id)
    return clean_payload


def _chat_timeline_snapshot_from_payload(payload: Mapping[str, Any]) -> RunTimelineSnapshot:
    timeline = run_timeline_snapshot_from_payload(payload)
    visible_events = _chat_visible_events(timeline.events)
    event_tool_calls = tool_call_snapshots_from_payloads(None, events=visible_events)
    visible_tool_calls = _chat_task_tool_calls(event_tool_calls, visible_events)
    clean_payload = dict(payload)
    clean_payload.pop("run_events", None)
    clean_payload.pop("recent_events", None)
    clean_payload.pop("timeline", None)
    clean_payload["events"] = [event.model_dump() for event in visible_events]
    clean_payload["tool_calls"] = [
        tool_call.model_dump(mode="python") for tool_call in visible_tool_calls
    ]
    return run_timeline_snapshot_from_payload(clean_payload)


def _chat_visible_events(events: list[PublicRunEvent]) -> list[PublicRunEvent]:
    return [
        event
        for event in events
        if event.visibility == "user" and event.sensitivity == "public"
    ]
