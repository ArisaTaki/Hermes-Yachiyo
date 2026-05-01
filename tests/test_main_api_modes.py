"""Main window API mode architecture tests."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from types import SimpleNamespace

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
        assert {item["id"] for item in data["modes"]["items"]} == {"bubble", "live2d"}
        assert data["hermes"]["command_exists"] is True
        assert {item["id"] for item in data["hermes"]["configuration_actions"]} >= {
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

        assert set(data["mode_settings"]) == {"bubble", "live2d"}
        assert data["assistant"]["persona_prompt"] == "你是八千代。"
        assert data["assistant"]["user_address"] == "老师"
        assert {item["id"] for item in data["hermes"]["configuration_actions"]} >= {
            "setup",
            "model",
            "config-edit",
            "doctor",
        }
        assert "摘要 2 条" in data["mode_settings"]["bubble"]["summary"]
        assert "hiyori" in data["mode_settings"]["live2d"]["summary"]
    finally:
        store.close()


def test_hermes_connection_test_success_uses_oneshot(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    calls = []
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("/bin/hermes", False),
        )

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.test_hermes_connection()

        assert result["success"] is True
        assert result["output_preview"] == "OK"
        assert result["command"] == "/bin/hermes -z <connectivity-check>"
        assert result["connection_validation"]["verified"] is True
        assert calls[0][0][0:2] == ["/bin/hermes", "-z"]
        assert calls[0][1]["timeout"] == 45.0
        assert (tmp_path / "yachiyo-config" / "hermes_connection.json").exists()
    finally:
        store.close()


def test_hermes_connection_test_failure_redacts_secret(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("/bin/hermes", False),
        )
        monkeypatch.setattr(
            "apps.shell.main_api.subprocess.run",
            lambda *_args, **_kwargs: SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="api_key=sk-super-secret-token failed",
            ),
        )

        api = MainWindowAPI(runtime, AppConfig())
        result = api.test_hermes_connection()

        assert result["success"] is False
        assert result["connection_validation"]["verified"] is False
        assert "sk-super-secret-token" not in result["error"]
        assert "[redacted]" in result["error"]
    finally:
        store.close()


def test_hermes_connection_validation_survives_reload_when_config_unchanged(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        "model:\n"
        "  provider: deepseek\n"
        "  default: deepseek-v4-flash\n"
        "  base_url: https://api.deepseek.com/v1\n",
        encoding="utf-8",
    )
    env_path.write_text("DEEPSEEK_API_KEY=sk-test-secret\n", encoding="utf-8")
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    calls = []
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("/bin/hermes", False),
        )

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            if argv[1:3] == ["config", "path"]:
                return SimpleNamespace(returncode=0, stdout=f"{config_path}\n", stderr="")
            if argv[1:3] == ["config", "env-path"]:
                return SimpleNamespace(returncode=0, stdout=f"{env_path}\n", stderr="")
            if argv[1] == "-z":
                return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")
            raise AssertionError(argv)

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        test_result = api.test_hermes_connection()
        config_result = api.get_hermes_configuration()

        assert test_result["connection_validation"]["verified"] is True
        assert config_result["connection_validation"]["verified"] is True
        assert config_result["connection_validation"]["provider"] == "deepseek"
        assert config_result["connection_validation"]["model"] == "deepseek-v4-flash"
        assert any(call[1] == "-z" for call in calls)
    finally:
        store.close()


def test_hermes_image_connection_test_records_vision_preflight(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        "model:\n"
        "  provider: xiaomi\n"
        "  default: mimo-v2.5-pro\n"
        "  base_url: https://token-plan-cn.xiaomimimo.com/v1\n",
        encoding="utf-8",
    )
    env_path.write_text("XIAOMI_API_KEY=tp-test-secret\n", encoding="utf-8")
    launcher = tmp_path / "hermes"
    launcher.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    calls = []
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: (str(launcher), False),
        )

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        monkeypatch.setattr(
            api,
            "get_hermes_configuration",
            lambda: {
                "ok": True,
                "command_exists": True,
                "config_path": str(config_path),
                "env_path": str(env_path),
                "model": {
                    "provider": "xiaomi",
                    "default": "mimo-v2.5-pro",
                    "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                },
                "api_key": {"name": "XIAOMI_API_KEY", "configured": True},
                "image_input": {
                    "route": "vision_text",
                    "provider": "xiaomi",
                    "model": "mimo-v2.5-pro",
                    "requires_vision_pipeline": True,
                },
            },
        )
        result = api.test_hermes_image_connection()

        assert result["success"] is True
        assert result["image_connection_validation"]["verified"] is True
        assert calls[0][0][0] == sys.executable
        assert calls[0][1]["timeout"] == 90.0
        assert (tmp_path / "yachiyo-config" / "hermes_image_connection.json").exists()
    finally:
        store.close()


def test_hermes_image_connection_resolves_command_name_from_path(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        "model:\n"
        "  provider: xiaomi\n"
        "  default: mimo-v2.5-pro\n"
        "  base_url: https://token-plan-cn.xiaomimimo.com/v1\n",
        encoding="utf-8",
    )
    env_path.write_text("XIAOMI_API_KEY=tp-test-secret\n", encoding="utf-8")
    launcher = tmp_path / "hermes"
    launcher.write_text(f"#!{sys.executable}\n", encoding="utf-8")
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    calls = []
    try:
        monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path / "yachiyo-config")
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("hermes", False),
        )
        monkeypatch.setattr(
            "apps.shell.main_api.shutil.which",
            lambda name: str(launcher) if name == "hermes" else None,
        )

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="OK\n", stderr="")

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        monkeypatch.setattr(
            api,
            "get_hermes_configuration",
            lambda: {
                "ok": True,
                "command_exists": True,
                "config_path": str(config_path),
                "env_path": str(env_path),
                "model": {
                    "provider": "xiaomi",
                    "default": "mimo-v2.5-pro",
                    "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                },
                "api_key": {"name": "XIAOMI_API_KEY", "configured": True},
                "image_input": {
                    "route": "vision_text",
                    "provider": "xiaomi",
                    "model": "mimo-v2.5-pro",
                    "requires_vision_pipeline": True,
                },
            },
        )

        result = api.test_hermes_image_connection()

        assert result["success"] is True
        assert calls[0][0][0] == sys.executable
    finally:
        store.close()


def test_get_hermes_configuration_reads_model_and_key_status(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        "model:\n"
        "  provider: openai\n"
        "  default: gpt-4.1\n"
        "  base_url: https://api.openai.com/v1\n",
        encoding="utf-8",
    )
    env_path.write_text("OPENAI_API_KEY=sk-test-secret\n", encoding="utf-8")
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("/bin/hermes", False),
        )

        def fake_run(argv, **_kwargs):
            if argv[-1] == "path":
                return SimpleNamespace(returncode=0, stdout=f"{config_path}\n", stderr="")
            if argv[-1] == "env-path":
                return SimpleNamespace(returncode=0, stdout=f"{env_path}\n", stderr="")
            raise AssertionError(argv)

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.get_hermes_configuration()

        assert result["ok"] is True
        assert result["model"]["provider"] == "openai"
        assert result["model"]["default"] == "gpt-4.1"
        assert result["api_key"] == {
            "name": "OPENAI_API_KEY",
            "configured": True,
            "display": "已配置",
        }
        openrouter = next(item for item in result["provider_options"] if item["id"] == "openrouter")
        assert openrouter["api_key_configured"] is True
        assert "OPENAI_API_KEY" in openrouter["api_key_names"]
        assert "sk-test-secret" not in str(result)
    finally:
        store.close()


def test_update_hermes_configuration_uses_config_set_and_redacts_errors(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    calls = []
    try:
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("/bin/hermes", False),
        )

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            if argv[1:3] == ["config", "set"]:
                return SimpleNamespace(returncode=0, stdout="ok", stderr="")
            if argv[-1] == "path":
                return SimpleNamespace(
                    returncode=0,
                    stdout=f"{tmp_path / 'config.yaml'}\n",
                    stderr="",
                )
            if argv[-1] == "env-path":
                return SimpleNamespace(returncode=0, stdout=f"{tmp_path / '.env'}\n", stderr="")
            raise AssertionError(argv)

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.update_hermes_configuration(
            {
                "provider": "openai",
                "model": "gpt-4.1",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test-secret",
            }
        )

        assert result["ok"] is True
        assert [call[3] for call in calls if call[1:3] == ["config", "set"]] == [
            "model.provider",
            "model.default",
            "model.base_url",
            "OPENAI_API_KEY",
        ]
        assert "sk-test-secret" not in result["message"]
    finally:
        store.close()


def test_update_hermes_configuration_writes_vision_chain_settings(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    calls = []
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"
    try:
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("/bin/hermes", False),
        )

        def fake_run(argv, **_kwargs):
            calls.append(argv)
            if argv[1:3] == ["config", "set"]:
                return SimpleNamespace(returncode=0, stdout="ok", stderr="")
            if argv[-1] == "path":
                return SimpleNamespace(returncode=0, stdout=f"{config_path}\n", stderr="")
            if argv[-1] == "env-path":
                return SimpleNamespace(returncode=0, stdout=f"{env_path}\n", stderr="")
            raise AssertionError(argv)

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.update_hermes_configuration(
            {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "image_input_mode": "text",
                "vision_provider": "xiaomi",
                "vision_model": "mimo-v2.5",
                "vision_base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "vision_api_key": "tp-secret",
            }
        )

        assert result["ok"] is True
        set_calls = [call for call in calls if call[1:3] == ["config", "set"]]
        assert [call[3] for call in set_calls] == [
            "model.provider",
            "model.default",
            "model.base_url",
            "agent.image_input_mode",
            "auxiliary.vision.provider",
            "auxiliary.vision.model",
            "auxiliary.vision.base_url",
            "XIAOMI_API_KEY",
        ]
        assert set_calls[-1][4] == "tp-secret"
    finally:
        store.close()


def test_open_terminal_command_rejects_unsupported_command(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        api = MainWindowAPI(runtime, AppConfig())
        result = api.open_terminal_command("rm -rf /tmp/hermes-yachiyo")

        assert result["success"] is False
        assert result["unsupported"] is True
    finally:
        store.close()


def test_run_hermes_diagnostic_command_returns_redacted_output(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setattr(
            "apps.shell.main_api.locate_hermes_binary",
            lambda: ("/bin/hermes", False),
        )
        monkeypatch.setattr(
            "apps.shell.main_api._diagnostic_cache_path",
            lambda: tmp_path / "hermes_diagnostics.json",
        )

        def fake_run(argv, **kwargs):
            if argv == ["/bin/hermes", "auth", "list"]:
                assert kwargs["timeout"] == 60.0
                return SimpleNamespace(
                    returncode=0,
                    stdout="OPENAI_API_KEY=sk-super-secret-token\n",
                    stderr="",
                )
            if argv == ["/bin/hermes", "config", "path"]:
                return SimpleNamespace(returncode=0, stdout=str(tmp_path / "config.yaml"), stderr="")
            if argv == ["/bin/hermes", "config", "env-path"]:
                return SimpleNamespace(returncode=0, stdout=str(tmp_path / ".env"), stderr="")
            raise AssertionError(f"unexpected argv: {argv}")

        monkeypatch.setattr("apps.shell.main_api.subprocess.run", fake_run)

        api = MainWindowAPI(runtime, AppConfig())
        result = api.run_hermes_diagnostic_command("hermes auth list")

        assert result["success"] is True
        assert result["command"] == "hermes auth list"
        assert "sk-super-secret-token" not in result["output"]
        assert "[redacted]" in result["output"]
        assert result["diagnostic_cache"]["commands"]["auth-list"]["success"] is True
    finally:
        store.close()


def test_run_hermes_diagnostic_command_rejects_non_diagnostic_command(tmp_path):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        api = MainWindowAPI(runtime, AppConfig())
        result = api.run_hermes_diagnostic_command("hermes setup")

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
        first = api.open_terminal_command("hermes doctor")
        second = api.open_terminal_command("hermes setup")

        assert first["success"] is True
        assert second["success"] is False
        assert second["throttled"] is True
        assert calls == ["hermes doctor"]
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


def test_restart_bridge_in_desktop_backend_defers_to_electron(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    runtime = _RuntimeStub(store)
    try:
        monkeypatch.setenv("HERMES_YACHIYO_DESKTOP_BACKEND", "1")
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
