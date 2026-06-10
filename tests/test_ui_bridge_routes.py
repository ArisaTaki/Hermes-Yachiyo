"""Electron UI bridge route tests."""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import apps.locald.screenshot as screenshot_mod
import apps.shell.config as config_mod
import apps.shell.live2d_resources as live2d_resources
import apps.shell.chat_api as chat_api_mod
from apps.bridge.routes import ui
from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.special_sessions import PROACTIVE_CHAT_SESSION_ID
from apps.core.state import AppState
from apps.shell.config import AppConfig


def _create_live2d_model_dir(root: Path, model_name: str = "demo") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{model_name}.model3.json").write_text("{}", encoding="utf-8")
    (root / f"{model_name}.moc3").write_text("stub", encoding="utf-8")
    return root


class _ChatRouteRuntime:
    def __init__(self, store: ChatStore) -> None:
        self.store = store
        self.state = AppState()
        self.chat_session = ChatSession(session_id="route-chat")
        self.chat_session.attach_store(store, load_existing=False)

    def start_new_session(self) -> str:
        self.chat_session = ChatSession()
        self.chat_session.attach_store(self.store, load_existing=False)
        return self.chat_session.session_id


@pytest.mark.asyncio
async def test_dashboard_route_uses_runtime_main_api(monkeypatch):
    runtime = SimpleNamespace(config=SimpleNamespace())
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeMainWindowAPI:
        def __init__(self, received_runtime, received_config):
            assert received_runtime is runtime
            assert received_config is runtime.config

        def get_dashboard_data(self):
            return {"app": {"running": True}}

    monkeypatch.setattr(ui, "MainWindowAPI", FakeMainWindowAPI)

    assert await ui.get_dashboard() == {"app": {"running": True}}


@pytest.mark.asyncio
async def test_settings_route_forwards_changes(monkeypatch):
    runtime = SimpleNamespace(config=SimpleNamespace())
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeMainWindowAPI:
        def __init__(self, received_runtime, received_config):
            assert received_runtime is runtime
            assert received_config is runtime.config

        def get_settings_data(self):
            return {"display": {"mode": "window"}}

        def update_settings(self, changes):
            return {"ok": True, "changes": changes}

    monkeypatch.setattr(ui, "MainWindowAPI", FakeMainWindowAPI)

    assert await ui.get_settings() == {"display": {"mode": "window"}}
    request = ui.SettingsUpdateRequest(changes={"display_mode": "bubble"})
    assert await ui.update_settings(request) == {
        "ok": True,
        "changes": {"display_mode": "bubble"},
    }


@pytest.mark.asyncio
async def test_clipboard_route_copies_text(monkeypatch):
    copied: list[str] = []

    monkeypatch.setattr(ui, "_copy_text_to_system_clipboard", copied.append)

    assert await ui.copy_clipboard_text(ui.ClipboardTextRequest(text="047e43ac")) == {"ok": True}
    assert copied == ["047e43ac"]


@pytest.mark.asyncio
async def test_clipboard_route_reports_system_failure(monkeypatch):
    def fail_copy(_text: str) -> None:
        raise RuntimeError("no clipboard")

    monkeypatch.setattr(ui, "_copy_text_to_system_clipboard", fail_copy)

    assert await ui.copy_clipboard_text(ui.ClipboardTextRequest(text="047e43ac")) == {
        "ok": False,
        "error": "no clipboard",
    }


def test_clipboard_route_redacts_secret_failure(monkeypatch):
    def fail_copy(_text: str) -> None:
        raise RuntimeError("pbcopy failed token=clipboard-secret-123456")

    monkeypatch.setattr(ui, "_copy_text_to_system_clipboard", fail_copy)

    result = asyncio.run(ui.copy_clipboard_text(ui.ClipboardTextRequest(text="047e43ac")))

    assert result["ok"] is False
    assert "clipboard-secret-123456" not in result["error"]
    assert "token=[redacted]" in result["error"]


