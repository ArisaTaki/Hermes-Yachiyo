"""Runtime tests for the native TaskRunner adapter."""

import asyncio
import threading

import pytest

from apps.bridge.routes import model_profiles as model_profile_routes
from apps.core.executor import NativeAgentExecutor, NativeAgentUnavailableExecutor, SimulatedExecutor
from apps.core.runtime import AppRuntime
from apps.core.task_runner import TaskRunner
from apps.shell.agent.runtime.run_readiness import native_agent_readiness
from apps.shell.config import AppConfig
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.model_profiles import ModelProfileService


def _make_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "oha-yachiyo"))

    import apps.core.chat_session as chat_session_mod
    import apps.core.chat_store as chat_store_mod
    import apps.core.activity_store as activity_store_mod

    if chat_store_mod._global_store is not None:
        chat_store_mod._global_store.close()
    chat_store_mod._global_store = None
    if activity_store_mod._global_store is not None:
        activity_store_mod._global_store.close()
    activity_store_mod._global_store = None
    chat_session_mod._global_session = None

    return AppRuntime(AppConfig())


def test_refresh_task_runner_executor_updates_existing_runner(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    runner = TaskRunner(runtime.state, executor=SimulatedExecutor())
    runtime._task_runner = runner

    monkeypatch.setattr(
        "apps.core.executor.select_executor",
        lambda rt: NativeAgentExecutor(),
    )

    result = runtime.refresh_task_runner_executor()

    assert result["updated"] is True
    assert result["previous_executor"] == "SimulatedExecutor"
    assert result["executor"] == "NativeAgentExecutor"
    assert runner.executor.name == "NativeAgentExecutor"


def test_profile_test_route_replaces_stale_unavailable_executor(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        profile = profile_service.create_profile(
            {
                "name": "Runtime Refresh",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-test-secret",
            }
        )
        profile_service.set_defaults({"chat": profile["profile_id"]})
        monkeypatch.setattr(
            runtime,
            "native_agent_readiness",
            lambda: native_agent_readiness(
                profile_service_factory=lambda: profile_service,
                supports_openai_compatible_api=lambda provider: provider == "openai_compatible",
                redact_error=str,
            ),
        )
        monkeypatch.setattr(
            "apps.shell.model_profiles.openai_compatible_chat",
            lambda *_args, **_kwargs: "OK",
        )
        monkeypatch.setattr(
            model_profile_routes,
            "get_model_profile_service",
            lambda: profile_service,
        )
        monkeypatch.setattr(model_profile_routes, "get_runtime", lambda: runtime)

        runtime._task_runner = TaskRunner(
            runtime.state,
            executor=NativeAgentUnavailableExecutor("profile unavailable"),
        )
        assert isinstance(runtime.task_runner.executor, NativeAgentUnavailableExecutor)

        result = asyncio.run(
            model_profile_routes.test_model_profile(profile["profile_id"])
        )

        assert result["success"] is True
        assert profile_service.get_profile(profile["profile_id"])["status"] == "available"
        assert isinstance(runtime.task_runner.executor, NativeAgentExecutor)
    finally:
        profile_service.close()


def test_start_does_not_require_native_agent_readiness(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "native_agent_readiness", lambda: {"ready": False, "reason": "model_profile_required"})
    monkeypatch.setattr(runtime, "_start_task_runner", lambda: None)

    runtime.start()

    assert runtime.running is True


def test_start_reconciles_activity_rows_left_by_interrupted_process(
    tmp_path,
    monkeypatch,
):
    runtime = _make_runtime(tmp_path, monkeypatch)

    class FakeRuntimeService:
        db_path = tmp_path / "agent-runtime.db"
        workspace_dir = tmp_path / "workspace"

        def reconcile_startup_runs(self, *_args, **_kwargs):
            return {}

        def get_task_run_projections(self, task_ids):
            statuses = {
                "completed-linked-task": "completed",
                "approval-linked-task": "approval_required",
                "deferred-linked-task": "running",
            }
            return {
                task_id: {"task_id": task_id, "status": statuses[task_id]}
                for task_id in task_ids
                if task_id in statuses
            }

        def close(self):
            return None

    runtime.agent_runtime_service = FakeRuntimeService()
    runtime.activity_store.record_event(
        event_id="stale-running",
        task_id="interrupted-task",
        phase="task_start",
        title="Interrupted task",
        status="running",
        created_at="2000-01-01T00:00:00+00:00",
    )
    runtime.activity_store.record_event(
        event_id="stale-progress",
        task_id="interrupted-task",
        phase="tool_progress",
        title="Interrupted tool",
        status="progress",
        created_at="2000-01-01T00:00:01+00:00",
    )
    runtime.activity_store.record_event(
        event_id="already-completed",
        task_id="completed-task",
        phase="task_complete",
        title="Completed task",
        status="completed",
        created_at="2000-01-01T00:00:02+00:00",
    )
    runtime.activity_store.record_event(
        event_id="linked-completed",
        task_id="completed-linked-task",
        phase="tool_progress",
        title="Completed native run",
        status="running",
        created_at="2000-01-01T00:00:03+00:00",
    )
    runtime.activity_store.record_event(
        event_id="linked-approval",
        task_id="approval-linked-task",
        phase="tool_progress",
        title="Waiting for approval",
        status="running",
        created_at="2000-01-01T00:00:04+00:00",
    )
    runtime.activity_store.record_event(
        event_id="linked-deferred-lease",
        task_id="deferred-linked-task",
        phase="tool_progress",
        title="Owned by a live lease",
        status="progress",
        created_at="2000-01-01T00:00:05+00:00",
    )
    runtime.activity_store.record_event(
        event_id="future-running",
        task_id="future-task",
        phase="task_start",
        title="Future task",
        status="running",
        created_at="2999-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(runtime, "_start_task_runner", lambda: None)

    runtime.start()
    try:
        events = {
            event.event_id: event
            for event in runtime.activity_store.list_events(limit=20)
        }

        assert events["stale-running"].status == "failed"
        assert events["stale-progress"].status == "failed"
        assert events["already-completed"].status == "completed"
        assert events["linked-completed"].status == "completed"
        assert events["linked-approval"].status == "running"
        assert events["linked-deferred-lease"].status == "progress"
        assert events["future-running"].status == "running"
        assert events["stale-running"].to_dict()["metadata"] == {
            "recovered_after_restart": 1,
            "recovery_reason": "runtime_restarted",
        }
        assert runtime.activity_store.reconcile_interrupted_tasks(
            runtime._startup_reconciliation_cutoff,
            terminal_status_by_task={},
            orphan_task_ids=set(),
        ) == 0
    finally:
        runtime.stop()


def test_start_reconciles_activity_from_canonical_run_after_partial_recovery_error(
    tmp_path,
    monkeypatch,
):
    runtime = _make_runtime(tmp_path, monkeypatch)

    class PartiallyFailedRuntimeService:
        db_path = tmp_path / "agent-runtime.db"
        workspace_dir = tmp_path / "workspace"

        def reconcile_startup_runs(self, *_args, **_kwargs):
            raise RuntimeError("group projection failed after Run commit")

        def get_task_run_projections(self, task_ids):
            assert "partially-recovered-task" in task_ids
            return {
                "partially-recovered-task": {
                    "task_id": "partially-recovered-task",
                    "run_id": "partially-recovered-run",
                    "status": "failed",
                }
            }

        def close(self):
            return None

    runtime.agent_runtime_service = PartiallyFailedRuntimeService()
    runtime.activity_store.record_event(
        event_id="partially-recovered-activity",
        task_id="partially-recovered-task",
        phase="tool_progress",
        title="Recovery committed before projection failed",
        status="running",
        created_at="2000-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(runtime, "_start_task_runner", lambda: None)

    runtime.start()
    try:
        event = runtime.activity_store.get_event("partially-recovered-activity")
        assert event is not None
        assert event.status == "failed"
    finally:
        runtime.stop()


def test_runtime_lease_watchdog_projects_terminal_run_to_activity(
    tmp_path,
    monkeypatch,
):
    runtime = _make_runtime(tmp_path, monkeypatch)

    class FakeRuntimeService:
        def reconcile_runtime_leases(self, _observed_at):
            return {
                "terminal_tasks": {
                    "expired-lease-task": {
                        "task_id": "expired-lease-task",
                        "run_id": "expired-lease-run",
                        "status": "failed",
                    }
                },
                "next_lease_expiry_at": "",
            }

    runtime.activity_store.record_event(
        event_id="expired-lease-activity",
        task_id="expired-lease-task",
        phase="tool_progress",
        title="Waiting for leased execution",
        status="running",
        created_at="2000-01-01T00:00:00+00:00",
    )
    runtime._runtime_instance_service = FakeRuntimeService()
    runtime._running = True
    monkeypatch.setattr(
        runtime,
        "_schedule_deferred_startup_reconciliation",
        lambda *_args, **_kwargs: None,
    )

    runtime._run_runtime_lease_watchdog()

    event = runtime.activity_store.get_event("expired-lease-activity")
    assert event is not None
    assert event.status == "failed"
    assert event.to_dict()["metadata"]["recovery_reason"] == (
        "runtime_status_reconciled"
    )


def test_runtime_lease_watchdog_retries_transient_activity_projection_failure(
    tmp_path,
    monkeypatch,
):
    runtime = _make_runtime(tmp_path, monkeypatch)

    class FakeRuntimeService:
        calls = 0

        def reconcile_runtime_leases(self, _observed_at):
            self.calls += 1
            return {
                "terminal_tasks": (
                    {
                        "retry-lease-task": {
                            "task_id": "retry-lease-task",
                            "run_id": "retry-lease-run",
                            "status": "failed",
                        }
                    }
                    if self.calls == 1
                    else {}
                ),
                "next_lease_expiry_at": "",
            }

    runtime.activity_store.record_event(
        event_id="retry-lease-activity",
        task_id="retry-lease-task",
        phase="tool_progress",
        title="Waiting for retry",
        status="running",
        created_at="2000-01-01T00:00:00+00:00",
    )
    runtime._runtime_instance_service = FakeRuntimeService()
    runtime._running = True
    monkeypatch.setattr(
        runtime,
        "_schedule_deferred_startup_reconciliation",
        lambda *_args, **_kwargs: None,
    )
    reconcile = runtime.activity_store.reconcile_interrupted_tasks
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("activity store temporarily unavailable")
        return reconcile(*args, **kwargs)

    monkeypatch.setattr(runtime.activity_store, "reconcile_interrupted_tasks", fail_once)

    runtime._run_runtime_lease_watchdog()
    assert runtime.activity_store.get_event("retry-lease-activity").status == "running"

    runtime._run_runtime_lease_watchdog()
    assert runtime.activity_store.get_event("retry-lease-activity").status == "failed"
    assert attempts == 2


def test_stop_closes_injected_native_runtime_service(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    closed = []
    closed_global = []

    class FakeNativeRuntime:
        def close(self):
            closed.append(True)

    runtime.agent_runtime_service = FakeNativeRuntime()
    runtime._running = True
    monkeypatch.setattr(runtime, "_stop_task_runner", lambda: None)
    monkeypatch.setattr("apps.shell.agent_runtime.close_agent_runtime_service", lambda: closed_global.append(True))

    runtime.stop()

    assert runtime.running is False
    assert closed == [True]
    assert closed_global == [True]


def test_runtime_exposes_global_native_runtime_service(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    service = object()
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_agent_runtime_service",
        lambda: service,
    )

    assert runtime.get_agent_runtime_service() is service


def test_runtime_exposes_and_closes_activity_store(tmp_path, monkeypatch):
    import apps.core.activity_store as activity_store_mod

    runtime = _make_runtime(tmp_path, monkeypatch)
    runtime._running = True
    monkeypatch.setattr(runtime, "_stop_task_runner", lambda: None)
    monkeypatch.setattr("apps.shell.agent_runtime.close_agent_runtime_service", lambda: None)

    assert runtime.activity_store is activity_store_mod.get_activity_store()

    runtime.stop()

    assert runtime.running is False
    assert activity_store_mod._global_store is None


def test_start_task_runner_receives_runtime_activity_store(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    created = []

    class FakeTaskRunner:
        def __init__(self, state, *, executor=None, activity_store=None):
            self.state = state
            self.executor = executor
            self.activity_store = activity_store
            created.append(self)

        async def start(self):
            return None

        async def stop(self):
            return None

    monkeypatch.setattr("apps.core.task_runner.TaskRunner", FakeTaskRunner)
    monkeypatch.setattr("apps.core.executor.select_executor", lambda rt: SimulatedExecutor())

    runtime._start_task_runner()
    try:
        assert len(created) == 1
        assert created[0].state is runtime.state
        assert created[0].activity_store is runtime.activity_store
        assert runtime.task_runner is created[0]
    finally:
        runtime._stop_task_runner()


def test_start_propagates_task_runner_startup_failure_and_releases_resources(
    tmp_path,
    monkeypatch,
):
    class FakeRuntimeService:
        db_path = tmp_path / "agent-runtime.db"
        workspace_dir = tmp_path / "workspace"

        def reconcile_startup_runs(self, *_args, **_kwargs):
            return {}

    starts = 0

    class FlakyTaskRunner:
        def __init__(self, state, *, executor=None, activity_store=None):
            self.state = state
            self.executor = executor
            self.activity_store = activity_store

        async def start(self):
            nonlocal starts
            starts += 1
            if starts == 1:
                raise RuntimeError("task-runner-startup-failed")

        async def stop(self):
            return None

    service = FakeRuntimeService()
    monkeypatch.setattr("apps.core.task_runner.TaskRunner", FlakyTaskRunner)
    monkeypatch.setattr(
        "apps.core.executor.select_executor",
        lambda _runtime: SimulatedExecutor(),
    )

    failed_runtime = _make_runtime(tmp_path / "failed", monkeypatch)
    failed_runtime.agent_runtime_service = service

    with pytest.raises(RuntimeError, match="task-runner-startup-failed"):
        failed_runtime.start()

    assert failed_runtime.running is False
    assert failed_runtime.task_runner is None
    assert failed_runtime._task_runner_thread is None
    assert failed_runtime._task_runner_loop is None
    assert failed_runtime._runtime_instance_lock is None

    replacement_runtime = _make_runtime(tmp_path / "replacement", monkeypatch)
    replacement_runtime.agent_runtime_service = service
    replacement_runtime.start()
    try:
        assert replacement_runtime.running is True
        assert replacement_runtime.task_runner is not None
        assert replacement_runtime._task_runner_thread is not None
        assert replacement_runtime._task_runner_thread.is_alive()
    finally:
        replacement_runtime.stop()


def test_start_task_runner_accepts_long_running_start_coroutine(
    tmp_path,
    monkeypatch,
):
    entered_start = threading.Event()

    class LongRunningTaskRunner:
        def __init__(self, state, *, executor=None, activity_store=None):
            self.state = state
            self.executor = executor
            self.activity_store = activity_store
            self._stop_requested = None

        async def start(self):
            self._stop_requested = asyncio.Event()
            entered_start.set()
            await self._stop_requested.wait()

        async def stop(self):
            assert self._stop_requested is not None
            self._stop_requested.set()

    monkeypatch.setattr("apps.core.task_runner.TaskRunner", LongRunningTaskRunner)
    monkeypatch.setattr(
        "apps.core.executor.select_executor",
        lambda _runtime: SimulatedExecutor(),
    )
    runtime = _make_runtime(tmp_path, monkeypatch)

    runtime._start_task_runner()
    try:
        assert entered_start.is_set()
        assert runtime._task_runner_thread is not None
        assert runtime._task_runner_thread.is_alive()
    finally:
        runtime._stop_task_runner()

    assert runtime.task_runner is None
    assert runtime._task_runner_thread is None
    assert runtime._task_runner_loop is None


def test_refresh_task_runner_executor_without_runner_is_noop(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)

    result = runtime.refresh_task_runner_executor()

    assert result["updated"] is False
    assert result["reason"] == "task_runner_not_started"


def test_is_native_agent_ready_uses_native_readiness(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "native_agent_readiness", lambda: {"ready": False})

    assert runtime.is_native_agent_ready() is False


def test_get_status_reports_native_readiness_without_native_agent_probe(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "native_agent_readiness", lambda: {"ready": True, "profile_id": "p1"})

    status = runtime.get_status()

    assert status["service"] == "oha-yachiyo"
    assert status["native_agent"]["ready"] is True
    assert status["native_agent_ready"] is True


def test_main_chat_runtime_policies_enable_native_tools_with_approval(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    from apps.shell.agent.tools.policy import (
        DAILY_DESKTOP_TOOL_NAMES,
        HIGH_RISK_DESKTOP_TOOL_NAMES,
        MEDIUM_RISK_BROWSER_TOOL_NAMES,
        MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    )

    tool_policy = runtime.main_chat_tool_policy()
    workspace_policy = runtime.main_chat_workspace_policy()

    assert set(tool_policy["allowed_tools"]) == {
        "workspace.list",
        "workspace.read",
        "data.analyze",
        "workspace.write_patch",
        "file.organize",
        "terminal.run",
        *DAILY_DESKTOP_TOOL_NAMES,
        "memory.add",
        "memory.replace",
        "memory.remove",
        "future_task.schedule",
        "future_task.list",
        "future_task.cancel",
        "artifact.write",
    }
    assert tool_policy["approval_required"]["workspace.write_patch"] is True
    assert tool_policy["approval_required"]["file.organize"] is True
    assert tool_policy["approval_required"]["terminal.run"] is True
    for tool in (
        *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
        *HIGH_RISK_DESKTOP_TOOL_NAMES,
        *MEDIUM_RISK_BROWSER_TOOL_NAMES,
    ):
        assert tool_policy["approval_required"][tool] is True
    assert workspace_policy["readable_scopes"] == ["."]
    assert workspace_policy["writable_scopes"] == ["."]


def test_switch_session_syncs_executor_via_public_method(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    executor = NativeAgentExecutor(chat_session=runtime.chat_session)
    runtime._task_runner = TaskRunner(runtime.state, executor=executor)

    runtime.switch_session("next-session")

    assert runtime.chat_session.session_id == "next-session"
    assert executor._chat_session is runtime.chat_session
