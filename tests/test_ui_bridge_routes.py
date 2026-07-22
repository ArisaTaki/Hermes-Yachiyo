"""Electron UI bridge route tests."""

from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

import apps.locald.screenshot as screenshot_mod
import apps.shell.chat_api as chat_api_mod
import apps.shell.config as config_mod
import apps.shell.live2d_resources as live2d_resources
import apps.shell.mode_settings as mode_settings
import apps.shell.tts as tts_mod
import apps.shell.tts_resources as tts_resources
from apps.bridge.routes import ui
from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.special_sessions import PROACTIVE_CHAT_SESSION_ID
from apps.core.state import AppState
from apps.shell.config import AppConfig
from packages.protocol.enums import TaskStatus, TaskType


def _create_live2d_model_dir(root: Path, model_name: str = "demo") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{model_name}.model3.json").write_text("{}", encoding="utf-8")
    (root / f"{model_name}.moc3").write_text("stub", encoding="utf-8")
    return root


class _GptSovitsHttpServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                return

            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                owner.requests.append(
                    {
                        "method": "GET",
                        "path": parsed.path,
                        "query": {key: values[-1] for key, values in query.items()},
                    }
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length") or "0"))
                owner.requests.append(
                    {
                        "method": "POST",
                        "path": urlparse(self.path).path,
                        "body": json.loads(body.decode("utf-8") or "{}"),
                    }
                )
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                self.wfile.write(b"RIFF\x24\x00\x00\x00WAVEfmt ")

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()


class _ChatRouteRuntime:
    def __init__(self, store: ChatStore) -> None:
        self.store = store
        self.state = AppState()
        self.cancelled_runner_tasks: list[str] = []
        self.chat_session = ChatSession(session_id="route-chat")
        self.chat_session.attach_store(store, load_existing=False)

    def start_new_session(self) -> str:
        self.chat_session = ChatSession()
        self.chat_session.attach_store(self.store, load_existing=False)
        return self.chat_session.session_id

    def switch_session(self, session_id: str) -> None:
        session = ChatSession(session_id=session_id)
        session.attach_store(
            self.store,
            load_existing=True,
            fail_active_messages=False,
            create_if_missing=False,
        )
        self.chat_session = session

    def cancel_task_runner_task(self, task_id: str) -> None:
        self.cancelled_runner_tasks.append(task_id)


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
async def test_yachiyo_desktop_permission_settings_route_opens_macos_pane(monkeypatch):
    calls = []
    cache_cleared = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ui.sys, "platform", "darwin")
    monkeypatch.setattr(ui.subprocess, "run", fake_run)
    monkeypatch.setattr(ui, "clear_desktop_permission_probe_cache", lambda: cache_cleared.append(True))

    result = await ui.open_yachiyo_desktop_permission_settings(
        ui.DesktopPermissionSettingsRequest(target="screen_recording")
    )

    assert result["ok"] is True
    assert result["opened"] is True
    assert result["target"] == "screen_recording"
    assert "Privacy_Screen" in result["settings_url"]
    assert calls[0][0][0] == "open"
    assert cache_cleared == [True]


@pytest.mark.asyncio
async def test_yachiyo_desktop_permission_settings_route_opens_music_app(monkeypatch):
    calls = []
    cache_cleared = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ui.sys, "platform", "darwin")
    monkeypatch.setattr(ui.subprocess, "run", fake_run)
    monkeypatch.setattr(ui, "clear_desktop_permission_probe_cache", lambda: cache_cleared.append(True))

    result = await ui.open_yachiyo_desktop_permission_settings(
        ui.DesktopPermissionSettingsRequest(target="music_app")
    )

    assert result == {
        "ok": True,
        "opened": True,
        "target": "music_app",
        "label": "Music.app",
        "app_name": "Music",
        "message": "已打开 Music.app，请确认它可启动并允许自动化控制。",
    }
    assert calls[0][0] == ["open", "-a", "Music"]
    assert cache_cleared == [True]


@pytest.mark.asyncio
async def test_yachiyo_desktop_permission_settings_route_reports_unsupported_platform(monkeypatch):
    monkeypatch.setattr(ui.sys, "platform", "linux")

    result = await ui.open_yachiyo_desktop_permission_settings(
        ui.DesktopPermissionSettingsRequest(target="accessibility")
    )

    assert result == {
        "ok": False,
        "opened": False,
        "target": "accessibility",
        "label": "辅助功能",
        "message": "当前平台不支持自动打开 macOS 系统设置。",
    }


