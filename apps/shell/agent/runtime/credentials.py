"""Runtime credential helpers for Agent model secrets."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.credential_store import CredentialStoreError
from packages.security import redact_api_error_text


def agent_model_credential_ref(agent_id: str) -> str:
    return f"agent:{agent_id}:model_api_key"


def _runtime_credential_error_message(exc: CredentialStoreError) -> str:
    if getattr(exc, "os_status", None) == -25293:
        return (
            "应用更新后无法读取原有钥匙串中的 API Key。"
            "请在 Agent Studio 中重新保存 API Key，然后重新测试连接。"
        )
    return redact_api_error_text(exc)


class RuntimeCredentialService:
    """Thin error-redacting facade over the configured credential store."""

    def __init__(self, credential_store: Any) -> None:
        self._credential_store = credential_store

    def agent_model_ref(self, agent_id: str) -> str:
        return agent_model_credential_ref(agent_id)

    def store(self, ref: str, secret: str) -> None:
        secret = str(secret or "").strip()
        if not secret:
            return
        try:
            self._credential_store.set(ref, secret)
        except CredentialStoreError as exc:
            raise AgentRuntimeError(_runtime_credential_error_message(exc)) from None

    def read(self, ref: str) -> str:
        ref = str(ref or "").strip()
        if not ref:
            return ""
        try:
            return self._credential_store.get(ref)
        except CredentialStoreError as exc:
            raise AgentRuntimeError(_runtime_credential_error_message(exc)) from None

    def delete(self, ref: str) -> None:
        ref = str(ref or "").strip()
        if not ref:
            return
        try:
            self._credential_store.delete(ref)
        except Exception:
            pass
