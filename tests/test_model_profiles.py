"""Model profile registry tests."""

from __future__ import annotations

import json

import pytest

from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.model_profiles import ModelProfileError, ModelProfileService


def make_profile_service(tmp_path) -> ModelProfileService:
    return ModelProfileService(
        db_path=tmp_path / "model-profiles.db",
        workspace_dir=tmp_path / "profiles",
    )


def test_model_profile_crud_redacts_and_preserves_api_key(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile(
            {
                "name": "Work Gateway",
                "capability": "chat",
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            }
        )

        assert profile["api_key_configured"] is True
        assert "api_key" not in profile

        updated = service.update_profile(
            profile["profile_id"],
            {"base_url": "https://gateway.example.test/v1", "api_key": ""},
        )
        private = service.get_profile_private(profile["profile_id"])

        assert updated["base_url"] == "https://gateway.example.test/v1"
        assert updated["api_key_configured"] is True
        assert private["api_key"] == "sk-secret"
    finally:
        service.close()


def test_model_profile_defaults_validate_capability(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        profile = service.create_profile({"name": "Vision", "capability": "vision"})

        with pytest.raises(ModelProfileError):
            service.set_defaults({"chat": profile["profile_id"]})

        result = service.set_defaults({"vision": profile["profile_id"]})
        assert result["defaults"]["vision"] == profile["profile_id"]
    finally:
        service.close()


def test_model_source_owns_credentials_and_models_reference_it(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "MiniMax",
                "provider": "openai_compatible",
                "base_url": "https://api.minimax.chat/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "MiniMax Chat",
                "capability": "chat",
                "model": "MiniMax-M2.7",
                "api_key": "sk-ignored",
            }
        )
        public_profile = service.get_profile(profile["profile_id"])
        private_profile = service.get_profile_private(profile["profile_id"])
        updated = service.update_profile(profile["profile_id"], {"model": "MiniMax-M2.8"})

        assert public_profile["source_name"] == "MiniMax"
        assert public_profile["base_url"] == "https://api.minimax.chat/v1"
        assert public_profile["api_key_configured"] is True
        assert private_profile["api_key"] == "sk-source-secret"
        assert service.get_profile_private(profile["profile_id"])["api_key"] == "sk-source-secret"
        assert updated["model"] == "MiniMax-M2.8"
    finally:
        service.close()


def test_model_source_reports_hermes_provider_adapter(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "Xiaomi MiMo",
                "provider": "xiaomi_mimo",
                "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "MiMo",
                "capability": "chat",
                "model": "mimo-v2-pro",
            }
        )
        public_source = service.get_source(source["source_id"])
        public_profile = service.get_profile(profile["profile_id"])

        assert public_source["hermes_provider"] == "xiaomi"
        assert public_source["api_key_name"] == "XIAOMI_API_KEY"
        assert public_source["can_use_as_hermes"] is True
        assert public_profile["hermes_provider"] == "xiaomi"
        assert public_profile["runtime_scope"] == "hermes"
    finally:
        service.close()


def test_openrouter_profile_keeps_openrouter_as_runtime_provider(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "OpenRouter",
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "DeepSeek via OpenRouter",
                "capability": "chat",
                "model": "deepseek/deepseek-chat",
            }
        )

        public_profile = service.get_profile(profile["profile_id"])

        assert public_profile["hermes_provider"] == "openrouter"
        assert public_profile["api_key_name"] == "OPENROUTER_API_KEY"
    finally:
        service.close()


def test_paused_source_marks_child_profiles_unavailable(tmp_path):
    service = make_profile_service(tmp_path)
    try:
        source = service.create_source(
            {
                "name": "Gateway",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "sk-source-secret",
            }
        )
        profile = service.create_profile(
            {
                "source_id": source["source_id"],
                "name": "Gateway Chat",
                "capability": "chat",
                "model": "demo-model",
            }
        )

        service.update_source(source["source_id"], {"enabled": False})
        paused_profile = service.get_profile(profile["profile_id"])

        assert paused_profile["enabled"] is False
        assert paused_profile["profile_enabled"] is True
        assert paused_profile["source_enabled"] is False

        service.update_source(source["source_id"], {"enabled": True})
        assert service.get_profile(profile["profile_id"])["enabled"] is True
    finally:
        service.close()


def test_model_profile_test_updates_status(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    profile = service.create_profile(
        {
            "name": "Runnable",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
    )
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *_args, **_kwargs: "OK")
    try:
        result = service.test_profile(profile["profile_id"])
        tested = service.get_profile(profile["profile_id"])

        assert result["ok"] is True
        assert tested["status"] == "available"
        assert tested["last_tested_at"]
    finally:
        service.close()


def test_test_and_save_profile_failure_does_not_persist(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Gateway",
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "api_key": "sk-source-secret",
        }
    )

    def fail_chat(*_args, **_kwargs):
        raise ModelProfileError("network failed")

    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fail_chat)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {"name": "Draft", "capability": "chat", "model": "demo-model"},
        )

        assert result["ok"] is False
        assert result["source"]["status"] == "failed"
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


def test_vision_profile_rejects_model_that_fails_real_image_test(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *args, **kwargs: calls.append((args, kwargs)) or "OK")
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "Text Only",
                "capability": "vision",
                "model": "qwen/qwen3-coder",
                "options": {"remote_model": {"id": "qwen/qwen3-coder", "input_modalities": ["text"]}},
            },
        )

        assert result["ok"] is False
        assert "真实图片测试" in result["message"]
        assert calls
        assert service.list_profiles()["profiles"] == []
    finally:
        service.close()


