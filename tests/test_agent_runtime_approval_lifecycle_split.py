"""Tests for approval lifecycle coordinator split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_lifecycle import ApprovalCoordinator


def test_approval_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.ApprovalCoordinator is ApprovalCoordinator
