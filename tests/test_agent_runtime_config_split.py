"""Tests for runtime config and clock helpers split from the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.clock import iso_epoch, utc_now_iso
from apps.shell.agent.runtime.config import (
    DEFAULT_AGENT_IDS,
    EXECUTION_BACKENDS,
    FINAL_RUN_STATUSES,
    MAIN_CHAT_AGENT_ID,
    MARKET_AGENT_OPERATING_DOCTRINE,
    MEMORY_CONTENT_MAX_CHARS,
    MEMORY_CONTEXT_LIMIT,
    NATIVE_LIBRARY_SOURCE_TYPES,
    SKILL_SOURCE_TYPES,
    SYSTEM_AGENT_IDS,
    WORKFLOW_NODE_TYPES,
    is_active_run_status,
    is_native_library_source_type,
    normalize_execution_backend,
    normalize_skill_source_type,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError


def test_runtime_config_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime._EXECUTION_BACKENDS is EXECUTION_BACKENDS
    assert agent_runtime._MEMORY_CONTEXT_LIMIT == MEMORY_CONTEXT_LIMIT
    assert agent_runtime._MEMORY_CONTENT_MAX_CHARS == MEMORY_CONTENT_MAX_CHARS
    assert agent_runtime._FINAL_RUN_STATUSES is FINAL_RUN_STATUSES
    assert agent_runtime._WORKFLOW_NODE_TYPES is WORKFLOW_NODE_TYPES
    assert agent_runtime._NATIVE_LIBRARY_SOURCE_TYPES is NATIVE_LIBRARY_SOURCE_TYPES
    assert agent_runtime._SKILL_SOURCE_TYPES is SKILL_SOURCE_TYPES
    assert agent_runtime._MAIN_CHAT_AGENT_ID == MAIN_CHAT_AGENT_ID
    assert agent_runtime._SYSTEM_AGENT_IDS is SYSTEM_AGENT_IDS
    assert agent_runtime._DEFAULT_AGENT_IDS is DEFAULT_AGENT_IDS
    assert agent_runtime._MARKET_AGENT_OPERATING_DOCTRINE == MARKET_AGENT_OPERATING_DOCTRINE
    assert agent_runtime._is_active_run_status is is_active_run_status
    assert agent_runtime._normalize_execution_backend is normalize_execution_backend
    assert agent_runtime._normalize_skill_source_type is normalize_skill_source_type
    assert agent_runtime._is_native_library_source_type is is_native_library_source_type
    assert agent_runtime._now is utc_now_iso
    assert agent_runtime._iso_epoch is iso_epoch


def test_runtime_config_normalizes_legacy_execution_backends_to_native() -> None:
    assert normalize_execution_backend("") == "native_profile"
    assert normalize_execution_backend("native_profile") == "native_profile"
    assert normalize_execution_backend("yachiyo_profile") == "native_profile"
    assert normalize_execution_backend("external_cli") == "native_profile"
    with pytest.raises(AgentRuntimeError, match="execution_backend"):
        normalize_execution_backend("hermes_profile")


def test_runtime_config_classifies_run_and_skill_source_types() -> None:
    assert is_active_run_status("running") is True
    assert is_active_run_status("") is True
    assert is_active_run_status("completed") is False
    assert is_active_run_status("failed") is False
    assert normalize_skill_source_type(" native_global ") == "native_global"
    assert is_native_library_source_type("native_global") is True
    assert is_native_library_source_type("local_dir") is False


def test_runtime_clock_helpers_parse_iso_epoch() -> None:
    assert iso_epoch("1970-01-01T00:00:01+00:00") == 1.0
    assert "T" in utc_now_iso()
