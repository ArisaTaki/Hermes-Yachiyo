"""Agent Studio-facing facade for agents, groups, workflows, and timelines."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .adapters import agent_definition_snapshot_from_payload
from .artifacts import artifact_content_snapshot_from_payload
from .contracts import (
    AgentDefinitionSnapshot,
    AgentDeskFileEventRequest,
    AgentDeskSnapshot,
    AgentGroupSnapshot,
    ApprovalDecision,
    ArtifactContentSnapshot,
    FutureTaskSnapshot,
    FutureTaskTriggerResultSnapshot,
    GroupRunSnapshot,
    InstallRestrictedToolPluginRequest,
    MemorySnapshot,
    PlannerDecisionSnapshot,
    PlannerOrchestrationStartSnapshot,
    PublicRunEvent,
    ReplanContinuationSnapshot,
    ReplanRecoveryActionSnapshot,
    ReplanRecoverySnapshot,
    RerunRunRequest,
    RuntimeExecutionEnvelopeSnapshot,
    RunEventPageSnapshot,
    RunTimelineSnapshot,
    RestrictedToolPluginSnapshot,
    SaveAgentGroupRequest,
    SaveAgentDeskFileRequest,
    SaveAgentDeskNoteRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    SkillFolderSnapshot,
    SkillSnapshot,
    SkillSourceRootSnapshot,
    StartAgentRunRequest,
    StartGroupRunRequest,
    StartPlannerOrchestrationRequest,
    StartWorkflowRunRequest,
    TaskCoreSnapshot,
    ToolCatalogSnapshot,
    ToolCallSnapshot,
    UpdateRestrictedToolPluginRequest,
    WorkflowRunSnapshot,
    WorkflowSnapshot,
)
from .desktop_execution_policy import (
    agent_studio_desktop_execution_policy,
    desktop_execution_policy_payload,
    runtime_execution_envelope_with_desktop_execution_policy,
    with_agent_studio_desktop_execution_policy,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from .desk import agent_desk_snapshot_from_payload
from .events import public_run_event_page_from_payload
from .event_page_windows import (
    FIRST_PAGE_GROUP_RUN_KEY_EVENT_TYPES,
    FIRST_PAGE_RUN_KEY_EVENT_TYPES,
    FIRST_PAGE_RUN_OR_WORKFLOW_KEY_EVENT_TYPES,
    FIRST_PAGE_WORKFLOW_RUN_KEY_EVENT_TYPES,
    events_with_first_page_key_event_window,
    run_event_page_with_projected_events,
)
from .future_tasks import (
    future_task_snapshot_from_payload,
    future_task_trigger_result_snapshot_from_payload,
)
from .groups import agent_group_snapshot_from_payload, group_run_snapshot_from_payload
from .isolated_provider_session import (
    annotate_envelope_with_desktop_provider_session,
    ensure_isolated_desktop_provider_session_for_envelope,
)
from .memories import memory_snapshot_from_payload
from .ports import StudioPort
from .planner_projection import runtime_planner_metadata
from .runtime_execution import (
    runtime_execution_envelope_from_decision,
    runtime_execution_envelope_payload_with_request_context,
    runtime_execution_requests_from_envelope_payload,
)
from .runtime_planner import RuntimePlanner
from .runtime_progress import ProgressEventScope, public_runtime_tool_result_events
from .start_event_enrichment import (
    start_payload_with_planner_decision_events,
    start_payload_with_planner_events,
)
from .task_progress_snapshots import task_progress_summary_from_task_core
from .skills import (
    skill_folder_snapshot_from_payload,
    skill_snapshot_from_payload,
    skill_source_root_snapshot_from_payload,
)
from .timelines import run_timeline_snapshot_from_payload
from .tool_catalog import (
    restricted_tool_plugin_snapshot_from_payload,
    runtime_tool_catalog_snapshot,
    tool_catalog_snapshot_from_payload,
)
from .workflows import (
    is_workflow_run_payload,
    workflow_run_snapshot_from_payload,
    workflow_snapshot_from_payload,
)


def _planner_metadata_with_catalog_readiness(
    metadata: Mapping[str, Any] | None,
    catalog: ToolCatalogSnapshot,
) -> dict[str, Any]:
    enriched = dict(metadata or {})
    enriched.setdefault("runtime_planner_request_trace", True)
    missing: dict[str, list[str]] = {}
    blocking: dict[str, list[str]] = {}
    for capability_id, capability in catalog.capabilities.items():
        clean_id = str(capability_id or "").strip()
        if not clean_id:
            continue
        if capability.missing_permissions:
            missing[clean_id] = list(capability.missing_permissions)
        if capability.blocking_conditions:
            blocking[clean_id] = list(capability.blocking_conditions)
    if missing and not isinstance(enriched.get("desktop_missing_permissions_by_capability"), dict):
        enriched["desktop_missing_permissions_by_capability"] = missing
    if blocking and not isinstance(enriched.get("desktop_blocking_conditions_by_capability"), dict):
        enriched["desktop_blocking_conditions_by_capability"] = blocking
    provider = catalog.sandbox_provider
    if provider is not None:
        enriched.setdefault("desktop_provider_available", bool(provider.available))
        enriched.setdefault("desktop_provider_adapter_ready", bool(provider.adapter_ready))
        enriched.setdefault("desktop_provider_id", str(provider.provider_id or ""))
        enriched.setdefault("desktop_provider_kind", str(provider.provider_kind or ""))
        enriched.setdefault(
            "desktop_provider_supported_tools",
            list(provider.supported_tools),
        )
        enriched.setdefault(
            "sandbox_provider",
            provider.model_dump(mode="json"),
        )
    return enriched


def _tool_names_from_catalog(
    catalog: ToolCatalogSnapshot,
    allowed_tools: Iterable[str] | None,
) -> list[str]:
    if allowed_tools is not None:
        return list(allowed_tools)
    return [
        str(tool.tool_name or "").strip()
        for tool in catalog.tools
        if str(tool.tool_name or "").strip()
    ]


_STUDIO_DESKTOP_BACKFILL_TOOLS = (
    "desktop.list_apps",
    "app.open",
    "desktop.verify",
)
_STUDIO_DESKTOP_BACKFILL_CAPABILITIES = {
    "desktop.app_discovery",
    "desktop.app_control",
    "desktop.visual_verification",
}


def _runtime_planner_decision_for_studio(
    prompt: str,
    *,
    catalog: ToolCatalogSnapshot,
    allowed_tools: Iterable[str] | None,
    metadata: Mapping[str, Any],
) -> tuple[PlannerDecisionSnapshot, dict[str, Any]]:
    enriched_metadata = dict(metadata)
    tools = _tool_names_from_catalog(catalog, allowed_tools)
    decision = RuntimePlanner().decision(
        prompt,
        allowed_tools=tools or None,
        metadata=enriched_metadata,
    )
    if allowed_tools is not None or not _decision_needs_desktop_backfill(decision):
        return decision, enriched_metadata

    backfilled_tools = _dedupe_tool_names([*tools, *_STUDIO_DESKTOP_BACKFILL_TOOLS])
    if backfilled_tools == tools:
        return decision, enriched_metadata

    enriched_metadata = {
        **enriched_metadata,
        "runtime_planner_catalog_backfill": "desktop_discover_operate_verify",
        "runtime_planner_catalog_backfilled_tools": list(_STUDIO_DESKTOP_BACKFILL_TOOLS),
    }
    return RuntimePlanner().decision(
        prompt,
        allowed_tools=backfilled_tools,
        metadata=enriched_metadata,
    ), enriched_metadata


def _decision_needs_desktop_backfill(decision: PlannerDecisionSnapshot) -> bool:
    intent_kind = str(decision.selected_intent.kind or "").strip()
    if intent_kind != "desktop_operation":
        return False
    missing = {
        str(capability_id or "").strip()
        for capability_id in decision.plan.tool_plan.missing_capabilities
        if str(capability_id or "").strip()
    }
    if not missing.intersection(_STUDIO_DESKTOP_BACKFILL_CAPABILITIES):
        return False
    return any(
        str(step.capability_id or "").strip() in _STUDIO_DESKTOP_BACKFILL_CAPABILITIES
        and str(step.status or "").strip() == "unavailable"
        and not str(step.tool_name or "").strip()
        for step in decision.plan.tool_plan.steps
    )


def _dedupe_tool_names(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    tools: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        tools.append(clean)
    return tools


def _studio_runtime_execution_envelope_with_policy(
    envelope: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(envelope, RuntimeExecutionEnvelopeSnapshot):
        payload = envelope.model_dump(mode="json")
    elif isinstance(envelope, Mapping):
        payload = dict(envelope)
    else:
        return {}
    return runtime_execution_envelope_with_desktop_execution_policy(
        payload,
        _studio_desktop_execution_policy(metadata),
    )


def _runtime_execution_envelope_payload_for_start(
    decision: PlannerDecisionSnapshot,
    *,
    allowed_tools: Iterable[str] | None = None,
    full_plan: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        full_plan=full_plan,
        metadata=metadata,
    )
    if envelope is None:
        return {}
    payload = envelope.model_dump(mode="json")
    session = ensure_isolated_desktop_provider_session_for_envelope(payload)
    if session.get("needed") and session.get("running"):
        refreshed = runtime_execution_envelope_from_decision(
            decision,
            allowed_tools=allowed_tools,
            full_plan=full_plan,
            metadata=metadata,
        )
        if refreshed is not None:
            payload = refreshed.model_dump(mode="json")
    return annotate_envelope_with_desktop_provider_session(payload, session)


def _studio_runtime_execution_envelope_for_start(
    envelope: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _studio_runtime_execution_envelope_with_policy(envelope, metadata)
    existing_session = (
        dict(payload.get("desktop_provider_session"))
        if isinstance(payload.get("desktop_provider_session"), Mapping)
        else {}
    )
    if existing_session.get("needed") and existing_session.get("running"):
        return annotate_envelope_with_desktop_provider_session(payload, existing_session)
    session = ensure_isolated_desktop_provider_session_for_envelope(payload)
    if session.get("needed") and session.get("running"):
        payload = _studio_runtime_execution_envelope_with_policy(payload, metadata)
    return annotate_envelope_with_desktop_provider_session(payload, session)


def _studio_runtime_execution_envelope_for_plan(
    envelope: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _studio_runtime_execution_envelope_with_policy(envelope, metadata)
    existing_session = (
        dict(payload.get("desktop_provider_session"))
        if isinstance(payload.get("desktop_provider_session"), Mapping)
        else {}
    )
    if _desktop_provider_session_is_relevant(existing_session):
        return annotate_envelope_with_desktop_provider_session(payload, existing_session)
    session = ensure_isolated_desktop_provider_session_for_envelope(
        payload,
        auto_start=False,
    )
    if not _desktop_provider_session_is_relevant(session):
        return payload
    if session.get("needed") and session.get("running"):
        payload = _studio_runtime_execution_envelope_with_policy(payload, metadata)
    return annotate_envelope_with_desktop_provider_session(payload, session)


def _desktop_provider_session_is_relevant(session: Mapping[str, Any]) -> bool:
    if not session:
        return False
    if session.get("needed") or session.get("running") or session.get("started"):
        return True
    if session.get("ok") is False:
        return True
    return str(session.get("reason") or "").strip() != ""


def _studio_desktop_execution_policy(metadata: Mapping[str, Any]) -> dict[str, Any]:
    for key in (
        "desktop_execution_policy",
        "yachiyo_desktop_execution_policy",
        "desktop_interaction_policy",
    ):
        policy = desktop_execution_policy_payload(metadata.get(key))
        if policy:
            return policy
    return agent_studio_desktop_execution_policy()


class AgentStudioService:
    """Facade for Agent Studio, groups, workflows, and runtime debugging."""

    def __init__(self, studio_port: StudioPort) -> None:
        self._studio_port = studio_port

    def list_agents(self) -> list[AgentDefinitionSnapshot]:
        return [
            agent_definition_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_agents(), "agents")
        ]

    def list_tool_catalog(self) -> ToolCatalogSnapshot:
        list_catalog = getattr(self._studio_port, "list_tool_catalog", None)
        if callable(list_catalog):
            return tool_catalog_snapshot_from_payload(list_catalog())
        return runtime_tool_catalog_snapshot()

    def desktop_provider_session_status(self) -> dict[str, Any]:
        session_status = getattr(self._studio_port, "desktop_provider_session_status", None)
        if callable(session_status):
            return dict(session_status())
        return {"ok": True, "status": "unavailable", "running": False}

    def start_desktop_provider_session(
        self,
        request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        start_session = getattr(self._studio_port, "start_desktop_provider_session", None)
        if callable(start_session):
            return dict(start_session(dict(request or {})))
        return {"ok": False, "status": "unavailable", "running": False}

    def stop_desktop_provider_session(self) -> dict[str, Any]:
        stop_session = getattr(self._studio_port, "stop_desktop_provider_session", None)
        if callable(stop_session):
            return dict(stop_session())
        return {"ok": True, "status": "unavailable", "running": False}

    def plan_task(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlannerDecisionSnapshot:
        planner_metadata = with_agent_studio_desktop_execution_policy(metadata)
        port_planner = getattr(self._studio_port, "plan_task", None)
        if callable(port_planner):
            payload = port_planner(
                prompt,
                allowed_tools=allowed_tools,
                metadata=planner_metadata,
            )
            if payload is not None:
                return PlannerDecisionSnapshot.model_validate(payload)
        catalog = self.list_tool_catalog()
        enriched_metadata = _planner_metadata_with_catalog_readiness(
            planner_metadata,
            catalog,
        )
        decision, _metadata = _runtime_planner_decision_for_studio(
            prompt,
            metadata=enriched_metadata,
            catalog=catalog,
            allowed_tools=allowed_tools,
        )
        return decision

    def plan_execution(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        direct: bool = False,
    ) -> RuntimeExecutionEnvelopeSnapshot:
        planner_metadata = with_agent_studio_desktop_execution_policy(metadata)
        port_planner = getattr(self._studio_port, "plan_execution", None)
        if callable(port_planner):
            payload = port_planner(
                prompt,
                allowed_tools=allowed_tools,
                metadata=planner_metadata,
                direct=direct,
            )
            if payload is not None:
                return RuntimeExecutionEnvelopeSnapshot.model_validate(
                    _studio_runtime_execution_envelope_for_plan(
                        payload,
                        planner_metadata,
                    )
                )
        catalog = self.list_tool_catalog()
        enriched_metadata = _planner_metadata_with_catalog_readiness(
            planner_metadata,
            catalog,
        )
        port_planner = getattr(self._studio_port, "plan_task", None)
        if callable(port_planner):
            payload = port_planner(
                prompt,
                allowed_tools=allowed_tools,
                metadata=enriched_metadata,
            )
            if payload is not None:
                decision = PlannerDecisionSnapshot.model_validate(payload)
            else:
                decision, enriched_metadata = _runtime_planner_decision_for_studio(
                    prompt,
                    metadata=enriched_metadata,
                    catalog=catalog,
                    allowed_tools=allowed_tools,
                )
        else:
            decision, enriched_metadata = _runtime_planner_decision_for_studio(
                prompt,
                metadata=enriched_metadata,
                catalog=catalog,
                allowed_tools=allowed_tools,
            )
        envelope = runtime_execution_envelope_from_decision(
            decision,
            allowed_tools=allowed_tools,
            direct=direct,
            full_plan=True,
            metadata=enriched_metadata,
        )
        if envelope is None:
            raise ValueError("Unable to build Agent Studio execution plan")
        return RuntimeExecutionEnvelopeSnapshot.model_validate(
            _studio_runtime_execution_envelope_for_plan(
                envelope.model_dump(mode="json"),
                planner_metadata,
            )
        )

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

    def start_planner_orchestration(
        self,
        request: StartPlannerOrchestrationRequest | Mapping[str, Any],
    ) -> PlannerOrchestrationStartSnapshot:
        payload = _request_payload(request)
        prompt = str(payload.get("prompt") or payload.get("objective") or "").strip()
        if not prompt:
            raise AgentRuntimeError("Planner orchestration prompt is required")

        metadata = (
            dict(payload.get("metadata"))
            if isinstance(payload.get("metadata"), Mapping)
            else {}
        )
        metadata = with_agent_studio_desktop_execution_policy(metadata)
        allowed_tools = _string_list(
            payload.get("allowed_tools"),
            fallback=["workflow.run", "group.run", "agent.group_run"],
        )
        decision = self.plan_task(
            prompt,
            allowed_tools=allowed_tools,
            metadata=metadata,
        )
        kind = _planner_orchestration_kind(decision)
        objective = (
            str(payload.get("objective") or decision.selected_intent.user_goal or prompt)
            .strip()
        )
        title = (
            str(payload.get("title") or decision.selected_intent.title or objective)
            .strip()
        )
        target_name = (
            str(
                payload.get("target_name")
                or _planner_intent_input(decision, "target_name_hint")
                or ""
            )
            .strip()
        )
        client_run_id = str(payload.get("client_run_id") or "").strip()
        if kind == "workflow":
            target = self._planner_workflow_target(
                target_id=str(
                    payload.get("workflow_id")
                    or payload.get("target_id")
                    or ""
                ).strip(),
                target_name=target_name,
            )
            if target.target_id:
                metadata_context = _planner_orchestration_execution_context(
                    kind="workflow",
                    target_id=target.target_id,
                )
                workflow_payload = _planner_orchestration_start_payload(
                    {
                        "workflow_id": target.target_id,
                        "objective": objective,
                        "title": title or target.target_name or "Workflow run",
                        "client_run_id": client_run_id or None,
                    },
                    metadata,
                    decision,
                    kind="workflow",
                    target_id=target.target_id,
                    target_name=target.target_name,
                    allowed_tools=allowed_tools,
                    execution_context=metadata_context,
                )
                raw_workflow_run = self._studio_port.start_workflow_run(workflow_payload)
                workflow_run = workflow_run_snapshot_from_payload(
                    start_payload_with_planner_decision_events(
                        raw_workflow_run,
                        decision,
                        event_context=_planner_orchestration_execution_context(
                            kind="workflow",
                            target_id=target.target_id,
                            run_payload=raw_workflow_run,
                        ),
                    )
                )
                return PlannerOrchestrationStartSnapshot(
                    kind="workflow",
                    status="started",
                    decision=decision,
                    run_id=workflow_run.run_id,
                    workflow_run_id=workflow_run.workflow_run_id or workflow_run.run_id,
                    target_id=target.target_id,
                    target_name=target.target_name,
                    objective=objective,
                    title=title,
                    route_to_studio=bool(decision.plan.route_to_studio),
                    message="Workflow run started from planner orchestration.",
                    workflow_run=workflow_run,
                )
            return _planner_orchestration_handoff_snapshot(
                decision,
                kind="workflow",
                status="target_not_found" if target_name else "handoff",
                target_name=target_name or None,
                objective=objective,
                title=title,
            )

        if kind == "group_run":
            target = self._planner_group_target(
                target_id=str(
                    payload.get("group_id")
                    or payload.get("target_id")
                    or ""
                ).strip(),
                target_name=target_name,
            )
            if target.target_id:
                metadata_context = _planner_orchestration_execution_context(
                    kind="group_run",
                    target_id=target.target_id,
                )
                group_payload = _planner_orchestration_start_payload(
                    {
                        "group_id": target.target_id,
                        "objective": objective,
                        "title": title or target.target_name or "Group run",
                        "client_run_id": client_run_id or None,
                    },
                    metadata,
                    decision,
                    kind="group_run",
                    target_id=target.target_id,
                    target_name=target.target_name,
                    allowed_tools=allowed_tools,
                    execution_context=metadata_context,
                )
                raw_group_run = self._studio_port.start_group_run(group_payload)
                group_run = group_run_snapshot_from_payload(
                    start_payload_with_planner_decision_events(
                        raw_group_run,
                        decision,
                        event_context=_planner_orchestration_execution_context(
                            kind="group_run",
                            target_id=target.target_id,
                            run_payload=raw_group_run,
                        ),
                    )
                )
                return PlannerOrchestrationStartSnapshot(
                    kind="group_run",
                    status="started",
                    decision=decision,
                    run_id=group_run.group_run_id,
                    group_run_id=group_run.group_run_id,
                    run_group_id=group_run.run_group_id or group_run.group_run_id,
                    target_id=target.target_id,
                    target_name=target.target_name,
                    objective=objective,
                    title=title,
                    route_to_studio=bool(decision.plan.route_to_studio),
                    message="GroupRun started from planner orchestration.",
                    group_run=group_run,
                )
            return _planner_orchestration_handoff_snapshot(
                decision,
                kind="group_run",
                status="target_not_found" if target_name else "handoff",
                target_name=target_name or None,
                objective=objective,
                title=title,
            )

        return PlannerOrchestrationStartSnapshot(
            kind=kind or "",
            status="unsupported",
            decision=decision,
            objective=objective,
            title=title,
            route_to_studio=bool(decision.plan.route_to_studio),
            message="Planner did not select Workflow or GroupRun orchestration.",
        )

    def _planner_workflow_target(
        self,
        *,
        target_id: str,
        target_name: str,
    ) -> "_PlannerOrchestrationTarget":
        if target_id:
            return _PlannerOrchestrationTarget(
                target_id=target_id,
                target_name=target_name or target_id,
            )
        target_key = _planner_lookup_key(target_name)
        if not target_key:
            return _PlannerOrchestrationTarget()
        try:
            workflows = self.list_workflows()
        except Exception:
            return _PlannerOrchestrationTarget(target_name=target_name)
        for workflow in workflows:
            payload = workflow.model_dump(mode="json")
            if _planner_target_matches(
                payload,
                target_key,
                id_keys=("workflow_id", "id"),
                name_keys=("name", "title", "nickname"),
            ):
                return _PlannerOrchestrationTarget(
                    target_id=str(payload.get("workflow_id") or payload.get("id") or "").strip(),
                    target_name=str(payload.get("name") or target_name).strip(),
                )
        return _PlannerOrchestrationTarget(target_name=target_name)

    def _planner_group_target(
        self,
        *,
        target_id: str,
        target_name: str,
    ) -> "_PlannerOrchestrationTarget":
        if target_id:
            return _PlannerOrchestrationTarget(
                target_id=target_id,
                target_name=target_name or target_id,
            )
        target_key = _planner_lookup_key(target_name)
        if not target_key:
            return _PlannerOrchestrationTarget()
        try:
            groups = self.list_groups()
        except Exception:
            return _PlannerOrchestrationTarget(target_name=target_name)
        for group in groups:
            payload = group.model_dump(mode="json")
            if _planner_target_matches(
                payload,
                target_key,
                id_keys=("group_id", "agent_group_id", "id"),
                name_keys=("name", "title", "nickname"),
            ):
                return _PlannerOrchestrationTarget(
                    target_id=str(
                        payload.get("group_id")
                        or payload.get("agent_group_id")
                        or payload.get("id")
                        or ""
                    ).strip(),
                    target_name=str(payload.get("name") or target_name).strip(),
                )
        return _PlannerOrchestrationTarget(target_name=target_name)

    def list_restricted_tool_plugins(self) -> list[RestrictedToolPluginSnapshot]:
        list_plugins = getattr(self._studio_port, "list_restricted_tool_plugins", None)
        if callable(list_plugins):
            return [
                restricted_tool_plugin_snapshot_from_payload(item)
                for item in _payload_items(list_plugins(), "plugins")
            ]
        return self.list_tool_catalog().plugins

    def _catalog_tool_names(self) -> list[str]:
        try:
            catalog = self.list_tool_catalog()
        except Exception:
            return []
        return [
            str(tool.tool_name or "").strip()
            for tool in catalog.tools
            if str(tool.tool_name or "").strip()
        ]

    def install_restricted_tool_plugin(
        self,
        request: InstallRestrictedToolPluginRequest | Mapping[str, Any],
    ) -> RestrictedToolPluginSnapshot:
        install_plugin = getattr(self._studio_port, "install_restricted_tool_plugin", None)
        if not callable(install_plugin):
            raise AgentRuntimeError("Restricted tool plugin install is not available")
        return restricted_tool_plugin_snapshot_from_payload(
            install_plugin(_request_payload(request))
        )

    def update_restricted_tool_plugin(
        self,
        plugin_id: str,
        request: UpdateRestrictedToolPluginRequest | Mapping[str, Any],
    ) -> RestrictedToolPluginSnapshot:
        update_plugin = getattr(self._studio_port, "update_restricted_tool_plugin", None)
        if not callable(update_plugin):
            raise AgentRuntimeError("Restricted tool plugin update is not available")
        return restricted_tool_plugin_snapshot_from_payload(
            update_plugin(plugin_id, _request_payload(request))
        )

    def uninstall_restricted_tool_plugin(self, plugin_id: str) -> RestrictedToolPluginSnapshot:
        uninstall_plugin = getattr(self._studio_port, "uninstall_restricted_tool_plugin", None)
        if not callable(uninstall_plugin):
            raise AgentRuntimeError("Restricted tool plugin uninstall is not available")
        return restricted_tool_plugin_snapshot_from_payload(uninstall_plugin(plugin_id))

    def get_agent(self, agent_id: str) -> AgentDefinitionSnapshot:
        return agent_definition_snapshot_from_payload(self._studio_port.get_agent(agent_id))

    def save_agent(
        self,
        request: SaveAgentRequest | Mapping[str, Any],
    ) -> AgentDefinitionSnapshot:
        return agent_definition_snapshot_from_payload(
            self._studio_port.save_agent(_request_payload(request))
        )

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        return dict(self._studio_port.delete_agent(agent_id))

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        return dict(self._studio_port.test_agent_model(agent_id))

    def get_agent_desk(self, agent_id: str) -> AgentDeskSnapshot:
        return agent_desk_snapshot_from_payload(self._studio_port.get_agent_desk(agent_id))

    def write_agent_desk_note(
        self,
        agent_id: str,
        request: SaveAgentDeskNoteRequest | Mapping[str, Any],
    ) -> AgentDeskSnapshot:
        return agent_desk_snapshot_from_payload(
            self._studio_port.write_agent_desk_note(agent_id, _request_payload(request))
        )

    def write_agent_desk_file(
        self,
        agent_id: str,
        request: SaveAgentDeskFileRequest | Mapping[str, Any],
    ) -> AgentDeskSnapshot:
        return agent_desk_snapshot_from_payload(
            self._studio_port.write_agent_desk_file(agent_id, _request_payload(request))
        )

    def trigger_agent_desk_file_event(
        self,
        agent_id: str,
        request: AgentDeskFileEventRequest | Mapping[str, Any],
    ) -> FutureTaskSnapshot:
        payload = self._studio_port.trigger_agent_desk_file_event(
            agent_id,
            _request_payload(request),
        )
        raw = payload.get("future_task") if isinstance(payload, Mapping) else None
        return future_task_snapshot_from_payload(raw if isinstance(raw, Mapping) else payload)

    def attach_skill(self, agent_id: str, skill_id: str) -> AgentDefinitionSnapshot:
        return agent_definition_snapshot_from_payload(
            self._studio_port.attach_skill(agent_id, skill_id)
        )

    def detach_skill(self, agent_id: str, skill_id: str) -> AgentDefinitionSnapshot:
        return agent_definition_snapshot_from_payload(
            self._studio_port.detach_skill(agent_id, skill_id)
        )

    def list_skills(self) -> list[SkillSnapshot]:
        return [
            skill_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_skills(), "skills")
        ]

    def update_skill(self, skill_id: str, request: Mapping[str, Any]) -> SkillSnapshot:
        return skill_snapshot_from_payload(self._studio_port.update_skill(skill_id, dict(request)))

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        return dict(self._studio_port.delete_skill(skill_id))

    def list_skill_folders(self) -> dict[str, Any]:
        payload = self._studio_port.list_skill_folders()
        folders = [
            skill_folder_snapshot_from_payload(item)
            for item in _payload_items(payload, "folders")
        ]
        uncategorized_payload = payload.get("uncategorized") if isinstance(payload, Mapping) else None
        uncategorized = (
            skill_folder_snapshot_from_payload(uncategorized_payload)
            if isinstance(uncategorized_payload, Mapping)
            else None
        )
        return {
            "folders": folders,
            "uncategorized": uncategorized,
        }

    def create_skill_folder(self, request: Mapping[str, Any]) -> SkillFolderSnapshot:
        return skill_folder_snapshot_from_payload(
            self._studio_port.create_skill_folder(dict(request))
        )

    def update_skill_folder(
        self,
        folder_id: str,
        request: Mapping[str, Any],
    ) -> SkillFolderSnapshot:
        return skill_folder_snapshot_from_payload(
            self._studio_port.update_skill_folder(folder_id, dict(request))
        )

    def delete_skill_folder(
        self,
        folder_id: str,
        delete_skills: bool = False,
    ) -> dict[str, Any]:
        return dict(self._studio_port.delete_skill_folder(folder_id, delete_skills))

    def list_skill_sources(self) -> list[SkillSourceRootSnapshot]:
        return [
            skill_source_root_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_skill_sources(), "roots")
        ]

    def import_skill(self, source_path: str, folder_id: str | None = None) -> SkillSnapshot:
        return skill_snapshot_from_payload(self._studio_port.import_skill(source_path, folder_id))

    def sync_native_skills(self) -> dict[str, Any]:
        return dict(self._studio_port.sync_native_skills())

    def install_skill_command(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        return dict(self._studio_port.install_skill_command(command, folder_id))

    def list_memories(
        self,
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[MemorySnapshot]:
        return [
            memory_snapshot_from_payload(item)
            for item in _payload_items(
                self._studio_port.list_memories(include_deleted, limit),
                "memories",
            )
        ]

    def create_memory(self, request: Mapping[str, Any]) -> MemorySnapshot:
        return memory_snapshot_from_payload(self._studio_port.create_memory(dict(request)))

    def update_memory(self, memory_id: str, request: Mapping[str, Any]) -> MemorySnapshot:
        return memory_snapshot_from_payload(
            self._studio_port.update_memory(memory_id, dict(request))
        )

    def delete_memory(self, memory_id: str, reason: str | None = None) -> dict[str, Any]:
        return dict(self._studio_port.delete_memory(memory_id, reason or ""))

    def list_future_tasks(
        self,
        include_finished: bool = True,
        limit: int = 100,
    ) -> list[FutureTaskSnapshot]:
        return [
            future_task_snapshot_from_payload(item)
            for item in _payload_items(
                self._studio_port.list_future_tasks(include_finished, limit),
                "future_tasks",
            )
        ]

    def cancel_future_task(
        self,
        future_task_id: str,
        reason: str | None = None,
    ) -> FutureTaskSnapshot:
        payload = self._studio_port.cancel_future_task(future_task_id, reason or "")
        raw = payload.get("future_task") if isinstance(payload, Mapping) else None
        return future_task_snapshot_from_payload(raw if isinstance(raw, Mapping) else payload)

    def trigger_due_future_tasks(
        self,
        now_epoch: float | None = None,
        limit: int = 20,
    ) -> list[FutureTaskTriggerResultSnapshot]:
        return [
            future_task_trigger_result_snapshot_from_payload(item)
            for item in _payload_items(
                self._studio_port.trigger_due_future_tasks(now_epoch, limit),
                "triggered",
            )
        ]

    def start_agent_run(
        self,
        request: StartAgentRunRequest | Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        payload = _request_payload(request)
        decision, planner_metadata = self._start_planner_decision_with_metadata(payload)
        start_payload = _planner_enriched_start_payload(
            payload,
            decision,
            allowed_tools=_planner_start_allowed_tools(payload),
            metadata_source="agent_studio_service_start",
            planner_metadata=planner_metadata,
        )
        return run_timeline_snapshot_from_payload(
            start_payload_with_planner_decision_events(
                self._studio_port.start_agent_run(start_payload),
                decision,
                request_payload=start_payload,
            )
        )

    def start_replan_recovery_action(
        self,
        run_id: str,
        request: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        payload = _request_payload(request)
        continuation = self.plan_replan_recovery_action(run_id, payload)
        return self.start_agent_run(_agent_start_payload_from_replan_continuation(continuation))

    def plan_replan_recovery_action(
        self,
        run_id: str,
        request: Mapping[str, Any],
    ) -> ReplanContinuationSnapshot:
        payload = _request_payload(request)
        source_run = self.get_run_timeline(run_id)
        return self._plan_replan_recovery_action_from_snapshot(source_run, payload)

    def start_next_replan_continuation(
        self,
        run_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> RunTimelineSnapshot | None:
        payload = _request_payload(request or {})
        payload["auto_start_only"] = True
        continuation = self.plan_next_replan_continuation(run_id, payload)
        if continuation is None:
            return None
        return self.start_agent_run(_agent_start_payload_from_replan_continuation(continuation))

    def plan_next_replan_continuation(
        self,
        run_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> ReplanContinuationSnapshot | None:
        payload = _request_payload(request or {})
        source_run = self.get_run_timeline(run_id)
        return _next_replan_recovery_action_continuation(
            source_run,
            payload,
            source="agent_studio_replan_auto_continuation",
            client_run_id=str(payload.get("client_run_id") or "").strip(),
            auto_start_only=not _payload_allows_manual_replan_continuation(payload),
        )

    def _start_replan_recovery_action_from_snapshot(
        self,
        source_run: Any,
        payload: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        continuation = self._plan_replan_recovery_action_from_snapshot(source_run, payload)
        return self.start_agent_run(_agent_start_payload_from_replan_continuation(continuation))

    def _plan_replan_recovery_action_from_snapshot(
        self,
        source_run: Any,
        payload: Mapping[str, Any],
    ) -> ReplanContinuationSnapshot:
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            raise AgentRuntimeError("Replan recovery request_id is required")
        recovery, action = _find_replan_recovery_action(
            getattr(source_run, "replan_recoveries", []),
            request_id=request_id,
            action_id=str(payload.get("action_id") or "").strip(),
        )
        agent_id = _replan_recovery_action_agent_id(payload, source_run, recovery)
        if not agent_id:
            raise AgentRuntimeError("Replan recovery action requires an agent_id")

        objective = _replan_recovery_action_objective(action)
        task_context = _replan_recovery_task_context(source_run, recovery, action)
        return _replan_recovery_action_continuation(
            source_run,
            recovery,
            action,
            task_context=task_context,
            continue_to_model=bool(payload.get("continue_to_model", True)),
            source="agent_studio_replan_recovery",
            title=str(payload.get("title") or action.label or objective).strip(),
            agent_id=agent_id,
            client_run_id=str(payload.get("client_run_id") or "").strip(),
            extra_metadata=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
        )

    def start_tool_recovery_action(
        self,
        run_id: str,
        request: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        payload = _request_payload(request)
        source_run = self.get_run_timeline(run_id)
        return self._start_tool_recovery_action_from_snapshot(source_run, payload)

    def _start_tool_recovery_action_from_snapshot(
        self,
        source_run: Any,
        payload: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        tool_call_id = str(payload.get("tool_call_id") or "").strip()
        if not tool_call_id:
            raise AgentRuntimeError("Tool recovery tool_call_id is required")
        action_id = str(payload.get("action_id") or "").strip()
        if not action_id:
            raise AgentRuntimeError("Tool recovery action_id is required")
        tool_call = _find_tool_recovery_tool_call(source_run, tool_call_id)
        action = _find_tool_call_recovery_action(tool_call, action_id)
        action_kind = str(payload.get("action_kind") or action.get("action_kind") or "").strip()
        agent_id = _tool_recovery_action_agent_id(payload, source_run, tool_call)
        if not agent_id:
            raise AgentRuntimeError("Tool recovery action requires an agent_id")
        direct_request = _tool_recovery_action_direct_request(
            tool_call,
            action,
            action_kind=action_kind,
            input_override=payload.get("input_override"),
            continue_to_model=bool(payload.get("continue_to_model", True)),
        )
        objective = _tool_recovery_action_objective(action, direct_request)
        start_payload: dict[str, Any] = {
            "agent_id": agent_id,
            "objective": objective,
            "title": str(payload.get("title") or objective).strip(),
            "client_run_id": str(payload.get("client_run_id") or "").strip() or None,
            "metadata": _tool_recovery_action_metadata(
                source_run,
                tool_call,
                action,
                direct_request,
                action_kind=action_kind,
                extra=payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
            ),
            "direct_tool_requests": [direct_request],
            "daily_desktop_planning_context": objective,
        }
        return self.start_agent_run(start_payload)

    def list_groups(self) -> list[AgentGroupSnapshot]:
        return [
            agent_group_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_groups(), "groups")
        ]

    def get_group(self, group_id: str) -> AgentGroupSnapshot:
        return agent_group_snapshot_from_payload(self._studio_port.get_group(group_id))

    def save_group(
        self,
        request: SaveAgentGroupRequest | Mapping[str, Any],
    ) -> AgentGroupSnapshot:
        return agent_group_snapshot_from_payload(
            self._studio_port.save_group(_request_payload(request))
        )

    def start_group_run(
        self,
        request: StartGroupRunRequest | Mapping[str, Any],
    ) -> GroupRunSnapshot:
        payload = _request_payload(request)
        decision, planner_metadata = self._start_planner_decision_with_metadata(payload)
        start_payload = _planner_enriched_start_payload(
            payload,
            decision,
            allowed_tools=_planner_start_allowed_tools(payload),
            metadata_source="agent_studio_service_start",
            execution_context=_planner_orchestration_execution_context(
                kind="group_run",
                target_id=str(payload.get("group_id") or "").strip(),
            ),
            planner_metadata=planner_metadata,
        )
        raw_group_run = self._studio_port.start_group_run(start_payload)
        event_context = _planner_orchestration_execution_context(
            kind="group_run",
            target_id=str(start_payload.get("group_id") or "").strip(),
            run_payload=raw_group_run,
        )
        return group_run_snapshot_from_payload(
            start_payload_with_planner_decision_events(
                raw_group_run,
                decision,
                event_context=event_context,
                request_payload=start_payload,
            )
        )

    def list_group_runs(self, limit: int = 50) -> list[GroupRunSnapshot]:
        return [
            group_run_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_group_runs(limit), "group_runs")
        ]

    def get_group_run(self, group_run_id: str) -> GroupRunSnapshot:
        return group_run_snapshot_from_payload(self._studio_port.get_group_run(group_run_id))

    def start_group_replan_recovery_action(
        self,
        group_run_id: str,
        request: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        payload = _request_payload(request)
        source_run = self.get_group_run(group_run_id)
        return self._start_replan_recovery_action_from_snapshot(source_run, payload)

    def start_next_group_replan_continuation(
        self,
        group_run_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> RunTimelineSnapshot | None:
        payload = _request_payload(request or {})
        payload["auto_start_only"] = True
        continuation = self.plan_next_group_replan_continuation(group_run_id, payload)
        if continuation is None:
            return None
        return self.start_agent_run(_agent_start_payload_from_replan_continuation(continuation))

    def plan_next_group_replan_continuation(
        self,
        group_run_id: str,
        request: Mapping[str, Any] | None = None,
    ) -> ReplanContinuationSnapshot | None:
        payload = _request_payload(request or {})
        source_run = self.get_group_run(group_run_id)
        return _next_replan_recovery_action_continuation(
            source_run,
            payload,
            source="agent_studio_group_replan_auto_continuation",
            client_run_id=str(payload.get("client_run_id") or "").strip(),
            auto_start_only=not _payload_allows_manual_replan_continuation(payload),
        )

    def start_group_tool_recovery_action(
        self,
        group_run_id: str,
        request: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        payload = _request_payload(request)
        source_run = self.get_group_run(group_run_id)
        return self._start_tool_recovery_action_from_snapshot(source_run, payload)

    def get_group_run_event_stream(self, group_run_id: str) -> Iterable[PublicRunEvent]:
        port_event_stream = getattr(self._studio_port, "get_group_run_event_stream", None)
        if callable(port_event_stream):
            raw_events = port_event_stream(group_run_id)
            yield from _group_run_events_from_port_payload(
                raw_events,
                group_run_id=group_run_id,
            )
            return

        group_run = self.get_group_run(group_run_id)
        if group_run.events:
            yield from group_run.events
            return
        for run in group_run.runs:
            yield from run.events

    def get_group_run_event_page(
        self,
        group_run_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> RunEventPageSnapshot:
        clean_after_sequence = max(0, int(after_sequence or 0))
        clean_limit = max(1, min(500, int(limit or 200)))
        port_event_page = getattr(self._studio_port, "get_group_run_event_page", None)
        if callable(port_event_page):
            raw_page = port_event_page(
                group_run_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            page = public_run_event_page_from_payload(
                raw_page,
                run_id=group_run_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            events = _group_run_events_from_port_payload(
                raw_page,
                group_run_id=group_run_id,
            )
            if clean_after_sequence == 0 and page.has_more:
                events = events_with_first_page_key_event_window(
                    events,
                    list(self.get_group_run_event_stream(group_run_id)),
                    page=page,
                    event_types=FIRST_PAGE_GROUP_RUN_KEY_EVENT_TYPES,
                )
            return run_event_page_with_projected_events(
                page,
                events,
            )

        events = [
            event
            for event in self.get_group_run_event_stream(group_run_id)
            if int(event.sequence or 0) > clean_after_sequence
        ]
        page_events = events[:clean_limit]
        next_after_sequence = max(
            [int(event.sequence or 0) for event in page_events] or [clean_after_sequence]
        )
        page = RunEventPageSnapshot(
            run_id=group_run_id,
            after_sequence=clean_after_sequence,
            limit=clean_limit,
            next_after_sequence=next_after_sequence,
            has_more=len(events) > clean_limit,
            events=page_events,
        )
        if clean_after_sequence == 0 and page.has_more:
            page_events = events_with_first_page_key_event_window(
                page_events,
                events,
                page=page,
                event_types=FIRST_PAGE_GROUP_RUN_KEY_EVENT_TYPES,
            )
        return run_event_page_with_projected_events(page, page_events)

    def list_workflows(self) -> list[WorkflowSnapshot]:
        return [
            workflow_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_workflows(), "workflows")
        ]

    def get_workflow(self, workflow_id: str) -> WorkflowSnapshot:
        return workflow_snapshot_from_payload(self._studio_port.get_workflow(workflow_id))

    def save_workflow(
        self,
        request: SaveWorkflowRequest | Mapping[str, Any],
    ) -> WorkflowSnapshot:
        return workflow_snapshot_from_payload(
            self._studio_port.save_workflow(_request_payload(request))
        )

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return dict(self._studio_port.delete_workflow(workflow_id))

    def start_workflow_run(
        self,
        request: StartWorkflowRunRequest | Mapping[str, Any],
    ) -> WorkflowRunSnapshot:
        payload = _request_payload(request)
        decision, planner_metadata = self._start_planner_decision_with_metadata(payload)
        start_payload = _planner_enriched_start_payload(
            payload,
            decision,
            allowed_tools=_planner_start_allowed_tools(payload),
            metadata_source="agent_studio_service_start",
            execution_context=_planner_orchestration_execution_context(
                kind="workflow",
                target_id=str(payload.get("workflow_id") or "").strip(),
            ),
            planner_metadata=planner_metadata,
        )
        raw_workflow_run = self._studio_port.start_workflow_run(start_payload)
        event_context = _planner_orchestration_execution_context(
            kind="workflow",
            target_id=str(start_payload.get("workflow_id") or "").strip(),
            run_payload=raw_workflow_run,
        )
        return workflow_run_snapshot_from_payload(
            start_payload_with_planner_decision_events(
                raw_workflow_run,
                decision,
                event_context=event_context,
                request_payload=start_payload,
            )
        )

    def _start_payload_with_planner_events(
        self,
        raw_payload: Mapping[str, Any],
        request_payload: Mapping[str, Any],
        *,
        event_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return start_payload_with_planner_events(
            raw_payload,
            request_payload,
            plan_task=self.plan_task,
            metadata_source="agent_studio_service_start",
            event_context=event_context,
        )

    def _start_planner_decision(
        self,
        payload: Mapping[str, Any],
    ) -> PlannerDecisionSnapshot | None:
        decision, _metadata = self._start_planner_decision_with_metadata(payload)
        return decision

    def _start_planner_decision_with_metadata(
        self,
        payload: Mapping[str, Any],
    ) -> tuple[PlannerDecisionSnapshot | None, dict[str, Any]]:
        metadata = _planner_start_metadata(
            payload,
            source="agent_studio_service_start",
        )
        prompt = _planner_start_prompt(payload)
        if not prompt:
            return None, metadata
        allowed_tools = _planner_start_allowed_tools(payload)
        try:
            port_planner = getattr(self._studio_port, "plan_task", None)
            if callable(port_planner):
                planner_payload = port_planner(
                    prompt,
                    allowed_tools=allowed_tools,
                    metadata=metadata,
                )
                if planner_payload is not None:
                    return PlannerDecisionSnapshot.model_validate(
                        planner_payload
                    ), metadata
            catalog = self.list_tool_catalog()
            enriched_metadata = _planner_metadata_with_catalog_readiness(
                metadata,
                catalog,
            )
            return _runtime_planner_decision_for_studio(
                prompt,
                metadata=enriched_metadata,
                catalog=catalog,
                allowed_tools=allowed_tools,
            )
        except Exception:
            return None, metadata

    def list_run_timelines(self, limit: int = 50) -> list[RunTimelineSnapshot]:
        return [
            _public_run_snapshot_from_payload(item)
            for item in _payload_items(self._studio_port.list_run_timelines(limit), "runs")
        ]

    def get_run_timeline(self, run_id: str) -> RunTimelineSnapshot | WorkflowRunSnapshot:
        return _public_run_snapshot_from_payload(self._studio_port.get_run_timeline(run_id))

    def rerun_run(
        self,
        run_id: str,
        request: RerunRunRequest | Mapping[str, Any] | None = None,
    ) -> RunTimelineSnapshot | WorkflowRunSnapshot:
        return _public_run_snapshot_from_payload(
            self._studio_port.rerun_run(run_id, _request_payload(request))
        )

    def cancel_run(self, run_id: str) -> RunTimelineSnapshot | WorkflowRunSnapshot:
        return _public_run_snapshot_from_payload(self._studio_port.cancel_run(run_id))

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return dict(self._studio_port.delete_run(run_id))

    def approve_run_approval(
        self,
        run_id: str,
        decision: ApprovalDecision | Mapping[str, Any] | None = None,
    ) -> RunTimelineSnapshot | WorkflowRunSnapshot:
        return _public_run_snapshot_from_payload(
            self._studio_port.approve_run_approval(run_id, _approval_payload(decision))
        )

    def reject_run_approval(
        self,
        run_id: str,
        decision: ApprovalDecision | Mapping[str, Any] | str | None = None,
    ) -> RunTimelineSnapshot | WorkflowRunSnapshot:
        return _public_run_snapshot_from_payload(
            self._studio_port.reject_run_approval(run_id, _rejection_payload(decision))
        )

    def read_run_artifact(self, run_id: str, artifact_path: str) -> ArtifactContentSnapshot:
        return artifact_content_snapshot_from_payload(
            self._studio_port.read_run_artifact(run_id, artifact_path),
            run_id=run_id,
            path=artifact_path,
        )

    def get_run_event_stream(self, run_id: str) -> Iterable[PublicRunEvent]:
        raw_events = self._studio_port.get_run_event_stream(run_id)
        yield from _run_events_from_port_payload(raw_events, run_id=run_id)

    def get_run_event_page(
        self,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> RunEventPageSnapshot:
        clean_after_sequence = max(0, int(after_sequence or 0))
        clean_limit = max(1, min(500, int(limit or 200)))
        port_event_page = getattr(self._studio_port, "get_run_event_page", None)
        if callable(port_event_page):
            raw_page = port_event_page(
                run_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            page = public_run_event_page_from_payload(
                raw_page,
                run_id=run_id,
                after_sequence=clean_after_sequence,
                limit=clean_limit,
            )
            raw_events = _payload_items(raw_page, "events")
            events = _run_events_from_port_payload(raw_page, run_id=run_id)
            port_event_stream = getattr(self._studio_port, "get_run_event_stream", None)
            if clean_after_sequence == 0 and page.has_more and callable(port_event_stream):
                events = events_with_first_page_key_event_window(
                    events,
                    list(self.get_run_event_stream(run_id)),
                    page=page,
                    event_types=_run_first_page_key_event_types(raw_page, raw_events),
                )
            return run_event_page_with_projected_events(
                page,
                events,
            )

        filtered_events = [
            event
            for event in self.get_run_event_stream(run_id)
            if int(event.sequence or 0) > clean_after_sequence
        ]
        page_events = filtered_events[:clean_limit]
        next_after_sequence = max(
            [int(event.sequence or 0) for event in page_events] or [clean_after_sequence]
        )
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
                filtered_events,
                page=page,
                event_types=FIRST_PAGE_RUN_OR_WORKFLOW_KEY_EVENT_TYPES,
            )
        return run_event_page_with_projected_events(page, page_events)


@dataclass(frozen=True)
class _PlannerOrchestrationTarget:
    target_id: str = ""
    target_name: str = ""


def _string_list(value: Any, *, fallback: list[str]) -> list[str]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        values = [str(item or "").strip() for item in value if str(item or "").strip()]
        if values:
            return values
    return list(fallback)


def _planner_orchestration_kind(decision: PlannerDecisionSnapshot) -> str:
    intent_kind = str(decision.selected_intent.kind or "").strip()
    if intent_kind == "workflow_orchestration":
        return "workflow"
    if intent_kind == "multi_agent":
        return "group_run"
    return ""


def _planner_intent_input(decision: PlannerDecisionSnapshot, key: str) -> str:
    inputs = decision.selected_intent.inputs
    if not isinstance(inputs, Mapping):
        return ""
    return str(inputs.get(key) or "").strip()


def _planner_orchestration_run_metadata(
    metadata: Mapping[str, Any],
    decision: PlannerDecisionSnapshot,
    *,
    kind: str,
    target_id: str,
    target_name: str,
    allowed_tools: Iterable[str] | None = None,
    execution_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        **dict(metadata),
        **runtime_planner_metadata(
            decision,
            allowed_tools=allowed_tools,
            metadata=metadata,
        ),
    }
    payload = with_agent_studio_desktop_execution_policy(payload)
    envelope = _runtime_execution_envelope_payload_for_start(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
        metadata=payload,
    ) or payload.get("yachiyo_execution_envelope")
    if isinstance(envelope, Mapping):
        payload["yachiyo_execution_envelope"] = _studio_runtime_execution_envelope_for_start(
            runtime_execution_envelope_payload_with_request_context(
                envelope,
                execution_context,
            ),
            payload,
        )
    payload.setdefault("source", "agent_studio_planner_orchestration")
    payload.update(
        {
            "planner_orchestration": True,
            "planner_orchestration_kind": kind,
            "planner_orchestration_target_id": target_id,
            "planner_orchestration_target": target_name,
            "decision_id": decision.decision_id,
            "plan_id": decision.plan.plan_id,
            "intent_kind": str(decision.selected_intent.kind or ""),
            "route_to_studio": bool(decision.plan.route_to_studio),
        }
    )
    return payload


def _planner_orchestration_start_payload(
    base_payload: Mapping[str, Any],
    metadata: Mapping[str, Any],
    decision: PlannerDecisionSnapshot,
    *,
    kind: str,
    target_id: str,
    target_name: str,
    allowed_tools: Iterable[str] | None = None,
    execution_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(base_payload)
    enriched_metadata = _planner_orchestration_run_metadata(
        metadata,
        decision,
        kind=kind,
        target_id=target_id,
        target_name=target_name,
        allowed_tools=allowed_tools,
        execution_context=execution_context,
    )
    payload["metadata"] = enriched_metadata
    envelope = enriched_metadata.get("yachiyo_execution_envelope")
    if isinstance(envelope, Mapping):
        payload.setdefault("runtime_execution_envelope", dict(envelope))
        if "direct_tool_requests" not in payload:
            direct_tool_requests = runtime_execution_requests_from_envelope_payload(
                envelope,
                allowed_tools=allowed_tools,
            )
            if direct_tool_requests:
                payload["direct_tool_requests"] = direct_tool_requests
    return payload


def _planner_orchestration_execution_context(
    *,
    kind: str,
    target_id: str,
    run_payload: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    payload = run_payload if isinstance(run_payload, Mapping) else {}
    if kind == "workflow":
        context = {"workflow_id": str(target_id or "").strip()}
        workflow_run_id = str(
            payload.get("workflow_run_id") or payload.get("run_id") or ""
        ).strip()
        if workflow_run_id:
            context["workflow_run_id"] = workflow_run_id
        workflow_node_id = str(
            payload.get("workflow_node_id") or payload.get("current_node_id") or ""
        ).strip()
        if workflow_node_id:
            context["workflow_node_id"] = workflow_node_id
        workflow_node_label = str(
            payload.get("workflow_node_label") or payload.get("current_node_label") or ""
        ).strip()
        if workflow_node_label:
            context["workflow_node_label"] = workflow_node_label
        workflow_node_kind = str(payload.get("workflow_node_kind") or "").strip()
        if workflow_node_kind:
            context["workflow_node_kind"] = workflow_node_kind
        return {key: value for key, value in context.items() if value}

    if kind == "group_run":
        context = {"group_id": str(target_id or "").strip()}
        group_run_id = str(
            payload.get("group_run_id")
            or payload.get("run_group_id")
            or payload.get("run_id")
            or ""
        ).strip()
        if group_run_id:
            context["group_run_id"] = group_run_id
            context["run_group_id"] = str(
                payload.get("run_group_id") or group_run_id
            ).strip()
        return {key: value for key, value in context.items() if value}

    return {}


def _planner_orchestration_handoff_snapshot(
    decision: PlannerDecisionSnapshot,
    *,
    kind: str,
    status: str,
    target_name: str | None,
    objective: str,
    title: str,
) -> PlannerOrchestrationStartSnapshot:
    if kind == "workflow":
        message = (
            f"Workflow target not found: {target_name}"
            if target_name
            else "Planner selected Workflow orchestration but no Workflow target was provided."
        )
    else:
        message = (
            f"Group target not found: {target_name}"
            if target_name
            else "Planner selected GroupRun orchestration but no Agent Group target was provided."
        )
    return PlannerOrchestrationStartSnapshot(
        kind=kind,
        status=status,
        decision=decision,
        target_name=target_name,
        objective=objective,
        title=title,
        route_to_studio=bool(decision.plan.route_to_studio),
        message=message,
    )


def _planner_lookup_key(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _planner_target_matches(
    payload: Mapping[str, Any],
    target_key: str,
    *,
    id_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
) -> bool:
    return any(
        _planner_lookup_key(payload.get(key)) == target_key
        for key in (*id_keys, *name_keys)
    )


def _request_payload(request: Any) -> dict[str, Any]:
    if request is None:
        return {}
    if hasattr(request, "model_dump"):
        return request.model_dump(exclude_none=True, by_alias=True)
    return dict(request)


def _planner_start_prompt(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("prompt")
        or payload.get("objective")
        or payload.get("goal")
        or payload.get("title")
        or ""
    ).strip()


def _planner_start_allowed_tools(payload: Mapping[str, Any]) -> list[str] | None:
    values = _string_list(payload.get("allowed_tools"), fallback=[])
    return values or None


def _planner_start_metadata(
    payload: Mapping[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    metadata = (
        dict(payload.get("metadata"))
        if isinstance(payload.get("metadata"), Mapping)
        else {}
    )
    metadata = with_agent_studio_desktop_execution_policy(metadata)
    metadata.setdefault("source", source)
    metadata["runtime_planner_entrypoint"] = True
    return metadata


def _planner_enriched_start_payload(
    payload: Mapping[str, Any],
    decision: PlannerDecisionSnapshot | None,
    *,
    allowed_tools: Iterable[str] | None,
    metadata_source: str,
    execution_context: Mapping[str, Any] | None = None,
    planner_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    start_payload = dict(payload)
    if decision is None:
        start_payload["metadata"] = (
            dict(planner_metadata)
            if isinstance(planner_metadata, Mapping)
            else _planner_start_metadata(
                start_payload,
                source=metadata_source,
            )
        )
        return start_payload
    metadata = (
        dict(planner_metadata)
        if isinstance(planner_metadata, Mapping)
        else _planner_start_metadata(start_payload, source=metadata_source)
    )
    metadata.update(
        runtime_planner_metadata(
            decision,
            allowed_tools=allowed_tools,
            metadata=metadata,
        )
    )
    full_plan_envelope = _runtime_execution_envelope_payload_for_start(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
        metadata=metadata,
    )
    envelope = full_plan_envelope or metadata.get("yachiyo_execution_envelope")
    if isinstance(envelope, Mapping):
        enriched_envelope = runtime_execution_envelope_payload_with_request_context(
            envelope,
            execution_context,
        )
        enriched_envelope = _studio_runtime_execution_envelope_for_start(
            enriched_envelope,
            metadata,
        )
        _apply_start_execution_envelope_metadata(metadata, enriched_envelope)
        start_payload.setdefault(
            "runtime_execution_envelope",
            dict(enriched_envelope),
        )
        if "direct_tool_requests" not in start_payload:
            direct_tool_requests = runtime_execution_requests_from_envelope_payload(
                enriched_envelope,
                allowed_tools=allowed_tools,
            )
            if direct_tool_requests:
                start_payload["direct_tool_requests"] = direct_tool_requests
    start_payload["metadata"] = metadata
    return start_payload


def _apply_start_execution_envelope_metadata(
    metadata: dict[str, Any],
    envelope: Mapping[str, Any],
) -> None:
    metadata["yachiyo_execution_envelope"] = dict(envelope)
    requests = [
        request
        for request in envelope.get("requests", [])
        if isinstance(request, Mapping)
    ]
    metadata["yachiyo_execution_requests"] = [
        request.get("tool_name")
        for request in requests
        if request.get("tool_name")
    ]
    previews = _start_execution_request_previews(requests)
    if previews:
        metadata["yachiyo_execution_request_previews"] = previews
    task_core = _start_execution_task_core(envelope)
    if task_core is not None:
        metadata["yachiyo_task_core"] = task_core.model_dump(mode="json")
        task_progress = task_progress_summary_from_task_core(task_core)
        if task_progress is not None:
            metadata["yachiyo_task_progress"] = task_progress.model_dump(mode="json")


def _start_execution_task_core(envelope: Mapping[str, Any]) -> TaskCoreSnapshot | None:
    task_core = envelope.get("task_core")
    if not isinstance(task_core, Mapping):
        return None
    try:
        return TaskCoreSnapshot.model_validate(task_core)
    except ValueError:
        return None


def _start_execution_request_previews(
    requests: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for request in requests:
        tool_name = str(request.get("tool_name") or request.get("tool") or "").strip()
        if not tool_name:
            continue
        preview: dict[str, Any] = {"tool_name": tool_name}
        for key in (
            "request_id",
            "step_id",
            "capability_id",
            "runtime_stage",
            "runtime_role",
            "status",
            "planning_reason",
            "source",
        ):
            value = request.get(key)
            if value not in (None, "", [], {}):
                preview[key] = value
        request_input = request.get("input")
        if isinstance(request_input, Mapping) and request_input:
            preview["input"] = dict(request_input)
        for key in (
            "approval_required",
            "continue_to_model",
            "requires_observation",
            "requires_post_action_verification",
        ):
            if bool(request.get(key)):
                preview[key] = True
        for key in ("depends_on", "fallback_tools", "replan_signal_ids", "replan_triggers"):
            value = request.get(key)
            if isinstance(value, list) and value:
                preview[key] = list(value)
        previews.append(preview)
    return previews


def _find_replan_recovery_action(
    recoveries: Iterable[ReplanRecoverySnapshot],
    *,
    request_id: str,
    action_id: str,
) -> tuple[ReplanRecoverySnapshot, ReplanRecoveryActionSnapshot]:
    for recovery in recoveries:
        if str(recovery.request_id or "").strip() != request_id:
            continue
        actions = [
            action
            for action in recovery.recovery_actions
            if str(action.tool or "").strip()
        ]
        if not actions:
            raise AgentRuntimeError("Replan recovery has no executable actions")
        if action_id:
            for action in actions:
                if str(action.action_id or "").strip() == action_id:
                    return recovery, action
            raise AgentRuntimeError("Replan recovery action_id was not found")
        if len(actions) == 1:
            return recovery, actions[0]
        raise AgentRuntimeError("Replan recovery action_id is required")
    raise AgentRuntimeError("Replan recovery request_id was not found")


def _replan_recovery_action_objective(action: ReplanRecoveryActionSnapshot) -> str:
    label = str(action.label or "").strip()
    tool = str(action.tool or "").strip()
    if label and label != tool:
        return f"执行恢复动作：{label}"
    return f"执行恢复动作：{tool}"


_AUTO_CONTINUATION_SAFE_TOOLS = {
    "app.focus",
    "app.open",
    "browser.current_page",
    "browser.screenshot",
    "desktop.active_window",
    "desktop.focus_app",
    "desktop.list_apps",
    "desktop.open_app",
    "desktop.read_ui",
    "desktop.running_apps",
    "desktop.ui_elements",
    "file.read",
    "fs.read_file",
    "screen.capture",
    "workspace.read",
}


_AUTO_CONTINUATION_APPROVAL_TOOLS = {
    "app.focus_and_click_ui_element",
    "app.focus_and_type_into_ui_element",
    "app.open_and_click_ui_element",
    "app.open_and_type_into_ui_element",
    "desktop.click",
    "desktop.click_ui_element",
    "desktop.safe_click",
    "desktop.safe_type_text",
    "desktop.type",
    "desktop.type_into_ui_element",
    "desktop.type_text",
    "python.run",
    "terminal.run",
}


def _next_replan_recovery_action_continuation(
    source_run: Any,
    payload: Mapping[str, Any],
    *,
    source: str,
    conversation_id: str = "",
    client_run_id: str = "",
    auto_start_only: bool = True,
) -> ReplanContinuationSnapshot | None:
    request_id_filter = str(payload.get("request_id") or "").strip()
    action_id_filter = str(payload.get("action_id") or "").strip()
    for recovery in reversed(list(getattr(source_run, "replan_recoveries", []) or [])):
        if request_id_filter and str(recovery.request_id or "").strip() != request_id_filter:
            continue
        if _replan_recovery_is_resolved(recovery):
            continue
        for action in _ordered_replan_recovery_actions(recovery):
            if action_id_filter and str(action.action_id or "").strip() != action_id_filter:
                continue
            task_context = _replan_recovery_task_context(source_run, recovery, action)
            agent_id = ""
            if source.startswith("agent_studio"):
                agent_id = _replan_recovery_action_agent_id(payload, source_run, recovery)
                if not agent_id:
                    continue
            continuation = _replan_recovery_action_continuation(
                source_run,
                recovery,
                action,
                task_context=task_context,
                continue_to_model=bool(payload.get("continue_to_model", True)),
                source=source,
                title=str(payload.get("title") or action.label or "").strip(),
                agent_id=agent_id,
                conversation_id=conversation_id,
                client_run_id=client_run_id,
                extra_metadata=payload.get("metadata")
                if isinstance(payload.get("metadata"), Mapping)
                else {},
            )
            if continuation.auto_start_eligible or not auto_start_only:
                return continuation
    return None


def _payload_allows_manual_replan_continuation(payload: Mapping[str, Any]) -> bool:
    if _payload_truthy(payload.get("auto_start_only")):
        return False
    return any(
        _payload_truthy(payload.get(key))
        for key in (
            "include_manual",
            "allow_manual",
            "manual_continuation",
            "return_manual",
        )
    )


def _payload_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _ordered_replan_recovery_actions(
    recovery: ReplanRecoverySnapshot,
) -> list[ReplanRecoveryActionSnapshot]:
    actions = list(recovery.recovery_actions or [])
    return [
        *[action for action in actions if action.selected],
        *[action for action in actions if not action.selected],
    ]


def _replan_recovery_is_resolved(recovery: ReplanRecoverySnapshot) -> bool:
    status = str(recovery.status or "").strip().lower()
    return status in {"completed", "resolved", "cancelled", "canceled"}


def _replan_recovery_action_continuation(
    source_run: Any,
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
    *,
    task_context: Mapping[str, Any],
    continue_to_model: bool,
    source: str,
    title: str = "",
    agent_id: str = "",
    conversation_id: str = "",
    client_run_id: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> ReplanContinuationSnapshot:
    objective = _replan_recovery_action_objective(action)
    continuation_id = "replan-continuation:{}:{}".format(
        str(recovery.request_id or "").strip(),
        str(action.action_id or action.tool or "").strip(),
    )
    direct_request = _replan_recovery_action_direct_request(
        recovery,
        action,
        task_context=task_context,
        continue_to_model=continue_to_model,
        source=source,
    )
    metadata = _replan_recovery_action_metadata(
        source_run,
        recovery,
        action,
        task_context=task_context,
        extra=extra_metadata or {},
        source=source,
    )
    risk_level = str(action.risk_level or recovery.risk_level or "").strip()
    auto_start = _replan_continuation_auto_start_context(
        action,
        direct_request=direct_request,
        risk_level=risk_level,
    )
    approval_required = bool(auto_start["approval_required"])
    auto_start_eligible = not auto_start["blockers"]
    metadata["replan_continuation_id"] = continuation_id
    metadata["replan_auto_start_eligible"] = auto_start_eligible
    metadata["replan_auto_start_reason"] = auto_start["reason"]
    if auto_start["blockers"]:
        metadata["replan_auto_start_blockers"] = auto_start["blockers"]
    return ReplanContinuationSnapshot(
        continuation_id=continuation_id,
        request_id=str(recovery.request_id or ""),
        action_id=str(action.action_id or "").strip() or None,
        tool_name=str(action.tool or "").strip(),
        prompt=objective,
        title=str(title or action.label or objective).strip(),
        source_run_id=_replan_recovery_source_id(source_run) or None,
        source_task_id=_first_text(getattr(source_run, "task_id", ""), recovery.task_id) or None,
        source_group_run_id=_first_text(
            getattr(source_run, "group_run_id", ""),
            getattr(source_run, "run_group_id", ""),
            recovery.group_run_id,
        ) or None,
        source_workflow_run_id=_first_text(
            getattr(source_run, "workflow_run_id", ""),
            recovery.workflow_run_id,
        ) or None,
        agent_id=str(agent_id or "").strip() or None,
        conversation_id=str(conversation_id or "").strip() or None,
        client_run_id=str(client_run_id or "").strip() or None,
        direct_tool_requests=[direct_request],
        metadata=metadata,
        task_context=dict(task_context),
        daily_desktop_planning_context=objective,
        approval_required=approval_required,
        auto_start_eligible=auto_start_eligible,
        auto_start_reason=str(auto_start["reason"]),
        auto_start_blockers=list(auto_start["blockers"]),
        risk_level=risk_level,
        source=str(source or "replan_continuation").strip(),
    )


def _replan_continuation_auto_start_context(
    action: ReplanRecoveryActionSnapshot,
    *,
    direct_request: Mapping[str, Any],
    risk_level: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    tool_name = str(action.tool or direct_request.get("tool") or "").strip()
    approval_required = bool(
        action.approval_required
        or direct_request.get("approval_required")
        or _replan_continuation_deferred_approval_required(direct_request)
        or str(action.approval_status or "").strip().lower() in {
            "pending",
            "required",
            "approval_required",
            "waiting_approval",
        }
    )
    clean_risk = str(risk_level or "").strip().lower()
    if not tool_name:
        blockers.append("missing_tool")
    if approval_required:
        blockers.append("approval_required")
    if clean_risk in {"high", "critical"}:
        blockers.append("high_risk")
    if tool_name and tool_name not in _AUTO_CONTINUATION_SAFE_TOOLS:
        blockers.append("tool_not_auto_safe")
    for key, deferred_tool_name in _replan_continuation_deferred_tool_names(
        direct_request
    ):
        if deferred_tool_name in _AUTO_CONTINUATION_SAFE_TOOLS:
            continue
        blocker = (
            "deferred_tool_not_auto_safe"
            if key == "deferred_tool"
            else "deferred_continuation_tool_not_auto_safe"
        )
        if blocker not in blockers:
            blockers.append(blocker)
    return {
        "approval_required": approval_required,
        "blockers": blockers,
        "reason": (
            "safe_low_risk_replan_continuation"
            if not blockers
            else "manual_replan_continuation_required"
        ),
    }


def _replan_continuation_deferred_approval_required(
    direct_request: Mapping[str, Any],
) -> bool:
    for _key, tool_name in _replan_continuation_deferred_tool_names(direct_request):
        if tool_name in _AUTO_CONTINUATION_APPROVAL_TOOLS:
            return True
    for item in _replan_continuation_deferred_items(direct_request):
        if bool(item.get("approval_required")):
            return True
        if _first_text(item.get("risk_level")).lower() in {"high", "critical"}:
            return True
    return False


def _replan_continuation_deferred_tool_names(
    direct_request: Mapping[str, Any],
) -> list[tuple[str, str]]:
    tools: list[tuple[str, str]] = []
    deferred_tool = _first_text(direct_request.get("deferred_tool"))
    if deferred_tool:
        tools.append(("deferred_tool", deferred_tool))
    for item in _replan_continuation_deferred_items(direct_request):
        tool_name = _first_text(item.get("tool"), item.get("tool_name"))
        if tool_name:
            tools.append(("deferred_continuation_tool", tool_name))
    return tools


def _replan_continuation_deferred_items(
    direct_request: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return _mapping_list(direct_request.get("deferred_continuation"))


def _agent_start_payload_from_replan_continuation(
    continuation: ReplanContinuationSnapshot,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "agent_id": continuation.agent_id,
        "objective": continuation.prompt,
        "title": continuation.title or continuation.prompt,
        "client_run_id": continuation.client_run_id,
        "metadata": dict(continuation.metadata),
        "direct_tool_requests": [
            dict(request) for request in continuation.direct_tool_requests
        ],
        "daily_desktop_planning_context": continuation.daily_desktop_planning_context,
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _chat_start_payload_from_replan_continuation(
    continuation: ReplanContinuationSnapshot,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": continuation.prompt,
        "title": continuation.title or continuation.prompt,
        "conversation_id": continuation.conversation_id,
        "metadata": dict(continuation.metadata),
        "direct_tool_requests": [
            dict(request) for request in continuation.direct_tool_requests
        ],
        "daily_desktop_planning_context": continuation.daily_desktop_planning_context,
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _replan_recovery_action_direct_request(
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
    *,
    task_context: Mapping[str, Any],
    continue_to_model: bool,
    source: str = "agent_studio_replan_recovery",
) -> dict[str, Any]:
    request = {
        "tool": str(action.tool or "").strip(),
        "input": dict(action.input or {}),
        "source": str(source or "agent_studio_replan_recovery").strip(),
        "planning_reason": str(
            action.planning_reason
            or recovery.planning_reason
            or "planner_replan_runtime_recovery_action"
        ),
        "replan_request_id": str(recovery.request_id or ""),
        "replan_trigger": str(recovery.trigger or ""),
        "recovery_action_label": str(action.label or recovery.recovery_action_label or ""),
        "permission_target": str(action.permission_target or recovery.permission_target or ""),
        "risk_level": str(action.risk_level or recovery.risk_level or ""),
        "approval_required": bool(action.approval_required),
        "selected": True,
    }
    replan_triggers = _replan_recovery_action_triggers(recovery, action)
    if replan_triggers:
        request["replan_triggers"] = replan_triggers
    replan_signal_ids = _replan_recovery_action_signal_ids(action)
    if replan_signal_ids:
        request["replan_signal_ids"] = replan_signal_ids
    if continue_to_model:
        request["continue_to_model"] = True
    for key, value in (
        ("step_id", recovery.source_step_id),
        ("source_step_id", recovery.source_step_id),
        ("source_tool_name", recovery.source_tool_name),
        ("capability_id", recovery.target_capability_id),
        ("target_capability_id", recovery.target_capability_id),
        ("action_id", action.action_id),
        ("replan_recovery_action_id", action.action_id),
    ):
        if value:
            request[key] = value
    for key in ("action_target", "observation_evidence", "observation_retry"):
        value = getattr(action, key) or getattr(recovery, key)
        if isinstance(value, Mapping) and value:
            request[key] = dict(value)
    for key in (
        "desktop_execution_policy",
        "desktop_execution_route",
        "sandbox_provider",
        "desktop_provider_session",
        "desktop_loop",
    ):
        value = getattr(action, key) or getattr(recovery, key)
        if isinstance(value, Mapping) and value:
            request[key] = dict(value)
    if _replan_recovery_action_is_provider_session_start(action):
        request["control_action"] = "desktop_provider_session.start"
        for key in ("api_route", "diagnostic_route"):
            value = _first_text(action.input.get(key))
            if value:
                request[key] = value
    deferred_tool = _first_text(action.deferred_tool, recovery.deferred_tool)
    if deferred_tool:
        request["deferred_tool"] = deferred_tool
    for key in ("deferred_input", "deferred_context"):
        value = getattr(action, key) or getattr(recovery, key)
        if isinstance(value, Mapping) and value:
            request[key] = dict(value)
    deferred_continuation = _mapping_list(
        action.deferred_continuation or recovery.deferred_continuation
    )
    if deferred_continuation:
        request["deferred_continuation"] = _replan_recovery_deferred_continuation_requests(
            recovery,
            action,
            deferred_continuation,
            task_context=task_context,
            source=source,
        )
    action_metadata = _mapping(action.metadata)
    for key in (
        "desktop_execution_policy",
        "desktop_execution_route",
        "sandbox_provider",
        "desktop_provider_session",
        "desktop_loop",
    ):
        if key in request:
            continue
        value = _mapping(action_metadata.get(key))
        if value:
            request[key] = value
    for key in ("runtime_stage", "runtime_role"):
        value = _first_text(action_metadata.get(key))
        if value:
            request[key] = value
    verification_targets = action.verification_targets or recovery.verification_targets
    if verification_targets:
        request["verification_targets"] = [dict(target) for target in verification_targets]
    _apply_replan_recovery_task_context(request, task_context)
    return request


def _replan_recovery_deferred_continuation_requests(
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
    continuation: Iterable[Mapping[str, Any]],
    *,
    task_context: Mapping[str, Any],
    source: str,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for index, item in enumerate(continuation, start=1):
        tool_name = _first_text(item.get("tool"), item.get("tool_name"))
        if not tool_name:
            continue
        request = dict(item)
        request["tool"] = tool_name
        request.setdefault("source", str(source or "agent_studio_replan_recovery").strip())
        request.setdefault("planning_reason", "planner_replan_deferred_continuation")
        request.setdefault("replan_request_id", str(recovery.request_id or ""))
        request.setdefault("replan_trigger", str(recovery.trigger or ""))
        if action.action_id:
            request.setdefault("replan_recovery_action_id", str(action.action_id or ""))
        if recovery.source_step_id:
            request.setdefault("source_step_id", recovery.source_step_id)
        if recovery.source_tool_name:
            request.setdefault("source_tool_name", recovery.source_tool_name)
        if recovery.target_capability_id:
            request.setdefault("target_capability_id", recovery.target_capability_id)
            request.setdefault("capability_id", recovery.target_capability_id)
        replan_triggers = _replan_recovery_action_triggers(recovery, action)
        if replan_triggers and "replan_triggers" not in request:
            request["replan_triggers"] = replan_triggers
        replan_signal_ids = _replan_recovery_action_signal_ids(action)
        if replan_signal_ids and "replan_signal_ids" not in request:
            request["replan_signal_ids"] = replan_signal_ids
        request.setdefault(
            "request_id",
            "replan-continuation:{}:{}:{}".format(
                str(recovery.request_id or "").strip(),
                index,
                tool_name,
            ),
        )
        _apply_replan_recovery_task_context(request, task_context)
        requests.append(request)
    return requests


def _replan_recovery_action_triggers(
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
) -> list[str]:
    triggers = _replan_recovery_action_metadata_list(action, "replan_triggers")
    trigger = _first_text(action.metadata.get("replan_trigger"), recovery.trigger)
    if trigger and trigger not in triggers:
        triggers.append(trigger)
    return triggers


def _replan_recovery_action_signal_ids(
    action: ReplanRecoveryActionSnapshot,
) -> list[str]:
    return _replan_recovery_action_metadata_list(action, "replan_signal_ids")


def _replan_recovery_action_metadata_list(
    action: ReplanRecoveryActionSnapshot,
    key: str,
) -> list[str]:
    metadata = _mapping(action.metadata)
    values = _string_list_from_any(metadata.get(key))
    singular = key[:-1] if key.endswith("s") else key
    single = _first_text(metadata.get(singular))
    if single and single not in values:
        values.append(single)
    return values


def _apply_replan_recovery_task_context(
    request: dict[str, Any],
    task_context: Mapping[str, Any],
) -> None:
    for context_key, request_key in (
        ("core_id", "core_id"),
        ("workspace_id", "workspace_id"),
        ("task_id", "task_id"),
        ("task_todo", "task_todo"),
        ("task_checkpoints", "task_checkpoints"),
        ("task_workspace_items", "task_workspace_items"),
        ("verification_targets", "verification_targets"),
        ("task_verification_targets", "task_verification_targets"),
    ):
        value = task_context.get(context_key)
        if value not in (None, "", [], {}):
            request[request_key] = value


def _replan_recovery_task_context(
    source_run: Any,
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
) -> dict[str, Any]:
    source_step_id = str(recovery.source_step_id or "").strip()
    action_metadata = _mapping(action.metadata)
    metadata_task_context = _mapping(action_metadata.get("task_context"))
    task_core = _source_task_core_for_recovery(source_run, recovery)
    workspace = getattr(task_core, "workspace", None) if task_core is not None else None
    todo = (
        _task_todo_context_for_step(task_core, source_step_id)
        or _mapping(action_metadata.get("task_todo"))
        or _mapping(metadata_task_context.get("task_todo"))
    )
    checkpoints = (
        _task_checkpoints_context_for_step(task_core, source_step_id)
        or _mapping_list(action_metadata.get("task_checkpoints"))
        or _mapping_list(metadata_task_context.get("task_checkpoints"))
    )
    workspace_items = (
        _task_workspace_items_context_for_step(workspace, source_step_id)
        or _mapping_list(action_metadata.get("task_workspace_items"))
        or _mapping_list(metadata_task_context.get("task_workspace_items"))
    )
    metadata_verification_targets = _merge_mapping_lists(
        _mapping_list(action_metadata.get("verification_targets")),
        _mapping_list(metadata_task_context.get("verification_targets")),
        _mapping_list(action_metadata.get("task_verification_targets")),
        _mapping_list(metadata_task_context.get("task_verification_targets")),
    )
    task_verification_targets = _replan_recovery_task_verification_targets(
        recovery,
        action,
        fallback_step_id=source_step_id,
        fallback_todo=todo,
        fallback_checkpoints=checkpoints,
        fallback_workspace_items=workspace_items,
    )
    task_verification_targets = _merge_mapping_lists(
        task_verification_targets,
        metadata_verification_targets,
    )
    if not todo and task_verification_targets:
        todo = _mapping(task_verification_targets[0].get("todo"))
    if not checkpoints and task_verification_targets:
        checkpoints = _mapping_list(task_verification_targets[0].get("checkpoints"))
    if not workspace_items and task_verification_targets:
        workspace_items = _mapping_list(task_verification_targets[0].get("workspace_items"))

    context: dict[str, Any] = {}
    for key, value in (
        ("core_id", _first_text(recovery.core_id, getattr(task_core, "core_id", ""))),
        (
            "workspace_id",
            _first_text(
                action_metadata.get("workspace_id"),
                metadata_task_context.get("workspace_id"),
                getattr(workspace, "workspace_id", ""),
            ),
        ),
        (
            "workspace_title",
            _first_text(
                action_metadata.get("workspace_title"),
                metadata_task_context.get("workspace_title"),
                getattr(workspace, "title", ""),
            ),
        ),
        ("task_id", _first_text(recovery.task_id, getattr(source_run, "task_id", ""))),
        ("source_step_id", source_step_id),
        ("planner_step_id", source_step_id),
    ):
        if value:
            context[key] = value
    if todo:
        context["task_todo"] = todo
        context["todos"] = [todo]
    if checkpoints:
        context["task_checkpoints"] = checkpoints
        context["checkpoints"] = checkpoints
    if workspace_items:
        context["task_workspace_items"] = workspace_items
        context["workspace_items"] = workspace_items
    if task_verification_targets:
        context["verification_targets"] = task_verification_targets
        context["task_verification_targets"] = task_verification_targets
    verification_targets = action.verification_targets or recovery.verification_targets
    if verification_targets:
        context["verification_targets"] = _merge_mapping_lists(
            _mapping_list(context.get("verification_targets")),
            verification_targets,
        )
    return context


def _merge_mapping_lists(*items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item_list in items:
        for item in item_list:
            record = _mapping(item)
            if record and record not in merged:
                merged.append(record)
    return merged


def _source_task_core_for_recovery(
    source_run: Any,
    recovery: ReplanRecoverySnapshot,
) -> Any:
    source_run_id = str(recovery.run_id or "").strip()
    fallback = None
    for candidate in _iter_source_run_nodes(source_run):
        task_core = getattr(candidate, "task_core", None)
        if task_core is None:
            continue
        if fallback is None:
            fallback = task_core
        if source_run_id and str(getattr(candidate, "run_id", "") or "").strip() == source_run_id:
            return task_core
    return fallback


def _iter_source_run_nodes(source_run: Any) -> Iterable[Any]:
    yield source_run
    for child_key in ("runs", "children"):
        for child in getattr(source_run, child_key, []) or []:
            yield from _iter_source_run_nodes(child)


def _task_todo_context_for_step(task_core: Any, step_id: str) -> dict[str, Any]:
    if task_core is None or not step_id:
        return {}
    for todo in list(getattr(task_core, "todos", []) or []):
        if str(getattr(todo, "step_id", "") or "").strip() == step_id:
            return _snapshot_record(todo)
    return {}


def _task_checkpoints_context_for_step(task_core: Any, step_id: str) -> list[dict[str, Any]]:
    if task_core is None or not step_id:
        return []
    return [
        record
        for checkpoint in list(getattr(task_core, "checkpoints", []) or [])
        if str(getattr(checkpoint, "after_step_id", "") or "").strip() == step_id
        for record in [_snapshot_record(checkpoint)]
        if record
    ]


def _task_workspace_items_context_for_step(workspace: Any, step_id: str) -> list[dict[str, Any]]:
    if workspace is None or not step_id:
        return []
    return [
        record
        for item in list(getattr(workspace, "items", []) or [])
        if str(getattr(item, "source_step_id", "") or "").strip() == step_id
        for record in [_snapshot_record(item)]
        if record
    ]


def _replan_recovery_task_verification_targets(
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
    *,
    fallback_step_id: str,
    fallback_todo: Mapping[str, Any],
    fallback_checkpoints: Iterable[Mapping[str, Any]],
    fallback_workspace_items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    raw_targets = _mapping_list(action.verification_targets or recovery.verification_targets)
    fallback_checkpoint_items = [dict(checkpoint) for checkpoint in fallback_checkpoints]
    fallback_workspace_item_records = [dict(item) for item in fallback_workspace_items]
    if not raw_targets and (
        fallback_todo or fallback_checkpoint_items or fallback_workspace_item_records
    ):
        raw_targets = [{"step_id": fallback_step_id}]
    targets: list[dict[str, Any]] = []
    for target in raw_targets:
        step_id = _first_text(target.get("step_id"), fallback_step_id)
        if not step_id:
            continue
        todo = _mapping(target.get("todo")) or _verification_target_todo(
            target,
            step_id=step_id,
            fallback_todo=fallback_todo,
        )
        checkpoints = _mapping_list(target.get("checkpoints")) or _verification_target_checkpoints(
            target,
            step_id=step_id,
            fallback_checkpoints=fallback_checkpoint_items,
        )
        workspace_items = (
            _mapping_list(target.get("workspace_items"))
            or _mapping_list(target.get("task_workspace_items"))
            or _verification_target_workspace_items(
                fallback_workspace_items=fallback_workspace_item_records,
            )
        )
        item = {
            "step_id": step_id,
            "todo": todo,
            "checkpoints": checkpoints,
        }
        if workspace_items:
            item["workspace_items"] = workspace_items
        targets.append(item)
    return targets


def _verification_target_todo(
    target: Mapping[str, Any],
    *,
    step_id: str,
    fallback_todo: Mapping[str, Any],
) -> dict[str, Any]:
    if fallback_todo:
        return dict(fallback_todo)
    todo_id = _first_text(target.get("todo_id"))
    if not todo_id:
        return {}
    return {
        key: value
        for key, value in {
            "todo_id": todo_id,
            "title": _first_text(target.get("todo_title"), target.get("title"), step_id),
            "status": _first_text(target.get("status"), "blocked"),
            "step_id": step_id,
            "tool_name": _first_text(target.get("tool_name"), target.get("tool")),
        }.items()
        if value
    }


def _verification_target_checkpoints(
    target: Mapping[str, Any],
    *,
    step_id: str,
    fallback_checkpoints: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fallback = [dict(checkpoint) for checkpoint in fallback_checkpoints]
    if fallback:
        return fallback
    checkpoint_ids = _string_list_from_any(target.get("checkpoint_ids"))
    checkpoint_titles = _string_list_from_any(target.get("checkpoint_titles"))
    return [
        {
            "checkpoint_id": checkpoint_id,
            "title": (
                checkpoint_titles[index]
                if index < len(checkpoint_titles)
                else checkpoint_id
            ),
            "status": "blocked",
            "after_step_id": step_id,
        }
        for index, checkpoint_id in enumerate(checkpoint_ids)
    ]


def _verification_target_workspace_items(
    *,
    fallback_workspace_items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [dict(item) for item in fallback_workspace_items]


def _snapshot_record(value: Any) -> dict[str, Any]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(mode="json")
        return dict(payload) if isinstance(payload, Mapping) else {}
    return dict(value) if isinstance(value, Mapping) else {}


def _replan_recovery_action_agent_id(
    payload: Mapping[str, Any],
    source_run: Any,
    recovery: ReplanRecoverySnapshot,
) -> str:
    explicit = str(payload.get("agent_id") or "").strip()
    if explicit:
        return explicit
    direct = str(getattr(source_run, "agent_id", "") or "").strip()
    if direct:
        return direct
    source_run_id = str(recovery.run_id or "").strip()
    if source_run_id:
        for run in getattr(source_run, "runs", []) or []:
            if str(getattr(run, "run_id", "") or "").strip() == source_run_id:
                agent_id = str(getattr(run, "agent_id", "") or "").strip()
                if agent_id:
                    return agent_id
        for participant in getattr(source_run, "participants", []) or []:
            if str(getattr(participant, "run_id", "") or "").strip() == source_run_id:
                agent_id = str(getattr(participant, "agent_id", "") or "").strip()
                if agent_id:
                    return agent_id
        for child in getattr(source_run, "children", []) or []:
            if str(getattr(child, "run_id", "") or "").strip() == source_run_id:
                agent_id = str(getattr(child, "agent_id", "") or "").strip()
                if agent_id:
                    return agent_id
    participants = [
        str(getattr(participant, "agent_id", "") or "").strip()
        for participant in getattr(source_run, "participants", []) or []
        if str(getattr(participant, "agent_id", "") or "").strip()
    ]
    unique_participants = list(dict.fromkeys(participants))
    if len(unique_participants) == 1:
        return unique_participants[0]
    return ""


def _replan_recovery_action_metadata(
    source_run: Any,
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
    *,
    task_context: Mapping[str, Any],
    extra: Mapping[str, Any],
    source: str = "agent_studio_replan_recovery",
) -> dict[str, Any]:
    metadata = dict(extra)
    source_id = _replan_recovery_source_id(source_run)
    metadata.update(
        {
            "daily_desktop_intent": True,
            "desktop_permission_recovery": True,
            "recovery_tool": str(action.tool or "").strip(),
            "recovery_input": dict(action.input or {}),
            "recovery_permission_target": str(
                action.permission_target or recovery.permission_target or ""
            ),
            "recovery_risk_level": str(action.risk_level or recovery.risk_level or ""),
            "replan_request_id": str(recovery.request_id or ""),
            "replan_recovery_action_id": str(action.action_id or ""),
            "replan_trigger": str(recovery.trigger or ""),
            "source": str(source or "agent_studio_replan_recovery").strip(),
            "source_run_id": source_id,
        }
    )
    replan_triggers = _replan_recovery_action_triggers(recovery, action)
    if replan_triggers:
        metadata["replan_triggers"] = replan_triggers
    replan_signal_ids = _replan_recovery_action_signal_ids(action)
    if replan_signal_ids:
        metadata["replan_signal_ids"] = replan_signal_ids
    if recovery.source_step_id:
        metadata["source_step_id"] = recovery.source_step_id
    if recovery.source_tool_name:
        metadata["source_tool_name"] = recovery.source_tool_name
    if recovery.target_capability_id:
        metadata["target_capability_id"] = recovery.target_capability_id
    group_run_id = str(getattr(source_run, "group_run_id", "") or recovery.group_run_id or "").strip()
    if group_run_id:
        metadata["source_group_run_id"] = group_run_id
    workflow_run_id = str(
        getattr(source_run, "workflow_run_id", "") or recovery.workflow_run_id or ""
    ).strip()
    if workflow_run_id:
        metadata["source_workflow_run_id"] = workflow_run_id
    source_task_id = str(getattr(source_run, "task_id", "") or recovery.task_id or "").strip()
    if source_task_id:
        metadata["source_task_id"] = source_task_id
    source_title = str(getattr(source_run, "title", "") or "").strip()
    if source_title:
        metadata["source_task_title"] = source_title
    if task_context:
        metadata["task_core_context"] = dict(task_context)
    action_metadata = _mapping(action.metadata)
    if _replan_recovery_action_is_provider_session_start(action):
        metadata["control_action"] = "desktop_provider_session.start"
        for key in ("api_route", "diagnostic_route"):
            value = _first_text(action.input.get(key))
            if value:
                metadata[key] = value
    for key in (
        "desktop_execution_policy",
        "desktop_execution_route",
        "sandbox_provider",
        "desktop_provider_session",
        "desktop_loop",
    ):
        value = getattr(action, key) or getattr(recovery, key)
        if isinstance(value, Mapping) and value:
            metadata[key] = dict(value)
            continue
        metadata_value = _mapping(action_metadata.get(key))
        if metadata_value:
            metadata[key] = metadata_value
    for key in ("runtime_stage", "runtime_role"):
        value = _first_text(action_metadata.get(key))
        if value:
            metadata[key] = value
    if action.approval_required:
        metadata["recovery_action_approval_required"] = True
    return metadata


def _replan_recovery_action_is_provider_session_start(
    action: ReplanRecoveryActionSnapshot,
) -> bool:
    if str(action.tool or "").strip() == "desktop.provider_session.start":
        return True
    metadata = _mapping(action.metadata)
    return str(metadata.get("runtime_retry_source") or "").strip() == (
        "desktop_provider_session"
    )


def _replan_recovery_source_id(source_run: Any) -> str:
    for key in ("run_id", "group_run_id", "workflow_run_id", "run_group_id"):
        value = str(getattr(source_run, key, "") or "").strip()
        if value:
            return value
    return ""


def _find_tool_recovery_tool_call(source_run: Any, tool_call_id: str) -> ToolCallSnapshot:
    for tool_call in _iter_source_run_tool_calls(source_run):
        if str(tool_call.tool_call_id or "").strip() == tool_call_id:
            return tool_call
    raise AgentRuntimeError("Tool recovery tool_call_id was not found")


def _iter_source_run_tool_calls(source_run: Any) -> Iterable[ToolCallSnapshot]:
    for tool_call in getattr(source_run, "tool_calls", []) or []:
        if isinstance(tool_call, ToolCallSnapshot):
            yield tool_call
    for child_key in ("runs", "children"):
        for child in getattr(source_run, child_key, []) or []:
            yield from _iter_source_run_tool_calls(child)


def _find_tool_call_recovery_action(
    tool_call: ToolCallSnapshot,
    action_id: str,
) -> dict[str, Any]:
    actions = [
        action
        for action in _tool_call_recovery_actions(tool_call)
        if str(action.get("tool") or action.get("retry_tool") or action.get("recovery_retry_tool") or "").strip()
    ]
    if not actions:
        raise AgentRuntimeError("Tool call has no executable recovery actions")
    for action in actions:
        if _tool_recovery_action_id(action) == action_id:
            return action
    raise AgentRuntimeError("Tool recovery action_id was not found")


def _tool_call_recovery_actions(tool_call: ToolCallSnapshot) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for source in (tool_call.output_preview, tool_call.input_preview, tool_call.metadata):
        actions.extend(_mapping_list_from_record(source, "recovery_actions"))
        data = source.get("data") if isinstance(source, Mapping) else None
        if isinstance(data, Mapping):
            actions.extend(_mapping_list_from_record(data, "recovery_actions"))
    return actions


def _tool_recovery_action_direct_request(
    tool_call: ToolCallSnapshot,
    action: Mapping[str, Any],
    *,
    action_kind: str,
    input_override: Any,
    continue_to_model: bool,
) -> dict[str, Any]:
    is_retry = action_kind == "retry_original"
    override = _mapping(input_override) if is_retry else {}
    if is_retry:
        tool = _first_text(
            action.get("retry_tool"),
            action.get("recovery_retry_tool"),
            tool_call.tool_name,
        )
        tool_input = (
            override
            or _mapping(action.get("retry_input"))
            or _mapping(action.get("recovery_retry_input"))
            or dict(tool_call.input_preview)
        )
        planning_reason = _first_text(
            action.get("planning_reason"),
            action.get("recovery_planning_reason"),
            tool_call.planning_reason,
            "agent_studio_tool_recovery_retry",
        )
    else:
        tool = _first_text(action.get("tool"), action.get("recovery_tool"))
        tool_input = (
            override
            or _mapping(action.get("input"))
            or _mapping(action.get("recovery_input"))
        )
        planning_reason = _first_text(
            action.get("planning_reason"),
            action.get("recovery_planning_reason"),
            tool_call.planning_reason,
            "agent_studio_tool_recovery",
        )
    if not tool:
        raise AgentRuntimeError("Tool recovery action has no executable tool")
    request: dict[str, Any] = {
        "tool": tool,
        "input": tool_input,
        "source": "agent_studio_tool_recovery",
        "planning_reason": planning_reason,
        "tool_call_id": str(tool_call.tool_call_id or ""),
        "source_tool_name": str(tool_call.tool_name or ""),
        "permission_target": _first_text(action.get("permission_target")),
        "risk_level": _first_text(action.get("risk_level"), tool_call.risk_level),
        "recovery_action_label": _first_text(action.get("label"), action.get("prompt"), tool),
        "selected": True,
    }
    if action_kind:
        request["action_kind"] = action_kind
    if continue_to_model:
        request["continue_to_model"] = True
    desktop_execution_policy = action.get("desktop_execution_policy")
    if isinstance(desktop_execution_policy, Mapping) and desktop_execution_policy:
        request["desktop_execution_policy"] = dict(desktop_execution_policy)
    desktop_execution_route = action.get("desktop_execution_route")
    if isinstance(desktop_execution_route, Mapping) and desktop_execution_route:
        request["desktop_execution_route"] = dict(desktop_execution_route)
    sandbox_provider = action.get("sandbox_provider")
    if isinstance(sandbox_provider, Mapping) and sandbox_provider:
        request["sandbox_provider"] = dict(sandbox_provider)
    for key, value in _tool_call_trace_fields(tool_call).items():
        if value:
            request[key] = value
    action_id = _tool_recovery_action_id(action)
    if action_id:
        request["action_id"] = action_id
    for key in (
        "action_target",
        "observation_evidence",
        "observation_retry",
        "followup_input",
        "retry_input_schema",
    ):
        value = action.get(key) or action.get(f"recovery_{key}")
        if isinstance(value, Mapping) and value:
            request[key] = dict(value)
    verification_targets = _mapping_list(action.get("verification_targets"))
    if verification_targets:
        request["verification_targets"] = verification_targets
    recommended_tools = _string_list_from_any(action.get("recommended_tools"))
    if recommended_tools:
        request["recommended_tools"] = recommended_tools
    required_retry_fields = _string_list_from_any(action.get("required_retry_fields"))
    if required_retry_fields:
        request["required_retry_fields"] = required_retry_fields
    return request


def _tool_recovery_action_agent_id(
    payload: Mapping[str, Any],
    source_run: Any,
    tool_call: ToolCallSnapshot,
) -> str:
    explicit = str(payload.get("agent_id") or "").strip()
    if explicit:
        return explicit
    direct = str(getattr(source_run, "agent_id", "") or "").strip()
    if direct:
        return direct
    for source_run_id in (
        tool_call.run_id,
        tool_call.source_run_id,
        tool_call.source_runnable_id,
    ):
        clean_source_run_id = str(source_run_id or "").strip()
        if not clean_source_run_id:
            continue
        agent_id = _agent_id_for_source_run_id(source_run, clean_source_run_id)
        if agent_id:
            return agent_id
    participants = [
        str(getattr(participant, "agent_id", "") or "").strip()
        for participant in getattr(source_run, "participants", []) or []
        if str(getattr(participant, "agent_id", "") or "").strip()
    ]
    unique_participants = list(dict.fromkeys(participants))
    if len(unique_participants) == 1:
        return unique_participants[0]
    return ""


def _agent_id_for_source_run_id(source_run: Any, source_run_id: str) -> str:
    for child_key in ("runs", "children"):
        for run in getattr(source_run, child_key, []) or []:
            if str(getattr(run, "run_id", "") or "").strip() != source_run_id:
                continue
            agent_id = str(getattr(run, "agent_id", "") or "").strip()
            if agent_id:
                return agent_id
    for participant in getattr(source_run, "participants", []) or []:
        if str(getattr(participant, "run_id", "") or "").strip() != source_run_id:
            continue
        agent_id = str(getattr(participant, "agent_id", "") or "").strip()
        if agent_id:
            return agent_id
    return ""


def _tool_recovery_action_metadata(
    source_run: Any,
    tool_call: ToolCallSnapshot,
    action: Mapping[str, Any],
    direct_request: Mapping[str, Any],
    *,
    action_kind: str,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = dict(extra)
    is_retry = action_kind == "retry_original"
    metadata.update(
        {
            "daily_desktop_intent": True,
            "desktop_permission_recovery": True,
            "recovery_tool": str(direct_request.get("tool") or ""),
            "recovery_input": dict(_mapping(direct_request.get("input"))),
            "recovery_permission_target": str(direct_request.get("permission_target") or ""),
            "recovery_risk_level": str(direct_request.get("risk_level") or ""),
            "source": "agent_studio_tool_recovery",
            "source_run_id": _replan_recovery_source_id(source_run),
            "source_tool_call_id": str(tool_call.tool_call_id or ""),
            "source_tool_name": str(tool_call.tool_name or ""),
            "tool_recovery_action_id": _tool_recovery_action_id(action),
        }
    )
    if action_kind:
        metadata["recovery_action_kind"] = action_kind
    if is_retry:
        metadata["desktop_permission_retry"] = True
    for key, value in _tool_call_trace_fields(tool_call).items():
        if key == "source_run_id":
            continue
        if value:
            metadata[f"source_{key}"] = value
    for key, metadata_key in (
        ("retry_tool", "recovery_retry_tool"),
        ("recovery_retry_tool", "recovery_retry_tool"),
        ("retry_input", "recovery_retry_input"),
        ("recovery_retry_input", "recovery_retry_input"),
        ("retry_input_schema", "recovery_retry_input_schema"),
        ("recovery_retry_input_schema", "recovery_retry_input_schema"),
        ("retry_input_source", "recovery_retry_input_source"),
        ("recovery_retry_input_source", "recovery_retry_input_source"),
        ("retry_artifact_tool", "recovery_retry_artifact_tool"),
        ("recovery_retry_artifact_tool", "recovery_retry_artifact_tool"),
        ("retry_artifact_kind", "recovery_retry_artifact_kind"),
        ("recovery_retry_artifact_kind", "recovery_retry_artifact_kind"),
        ("retry_prompt", "recovery_retry_prompt"),
        ("recovery_retry_prompt", "recovery_retry_prompt"),
        ("retry_source_event_type", "recovery_retry_source_event_type"),
        ("recovery_retry_source_event_type", "recovery_retry_source_event_type"),
        ("retry_source_tool_call_id", "recovery_retry_source_tool_call_id"),
        ("recovery_retry_source_tool_call_id", "recovery_retry_source_tool_call_id"),
        ("followup_tool", "recovery_followup_tool"),
        ("recovery_followup_tool", "recovery_followup_tool"),
        ("followup_input", "recovery_followup_input"),
        ("recovery_followup_input", "recovery_followup_input"),
    ):
        value = action.get(key)
        if value:
            metadata[metadata_key] = dict(value) if isinstance(value, Mapping) else value
    recommended_tools = _string_list_from_any(action.get("recommended_tools"))
    if recommended_tools:
        metadata["recommended_tools"] = recommended_tools
    desktop_execution_policy = action.get("desktop_execution_policy")
    if isinstance(desktop_execution_policy, Mapping) and desktop_execution_policy:
        metadata["desktop_execution_policy"] = dict(desktop_execution_policy)
    desktop_execution_route = action.get("desktop_execution_route")
    if isinstance(desktop_execution_route, Mapping) and desktop_execution_route:
        metadata["desktop_execution_route"] = dict(desktop_execution_route)
    sandbox_provider = action.get("sandbox_provider")
    if isinstance(sandbox_provider, Mapping) and sandbox_provider:
        metadata["sandbox_provider"] = dict(sandbox_provider)
    required_retry_fields = _string_list_from_any(action.get("required_retry_fields"))
    if required_retry_fields:
        metadata["required_retry_fields"] = required_retry_fields
    source_task_id = str(getattr(source_run, "task_id", "") or tool_call.task_id or "").strip()
    if source_task_id:
        metadata["source_task_id"] = source_task_id
    source_title = str(getattr(source_run, "title", "") or "").strip()
    if source_title:
        metadata["source_task_title"] = source_title
    if action.get("approval_required") or action.get("requires_approval"):
        metadata["recovery_action_approval_required"] = True
    return metadata


def _tool_recovery_action_objective(
    action: Mapping[str, Any],
    direct_request: Mapping[str, Any],
) -> str:
    label = _first_text(action.get("label"), action.get("prompt"))
    tool = str(direct_request.get("tool") or "").strip()
    if label and label != tool:
        return f"执行恢复动作：{label}"
    return f"执行恢复动作：{tool}"


def _tool_recovery_action_id(action: Mapping[str, Any]) -> str:
    return _first_text(action.get("action_id"), action.get("id"))


def _tool_call_trace_fields(tool_call: ToolCallSnapshot) -> dict[str, str]:
    return {
        key: str(getattr(tool_call, key) or "").strip()
        for key in (
            "source_run_id",
            "workflow_id",
            "workflow_run_id",
            "workflow_node_id",
            "workflow_node_label",
            "group_id",
            "group_run_id",
            "core_id",
            "workspace_id",
            "task_id",
            "decision_id",
            "plan_id",
            "tool_plan_id",
            "intent_kind",
            "step_id",
            "planner_step_id",
            "capability_id",
            "replan_request_id",
            "replan_trigger",
        )
    }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping_list_from_record(record: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    return _mapping_list(record.get(key))


def _string_list_from_any(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _rejection_payload(
    request: ApprovalDecision | Mapping[str, Any] | str | None,
) -> dict[str, Any] | None:
    if request is None:
        return None
    if isinstance(request, str):
        return {"approved": False, "reason": request}
    payload = _request_payload(request)
    payload.setdefault("approved", False)
    return payload


def _approval_payload(
    request: ApprovalDecision | Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if request is None:
        return None
    payload = _request_payload(request)
    payload.setdefault("approved", True)
    return payload


def _public_run_snapshot_from_payload(
    payload: Mapping[str, Any],
) -> RunTimelineSnapshot | WorkflowRunSnapshot:
    if is_workflow_run_payload(payload):
        return workflow_run_snapshot_from_payload(payload)
    return run_timeline_snapshot_from_payload(payload)


_GROUP_RUN_LIFECYCLE_EVENT_TYPES = {
    "group.run.started",
    "group.run.completed",
    "group.run.failed",
    "group.run.cancelled",
}
_WORKFLOW_RUN_LIFECYCLE_EVENT_TYPES = {
    "workflow.run.started",
    "workflow.run.completed",
    "workflow.run.failed",
    "workflow.run.cancelled",
}


def _group_run_events_from_port_payload(
    payload: Any,
    *,
    group_run_id: str,
) -> list[PublicRunEvent]:
    raw_events = _payload_items(payload, "events")
    projected_payload = _event_projection_payload(payload, raw_events)
    projected_payload.setdefault("group_run_id", group_run_id)
    projected_payload.setdefault("run_group_id", group_run_id)
    events = group_run_snapshot_from_payload(projected_payload).events
    return _drop_unreported_lifecycle_events(
        events,
        raw_events,
        lifecycle_event_types=_GROUP_RUN_LIFECYCLE_EVENT_TYPES,
    )


def _run_events_from_port_payload(
    payload: Any,
    *,
    run_id: str,
) -> list[PublicRunEvent]:
    raw_events = _payload_items(payload, "events")
    projected_payload = _event_projection_payload(payload, raw_events)
    projected_payload.setdefault("run_id", run_id)
    if _is_workflow_event_payload(projected_payload, raw_events):
        projected_payload.setdefault("workflow_run_id", run_id)
        events = workflow_run_snapshot_from_payload(projected_payload).events
        return _drop_unreported_lifecycle_events(
            events,
            raw_events,
            lifecycle_event_types=_WORKFLOW_RUN_LIFECYCLE_EVENT_TYPES,
        )
    return run_timeline_snapshot_from_payload(projected_payload).events


def _event_projection_payload(payload: Any, raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    projected = dict(payload) if isinstance(payload, Mapping) else {}
    projected["events"] = raw_events
    return projected


def _is_workflow_event_payload(
    payload: Mapping[str, Any],
    raw_events: list[dict[str, Any]],
) -> bool:
    if is_workflow_run_payload(payload):
        return True
    for event in raw_events:
        event_type = str(event.get("event_type") or event.get("event") or "").strip()
        if event_type.startswith("workflow.run."):
            return True
        event_payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
        if str(event_payload.get("planner_scope") or "").strip() == "workflow_run":
            return True
    return False


def _run_first_page_key_event_types(
    payload: Any,
    raw_events: list[dict[str, Any]],
) -> set[str]:
    projected_payload = _event_projection_payload(payload, raw_events)
    if _is_workflow_event_payload(projected_payload, raw_events):
        return FIRST_PAGE_WORKFLOW_RUN_KEY_EVENT_TYPES
    return FIRST_PAGE_RUN_KEY_EVENT_TYPES


def _drop_unreported_lifecycle_events(
    events: list[PublicRunEvent],
    raw_events: list[dict[str, Any]],
    *,
    lifecycle_event_types: set[str],
) -> list[PublicRunEvent]:
    raw_event_types = {
        str(event.get("event_type") or event.get("event") or "").strip()
        for event in raw_events
    }
    return [
        event
        for event in events
        if event.event_type not in lifecycle_event_types
        or event.event_type in raw_event_types
    ]


def _payload_items(payload: Any, key: str) -> list[dict[str, Any]]:
    items = payload.get(key) if isinstance(payload, Mapping) else payload
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes, Mapping)):
        return []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
