"""Callable signature helpers shared by split runtime services."""

from __future__ import annotations

from inspect import Parameter, signature
from typing import Any


def supports_keyword(callback: Any, keyword: str) -> bool:
    try:
        parameters = signature(callback).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind == Parameter.VAR_KEYWORD or parameter.name == keyword
        for parameter in parameters
    )
