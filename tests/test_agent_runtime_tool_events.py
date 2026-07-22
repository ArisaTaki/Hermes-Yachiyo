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
from apps.shell.agent.runtime.tool_execution import _tool_request_trace_payload
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


def test_artifact_created_payload_preserves_data_analysis_plan_metadata() -> None:
    payload = artifact_created_payload(
        {
            "ok": True,
            "summary": "Analyzed data",
            "artifact": {
                "path": "analysis-chart.png",
                "kind": "image",
                "planned_kind": "chart",
                "source_kind": "csv",
                "requested_outputs": ["report", "chart"],
                "manifest_index": 1,
                "mime_type": "image/png",
                "size_bytes": 321,
                "width": 640,
                "height": 360,
            },
        },
        run_id="run-data",
        source_tool="data.analyze",
    )

    assert payload["source_tool"] == "data.analyze"
    assert payload["kind"] == "image"
    assert payload["planned_kind"] == "chart"
    assert payload["source_kind"] == "csv"
    assert payload["requested_outputs"] == ["report", "chart"]
    assert payload["manifest_index"] == 1
    assert payload["artifact"]["kind"] == "image"
    assert payload["artifact"]["planned_kind"] == "chart"
    assert payload["artifact"]["source_kind"] == "csv"
    assert payload["artifact"]["requested_outputs"] == ["report", "chart"]
    assert payload["artifact"]["manifest_index"] == 1


def test_runtime_tool_call_event_recorder_records_lifecycle_events() -> None:
    events: list[tuple[str, str, dict[str, object]]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        events.append((run_id, event_type, payload))
        return {"run_id": run_id, "event_type": event_type, "payload": payload}

    recorder = RuntimeToolCallEventRecorder(append_run_event=append_run_event)
    trace = {
        "source": "runtime_planner",
        "step_id": "inspect-data-source",
        "capability_id": "file.workspace_read",
        "replan_request_id": "replan-1",
    }

    assert recorder.requested("", "workspace.read", {"path": "README.md"}) is None
    recorder.denied("run-1", "terminal.run", {"command": "rm -rf tmp"})
    recorder.requested("run-1", "workspace.read", {"path": "README.md"}, trace=trace)
    recorder.started(
        "run-1",
        "workspace.read",
        {"path": "README.md"},
        approved=True,
        trace=trace,
    )
    recorder.failed(
        "run-1",
        "terminal.run",
        {"command": "echo ok", "API_KEY": "sk-secret-value"},
        pre_validation=True,
        error=RuntimeError("sk-secret-value"),
        trace={**trace, "capability_id": "terminal.execution"},
    )
    recorder.result(
        "run-1",
        "terminal.run",
        {"command": "echo ok"},
        {"ok": False, "approval_required": True, "error": "needs approval"},
        trace={**trace, "capability_id": "terminal.execution"},
    )
    recorder.result(
        "run-1",
        "workspace.read",
        {"path": "README.md"},
        {"ok": True, "content": "hello"},
        trace=trace,
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
    assert events[1][2]["step_id"] == "inspect-data-source"
    assert events[2][2]["capability_id"] == "file.workspace_read"
    assert failed_payload["capability_id"] == "terminal.execution"
    assert events[5][2]["replan_request_id"] == "replan-1"
    assert "sk-secret-value" not in json.dumps(events, ensure_ascii=False)
    assert events[-1][2]["approved"] is True


def test_automatic_recovery_tool_events_are_persisted_as_internal() -> None:
    events: list[tuple[str, str, dict[str, object], str]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, object],
        *,
        visibility: str = "user",
    ) -> dict[str, object]:
        events.append((run_id, event_type, payload, visibility))
        return {
            "run_id": run_id,
            "event_type": event_type,
            "payload": payload,
            "visibility": visibility,
        }

    trace = _tool_request_trace_payload(
        {
            "tool_call_id": "recovery-list-1",
            "source": "runtime_replan_recovery",
            "planning_reason": "file_resolution_discovery",
        }
    )
    assert _tool_request_trace_payload(
        {
            "tool_call_id": "coordinator-list-1",
            "source": "runtime_internal_recovery",
            "planning_reason": "app_resolution_discovery",
        }
    )["visibility"] == "internal"
    recorder = RuntimeToolCallEventRecorder(append_run_event=append_run_event)

    recorder.started("run-1", "workspace.list", {"path": "."}, trace=trace)
    recorder.agent_tool_call(
        "run-1",
        "workspace.list",
        {"path": "."},
        {"ok": True, "entries": []},
        trace=trace,
    )

    assert trace["visibility"] == "internal"
    assert [event_type for _run_id, event_type, _payload, _visibility in events] == [
        "tool.started",
        "agent.tool.call",
    ]
    assert all(visibility == "internal" for *_rest, visibility in events)
    assert all(payload["visibility"] == "internal" for _, _, payload, _ in events)


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
        public_events = service.list_run_events(run["run_id"], limit=100)["events"]
        assert not any(
            event["event_type"]
            in {"tool.requested", "tool.started", "tool.completed", "agent.tool.call"}
            for event in public_events
        )
        events = service.list_run_events(
            run["run_id"], limit=100, include_internal=True
        )["events"]
        tool_lifecycle_events = [
            event
            for event in events
            if event["event_type"]
            in {"tool.requested", "tool.started", "tool.completed", "agent.tool.call"}
            and event["payload"].get("tool_call_id") == "call_workspace_read"
        ]
        event_types = [event["event_type"] for event in tool_lifecycle_events]
        requested = next(
            event
            for event in tool_lifecycle_events
            if event["event_type"] == "tool.requested"
        )
        completed = next(
            event
            for event in tool_lifecycle_events
            if event["event_type"] == "tool.completed"
        )

        assert event_types.index("tool.requested") < event_types.index("tool.started")
        assert event_types.index("tool.started") < event_types.index("tool.completed")
        assert event_types.index("tool.completed") < event_types.index("agent.tool.call")
        assert requested["payload"]["tool"] == "workspace.read"
        assert requested["payload"]["input_preview"]["path"] == "README.md"
        assert completed["payload"]["status"] == "completed"
        assert completed["payload"]["output_preview"]["ok"] is True
        assert {event["payload"]["tool_call_id"] for event in tool_lifecycle_events} == {
            "call_workspace_read"
        }
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
            {
                "agent_id": agent["agent_id"],
                "user_goal": 'Write exactly "safe artifact body" to notes.md',
            }
        )
        events = service.list_run_events(
            run["run_id"], limit=100, include_internal=True
        )["events"]
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
