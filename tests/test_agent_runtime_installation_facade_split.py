"""Tests for runtime installation facade methods split out of the legacy runtime."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from apps.shell import agent_runtime
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
    class CapturedCollaborator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    for name in (
        "RuntimeAgentRunAsyncCoordinator",
        "RuntimeAgentModelTester",
        "RuntimeRunTimelineService",
        "MainChatRuntimeConfigBuilder",
        "MainChatVirtualAgentProjector",
        "RuntimeToolBrokerFactory",
        "MainChatRunLifecycle",
    ):
        monkeypatch.setattr(agent_runtime, name, CapturedCollaborator)

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

    assert isinstance(engine.agent_run_async_coordinator, CapturedCollaborator)
    assert engine.agent_run_async_coordinator.kwargs["starter"] == "starter"
    assert isinstance(engine.agent_model_tester, CapturedCollaborator)
    assert engine.agent_model_tester.kwargs["call_custom_api"] == "custom-api-call"
    assert isinstance(engine.run_timeline, CapturedCollaborator)
    assert engine.run_timeline.kwargs["runs"] == "runs"
    assert isinstance(engine.main_chat_config, CapturedCollaborator)
    assert engine.main_chat_config.kwargs["agent_workspaces_dir"] == "agent-workspaces"
    assert isinstance(engine.main_chat_virtual_agent_projector, CapturedCollaborator)
    assert isinstance(engine.tool_brokers, CapturedCollaborator)
    assert engine.tool_brokers.kwargs["memory_store"] == "memory-store"
    assert isinstance(engine.main_chat_runs, CapturedCollaborator)
    assert engine.main_chat_runs.kwargs["timeline_factory"] == "timeline-factory"


def test_installation_facade_installs_run_budget_and_main_chat_model(monkeypatch) -> None:
    class CapturedMainChatModel:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(agent_runtime, "MainChatModelCaller", CapturedMainChatModel)
    monkeypatch.setattr(
        agent_runtime,
        "_runtime_context_budget_checker",
        lambda **kwargs: ("context-checker", kwargs),
    )
    monkeypatch.setattr(
        agent_runtime,
        "_runtime_model_output_limiter",
        lambda **kwargs: ("output-limiter", kwargs),
    )
    monkeypatch.setattr(
        agent_runtime,
        "_runtime_run_budget_factory",
        lambda **kwargs: ("run-budget", kwargs),
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

    assert context_checker[0] == "context-checker"
    assert output_limiter[0] == "output-limiter"
    assert engine.runtime_run_budget[0] == "run-budget"
    assert isinstance(engine.main_chat_model, CapturedMainChatModel)
    assert engine.main_chat_model.kwargs["run_budget"] is engine.runtime_run_budget
    assert engine.main_chat_model.kwargs["check_context_budget"] is context_checker
    assert engine.main_chat_model.kwargs["limit_model_output"] is output_limiter
    assert engine.main_chat_model.kwargs["timeline_factory"] == "timeline-factory"
    assert engine.main_chat_model.kwargs["call_model"] == "model-call"
    assert engine.main_chat_model.kwargs["terminal_run_or_none"] == "terminal-run-or-none"


def test_installation_facade_installs_tooling_and_custom_agent_loop(monkeypatch) -> None:
    class CapturedRuntimeToolOperations:
        model_tool_schemas = "model-tool-schemas"

        @staticmethod
        def validate_tool_payload(payload):
            return payload

        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class CapturedCustomApiAgentLoop:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def fake_build_runtime_tooling(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            tool_loop_projection="tool-loop-projection",
            tool_call_executor="tool-call-executor",
            tool_request_runner="tool-request-runner",
        )

    monkeypatch.setattr(agent_runtime, "RuntimeToolOperations", CapturedRuntimeToolOperations)
    monkeypatch.setattr(agent_runtime, "RuntimeCustomApiAgentLoop", CapturedCustomApiAgentLoop)
    monkeypatch.setattr(agent_runtime, "_build_runtime_tooling", fake_build_runtime_tooling)
    monkeypatch.setattr(
        agent_runtime,
        "_runtime_tool_result_limiter",
        lambda **kwargs: ("tool-result-limiter", kwargs),
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
    assert isinstance(engine.tool_operations, CapturedRuntimeToolOperations)
    assert engine.tool_operations.kwargs["tool_request_runner"] == "tool-request-runner"
    assert engine.tool_operations.kwargs["tool_call_executor"] == "tool-call-executor"
    assert isinstance(engine.custom_api_agent_loop, CapturedCustomApiAgentLoop)
    assert engine.custom_api_agent_loop.kwargs["run_budget"] == "run-budget"
    assert engine.custom_api_agent_loop.kwargs["check_context_budget"] == "context-budget-checker"
    assert engine.custom_api_agent_loop.kwargs["tool_schemas"] == "model-tool-schemas"
    assert engine.custom_api_agent_loop.kwargs["limit_model_output"] == "model-output-limiter"
    assert engine.custom_api_agent_loop.kwargs["tool_loop_projection"] == "tool-loop-projection"


def test_installation_facade_installs_agent_and_approval_services(monkeypatch) -> None:
    class CapturedAgentRunExecutor:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def fake_build_runtime_agent_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            agent_skill_loader="agent-skill-loader",
            agent_context_builder="agent-context-builder",
            agent_run_preparer="agent-run-preparer",
            agent_run_outcomes="agent-run-outcomes",
        )

    def fake_build_runtime_approval_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            approval_pause="approval-pause",
            approvals="approvals",
            approval_resume="approval-resume",
        )

    monkeypatch.setattr(agent_runtime, "_build_runtime_agent_services", fake_build_runtime_agent_services)
    monkeypatch.setattr(agent_runtime, "_build_runtime_approval_services", fake_build_runtime_approval_services)
    monkeypatch.setattr(agent_runtime, "RuntimeAgentRunExecutor", CapturedAgentRunExecutor)

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
    assert engine.agent_run_preparer == "agent-run-preparer"
    assert engine.agent_run_outcomes == "agent-run-outcomes"
    assert engine.approval_pause == "approval-pause"
    assert engine.approvals == "approvals"
    assert engine.approval_resume == "approval-resume"
    assert isinstance(engine.agent_run_executor, CapturedAgentRunExecutor)
    assert engine.agent_run_executor.kwargs["preparer"] == "agent-run-preparer"
    assert engine.agent_run_executor.kwargs["continue_custom_api_agent"] == "run-custom-api-agent"
    assert engine.agent_run_executor.kwargs["approval_pause"] == "approval-pause"


def test_installation_facade_installs_approval_runtime_services(monkeypatch) -> None:
    class CapturedCollaborator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class CapturedToolApprovalResume(CapturedCollaborator):
        approve_agent_run = "approve-agent-run"

    class CapturedApprovalDispatcher(CapturedCollaborator):
        approve_once = "approve-once"

    monkeypatch.setattr(agent_runtime, "RuntimeApprovalTransitionService", CapturedCollaborator)
    monkeypatch.setattr(agent_runtime, "RuntimeToolApprovalResumeService", CapturedToolApprovalResume)
    monkeypatch.setattr(agent_runtime, "RuntimeApprovalRunDispatcher", CapturedApprovalDispatcher)
    monkeypatch.setattr(agent_runtime, "RuntimeApprovalExecutionService", CapturedCollaborator)

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

    assert isinstance(engine.approval_transitions, CapturedCollaborator)
    assert engine.approval_transitions.kwargs["approvals"] == "approvals"
    assert isinstance(engine.tool_approval_resume, CapturedToolApprovalResume)
    assert engine.tool_approval_resume.kwargs["tool_brokers"] == "tool-brokers"
    assert engine.tool_approval_resume.kwargs["run_budget"] == "run-budget"
    assert isinstance(engine.approval_resume_dispatcher, CapturedApprovalDispatcher)
    assert "approve_workflow_run" in engine.approval_resume_dispatcher.kwargs
    assert "approve_main_chat_run" in engine.approval_resume_dispatcher.kwargs
    assert "approve_agent_run" in engine.approval_resume_dispatcher.kwargs
    assert isinstance(engine.approval_execution, CapturedCollaborator)
    assert engine.approval_execution.kwargs["execution_lock"] == "approval-execution-lock"
    assert engine.approval_execution.kwargs["approve_once"] == "approve-once"


def test_installation_facade_installs_main_chat_model_loop_runner(monkeypatch) -> None:
    class CapturedMainChatModelLoopRunner:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(agent_runtime, "MainChatModelLoopRunner", CapturedMainChatModelLoopRunner)

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

    assert isinstance(engine.main_chat_model_loop, CapturedMainChatModelLoopRunner)
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

    def fake_build_runtime_workflow_planning_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            workflow_parent_locator="workflow-parent-locator",
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
        fake_build_runtime_workflow_planning_services,
    )
    monkeypatch.setattr(agent_runtime, "RuntimeWorkflowRunCoordinator", CapturedWorkflowRunCoordinator)

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

    assert engine.workflow_parent_locator == "workflow-parent-locator"
    assert engine.workflow_path_planner == "workflow-path-planner"
    assert engine.workflow_definition_validator == "workflow-definition-validator"
    assert engine.run_readiness_validator == "run-readiness-validator"
    assert engine.workflow_run_start_projector == "workflow-run-start-projector"
    assert engine.workflow_run_starter == "workflow-run-starter"
    assert engine.workflow_resume_planner == "workflow-resume-planner"
    assert isinstance(engine.workflow_run_coordinator, CapturedWorkflowRunCoordinator)
    assert engine.workflow_run_coordinator.kwargs["starter"] == "workflow-run-starter"
    assert engine.workflow_run_coordinator.kwargs["start_projector"] == "workflow-run-start-projector"
    assert engine.workflow_run_coordinator.kwargs["lock"] == "db-lock"


def test_installation_facade_installs_workflow_execution_and_async(monkeypatch) -> None:
    class CapturedWorkflowRunAsyncCoordinator:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class CapturedWorkflowApprovalExecution:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def fake_build_runtime_workflow_execution_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            workflow_continuation=SimpleNamespace(project_background_failure="project-background-failure"),
            workflow_approval_resume="workflow-approval-resume",
            workflow_cancellation="workflow-cancellation",
            workflow_child_outcomes="workflow-child-outcomes",
        )

    monkeypatch.setattr(
        agent_runtime,
        "_build_runtime_workflow_execution_services",
        fake_build_runtime_workflow_execution_services,
    )
    monkeypatch.setattr(
        agent_runtime,
        "RuntimeWorkflowRunAsyncCoordinator",
        CapturedWorkflowRunAsyncCoordinator,
    )
    monkeypatch.setattr(
        agent_runtime,
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
    assert engine.workflow_approval_resume == "workflow-approval-resume"
    assert engine.workflow_cancellation == "workflow-cancellation"
    assert engine.workflow_child_outcomes == "workflow-child-outcomes"
    assert isinstance(engine.workflow_run_async_coordinator, CapturedWorkflowRunAsyncCoordinator)
    assert engine.workflow_run_async_coordinator.kwargs["starter"] == "workflow-run-starter"
    assert engine.workflow_run_async_coordinator.kwargs["start_projector"] is engine.workflow_run_start_projector
    assert "project_background_failure" in engine.workflow_run_async_coordinator.kwargs
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

    class CapturedFutureTaskService:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    class CapturedAgentRunGroupProjection:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    def fake_build_runtime_runnable_services(**kwargs):
        return SimpleNamespace(
            kwargs=kwargs,
            future_task_scheduler="future-task-scheduler",
            chat_runnable_parser="chat-runnable-parser",
            runnable_catalog="runnable-catalog",
            runnable_run_coordinator="runnable-run-coordinator",
        )

    monkeypatch.setattr(agent_runtime, "RuntimeRunnableResolver", CapturedRunnableResolver)
    monkeypatch.setattr(agent_runtime, "_build_runtime_runnable_services", fake_build_runtime_runnable_services)
    monkeypatch.setattr(agent_runtime, "RuntimeFutureTaskService", CapturedFutureTaskService)
    monkeypatch.setattr(agent_runtime, "AgentRunGroupProjectionCoordinator", CapturedAgentRunGroupProjection)

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
    assert engine.runnable_resolver.kwargs["main_chat_virtual_agent"] == "main-chat-virtual-agent"
    assert engine.future_task_scheduler == "future-task-scheduler"
    assert engine.chat_runnable_parser == "chat-runnable-parser"
    assert engine.runnable_catalog == "runnable-catalog"
    assert engine.runnable_run_coordinator == "runnable-run-coordinator"
    assert isinstance(engine.future_task_service, CapturedFutureTaskService)
    assert engine.future_task_service.kwargs["resolve_runnable"] == "resolve-runnable"
    assert engine.future_task_service.kwargs["trigger_scheduler"] == "future-task-scheduler"
    assert isinstance(engine.agent_run_group_projection, CapturedAgentRunGroupProjection)
    assert "get_run_group" in engine.agent_run_group_projection.kwargs
    assert "update_run_group" in engine.agent_run_group_projection.kwargs
