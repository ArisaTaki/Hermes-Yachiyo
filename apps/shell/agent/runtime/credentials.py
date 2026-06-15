"""Runtime credential helpers for Agent model secrets."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.credential_store import CredentialStoreError
from packages.security import redact_api_error_text


def agent_model_credential_ref(agent_id: str) -> str:
    return f"agent:{agent_id}:model_api_key"


class RuntimeCredentialService:
    """Thin error-redacting facade over the configured credential store."""

    def __init__(self, credential_store: Any) -> None:
        self._credential_store = credential_store

    def store(self, ref: str, secret: str) -> None:
        secret = str(secret or "").strip()
        if not secret:
            return
        try:
            self._credential_store.set(ref, secret)
        except CredentialStoreError as exc:
            raise AgentRuntimeError(redact_api_error_text(exc)) from exc

    def read(self, ref: str) -> str:
        ref = str(ref or "").strip()
        if not ref:
            return ""
        try:
            return self._credential_store.get(ref)
        except CredentialStoreError as exc:
            raise AgentRuntimeError(redact_api_error_text(exc)) from exc

    def delete(self, ref: str) -> None:
        ref = str(ref or "").strip()
        if not ref:
            return
        try:
            self._credential_store.delete(ref)
        except CredentialStoreError:
            pass