@pytest.mark.asyncio
async def test_settings_operation_routes_use_main_api(monkeypatch):
    runtime = SimpleNamespace(config=SimpleNamespace())
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeMainWindowAPI:
        def __init__(self, received_runtime, received_config):
            assert received_runtime is runtime
            assert received_config is runtime.config

        def open_terminal_command(self, command):
            return {"success": True, "command": command}

        def run_native_diagnostic_command(self, command):
            return {"success": True, "command": command, "output": "ok"}

        def get_native_diagnostic_cache(self):
            return {"commands": {"doctor": {"success": True}}}

        def test_native_connection(self):
            return {"success": True, "message": "ok"}

        def test_native_image_connection(self):
            return {"success": True, "message": "image ok"}

        def get_native_configuration(self):
            return {"ok": True, "model": {"provider": "openai"}}

        def update_native_configuration(self, changes):
            return {"ok": True, "changes": changes}

        def get_native_tool_config(self):
            return {"ok": True, "tools": [{"id": "web"}]}

        def update_native_tool_config(self, tool_id, changes):
            return {"ok": True, "tool_id": tool_id, "changes": changes}

        def test_native_tool_config(self, tool_id):
            return {"ok": True, "tool_id": tool_id, "status": "pass"}

        def check_native_agent_update(self):
            return {"ok": True, "update_available": True}

        def update_native_agent(self, full_backup=False):
            return {"ok": True, "message": "updated", "full_backup": full_backup}

        def launch_browser_cdp(self):
            return {"ok": True, "url": "http://127.0.0.1:9222"}

        def recheck_native_agent(self):
            return {"native_agent": {"ready": True}}

        def restart_bridge(self):
            return {"ok": True, "bridge": "restarted"}

        def get_backup_status(self):
            return {"ok": True, "backups": []}

        def create_backup(self, overwrite_latest):
            return {"ok": True, "overwrite_latest": overwrite_latest}

        def restore_backup(self, backup_path):
            return {"ok": True, "restore": backup_path}

        def delete_backup(self, backup_path):
            return {"ok": True, "delete": backup_path}

        def open_backup_location(self, backup_path):
            return {"ok": True, "open": backup_path}

        def get_uninstall_preview(self, scope, keep_config, include_gpt_sovits=False):
            return {
                "ok": True,
                "scope": scope,
                "keep_config": keep_config,
                "include_gpt_sovits": include_gpt_sovits,
            }

        def run_uninstall(self, scope, keep_config, confirm_text, include_gpt_sovits=False):
            return {
                "ok": True,
                "scope": scope,
                "keep_config": keep_config,
                "include_gpt_sovits": include_gpt_sovits,
                "confirm_text": confirm_text,
            }

    monkeypatch.setattr(ui, "MainWindowAPI", FakeMainWindowAPI)

    assert await ui.open_native_terminal_command(ui.TerminalCommandRequest(command="native doctor")) == {
        "success": True,
        "command": "native doctor",
    }
    diagnostic_request = ui.TerminalCommandRequest(command="native doctor")
    assert await ui.run_native_diagnostic_command(diagnostic_request) == {
        "success": True,
        "command": "native doctor",
        "output": "ok",
    }
    assert await ui.get_native_diagnostic_cache() == {"commands": {"doctor": {"success": True}}}
    assert await ui.test_native_connection() == {"success": True, "message": "ok"}
    assert await ui.test_native_image_connection() == {"success": True, "message": "image ok"}
    assert await ui.get_native_configuration() == {"ok": True, "model": {"provider": "openai"}}
    assert await ui.update_native_configuration(ui.NativeConfigUpdateRequest(provider="openai", model="gpt-4.1")) == {
        "ok": True,
        "changes": {"provider": "openai", "model": "gpt-4.1", "base_url": "", "api_key": ""},
    }
    assert await ui.get_native_tool_config() == {"ok": True, "tools": [{"id": "web"}]}
    assert await ui.update_native_tool_config(
        ui.NativeToolConfigUpdateRequest(tool_id="web", changes={"web.backend": "exa"})
    ) == {
        "ok": True,
        "tool_id": "web",
        "changes": {"web.backend": "exa"},
    }
    assert await ui.test_native_tool_config(ui.NativeToolConfigTestRequest(tool_id="web")) == {
        "ok": True,
        "tool_id": "web",
        "status": "pass",
    }
    assert await ui.check_native_agent_update() == {"ok": True, "update_available": True}
    assert await ui.update_native_agent() == {"ok": True, "message": "updated", "full_backup": False}
    assert await ui.update_native_agent(ui.NativeUpdateRunRequest(backup=True)) == {
        "ok": True,
        "message": "updated",
        "full_backup": True,
    }
    assert await ui.launch_native_browser_cdp() == {
        "ok": True,
        "url": "http://127.0.0.1:9222",
    }
    assert await ui.recheck_native_agent() == {"native_agent": {"ready": True}}
    assert await ui.restart_bridge() == {"ok": True, "bridge": "restarted"}
    assert await ui.get_backup_status() == {"ok": True, "backups": []}
    assert await ui.create_backup(ui.BackupCreateRequest(overwrite_latest=True)) == {"ok": True, "overwrite_latest": True}
    assert await ui.restore_backup(ui.BackupPathRequest(backup_path="backup.zip")) == {"ok": True, "restore": "backup.zip"}
    assert await ui.delete_backup(ui.BackupPathRequest(backup_path="backup.zip")) == {"ok": True, "delete": "backup.zip"}
    assert await ui.open_backup_location(ui.BackupPathRequest(backup_path="backup.zip")) == {"ok": True, "open": "backup.zip"}
    assert await ui.get_uninstall_preview(scope="oha_only", keep_config=False, include_gpt_sovits=True) == {
        "ok": True,
        "scope": "oha_only",
        "keep_config": False,
        "include_gpt_sovits": True,
    }
    assert await ui.run_uninstall(ui.UninstallRunRequest(
        scope="oha_only",
        keep_config=True,
        include_gpt_sovits=True,
        confirm_text="UNINSTALL",
    )) == {
        "ok": True,
        "scope": "oha_only",
        "keep_config": True,
        "include_gpt_sovits": True,
        "confirm_text": "UNINSTALL",
    }


