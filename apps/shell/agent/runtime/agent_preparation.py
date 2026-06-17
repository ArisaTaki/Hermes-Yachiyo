"""Agent run preparation helpers for observable runtime execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AgentRunPreparation:
    backend: str
    runtime: dict[str, Any]
    timeline: list[dict[str, Any]]
    artifact_root: Path
    skills: list[dict[str, Any]]
    context: str
    broker: Any
    artifacts: list[dict[str, Any]]


class RuntimeAgentRunPreparer:
    """Builds the model-visible context and first observable artifacts for an Agent Run."""

    def __init__(
        self,
        *,
        agent_artifacts_dir: Path,
        normalize_execution_backend: Callable[..., str],
        compile_agent_runtime: Callable[[dict[str, Any]], dict[str, Any]],
        load_agent_skills: Callable[[list[str]], list[dict[str, Any]]],
        agent_context: Callable[..., str],
        memory_store: Callable[..., Any],
        future_task_store: Callable[..., Any],
        runtime_agent_timeline: Any,
        runtime_agent_run_events: Any,
        runtime_trace_events: Any,
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        timeline_factory: Callable[..., dict[str, Any]],
        memory_context_limit: int,
        tool_broker_factory: Callable[..., Any] | None = None,
        tool_brokers: Any | None = None,
    ) -> None:
        self._agent_artifacts_dir = agent_artifacts_dir
        self._normalize_execution_backend = normalize_execution_backend
        self._compile_agent_runtime = compile_agent_runtime
        self._load_agent_skills = load_agent_skills
        self._agent_context = agent_context
        self._memory_store = memory_store
        self._future_task_store = future_task_store
        self._tool_broker_factory = tool_broker_factory
        self._tool_brokers = tool_brokers
        self._runtime_agent_timeline = runtime_agent_timeline
        self._runtime_agent_run_events = runtime_agent_run_events
        self._runtime_trace_events = runtime_trace_events
        self._append_run_event = append_run_event
        self._timeline_factory = timeline_factory
        self._memory_context_limit = memory_context_limit

    def prepare(
        self,
        run_id: str,
        agent: dict[str, Any],
        user_goal: str,
        upstream: str = "",
    ) -> AgentRunPreparation:
        backend = self._normalize_execution_backend(
            agent.get("execution_backend"),
            model_mode=str(agent.get("model_mode") or "profile"),
        )
        runtime = self._compile_agent_runtime(agent)
        timeline = [
            self._runtime_agent_timeline.started(
                str(agent["name"]),
                backend=backend,
                runtime=runtime["runtime"],
            )
        ]
        self._runtime_agent_run_events.started(
            run_id,
            agent_id=str(agent.get("agent_id") or ""),
            agent_name=str(agent.get("name") or ""),
            backend=backend,
            runtime=runtime["runtime"],
        )
        timeline.append(
            self._runtime_agent_timeline.compiled(
                allowed_tools=runtime["tool_policy"].get("allowed_tools") or [],
            )
        )
        artifact_root = self._agent_artifacts_dir / run_id
        skills = self._load_agent_skills(agent.get("skill_ids") or [])
        context = self._agent_context(agent, user_goal, upstream, skills=skills)
        default_runnable_id = str(agent.get("agent_id") or "")
        if self._tool_brokers is not None:
            broker = self._tool_brokers.for_run(
                run_id=run_id,
                workspace_policy=runtime["workspace_policy"],
                default_runnable_id=default_runnable_id,
                skills=skills,
            )
        else:
            if self._tool_broker_factory is None:
                raise RuntimeError(
                    "Tool broker factory is required when shared tool brokers are not configured"
                )
            broker = self._tool_broker_factory(
                runtime["workspace_policy"],
                artifact_root,
                skills=skills,
                memory_store=self._memory_store(source_run_id=run_id),
                future_task_store=self._future_task_store(
                    source_run_id=run_id,
                    default_runnable_id=default_runnable_id,
                ),
            )
        return AgentRunPreparation(
            backend=backend,
            runtime=runtime,
            timeline=timeline,
            artifact_root=artifact_root,
            skills=skills,
            context=context,
            broker=broker,
            artifacts=[],
        )

    def write_context_artifact(self, run_id: str, preparation: AgentRunPreparation) -> dict[str, Any]:
        retrieved_memories = self._memory_store().list_items(
            include_deleted=False,
            limit=self._memory_context_limit,
        )
        self._append_run_event(
            run_id,
            "memory.retrieved",
            self._runtime_trace_events.memory_retrieved_payload(retrieved_memories),
        )
        artifact = preparation.broker.artifact_write("agent-context.md", preparation.context)
        preparation.artifacts.append({"kind": "context", **artifact})
        preparation.timeline.append(
            self._timeline_factory("agent.artifact.write", "agent-context.md", artifact=artifact)
        )
        self._append_run_event(
            run_id,
            "agent.artifact.write",
            {"kind": "agent_artifact", "artifact": artifact, **artifact},
        )
        return artifact
