"""Chat/Bubble/Live2D-facing Yachiyo Agent facade."""

from __future__ import annotations

import logging
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
    RunEventPageSnapshot,
    RuntimeExecutionEnvelopeSnapshot,
    RunTimelineSnapshot,
    StartChatTaskRequest,
)
from .desktop_execution_policy import with_daily_entrypoint_desktop_execution_policy
from .event_page_windows import (
    FIRST_PAGE_TASK_KEY_EVENT_TYPES,
    events_with_first_page_key_event_window,
    run_event_page_with_projected_events,
)
from .events import public_run_event_page_from_payload
from .planner_projection import planner_enriched_chat_request
from .ports import ChatTaskStarter, RuntimePort, TaskLifecycleProjector
from .replan_continuation_results import ReplanContinuationStartResult
from .run_snapshots import run_timeline_snapshot_from_payload
from .runtime_execution import runtime_execution_envelope_from_decision
from .runtime_planner import RuntimePlanner
from .runtime_progress import ProgressEventScope, public_runtime_tool_result_events
from .start_event_enrichment import start_payload_with_planner_events
from .task_cards import agent_task_snapshot_from_payload, agent_task_snapshots_from_payloads
from .task_core_snapshots import task_core_snapshot_from_payload
from .task_snapshots import (
    _chat_task_tool_calls,
    _chat_visible_events as _chat_visible_task_events,
    run_events_from_payload,
)
from .tool_call_snapshots import tool_call_snapshots_from_payloads

_MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"
_RUNTIME_MANAGED_MAIN_CHAT_SOURCES = frozenset(
    {
        "chat",
        "launcher",
        "live2d",
        "packaged_daily_provider_acceptance_v2",
    }
)

_LOGGER = logging.getLogger(__name__)

