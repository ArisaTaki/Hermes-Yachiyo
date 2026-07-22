"""Tests for runtime credential helper split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.credentials import (
    RuntimeCredentialService,
    agent_model_credential_ref,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import CredentialStoreError, MemoryCredentialStore


def test_runtime_credential_service_stores_reads_and_deletes_model_secrets() -> None:
    store = MemoryCredentialStore()
    service = RuntimeCredentialService(store)
    ref = agent_model_credential_ref("agent-1")

    assert service.agent_model_ref("agent-1") == ref
    service.store(ref, "  sk-agent-secret123456  ")

    assert ref == "agent:agent-1:model_api_key"
    assert service.read(ref) == "sk-agent-secret123456"
    service.delete(ref)
    assert service.read(ref) == ""
    service.store(ref, "")
    assert service.read(ref) == ""


def test_runtime_credential_service_redacts_store_and_read_errors() -> None:
    class FailingCredentialStore:
        def get(self, _ref: str) -> str:
            raise CredentialStoreError("read failed sk-read-secret123456")

        def set(self, _ref: str, _secret: str) -> None:
            raise CredentialStoreError("write failed sk-write-secret123456")

        def delete(self, _ref: str) -> None:
            raise CredentialStoreError("delete failed sk-delete-secret123456")

    service = RuntimeCredentialService(FailingCredentialStore())

    with pytest.raises(AgentRuntimeError) as store_error:
        service.store("agent:agent-1:model_api_key", "sk-input-secret123456")
    with pytest.raises(AgentRuntimeError) as read_error:
        service.read("agent:agent-1:model_api_key")
    service.delete("agent:agent-1:model_api_key")

    assert "sk-write-secret123456" not in str(store_error.value)
    assert "sk-read-secret123456" not in str(read_error.value)
    assert "[redacted]" in str(store_error.value)
    assert "[redacted]" in str(read_error.value)
    assert store_error.value.__cause__ is None
    assert read_error.value.__cause__ is None


def test_runtime_credential_cleanup_never_surfaces_native_delete_errors() -> None:
    class UnexpectedDeleteFailure:
        def delete(self, _ref: str) -> None:
            raise RuntimeError("native cleanup failed sk-delete-secret123456")

    RuntimeCredentialService(UnexpectedDeleteFailure()).delete(
        "agent:agent-1:model_api_key"
    )


def test_runtime_credential_auth_failure_points_to_agent_studio_recovery() -> None:
    class InaccessibleAgentCredential:
        def get(self, _ref: str) -> str:
            raise CredentialStoreError(
                "应用更新后无法读取原有钥匙串凭据，请前往模型配置。",
                operation="find",
                os_status=-25293,
            )

    service = RuntimeCredentialService(InaccessibleAgentCredential())

    with pytest.raises(AgentRuntimeError) as error:
        service.read("agent:agent-1:model_api_key")

    assert "Agent Studio" in str(error.value)
    assert "重新保存 API Key" in str(error.value)
    assert "模型配置" not in str(error.value)


def test_runtime_credentials_remain_available_from_legacy_runtime_module() -> None:
    assert agent_runtime.RuntimeCredentialService is RuntimeCredentialService


def test_agent_runtime_service_credential_ref_delegates_to_runtime_credentials(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert service._agent_model_credential_ref("agent-1") == "agent:agent-1:model_api_key"
        assert service._agent_model_credential_ref("agent-1") == service.runtime_credentials.agent_model_ref("agent-1")
    finally:
        service.close()
