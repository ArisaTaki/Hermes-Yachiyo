"""Mode settings model and update behavior tests."""

from __future__ import annotations

import json

import apps.shell.config as config_mod
from apps.shell.config import AppConfig, load_config, save_config
from apps.shell.mode_settings import (
    apply_settings_changes,
    serialize_mode_settings,
    serialize_mode_window_data,
)


def test_app_config_has_separate_mode_models():
    config = AppConfig()

    assert config.window_mode.width > 0
    assert config.bubble_mode.summary_count == 3
    assert config.live2d_mode.idle_motion_group == "Idle"
    assert config.live2d_mode.scale == 1.0
    assert config.live2d_mode.show_on_all_spaces is True
    assert config.live2d is config.live2d_mode


def test_apply_settings_changes_updates_bubble_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(
        config,
        {
            "bubble_mode.summary_count": 2,
            "bubble_mode.default_display": "recent_reply",
            "bubble_mode.opacity": 0.8,
        },
    )

    assert result["ok"] is True
    assert config.bubble_mode.summary_count == 2
    assert config.bubble_mode.default_display == "recent_reply"
    assert config.bubble_mode.opacity == 0.8
    assert result["mode_settings"]["bubble"]["config"]["summary_count"] == 2


def test_apply_settings_changes_rejects_invalid_single_field(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"bubble_mode.summary_count": 8})

    assert result["ok"] is False
    assert result["applied"] == {}
    assert config.bubble_mode.summary_count == 3
    assert "summary_count" in result["error"]


def test_apply_settings_changes_supports_legacy_live2d_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(
        config,
        {
            "live2d.model_name": "hiyori",
            "live2d.window_on_top": False,
            "live2d.scale": 1.25,
        },
    )

    assert result["ok"] is True
    assert config.live2d_mode.model_name == "hiyori"
    assert config.live2d_mode.window_on_top is False
    assert config.live2d_mode.scale == 1.25


def test_serialize_mode_settings_returns_separate_sections():
    config = AppConfig()

    payload = serialize_mode_settings(config)

    assert set(payload) == {"bubble", "live2d"}
    assert "摘要" in payload["bubble"]["summary"]
    assert "未配置模型" in payload["live2d"]["summary"]


def test_serialize_mode_window_data_includes_common_and_part():
    config = AppConfig(display_mode="live2d")
    config.live2d_mode.scale = 1.2

    payload = serialize_mode_window_data(config, "live2d")

    assert payload["common"]["display_mode"] == "live2d"
    assert payload["common"]["bridge_host"] == "127.0.0.1"
    assert payload["settings"]["config"]["scale"] == 1.2
    assert payload["settings"]["config"]["show_on_all_spaces"] is True


def test_load_config_reads_legacy_live2d_block(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps(
            {
                "display_mode": "bubble",
                "bubble_mode": {"summary_count": 1},
                "live2d": {
                    "model_name": "legacy-model",
                    "window_on_top": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.display_mode == "bubble"
    assert config.bubble_mode.summary_count == 1
    assert config.live2d_mode.model_name == "legacy-model"
    assert config.live2d_mode.window_on_top is False


def test_load_config_migrates_legacy_window_display_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps({"display_mode": "window"}, ensure_ascii=False),
        encoding="utf-8",
    )

    config = load_config()

    assert config.display_mode == "bubble"


def test_save_config_persists_mode_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()
    config.window_mode.recent_messages_limit = 5
    config.bubble_mode.summary_count = 2
    config.live2d_mode.model_name = "hiyori"
    config.live2d_mode.scale = 1.4
    config.live2d_mode.show_on_all_spaces = False

    save_config(config)
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))

    assert data["window_mode"]["recent_messages_limit"] == 5
    assert data["bubble_mode"]["summary_count"] == 2
    assert data["live2d_mode"]["model_name"] == "hiyori"
    assert data["live2d_mode"]["scale"] == 1.4
    assert data["live2d_mode"]["show_on_all_spaces"] is False
