from __future__ import annotations

from apps.shell.hermes_capabilities import (
    build_hermes_image_input_capability,
    lookup_model_supports_vision,
)


def _config(tmp_path, body: str = ""):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_xiaomi_pro_auto_uses_vision_text_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apps.shell.hermes_capabilities._load_models_dev_cache",
        lambda: {
            "xiaomi": {
                "models": {
                    "mimo-v2.5-pro": {
                        "attachment": True,
                        "modalities": {"input": ["text", "image"]},
                    }
                }
            }
        },
    )

    capability = build_hermes_image_input_capability(
        provider="xiaomi",
        model="mimo-v2.5-pro",
        config_path=_config(tmp_path),
    )

    assert capability["can_attach_images"] is True
    assert capability["route"] == "vision_text"
    assert capability["requires_vision_pipeline"] is True
    assert capability["supports_native_vision"] is False


def test_xiaomi_pro_native_mode_is_blocked(tmp_path):
    capability = build_hermes_image_input_capability(
        provider="xiaomi",
        model="mimo-v2.5-pro",
        config_path=_config(tmp_path, "agent:\n  image_input_mode: native\n"),
    )

    assert capability["can_attach_images"] is False
    assert capability["route"] == "blocked"


def test_xiaomi_vision_metadata_overrides_stale_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apps.shell.hermes_capabilities._load_models_dev_cache",
        lambda: {
            "xiaomi": {
                "models": {
                    "mimo-v2.5": {
                        "attachment": False,
                        "modalities": {"input": ["text"]},
                    }
                }
            }
        },
    )

    assert lookup_model_supports_vision("xiaomi", "mimo-v2.5") is True
    capability = build_hermes_image_input_capability(
        provider="xiaomi",
        model="mimo-v2.5",
        config_path=_config(tmp_path),
    )
    assert capability["route"] == "native"