@pytest.mark.asyncio
async def test_proactive_screen_permission_route_checks_real_capture(monkeypatch):
    calls = []

    def fake_check(*, open_settings=False):
        calls.append(open_settings)
        return {"ok": False, "allowed": False, "permission_denied": True, "settings_opened": open_settings}

    monkeypatch.setattr(screenshot_mod, "check_screen_capture_permission", fake_check)

    result = await ui.check_proactive_screen_permission(ui.ScreenPermissionRequest(open_settings=True))

    assert result == {"ok": False, "allowed": False, "permission_denied": True, "settings_opened": True}
    assert calls == [True]


@pytest.mark.asyncio
async def test_chat_routes_use_shared_chat_api(monkeypatch):
    runtime = SimpleNamespace()
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_messages(self, limit, anchor_message_id=""):
            return {"messages": [], "limit": limit, "anchor_message_id": anchor_message_id}

        def send_message(self, text, attachments=None, runnable_id="", client_message_id=""):
            return {
                "ok": True,
                "text": text,
                "attachments": attachments or [],
                "runnable_id": runnable_id,
                "client_message_id": client_message_id,
            }

        def retry_message(self, message_id):
            return {"ok": True, "message_id": message_id}

        def summarize_delegated_run(self, run_id):
            return {
                "ok": True,
                "summary_created": True,
                "run_id": run_id,
                "task_id": "summary-task-1",
            }

        def create_group_session(self, *, name="", avatar_url="", participant_ids=None):
            return {"ok": True, "name": name, "avatar_url": avatar_url, "participant_ids": participant_ids or []}

        def update_group_session(self, session_id, *, name="", avatar_url="", participant_ids=None):
            return {
                "ok": True,
                "session_id": session_id,
                "name": name,
                "avatar_url": avatar_url,
                "participant_ids": participant_ids or [],
            }

        def get_session_info(self):
            return {"session_id": "session-1"}

        def clear_session(self):
            return {"ok": True}

        def cancel_current_tasks(self):
            return {"ok": True, "cancelled_tasks": 1}

        def delete_current_session(self):
            return {"ok": True, "deleted": True}

        def list_sessions(self, limit, query=""):
            return {"sessions": [], "limit": limit, "query": query}

        def load_session(self, session_id):
            return {"ok": True, "session_id": session_id}

        def get_executor_info(self):
            return {"executor": "NativeAgentExecutor", "available": True}

    monkeypatch.setattr(ui, "ChatAPI", FakeChatAPI)

    assert await ui.get_chat_messages(limit=12, anchor_message_id="m1") == {
        "messages": [],
        "limit": 12,
        "anchor_message_id": "m1",
    }
    assert await ui.send_chat_message(ui.SendChatMessageRequest(text="hello")) == {
        "ok": True,
        "text": "hello",
        "attachments": [],
        "runnable_id": "",
        "client_message_id": "",
    }
    assert await ui.send_chat_message(ui.SendChatMessageRequest(text="hello", client_message_id="client-1")) == {
        "ok": True,
        "text": "hello",
        "attachments": [],
        "runnable_id": "",
        "client_message_id": "client-1",
    }
    assert await ui.send_chat_message(
        ui.SendChatMessageRequest(text="hello"),
        SimpleNamespace(headers={"idempotency-key": "header-1"}),
    ) == {
        "ok": True,
        "text": "hello",
        "attachments": [],
        "runnable_id": "",
        "client_message_id": "header-1",
    }
    image_attachment = {
        "id": "pending-image",
        "name": "sketch.png",
        "mime_type": "image/png",
        "data_url": "data:image/png;base64,abc",
    }
    assert await ui.send_chat_message(
        ui.SendChatMessageRequest(text="给 Design 看这张图", attachments=[image_attachment], runnable_id="agent_design")
    ) == {
        "ok": True,
        "text": "给 Design 看这张图",
        "attachments": [image_attachment],
        "runnable_id": "agent_design",
        "client_message_id": "",
    }
    assert await ui.retry_chat_message(ui.RetryChatMessageRequest(message_id="m1")) == {
        "ok": True,
        "message_id": "m1",
    }
    assert await ui.summarize_delegated_run(ui.SummarizeDelegatedRunRequest(run_id="run_delegate_1")) == {
        "ok": True,
        "summary_created": True,
        "run_id": "run_delegate_1",
        "task_id": "summary-task-1",
    }
    assert await ui.create_chat_group(ui.CreateChatGroupRequest(name="demo", avatar_url="https://example.test/g.png", participant_ids=["a1"])) == {
        "ok": True,
        "name": "demo",
        "avatar_url": "https://example.test/g.png",
        "participant_ids": ["a1"],
    }
    assert await ui.update_chat_group("group-1", ui.UpdateChatGroupRequest(name="new", avatar_url="https://example.test/n.png", participant_ids=["a1"])) == {
        "ok": True,
        "session_id": "group-1",
        "name": "new",
        "avatar_url": "https://example.test/n.png",
        "participant_ids": ["a1"],
    }
    uploaded_avatar = "data:image/png;base64," + ("a" * 4096)
    assert await ui.create_chat_group(ui.CreateChatGroupRequest(name="uploaded", avatar_url=uploaded_avatar, participant_ids=["a1"])) == {
        "ok": True,
        "name": "uploaded",
        "avatar_url": uploaded_avatar,
        "participant_ids": ["a1"],
    }
    assert await ui.update_chat_group("group-1", ui.UpdateChatGroupRequest(name="uploaded-new", avatar_url=uploaded_avatar, participant_ids=["a1"])) == {
        "ok": True,
        "session_id": "group-1",
        "name": "uploaded-new",
        "avatar_url": uploaded_avatar,
        "participant_ids": ["a1"],
    }
    assert await ui.get_chat_session() == {"session_id": "session-1"}
    assert await ui.clear_chat_session() == {"ok": True}
    assert await ui.cancel_chat_session_tasks() == {"ok": True, "cancelled_tasks": 1}
    assert await ui.delete_chat_session() == {"ok": True, "deleted": True}
    assert await ui.list_chat_sessions(limit=3, query="聊天") == {
        "sessions": [],
        "limit": 3,
        "query": "聊天",
    }
    assert await ui.load_chat_session(ui.LoadChatSessionRequest(session_id="s2")) == {
        "ok": True,
        "session_id": "s2",
    }
    assert await ui.get_chat_executor() == {
        "executor": "NativeAgentExecutor",
        "available": True,
    }


