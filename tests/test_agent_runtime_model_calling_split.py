"""Tests for model call helpers split from the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.model_calling import call_model_profile_chat_message, callable_accepts_keyword


def test_model_calling_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime._callable_accepts_keyword is callable_accepts_keyword


def test_model_calling_passes_stream_only_when_supported() -> None:
    calls: list[dict[str, Any]] = []

    def chat_without_stream(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        calls.append({
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "messages": messages,
            "tools": tools,
            "has_stream": False,
        })
        return {"content": "ok"}

    def chat_with_stream(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> dict[str, str]:
        calls.append({
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "messages": messages,
            "tools": tools,
            "stream": stream,
        })
        return {"content": "stream ok"}

    messages = [{"role": "user", "content": "hello"}]
    assert callable_accepts_keyword(chat_with_stream, "stream") is True
    assert callable_accepts_keyword(chat_without_stream, "stream") is False
    assert call_model_profile_chat_message(
        chat_without_stream,
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        messages,
        stream=True,
    ) == {"content": "ok"}
    assert call_model_profile_chat_message(
        chat_with_stream,
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        messages,
        tools=[{"type": "function"}],
        stream=True,
    ) == {"content": "stream ok"}

    assert calls[0]["has_stream"] is False
    assert calls[1]["stream"] is True
    assert calls[1]["tools"] == [{"type": "function"}]


def test_legacy_model_call_wrapper_uses_current_openai_compatible_function(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_chat(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> dict[str, str]:
        calls.append({
            "base_url": base_url,
            "model": model,
            "api_key": api_key,
            "messages": messages,
            "tools": tools,
            "stream": stream,
        })
        return {"content": "patched"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    result = agent_runtime._call_model_profile_chat_message(
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hello"}],
        tools=[{"type": "function"}],
        stream=True,
    )

    assert result == {"content": "patched"}
    assert calls == [
        {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-test",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [{"type": "function"}],
            "stream": True,
        }
    ]
