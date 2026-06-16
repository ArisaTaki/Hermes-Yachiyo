"""Agent and main-chat runtime entrypoint setup."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from packages.security import redact_api_error_text

from apps.shell.agent.runtime.agent_runs import RuntimeAgentRunAsyncCoordinator
from apps.shell.agent.runtime.config import (
    DEFAULT_AGENT_IDS,
    FINAL_RUN_STATUSES,
    MAIN_CHAT_AGENT_ID,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_secrets
from apps.shell.agent.runtime.main_chat_config import (
    MainChatRuntimeConfigBuilder,
    MainChatVirtualAgentProjector,
)
from apps.shell.agent.runtime.main_chat_runs import MainChatRunLifecycle
from apps.shell.agent.runtime.model_profiles import RuntimeAgentModelTester
from apps.shell.agent.runtime.run_timeline import RuntimeRunTimelineService
from apps.shell.agent.runtime.tool_brokers import RuntimeToolBrokerFactory
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import FUTURE_TASK_TOOL_NAMES, MEMORY_TOOL_NAMES


@dataclass(frozen=True)
class RuntimeAgentChatEntrypointSetup:
    agent_run_async_coordinator: RuntimeAgentRunAsyncCoordinator
    agent_model_tester: RuntimeAgentModelTester
    run_timeline: RuntimeRunTimelineService
    main_chat_config: MainChatRuntimeConfigBuilder
    main_chat_virtual_agent_projector: MainChatVirtualAgentProjector
    tool_brokers: RuntimeToolBrokerFactory
    main_chat_runs: MainChatRunLifecycle


def build_runtime_agent_chat_entrypoint_setup(
    *,
    get_agent_private: Callable[[str], dict[str, Any]],
    validate_agent_run_readiness: Callable[[dict[str, Any]], None],
    agent_run_starter: Any,
    execute_agent_run: Callable[..., dict[str, Any]],
    project_agent_run_group_if_root: Callable[[dict[str, Any]], dict[str, Any]],
    resolve_runnable: Callable[..., dict[str, Any] | None],
    update_run: Callable[..., dict[str, Any]],
    runtime_agent_timeline: Any,
    runtime_agent_run_events: Any,
    call_custom_api: Callable[..., Any],
    runs: Any,
    run_groups: Any,
    runtime_events: Any,
    run_artifacts: Any,
    agent_workspaces_dir: Path,
    agent_artifacts_dir: Path,
    memory_store: Any,
    future_task_store: Any,
    insert_run: Callable[..., dict[str, Any]],
    link_task_run: Callable[..., Any],
    get_run: Callable[[str], dict[str, Any]],
    task_run_links: Any,
    runtime_task_events: Any,
    runtime_timeline_factory: Callable[..., dict[str, Any]],
    compile_tool_policy: Callable[[str, Any], dict[str, Any]],
    compile_workspace_policy: Callable[[Any], dict[str, Any]],
    trust_workspace_from_policy: Callable[..., None],
    profile_service_factory: Callable[[], Any],
    workspace_status: Callable[[], dict[str, Any]],
) -> RuntimeAgentChatEntrypointSetup:
    main_chat_config = MainChatRuntimeConfigBuilder(
        main_chat_agent_id=MAIN_CHAT_AGENT_ID,
        agent_workspaces_dir=agent_workspaces_dir,
        workspace_status=workspace_status,
        compile_tool_policy=compile_tool_policy,
        compile_workspace_policy=compile_workspace_policy,
        trust_workspace_from_policy=trust_workspace_from_policy,
        memory_tool_names=list(MEMORY_TOOL_NAMES),
        future_task_tool_names=list(FUTURE_TASK_TOOL_NAMES),
    )
    return RuntimeAgentChatEntrypointSetup(
        agent_run_async_coordinator=RuntimeAgentRunAsyncCoordinator(
            get_agent_private=get_agent_private,
            validate_agent_run_readiness=validate_agent_run_readiness,
            starter=agent_run_starter,
            execute_agent_run=execute_agent_run,
            project_agent_run_group_if_root=project_agent_run_group_if_root,
            resolve_runnable=resolve_runnable,
            update_run=update_run,
            runtime_agent_timeline=runtime_agent_timeline,
            runtime_agent_run_events=runtime_agent_run_events,
            redact_error=redact_secrets,
            error_type=AgentRuntimeError,
        ),
        agent_model_tester=RuntimeAgentModelTester(
            profile_service_factory=profile_service_factory,
            default_agent_ids=DEFAULT_AGENT_IDS,
            call_custom_api=call_custom_api,
            now_seconds=time.time,
            redact_error=redact_api_error_text,
            error_type=AgentRuntimeError,
        ),
        run_timeline=RuntimeRunTimelineService(
            runs=runs,
            run_groups=run_groups,
            runtime_events=runtime_events,
            run_artifacts=run_artifacts,
        ),
        main_chat_config=main_chat_config,
        main_chat_virtual_agent_projector=MainChatVirtualAgentProjector(
            main_chat_config=main_chat_config,
            default_profile_id=lambda: str(
                profile_service_factory().get_defaults().get("chat") or ""
            ).strip(),
        ),
        tool_brokers=RuntimeToolBrokerFactory(
            agent_artifacts_dir=agent_artifacts_dir,
            tool_broker_factory=ToolBroker,
            memory_store=memory_store,
            future_task_store=future_task_store,
            main_chat_agent_id=MAIN_CHAT_AGENT_ID,
        ),
        main_chat_runs=MainChatRunLifecycle(
            main_chat_agent_id=MAIN_CHAT_AGENT_ID,
            insert_run=insert_run,
            link_task_run=link_task_run,
            get_run=get_run,
            update_run=update_run,
            task_run_links=task_run_links,
            task_events=runtime_task_events,
            timeline_factory=runtime_timeline_factory,
            redact_secrets=redact_secrets,
            final_statuses=FINAL_RUN_STATUSES,
        ),
    )