def test_vision_profile_test_uses_image_payload_and_saves(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []

    def fake_chat(base_url, model, api_key, messages):
        calls.append((base_url, model, api_key, messages))
        return "red"

    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", fake_chat)
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "Vision",
                "capability": "vision",
                "model": "openai/gpt-4.1-mini",
                "options": {
                    "remote_model": {
                        "id": "openai/gpt-4.1-mini",
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                    }
                },
            },
        )

        assert result["ok"] is True
        assert result["profile"]["status"] == "available"
        assert service.get_source(source["source_id"])["status"] == "available"
        assert result["profile"]["options"]["remote_model"]["input_modalities"] == ["text", "image"]
        assert calls[0][3][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        service.close()


def test_vision_profile_can_pass_without_remote_metadata(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "Xiaomi",
            "provider": "xiaomi",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key": "sk-source-secret",
        }
    )
    calls = []
    monkeypatch.setattr("apps.shell.model_profiles.openai_compatible_chat", lambda *args, **kwargs: calls.append((args, kwargs)) or "red")
    try:
        result = service.test_and_save_profile(
            source["source_id"],
            {
                "name": "MiMo Vision",
                "capability": "vision",
                "model": "mimo-v2.5",
            },
        )

        assert result["ok"] is True
        assert result["profile"]["status"] == "available"
        assert result["profile"]["capability"] == "vision"
        assert calls[0][0][3][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        service.close()


def test_fetch_source_models_reads_openai_compatible_list(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "DeepSeek",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-source-secret",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {"id": "deepseek-chat", "owned_by": "deepseek"},
                        {"id": "deepseek-chat", "owned_by": "deepseek"},
                        {"id": "deepseek-reasoner"},
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert timeout == 20
        assert request.full_url == "https://api.deepseek.com/models"
        assert request.get_header("Authorization") == "Bearer sk-source-secret"
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])

        assert result["ok"] is True
        assert result["count"] == 2
        assert result["models"] == [
            {"id": "deepseek-chat", "owned_by": "deepseek", "provider_key": "deepseek"},
            {"id": "deepseek-reasoner", "owned_by": "", "provider_key": "deepseek"},
        ]
        assert "api_key" not in result["source"]
    finally:
        service.close()


def test_fetch_source_models_preserves_openrouter_metadata(monkeypatch, tmp_path):
    service = make_profile_service(tmp_path)
    source = service.create_source(
        {
            "name": "OpenRouter",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {
                    "data": [
                        {
                            "id": "qwen/qwen3-coder",
                            "canonical_slug": "qwen/qwen3-coder",
                            "name": "Qwen: Qwen3 Coder",
                            "context_length": 262144,
                            "architecture": {
                                "modality": "text->text",
                                "input_modalities": ["text"],
                                "output_modalities": ["text"],
                            },
                            "pricing": {"prompt": "0", "completion": "0"},
                            "top_provider": {"max_completion_tokens": 65536, "is_moderated": False},
                            "supported_parameters": ["tools", "structured_outputs"],
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert timeout == 20
        assert request.full_url == "https://openrouter.ai/api/v1/models"
        assert request.get_header("Authorization") is None
        return FakeResponse()

    monkeypatch.setattr("apps.shell.model_profiles.urlrequest.urlopen", fake_urlopen)
    try:
        result = service.fetch_source_models(source["source_id"])
        model = result["models"][0]

        assert model["provider_key"] == "qwen"
        assert model["name"] == "Qwen: Qwen3 Coder"
        assert model["context_length"] == 262144
        assert model["max_completion_tokens"] == 65536
        assert model["input_modalities"] == ["text"]
        assert model["supported_parameters"] == ["tools", "structured_outputs"]
        assert model["is_free"] is True
    finally:
        service.close()


def test_agent_runtime_uses_model_profile(monkeypatch, tmp_path):
    profile_service = make_profile_service(tmp_path)
    runtime = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        seed_templates=False,
    )
    profile = profile_service.create_profile(
        {
            "name": "Agent Profile",
            "capability": "chat",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
    )
    profile_service._record_test_result(profile["profile_id"], ok=True, message="OK")
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat", lambda *_args, **_kwargs: "Profile result")
    try:
        agent = runtime.create_agent(
            {
                "name": "Profile Agent",
                "model_mode": "profile",
                "model_profile_id": profile["profile_id"],
            }
        )
        run = runtime.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Hello"})

        assert run["status"] == "completed"
        assert run["result"] == "Profile result"
    finally:
        runtime.close()
        profile_service.close()


def test_agent_runtime_uses_openai_compatible_provider_source_profile(monkeypatch, tmp_path):
    profile_service = make_profile_service(tmp_path)
    runtime = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        seed_templates=False,
    )
    source = profile_service.create_source(
        {
            "name": "Xiaomi MiMo",
            "provider": "xiaomi_mimo",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key": "sk-secret",
        }
    )
    profile = profile_service.create_profile(
        {
            "source_id": source["source_id"],
            "name": "MiMo Agent",
            "capability": "chat",
            "model": "mimo-v2.5-pro",
        }
    )
    profile_service._record_test_result(profile["profile_id"], ok=True, message="OK")
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat", lambda *_args, **_kwargs: "MiMo result")
    try:
        agent = runtime.create_agent(
            {
                "name": "MiMo Profile Agent",
                "model_mode": "profile",
                "model_profile_id": profile["profile_id"],
            }
        )
        run = runtime.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Hello"})

        assert run["status"] == "completed"
        assert run["result"] == "MiMo result"
    finally:
        runtime.close()
        profile_service.close()
