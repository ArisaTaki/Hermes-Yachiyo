"""Runtime foundation setup for NativeRunEngine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from packages.security import contains_sensitive_text

from apps.shell.agent.repositories.row_projections import RuntimeRowProjector
from apps.shell.agent.runtime.approval_snapshots import public_pending_approval
from apps.shell.agent.runtime.clock import utc_now_iso
from apps.shell.agent.runtime.config import (
    FINAL_RUN_STATUSES,
    MAIN_CHAT_AGENT_ID,
    normalize_execution_backend,
)
from apps.shell.agent.runtime.definition_names import RuntimeDefinitionNameGuard
from apps.shell.agent.runtime.engine_state import (
    RuntimeEngineStateBundle,
    build_runtime_engine_state,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_secrets
from apps.shell.agent.runtime.recorders import RuntimeRecorderBundle, build_runtime_recorders
from apps.shell.agent.runtime.run_requests import RuntimeRunRequestParser
from apps.shell.agent.runtime.run_status import RuntimeTerminalRunResolver
from apps.shell.agent.runtime.runnable_names import RuntimeRunnableNameResolver
from apps.shell.agent.runtime.schema import RuntimeSchemaService
from apps.shell.agent.runtime.serialization import json_load


@dataclass(frozen=True)
class RuntimeFoundationSetup:
    engine_state: RuntimeEngineStateBundle
    runtime_schema: RuntimeSchemaService
    row_projector: RuntimeRowProjector
    definition_name_guard: RuntimeDefinitionNameGuard
    runnable_name_resolver: RuntimeRunnableNameResolver
    run_request_parser: RuntimeRunRequestParser
    terminal_run_resolver: RuntimeTerminalRunResolver
    recorders: RuntimeRecorderBundle


def build_runtime_foundation_setup(
    *,
    db_path: Path | str | None,
    workspace_dir: Path | str | None,
    credential_store: Any,
    default_tool_policy: Callable[[str], dict[str, Any]],
    default_workspace_policy: Callable[[], dict[str, Any]],
    compile_tool_policy: Callable[[str, Any], dict[str, Any]],
    compile_workspace_policy: Callable[[Any], dict[str, Any]],
    read_credential: Callable[[str], str],
    task_run_link_for_run: Callable[[str], dict[str, Any] | None],
    run_group_source: Callable[[str], str],
    runnable_name: Callable[[str, str], str],
    ensure_row_factory: Callable[[], Any],
    append_run_event: Callable[[str, str, dict[str, Any]], None],
    get_run: Callable[[str], dict[str, Any]],
) -> RuntimeFoundationSetup:
    engine_state = build_runtime_engine_state(
        db_path=db_path,
        workspace_dir=workspace_dir,
        credential_store=credential_store,
    )
    return RuntimeFoundationSetup(
        engine_state=engine_state,
        runtime_schema=RuntimeSchemaService(
            engine_state.conn,
            now=utc_now_iso,
            redact_secrets=redact_secrets,
            credential_store=engine_state.credential_store,
        ),
        row_projector=RuntimeRowProjector(
            skills_dir=engine_state.skills_dir,
            json_load=json_load,
            default_tool_policy=default_tool_policy,
            default_workspace_policy=default_workspace_policy,
            compile_tool_policy=compile_tool_policy,
            compile_workspace_policy=compile_workspace_policy,
            normalize_execution_backend=normalize_execution_backend,
            read_credential=read_credential,
            public_pending_approval=public_pending_approval,
            task_run_link_for_run=task_run_link_for_run,
            run_group_source=run_group_source,
            runnable_name=runnable_name,
        ),
        definition_name_guard=RuntimeDefinitionNameGuard(
            engine_state.conn,
            ensure_row_factory=ensure_row_factory,
            error_type=AgentRuntimeError,
        ),
        runnable_name_resolver=RuntimeRunnableNameResolver(
            engine_state.conn,
            ensure_row_factory=ensure_row_factory,
            main_chat_agent_id=MAIN_CHAT_AGENT_ID,
        ),
        run_request_parser=RuntimeRunRequestParser(
            contains_sensitive_text=contains_sensitive_text,
            error_type=AgentRuntimeError,
        ),
        terminal_run_resolver=RuntimeTerminalRunResolver(
            get_run=get_run,
            final_statuses=FINAL_RUN_STATUSES,
        ),
        recorders=build_runtime_recorders(
            append_run_event=append_run_event,
            now=utc_now_iso,
        ),
    )
