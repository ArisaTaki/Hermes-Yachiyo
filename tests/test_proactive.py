"""主动桌面观察服务测试。"""

from __future__ import annotations

from apps.core.chat_session import ChatSession
from apps.core.state import AppState
import apps.shell.proactive as proactive_mod
from apps.shell.config import AppConfig
from apps.shell.proactive import ProactiveDesktopService, build_proactive_desktop_prompt
from packages.protocol.enums import RiskLevel, TaskStatus, TaskType


class _ExecutorStub:
    name = "HermesExecutor"


class _RunnerStub:
    executor = _ExecutorStub()


class _RuntimeStub:
    def __init__(self) -> None:
        self.config = AppConfig()
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
    runtime.config.live2d_mode.proactive_enabled = True
    runtime.config.live2d_mode.proactive_desktop_watch_enabled = True
    runtime.config.live2d_mode.proactive_interval_seconds = 60
    runtime.config.tts.max_chars = 42
    runtime.config.tts.notification_prompt = "只说一句轻快提醒。"
    service = ProactiveDesktopService(runtime, runtime.config.live2d_mode)

    state = service.get_state()
    tasks = runtime.state.list_tasks()

    assert state["status"] == "scheduled"
    assert state["task_id"] == tasks[0].task_id
    assert tasks[0].task_type == TaskType.SCREENSHOT
    assert tasks[0].risk_level == RiskLevel.LOW
    assert "只说一句轻快提醒" in tasks[0].description
    assert "最多 42 个中文字符" in tasks[0].description
    assert service.last_task_id == tasks[0].task_id


def test_build_proactive_desktop_prompt_uses_tts_notification_constraints():
    runtime = _RuntimeStub()
    runtime.config.tts.max_chars = 33
    runtime.config.tts.notification_prompt = "像打招呼一样提醒。"

    prompt = build_proactive_desktop_prompt(runtime)

    assert "像打招呼一样提醒" in prompt
    assert "最多 33 个中文字符" in prompt


def test_proactive_service_completed_state_exposes_observation_text():
    runtime = _RuntimeStub()
    runtime.config.bubble_mode.proactive_enabled = True
    runtime.config.bubble_mode.proactive_desktop_watch_enabled = True
    service = ProactiveDesktopService(runtime, runtime.config.bubble_mode)
    scheduled = service.get_state()

    runtime.state.update_task_status(
        scheduled["task_id"],
        TaskStatus.COMPLETED,
        result="你已经连续处理工具配置很久了，建议先保存进度再休息一下。",
    )
    state = service.get_state()

    assert state["status"] == "completed"
    assert state["has_attention"] is True
    assert state["attention_source"] == "proactive_desktop_watch"
    assert state["attention_text"] == "你已经连续处理工具配置很久了，建议先保存进度再休息一下。"
    assert state["message"] == state["attention_text"]


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
