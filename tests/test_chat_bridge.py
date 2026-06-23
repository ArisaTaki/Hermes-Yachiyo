"""ChatBridge session overview tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell import chat_bridge as chat_bridge_mod
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.chat_bridge import ChatBridge
from apps.shell.credential_store import MemoryCredentialStore


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


def test_chat_bridge_quick_message_executes_daily_desktop_task_for_launcher_entrypoints(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _runtime_with_chat_store(store)
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
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
            AssertionError("launcher daily desktop quick message should not call model")
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
                "launch_verified": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    bridge = ChatBridge(runtime)
    try:
        result = bridge.send_quick_message(
            "打开 Apple Music",
            metadata={
                "source": "launcher",
                "launcher_mode": "live2d",
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
        messages = store.load_messages("session-current", limit=10)
        user = next(message for message in messages if message.role == "user")
        assistant = next(message for message in messages if message.role == "assistant")
        user_metadata = json.loads(user.metadata_json)

        assert result["ok"] is True
        assert open_calls == ["Music"]
        assert agent_task["task_id"] == result["task_id"]
        assert agent_task["conversation_id"] == "session-current"
        assert agent_task["status"] == "completed"
        assert agent_task["summary"] == "已打开 Music。"
        assert agent_task["open_in_studio_url"] == f"#/agents?run_id={run['run_id']}"
        assert agent_task["tool_calls"][-1]["tool_name"] == "app.open"
        assert agent_task["tool_calls"][-1]["status"] == "completed"
        assert run["status"] == "completed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert user_metadata["source"] == "launcher"
        assert user_metadata["launcher_mode"] == "live2d"
        assert assistant.content == "已打开 Music。"
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
