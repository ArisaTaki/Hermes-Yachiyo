"""Approval generation isolation across public runtime entrypoints."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from apps.bridge.routes import agents as agent_routes
from apps.bridge.routes import (
    yachiyo_chat_handlers,
    yachiyo_services,
    yachiyo_studio_run_handlers,
)
from apps.shell.agent_runtime import AgentRuntimeError


class _UnexpectedApprovalService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def approve_run_approval(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("approve", args))
        return {"run_id": str(args[0]), "status": "running"}

    def reject_run_approval(self, *args: Any) -> dict[str, Any]:
        self.calls.append(("reject", args))
        return {"run_id": str(args[0]), "status": "cancelled"}


@pytest.mark.asyncio
async def test_public_approval_handlers_fail_closed_without_expected_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _UnexpectedApprovalService()
    agent_service = SimpleNamespace(
        approve=lambda *_args: runtime.calls.append(("chat-approve", _args)),
        reject=lambda *_args: runtime.calls.append(("chat-reject", _args)),
    )
    studio_service = SimpleNamespace(
        approve_run_approval=lambda *_args: runtime.calls.append(("studio-approve", _args)),
        reject_run_approval=lambda *_args: runtime.calls.append(("studio-reject", _args)),
    )
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: runtime)
    monkeypatch.setattr(yachiyo_chat_handlers, "agent_service", lambda _request=None: agent_service)
    monkeypatch.setattr(
        yachiyo_studio_run_handlers,
        "studio_service",
        lambda _request=None: studio_service,
    )

    calls = [
        lambda: agent_routes.approve_run_approval("run-1"),
        lambda: agent_routes.reject_run_approval("run-1"),
        lambda: agent_routes.approve_run_approval(
            "run-1",
            agent_routes.ApprovalRejectRequest(),
        ),
        lambda: agent_routes.reject_run_approval(
            "run-1",
            agent_routes.ApprovalRejectRequest(reason="no id"),
        ),
        lambda: yachiyo_chat_handlers.approve_task("task-1"),
        lambda: yachiyo_chat_handlers.reject_task("task-1"),
        lambda: yachiyo_studio_run_handlers.approve_run_approval("run-1"),
        lambda: yachiyo_studio_run_handlers.reject_run_approval("run-1"),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as missing:
            await call()
        assert missing.value.status_code == 400
    assert runtime.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_marker",
    [
        "approval_generation_mismatch",
        "approval_generation_projection_missing",
        "approval_generation_conflict",
    ],
)
async def test_public_approval_handler_maps_generation_errors_to_conflict(
    monkeypatch: pytest.MonkeyPatch,
    error_marker: str,
) -> None:
    class _StaleRuntime:
        @staticmethod
        def approve_run_approval(_run_id: str, _expected_approval_id: str) -> dict[str, Any]:
            raise AgentRuntimeError(error_marker)

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: _StaleRuntime())

    with pytest.raises(HTTPException) as stale:
        await agent_routes.approve_run_approval(
            "run-1",
            agent_routes.ApprovalRejectRequest(approval_id="approval-old"),
        )
    assert stale.value.status_code == 409
    assert yachiyo_services.bad_request(
        AgentRuntimeError(error_marker)
    ).status_code == 409
