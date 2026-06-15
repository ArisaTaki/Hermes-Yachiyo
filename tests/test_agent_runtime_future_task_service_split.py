"""Tests for FutureTask runtime service split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.future_task_service import RuntimeFutureTaskService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_future_task_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeFutureTaskService is RuntimeFutureTaskService


def test_native_runtime_installs_split_future_task_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.future_task_service, RuntimeFutureTaskService)
        assert service.future_task_service._trigger_scheduler is service.future_task_scheduler
    finally:
        service.close()


def test_runtime_future_task_service_schedules_against_resolved_runnable() -> None:
    resolve_calls: list[dict[str, str]] = []
    stores: list[FakeFutureTaskStore] = []

    def future_task_store(**kwargs: Any) -> "FakeFutureTaskStore":
        store = FakeFutureTaskStore(**kwargs)
        stores.append(store)
        return store

    service = RuntimeFutureTaskService(
        future_task_store=future_task_store,
        resolve_runnable=lambda **kwargs: resolve_calls.append(dict(kwargs)) or {"kind": "agent"},
        trigger_scheduler=FakeTriggerScheduler(),
        default_runnable_id="builtin:yachiyo-main",
        error_type=AgentRuntimeError,
    )

    result = service.schedule(
        {
            "title": "Follow up",
            "goal": "Check release checklist.",
            "delay_seconds": 10,
        },
        source_run_id="run-1",
    )

    assert resolve_calls == [{"runnable_id": "builtin:yachiyo-main", "name": ""}]
    assert stores[0].source_run_id == "run-1"
    assert stores[0].default_runnable_id == "builtin:yachiyo-main"
    assert stores[0].scheduled == {
        "title": "Follow up",
        "prompt": "Check release checklist.",
        "runnable_id": "builtin:yachiyo-main",
        "runnable_name": "",
        "delay_seconds": 10,
        "scheduled_at_epoch": None,
        "cron": "",
    }
    assert result["future_task"]["title"] == "Follow up"


def test_runtime_future_task_service_rejects_unknown_runnable() -> None:
    service = RuntimeFutureTaskService(
        future_task_store=lambda **_kwargs: FakeFutureTaskStore(),
        resolve_runnable=lambda **_kwargs: None,
        trigger_scheduler=FakeTriggerScheduler(),
        default_runnable_id="builtin:yachiyo-main",
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match="不存在"):
        service.schedule({"prompt": "Do it", "runnable_id": "missing-agent"})


def test_runtime_future_task_service_lists_cancels_and_triggers() -> None:
    stores: list[FakeFutureTaskStore] = []
    trigger_scheduler = FakeTriggerScheduler()

    def future_task_store(**kwargs: Any) -> "FakeFutureTaskStore":
        store = FakeFutureTaskStore(**kwargs)
        stores.append(store)
        return store

    service = RuntimeFutureTaskService(
        future_task_store=future_task_store,
        resolve_runnable=lambda **_kwargs: {"kind": "agent"},
        trigger_scheduler=trigger_scheduler,
        default_runnable_id="builtin:yachiyo-main",
        error_type=AgentRuntimeError,
    )

    listed = service.list(include_finished=False, limit=5)
    cancelled = service.cancel("future-1", reason="user")
    triggered = service.trigger_due(now_epoch=123.0, limit=3)

    assert listed == {"ok": True, "future_tasks": [{"future_task_id": "future-1"}]}
    assert stores[0].listed == {"include_finished": False, "limit": 5}
    assert stores[1].source_run_id == "manual"
    assert stores[1].cancelled == {"future_task_id": "future-1", "reason": "user"}
    assert cancelled["future_task"]["status"] == "cancelled"
    assert trigger_scheduler.calls == [{"now_epoch": 123.0, "limit": 3}]
    assert triggered == {"ok": True, "triggered": []}


class FakeFutureTaskStore:
    def __init__(self, **kwargs: Any) -> None:
        self.source_run_id = str(kwargs.get("source_run_id") or "")
        self.default_runnable_id = str(kwargs.get("default_runnable_id") or "")
        self.scheduled: dict[str, Any] = {}
        self.listed: dict[str, Any] = {}
        self.cancelled: dict[str, Any] = {}

    def schedule(self, **kwargs: Any) -> dict[str, Any]:
        self.scheduled = dict(kwargs)
        return {"ok": True, "future_task": {"future_task_id": "future-1", "title": kwargs["title"]}}

    def list_tasks(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.listed = dict(kwargs)
        return [{"future_task_id": "future-1"}]

    def cancel(self, future_task_id: str, *, reason: str = "") -> dict[str, Any]:
        self.cancelled = {"future_task_id": future_task_id, "reason": reason}
        return {"ok": True, "future_task": {"future_task_id": future_task_id, "status": "cancelled"}}


class FakeTriggerScheduler:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def trigger_due_future_tasks(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(dict(kwargs))
        return {"ok": True, "triggered": []}
