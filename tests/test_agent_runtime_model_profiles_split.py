"""Tests for model profile resolution split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.model_profiles import RuntimeAgentModelTester, RuntimeModelProfileResolver
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

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        return self.get_profile_private(profile_id)

    def get_defaults(self) -> dict[str, str]:
        return dict(self.defaults)

    def test_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self.get_profile(profile_id)
        return {"ok": True, "message": f"tested {profile_id}", "model": profile["model"]}


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


def test_runtime_model_profile_resolver_validates_agent_profile_refs() -> None:
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
    profile_service.profiles["vision-1"] = {
        **profile_service.profiles["chat-1"],
        "capability": "vision",
    }
    resolver = _resolver(profile_service)

    assert resolver.validate_available_profile("chat-1", "chat")["model"] == "demo-model"
    resolver.validate_agent_profile_refs(
        {
            "model_mode": "profile",
            "model_profile_id": "chat-1",
            "vision_model_profile_id": "vision-1",
        }
    )

    with pytest.raises(AgentRuntimeError, match="类型不匹配"):
        resolver.validate_available_profile("chat-1", "vision")
    with pytest.raises(AgentRuntimeError, match="不存在"):
        resolver.validate_agent_profile_refs({"model_mode": "profile", "model_profile_id": "missing"})


def test_runtime_agent_model_tester_covers_profile_follow_main_and_custom_api() -> None:
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
    profile_service.profiles["vision-1"] = {
        **profile_service.profiles["chat-1"],
        "model": "vision-model",
        "capability": "vision",
    }
    profile_service.defaults["chat"] = "chat-1"
    custom_calls: list[tuple[str, str, str, list[dict[str, str]]]] = []
    clock = iter([10.0, 10.25])
    tester = RuntimeAgentModelTester(
        profile_service_factory=lambda: profile_service,
        default_agent_ids={"builtin:yachiyo-main"},
        call_custom_api=lambda base_url, model, api_key, messages: custom_calls.append(
            (base_url, model, api_key, messages)
        )
        or "Custom OK",
        now_seconds=lambda: next(clock),
        redact_error=str,
        error_type=AgentRuntimeError,
    )

    profile_result = tester.test_agent_model(
        {
            "agent_id": "agent-1",
            "model_profile_id": "chat-1",
            "vision_model_profile_id": "vision-1",
        }
    )
    follow_main_result = tester.test_agent_model({"agent_id": "builtin:yachiyo-main"})
    custom_result = tester.test_agent_model(
        {
            "agent_id": "agent-2",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://custom.example.test/v1/",
                "model": "custom-model",
                "api_key": "sk-custom",
            },
        }
    )
    missing_result = tester.test_agent_model({"agent_id": "agent-3", "model_mode": "custom_api", "model_config": {}})

    assert profile_result["mode"] == "profile"
    assert profile_result["message"] == "tested chat-1；图片识别 Profile 测试通过。"
    assert follow_main_result["mode"] == "follow_main"
    assert custom_result == {"ok": True, "latency_ms": 250, "message": "Custom OK"}
    assert custom_calls == [
        (
            "https://custom.example.test/v1",
            "custom-model",
            "sk-custom",
            [{"role": "user", "content": "Reply with OK."}],
        )
    ]
    assert missing_result == {"ok": False, "missing": ["base_url", "model", "api_key"], "message": "custom_api 配置不完整。"}


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
        assert agent_runtime.RuntimeAgentModelTester is RuntimeAgentModelTester
        assert isinstance(service.model_profile_resolver, RuntimeModelProfileResolver)
        assert isinstance(service.agent_model_tester, RuntimeAgentModelTester)
        assert service._agent_model_config_private(
            {"agent_id": "agent-1", "model_mode": "follow_main"}
        )["model"] == "demo-model"
        assert agent_runtime.NativeRunEngine._model_profile_config_private(
            "chat-1",
            capability="chat",
        )["api_key"] == "sk-secret"
    finally:
        service.close()
