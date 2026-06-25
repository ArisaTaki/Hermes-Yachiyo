"""ChatBridge session overview tests."""

from __future__ import annotations

import json
from datetime import date, timedelta
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
    launcher_mode: str = "live2d",
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
                "launcher_mode": launcher_mode,
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
        policy_decision_events = [
            event for event in events if event["event_type"] == "agent.tool.policy_decision"
        ]
        messages = store.load_messages("session-current", limit=10)
        user = [message for message in messages if message.role == "user"][-1]
        assistant = [message for message in messages if message.role == "assistant"][-1]
        user_metadata = json.loads(user.metadata_json)

        assert result["ok"] is True
        assert agent_task["task_id"] == result["task_id"]
        assert agent_task["conversation_id"] == "session-current"
        assert agent_task["open_in_studio_url"] == f"#/agents?run_id={run['run_id']}"
        assert user_metadata["source"] == "launcher"
        assert user_metadata["launcher_mode"] == launcher_mode
        assert user_metadata["daily_desktop_intent"] is True
        assert user_metadata["daily_desktop_source"] == "daily_desktop_intent"
        assert user_metadata["daily_desktop_planning_reason"] == "clear_daily_desktop_intent"
        assert user_metadata["daily_desktop_tool"]
        assert user_metadata["daily_desktop_tools"]
        assert policy_decision_events
        assert policy_decision_events[0]["payload"]["decision"] == "allow"
        assert policy_decision_events[0]["payload"]["policy_scope"] == "daily_desktop"
        assert policy_decision_events[0]["payload"]["tool"] == user_metadata["daily_desktop_tool"]
        if agent_task["status"] == "waiting_approval":
            assert assistant.content in {
                agent_task["summary"],
                "等待你在 Agent Studio 中审批后继续。",
            }
        else:
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


def test_chat_bridge_agent_session_quick_message_uses_daily_desktop_overlay_for_lightweight_entrypoints(tmp_path, monkeypatch):
    for mode in ("bubble", "live2d"):
        store = ChatStore(db_path=str(tmp_path / f"{mode}-chat.db"))
        runtime = _runtime_with_chat_store(store)
        agent = {
            "id": "agent_native",
            "name": "Native Agent",
            "nickname": "Native Agent",
            "kind": "agent",
            "enabled": True,
            "tool_policy": {
                "allowed_tools": ["workspace.read"],
                "approval_required": {},
            },
        }
        captured: list[dict[str, Any]] = []

        class FakeRunnableService:
            def list_runnables(self):
                return {"runnables": [agent]}

            def parse_known_chat_runnable(self, text):
                if text.startswith("@Native Agent"):
                    return "Native Agent", text.replace("@Native Agent", "", 1).strip()
                return None

            def resolve_runnable(self, *, runnable_id="", name=""):
                if runnable_id == agent["id"] or name == agent["name"] or name == agent["nickname"]:
                    return agent
                return None

            def create_run_for_runnable_async(self, **kwargs):
                captured.append(dict(kwargs))
                run = {
                    "run_id": f"{mode}-agent-run-{len(captured)}",
                    "run_group_id": kwargs.get("run_group_id") or f"{mode}-run-group-{len(captured)}",
                    "status": "processing",
                    "result": "",
                    "runnable": agent,
                }
                on_complete = kwargs.get("on_complete")
                if on_complete:
                    on_complete({
                        **run,
                        "status": "completed",
                        "result": "Agent result",
                    })
                return run

        runtime.agent_runtime_service = FakeRunnableService()
        bridge = ChatBridge(runtime)
        try:
            first = bridge.send_quick_message(
                "@Native Agent 你好",
                metadata={
                    "source": "launcher",
                    "launcher_mode": mode,
                    "launcher_surface": "quick_message",
                },
            )
            assert first["ok"] is True
            assert "daily_desktop_policy_overlay" not in captured[-1]

            second = bridge.send_quick_message(
                "能否帮我播放apple Music?",
                metadata={
                    "source": "launcher",
                    "launcher_mode": mode,
                    "launcher_surface": "quick_message",
                },
            )

            assert second["ok"] is True
            assert captured[-1]["runnable_id"] == agent["id"]
            assert captured[-1]["user_goal"] == "能否帮我播放apple Music?"
            assert captured[-1]["daily_desktop_policy_overlay"] is True
            user = [message for message in runtime.chat_session.get_messages() if message.role == "user"][-1]
            assert user.metadata["launcher_mode"] == mode
            assert user.metadata["daily_desktop_tool"] == "media.apple_music_open_and_play"
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


def test_chat_bridge_quick_message_opens_system_ui_apps_without_model(
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
    cases = (
        ("打开启动台", "bubble", "Launchpad", "已打开 Launchpad。"),
        ("open control center", "live2d", "Control Center", "已打开 Control Center。"),
        ("open notification center", "bubble", "Notification Center", "已打开 Notification Center。"),
    )
    for text, launcher_mode, app_name, summary in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert open_calls[-1] == app_name
        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": app_name}
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_opens_system_settings_pane_without_model(
    tmp_path,
    monkeypatch,
):
    settings_calls: list[str] = []

    def fake_system_settings_open(target: str) -> dict:
        settings_calls.append(target)
        return {
            "ok": True,
            "action": "system.settings_open",
            "summary": f"Opened System Settings: {target}",
            "data": {
                "target": target,
                "open_target": "system_settings",
                "settings_label": target,
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.system_settings_open",
        fake_system_settings_open,
    )
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开蓝牙",
    )

    assert result["ok"] is True
    assert settings_calls == ["蓝牙"]
    assert agent_task["summary"] == "已打开系统设置：蓝牙。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "system.settings_open"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"target": "蓝牙"}
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types

    cases = (
        ("打开 Wi-Fi", "bubble", "Wi-Fi", "已打开系统设置：Wi-Fi。"),
        ("打开无线网络", "live2d", "Wi-Fi", "已打开系统设置：Wi-Fi。"),
        ("打开网络", "bubble", "网络", "已打开系统设置：网络。"),
        ("打开显示设置", "live2d", "显示器", "已打开系统设置：显示器。"),
        ("打开声音设置", "bubble", "声音", "已打开系统设置：声音。"),
        ("open sound settings", "live2d", "声音", "已打开系统设置：声音。"),
        ("打开键盘设置", "bubble", "键盘", "已打开系统设置：键盘。"),
        ("open keyboard settings", "live2d", "键盘", "已打开系统设置：键盘。"),
        ("打开通知设置", "bubble", "通知", "已打开系统设置：通知。"),
        ("open notification settings", "live2d", "通知", "已打开系统设置：通知。"),
        ("打开定位权限", "bubble", "定位服务", "已打开系统设置：定位服务。"),
        ("打开系统设置里的辅助功能", "bubble", "辅助功能权限", "已打开系统设置：辅助功能权限。"),
        ("打开系统设置里的辅助功能", "live2d", "辅助功能权限", "已打开系统设置：辅助功能权限。"),
        ("打开隐私", "bubble", "隐私与安全性", "已打开系统设置：隐私与安全性。"),
        ("open desktop permissions", "live2d", "隐私与安全性", "已打开系统设置：隐私与安全性。"),
        ("打开输入监控权限", "bubble", "输入监控", "已打开系统设置：输入监控。"),
        ("打开完全磁盘访问权限", "live2d", "完全磁盘访问", "已打开系统设置：完全磁盘访问。"),
        ("打开摄像头权限", "bubble", "摄像头", "已打开系统设置：摄像头。"),
        ("修复自动化权限", "bubble", "自动化权限", "已打开系统设置：自动化权限。"),
        ("修一下屏幕录制权限", "live2d", "屏幕录制权限", "已打开系统设置：屏幕录制权限。"),
        ("fix full disk access permissions", "bubble", "完全磁盘访问", "已打开系统设置：完全磁盘访问。"),
        ("fix input monitoring permissions", "live2d", "输入监控", "已打开系统设置：输入监控。"),
    )
    for prompt, launcher_mode, target, summary in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "system.settings_open"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"target": target}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert settings_calls == [
        "蓝牙",
        "Wi-Fi",
        "Wi-Fi",
        "网络",
        "显示器",
        "声音",
        "声音",
        "键盘",
        "键盘",
        "通知",
        "通知",
        "定位服务",
        "辅助功能权限",
        "辅助功能权限",
        "隐私与安全性",
        "隐私与安全性",
        "输入监控",
        "完全磁盘访问",
        "摄像头",
        "自动化权限",
        "屏幕录制权限",
        "完全磁盘访问",
        "输入监控",
    ]


def test_chat_bridge_quick_message_focuses_app_for_polite_launcher_entrypoint(
    tmp_path,
    monkeypatch,
):
    focus_calls: list[str] = []

    def fake_app_focus(app_name: str) -> dict:
        focus_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    cases = (
        ("能不能切到 Slack", "bubble", "Slack"),
        ("切一下微信", "bubble", "WeChat"),
        ("微信切一下", "live2d", "WeChat"),
        ("你能帮我切到Chrome吗", "bubble", "Google Chrome"),
        ("你可以帮我聚焦Chrome吗", "live2d", "Google Chrome"),
        ("go back to WeChat", "bubble", "WeChat"),
        ("switch back to WeChat", "live2d", "WeChat"),
    )
    for prompt, launcher_mode, app_name in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == f"已切换到 {app_name}。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": app_name}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert focus_calls == [
        "Slack",
        "WeChat",
        "WeChat",
        "Google Chrome",
        "Google Chrome",
        "WeChat",
        "WeChat",
    ]


def test_chat_bridge_quick_message_opens_notes_and_creates_note_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: new note",
            "data": {
                "shortcut_action": action,
                "shortcut_label": "new note",
            },
        }

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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.browser.extract_text", fake_extract_text)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "open Notes and make a new note",
    )

    assert result["ok"] is True
    assert calls == [
        ("open", "Notes"),
        ("focus", "Notes"),
        ("shortcut", "new_note"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Notes 并新建笔记。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open_and_safe_shortcut"
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "app_name": "Notes",
        "action": "new_note",
    }
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types

    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "summarize current webpage",
        launcher_mode="live2d",
    )

    assert extract_calls == [""]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "网页内容摘要：\n- Yachiyo desktop agent runtime"
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


def test_chat_bridge_quick_message_opens_notes_creates_note_and_types_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str, str, str]] = []

    def fake_notes_create(body: str, *, title: str = "", folder_name: str = "") -> dict:
        calls.append(("note", body, title, folder_name))
        return {
            "ok": True,
            "action": "notes.create",
            "summary": "Created note: hello",
            "data": {"title": "hello", "body_length": len(body), "folder_name": folder_name},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.notes_create", fake_notes_create)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "新建一个备忘录写 hello",
    )

    assert result["ok"] is True
    assert calls == [("note", "hello", "", "")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已创建备忘录：hello（5 个字符）。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-1:]] == [
        "notes.create",
    ]
    assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "notes.create"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types

    cases = (
        ("新建备忘录 hello", "bubble"),
        ("帮我记下 hello", "live2d"),
        ("帮我新建备忘录：hello", "bubble"),
    )
    for prompt, launcher_mode in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert calls[-1] == ("note", "hello", "", "")
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已创建备忘录：hello（5 个字符）。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "notes.create"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types


