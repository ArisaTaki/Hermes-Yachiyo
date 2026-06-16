"""Run repository and projection service setup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from packages.security import contains_sensitive_text

from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.runtime.agent_runs import RuntimeAgentRunCoordinator, RuntimeAgentRunStarter
from apps.shell.agent.runtime.approval_snapshots import ApprovalSnapshotBuilder
from apps.shell.agent.runtime.clock import utc_now_iso
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_json_value, redact_secrets
from apps.shell.agent.runtime.run_facade import RUNTIME_UNSET
from apps.shell.agent.runtime.run_projections import RunProjectionCoordinator
from apps.shell.agent.runtime.serialization import json_dump_sorted, json_load
from apps.shell.agent.tools.workspace import _is_within, _read_text, _safe_rel_path


@dataclass(frozen=True)
class RuntimeRunServiceBundle:
    approval_snapshots: ApprovalSnapshotBuilder
    run_groups: RunGroupRepository
    run_approvals: ApprovalRepository
    run_artifacts: RunArtifactRepository
    run_projections: RunProjectionCoordinator
    runs: RunRepository
    run_events: RunEventRepository
    agent_run_starter: RuntimeAgentRunStarter


@dataclass(frozen=True)
class RuntimeRunLayerSetup:
    run_services: RuntimeRunServiceBundle
    agent_run_coordinator: RuntimeAgentRunCoordinator


def build_runtime_run_services(
    *,
    conn: Any,
    db_lock: Any,
    ensure_row_factory: Callable[[], None],
    row_to_run_group: Callable[[Any], dict[str, Any]],
    row_to_run: Callable[[Any], dict[str, Any]],
    now: Callable[[], str],
    json_dump: Callable[[Any], str],
    json_load: Callable[[Any, Any], Any],
    redact_secrets: Callable[[Any], str],
    redact_json_value: Callable[[Any], Any],
    contains_sensitive_text: Callable[[Any], bool],
    error_type: type[Exception],
    unset_sentinel: Any,
    agent_artifacts_dir: Path,
    workflow_artifacts_dir: Path,
    get_run: Callable[[str], dict[str, Any]],
    safe_rel_path: Callable[[str], str],
    is_within: Callable[[Path, Path], bool],
    read_text: Callable[[Path], str],
    task_run_links: Any,
    accepting_runs: Callable[[], bool],
    append_run_to_group: Callable[[str, str], Any],
    get_run_group: Callable[[str], dict[str, Any]],
    insert_run_group: Callable[..., dict[str, Any]],
    insert_run: Callable[..., dict[str, Any]],
    run_by_client_request_id: Callable[[str], dict[str, Any] | None],
    client_request_id_from_payload: Callable[[dict[str, Any]], str],
    agent_workspace_dir: Callable[[str], Path],
) -> RuntimeRunServiceBundle:
    approval_snapshots = ApprovalSnapshotBuilder()
    run_groups = RunGroupRepository(
        conn,
        ensure_row_factory=ensure_row_factory,
        row_to_run_group=row_to_run_group,
        row_to_run=row_to_run,
        now=now,
        json_dump=json_dump,
        redact_secrets=redact_secrets,
    )
    run_approvals = ApprovalRepository(
        conn,
        db_lock,
        now=now,
        json_dump=json_dump,
        public_pending_approval=approval_snapshots.public_pending_approval,
    )
    run_artifacts = RunArtifactRepository(
        conn,
        agent_artifacts_dir=agent_artifacts_dir,
        workflow_artifacts_dir=workflow_artifacts_dir,
        get_run=get_run,
        now=now,
        json_dump=json_dump,
        redact_json_value=redact_json_value,
        redact_secrets=redact_secrets,
        safe_rel_path=safe_rel_path,
        is_within=is_within,
        read_text=read_text,
    )
    run_projections = RunProjectionCoordinator(
        run_artifacts=run_artifacts,
        run_approvals=run_approvals,
        task_run_links=task_run_links,
    )
    runs = RunRepository(
        conn,
        ensure_row_factory=ensure_row_factory,
        row_to_run=row_to_run,
        accepting_runs=accepting_runs,
        sync_projections=run_projections.sync,
        append_run_to_group=append_run_to_group,
        now=now,
        json_dump=json_dump,
        json_load=json_load,
        redact_secrets=redact_secrets,
        redact_json_value=redact_json_value,
        contains_sensitive_text=contains_sensitive_text,
        error_type=error_type,
        unset_sentinel=unset_sentinel,
    )
    run_events = RunEventRepository(
        conn,
        db_lock,
        now=now,
        json_dump=json_dump,
        json_load=json_load,
        error_type=error_type,
        ensure_run_exists=get_run,
        sync_event_cursor=run_projections.sync_event_cursor,
    )
    return RuntimeRunServiceBundle(
        approval_snapshots=approval_snapshots,
        run_groups=run_groups,
        run_approvals=run_approvals,
        run_artifacts=run_artifacts,
        run_projections=run_projections,
        runs=runs,
        run_events=run_events,
        agent_run_starter=RuntimeAgentRunStarter(
            get_run_group=get_run_group,
            insert_run_group=insert_run_group,
            insert_run=insert_run,
            run_by_client_request_id=run_by_client_request_id,
            client_request_id_from_payload=client_request_id_from_payload,
            agent_workspace_dir=agent_workspace_dir,
        ),
    )


def build_runtime_run_layer_setup(
    *,
    conn: Any,
    db_lock: Any,
    ensure_row_factory: Callable[[], None],
    row_to_run_group: Callable[[Any], dict[str, Any]],
    row_to_run: Callable[[Any], dict[str, Any]],
    agent_artifacts_dir: Path,
    workflow_artifacts_dir: Path,
    get_run: Callable[[str], dict[str, Any]],
    task_run_links: Any,
    accepting_runs: Callable[[], bool],
    append_run_to_group: Callable[[str, str], Any],
    get_run_group: Callable[[str], dict[str, Any]],
    insert_run_group: Callable[..., dict[str, Any]],
    insert_run: Callable[..., dict[str, Any]],
    run_by_client_request_id: Callable[[str], dict[str, Any] | None],
    client_request_id_from_payload: Callable[[dict[str, Any]], str],
    agent_workspace_dir: Callable[..., Any],
    get_agent_private: Callable[[str], dict[str, Any]],
    validate_agent_run_readiness: Callable[[dict[str, Any]], None],
    execute_agent_run: Callable[..., dict[str, Any]],
    project_agent_run_group_if_root: Callable[[dict[str, Any]], dict[str, Any]],
) -> RuntimeRunLayerSetup:
    run_services = build_runtime_run_services(
        conn=conn,
        db_lock=db_lock,
        ensure_row_factory=ensure_row_factory,
        row_to_run_group=row_to_run_group,
        row_to_run=row_to_run,
        now=utc_now_iso,
        json_dump=json_dump_sorted,
        json_load=json_load,
        redact_secrets=redact_secrets,
        redact_json_value=redact_json_value,
        contains_sensitive_text=contains_sensitive_text,
        error_type=AgentRuntimeError,
        unset_sentinel=RUNTIME_UNSET,
        agent_artifacts_dir=agent_artifacts_dir,
        workflow_artifacts_dir=workflow_artifacts_dir,
        get_run=get_run,
        safe_rel_path=_safe_rel_path,
        is_within=_is_within,
        read_text=_read_text,
        task_run_links=task_run_links,
        accepting_runs=accepting_runs,
        append_run_to_group=append_run_to_group,
        get_run_group=get_run_group,
        insert_run_group=insert_run_group,
        insert_run=insert_run,
        run_by_client_request_id=run_by_client_request_id,
        client_request_id_from_payload=client_request_id_from_payload,
        agent_workspace_dir=agent_workspace_dir,
    )
    return RuntimeRunLayerSetup(
        run_services=run_services,
        agent_run_coordinator=RuntimeAgentRunCoordinator(
            get_agent_private=get_agent_private,
            validate_agent_run_readiness=validate_agent_run_readiness,
            starter=run_services.agent_run_starter,
            execute_agent_run=execute_agent_run,
            project_agent_run_group_if_root=project_agent_run_group_if_root,
            lock=db_lock,
            error_type=AgentRuntimeError,
        ),
    )
