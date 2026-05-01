from __future__ import annotations

from apps.shell.hermes_capabilities import (
    build_hermes_image_input_capability,
    lookup_model_supports_vision,
)


def _config(tmp_path, body: str = ""):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_xiaomi_pro_auto_uses_native_images_from_models_cache(tmp_path, monkeypatch):
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
    assert capability["route"] == "native"
    assert capability["requires_vision_pipeline"] is False
    assert capability["supports_native_vision"] is True


def test_separate_vision_config_enables_text_pipeline(tmp_path):
    capability = build_hermes_image_input_capability(
        provider="deepseek",
        model="deepseek-chat",
        config_path=_config(
            tmp_path,
            "agent:\n"
            "  image_input_mode: text\n"
            "auxiliary:\n"
            "  vision:\n"
            "    provider: xiaomi\n"
            "    model: mimo-v2.5\n",
        ),
    )

    assert capability["can_attach_images"] is True
    assert capability["route"] == "vision_text"
    assert capability["requires_vision_pipeline"] is True


def test_auto_mode_uses_main_model_when_it_supports_images(tmp_path, monkeypatch):
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
        config_path=_config(
            tmp_path,
            "agent:\n"
            "  image_input_mode: auto\n"
            "auxiliary:\n"
            "  vision:\n"
            "    provider: xiaomi\n"
            "    model: mimo-v2.5\n",
        ),
    )

    assert capability["can_attach_images"] is True
    assert capability["route"] == "native"


def test_xiaomi_pro_native_mode_is_allowed(tmp_path, monkeypatch):
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
        config_path=_config(tmp_path, "agent:\n  image_input_mode: native\n"),
    )

    assert capability["can_attach_images"] is True
    assert capability["route"] == "native"


def test_xiaomi_models_cache_overrides_stale_fallback(tmp_path, monkeypatch):
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

    assert lookup_model_supports_vision("xiaomi", "mimo-v2.5") is False
    capability = build_hermes_image_input_capability(
        provider="xiaomi",
        model="mimo-v2.5",
        config_path=_config(tmp_path),
    )
    assert capability["route"] == "blocked"
