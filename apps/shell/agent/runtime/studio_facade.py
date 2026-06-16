"""Agent Studio compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell.agent.runtime.run_readiness import RuntimeRunReadinessValidator
from apps.shell.agent.runtime.skill_content import SkillContentInspector


class RuntimeStudioFacadeMixin:
    """Keeps Studio-facing legacy methods while delegating to split services."""

    def _validate_agent_profile_refs(self, payload: dict[str, Any]) -> None:
        self.model_profile_resolver.validate_agent_profile_refs(payload)

    def list_agents(self) -> dict[str, Any]:
        return self.agent_definitions.list()

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.get(agent_id)

    def _get_agent_private(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.get_private(agent_id)

    def create_agent(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        return self.agent_definitions.create(payload, seed=seed)

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.agent_definitions.update(agent_id, payload)

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.delete(agent_id)

    def attach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        return self.agent_skill_attachments.attach(agent_id, skill_id)

    def detach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        return self.agent_skill_attachments.detach(agent_id, skill_id)

    def list_skill_folders(self) -> dict[str, Any]:
        return self.skill_folders.list()

    def create_skill_folder(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_folders.create(payload)

    def get_skill_folder(self, folder_id: str) -> dict[str, Any]:
        return self.skill_folders.get(folder_id)

    def update_skill_folder(self, folder_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_folders.update(folder_id, payload)

    def delete_skill_folder(self, folder_id: str, *, delete_skills: bool = False) -> dict[str, Any]:
        return self.skill_folders.delete(folder_id, delete_skills=delete_skills)

    def list_skills(self) -> dict[str, Any]:
        return self.skill_records.list()

    def list_native_skill_sources(self) -> dict[str, Any]:
        return self.skill_sources.list_native_sources()

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        return self.skill_records.get(skill_id)

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        return self.skill_import_service.import_skill(source_path, folder_id)

    def _normalize_skill_folder_id(self, folder_id: str | None) -> str:
        return self.skill_folders.normalize_id(folder_id)

    def _validate_skill_folder_name(self, name: str, *, current_folder_id: str = "") -> None:
        self.skill_folders.validate_name(name, current_folder_id=current_folder_id)

    def update_skill(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_records.update(skill_id, payload)

    @staticmethod
    def _skill_name(markdown: str, fallback: str) -> str:
        return SkillContentInspector.name(markdown, fallback)

    @staticmethod
    def _skill_description(markdown: str) -> str:
        return SkillContentInspector.description(markdown)

    @staticmethod
    def _skill_summary(markdown: str) -> str:
        return SkillContentInspector.summary(markdown)

    @staticmethod
    def _skill_asset_paths(root: Path) -> list[str]:
        return SkillContentInspector.asset_paths(root)

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        return self.skill_records.delete(skill_id)

    def list_workflows(self) -> dict[str, Any]:
        return self.workflows.list()

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.workflows.get(workflow_id)

    def create_workflow(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        return self.workflows.create(payload, seed=seed)

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.workflows.update(workflow_id, payload)

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.workflows.delete(workflow_id)

    def validate_workflow(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        return self.workflow_definition_validator.validate(nodes, edges)

    def _workflow_agent_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        return self.run_readiness_validator.workflow_agent_for_node(node)

    @staticmethod
    def _workflow_id_for_node(node: dict[str, Any]) -> str:
        return RuntimeRunReadinessValidator.workflow_id_for_node(node)

    def _workflow_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        return self.run_readiness_validator.workflow_for_node(node)

    def _validate_workflow_agent_nodes(self, nodes: list[dict[str, Any]]) -> None:
        self.run_readiness_validator.validate_workflow_agent_nodes(nodes)

    def _validate_workflow_subworkflow_nodes(
        self,
        nodes: list[dict[str, Any]],
        *,
        parent_workflow_id: str = "",
    ) -> None:
        self.run_readiness_validator.validate_workflow_subworkflow_nodes(
            nodes,
            parent_workflow_id=parent_workflow_id,
        )

    def _validate_agent_run_readiness(
        self,
        agent: dict[str, Any],
        *,
        label: str = "Agent",
        require_model_config: bool = False,
    ) -> None:
        self.run_readiness_validator.validate_agent_run_readiness(
            agent,
            label=label,
            require_model_config=require_model_config,
        )

    def _validate_workflow_agent_run_readiness(self, nodes: list[dict[str, Any]]) -> None:
        self.run_readiness_validator.validate_workflow_agent_run_readiness(nodes)

    def _validate_workflow_runnable_steps(self, nodes: list[dict[str, Any]]) -> None:
        self.run_readiness_validator.validate_workflow_runnable_steps(nodes)

    def list_runs(self, limit: int = 50) -> dict[str, Any]:
        return self.run_timeline.list_runs(limit)

    def list_run_groups(self, limit: int = 50) -> dict[str, Any]:
        return self.run_timeline.list_run_groups(limit)

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return self.run_timeline.get_run_group(run_group_id)

    def _run_group_source(self, run_group_id: str) -> str:
        return self.run_timeline.run_group_source(run_group_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.run_timeline.get_run(run_id)

    def link_task_run(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        return self.task_run_links.link(task_id=task_id, run_id=run_id, session_id=session_id)

    def get_task_run_link(self, task_id: str) -> dict[str, Any]:
        return self.task_run_links.get(task_id)

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        return self.run_timeline.append_event(
            run_id,
            event_type,
            payload,
            actor=actor,
            visibility=visibility,
            sensitivity=sensitivity,
        )

    def list_run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        return self.run_timeline.list_events(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
            include_internal=include_internal,
        )

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return self.run_deletion.delete(run_id)

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return self.run_timeline.read_artifact(run_id, artifact_path)
