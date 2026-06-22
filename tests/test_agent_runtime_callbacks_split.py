"""Tests for shared callback signature helpers split out of runtime services."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.callbacks import supports_keyword


def test_runtime_callback_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.supports_keyword is supports_keyword


def test_supports_keyword_accepts_named_keyword_and_kwargs() -> None:
    def named(*, workflow_run_id: str = "") -> None:
        return None

    def variadic(**_kwargs: Any) -> None:
        return None

    def positional(_value: str) -> None:
        return None

    assert supports_keyword(named, "workflow_run_id") is True
    assert supports_keyword(variadic, "workflow_run_id") is True
    assert supports_keyword(positional, "workflow_run_id") is False
