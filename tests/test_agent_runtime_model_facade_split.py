"""Tests for Model facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.model_facade import RuntimeModelFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class _FakeProfileService:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.defaults: dict[str, str] = {}

    def get_profile_private(self, profile_id: str) -> dict[str, Any]:
        return self.profiles[profile_id]

    def get_profile(self, profile_id: str) -> dict[str, Any]:
        return self.get_profile_private(profile_id)

    def get_defaults(self) -> dict[str, str]:
        return dict(self.defaults)


def test_runtime_model_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeModelFacadeMixin is RuntimeModelFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeModelFacadeMixin)
    for method_name in (
        "_validate_available_profile",
        "_model_profile_config_private",
        "_chat_profile_model_config_private",
        "_agent_model_config_private",
        "_openai_compatible_chat",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_model_profile_facade_methods_available_after_split(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    profile_service = _FakeProfileService()
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
    monkeypatch.setattr(agent_runtime, "get_model_profile_service", lambda: profile_service)

    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.NativeRunEngine._validate_available_profile(
            "chat-1",
            "chat",
        )["model"] == "demo-model"
        assert agent_runtime.NativeRunEngine._model_profile_config_private(
            "chat-1",
            capability="chat",
        )["api_key"] == "sk-secret"
        assert agent_runtime.NativeRunEngine._chat_profile_model_config_private(
            "chat-1",
        )["base_url"] == "https://api.example.test/v1"
        assert service._agent_model_config_private(
            {"agent_id": "agent-1", "model_mode": "follow_main"},
        )["model"] == "demo-model"
    finally:
        service.close()


def test_model_facade_preserves_legacy_module_monkeypatch_points(monkeypatch: Any) -> None:
    calls: list[dict[str, Any]] = []

    class _FakeAdapter:
        def call(
            self,
            base_url: str,
            model: str,
            api_key: str,
            messages: list[dict[str, str]],
        ) -> str:
            calls.append(
                {
                    "base_url": base_url,
                    "model": model,
                    "api_key": api_key,
                    "messages": messages,
                }
            )
            return "ok"

    monkeypatch.setattr(
        agent_runtime.NativeRunEngine,
        "_model_profile_config_private",
        staticmethod(lambda profile_id, *, capability: {"profile_id": profile_id, "capability": capability}),
    )
    monkeypatch.setattr(agent_runtime, "_legacy_openai_compatible_chat_adapter", _FakeAdapter())

    assert agent_runtime.NativeRunEngine._chat_profile_model_config_private("chat-1") == {
        "profile_id": "chat-1",
        "capability": "chat",
    }
    assert agent_runtime.NativeRunEngine._openai_compatible_chat(
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hello"}],
    ) == "ok"
    assert calls == [
        {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-test",
            "messages": [{"role": "user", "content": "hello"}],
        }
    ]
