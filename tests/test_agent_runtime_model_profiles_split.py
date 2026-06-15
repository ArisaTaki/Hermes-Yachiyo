"""Tests for model profile resolution split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.model_profiles import RuntimeModelProfileResolver
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeProfileService:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.defaults: dict[str, str] = {}

    def get_profile_private(self, profile_id: str) -> dict[str, Any]:
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            raise KeyError(profile_id) from exc

    def get_defaults(self) -> dict[str, str]:
        return dict(self.defaults)


def _resolver(profile_service: FakeProfileService) -> RuntimeModelProfileResolver:
    return RuntimeModelProfileResolver(
        profile_service_factory=lambda: profile_service,
        supports_openai_compatible_api=lambda provider: provider
        in {"openai_compatible", "xiaomi_mimo"},
        default_agent_ids={"builtin:yachiyo-main"},
        error_type=AgentRuntimeError,
    )


def test_runtime_model_profile_resolver_validates_profile_contract() -> None:
    profile_service = FakeProfileService()
    profile_service.profiles["chat-1"] = {
        "provider": "xiaomi_mimo",
        "base_url": "https://api.example.test/v1",
        "model": "mimo-v2.5-pro",
        "api_key": "sk-secret",
        "enabled": True,
        "status": "available",
        "capability": "chat",
    }

    assert _resolver(profile_service).model_profile_config_private(
        "chat-1",
        capability="chat",
    ) == {
        "provider": "xiaomi_mimo",
        "base_url": "https://api.example.test/v1",
        "model": "mimo-v2.5-pro",
        "api_key": "sk-secret",
    }

    profile_service.profiles["disabled"] = {
        **profile_service.profiles["chat-1"],
        "enabled": False,
    }
    with pytest.raises(AgentRuntimeError, match="已停用"):
        _resolver(profile_service).model_profile_config_private("disabled", capability="chat")

    profile_service.profiles["untested"] = {
        **profile_service.profiles["chat-1"],
        "status": "pending",
    }
    with pytest.raises(AgentRuntimeError, match="尚未通过连接测试"):
        _resolver(profile_service).model_profile_config_private("untested", capability="chat")

    profile_service.profiles["unsupported"] = {
        **profile_service.profiles["chat-1"],
        "provider": "native_only",
    }
    with pytest.raises(AgentRuntimeError, match="OpenAI-compatible"):
        _resolver(profile_service).model_profile_config_private("unsupported", capability="chat")

    profile_service.profiles["vision"] = {
        **profile_service.profiles["chat-1"],
        "capability": "vision",
    }
    with pytest.raises(AgentRuntimeError, match="chat"):
        _resolver(profile_service).model_profile_config_private("vision", capability="chat")


def test_runtime_model_profile_resolver_supports_agent_modes() -> None:
    profile_service = FakeProfileService()
    profile_service.profiles["default-chat"] = {
        "provider": "openai_compatible",
        "base_url": "https://api.example.test/v1",
        "model": "demo-model",
        "api_key": "sk-secret",
        "enabled": True,
        "status": "available",
        "capability": "chat",
    }
    profile_service.defaults["chat"] = "default-chat"
    resolver = _resolver(profile_service)

    assert resolver.agent_model_config_private(
        {"agent_id": "agent-1", "model_mode": "follow_main"}
    )["model"] == "demo-model"
    assert resolver.agent_model_config_private(
        {
            "agent_id": "agent-2",
            "model_mode": "custom_api",
            "model_config": {"base_url": "https://custom.example.test/v1"},
        }
    ) == {"base_url": "https://custom.example.test/v1"}

    with pytest.raises(AgentRuntimeError, match="缺少可运行的 Chat Profile"):
        resolver.agent_model_config_private({"agent_id": "agent-3", "model_mode": "profile"})


def test_native_runtime_uses_split_model_profile_resolver(tmp_path, monkeypatch) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    profile_service = FakeProfileService()
    profile_service.profiles["chat-1"] = {
        "provider": "openai_compatible",
        "base_url": "https://api.example.test/v1",
        "model": "demo-model",
        "api_key": "sk-secret",
        "enabled": True,
        "status": "available",
        "capability": "chat",
    }
    profile_service.defaults["chat"] = "chat-1"
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: profile_service)

    try:
        assert agent_runtime.RuntimeModelProfileResolver is RuntimeModelProfileResolver
        assert isinstance(service.model_profile_resolver, RuntimeModelProfileResolver)
        assert service._agent_model_config_private(
            {"agent_id": "agent-1", "model_mode": "follow_main"}
        )["model"] == "demo-model"
        assert agent_runtime.NativeRunEngine._model_profile_config_private(
            "chat-1",
            capability="chat",
        )["api_key"] == "sk-secret"
    finally:
        service.close()