@pytest.mark.asyncio
async def test_chat_group_routes_create_real_group_context(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    design = {
        "id": "agent_design",
        "name": "Design Agent",
        "nickname": "Design",
        "kind": "agent",
        "enabled": True,
        "category": "design",
        "description": "负责 UI 方案与视觉验收。",
        "output_contract": "markdown",
    }
    coding = {
        "id": "agent_coding",
        "name": "Coding Agent",
        "nickname": "Code",
        "kind": "agent",
        "enabled": True,
        "category": "coding",
        "description": "负责前端实现与代码修改。",
        "output_contract": "diff",
    }

    class FakeRunnableService:
        def resolve_runnable(self, *, runnable_id="", name=""):
            for agent in (design, coding):
                if runnable_id == agent["id"] or name in {agent["name"], agent["nickname"]}:
                    return agent
            return None

    monkeypatch.setattr(chat_api_mod, "get_agent_runtime_service", lambda: FakeRunnableService())
    try:
        created = await ui.create_chat_group(
            ui.CreateChatGroupRequest(name="设计群", participant_ids=[design["id"]])
        )
        assert created["ok"] is True
        assert created["session_context"]["conversation_kind"] == "group"
        assert [item["nickname"] for item in created["session_context"]["participants"]] == [
            "月見八千代",
            "Design",
        ]
        updated = await ui.update_chat_group(
            created["session_id"],
            ui.UpdateChatGroupRequest(name="设计实现群", participant_ids=[design["id"], coding["id"]]),
        )

        assert updated["ok"] is True
        assert updated["session_context"]["runnable_name"] == "设计实现群"
        assert [item["nickname"] for item in updated["session_context"]["participants"]] == [
            "月見八千代",
            "Design",
            "Code",
        ]

        sent = await ui.send_chat_message(ui.SendChatMessageRequest(text="帮我安排一个登录页视觉方案"))

        assert sent["ok"] is True
        task = runtime.state.get_task(sent["task_id"])
        assert task is not None
        assert task.chat_session_id == runtime.chat_session.session_id
        assert "[Yachiyo 群组上下文]" in task.description
        assert "- Design（Agent；Design Agent） - 类别：design；交付：markdown" in task.description
        assert "- Code（Agent；Coding Agent） - 类别：coding；交付：diff" in task.description
        assert "负责 UI 方案与视觉验收。" in task.description
        assert "负责前端实现与代码修改。" in task.description
    finally:
        store.close()


@pytest.mark.asyncio
async def test_activity_route_forwards_filters(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ui,
        "list_activity_events",
        lambda **kwargs: calls.append(kwargs) or {"ok": True, "events": []},
    )

    result = await ui.get_activity_events(
        query="script",
        status="running",
        tool="terminal",
        session_id="s1",
        task_id="t1",
        limit=25,
    )

    assert result == {"ok": True, "events": []}
    assert calls == [{
        "query": "script",
        "status": "running",
        "tool": "terminal",
        "phase": "",
        "session_id": "s1",
        "task_id": "t1",
        "limit": 25,
    }]

@pytest.mark.asyncio
async def test_launcher_routes_reuse_chat_bridge_and_notification_tracker(monkeypatch):
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            bubble_mode=SimpleNamespace(
                summary_count=2,
                default_display="summary",
                show_unread_dot=True,
                auto_hide=False,
                opacity=0.9,
            ),
            live2d_mode=SimpleNamespace(
                show_reply_bubble=True,
                enable_quick_input=True,
                click_action="open_chat",
                default_open_behavior="reply_bubble",
            ),
        )
    )
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    ui._launcher_notifications.clear()

    class FakeChatBridge:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_conversation_overview(self, summary_count, session_limit):
            assert session_limit == 3
            return {
                "empty": False,
                "is_processing": False,
                "status_label": f"最近 {summary_count} 条",
                "latest_reply": "短回复",
                "latest_reply_full": "完整回复",
            }

        def send_quick_message(self, text):
            return {"ok": True, "text": text}

    class FakeNotificationTracker:
        def update(self, chat, external_attention=False):
            assert chat["latest_reply"] == "短回复"
            assert external_attention is False
            return {"has_unread": True, "latest_message": {"status": "completed"}}

        def acknowledge(self, chat=None):
            assert chat is not None

    monkeypatch.setattr(ui, "ChatBridge", FakeChatBridge)
    monkeypatch.setattr(ui, "LauncherNotificationTracker", FakeNotificationTracker)
    ui._launcher_proactive_services.clear()

    bubble_payload = await ui.get_launcher_view("bubble")
    assert bubble_payload["mode"] == "bubble"
    assert bubble_payload["proactive"]["status"] == "disabled"
    bubble_launcher = bubble_payload["launcher"]
    assert bubble_launcher["default_display"] == "summary"
    assert bubble_launcher["expand_trigger"] == "click"
    assert bubble_launcher["show_unread_dot"] is True
    assert bubble_launcher["auto_hide"] is False
    assert bubble_launcher["opacity"] == 0.9
    assert bubble_launcher["avatar_url"].startswith("data:image/")
    assert bubble_launcher["suppress_status_dot"] is False
    assert bubble_launcher["has_attention"] is True
    assert bubble_launcher["latest_status"] == "completed"
    assert bubble_launcher["status_label"] == "最近 2 条"
    assert bubble_launcher["latest_reply"] == "短回复"
    assert bubble_launcher["latest_reply_full"] == "完整回复"

    live2d_payload = await ui.get_launcher_view("live2d")
    assert live2d_payload["launcher"]["show_reply_bubble"] is True
    assert live2d_payload["launcher"]["enable_quick_input"] is True
    assert live2d_payload["launcher"]["latest_status"] == "completed"
    assert await ui.acknowledge_launcher(ui.LauncherAckRequest(mode="live2d")) == {
        "ok": True,
        "mode": "live2d",
        "session_id": PROACTIVE_CHAT_SESSION_ID,
    }
    assert await ui.send_launcher_quick_message(ui.LauncherQuickMessageRequest(text="hi")) == {
        "ok": True,
        "text": "hi",
    }


