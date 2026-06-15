"""Tests for run projection coordinators split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_projections import (
    ApprovalResumeProjectionCoordinator,
    RunProjectionCoordinator,
)


def test_run_projection_coordinators_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RunProjectionCoordinator is RunProjectionCoordinator
    assert (
        agent_runtime.ApprovalResumeProjectionCoordinator
        is ApprovalResumeProjectionCoordinator
    )
