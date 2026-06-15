"""Tests for helpers split out of the legacy agent runtime module."""

from __future__ import annotations

import json

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import (
    RuntimeRunEventRecorder,
    canonical_run_event_aliases,
    redact_json_value,
    redact_run_event_payload,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_event_redaction_helpers_match_runtime_json_alias() -> None:
    payload = {
        "command": "echo ok",
        "api_key": "sk-runtime-event-secret123456",
        "nested": ["token=sk-runtime-event-nested123456"],
    }

    split_payload = redact_run_event_payload(payload)
    split_json = redact_json_value(payload)
    legacy_json = agent_runtime._redact_json_value(payload)

    serialized = json.dumps(
        {
            "split_payload": split_payload,
            "split_json": split_json,
            "legacy_json": legacy_json,
        },
        ensure_ascii=False,
    )
    assert "sk-runtime-event-secret123456" not in serialized
    assert "sk-runtime-event-nested123456" not in serialized
    assert split_json == legacy_json


def test_runtime_run_event_recorder_appends_compatibility_aliases() -> None:
    class FakeRunEvents:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict[str, object] | None]] = []

        def append(
            self,
            run_id: str,
            event_type: str,
            payload: dict[str, object] | None = None,
            **_kwargs: object,
        ) -> dict[str, object]:
            sequence = len(self.calls) + 1
            self.calls.append((run_id, event_type, payload))
            return {
                "run_id": run_id,
                "event_type": event_type,
                "payload": payload or {},
                "sequence": sequence,
            }

        def list(self, run_id: str, **_kwargs: object) -> dict[str, object]:
            return {"ok": True, "run_id": run_id, "events": []}

    repository = FakeRunEvents()
    recorder = RuntimeRunEventRecorder(repository)

    event = recorder.append("run-1", "workflow.node.agent", {"status": "completed"})

    assert event["event_type"] == "workflow.node.agent"
    assert [call[1] for call in repository.calls] == [
        "workflow.node.agent",
        "workflow.node.started",
        "workflow.node.completed",
    ]
    assert canonical_run_event_aliases("model.output.completed") == ["model.completed"]
    assert agent_runtime._canonical_run_event_aliases("model.output.completed") == ["model.completed"]


def test_agent_runtime_service_uses_runtime_event_recorder_from_legacy_entrypoint(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runtime_events, RuntimeRunEventRecorder)

        run = service.start_main_chat_run(
            task_id="task-runtime-event-recorder",
            session_id="session-runtime-event-recorder",
            user_goal="record events",
        )
        service.append_run_event(run["run_id"], "workflow.run.completed", {"status": "completed"})
        event_types = [
            event["event_type"]
            for event in service.list_run_events(run["run_id"])["events"]
        ]

        assert "workflow.run.completed" in event_types
        assert "workflow.completed" in event_types
    finally:
        service.close()
