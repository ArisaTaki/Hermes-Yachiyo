"""Model call compatibility helpers for runtime services."""

from __future__ import annotations

import inspect
from typing import Any, Callable


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
