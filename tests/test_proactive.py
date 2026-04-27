"""主动桌面观察服务测试。"""

from __future__ import annotations

from apps.core.chat_session import ChatSession
from apps.core.state import AppState
import apps.shell.proactive as proactive_mod
from apps.shell.config import AppConfig
from apps.shell.proactive import ProactiveDesktopService
from packages.protocol.enums import RiskLevel, TaskStatus, TaskType


class _ExecutorStub:
    name = "HermesExecutor"


class _RunnerStub:
    executor = _ExecutorStub()


class _RuntimeStub:
    def __init__(self) -> None:
        self.state = AppState()
        self.chat_session = ChatSession(session_id="proactive-test")
        self.task_runner = _RunnerStub()
        self.ready = True
        self.limited_tools: list[str] = []

    def is_hermes_ready(self) -> bool:
        return self.ready

    def get_status(self) -> dict:
        return {"hermes": {"limited_tools": self.limited_tools}}


def test_proactive_service_disabled():
    runtime = _RuntimeStub()
    config = AppConfig()
    service = ProactiveDesktopService(runtime, config.bubble_mode)

    state = service.get_state()

    assert state["status"] == "disabled"
    assert state["enabled"] is False
    assert runtime.state.list_tasks() == []


def test_proactive_service_blocks_when_hermes_not_ready():
    runtime = _RuntimeStub()
    runtime.ready = False
    config = AppConfig()
    config.bubble_mode.proactive_enabled = True
    config.bubble_mode.proactive_desktop_watch_enabled = True
    service = ProactiveDesktopService(runtime, config.bubble_mode)

    state = service.get_state()

    assert state["status"] == "blocked"
    assert "Hermes Agent" in state["error"]
    assert runtime.state.list_tasks() == []


def test_proactive_service_blocks_when_vision_limited():
    runtime = _RuntimeStub()
    runtime.limited_tools = ["vision"]
    config = AppConfig()
    config.bubble_mode.proactive_enabled = True
    config.bubble_mode.proactive_desktop_watch_enabled = True
    service = ProactiveDesktopService(runtime, config.bubble_mode)

    state = service.get_state()

    assert state["status"] == "blocked"
    assert "vision" in state["error"]
    assert runtime.state.list_tasks() == []


def test_proactive_service_creates_low_risk_screenshot_task():
    runtime = _RuntimeStub()
    config = AppConfig()
    config.live2d_mode.proactive_enabled = True
    config.live2d_mode.proactive_desktop_watch_enabled = True
    config.live2d_mode.proactive_interval_seconds = 60
    service = ProactiveDesktopService(runtime, config.live2d_mode)

    state = service.get_state()
    tasks = runtime.state.list_tasks()

    assert state["status"] == "scheduled"
    assert state["task_id"] == tasks[0].task_id
    assert tasks[0].task_type == TaskType.SCREENSHOT
    assert tasks[0].risk_level == RiskLevel.LOW
    assert service.last_task_id == tasks[0].task_id


def test_proactive_service_reports_failed_before_retry_interval(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(proactive_mod.time, "monotonic", lambda: now[0])
    runtime = _RuntimeStub()
    config = AppConfig()
    config.bubble_mode.proactive_enabled = True
    config.bubble_mode.proactive_desktop_watch_enabled = True
    config.bubble_mode.proactive_interval_seconds = 60
    service = ProactiveDesktopService(runtime, config.bubble_mode)

    scheduled = service.get_state()
    runtime.state.update_task_status(scheduled["task_id"], TaskStatus.FAILED, error="vision failed")
    now[0] = 1030.0

    state = service.get_state()

    assert state["status"] == "failed"
    assert state["task_id"] == scheduled["task_id"]
    assert state["error"] == "vision failed"
    assert len(runtime.state.list_tasks()) == 1


def test_proactive_service_retries_failed_task_after_interval(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(proactive_mod.time, "monotonic", lambda: now[0])
    runtime = _RuntimeStub()
    config = AppConfig()
    config.live2d_mode.proactive_enabled = True
    config.live2d_mode.proactive_desktop_watch_enabled = True
    config.live2d_mode.proactive_interval_seconds = 60
    service = ProactiveDesktopService(runtime, config.live2d_mode)

    scheduled = service.get_state()
    runtime.state.update_task_status(scheduled["task_id"], TaskStatus.FAILED, error="vision failed")
    now[0] = 1061.0

    failed = service.get_state()
    assert failed["status"] == "failed"
    assert failed["task_id"] == scheduled["task_id"]

    now[0] = 1062.0
    state = service.get_state()
    tasks = runtime.state.list_tasks()

    assert state["status"] == "scheduled"
    assert state["task_id"] != scheduled["task_id"]
    assert service.last_task_id == state["task_id"]
    assert len(tasks) == 2
    assert tasks[-1].task_type == TaskType.SCREENSHOT
    assert tasks[-1].risk_level == RiskLevel.LOW
