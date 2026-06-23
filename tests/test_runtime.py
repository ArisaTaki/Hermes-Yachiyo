"""Runtime tests for the native TaskRunner adapter."""

from apps.core.executor import NativeAgentExecutor, SimulatedExecutor
from apps.core.runtime import AppRuntime
from apps.core.task_runner import TaskRunner
from apps.shell.config import AppConfig


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


def test_start_does_not_require_native_agent_readiness(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "native_agent_readiness", lambda: {"ready": False, "reason": "model_profile_required"})
    monkeypatch.setattr(runtime, "_start_task_runner", lambda: None)

    runtime.start()

    assert runtime.running is True


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
        "workspace.write_patch",
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
