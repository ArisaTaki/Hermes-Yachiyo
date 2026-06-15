"""Tests for Agent/Skill definition service setup split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.skill_folders import SkillFolderRepository
from apps.shell.agent.repositories.skills import SkillRepository
from apps.shell.agent.repositories.studio_deletions import StudioDeletionRepository
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.repositories.workspaces import TrustedWorkspaceRepository
from apps.shell.agent.runtime.definition_services import (
    RuntimeDefinitionServiceBundle,
    build_runtime_definition_services,
)
from apps.shell.agent.runtime.skill_attachments import RuntimeAgentSkillAttachmentService
from apps.shell.agent.runtime.skill_content import SkillContentInspector
from apps.shell.agent.runtime.skill_import import SkillImportPreparer, SkillImportSourceResolver
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from apps.shell.agent.runtime.skill_sources import SkillSourceDiscovery
from apps.shell.agent.runtime.skill_sync import SkillSyncPlanner
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_definition_service_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeDefinitionServiceBundle is RuntimeDefinitionServiceBundle
    assert agent_runtime.RuntimeAgentSkillAttachmentService is RuntimeAgentSkillAttachmentService


def test_build_runtime_definition_services_wires_repositories_and_skill_helpers(tmp_path) -> None:
    conn = object()

    def ensure_row_factory() -> None:
        return None

    def row_projection(row: Any) -> dict[str, Any]:
        return dict(row) if isinstance(row, dict) else {}

    bundle = build_runtime_definition_services(
        conn=conn,
        ensure_row_factory=ensure_row_factory,
        get_run=lambda run_id: {"run_id": run_id},
        now=lambda: "2026-06-15T10:00:00Z",
        error_type=agent_runtime.AgentRuntimeError,
        row_to_skill_folder=row_projection,
        slug=lambda value, fallback: str(value or fallback).strip() or fallback,
        skill_folder_id_suffix_factory=lambda: "folder",
        delete_skill=lambda _skill_id: None,
        row_to_skill=row_projection,
        json_dump=lambda value: "{}",
        json_load=lambda _value, default: default,
        normalize_skill_folder_id=lambda value: str(value or ""),
        installed_skill_source_map=lambda: {},
        record_studio_deletion=lambda *_args, **_kwargs: None,
        skill_deletion_key=lambda *_args, **_kwargs: "delete-key",
        is_native_library_source_type=lambda _value: False,
        skills_dir=tmp_path / "skills",
        skill_installs_dir=tmp_path / "skill-installs",
        skill_id_factory=lambda name: f"skill_{name}",
        row_to_agent=row_projection,
        row_to_agent_private=row_projection,
        coerce_named_row=lambda row: row,
        main_chat_virtual_agent=lambda: {"agent_id": "builtin:yachiyo-main"},
        agent_id_factory=lambda name: f"agent_{name}",
        normalize_execution_backend=lambda value, **_kwargs: str(value or "native_profile"),
        ensure_global_name_available=lambda *_args, **_kwargs: None,
        validate_agent_profile_refs=lambda _agent: None,
        compile_tool_policy=lambda *_args, **_kwargs: {},
        compile_workspace_policy=lambda _policy: {},
        assign_default_agent_workdir=lambda _agent, policy: policy,
        trust_workspace_from_policy=lambda *_args, **_kwargs: None,
        agent_model_credential_ref=lambda _agent: "",
        store_credential=lambda *_args, **_kwargs: None,
        delete_credential=lambda _credential_id: None,
        clear_studio_deletion=lambda *_args, **_kwargs: None,
        system_agent_ids={"builtin:yachiyo-main"},
        main_chat_agent_id="builtin:yachiyo-main",
        native_skill_home=lambda: tmp_path / "native",
        skill_installs_native_home=tmp_path / "skill-installs" / "native",
        normalize_skill_source_type=lambda value: str(value or "local_dir"),
        native_library_source_types={"native_global"},
        workspace_dir=tmp_path / "workspace",
        skill_import_id_factory=lambda: "import-id",
        skill_source_types={"local_dir", "native_global"},
        row_to_workflow=row_projection,
        workflow_id_factory=lambda name: f"workflow_{name}",
        validate_workflow=lambda _nodes, _edges: None,
        validate_workflow_agent_nodes=lambda _nodes: None,
        validate_workflow_subworkflow_nodes=lambda _nodes, **_kwargs: None,
    )

    assert isinstance(bundle, RuntimeDefinitionServiceBundle)
    assert isinstance(bundle.task_run_links, TaskRunLinkRepository)
    assert isinstance(bundle.trusted_workspaces, TrustedWorkspaceRepository)
    assert isinstance(bundle.studio_deletions, StudioDeletionRepository)
    assert isinstance(bundle.skill_folders, SkillFolderRepository)
    assert isinstance(bundle.skill_records, SkillRepository)
    assert isinstance(bundle.agent_definitions, AgentDefinitionRepository)
    assert isinstance(bundle.agent_skill_attachments, RuntimeAgentSkillAttachmentService)
    assert isinstance(bundle.skill_install_validator, SkillInstallCommandValidator)
    assert isinstance(bundle.skill_sources, SkillSourceDiscovery)
    assert isinstance(bundle.skill_content, SkillContentInspector)
    assert isinstance(bundle.skill_import_sources, SkillImportSourceResolver)
    assert isinstance(bundle.skill_import_preparer, SkillImportPreparer)
    assert isinstance(bundle.skill_sync, SkillSyncPlanner)
    assert isinstance(bundle.workflows, WorkflowRepository)
    assert bundle.task_run_links._conn is conn
    assert bundle.skill_records._conn is conn
    assert bundle.agent_definitions._conn is conn
    assert bundle.agent_skill_attachments._agent_definitions is bundle.agent_definitions
    assert bundle.agent_skill_attachments._skill_records is bundle.skill_records
    assert bundle.workflows._conn is conn
    assert bundle.skill_import_preparer._content is bundle.skill_content


def test_native_runtime_installs_definition_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.task_run_links, TaskRunLinkRepository)
        assert isinstance(service.trusted_workspaces, TrustedWorkspaceRepository)
        assert isinstance(service.studio_deletions, StudioDeletionRepository)
        assert isinstance(service.skill_folders, SkillFolderRepository)
        assert isinstance(service.skill_records, SkillRepository)
        assert isinstance(service.agent_definitions, AgentDefinitionRepository)
        assert isinstance(service.agent_skill_attachments, RuntimeAgentSkillAttachmentService)
        assert isinstance(service.skill_install_validator, SkillInstallCommandValidator)
        assert isinstance(service.skill_sources, SkillSourceDiscovery)
        assert isinstance(service.skill_content, SkillContentInspector)
        assert isinstance(service.skill_import_sources, SkillImportSourceResolver)
        assert isinstance(service.skill_import_preparer, SkillImportPreparer)
        assert isinstance(service.skill_sync, SkillSyncPlanner)
        assert isinstance(service.workflows, WorkflowRepository)
        assert service.task_run_links._conn is service._conn
        assert service.skill_records._conn is service._conn
        assert service.agent_definitions._conn is service._conn
        assert service.agent_skill_attachments._agent_definitions is service.agent_definitions
        assert service.agent_skill_attachments._skill_records is service.skill_records
        assert service.workflows._conn is service._conn
        assert service.skill_import_preparer._content is service.skill_content
    finally:
        service.close()