@pytest.mark.asyncio
async def test_chat_routes_use_shared_chat_api(monkeypatch):
    runtime = SimpleNamespace(chat_session=SimpleNamespace(session_id="session-route"))
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_messages(self, limit, anchor_message_id=""):
            return {"messages": [], "limit": limit, "anchor_message_id": anchor_message_id}

        def get_messages_in_session(self, session_id, limit, anchor_message_id=""):
            assert session_id == runtime.chat_session.session_id
            return self.get_messages(limit, anchor_message_id=anchor_message_id)

        def send_message(self, text, attachments=None, runnable_id="", client_message_id=""):
            return {
                "ok": True,
                "text": text,
                "attachments": attachments or [],
                "runnable_id": runnable_id,
                "client_message_id": client_message_id,
            }

        def send_message_in_session(
            self,
            session_id,
            text,
            attachments=None,
            runnable_id="",
            client_message_id="",
        ):
            assert session_id == runtime.chat_session.session_id
            return self.send_message(
                text,
                attachments,
                runnable_id=runnable_id,
                client_message_id=client_message_id,
            )

        def retry_message(self, message_id, *, client_message_id=""):
            return {
                "ok": True,
                "message_id": message_id,
                "client_message_id": client_message_id,
            }

        def summarize_delegated_run(self, run_id, *, conversation_id=""):
            return {
                "ok": True,
                "summary_created": True,
                "run_id": run_id,
                "conversation_id": conversation_id,
                "run_group_id": "run_group_delegate_1",
                "run_status": "completed",
                "source_task_id": "source-task-1",
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

        def delete_session(self, session_id=""):
            return {"ok": True, "deleted": True, "deleted_session_id": session_id}

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
    assert await ui.send_chat_message(ui.SendChatMessageRequest(text="hello", message_id="legacy-1")) == {
        "ok": True,
        "text": "hello",
        "attachments": [],
        "runnable_id": "",
        "client_message_id": "legacy-1",
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
    assert await ui.retry_chat_message(ui.RetryChatMessageRequest(
        message_id="m1",
        client_message_id="retry-client-1",
    )) == {
        "ok": True,
        "message_id": "m1",
        "client_message_id": "retry-client-1",
    }
    assert await ui.summarize_delegated_run(
        ui.SummarizeDelegatedRunRequest(
            run_id="run_delegate_1",
            conversation_id="session-summary-a",
        )
    ) == {
        "ok": True,
        "summary_created": True,
        "run_id": "run_delegate_1",
        "conversation_id": "session-summary-a",
        "run_group_id": "run_group_delegate_1",
        "run_status": "completed",
        "source_task_id": "source-task-1",
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
    assert await ui.delete_chat_session(
        ui.DeleteChatSessionRequest(session_id="session-delete-a")
    ) == {
        "ok": True,
        "deleted": True,
        "deleted_session_id": "session-delete-a",
    }
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
async def test_send_chat_message_keeps_bridge_event_loop_responsive(monkeypatch):
    runtime = SimpleNamespace(chat_session=SimpleNamespace(session_id="session-slow-send"))
    started = threading.Event()
    release = threading.Event()
    release_timer = threading.Timer(0.25, release.set)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class SlowChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def send_message_in_session(
            self,
            session_id,
            text,
            attachments=None,
            runnable_id="",
            client_message_id="",
        ):
            assert session_id == runtime.chat_session.session_id
            started.set()
            assert release.wait(timeout=1)
            return {"ok": True, "task_id": "task-slow-chat"}

    monkeypatch.setattr(ui, "ChatAPI", SlowChatAPI)
    release_timer.start()
    started_at = time.monotonic()
    try:
        send_task = asyncio.create_task(
            ui.send_chat_message(ui.SendChatMessageRequest(text="slow desktop task"))
        )
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0.02)
        assert time.monotonic() - started_at < 0.15
        assert await send_task == {"ok": True, "task_id": "task-slow-chat"}
    finally:
        release.set()
        release_timer.cancel()


@pytest.mark.asyncio
async def test_get_chat_messages_keeps_bridge_event_loop_responsive(monkeypatch):
    runtime = SimpleNamespace(chat_session=SimpleNamespace(session_id="session-slow-get"))
    started = threading.Event()
    release = threading.Event()
    release_timer = threading.Timer(0.25, release.set)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class SlowChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_messages_in_session(self, session_id, limit, anchor_message_id=""):
            assert session_id == runtime.chat_session.session_id
            started.set()
            assert release.wait(timeout=1)
            return {"ok": True, "messages": [], "limit": limit}

    monkeypatch.setattr(ui, "ChatAPI", SlowChatAPI)
    release_timer.start()
    started_at = time.monotonic()
    try:
        messages_task = asyncio.create_task(ui.get_chat_messages(limit=12))
        assert await asyncio.to_thread(started.wait, 1)
        await asyncio.sleep(0.02)
        assert time.monotonic() - started_at < 0.15
        assert await messages_task == {"ok": True, "messages": [], "limit": 12}
    finally:
        release.set()
        release_timer.cancel()


@pytest.mark.asyncio
async def test_send_chat_message_stays_bound_to_session_selected_before_worker_starts(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    session_a_id = runtime.chat_session.session_id
    session_b = ChatSession(session_id="route-chat-b")
    session_b.attach_store(store, load_existing=False)
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class BlockingChatAPI(chat_api_mod.ChatAPI):
        def send_message(
            self,
            text,
            attachments=None,
            *,
            runnable_id="",
            client_message_id="",
            metadata=None,
        ):
            started.set()
            assert release.wait(timeout=3)
            return super().send_message(
                text,
                attachments,
                runnable_id=runnable_id,
                client_message_id=client_message_id,
                metadata=metadata,
            )

    monkeypatch.setattr(ui, "ChatAPI", BlockingChatAPI)

    try:
        send_task = asyncio.create_task(
            ui.send_chat_message(
                ui.SendChatMessageRequest(
                    text="message for session A",
                    client_message_id="session-race-send-a",
                )
            )
        )
        assert await asyncio.to_thread(started.wait, 3)

        loaded = await ui.load_chat_session(
            ui.LoadChatSessionRequest(session_id=session_b.session_id)
        )
        assert loaded["ok"] is True
        assert runtime.chat_session.session_id == session_b.session_id

        release.set()
        result = await send_task

        assert result["ok"] is True
        assert runtime.chat_session.session_id == session_b.session_id
        assert [
            message.content
            for message in store.load_messages(session_a_id, limit=0)
            if message.role == "user"
        ] == ["message for session A"]
        assert [
            message.content
            for message in store.load_messages(session_b.session_id, limit=0)
            if message.role == "user"
        ] == []
    finally:
        release.set()
        store.close()


@pytest.mark.asyncio
async def test_get_chat_messages_stays_bound_to_session_selected_before_worker_starts(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    session_a_id = runtime.chat_session.session_id
    runtime.chat_session.add_user_message("message already in session A")
    session_b = ChatSession(session_id="route-chat-get-b")
    session_b.attach_store(store, load_existing=False)
    session_b.add_user_message("message already in session B")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class BlockingChatAPI(chat_api_mod.ChatAPI):
        def get_messages(self, limit=0, anchor_message_id=""):
            started.set()
            assert release.wait(timeout=3)
            return super().get_messages(limit, anchor_message_id=anchor_message_id)

    monkeypatch.setattr(ui, "ChatAPI", BlockingChatAPI)

    try:
        messages_task = asyncio.create_task(ui.get_chat_messages(limit=20))
        assert await asyncio.to_thread(started.wait, 3)

        loaded = await ui.load_chat_session(
            ui.LoadChatSessionRequest(session_id=session_b.session_id)
        )
        assert loaded["ok"] is True
        assert runtime.chat_session.session_id == session_b.session_id

        release.set()
        result = await messages_task

        assert result["ok"] is True
        assert result["session_id"] == session_a_id
        assert [message["content"] for message in result["messages"]] == [
            "message already in session A"
        ]
        assert runtime.chat_session.session_id == session_b.session_id
    finally:
        release.set()
        store.close()


@pytest.mark.asyncio
async def test_send_chat_message_does_not_recreate_a_deleted_captured_session(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    session_a_id = runtime.chat_session.session_id
    session_b = ChatSession(session_id="route-chat-delete-b")
    session_b.attach_store(store, load_existing=False)
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class BlockingChatAPI(chat_api_mod.ChatAPI):
        def send_message(
            self,
            text,
            attachments=None,
            *,
            runnable_id="",
            client_message_id="",
            metadata=None,
        ):
            started.set()
            assert release.wait(timeout=3)
            return super().send_message(
                text,
                attachments,
                runnable_id=runnable_id,
                client_message_id=client_message_id,
                metadata=metadata,
            )

    monkeypatch.setattr(ui, "ChatAPI", BlockingChatAPI)

    try:
        send_task = asyncio.create_task(
            ui.send_chat_message(
                ui.SendChatMessageRequest(
                    text="must not survive deleted session",
                    client_message_id="session-deleted-before-send",
                )
            )
        )
        assert await asyncio.to_thread(started.wait, 3)

        runtime.switch_session(session_b.session_id)
        store.delete_session(session_a_id)
        release.set()
        result = await send_task

        assert result["ok"] is False
        assert result["committed"] is False
        assert result["delivery_state"] == "not_committed"
        assert result["reason"] == "chat_session_deleted"
        assert runtime.chat_session.session_id == session_b.session_id
        assert store.get_session(session_a_id) is None
        assert store.load_messages(session_a_id, limit=0) == []
        assert store.load_messages(session_b.session_id, limit=0) == []
    finally:
        release.set()
        store.close()


@pytest.mark.asyncio
async def test_delete_waits_for_committed_send_then_cancels_it_without_touching_loaded_session(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    session_a_id = runtime.chat_session.session_id
    session_b = ChatSession(session_id="route-chat-delete-loaded-b")
    session_b.attach_store(store, load_existing=False)
    session_b.add_user_message("keep session B")
    send_committed = threading.Event()
    release_send = threading.Event()
    delete_entered = threading.Event()
    committed_task_id = ""
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class BlockingAfterCommitChatAPI(chat_api_mod.ChatAPI):
        def send_message(
            self,
            text,
            attachments=None,
            *,
            runnable_id="",
            client_message_id="",
            metadata=None,
        ):
            nonlocal committed_task_id
            result = super().send_message(
                text,
                attachments,
                runnable_id=runnable_id,
                client_message_id=client_message_id,
                metadata=metadata,
            )
            committed_task_id = str(result.get("task_id") or "")
            assert committed_task_id
            send_committed.set()
            assert release_send.wait(timeout=3)
            return result

        def delete_session(self, session_id=""):
            delete_entered.set()
            return super().delete_session(session_id)

    monkeypatch.setattr(ui, "ChatAPI", BlockingAfterCommitChatAPI)

    try:
        send_task = asyncio.create_task(
            ui.send_chat_message(
                ui.SendChatMessageRequest(
                    text="committed in A before delete",
                    client_message_id="session-delete-after-commit",
                )
            )
        )
        assert await asyncio.to_thread(send_committed.wait, 3)
        assert runtime.state.get_task(committed_task_id) is not None

        loaded = await ui.load_chat_session(
            ui.LoadChatSessionRequest(session_id=session_b.session_id)
        )
        assert loaded["ok"] is True
        assert runtime.chat_session.session_id == session_b.session_id

        heartbeat_started_at = time.monotonic()
        delete_task = asyncio.create_task(
            ui.delete_chat_session(
                ui.DeleteChatSessionRequest(session_id=session_a_id)
            )
        )
        assert await asyncio.to_thread(delete_entered.wait, 3)
        await asyncio.sleep(0.02)

        assert time.monotonic() - heartbeat_started_at < 0.15
        assert delete_task.done() is False

        release_send.set()
        send_result, delete_result = await asyncio.gather(send_task, delete_task)

        assert send_result["ok"] is True
        assert send_result["committed"] is True
        assert delete_result["ok"] is True
        assert delete_result["deleted_session_id"] == session_a_id
        assert delete_result["session_id"] == session_b.session_id
        assert delete_result["cancelled_tasks"] == 1
        task = runtime.state.get_task(committed_task_id)
        assert task is not None
        assert task.status == TaskStatus.CANCELLED
        assert runtime.cancelled_runner_tasks == [committed_task_id]
        assert store.get_session(session_a_id) is None
        assert store.load_messages(session_a_id, limit=0) == []
        assert store.get_session(session_b.session_id) is not None
        assert [
            message.content
            for message in store.load_messages(session_b.session_id, limit=0)
        ] == ["keep session B"]
        assert runtime.chat_session.session_id == session_b.session_id
        assert all(
            item.status not in (TaskStatus.PENDING, TaskStatus.RUNNING)
            for item in runtime.state.list_tasks()
            if item.chat_session_id == session_a_id
        )
    finally:
        release_send.set()
        store.close()


@pytest.mark.asyncio
async def test_delete_remains_bound_to_captured_session_when_another_window_loads_b(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    session_a_id = runtime.chat_session.session_id
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    sent_a = await ui.send_chat_message(
        ui.SendChatMessageRequest(
            text="active task in A",
            client_message_id="delete-cas-session-a",
        )
    )
    task_a_id = sent_a["task_id"]

    session_b = ChatSession(session_id="route-chat-delete-cas-b")
    session_b.attach_store(store, load_existing=False)
    message_b_id = session_b.add_user_message("keep active task in B")
    task_b = runtime.state.create_task(
        task_type=TaskType.GENERAL,
        description="task in B must survive",
        chat_session_id=session_b.session_id,
    )
    session_b.link_message_to_task(message_b_id, task_b.task_id)
    cancel_entered = threading.Event()
    release_cancel = threading.Event()

    class BlockingDeleteChatAPI(chat_api_mod.ChatAPI):
        def _cancel_active_session_tasks(self, reason):
            cancel_entered.set()
            assert release_cancel.wait(timeout=3)
            return super()._cancel_active_session_tasks(reason)

    monkeypatch.setattr(ui, "ChatAPI", BlockingDeleteChatAPI)

    try:
        delete_task = asyncio.create_task(
            ui.delete_chat_session()
        )
        assert await asyncio.to_thread(cancel_entered.wait, 3)

        load_started_at = time.monotonic()
        loaded = await ui.load_chat_session(
            ui.LoadChatSessionRequest(session_id=session_b.session_id)
        )
        assert time.monotonic() - load_started_at < 0.15
        assert loaded["ok"] is True
        assert runtime.chat_session.session_id == session_b.session_id
        assert delete_task.done() is False

        release_cancel.set()
        deleted = await delete_task

        assert deleted["ok"] is True
        assert deleted["deleted_session_id"] == session_a_id
        assert deleted["session_id"] == session_b.session_id
        assert runtime.chat_session.session_id == session_b.session_id
        assert store.get_session(session_a_id) is None
        assert store.load_messages(session_a_id, limit=0) == []
        assert runtime.state.get_task(task_a_id).status == TaskStatus.CANCELLED
        assert runtime.state.get_task(task_b.task_id).status == TaskStatus.PENDING
        assert runtime.cancelled_runner_tasks == [task_a_id]
        assert [
            (message.content, message.task_id)
            for message in store.load_messages(session_b.session_id, limit=0)
        ] == [("keep active task in B", task_b.task_id)]
    finally:
        release_cancel.set()
        store.close()


@pytest.mark.asyncio
async def test_discard_waits_for_committed_send_and_keeps_nonempty_captured_session(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    session_a_id = runtime.chat_session.session_id
    session_b = ChatSession(session_id="route-chat-discard-send-wins-b")
    session_b.attach_store(store, load_existing=False)
    session_b.add_user_message("keep B while discarding A")
    send_committed = threading.Event()
    release_send = threading.Event()
    discard_entered = threading.Event()
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class BlockingSendChatAPI(chat_api_mod.ChatAPI):
        def send_message(
            self,
            text,
            attachments=None,
            *,
            runnable_id="",
            client_message_id="",
            metadata=None,
        ):
            result = super().send_message(
                text,
                attachments,
                runnable_id=runnable_id,
                client_message_id=client_message_id,
                metadata=metadata,
            )
            assert result.get("task_id")
            send_committed.set()
            assert release_send.wait(timeout=3)
            return result

        def discard_empty_current_session(self, session_id=""):
            discard_entered.set()
            if session_id:
                return super().discard_empty_current_session(session_id)
            return super().discard_empty_current_session()

    monkeypatch.setattr(ui, "ChatAPI", BlockingSendChatAPI)

    try:
        send_task = asyncio.create_task(
            ui.send_chat_message(
                ui.SendChatMessageRequest(
                    text="send wins discard race in A",
                    client_message_id="discard-send-wins-a",
                )
            )
        )
        assert await asyncio.to_thread(send_committed.wait, 3)

        heartbeat_started_at = time.monotonic()
        discard_task = asyncio.create_task(ui.discard_empty_chat_session())
        assert await asyncio.to_thread(discard_entered.wait, 3)
        await asyncio.sleep(0.02)
        assert time.monotonic() - heartbeat_started_at < 0.15
        assert discard_task.done() is False

        loaded = await ui.load_chat_session(
            ui.LoadChatSessionRequest(session_id=session_b.session_id)
        )
        assert loaded["ok"] is True
        assert runtime.chat_session.session_id == session_b.session_id

        release_send.set()
        send_result, discard_result = await asyncio.gather(send_task, discard_task)

        assert send_result["ok"] is True
        assert send_result["committed"] is True
        assert discard_result == {
            "ok": True,
            "discarded": False,
            "session_id": session_a_id,
        }
        assert store.get_session(session_a_id) is not None
        assert [
            message.content
            for message in store.load_messages(session_a_id, limit=0)
            if message.role == "user"
        ] == ["send wins discard race in A"]
        assert [
            message.content
            for message in store.load_messages(session_b.session_id, limit=0)
        ] == ["keep B while discarding A"]
        assert runtime.chat_session.session_id == session_b.session_id
    finally:
        release_send.set()
        store.close()


@pytest.mark.asyncio
async def test_chat_message_route_retry_after_lost_response_reuses_committed_task(
    tmp_path,
    monkeypatch,
):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _ChatRouteRuntime(store)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    try:
        request = ui.SendChatMessageRequest(
            text="send exactly once",
            client_message_id="route-response-lost-1",
        )
        first = await ui.send_chat_message(request)
        retry = await ui.send_chat_message(request)

        assert first["ok"] is True
        assert first["committed"] is True
        assert first["delivery_state"] == "accepted"
        assert retry["ok"] is True
        assert retry["committed"] is True
        assert retry["delivery_state"] == "accepted"
        assert retry["idempotent"] is True
        assert retry["client_message_id"] == request.client_message_id
        assert retry["message_id"] == first["message_id"]
        assert retry["task_id"] == first["task_id"]
        assert len(runtime.state.list_tasks()) == 1
        assert len(
            [
                message
                for message in runtime.chat_session.get_messages(0)
                if message.role.value == "user"
            ]
        ) == 1

        rejected = await ui.send_chat_message(
            ui.SendChatMessageRequest(
                text="",
                client_message_id="route-invalid-empty-1",
            )
        )
        assert rejected["ok"] is False
        assert rejected["committed"] is False
        assert rejected["delivery_state"] == "not_committed"
    finally:
        store.close()


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
        assert "[Oha-Yachiyo 群组上下文]" in task.description
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
    recovery_action = {
        "label": "打开辅助功能权限",
        "tool": "app.open",
        "input": {"app_name": "辅助功能权限"},
        "permission_target": "accessibility",
        "risk_level": "low",
    }

    class FakeChatBridge:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_conversation_overview(self, summary_count, session_limit):
            assert session_limit == 3
            return {
                "empty": False,
                "agent_task": {
                    "task_id": "launcher-task-1",
                    "conversation_id": "launcher-session-1",
                    "title": "Public launcher task",
                    "status": "waiting_approval",
                    "needs_user_action": True,
                    "pending_approvals": [
                        {
                            "approval_id": "approval-1",
                            "tool_name": "terminal.run",
                            "status": "pending",
                            "open_in_studio_url": "#/agents?run_id=launcher-task-1",
                        }
                    ],
                    "recent_events": [
                        {
                            "event_type": "agent.tool.approval_required",
                            "title": "Approval required",
                        },
                        {
                            "event_type": "agent.desktop.permission_recovery",
                            "title": "需要辅助功能权限",
                            "payload": {
                                "permission_targets": ["accessibility"],
                                "affected_tools": ["desktop.safe_click"],
                                "recovery_actions": [recovery_action],
                            },
                        }
                    ],
                    "tool_calls": [
                        {
                            "tool_name": "desktop.safe_click",
                            "status": "failed",
                            "output_preview": {
                                "permission_error": True,
                                "permission_targets": ["accessibility"],
                                "recovery_actions": [recovery_action],
                            },
                        }
                    ],
                    "artifacts": [],
                    "open_in_studio_url": "#/agents?run_id=launcher-task-1",
                },
                "is_processing": False,
                "status_label": f"最近 {summary_count} 条",
                "latest_reply": "短回复",
                "latest_reply_full": "完整回复",
            }

        def send_quick_message(self, text, *, metadata=None):
            assert metadata == {
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
            }
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
    assert bubble_payload["chat"]["agent_task"]["task_id"] == "launcher-task-1"
    assert bubble_payload["chat"]["agent_task"]["status"] == "waiting_approval"
    assert bubble_payload["chat"]["agent_task"]["needs_user_action"] is True
    assert (
        bubble_payload["chat"]["agent_task"]["pending_approvals"][0]["open_in_studio_url"]
        == "#/agents?run_id=launcher-task-1"
    )
    assert (
        bubble_payload["chat"]["agent_task"]["recent_events"][0]["event_type"]
        == "agent.tool.approval_required"
    )
    assert (
        bubble_payload["chat"]["agent_task"]["recent_events"][1]["event_type"]
        == "agent.desktop.permission_recovery"
    )
    assert (
        bubble_payload["chat"]["agent_task"]["recent_events"][1]["payload"]["recovery_actions"][0]
        == recovery_action
    )
    assert (
        bubble_payload["chat"]["agent_task"]["tool_calls"][0]["output_preview"]["recovery_actions"][0]
        == recovery_action
    )

    live2d_payload = await ui.get_launcher_view("live2d")
    assert live2d_payload["launcher"]["show_reply_bubble"] is True
    assert live2d_payload["launcher"]["enable_quick_input"] is True
    assert live2d_payload["launcher"]["latest_status"] == "completed"
    assert live2d_payload["chat"]["agent_task"]["task_id"] == "launcher-task-1"
    assert live2d_payload["chat"]["agent_task"]["open_in_studio_url"] == "#/agents?run_id=launcher-task-1"
    assert (
        live2d_payload["chat"]["agent_task"]["recent_events"][1]["payload"]["permission_targets"]
        == ["accessibility"]
    )
    assert (
        live2d_payload["chat"]["agent_task"]["tool_calls"][0]["output_preview"]["permission_targets"]
        == ["accessibility"]
    )
    assert await ui.acknowledge_launcher(ui.LauncherAckRequest(mode="live2d")) == {
        "ok": True,
        "mode": "live2d",
        "session_id": PROACTIVE_CHAT_SESSION_ID,
    }
    assert await ui.send_launcher_quick_message(ui.LauncherQuickMessageRequest(text="hi")) == {
        "ok": True,
        "text": "hi",
    }


@pytest.mark.asyncio
async def test_launcher_quick_message_returns_agent_task_snapshot_when_available(monkeypatch):
    class FakeLauncherAgentRuntimeService:
        def get_run(self, run_id: str):
            return {
                "run_id": run_id,
                "user_goal": "Launcher quick task",
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

    runtime = SimpleNamespace(agent_runtime_service=FakeLauncherAgentRuntimeService())
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeChatBridge:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def send_quick_message(self, text, *, metadata=None):
            assert metadata == {
                "source": "launcher",
                "launcher_mode": "live2d",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
            }
            return {"ok": True, "text": text, "task_id": "launcher-task-1"}

    monkeypatch.setattr(ui, "ChatBridge", FakeChatBridge)

    result = await ui.send_launcher_quick_message(
        ui.LauncherQuickMessageRequest(text="hi", mode="live2d"),
    )

    assert result["ok"] is True
    assert result["text"] == "hi"
    assert result["task_id"] == "launcher-task-1"
    assert result["agent_task"]["task_id"] == "launcher-task-1"
    assert result["agent_task"]["status"] == "waiting_approval"
    assert result["agent_task"]["needs_user_action"] is True
    assert result["agent_task"]["open_in_studio_url"] == "#/agents?run_id=launcher-task-1"


@pytest.mark.asyncio
async def test_launcher_quick_message_preserves_chat_bridge_agent_task_recovery(monkeypatch):
    runtime_snapshot_calls: list[str] = []

    class FakeLauncherAgentRuntimeService:
        def get_run(self, run_id: str):
            runtime_snapshot_calls.append(run_id)
            return {
                "run_id": run_id,
                "user_goal": "Stale launcher task",
                "status": "running",
                "timeline": [],
            }

    runtime = SimpleNamespace(agent_runtime_service=FakeLauncherAgentRuntimeService())
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    recovery_action = {
        "label": "打开辅助功能权限",
        "tool": "app.open",
        "input": {"app_name": "辅助功能权限"},
        "permission_target": "accessibility",
        "risk_level": "low",
    }
    agent_task = {
        "task_id": "launcher-task-recovery",
        "conversation_id": "launcher-session-1",
        "title": "点击 120, 240",
        "status": "failed",
        "needs_user_action": True,
        "pending_approvals": [],
        "recent_events": [
            {
                "event_type": "agent.desktop.permission_recovery",
                "title": "需要辅助功能权限",
                "payload": {
                    "permission_targets": ["accessibility"],
                    "affected_tools": ["desktop.safe_click"],
                    "recovery_actions": [recovery_action],
                },
            }
        ],
        "tool_calls": [
            {
                "tool_name": "desktop.safe_click",
                "status": "failed",
                "output_preview": {
                    "permission_error": True,
                    "permission_targets": ["accessibility"],
                    "recovery_actions": [recovery_action],
                },
            }
        ],
        "artifacts": [],
        "open_in_studio_url": "#/agents?run_id=launcher-task-recovery",
    }

    class FakeChatBridge:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def send_quick_message(self, text, *, metadata=None):
            assert metadata == {
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "quick_message",
                "runnable_kind": "main",
            }
            return {
                "ok": True,
                "text": text,
                "task_id": "launcher-task-recovery",
                "agent_task": agent_task,
            }

    monkeypatch.setattr(ui, "ChatBridge", FakeChatBridge)

    result = await ui.send_launcher_quick_message(
        ui.LauncherQuickMessageRequest(text="点击 120, 240", mode="bubble"),
    )

    assert runtime_snapshot_calls == []
    assert result["ok"] is True
    assert result["agent_task"] == agent_task
    assert (
        result["agent_task"]["recent_events"][0]["payload"]["recovery_actions"][0]
        == recovery_action
    )
    assert (
        result["agent_task"]["tool_calls"][0]["output_preview"]["recovery_actions"][0]
        == recovery_action
    )


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


@pytest.mark.asyncio
async def test_live2d_and_tts_resource_routes_import_save_and_test(monkeypatch, tmp_path):
    config = AppConfig(display_mode="bubble")
    runtime = SimpleNamespace(config=config)
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    monkeypatch.setattr(mode_settings, "save_config", lambda _config: None)
    monkeypatch.setattr(live2d_resources, "get_user_live2d_assets_dir", lambda: tmp_path / "live2d-assets")
    monkeypatch.setattr(tts_resources, "get_user_tts_assets_dir", lambda: tmp_path / "tts-assets")
    monkeypatch.setattr(tts_mod.TTSService, "_play_audio_file", lambda self, audio_path: None)

    live2d_source = tmp_path / "live2d-release" / "yachiyo-live2d"
    _create_live2d_model_dir(live2d_source, model_name="yachiyo")
    live2d_archive = tmp_path / "yachiyo-live2d.zip"
    with zipfile.ZipFile(live2d_archive, "w") as archive:
        for file_path in live2d_source.rglob("*"):
            archive.write(file_path, file_path.relative_to(live2d_source.parent))

    live2d_import = await ui.import_live2d_archive_path(
        ui.Live2DResourcePathRequest(path=str(live2d_archive))
    )
    live2d_changes = {
        **live2d_import["draft_changes"],
        "display_mode": "live2d",
    }
    live2d_save = await ui.update_settings(ui.SettingsUpdateRequest(changes=live2d_changes))

    assert live2d_import["ok"] is True
    assert live2d_save["ok"] is True
    assert config.display_mode == "live2d"
    assert Path(config.live2d_mode.model_path).is_dir()
    assert Path(config.live2d_mode.model_path, "yachiyo.model3.json").is_file()

    with _GptSovitsHttpServer() as gsv:
        voice_root = tmp_path / "voice-package"
        (voice_root / "GPT_weights_v4").mkdir(parents=True)
        (voice_root / "SoVITS_weights_v4").mkdir(parents=True)
        (voice_root / "refs").mkdir(parents=True)
        (voice_root / "GPT_weights_v4" / "yachiyo.ckpt").write_bytes(b"gpt")
        (voice_root / "SoVITS_weights_v4" / "yachiyo.pth").write_bytes(b"sovits")
        (voice_root / "refs" / "yachiyo.wav").write_bytes(b"RIFFvoice")
        (voice_root / "yachiyo-tts-preset.json").write_text(
            json.dumps(
                {
                    "kind": tts_resources.TTS_PRESET_KIND,
                    "schema_version": 1,
                    "slug": "route-e2e-voice",
                    "base_url": gsv.url,
                    "files": {
                        "gpt_weights": "GPT_weights_v4/yachiyo.ckpt",
                        "sovits_weights": "SoVITS_weights_v4/yachiyo.pth",
                        "ref_audio": "refs/yachiyo.wav",
                    },
                    "gpt_sovits": {
                        "ref_audio_text": "月見八千代です。",
                        "ref_audio_language": "ja",
                        "text_language": "zh",
                        "top_k": 9,
                    },
                }
            ),
            encoding="utf-8",
        )
        voice_archive = tmp_path / "route-e2e-voice.zip"
        with zipfile.ZipFile(voice_archive, "w") as archive:
            for file_path in voice_root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(voice_root))

        voice_import = await ui.import_tts_voice_archive_path(
            ui.TtsResourcePathRequest(path=str(voice_archive))
        )
        voice_save = await ui.update_settings(
            ui.SettingsUpdateRequest(changes=voice_import["draft_changes"])
        )
        tts_result = await ui.test_proactive_tts(
            ui.TtsTestRequest(text="Live2D 和 GPT-SoVITS 资源链路测试。")
        )

    assert voice_import["ok"] is True
    assert voice_save["ok"] is True
    assert config.tts.enabled is True
    assert config.tts.provider == "gpt-sovits"
    assert config.tts.gsv_base_url == gsv.url
    assert Path(config.tts.gsv_gpt_weights_path).is_file()
    assert Path(config.tts.gsv_sovits_weights_path).is_file()
    assert Path(config.tts.gsv_ref_audio_path).is_file()
    assert tts_result["ok"] is True
    assert tts_result["success"] is True
    assert tts_result["provider"] == "gpt-sovits"
    assert tts_result["spoken_text"] == "Live2D 和 GPT-SoVITS 资源链路测试。"

    weight_requests = [item for item in gsv.requests if item["method"] == "GET"]
    tts_requests = [item for item in gsv.requests if item["method"] == "POST" and item["path"] == "/tts"]
    assert [item["path"] for item in weight_requests] == ["/set_gpt_weights", "/set_sovits_weights"]
    assert weight_requests[0]["query"]["weights_path"] == config.tts.gsv_gpt_weights_path
    assert weight_requests[1]["query"]["weights_path"] == config.tts.gsv_sovits_weights_path
    assert len(tts_requests) == 1
    assert tts_requests[0]["body"]["text"] == "Live2D 和 GPT-SoVITS 资源链路测试。"
    assert tts_requests[0]["body"]["ref_audio_path"] == config.tts.gsv_ref_audio_path
    assert tts_requests[0]["body"]["prompt_text"] == "月見八千代です。"
    assert tts_requests[0]["body"]["top_k"] == 9


def test_live2d_zip_member_name_recovers_utf8_without_flag():
    original = "八千代辉夜姬/八千代辉夜姬.model3.json"
    garbled = original.encode("utf-8").decode("cp437")
    info = zipfile.ZipInfo(garbled)
    info.flag_bits = 0

    assert live2d_resources._decode_zip_member_name(info) == original
