"""Runtime installation compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.agent_chat_entrypoints import (
    build_runtime_agent_chat_entrypoint_setup,
)
from apps.shell.agent.runtime.credentials import RuntimeCredentialService
from apps.shell.agent.runtime.core_services import build_runtime_memory_core_setup
from apps.shell.agent.runtime.foundation import build_runtime_foundation_setup
from apps.shell.agent.runtime.model_calling import (
    RuntimeModelProfileChatAdapter,
    RuntimeOpenAICompatibleChatAdapter,
    build_runtime_model_call_adapters,
)
from apps.shell.agent.runtime.approval_services import (
    build_runtime_approval_runtime_services,
)
from apps.shell.agent.runtime.main_chat_model import build_runtime_main_chat_model_setup
from apps.shell.agent.runtime.main_chat_model_loop import (
    build_runtime_main_chat_model_loop_runner,
)
from apps.shell.agent.runtime.run_cancellation import RuntimeRunCancellationCoordinator
from apps.shell.agent.runtime.run_services import build_runtime_run_layer_setup
from apps.shell.agent.runtime.tooling import build_runtime_tooling_stack


def _legacy_agent_runtime_module() -> Any:
    from apps.shell import agent_runtime

    return agent_runtime


class RuntimeInstallationFacadeMixin:
    """Keeps legacy runtime collaborator installation methods."""

    def _install_runtime_model_adapters(self) -> None:
        adapters = build_runtime_model_call_adapters(
            chat_message_provider=lambda: _legacy_agent_runtime_module().openai_compatible_chat_message,
            timeout_provider=lambda: _legacy_agent_runtime_module().read_openai_compatible_chat_timeout(),
            urlopen=lambda *args, **kwargs: _legacy_agent_runtime_module().urlopen_with_bundled_ca(*args, **kwargs),
            redact_error=lambda value: _legacy_agent_runtime_module().redact_secrets(value),
        )
        self.model_profile_chat_adapter = adapters.model_profile_chat_adapter
        self.openai_compatible_chat_adapter = adapters.openai_compatible_chat_adapter

    def _install_runtime_foundation(
        self,
        *,
        db_path: Any,
        workspace_dir: Any,
        credential_store: Any,
    ) -> None:
        setup = build_runtime_foundation_setup(
            db_path=db_path,
            workspace_dir=workspace_dir,
            credential_store=credential_store,
            default_tool_policy=self._default_tool_policy,
            default_workspace_policy=self._default_workspace_policy,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            read_credential=self._read_credential,
            task_run_link_for_run=lambda run_id: self.task_run_links.for_run(run_id),
            run_group_source=self._run_group_source,
            runnable_name=self._runnable_name,
            ensure_row_factory=self._ensure_row_factory,
            append_run_event=self.append_run_event,
            get_run=lambda run_id: self.get_run(run_id),
        )
        self._install_runtime_engine_state(setup.engine_state)
        self.runtime_schema = setup.runtime_schema
        self.row_projector = setup.row_projector
        self.definition_name_guard = setup.definition_name_guard
        self.runnable_name_resolver = setup.runnable_name_resolver
        self.run_request_parser = setup.run_request_parser
        self.terminal_run_resolver = setup.terminal_run_resolver
        self._install_runtime_recorders(setup.recorders)

    def _install_runtime_definition_layer(self) -> None:
        legacy = _legacy_agent_runtime_module()
        definition_services = legacy._build_runtime_definition_services(
            conn=self._conn,
            ensure_row_factory=self._ensure_row_factory,
            get_run=lambda run_id: self.get_run(run_id),
            now=legacy._now,
            error_type=legacy.AgentRuntimeError,
            row_to_skill_folder=self._row_to_skill_folder,
            slug=legacy._slug,
            skill_folder_id_suffix_factory=lambda: legacy.uuid4().hex[:6],
            delete_skill=lambda skill_id: self.delete_skill(skill_id),
            row_to_skill=self._row_to_skill,
            json_dump=legacy._json_dump,
            json_load=legacy._json_load,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            installed_skill_source_map=self._installed_skill_source_map,
            record_studio_deletion=self._record_studio_deletion,
            skill_deletion_key=self._skill_deletion_key,
            is_native_library_source_type=legacy._is_native_library_source_type,
            skills_dir=self.skills_dir,
            skill_installs_dir=self.skill_installs_dir,
            skill_id_factory=lambda name: f"skill_{legacy._slug(name, 'skill')}_{legacy.uuid4().hex[:8]}",
            row_to_agent=self._row_to_agent,
            row_to_agent_private=self._row_to_agent_private,
            coerce_named_row=self._coerce_named_row,
            main_chat_virtual_agent=self._main_chat_virtual_agent,
            agent_id_factory=lambda name: f"agent_{legacy._slug(name, 'agent')}_{legacy.uuid4().hex[:8]}",
            normalize_execution_backend=legacy._normalize_execution_backend,
            ensure_global_name_available=self.definition_name_guard.ensure_available,
            validate_agent_profile_refs=self._validate_agent_profile_refs,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            assign_default_agent_workdir=self._assign_default_agent_workdir,
            trust_workspace_from_policy=self._trust_workspace_from_policy,
            agent_model_credential_ref=self._agent_model_credential_ref,
            store_credential=self._store_credential,
            delete_credential=self._delete_credential,
            clear_studio_deletion=self._clear_studio_deletion,
            system_agent_ids=legacy._SYSTEM_AGENT_IDS,
            main_chat_agent_id=legacy._MAIN_CHAT_AGENT_ID,
            native_skill_home=legacy._native_skill_home,
            skill_installs_native_home=self.skill_installs_native_home,
            normalize_skill_source_type=legacy._normalize_skill_source_type,
            native_library_source_types=legacy._NATIVE_LIBRARY_SOURCE_TYPES,
            workspace_dir=self.workspace_dir,
            skill_import_id_factory=lambda: legacy.uuid4().hex,
            skill_source_types=legacy._SKILL_SOURCE_TYPES,
            row_to_workflow=self._row_to_workflow,
            workflow_id_factory=lambda name: f"workflow_{legacy._slug(name, 'workflow')}_{legacy.uuid4().hex[:8]}",
            validate_workflow=self.validate_workflow,
            validate_workflow_agent_nodes=self._validate_workflow_agent_nodes,
            validate_workflow_subworkflow_nodes=self._validate_workflow_subworkflow_nodes,
        )
        self._install_runtime_definition_services(definition_services)

    def _install_runtime_run_layer(self) -> None:
        setup = build_runtime_run_layer_setup(
            conn=self._conn,
            db_lock=self._db_lock,
            ensure_row_factory=self._ensure_row_factory,
            row_to_run_group=self._row_to_run_group,
            row_to_run=self._row_to_run,
            agent_artifacts_dir=self.agent_artifacts_dir,
            workflow_artifacts_dir=self.workflow_artifacts_dir,
            get_run=self.get_run,
            task_run_links=self.task_run_links,
            accepting_runs=lambda: self._accepting_runs,
            append_run_to_group=self._append_run_to_group,
            get_run_group=self.get_run_group,
            insert_run_group=self._insert_run_group,
            insert_run=self._insert_run,
            run_by_client_request_id=self._run_by_client_request_id,
            client_request_id_from_payload=self.run_request_parser.client_request_id_from_payload,
            agent_workspace_dir=self._agent_workspace_dir,
            get_agent_private=lambda agent_id: self._get_agent_private(agent_id),
            validate_agent_run_readiness=lambda agent: self._validate_agent_run_readiness(agent),
            execute_agent_run=lambda run_id, agent, user_goal, **kwargs: self._execute_agent_run(
                run_id,
                agent,
                user_goal,
                **kwargs,
            ),
            project_agent_run_group_if_root=lambda result: self._project_agent_run_group_if_root(result),
        )
        self._install_runtime_run_services(setup.run_services)
        self.agent_run_coordinator = setup.agent_run_coordinator

    def _install_runtime_memory_and_core(self) -> Any:
        setup = build_runtime_memory_core_setup(
            conn=self._conn,
            db_lock=self._db_lock,
            run_events=self.run_events,
            profile_service_factory=lambda: _legacy_agent_runtime_module().get_model_profile_service(),
            supports_openai_compatible_api=_legacy_agent_runtime_module().supports_openai_compatible_api,
        )
        self._install_runtime_memory_services(setup.memory_services)
        self._install_runtime_core_services(setup.core_services)
        return setup.timeline_factory

    def _install_runtime_agent_chat_entrypoints(
        self,
        *,
        runtime_timeline_factory: Any,
    ) -> None:
        setup = build_runtime_agent_chat_entrypoint_setup(
            get_agent_private=lambda agent_id: self._get_agent_private(agent_id),
            validate_agent_run_readiness=lambda agent: self._validate_agent_run_readiness(agent),
            agent_run_starter=self.agent_run_starter,
            execute_agent_run=lambda run_id, agent, user_goal, **kwargs: self._execute_agent_run(
                run_id,
                agent,
                user_goal,
                **kwargs,
            ),
            project_agent_run_group_if_root=lambda result: self._project_agent_run_group_if_root(result),
            resolve_runnable=lambda **kwargs: self.resolve_runnable(**kwargs),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            runtime_agent_timeline=self.runtime_agent_timeline,
            runtime_agent_run_events=self.runtime_agent_run_events,
            call_custom_api=self.openai_compatible_chat_adapter.call,
            runs=self.runs,
            run_groups=self.run_groups,
            runtime_events=self.runtime_events,
            run_artifacts=self.run_artifacts,
            agent_workspaces_dir=self.agent_workspaces_dir,
            agent_artifacts_dir=self.agent_artifacts_dir,
            memory_store=self._memory_store,
            future_task_store=self._future_task_store,
            insert_run=self._insert_run,
            link_task_run=self.link_task_run,
            get_run=self.get_run,
            task_run_links=self.task_run_links,
            runtime_task_events=self.runtime_task_events,
            runtime_timeline_factory=runtime_timeline_factory,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            trust_workspace_from_policy=self._trust_workspace_from_policy,
            profile_service_factory=lambda: _legacy_agent_runtime_module().get_model_profile_service(),
            workspace_status=lambda: _legacy_agent_runtime_module().get_workspace_status(),
        )
        self.agent_run_async_coordinator = setup.agent_run_async_coordinator
        self.agent_model_tester = setup.agent_model_tester
        self._install_runtime_run_timeline(setup.run_timeline)
        self._install_runtime_main_chat_config(setup.main_chat_config)
        self.main_chat_virtual_agent_projector = setup.main_chat_virtual_agent_projector
        self._install_runtime_tool_brokers(setup.tool_brokers)
        self._install_runtime_main_chat_runs(setup.main_chat_runs)

    def _install_runtime_run_budget_and_main_chat_model(
        self,
        *,
        runtime_timeline_factory: Any,
    ) -> tuple[Any, Any]:
        setup = build_runtime_main_chat_model_setup(
            runtime_limits=lambda: self.runtime_limits,
            get_run=self.get_run,
            default_profile_id=lambda capability: str(
                _legacy_agent_runtime_module().get_model_profile_service().get_defaults().get(capability) or ""
            ).strip(),
            model_profile_config_private=lambda profile_id, capability="chat": self._model_profile_config_private(
                profile_id,
                capability=capability,
            ),
            runtime_timeline_factory=runtime_timeline_factory,
            update_run=self._update_run,
            append_run_event=self.append_run_event,
            task_model_events=self.runtime_task_model_events,
            call_model=self.model_profile_chat_adapter.call,
            terminal_run_or_none=self.terminal_run_resolver.terminal_run_or_none,
        )
        self.runtime_run_budget = setup.run_budget
        self._install_runtime_main_chat_model(setup.main_chat_model)
        return setup.context_budget_checker, setup.model_output_limiter

    def _install_runtime_tooling_and_custom_agent_loop(
        self,
        *,
        runtime_timeline_factory: Any,
        runtime_context_budget_checker: Any,
        runtime_model_output_limiter: Any,
    ) -> None:
        tooling_stack = build_runtime_tooling_stack(
            runtime_limits=lambda: self.runtime_limits,
            runtime_run_budget=self.runtime_run_budget,
            runtime_timeline_factory=runtime_timeline_factory,
            runtime_context_budget_checker=runtime_context_budget_checker,
            runtime_model_output_limiter=runtime_model_output_limiter,
            tool_call_events=self.runtime_tool_call_events,
            trace_events=self.runtime_trace_events,
            append_run_event=self.append_run_event,
            pending_approval_builder=self.tool_pending_approvals,
            call_agent_tool=self._call_agent_tool,
            agent_model_config_private=self._agent_model_config_private,
            compile_agent_runtime=self._compile_agent_runtime,
            call_model=self.model_profile_chat_adapter.call,
            tool_requests_from_message=self._tool_requests_from_message,
            run_tool_requests=self._run_tool_requests,
        )
        self._install_runtime_tooling(tooling_stack.tooling)
        self.tool_operations = tooling_stack.tool_operations
        self._install_runtime_custom_api_agent_loop(tooling_stack.custom_api_agent_loop)

    def _install_runtime_agent_and_approval_services(
        self,
        *,
        runtime_timeline_factory: Any,
    ) -> None:
        legacy = _legacy_agent_runtime_module()
        agent_services = legacy._build_runtime_agent_services(
            get_skill=self.get_skill,
            error_type=legacy.AgentRuntimeError,
            compile_agent_runtime=self._compile_agent_runtime,
            load_agent_skills=self._load_agent_skills,
            long_term_memory_context=self._long_term_memory_context,
            operating_doctrine=legacy._MARKET_AGENT_OPERATING_DOCTRINE,
            agent_artifacts_dir=self.agent_artifacts_dir,
            normalize_execution_backend=legacy._normalize_execution_backend,
            agent_context=self._agent_context,
            memory_store=self._memory_store,
            future_task_store=self._future_task_store,
            runtime_agent_timeline=self.runtime_agent_timeline,
            runtime_agent_run_events=self.runtime_agent_run_events,
            runtime_trace_events=self.runtime_trace_events,
            append_run_event=self.append_run_event,
            timeline_factory=runtime_timeline_factory,
            memory_context_limit=legacy._MEMORY_CONTEXT_LIMIT,
            runtime_task_model_events=self.runtime_task_model_events,
            update_run=self._update_run,
            model_output_metadata=legacy._model_output_metadata,
            redact_secrets=legacy.redact_secrets,
            tool_brokers=self.tool_brokers,
        )
        self._install_runtime_agent_services(agent_services)
        approval_services = legacy._build_runtime_approval_services(
            timeline_factory=runtime_timeline_factory,
            append_run_event=self.append_run_event,
            update_run=self._update_run,
            snapshots=self.approval_snapshots,
            call_agent_tool=self._call_agent_tool,
            fatal_tool_failure_detail=self._fatal_tool_failure_detail,
            append_tool_result_message=self._append_tool_result_message,
            run_tool_requests=self._run_tool_requests,
            claim_pending_approval=self.run_approvals.claim_pending_approval,
            continue_custom_api_agent=self._run_custom_api_agent,
        )
        self._install_runtime_approval_services(approval_services)
        self.agent_run_executor = legacy.RuntimeAgentRunExecutor(
            preparer=self.agent_run_preparer,
            continue_custom_api_agent=self._run_custom_api_agent,
            agent_run_outcomes=self.agent_run_outcomes,
            approval_pause=self.approval_pause,
        )

    def _install_runtime_approval_runtime_services(self) -> None:
        setup = build_runtime_approval_runtime_services(
            get_run=lambda run_id: self.get_run(run_id),
            pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
            approvals=self.approvals,
            project_child_run_transition=lambda result: self._project_child_run_transition(result),
            project_cancelled_workflow_group_if_root=lambda run, result: self._project_cancelled_workflow_group_if_root(
                run,
                result,
            ),
            cancel_run=lambda run_id: self.cancel_run(run_id),
            get_agent_private=lambda agent_id: self._get_agent_private(agent_id),
            compile_agent_runtime=lambda agent: self._compile_agent_runtime(agent),
            load_agent_skills=lambda skill_ids: self._load_agent_skills(skill_ids),
            tool_brokers=self.tool_brokers,
            run_budget=self.runtime_run_budget,
            resume_approved_tool_run=lambda **kwargs: self._resume_approved_tool_run(**kwargs),
            main_chat_agent_config=lambda **kwargs: self._main_chat_agent_config(**kwargs),
            main_chat_pending_approval=lambda pending_approval, **kwargs: self._main_chat_pending_approval(
                pending_approval,
                **kwargs,
            ),
            default_chat_profile_id=lambda: str(
                _legacy_agent_runtime_module().get_model_profile_service().get_defaults().get("chat") or ""
            ).strip(),
            project_agent_running=lambda running: self._project_agent_approval_resume_running(running),
            project_agent_completed=lambda context, result_text: self._project_agent_approval_resume_completed(
                context,
                result_text,
            ),
            project_main_chat_completed=lambda context, result_text: self._project_main_chat_approval_resume_completed(
                context,
                result_text,
            ),
            approve_workflow_run=lambda run: self._approve_workflow_run_approval(run),
            approve_main_chat_run=lambda run: self._approve_main_chat_run_approval(run),
            execution_lock=self._approval_execution_lock,
            execution_in_progress=self._approval_execution_in_progress,
        )
        self._install_runtime_approval_transitions(setup.approval_transitions)
        self._install_runtime_tool_approval_resume(setup.tool_approval_resume)
        self.approval_resume_dispatcher = setup.approval_resume_dispatcher
        self.approval_execution = setup.approval_execution

    def _install_runtime_main_chat_model_loop_runner(
        self,
        *,
        runtime_timeline_factory: Any,
        runtime_context_budget_checker: Any,
    ) -> None:
        self._install_runtime_main_chat_model_loop(
            build_runtime_main_chat_model_loop_runner(
                get_run=self.get_run,
                profile_service_factory=lambda: _legacy_agent_runtime_module().get_model_profile_service(),
                model_profile_config_private=lambda profile_id: self._model_profile_config_private(
                    profile_id,
                    capability="chat",
                ),
                main_chat_agent_config=self._main_chat_agent_config,
                compile_agent_runtime=self._compile_agent_runtime,
                run_budget=self.runtime_run_budget,
                check_context_budget=runtime_context_budget_checker,
                runtime_agent_timeline=self.runtime_agent_timeline,
                timeline_factory=runtime_timeline_factory,
                update_run=self._update_run,
                append_run_event=self.append_run_event,
                task_model_events=self.runtime_task_model_events,
                tool_brokers=self.tool_brokers,
                continue_custom_api_agent=self._run_custom_api_agent,
                main_chat_pending_approval=self._main_chat_pending_approval,
                approval_pause=self.approval_pause,
                terminal_run_or_none=self.terminal_run_resolver.terminal_run_or_none,
            )
        )

    def _install_runtime_workflow_planning_and_coordinator(
        self,
        *,
        runtime_timeline_factory: Any,
    ) -> None:
        legacy = _legacy_agent_runtime_module()
        workflow_planning_services = legacy._build_runtime_workflow_planning_services(
            get_run_group=self.get_run_group,
            get_run=self.get_run,
            node_kind=self._node_kind,
            node_types=legacy._WORKFLOW_NODE_TYPES,
            get_agent_private=self._get_agent_private,
            get_workflow=self.get_workflow,
            load_agent_skills=self._load_agent_skills,
            agent_model_config_private=self._agent_model_config_private,
            default_agent_ids=legacy._DEFAULT_AGENT_IDS,
            timeline_factory=runtime_timeline_factory,
            workflow_path_snapshot=self._workflow_path_snapshot,
            workflow_runtime_snapshot=self._workflow_runtime_snapshot,
            insert_run_group=self._insert_run_group,
            insert_run=self._insert_run,
            run_by_client_request_id=self._run_by_client_request_id,
            client_request_id_from_payload=self.run_request_parser.client_request_id_from_payload,
            workflow_path=self._workflow_path,
        )
        self._install_runtime_workflow_planning_services(workflow_planning_services)
        self.workflow_run_coordinator = legacy.RuntimeWorkflowRunCoordinator(
            get_workflow=lambda workflow_id: self.get_workflow(workflow_id),
            validate_workflow=lambda nodes, edges: self.validate_workflow(nodes, edges),
            validate_workflow_agent_nodes=lambda nodes: self._validate_workflow_agent_nodes(nodes),
            validate_workflow_subworkflow_nodes=lambda nodes, **kwargs: (
                self._validate_workflow_subworkflow_nodes(nodes, **kwargs)
            ),
            validate_workflow_runnable_steps=lambda nodes: self._validate_workflow_runnable_steps(nodes),
            validate_workflow_agent_run_readiness=lambda nodes: self._validate_workflow_agent_run_readiness(nodes),
            starter=self.workflow_run_starter,
            start_projector=self.workflow_run_start_projector,
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            continue_workflow_run=lambda run, workflow, **kwargs: self._continue_workflow_run(
                run,
                workflow,
                **kwargs,
            ),
            lock=self._db_lock,
            error_type=legacy.AgentRuntimeError,
        )

    def _install_runtime_workflow_execution_and_async(
        self,
        *,
        runtime_timeline_factory: Any,
    ) -> None:
        legacy = _legacy_agent_runtime_module()
        workflow_execution_services = legacy._build_runtime_workflow_execution_services(
            engine=self,
            iso_epoch=lambda value: legacy._iso_epoch(value),
            workflow_path=self.workflow_path_planner.workflow_path,
            workflow_nodes_by_id=self.workflow_path_planner.nodes_by_id,
            workflow_next_node_id=self.workflow_path_planner.next_node_id,
            workflow_parallel_plan=self.workflow_path_planner.parallel_plan,
            workflow_condition_selection=self.workflow_path_planner.condition_selection,
            workflow_loop_selection=self.workflow_path_planner.loop_selection,
            workflow_loop_iterations_from_timeline=(
                self.workflow_path_planner.loop_iterations_from_timeline
            ),
            workflow_loop_step_limit=self.workflow_path_planner.loop_step_limit,
            workflow_run_started_projection=self.workflow_run_start_projector.started_projection,
            workflow_artifact_write=lambda run, artifact_path, context: (
                self.tool_brokers.for_run(
                    run_id=str(run.get("run_id") or ""),
                    workspace_policy=self._default_workspace_policy(),
                    artifacts_dir=self.workflow_artifacts_dir,
                ).artifact_write(artifact_path, context)
            ),
            claim_pending_approval=self.run_approvals.claim_pending_approval,
            get_current_run=lambda run_id: self.get_run(run_id),
            pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
            get_run=lambda run_id: self.get_run(run_id),
            merge_workflow_child_run_outcome=lambda timeline, artifacts, child_run, label: (
                self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
            ),
            timeline_factory=runtime_timeline_factory,
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
            approve_workflow_node=lambda run_id, **kwargs: self.approvals.approve_workflow_node(run_id, **kwargs),
        )
        self._install_runtime_workflow_execution_services(workflow_execution_services)
        self.workflow_run_async_coordinator = legacy.RuntimeWorkflowRunAsyncCoordinator(
            get_workflow=lambda workflow_id: self.get_workflow(workflow_id),
            validate_workflow=lambda nodes, edges: self.validate_workflow(nodes, edges),
            validate_workflow_agent_nodes=lambda nodes: self._validate_workflow_agent_nodes(nodes),
            validate_workflow_subworkflow_nodes=lambda nodes, **kwargs: (
                self._validate_workflow_subworkflow_nodes(nodes, **kwargs)
            ),
            validate_workflow_runnable_steps=lambda nodes: self._validate_workflow_runnable_steps(nodes),
            validate_workflow_agent_run_readiness=lambda nodes: self._validate_workflow_agent_run_readiness(nodes),
            starter=self.workflow_run_starter,
            start_projector=self.workflow_run_start_projector,
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            continue_workflow_run=lambda run, workflow, **kwargs: self._continue_workflow_run(
                run,
                workflow,
                **kwargs,
            ),
            project_background_failure=lambda run, **kwargs: self.workflow_continuation.project_background_failure(
                run,
                **kwargs,
            ),
            resolve_runnable=lambda **kwargs: self.resolve_runnable(**kwargs),
            error_type=legacy.AgentRuntimeError,
        )
        self.workflow_approval_execution = legacy.RuntimeWorkflowApprovalExecutionService(
            pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
            workflow_for_run_resume=lambda run: self._workflow_for_run_resume(run),
            workflow_run_is_group_root=lambda run: self._workflow_run_is_group_root(run),
            workflow_approval_resume=self.workflow_approval_resume,
        )

    def _install_runtime_runnable_entrypoints(self) -> None:
        legacy = _legacy_agent_runtime_module()
        self.runnable_resolver = legacy.RuntimeRunnableResolver(
            main_chat_agent_id=legacy._MAIN_CHAT_AGENT_ID,
            main_chat_virtual_agent=self._main_chat_virtual_agent,
            ensure_row_factory=self._ensure_row_factory,
            fetch_agent_by_id=lambda agent_id: self._conn.execute(
                "SELECT * FROM agents WHERE agent_id=?",
                (agent_id,),
            ).fetchone(),
            fetch_workflow_by_id=lambda workflow_id: self._conn.execute(
                "SELECT * FROM workflows WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone(),
            fetch_agents_by_name=lambda name: self._conn.execute(
                "SELECT * FROM agents WHERE LOWER(name)=LOWER(?) OR LOWER(nickname)=LOWER(?)",
                (name, name),
            ).fetchall(),
            fetch_workflow_by_name=lambda name: self._conn.execute(
                "SELECT * FROM workflows WHERE LOWER(name)=LOWER(?)",
                (name,),
            ).fetchone(),
            row_to_agent=self._row_to_agent,
            row_to_workflow=self._row_to_workflow,
            agent_summary=self._agent_runnable_summary,
            workflow_summary=self._workflow_runnable_summary,
            error_type=legacy.AgentRuntimeError,
        )
        runnable_services = legacy._build_runtime_runnable_services(
            conn=self._conn,
            db_lock=self._db_lock,
            create_run_for_runnable=lambda **kwargs: self.create_run_for_runnable(**kwargs),
            future_task_store=lambda **kwargs: self._future_task_store(**kwargs),
            now=legacy._now,
            redact_secrets=legacy.redact_secrets,
            error_type=legacy.AgentRuntimeError,
            list_runnables=lambda: list(self.list_runnables().get("runnables") or []),
            node_kind=self._node_kind,
            get_agent=self.get_agent,
            resolve_runnable=self.runnable_resolver.resolve,
            create_agent_run=self.create_agent_run,
            create_workflow_run=self.create_workflow_run,
            create_agent_run_async=self.create_agent_run_async,
            create_workflow_run_async=self.create_workflow_run_async,
        )
        self._install_runtime_runnable_services(runnable_services)
        self.future_task_service = legacy.RuntimeFutureTaskService(
            future_task_store=lambda **kwargs: self._future_task_store(**kwargs),
            resolve_runnable=self.runnable_resolver.resolve,
            trigger_scheduler=self.future_task_scheduler,
            default_runnable_id=legacy._MAIN_CHAT_AGENT_ID,
            error_type=legacy.AgentRuntimeError,
        )
        self.agent_run_group_projection = legacy.AgentRunGroupProjectionCoordinator(
            get_run_group=lambda run_group_id: self.get_run_group(run_group_id),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(
                run_group_id,
                **kwargs,
            ),
        )

    def _install_runtime_workflow_transitions(
        self,
        *,
        runtime_timeline_factory: Any,
    ) -> None:
        legacy = _legacy_agent_runtime_module()
        workflow_transition_services = legacy._build_runtime_workflow_transition_services(
            parent_runs_waiting_for_child=lambda child_run: self._workflow_parent_runs_waiting_for_child(child_run),
            workflow_run_is_group_root=lambda workflow_run: self._workflow_run_is_group_root(workflow_run),
            workflow_child_node_context=lambda timeline, child_run: self._workflow_child_node_context(
                timeline,
                child_run,
            ),
            merge_workflow_child_run_outcome=lambda timeline, artifacts, child_run, label: (
                self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
            ),
            workflow_for_run_resume=lambda workflow_run: self._workflow_for_run_resume(workflow_run),
            workflow_resume_start_index=lambda workflow, workflow_run, child_run_id: (
                self._workflow_resume_start_index(workflow, workflow_run, child_run_id)
            ),
            workflow_next_node_id=lambda workflow, node_id, context: (
                self._workflow_next_node_id(workflow, node_id, context)
            ),
            continue_workflow_run=lambda run, workflow, **kwargs: self.workflow_continuation.continue_run(
                run,
                workflow,
                **kwargs,
            ),
            timeline_factory=runtime_timeline_factory,
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
            update_agent_run_group_if_root=lambda run: self._update_agent_run_group_if_root(run),
            mark_parent_workflows_child_running=lambda run: self._mark_parent_workflows_child_running(run),
            resume_parent_workflows_after_child_update=lambda run: self._resume_parent_workflows_after_child_update(run),
            get_run=lambda run_id: self.get_run(run_id),
        )
        self._install_runtime_workflow_transition_services(workflow_transition_services)

    def _install_runtime_run_control_and_shutdown(
        self,
        *,
        runtime_timeline_factory: Any,
    ) -> None:
        legacy = _legacy_agent_runtime_module()
        self._install_runtime_run_cancellation(
            legacy.RuntimeRunCancellationService(
                get_run=lambda run_id: self.get_run(run_id),
                update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
                append_run_event=lambda run_id, event_type, payload: self.append_run_event(
                    run_id,
                    event_type,
                    payload,
                ),
                timeline_factory=runtime_timeline_factory,
                workflow_cancellation=self.workflow_cancellation,
                workflow_run_is_group_root=lambda result: self._workflow_run_is_group_root(result),
                project_cancelled_workflow_group_if_root=lambda run, result: (
                    self._project_cancelled_workflow_group_if_root(run, result)
                ),
                resume_parent_workflows_after_child_update=lambda projected: (
                    self._resume_parent_workflows_after_child_update(projected)
                ),
                project_child_run_transition=lambda result: self._project_child_run_transition(result),
                final_statuses=legacy._FINAL_RUN_STATUSES,
            )
        )
        self._install_runtime_run_rerun(
            legacy.RuntimeRunRerunService(
                get_run=lambda run_id: self.get_run(run_id),
                create_agent_run=lambda payload: self.create_agent_run(payload),
                create_workflow_run=lambda payload: self.create_workflow_run(payload),
                timeline_factory=runtime_timeline_factory,
                append_run_event=lambda run_id, event_type, payload: self.append_run_event(
                    run_id,
                    event_type,
                    payload,
                ),
                update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
                resolve_runnable=lambda **kwargs: self.resolve_runnable(**kwargs),
                final_statuses=legacy._FINAL_RUN_STATUSES,
                error_type=legacy.AgentRuntimeError,
            )
        )
        self._install_runtime_run_deletion(
            legacy.RuntimeRunDeletionService(
                get_run=lambda run_id: self.get_run(run_id),
                group_runs=lambda run_group_id: self.run_groups.runs(run_group_id),
                delete_run_rows=lambda targets, **kwargs: self.runs.delete_rows(
                    targets,
                    **kwargs,
                ),
                delete_artifacts=lambda *args, **kwargs: self.run_artifacts.delete_files(
                    *args,
                    **kwargs,
                ),
                delete_group=lambda run_group_id: self.run_groups.delete(run_group_id),
                remove_group_run_ids=lambda run_group_id, deleted_ids: (
                    self.run_groups.remove_run_ids(run_group_id, deleted_ids)
                ),
                commit=lambda: self._conn.commit(),
                is_active_run_status=legacy._is_active_run_status,
                error_type=legacy.AgentRuntimeError,
            )
        )
        self._install_runtime_shutdown(
            legacy.RuntimeShutdownService(
                conn=self._conn,
                credential_store=self._credential_store,
                is_closed=lambda: self._closed,
                mark_not_accepting=lambda: setattr(self, "_accepting_runs", False),
                mark_closed=lambda: setattr(self, "_closed", True),
                cancel_terminal_process_groups=lambda: legacy.cancel_terminal_process_groups(),
                ensure_row_factory=lambda: self._ensure_row_factory(),
                cancel_run=lambda run_id: self.cancel_run(run_id),
            )
        )

    def _install_runtime_post_db_support_services(self, *, seed_templates: bool) -> None:
        legacy = _legacy_agent_runtime_module()
        self.workspace_policy_service = legacy.RuntimeWorkspacePolicyService(
            conn=self._conn,
            agent_workspaces_dir=self.agent_workspaces_dir,
            trusted_workspaces=self.trusted_workspaces,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            default_workspace_policy=self._default_workspace_policy,
            json_load=legacy._json_load,
            json_dump=legacy._json_dump,
            now=legacy._now,
        )
        self._migrate_agent_workspace_policies()
        self.seed_template_service = legacy.RuntimeSeedTemplateService(
            conn=self._conn,
            create_agent=self.create_agent,
            create_workflow=self.create_workflow,
            default_tool_policy=self._default_tool_policy,
            default_workspace_policy=self._default_workspace_policy,
            has_studio_deletion=self._has_studio_deletion,
        )
        self.skill_import_service = legacy.RuntimeSkillImportService(
            conn=self._conn,
            source_resolver=self.skill_import_sources,
            preparer=self.skill_import_preparer,
            skill_records=self.skill_records,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            skill_deletion_key=self._skill_deletion_key,
            clear_studio_deletion=self._clear_studio_deletion,
            get_skill=self.get_skill,
            error_type=legacy.AgentRuntimeError,
        )
        self.skill_sync_service = legacy.RuntimeSkillSyncService(
            conn=self._conn,
            skill_sync=self.skill_sync,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            skill_deletion_key=self._skill_deletion_key,
            has_studio_deletion=self._has_studio_deletion,
            clear_studio_deletion=self._clear_studio_deletion,
            import_skill_root=self._import_skill_root,
            now=legacy._now,
            redact_error=legacy.redact_api_error_text,
            error_type=legacy.AgentRuntimeError,
        )
        self.skill_install_service = legacy.RuntimeSkillInstallService(
            validator=self.skill_install_validator,
            skill_installs_dir=self.skill_installs_dir,
            skill_installs_native_home=self.skill_installs_native_home,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            sync_installed_skills=self.sync_installed_skills,
            run_command=lambda *args, **kwargs: legacy.subprocess.run(*args, **kwargs),
            now=legacy._now,
            redact_secrets=legacy.redact_secrets,
            error_type=legacy.AgentRuntimeError,
        )
        if seed_templates:
            self._seed_templates()

    def _install_runtime_engine_state(self, state: Any) -> None:
        self.workspace_dir = state.workspace_dir
        self.db_path = state.db_path
        self._credential_store = state.credential_store
        self.skills_dir = state.skills_dir
        self.skill_installs_dir = state.skill_installs_dir
        self.skill_installs_native_home = state.skill_installs_native_home
        self.agent_artifacts_dir = state.agent_artifacts_dir
        self.workflow_artifacts_dir = state.workflow_artifacts_dir
        self.agent_workspaces_dir = state.agent_workspaces_dir
        self._accepting_runs = state.accepting_runs
        self._closed = state.closed
        self.runtime_limits = state.runtime_limits
        self._db_lock = state.db_lock
        self._approval_execution_lock = state.approval_execution_lock
        self._approval_execution_in_progress = state.approval_execution_in_progress
        self._run_cancel_locks = state.run_cancel_locks
        self._run_cancel_locks_guard = state.run_cancel_locks_guard
        self._conn = state.conn
        self.runtime_credentials = RuntimeCredentialService(state.credential_store)

    def _install_runtime_recorders(self, recorders: Any) -> None:
        self.tool_request_parser = recorders.tool_request_parser
        self.runtime_agent_run_events = recorders.runtime_agent_run_events
        self.tool_event_payloads = recorders.tool_event_payloads
        self.runtime_tool_call_events = recorders.runtime_tool_call_events
        self.runtime_task_model_events = recorders.runtime_task_model_events
        self.runtime_task_events = recorders.runtime_task_events
        self.runtime_trace_events = recorders.runtime_trace_events
        self.tool_pending_approvals = recorders.tool_pending_approvals

    def _install_runtime_definition_services(self, services: Any) -> None:
        self.task_run_links = services.task_run_links
        self.trusted_workspaces = services.trusted_workspaces
        self.studio_deletions = services.studio_deletions
        self.skill_folders = services.skill_folders
        self.skill_records = services.skill_records
        self.agent_definitions = services.agent_definitions
        self.agent_skill_attachments = services.agent_skill_attachments
        self.skill_install_validator = services.skill_install_validator
        self.skill_sources = services.skill_sources
        self.skill_content = services.skill_content
        self.skill_import_sources = services.skill_import_sources
        self.skill_import_preparer = services.skill_import_preparer
        self.skill_sync = services.skill_sync
        self.workflows = services.workflows

    def _install_runtime_run_services(self, services: Any) -> None:
        self.approval_snapshots = services.approval_snapshots
        self.run_groups = services.run_groups
        self.run_approvals = services.run_approvals
        self.run_artifacts = services.run_artifacts
        self.run_projections = services.run_projections
        self.runs = services.runs
        self.run_events = services.run_events
        self.agent_run_starter = services.agent_run_starter

    def _install_runtime_memory_services(self, memory_services: Any) -> None:
        self.memory_services = memory_services

    def _install_runtime_core_services(self, core_services: Any) -> None:
        self.runtime_events = core_services.runtime_events
        self.runtime_agent_timeline = core_services.runtime_agent_timeline
        self.runtime_policy = core_services.runtime_policy
        self.model_profile_resolver = core_services.model_profile_resolver

    def _install_runtime_run_timeline(self, run_timeline: Any) -> None:
        self.run_timeline = run_timeline

    def _install_runtime_main_chat_config(self, main_chat_config: Any) -> None:
        self.main_chat_config = main_chat_config

    def _install_runtime_tool_brokers(self, tool_brokers: Any) -> None:
        self.tool_brokers = tool_brokers

    def _install_runtime_main_chat_runs(self, main_chat_runs: Any) -> None:
        self.main_chat_runs = main_chat_runs

    def _install_runtime_main_chat_model(self, main_chat_model: Any) -> None:
        self.main_chat_model = main_chat_model

    def _install_runtime_main_chat_model_loop(self, main_chat_model_loop: Any) -> None:
        self.main_chat_model_loop = main_chat_model_loop

    def _install_runtime_tooling(self, tooling: Any) -> None:
        self.tool_loop_projection = tooling.tool_loop_projection
        self.tool_call_executor = tooling.tool_call_executor
        self.tool_request_runner = tooling.tool_request_runner

    def _install_runtime_custom_api_agent_loop(self, custom_api_agent_loop: Any) -> None:
        self.custom_api_agent_loop = custom_api_agent_loop

    def _install_runtime_agent_services(self, agent_services: Any) -> None:
        self.agent_skill_loader = agent_services.agent_skill_loader
        self.agent_context_builder = agent_services.agent_context_builder
        self.agent_run_preparer = agent_services.agent_run_preparer
        self.agent_run_outcomes = agent_services.agent_run_outcomes

    def _install_runtime_approval_services(self, approval_services: Any) -> None:
        self.approval_pause = approval_services.approval_pause
        self.approvals = approval_services.approvals
        self.approval_resume = approval_services.approval_resume

    def _install_runtime_approval_transitions(self, approval_transitions: Any) -> None:
        self.approval_transitions = approval_transitions

    def _install_runtime_tool_approval_resume(self, tool_approval_resume: Any) -> None:
        self.tool_approval_resume = tool_approval_resume

    def _install_runtime_workflow_execution_services(self, workflow_services: Any) -> None:
        self.workflow_continuation = workflow_services.workflow_continuation
        self.workflow_approval_resume = workflow_services.workflow_approval_resume
        self.workflow_cancellation = workflow_services.workflow_cancellation
        self.workflow_child_outcomes = workflow_services.workflow_child_outcomes

    def _install_runtime_workflow_planning_services(self, workflow_services: Any) -> None:
        self.workflow_parent_locator = workflow_services.workflow_parent_locator
        self.workflow_path_planner = workflow_services.workflow_path_planner
        self.workflow_definition_validator = workflow_services.workflow_definition_validator
        self.run_readiness_validator = workflow_services.run_readiness_validator
        self.workflow_run_start_projector = workflow_services.workflow_run_start_projector
        self.workflow_run_starter = workflow_services.workflow_run_starter
        self.workflow_resume_planner = workflow_services.workflow_resume_planner

    def _install_runtime_runnable_services(self, runnable_services: Any) -> None:
        self.future_task_scheduler = runnable_services.future_task_scheduler
        self.chat_runnable_parser = runnable_services.chat_runnable_parser
        self.runnable_catalog = runnable_services.runnable_catalog
        self.runnable_run_coordinator = runnable_services.runnable_run_coordinator

    def _install_runtime_workflow_transition_services(self, workflow_services: Any) -> None:
        self.workflow_parent_resume = workflow_services.workflow_parent_resume
        self.approval_resume_projection = workflow_services.approval_resume_projection
        self.run_transition_projection = workflow_services.run_transition_projection

    def _install_runtime_run_cancellation(self, run_cancellation: Any) -> None:
        self.run_cancellation = run_cancellation
        self.run_cancellation_coordinator = RuntimeRunCancellationCoordinator(
            cancel_once=self.run_cancellation.cancel_once,
            run_cancel_locks=self._run_cancel_locks,
            run_cancel_locks_guard=self._run_cancel_locks_guard,
        )

    def _install_runtime_run_rerun(self, run_rerun: Any) -> None:
        self.run_rerun = run_rerun

    def _install_runtime_run_deletion(self, run_deletion: Any) -> None:
        self.run_deletion = run_deletion

    def _install_runtime_shutdown(self, shutdown: Any) -> None:
        self.runtime_shutdown = shutdown
