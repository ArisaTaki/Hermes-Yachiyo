"""Tests for helpers split out of the legacy agent runtime module."""

from __future__ import annotations

import json

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import (
    RuntimeAgentRunEventRecorder,
    RuntimeRunEventRecorder,
    RuntimeTaskEventRecorder,
    RuntimeTaskModelEventBuilder,
    RuntimeTraceEventBuilder,
    artifact_created_payload,
    canonical_run_event_aliases,
    canonical_tool_event_payload,
    canonical_tool_input_preview,
    agent_run_completed_payload,
    agent_run_failed_payload,
    agent_run_started_payload,
    memory_retrieved_payload,
    memory_skill_trace_event,
    memory_trace_result,
    model_request_failed_payload,
    model_request_started_payload,
    model_output_completed_payload,
    redact_json_value,
    redact_run_event_payload,
    redact_secrets,
    runtime_trace_input_preview,
    skill_trace_result,
    task_run_event_payload,
    tool_input_preview,
    tool_trace_status,
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
    assert agent_runtime.redact_secrets is redact_secrets


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
    assert canonical_run_event_aliases("agent.tool.started") == ["tool.started"]
    assert canonical_run_event_aliases("agent.tool.completed") == ["tool.completed"]
    assert canonical_run_event_aliases("agent.tool.failed") == ["tool.failed"]
    assert canonical_run_event_aliases("agent.tool.approval_required") == [
        "tool.approval_required"
    ]
    assert canonical_run_event_aliases("agent.tool.approval_approved") == [
        "tool.approved",
        "approval.approved",
    ]
    assert canonical_run_event_aliases("agent.tool.approval_rejected") == [
        "tool.rejected",
        "approval.rejected",
    ]
    assert canonical_run_event_aliases("agent.tool.approval_timeout") == [
        "approval.timeout"
    ]
    assert canonical_run_event_aliases("workflow.node.approval_approved") == [
        "approval.approved"
    ]
    assert canonical_run_event_aliases("workflow.node.approval_rejected") == [
        "approval.rejected"
    ]
    assert canonical_run_event_aliases("workflow.node.approval_timeout") == [
        "approval.timeout"
    ]
    assert agent_runtime._canonical_run_event_aliases("model.output.completed") == ["model.completed"]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "agent.tool.started",
        {"tool": "workspace.read", "status": "running"},
    )
    assert [call[1] for call in repository.calls] == [
        "agent.tool.started",
        "tool.started",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "agent.tool.completed",
        {"tool": "workspace.read", "status": "completed"},
    )
    assert [call[1] for call in repository.calls] == [
        "agent.tool.completed",
        "tool.completed",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "agent.tool.failed",
        {"tool": "terminal.run", "status": "failed"},
    )
    assert [call[1] for call in repository.calls] == [
        "agent.tool.failed",
        "tool.failed",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "agent.tool.approval_required",
        {"tool": "terminal.run", "status": "approval_required"},
    )
    assert [call[1] for call in repository.calls] == [
        "agent.tool.approval_required",
        "tool.approval_required",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "agent.tool.approval_approved",
        {"tool": "terminal.run", "status": "completed"},
    )
    assert [call[1] for call in repository.calls] == [
        "agent.tool.approval_approved",
        "tool.approved",
        "approval.approved",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "agent.tool.approval_rejected",
        {"tool": "terminal.run", "status": "cancelled"},
    )
    assert [call[1] for call in repository.calls] == [
        "agent.tool.approval_rejected",
        "tool.rejected",
        "approval.rejected",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "workflow.node.approval_approved",
        {"workflow_node_id": "approval-1", "status": "completed"},
    )
    assert [call[1] for call in repository.calls] == [
        "workflow.node.approval_approved",
        "approval.approved",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "workflow.node.approval_rejected",
        {"workflow_node_id": "approval-1", "status": "cancelled"},
    )
    assert [call[1] for call in repository.calls] == [
        "workflow.node.approval_rejected",
        "approval.rejected",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "agent.tool.approval_timeout",
        {"tool": "terminal.run", "status": "cancelled"},
    )
    assert [call[1] for call in repository.calls] == [
        "agent.tool.approval_timeout",
        "approval.timeout",
    ]

    repository.calls.clear()
    recorder.append(
        "run-1",
        "workflow.node.approval_timeout",
        {"workflow_node_id": "approval-1", "status": "cancelled"},
    )
    assert [call[1] for call in repository.calls] == [
        "workflow.node.approval_timeout",
        "approval.timeout",
    ]


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


def test_legacy_trace_event_helpers_are_runtime_reexports() -> None:
    assert agent_runtime._tool_input_preview is tool_input_preview
    assert agent_runtime._canonical_tool_event_payload is canonical_tool_event_payload
    assert agent_runtime._canonical_tool_input_preview is canonical_tool_input_preview
    assert agent_runtime._artifact_created_payload is artifact_created_payload
    assert agent_runtime._canonical_run_event_aliases is canonical_run_event_aliases
    assert agent_runtime._memory_skill_trace_event is memory_skill_trace_event
    assert agent_runtime._runtime_trace_input_preview is runtime_trace_input_preview
    assert agent_runtime._tool_trace_status is tool_trace_status
    assert agent_runtime._skill_trace_result is skill_trace_result
    assert agent_runtime._memory_trace_result is memory_trace_result
    assert agent_runtime._memory_retrieved_payload is memory_retrieved_payload
    assert agent_runtime._task_run_event_payload is task_run_event_payload


