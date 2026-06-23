"""ChatBridge session overview tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell import chat_bridge as chat_bridge_mod
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.chat_bridge import ChatBridge
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent import YachiyoAgentService
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort


class _EmptyActivityStore:
    def list_events(self, **_kwargs):
        return []


class _FakeNoDefaultProfileService:
    def get_defaults(self):
        return {"chat": ""}

    def get_profile_private(self, profile_id):
        raise KeyError(profile_id)


def _runtime_with_chat_store(store: ChatStore) -> SimpleNamespace:
    session = ChatSession(session_id="session-current")
    session.attach_store(store, load_existing=False)
    return SimpleNamespace(
        state=AppState(),
        chat_session=session,
        task_runner=None,
        agent_runtime_service=_FakeAgentRuntimeService(),
        store=store,
    )


def _run_launcher_daily_desktop_quick_message(
    tmp_path,
    monkeypatch,
    text: str,
    permission_probe: Any | None = None,
    permission_preflight: Any | None = None,
    seed_messages: list[tuple[str, str]] | None = None,
) -> tuple[dict, dict, dict, list[str]]:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    for role, content in seed_messages or []:
        if role == "user":
            runtime.chat_session.add_user_message(content)
        elif role == "assistant":
            runtime.chat_session.add_assistant_message(content)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher daily desktop quick message should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        permission_probe or (lambda use_cache=True: {}),
    )
    if permission_preflight is not None:
        monkeypatch.setattr(
            "apps.shell.agent.tools.desktop.permission_preflight",
            permission_preflight,
        )
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            text,
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
            },
        )
        agent_task = result["agent_task"]
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])
        task_timeline = YachiyoAgentService(LegacyRuntimePort(service)).get_task_timeline(
            result["task_id"]
        ).model_dump(mode="json")
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        messages = store.load_messages("session-current", limit=10)
        user = [message for message in messages if message.role == "user"][-1]
        assistant = [message for message in messages if message.role == "assistant"][-1]
        user_metadata = json.loads(user.metadata_json)

        assert result["ok"] is True
        assert agent_task["task_id"] == result["task_id"]
        assert agent_task["conversation_id"] == "session-current"
        assert agent_task["open_in_studio_url"] == f"#/agents?run_id={run['run_id']}"
        assert user_metadata["source"] == "launcher"
        assert user_metadata["launcher_mode"] == "live2d"
        assert user_metadata["daily_desktop_intent"] is True
        assert user_metadata["daily_desktop_source"] == "daily_desktop_intent"
        assert user_metadata["daily_desktop_planning_reason"] == "clear_daily_desktop_intent"
        assert user_metadata["daily_desktop_tool"]
        assert user_metadata["daily_desktop_tools"]
        assert assistant.content == agent_task["summary"]
        result["_events"] = events
        result["_task_timeline"] = task_timeline
        return result, agent_task, run, event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_conversation_overview_preserves_session_summary(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    monkeypatch.setattr(chat_bridge_mod, "get_activity_store", lambda: _EmptyActivityStore())
    try:
        runtime.chat_session.add_user_message("请分析 NativeRunEngine 迁移\n保留会话总结")
        runtime.chat_session.add_assistant_message(
            "已经保留 ChatBridge 会话概览。",
            task_id="session-task-1",
        )

        bridge = ChatBridge(runtime)
        sessions = bridge.get_recent_sessions(limit=3)
        overview = bridge.get_conversation_overview(summary_count=2, session_limit=3)

        assert sessions["ok"] is True
        current = sessions["sessions"][0]
        assert current["session_id"] == "session-current"
        assert current["summary"] == (
            "用户：请分析 NativeRunEngine 迁移 保留会话总结；回复：已经保留 ChatBridge 会话概览。"
        )
        assert current["latest_role"] == "assistant"
        assert current["latest_status"] == "completed"
        assert current["latest_task_id"] == "session-task-1"
        assert overview["ok"] is True
        assert overview["latest_reply"] == "已经保留 ChatBridge 会话概览。"
        assert overview["latest_reply_full"] == "已经保留 ChatBridge 会话概览。"
        assert overview["agent_task"]["task_id"] == "session-task-1"
        assert overview["agent_task"]["status"] == "waiting_approval"
        assert overview["agent_task"]["needs_user_action"] is True
        assert overview["agent_task"]["open_in_studio_url"] == "#/agents?run_id=session-task-1"
        assert overview["recent_sessions"][0]["summary"] == current["summary"]
        assert overview["recent_sessions"][0]["latest_task_id"] == "session-task-1"
    finally:
        store.close()


def test_chat_bridge_quick_message_returns_agent_task_snapshot_for_lightweight_entrypoints(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakeDesktopIntentRuntimeService()
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-browser",
            "task_id": "task-browser",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("打开 GitHub")

        assert result["ok"] is True
        assert result["task_id"] == "task-browser"
        assert result["status"] == "pending"
        assert result["echo"] == "打开 GitHub"
        assert result["agent_task"]["task_id"] == "task-browser"
        assert result["agent_task"]["conversation_id"] == "session-current"
        assert result["agent_task"]["status"] == "running"
        assert result["agent_task"]["current_step"] == "已回退执行 · 打开网页 · 系统浏览器"
        assert result["agent_task"]["open_in_studio_url"] == "#/agents?run_id=run-browser"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_completed"
        assert result["agent_task"]["recent_events"][0]["payload"]["source"] == "daily_desktop_intent"
        assert result["agent_task"]["tool_calls"][0]["tool_name"] == "browser.open_url"
        assert result["agent_task"]["tool_calls"][0]["status"] == "completed"
    finally:
        store.close()


def test_chat_bridge_quick_message_plans_structured_recovery_for_lightweight_entrypoints(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = None
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-recovery",
            "task_id": "task-recovery",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message(
            "修复屏幕录制",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
                "daily_desktop_intent": True,
                "desktop_permission_recovery": True,
                "recovery_tool": "app.open",
                "recovery_input": {"app_name": "屏幕录制权限"},
                "recovery_permission_target": "screen_recording",
                "recovery_risk_level": "low",
            },
        )

        assert result["ok"] is True
        assert result["task_id"] == "task-recovery"
        assert result["status"] == "pending"
        assert result["echo"] == "修复屏幕录制"
        assert result["agent_task"]["task_id"] == "task-recovery"
        assert result["agent_task"]["conversation_id"] == "session-current"
        assert result["agent_task"]["status"] == "queued"
        assert result["agent_task"]["current_step"] == "准备执行 · 打开应用"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
        assert result["agent_task"]["recent_events"][0]["payload"]["tool"] == "app.open"
        assert result["agent_task"]["recent_events"][0]["payload"]["input_preview"] == {
            "app_name": "屏幕录制权限"
        }
    finally:
        store.close()


def test_chat_bridge_quick_message_plans_multi_step_desktop_request_for_lightweight_entrypoints(
    tmp_path,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = None
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-multi-step",
            "task_id": "task-multi-step",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message(
            "打开 Notes，输入 hello，再复制",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
            },
        )

        assert result["ok"] is True
        assert result["task_id"] == "task-multi-step"
        assert result["agent_task"]["task_id"] == "task-multi-step"
        assert result["agent_task"]["conversation_id"] == "session-current"
        assert result["agent_task"]["status"] == "queued"
        assert result["agent_task"]["current_step"] == "准备执行 · 打开应用并输入文字"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
        assert result["agent_task"]["recent_events"][0]["payload"]["tool"] == (
            "app.open_and_safe_type_text"
        )
        assert result["agent_task"]["recent_events"][0]["payload"]["input_preview"] == {
            "app_name": "Notes",
            "text": "hello",
        }
    finally:
        store.close()


def test_chat_bridge_quick_message_executes_daily_desktop_task_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {
                "app_name": app_name,
                "launch_verified": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "可以帮我打开 Word 吗",
    )

    assert result["ok"] is True
    assert open_calls == ["Microsoft Word"]
    assert agent_task["summary"] == "已打开 Microsoft Word。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_opens_named_music_app_without_model(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {
                "app_name": app_name,
                "launch_verified": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "播放网易云音乐",
    )

    assert result["ok"] is True
    assert open_calls == ["网易云音乐"]
    assert agent_task["summary"] == "已打开网易云音乐。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_running_apps_without_model(
    tmp_path,
    monkeypatch,
):
    running_calls = 0

    def fake_running_apps() -> dict:
        nonlocal running_calls
        running_calls += 1
        return {
            "ok": True,
            "action": "desktop.running_apps",
            "summary": "Running apps: Finder, Google Chrome, Music",
            "data": {
                "apps": [
                    {"name": "Finder", "pid": 101, "frontmost": False},
                    {"name": "Google Chrome", "pid": 202, "frontmost": True},
                    {"name": "Music", "pid": 303, "frontmost": False},
                ],
                "frontmost": "Google Chrome",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.running_apps", fake_running_apps)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "现在开了哪些应用",
    )

    assert result["ok"] is True
    assert running_calls == 1
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "正在运行的应用：Finder, Google Chrome, Music。前台是 Google Chrome。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.running_apps"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_active_window_without_model(
    tmp_path,
    monkeypatch,
):
    active_window_calls = 0

    def fake_active_window() -> dict:
        nonlocal active_window_calls
        active_window_calls += 1
        return {
            "ok": True,
            "action": "desktop.active_window",
            "summary": "Foreground window: Google Chrome - ChatGPT",
            "data": {
                "app_name": "Google Chrome",
                "title": "ChatGPT",
                "pid": 202,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.active_window", fake_active_window)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "what app am I using?",
    )

    assert result["ok"] is True
    assert active_window_calls == 1
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "当前前台窗口是 Google Chrome：ChatGPT。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.active_window"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_named_windows_list_without_model(
    tmp_path,
    monkeypatch,
):
    windows_calls: list[str] = []

    def fake_windows(app_name: str = "") -> dict:
        windows_calls.append(app_name)
        return {
            "ok": True,
            "action": "desktop.windows",
            "summary": "Read Slack windows",
            "data": {
                "app_name": app_name,
                "windows": [
                    {"app_name": app_name or "Slack", "title": "general"},
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.windows", fake_windows)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "Slack窗口列表",
    )

    assert result["ok"] is True
    assert windows_calls == ["Slack"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "当前窗口：Slack: general。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.windows"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": "Slack"}
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_app_status_without_model(
    tmp_path,
    monkeypatch,
):
    status_calls: list[str] = []

    def fake_app_status(app_name: str) -> dict:
        status_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.status",
            "summary": f"{app_name} is running",
            "data": {"app_name": app_name, "running": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_status", fake_app_status)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "Chrome 开着吗",
    )

    assert result["ok"] is True
    assert status_calls == ["Google Chrome"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "Google Chrome 当前正在运行。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.status"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert agent_task["tool_calls"][-1]["input_preview"]["app_name"] == "Google Chrome"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_minimize_window_without_approval(
    tmp_path,
    monkeypatch,
):
    minimize_calls = 0

    def fake_minimize_window() -> dict:
        nonlocal minimize_calls
        minimize_calls += 1
        return {
            "ok": True,
            "action": "desktop.minimize_window",
            "summary": "Minimized the foreground window",
            "data": {"key": "m", "modifiers": ["command"]},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_minimize_window",
        fake_minimize_window,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "最小化当前窗口",
    )

    assert result["ok"] is True
    assert minimize_calls == 1
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已最小化当前窗口。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.minimize_window"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_hide_app_without_approval(
    tmp_path,
    monkeypatch,
):
    hide_calls = 0

    def fake_hide_app() -> dict:
        nonlocal hide_calls
        hide_calls += 1
        return {
            "ok": True,
            "action": "desktop.hide_app",
            "summary": "Hid the foreground app",
            "data": {"key": "h", "modifiers": ["command"]},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_hide_app",
        fake_hide_app,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "隐藏当前应用",
    )

    assert result["ok"] is True
    assert hide_calls == 1
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已隐藏当前应用。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.hide_app"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_named_app_hide_without_approval(
    tmp_path,
    monkeypatch,
):
    hide_calls: list[str] = []

    def fake_app_hide(app_name: str) -> dict:
        hide_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.hide",
            "summary": f"Hid {app_name}",
            "data": {"app_name": app_name, "hide_status": "hidden"},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.app_hide",
        fake_app_hide,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "隐藏 Slack",
    )

    assert result["ok"] is True
    assert hide_calls == ["Slack"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已隐藏 Slack。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.hide"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_named_app_show_without_approval(
    tmp_path,
    monkeypatch,
):
    show_calls: list[str] = []

    def fake_app_show(app_name: str) -> dict:
        show_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.show",
            "summary": f"Showed {app_name}",
            "data": {"app_name": app_name, "show_status": "shown", "restored_window_count": 1},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.app_show",
        fake_app_show,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Slack 并切到前台",
    )

    assert result["ok"] is True
    assert show_calls == ["Slack"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已显示 Slack。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.show"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_named_app_window_focus_without_approval(
    tmp_path,
    monkeypatch,
):
    focus_calls: list[tuple[str, str]] = []

    def fake_app_focus_window(app_name: str, title_contains: str) -> dict:
        focus_calls.append((app_name, title_contains))
        return {
            "ok": True,
            "action": "app.focus_window",
            "summary": f"Focused {app_name} window: {title_contains}",
            "data": {
                "app_name": app_name,
                "title_contains": title_contains,
                "focus_status": "focused",
                "window_index": 2,
                "window_title": title_contains,
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.app_focus_window",
        fake_app_focus_window,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "切到 Slack 的 general 窗口",
    )

    assert result["ok"] is True
    assert focus_calls == [("Slack", "general")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已切换到 Slack 的 general 窗口。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_window"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_named_app_minimize_without_approval(
    tmp_path,
    monkeypatch,
):
    minimize_calls: list[str] = []

    def fake_app_minimize(app_name: str) -> dict:
        minimize_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.minimize",
            "summary": f"Minimized {app_name}",
            "data": {"app_name": app_name, "minimize_status": "minimized", "window_count": 2},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.app_minimize",
        fake_app_minimize,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "最小化 Slack",
    )

    assert result["ok"] is True
    assert minimize_calls == ["Slack"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已最小化 Slack。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.minimize"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_natural_music_request_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    open_and_play_calls = 0

    def fake_apple_music_open_and_play() -> dict:
        nonlocal open_and_play_calls
        open_and_play_calls += 1
        return {
            "ok": True,
            "action": "media.apple_music_open_and_play",
            "summary": "Opened Music and started playback",
            "data": {
                "app_name": "Music",
                "open_ok": True,
                "playback_ok": True,
                "control": "play",
                "player_state": "playing",
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_open_and_play",
        fake_apple_music_open_and_play,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "Can you play Apple Music?",
    )

    assert result["ok"] is True
    assert open_and_play_calls == 1
    assert agent_task["summary"] == "已打开 Apple Music 并开始播放。当前：超时空辉夜姬 - Yachiyo。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "media.apple_music_open_and_play"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert result["_task_timeline"]["run_id"] == run["run_id"]
    assert result["_task_timeline"]["task_id"] == result["task_id"]
    assert result["_task_timeline"]["status"] == "completed"
    assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "media.apple_music_open_and_play"
    assert result["_task_timeline"]["tool_calls"][-1]["status"] == "completed"
    assert result["_task_timeline"]["tool_calls"][-1]["output_preview"]["data"]["track"] == "超时空辉夜姬"
    timeline_event_types = [
        event["event_type"] for event in result["_task_timeline"]["events"]
    ]
    assert timeline_event_types.index("agent.desktop.intent_planned") < timeline_event_types.index(
        "agent.tool.call"
    ) < timeline_event_types.index("agent.desktop.intent_completed")
    assert run["status"] == "completed"
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_music_followup_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    play_calls: list[str] = []

    def fake_apple_music_play(query: str) -> dict:
        play_calls.append(query)
        return {
            "ok": True,
            "action": "media.apple_music_play",
            "summary": f"Apple Music playing {query}",
            "data": {
                "query": query,
                "track": query,
                "artist": "Yachiyo",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_play",
        fake_apple_music_play,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "超时空辉夜姬吧",
        seed_messages=[
            ("user", "能否帮我播放 Apple Music?"),
            ("assistant", "想听哪首歌？"),
        ],
    )

    assert result["ok"] is True
    assert play_calls == ["超时空辉夜姬"]
    assert agent_task["summary"] == "已在 Apple Music 播放：超时空辉夜姬 - Yachiyo。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
    assert result["_task_timeline"]["tool_calls"][-1]["status"] == "completed"
    assert result["_task_timeline"]["tool_calls"][-1]["output_preview"]["data"]["track"] == "超时空辉夜姬"
    run_event_types = [event["event_type"] for event in result["_events"]]
    assert run_event_types.index("agent.desktop.intent_planned") < run_event_types.index(
        "agent.tool.call"
    ) < run_event_types.index("agent.desktop.intent_completed")
    assert run["status"] == "completed"
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_app_search_followup_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: find",
            "data": {"shortcut_action": action, "key": "f", "modifiers": ["command"]},
        }

    def fake_safe_type_text(text: str) -> dict:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "搜索张三",
        seed_messages=[
            ("user", "打开微信"),
            ("assistant", "已打开 WeChat。"),
        ],
    )

    assert result["ok"] is True
    assert calls == [("focus", "WeChat"), ("shortcut", "find"), ("type", "张三")]
    assert agent_task["summary"] == "已切到 WeChat 并打开查找。 已向前台输入文字（2 个字符）。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
    ]
    assert result["_task_timeline"]["tool_calls"][-2]["tool_name"] == "app.focus_and_safe_shortcut"
    assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "desktop.safe_type_text"
    run_event_types = [event["event_type"] for event in result["_events"]]
    assert run_event_types.count("agent.desktop.intent_planned") == 2
    assert run_event_types.index("agent.desktop.intent_planned") < run_event_types.index(
        "agent.tool.call"
    ) < run_event_types.index("agent.desktop.intent_completed")
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_browser_read_followup_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    extract_calls: list[str] = []

    def fake_extract_text(selector: str = "") -> dict:
        extract_calls.append(selector)
        return {
            "ok": True,
            "action": "browser.extract_text",
            "summary": "Extracted 29 characters from browser page",
            "data": {
                "selector": selector,
                "text": "Yachiyo desktop agent runtime",
                "truncated": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.extract_text", fake_extract_text)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "读取内容",
        seed_messages=[
            ("user", "打开 GitHub"),
            ("assistant", "已打开 GitHub。"),
        ],
    )

    assert result["ok"] is True
    assert extract_calls == [""]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "Yachiyo desktop agent runtime"
    assert agent_task["tool_calls"][-1]["tool_name"] == "browser.extract_text"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "browser.extract_text"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_requires_approval_for_browser_click_followup(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-browser-click-followup.db",
        workspace_dir=tmp_path / "runtime-browser-click-followup",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    runtime.chat_session.add_user_message("打开 GitHub")
    runtime.chat_session.add_assistant_message("已打开 GitHub。")
    click_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher browser click follow-up should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )

    def fake_browser_click(selector: str, **kwargs: Any) -> dict:
        click_calls.append((selector, int(kwargs.get("click_count") or 1)))
        return {
            "ok": True,
            "action": "browser.click",
            "summary": "Clicked browser selector",
            "data": {
                "selector": selector,
                "label": "登录",
                "tag": "BUTTON",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.click", fake_browser_click)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "点登录",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert click_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == "browser.click"
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "selector": "text=登录",
            "click_count": 1,
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "browser.click"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert click_calls == [("text=登录", 1)]
        assert approved.status == "completed"
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_browser_open_url_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    opened_urls: list[str] = []

    def fake_open_url(url: str) -> dict:
        opened_urls.append(url)
        return {
            "ok": True,
            "action": "browser.open_url",
            "summary": f"Opened {url}",
            "data": {"url": url},
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开浏览器并访问 GitHub",
    )

    assert opened_urls == ["https://github.com"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开网页：https://github.com。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_browser_open_url_and_extract_text(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_open_url(url: str) -> dict:
        calls.append(("open", url))
        return {
            "ok": True,
            "action": "browser.open_url",
            "summary": f"Opened {url}",
            "data": {"url": url},
        }

    def fake_extract_text(selector: str = "") -> dict:
        calls.append(("extract", selector))
        return {
            "ok": True,
            "action": "browser.extract_text",
            "summary": "Extracted 31 characters from browser page",
            "data": {
                "selector": selector,
                "text": "GitHub page text for Yachiyo",
                "truncated": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    monkeypatch.setattr("apps.shell.agent.tools.browser.extract_text", fake_extract_text)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 GitHub 并读一下页面",
    )

    assert calls == [("open", "https://github.com"), ("extract", "")]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "GitHub page text for Yachiyo"
    assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url_and_extract_text"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_system_volume_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    volume_calls: list[tuple[str, object, object]] = []

    def fake_system_volume(action: str, *, level=None, step=None) -> dict:
        volume_calls.append((action, level, step))
        return {
            "ok": True,
            "action": "system.volume",
            "summary": "System volume increased from 40% to 50%",
            "data": {
                "requested_action": action,
                "old_level": 40,
                "old_muted": False,
                "level": 50,
                "muted": False,
                "changed": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.system_volume", fake_system_volume)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "调大音量",
    )

    assert volume_calls == [("up", None, None)]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已把系统音量从 40% 调高到 50%。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "system.volume"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_clipboard_write_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    clipboard_calls: list[str] = []

    def fake_clipboard_write(text: str) -> dict:
        clipboard_calls.append(text)
        return {
            "ok": True,
            "action": "clipboard.write",
            "summary": "Copied 11 characters to clipboard",
            "data": {
                "text_length": len(text),
                "platform": "macos",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.clipboard_write", fake_clipboard_write)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "copy hello world to clipboard",
    )

    assert clipboard_calls == ["hello world"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已复制 11 个字符到剪贴板。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "clipboard.write"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_open_path_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []

    def fake_open_path(path: str) -> dict:
        open_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.open_path",
            "summary": f"Opened {path}",
            "data": {
                "path": path,
                "open_target": "system_open",
                "exists": True,
                "is_dir": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.open_path", fake_open_path)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开下载文件夹",
    )

    assert open_calls == ["~/Downloads"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开文件夹：~/Downloads。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_reveal_path_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    reveal_calls: list[str] = []

    def fake_reveal_path(path: str) -> dict:
        reveal_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.reveal_path",
            "summary": f"Revealed {path}",
            "data": {
                "path": path,
                "open_target": "finder_reveal",
                "exists": True,
                "is_dir": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.reveal_path", fake_reveal_path)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "在 Finder 中显示 ~/Downloads/report.pdf",
    )

    assert reveal_calls == ["~/Downloads/report.pdf"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已在 Finder 中显示：~/Downloads/report.pdf。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.reveal_path"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_screen_capture_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    capture_targets: list[str] = []

    def fake_screen_capture(target_path) -> dict:
        capture_targets.append(str(target_path))
        return {
            "ok": True,
            "action": "screen.capture",
            "summary": "已截取当前屏幕。",
            "data": {
                "path": str(target_path),
                "mime_type": "image/png",
                "size_bytes": 10,
                "width": 100,
                "height": 80,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.screen_capture", fake_screen_capture)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "当前屏幕是什么",
    )

    assert capture_targets
    assert capture_targets[0].endswith("screenshots/current-screen.png")
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已截取当前屏幕。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "screen.capture"
    assert agent_task["artifacts"][-1]["path"] == "screenshots/current-screen.png"
    assert run["status"] == "completed"
    assert "artifact.created" in event_types
    assert "agent.desktop.intent_completed" in event_types


def test_chat_bridge_quick_message_executes_browser_extract_text_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    extract_calls: list[str] = []

    def fake_extract_text(selector: str = "") -> dict:
        extract_calls.append(selector)
        return {
            "ok": True,
            "action": "browser.extract_text",
            "summary": "Extracted 29 characters from browser page",
            "data": {
                "selector": selector,
                "text": "Yachiyo desktop agent runtime",
                "truncated": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.extract_text", fake_extract_text)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "read this page",
    )

    assert extract_calls == [""]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "Yachiyo desktop agent runtime"
    assert agent_task["tool_calls"][-1]["tool_name"] == "browser.extract_text"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_browser_screenshot_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    screenshot_targets: list[str] = []

    def fake_browser_screenshot(target_path) -> dict:
        screenshot_targets.append(str(target_path))
        return {
            "ok": True,
            "action": "browser.screenshot",
            "summary": "Captured current browser page",
            "data": {
                "path": str(target_path),
                "mime_type": "image/png",
                "format": "png",
                "size": 10,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.screenshot", fake_browser_screenshot)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "screenshot this page",
    )

    assert screenshot_targets
    assert screenshot_targets[0].endswith("browser/current-page.png")
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已截取当前网页。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "browser.screenshot"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert agent_task["artifacts"][-1]["path"] == "browser/current-page.png"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "artifact.created" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_permission_diagnosis_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    permission_calls: list[bool] = []

    def fake_permissions() -> dict:
        permission_calls.append(True)
        return {
            "ok": True,
            "action": "desktop.permissions",
            "summary": "Desktop permissions ready",
            "data": {
                "permission_targets": [],
                "affected_tools": [],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.permissions", fake_permissions)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "检查桌面权限",
    )

    assert permission_calls == [True]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "桌面执行权限已就绪。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.permissions"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_safe_shortcut_without_approval(
    tmp_path,
    monkeypatch,
):
    shortcut_calls: list[str] = []

    def fake_safe_shortcut(action: str) -> dict:
        shortcut_calls.append(action)
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: copy",
            "data": {
                "shortcut_action": action,
                "key": "c",
                "modifiers": ["command"],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "复制一下选中的内容",
    )

    assert shortcut_calls == ["copy"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已复制选中内容。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_shortcut"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_safe_type_text_without_approval(
    tmp_path,
    monkeypatch,
):
    typed_text: list[str] = []

    def fake_safe_type_text(text: str) -> dict:
        typed_text.append(text)
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "输入 你好八千代",
    )

    assert typed_text == ["你好八千代"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已向前台输入文字（5 个字符）。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_type_text"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_app_open_and_safe_type_text_without_approval(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_type_text(text: str) -> dict:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Notes 并输入 hello yachiyo",
    )

    assert calls == [("open", "Notes"), ("focus", "Notes"), ("type", "hello yachiyo")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Notes 并输入文字（13 个字符）。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open_and_safe_type_text"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_multi_step_daily_desktop_intent_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []
    permission_probe_calls: list[bool] = []
    permission_cache_warmed = False

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_type_text(text: str) -> dict:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: copy",
            "data": {"shortcut_action": action, "key": "c", "modifiers": ["command"]},
        }

    def fake_permission_probe(use_cache: bool = True) -> dict[str, list[str]]:
        nonlocal permission_cache_warmed
        permission_probe_calls.append(use_cache)
        permission_cache_warmed = True
        return {"foreground_input": ["accessibility"]}

    def fake_permission_preflight() -> dict:
        if not permission_cache_warmed:
            return {
                "ok": True,
                "action": "desktop.permission_preflight",
                "permission_error": False,
                "permission_targets": [],
                "affected_tools": [],
                "recovery_actions": [],
                "data": {"ready": True},
            }
        return {
            "ok": True,
            "action": "desktop.permission_preflight",
            "permission_error": True,
            "permission_targets": ["accessibility"],
            "affected_tools": ["app.open_and_safe_type_text", "desktop.safe_shortcut"],
            "recovery_actions": [
                {
                    "label": "打开辅助功能权限",
                    "tool": "app.open",
                    "input": {"app_name": "辅助功能权限"},
                    "permission_target": "accessibility",
                    "risk_level": "low",
                }
            ],
            "diagnostic_route": "/yachiyo/readiness",
            "data": {
                "ready": False,
                "permission_targets": ["accessibility"],
                "affected_tools": ["app.open_and_safe_type_text", "desktop.safe_shortcut"],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Notes，输入 hello，再复制",
        permission_probe=fake_permission_probe,
        permission_preflight=fake_permission_preflight,
    )

    assert calls == [
        ("open", "Notes"),
        ("focus", "Notes"),
        ("type", "hello"),
        ("shortcut", "copy"),
    ]
    assert permission_probe_calls == [True]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Notes 并输入文字（5 个字符）。 已复制选中内容。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
    ]
    assert run["status"] == "completed"
    assert event_types.count("agent.desktop.intent_planned") == 2
    assert "agent.desktop.permission_preflight" in event_types
    assert event_types.index("agent.desktop.permission_preflight") < event_types.index(
        "tool.requested"
    )
    preflight_event = next(
        event
        for event in _result["_events"]
        if event["event_type"] == "agent.desktop.permission_preflight"
    )
    assert preflight_event["payload"]["permission_targets"] == ["accessibility"]
    assert preflight_event["payload"]["affected_tools"] == [
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
    ]
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_app_find_sequence_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut",
            "data": {"shortcut_action": action},
        }

    def fake_safe_type_text(text: str) -> dict:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"text": text, "character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Notes，然后搜索 hello",
    )

    assert calls == [
        ("open", "Notes"),
        ("focus", "Notes"),
        ("shortcut", "find"),
        ("type", "hello"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Notes 并打开查找。 已向前台输入文字（5 个字符）。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
    ]
    assert run["status"] == "completed"
    assert event_types.count("agent.desktop.intent_planned") == 2
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_safe_click_without_approval(
    tmp_path,
    monkeypatch,
):
    clicked: list[tuple[int, int]] = []

    def fake_safe_click(x: int, y: int) -> dict:
        clicked.append((x, y))
        return {
            "ok": True,
            "action": "desktop.safe_click",
            "summary": "Clicked explicit foreground coordinate at (120, 240)",
            "data": {
                "x": x,
                "y": y,
                "click_count": 1,
                "explicit_user_coordinates": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_click", fake_safe_click)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "点击 120, 240",
    )

    assert clicked == [(120, 240)]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已点击前台位置：120, 240。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_click"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_surfaces_safe_click_accessibility_recovery(
    tmp_path,
    monkeypatch,
):
    osascript_calls: list[tuple[str, list[str] | None]] = []
    monkeypatch.setattr("apps.shell.agent.tools.desktop._desktop_platform", lambda: "macos")

    def fake_run_osascript(script: str, args: list[str] | None = None) -> dict:
        osascript_calls.append((script, args))
        return {
            "ok": False,
            "summary": "osascript failed",
            "error": "Not authorized to send Apple events to System Events. Accessibility permission denied.",
            "permission_error": True,
            "fallback_used": False,
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop._run_osascript", fake_run_osascript)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "点击 120, 240",
    )
    timeline = result["_task_timeline"]
    recovery_event = next(
        event
        for event in timeline["events"]
        if event["event_type"] == "agent.desktop.permission_recovery"
    )

    assert osascript_calls
    assert osascript_calls[0][1] == ["120", "240", "1"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert "桌面操作未完成：Not authorized to send Apple events to System Events." in agent_task["summary"]
    assert "缺少权限：accessibility" in agent_task["summary"]
    assert "可直接打开：打开辅助功能权限。" in agent_task["summary"]
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_click"
    assert agent_task["tool_calls"][-1]["status"] == "failed"
    assert agent_task["tool_calls"][-1]["output_preview"]["permission_error"] is True
    assert agent_task["tool_calls"][-1]["output_preview"]["permission_targets"] == ["accessibility"]
    assert agent_task["tool_calls"][-1]["output_preview"]["recovery_actions"] == [
        {
            "label": "打开辅助功能权限",
            "tool": "app.open",
            "input": {"app_name": "辅助功能权限"},
            "permission_target": "accessibility",
            "recovery_retry_input": {"x": 120, "y": 240},
            "recovery_retry_prompt": "点击 120, 240",
            "recovery_retry_tool": "desktop.safe_click",
            "retry_input": {"x": 120, "y": 240},
            "retry_prompt": "点击 120, 240",
            "retry_tool": "desktop.safe_click",
            "risk_level": "low",
        }
    ]
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.permission_recovery" in event_types
    assert "model.request.started" not in event_types
    assert recovery_event["payload"]["permission_targets"] == ["accessibility"]
    assert recovery_event["payload"]["affected_tools"] == ["desktop.safe_click"]
    assert recovery_event["payload"]["recovery_actions"] == agent_task["tool_calls"][-1]["output_preview"]["recovery_actions"]


def test_chat_bridge_quick_message_surfaces_browser_cdp_recovery(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("apps.shell.agent.tools.browser._configured_browser_cdp_url", lambda: "")
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "当前网页是什么",
    )
    timeline = result["_task_timeline"]
    recovery_event = next(
        event
        for event in timeline["events"]
        if event["event_type"] == "agent.desktop.permission_recovery"
    )

    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert "桌面操作未完成：chrome_cdp_unavailable" in agent_task["summary"]
    assert "缺少权限：chrome_cdp" in agent_task["summary"]
    assert "可直接打开：打开 Google Chrome。" in agent_task["summary"]
    assert agent_task["tool_calls"][-1]["tool_name"] == "browser.current_page"
    assert agent_task["tool_calls"][-1]["status"] == "failed"
    assert agent_task["tool_calls"][-1]["output_preview"]["permission_error"] is True
    assert agent_task["tool_calls"][-1]["output_preview"]["permission_targets"] == ["chrome_cdp"]
    assert agent_task["tool_calls"][-1]["output_preview"]["recovery_actions"] == [
        {
            "label": "打开 Google Chrome",
            "tool": "app.open",
            "input": {"app_name": "Google Chrome"},
            "permission_target": "chrome_cdp",
            "recovery_retry_input": {},
            "recovery_retry_prompt": "查看当前网页",
            "recovery_retry_tool": "browser.current_page",
            "retry_input": {},
            "retry_prompt": "查看当前网页",
            "retry_tool": "browser.current_page",
            "risk_level": "low",
        }
    ]
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.permission_recovery" in event_types
    assert "model.request.started" not in event_types
    assert recovery_event["payload"]["permission_targets"] == ["chrome_cdp"]
    assert recovery_event["payload"]["affected_tools"] == ["browser.current_page"]
    assert recovery_event["payload"]["recovery_actions"] == agent_task["tool_calls"][-1]["output_preview"]["recovery_actions"]


def test_chat_bridge_quick_message_executes_structured_recovery_action_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-recovery-action.db",
        workspace_dir=tmp_path / "runtime-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    open_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher structured recovery action should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {
                "app_name": app_name,
                "open_target": "system_settings",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "修复屏幕录制",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
                "daily_desktop_intent": True,
                "desktop_permission_recovery": True,
                "recovery_tool": "app.open",
                "recovery_input": {"app_name": "屏幕录制权限"},
                "recovery_permission_target": "screen_recording",
                "recovery_risk_level": "low",
            },
        )
        agent_task = result["agent_task"]
        run = service.get_run(result["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]
        messages = store.load_messages("session-current", limit=10)
        user = next(message for message in messages if message.role == "user")
        user_metadata = json.loads(user.metadata_json)

        assert result["ok"] is True
        assert open_calls == ["屏幕录制权限"]
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已打开屏幕录制权限。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
        assert agent_task["tool_calls"][-1]["input_preview"]["app_name"] == "屏幕录制权限"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert user_metadata["desktop_permission_recovery"] is True
        assert user_metadata["recovery_tool"] == "app.open"
        assert user_metadata["recovery_input"] == {"app_name": "屏幕录制权限"}
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_approval_executes_and_completes_launcher_task(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-approval.db",
        workspace_dir=tmp_path / "runtime-approval",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    hotkey_calls: list[tuple[str, list[str] | None]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher hotkey approval should not call model")
        ),
    )

    def fake_hotkey(key: str, *, modifiers: list[str] | None = None) -> dict:
        hotkey_calls.append((key, modifiers))
        return {
            "ok": True,
            "action": "desktop.hotkey",
            "summary": "Sent hotkey",
            "data": {
                "key": key,
                "modifiers": list(modifiers or []),
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_hotkey", fake_hotkey)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "按 Command+L",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert hotkey_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == "desktop.hotkey"
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "desktop.hotkey"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert hotkey_calls == [("l", ["command"])]
        assert approved.status == "completed"
        assert approved.summary == "已发送快捷键：Command+L。"
        assert approved.needs_user_action is False
        assert approved.pending_approvals == []
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.output.completed" in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_browser_click_approval_executes_and_completes(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-browser-click-approval.db",
        workspace_dir=tmp_path / "runtime-browser-click-approval",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    click_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher browser click approval should not call model")
        ),
    )

    def fake_browser_click(selector: str, **kwargs: Any) -> dict:
        click_calls.append((selector, int(kwargs.get("click_count") or 1)))
        return {
            "ok": True,
            "action": "browser.click",
            "summary": "Clicked browser selector",
            "data": {
                "selector": selector,
                "label": "登录",
                "tag": "BUTTON",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.click", fake_browser_click)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "点击当前网页上的登录按钮",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert click_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == "browser.click"
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "selector": "text=登录",
            "click_count": 1,
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "browser.click"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert click_calls == [("text=登录", 1)]
        assert approved.status == "completed"
        assert approved.summary == "已点击网页元素：登录。"
        assert approved.needs_user_action is False
        assert approved.pending_approvals == []
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.output.completed" in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_requires_approval_for_app_quit(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-app-quit-approval.db",
        workspace_dir=tmp_path / "runtime-app-quit-approval",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    quit_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher app quit approval should not call model")
        ),
    )

    def fake_app_quit(app_name: str) -> dict:
        quit_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.quit",
            "summary": f"Quit {app_name}",
            "data": {"app_name": app_name, "running": False},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_quit", fake_app_quit)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "退出 Slack",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert quit_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == "app.quit"
        assert "退出应用 Slack" in waiting_task["pending_approvals"][0]["policy_reason"]
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.quit"
        assert waiting_run["pending_approval"]["input_preview"] == {"app_name": "Slack"}

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert quit_calls == ["Slack"]
        assert approved.status == "completed"
        assert approved.summary == "已退出 Slack。"
        assert approved.needs_user_action is False
        assert approved.pending_approvals == []
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.output.completed" in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_requires_approval_for_foreground_input_tools(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-foreground-approval.db",
        workspace_dir=tmp_path / "runtime-foreground-approval",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher foreground approval should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_type_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("type_text should wait for approval")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_click",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("click should wait for approval")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_close_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("close_window should wait for approval")
        ),
    )
    bridge = ChatBridge(runtime)
    try:
        cases = [
            ("关闭当前窗口", "desktop.close_window", {}),
        ]
        for text, tool_name, input_preview in cases:
            result = bridge.send_quick_message(
                text,
                metadata={
                    "source": "launcher",
                    "launcher_mode": "bubble",
                    "launcher_surface": "quick_message",
                },
            )
            task_id = result["task_id"]
            waiting_task = result["agent_task"]
            link = service.get_task_run_link(task_id)
            waiting_run = service.get_run(link["run_id"])

            assert result["ok"] is True
            assert waiting_task["status"] == "waiting_approval"
            assert waiting_task["needs_user_action"] is True
            assert waiting_task["pending_approvals"][0]["tool_name"] == tool_name
            assert waiting_run["status"] == "approval_required"
            assert waiting_run["pending_approval"]["tool"] == tool_name
            assert waiting_run["pending_approval"]["input_preview"] == input_preview
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_waits_briefly_for_daily_desktop_snapshot(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakeDelayedDesktopIntentRuntimeService()
    monkeypatch.setattr(chat_bridge_mod, "_QUICK_DESKTOP_SNAPSHOT_ATTEMPTS", 2)
    monkeypatch.setattr(chat_bridge_mod, "_QUICK_DESKTOP_SNAPSHOT_DELAY_SECONDS", 0)
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-delayed-browser",
            "task_id": "task-delayed-browser",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("打开 GitHub")

        assert result["ok"] is True
        assert result["task_id"] == "task-delayed-browser"
        assert result["agent_task"]["task_id"] == "task-delayed-browser"
        assert result["agent_task"]["status"] == "running"
        assert result["agent_task"]["current_step"] == "已回退执行 · 打开网页 · 系统浏览器"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_completed"
        assert result["agent_task"]["tool_calls"][0]["tool_name"] == "browser.open_url"
        assert runtime.agent_runtime_service.calls == [
            ("get_task_run_link", "task-delayed-browser"),
            ("get_task_run_link", "task-delayed-browser"),
            ("get_task_run_link", "task-delayed-browser"),
        ]
    finally:
        store.close()


def test_chat_bridge_quick_message_returns_planned_desktop_task_before_run_link(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakePendingDesktopIntentRuntimeService()
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-pending-browser",
            "task_id": "task-pending-browser",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("打开 GitHub")

        assert result["ok"] is True
        assert result["task_id"] == "task-pending-browser"
        assert result["status"] == "pending"
        assert result["echo"] == "打开 GitHub"
        assert result["agent_task"]["task_id"] == "task-pending-browser"
        assert result["agent_task"]["conversation_id"] == "session-current"
        assert result["agent_task"]["status"] == "queued"
        assert result["agent_task"]["current_step"] == "准备执行 · 打开网页"
        assert result["agent_task"]["progress_text"] == "准备执行 · 打开网页"
        assert result["agent_task"]["open_in_studio_url"] is None
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
        assert result["agent_task"]["recent_events"][0]["detail"] == "browser.open_url"
        assert result["agent_task"]["recent_events"][0]["payload"] == {
            "input_preview": {"url": "https://github.com"},
            "planning_reason": "clear_daily_desktop_intent",
            "source": "daily_desktop_intent",
            "status": "planned",
            "tool": "browser.open_url",
        }
        assert runtime.agent_runtime_service.calls == [
            ("get_task_run_link", "task-pending-browser")
        ] * chat_bridge_mod._QUICK_DESKTOP_SNAPSHOT_ATTEMPTS
    finally:
        store.close()


def test_chat_bridge_quick_message_plans_screen_capture_for_lightweight_entrypoints(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakePendingDesktopIntentRuntimeService()
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-screen",
            "task_id": "task-screen",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("帮我看看现在屏幕")

        assert result["ok"] is True
        assert result["task_id"] == "task-screen"
        assert result["agent_task"]["task_id"] == "task-screen"
        assert result["agent_task"]["status"] == "queued"
        assert result["agent_task"]["current_step"] == "准备执行 · 截取屏幕"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
        assert result["agent_task"]["recent_events"][0]["detail"] == "screen.capture"
        assert result["agent_task"]["recent_events"][0]["payload"] == {
            "input_preview": {"reason": "user asked to capture the screen"},
            "planning_reason": "clear_daily_desktop_intent",
            "source": "daily_desktop_intent",
            "status": "planned",
            "tool": "screen.capture",
        }
    finally:
        store.close()


def test_chat_bridge_quick_message_keeps_plain_chat_without_planned_agent_task(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakePendingDesktopIntentRuntimeService()
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-plain",
            "task_id": "task-plain",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("今天状态怎么样？")

        assert result == {
            "ok": True,
            "message_id": "message-plain",
            "task_id": "task-plain",
            "status": "pending",
            "echo": "今天状态怎么样？",
        }
        assert runtime.agent_runtime_service.calls == [("get_task_run_link", "task-plain")]
    finally:
        store.close()


def test_chat_bridge_quick_message_forwards_entrypoint_metadata(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    bridge = ChatBridge(runtime)
    received: dict[str, object] = {}

    def send_message(text, **kwargs):
        received["text"] = text
        received["metadata"] = kwargs.get("metadata")
        return {
            "ok": True,
            "message_id": "message-launcher",
            "task_id": "",
            "status": "pending",
        }

    bridge._chat_api = SimpleNamespace(send_message=send_message)
    try:
        result = bridge.send_quick_message(
            "打开 Cursor",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
            },
        )

        assert result["ok"] is True
        assert received == {
            "text": "打开 Cursor",
            "metadata": {
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
            },
        }
    finally:
        store.close()


def test_session_summary_uses_processing_and_failed_statuses():
    assert chat_bridge_mod._session_summary([
        {
            "role": "user",
            "content": "生成最终验收清单",
            "status": "processing",
            "created_at": "2026-06-10T00:00:00+00:00",
        }
    ]) == "处理中：生成最终验收清单"
    assert chat_bridge_mod._session_summary([
        {
            "role": "user",
            "content": "运行发布验证",
            "status": "completed",
            "created_at": "2026-06-10T00:00:00+00:00",
        },
        {
            "role": "assistant",
            "content": "provider error: token redacted",
            "status": "failed",
            "created_at": "2026-06-10T00:01:00+00:00",
        },
    ]) == "失败：provider error: token redacted"


class _FakeAgentRuntimeService:
    def get_run(self, run_id: str):
        return {
            "run_id": run_id,
            "user_goal": "Launcher Agent Task",
            "status": "approval_required",
            "pending_approval": {
                "approval_id": "approval-1",
                "tool": "terminal.run",
                "input_preview": {"command": "pytest"},
            },
            "timeline": [
                {
                    "event": "agent.tool.approval_required",
                    "detail": "terminal.run",
                }
            ],
        }


class _FakeDesktopIntentRuntimeService:
    def get_task_run_link(self, task_id: str):
        assert task_id == "task-browser"
        return {
            "task_id": task_id,
            "run_id": "run-browser",
            "session_id": "session-current",
        }

    def get_run(self, run_id: str):
        assert run_id == "run-browser"
        return {
            "run_id": run_id,
            "kind": "main_chat_run",
            "user_goal": "打开 GitHub",
            "status": "running",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "browser.open_url",
                    "payload": {
                        "tool": "browser.open_url",
                        "source": "daily_desktop_intent",
                        "result": {
                            "ok": True,
                            "fallback_used": True,
                            "fallback": "system_browser",
                            "data": {"url": "https://github.com"},
                        },
                    },
                }
            ],
        }


class _FakeDelayedDesktopIntentRuntimeService:
    def __init__(self) -> None:
        self.calls = []

    def get_task_run_link(self, task_id: str):
        self.calls.append(("get_task_run_link", task_id))
        if len(self.calls) == 1:
            raise KeyError(task_id)
        return {
            "task_id": task_id,
            "run_id": "run-delayed-browser",
            "session_id": "session-current",
        }

    def get_run(self, run_id: str):
        assert run_id == "run-delayed-browser"
        return {
            "run_id": run_id,
            "kind": "main_chat_run",
            "user_goal": "打开 GitHub",
            "status": "running",
            "timeline": [
                {
                    "event_type": "agent.desktop.intent_completed",
                    "detail": "browser.open_url",
                    "payload": {
                        "tool": "browser.open_url",
                        "source": "daily_desktop_intent",
                        "result": {
                            "ok": True,
                            "fallback_used": True,
                            "fallback": "system_browser",
                            "data": {"url": "https://github.com"},
                        },
                    },
                }
            ],
        }


class _FakePendingDesktopIntentRuntimeService:
    def __init__(self) -> None:
        self.calls = []

    def get_task_run_link(self, task_id: str):
        self.calls.append(("get_task_run_link", task_id))
        raise KeyError(task_id)
