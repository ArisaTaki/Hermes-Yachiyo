"""Hermes-like Tool and Artifact RunEvent observability tests."""

from __future__ import annotations

import json

from apps.shell import agent_runtime
from apps.shell.agent.runtime.events import (
    RuntimeToolCallEventRecorder,
    ToolEventPayloadBuilder,
    artifact_created_payload,
    runtime_trace_input_preview,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_tool_event_payload_builder_remains_exported_and_redacts_inputs() -> None:
    builder = ToolEventPayloadBuilder()
    artifact_preview = {"path": "report.md", "content": "do not expose"}
    memory_preview = {"kind": "fact", "content": "private", "old_content": "old private"}

    assert agent_runtime.ToolEventPayloadBuilder is ToolEventPayloadBuilder
    assert runtime_trace_input_preview("artifact.write", artifact_preview) == {"path": "report.md"}
    assert runtime_trace_input_preview("memory.add", memory_preview) == {"kind": "fact"}
    assert builder.payload(
        "terminal.run",
        {"command": "echo ok", "API_KEY": "sk-secret-value"},
        pre_validation=True,
        status="requested",
    ) == {
        "tool": "terminal.run",
        "input_preview": {"redacted": True, "reason": "sensitive_input"},
        "approved": False,
        "status": "requested",
    }


def test_tool_event_payload_builder_projects_result_and_error() -> None:
    builder = ToolEventPayloadBuilder()

    payload = builder.payload(
        "workspace.read",
        {"path": "README.md"},
        approved=True,
        result={"ok": True, "content": "hello"},
        error=RuntimeError("sk-secret-value"),
        status="failed",
    )

    assert payload["tool"] == "workspace.read"
    assert payload["input_preview"] == {"path": "README.md"}
    assert payload["approved"] is True
    assert payload["status"] == "failed"
    assert payload["output_preview"] == {"ok": True, "content": "hello"}
    assert "sk-secret-value" not in payload["error"]


def test_artifact_created_payload_projects_structured_tool_artifacts() -> None:
    payload = artifact_created_payload(
        {
            "ok": True,
            "summary": "Captured screen",
            "artifact": {
                "path": "screenshots/current-screen.png",
                "kind": "image",
                "mime_type": "image/png",
                "size_bytes": 321,
                "width": 800,
                "height": 600,
            },
        },
        run_id="run-screen",
        source_tool="screen.capture",
    )

    assert payload["source_tool"] == "screen.capture"
    assert payload["kind"] == "image"
    assert payload["path"] == "screenshots/current-screen.png"
    assert payload["size_bytes"] == 321
    assert payload["artifact"] == {
        "artifact_id": "screenshots/current-screen.png",
        "kind": "image",
        "path": "screenshots/current-screen.png",
        "size_bytes": 321,
        "source_tool": "screen.capture",
        "mime_type": "image/png",
        "width": 800,
        "height": 600,
    }


def test_runtime_tool_call_event_recorder_records_lifecycle_events() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, object]) -> dict[str, object]:
        events.append((run_id, event_type, payload))
        return {"run_id": run_id, "event_type": event_type, "payload": payload}

    recorder = RuntimeToolCallEventRecorder(append_run_event=append_run_event)

    assert recorder.requested("", "workspace.read", {"path": "README.md"}) is None
    recorder.denied("run-1", "terminal.run", {"command": "rm -rf tmp"})
    recorder.requested("run-1", "workspace.read", {"path": "README.md"})
    recorder.started("run-1", "workspace.read", {"path": "README.md"}, approved=True)
    recorder.failed(
        "run-1",
        "terminal.run",
        {"command": "echo ok", "API_KEY": "sk-secret-value"},
        pre_validation=True,
        error=RuntimeError("sk-secret-value"),
    )
    recorder.result(
        "run-1",
        "terminal.run",
        {"command": "echo ok"},
        {"ok": False, "approval_required": True, "error": "needs approval"},
    )
    recorder.result(
        "run-1",
        "workspace.read",
        {"path": "README.md"},
        {"ok": True, "content": "hello"},
    )
    recorder.agent_tool_call(
        "run-1",
        "workspace.read",
        {"path": "README.md"},
        {"ok": True, "content": "hello"},
        approved=True,
    )

    event_types = [event_type for _run_id, event_type, _payload in events]
    failed_payload = events[3][2]

    assert event_types == [
        "agent.tool.denied",
        "tool.requested",
        "tool.started",
        "tool.failed",
        "tool.approval_required",
        "tool.completed",
        "agent.tool.call",
    ]
    assert failed_payload["input_preview"] == {"redacted": True, "reason": "sensitive_input"}
    assert "sk-secret-value" not in json.dumps(events, ensure_ascii=False)
    assert events[-1][2]["approved"] is True


def test_agent_runtime_service_uses_tool_call_event_recorder(tmp_path) -> None:
    service = _service(tmp_path)
    try:
        assert isinstance(service.runtime_tool_call_events, RuntimeToolCallEventRecorder)
    finally:
        service.close()


def test_agent_tool_call_emits_canonical_tool_events(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_workspace_read",
                        "type": "function",
                        "function": {
                            "name": "workspace_read",
                            "arguments": json.dumps({"path": "README.md"}),
                        },
                    }
                ],
            }
        return {"content": "Read complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = _custom_agent(
            service,
            "Tool Event Agent",
            tool_policy={"allowed_tools": ["workspace.read"]},
            workspace_policy={"default_workdir": str(workdir), "readable_scopes": ["."]},
        )
        run = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Read README"}
        )
        events = service.list_run_events(run["run_id"], limit=100)["events"]
        event_types = [event["event_type"] for event in events]
        requested = next(event for event in events if event["event_type"] == "tool.requested")
        completed = next(event for event in events if event["event_type"] == "tool.completed")

        assert event_types.index("tool.requested") < event_types.index("tool.started")
        assert event_types.index("tool.started") < event_types.index("tool.completed")
        assert event_types.index("tool.completed") < event_types.index("agent.tool.call")
        assert requested["payload"]["tool"] == "workspace.read"
        assert requested["payload"]["input_preview"]["path"] == "README.md"
        assert completed["payload"]["status"] == "completed"
        assert completed["payload"]["output_preview"]["ok"] is True
    finally:
        service.close()


def test_agent_artifact_write_emits_artifact_created_without_content(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_artifact_write",
                        "type": "function",
                        "function": {
                            "name": "artifact_write",
                            "arguments": json.dumps(
                                {
                                    "path": "notes.md",
                                    "content": "safe artifact body",
                                }
                            ),
                        },
                    }
                ],
            }
        return {"content": "Artifact complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = _custom_agent(
            service,
            "Artifact Event Agent",
            tool_policy={"allowed_tools": ["artifact.write"]},
        )
        run = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Write artifact"}
        )
        events = service.list_run_events(run["run_id"], limit=100)["events"]
        artifact_event = next(
            event
            for event in events
            if event["event_type"] == "artifact.created"
            and event["payload"].get("path") == "notes.md"
        )
        serialized_payload = json.dumps(artifact_event["payload"], ensure_ascii=False)

        assert artifact_event["payload"]["path"] == "notes.md"
        assert artifact_event["payload"]["size_bytes"] > 0
        assert artifact_event["payload"]["source_tool"] == "artifact.write"
        assert "safe artifact body" not in serialized_payload
        assert "content" not in serialized_payload
    finally:
        service.close()


def _service(tmp_path) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )


def _custom_agent(
    service: AgentRuntimeService,
    name: str,
    **overrides,
) -> dict:
    return service.create_agent(
        {
            "name": name,
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
            **overrides,
        }
    )