_PUBLIC_CHAT_RUNTIME_AUTHORITY_METADATA_KEYS = frozenset(
    {
        "action_target",
        "allow_live_foreground",
        "allow_nonisolated_desktop_provider",
        "allow_user_foreground_takeover",
        "allowed_tools",
        "approval_id",
        "approval_required",
        "approval_status",
        "blocked_direct_tool_request",
        "blocked_direct_tool_requests",
        "blocking_conditions",
        "completion_authority",
        "decision_id",
        "desktop_allow_user_foreground_takeover",
        "desktop_execution_policy",
        "desktop_execution_route",
        "desktop_blocking_conditions",
        "desktop_blocking_conditions_by_capability",
        "desktop_interaction_policy",
        "desktop_permission_recovery",
        "desktop_provider_health_probe",
        "desktop_provider_id",
        "desktop_provider_kind",
        "desktop_provider_session_auto_start",
        "desktop_provider_session_id",
        "desktop_missing_permissions",
        "desktop_missing_permissions_by_capability",
        "desktop_runtime_blocking_conditions",
        "desktop_runtime_blocking_conditions_by_capability",
        "desktop_tool_readiness_by_tool",
        "direct_tool_request",
        "direct_tool_requests",
        "execution_authority",
        "execution_mode",
        "execution_envelope",
        "execution_request",
        "execution_requests",
        "goal_completion_authority",
        "goal_contract",
        "goal_contract_id",
        "goal_criterion_id",
        "missing_permissions",
        "plan_id",
        "planner_goal_contract",
        "planner_step_id",
        "policy_reason",
        "postcondition_verified",
        "prefer_background_desktop",
        "prefer_isolated_desktop",
        "provider_id",
        "provider_kind",
        "provider_readiness",
        "provider_tool_readiness",
        "readiness",
        "recovery_scope_id",
        "replan_request_id",
        "request_id",
        "risk_level",
        "run_id",
        "runtime_execution_envelope",
        "runtime_execution_metadata",
        "runtime_execution_request",
        "runtime_execution_requests",
        "runtime_tool_readiness_by_tool",
        "sandbox_id",
        "step_id",
        "task_core",
        "tool_readiness_by_tool",
        "tool_policy",
        "tool_call_id",
        "tool_plan_id",
        "verification_contract",
        "verification_passed",
        "workspace_policy",
        "yachiyo_desktop_execution_policy",
        "yachiyo_execution_envelope",
        "yachiyo_execution_request",
        "yachiyo_execution_requests",
        "yachiyo_goal_contract",
        "yachiyo_task_core",
    }
)
_PUBLIC_CHAT_RUNTIME_AUTHORITY_METADATA_PREFIXES = (
    "_runtime",
    "planner_execution_",
    "recovery_",
    "replan_",
    "runtime_execution_",
    "runtime_private_",
    "runtime_recovery_",
    "runtime_replan_",
    "yachiyo_execution_",
    "yachiyo_recovery_",
    "yachiyo_replan_",
    "yachiyo_runtime_",
)


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
        runtime_managed_main_chat = _runtime_managed_main_chat_request(payload)
        task: AgentTaskSnapshot | None = None
        if runtime_managed_main_chat and self._chat_task_starter is not None:
            runtime_managed_starter = getattr(
                self._chat_task_starter,
                "start_runtime_managed_main_chat_task",
                None,
            )
            if callable(runtime_managed_starter):
                chat_payload = runtime_managed_starter(payload)
                if chat_payload is not None:
                    task = _task_with_request_metadata(
                        agent_task_snapshot_from_payload(
                            self._start_payload_with_planner_events(chat_payload, payload)
                        ),
                        metadata,
                    )
        if task is None and self._chat_task_starter is not None and not runtime_managed_main_chat:
            chat_payload = self._chat_task_starter.start_chat_task(payload)
            if chat_payload is not None:
                task = _task_with_request_metadata(
                    agent_task_snapshot_from_payload(
                        self._start_payload_with_planner_events(chat_payload, payload)
                    ),
                    metadata,
                )
        if task is None:
            task = _task_with_request_metadata(
                agent_task_snapshot_from_payload(
                    self._start_payload_with_planner_events(
                        self._runtime_port.start_chat_task(payload),
                        payload,
                    )
                ),
                metadata,
            )
        external_chat_run = bool(
            runtime_managed_main_chat
            or str(payload.get("workflow_id") or "").strip()
            or str(payload.get("group_id") or payload.get("agent_group_id") or "").strip()
        )
        if external_chat_run and self._chat_task_starter is not None:
            record_user_message = getattr(
                self._chat_task_starter,
                "record_started_chat_user_message",
                None,
            )
            if callable(record_user_message):
                try:
                    record_user_message(payload, task.model_dump(mode="json"))
                except Exception:
                    remember_pending = getattr(
                        self._chat_task_starter,
                        "remember_pending_chat_user_message",
                        None,
                    )
                    pending_metadata = (
                        remember_pending(payload, task.model_dump(mode="json"))
                        if callable(remember_pending)
                        else {}
                    )
                    if pending_metadata:
                        task = task.model_copy(
                            update={
                                "metadata": {
                                    **dict(task.metadata or {}),
                                    **dict(pending_metadata),
                                }
                            }
                        )
        return task

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
            client_run_id=_chat_replan_client_id(payload),
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
            client_run_id=_chat_replan_client_id(payload),
            extra_metadata=(
                payload.get("metadata")
                if isinstance(payload.get("metadata"), Mapping)
                else {}
            ),
        )

    def get_task_snapshot(self, task_id: str) -> AgentTaskSnapshot:
        task = agent_task_snapshot_from_payload(
            self._runtime_port.get_task_snapshot(task_id)
        )
        task = self._repair_pending_chat_projection(task)
        return self._project_terminal_task(task_id, task)

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
        yield from _chat_visible_events(
            run_events_from_payload(raw_events, run_id=run_id, keys=("events",))
        )

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
                full_stream = list(self.get_task_event_stream(task_id))
                if not events:
                    events = [
                        event
                        for event in full_stream
                        if int(event.sequence or 0) > int(page.next_after_sequence or 0)
                    ][:clean_limit]
                events = events_with_first_page_key_event_window(
                    events,
                    full_stream,
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
        tasks = agent_task_snapshots_from_payloads(
            self._runtime_port.list_recent_tasks(conversation_id)
        )
        return [self._repair_pending_chat_projection(task) for task in tasks]

    def _repair_pending_chat_projection(
        self,
        task: AgentTaskSnapshot,
    ) -> AgentTaskSnapshot:
        if self._chat_task_starter is None:
            return task
        retry_pending = getattr(
            self._chat_task_starter,
            "retry_pending_chat_user_message",
            None,
        )
        task_payload = task.model_dump(mode="json")
        if callable(retry_pending):
            retry_pending(task.task_id, task_payload)
        pending_metadata_reader = getattr(
            self._chat_task_starter,
            "pending_chat_user_message_metadata",
            None,
        )
        pending_metadata = (
            pending_metadata_reader(task.task_id, task_payload)
            if callable(pending_metadata_reader)
            else {}
        )
        if not pending_metadata:
            return task
        return task.model_copy(
            update={
                "metadata": {
                    **dict(task.metadata or {}),
                    **dict(pending_metadata),
                }
            }
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
        metadata, ignored_metadata_paths = (
            _public_chat_metadata_without_runtime_authority(request.metadata)
        )
        ignored_top_level = sorted(
            str(key)
            for key in (request.model_extra or {})
            if str(key).strip()
        )
        ignored = [*ignored_top_level, *ignored_metadata_paths]
        if ignored:
            _LOGGER.warning(
                "Ignored Runtime authority fields from public chat task request: %s",
                ", ".join(sorted(set(ignored))),
            )
        payload: dict[str, Any] = {
            "prompt": request.prompt,
            "metadata": metadata,
        }
        for key in (
            "conversation_id",
            "title",
            "agent_id",
            "workflow_id",
            "group_id",
        ):
            value = getattr(request, key)
            if value is not None:
                payload[key] = value
        if request.attachments is not None:
            payload["attachments"] = [
                dict(item)
                for item in request.attachments
                if isinstance(item, Mapping)
            ]
        return payload
    return dict(request)


def _public_chat_metadata_without_runtime_authority(
    metadata: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    ignored_paths: list[str] = []

    def sanitize(value: Any, *, path: str) -> Any:
        if isinstance(value, Mapping):
            clean: dict[str, Any] = {}
            for raw_key, raw_value in value.items():
                key = str(raw_key or "").strip()
                normalized = key.casefold().replace("-", "_")
                child_path = f"{path}.{key}" if path else key
                if _public_chat_metadata_key_is_runtime_authority(normalized):
                    ignored_paths.append(child_path)
                    continue
                clean[key] = sanitize(raw_value, path=child_path)
            return clean
        if isinstance(value, list):
            return [
                sanitize(item, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
        if isinstance(value, tuple):
            return [
                sanitize(item, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
        return value

    return sanitize(metadata, path="metadata"), ignored_paths


def _public_chat_metadata_key_is_runtime_authority(key: str) -> bool:
    normalized = str(key or "").strip().casefold().replace("-", "_")
    return bool(
        normalized in _PUBLIC_CHAT_RUNTIME_AUTHORITY_METADATA_KEYS
        or normalized.startswith(
            _PUBLIC_CHAT_RUNTIME_AUTHORITY_METADATA_PREFIXES
        )
    )


def _runtime_managed_main_chat_request(payload: Mapping[str, Any]) -> bool:
    """Keep consumer main-agent tool runs on the asynchronous runtime path."""

    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    source = str(metadata.get("source") or "").strip().lower()
    if source not in _RUNTIME_MANAGED_MAIN_CHAT_SOURCES:
        return False

    if _chat_request_has_target(payload, "workflow_id") or _chat_request_has_target(
        payload,
        "group_id",
        "agent_group_id",
    ):
        return False
    if _chat_request_has_mapping_items(payload, "attachments"):
        return False
    runnable_id = str(
        payload.get("agent_id") or payload.get("runnable_id") or ""
    ).strip()
    if runnable_id and runnable_id != _MAIN_CHAT_AGENT_ID:
        return False
    direct_request = payload.get("direct_tool_request")
    return bool(
        (isinstance(direct_request, Mapping) and direct_request)
        or _chat_request_has_mapping_items(payload, "direct_tool_requests")
        or _chat_request_has_mapping_items(payload, "blocked_direct_tool_requests")
    )


def _chat_request_has_target(payload: Mapping[str, Any], *keys: str) -> bool:
    return any(str(payload.get(key) or "").strip() for key in keys)


def _chat_request_has_mapping_items(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return False
    return any(isinstance(item, Mapping) for item in value)


def _chat_replan_client_id(payload: Mapping[str, Any]) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    return str(
        payload.get("client_run_id")
        or payload.get("client_message_id")
        or payload.get("client_task_id")
        or payload.get("idempotency_key")
        or metadata.get("client_run_id")
        or metadata.get("client_message_id")
        or metadata.get("client_task_id")
        or metadata.get("idempotency_key")
        or ""
    ).strip()


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
    projected = run_timeline_snapshot_from_payload(clean_payload)
    # The generic timeline projector intentionally merges unmatched event tool
    # calls back into explicit payload tool calls. Chat has a narrower public
    # boundary: once internal verifier calls have been removed above, do not
    # let the generic merge re-introduce them into the project conversation.
    return projected.model_copy(
        update={
            "events": visible_events,
            "tool_calls": visible_tool_calls,
        }
    )


def _chat_visible_events(events: list[PublicRunEvent]) -> list[PublicRunEvent]:
    # Reuse the task-card boundary as the single visibility classifier, while
    # preserving the richer public payloads needed by timeline projections.
    return [event for event in events if _chat_visible_task_events([event])]