def test_launcher_tts_only_triggers_for_proactive_attention(monkeypatch):
    spoken = []
    config = SimpleNamespace(
        tts=SimpleNamespace(enabled=True, provider="command", command="say {text}", max_chars=80)
    )
    runtime = SimpleNamespace(config=config)

    class FakeTTSService:
        def __init__(self, _config):
            pass

        def get_status(self):
            return {"enabled": True, "provider": "command", "ok": True, "message": "idle"}

        def speak_async(self, text, **_kwargs):
            spoken.append(text)
            return {"enabled": True, "provider": "command", "ok": True, "scheduled": True}

    monkeypatch.setattr(ui, "TTSService", FakeTTSService)
    ui._launcher_tts_services.clear()
    ui._launcher_last_tts_attention.clear()
    ui._launcher_pending_tts_attention.clear()
    ui._launcher_completed_tts_attention.clear()

    idle = ui._maybe_trigger_proactive_tts(runtime, "live2d", {"has_attention": False})
    first = ui._maybe_trigger_proactive_tts(
        runtime,
        "bubble",
        {
            "has_attention": True,
            "task_id": "task-1",
            "attention_text": "桌面观察提醒：先保存一下进度。",
        },
    )
    duplicate = ui._maybe_trigger_proactive_tts(
        runtime,
        "bubble",
        {
            "has_attention": True,
            "task_id": "task-1",
            "attention_text": "桌面观察提醒：先保存一下进度。",
        },
    )

    assert idle["message"] == "idle"
    assert first["scheduled"] is True
    assert duplicate["pending_audio"] is True
    assert duplicate["message"] == "主动关怀语音生成中"
    assert spoken == ["桌面观察提醒：先保存一下进度。"]


