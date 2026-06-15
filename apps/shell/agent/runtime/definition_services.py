"""Agent, Skill, and Studio definition service setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.skill_folders import SkillFolderRepository
from apps.shell.agent.repositories.skills import SkillRepository
from apps.shell.agent.repositories.studio_deletions import StudioDeletionRepository
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.repositories.workspaces import TrustedWorkspaceRepository
from apps.shell.agent.runtime.skill_content import SkillContentInspector
from apps.shell.agent.runtime.skill_import import SkillImportPreparer, SkillImportSourceResolver
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from apps.shell.agent.runtime.skill_sources import SkillSourceDiscovery
from apps.shell.agent.runtime.skill_sync import SkillSyncPlanner


@dataclass(frozen=True)
class RuntimeDefinitionServiceBundle:
    task_run_links: TaskRunLinkRepository
    trusted_workspaces: TrustedWorkspaceRepository
    studio_deletions: StudioDeletionRepository
    skill_folders: SkillFolderRepository
    skill_records: SkillRepository
    agent_definitions: AgentDefinitionRepository
    skill_install_validator: SkillInstallCommandValidator
    skill_sources: SkillSourceDiscovery
    skill_content: SkillContentInspector
    skill_import_sources: SkillImportSourceResolver
    skill_import_preparer: SkillImportPreparer
    skill_sync: SkillSyncPlanner
    workflows: WorkflowRepository


def build_runtime_definition_services(
    *,
    conn: Any,
    ensure_row_factory: Callable[[], None],
    get_run: Callable[[str], dict[str, Any]],
    now: Callable[[], str],
    error_type: type[Exception],
    row_to_skill_folder: Callable[[Any], dict[str, Any]],
    slug: Callable[[Any, str], str],
    skill_folder_id_suffix_factory: Callable[[], str],
    delete_skill: Callable[[str], Any],
    row_to_skill: Callable[[Any], dict[str, Any]],
    json_dump: Callable[[Any], str],
    json_load: Callable[[Any, Any], Any],
    normalize_skill_folder_id: Callable[[Any], str],
    installed_skill_source_map: Callable[[], dict[str, Any]],
    record_studio_deletion: Callable[..., Any],
    skill_deletion_key: Callable[[dict[str, Any]], str],
    is_native_library_source_type: Callable[[Any], bool],
    skills_dir: Path,
    skill_installs_dir: Path,
    skill_id_factory: Callable[[str], str],
    row_to_agent: Callable[[Any], dict[str, Any]],
    row_to_agent_private: Callable[[Any], dict[str, Any]],
    coerce_named_row: Callable[[Any], Any],
    main_chat_virtual_agent: Callable[[], dict[str, Any]],
    agent_id_factory: Callable[[str], str],
    normalize_execution_backend: Callable[..., str],
    ensure_global_name_available: Callable[..., None],
    validate_agent_profile_refs: Callable[[dict[str, Any]], None],
    compile_tool_policy: Callable[..., dict[str, Any]],
    compile_workspace_policy: Callable[[Any], dict[str, Any]],
    assign_default_agent_workdir: Callable[..., dict[str, Any]],
    trust_workspace_from_policy: Callable[..., Any],
    agent_model_credential_ref: Callable[[dict[str, Any]], str],
    store_credential: Callable[..., Any],
    delete_credential: Callable[[str], Any],
    clear_studio_deletion: Callable[[str, str], Any],
    system_agent_ids: set[str],
    main_chat_agent_id: str,
    native_skill_home: Callable[[], Path],
    skill_installs_native_home: Path,
    normalize_skill_source_type: Callable[[Any], str],
    native_library_source_types: set[str],
    workspace_dir: Path,
    skill_import_id_factory: Callable[[], str],
    skill_source_types: set[str],
    row_to_workflow: Callable[[Any], dict[str, Any]],
    workflow_id_factory: Callable[[str], str],
    validate_workflow: Callable[[list[dict[str, Any]], list[dict[str, Any]]], Any],
    validate_workflow_agent_nodes: Callable[[list[dict[str, Any]]], Any],
    validate_workflow_subworkflow_nodes: Callable[..., Any],
) -> RuntimeDefinitionServiceBundle:
    skill_content = SkillContentInspector()
    return RuntimeDefinitionServiceBundle(
        task_run_links=TaskRunLinkRepository(
            conn,
            ensure_row_factory=ensure_row_factory,
            get_run=get_run,
            now=now,
            error_type=error_type,
        ),
        trusted_workspaces=TrustedWorkspaceRepository(
            conn,
            now=now,
            error_type=error_type,
        ),
        studio_deletions=StudioDeletionRepository(
            conn,
            now=now,
        ),
        skill_folders=SkillFolderRepository(
            conn,
            ensure_row_factory=ensure_row_factory,
            row_to_skill_folder=row_to_skill_folder,
            now=now,
            slug=slug,
            id_suffix_factory=skill_folder_id_suffix_factory,
            delete_skill=delete_skill,
            error_type=error_type,
        ),
        skill_records=SkillRepository(
            conn,
            ensure_row_factory=ensure_row_factory,
            row_to_skill=row_to_skill,
            now=now,
            json_dump=json_dump,
            json_load=json_load,
            normalize_skill_folder_id=normalize_skill_folder_id,
            installed_skill_source_map=installed_skill_source_map,
            record_studio_deletion=record_studio_deletion,
            skill_deletion_key=skill_deletion_key,
            is_native_library_source_type=is_native_library_source_type,
            skills_dir=skills_dir,
            skill_installs_dir=skill_installs_dir,
            skill_id_factory=skill_id_factory,
            asset_paths_for=SkillContentInspector.asset_paths,
        ),
        agent_definitions=AgentDefinitionRepository(
            conn,
            ensure_row_factory=ensure_row_factory,
            row_to_agent=row_to_agent,
            row_to_agent_private=row_to_agent_private,
            coerce_named_row=coerce_named_row,
            main_chat_virtual_agent=main_chat_virtual_agent,
            now=now,
            json_dump=json_dump,
            agent_id_factory=agent_id_factory,
            normalize_execution_backend=normalize_execution_backend,
            ensure_global_name_available=ensure_global_name_available,
            validate_agent_profile_refs=validate_agent_profile_refs,
            compile_tool_policy=compile_tool_policy,
            compile_workspace_policy=compile_workspace_policy,
            assign_default_agent_workdir=assign_default_agent_workdir,
            trust_workspace_from_policy=trust_workspace_from_policy,
            agent_model_credential_ref=agent_model_credential_ref,
            store_credential=store_credential,
            delete_credential=delete_credential,
            record_studio_deletion=record_studio_deletion,
            clear_studio_deletion=clear_studio_deletion,
            system_agent_ids=system_agent_ids,
            main_chat_agent_id=main_chat_agent_id,
            error_type=error_type,
        ),
        skill_install_validator=SkillInstallCommandValidator(
            error_type=error_type,
        ),
        skill_sources=SkillSourceDiscovery(
            native_skill_home=native_skill_home,
            skill_installs_dir=skill_installs_dir,
            skill_installs_native_home=skill_installs_native_home,
            json_load=json_load,
            normalize_source_type=normalize_skill_source_type,
            native_library_source_types=native_library_source_types,
        ),
        skill_content=skill_content,
        skill_import_sources=SkillImportSourceResolver(
            workspace_dir=workspace_dir,
            id_factory=skill_import_id_factory,
            error_type=error_type,
        ),
        skill_import_preparer=SkillImportPreparer(
            content=skill_content,
            skill_source_types=skill_source_types,
            now=now,
            error_type=error_type,
        ),
        skill_sync=SkillSyncPlanner(
            skill_source_types=skill_source_types,
            count_skill_files=SkillSourceDiscovery.count_skill_files,
        ),
        workflows=WorkflowRepository(
            conn,
            ensure_row_factory=ensure_row_factory,
            row_to_workflow=row_to_workflow,
            now=now,
            json_dump=json_dump,
            workflow_id_factory=workflow_id_factory,
            ensure_global_name_available=ensure_global_name_available,
            validate_workflow=validate_workflow,
            validate_workflow_agent_nodes=validate_workflow_agent_nodes,
            validate_workflow_subworkflow_nodes=validate_workflow_subworkflow_nodes,
            record_studio_deletion=record_studio_deletion,
            clear_studio_deletion=clear_studio_deletion,
        ),
    )
