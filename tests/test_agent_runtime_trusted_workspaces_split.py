"""Tests for trusted workspace repository split out of the legacy runtime."""

from __future__ import annotations

from apps.shell.agent.repositories.workspaces import TrustedWorkspaceRepository
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_native_runtime_uses_split_trusted_workspace_repository(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        trusted = service.trust_workspace(tmp_path, source="test")

        assert isinstance(service.trusted_workspaces, TrustedWorkspaceRepository)
        assert trusted["path"] == str(tmp_path.resolve())
        assert service.list_trusted_workspaces()["workspaces"][0]["source"] == "test"
    finally:
        service.close()
