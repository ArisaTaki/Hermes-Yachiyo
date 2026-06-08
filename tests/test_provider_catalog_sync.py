"""Provider catalog synchronization tests."""

from __future__ import annotations

import json
import ssl
from urllib import error as urlerror

from apps.shell.model_profiles import ModelProfileService
from apps.shell.provider_catalog_sync import (
    cached_model_metadata,
    cached_provider_models,
    load_provider_catalog_cache,
    normalize_provider_models,
    sync_provider_catalogs,
)


def test_normalize_provider_models_preserves_capability_metadata():
    models = normalize_provider_models(
        {
            "data": [
                {
                    "id": "openai/gpt-4o-mini",
                    "name": "GPT-4o mini",
                    "architecture": {
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                        "modality": "text+image->text",
                    },
                    "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
                    "supported_parameters": ["tools"],
                    "top_provider": {"context_length": 128000, "max_completion_tokens": 16384},
                }
            ]
        },
        provider="openrouter",
        source_url="https://openrouter.ai/api/v1/models",
    )

    assert models[0]["id"] == "openai/gpt-4o-mini"
    assert models[0]["provider_key"] == "openai"
    assert models[0]["input_modalities"] == ["text", "image"]
    assert models[0]["capability_hint"]["supports_vision"] is True
    assert models[0]["context_length"] == 128000
    assert models[0]["supported_parameters"] == ["tools"]


def test_sync_provider_catalogs_writes_cache(monkeypatch, tmp_path):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"data": [{"id": "deepseek-chat", "owned_by": "deepseek"}]}).encode("utf-8")

    def fake_urlopen(request, timeout, context):
        assert timeout == 20.0
        assert isinstance(context, ssl.SSLContext)
        assert request.full_url == "https://api.deepseek.com/v1/models"
        assert request.get_header("Authorization") == "Bearer sk-deepseek"
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    monkeypatch.setattr("apps.shell.provider_catalog_sync.urlrequest.urlopen", fake_urlopen)

    cache_path = tmp_path / "provider-capabilities.json"
    result = sync_provider_catalogs(providers=["deepseek"], cache_path=cache_path)
    cache = load_provider_catalog_cache(cache_path)

    assert result["ok"] is True
    assert result["providers"]["deepseek"]["status"] == "ok"
    assert cache["providers"]["deepseek"]["models"][0]["id"] == "deepseek-chat"
    assert cached_model_metadata("deepseek", "deepseek-chat", cache_path=cache_path)["provider_key"] == "deepseek"


def test_cached_provider_models_returns_empty_for_missing_cache(tmp_path):
    assert cached_provider_models("openrouter", cache_path=tmp_path / "missing.json") == []


def test_model_source_fetch_uses_provider_cache_when_remote_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cache_path = tmp_path / "yachiyo" / "provider-capabilities.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "generated_at": "2026-05-19T00:00:00+00:00",
                "providers": {
                    "openrouter": {
                        "provider": "openrouter",
                        "status": "ok",
                        "models": [
                            {
                                "id": "openai/gpt-4o-mini",
                                "provider_key": "openai",
                                "input_modalities": ["text", "image"],
                                "output_modalities": ["text"],
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    service = ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
    )
    source = service.create_source(
        {
            "name": "OpenRouter",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
        }
    )

    def fake_urlopen(*_args, **_kwargs):
        raise urlerror.URLError("offline")

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])

        assert result["ok"] is True
        assert result["from_cache"] is True
        assert result["models"][0]["id"] == "openai/gpt-4o-mini"
        assert result["models"][0]["input_modalities"] == ["text", "image"]
    finally:
        service.close()
