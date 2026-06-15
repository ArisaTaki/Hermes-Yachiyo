"""Tests for cancellation projections split out of the legacy agent runtime module."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.cancellation import (
    RunCancellationProjection,
    WorkflowCancellationProjectionCoordinator,
    WorkflowCancellationTarget,
)


def test_runtime_cancellation_projections_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowCancellationTarget is WorkflowCancellationTarget
    assert agent_runtime.RunCancellationProjection is RunCancellationProjection
    assert (
        agent_runtime.WorkflowCancellationProjectionCoordinator
        is WorkflowCancellationProjectionCoordinator
    )
