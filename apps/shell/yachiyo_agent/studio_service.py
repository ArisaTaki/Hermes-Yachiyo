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
    ToolCatalogSnapshot,
    UpdateRestrictedToolPluginRequest,
    WorkflowRunSnapshot,
    WorkflowSnapshot,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from .desk import agent_desk_snapshot_from_payload
from .events import public_run_event_page_from_payload
from .future_tasks import (
    future_task_snapshot_from_payload,
    future_task_trigger_result_snapshot_from_payload,
)
from .groups import agent_group_snapshot_from_payload, group_run_snapshot_from_payload
from .memories import memory_snapshot_from_payload
from .ports import StudioPort
from .planner_projection import runtime_planner_metadata
from .runtime_execution import runtime_execution_envelope_from_decision
from .runtime_planner import RuntimePlanner
from .runtime_progress import ProgressEventScope, public_runtime_tool_result_events
from .start_event_enrichment import (
    start_payload_with_planner_decision_events,
    start_payload_with_planner_events,
)
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
    return enriched


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

    def plan_task(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlannerDecisionSnapshot:
        port_planner = getattr(self._studio_port, "plan_task", None)
        if callable(port_planner):
            payload = port_planner(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata or {},
            )
            if payload is not None:
                return PlannerDecisionSnapshot.model_validate(payload)
        catalog = self.list_tool_catalog()
        tools = (
            list(allowed_tools)
            if allowed_tools is not None
            else [
                str(tool.tool_name or "").strip()
                for tool in catalog.tools
                if str(tool.tool_name or "").strip()
            ]
        )
        return RuntimePlanner().decision(
            prompt,
            allowed_tools=tools or None,
            metadata=_planner_metadata_with_catalog_readiness(metadata, catalog),
        )

    def plan_execution(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
        direct: bool = False,
    ) -> RuntimeExecutionEnvelopeSnapshot:
        port_planner = getattr(self._studio_port, "plan_execution", None)
        if callable(port_planner):
            payload = port_planner(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata or {},
                direct=direct,
            )
            if payload is not None:
                return RuntimeExecutionEnvelopeSnapshot.model_validate(payload)
        decision = self.plan_task(
            prompt,
            allowed_tools=allowed_tools,
            metadata=metadata,
        )
        envelope = runtime_execution_envelope_from_decision(
            decision,
            allowed_tools=allowed_tools,
            direct=direct,
            full_plan=True,
        )
        if envelope is None:
            raise ValueError("Unable to build Agent Studio execution plan")
        return envelope

    def project_tool_result_events(
        self,
        decision: PlannerDecisionSnapshot,
        *,
        tool_request: Mapping[str, Any],
        tool_event: Mapping[str, Any],
        event_scope: ProgressEventScope = "agent",
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
                workflow_payload = {
                    "workflow_id": target.target_id,
                    "objective": objective,
                    "title": title or target.target_name or "Workflow run",
                    "client_run_id": client_run_id or None,
                    "metadata": _planner_orchestration_run_metadata(
                        metadata,
                        decision,
                        kind="workflow",
                        target_id=target.target_id,
                        target_name=target.target_name,
                        allowed_tools=allowed_tools,
                    ),
                }
                workflow_run = workflow_run_snapshot_from_payload(
                    start_payload_with_planner_decision_events(
                        self._studio_port.start_workflow_run(workflow_payload),
                        decision,
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
                group_payload = {
                    "group_id": target.target_id,
                    "objective": objective,
                    "title": title or target.target_name or "Group run",
                    "client_run_id": client_run_id or None,
                    "metadata": _planner_orchestration_run_metadata(
                        metadata,
                        decision,
                        kind="group_run",
                        target_id=target.target_id,
                        target_name=target.target_name,
                        allowed_tools=allowed_tools,
                    ),
                }
                group_run = group_run_snapshot_from_payload(
                    start_payload_with_planner_decision_events(
                        self._studio_port.start_group_run(group_payload),
                        decision,
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
        return run_timeline_snapshot_from_payload(
            self._start_payload_with_planner_events(
                self._studio_port.start_agent_run(payload),
                payload,
            )
        )

    def start_replan_recovery_action(
        self,
        run_id: str,
        request: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
        payload = _request_payload(request)
        source_run = self.get_run_timeline(run_id)
        return self._start_replan_recovery_action_from_snapshot(source_run, payload)

    def _start_replan_recovery_action_from_snapshot(
        self,
        source_run: Any,
        payload: Mapping[str, Any],
    ) -> RunTimelineSnapshot:
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
        direct_request = _replan_recovery_action_direct_request(
            recovery,
            action,
            continue_to_model=bool(payload.get("continue_to_model", True)),
        )
        start_payload: dict[str, Any] = {
            "agent_id": agent_id,
            "objective": objective,
            "title": str(payload.get("title") or action.label or objective).strip(),
            "client_run_id": str(payload.get("client_run_id") or "").strip() or None,
            "metadata": _replan_recovery_action_metadata(
                source_run,
                recovery,
                action,
                payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {},
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
        return group_run_snapshot_from_payload(
            self._start_payload_with_planner_events(
                self._studio_port.start_group_run(payload),
                payload,
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
                events = _events_with_first_page_key_event_window(
                    events,
                    self.get_group_run_event_stream(group_run_id),
                    page=page,
                    event_types=_GROUP_RUN_FIRST_PAGE_KEY_EVENT_TYPES,
                )
            return _run_event_page_with_projected_events(
                page,
                events,
            )

        events = [
            event
            for event in self.get_group_run_event_stream(group_run_id)
            if int(event.sequence or 0) > clean_after_sequence
        ]
        page = events[:clean_limit]
        next_after_sequence = max(
            [int(event.sequence or 0) for event in page] or [clean_after_sequence]
        )
        return RunEventPageSnapshot(
            run_id=group_run_id,
            after_sequence=clean_after_sequence,
            limit=clean_limit,
            next_after_sequence=next_after_sequence,
            has_more=len(events) > clean_limit,
            events=page,
        )

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
        return workflow_run_snapshot_from_payload(
            self._start_payload_with_planner_events(
                self._studio_port.start_workflow_run(payload),
                payload,
            )
        )

    def _start_payload_with_planner_events(
        self,
        raw_payload: Mapping[str, Any],
        request_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        return start_payload_with_planner_events(
            raw_payload,
            request_payload,
            plan_task=self.plan_task,
            metadata_source="agent_studio_service_start",
        )

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
            return _run_event_page_with_projected_events(
                page,
                _run_events_from_port_payload(raw_page, run_id=run_id),
            )

        filtered_events = [
            event
            for event in self.get_run_event_stream(run_id)
            if int(event.sequence or 0) > clean_after_sequence
        ]
        page = filtered_events[:clean_limit]
        next_after_sequence = max(
            [int(event.sequence or 0) for event in page] or [clean_after_sequence]
        )
        return RunEventPageSnapshot(
            run_id=run_id,
            after_sequence=clean_after_sequence,
            limit=clean_limit,
            next_after_sequence=next_after_sequence,
            has_more=len(filtered_events) > clean_limit,
            events=page,
        )


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
) -> dict[str, Any]:
    payload = {
        **dict(metadata),
        **runtime_planner_metadata(decision, allowed_tools=allowed_tools),
    }
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


def _replan_recovery_action_direct_request(
    recovery: ReplanRecoverySnapshot,
    action: ReplanRecoveryActionSnapshot,
    *,
    continue_to_model: bool,
) -> dict[str, Any]:
    request = {
        "tool": str(action.tool or "").strip(),
        "input": dict(action.input or {}),
        "source": "agent_studio_replan_recovery",
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
        "selected": True,
    }
    if continue_to_model:
        request["continue_to_model"] = True
    for key, value in (
        ("step_id", recovery.source_step_id),
        ("capability_id", recovery.target_capability_id),
        ("action_id", action.action_id),
    ):
        if value:
            request[key] = value
    for key in ("action_target", "observation_evidence", "observation_retry"):
        value = getattr(action, key) or getattr(recovery, key)
        if isinstance(value, Mapping) and value:
            request[key] = dict(value)
    verification_targets = action.verification_targets or recovery.verification_targets
    if verification_targets:
        request["verification_targets"] = [dict(target) for target in verification_targets]
    return request


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
    extra: Mapping[str, Any],
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
            "source": "agent_studio_replan_recovery",
            "source_run_id": source_id,
        }
    )
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
    if action.approval_required:
        metadata["recovery_action_approval_required"] = True
    return metadata


def _replan_recovery_source_id(source_run: Any) -> str:
    for key in ("run_id", "group_run_id", "workflow_run_id", "run_group_id"):
        value = str(getattr(source_run, key, "") or "").strip()
        if value:
            return value
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
_GROUP_RUN_FIRST_PAGE_KEY_EVENT_TYPES = {
    "group.run.approval_required",
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


def _run_event_page_with_projected_events(
    page: RunEventPageSnapshot,
    events: list[PublicRunEvent],
) -> RunEventPageSnapshot:
    next_after_sequence = max(
        [int(event.sequence or 0) for event in events] or [int(page.next_after_sequence or 0)]
    )
    return page.model_copy(
        update={
            "events": events,
            "next_after_sequence": max(int(page.next_after_sequence or 0), next_after_sequence),
        }
    )


def _events_with_first_page_key_event_window(
    events: list[PublicRunEvent],
    full_stream: Iterable[PublicRunEvent],
    *,
    page: RunEventPageSnapshot,
    event_types: set[str],
) -> list[PublicRunEvent]:
    if not events or not event_types:
        return events
    next_after_sequence = int(page.next_after_sequence or 0)
    stream = sorted(
        [
            event
            for event in full_stream
            if int(event.sequence or 0) > next_after_sequence
        ],
        key=lambda event: int(event.sequence or 0),
    )
    key_event_sequence = 0
    for event in stream:
        if event.event_type in event_types:
            key_event_sequence = int(event.sequence or 0)
            break
    if key_event_sequence <= next_after_sequence:
        return events
    existing_sequences = {int(event.sequence or 0) for event in events}
    supplement = [
        event
        for event in stream
        if next_after_sequence < int(event.sequence or 0) <= key_event_sequence
        and int(event.sequence or 0) not in existing_sequences
    ]
    if not supplement:
        return events
    return [*events, *supplement]


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
