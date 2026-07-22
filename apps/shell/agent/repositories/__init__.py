"""Persistence boundaries for Agent runtime state."""

from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.memories import AgentMemoryStore, MemoryQuery
from apps.shell.agent.repositories.row_projections import RuntimeRowProjector
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.repositories.skill_folders import SkillFolderRepository
from apps.shell.agent.repositories.skills import SkillRepository
from apps.shell.agent.repositories.sqlite import (
    LockedConnection,
    LockedCursor,
    coerce_named_row,
    named_row_factory,
    open_locked_runtime_connection,
)
from apps.shell.agent.repositories.studio_deletions import StudioDeletionRepository
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.repositories.workspaces import TrustedWorkspaceRepository

__all__ = [
    "AgentDefinitionRepository",
    "AgentFutureTaskStore",
    "AgentMemoryStore",
    "MemoryQuery",
    "ApprovalRepository",
    "LockedConnection",
    "LockedCursor",
    "RunArtifactRepository",
    "RunEventRepository",
    "RunGroupRepository",
    "RunRepository",
    "RuntimeRowProjector",
    "SkillFolderRepository",
    "SkillRepository",
    "StudioDeletionRepository",
    "TaskRunLinkRepository",
    "TrustedWorkspaceRepository",
    "WorkflowRepository",
    "coerce_named_row",
    "named_row_factory",
    "open_locked_runtime_connection",
]
