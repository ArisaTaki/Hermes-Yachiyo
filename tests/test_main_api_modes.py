"""Main window API mode architecture tests."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from types import SimpleNamespace

import apps.shell.config as config_mod
import apps.shell.main_api as main_api_mod
from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell.config import AppConfig
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.main_api import MainWindowAPI
from apps.shell.model_profiles import ModelProfileService


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
        self.executor_refresh_count = 0

    def get_status(self):
        return {
            "version": "0.4.0",
            "running": True,
            "uptime_seconds": 12.3,
            "task_counts": {"pending": 1, "running": 0, "completed": 2},
            "native_agent": {"ready": True, "limited_tools": []},
            "native_agent_ready": True,
        }

    def is_native_agent_ready(self):
        return True

    def native_agent_readiness(self):
        from apps.shell.agent_runtime import get_native_agent_readiness

        return get_native_agent_readiness()

    def refresh_task_runner_executor(self):
        self.executor_refresh_count += 1
        return {
            "updated": True,
            "executor": "NativeAgentExecutor",
            "previous_executor": None,
            "reason": "native_agent_ready",
        }


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
        monkeypatch.setattr(
            "apps.shell.main_api.get_workspace_status",
            lambda: {"initialized": True, "workspace_path": "/tmp/ws", "created_at": "now"},
        )
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        api = MainWindowAPI(runtime, AppConfig())
        data = api.get_dashboard_data()

        assert data["modes"]["current"] == "bubble"
        assert {item["id"] for item in data["modes"]["items"]} == {"none", "bubble", "live2d"}
        assert "hermes" not in data
        assert data["native_agent"]["command_exists"] is True
        assert {item["id"] for item in data["native_agent"]["configuration_actions"]} >= {
            "setup",
            "model",
            "doctor",
        }
        assert data["chat"]["messages"][0]["content"] == "来自 control center"
        assert "recent_sessions" in data["chat"]
    finally:
        store.close()


def test_settings_data_exposes_mode_settings_summaries(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(
            "apps.shell.main_api.get_workspace_status",
            lambda: {
                "initialized": True,
                "workspace_path": "/tmp/ws",
                "created_at": "now",
                "dirs": {},
            },
        )
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

        assert "hermes" not in data
        assert set(data["mode_settings"]) == {"bubble", "live2d"}
        assert data["assistant"]["persona_prompt"] == "你是八千代。"
        assert data["assistant"]["user_address"] == "老师"
        assert {item["id"] for item in data["native_agent"]["configuration_actions"]} >= {
            "setup",
            "model",
            "config-edit",
            "doctor",
        }
        assert "摘要 2 条" in data["mode_settings"]["bubble"]["summary"]
        assert "hiyori" in data["mode_settings"]["live2d"]["summary"]
    finally:
        store.close()


def _install_profile_service(monkeypatch, profile_service):
    monkeypatch.setattr("apps.shell.main_api.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.model_profiles.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.native_capabilities.get_model_profile_service", lambda: profile_service)


def _available_chat_profile(profile_service, *, name="Main", provider="openai", model="gpt-4.1-mini", api_key="sk-test-secret"):
    profile = profile_service.create_profile(
        {
            "name": name,
            "capability": "chat",
            "provider": provider,
            "base_url": "https://api.openai.com/v1",
            "model": model,
            "api_key": api_key,
        }
    )
    profile_service._record_test_result(profile["profile_id"], ok=True, message="OK")
    profile_service.set_defaults({"chat": profile["profile_id"]})
    return profile_service.get_profile(profile["profile_id"])


def test_native_connection_test_uses_default_chat_profile(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        profile = _available_chat_profile(profile_service)
        _install_profile_service(monkeypatch, profile_service)
        monkeypatch.setattr(
            profile_service,
            "test_profile",
            lambda profile_id: {
                "ok": True,
                "success": True,
                "message": "OK",
                "profile": profile_service.get_profile(profile_id),
            },
        )

        api = MainWindowAPI(runtime, AppConfig())
        result = api.test_native_connection()

        assert result["success"] is True
        assert result["command"] == "native:model-profile:test:chat"
        assert result["profile"]["profile_id"] == profile["profile_id"]
        assert result["connection_validation"]["verified"] is True
        assert runtime.executor_refresh_count == 1
        assert (tmp_path / "yachiyo-config" / "native_connection.json").exists()
        assert "sk-test-secret" not in str(result)
    finally:
        profile_service.close()
        store.close()


def test_native_connection_missing_default_returns_structured_error(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        _install_profile_service(monkeypatch, profile_service)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.test_native_connection()

        assert result["success"] is False
        assert result["code"] == "native_agent_not_ready"
        assert result["reason"] == "model_profile_required"
        assert "Hermes" not in result["error"]
    finally:
        profile_service.close()
        store.close()


def test_native_image_connection_uses_default_vision_profile(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        _available_chat_profile(profile_service, provider="deepseek", model="deepseek-chat")
        vision = profile_service.create_profile(
            {
                "name": "Vision",
                "capability": "vision",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4.1-mini",
                "api_key": "sk-vision-secret",
                "options": {"remote_model": {"id": "gpt-4.1-mini", "input_modalities": ["text", "image"]}},
            }
        )
        profile_service._record_test_result(vision["profile_id"], ok=True, message="OK")
        profile_service.set_defaults({"vision": vision["profile_id"]})
        _install_profile_service(monkeypatch, profile_service)
        monkeypatch.setattr("apps.shell.native_capabilities.lookup_model_supports_vision", lambda *_args: False)
        monkeypatch.setattr(
            profile_service,
            "test_profile",
            lambda profile_id: {
                "ok": True,
                "success": True,
                "message": "OK",
                "profile": profile_service.get_profile(profile_id),
            },
        )

        api = MainWindowAPI(runtime, AppConfig())
        result = api.test_native_image_connection()

        assert result["success"] is True
        assert result["image_input"]["route"] == "vision_text"
        assert result["image_connection_validation"]["verified"] is True
        assert "sk-vision-secret" not in str(result)
    finally:
        profile_service.close()
        store.close()


def test_get_native_configuration_reads_model_profiles_without_secret(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        _available_chat_profile(profile_service, provider="openrouter", model="openai/gpt-4.1-mini")
        _install_profile_service(monkeypatch, profile_service)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.get_native_configuration()

        assert result["ok"] is True
        assert result["command_exists"] is True
        assert result["model"]["provider"] == "openrouter"
        assert result["model"]["default"] == "openai/gpt-4.1-mini"
        assert result["api_key"]["configured"] is True
        assert "sk-test-secret" not in str(result)
    finally:
        profile_service.close()
        store.close()


def test_update_native_configuration_creates_default_profile_without_plaintext_sqlite(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_db = tmp_path / "profiles.db"
    profile_service = ModelProfileService(
        db_path=profile_db,
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        _install_profile_service(monkeypatch, profile_service)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.update_native_configuration(
            {
                "provider": "openai",
                "model": "gpt-4.1",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test-secret",
            }
        )

        assert result["ok"] is True
        profile_id = profile_service.get_defaults()["chat"]
        private_profile = profile_service.get_profile_private(profile_id)
        assert private_profile["api_key"] == "sk-test-secret"
        row = profile_service._conn.execute(
            "SELECT api_key, credential_ref FROM model_profiles WHERE profile_id=?",
            (profile_id,),
        ).fetchone()
        assert row["api_key"] == ""
        assert row["credential_ref"] == f"model_profile:{profile_id}:api_key"
        assert "sk-test-secret" not in str(result)
        assert runtime.executor_refresh_count == 1
    finally:
        profile_service.close()
        store.close()


def test_update_native_configuration_sets_existing_profile_defaults(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        profile = _available_chat_profile(profile_service)
        profile_service.set_defaults({"chat": ""})
        _install_profile_service(monkeypatch, profile_service)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.update_native_configuration({"chat_profile_id": profile["profile_id"]})

        assert result["ok"] is True
        assert profile_service.get_defaults()["chat"] == profile["profile_id"]
        assert runtime.executor_refresh_count == 1
    finally:
        profile_service.close()
        store.close()


def test_update_native_configuration_writes_vision_profile_and_image_mode(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        _available_chat_profile(profile_service, provider="deepseek", model="deepseek-chat")
        _install_profile_service(monkeypatch, profile_service)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.update_native_configuration(
            {
                "image_input_mode": "vision",
                "vision_provider": "openai",
                "vision_model": "gpt-4.1-mini",
                "vision_base_url": "https://api.openai.com/v1",
                "vision_api_key": "sk-vision-secret",
            }
        )

        assert result["ok"] is True
        vision_id = profile_service.get_defaults()["vision"]
        private_vision = profile_service.get_profile_private(vision_id)
        assert private_vision["api_key"] == "sk-vision-secret"
        config_text = (tmp_path / "yachiyo-config" / "native_tool_config.json").read_text(encoding="utf-8")
        assert '"agent.image_input_mode": "text"' in config_text
        assert "sk-vision-secret" not in str(result)
    finally:
        profile_service.close()
        store.close()


def test_tool_config_projection_does_not_expose_env_values(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")

        api = MainWindowAPI(runtime, AppConfig())
        update = api.update_native_tool_config(
            "web",
            {"web.backend": "exa", "FIRECRAWL_API_KEY": "fc-secret"},
        )
        result = api.get_native_tool_config()
        web = next(tool for tool in result["tools"] if tool["id"] == "web")
        backend = next(field for field in web["fields"] if field["key"] == "web.backend")
        firecrawl_key = next(field for field in web["fields"] if field["key"] == "FIRECRAWL_API_KEY")

        assert update["ok"] is True
        assert "hermes_toolsets" not in result
        assert any(toolset["id"] == "web" for toolset in result["native_toolsets"])
        assert backend["value"] == "exa"
        assert firecrawl_key["configured"] is True
        assert firecrawl_key["value"] == ""
        assert result["tool_config_state"]["env_configured"]["FIRECRAWL_API_KEY"] is True
        assert "fc-secret" not in str(update)
        assert "fc-secret" not in str(result)
        assert "fc-secret" not in (tmp_path / "yachiyo-config" / "native_tool_config.json").read_text(encoding="utf-8")
    finally:
        store.close()


def test_update_native_tool_config_rejects_unknown_image_provider(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        api = MainWindowAPI(runtime, AppConfig())
        result = api.update_native_tool_config(
            "image_gen",
            {"image_gen.provider": "minimax-image", "image_gen.model": "image-01"},
        )

        assert result["ok"] is False
        assert result["field"] == "image_gen.provider"
        assert not (tmp_path / "yachiyo-config" / "native_tool_config.json").exists()
    finally:
        store.close()


def test_test_native_tool_config_runs_native_static_checks(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        api = MainWindowAPI(runtime, AppConfig())
        api.update_native_tool_config("web", {"web.backend": "exa", "EXA_API_KEY": "exa-secret"})

        result = api.test_native_tool_config("web")

        assert result["ok"] is True
        assert result["status"] == "warn"
        assert any(check["label"] == "Exa API Key" and check["status"] == "pass" for check in result["checks"])
        assert any(check["label"] == "Native ToolBroker" and check["status"] == "warn" for check in result["checks"])
        assert "exa-secret" not in str(result)
    finally:
        store.close()


def test_check_native_agent_update_reports_no_external_update(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        api = MainWindowAPI(runtime, AppConfig())
        result = api.check_native_agent_update()

        assert result["ok"] is True
        assert result["update_available"] is False
        assert result["behind_commits"] == 0
        assert "oha-yachiyo" in result["summary"]
    finally:
        store.close()


def test_update_native_agent_is_unsupported_external_kernel_endpoint(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        api = MainWindowAPI(runtime, AppConfig())
        result = api.update_native_agent(full_backup=True)

        assert result["ok"] is False
        assert result["unsupported"] is True
        assert result["code"] == "external_execution_kernel_removed"
    finally:
        store.close()


def test_launch_browser_cdp_writes_native_config_url(tmp_path, monkeypatch):
    class _Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        monkeypatch.setattr("apps.shell.main_api.socket.create_connection", lambda *_args, **_kwargs: _Socket())

        api = MainWindowAPI(runtime, AppConfig())
        result = api.launch_browser_cdp()

        assert result["ok"] is True
        assert result["url"] == "http://127.0.0.1:9222"
        config_text = (tmp_path / "yachiyo-config" / "native_tool_config.json").read_text(encoding="utf-8")
        assert '"browser.cdp_url": "http://127.0.0.1:9222"' in config_text
    finally:
        store.close()


def test_run_native_diagnostic_command_returns_native_output_and_cache(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    profile_service = ModelProfileService(
        db_path=tmp_path / "profiles.db",
        workspace_dir=tmp_path / "profiles",
        credential_store=MemoryCredentialStore(),
    )
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        _available_chat_profile(profile_service)
        _install_profile_service(monkeypatch, profile_service)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.run_native_diagnostic_command("native auth list")

        assert result["success"] is True
        assert result["command"] == "native auth list"
        assert "model_profiles" in result["output"]
        assert "sk-test-secret" not in result["output"]
        assert result["diagnostic_cache"]["commands"]["auth-list"]["success"] is True
    finally:
        profile_service.close()
        store.close()


def test_open_terminal_command_rejects_unsupported_command(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        api = MainWindowAPI(runtime, AppConfig())
        result = api.open_terminal_command("rm -rf /tmp/oha-yachiyo")

        assert result["success"] is False
        assert result["unsupported"] is True
    finally:
        store.close()


def test_run_native_diagnostic_command_rejects_non_diagnostic_command(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        api = MainWindowAPI(runtime, AppConfig())
        result = api.run_native_diagnostic_command("native setup")

        assert result["success"] is False
        assert result["unsupported"] is True
    finally:
        store.close()


def test_open_terminal_command_throttles_rapid_requests(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    calls = []
    try:
        monkeypatch.setattr("apps.shell.main_api._LAST_TERMINAL_COMMAND_AT", 0.0)
        monkeypatch.setattr(
            "apps.shell.terminal.open_terminal_command",
            lambda command: calls.append(command) or (True, None),
        )

        api = MainWindowAPI(runtime, AppConfig())
        command = 'echo "Oha-Yachiyo GPT-SoVITS 服务启动"; cd /tmp && python api_v2.py'
        first = api.open_terminal_command(command)
        second = api.open_terminal_command(command)

        assert first["success"] is True
        assert second["success"] is False
        assert second["throttled"] is True
        assert calls == [command]
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

        live2d_dir = tmp_path / "live2d" / "demo"
        live2d_dir.mkdir(parents=True)
        (live2d_dir / "demo.model3.json").write_text("{}", encoding="utf-8")
        (live2d_dir / "demo.moc3").write_text("stub", encoding="utf-8")
        config = AppConfig(display_mode="bubble")
        config.live2d_mode.model_path = str(live2d_dir)
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


def test_display_mode_change_can_disable_persistent_mode(tmp_path, monkeypatch):
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
        result = api.update_settings({"display_mode": "none"})

        assert result["ok"] is True
        assert result["mode_switch_scheduled"] is True
        assert result["target_display_mode"] == "none"
        assert config.display_mode == "none"
    finally:
        store.close()


def test_display_mode_change_rejects_live2d_without_resources(tmp_path, monkeypatch):
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
        config.live2d_mode.model_path = str(tmp_path / "missing-live2d-model")
        api = MainWindowAPI(runtime, config)
        result = api.update_settings({"display_mode": "live2d"})

        assert result["ok"] is False
        assert "Live2D 资源未就绪" in result["error"]
        assert config.display_mode == "bubble"
    finally:
        store.close()


def test_live2d_resource_save_can_activate_display_mode(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        live2d_dir = tmp_path / "live2d" / "demo"
        live2d_dir.mkdir(parents=True)
        (live2d_dir / "demo.model3.json").write_text("{}", encoding="utf-8")
        (live2d_dir / "demo.moc3").write_text("stub", encoding="utf-8")
        config = AppConfig(display_mode="bubble")
        api = MainWindowAPI(runtime, config)

        result = api.update_settings({
            "live2d_mode.model_path": str(live2d_dir),
            "display_mode": "live2d",
        })

        assert result["ok"] is True
        assert result["target_display_mode"] == "live2d"
        assert config.live2d_mode.model_path == str(live2d_dir)
        assert config.display_mode == "live2d"
    finally:
        store.close()


def test_restart_bridge_in_desktop_backend_defers_to_electron(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setenv("OHA_YACHIYO_DESKTOP_BACKEND", "1")
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        api = MainWindowAPI(runtime, AppConfig())
        result = api.restart_bridge()

        assert result["ok"] is True
        assert result["desktop_restart_backend_required"] is True
        assert result["bridge_url"] == "http://127.0.0.1:8420"
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
        monkeypatch.setattr(
            "apps.shell.main_api.get_integration_snapshot",
            lambda config, boot: _fake_snapshot(),
        )

        config = AppConfig()
        api = MainWindowAPI(runtime, config)
        result = api.update_settings({"assistant.user_address": "老师"})

        assert result["ok"] is True
        assert result["app_state"]["assistant"]["user_address"] == "老师"
        assert config.assistant.user_address == "老师"
    finally:
        store.close()