def test_launcher_tts_triggers_without_probability_gate(monkeypatch):
    spoken = []
    config = SimpleNamespace(
        tts=SimpleNamespace(
            enabled=True,
            provider="command",
            command="say {text}",
            max_chars=80,
        )
    )
    runtime = SimpleNamespace(config=config)

    class FakeTTSService:
        def __init__(self, _config):
            pass

        def get_status(self):
            return {"enabled": True, "provider": "command", "ok": True, "message": "idle"}

        def speak_async(self, text, **_kwargs):
            spoken.append(text)
            return {"enabled": True, "provider": "command", "ok": True, "scheduled": True}

    monkeypatch.setattr(ui, "TTSService", FakeTTSService)
    ui._launcher_tts_services.clear()
    ui._launcher_last_tts_attention.clear()
    ui._launcher_pending_tts_attention.clear()
    ui._launcher_completed_tts_attention.clear()

    first = ui._maybe_trigger_proactive_tts(
        runtime,
        "live2d",
        {"has_attention": True, "task_id": "task-skip", "attention_text": "先喝口水。"},
    )
    duplicate = ui._maybe_trigger_proactive_tts(
        runtime,
        "bubble",
        {"has_attention": True, "task_id": "task-skip", "attention_text": "先喝口水。"},
    )

    assert first["scheduled"] is True
    assert duplicate["pending_audio"] is True
    assert spoken == ["先喝口水。"]


@pytest.mark.asyncio
async def test_launcher_hides_proactive_reply_while_tts_audio_is_generating(monkeypatch):
    config = SimpleNamespace(
        tts=SimpleNamespace(enabled=True, provider="command", command="say {text}", max_chars=80),
        bubble_mode=SimpleNamespace(
            summary_count=2,
            default_display="summary",
            show_unread_dot=True,
            auto_hide=False,
            opacity=0.9,
        ),
        live2d_mode=SimpleNamespace(),
    )
    runtime = SimpleNamespace(config=config)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        ui,
        "_launcher_proactive_state",
        lambda *_args, **_kwargs: {
            "has_attention": True,
            "task_id": "task-pending-audio",
            "attention_text": "八六，先保存一下进度。",
            "message": "八六，先保存一下进度。",
        },
    )

    class FakeChatBridge:
        def __init__(self, _runtime):
            pass

        def get_conversation_overview(self, summary_count, session_limit):
            return {
                "empty": False,
                "is_processing": False,
                "status_label": "最近 2 条",
                "latest_reply": "八六，先保存一下进度。",
                "latest_reply_full": "八六，先保存一下进度。",
                "latest_notifiable_message": {
                    "marker": "task-pending-audio",
                    "status": "completed",
                    "content": "八六，先保存一下进度。",
                },
            }

    class FakeTTSService:
        def __init__(self, _config):
            pass

        def get_status(self):
            return {"enabled": True, "provider": "command", "ok": True, "message": "idle"}

        def speak_async(self, text, **_kwargs):
            return {"enabled": True, "provider": "command", "ok": True, "scheduled": True}

    monkeypatch.setattr(ui, "ChatBridge", FakeChatBridge)
    monkeypatch.setattr(ui, "TTSService", FakeTTSService)
    ui._launcher_notifications.clear()
    ui._launcher_tts_services.clear()
    ui._launcher_last_tts_attention.clear()
    ui._launcher_pending_tts_attention.clear()
    ui._launcher_completed_tts_attention.clear()

    payload = await ui.get_launcher_view("bubble")

    assert payload["tts"]["pending_audio"] is True
    assert payload["proactive"]["has_attention"] is False
    assert payload["proactive"]["status"] == "tts_pending"
    assert payload["notification"]["has_unread"] is False
    assert payload["launcher"]["has_attention"] is False
    assert payload["launcher"]["latest_reply"] == ""


@pytest.mark.asyncio
async def test_proactive_tts_test_route_invokes_sync_service(monkeypatch):
    spoken = []
    config = SimpleNamespace(
        tts=SimpleNamespace(enabled=True, provider="command", command="say {text}", max_chars=80)
    )
    runtime = SimpleNamespace(config=config)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeTTSService:
        def __init__(self, received_config):
            assert received_config is config.tts

        def speak_sync(self, text):
            spoken.append(text)
            return {
                "ok": True,
                "success": True,
                "provider": "command",
                "message": "TTS 测试已完成",
                "spoken_text": text,
            }

    monkeypatch.setattr(ui, "TTSService", FakeTTSService)

    result = await ui.test_proactive_tts(ui.TtsTestRequest(text="测试一下主动关怀语音。"))

    assert result == {
        "tool": "proactive_tts",
        "ok": True,
        "success": True,
        "provider": "command",
        "message": "TTS 测试已完成",
        "spoken_text": "测试一下主动关怀语音。",
    }
    assert spoken == ["测试一下主动关怀语音。"]


