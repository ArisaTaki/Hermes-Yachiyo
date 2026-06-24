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


def test_chat_bridge_quick_message_opens_system_settings_pane_without_model(
    tmp_path,
    monkeypatch,
):
    open_calls: list[str] = []

    def fake_app_open(app_name: str) -> dict:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened System Settings: {app_name}",
            "data": {
                "app_name": app_name,
                "open_target": "system_settings",
                "settings_label": "Bluetooth",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开蓝牙设置",
    )

    assert result["ok"] is True
    assert open_calls == ["System Settings"]
    assert agent_task["summary"] == "已打开 System Settings。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": "System Settings"}
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


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
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "能不能切到 Slack",
    )

    assert result["ok"] is True
    assert focus_calls == ["Slack"]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已切换到 Slack。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus"
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

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
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
        "打开 Spotify 播放周杰伦",
    )

    assert result["ok"] is True
    assert open_calls == ["Spotify"]
    assert agent_task["summary"] == "已打开 Spotify。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
    assert agent_task["tool_calls"][-1]["status"] == "completed"
    assert run["status"] == "completed"
    assert "agent.desktop.intent_planned" in event_types
    assert "agent.tool.call" in event_types
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types
    assert "model.requested" not in event_types


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
    result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "打开 ChatGPT 客户端",
    )

    assert result["ok"] is True
    assert open_calls == ["ChatGPT"]
    assert agent_task["summary"] == "已打开 ChatGPT。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
    assert agent_task["tool_calls"][-1]["input_preview"] == {"app_name": "ChatGPT"}
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
        "看看当前界面有哪些按钮",
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

    for launcher_mode in ("bubble", "live2d"):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "给我来点音乐",
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

    assert open_and_play_calls == 3


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

    for launcher_mode in ("bubble", "live2d"):
        result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "换首歌",
            launcher_mode=launcher_mode,
        )

        assert result["ok"] is True
        assert agent_task["summary"] == "已切到下一首 Apple Music。当前：超时空辉夜姬 - Yachiyo。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "media.apple_music_control"
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

    assert control_calls == ["next", "next"]


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
        "复制以下内容：hello world",
    )

    assert clipboard_calls == ["hello world"]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "已复制 11 个字符到剪贴板。"
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
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "剪贴板里是什么",
    )

    assert read_calls == [2000]
    assert agent_task["status"] == "completed"
    assert agent_task["summary"] == "剪贴板内容：hello world"
    assert agent_task["tool_calls"][-1]["tool_name"] == "clipboard.read"
    assert agent_task["tool_calls"][-1]["input_preview"] == {}
    assert run["status"] == "completed"
    assert "agent.desktop.intent_completed" in event_types
    assert "model.request.started" not in event_types


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

    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "屏幕上有什么",
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

    assert len(capture_targets) == 3


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

    assert len(calls) == 8
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
    _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
        tmp_path,
        monkeypatch,
        "Chrome 新建标签页",
    )

    assert calls == [("focus", "Google Chrome"), ("shortcut", "new_tab")]
    assert agent_task["status"] == "completed"
    assert agent_task["needs_user_action"] is False
    assert agent_task["pending_approvals"] == []
    assert agent_task["summary"] == "已切到 Google Chrome 并新建标签页。"
    assert agent_task["tool_calls"][-1]["tool_name"] == "app.focus_and_safe_shortcut"
    assert agent_task["tool_calls"][-1]["input_preview"] == {
        "app_name": "Google Chrome",
        "action": "new_tab",
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
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "按向下箭头三次",
            launcher_mode=launcher_mode,
        )

        assert agent_task["status"] == "completed"
        assert agent_task["needs_user_action"] is False
        assert agent_task["pending_approvals"] == []
        assert agent_task["summary"] == "已按下箭头（3 次）。"
        assert agent_task["tool_calls"][-1]["tool_name"] == "desktop.safe_key"
        assert agent_task["tool_calls"][-1]["input_preview"] == {
            "action": "arrow_down",
            "repeat_count": 3,
        }
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types

    assert pressed == [("arrow_down", 3), ("arrow_down", 3)]


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
    for launcher_mode in ("bubble", "live2d"):
        _result, agent_task, run, event_types = _run_launcher_daily_desktop_quick_message(
            tmp_path,
            monkeypatch,
            "翻到下一页",
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

    assert scrolled == [("down", 1), ("down", 1)]


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
    bridge = ChatBridge(runtime)
    try:
        cases = [
            ("关闭当前窗口", "desktop.close_window", {}),
            (
                "click the search field",
                "desktop.click_ui_element",
                {"target": "search", "role_filter": "text", "limit": 80, "click_count": 1},
            ),
            (
                "open Chrome and press command l",
                "app.open_and_hotkey",
                {"app_name": "Google Chrome", "key": "l", "modifiers": ["command"]},
            ),
            ("send current message", "desktop.submit_foreground", {"action": "send"}),
            ("发送当前内容", "desktop.submit_foreground", {"action": "send"}),
            ("按回车提交", "desktop.submit_foreground", {"action": "submit"}),
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
