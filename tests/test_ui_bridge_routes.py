"""Electron UI bridge route tests."""

from __future__ import annotations

import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import apps.shell.live2d_resources as live2d_resources
import apps.shell.config as config_mod
from apps.bridge.routes import ui
from apps.shell.config import AppConfig


def _create_live2d_model_dir(root: Path, model_name: str = "demo") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{model_name}.model3.json").write_text("{}", encoding="utf-8")
    (root / f"{model_name}.moc3").write_text("stub", encoding="utf-8")
    return root


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
async def test_settings_operation_routes_use_main_api(monkeypatch):
    runtime = SimpleNamespace(config=SimpleNamespace())
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeMainWindowAPI:
        def __init__(self, received_runtime, received_config):
            assert received_runtime is runtime
            assert received_config is runtime.config

        def open_terminal_command(self, command):
            return {"success": True, "command": command}

        def recheck_hermes(self):
            return {"hermes": {"ready": True}}

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

        def get_uninstall_preview(self, scope, keep_config):
            return {"ok": True, "scope": scope, "keep_config": keep_config}

        def run_uninstall(self, scope, keep_config, confirm_text):
            return {"ok": True, "scope": scope, "keep_config": keep_config, "confirm_text": confirm_text}

    monkeypatch.setattr(ui, "MainWindowAPI", FakeMainWindowAPI)

    assert await ui.open_hermes_terminal_command(ui.TerminalCommandRequest(command="hermes doctor")) == {
        "success": True,
        "command": "hermes doctor",
    }
    assert await ui.recheck_hermes() == {"hermes": {"ready": True}}
    assert await ui.restart_bridge() == {"ok": True, "bridge": "restarted"}
    assert await ui.get_backup_status() == {"ok": True, "backups": []}
    assert await ui.create_backup(ui.BackupCreateRequest(overwrite_latest=True)) == {"ok": True, "overwrite_latest": True}
    assert await ui.restore_backup(ui.BackupPathRequest(backup_path="backup.zip")) == {"ok": True, "restore": "backup.zip"}
    assert await ui.delete_backup(ui.BackupPathRequest(backup_path="backup.zip")) == {"ok": True, "delete": "backup.zip"}
    assert await ui.open_backup_location(ui.BackupPathRequest(backup_path="backup.zip")) == {"ok": True, "open": "backup.zip"}
    assert await ui.get_uninstall_preview(scope="include_hermes", keep_config=False) == {
        "ok": True,
        "scope": "include_hermes",
        "keep_config": False,
    }
    assert await ui.run_uninstall(ui.UninstallRunRequest(scope="yachiyo_only", keep_config=True, confirm_text="UNINSTALL")) == {
        "ok": True,
        "scope": "yachiyo_only",
        "keep_config": True,
        "confirm_text": "UNINSTALL",
    }


@pytest.mark.asyncio
async def test_chat_routes_use_shared_chat_api(monkeypatch):
    runtime = SimpleNamespace()
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_messages(self, limit):
            return {"messages": [], "limit": limit}

        def send_message(self, text):
            return {"ok": True, "text": text}

        def get_session_info(self):
            return {"session_id": "session-1"}

        def clear_session(self):
            return {"ok": True}

        def delete_current_session(self):
            return {"ok": True, "deleted": True}

        def list_sessions(self, limit):
            return {"sessions": [], "limit": limit}

        def load_session(self, session_id):
            return {"ok": True, "session_id": session_id}

        def get_executor_info(self):
            return {"executor": "HermesExecutor", "available": True}

    monkeypatch.setattr(ui, "ChatAPI", FakeChatAPI)

    assert await ui.get_chat_messages(limit=12) == {"messages": [], "limit": 12}
    assert await ui.send_chat_message(ui.SendChatMessageRequest(text="hello")) == {
        "ok": True,
        "text": "hello",
    }
    assert await ui.get_chat_session() == {"session_id": "session-1"}
    assert await ui.clear_chat_session() == {"ok": True}
    assert await ui.delete_chat_session() == {"ok": True, "deleted": True}
    assert await ui.list_chat_sessions(limit=3) == {"sessions": [], "limit": 3}
    assert await ui.load_chat_session(ui.LoadChatSessionRequest(session_id="s2")) == {
        "ok": True,
        "session_id": "s2",
    }
    assert await ui.get_chat_executor() == {
        "executor": "HermesExecutor",
        "available": True,
    }


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
    }
    assert await ui.send_launcher_quick_message(ui.LauncherQuickMessageRequest(text="hi")) == {
        "ok": True,
        "text": "hi",
    }


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
    assert launcher["scale"] == 1.0
    assert launcher["mouse_follow_enabled"] is True
    assert launcher["resource"]["state"] == "not_configured"
    assert "GitHub Releases" in launcher["resource"]["help_text"]
    assert launcher["renderer"]["enabled"] is False
    assert launcher["renderer"]["model_url"] == ""


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