def test_chat_bridge_quick_message_opens_word_and_creates_document_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: new document",
            "data": {
                "shortcut_action": action,
                "shortcut_label": "new document",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Word 新建文档",
    )

    assert result["ok"] is True
    assert calls == [
        ("open", "Microsoft Word"),
        ("focus", "Microsoft Word"),
        ("shortcut", "new_document"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Microsoft Word 并新建文档。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open_and_safe_shortcut"
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "app_name": "Microsoft Word",
        "action": "new_document",
    }
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_opens_calendar_and_creates_event_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: new calendar event",
            "data": {
                "shortcut_action": action,
                "shortcut_label": "new calendar event",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    cases = (
        (
            "打开日历新建日程",
            "bubble",
            "app.open_and_safe_shortcut",
            "已打开 Calendar 并新建日程。",
        ),
        (
            "日历新建日程",
            "live2d",
            "app.focus_and_safe_shortcut",
            "已切到 Calendar 并新建日程。",
        ),
    )
    for prompt, launcher_mode, tool_name, summary in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == summary
        assert agent_task["tool_calls"][-1]["tool_name"] == tool_name
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Calendar",
            "action": "new_event",
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert calls == [
        ("open", "Calendar"),
        ("focus", "Calendar"),
        ("shortcut", "new_event"),
        ("focus", "Calendar"),
        ("shortcut", "new_event"),
    ]


def test_chat_bridge_quick_message_opens_named_music_app_without_model(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []
    music_calls: list[str] = []

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

    def fake_music_app_open_and_play(app_name: str) -> dict:
        music_calls.append(app_name)
        return {
            "ok": True,
            "action": "media.music_app_open_and_play",
            "summary": f"Opened {app_name} and attempted playback with media key",
            "data": {
                "app_name": app_name,
                "playback_state_unverified": True,
            },
            "permission_error": False,
            "fallback_used": True,
            "fallback": "system_media_key",
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.music_app_open_and_play",
        fake_music_app_open_and_play,
    )
    app_cases = (
        ("微信帮我打开一下", "live2d", "WeChat"),
        ("open WeChat for me", "bubble", "WeChat"),
        ("你能帮我打开微信吗", "live2d", "WeChat"),
        ("你能启动一下备忘录吗", "bubble", "Notes"),
        ("Could you launch Calendar for me?", "live2d", "Calendar"),
        ("Would you open Notes please?", "bubble", "Notes"),
    )
    for prompt, launcher_mode, app_name in app_cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == f"已打开 {app_name}。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": app_name}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    music_cases = (
        ("打开 Spotify 播放周杰伦", "bubble", "Spotify", "已打开 Spotify，并用媒体键尝试开始播放。"),
        ("用 Spotify 播放音乐", "live2d", "Spotify", "已打开 Spotify，并用媒体键尝试开始播放。"),
        ("打开网易云并播放", "bubble", "网易云音乐", "已打开网易云音乐，并用媒体键尝试开始播放。"),
        ("可以帮我打开网易云并播放吗", "live2d", "网易云音乐", "已打开网易云音乐，并用媒体键尝试开始播放。"),
        ("Could you launch Spotify and play music?", "bubble", "Spotify", "已打开 Spotify，并用媒体键尝试开始播放。"),
    )
    for prompt, launcher_mode, app_name, expected_summary in music_cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == expected_summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "media.music_app_open_and_play"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": app_name}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert music_calls == ["Spotify", "Spotify", "网易云音乐", "网易云音乐", "Spotify"]

    assert open_calls == ["WeChat", "WeChat", "WeChat", "Notes", "Calendar", "Notes"]


def test_chat_bridge_quick_message_opens_default_browser_without_model(
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
    cases = (
        ("打开默认浏览器", "live2d"),
        ("打开网页", "bubble"),
        ("open a browser", "live2d"),
        ("open a webpage", "bubble"),
    )
    for prompt, launcher_mode in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == "已打开 Google Chrome。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": "Google Chrome"}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert open_calls == ["Google Chrome", "Google Chrome", "Google Chrome", "Google Chrome"]


def test_chat_bridge_quick_message_opens_explicit_desktop_client_without_model(
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
    cases = (
        ("打开 ChatGPT 客户端", "live2d", "ChatGPT"),
        ("打开文件夹", "bubble", "Finder"),
        ("open a folder", "live2d", "Finder"),
    )
    for prompt, launcher_mode, app_name in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == f"已打开 {app_name}。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": app_name}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert open_calls == ["ChatGPT", "Finder", "Finder"]


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
        "当前有哪些 App 在运行",
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
    cases = (
        ("what app am I using?", "live2d"),
        ("what is the frontmost window", "bubble"),
    )
    for prompt, launcher_mode in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
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

    assert active_window_calls == 2


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
        "what windows are open in Slack",
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


def test_chat_bridge_quick_message_focuses_app_then_reads_ui_elements(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, object, object]] = []

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name, None))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_ui_elements(role_filter: str = "", limit: int = 80) -> dict:
        calls.append(("ui", role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read Slack buttons",
            "data": {
                "app_name": "Slack",
                "title": "general",
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "Send",
                        "center": {"x": 640, "y": 720},
                    },
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "what buttons are visible in Slack",
    )

    assert result["ok"] is True
    assert calls == [("focus", "Slack", None), ("ui", "button", 80)]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == (
        "已切换到 Slack。 当前 Slack 界面控件：Button Send（640, 720）。"
    )
    assert [call["tool_name"] for call in agent_task["tool_calls"][-2:]] == [
        "app.focus",
        "desktop.ui_elements",
    ]
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "role_filter": "button",
        "limit": 80,
    }
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_reads_current_ui_elements_without_fake_app_focus(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, object, object]] = []

    def fake_ui_elements(role_filter: str = "", limit: int = 80) -> dict:
        calls.append(("ui", role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read current buttons",
            "data": {
                "app_name": "Google Chrome",
                "title": "ChatGPT",
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "Send",
                        "center": {"x": 640, "y": 720},
                    },
                ],
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.app_focus",
        lambda app_name: (_ for _ in ()).throw(
            AssertionError(f"current UI query should not focus fake app: {app_name}")
        ),
    )
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "你能看看现在有哪些按钮吗",
    )

    assert calls == [("ui", "button", 80)]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["summary"] == "当前 Google Chrome 界面控件：Button Send（640, 720）。"
    assert [call["tool_name"] for call in agent_task["tool_calls"][-1:]] == [
        "desktop.ui_elements",
    ]
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "role_filter": "button",
        "limit": 80,
    }
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "读一下当前界面文字",
    )

    assert calls[-1] == ("ui", "text", 80)
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.ui_elements"
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "role_filter": "text",
        "limit": 80,
    }
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_opens_app_then_reads_ui_elements_for_chinese_followup(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, object, object]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name, None))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_ui_elements(role_filter: str = "", limit: int = 80) -> dict:
        calls.append(("ui", role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read WeChat buttons",
            "data": {
                "app_name": "WeChat",
                "title": "Chats",
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "搜索",
                        "center": {"x": 120, "y": 88},
                    },
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开微信看看有什么按钮",
    )

    assert result["ok"] is True
    assert calls == [("open", "WeChat", None), ("ui", "button", 80)]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == (
        "已打开 WeChat。 当前 WeChat 界面控件：Button 搜索（120, 88）。"
    )
    assert [call["tool_name"] for call in agent_task["tool_calls"][-2:]] == [
        "app.open",
        "desktop.ui_elements",
    ]
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "role_filter": "button",
        "limit": 80,
    }
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert event_types.count("agent.desktop.intent_planned") == 2
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_opens_system_settings_then_reads_options_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, object, object]] = []

    def fake_system_settings_open(target: str) -> dict:
        calls.append(("settings", target, None))
        return {
            "ok": True,
            "action": "system.settings_open",
            "summary": f"Opened System Settings: {target}",
            "data": {
                "target": target,
                "open_target": "system_settings",
                "settings_label": "System Settings",
            },
        }

    def fake_ui_elements(role_filter: str = "", limit: int = 80) -> dict:
        calls.append(("ui", role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read System Settings options",
            "data": {
                "app_name": "System Settings",
                "title": "Settings",
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "General",
                        "center": {"x": 120, "y": 88},
                    },
                ],
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.system_settings_open",
        fake_system_settings_open,
    )
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    for launcher_mode in ("bubble", "live2d"):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "打开系统设置看看有哪些选项",
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == (
            "已打开系统设置。 当前 System Settings 界面控件："
            "Button General（120, 88）。"
        )
        assert [call["tool_name"] for call in agent_task["tool_calls"][-2:]] == [
            "system.settings_open",
            "desktop.ui_elements",
        ]
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "role_filter": "",
            "limit": 80,
        }
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert event_types.count("agent.desktop.intent_planned") == 2
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert calls == [
        ("settings", "系统设置", None),
        ("ui", "", 80),
        ("settings", "系统设置", None),
        ("ui", "", 80),
    ]


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
    cases = (
        ("最小化当前窗口", "bubble"),
        ("隐藏当前窗口", "bubble"),
        ("隐藏前台窗口", "live2d"),
        ("Can you minimize the current app?", "live2d"),
        ("Could you minimize the foreground application please?", "bubble"),
    )
    for index, (text, launcher_mode) in enumerate(cases, start=1):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert minimize_calls == index
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
    cases = (
        ("隐藏当前应用", "bubble"),
        ("你可以帮我隐藏一下前台应用吗", "live2d"),
        ("Can you hide the current app?", "bubble"),
        ("Could you hide the foreground app please?", "live2d"),
    )
    for index, (text, launcher_mode) in enumerate(cases, start=1):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert hide_calls == index
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


def test_chat_bridge_quick_message_executes_app_prefix_hide_for_launcher_entrypoints(
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

    for launcher_mode in ("bubble", "live2d"):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 收起来",
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已隐藏 Google Chrome。"
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

    assert hide_calls == ["Google Chrome", "Google Chrome"]


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
    cases = (
        ("打开 Slack 并切到前台", "live2d", "Slack"),
        ("把微信调出来", "bubble", "WeChat"),
        ("你能帮我显示Finder吗", "live2d", "Finder"),
        ("你能帮我还原微信吗", "bubble", "WeChat"),
    )
    for prompt, launcher_mode, app_name in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == f"已显示 {app_name}。"
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

    assert show_calls == ["Slack", "WeChat", "Finder", "WeChat"]


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


def test_chat_bridge_quick_message_executes_app_prefix_minimize_for_launcher_entrypoints(
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

    for launcher_mode in ("bubble", "live2d"):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 最小化一下",
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已最小化 Google Chrome。"
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

    assert minimize_calls == ["Google Chrome", "Google Chrome"]


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

    launcher_prompts = [
        ("能帮我播放 Apple Music 吗", "bubble"),
        ("给我来点音乐", "bubble"),
        ("帮我用 Apple Music 放一首歌", "live2d"),
        ("用 Apple Music 随便放点歌", "bubble"),
        ("打开 Apple Music 播放音乐", "live2d"),
        ("打开 Apple Music 随便放点音乐", "bubble"),
        ("播放一下 Apple Music 里的歌", "live2d"),
        ("Apple Music 随便放点", "bubble"),
        ("Music app play something", "live2d"),
        ("start playing in Music", "bubble"),
        ("放音乐听听", "live2d"),
        ("听点音乐", "bubble"),
        ("想听音乐", "live2d"),
        ("我想听歌", "bubble"),
        ("听一首歌", "live2d"),
        ("播点东西", "bubble"),
        ("play something", "live2d"),
        ("I want to listen to music", "bubble"),
        ("用 Apple Music 听点音乐", "bubble"),
        ("播放苹果音乐", "live2d"),
    ]
    for prompt, launcher_mode in launcher_prompts:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == "已打开 Apple Music 并开始播放。当前：超时空辉夜姬 - Yachiyo。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "media.apple_music_open_and_play"
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert result["_task_timeline"]["run_id"] == run["run_id"]
        assert result["_task_timeline"]["status"] == "completed"
        assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "media.apple_music_open_and_play"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert open_and_play_calls == 21


def test_chat_bridge_quick_message_executes_natural_schedule_creation_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    tomorrow = date.today() + timedelta(days=1)
    tomorrow_1000 = f"{tomorrow.isoformat()}T10:00"
    tomorrow_1100 = f"{tomorrow.isoformat()}T11:00"
    calls: list[tuple[str, str, str, str]] = []

    def fake_calendar_create_event(
        title: str,
        *,
        start_at: str,
        end_at: str | None = None,
        calendar_name: str = "",
    ) -> dict:
        calls.append(("calendar", title, start_at, str(end_at or "")))
        return {
            "ok": True,
            "action": "calendar.create_event",
            "summary": "Created calendar event",
            "data": {
                "title": title,
                "start_at": start_at,
                "end_at": str(end_at or ""),
                "calendar_name": calendar_name,
            },
        }

    def fake_reminders_create(title: str, *, due_at: str | None = None, list_name: str = "") -> dict:
        calls.append(("reminder", title, str(due_at or ""), list_name))
        return {
            "ok": True,
            "action": "reminders.create",
            "summary": "Created reminder",
            "data": {
                "title": title,
                "due_at": str(due_at or ""),
                "list_name": list_name,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.calendar_create_event", fake_calendar_create_event)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.reminders_create", fake_reminders_create)

    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "创建明天上午10点开会的日程",
        launcher_mode="bubble",
    )

    assert result["ok"] is True
    assert calls[-1] == ("calendar", "开会", tomorrow_1000, tomorrow_1100)
    assert agent_task["summary"] == f"已创建日历事件：开会（{tomorrow_1000} - {tomorrow_1100}）。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "calendar.create_event"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types

    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "创建明天上午10点开会的提醒",
        launcher_mode="live2d",
    )

    assert result["ok"] is True
    assert calls[-1] == ("reminder", "开会", tomorrow_1000, "")
    assert agent_task["summary"] == f"已创建提醒事项：开会（{tomorrow_1000}）。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "reminders.create"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types

    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "明天上午10点提醒我开会",
        launcher_mode="bubble",
    )

    assert result["ok"] is True
    assert calls[-1] == ("reminder", "开会", tomorrow_1000, "")
    assert agent_task["summary"] == f"已创建提醒事项：开会（{tomorrow_1000}）。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "reminders.create"
    assert run["status"] == "completed"
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

    direct_prompts = (
        ("我想听超时空辉夜姬吧", "bubble", "超时空辉夜姬"),
        ("播放超时空辉夜姬 Apple Music", "live2d", "超时空辉夜姬"),
        ("放点周杰伦", "bubble", "周杰伦"),
        ("播点轻音乐", "live2d", "轻音乐"),
        ("play some jazz", "bubble", "jazz"),
        ("play Some Nights", "live2d", "Some Nights"),
        ("帮我在 Apple Music 搜一下超时空辉夜姬并播放", "bubble", "超时空辉夜姬"),
        ("Apple Music 搜索超时空辉夜姬并播放", "live2d", "超时空辉夜姬"),
        ("search Space Oddity in Apple Music and play it", "bubble", "Space Oddity"),
        ("Apple Music search Space Oddity and play it", "live2d", "Space Oddity"),
        ("search Apple Music for Taylor Swift and play it", "bubble", "Taylor Swift"),
    )
    for prompt, launcher_mode, query in direct_prompts:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert play_calls[-1] == query
        assert agent_task["summary"] == f"已在 Apple Music 播放：{query} - Yachiyo。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"query": query}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
        assert result["_task_timeline"]["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert play_calls == ["超时空辉夜姬"] + [query for _prompt, _launcher_mode, query in direct_prompts]


def test_chat_bridge_quick_message_executes_music_control_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    control_calls: list[str] = []

    def fake_apple_music_control(action: str) -> dict:
        control_calls.append(action)
        return {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": f"Apple Music {action} executed",
            "data": {
                "control": action,
                "player_state": "playing",
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_control",
        fake_apple_music_control,
    )

    cases = (
        ("换首歌", "bubble", "next", "已切到下一首 Apple Music。当前：超时空辉夜姬 - Yachiyo。"),
        ("换首歌", "live2d", "next", "已切到下一首 Apple Music。当前：超时空辉夜姬 - Yachiyo。"),
        ("继续放歌", "bubble", "play", "已继续播放 Apple Music。当前：超时空辉夜姬 - Yachiyo。"),
        ("恢复音乐", "live2d", "play", "已继续播放 Apple Music。当前：超时空辉夜姬 - Yachiyo。"),
        ("pause the music", "bubble", "pause", "已暂停 Apple Music。当前：超时空辉夜姬 - Yachiyo。"),
    )
    for prompt, launcher_mode, expected_action, expected_summary in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == expected_summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "media.apple_music_control"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"action": expected_action}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert result["_task_timeline"]["run_id"] == run["run_id"]
        assert result["_task_timeline"]["status"] == "completed"
        assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "media.apple_music_control"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert control_calls == ["next", "next", "play", "play", "pause"]


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


def test_chat_bridge_quick_message_executes_app_search_field_type_without_approval(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

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

    def fake_search_submit() -> dict:
        calls.append(("search_submit", ""))
        return {
            "ok": True,
            "action": "desktop.search_submit",
            "summary": "",
            "data": {"key": "return", "modifiers": []},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_search_submit", fake_search_submit)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Slack 点击搜索框输入 yachiyo 并搜索",
    )

    assert result["ok"] is True
    assert calls == [
        ("open", "Slack"),
        ("focus", "Slack"),
        ("shortcut", "find"),
        ("type", "yachiyo"),
        ("search_submit", ""),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == (
        "已打开 Slack 并打开查找。 已向前台输入文字（7 个字符）。 已提交前台搜索。"
    )
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-3:]] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
    ]
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types

    launcher_cases = [
        ("在微信搜索文件传输助手", "bubble", "WeChat", "文件传输助手"),
        ("Apple Music 搜索超时空辉夜姬", "live2d", "Music", "超时空辉夜姬"),
    ]
    for prompt, launcher_mode, app_name, typed_text in launcher_cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert calls[-3:] == [
            ("focus", app_name),
            ("shortcut", "find"),
            ("type", typed_text),
        ]
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == (
            f"已切到 {app_name} 并打开查找。 已向前台输入文字（{len(typed_text)} 个字符）。"
        )
        assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
        ]
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types


