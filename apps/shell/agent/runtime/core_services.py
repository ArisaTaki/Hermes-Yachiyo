"""Core runtime service setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.clock import utc_now_iso
from apps.shell.agent.runtime.config import (
    DEFAULT_AGENT_IDS,
    MEMORY_CONTENT_MAX_CHARS,
    MEMORY_CONTEXT_LIMIT,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import RuntimeRunEventRecorder
from apps.shell.agent.runtime.events import redact_json_value, redact_secrets
from apps.shell.agent.runtime.memory_services import RuntimeMemoryService
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver
from apps.shell.agent.runtime.serialization import json_dump_sorted
from apps.shell.agent.runtime.timeline import RuntimeAgentTimelineBuilder
from apps.shell.agent.runtime.timeline import runtime_timeline_factory
from apps.shell.agent.tools.policy import MEMORY_KINDS, MEMORY_SCOPES, RuntimePolicyCompiler


@dataclass(frozen=True)
class RuntimeCoreServiceBundle:
    runtime_events: RuntimeRunEventRecorder
    runtime_agent_timeline: RuntimeAgentTimelineBuilder
    runtime_policy: RuntimePolicyCompiler
    model_profile_resolver: RuntimeModelProfileResolver


@dataclass(frozen=True)
class RuntimeMemoryCoreSetup:
    memory_services: RuntimeMemoryService
    timeline_factory: Callable[..., dict[str, Any]]
    core_services: RuntimeCoreServiceBundle


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


def build_runtime_memory_core_setup(
    *,
    conn: Any,
    db_lock: Any,
    run_events: Any,
    profile_service_factory: Callable[[], Any],
    supports_openai_compatible_api: Callable[[str], bool],
) -> RuntimeMemoryCoreSetup:
    timeline_factory = runtime_timeline_factory(
        now=utc_now_iso,
        redact_detail=redact_secrets,
        redact_payload=redact_json_value,
    )
    return RuntimeMemoryCoreSetup(
        memory_services=RuntimeMemoryService(
            conn,
            db_lock,
            now=utc_now_iso,
            json_dump=json_dump_sorted,
            redact_json_value=redact_json_value,
            redact_secrets=redact_secrets,
            memory_scopes=MEMORY_SCOPES,
            memory_kinds=MEMORY_KINDS,
            context_limit=MEMORY_CONTEXT_LIMIT,
            content_max_chars=MEMORY_CONTENT_MAX_CHARS,
            error_type=AgentRuntimeError,
        ),
        timeline_factory=timeline_factory,
        core_services=build_runtime_core_services(
            run_events=run_events,
            timeline_factory=timeline_factory,
            profile_service_factory=profile_service_factory,
            supports_openai_compatible_api=supports_openai_compatible_api,
            default_agent_ids=DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        ),
    )
