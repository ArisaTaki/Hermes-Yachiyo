"""Tests for run request parsing split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_requests import RuntimeRunRequestParser
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_run_request_parser_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunRequestParser is RuntimeRunRequestParser


def test_run_request_parser_normalizes_client_request_id_aliases() -> None:
    parser = RuntimeRunRequestParser(contains_sensitive_text=lambda _value: False)

    assert parser.client_request_id_from_payload({"client_run_id": "  run-1  "}) == "run-1"
    assert parser.client_request_id_from_payload({"client_request_id": "request-1"}) == "request-1"
    assert parser.client_request_id_from_payload({"idempotency_key": "idempotency-1"}) == "idempotency-1"
    assert parser.client_request_id_from_payload({"client_run_id": "x" * 200}) == "x" * 128
    assert parser.client_request_id_from_payload({}) == ""


def test_run_request_parser_rejects_sensitive_client_request_id() -> None:
    parser = RuntimeRunRequestParser(
        contains_sensitive_text=lambda value: "secret" in str(value),
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match="不能包含 API key"):
        parser.client_request_id_from_payload({"idempotency_key": "secret-token"})


def test_native_runtime_uses_split_run_request_parser(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.run_request_parser, RuntimeRunRequestParser)
        assert service.agent_run_starter._client_request_id_from_payload.__self__ is service.run_request_parser
        assert service.workflow_run_starter._client_request_id_from_payload.__self__ is service.run_request_parser
    finally:
        service.close()
