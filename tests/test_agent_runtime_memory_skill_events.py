"""Memory and Skill RunEvent observability tests."""

from __future__ import annotations

import json

from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_agent_skill_read_emits_skill_dispatch_event(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    source = tmp_path / "demo-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: Demo Skill\ndescription: Use the demo operation.\n---\n\n# Demo Skill\n\nUseful instruction.",
        encoding="utf-8",
    )
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_skill_read",
                        "type": "function",
                        "function": {
                            "name": "skill_read",
                            "arguments": json.dumps({"name": "Demo Skill"}),
                        },
                    }
                ],
            }
        return {"content": "Skill instruction applied"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        skill = service.import_skill(str(source))
        agent = _custom_agent(service, "Skill Trace Agent")
        service.attach_skill(agent["agent_id"], skill["skill_id"])

        run = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Use Demo Skill"}
        )
        events = service.list_run_events(run["run_id"], limit=50)["events"]
        event_types = [event["event_type"] for event in events]
        skill_event = next(event for event in events if event["event_type"] == "skill.dispatch.read")
        selected_event = next(event for event in events if event["event_type"] == "skill.selected")

        assert "skill.selected" in event_types
        assert skill_event["payload"]["tool"] == "skill.read"
        assert skill_event["payload"]["status"] == "completed"
        assert skill_event["payload"]["result"]["skill_id"] == skill["skill_id"]
        assert skill_event["payload"]["result"]["name"] == "Demo Skill"
        assert "skill_markdown" not in skill_event["payload"]["result"]
        assert selected_event["payload"]["result"]["skill_id"] == skill["skill_id"]
    finally:
        service.close()


def test_agent_memory_add_emits_memory_write_event_without_memory_content(
    tmp_path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_memory_add",
                        "type": "function",
                        "function": {
                            "name": "memory_add",
                            "arguments": json.dumps(
                                {
                                    "content": "User prefers concise Chinese replies.",
                                    "kind": "preference",
                                    "scope": "global",
                                }
                            ),
                        },
                    }
                ],
            }
        return {"content": "Memory updated"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = _custom_agent(service, "Memory Trace Agent")

        run = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Remember my preference"}
        )
        events = service.list_run_events(run["run_id"], limit=50)["events"]
        memory_event = next(event for event in events if event["event_type"] == "memory.write.add")

        assert memory_event["payload"]["tool"] == "memory.add"
        assert memory_event["payload"]["status"] == "completed"
        assert memory_event["payload"]["result"]["action"] == "memory.add"
        assert memory_event["payload"]["result"]["kind"] == "preference"
        assert memory_event["payload"]["result"]["memory_id"]
        assert "content" not in memory_event["payload"]["result"]
        assert "concise Chinese" not in json.dumps(memory_event["payload"], ensure_ascii=False)
    finally:
        service.close()


def test_agent_run_emits_memory_retrieved_without_memory_content(tmp_path, monkeypatch) -> None:
    service = _service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        return {"content": "Memory context checked"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        memory = service.create_memory_item(
            {
                "content": "User prefers concise Chinese replies.",
                "kind": "preference",
                "scope": "global",
            }
        )
        agent = _custom_agent(service, "Memory Retrieval Agent")

        run = service.create_agent_run(
            {"agent_id": agent["agent_id"], "user_goal": "Use memory context"}
        )
        events = service.list_run_events(run["run_id"], limit=50)["events"]
        retrieved_event = next(event for event in events if event["event_type"] == "memory.retrieved")
        serialized_payload = json.dumps(retrieved_event["payload"], ensure_ascii=False)

        assert retrieved_event["payload"]["count"] >= 1
        assert retrieved_event["payload"]["memories"][0]["memory_id"] == memory["memory"]["memory_id"]
        assert retrieved_event["payload"]["memories"][0]["kind"] == "preference"
        assert "concise Chinese" not in serialized_payload
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


def _custom_agent(service: AgentRuntimeService, name: str) -> dict:
    return service.create_agent(
        {
            "name": name,
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
        }
    )
