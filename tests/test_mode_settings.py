"""Mode settings model and update behavior tests."""

from __future__ import annotations

import json
from pathlib import Path

import apps.shell.config as config_mod
from apps.shell.assets import (
    DEFAULT_BUBBLE_AVATAR_PATH,
    LEGACY_BUNDLED_LIVE2D_MODEL_DIR,
    LIVE2D_RELEASES_URL,
)
from apps.shell.config import AppConfig, ModelState, load_config, save_config
from apps.shell.mode_settings import (
    apply_settings_changes,
    build_display_settings,
    serialize_mode_settings,
    serialize_mode_window_data,
)


def _create_live2d_model_dir(root: Path, model_name: str = "demo") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{model_name}.model3.json").write_text("{}", encoding="utf-8")
    (root / f"{model_name}.moc3").write_text("stub", encoding="utf-8")
    return root


def _patch_no_live2d_assets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config_mod, "find_default_live2d_model_dir", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(config_mod, "get_user_live2d_assets_dir", lambda: tmp_path / "assets" / "live2d")


def test_app_config_has_separate_mode_models(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config = AppConfig()

    assert config.window_mode.width > 0
    assert config.bubble_mode.summary_count == 3
    assert config.bubble_mode.avatar_path == str(DEFAULT_BUBBLE_AVATAR_PATH)
    assert config.bubble_mode.position_x_percent == 1.0
    assert config.bubble_mode.position_y_percent == 1.0
    assert config.bubble_mode.edge_snap is True
    assert config.bubble_mode.proactive_enabled is False
    assert config.bubble_mode.proactive_trigger_probability == 0.6
    assert config.live2d_mode.idle_motion_group == "Idle"
    assert config.live2d_mode.position_anchor == "right_bottom"
    assert config.live2d_mode.position_x == 0
    assert config.live2d_mode.position_y == 0
    assert config.live2d_mode.scale == 0.6
    assert config.live2d_mode.show_on_all_spaces is True
    assert config.live2d_mode.model_name == ""
    assert config.live2d_mode.model_path == ""
    assert config.live2d_mode.mouse_follow_enabled is True
    assert config.live2d_mode.proactive_enabled is False
    assert config.live2d_mode.proactive_trigger_probability == 0.6
    assert config.live2d_mode.validate() == ModelState.NOT_CONFIGURED
    assert config.live2d is config.live2d_mode
    assert config.assistant.persona_prompt == config_mod.DEFAULT_ASSISTANT_PERSONA_PROMPT
    assert config.assistant.user_address == config_mod.DEFAULT_ASSISTANT_USER_ADDRESS
    assert "<Role>Hermes-Yachiyo Agent</Role>" in config.assistant.persona_prompt
    assert "月见八千代" in config.assistant.persona_prompt
    assert "括号动作示例" in config.assistant.persona_prompt
    assert config.assistant.user_address == "彩叶"
    assert config.tts.enabled is False
    assert config.tts.provider == "none"
    assert config.tts.endpoint == ""
    assert config.tts.command == ""
    assert config.tts.voice == ""
    assert config.tts.timeout_seconds == 180
    assert config.tts.max_chars == 80
    assert config.tts.trigger_probability == 0.6
    assert config.tts.notification_prompt == config_mod.DEFAULT_TTS_NOTIFICATION_PROMPT
    assert config.tts.gsv_base_url == "http://127.0.0.1:9880"
    assert config.tts.gsv_service_workdir == ""
    assert config.tts.gsv_service_command == "python api_v2.py -a 127.0.0.1 -p 9880"
    assert config.tts.gsv_ref_audio_language == "ja"
    assert config.tts.gsv_text_language == "zh"
    assert config.tts.gsv_top_k == 15
    assert config.tts.gsv_media_type == "wav"


def test_legacy_live2d_default_position_migrates_to_right_bottom(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        json.dumps({"live2d_mode": {"position_x": 48, "position_y": 48, "scale": 1.0}}),
        encoding="utf-8",
    )

    config = load_config()

    assert config.live2d_mode.position_anchor == "right_bottom"
    assert config.live2d_mode.position_x == 0
    assert config.live2d_mode.position_y == 0
    assert config.live2d_mode.scale == 0.6


def test_existing_live2d_position_without_anchor_stays_custom(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        json.dumps({"live2d_mode": {"position_x": 80, "position_y": 96, "scale": 1.0}}),
        encoding="utf-8",
    )

    config = load_config()

    assert config.live2d_mode.position_anchor == "custom"
    assert config.live2d_mode.position_x == 80
    assert config.live2d_mode.position_y == 96
    assert config.live2d_mode.scale == 1.0


def test_previous_live2d_default_anchor_migrates_to_right_bottom(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "live2d_mode": {
                    "position_anchor": "left_bottom",
                    "position_x": 0,
                    "position_y": 0,
                    "scale": 0.5,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.live2d_mode.position_anchor == "right_bottom"
    assert config.live2d_mode.position_x == 0
    assert config.live2d_mode.position_y == 0
    assert config.live2d_mode.scale == 0.6


def test_auto_saved_live2d_left_default_migrates_to_right_bottom(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "live2d_mode": {
                    "position_anchor": "custom",
                    "position_x": 0,
                    "position_y": 269,
                    "scale": 0.72,
                    "width": 420,
                    "height": 680,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.live2d_mode.position_anchor == "right_bottom"
    assert config.live2d_mode.position_x == 0
    assert config.live2d_mode.position_y == 0
    assert config.live2d_mode.scale == 0.6


def test_live2d_auto_discovers_user_assets(monkeypatch, tmp_path):
    user_root = tmp_path / "user-assets" / "live2d"
    model_dir = _create_live2d_model_dir(user_root / "yachiyo")
    monkeypatch.setattr(config_mod, "get_user_live2d_assets_dir", lambda: user_root)
    monkeypatch.setattr(
        config_mod,
        "find_default_live2d_model_dir",
        lambda *_args, **_kwargs: user_root,
    )

    config = AppConfig()
    resource = config.live2d_mode.resource_info()

    assert resource.state == ModelState.PATH_VALID
    assert resource.source == "auto_discovered"
    assert resource.effective_model_path == str(model_dir)
    assert resource.default_assets_root_display.endswith("user-assets/live2d")


def test_live2d_model_summary_reads_expression_and_motion_metadata(monkeypatch, tmp_path):
    user_root = tmp_path / "user-assets" / "live2d"
    model_dir = _create_live2d_model_dir(user_root / "yachiyo")
    (model_dir / "demo.model3.json").write_text(
        json.dumps(
            {
                "FileReferences": {
                    "Expressions": [
                        {"Name": "Happy", "File": "expressions/happy.exp3.json"},
                    ],
                    "Motions": {
                        "Idle": [
                            {"File": "motions/idle.motion3.json"},
                            {"File": "motions/idle2.motion3.json", "Sound": "sounds/idle.wav"},
                        ],
                        "TapBody": [{"File": "motions/tap.motion3.json"}],
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "get_user_live2d_assets_dir", lambda: user_root)
    monkeypatch.setattr(config_mod, "find_default_live2d_model_dir", lambda *_args, **_kwargs: model_dir)

    config = AppConfig()
    payload = serialize_mode_window_data(config, "live2d")
    summary = payload["settings"]["config"]["summary"]

    assert summary["expressions"] == [
        {"name": "Happy", "file": "expressions/happy.exp3.json"}
    ]
    assert len(summary["motion_groups"]["Idle"]) == 2
    assert summary["motion_groups"]["Idle"][1]["has_sound"] is True
    assert summary["motion_groups"]["TapBody"][0]["display_name"] == "tap.motion3"


def test_live2d_model_summary_discovers_sidecar_expressions_and_motions(monkeypatch, tmp_path):
    user_root = tmp_path / "user-assets" / "live2d"
    model_dir = _create_live2d_model_dir(user_root / "yachiyo")
    (model_dir / "demo.model3.json").write_text(
        json.dumps({"FileReferences": {"Moc": "demo.moc3", "Textures": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (model_dir / "笑咪咪.exp3.json").write_text("{}", encoding="utf-8")
    motion_dir = model_dir / "Idle"
    motion_dir.mkdir()
    (motion_dir / "idle.motion3.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config_mod, "get_user_live2d_assets_dir", lambda: user_root)
    monkeypatch.setattr(config_mod, "find_default_live2d_model_dir", lambda *_args, **_kwargs: model_dir)

    config = AppConfig()
    payload = serialize_mode_window_data(config, "live2d")
    summary = payload["settings"]["config"]["summary"]

    assert summary["expressions"] == [{"name": "笑咪咪", "file": "笑咪咪.exp3.json"}]
    assert summary["motion_groups"]["Idle"][0]["file"] == "Idle/idle.motion3.json"


def test_apply_settings_changes_updates_bubble_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(
        config,
        {
            "bubble_mode.summary_count": 2,
            "bubble_mode.default_display": "recent_reply",
            "bubble_mode.position_x_percent": 0.75,
            "bubble_mode.position_y_percent": 1.0,
            "bubble_mode.opacity": 0.8,
            "bubble_mode.edge_snap": False,
            "bubble_mode.proactive_enabled": True,
            "bubble_mode.proactive_desktop_watch_enabled": True,
            "bubble_mode.proactive_interval_seconds": 600,
            "bubble_mode.proactive_trigger_probability": 0.45,
            "assistant.persona_prompt": "你是八千代。",
            "assistant.user_address": "老师",
            "tts.provider": "command",
            "tts.command": "say {text}",
            "tts.voice": "kyoko",
            "tts.timeout_seconds": 10,
            "tts.max_chars": 60,
            "tts.trigger_probability": 0.35,
            "tts.notification_prompt": "只说一句提醒。",
            "tts.gsv_base_url": "http://host.docker.internal:9880",
            "tts.gsv_service_workdir": "/apps/GPT-SoVITS",
            "tts.gsv_service_command": "python api_v2.py -a 127.0.0.1 -p 9880",
            "tts.gsv_ref_audio_path": "/voices/ref.wav",
            "tts.gsv_ref_audio_text": "なんだか孤独になっちゃった夜は",
            "tts.gsv_text_language": "zh",
            "tts.gsv_top_k": 12,
            "tts.gsv_batch_threshold": 0.5,
        },
    )

    assert result["ok"] is True
    assert config.bubble_mode.summary_count == 2
    assert config.bubble_mode.default_display == "recent_reply"
    assert config.bubble_mode.position_x_percent == 0.75
    assert config.bubble_mode.position_y_percent == 1.0
    assert config.bubble_mode.opacity == 0.8
    assert config.bubble_mode.edge_snap is False
    assert config.bubble_mode.proactive_enabled is True
    assert config.bubble_mode.proactive_desktop_watch_enabled is True
    assert config.bubble_mode.proactive_interval_seconds == 600
    assert config.bubble_mode.proactive_trigger_probability == 0.45
    assert config.assistant.persona_prompt == "你是八千代。"
    assert config.assistant.user_address == "老师"
    assert config.tts.provider == "command"
    assert config.tts.command == "say {text}"
    assert config.tts.voice == "kyoko"
    assert config.tts.timeout_seconds == 10
    assert config.tts.max_chars == 60
    assert config.tts.trigger_probability == 0.35
    assert config.tts.notification_prompt == "只说一句提醒。"
    assert config.tts.gsv_base_url == "http://host.docker.internal:9880"
    assert config.tts.gsv_service_workdir == "/apps/GPT-SoVITS"
    assert config.tts.gsv_service_command == "python api_v2.py -a 127.0.0.1 -p 9880"
    assert config.tts.gsv_ref_audio_path == "/voices/ref.wav"
    assert config.tts.gsv_ref_audio_text == "なんだか孤独になっちゃった夜は"
    assert config.tts.gsv_top_k == 12
    assert config.tts.gsv_batch_threshold == 0.5
    assert result["mode_settings"]["bubble"]["config"]["summary_count"] == 2
    assert result["mode_settings"]["bubble"]["config"]["position_x_percent"] == 0.75
    assert result["mode_settings"]["bubble"]["config"]["proactive_trigger_probability"] == 0.45
    assert "assistant" not in result["mode_settings"]["bubble"]["config"]


def test_apply_settings_changes_rejects_invalid_single_field(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"bubble_mode.summary_count": 8})

    assert result["ok"] is False
    assert result["applied"] == {}
    assert config.bubble_mode.summary_count == 3
    assert "summary_count" in result["error"]


def test_apply_settings_changes_rejects_out_of_range_bubble_size(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"bubble_mode.width": 72})

    assert result["ok"] is False
    assert config.bubble_mode.width != 72
    assert "80-192" in result["error"]


def test_apply_settings_changes_accepts_expanded_bubble_size_range(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"bubble_mode.width": 192, "bubble_mode.height": 80})

    assert result["ok"] is True
    assert config.bubble_mode.width == 192
    assert config.bubble_mode.height == 80
    assert result["effects"]["has_restart_mode"] is True


def test_apply_settings_changes_rejects_invalid_bubble_percent_position(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"bubble_mode.position_x_percent": 1.2})

    assert result["ok"] is False
    assert config.bubble_mode.position_x_percent == 1.0
    assert "0-100%" in result["error"]


def test_apply_settings_changes_rejects_legacy_bubble_hover_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"bubble_mode.expand_trigger": "hover"})

    assert result["ok"] is False
    assert config.bubble_mode.expand_trigger == "click"
    assert "hover 已废弃" in result["error"]


def test_apply_settings_changes_rejects_invalid_new_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(
        config,
        {
            "tts.provider": "bad",
            "tts.timeout_seconds": 999,
            "tts.max_chars": 999,
            "tts.gsv_top_k": 0,
            "tts.gsv_media_type": "raw",
            "live2d_mode.proactive_interval_seconds": 10,
        },
    )

    assert result["ok"] is False
    assert config.tts.provider == "none"
    assert config.tts.timeout_seconds == 180
    assert config.tts.max_chars == 80
    assert config.live2d_mode.proactive_interval_seconds == 300
    assert "tts.provider" in result["error"]


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
            "live2d.mouse_follow_enabled": False,
        },
    )

    assert result["ok"] is True
    assert config.live2d_mode.model_name == "hiyori"
    assert config.live2d_mode.window_on_top is False
    assert config.live2d_mode.scale == 1.25
    assert config.live2d_mode.mouse_follow_enabled is False


def test_live2d_auto_open_chat_window_is_startup_only_effect(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()

    result = apply_settings_changes(config, {"live2d_mode.auto_open_chat_window": True})

    assert result["ok"] is True
    assert config.live2d_mode.auto_open_chat_window is True
    assert result["effects"]["has_restart_mode"] is True
    assert "重启当前模式" in result["effects"]["hint"]


def test_serialize_mode_settings_returns_separate_sections(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config = AppConfig()

    payload = serialize_mode_settings(config)

    assert set(payload) == {"bubble", "live2d"}
    assert "摘要" in payload["bubble"]["summary"]
    assert "未导入资源" in payload["live2d"]["summary"]
    assert payload["bubble"]["config"]["avatar_path_display"].startswith(
        "apps/shell/assets/avatars/"
    )
    assert payload["bubble"]["config"]["position_x_percent"] == 1.0
    assert payload["bubble"]["config"]["position_y_percent"] == 1.0
    assert payload["live2d"]["config"]["model_path_display"] == ""
    assert payload["live2d"]["config"]["position_anchor"] == "right_bottom"
    assert payload["live2d"]["config"]["scale"] == 0.6
    assert payload["live2d"]["config"]["resource"]["releases_url"] == LIVE2D_RELEASES_URL
    assert payload["live2d"]["config"]["resource"]["state"] == "not_configured"
    assert "assistant" not in payload["bubble"]["config"]
    assert "assistant" not in payload["live2d"]["config"]
    assert payload["live2d"]["config"]["tts"]["provider"] == "none"
    assert payload["live2d"]["config"]["tts_timeout_seconds"] == 180


def test_serialize_mode_window_data_returns_mode_part_only(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config = AppConfig(display_mode="live2d")
    config.live2d_mode.scale = 1.2

    payload = serialize_mode_window_data(config, "live2d")

    assert "common" not in payload
    assert payload["mode"]["id"] == "live2d"
    assert payload["settings"]["config"]["scale"] == 1.2
    assert payload["settings"]["config"]["mouse_follow_enabled"] is True
    assert payload["settings"]["config"]["show_on_all_spaces"] is True
    assert payload["settings"]["config"]["show_reply_bubble"] is True
    assert payload["settings"]["config"]["enable_quick_input"] is True


def test_display_settings_fall_back_to_bubble_when_live2d_assets_missing(monkeypatch, tmp_path):
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config = AppConfig(display_mode="live2d")

    payload = build_display_settings(config)

    assert payload["current_mode"] == "bubble"
    assert payload["configured_mode"] == "live2d"


def test_load_config_reads_legacy_live2d_block(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    _patch_no_live2d_assets(monkeypatch, tmp_path)
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
    assert config.live2d_mode.model_path == ""
    assert config.live2d_mode.window_on_top is False


def test_load_config_migrates_legacy_window_display_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps({"display_mode": "window"}, ensure_ascii=False),
        encoding="utf-8",
    )

    config = load_config()

    assert config.display_mode == "bubble"
    assert config.live2d_mode.model_name == ""
    assert config.live2d_mode.model_path == ""


def test_load_config_clears_legacy_bundled_live2d_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps(
            {
                "live2d_mode": {
                    "model_name": "八千代辉夜姬",
                    "model_path": str(LEGACY_BUNDLED_LIVE2D_MODEL_DIR),
                },
                "assistant": {"persona_prompt": "  八千代  ", "user_address": "老师"},
                "tts": {"enabled": True, "provider": "bad", "timeout_seconds": 999},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = load_config()

    assert config.live2d_mode.model_name == ""
    assert config.live2d_mode.model_path == ""
    assert config.assistant.persona_prompt == "  八千代  "
    assert config.assistant.user_address == "老师"
    assert config.tts.enabled is True
    assert config.tts.provider == "none"
    assert config.tts.timeout_seconds == 180


def test_load_config_normalizes_legacy_bubble_hover_to_click(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    _patch_no_live2d_assets(monkeypatch, tmp_path)
    config_mod._CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_mod._CONFIG_FILE.write_text(
        json.dumps({"bubble_mode": {"expand_trigger": "hover"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    config = load_config()

    assert config.bubble_mode.expand_trigger == "click"


def test_save_config_persists_mode_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "_CONFIG_FILE", tmp_path / "config.json")
    config = AppConfig()
    config.window_mode.recent_messages_limit = 5
    config.bubble_mode.summary_count = 2
    config.live2d_mode.model_name = "hiyori"
    config.live2d_mode.scale = 1.4
    config.live2d_mode.show_on_all_spaces = False
    config.live2d_mode.mouse_follow_enabled = False
    config.assistant.persona_prompt = "你是八千代。"
    config.assistant.user_address = "老师"
    config.tts.enabled = True
    config.tts.provider = "http"
    config.tts.endpoint = "http://127.0.0.1:9000/tts"
    config.tts.max_chars = 66
    config.tts.trigger_probability = 0.4
    config.tts.notification_prompt = "短提醒"

    save_config(config)
    data = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))

    assert data["window_mode"]["recent_messages_limit"] == 5
    assert data["bubble_mode"]["summary_count"] == 2
    assert data["live2d_mode"]["model_name"] == "hiyori"
    assert data["live2d_mode"]["scale"] == 1.4
    assert data["live2d_mode"]["show_on_all_spaces"] is False
    assert data["live2d_mode"]["mouse_follow_enabled"] is False
    assert data["assistant"]["persona_prompt"] == "你是八千代。"
    assert data["assistant"]["user_address"] == "老师"
    assert data["tts"]["enabled"] is True
    assert data["tts"]["provider"] == "http"
    assert data["tts"]["endpoint"] == "http://127.0.0.1:9000/tts"
    assert data["tts"]["max_chars"] == 66
    assert data["tts"]["trigger_probability"] == 0.4
    assert data["tts"]["notification_prompt"] == "短提醒"