def test_chat_bridge_quick_message_prepares_comm_message_then_waits_for_send_approval(
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
            "data": {"shortcut_action": action},
        }

    def fake_safe_type_text(text: str) -> dict:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    def fake_search_submit() -> dict:
        calls.append(("search_submit", ""))
        return {
            "ok": True,
            "action": "desktop.search_submit",
            "summary": "",
            "data": {"key": "return", "modifiers": []},
        }

    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-comm-approval.db",
        workspace_dir=tmp_path / "runtime-comm-approval",
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
            AssertionError("launcher communication compose should not call model")
        ),
    )
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_search_submit", fake_search_submit)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_submit_foreground",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("submit_foreground should wait for approval")
        ),
    )
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "在微信给张三发你好",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
            },
        )
        agent_task = result["agent_task"]
        link = service.get_task_run_link(result["task_id"])
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]
    finally:
        service.close()
        store.close()

    assert result["ok"] is True
    assert calls == [
        ("focus", "WeChat"),
        ("shortcut", "find"),
        ("type", "张三"),
        ("search_submit", ""),
        ("type", "你好"),
    ]
    assert agent_task["status"] == "waiting_approval"
    assert agent_task["needs_user_action"] is True
    assert agent_task["pending_approvals"][0]["tool_name"] == "desktop.submit_foreground"
    assert run["status"] == "approval_required"
    assert run["pending_approval"]["tool"] == "desktop.submit_foreground"
    assert run["pending_approval"]["input_preview"] == {"action": "send"}
    assert "agent.desktop.intent_approval_required" in event_types
    assert "agent.desktop.intent_completed" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


def test_chat_bridge_quick_message_executes_foreground_search_type_submit_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

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

    def fake_search_submit() -> dict:
        calls.append(("search_submit", ""))
        return {
            "ok": True,
            "action": "desktop.search_submit",
            "summary": "",
            "data": {"key": "return", "modifiers": []},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_search_submit", fake_search_submit)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "点搜索框输入 yachiyo 然后搜索",
    )

    assert result["ok"] is True
    assert calls == [("shortcut", "find"), ("type", "yachiyo"), ("search_submit", "")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开查找。 已向前台输入文字（7 个字符）。 已提交前台搜索。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-3:]] == [
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
    ]
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert event_types.count("agent.desktop.intent_planned") == 3
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
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

    for prompt, launcher_mode in (
        ("总结当前网页", "bubble"),
        ("what is this page about", "live2d"),
    ):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "网页内容摘要：\n- Yachiyo desktop agent runtime"
        assert agent_task["tool_calls"][-1]["tool_name"] == "browser.extract_text"
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert result["_task_timeline"]["tool_calls"][-1]["tool_name"] == "browser.extract_text"
        planned_event = next(
            event
            for event in result["_task_timeline"]["events"]
            if event["event_type"] == "agent.desktop.intent_planned"
            and event["payload"].get("presentation") == "summary"
        )
        completed_event = next(
            event
            for event in result["_task_timeline"]["events"]
            if event["event_type"] == "agent.desktop.intent_completed"
        )
        assert planned_event["payload"]["presentation"] == "summary"
        assert completed_event["payload"]["presentation"] == "summary"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types

    assert extract_calls == ["", "", ""]


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


