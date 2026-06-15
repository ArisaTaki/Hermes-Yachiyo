"""Tests for runnable service setup split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.delegation import ChatRunnableMentionParser
from apps.shell.agent.runtime.future_task_scheduler import FutureTaskTriggerScheduler
from apps.shell.agent.runtime.runnable_services import (
    RuntimeRunnableServiceBundle,
    build_runtime_runnable_services,
)
from apps.shell.agent.runtime.runnables import (
    RuntimeRunnableCatalog,
    RuntimeRunnableResolver,
    RuntimeRunnableRunCoordinator,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_runnable_service_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunnableServiceBundle is RuntimeRunnableServiceBundle


def test_build_runtime_runnable_services_wires_future_tasks_delegation_and_runs() -> None:
    conn = object()
    db_lock = object()

    def list_runnables() -> list[dict[str, Any]]:
        return [{"id": "agent-1", "name": "Agent", "kind": "agent", "enabled": True}]

    def node_kind(node: dict[str, Any]) -> str:
        return str(node.get("type") or "")

    def resolve_runnable(**_kwargs: Any) -> dict[str, Any]:
        return {"id": "agent-1", "name": "Agent", "kind": "agent", "enabled": True}

    bundle = build_runtime_runnable_services(
        conn=conn,
        db_lock=db_lock,
        create_run_for_runnable=lambda **kwargs: {"run_id": "run-1", **kwargs},
        future_task_store=lambda **_kwargs: object(),
        now=lambda: "2026-06-15T10:00:00Z",
        redact_secrets=lambda value: str(value),
        error_type=agent_runtime.AgentRuntimeError,
        list_runnables=list_runnables,
        node_kind=node_kind,
        get_agent=lambda agent_id: {"agent_id": agent_id, "name": "Agent", "enabled": True},
        resolve_runnable=resolve_runnable,
        create_agent_run=lambda payload: {"run_id": "agent-run", "status": "completed", **payload},
        create_workflow_run=lambda payload: {"run_id": "workflow-run", "status": "completed", **payload},
        create_agent_run_async=lambda payload, **_kwargs: {"run_id": "agent-run", **payload},
        create_workflow_run_async=lambda payload, **_kwargs: {"run_id": "workflow-run", **payload},
    )

    assert isinstance(bundle, RuntimeRunnableServiceBundle)
    assert isinstance(bundle.future_task_scheduler, FutureTaskTriggerScheduler)
    assert isinstance(bundle.chat_runnable_parser, ChatRunnableMentionParser)
    assert isinstance(bundle.runnable_catalog, RuntimeRunnableCatalog)
    assert isinstance(bundle.runnable_run_coordinator, RuntimeRunnableRunCoordinator)
    assert bundle.future_task_scheduler._conn is conn
    assert bundle.future_task_scheduler._db_lock is db_lock
    assert bundle.chat_runnable_parser._list_runnables is list_runnables
    assert bundle.runnable_catalog._node_kind is node_kind
    assert bundle.runnable_run_coordinator._resolve_runnable is resolve_runnable


def test_native_runtime_installs_runnable_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.future_task_scheduler, FutureTaskTriggerScheduler)
        assert isinstance(service.chat_runnable_parser, ChatRunnableMentionParser)
        assert isinstance(service.runnable_catalog, RuntimeRunnableCatalog)
        assert isinstance(service.runnable_resolver, RuntimeRunnableResolver)
        assert isinstance(service.runnable_run_coordinator, RuntimeRunnableRunCoordinator)
        assert service.future_task_scheduler._conn is service._conn
        assert service.future_task_scheduler._db_lock is service._db_lock
        assert service.runnable_catalog._get_agent.__self__ is service
        assert service.runnable_run_coordinator._resolve_runnable.__self__ is service.runnable_resolver
        assert service.runnable_run_coordinator._create_agent_run.__self__ is service
        assert service.runnable_run_coordinator._create_workflow_run.__self__ is service
    finally:
        service.close()
