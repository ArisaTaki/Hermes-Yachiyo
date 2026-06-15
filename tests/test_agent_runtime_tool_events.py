"""Hermes-like Tool and Artifact RunEvent observability tests."""

from __future__ import annotations

import json

from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


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
        artifact_event = next(event for event in events if event["event_type"] == "artifact.created")
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