def test_chat_bridge_quick_message_opens_browser_then_requires_approval_for_page_click(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-browser-open-click.db",
        workspace_dir=tmp_path / "runtime-browser-open-click",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    open_calls: list[str] = []
    click_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher browser open+click should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.browser.click", fake_browser_click)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开 Chrome 点击登录按钮",
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
        assert open_calls == ["Google Chrome"]
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

        assert open_calls == ["Google Chrome"]
        assert click_calls == [("text=登录", 1)]
        assert approved.status == "completed"
        assert approved.summary == "已打开 Google Chrome。 已点击网页元素：登录。"
        assert approved.needs_user_action is False
        assert approved.pending_approvals == []
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_searches_then_requires_approval_for_first_result_click(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-browser-search-click.db",
        workspace_dir=tmp_path / "runtime-browser-search-click",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    open_calls: list[str] = []
    click_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher browser search+click should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )

    def fake_open_url(url: str) -> dict:
        open_calls.append(url)
        return {
            "ok": True,
            "action": "browser.open_url",
            "summary": f"Opened browser page: {url}",
            "data": {"url": url, "title": "Search"},
        }

    def fake_browser_click(selector: str, **kwargs: Any) -> dict:
        click_calls.append((selector, int(kwargs.get("click_count") or 1)))
        return {
            "ok": True,
            "action": "browser.click",
            "summary": "Clicked browser selector",
            "data": {
                "selector": selector,
                "label": "Yachiyo result",
                "tag": "A",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    monkeypatch.setattr("apps.shell.agent.tools.browser.click", fake_browser_click)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开 Chrome 搜索 yachiyo 然后打开第一个结果",
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
        assert open_calls == ["https://www.google.com/search?q=yachiyo"]
        assert click_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert any(
            call["tool_name"] == "browser.open_url" and call["status"] == "completed"
            for call in waiting_task["tool_calls"]
        )
        assert waiting_task["pending_approvals"][0]["tool_name"] == "browser.click"
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "selector": "search-result=1",
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

        assert open_calls == ["https://www.google.com/search?q=yachiyo"]
        assert click_calls == [("search-result=1", 1)]
        assert approved.status == "completed"
        assert approved.summary == (
            "已打开网页：https://www.google.com/search?q=yachiyo。 "
            "已点击网页元素：Yachiyo result。"
        )
        assert approved.needs_user_action is False
        assert approved.pending_approvals == []
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_requires_approval_for_app_scoped_ui_click(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-app-ui-click.db",
        workspace_dir=tmp_path / "runtime-app-ui-click",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    focus_calls: list[str] = []
    click_calls: list[tuple[str, str, int, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher app-scoped UI click should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )

    def fake_app_focus(app_name: str) -> dict:
        focus_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_click_ui_element(
        target: str,
        *,
        role_filter: str = "",
        limit: int = 80,
        click_count: int = 1,
    ) -> dict:
        click_calls.append((target, role_filter, limit, click_count))
        return {
            "ok": True,
            "action": "desktop.click_ui_element",
            "summary": f"Clicked {target}",
            "data": {"target": target, "role_filter": role_filter},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.click_ui_element",
        fake_click_ui_element,
    )
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "click the Send button in Slack",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert focus_calls == []
        assert click_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == (
            "app.focus_and_click_ui_element"
        )
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "app_name": "Slack",
            "target": "Send",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.focus_and_click_ui_element"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert focus_calls == ["Slack"]
        assert click_calls == [("Send", "button", 80, 1)]
        assert approved.status == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_requires_approval_for_app_open_ui_click(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-app-open-ui-click.db",
        workspace_dir=tmp_path / "runtime-app-open-ui-click",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    open_calls: list[str] = []
    focus_calls: list[str] = []
    click_calls: list[tuple[str, str, int, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher app open UI click should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_app_focus(app_name: str) -> dict:
        focus_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_click_ui_element(
        target: str,
        *,
        role_filter: str = "",
        limit: int = 80,
        click_count: int = 1,
    ) -> dict:
        click_calls.append((target, role_filter, limit, click_count))
        return {
            "ok": True,
            "action": "desktop.click_ui_element",
            "summary": f"Clicked {target}",
            "data": {"target": target, "role_filter": role_filter},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.click_ui_element",
        fake_click_ui_element,
    )
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开 Slack 点搜索",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert open_calls == []
        assert focus_calls == []
        assert click_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == (
            "app.open_and_click_ui_element"
        )
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "app_name": "Slack",
            "target": "搜索",
            "role_filter": "",
            "limit": 80,
            "click_count": 1,
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.open_and_click_ui_element"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert open_calls == ["Slack"]
        assert focus_calls == ["Slack"]
        assert click_calls == [("搜索", "", 80, 1)]
        assert approved.status == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_continues_after_app_open_non_search_ui_click_approval(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-app-open-ui-click-then-type.db",
        workspace_dir=tmp_path / "runtime-app-open-ui-click-then-type",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    open_calls: list[str] = []
    focus_calls: list[str] = []
    click_calls: list[tuple[str, str, int, int]] = []
    typed_text: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher app open UI click then type should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_app_focus(app_name: str) -> dict:
        focus_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_click_ui_element(
        target: str,
        *,
        role_filter: str = "",
        limit: int = 80,
        click_count: int = 1,
    ) -> dict:
        click_calls.append((target, role_filter, limit, click_count))
        return {
            "ok": True,
            "action": "desktop.click_ui_element",
            "summary": f"Clicked {target}",
            "data": {"target": target, "role_filter": role_filter},
        }

    def fake_safe_type_text(text: str) -> dict:
        typed_text.append(text)
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.click_ui_element",
        fake_click_ui_element,
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_type_text",
        fake_safe_type_text,
    )
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开 Slack 点频道输入 yachiyo",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert open_calls == []
        assert focus_calls == []
        assert click_calls == []
        assert typed_text == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == (
            "app.open_and_click_ui_element"
        )
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "app_name": "Slack",
            "target": "频道",
            "role_filter": "",
            "limit": 80,
            "click_count": 1,
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.open_and_click_ui_element"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert open_calls == ["Slack"]
        assert focus_calls == ["Slack"]
        assert click_calls == [("频道", "", 80, 1)]
        assert typed_text == ["yachiyo"]
        assert approved.status == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_requires_approval_for_app_open_type_into_ui_element(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-app-open-type-into-ui.db",
        workspace_dir=tmp_path / "runtime-app-open-type-into-ui",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    open_calls: list[str] = []
    focus_calls: list[str] = []
    type_calls: list[tuple[str, str, str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher app open UI type should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_app_focus(app_name: str) -> dict:
        focus_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_type_into_ui_element(
        target: str,
        text: str,
        *,
        role_filter: str = "",
        limit: int = 80,
    ) -> dict:
        type_calls.append((target, text, role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.type_into_ui_element",
            "summary": f"Typed into {target}",
            "data": {
                "target": target,
                "text": text,
                "role_filter": role_filter,
                "character_count": len(text),
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.type_into_ui_element",
        fake_type_into_ui_element,
    )
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开微信在消息框输入文件传输助手",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
            },
        )
        task_id = result["task_id"]
        waiting_task = result["agent_task"]
        link = service.get_task_run_link(task_id)
        waiting_run = service.get_run(link["run_id"])

        assert result["ok"] is True
        assert open_calls == []
        assert focus_calls == []
        assert type_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == (
            "app.open_and_type_into_ui_element"
        )
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "app_name": "WeChat",
            "target": "消息",
            "text": "文件传输助手",
            "role_filter": "text",
            "limit": 80,
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.open_and_type_into_ui_element"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert open_calls == ["WeChat"]
        assert focus_calls == ["WeChat"]
        assert type_calls == [("消息", "文件传输助手", "text", 80)]
        assert approved.status == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_app_scoped_search_field_type_without_approval(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开微信在搜索框输入文件传输助手",
    )

    assert result["ok"] is True
    assert calls == [
        ("open", "WeChat"),
        ("focus", "WeChat"),
        ("shortcut", "find"),
        ("type", "文件传输助手"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 WeChat 并打开查找。 已向前台输入文字（6 个字符）。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
    ]
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


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

    local_url_cases = (
        ("打开 127.0.0.1:5173", "bubble", "http://127.0.0.1:5173"),
        ("打开本地 127.0.0.1:5173", "bubble", "http://127.0.0.1:5173"),
        ("打开网页 github.com", "live2d", "https://github.com"),
        ("open 192.168.1.10:8000/status", "live2d", "http://192.168.1.10:8000/status"),
        ("Can you search Chrome for weather?", "bubble", "https://www.google.com/search?q=weather"),
    )
    for prompt, launcher_mode, url in local_url_cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == f"已打开网页：{url}。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"url": url}
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "百度 open hanako",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "已打开网页：https://www.baidu.com/s?wd=open+hanako。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url"
        assert agent_task["tool_calls"][-1]["input_preview"]["url"] == "https://www.baidu.com/s?wd=open+hanako"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert opened_urls == [
        "https://github.com",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5173",
        "https://github.com",
        "http://192.168.1.10:8000/status",
        "https://www.google.com/search?q=weather",
        "https://www.baidu.com/s?wd=open+hanako",
        "https://www.baidu.com/s?wd=open+hanako",
    ]


def test_chat_bridge_quick_message_executes_address_bar_url_without_approval(
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
        "在地址栏输入 github.com 并回车",
    )

    assert opened_urls == ["https://github.com"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开网页：https://github.com。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url"
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.intent_approval_required" not in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


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
    cases = [
        ("打开 GitHub 并读一下页面", "live2d", "https://github.com", "GitHub page text for Yachiyo", ""),
        ("打开 GitHub 看看内容", "bubble", "https://github.com", "GitHub page text for Yachiyo", ""),
        ("打开 github.com 读一下内容", "live2d", "https://github.com", "GitHub page text for Yachiyo", ""),
        ("浏览器打开 GitHub 然后读一下", "bubble", "https://github.com", "GitHub page text for Yachiyo", ""),
        ("打开网页并读一下 github.com", "live2d", "https://github.com", "GitHub page text for Yachiyo", ""),
        (
            "打开 GitHub 并概括内容",
            "bubble",
            "https://github.com",
            "网页内容摘要：\n- GitHub page text for Yachiyo",
            "summary",
        ),
        (
            "open github.com and summarize",
            "live2d",
            "https://github.com",
            "网页内容摘要：\n- GitHub page text for Yachiyo",
            "summary",
        ),
        (
            "summarize github.com after opening it",
            "bubble",
            "https://github.com",
            "网页内容摘要：\n- GitHub page text for Yachiyo",
            "summary",
        ),
        (
            "搜索 oha yachiyo 并读一下结果",
            "bubble",
            "https://www.google.com/search?q=oha+yachiyo",
            "GitHub page text for Yachiyo",
            "",
        ),
        (
            "search oha yachiyo and summarize results",
            "live2d",
            "https://www.google.com/search?q=oha+yachiyo",
            "网页内容摘要：\n- GitHub page text for Yachiyo",
            "summary",
        ),
    ]
    for prompt, launcher_mode, expected_url, expected_summary, expected_presentation in cases:
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == expected_summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url_and_extract_text"
        assert agent_task["tool_calls"][-1]["input_preview"]["url"] == expected_url
        completed_event = next(
            event
            for event in result["_task_timeline"]["events"]
            if event["event_type"] == "agent.desktop.intent_completed"
        )
        if expected_presentation:
            assert completed_event["payload"]["presentation"] == expected_presentation
        else:
            assert "presentation" not in completed_event["payload"]
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://github.com"),
        ("extract", ""),
        ("open", "https://www.google.com/search?q=oha+yachiyo"),
        ("extract", ""),
        ("open", "https://www.google.com/search?q=oha+yachiyo"),
        ("extract", ""),
    ]


def test_chat_bridge_quick_message_executes_browser_open_url_and_screenshot(
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

    def fake_screenshot(target_path) -> dict:
        calls.append(("screenshot", str(target_path)))
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

    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    monkeypatch.setattr("apps.shell.agent.tools.browser.screenshot", fake_screenshot)
    cases = (
        ("打开 Chrome 访问 github.com 并截图", "bubble", "https://github.com"),
        ("打开网页并截图 github.com", "live2d", "https://github.com"),
        (
            "用浏览器搜索 oha yachiyo 并截图",
            "bubble",
            "https://www.google.com/search?q=oha+yachiyo",
        ),
        (
            "google oha yachiyo and screenshot results",
            "live2d",
            "https://www.google.com/search?q=oha+yachiyo",
        ),
    )
    for text, launcher_mode, expected_url in cases:
        calls.clear()
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert calls[0] == ("open", expected_url)
        assert calls[1][0] == "screenshot"
        assert calls[1][1].endswith("browser/current-page.png")
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已打开网页并截取当前网页。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url_and_screenshot"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "url": expected_url,
            "reason": "user asked to capture the browser page after opening a URL",
        }
        assert agent_task["artifacts"][-1]["path"] == "browser/current-page.png"
        completed_event = next(
            event
            for event in result["_task_timeline"]["events"]
            if event["event_type"] == "agent.desktop.intent_completed"
        )
        assert completed_event["detail"] == "browser.open_url_and_screenshot"
        assert run["status"] == "completed"
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_system_volume_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    volume_calls: list[tuple[str, object, object]] = []

    def fake_system_volume(action: str, *, level=None, step=None) -> dict:
        volume_calls.append((action, level, step))
        if action == "down":
            old_level = 50
            new_level = 40
            summary = "System volume decreased from 50% to 40%"
        elif action == "status":
            old_level = 50
            new_level = 50
            summary = "System volume is 50%"
        else:
            old_level = 40
            new_level = 50
            summary = "System volume increased from 40% to 50%"
        return {
            "ok": True,
            "action": "system.volume",
            "summary": summary,
            "data": {
                "requested_action": action,
                "old_level": old_level,
                "old_muted": False,
                "level": new_level,
                "muted": False,
                "changed": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.system_volume", fake_system_volume)
    cases = (
        ("调大音量", "bubble", "up", "已把系统音量从 40% 调高到 50%。"),
        ("turn it up", "live2d", "up", "已把系统音量从 40% 调高到 50%。"),
        ("大点声", "bubble", "up", "已把系统音量从 40% 调高到 50%。"),
        ("sound up", "live2d", "up", "已把系统音量从 40% 调高到 50%。"),
        ("make it quieter", "bubble", "down", "已把系统音量从 50% 调低到 40%。"),
        ("sound down", "live2d", "down", "已把系统音量从 50% 调低到 40%。"),
        ("查看当前音量", "bubble", "status", "当前系统音量是 50%。"),
        ("show current volume", "live2d", "status", "当前系统音量是 50%。"),
    )
    for prompt, launcher_mode, action, summary in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "system.volume"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"action": action}
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert volume_calls == [
        ("up", None, None),
        ("up", None, None),
        ("up", None, None),
        ("up", None, None),
        ("down", None, None),
        ("down", None, None),
        ("status", None, None),
        ("status", None, None),
    ]


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
        "复制以下内容：hello world",
    )

    assert clipboard_calls == ["hello world"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已复制 11 个字符到剪贴板。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "clipboard.write"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    cases = (
        ("设置剪贴板为 hello", "bubble"),
        ("set clipboard to hello", "live2d"),
    )
    for text, launcher_mode in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert clipboard_calls[-1] == "hello"
        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "已复制 5 个字符到剪贴板。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "clipboard.write"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_clipboard_read_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    read_calls: list[int] = []

    def fake_clipboard_read(*, max_chars=2000) -> dict:
        read_calls.append(max_chars)
        return {
            "ok": True,
            "action": "clipboard.read",
            "summary": "Read 11 characters from clipboard",
            "data": {
                "text": "hello world",
                "text_length": 11,
                "truncated": False,
                "max_chars": max_chars,
                "platform": "macos",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.clipboard_read", fake_clipboard_read)
    cases = (
        ("剪贴板里是什么", "bubble"),
        ("读一下剪贴板", "live2d"),
        ("把剪贴板读给我", "bubble"),
        ("what is on my clipboard", "live2d"),
    )
    for text, launcher_mode in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "剪贴板内容：hello world"
        assert agent_task["tool_calls"][-1]["tool_name"] == "clipboard.read"
        assert agent_task["tool_calls"][-1]["input_preview"] == {}
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert read_calls == [2000, 2000, 2000, 2000]


def test_chat_bridge_quick_message_copies_and_reads_selected_text_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str | int]] = []

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: copy",
            "data": {"shortcut_action": action},
        }

    def fake_clipboard_read(*, max_chars=2000) -> dict:
        calls.append(("read", max_chars))
        return {
            "ok": True,
            "action": "clipboard.read",
            "summary": "Read 13 characters from clipboard",
            "data": {
                "text": "selected text",
                "text_length": 13,
                "truncated": False,
                "max_chars": max_chars,
                "platform": "macos",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.clipboard_read", fake_clipboard_read)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "读一下选中的内容",
    )

    assert calls == [("shortcut", "copy"), ("read", 2000)]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已复制选中内容。 剪贴板内容：selected text。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "desktop.safe_shortcut",
        "clipboard.read",
    ]
    assert run["status"] == "completed"
    assert event_types.count("agent.desktop.intent_planned") == 2
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "我选中了什么",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "已复制选中内容。 剪贴板内容：selected text。"
        assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
            "desktop.safe_shortcut",
            "clipboard.read",
        ]
        assert run["status"] == "completed"
        assert event_types.count("agent.desktop.intent_planned") == 2
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    for prompt, launcher_mode in (
        ("复制选中文字并读取剪贴板", "bubble"),
        ("copy selected text and read clipboard", "live2d"),
    ):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "已复制选中内容。 剪贴板内容：selected text。"
        assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
            "desktop.safe_shortcut",
            "clipboard.read",
        ]
        assert run["status"] == "completed"
        assert event_types.count("agent.desktop.intent_planned") == 2
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("shortcut", "copy"),
        ("read", 2000),
        ("shortcut", "copy"),
        ("read", 2000),
        ("shortcut", "copy"),
        ("read", 2000),
        ("shortcut", "copy"),
        ("read", 2000),
        ("shortcut", "copy"),
        ("read", 2000),
    ]


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
        "open Finder and open Downloads folder",
    )

    assert open_calls == ["~/Downloads"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开文件夹：~/Downloads。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    cases = (
        ("打开 Finder 看看下载文件夹", "bubble", "~/Downloads"),
        ("打开访达看看下载文件夹", "live2d", "~/Downloads"),
        ("打开图片文件夹", "bubble", "~/Pictures"),
        ("在 Finder 打开照片目录", "live2d", "~/Pictures"),
        ("打开公共文件夹", "bubble", "~/Public"),
        ("打开 Public 文件夹", "live2d", "~/Public"),
        ("打开影片文件夹", "live2d", "~/Movies"),
        ("打开音乐目录", "bubble", "~/Music"),
        ("打开 Music 文件夹", "live2d", "~/Music"),
        ("打开用户目录", "bubble", "~"),
        ("open user directory", "live2d", "~"),
        ("打开当前工作区", "bubble", "."),
        ("打开项目目录", "live2d", "."),
        ("打开垃圾桶", "bubble", "~/.Trash"),
        ("open trash folder", "live2d", "~/.Trash"),
    )
    for prompt, launcher_mode, expected_path in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert open_calls[-1] == expected_path
        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == f"已打开文件夹：{expected_path}。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"path": expected_path}
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_latest_download_open_path_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []

    def fake_open_path(path: str) -> dict:
        open_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.open_path",
            "summary": "Opened new.pdf",
            "data": {
                "path": path,
                "display_path": "~/Downloads/new.pdf",
                "desktop_object": "latest_download",
                "open_target": "system_open",
                "exists": True,
                "is_dir": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.open_path", fake_open_path)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开最近下载的文件",
    )

    assert open_calls == ["latest_download"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开文件：~/Downloads/new.pdf。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"path": "latest_download"}
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开下载目录里的最新文件",
        launcher_mode="live2d",
    )

    assert open_calls[-1] == "latest_download"
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开文件：~/Downloads/new.pdf。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"path": "latest_download"}
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_latest_screenshot_open_path_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []

    def fake_open_path(path: str) -> dict:
        open_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.open_path",
            "summary": "Opened Screenshot.png",
            "data": {
                "path": path,
                "display_path": "~/Desktop/Screenshot.png",
                "desktop_object": "latest_screenshot",
                "source_folder": "~/Desktop",
                "open_target": "system_open",
                "exists": True,
                "is_dir": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.open_path", fake_open_path)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开刚才的截图",
    )

    assert open_calls == ["latest_screenshot"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开文件：~/Desktop/Screenshot.png。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"path": "latest_screenshot"}
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_finder_selection_open_path_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []

    def fake_open_path(path: str) -> dict:
        open_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.open_path",
            "summary": "Opened selected.pdf",
            "data": {
                "path": path,
                "display_path": "~/Desktop/selected.pdf",
                "desktop_object": "finder_selection",
                "source_app": "Finder",
                "open_target": "system_open",
                "exists": True,
                "is_dir": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.open_path", fake_open_path)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开选中的文件",
    )

    assert open_calls == ["finder_selection"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开文件：~/Desktop/selected.pdf。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"path": "finder_selection"}
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开当前选中的 Finder 文件",
        launcher_mode="bubble",
    )

    assert open_calls[-1] == "finder_selection"
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已打开文件：~/Desktop/selected.pdf。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"path": "finder_selection"}
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
        "open Finder and show Downloads folder",
    )

    assert reveal_calls == ["~/Downloads"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已在 Finder 中显示：~/Downloads。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.reveal_path"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    for prompt, launcher_mode in (
        ("显示当前选中的 Finder 文件", "bubble"),
        ("显示当前选中文件", "live2d"),
        ("在 Finder 中显示当前工作区", "bubble"),
        ("在 Finder 中显示项目目录", "live2d"),
    ):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        expected_path = "finder_selection" if "选中" in prompt else "."
        assert reveal_calls[-1] == expected_path
        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == f"已在 Finder 中显示：{expected_path}。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.reveal_path"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"path": expected_path}
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
        "look at my screen",
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

    for launcher_mode, prompt in (
        ("bubble", "帮我截个屏"),
        ("bubble", "看一下我现在的界面"),
        ("live2d", "show me the screen"),
    ):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "已截取当前屏幕。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "screen.capture"
        assert agent_task["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert run["status"] == "completed"
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert len(capture_targets) == 4


def test_chat_bridge_quick_message_executes_app_then_screen_capture_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_screen_capture(target_path) -> dict:
        calls.append(("capture", str(target_path)))
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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.screen_capture", fake_screen_capture)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开微信然后截图",
    )

    assert calls[0] == ("open", "WeChat")
    assert calls[1][0] == "capture"
    assert calls[1][1].endswith("screenshots/current-screen.png")
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 WeChat。 已截取当前屏幕。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "app.open",
        "screen.capture",
    ]
    assert agent_task["artifacts"][-1]["path"] == "screenshots/current-screen.png"
    assert run["status"] == "completed"
    assert event_types.count("agent.desktop.intent_planned") == 2
    assert "artifact.created" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    cases = (
        ("打开微信看看有没有新消息", "bubble", "WeChat"),
        ("把微信打开然后看看有没有未读", "live2d", "WeChat"),
        ("打开微信读一下当前聊天", "bubble", "WeChat"),
        ("打开 Slack 看消息", "bubble", "Slack"),
        ("open Discord and read messages", "live2d", "Discord"),
        ("打开活动监视器看看 CPU", "live2d", "Activity Monitor"),
        ("打开系统活动监视器看看 CPU", "bubble", "Activity Monitor"),
    )
    for prompt, launcher_mode, app_name in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert calls[-2] == ("open", app_name)
        assert calls[-1][0] == "capture"
        assert calls[-1][1].endswith("screenshots/current-screen.png")
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == f"已打开 {app_name}。 已截取当前屏幕。"
        assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
            "app.open",
            "screen.capture",
        ]
        assert agent_task["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert run["status"] == "completed"
        assert event_types.count("agent.desktop.intent_planned") == 2
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_app_prefix_screen_capture_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_screen_capture(target_path) -> dict:
        calls.append(("capture", str(target_path)))
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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.screen_capture", fake_screen_capture)
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 看看界面",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切换到 Google Chrome。 已截取当前屏幕。"
        assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
            "app.focus",
            "screen.capture",
        ]
        assert agent_task["tool_calls"][-2]["input_preview"] == {
            "app_name": "Google Chrome",
        }
        assert agent_task["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert run["status"] == "completed"
        assert event_types.count("agent.desktop.intent_planned") == 2
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 观察一下",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切换到 Google Chrome。 已截取当前屏幕。"
        assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
            "app.focus",
            "screen.capture",
        ]
        assert agent_task["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert run["status"] == "completed"
        assert event_types.count("agent.desktop.intent_planned") == 2
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "看一下 Chrome 当前界面",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切换到 Google Chrome。 已截取当前屏幕。"
        assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
            "app.focus",
            "screen.capture",
        ]
        assert agent_task["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert run["status"] == "completed"
        assert event_types.count("agent.desktop.intent_planned") == 2
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert len(calls) == 12
    for index in range(0, len(calls), 2):
        assert calls[index] == ("focus", "Google Chrome")
        assert calls[index + 1][0] == "capture"
        assert calls[index + 1][1].endswith("screenshots/current-screen.png")


def test_chat_bridge_quick_message_executes_app_safe_shortcut_sequence_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut",
            "data": {"shortcut_action": action},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开微信然后全选复制",
    )

    assert calls == [
        ("open", "WeChat"),
        ("focus", "WeChat"),
        ("shortcut", "select_all"),
        ("shortcut", "copy"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 WeChat 并全选。 已复制选中内容。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "app.open_and_safe_shortcut",
        "desktop.safe_shortcut",
    ]
    assert run["status"] == "completed"
    assert event_types.count("agent.desktop.intent_planned") == 2
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    calls.clear()
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Finder 并按 Command N",
    )

    assert calls == [
        ("open", "Finder"),
        ("focus", "Finder"),
        ("shortcut", "new_window"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Finder 并新建窗口。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open_and_safe_shortcut"
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "app_name": "Finder",
        "action": "new_window",
    }
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types

    calls.clear()
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "把Chrome打开然后新建标签页",
    )

    assert calls == [
        ("open", "Google Chrome"),
        ("focus", "Google Chrome"),
        ("shortcut", "new_tab"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Google Chrome 并新建标签页。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open_and_safe_shortcut"
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "app_name": "Google Chrome",
        "action": "new_tab",
    }
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


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
        "读当前网页",
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


def test_chat_bridge_quick_message_opens_browser_then_extracts_current_page_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_extract_text(selector: str = "") -> dict:
        calls.append(("extract", selector))
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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.browser.extract_text", fake_extract_text)
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Chrome 读取当前页",
    )

    assert calls == [("open", "Google Chrome"), ("extract", "")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Google Chrome。 Yachiyo desktop agent runtime。"
    assert [tool_call["tool_name"] for tool_call in agent_task["tool_calls"][-2:]] == [
        "app.open",
        "browser.extract_text",
    ]
    assert run["status"] == "completed"
    assert run["pending_approval"] == {}
    assert event_types.count("agent.desktop.intent_planned") == 2
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
    for prompt, launcher_mode in (
        ("screenshot this page", "bubble"),
        ("screenshot current webpage", "live2d"),
    ):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert screenshot_targets[-1].endswith("browser/current-page.png")
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

    assert len(screenshot_targets) == 2
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
        "需要什么权限",
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
    cases = (
        ("复制一下选中的内容", "live2d", "copy", "已复制选中内容。"),
        ("复制选中文字", "bubble", "copy", "已复制选中内容。"),
        ("copy current selection", "live2d", "copy", "已复制选中内容。"),
        ("你可以帮我复制一下吗", "bubble", "copy", "已复制选中内容。"),
        ("你能帮我粘贴吗", "live2d", "paste", "已粘贴。"),
        ("你能帮我全选吗", "bubble", "select_all", "已全选。"),
        ("你可以帮我撤销吗", "live2d", "undo", "已撤销。"),
        ("切到下一个窗口", "bubble", "next_window", "已切到下一个窗口。"),
        ("切到上一个窗口", "live2d", "previous_window", "已切到上一个窗口。"),
        ("打开任务控制中心", "bubble", "mission_control", "已打开任务控制中心。"),
        ("显示当前应用窗口", "bubble", "application_windows", "已显示当前应用窗口。"),
        ("打开聚焦搜索", "bubble", "spotlight_search", "已打开 Spotlight。"),
        ("打开 emoji 面板", "live2d", "emoji_picker", "已打开 Emoji 面板。"),
        ("锁屏", "bubble", "lock_screen", "已锁屏。"),
        ("打开强制退出窗口", "live2d", "force_quit_dialog", "已打开强制退出窗口。"),
        ("Can you copy?", "bubble", "copy", "已复制选中内容。"),
        ("Could you paste?", "live2d", "paste", "已粘贴。"),
        ("Would you select all please?", "bubble", "select_all", "已全选。"),
        ("switch to next window", "bubble", "next_window", "已切到下一个窗口。"),
        ("switch to previous window", "live2d", "previous_window", "已切到上一个窗口。"),
        ("show mission control", "live2d", "mission_control", "已打开任务控制中心。"),
        ("show app windows", "live2d", "application_windows", "已显示当前应用窗口。"),
        ("spotlight search", "bubble", "spotlight_search", "已打开 Spotlight。"),
        ("show emoji picker", "live2d", "emoji_picker", "已打开 Emoji 面板。"),
        ("lock screen", "bubble", "lock_screen", "已锁屏。"),
        ("show force quit applications", "bubble", "force_quit_dialog", "已打开强制退出窗口。"),
        ("浏览器刷新", "live2d", "refresh", "已刷新。"),
        ("refresh page", "bubble", "refresh", "已刷新。"),
        ("refresh the current page", "bubble", "refresh", "已刷新。"),
        ("刷新当前页面", "live2d", "refresh", "已刷新。"),
        ("reload page", "live2d", "refresh", "已刷新。"),
        ("open new tab", "bubble", "new_tab", "已新建标签页。"),
        ("open a new tab", "live2d", "new_tab", "已新建标签页。"),
        ("新开一个标签页", "bubble", "new_tab", "已新建标签页。"),
        ("go back one page", "live2d", "browser_back", "已返回上一页。"),
        ("forward page", "bubble", "browser_forward", "已前进一页。"),
        ("把剪贴板内容粘贴到当前输入框", "bubble", "paste", "已粘贴。"),
        ("关闭当前标签页", "bubble", "close_tab", "已关闭标签页。"),
        ("切到下一个标签页", "live2d", "next_tab", "已切到下一个标签页。"),
        ("切到上一个标签页", "bubble", "previous_tab", "已切到上一个标签页。"),
        (
            "重新打开关闭的标签页",
            "live2d",
            "reopen_closed_tab",
            "已重新打开关闭的标签页。",
        ),
        (
            "重新打开刚关闭的标签页",
            "bubble",
            "reopen_closed_tab",
            "已重新打开关闭的标签页。",
        ),
    )
    for text, launcher_mode, action, summary in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert shortcut_calls[-1] == action
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_shortcut"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"action": action}
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_app_scoped_safe_shortcut_without_approval(
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
            "summary": "Executed safe shortcut: new tab",
            "data": {"shortcut_action": action, "key": "t", "modifiers": ["command"]},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    cases = (
        ("Chrome 新建标签页", "new_tab", "已切到 Google Chrome 并新建标签页。"),
        ("Chrome 关闭当前标签页", "close_tab", "已切到 Google Chrome 并关闭标签页。"),
        ("Chrome 切到下一个标签页", "next_tab", "已切到 Google Chrome 并切到下一个标签页。"),
        ("Chrome 切到上一个标签页", "previous_tab", "已切到 Google Chrome 并切到上一个标签页。"),
    )
    for text, action, summary in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
        )

        assert calls[-2:] == [("focus", "Google Chrome"), ("shortcut", action)]
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_shortcut"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Google Chrome",
            "action": action,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_app_scoped_browser_back_without_fake_app_name(
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
            "summary": "Executed safe shortcut: browser back",
            "data": {
                "shortcut_action": action,
                "shortcut_label": "browser back",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "切到 Chrome 后退一下",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切到 Google Chrome 并返回上一页。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_shortcut"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Google Chrome",
            "action": "browser_back",
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("focus", "Google Chrome"),
        ("shortcut", "browser_back"),
        ("focus", "Google Chrome"),
        ("shortcut", "browser_back"),
    ]


def test_chat_bridge_quick_message_executes_app_prefix_find_shortcut_without_model(
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
            "data": {
                "shortcut_action": action,
                "shortcut_label": "find",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 查找一下",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切到 Google Chrome 并打开查找。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_shortcut"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Google Chrome",
            "action": "find",
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("focus", "Google Chrome"),
        ("shortcut", "find"),
        ("focus", "Google Chrome"),
        ("shortcut", "find"),
    ]


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
        "输入 你好八千代 到前台",
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

    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "在当前输入框输入 hello",
        launcher_mode="bubble",
    )

    assert typed_text[-1] == "hello"
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已向前台输入文字（5 个字符）。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_type_text"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


def test_chat_bridge_quick_message_executes_search_submit_without_approval(
    tmp_path,
    monkeypatch,
):
    submit_calls: list[str] = []

    def fake_search_submit() -> dict:
        submit_calls.append("search_submit")
        return {
            "ok": True,
            "action": "desktop.search_submit",
            "summary": "Submitted foreground search query",
            "data": {"key": "return", "modifiers": []},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_search_submit", fake_search_submit)
    cases = (
        ("提交当前搜索", "bubble"),
        ("press enter to search", "live2d"),
    )
    for prompt, launcher_mode in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已提交前台搜索。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.search_submit"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert submit_calls == ["search_submit", "search_submit"]


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
        "打开 Notes 输入 hello yachiyo",
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

    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开微信发你好",
    )

    assert calls[-3:] == [("open", "WeChat"), ("focus", "WeChat"), ("type", "你好")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 WeChat 并输入文字（2 个字符）。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open_and_safe_type_text"
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "app_name": "WeChat",
        "text": "你好",
    }
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
        "打开 Finder，然后搜索下载",
    )

    assert calls == [
        ("open", "Finder"),
        ("focus", "Finder"),
        ("shortcut", "find"),
        ("type", "下载"),
    ]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已打开 Finder 并打开查找。 已向前台输入文字（2 个字符）。"
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


def test_chat_bridge_quick_message_executes_safe_arrow_key_without_approval(
    tmp_path,
    monkeypatch,
):
    pressed: list[tuple[str, int]] = []

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict:
        pressed.append((action, repeat_count))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": "Pressed Down Arrow",
            "data": {
                "key_action": action,
                "key_label": "Down Arrow",
                "repeat_count": repeat_count,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    cases = (
        ("按向下箭头三次", "bubble", "arrow_down", 3, "已按下箭头（3 次）。"),
        ("按向下箭头三次", "live2d", "arrow_down", 3, "已按下箭头（3 次）。"),
        ("你能帮我按一下Escape吗", "bubble", "escape", 1, "已按Escape。"),
        ("你可以帮我按Tab吗", "live2d", "tab", 1, "已按Tab。"),
        ("显示桌面", "bubble", "show_desktop", 1, "已显示桌面。"),
        ("Could you press Escape?", "bubble", "escape", 1, "已按Escape。"),
        ("Can you hit Tab?", "live2d", "tab", 1, "已按Tab。"),
        ("show desktop", "live2d", "show_desktop", 1, "已显示桌面。"),
    )
    for text, launcher_mode, action, repeat_count, summary in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            text,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == summary
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_key"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "action": action,
            "repeat_count": repeat_count,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert pressed == [
        ("arrow_down", 3),
        ("arrow_down", 3),
        ("escape", 1),
        ("tab", 1),
        ("show_desktop", 1),
        ("escape", 1),
        ("tab", 1),
        ("show_desktop", 1),
    ]


def test_chat_bridge_quick_message_executes_next_input_focus_as_safe_tab_key(
    tmp_path,
    monkeypatch,
):
    pressed: list[tuple[str, int]] = []
    typed_texts: list[str] = []

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict:
        pressed.append((action, repeat_count))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": "Pressed Tab",
            "data": {
                "key_action": action,
                "key_label": "Tab",
                "repeat_count": repeat_count,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_type_text",
        lambda text: typed_texts.append(text) or {"ok": True, "action": "desktop.safe_type_text"},
    )
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "切到下一个输入框",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已按Tab。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_key"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "action": "tab",
            "repeat_count": 1,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert pressed == [("tab", 1), ("tab", 1)]
    assert typed_texts == []


def test_chat_bridge_quick_message_executes_app_prefix_safe_tab_key_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str] | tuple[str, str, int]] = []

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict:
        calls.append(("key", action, repeat_count))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": "Pressed Tab",
            "data": {
                "key_action": action,
                "key_label": "Tab",
                "repeat_count": repeat_count,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 按 Tab",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切到 Google Chrome 并按Tab。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_key"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Google Chrome",
            "action": "tab",
            "repeat_count": 1,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("focus", "Google Chrome"),
        ("key", "tab", 1),
        ("focus", "Google Chrome"),
        ("key", "tab", 1),
    ]


def test_chat_bridge_quick_message_executes_previous_input_focus_as_safe_shift_tab_key(
    tmp_path,
    monkeypatch,
):
    pressed: list[tuple[str, int]] = []
    typed_texts: list[str] = []

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict:
        pressed.append((action, repeat_count))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": "Pressed Shift+Tab",
            "data": {
                "key_action": action,
                "key_label": "Shift+Tab",
                "repeat_count": repeat_count,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_type_text",
        lambda text: typed_texts.append(text) or {"ok": True, "action": "desktop.safe_type_text"},
    )
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "切到上一个输入框",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已按Shift+Tab。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_key"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "action": "shift_tab",
            "repeat_count": 1,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert pressed == [("shift_tab", 1), ("shift_tab", 1)]
    assert typed_texts == []


def test_chat_bridge_quick_message_executes_safe_scroll_page_without_approval(
    tmp_path,
    monkeypatch,
):
    scrolled: list[tuple[str, int]] = []

    def fake_safe_scroll(direction: str, *, pages: int = 1) -> dict:
        scrolled.append((direction, pages))
        return {
            "ok": True,
            "action": "desktop.safe_scroll",
            "summary": "Scrolled foreground desktop down 1 page",
            "data": {
                "direction": direction,
                "pages": pages,
                "explicit_user_scroll": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_scroll", fake_safe_scroll)
    cases = (
        ("翻到下一页", "bubble"),
        ("翻到下一页", "live2d"),
        ("滚动一下", "bubble"),
        ("scroll a little", "live2d"),
    )
    for prompt, launcher_mode in cases:
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            prompt,
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已向下滚动前台界面（1 页）。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_scroll"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "direction": "down",
            "pages": 1,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert scrolled == [("down", 1), ("down", 1), ("down", 1), ("down", 1)]


def test_chat_bridge_quick_message_executes_app_prefix_safe_scroll_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str] | tuple[str, str, int]] = []

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_safe_scroll(direction: str, *, pages: int = 1) -> dict:
        calls.append(("scroll", direction, pages))
        return {
            "ok": True,
            "action": "desktop.safe_scroll",
            "summary": "Scrolled foreground desktop down 1 page",
            "data": {
                "direction": direction,
                "pages": pages,
                "explicit_user_scroll": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_scroll", fake_safe_scroll)
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 向下滚动一下",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切到 Google Chrome 并向下滚动前台界面（1 页）。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_scroll"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Google Chrome",
            "direction": "down",
            "pages": 1,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("focus", "Google Chrome"),
        ("scroll", "down", 1),
        ("focus", "Google Chrome"),
        ("scroll", "down", 1),
    ]


def test_chat_bridge_quick_message_executes_app_prefix_safe_click_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str] | tuple[str, int, int]] = []

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_safe_click(x: int, y: int) -> dict:
        calls.append(("click", x, y))
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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_click", fake_safe_click)
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 点击 120, 240",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切到 Google Chrome 并点击前台位置：120, 240。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_click"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Google Chrome",
            "x": 120,
            "y": 240,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("focus", "Google Chrome"),
        ("click", 120, 240),
        ("focus", "Google Chrome"),
        ("click", 120, 240),
    ]


