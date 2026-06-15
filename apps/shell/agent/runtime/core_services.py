"""Core runtime service setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.events import RuntimeRunEventRecorder
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver
from apps.shell.agent.runtime.timeline import RuntimeAgentTimelineBuilder
from apps.shell.agent.tools.policy import RuntimePolicyCompiler


@dataclass(frozen=True)
class RuntimeCoreServiceBundle:
    runtime_events: RuntimeRunEventRecorder
    runtime_agent_timeline: RuntimeAgentTimelineBuilder
    runtime_policy: RuntimePolicyCompiler
    model_profile_resolver: RuntimeModelProfileResolver


def build_runtime_core_services(
    *,
    run_events: Any,
    timeline_factory: Callable[..., dict[str, Any]],
    profile_service_factory: Callable[[], Any],
    supports_openai_compatible_api: Callable[[str], bool],
    default_agent_ids: set[str],
    error_type: type[Exception],
) -> RuntimeCoreServiceBundle:
    return RuntimeCoreServiceBundle(
        runtime_events=RuntimeRunEventRecorder(run_events),
        runtime_agent_timeline=RuntimeAgentTimelineBuilder(
            timeline_factory=timeline_factory,
        ),
        runtime_policy=RuntimePolicyCompiler(),
        model_profile_resolver=RuntimeModelProfileResolver(
            profile_service_factory=profile_service_factory,
            supports_openai_compatible_api=supports_openai_compatible_api,
            default_agent_ids=default_agent_ids,
            error_type=error_type,
        ),
    )
