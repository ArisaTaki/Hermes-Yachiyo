"""Agent run service setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from apps.shell.agent.runtime.agent_context import AgentContextBuilder
from apps.shell.agent.runtime.agent_outcomes import RuntimeAgentRunOutcomeProjector
from apps.shell.agent.runtime.agent_preparation import RuntimeAgentRunPreparer
from apps.shell.agent.runtime.agent_skills import RuntimeAgentSkillLoader


@dataclass(frozen=True)
class RuntimeAgentServiceBundle:
    agent_skill_loader: RuntimeAgentSkillLoader
    agent_context_builder: AgentContextBuilder
    agent_run_preparer: RuntimeAgentRunPreparer
    agent_run_outcomes: RuntimeAgentRunOutcomeProjector


def build_runtime_agent_services(
    *,
    get_skill: Callable[[str], dict[str, Any]],
    error_type: type[Exception],
    compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
    load_agent_skills: Callable[[list[str]], list[dict[str, Any]]],
    long_term_memory_context: Callable[[], str],
    operating_doctrine: str,
    agent_artifacts_dir: Path,
    normalize_execution_backend: Callable[..., str],
    agent_context: Callable[..., str],
    memory_store: Callable[..., Any],
    future_task_store: Callable[..., Any],
    runtime_agent_timeline: Any,
    runtime_agent_run_events: Any,
    runtime_trace_events: Any,
    append_run_event: Callable[[str, str, dict[str, Any]], Any],
    timeline_factory: Callable[..., dict[str, Any]],
    memory_context_limit: int,
    runtime_task_model_events: Any,
    update_run: Callable[..., dict[str, Any]],
    model_output_metadata: Callable[[Any], dict[str, Any]],
    redact_secrets: Callable[[Any], str],
    tool_broker_factory: Callable[..., Any] | None = None,
    tool_brokers: Any | None = None,
    agent_desk_context: Callable[[dict[str, Any]], str] | None = None,
) -> RuntimeAgentServiceBundle:
    return RuntimeAgentServiceBundle(
        agent_skill_loader=RuntimeAgentSkillLoader(
            get_skill=get_skill,
            error_type=error_type,
        ),
        agent_context_builder=AgentContextBuilder(
            compile_agent_runtime=compile_agent_runtime,
            load_agent_skills=load_agent_skills,
            long_term_memory_context=long_term_memory_context,
            operating_doctrine=operating_doctrine,
            agent_desk_context=agent_desk_context,
        ),
        agent_run_preparer=RuntimeAgentRunPreparer(
            agent_artifacts_dir=agent_artifacts_dir,
            normalize_execution_backend=normalize_execution_backend,
            compile_agent_runtime=compile_agent_runtime,
            load_agent_skills=load_agent_skills,
            agent_context=agent_context,
            memory_store=memory_store,
            future_task_store=future_task_store,
            tool_broker_factory=tool_broker_factory,
            runtime_agent_timeline=runtime_agent_timeline,
            runtime_agent_run_events=runtime_agent_run_events,
            runtime_trace_events=runtime_trace_events,
            append_run_event=append_run_event,
            timeline_factory=timeline_factory,
            memory_context_limit=memory_context_limit,
            tool_brokers=tool_brokers,
        ),
        agent_run_outcomes=RuntimeAgentRunOutcomeProjector(
            append_run_event=append_run_event,
            runtime_task_model_events=runtime_task_model_events,
            runtime_agent_timeline=runtime_agent_timeline,
            runtime_agent_run_events=runtime_agent_run_events,
            update_run=update_run,
            model_output_metadata=model_output_metadata,
            redact_secrets=redact_secrets,
        ),
    )