def test_chat_bridge_quick_message_executes_app_prefix_safe_type_text_without_model(
    tmp_path,
    monkeypatch,
):
    calls: list[tuple[str, str]] = []

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
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
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "Chrome 输入 hello",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已切到 Google Chrome 并输入文字（5 个字符）。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_type_text"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "app_name": "Google Chrome",
            "text": "hello",
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert calls == [
        ("focus", "Google Chrome"),
        ("type", "hello"),
        ("focus", "Google Chrome"),
        ("type", "hello"),
    ]


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
    assert agent_task["needs_user_action"] is True
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
            "tool": "system.settings_open",
            "input": {"target": "辅助功能权限"},
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
    assert agent_task["needs_user_action"] is True
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


def test_chat_bridge_quick_message_surfaces_app_open_recovery(
    tmp_path,
    monkeypatch,
):
    def fake_app_open(app_name: str) -> dict:
        return {
            "ok": False,
            "action": "app.open",
            "summary": "app.open failed",
            "error": "Application not found.",
            "error_code": "app_not_found",
            "data": {"app_name": app_name},
            "permission_error": False,
            "fallback_used": False,
            "recovery_hints": ["确认应用已安装，或换用精确应用名。"],
            "recovery_actions": [
                {
                    "label": "打开应用程序文件夹",
                    "tool": "desktop.open_path",
                    "input": {"path": "/Applications"},
                    "permission_target": "app_not_found",
                    "risk_level": "low",
                },
                {
                    "label": "打开 App Store",
                    "tool": "app.open",
                    "input": {"app_name": "App Store"},
                    "permission_target": "app_not_found",
                    "risk_level": "low",
                },
            ],
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 MissingTool",
    )
    timeline = result["_task_timeline"]
    recovery_event = next(
        event
        for event in timeline["events"]
        if event["event_type"] == "agent.desktop.permission_recovery"
    )

    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is True
    assert "已尝试启动 MissingTool，但 macOS 没找到这个应用。" in agent_task["summary"]
    assert "可直接打开：打开应用程序文件夹、打开 App Store。" in agent_task["summary"]
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
    assert agent_task["tool_calls"][-1]["status"] == "failed"
    assert agent_task["tool_calls"][-1]["output_preview"]["error_code"] == "app_not_found"
    assert agent_task["tool_calls"][-1]["output_preview"]["recovery_actions"][0] == {
        "label": "打开应用程序文件夹",
        "tool": "desktop.open_path",
        "input": {"path": "/Applications"},
        "permission_target": "app_not_found",
        "risk_level": "low",
    }
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.permission_recovery" in event_types
    assert "model.request.started" not in event_types
    assert recovery_event["payload"]["permission_targets"] == []
    assert recovery_event["payload"]["affected_tools"] == ["app.open"]
    assert recovery_event["payload"]["recovery_actions"] == agent_task["tool_calls"][-1]["output_preview"]["recovery_actions"]


