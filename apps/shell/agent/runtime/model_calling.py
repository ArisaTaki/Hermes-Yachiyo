"""Model call compatibility helpers for runtime services."""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest

from apps.shell.agent.runtime.errors import AgentRuntimeError


def callable_accepts_keyword(func: Any, name: str) -> bool:
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())


def call_model_profile_chat_message(
    chat_message: Callable[..., Any],
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
) -> Any:
    kwargs: dict[str, Any] = {}
    if tools is not None:
        kwargs["tools"] = tools
    if stream and callable_accepts_keyword(chat_message, "stream"):
        kwargs["stream"] = True
    return chat_message(base_url, model, api_key, messages, **kwargs)


class RuntimeModelProfileChatAdapter:
    """Binds runtime model callers to the current model-profile chat function."""

    def __init__(self, *, chat_message_provider: Callable[[], Callable[..., Any]]) -> None:
        self._chat_message_provider = chat_message_provider

    def call(
        self,
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
    ) -> Any:
        return call_model_profile_chat_message(
            self._chat_message_provider(),
            base_url,
            model,
            api_key,
            messages,
            tools=tools,
            stream=stream,
        )


class RuntimeOpenAICompatibleChatAdapter:
    """Binds custom API chat calls to runtime transport dependencies."""

    def __init__(
        self,
        *,
        timeout_provider: Callable[[], float],
        urlopen: Callable[..., Any],
        redact_error: Callable[[Any], str],
    ) -> None:
        self._timeout_provider = timeout_provider
        self._urlopen = urlopen
        self._redact_error = redact_error

    def call(
        self,
        base_url: str,
        model: str,
        api_key: str,
        messages: list[dict[str, str]],
    ) -> str:
        return openai_compatible_chat(
            base_url,
            model,
            api_key,
            messages,
            timeout=self._timeout_provider(),
            urlopen=self._urlopen,
            redact_error=self._redact_error,
        )


def openai_compatible_chat(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, str]],
    *,
    timeout: float,
    urlopen: Callable[..., Any],
    redact_error: Callable[[Any], str],
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode("utf-8")
    request = urlrequest.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise AgentRuntimeError(f"custom_api 调用超时：等待响应超过 {timeout:g} 秒") from exc
    except (urlerror.URLError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError(f"custom_api 调用失败：{redact_error(exc)}") from exc
    return str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
