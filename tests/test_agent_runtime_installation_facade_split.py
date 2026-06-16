"""Tests for runtime installation facade methods split out of the legacy runtime."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from apps.shell import agent_runtime
from apps.shell.agent.runtime import installation_facade as installation_facade_mod
from apps.shell.agent.runtime.credentials import RuntimeCredentialService
from apps.shell.agent.runtime.engine_state import build_runtime_engine_state
from apps.shell.agent.runtime.installation_facade import RuntimeInstallationFacadeMixin
from apps.shell.agent.runtime.model_calling import (
    RuntimeModelProfileChatAdapter,
    RuntimeOpenAICompatibleChatAdapter,
)
from apps.shell.agent.runtime.run_cancellation import RuntimeRunCancellationCoordinator
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_installation_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeInstallationFacadeMixin is RuntimeInstallationFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeInstallationFacadeMixin)
    for method_name in (
        "_install_runtime_model_adapters",
        "_install_runtime_foundation",
        "_install_runtime_definition_layer",
        "_install_runtime_run_layer",
        "_install_runtime_memory_and_core",
        "_install_runtime_agent_chat_entrypoints",
        "_install_runtime_run_budget_and_main_chat_model",
        "_install_runtime_tooling_and_custom_agent_loop",
        "_install_runtime_agent_and_approval_services",
        "_install_runtime_approval_runtime_services",
        "_install_runtime_main_chat_model_loop_runner",
        "_install_runtime_workflow_planning_and_coordinator",
        "_install_runtime_workflow_execution_and_async",
        "_install_runtime_runnable_entrypoints",
        "_install_runtime_workflow_transitions",
        "_install_runtime_run_control_and_shutdown",
        "_install_runtime_post_db_support_services",
        "_install_runtime_engine_state",
        "_install_runtime_recorders",
        "_install_runtime_definition_services",
        "_install_runtime_run_services",
        "_install_runtime_memory_services",
        "_install_runtime_core_services",
        "_install_runtime_run_timeline",
        "_install_runtime_main_chat_config",
        "_install_runtime_tool_brokers",
        "_install_runtime_main_chat_runs",
        "_install_runtime_main_chat_model",
        "_install_runtime_main_chat_model_loop",
        "_install_runtime_tooling",
        "_install_runtime_custom_api_agent_loop",
        "_install_runtime_agent_services",
        "_install_runtime_approval_services",
        "_install_runtime_approval_transitions",
        "_install_runtime_tool_approval_resume",
        "_install_runtime_workflow_execution_services",
        "_install_runtime_workflow_planning_services",
        "_install_runtime_runnable_services",
        "_install_runtime_workflow_transition_services",
        "_install_runtime_run_cancellation",
        "_install_runtime_run_rerun",
        "_install_runtime_run_deletion",
        "_install_runtime_shutdown",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_installation_facade_installs_model_adapters(monkeypatch) -> None:
    calls: list[tuple[str, str, str, list[dict[str, str]]]] = []

    def fake_chat(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
        **_kwargs,
    ) -> dict[str, str]:
        calls.append((base_url, model, api_key, messages))
        return {"content": "patched"}

    monkeypatch.setattr(agent_runtime, "openai_compatible_chat_message", fake_chat)
    engine = object.__new__(agent_runtime.NativeRunEngine)

    engine._install_runtime_model_adapters()

    assert isinstance(engine.model_profile_chat_adapter, RuntimeModelProfileChatAdapter)
    assert isinstance(engine.openai_compatible_chat_adapter, RuntimeOpenAICompatibleChatAdapter)
    assert engine.model_profile_chat_adapter.call(
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hi"}],
    ) == {"content": "patched"}
    assert calls == [
        (
            "https://api.example.test/v1",
            "demo-model",
            "sk-test",
            [{"role": "user", "content": "hi"}],
        )
    ]


def test_installation_facade_installs_engine_state_under_legacy_attributes(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    state = build_runtime_engine_state(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=credential_store,
    )
    engine = object.__new__(agent_runtime.NativeRunEngine)
    try:
        engine._install_runtime_engine_state(state)

        assert engine.workspace_dir == state.workspace_dir
        assert engine.db_path == state.db_path
        assert engine._credential_store is credential_store
        assert engine.skills_dir == state.skills_dir
        assert engine.agent_artifacts_dir == state.agent_artifacts_dir
        assert engine.workflow_artifacts_dir == state.workflow_artifacts_dir
        assert engine.runtime_limits is state.runtime_limits
        assert engine._conn is state.conn
        assert isinstance(engine.runtime_credentials, RuntimeCredentialService)
    finally:
        state.conn.close()
        credential_store.close()


def test_installation_facade_installs_definition_layer_from_split_builder(monkeypatch) -> None:
    def forbidden_legacy_builder(**_kwargs):
        raise AssertionError("definition layer should use split installation builder")

    def fake_build_runtime_definition_services(**kwargs):
        return SimpleNamespace(
            task_run_links=SimpleNamespace(kwargs=kwargs),
            trusted_workspaces="trusted-workspaces",
            studio_deletions="studio-deletions",
            skill_folders="skill-folders",
            skill_records="skill-records",
            agent_definitions="agent-definitions",
            agent_skill_attachments="agent-skill-attachments",
            skill_install_validator="skill-install-validator",
            skill_sources="skill-sources",
            skill_content="skill-content",
            skill_import_sources="skill-import-sources",
            skill_import_preparer="skill-import-preparer",
            skill_sync="skill-sync",
            workflows="workflows",
        )

    monkeypatch.setattr(agent_runtime, "_build_runtime_definition_services", forbidden_legacy_builder)
    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_definition_services",
        fake_build_runtime_definition_services,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine._conn = "conn"
    engine._ensure_row_factory = "ensure-row-factory"
    engine.get_run = "get-run"
    engine._row_to_skill_folder = "row-to-skill-folder"
    engine.delete_skill = "delete-skill"
    engine._row_to_skill = "row-to-skill"
    engine._normalize_skill_folder_id = "normalize-skill-folder-id"
    engine._installed_skill_source_map = "installed-skill-source-map"
    engine._record_studio_deletion = "record-studio-deletion"
    engine._skill_deletion_key = "skill-deletion-key"
    engine.skills_dir = "skills-dir"
    engine.skill_installs_dir = "skill-installs-dir"
    engine._row_to_agent = "row-to-agent"
    engine._row_to_agent_private = "row-to-agent-private"
    engine._coerce_named_row = "coerce-named-row"
    engine._main_chat_virtual_agent = "main-chat-virtual-agent"
    engine.definition_name_guard = SimpleNamespace(ensure_available="ensure-available")
    engine._validate_agent_profile_refs = "validate-agent-profile-refs"
    engine._compile_tool_policy = "compile-tool-policy"
    engine._compile_workspace_policy = "compile-workspace-policy"
    engine._assign_default_agent_workdir = "assign-default-agent-workdir"
    engine._trust_workspace_from_policy = "trust-workspace-from-policy"
    engine._agent_model_credential_ref = "agent-model-credential-ref"
    engine._store_credential = "store-credential"
    engine._delete_credential = "delete-credential"
    engine._clear_studio_deletion = "clear-studio-deletion"
    engine.skill_installs_native_home = "skill-installs-native-home"
    engine.workspace_dir = "workspace-dir"
    engine._row_to_workflow = "row-to-workflow"
    engine.validate_workflow = "validate-workflow"
    engine._validate_workflow_agent_nodes = "validate-workflow-agent-nodes"
    engine._validate_workflow_subworkflow_nodes = "validate-workflow-subworkflow-nodes"

    engine._install_runtime_definition_layer()

    kwargs = engine.task_run_links.kwargs
    assert kwargs["conn"] == "conn"
    assert kwargs["now"] is installation_facade_mod.utc_now_iso
    assert kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert kwargs["slug"] is installation_facade_mod.slug
    assert kwargs["json_dump"] is installation_facade_mod.json_dump_sorted
    assert kwargs["json_load"] is installation_facade_mod.json_load
    assert kwargs["system_agent_ids"] is installation_facade_mod.SYSTEM_AGENT_IDS
    assert kwargs["main_chat_agent_id"] == installation_facade_mod.MAIN_CHAT_AGENT_ID
    assert kwargs["native_skill_home"] is installation_facade_mod.native_skill_home
    assert kwargs["normalize_execution_backend"] is installation_facade_mod.normalize_execution_backend
    assert kwargs["normalize_skill_source_type"] is installation_facade_mod.normalize_skill_source_type
    assert engine.agent_definitions == "agent-definitions"
    assert engine.workflows == "workflows"


def test_installation_facade_installs_cancellation_and_service_bundles() -> None:
    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine._run_cancel_locks = {}
    engine._run_cancel_locks_guard = threading.RLock()
    run_cancellation = SimpleNamespace(cancel_once=lambda run_id: {"run_id": run_id})
    runnable_services = SimpleNamespace(
        future_task_scheduler="future",
        chat_runnable_parser="parser",
        runnable_catalog="catalog",
        runnable_run_coordinator="coordinator",
    )

    engine._install_runtime_run_cancellation(run_cancellation)
    engine._install_runtime_runnable_services(runnable_services)

    assert engine.run_cancellation is run_cancellation
    assert isinstance(engine.run_cancellation_coordinator, RuntimeRunCancellationCoordinator)
    assert engine.run_cancellation_coordinator._cancel_once is run_cancellation.cancel_once
    assert engine.future_task_scheduler == "future"
    assert engine.chat_runnable_parser == "parser"
    assert engine.runnable_catalog == "catalog"
    assert engine.runnable_run_coordinator == "coordinator"


def test_installation_facade_installs_agent_chat_entrypoints(monkeypatch) -> None:
    def fake_build_runtime_agent_chat_entrypoint_setup(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            agent_run_async_coordinator=SimpleNamespace(kwargs=kwargs),
            agent_model_tester=SimpleNamespace(kwargs=kwargs),
            run_timeline=SimpleNamespace(kwargs=kwargs),
            main_chat_config=SimpleNamespace(kwargs=kwargs),
            main_chat_virtual_agent_projector=SimpleNamespace(kwargs=kwargs),
            tool_brokers=SimpleNamespace(kwargs=kwargs),
            main_chat_runs=SimpleNamespace(kwargs=kwargs),
        )

    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_agent_chat_entrypoint_setup",
        fake_build_runtime_agent_chat_entrypoint_setup,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.agent_run_starter = "starter"
    engine.runtime_agent_timeline = "agent-timeline"
    engine.runtime_agent_run_events = "agent-run-events"
    engine.openai_compatible_chat_adapter = SimpleNamespace(call="custom-api-call")
    engine.runs = "runs"
    engine.run_groups = "run-groups"
    engine.runtime_events = "runtime-events"
    engine.run_artifacts = "run-artifacts"
    engine.agent_workspaces_dir = "agent-workspaces"
    engine.agent_artifacts_dir = "agent-artifacts"
    engine._memory_store = "memory-store"
    engine._future_task_store = "future-task-store"
    engine._insert_run = "insert-run"
    engine.link_task_run = "link-task-run"
    engine.get_run = "get-run"
    engine._update_run = "update-run"
    engine.task_run_links = "task-run-links"
    engine.runtime_task_events = "task-events"

    engine._install_runtime_agent_chat_entrypoints(
        runtime_timeline_factory="timeline-factory",
    )

    assert engine.agent_run_async_coordinator.kwargs["agent_run_starter"] == "starter"
    assert engine.agent_model_tester.kwargs["call_custom_api"] == "custom-api-call"
    assert engine.run_timeline.kwargs["runs"] == "runs"
    assert engine.main_chat_config.kwargs["agent_workspaces_dir"] == "agent-workspaces"
    assert engine.tool_brokers.kwargs["memory_store"] == "memory-store"
    assert engine.main_chat_runs.kwargs["runtime_timeline_factory"] == "timeline-factory"


def test_installation_facade_installs_run_budget_and_main_chat_model(monkeypatch) -> None:
    def fake_build_runtime_main_chat_model_setup(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            context_budget_checker="context-checker",
            model_output_limiter="output-limiter",
            run_budget="run-budget",
            main_chat_model=SimpleNamespace(kwargs=kwargs),
        )

    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_main_chat_model_setup",
        fake_build_runtime_main_chat_model_setup,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.runtime_limits = "runtime-limits"
    engine.get_run = "get-run"
    engine._update_run = "update-run"
    engine.append_run_event = "append-run-event"
    engine.runtime_task_model_events = "task-model-events"
    engine.model_profile_chat_adapter = SimpleNamespace(call="model-call")
    engine.terminal_run_resolver = SimpleNamespace(terminal_run_or_none="terminal-run-or-none")

    context_checker, output_limiter = engine._install_runtime_run_budget_and_main_chat_model(
        runtime_timeline_factory="timeline-factory",
    )

    assert context_checker == "context-checker"
    assert output_limiter == "output-limiter"
    assert engine.runtime_run_budget == "run-budget"
    assert engine.main_chat_model.kwargs["runtime_timeline_factory"] == "timeline-factory"
    assert engine.main_chat_model.kwargs["get_run"] == "get-run"
    assert engine.main_chat_model.kwargs["call_model"] == "model-call"
    assert engine.main_chat_model.kwargs["terminal_run_or_none"] == "terminal-run-or-none"


def test_installation_facade_installs_tooling_and_custom_agent_loop(monkeypatch) -> None:
    def fake_build_runtime_tooling_stack(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            tooling=SimpleNamespace(
                kwargs=kwargs,
                tool_loop_projection="tool-loop-projection",
                tool_call_executor="tool-call-executor",
                tool_request_runner="tool-request-runner",
            ),
            tool_operations=SimpleNamespace(
                tool_request_runner="tool-request-runner",
                tool_call_executor="tool-call-executor",
            ),
            custom_api_agent_loop=SimpleNamespace(
                kwargs=kwargs,
                run_budget=kwargs["runtime_run_budget"],
                check_context_budget=kwargs["runtime_context_budget_checker"],
                limit_model_output=kwargs["runtime_model_output_limiter"],
            ),
        )

    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_tooling_stack",
        fake_build_runtime_tooling_stack,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.runtime_run_budget = "run-budget"
    engine.runtime_limits = "runtime-limits"
    engine.runtime_tool_call_events = "tool-call-events"
    engine.runtime_trace_events = "trace-events"
    engine.append_run_event = "append-run-event"
    engine.tool_pending_approvals = "pending-approval-builder"
    engine._call_agent_tool = "call-agent-tool"
    engine._agent_model_config_private = "agent-model-config-private"
    engine._compile_agent_runtime = "compile-agent-runtime"
    engine.model_profile_chat_adapter = SimpleNamespace(call="model-call")
    engine._tool_requests_from_message = "tool-requests-from-message"
    engine._run_tool_requests = "run-tool-requests"

    engine._install_runtime_tooling_and_custom_agent_loop(
        runtime_timeline_factory="timeline-factory",
        runtime_context_budget_checker="context-budget-checker",
        runtime_model_output_limiter="model-output-limiter",
    )

    assert engine.tool_loop_projection == "tool-loop-projection"
    assert engine.tool_call_executor == "tool-call-executor"
    assert engine.tool_request_runner == "tool-request-runner"
    assert engine.tool_operations.tool_request_runner == "tool-request-runner"
    assert engine.tool_operations.tool_call_executor == "tool-call-executor"
    assert engine.custom_api_agent_loop.run_budget == "run-budget"
    assert engine.custom_api_agent_loop.check_context_budget == "context-budget-checker"
    assert engine.custom_api_agent_loop.limit_model_output == "model-output-limiter"
    assert engine.custom_api_agent_loop.kwargs["runtime_timeline_factory"] == "timeline-factory"
    assert engine.custom_api_agent_loop.kwargs["call_model"] == "model-call"


def test_installation_facade_installs_tooling_bundle_attributes() -> None:
    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine._install_runtime_tooling(
        SimpleNamespace(
            tool_loop_projection="tool-loop-projection",
            tool_call_executor="tool-call-executor",
            tool_request_runner="tool-request-runner",
        )
    )

    assert engine.tool_loop_projection == "tool-loop-projection"
    assert engine.tool_call_executor == "tool-call-executor"
    assert engine.tool_request_runner == "tool-request-runner"


def test_installation_facade_installs_agent_and_approval_services(monkeypatch) -> None:
    class CapturedAgentRunExecutor:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def forbidden_agent_builder(**_kwargs):
        raise AssertionError("agent services should use split installation builder")

    def forbidden_approval_builder(**_kwargs):
        raise AssertionError("approval services should use split installation builder")

    def fake_build_runtime_agent_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            agent_skill_loader="agent-skill-loader",
            agent_context_builder="agent-context-builder",
            agent_run_preparer=SimpleNamespace(kwargs=kwargs),
            agent_run_outcomes="agent-run-outcomes",
        )

    def fake_build_runtime_approval_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            approval_pause="approval-pause",
            approvals="approvals",
            approval_resume="approval-resume",
        )

    monkeypatch.setattr(agent_runtime, "_build_runtime_agent_services", forbidden_agent_builder)
    monkeypatch.setattr(agent_runtime, "_build_runtime_approval_services", forbidden_approval_builder)
    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_agent_services",
        fake_build_runtime_agent_services,
    )
    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_approval_services",
        fake_build_runtime_approval_services,
    )
    monkeypatch.setattr(installation_facade_mod, "RuntimeAgentRunExecutor", CapturedAgentRunExecutor)

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.get_skill = "get-skill"
    engine._compile_agent_runtime = "compile-agent-runtime"
    engine._load_agent_skills = "load-agent-skills"
    engine._long_term_memory_context = "long-term-memory-context"
    engine.agent_artifacts_dir = "agent-artifacts"
    engine._agent_context = "agent-context"
    engine._memory_store = "memory-store"
    engine._future_task_store = "future-task-store"
    engine.runtime_agent_timeline = "agent-timeline"
    engine.runtime_agent_run_events = "agent-run-events"
    engine.runtime_trace_events = "trace-events"
    engine.append_run_event = "append-run-event"
    engine.runtime_task_model_events = "task-model-events"
    engine._update_run = "update-run"
    engine.tool_brokers = "tool-brokers"
    engine.approval_snapshots = "approval-snapshots"
    engine._call_agent_tool = "call-agent-tool"
    engine._fatal_tool_failure_detail = "fatal-tool-failure-detail"
    engine._append_tool_result_message = "append-tool-result-message"
    engine._run_tool_requests = "run-tool-requests"
    engine.run_approvals = SimpleNamespace(claim_pending_approval="claim-pending-approval")
    engine._run_custom_api_agent = "run-custom-api-agent"

    engine._install_runtime_agent_and_approval_services(
        runtime_timeline_factory="timeline-factory",
    )

    assert engine.agent_skill_loader == "agent-skill-loader"
    assert engine.agent_context_builder == "agent-context-builder"
    assert engine.agent_run_preparer.kwargs["get_skill"] == "get-skill"
    assert engine.agent_run_outcomes == "agent-run-outcomes"
    assert engine.agent_run_preparer.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert (
        engine.agent_run_preparer.kwargs["operating_doctrine"]
        == installation_facade_mod.MARKET_AGENT_OPERATING_DOCTRINE
    )
    assert engine.agent_run_preparer.kwargs["memory_context_limit"] == installation_facade_mod.MEMORY_CONTEXT_LIMIT
    assert (
        engine.agent_run_preparer.kwargs["normalize_execution_backend"]
        is installation_facade_mod.normalize_execution_backend
    )
    assert (
        engine.agent_run_preparer.kwargs["model_output_metadata"]
        is installation_facade_mod.model_output_metadata
    )
    assert engine.agent_run_preparer.kwargs["redact_secrets"] is installation_facade_mod.redact_secrets
    assert engine.approval_pause == "approval-pause"
    assert engine.approvals == "approvals"
    assert engine.approval_resume == "approval-resume"
    assert isinstance(engine.agent_run_executor, CapturedAgentRunExecutor)
    assert engine.agent_run_executor.kwargs["preparer"] is engine.agent_run_preparer
    assert engine.agent_run_executor.kwargs["continue_custom_api_agent"] == "run-custom-api-agent"
    assert engine.agent_run_executor.kwargs["approval_pause"] == "approval-pause"


def test_installation_facade_installs_approval_runtime_services(monkeypatch) -> None:
    def fake_build_runtime_approval_runtime_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            approval_transitions=SimpleNamespace(kwargs=kwargs),
            tool_approval_resume=SimpleNamespace(kwargs=kwargs, approve_agent_run="approve-agent-run"),
            approval_resume_dispatcher=SimpleNamespace(kwargs=kwargs, approve_once="approve-once"),
            approval_execution=SimpleNamespace(kwargs=kwargs),
        )

    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_approval_runtime_services",
        fake_build_runtime_approval_runtime_services,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.get_run = "get-run"
    engine.runs = SimpleNamespace(pending_approval_private="pending-approval-private")
    engine.approvals = "approvals"
    engine.cancel_run = "cancel-run"
    engine.tool_brokers = "tool-brokers"
    engine.runtime_run_budget = "run-budget"
    engine._approval_execution_lock = "approval-execution-lock"
    engine._approval_execution_in_progress = "approval-execution-in-progress"

    engine._install_runtime_approval_runtime_services()

    assert engine.approval_transitions.kwargs["approvals"] == "approvals"
    assert engine.tool_approval_resume.kwargs["tool_brokers"] == "tool-brokers"
    assert engine.tool_approval_resume.kwargs["run_budget"] == "run-budget"
    assert "approve_workflow_run" in engine.approval_resume_dispatcher.kwargs
    assert "approve_main_chat_run" in engine.approval_resume_dispatcher.kwargs
    assert engine.tool_approval_resume.approve_agent_run == "approve-agent-run"
    assert engine.approval_resume_dispatcher.approve_once == "approve-once"
    assert engine.approval_execution.kwargs["execution_lock"] == "approval-execution-lock"


def test_installation_facade_installs_main_chat_model_loop_runner(monkeypatch) -> None:
    def fake_build_runtime_main_chat_model_loop_runner(**kwargs):
        return SimpleNamespace(kwargs=kwargs)

    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_main_chat_model_loop_runner",
        fake_build_runtime_main_chat_model_loop_runner,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.get_run = "get-run"
    engine._model_profile_config_private = "model-profile-config-private"
    engine._main_chat_agent_config = "main-chat-agent-config"
    engine._compile_agent_runtime = "compile-agent-runtime"
    engine.runtime_run_budget = "runtime-run-budget"
    engine.runtime_agent_timeline = "runtime-agent-timeline"
    engine._update_run = "update-run"
    engine.append_run_event = "append-run-event"
    engine.runtime_task_model_events = "task-model-events"
    engine.tool_brokers = "tool-brokers"
    engine._run_custom_api_agent = "run-custom-api-agent"
    engine._main_chat_pending_approval = "main-chat-pending-approval"
    engine.approval_pause = "approval-pause"
    engine.terminal_run_resolver = SimpleNamespace(terminal_run_or_none="terminal-run-or-none")

    engine._install_runtime_main_chat_model_loop_runner(
        runtime_timeline_factory="timeline-factory",
        runtime_context_budget_checker="context-budget-checker",
    )

    assert engine.main_chat_model_loop.kwargs["get_run"] == "get-run"
    assert engine.main_chat_model_loop.kwargs["run_budget"] == "runtime-run-budget"
    assert engine.main_chat_model_loop.kwargs["check_context_budget"] == "context-budget-checker"
    assert engine.main_chat_model_loop.kwargs["timeline_factory"] == "timeline-factory"
    assert engine.main_chat_model_loop.kwargs["tool_brokers"] == "tool-brokers"
    assert engine.main_chat_model_loop.kwargs["approval_pause"] == "approval-pause"
    assert engine.main_chat_model_loop.kwargs["terminal_run_or_none"] == "terminal-run-or-none"


def test_installation_facade_installs_workflow_planning_and_coordinator(monkeypatch) -> None:
    class CapturedWorkflowRunCoordinator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyWorkflowRunCoordinator:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("workflow coordinator should use split installation class")

    def forbidden_workflow_planning_builder(**_kwargs):
        raise AssertionError("workflow planning should use split installation builder")

    def fake_build_runtime_workflow_planning_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            workflow_parent_locator=SimpleNamespace(kwargs=kwargs),
            workflow_path_planner="workflow-path-planner",
            workflow_definition_validator="workflow-definition-validator",
            run_readiness_validator="run-readiness-validator",
            workflow_run_start_projector="workflow-run-start-projector",
            workflow_run_starter="workflow-run-starter",
            workflow_resume_planner="workflow-resume-planner",
        )

    monkeypatch.setattr(
        agent_runtime,
        "_build_runtime_workflow_planning_services",
        forbidden_workflow_planning_builder,
    )
    monkeypatch.setattr(
        agent_runtime,
        "RuntimeWorkflowRunCoordinator",
        ForbiddenLegacyWorkflowRunCoordinator,
    )
    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_workflow_planning_services",
        fake_build_runtime_workflow_planning_services,
    )
    monkeypatch.setattr(
        installation_facade_mod,
        "RuntimeWorkflowRunCoordinator",
        CapturedWorkflowRunCoordinator,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.get_run_group = "get-run-group"
    engine.get_run = "get-run"
    engine._node_kind = "node-kind"
    engine._get_agent_private = "get-agent-private"
    engine.get_workflow = "get-workflow"
    engine._load_agent_skills = "load-agent-skills"
    engine._agent_model_config_private = "agent-model-config-private"
    engine._workflow_path_snapshot = "workflow-path-snapshot"
    engine._workflow_runtime_snapshot = "workflow-runtime-snapshot"
    engine._insert_run_group = "insert-run-group"
    engine._insert_run = "insert-run"
    engine._run_by_client_request_id = "run-by-client-request-id"
    engine.run_request_parser = SimpleNamespace(client_request_id_from_payload="client-request-id-from-payload")
    engine._workflow_path = "workflow-path"
    engine.validate_workflow = "validate-workflow"
    engine._validate_workflow_agent_nodes = "validate-workflow-agent-nodes"
    engine._validate_workflow_subworkflow_nodes = "validate-workflow-subworkflow-nodes"
    engine._validate_workflow_runnable_steps = "validate-workflow-runnable-steps"
    engine._validate_workflow_agent_run_readiness = "validate-workflow-agent-run-readiness"
    engine.append_run_event = "append-run-event"
    engine._continue_workflow_run = "continue-workflow-run"
    engine._db_lock = "db-lock"

    engine._install_runtime_workflow_planning_and_coordinator(
        runtime_timeline_factory="timeline-factory",
    )

    assert engine.workflow_parent_locator.kwargs["get_run"] == "get-run"
    assert engine.workflow_path_planner == "workflow-path-planner"
    assert engine.workflow_parent_locator.kwargs["node_types"] is installation_facade_mod.WORKFLOW_NODE_TYPES
    assert engine.workflow_parent_locator.kwargs["default_agent_ids"] is installation_facade_mod.DEFAULT_AGENT_IDS
    assert engine.workflow_definition_validator == "workflow-definition-validator"
    assert engine.run_readiness_validator == "run-readiness-validator"
    assert engine.workflow_run_start_projector == "workflow-run-start-projector"
    assert engine.workflow_run_starter == "workflow-run-starter"
    assert engine.workflow_resume_planner == "workflow-resume-planner"
    assert isinstance(engine.workflow_run_coordinator, CapturedWorkflowRunCoordinator)
    assert engine.workflow_run_coordinator.kwargs["starter"] == "workflow-run-starter"
    assert engine.workflow_run_coordinator.kwargs["start_projector"] == "workflow-run-start-projector"
    assert engine.workflow_run_coordinator.kwargs["lock"] == "db-lock"
    assert engine.workflow_run_coordinator.kwargs["error_type"] is agent_runtime.AgentRuntimeError


def test_installation_facade_installs_workflow_execution_and_async(monkeypatch) -> None:
    class CapturedWorkflowRunAsyncCoordinator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyWorkflowRunAsyncCoordinator:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("workflow async coordinator should use split installation class")

    class CapturedWorkflowApprovalExecution:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyWorkflowApprovalExecution:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("workflow approval execution should use split installation class")

    def forbidden_workflow_execution_builder(**_kwargs):
        raise AssertionError("workflow execution should use split installation builder")

    def fake_build_runtime_workflow_execution_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            workflow_continuation=SimpleNamespace(
                kwargs=kwargs,
                project_background_failure="project-background-failure",
            ),
            workflow_approval_resume="workflow-approval-resume",
            workflow_cancellation="workflow-cancellation",
            workflow_child_outcomes="workflow-child-outcomes",
        )

    monkeypatch.setattr(
        agent_runtime,
        "_build_runtime_workflow_execution_services",
        forbidden_workflow_execution_builder,
    )
    monkeypatch.setattr(
        agent_runtime,
        "RuntimeWorkflowRunAsyncCoordinator",
        ForbiddenLegacyWorkflowRunAsyncCoordinator,
    )
    monkeypatch.setattr(
        agent_runtime,
        "RuntimeWorkflowApprovalExecutionService",
        ForbiddenLegacyWorkflowApprovalExecution,
    )
    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_workflow_execution_services",
        fake_build_runtime_workflow_execution_services,
    )
    monkeypatch.setattr(
        installation_facade_mod,
        "RuntimeWorkflowRunAsyncCoordinator",
        CapturedWorkflowRunAsyncCoordinator,
    )
    monkeypatch.setattr(
        installation_facade_mod,
        "RuntimeWorkflowApprovalExecutionService",
        CapturedWorkflowApprovalExecution,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.workflow_path_planner = SimpleNamespace(
        workflow_path="workflow-path",
        nodes_by_id="nodes-by-id",
        next_node_id="next-node-id",
        parallel_plan="parallel-plan",
        condition_selection="condition-selection",
        loop_selection="loop-selection",
        loop_iterations_from_timeline="loop-iterations-from-timeline",
        loop_step_limit="loop-step-limit",
    )
    engine.workflow_run_start_projector = SimpleNamespace(started_projection="started-projection")
    engine.tool_brokers = "tool-brokers"
    engine.workflow_artifacts_dir = "workflow-artifacts"
    engine.run_approvals = SimpleNamespace(claim_pending_approval="claim-pending-approval")
    engine.get_run = "get-run"
    engine.runs = SimpleNamespace(pending_approval_private="pending-approval-private")
    engine._merge_workflow_child_run_outcome = "merge-workflow-child-run-outcome"
    engine.append_run_event = "append-run-event"
    engine._update_run = "update-run"
    engine._update_run_group = "update-run-group"
    engine.approvals = SimpleNamespace(approve_workflow_node="approve-workflow-node")
    engine.get_workflow = "get-workflow"
    engine.validate_workflow = "validate-workflow"
    engine._validate_workflow_agent_nodes = "validate-workflow-agent-nodes"
    engine._validate_workflow_subworkflow_nodes = "validate-workflow-subworkflow-nodes"
    engine._validate_workflow_runnable_steps = "validate-workflow-runnable-steps"
    engine._validate_workflow_agent_run_readiness = "validate-workflow-agent-run-readiness"
    engine.workflow_run_starter = "workflow-run-starter"
    engine._continue_workflow_run = "continue-workflow-run"
    engine.resolve_runnable = "resolve-runnable"
    engine._workflow_for_run_resume = "workflow-for-run-resume"
    engine._workflow_run_is_group_root = "workflow-run-is-group-root"

    engine._install_runtime_workflow_execution_and_async(
        runtime_timeline_factory="timeline-factory",
    )

    assert engine.workflow_continuation.project_background_failure == "project-background-failure"
    assert engine.workflow_continuation.kwargs["iso_epoch"] is installation_facade_mod.iso_epoch
    assert engine.workflow_approval_resume == "workflow-approval-resume"
    assert engine.workflow_cancellation == "workflow-cancellation"
    assert engine.workflow_child_outcomes == "workflow-child-outcomes"
    assert isinstance(engine.workflow_run_async_coordinator, CapturedWorkflowRunAsyncCoordinator)
    assert engine.workflow_run_async_coordinator.kwargs["starter"] == "workflow-run-starter"
    assert engine.workflow_run_async_coordinator.kwargs["start_projector"] is engine.workflow_run_start_projector
    assert "project_background_failure" in engine.workflow_run_async_coordinator.kwargs
    assert engine.workflow_run_async_coordinator.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert isinstance(engine.workflow_approval_execution, CapturedWorkflowApprovalExecution)
    assert (
        engine.workflow_approval_execution.kwargs["workflow_approval_resume"]
        == "workflow-approval-resume"
    )


def test_installation_facade_installs_runnable_entrypoints(monkeypatch) -> None:
    class CapturedRunnableResolver:
        resolve = "resolve-runnable"

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyRunnableResolver:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("runnable resolver should use split installation class")

    class CapturedFutureTaskService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyFutureTaskService:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("future task service should use split installation class")

    class CapturedAgentRunGroupProjection:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyAgentRunGroupProjection:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("agent run group projection should use split installation class")

    def forbidden_runnable_builder(**_kwargs):
        raise AssertionError("runnable services should use split installation builder")

    def fake_build_runtime_runnable_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            future_task_scheduler=SimpleNamespace(kwargs=kwargs),
            chat_runnable_parser="chat-runnable-parser",
            runnable_catalog="runnable-catalog",
            runnable_run_coordinator="runnable-run-coordinator",
        )

    monkeypatch.setattr(agent_runtime, "RuntimeRunnableResolver", ForbiddenLegacyRunnableResolver)
    monkeypatch.setattr(agent_runtime, "_build_runtime_runnable_services", forbidden_runnable_builder)
    monkeypatch.setattr(agent_runtime, "RuntimeFutureTaskService", ForbiddenLegacyFutureTaskService)
    monkeypatch.setattr(agent_runtime, "AgentRunGroupProjectionCoordinator", ForbiddenLegacyAgentRunGroupProjection)
    monkeypatch.setattr(installation_facade_mod, "RuntimeRunnableResolver", CapturedRunnableResolver)
    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_runnable_services",
        fake_build_runtime_runnable_services,
    )
    monkeypatch.setattr(installation_facade_mod, "RuntimeFutureTaskService", CapturedFutureTaskService)
    monkeypatch.setattr(
        installation_facade_mod,
        "AgentRunGroupProjectionCoordinator",
        CapturedAgentRunGroupProjection,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine._main_chat_virtual_agent = "main-chat-virtual-agent"
    engine._ensure_row_factory = "ensure-row-factory"
    engine._conn = "conn"
    engine._row_to_agent = "row-to-agent"
    engine._row_to_workflow = "row-to-workflow"
    engine._agent_runnable_summary = "agent-runnable-summary"
    engine._workflow_runnable_summary = "workflow-runnable-summary"
    engine._db_lock = "db-lock"
    engine.create_run_for_runnable = "create-run-for-runnable"
    engine._node_kind = "node-kind"
    engine.get_agent = "get-agent"
    engine.create_agent_run = "create-agent-run"
    engine.create_workflow_run = "create-workflow-run"
    engine.create_agent_run_async = "create-agent-run-async"
    engine.create_workflow_run_async = "create-workflow-run-async"
    engine.get_run_group = "get-run-group"
    engine._update_run_group = "update-run-group"

    engine._install_runtime_runnable_entrypoints()

    assert isinstance(engine.runnable_resolver, CapturedRunnableResolver)
    assert engine.runnable_resolver.kwargs["main_chat_agent_id"] == installation_facade_mod.MAIN_CHAT_AGENT_ID
    assert engine.runnable_resolver.kwargs["main_chat_virtual_agent"] == "main-chat-virtual-agent"
    assert engine.runnable_resolver.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert engine.future_task_scheduler.kwargs["conn"] == "conn"
    assert engine.chat_runnable_parser == "chat-runnable-parser"
    assert engine.runnable_catalog == "runnable-catalog"
    assert engine.runnable_run_coordinator == "runnable-run-coordinator"
    assert engine.future_task_scheduler.kwargs["now"] is installation_facade_mod.utc_now_iso
    assert engine.future_task_scheduler.kwargs["redact_secrets"] is installation_facade_mod.redact_secrets
    assert engine.future_task_scheduler.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert isinstance(engine.future_task_service, CapturedFutureTaskService)
    assert engine.future_task_service.kwargs["resolve_runnable"] == "resolve-runnable"
    assert engine.future_task_service.kwargs["trigger_scheduler"] is engine.future_task_scheduler
    assert engine.future_task_service.kwargs["default_runnable_id"] == installation_facade_mod.MAIN_CHAT_AGENT_ID
    assert engine.future_task_service.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert isinstance(engine.agent_run_group_projection, CapturedAgentRunGroupProjection)
    assert "get_run_group" in engine.agent_run_group_projection.kwargs
    assert "update_run_group" in engine.agent_run_group_projection.kwargs


def test_installation_facade_installs_workflow_transitions(monkeypatch) -> None:
    def forbidden_workflow_transition_builder(**_kwargs):
        raise AssertionError("workflow transitions should use split installation builder")

    def fake_build_runtime_workflow_transition_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            workflow_parent_resume=SimpleNamespace(kwargs=kwargs),
            approval_resume_projection="approval-resume-projection",
            run_transition_projection="run-transition-projection",
        )

    monkeypatch.setattr(
        agent_runtime,
        "_build_runtime_workflow_transition_services",
        forbidden_workflow_transition_builder,
    )
    monkeypatch.setattr(
        installation_facade_mod,
        "build_runtime_workflow_transition_services",
        fake_build_runtime_workflow_transition_services,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine.workflow_continuation = SimpleNamespace(continue_run="continue-run")
    engine.append_run_event = "append-run-event"
    engine._update_run = "update-run"
    engine._update_run_group = "update-run-group"
    engine._update_agent_run_group_if_root = "update-agent-run-group-if-root"
    engine._mark_parent_workflows_child_running = "mark-parent-workflows-child-running"
    engine._resume_parent_workflows_after_child_update = "resume-parent-workflows-after-child-update"
    engine.get_run = "get-run"

    engine._install_runtime_workflow_transitions(
        runtime_timeline_factory="timeline-factory",
    )

    assert engine.workflow_parent_resume.kwargs["timeline_factory"] == "timeline-factory"
    assert callable(engine.workflow_parent_resume.kwargs["get_run"])
    assert engine.approval_resume_projection == "approval-resume-projection"
    assert engine.run_transition_projection == "run-transition-projection"


def test_installation_facade_installs_run_control_and_shutdown(monkeypatch) -> None:
    class CapturedRunCancellation:
        cancel_once = "cancel-once"

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class CapturedCollaborator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyCollaborator:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("run control should use split installation classes")

    def fake_cancel_terminal_process_groups() -> None:
        return None

    monkeypatch.setattr(agent_runtime, "RuntimeRunCancellationService", ForbiddenLegacyCollaborator)
    monkeypatch.setattr(agent_runtime, "RuntimeRunRerunService", ForbiddenLegacyCollaborator)
    monkeypatch.setattr(agent_runtime, "RuntimeRunDeletionService", ForbiddenLegacyCollaborator)
    monkeypatch.setattr(agent_runtime, "RuntimeShutdownService", ForbiddenLegacyCollaborator)
    monkeypatch.setattr(installation_facade_mod, "RuntimeRunCancellationService", CapturedRunCancellation)
    monkeypatch.setattr(installation_facade_mod, "RuntimeRunRerunService", CapturedCollaborator)
    monkeypatch.setattr(installation_facade_mod, "RuntimeRunDeletionService", CapturedCollaborator)
    monkeypatch.setattr(installation_facade_mod, "RuntimeShutdownService", CapturedCollaborator)
    monkeypatch.setattr(
        installation_facade_mod,
        "cancel_terminal_process_groups",
        fake_cancel_terminal_process_groups,
    )

    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine._run_cancel_locks = {}
    engine._run_cancel_locks_guard = threading.RLock()
    engine.get_run = "get-run"
    engine._update_run = "update-run"
    engine.append_run_event = "append-run-event"
    engine.workflow_cancellation = "workflow-cancellation"
    engine.create_agent_run = "create-agent-run"
    engine.create_workflow_run = "create-workflow-run"
    engine.resolve_runnable = "resolve-runnable"
    engine.run_groups = SimpleNamespace(
        runs="group-runs",
        delete="delete-group",
        remove_run_ids="remove-run-ids",
    )
    engine.runs = SimpleNamespace(delete_rows="delete-run-rows")
    engine.run_artifacts = SimpleNamespace(delete_files="delete-artifacts")
    engine._conn = SimpleNamespace(commit=lambda: "commit")
    engine._credential_store = "credential-store"
    engine._closed = False
    engine.cancel_run = "cancel-run"
    engine._ensure_row_factory = "ensure-row-factory"

    engine._install_runtime_run_control_and_shutdown(
        runtime_timeline_factory="timeline-factory",
    )

    assert isinstance(engine.run_cancellation, CapturedRunCancellation)
    assert engine.run_cancellation.kwargs["workflow_cancellation"] == "workflow-cancellation"
    assert engine.run_cancellation.kwargs["timeline_factory"] == "timeline-factory"
    assert engine.run_cancellation.kwargs["final_statuses"] is installation_facade_mod.FINAL_RUN_STATUSES
    assert isinstance(engine.run_cancellation_coordinator, RuntimeRunCancellationCoordinator)
    assert engine.run_cancellation_coordinator._cancel_once == "cancel-once"
    assert isinstance(engine.run_rerun, CapturedCollaborator)
    assert callable(engine.run_rerun.kwargs["create_agent_run"])
    assert callable(engine.run_rerun.kwargs["create_workflow_run"])
    assert engine.run_rerun.kwargs["timeline_factory"] == "timeline-factory"
    assert engine.run_rerun.kwargs["final_statuses"] is installation_facade_mod.FINAL_RUN_STATUSES
    assert engine.run_rerun.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert isinstance(engine.run_deletion, CapturedCollaborator)
    assert "delete_run_rows" in engine.run_deletion.kwargs
    assert "delete_artifacts" in engine.run_deletion.kwargs
    assert engine.run_deletion.kwargs["is_active_run_status"] is installation_facade_mod.is_active_run_status
    assert engine.run_deletion.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert isinstance(engine.runtime_shutdown, CapturedCollaborator)
    assert engine.runtime_shutdown.kwargs["conn"] is engine._conn
    assert engine.runtime_shutdown.kwargs["credential_store"] == "credential-store"
    assert engine.runtime_shutdown.kwargs["cancel_terminal_process_groups"] is fake_cancel_terminal_process_groups


def test_installation_facade_installs_post_db_support_services(monkeypatch) -> None:
    class CapturedCollaborator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class ForbiddenLegacyCollaborator:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("post-db support should use split installation classes")

    def fake_run_command(*_args, **_kwargs):
        return None

    for name in (
        "RuntimeWorkspacePolicyService",
        "RuntimeSeedTemplateService",
        "RuntimeSkillImportService",
        "RuntimeSkillSyncService",
        "RuntimeSkillInstallService",
    ):
        monkeypatch.setattr(agent_runtime, name, ForbiddenLegacyCollaborator)
        monkeypatch.setattr(installation_facade_mod, name, CapturedCollaborator)
    monkeypatch.setattr(installation_facade_mod.subprocess, "run", fake_run_command)

    calls: list[str] = []
    engine = object.__new__(agent_runtime.NativeRunEngine)
    engine._conn = "conn"
    engine.agent_workspaces_dir = "agent-workspaces"
    engine.trusted_workspaces = "trusted-workspaces"
    engine._compile_tool_policy = "compile-tool-policy"
    engine._compile_workspace_policy = "compile-workspace-policy"
    engine._default_workspace_policy = "default-workspace-policy"
    engine.create_agent = "create-agent"
    engine.create_workflow = "create-workflow"
    engine._default_tool_policy = "default-tool-policy"
    engine._has_studio_deletion = "has-studio-deletion"
    engine.skill_import_sources = "skill-import-sources"
    engine.skill_import_preparer = "skill-import-preparer"
    engine.skill_records = "skill-records"
    engine._normalize_skill_folder_id = "normalize-skill-folder-id"
    engine._skill_deletion_key = "skill-deletion-key"
    engine._clear_studio_deletion = "clear-studio-deletion"
    engine.get_skill = "get-skill"
    engine.skill_sync = "skill-sync"
    engine._import_skill_root = "import-skill-root"
    engine.skill_install_validator = "skill-install-validator"
    engine.skill_installs_dir = "skill-installs"
    engine.skill_installs_native_home = "skill-installs-native-home"
    engine.sync_installed_skills = "sync-installed-skills"
    engine._migrate_agent_workspace_policies = lambda: calls.append("migrate")
    engine._seed_templates = lambda: calls.append("seed")

    engine._install_runtime_post_db_support_services(seed_templates=True)

    assert isinstance(engine.workspace_policy_service, CapturedCollaborator)
    assert engine.workspace_policy_service.kwargs["trusted_workspaces"] == "trusted-workspaces"
    assert engine.workspace_policy_service.kwargs["json_load"] is installation_facade_mod.json_load
    assert engine.workspace_policy_service.kwargs["json_dump"] is installation_facade_mod.json_dump_sorted
    assert engine.workspace_policy_service.kwargs["now"] is installation_facade_mod.utc_now_iso
    assert isinstance(engine.seed_template_service, CapturedCollaborator)
    assert engine.seed_template_service.kwargs["create_agent"] == "create-agent"
    assert isinstance(engine.skill_import_service, CapturedCollaborator)
    assert engine.skill_import_service.kwargs["source_resolver"] == "skill-import-sources"
    assert engine.skill_import_service.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert isinstance(engine.skill_sync_service, CapturedCollaborator)
    assert engine.skill_sync_service.kwargs["skill_sync"] == "skill-sync"
    assert engine.skill_sync_service.kwargs["now"] is installation_facade_mod.utc_now_iso
    assert engine.skill_sync_service.kwargs["redact_error"] is installation_facade_mod.redact_api_error_text
    assert engine.skill_sync_service.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert isinstance(engine.skill_install_service, CapturedCollaborator)
    assert engine.skill_install_service.kwargs["validator"] == "skill-install-validator"
    assert engine.skill_install_service.kwargs["run_command"] is fake_run_command
    assert engine.skill_install_service.kwargs["now"] is installation_facade_mod.utc_now_iso
    assert engine.skill_install_service.kwargs["redact_secrets"] is installation_facade_mod.redact_secrets
    assert engine.skill_install_service.kwargs["error_type"] is agent_runtime.AgentRuntimeError
    assert calls == ["migrate", "seed"]
