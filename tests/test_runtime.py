"""Runtime 测试 — TaskRunner 执行器热切换"""

from apps.core.executor import HermesExecutor, SimulatedExecutor
from apps.core.runtime import HermesRuntime
from apps.core.task_runner import TaskRunner
from apps.shell.config import AppConfig
from packages.protocol.enums import HermesInstallStatus, Platform
from packages.protocol.install import HermesInstallInfo


def _make_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    import apps.core.chat_session as chat_session_mod
    import apps.core.chat_store as chat_store_mod

    if chat_store_mod._global_store is not None:
        chat_store_mod._global_store.close()
    chat_store_mod._global_store = None
    chat_session_mod._global_session = None

    return HermesRuntime(AppConfig())


def test_refresh_task_runner_executor_updates_existing_runner(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    runner = TaskRunner(runtime.state, executor=SimulatedExecutor())
    runtime._task_runner = runner

    monkeypatch.setattr(
        "apps.core.executor.select_executor",
        lambda rt: HermesExecutor(),
    )

    result = runtime.refresh_task_runner_executor()

    assert result["updated"] is True
    assert result["previous_executor"] == "SimulatedExecutor"
    assert result["executor"] == "HermesExecutor"
    assert runner.executor.name == "HermesExecutor"


def test_start_accepts_prechecked_install_info(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    install_info = HermesInstallInfo(
        status=HermesInstallStatus.READY,
        platform=Platform.MACOS,
        command_exists=True,
    )

    monkeypatch.setattr(
        "apps.core.runtime.check_hermes_installation",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected install check")),
    )
    monkeypatch.setattr(runtime, "_start_task_runner", lambda: None)

    runtime.start(install_info=install_info)

    assert runtime.running is True
    assert runtime.hermes_install_info is install_info


def test_refresh_task_runner_executor_without_runner_is_noop(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)

    result = runtime.refresh_task_runner_executor()

    assert result["updated"] is False
    assert result["reason"] == "task_runner_not_started"


def test_switch_session_syncs_executor_via_public_method(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path, monkeypatch)
    executor = HermesExecutor(chat_session=runtime.chat_session)
    runtime._task_runner = TaskRunner(runtime.state, executor=executor)

    runtime.switch_session("next-session")

    assert runtime.chat_session.session_id == "next-session"
    assert executor._chat_session is runtime.chat_session
