"""Model profile registry tests."""

from __future__ import annotations

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
