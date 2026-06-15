"""Tests for task-run link repository split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository


def test_task_run_link_repository_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.TaskRunLinkRepository is TaskRunLinkRepository