def test_runtime_task_model_event_builder_projects_task_and_model_payloads() -> None:
    builder = RuntimeTaskModelEventBuilder()

    request_payload = builder.model_request_started_payload(
        profile_id="profile-chat",
        model="demo-model",
        capability="chat",
        message_count=2,
    )
    failed_request_payload = builder.model_request_failed_payload(
        "api_key=sk-runtime-model-request123456",
    )
    model_payload = builder.model_output_completed_payload(
        "hello",
        truncated=True,
        metadata={
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "ignored": None,
        },
    )
    task_payload = builder.task_run_event_payload(
        task_id="task-1",
        run_id="run-1",
        session_id="session-1",
        status="completed",
        result="done sk-runtime-task-secret123456",
    )
    failed_payload = builder.task_run_event_payload(
        task_id="task-2",
        run_id="run-2",
        session_id="session-2",
        status="failed",
        error="api_key=sk-runtime-task-error123456",
    )
    serialized = json.dumps(
        {
            "task": task_payload,
            "failed": failed_payload,
        },
        ensure_ascii=False,
    )

    assert request_payload == {
        "profile_id": "profile-chat",
        "model": "demo-model",
        "capability": "chat",
        "message_count": 2,
    }
    assert request_payload == model_request_started_payload(
        profile_id="profile-chat",
        model="demo-model",
        capability="chat",
        message_count=2,
    )
    assert "sk-runtime-model-request123456" not in failed_request_payload["error"]
    assert failed_request_payload == model_request_failed_payload(
        "api_key=sk-runtime-model-request123456",
    )
    assert model_payload == {
        "content": "hello",
        "output_chars": 5,
        "truncated": True,
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 3, "completion_tokens": 2},
    }
    assert "ignored" not in model_payload
    assert model_payload == model_output_completed_payload(
        "hello",
        truncated=True,
        metadata={
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "ignored": None,
        },
    )
    assert task_payload["task_id"] == "task-1"
    assert task_payload["status"] == "completed"
    assert "sk-runtime-task-secret123456" not in task_payload["result"]
    assert failed_payload["status"] == "failed"
    assert "sk-runtime-task-error123456" not in failed_payload["error"]
    assert "sk-runtime-task-secret123456" not in serialized
    assert "sk-runtime-task-error123456" not in serialized


def test_legacy_task_model_helpers_delegate_to_runtime_builder() -> None:
    assert agent_runtime._model_output_completed_payload(
        "hello",
        truncated=True,
        metadata={"finish_reason": "stop", "ignored": None},
    ) == model_output_completed_payload(
        "hello",
        truncated=True,
        metadata={"finish_reason": "stop", "ignored": None},
    )
    assert agent_runtime._task_run_event_payload(
        task_id="task-3",
        run_id="run-3",
        session_id="session-3",
        status="running",
    ) == task_run_event_payload(
        task_id="task-3",
        run_id="run-3",
        session_id="session-3",
        status="running",
    )


def test_runtime_task_event_recorder_records_task_lifecycle_events() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, object]) -> None:
        events.append((run_id, event_type, payload))

    recorder = RuntimeTaskEventRecorder(append_run_event=append_run_event)

    recorder.started("run-1", task_id="task-1", session_id="session-1")
    recorder.completed(
        "run-1",
        task_id="task-1",
        session_id="session-1",
        result="done sk-task-lifecycle-secret123456",
    )
    recorder.failed(
        "run-2",
        task_id="task-2",
        session_id="session-2",
        error="api_key=sk-task-lifecycle-error123456",
    )
    serialized = json.dumps(events, ensure_ascii=False)

    assert [event_type for _run_id, event_type, _payload in events] == [
        "run.started",
        "task.created",
        "task.started",
        "task.linked",
        "task.completed",
        "run.completed",
        "task.failed",
        "run.failed",
    ]
    assert events[1][2] == {
        "task_id": "task-1",
        "run_id": "run-1",
        "session_id": "session-1",
        "status": "running",
    }
    assert events[4][2]["status"] == "completed"
    assert events[6][2]["status"] == "failed"
    assert "sk-task-lifecycle-secret123456" not in serialized
    assert "sk-task-lifecycle-error123456" not in serialized


def test_runtime_agent_run_event_recorder_records_agent_lifecycle_events() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, object]) -> None:
        events.append((run_id, event_type, payload))

    recorder = RuntimeAgentRunEventRecorder(append_run_event=append_run_event)

    recorder.started(
        "run-agent",
        agent_id="agent-1",
        agent_name="Researcher",
        backend="native_profile",
        runtime="oha_agent",
    )
    recorder.completed("run-agent", "final answer")
    recorder.failed("run-agent-2", "safe failure")

    assert [event_type for _run_id, event_type, _payload in events] == [
        "agent.run.started",
        "agent.run.completed",
        "agent.run.failed",
    ]
    assert events[0][2] == agent_run_started_payload(
        agent_id="agent-1",
        agent_name="Researcher",
        backend="native_profile",
        runtime="oha_agent",
    )
    assert events[1][2] == agent_run_completed_payload("final answer")
    assert events[2][2] == agent_run_failed_payload("safe failure")


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


def test_agent_runtime_service_uses_task_model_event_builder(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runtime_agent_run_events, RuntimeAgentRunEventRecorder)
        assert isinstance(service.runtime_task_model_events, RuntimeTaskModelEventBuilder)
        assert isinstance(service.runtime_task_events, RuntimeTaskEventRecorder)
    finally:
        service.close()
