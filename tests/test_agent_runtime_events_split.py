"""Tests for helpers split out of the legacy agent runtime module."""

from __future__ import annotations

import json

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import (
    RuntimeRunEventRecorder,
    RuntimeTraceEventBuilder,
    artifact_created_payload,
    canonical_run_event_aliases,
    memory_retrieved_payload,
    memory_skill_trace_event,
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


def test_runtime_trace_event_builder_projects_artifact_memory_and_skill_facts() -> None:
    builder = RuntimeTraceEventBuilder()
    artifact_result = {
        "ok": True,
        "artifact_id": "artifact-1",
        "path": "notes.md",
        "bytes": 42,
        "content": "do not expose",
    }
    memory_result = {
        "ok": True,
        "action": "memory.add",
        "memory": {
            "memory_id": "mem-1",
            "kind": "preference",
            "scope": "global",
            "content": "private memory body",
        },
    }
    skill_result = {
        "ok": True,
        "skill_id": "skill-1",
        "name": "Demo Skill",
        "description": "Useful",
        "skill_markdown": "private skill body",
    }
    memories = [
        {
            "memory_id": "mem-1",
            "kind": "preference",
            "scope": "global",
            "content": "private memory body",
        }
    ]

    artifact_payload = builder.artifact_created_payload(artifact_result, run_id="run-1")
    memory_event = builder.memory_skill_trace_event(
        "memory.add",
        {"kind": "preference", "content": "private memory body"},
        memory_result,
    )
    skill_event = builder.memory_skill_trace_event(
        "skill.read",
        {"name": "Demo Skill"},
        skill_result,
    )
    retrieved_payload = builder.memory_retrieved_payload(memories)
    serialized = json.dumps(
        {
            "artifact": artifact_payload,
            "memory": memory_event,
            "skill": skill_event,
            "retrieved": retrieved_payload,
        },
        ensure_ascii=False,
    )

    assert artifact_payload == artifact_created_payload(artifact_result, run_id="run-1")
    assert artifact_payload["source_tool"] == "artifact.write"
    assert memory_event == memory_skill_trace_event(
        "memory.add",
        {"kind": "preference", "content": "private memory body"},
        memory_result,
    )
    assert memory_event is not None
    assert memory_event["event_type"] == "memory.write.add"
    assert memory_event["payload"]["input_preview"] == {"kind": "preference"}
    assert skill_event is not None
    assert skill_event["event_type"] == "skill.dispatch.read"
    assert skill_event["payload"]["result"]["skill_id"] == "skill-1"
    assert retrieved_payload == memory_retrieved_payload(memories)
    assert "do not expose" not in serialized
    assert "private memory body" not in serialized
    assert "private skill body" not in serialized
    assert "content" not in serialized


def test_legacy_trace_event_helpers_delegate_to_runtime_builder() -> None:
    artifact_result = {"ok": True, "path": "report.md", "bytes": 12}
    memory_result = {
        "ok": True,
        "action": "memory.remove",
        "memory": {
            "memory_id": "mem-2",
            "kind": "fact",
            "scope": "project",
            "deleted_at": "2026-06-15T00:00:00Z",
            "content": "removed secret body",
        },
    }
    memories = [memory_result["memory"]]

    assert agent_runtime._artifact_created_payload(
        artifact_result,
        run_id="run-2",
    ) == artifact_created_payload(artifact_result, run_id="run-2")
    assert agent_runtime._memory_skill_trace_event(
        "memory.remove",
        {"old_content": "removed secret body"},
        memory_result,
    ) == memory_skill_trace_event(
        "memory.remove",
        {"old_content": "removed secret body"},
        memory_result,
    )
    assert agent_runtime._memory_retrieved_payload(memories) == memory_retrieved_payload(memories)


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