def test_chat_bridge_quick_message_surfaces_app_foreground_action_recovery(
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

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict:
        calls.append(("key", action))
        return {
            "ok": False,
            "action": "desktop.safe_key",
            "summary": "desktop.safe_key failed",
            "error": "Not authorized to send events to System Events.",
            "permission_error": True,
            "permission_targets": ["accessibility"],
            "recovery_actions": [
                {
                    "label": "打开辅助功能权限",
                    "tool": "app.open",
                    "input": {"app_name": "辅助功能权限"},
                    "permission_target": "accessibility",
                    "risk_level": "low",
                }
            ],
            "data": {
                "key_action": action,
                "key_label": "Tab",
                "repeat_count": repeat_count,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 Chrome，然后按 Tab",
    )
    timeline = result["_task_timeline"]
    recovery_event = next(
        event
        for event in timeline["events"]
        if event["event_type"] == "agent.desktop.permission_recovery"
    )
    tool_call = agent_task["tool_calls"][-1]

    assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("key", "tab")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is True
    assert agent_task["summary"].startswith(
        "已打开 Google Chrome，但没能按Tab。 缺少权限：accessibility。"
    )
    assert "可直接打开：打开辅助功能权限。" in agent_task["summary"]
    assert tool_call["tool_name"] == "app.open_and_safe_key"
    assert tool_call["status"] == "failed"
    assert tool_call["output_preview"]["permission_targets"] == ["accessibility"]
    assert tool_call["output_preview"]["recovery_actions"] == [
        {
            "label": "打开辅助功能权限",
            "tool": "app.open",
            "input": {"app_name": "辅助功能权限"},
            "permission_target": "accessibility",
            "recovery_retry_input": {
                "app_name": "Google Chrome",
                "action": "tab",
                "repeat_count": 1,
            },
            "recovery_retry_prompt": "打开Google Chrome并按Tab",
            "recovery_retry_tool": "app.open_and_safe_key",
            "retry_input": {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
            "retry_prompt": "打开Google Chrome并按Tab",
            "retry_tool": "app.open_and_safe_key",
            "risk_level": "low",
        }
    ]
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "agent.desktop.permission_recovery" in event_types
    assert "model.request.started" not in event_types
    assert recovery_event["payload"]["permission_targets"] == ["accessibility"]
    assert recovery_event["payload"]["affected_tools"] == ["app.open_and_safe_key"]
    assert recovery_event["payload"]["recovery_actions"] == tool_call["output_preview"]["recovery_actions"]


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


def test_chat_bridge_quick_message_executes_open_path_recovery_action_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-open-path-recovery-action.db",
        workspace_dir=tmp_path / "runtime-open-path-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    open_path_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher open-path recovery action should not call model")
        ),
    )

    def fake_open_path(path: str) -> dict:
        open_path_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.open_path",
            "summary": f"Opened {path}",
            "data": {
                "path": path,
                "display_path": path,
                "open_target": "system_open",
                "exists": True,
                "is_dir": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.open_path", fake_open_path)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开路径",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
                "daily_desktop_intent": True,
                "desktop_permission_recovery": True,
                "recovery_tool": "desktop.open_path",
                "recovery_input": {"path": "~/Downloads"},
                "recovery_permission_target": "file_access",
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
        assert open_path_calls == ["~/Downloads"]
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已打开文件夹：~/Downloads。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.open_path"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"path": "~/Downloads"}
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert user_metadata["desktop_permission_recovery"] is True
        assert user_metadata["recovery_tool"] == "desktop.open_path"
        assert user_metadata["recovery_input"] == {"path": "~/Downloads"}
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_browser_open_recovery_action_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-browser-open-recovery-action.db",
        workspace_dir=tmp_path / "runtime-browser-open-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    opened_urls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher browser recovery action should not call model")
        ),
    )

    def fake_open_url(url: str) -> dict:
        opened_urls.append(url)
        return {
            "ok": True,
            "action": "browser.open_url",
            "summary": f"Opened {url}",
            "data": {
                "url": url,
                "browser": "Google Chrome",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开链接",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
                "daily_desktop_intent": True,
                "desktop_permission_recovery": True,
                "recovery_tool": "browser.open_url",
                "recovery_input": {"url": "https://github.com"},
                "recovery_permission_target": "browser",
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
        assert opened_urls == ["https://github.com"]
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已打开网页：https://github.com。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "browser.open_url"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"url": "https://github.com"}
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert user_metadata["desktop_permission_recovery"] is True
        assert user_metadata["recovery_tool"] == "browser.open_url"
        assert user_metadata["recovery_input"] == {"url": "https://github.com"}
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_control_recovery_actions_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-control-recovery-action.db",
        workspace_dir=tmp_path / "runtime-control-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    music_control_calls: list[str] = []
    music_play_calls: list[str] = []
    music_open_calls: list[str] = []
    music_app_calls: list[str] = []
    volume_calls: list[tuple[str, object, object]] = []
    brightness_calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher control recovery action should not call model")
        ),
    )

    def fake_apple_music_control(action: str) -> dict:
        music_control_calls.append(action)
        return {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": f"Apple Music {action} executed",
            "data": {"control": action, "player_state": "paused"},
        }

    def fake_apple_music_play(query: str) -> dict:
        music_play_calls.append(query)
        return {
            "ok": True,
            "action": "media.apple_music_play",
            "summary": f"Apple Music playing {query}",
            "data": {"query": query, "track": query, "artist": "Yachiyo"},
        }

    def fake_apple_music_open_and_play() -> dict:
        music_open_calls.append("open")
        return {
            "ok": True,
            "action": "media.apple_music_open_and_play",
            "summary": "Opened Music and started playback",
            "data": {
                "app_name": "Music",
                "playback_ok": True,
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
        }

    def fake_music_app_open_and_play(app_name: str) -> dict:
        music_app_calls.append(app_name)
        return {
            "ok": True,
            "action": "media.music_app_open_and_play",
            "summary": f"Opened {app_name} and attempted playback with media key",
            "data": {"app_name": app_name, "playback_state_unverified": True},
        }

    def fake_system_volume(action: str, *, level=None, step=None) -> dict:
        volume_calls.append((action, level, step))
        return {
            "ok": True,
            "action": "system.volume",
            "summary": "System volume set to 35%",
            "data": {
                "requested_action": action,
                "old_level": 20,
                "old_muted": False,
                "level": level,
                "muted": False,
                "changed": True,
            },
        }

    def fake_system_brightness(action: str, *, step=None) -> dict:
        brightness_calls.append((action, step))
        return {
            "ok": True,
            "action": "system.brightness",
            "summary": "Display brightness decreased",
            "data": {
                "requested_action": action,
                "step": step,
                "key_code": 144,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.apple_music_control", fake_apple_music_control)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.apple_music_play", fake_apple_music_play)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_open_and_play",
        fake_apple_music_open_and_play,
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.music_app_open_and_play",
        fake_music_app_open_and_play,
    )
    monkeypatch.setattr("apps.shell.agent.tools.desktop.system_volume", fake_system_volume)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.system_brightness", fake_system_brightness)
    bridge = ChatBridge(runtime)
    try:
        cases = (
            (
                "暂停音乐",
                "media.apple_music_control",
                {"action": "pause"},
                "已暂停 Apple Music。",
            ),
            (
                "播放歌曲",
                "media.apple_music_play",
                {"query": "超时空辉夜姬"},
                "已在 Apple Music 播放：超时空辉夜姬 - Yachiyo。",
            ),
            (
                "打开 Apple Music 并播放",
                "media.apple_music_open_and_play",
                {},
                "已打开 Apple Music 并开始播放。当前：超时空辉夜姬 - Yachiyo。",
            ),
            (
                "打开 Spotify 并播放",
                "media.music_app_open_and_play",
                {"app_name": "Spotify"},
                "已打开 Spotify，并用媒体键尝试开始播放。",
            ),
            (
                "设置音量",
                "system.volume",
                {"action": "set", "level": 35},
                "已把系统音量调到 35%。",
            ),
            (
                "调低亮度",
                "system.brightness",
                {"action": "down"},
                "已调低屏幕亮度（2 格）。",
            ),
        )
        for prompt, tool_name, tool_input, expected_summary in cases:
            result = bridge.send_quick_message(
                prompt,
                metadata={
                    "source": "launcher",
                    "launcher_mode": "live2d",
                    "launcher_surface": "quick_message",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                    "desktop_permission_recovery": True,
                    "recovery_tool": tool_name,
                    "recovery_input": tool_input,
                    "recovery_permission_target": "desktop_control",
                    "recovery_risk_level": "low",
                },
            )
            agent_task = result["agent_task"]
            run = service.get_run(result["run_id"])
            event_types = [
                event["event_type"]
                for event in service.list_run_events(run["run_id"])["events"]
            ]

            assert result["ok"] is True
            assert agent_task["status"] == "completed"
            assert agent_task["needs_user_action"] is False
            assert agent_task["pending_approvals"] == []
            assert agent_task["summary"] == expected_summary
            assert agent_task["tool_calls"][-1]["tool_name"] == tool_name
            assert agent_task["tool_calls"][-1]["input_preview"] == tool_input
            assert run["status"] == "completed"
            assert run["pending_approval"] == {}
            assert "agent.desktop.intent_planned" in event_types
            assert "agent.tool.call" in event_types
            assert "agent.desktop.intent_completed" in event_types
            assert "agent.desktop.intent_approval_required" not in event_types
            assert "model.request.started" not in event_types
            assert "model.requested" not in event_types

        assert music_control_calls == ["pause"]
        assert music_play_calls == ["超时空辉夜姬"]
        assert music_open_calls == ["open"]
        assert music_app_calls == ["Spotify"]
        assert volume_calls == [("set", 35, None)]
        assert brightness_calls == [("down", None)]
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_diagnostic_recovery_actions_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-diagnostic-recovery-action.db",
        workspace_dir=tmp_path / "runtime-diagnostic-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    clipboard_writes: list[str] = []
    clipboard_reads: list[int] = []
    screen_targets: list[str] = []
    permission_calls: list[bool] = []
    active_window_calls = 0
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher diagnostic recovery action should not call model")
        ),
    )

    def fake_clipboard_write(text: str) -> dict:
        clipboard_writes.append(text)
        return {
            "ok": True,
            "action": "clipboard.write",
            "summary": "Copied 5 characters to clipboard",
            "data": {"text_length": len(text), "platform": "macos"},
        }

    def fake_clipboard_read(*, max_chars=2000) -> dict:
        clipboard_reads.append(max_chars)
        return {
            "ok": True,
            "action": "clipboard.read",
            "summary": "Read 11 characters from clipboard",
            "data": {
                "text": "hello world",
                "text_length": 11,
                "truncated": False,
                "max_chars": max_chars,
                "platform": "macos",
            },
        }

    def fake_screen_capture(target_path) -> dict:
        screen_targets.append(str(target_path))
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

    def fake_permissions() -> dict:
        permission_calls.append(True)
        return {
            "ok": True,
            "action": "desktop.permissions",
            "summary": "Desktop permissions ready",
            "data": {"permission_targets": [], "affected_tools": []},
        }

    def fake_active_window() -> dict:
        nonlocal active_window_calls
        active_window_calls += 1
        return {
            "ok": True,
            "action": "desktop.active_window",
            "summary": "Foreground window: Google Chrome - ChatGPT",
            "data": {"app_name": "Google Chrome", "title": "ChatGPT", "pid": 202},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.clipboard_write", fake_clipboard_write)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.clipboard_read", fake_clipboard_read)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.screen_capture", fake_screen_capture)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.permissions", fake_permissions)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.active_window", fake_active_window)
    bridge = ChatBridge(runtime)
    try:
        cases = (
            (
                "写入剪贴板",
                "clipboard.write",
                {"text": "hello"},
                "已复制 5 个字符到剪贴板。",
            ),
            (
                "读取剪贴板",
                "clipboard.read",
                {},
                "剪贴板内容：hello world",
            ),
            (
                "截图当前屏幕",
                "screen.capture",
                {"reason": "structured recovery"},
                "已截取当前屏幕。",
            ),
            (
                "检查桌面权限",
                "desktop.permissions",
                {},
                "桌面执行权限已就绪。",
            ),
            (
                "查看当前窗口",
                "desktop.active_window",
                {},
                "当前前台窗口是 Google Chrome：ChatGPT。",
            ),
        )
        for prompt, tool_name, tool_input, expected_summary in cases:
            result = bridge.send_quick_message(
                prompt,
                metadata={
                    "source": "launcher",
                    "launcher_mode": "live2d",
                    "launcher_surface": "quick_message",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                    "desktop_permission_recovery": True,
                    "recovery_tool": tool_name,
                    "recovery_input": tool_input,
                    "recovery_permission_target": "desktop_diagnostic",
                    "recovery_risk_level": "low",
                },
            )
            agent_task = result["agent_task"]
            run = service.get_run(result["run_id"])
            event_types = [
                event["event_type"]
                for event in service.list_run_events(run["run_id"])["events"]
            ]

            assert result["ok"] is True
            assert agent_task["status"] == "completed"
            assert agent_task["needs_user_action"] is False
            assert agent_task["pending_approvals"] == []
            assert agent_task["summary"] == expected_summary
            assert agent_task["tool_calls"][-1]["tool_name"] == tool_name
            assert agent_task["tool_calls"][-1]["input_preview"] == tool_input
            assert run["status"] == "completed"
            assert run["pending_approval"] == {}
            assert "agent.desktop.intent_planned" in event_types
            assert "agent.tool.call" in event_types
            assert "agent.desktop.intent_completed" in event_types
            assert "agent.desktop.intent_approval_required" not in event_types
            assert "model.request.started" not in event_types
            assert "model.requested" not in event_types

        assert clipboard_writes == ["hello"]
        assert clipboard_reads == [2000]
        assert screen_targets and screen_targets[0].endswith("screenshots/current-screen.png")
        assert permission_calls == [True]
        assert active_window_calls == 1
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_observation_recovery_actions_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-observation-recovery-action.db",
        workspace_dir=tmp_path / "runtime-observation-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    current_page_calls = 0
    opened_urls: list[str] = []
    extract_calls: list[str] = []
    screenshot_calls: list[str] = []
    running_calls = 0
    windows_calls: list[str] = []
    ui_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher observation recovery action should not call model")
        ),
    )

    def fake_current_page() -> dict:
        nonlocal current_page_calls
        current_page_calls += 1
        return {
            "ok": True,
            "action": "browser.current_page",
            "summary": "Current browser page: ChatGPT",
            "data": {"title": "ChatGPT", "url": "https://chatgpt.com/"},
        }

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

    def fake_open_url(url: str) -> dict:
        opened_urls.append(url)
        return {
            "ok": True,
            "action": "browser.open_url",
            "summary": f"Opened {url}",
            "data": {"url": url, "browser": "Google Chrome"},
        }

    def fake_screenshot(target_path) -> dict:
        screenshot_calls.append(str(target_path))
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

    def fake_windows(app_name: str = "") -> dict:
        windows_calls.append(app_name)
        return {
            "ok": True,
            "action": "desktop.windows",
            "summary": "Read open windows",
            "data": {
                "app_name": app_name,
                "windows": [
                    {"app_name": "Google Chrome", "title": "ChatGPT"},
                ],
            },
        }

    def fake_ui_elements(role_filter: str = "", limit: int = 80) -> dict:
        ui_calls.append((role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read current UI elements",
            "data": {
                "app_name": "Google Chrome",
                "title": "ChatGPT",
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "Send",
                        "enabled": True,
                        "center": {"x": 640, "y": 720},
                    },
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.current_page", fake_current_page)
    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    monkeypatch.setattr("apps.shell.agent.tools.browser.extract_text", fake_extract_text)
    monkeypatch.setattr("apps.shell.agent.tools.browser.screenshot", fake_screenshot)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.running_apps", fake_running_apps)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.windows", fake_windows)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    bridge = ChatBridge(runtime)
    try:
        cases = (
            (
                "查看当前网页",
                "browser.current_page",
                {},
                "当前网页是 ChatGPT：https://chatgpt.com/。",
            ),
            (
                "读取当前网页",
                "browser.extract_text",
                {},
                "Yachiyo desktop agent runtime",
            ),
            (
                "打开并读取 GitHub",
                "browser.open_url_and_extract_text",
                {"url": "https://github.com", "selector": ""},
                "Yachiyo desktop agent runtime",
            ),
            (
                "打开并截取 GitHub",
                "browser.open_url_and_screenshot",
                {"url": "https://github.com", "reason": "structured recovery"},
                "已打开网页并截取当前网页。",
            ),
            (
                "截取当前网页",
                "browser.screenshot",
                {"reason": "structured recovery"},
                "已截取当前网页。",
            ),
            (
                "查看正在运行的应用",
                "desktop.running_apps",
                {},
                "正在运行的应用：Finder, Google Chrome, Music。前台是 Google Chrome。",
            ),
            (
                "查看 Chrome 窗口",
                "desktop.windows",
                {"app_name": "Google Chrome"},
                "当前窗口：Google Chrome: ChatGPT。",
            ),
            (
                "查看界面按钮",
                "desktop.ui_elements",
                {"role_filter": "button", "limit": 80},
                "当前 Google Chrome 界面控件：Button Send（640, 720）。",
            ),
        )
        for prompt, tool_name, tool_input, expected_summary in cases:
            result = bridge.send_quick_message(
                prompt,
                metadata={
                    "source": "launcher",
                    "launcher_mode": "live2d",
                    "launcher_surface": "quick_message",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                    "desktop_permission_recovery": True,
                    "recovery_tool": tool_name,
                    "recovery_input": tool_input,
                    "recovery_permission_target": "desktop_observation",
                    "recovery_risk_level": "low",
                },
            )
            agent_task = result["agent_task"]
            run = service.get_run(result["run_id"])
            event_types = [
                event["event_type"]
                for event in service.list_run_events(run["run_id"])["events"]
            ]

            assert result["ok"] is True
            assert agent_task["status"] == "completed"
            assert agent_task["needs_user_action"] is False
            assert agent_task["pending_approvals"] == []
            assert agent_task["summary"] == expected_summary
            assert agent_task["tool_calls"][-1]["tool_name"] == tool_name
            assert agent_task["tool_calls"][-1]["input_preview"] == tool_input
            assert run["status"] == "completed"
            assert run["pending_approval"] == {}
            assert "agent.desktop.intent_planned" in event_types
            assert "agent.tool.call" in event_types
            assert "agent.desktop.intent_completed" in event_types
            assert "agent.desktop.intent_approval_required" not in event_types
            assert "model.request.started" not in event_types
            assert "model.requested" not in event_types

        assert current_page_calls == 1
        assert opened_urls == ["https://github.com", "https://github.com"]
        assert extract_calls == ["", ""]
        assert len(screenshot_calls) == 2
        assert all(call.endswith("browser/current-page.png") for call in screenshot_calls)
        assert running_calls == 1
        assert windows_calls == ["Google Chrome"]
        assert ui_calls == [("button", 80)]
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_safe_foreground_recovery_actions_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-safe-foreground-recovery-action.db",
        workspace_dir=tmp_path / "runtime-safe-foreground-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    calls: list[tuple] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher safe foreground recovery action should not call model")
        ),
    )

    def fake_safe_shortcut(action: str) -> dict:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": f"Executed safe shortcut: {action}",
            "data": {"shortcut_action": action},
        }

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict:
        calls.append(("key", action, repeat_count))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": f"Pressed {action}",
            "data": {"key_action": action, "repeat_count": repeat_count},
        }

    def fake_safe_scroll(direction: str, *, pages: int = 1) -> dict:
        calls.append(("scroll", direction, pages))
        return {
            "ok": True,
            "action": "desktop.safe_scroll",
            "summary": f"Scrolled foreground desktop {direction}",
            "data": {"direction": direction, "pages": pages},
        }

    def fake_safe_click(x: int, y: int) -> dict:
        calls.append(("click", x, y))
        return {
            "ok": True,
            "action": "desktop.safe_click",
            "summary": f"Clicked explicit foreground coordinate at ({x}, {y})",
            "data": {"x": x, "y": y, "click_count": 1},
        }

    def fake_safe_type_text(text: str) -> dict:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_scroll", fake_safe_scroll)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_click", fake_safe_click)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    bridge = ChatBridge(runtime)
    try:
        cases = (
            (
                "复制选中内容",
                "desktop.safe_shortcut",
                {"action": "copy"},
                "已复制选中内容。",
            ),
            (
                "按 Tab",
                "desktop.safe_key",
                {"action": "tab", "repeat_count": 1},
                "已按Tab。",
            ),
            (
                "向下滚动",
                "desktop.safe_scroll",
                {"direction": "down", "pages": 2},
                "已向下滚动前台界面（2 页）。",
            ),
            (
                "点击前台位置",
                "desktop.safe_click",
                {"x": 120, "y": 240},
                "已点击前台位置：120, 240。",
            ),
            (
                "输入文字",
                "desktop.safe_type_text",
                {"text": "hello"},
                "已向前台输入文字（5 个字符）。",
            ),
        )
        for prompt, tool_name, tool_input, expected_summary in cases:
            result = bridge.send_quick_message(
                prompt,
                metadata={
                    "source": "launcher",
                    "launcher_mode": "live2d",
                    "launcher_surface": "quick_message",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                    "desktop_permission_recovery": True,
                    "recovery_tool": tool_name,
                    "recovery_input": tool_input,
                    "recovery_permission_target": "foreground_input",
                    "recovery_risk_level": "low",
                },
            )
            agent_task = result["agent_task"]
            run = service.get_run(result["run_id"])
            event_types = [
                event["event_type"]
                for event in service.list_run_events(run["run_id"])["events"]
            ]

            assert result["ok"] is True
            assert agent_task["status"] == "completed"
            assert agent_task["needs_user_action"] is False
            assert agent_task["pending_approvals"] == []
            assert agent_task["summary"] == expected_summary
            assert agent_task["tool_calls"][-1]["tool_name"] == tool_name
            assert agent_task["tool_calls"][-1]["input_preview"] == tool_input
            assert run["status"] == "completed"
            assert run["pending_approval"] == {}
            assert "agent.desktop.intent_planned" in event_types
            assert "agent.tool.call" in event_types
            assert "agent.desktop.intent_completed" in event_types
            assert "agent.desktop.intent_approval_required" not in event_types
            assert "model.request.started" not in event_types
            assert "model.requested" not in event_types

        assert calls == [
            ("shortcut", "copy"),
            ("key", "tab", 1),
            ("scroll", "down", 2),
            ("click", 120, 240),
            ("type", "hello"),
        ]
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_app_foreground_recovery_actions_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-app-foreground-recovery-action.db",
        workspace_dir=tmp_path / "runtime-app-foreground-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    calls: list[tuple] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher app foreground recovery action should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

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
            "summary": f"Executed safe shortcut: {action}",
            "data": {"shortcut_action": action},
        }

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict:
        calls.append(("key", action, repeat_count))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": f"Pressed {action}",
            "data": {"key_action": action, "repeat_count": repeat_count},
        }

    def fake_safe_scroll(direction: str, *, pages: int = 1) -> dict:
        calls.append(("scroll", direction, pages))
        return {
            "ok": True,
            "action": "desktop.safe_scroll",
            "summary": f"Scrolled foreground desktop {direction}",
            "data": {"direction": direction, "pages": pages},
        }

    def fake_safe_click(x: int, y: int) -> dict:
        calls.append(("click", x, y))
        return {
            "ok": True,
            "action": "desktop.safe_click",
            "summary": f"Clicked explicit foreground coordinate at ({x}, {y})",
            "data": {"x": x, "y": y, "click_count": 1},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_scroll", fake_safe_scroll)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_click", fake_safe_click)
    bridge = ChatBridge(runtime)
    try:
        cases = (
            (
                "打开 Notes 并输入文字",
                "app.open_and_safe_type_text",
                {"app_name": "Notes", "text": "hello"},
                "已打开 Notes 并输入文字（5 个字符）。",
            ),
            (
                "切到 Chrome 并粘贴",
                "app.focus_and_safe_shortcut",
                {"app_name": "Google Chrome", "action": "paste"},
                "已切到 Google Chrome 并粘贴。",
            ),
            (
                "打开 Chrome 并按 Tab",
                "app.open_and_safe_key",
                {"app_name": "Google Chrome", "action": "tab", "repeat_count": 1},
                "已打开 Google Chrome 并按Tab。",
            ),
            (
                "切到 Chrome 并向下滚动",
                "app.focus_and_safe_scroll",
                {"app_name": "Google Chrome", "direction": "down", "pages": 2},
                "已切到 Google Chrome 并向下滚动前台界面（2 页）。",
            ),
            (
                "打开 Chrome 并点击",
                "app.open_and_safe_click",
                {"app_name": "Google Chrome", "x": 120, "y": 240},
                "已打开 Google Chrome 并点击前台位置：120, 240。",
            ),
        )
        for prompt, tool_name, tool_input, expected_summary in cases:
            result = bridge.send_quick_message(
                prompt,
                metadata={
                    "source": "launcher",
                    "launcher_mode": "live2d",
                    "launcher_surface": "quick_message",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                    "desktop_permission_recovery": True,
                    "recovery_tool": tool_name,
                    "recovery_input": tool_input,
                    "recovery_permission_target": "foreground_input",
                    "recovery_risk_level": "low",
                },
            )
            agent_task = result["agent_task"]
            run = service.get_run(result["run_id"])
            event_types = [
                event["event_type"]
                for event in service.list_run_events(run["run_id"])["events"]
            ]

            assert result["ok"] is True
            assert agent_task["status"] == "completed"
            assert agent_task["needs_user_action"] is False
            assert agent_task["pending_approvals"] == []
            assert agent_task["summary"] == expected_summary
            assert agent_task["tool_calls"][-1]["tool_name"] == tool_name
            assert agent_task["tool_calls"][-1]["input_preview"] == tool_input
            assert run["status"] == "completed"
            assert run["pending_approval"] == {}
            assert "agent.desktop.intent_planned" in event_types
            assert "agent.tool.call" in event_types
            assert "agent.desktop.intent_completed" in event_types
            assert "agent.desktop.intent_approval_required" not in event_types
            assert "model.request.started" not in event_types
            assert "model.requested" not in event_types

        assert ("type", "hello") in calls
        assert ("shortcut", "paste") in calls
        assert ("key", "tab", 1) in calls
        assert ("scroll", "down", 2) in calls
        assert ("click", 120, 240) in calls
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_ui_element_recovery_retry_keeps_approval_gate(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-ui-element-recovery-approval.db",
        workspace_dir=tmp_path / "runtime-ui-element-recovery-approval",
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
            AssertionError("launcher UI element recovery retry should not call model")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.chat_api.desktop_permission_missing_by_capability",
        lambda use_cache=True: {},
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.type_into_ui_element",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("type_into_ui_element should wait for approval")
        ),
    )
    bridge = ChatBridge(runtime)
    try:
        tool_input = {
            "app_name": "WeChat",
            "target": "消息",
            "text": "文件传输助手",
            "role_filter": "text",
            "limit": 80,
        }
        result = bridge.send_quick_message(
            "恢复后重试原操作",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
                "daily_desktop_intent": True,
                "desktop_permission_recovery": True,
                "desktop_permission_retry": True,
                "recovery_action_kind": "retry_original",
                "recovery_tool": "app.open_and_type_into_ui_element",
                "recovery_input": tool_input,
                "recovery_permission_target": "foreground_input",
                "recovery_retry_tool": "app.open_and_type_into_ui_element",
                "recovery_retry_input": tool_input,
                "source_task_id": "task-source-ui-type",
            },
        )
        agent_task = result["agent_task"]
        run = service.get_run(result["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert result["ok"] is True
        assert agent_task["status"] == "waiting_approval"
        assert agent_task["needs_user_action"] is True
        assert agent_task["pending_approvals"][0]["tool_name"] == "app.open_and_type_into_ui_element"
        assert agent_task["pending_approvals"][0]["input_preview"] == tool_input
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.open_and_type_into_ui_element"
        assert agent_task["tool_calls"][-1]["status"] == "waiting_approval"
        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "app.open_and_type_into_ui_element"
        assert run["pending_approval"]["input_preview"] == tool_input
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.tool.approval_required" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_executes_recovery_retry_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-recovery-retry.db",
        workspace_dir=tmp_path / "runtime-recovery-retry",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    play_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher recovery retry should not call model")
        ),
    )

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
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "恢复后重试原操作",
            metadata={
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
                "daily_desktop_intent": True,
                "desktop_permission_recovery": True,
                "desktop_permission_retry": True,
                "recovery_action_kind": "retry_original",
                "recovery_tool": "media.apple_music_play",
                "recovery_input": {"query": "超时空辉夜姬"},
                "recovery_permission_target": "music_app",
                "recovery_retry_tool": "media.apple_music_play",
                "recovery_retry_input": {"query": "超时空辉夜姬"},
                "recovery_retry_prompt": "播放超时空辉夜姬",
                "source_task_id": "task-source-music",
            },
        )
        agent_task = result["agent_task"]
        run = service.get_run(result["run_id"])
        events = service.list_run_events(run["run_id"])["events"]
        event_types = [event["event_type"] for event in events]
        planned_event = next(
            event for event in events if event["event_type"] == "agent.desktop.intent_planned"
        )
        retry_context_event = next(
            event
            for event in events
            if event["event_type"] == "agent.desktop.recovery_retry_context"
        )
        messages = store.load_messages("session-current", limit=10)
        user = next(message for message in messages if message.role == "user")
        user_metadata = json.loads(user.metadata_json)

        assert result["ok"] is True
        assert play_calls == ["超时空辉夜姬"]
        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已在 Apple Music 播放：超时空辉夜姬 - Yachiyo。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
        assert agent_task["tool_calls"][-1]["input_preview"] == {"query": "超时空辉夜姬"}
        assert planned_event["payload"]["source"] == "daily_desktop_metadata"
        assert planned_event["payload"]["planning_reason"] == "structured_recovery_metadata"
        assert planned_event["payload"]["tool"] == "media.apple_music_play"
        assert retry_context_event["payload"]["retry_tool"] == "media.apple_music_play"
        assert retry_context_event["payload"]["retry_input"] == {"query": "超时空辉夜姬"}
        assert retry_context_event["payload"]["retry_prompt"] == "播放超时空辉夜姬"
        assert retry_context_event["payload"]["source_task_id"] == "task-source-music"
        assert user_metadata["desktop_permission_retry"] is True
        assert user_metadata["recovery_action_kind"] == "retry_original"
        assert user_metadata["recovery_retry_tool"] == "media.apple_music_play"
        assert "agent.desktop.recovery_retry_context" in event_types
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
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
            "你能帮我按Command L吗",
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