@pytest.mark.asyncio
async def test_proactive_tts_status_route_returns_last_launcher_status(monkeypatch):
    config = SimpleNamespace(
        tts=SimpleNamespace(enabled=True, provider="command", command="say {text}", max_chars=80)
    )
    runtime = SimpleNamespace(config=config)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeTTSService:
        def __init__(self, received_config):
            assert received_config is config.tts

        def get_status(self):
            return {
                "enabled": True,
                "provider": "command",
                "ok": False,
                "error": "boom",
                "message": "TTS 触发失败",
            }

    service = FakeTTSService(config.tts)
    ui._launcher_tts_services.clear()
    ui._launcher_tts_services[id(runtime)] = service

    result = await ui.get_proactive_tts_status()

    assert result == {
        "tool": "proactive_tts",
        "source": "launcher",
        "enabled": True,
        "provider": "command",
        "ok": False,
        "error": "boom",
        "message": "TTS 触发失败",
    }
    ui._launcher_tts_services.clear()


@pytest.mark.asyncio
async def test_gpt_sovits_service_routes_use_runtime_config(monkeypatch):
    config = SimpleNamespace(tts=SimpleNamespace(provider="gpt-sovits"))
    runtime = SimpleNamespace(config=config)
    calls = []
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        ui,
        "get_gpt_sovits_service_status",
        lambda received_config: calls.append(("status", received_config)) or {"reachable": True},
    )
    monkeypatch.setattr(
        ui,
        "get_gpt_sovits_service_status_for_values",
        lambda **kwargs: calls.append(("draft_status", kwargs)) or {"workdir_exists": True},
    )
    monkeypatch.setattr(
        ui,
        "install_gpt_sovits_launch_agent",
        lambda received_config: calls.append(("install", received_config)) or {"ok": True},
    )
    monkeypatch.setattr(
        ui,
        "adopt_gpt_sovits_launch_agent",
        lambda received_config: calls.append(("adopt", received_config)) or {"ok": True},
    )
    monkeypatch.setattr(
        ui,
        "uninstall_gpt_sovits_launch_agent",
        lambda received_config: calls.append(("uninstall", received_config)) or {"ok": True},
    )

    assert await ui.get_tts_gpt_sovits_service_status() == {"reachable": True}
    assert await ui.get_tts_gpt_sovits_service_status_for_draft(
        ui.GptSovitsServiceStatusRequest(
            base_url="http://127.0.0.1:9880",
            workdir="~/AI/GPT-SoVITS",
            command="python api_v2.py",
        )
    ) == {"workdir_exists": True}
    assert await ui.install_tts_gpt_sovits_service() == {"ok": True}
    assert await ui.adopt_tts_gpt_sovits_service() == {"ok": True}
    assert await ui.uninstall_tts_gpt_sovits_service() == {"ok": True}
    assert calls == [
        ("status", config),
        (
            "draft_status",
            {
                "base_url": "http://127.0.0.1:9880",
                "workdir": "~/AI/GPT-SoVITS",
                "command": "python api_v2.py",
            },
        ),
        ("install", config),
        ("adopt", config),
        ("uninstall", config),
    ]


