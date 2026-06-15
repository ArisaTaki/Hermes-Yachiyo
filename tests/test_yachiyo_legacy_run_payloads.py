"""Legacy runtime payload projection regressions."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent.legacy_ports import (
    LegacyRunPayloadProjector,
    _chat_task_payload,
    _group_artifacts,
    _group_run_from_legacy_run_group,
)


def test_legacy_run_projector_preserves_chat_task_payload_shape() -> None:
    run = {
        "run_id": "run-123",
        "session_id": "chat-1",
        "user_goal": "Summarize the brief",
        "result": "Done",
        "timeline": [{"event_type": "run.started"}],
        "status": "completed",
    }

    payload = LegacyRunPayloadProjector().chat_task_payload(run)
    wrapper_payload = _chat_task_payload(run)

    assert payload == wrapper_payload
    assert payload["run_id"] == "run-123"
    assert payload["task_id"] == "run-123"
    assert payload["conversation_id"] == "chat-1"
    assert payload["title"] == "Summarize the brief"
    assert payload["summary"] == "Done"
    assert payload["recent_events"] == [{"event_type": "run.started"}]
    assert payload["open_in_studio_url"] == "#/agents?run_id=run-123"
    assert payload["status"] == "completed"


def test_legacy_run_projector_prefers_explicit_chat_task_fields() -> None:
    run = {
        "run_id": "run-123",
        "task_id": "task-456",
        "session_id": "chat-1",
        "runnable_name": "Writer",
        "summary": "Summary wins",
        "result": "Result fallback",
    }

    payload = LegacyRunPayloadProjector().chat_task_payload(
        run,
        conversation_id="conversation-override",
    )

    assert payload["task_id"] == "task-456"
    assert payload["conversation_id"] == "conversation-override"
    assert payload["title"] == "Writer"
    assert payload["summary"] == "Summary wins"
    assert payload["recent_events"] == []


def test_legacy_run_projector_preserves_group_run_payload_shape() -> None:
    runtime = _FakeRuntime(
        {
            "run-1": {
                "run_id": "run-1",
                "artifacts": [{"artifact_id": "artifact-1", "path": "out.md"}],
                "pending_approval": {"approval_id": "approval-1"},
            },
            "run-2": {
                "run_id": "run-2",
                "artifacts": [{"artifact_id": "artifact-2", "path": "plan.md"}],
            },
        }
    )
    run_group = {
        "run_group_id": "group-run-1",
        "group_id": "group-1",
        "title": "Studio group run",
        "summary": "Final answer",
        "status": "completed",
        "child_run_ids": ["run-1", "missing-run", "run-2"],
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:01:00Z",
    }

    payload = LegacyRunPayloadProjector().group_run_from_legacy_run_group(
        run_group,
        runtime,
    )
    wrapper_payload = _group_run_from_legacy_run_group(run_group, runtime)

    assert payload == wrapper_payload
    assert payload["run_group_id"] == "group-run-1"
    assert payload["group_run_id"] == "group-run-1"
    assert payload["group_id"] == "group-1"
    assert payload["title"] == "Studio group run"
    assert payload["status"] == "completed"
    assert payload["objective"] == "Final answer"
    assert [run["run_id"] for run in payload["runs"]] == ["run-1", "run-2"]
    assert payload["child_run_ids"] == ["run-1", "missing-run", "run-2"]
    assert payload["pending_approvals"] == [{"approval_id": "approval-1"}]
    assert payload["final_answer"] == "Final answer"
    assert payload["shared_artifacts"] == [
        {"artifact_id": "artifact-1", "path": "out.md", "source_run_id": "run-1"},
        {"artifact_id": "artifact-2", "path": "plan.md", "source_run_id": "run-2"},
    ]


def test_legacy_group_artifacts_ignores_non_dict_artifacts() -> None:
    runs = [
        {
            "run_id": "run-1",
            "artifacts": [
                {"artifact_id": "artifact-1"},
                "not-a-dict",
                None,
            ],
        }
    ]

    assert _group_artifacts(runs) == [
        {"artifact_id": "artifact-1", "source_run_id": "run-1"}
    ]


class _FakeRuntime:
    def __init__(self, runs: dict[str, dict[str, Any]]) -> None:
        self._runs = runs

    def get_run(self, run_id: str) -> dict[str, Any]:
        try:
            return self._runs[run_id]
        except KeyError:
            raise KeyError(run_id) from None
