"""Future task and runnable service setup for the legacy engine entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from apps.shell.agent.runtime.delegation import ChatRunnableMentionParser
from apps.shell.agent.runtime.future_task_scheduler import FutureTaskTriggerScheduler
from apps.shell.agent.runtime.runnables import RuntimeRunnableCatalog, RuntimeRunnableRunCoordinator


@dataclass(frozen=True)
class RuntimeRunnableServiceBundle:
    future_task_scheduler: FutureTaskTriggerScheduler
    chat_runnable_parser: ChatRunnableMentionParser
    runnable_catalog: RuntimeRunnableCatalog
    runnable_run_coordinator: RuntimeRunnableRunCoordinator


def build_runtime_runnable_services(
    *,
    conn: Any,
    db_lock: Any,
    create_run_for_runnable: Callable[..., dict[str, Any]],
    future_task_store: Callable[..., Any],
    now: Callable[[], str],
    redact_secrets: Callable[[Any], str],
    error_type: type[Exception],
    list_runnables: Callable[[], list[dict[str, Any]]],
    node_kind: Callable[[dict[str, Any]], str],
    get_agent: Callable[[str], dict[str, Any]],
    resolve_runnable: Callable[..., dict[str, Any] | None],
    create_agent_run: Callable[[dict[str, Any]], dict[str, Any]],
    create_workflow_run: Callable[[dict[str, Any]], dict[str, Any]],
    create_agent_run_async: Callable[..., dict[str, Any]],
    create_workflow_run_async: Callable[..., dict[str, Any]],
) -> RuntimeRunnableServiceBundle:
    return RuntimeRunnableServiceBundle(
        future_task_scheduler=FutureTaskTriggerScheduler(
            conn,
            db_lock,
            create_run_for_runnable=create_run_for_runnable,
            future_task_store=future_task_store,
            now=now,
            redact_secrets=redact_secrets,
            error_type=error_type,
        ),
        chat_runnable_parser=ChatRunnableMentionParser(
            list_runnables=list_runnables,
        ),
        runnable_catalog=RuntimeRunnableCatalog(
            node_kind=node_kind,
            get_agent=get_agent,
        ),
        runnable_run_coordinator=RuntimeRunnableRunCoordinator(
            resolve_runnable=resolve_runnable,
            create_agent_run=create_agent_run,
            create_workflow_run=create_workflow_run,
            create_agent_run_async=create_agent_run_async,
            create_workflow_run_async=create_workflow_run_async,
            error_type=error_type,
        ),
    )
