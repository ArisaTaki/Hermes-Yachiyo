from __future__ import annotations

from apps.shell.hermes_capabilities import (
    build_hermes_image_input_capability,
    infer_effective_hermes_provider,
    lookup_model_supports_vision,
)


def _config(tmp_path, body: str = ""):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_xiaomi_pro_auto_uses_text_pipeline_despite_stale_models_cache(tmp_path, monkeypatch):
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


def test_auto_mode_uses_separate_vision_when_explicitly_configured(tmp_path, monkeypatch):
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
    assert capability["route"] == "vision_text"
    assert capability["requires_vision_pipeline"] is True


def test_xiaomi_pro_native_mode_is_blocked_when_known_unsupported(tmp_path, monkeypatch):
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

    assert capability["can_attach_images"] is False
    assert capability["route"] == "blocked"


def test_xiaomi_verified_native_models_override_stale_models_cache(tmp_path, monkeypatch):
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


def test_auto_provider_infers_openrouter_from_base_url_for_image_capability(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "apps.shell.hermes_capabilities._load_models_dev_cache",
        lambda: {
            "openrouter": {
                "models": {
                    "anthropic/claude-opus-4.6": {
                        "attachment": True,
                        "modalities": {"input": ["text", "image"]},
                    }
                }
            }
        },
    )

    capability = build_hermes_image_input_capability(
        provider="auto",
        model="anthropic/claude-opus-4.6",
        config_path=_config(
            tmp_path,
            "model:\n"
            "  provider: auto\n"
            "  default: anthropic/claude-opus-4.6\n"
            "  base_url: https://openrouter.ai/api/v1\n",
        ),
    )

    assert capability["provider"] == "openrouter"
    assert capability["route"] == "native"
    assert capability["can_attach_images"] is True


def test_effective_provider_inference_keeps_explicit_provider():
    assert (
        infer_effective_hermes_provider(
            "custom",
            "https://openrouter.ai/api/v1",
            "anthropic/claude-opus-4.6",
        )
        == "custom"
    )
