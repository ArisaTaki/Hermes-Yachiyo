"""Main window API mode architecture tests."""

from __future__ import annotations

from dataclasses import dataclass

import apps.shell.config as config_mod
from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell.config import AppConfig
from apps.shell.main_api import MainWindowAPI


@dataclass
class _BridgeStatus:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8420
    state: str = "running"
    url: str = "http://127.0.0.1:8420"
    config_dirty: bool = False
    boot_config: dict | None = None
    drift_details: list[str] | None = None

    def to_dict(self):
        return {
            "enabled": self.enabled,
            "host": self.host,
            "port": self.port,
            "state": self.state,
            "url": self.url,
            "config_dirty": self.config_dirty,
            "boot_config": self.boot_config,
            "drift_details": self.drift_details or [],
        }

    def to_dashboard_dict(self):
        data = self.to_dict()
        data["running"] = self.state
        return data


@dataclass
class _IntegrationStatus:
    status: str = "not_configured"
    label: str = "⚪ 未配置"
    description: str = ""
    blockers: list[str] | None = None

    def to_dict(self):
        return {
            "status": self.status,
            "label": self.label,
            "description": self.description,
            "blockers": self.blockers or [],
        }


@dataclass
class _Snapshot:
    bridge: _BridgeStatus
    astrbot: _IntegrationStatus
    hapi: _IntegrationStatus


class _RuntimeStub:
    def __init__(self, store: ChatStore) -> None:
        self.state = AppState()
        self.chat_session = ChatSession(session_id="main-api")
        self.chat_session.attach_store(store, load_existing=False)
        self.task_runner = None

    def get_status(self):
        return {
            "version": "0.1.0",
            "running": True,
            "uptime_seconds": 12.3,
            "task_counts": {"pending": 1, "running": 0, "completed": 2},
            "hermes": {
                "install_status": "ready",
                "version": "1.0.0",
                "platform": "darwin",
                "command_exists": True,
                "readiness_level": "full_ready",
                "limited_tools": [],
                "doctor_issues_count": 0,
                "hermes_home": "~/.hermes",
            },
        }

    def is_hermes_ready(self):
        return True


def _fake_snapshot() -> _Snapshot:
    return _Snapshot(
        bridge=_BridgeStatus(),
        astrbot=_IntegrationStatus(),
        hapi=_IntegrationStatus(label="⚪ 未配置"),
    )


def test_dashboard_data_includes_chat_overview_and_modes(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    runtime.chat_session.add_user_message("来自 control center")
    try:
        monkeypatch.setattr("apps.shell.main_api.get_workspace_status", lambda: {"initialized": True, "workspace_path": "/tmp/ws", "created_at": "now"})
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        api = MainWindowAPI(runtime, AppConfig())
        data = api.get_dashboard_data()

        assert data["modes"]["current"] == "bubble"
        assert {item["id"] for item in data["modes"]["items"]} == {"bubble", "live2d"}
        assert data["chat"]["messages"][0]["content"] == "来自 control center"
        assert "recent_sessions" in data["chat"]
    finally:
        store.close()


def test_settings_data_exposes_mode_settings_summaries(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr("apps.shell.main_api.get_workspace_status", lambda: {"initialized": True, "workspace_path": "/tmp/ws", "created_at": "now", "dirs": {}})
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        model_dir = tmp_path / "models" / "hiyori"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "hiyori.model3.json").write_text("{}", encoding="utf-8")
        (model_dir / "hiyori.moc3").write_text("stub", encoding="utf-8")

        config = AppConfig()
        config.bubble_mode.summary_count = 2
        config.assistant.persona_prompt = "你是八千代。"
        config.assistant.user_address = "老师"
        config.live2d_mode.model_name = "hiyori"
        config.live2d_mode.model_path = str(model_dir)

        api = MainWindowAPI(runtime, config)
        data = api.get_settings_data()

        assert set(data["mode_settings"]) == {"bubble", "live2d"}
        assert data["assistant"]["persona_prompt"] == "你是八千代。"
        assert data["assistant"]["user_address"] == "老师"
        assert "摘要 2 条" in data["mode_settings"]["bubble"]["summary"]
        assert "hiyori" in data["mode_settings"]["live2d"]["summary"]
    finally:
        store.close()


def test_display_mode_change_schedules_mode_switch(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        config = AppConfig(display_mode="bubble")
        api = MainWindowAPI(runtime, config)
        result = api.update_settings({"display_mode": "live2d"})

        assert result["ok"] is True
        assert result["mode_switch_scheduled"] is True
        assert result["target_display_mode"] == "live2d"
        assert result["effects"]["has_restart_mode"] is True
        assert result["effects"]["has_restart_app"] is False
        assert config.display_mode == "live2d"
    finally:
        store.close()


def test_assistant_persona_prompt_updates_from_main_settings(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        config = AppConfig()
        api = MainWindowAPI(runtime, config)
        result = api.update_settings({"assistant.persona_prompt": "你是八千代。"})

        assert result["ok"] is True
        assert result["app_state"]["assistant"]["persona_prompt"] == "你是八千代。"
        assert config.assistant.persona_prompt == "你是八千代。"
    finally:
        store.close()


def test_assistant_user_address_updates_from_main_settings(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr("apps.shell.main_api.get_integration_snapshot", lambda config, boot: _fake_snapshot())

        config = AppConfig()
        api = MainWindowAPI(runtime, config)
        result = api.update_settings({"assistant.user_address": "老师"})

        assert result["ok"] is True
        assert result["app_state"]["assistant"]["user_address"] == "老师"
        assert config.assistant.user_address == "老师"
    finally:
        store.close()
