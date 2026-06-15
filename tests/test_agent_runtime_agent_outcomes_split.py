"""Tests for Agent Run outcome projection split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_outcomes import RuntimeAgentRunOutcomeProjector
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeTimeline:
    def completed(self) -> dict[str, Any]:
        return {"event": "agent.completed"}

    def failed(self, error: str) -> dict[str, Any]:
        return {"event": "agent.failed", "error": error}


class FakeTaskModelEvents:
    def model_output_completed_payload(
        self,
        content: str,
        *,
        truncated: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "content": content,
            "truncated": truncated,
            "metadata": metadata or {},
        }


class FakeRunEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def completed(self, run_id: str, result: str) -> None:
        self.calls.append(("completed", run_id, result))

    def failed(self, run_id: str, error: str) -> None:
        self.calls.append(("failed", run_id, error))


class FakeOutput(str):
    output_truncated = True
    model_metadata = {"finish_reason": "stop"}


def _projector(
    *,
    run_events: list[tuple[str, str, dict[str, Any]]] | None = None,
    run_updates: list[tuple[str, dict[str, Any]]] | None = None,
    recorder: FakeRunEvents | None = None,
) -> RuntimeAgentRunOutcomeProjector:
    run_events = run_events if run_events is not None else []
    run_updates = run_updates if run_updates is not None else []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        run_updates.append((run_id, kwargs))
        return {"run_id": run_id, **kwargs}

    return RuntimeAgentRunOutcomeProjector(
        append_run_event=lambda run_id, event_type, payload: run_events.append((run_id, event_type, payload)),
        runtime_task_model_events=FakeTaskModelEvents(),
        runtime_agent_timeline=FakeTimeline(),
        runtime_agent_run_events=recorder or FakeRunEvents(),
        update_run=update_run,
        model_output_metadata=lambda value: getattr(value, "model_metadata", {}),
        redact_secrets=lambda value: str(value).replace("sk-secret", "[REDACTED]"),
    )


def test_agent_run_outcome_projector_projects_completed_run() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    run_updates: list[tuple[str, dict[str, Any]]] = []
    recorder = FakeRunEvents()
    timeline = [{"event": "agent.started"}]
    artifacts = [{"kind": "context", "path": "agent-context.md"}]

    result = _projector(
        run_events=run_events,
        run_updates=run_updates,
        recorder=recorder,
    ).completed(
        "run-1",
        FakeOutput("Done"),
        timeline=timeline,
        artifacts=artifacts,
    )

    assert run_events == [
        (
            "run-1",
            "model.output.completed",
            {
                "content": "Done",
                "truncated": True,
                "metadata": {"finish_reason": "stop"},
            },
        )
    ]
    assert timeline == [{"event": "agent.started"}, {"event": "agent.completed"}]
    assert recorder.calls == [("completed", "run-1", "Done")]
    assert run_updates == [
        (
            "run-1",
            {
                "status": "completed",
                "result": "Done",
                "timeline": timeline,
                "artifacts": artifacts,
                "pending_approval": None,
            },
        )
    ]
    assert result["status"] == "completed"
    assert result["result"] == "Done"


def test_agent_run_outcome_projector_projects_failed_run_with_redaction() -> None:
    run_updates: list[tuple[str, dict[str, Any]]] = []
    recorder = FakeRunEvents()
    timeline = [{"event": "agent.started"}]

    result = _projector(run_updates=run_updates, recorder=recorder).failed(
        "run-1",
        RuntimeError("provider leaked sk-secret"),
        timeline=timeline,
        artifacts=[],
    )

    assert timeline == [
        {"event": "agent.started"},
        {"event": "agent.failed", "error": "provider leaked [REDACTED]"},
    ]
    assert recorder.calls == [("failed", "run-1", "provider leaked [REDACTED]")]
    assert run_updates == [
        (
            "run-1",
            {
                "status": "failed",
                "result": "provider leaked [REDACTED]",
                "timeline": timeline,
                "artifacts": [],
                "pending_approval": None,
            },
        )
    ]
    assert result["status"] == "failed"
    assert result["result"] == "provider leaked [REDACTED]"


def test_native_runtime_uses_split_agent_run_outcome_projector(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeAgentRunOutcomeProjector is RuntimeAgentRunOutcomeProjector
        assert isinstance(service.agent_run_outcomes, RuntimeAgentRunOutcomeProjector)
    finally:
        service.close()