def test_chat_bridge_quick_message_approval_copies_current_page_link_without_model(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-current-page-link-copy.db",
        workspace_dir=tmp_path / "runtime-current-page-link-copy",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    hotkey_calls: list[tuple[str, list[str] | None]] = []
    shortcut_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("current page link copy should not call model")
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

    def fake_safe_shortcut(action: str) -> dict:
        shortcut_calls.append(action)
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Copied",
            "data": {
                "shortcut_action": action,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_hotkey", fake_hotkey)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "copy current page link",
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
        assert shortcut_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == "desktop.hotkey"
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "key": "l",
            "modifiers": ["command"],
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "desktop.hotkey"

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert hotkey_calls == [("l", ["command"])]
        assert shortcut_calls == ["copy"]
        assert approved.status == "completed"
        assert approved.summary == "已发送快捷键：Command+L。 已复制选中内容。"
        assert approved.needs_user_action is False
        assert approved.pending_approvals == []
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
    finally:
        service.close()
        store.close()


def test_chat_bridge_quick_message_routes_system_hotkeys_to_approval_and_completes(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-system-hotkey-approval.db",
        workspace_dir=tmp_path / "runtime-system-hotkey-approval",
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
            AssertionError("launcher system hotkey approval should not call model")
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
        cases = (
            (
                "最大化当前窗口",
                {"key": "f", "modifiers": ["control", "command"]},
                ("f", ["control", "command"]),
                "已发送快捷键：Control+Command+F。",
            ),
            (
                "switch to previous app",
                {"key": "tab", "modifiers": ["command"]},
                ("tab", ["command"]),
                "已发送快捷键：Command+tab。",
            ),
            (
                "switch to next app",
                {"key": "tab", "modifiers": ["command"]},
                ("tab", ["command"]),
                "已发送快捷键：Command+tab。",
            ),
        )
        for text, input_preview, expected_call, summary in cases:
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
            assert waiting_task["pending_approvals"][0]["tool_name"] == "desktop.hotkey"
            assert waiting_task["pending_approvals"][0]["input_preview"] == input_preview
            assert waiting_run["status"] == "approval_required"
            assert waiting_run["pending_approval"]["tool"] == "desktop.hotkey"

            approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
            run = service.get_run(link["run_id"])
            event_types = [
                event["event_type"]
                for event in service.list_run_events(run["run_id"])["events"]
            ]

            assert hotkey_calls[-1] == expected_call
            assert approved.status == "completed"
            assert approved.summary == summary
            assert approved.needs_user_action is False
            assert approved.pending_approvals == []
            assert run["status"] == "completed"
            assert run["pending_approval"] == {}
            assert "agent.desktop.intent_approval_required" in event_types
            assert "agent.desktop.intent_completed" in event_types
            assert "model.output.completed" in event_types

        assert hotkey_calls == [
            ("f", ["control", "command"]),
            ("tab", ["command"]),
            ("tab", ["command"]),
        ]
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


def test_chat_bridge_quick_message_browser_search_result_and_type_text_require_approval(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-browser-search-result-type.db",
        workspace_dir=tmp_path / "runtime-browser-search-result-type",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    click_calls: list[tuple[str, int]] = []
    type_calls: list[tuple[str, str]] = []
    search_selector = (
        'input[type="search"], input[name="q"], textarea[name="q"], '
        'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
        'input[aria-label*="search" i], input[placeholder*="search" i]'
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher browser approval should not call model")
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
                "label": "Yachiyo result",
                "tag": "A",
            },
        }

    def fake_browser_type_text(selector: str, text: str, **_kwargs: Any) -> dict:
        type_calls.append((selector, text))
        return {
            "ok": True,
            "action": "browser.type_text",
            "summary": "Typed browser text",
            "data": {
                "selector": selector,
                "length": len(text),
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.click", fake_browser_click)
    monkeypatch.setattr("apps.shell.agent.tools.browser.type_text", fake_browser_type_text)
    bridge = ChatBridge(runtime)
    try:
        cases = (
            (
                "click the first search result",
                "browser.click",
                {"selector": "search-result=1", "click_count": 1},
            ),
            (
                "type hello in current webpage search field",
                "browser.type_text",
                {"selector": search_selector, "text": "hello"},
            ),
        )
        for prompt, tool_name, input_preview in cases:
            result = bridge.send_quick_message(
                prompt,
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
            assert waiting_task["pending_approvals"][0]["input_preview"] == input_preview
            assert waiting_run["status"] == "approval_required"
            assert waiting_run["pending_approval"]["tool"] == tool_name

            approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
            run = service.get_run(link["run_id"])
            event_types = [
                event["event_type"]
                for event in service.list_run_events(run["run_id"])["events"]
            ]

            assert approved.status == "completed"
            assert approved.needs_user_action is False
            assert approved.pending_approvals == []
            assert run["status"] == "completed"
            assert run["pending_approval"] == {}
            assert "agent.desktop.intent_approval_required" in event_types
            assert "agent.desktop.intent_completed" in event_types
            assert "model.output.completed" in event_types

        assert click_calls == [("search-result=1", 1)]
        assert type_calls == [(search_selector, "hello")]
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


def test_chat_bridge_quick_message_requires_approval_for_terminal_run_intent(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-terminal-run-approval.db",
        workspace_dir=tmp_path / "runtime-terminal-run-approval",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    runtime.agent_runtime_service = service
    terminal_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: _FakeNoDefaultProfileService(),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("launcher terminal run intent should not call model")
        ),
    )

    def fake_run_terminal_command(command: str, **kwargs: Any) -> dict:
        terminal_calls.append((command, bool(kwargs.get("shell", False))))
        return {
            "ok": True,
            "returncode": 0,
            "timed_out": False,
            "shell": bool(kwargs.get("shell", False)),
            "stdout": "Desktop\n",
            "stderr": "",
        }

    monkeypatch.setattr("apps.shell.agent.tools.broker.run_terminal_command", fake_run_terminal_command)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开终端运行 ls",
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
        assert terminal_calls == []
        assert waiting_task["status"] == "waiting_approval"
        assert waiting_task["needs_user_action"] is True
        assert waiting_task["pending_approvals"][0]["tool_name"] == "terminal.run"
        assert waiting_task["pending_approvals"][0]["input_preview"] == {
            "command": "ls",
        }
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "terminal.run"
        assert waiting_run["pending_approval"]["input_preview"] == {
            "command": "ls",
        }

        approved = YachiyoAgentService(LegacyRuntimePort(service)).approve(task_id)
        run = service.get_run(link["run_id"])
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert terminal_calls == [("ls", False)]
        assert approved.status == "completed"
        assert approved.summary == "已运行命令：ls。\n输出：Desktop"
        assert approved.needs_user_action is False
        assert approved.pending_approvals == []
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert "agent.desktop.intent_approval_required" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
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
        "apps.shell.agent.tools.desktop.click_ui_element",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("click_ui_element should wait for approval")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.type_into_ui_element",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("type_into_ui_element should wait for approval")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_submit_foreground",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("submit_foreground should wait for approval")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_close_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("close_window should wait for approval")
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_hotkey",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hotkey should wait for approval")
        ),
    )
    bridge = ChatBridge(runtime)
    try:
        cases = [
            ("关闭当前窗口", "desktop.close_window", {}),
            ("把当前窗口关了", "desktop.close_window", {}),
            ("当前窗口关一下", "desktop.close_window", {}),
            (
                "click the search field",
                "desktop.click_ui_element",
                {"target": "search", "role_filter": "text", "limit": 80, "click_count": 1},
            ),
            (
                "点击可见的登录按钮",
                "desktop.click_ui_element",
                {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
            ),
            (
                "点一下登录",
                "desktop.click_ui_element",
                {"target": "登录", "role_filter": "button", "limit": 80, "click_count": 1},
            ),
            (
                "Can you click the login button?",
                "desktop.click_ui_element",
                {"target": "login", "role_filter": "button", "limit": 80, "click_count": 1},
            ),
            (
                "click login",
                "desktop.click_ui_element",
                {"target": "login", "role_filter": "button", "limit": 80, "click_count": 1},
            ),
            (
                "Can you type hello into the search field?",
                "desktop.type_into_ui_element",
                {"target": "search", "text": "hello", "role_filter": "text", "limit": 80},
            ),
            (
                "open Chrome and press command l",
                "app.open_and_hotkey",
                {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
            ),
            (
                "Could you open Chrome and press Command L?",
                "app.open_and_hotkey",
                {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
            ),
            ("send current message", "desktop.submit_foreground", {"action": "send"}),
            ("发送当前内容", "desktop.submit_foreground", {"action": "send"}),
            ("按回车提交", "desktop.submit_foreground", {"action": "submit"}),
            ("按 Command+L", "desktop.hotkey", {"key": "l", "modifiers": ["command"]}),
            ("Can you press Command L?", "desktop.hotkey", {"key": "l", "modifiers": ["command"]}),
            ("敲一下回车", "desktop.hotkey", {"key": "return", "modifiers": []}),
            ("hit enter", "desktop.hotkey", {"key": "return", "modifiers": []}),
            ("tap the return key", "desktop.hotkey", {"key": "return", "modifiers": []}),
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


def test_chat_bridge_quick_message_plans_app_observe_for_lightweight_entrypoints(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakePendingDesktopIntentRuntimeService()
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-app-observe",
            "task_id": "task-app-observe",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("看一下 Chrome 当前界面")

        assert result["ok"] is True
        assert result["task_id"] == "task-app-observe"
        assert result["agent_task"]["task_id"] == "task-app-observe"
        assert result["agent_task"]["status"] == "queued"
        assert result["agent_task"]["current_step"] == "准备执行 · 聚焦应用"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
        assert result["agent_task"]["recent_events"][0]["detail"] == "app.focus"
        assert result["agent_task"]["recent_events"][0]["payload"] == {
            "input_preview": {"app_name": "Google Chrome"},
            "planning_reason": "clear_daily_desktop_intent",
            "source": "daily_desktop_intent",
            "status": "planned",
            "tool": "app.focus",
        }
    finally:
        store.close()


def test_chat_bridge_quick_message_plans_app_open_visual_followup_for_lightweight_entrypoints(
    tmp_path,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakePendingDesktopIntentRuntimeService()
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-app-open-observe",
            "task_id": "task-app-open-observe",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("打开微信看看有没有新消息")

        assert result["ok"] is True
        assert result["task_id"] == "task-app-open-observe"
        assert result["agent_task"]["task_id"] == "task-app-open-observe"
        assert result["agent_task"]["status"] == "queued"
        assert result["agent_task"]["current_step"] == "准备执行 · 打开应用"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
        assert result["agent_task"]["recent_events"][0]["detail"] == "app.open"
        assert result["agent_task"]["recent_events"][0]["payload"] == {
            "input_preview": {"app_name": "WeChat"},
            "planning_reason": "clear_daily_desktop_intent",
            "source": "daily_desktop_intent",
            "status": "planned",
            "tool": "app.open",
        }
    finally:
        store.close()


def test_chat_bridge_quick_message_plans_note_creation_for_lightweight_entrypoints(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    runtime.agent_runtime_service = _FakePendingDesktopIntentRuntimeService()
    bridge = ChatBridge(runtime)
    bridge._chat_api = SimpleNamespace(
        send_message=lambda text, **_kwargs: {
            "ok": True,
            "message_id": "message-note",
            "task_id": "task-note",
            "status": "pending",
            "echo": text,
        }
    )
    try:
        result = bridge.send_quick_message("帮我记下 hello")

        assert result["ok"] is True
        assert result["task_id"] == "task-note"
        assert result["agent_task"]["task_id"] == "task-note"
        assert result["agent_task"]["status"] == "queued"
        assert result["agent_task"]["current_step"] == "准备执行 · 创建备忘录"
        assert result["agent_task"]["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
        assert result["agent_task"]["recent_events"][0]["detail"] == "notes.create"
        assert result["agent_task"]["recent_events"][0]["payload"] == {
            "input_preview": {"body": "hello"},
            "planning_reason": "clear_daily_desktop_intent",
            "source": "daily_desktop_intent",
            "status": "planned",
            "tool": "notes.create",
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
