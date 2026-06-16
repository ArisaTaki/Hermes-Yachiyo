"""Tests for legacy-compatible model dependency providers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from apps.shell.agent.runtime.model_compat import (
    RuntimeModelCompatibilityProvider,
    build_legacy_model_call_adapters,
)


class _FakeProfileService:
    def get_defaults(self) -> dict[str, str]:
        return {"chat": "chat-profile"}


def test_runtime_model_compat_provider_preserves_legacy_monkeypatch_points() -> None:
    calls: list[tuple[str, str, str, list[dict[str, str]]]] = []

    def fake_chat(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        return {"content": "patched"}

    def fake_timeout() -> float:
        return 42.0

    def fake_urlopen(*args: Any, **kwargs: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return args, kwargs

    def fake_redact(value: Any) -> str:
        return f"redacted:{value}"

    def fake_supports(provider: str) -> bool:
        return provider == "openai_compatible"

    class _FakeAdapter:
        def call(
            self,
            base_url: str,
            model: str,
            api_key: str,
            messages: list[dict[str, str]],
        ) -> str:
            calls.append((base_url, model, api_key, messages))
            return "ok"

    fake_module = SimpleNamespace(
        openai_compatible_chat_message=fake_chat,
        read_openai_compatible_chat_timeout=fake_timeout,
        urlopen_with_bundled_ca=fake_urlopen,
        redact_secrets=fake_redact,
        get_model_profile_service=lambda: _FakeProfileService(),
        supports_openai_compatible_api=fake_supports,
        get_workspace_status=lambda: {"initialized": True},
        NativeRunEngine=SimpleNamespace(
            _model_profile_config_private=staticmethod(
                lambda profile_id, *, capability: {
                    "profile_id": profile_id,
                    "capability": capability,
                }
            )
        ),
        _legacy_openai_compatible_chat_adapter=_FakeAdapter(),
    )
    provider = RuntimeModelCompatibilityProvider(module_loader=lambda: fake_module)

    assert provider.chat_message() is fake_chat
    assert provider.chat_timeout() == 42.0
    assert provider.urlopen("request", timeout=42) == (("request",), {"timeout": 42})
    assert provider.redact_error("secret") == "redacted:secret"
    assert provider.profile_service().get_defaults() == {"chat": "chat-profile"}
    assert provider.supports_openai_compatible_api("openai_compatible") is True
    assert provider.workspace_status() == {"initialized": True}
    assert provider.default_profile_id("chat") == "chat-profile"
    assert provider.chat_default_profile_id() == "chat-profile"
    assert provider.chat_profile_model_config_private("chat-profile") == {
        "profile_id": "chat-profile",
        "capability": "chat",
    }
    assert provider.openai_compatible_chat(
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hello"}],
    ) == "ok"
    assert calls == [
        (
            "https://api.example.test/v1",
            "demo-model",
            "sk-test",
            [{"role": "user", "content": "hello"}],
        )
    ]

    adapters = build_legacy_model_call_adapters(provider)
    assert adapters.model_profile_chat_adapter.call(
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hello"}],
    ) == {"content": "patched"}