@pytest.mark.asyncio
async def test_launcher_live2d_payload_includes_preview_and_renderer(monkeypatch):
    monkeypatch.setattr(config_mod, "find_default_live2d_model_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config_mod, "get_user_live2d_assets_dir", lambda: Path("/tmp/no-live2d-assets"))
    config = AppConfig(display_mode="live2d")
    runtime = SimpleNamespace(config=config, task_runner=None)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    ui._launcher_notifications.clear()
    ui._launcher_proactive_services.clear()

    class FakeChatBridge:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_conversation_overview(self, summary_count, session_limit):
            return {"empty": True, "is_processing": False, "status_label": "暂无对话"}

    monkeypatch.setattr(ui, "ChatBridge", FakeChatBridge)

    payload = await ui.get_launcher_view("live2d")
    launcher = payload["launcher"]

    assert launcher["preview_url"].startswith("data:image/")
    assert launcher["scale"] == 0.6
    assert launcher["position_anchor"] == "right_bottom"
    assert launcher["mouse_follow_enabled"] is True
    assert launcher["render_quality_preset"] == "balanced"
    assert launcher["render_fps"] == 24
    assert launcher["render_resolution"] == 1.25
    assert launcher["hit_region_precision"] == "medium"
    assert launcher["resource"]["state"] == "not_configured"
    assert "GitHub Releases" in launcher["resource"]["help_text"]
    assert launcher["renderer"]["enabled"] is False
    assert launcher["renderer"]["model_url"] == ""
    assert launcher["renderer"]["render_quality_preset"] == "balanced"
    assert launcher["renderer"]["render_fps"] == 24
    assert launcher["renderer"]["render_resolution"] == 1.25
    assert launcher["renderer"]["hit_region_precision"] == "medium"


@pytest.mark.asyncio
async def test_launcher_position_route_persists_bubble_percent(monkeypatch):
    config = SimpleNamespace(
        bubble_mode=SimpleNamespace(width=112, height=112),
        live2d_mode=SimpleNamespace(),
    )
    runtime = SimpleNamespace(config=config)
    calls = []
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        ui,
        "apply_settings_changes",
        lambda received_config, changes: calls.append((received_config, changes)) or {"ok": True, "applied": changes},
    )

    payload = await ui.save_launcher_position(
        ui.LauncherPositionRequest(
            mode="bubble",
                x=444,
                y=344,
            width=112,
            height=112,
            work_area=ui.LauncherWorkAreaRequest(x=0, y=0, width=1000, height=800),
        )
    )

    assert payload["ok"] is True
    assert payload["mode"] == "bubble"
    assert calls[0][0] is config
    assert calls[0][1]["bubble_mode.position_x"] == 444
    assert calls[0][1]["bubble_mode.position_y"] == 344
    assert calls[0][1]["bubble_mode.position_x_percent"] == pytest.approx(0.5)
    assert calls[0][1]["bubble_mode.position_y_percent"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_launcher_position_route_persists_live2d_bounds(monkeypatch):
    config = SimpleNamespace(
        bubble_mode=SimpleNamespace(),
        live2d_mode=SimpleNamespace(),
    )
    runtime = SimpleNamespace(config=config)
    calls = []
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        ui,
        "apply_settings_changes",
        lambda received_config, changes: calls.append((received_config, changes)) or {"ok": True, "applied": changes},
    )

    payload = await ui.save_launcher_position(
        ui.LauncherPositionRequest(mode="live2d", x=80, y=96, width=420, height=680)
    )

    assert payload["ok"] is True
    assert calls == [
        (
            config,
            {
                "live2d_mode.position_anchor": "custom",
                "live2d_mode.position_x": 80,
                "live2d_mode.position_y": 96,
                "live2d_mode.width": 420,
                "live2d_mode.height": 680,
            },
        )
    ]


@pytest.mark.asyncio
async def test_mode_settings_route_serializes_descriptor(monkeypatch):
    runtime = SimpleNamespace(config=SimpleNamespace())
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        ui,
        "serialize_mode_window_data",
        lambda config, mode_id: {
            "mode": {"id": mode_id, "name": "Bubble"},
            "settings": {"summary": mode_id, "config": {"size": 112}},
        },
    )

    payload = await ui.get_mode_settings("bubble")

    assert payload == {
        "mode": {"id": "bubble", "name": "Bubble"},
        "settings": {"summary": "bubble", "config": {"size": 112}},
    }


@pytest.mark.asyncio
async def test_live2d_prepare_model_path_route_returns_draft(monkeypatch, tmp_path):
    config = AppConfig(display_mode="live2d")
    runtime = SimpleNamespace(config=config)
    model_dir = _create_live2d_model_dir(tmp_path / "picked" / "yachiyo")
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    result = await ui.prepare_live2d_model_path(
        ui.Live2DResourcePathRequest(path=str(model_dir))
    )

    assert result["ok"] is True
    assert config.live2d_mode.model_path == ""
    assert result["draft_changes"] == {"live2d_mode.model_path": str(model_dir)}
    assert result["preview"]["settings"]["config"]["model_path"] == str(model_dir)
    assert "等待保存更改" in result["message"]


@pytest.mark.asyncio
async def test_live2d_import_archive_route_returns_draft(monkeypatch, tmp_path):
    source_root = tmp_path / "release" / "yachiyo"
    _create_live2d_model_dir(source_root, model_name="yachiyo")
    archive_path = tmp_path / "yachiyo-live2d.zip"
    import_root = tmp_path / "imported"
    config = AppConfig(display_mode="live2d")
    runtime = SimpleNamespace(config=config)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    monkeypatch.setattr(live2d_resources, "get_user_live2d_assets_dir", lambda: import_root)

    with zipfile.ZipFile(archive_path, "w") as archive:
        for file_path in source_root.rglob("*"):
            archive.write(file_path, file_path.relative_to(source_root.parent))

    result = await ui.import_live2d_archive_path(
        ui.Live2DResourcePathRequest(path=str(archive_path))
    )

    imported_path = import_root / "yachiyo"
    assert result["ok"] is True
    assert imported_path.exists()
    assert config.live2d_mode.model_path == ""
    assert result["draft_changes"] == {"live2d_mode.model_path": str(imported_path)}
    assert result["preview"]["settings"]["config"]["model_path"] == str(imported_path)
    assert "已导入" in result["message"]


def test_live2d_zip_member_name_recovers_utf8_without_flag():
    original = "八千代辉夜姬/八千代辉夜姬.model3.json"
    garbled = original.encode("utf-8").decode("cp437")
    info = zipfile.ZipInfo(garbled)
    info.flag_bits = 0

    assert live2d_resources._decode_zip_member_name(info) == original
