"""Tests for model call helpers split from the legacy runtime."""

from __future__ import annotations

from typing import Any
from urllib import error as urlerror

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.model_calling import (
    RuntimeModelProfileChatAdapter,
    RuntimeOpenAICompatibleChatAdapter,
    call_model_profile_chat_message,
    callable_accepts_keyword,
    openai_compatible_chat,
)


def test_model_calling_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeModelProfileChatAdapter is RuntimeModelProfileChatAdapter
    assert agent_runtime.RuntimeOpenAICompatibleChatAdapter is RuntimeOpenAICompatibleChatAdapter
    assert agent_runtime._runtime_call_model_profile_chat_message is call_model_profile_chat_message
    assert agent_runtime._callable_accepts_keyword is callable_accepts_keyword


def test_model_profile_chat_adapter_uses_current_provider() -> None:
    calls: list[dict[str, Any]] = []
    current_chat: dict[str, Any] = {}

    def first_chat(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, str]:
        calls.append({"chat": "first", "kwargs": kwargs})
        return {"content": "first"}

    def second_chat(
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, str]:
        calls.append({"chat": "second", "kwargs": kwargs})
        return {"content": "second"}

    current_chat["func"] = first_chat
    adapter = RuntimeModelProfileChatAdapter(
        chat_message_provider=lambda: current_chat["func"],
    )

    assert adapter.call("https://api.example.test/v1", "demo", "sk-test", []) == {"content": "first"}
    current_chat["func"] = second_chat
    assert adapter.call(
        "https://api.example.test/v1",
        "demo",
        "sk-test",
        [],
        tools=[{"type": "function"}],
        stream=True,
    ) == {"content": "second"}
    assert calls == [
        {"chat": "first", "kwargs": {}},
        {"chat": "second", "kwargs": {"tools": [{"type": "function"}], "stream": True}},
    ]


def test_openai_compatible_chat_adapter_uses_runtime_dependencies() -> None:
    calls: list[dict[str, Any]] = []
    timeouts = [5.0, 8.0]

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        calls.append({
            "url": request.full_url,
            "timeout": timeout,
        })
        return FakeResponse(b'{"choices":[{"message":{"content":"custom ok"}}]}')

    adapter = RuntimeOpenAICompatibleChatAdapter(
        timeout_provider=lambda: timeouts.pop(0),
        urlopen=fake_urlopen,
        redact_error=str,
    )

    assert adapter.call(
        "https://api.example.test/v1/",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hello"}],
    ) == "custom ok"
    assert adapter.call(
        "https://api.example.test/v1/",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "again"}],
    ) == "custom ok"
    assert calls == [
        {"url": "https://api.example.test/v1/chat/completions", "timeout": 5.0},
        {"url": "https://api.example.test/v1/chat/completions", "timeout": 8.0},
    ]


def test_legacy_openai_compatible_chat_wrapper_delegates_to_adapter(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAdapter:
        def call(
            self,
            base_url: str,
            model: str,
            api_key: str,
            messages: list[dict[str, str]],
        ) -> str:
            calls.append({
                "base_url": base_url,
                "model": model,
                "api_key": api_key,
                "messages": messages,
            })
            return "legacy ok"

    monkeypatch.setattr(agent_runtime, "_legacy_openai_compatible_chat_adapter", FakeAdapter())

    assert agent_runtime.NativeRunEngine._openai_compatible_chat(
        "https://api.example.test/v1",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hello"}],
    ) == "legacy ok"
    assert calls == [
        {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-test",
            "messages": [{"role": "user", "content": "hello"}],
        }
    ]


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


def test_openai_compatible_chat_posts_chat_completion_request() -> None:
    calls: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        calls.append({
            "url": request.full_url,
            "headers": dict(request.header_items()),
            "body": request.data.decode("utf-8"),
            "timeout": timeout,
        })
        return FakeResponse(b'{"choices":[{"message":{"content":"custom ok"}}]}')

    result = openai_compatible_chat(
        "https://api.example.test/v1/",
        "demo-model",
        "sk-test",
        [{"role": "user", "content": "hello"}],
        timeout=12.5,
        urlopen=fake_urlopen,
        redact_error=str,
    )

    assert result == "custom ok"
    assert calls == [
        {
            "url": "https://api.example.test/v1/chat/completions",
            "headers": {
                "Content-type": "application/json",
                "Authorization": "Bearer sk-test",
            },
            "body": '{"model": "demo-model", "messages": [{"role": "user", "content": "hello"}], "temperature": 0.2}',
            "timeout": 12.5,
        }
    ]


def test_openai_compatible_chat_redacts_transport_errors() -> None:
    def failing_urlopen(_request: Any, *, timeout: float) -> FakeResponse:
        raise urlerror.URLError("token=sk-secret-value")

    with pytest.raises(AgentRuntimeError) as excinfo:
        openai_compatible_chat(
            "https://api.example.test/v1",
            "demo-model",
            "sk-test",
            [{"role": "user", "content": "hello"}],
            timeout=3,
            urlopen=failing_urlopen,
            redact_error=lambda value: str(value).replace("sk-secret-value", "[redacted]"),
        )

    assert "custom_api 调用失败" in str(excinfo.value)
    assert "sk-secret-value" not in str(excinfo.value)


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body
