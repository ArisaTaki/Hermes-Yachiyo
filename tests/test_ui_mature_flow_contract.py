"""Mature UI flow contract tests that do not require a browser runner.

These tests exercise the Bridge functions that ChatView and AgentStudioView call
for the v0.5 preserved flows. They are intentionally synchronous wrappers around
async route functions so the current test environment can run them without
pytest-asyncio.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import apps.locald.screenshot as screenshot_mod
from apps.bridge.routes import agents, model_profiles, runs as run_routes, ui


def _load_screen_route_module():
    route_path = Path(__file__).resolve().parents[1] / "apps" / "bridge" / "routes" / "screen.py"
    spec = importlib.util.spec_from_file_location("_oha_mature_flow_screen_route", route_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chat_ui_bridge_contract_preserves_message_image_idempotency_attachment_and_cancel(monkeypatch, tmp_path):
    runtime = SimpleNamespace(name="runtime")
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    attachment_path = tmp_path / "screen.png"
    attachment_path.write_bytes(b"png")

    class FakeChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def send_message(self, text, attachments=None, runnable_id="", client_message_id=""):
            calls.append(
                (
                    "send",
                    {
                        "text": text,
                        "attachments": attachments or [],
                        "runnable_id": runnable_id,
                        "client_message_id": client_message_id,
                    },
                )
            )
            return {"ok": True, **calls[-1][1]}

        def cancel_current_tasks(self):
            calls.append(("cancel", {}))
            return {
                "ok": True,
                "cancelled_tasks": 1,
                "processing_count": 0,
                "is_processing": False,
                "messages": [{"id": "assistant-cancelled", "status": "failed"}],
            }

        def get_attachment_file(self, attachment_id):
            calls.append(("get_attachment_file", {"attachment_id": attachment_id}))
            return {
                "ok": True,
                "path": str(attachment_path),
                "mime_type": "image/png",
                "name": "screen.png",
            }

    monkeypatch.setattr(ui, "ChatAPI", FakeChatAPI)
    image_attachment = {
        "id": "pending-image",
        "name": "screen.png",
        "mime_type": "image/png",
        "data_url": "data:image/png;base64,AAAA",
    }

    sent = asyncio.run(
        ui.send_chat_message(
            ui.SendChatMessageRequest(
                text="帮我看这张图",
                attachments=[image_attachment],
                runnable_id="agent_design",
                client_message_id="client-message-1",
            )
        )
    )
    header_idempotent = asyncio.run(
        ui.send_chat_message(
            ui.SendChatMessageRequest(text="同一条消息"),
            SimpleNamespace(headers={"idempotency-key": "header-message-1"}),
        )
    )
    attachment_response = asyncio.run(ui.get_chat_attachment("pending-image"))
    cancelled = asyncio.run(ui.cancel_chat_session_tasks())

    assert sent["attachments"] == [image_attachment]
    assert sent["runnable_id"] == "agent_design"
    assert sent["client_message_id"] == "client-message-1"
    assert header_idempotent["client_message_id"] == "header-message-1"
    assert attachment_response.path == str(attachment_path)
    assert attachment_response.media_type == "image/png"
    assert attachment_response.filename == "screen.png"
    assert attachment_response.content_disposition_type == "inline"
    assert cancelled["cancelled_tasks"] == 1
    assert cancelled["is_processing"] is False
    assert [name for name, _payload in calls] == ["send", "send", "get_attachment_file", "cancel"]


def test_chat_ui_bridge_contract_preserves_session_lifecycle(monkeypatch):
    runtime = SimpleNamespace(name="runtime")
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def get_session_info(self):
            calls.append(("get_session_info", {}))
            return {
                "ok": True,
                "session_id": "session-current",
                "session_context": {"conversation_kind": "main"},
                "message_count": 2,
                "is_processing": False,
                "processing_count": 0,
                "approval_count": 0,
            }

        def list_sessions(self, limit=20, query=""):
            calls.append(("list_sessions", {"limit": limit, "query": query}))
            return {
                "ok": True,
                "current_session_id": "session-current",
                "query": query,
                "sessions": [
                    {
                        "session_id": "session-current",
                        "title": "NativeRunEngine 验收",
                        "conversation_kind": "main",
                    }
                ],
            }

        def load_session(self, session_id):
            calls.append(("load_session", {"session_id": session_id}))
            return {"ok": True, "session_id": session_id, "message_count": 4}

        def clear_session(self):
            calls.append(("clear_session", {}))
            return {
                "ok": True,
                "session_id": "session-new",
                "previous_session_id": "session-current",
                "cancelled_tasks": 0,
            }

        def discard_empty_current_session(self):
            calls.append(("discard_empty_current_session", {}))
            return {
                "ok": True,
                "discarded": True,
                "deleted_session_id": "session-new",
                "session_id": "session-current",
                "empty": False,
            }

        def delete_current_session(self):
            calls.append(("delete_current_session", {}))
            return {
                "ok": True,
                "deleted_session_id": "session-current",
                "session_id": "session-after-delete",
                "cancelled_tasks": 1,
                "remaining_sessions": 0,
                "empty": True,
            }

    monkeypatch.setattr(ui, "ChatAPI", FakeChatAPI)

    info = asyncio.run(ui.get_chat_session())
    sessions = asyncio.run(ui.list_chat_sessions(limit=0, query="NativeRunEngine 验收"))
    loaded = asyncio.run(
        ui.load_chat_session(ui.LoadChatSessionRequest(session_id="session-archived"))
    )
    cleared = asyncio.run(ui.clear_chat_session())
    discarded = asyncio.run(ui.discard_empty_chat_session())
    deleted = asyncio.run(ui.delete_chat_session())

    assert info["session_id"] == "session-current"
    assert sessions["query"] == "NativeRunEngine 验收"
    assert sessions["sessions"][0]["title"] == "NativeRunEngine 验收"
    assert loaded == {"ok": True, "session_id": "session-archived", "message_count": 4}
    assert cleared["previous_session_id"] == "session-current"
    assert discarded["discarded"] is True
    assert deleted["cancelled_tasks"] == 1
    assert calls == [
        ("get_session_info", {}),
        ("list_sessions", {"limit": 0, "query": "NativeRunEngine 验收"}),
        ("load_session", {"session_id": "session-archived"}),
        ("clear_session", {}),
        ("discard_empty_current_session", {}),
        ("delete_current_session", {}),
    ]


def test_chat_ui_bridge_contract_preserves_group_and_delegated_summary(monkeypatch):
    runtime = SimpleNamespace(name="runtime")
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)

    class FakeChatAPI:
        def __init__(self, received_runtime):
            assert received_runtime is runtime

        def create_group_session(self, *, name="", avatar_url="", participant_ids=None):
            payload = {
                "name": name,
                "avatar_url": avatar_url,
                "participant_ids": participant_ids or [],
            }
            calls.append(("create_group", payload))
            return {"ok": True, "session_id": "group-1", **payload}

        def update_group_session(self, session_id, *, name="", avatar_url="", participant_ids=None):
            payload = {
                "session_id": session_id,
                "name": name,
                "avatar_url": avatar_url,
                "participant_ids": participant_ids or [],
            }
            calls.append(("update_group", payload))
            return {"ok": True, **payload}

        def summarize_delegated_run(self, run_id):
            calls.append(("summarize_delegated_run", {"run_id": run_id}))
            return {
                "ok": True,
                "summary_created": True,
                "run_id": run_id,
                "task_id": "summary-task-1",
            }

    monkeypatch.setattr(ui, "ChatAPI", FakeChatAPI)

    created = asyncio.run(
        ui.create_chat_group(
            ui.CreateChatGroupRequest(
                name="产品群聊",
                avatar_url="data:image/png;base64,AAAA",
                participant_ids=["agent_design", "agent_coding"],
            )
        )
    )
    updated = asyncio.run(
        ui.update_chat_group(
            "group-1",
            ui.UpdateChatGroupRequest(
                name="产品群聊 v2",
                avatar_url="https://example.test/group.png",
                participant_ids=["agent_design"],
            ),
        )
    )
    summarized = asyncio.run(
        ui.summarize_delegated_run(
            ui.SummarizeDelegatedRunRequest(run_id="run_delegate_1")
        )
    )

    assert created["session_id"] == "group-1"
    assert created["participant_ids"] == ["agent_design", "agent_coding"]
    assert updated["name"] == "产品群聊 v2"
    assert updated["participant_ids"] == ["agent_design"]
    assert summarized == {
        "ok": True,
        "summary_created": True,
        "run_id": "run_delegate_1",
        "task_id": "summary-task-1",
    }
    assert [name for name, _payload in calls] == [
        "create_group",
        "update_group",
        "summarize_delegated_run",
    ]


def test_activity_store_bridge_contract_preserves_feed_detail_and_delete(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_list_activity_events(**kwargs):
        calls.append(("list_activity_events", kwargs))
        return {
            "ok": True,
            "events": [{"event_id": "activity-1", "phase": "tool_start"}],
        }

    def fake_get_activity_event_detail(event_id, *, limit=200):
        calls.append(("get_activity_event_detail", {"event_id": event_id, "limit": limit}))
        return {
            "ok": True,
            "event": {"event_id": event_id},
            "trace": [{"event_id": "activity-trace-1"}],
        }

    def fake_delete_activity_event(event_id):
        calls.append(("delete_activity_event", {"event_id": event_id}))
        return {"ok": True, "deleted": True, "event_id": event_id}

    def fake_delete_activity_events(event_ids):
        calls.append(("delete_activity_events", {"event_ids": event_ids}))
        return {"ok": True, "deleted": len(event_ids), "requested": len(event_ids)}

    monkeypatch.setattr(ui, "list_activity_events", fake_list_activity_events)
    monkeypatch.setattr(ui, "get_activity_event_detail", fake_get_activity_event_detail)
    monkeypatch.setattr(ui, "delete_activity_event", fake_delete_activity_event)
    monkeypatch.setattr(ui, "delete_activity_events", fake_delete_activity_events)

    feed = asyncio.run(
        ui.get_activity_events(
            query="terminal",
            status="running",
            tool="terminal.run",
            phase="tool_start",
            session_id="session-1",
            task_id="task-1",
            limit=25,
        )
    )
    detail = asyncio.run(ui.get_activity_event("activity-1", limit=50))
    deleted_one = asyncio.run(ui.delete_activity("activity-1"))
    deleted_many = asyncio.run(
        ui.delete_activity_events_route(
            ui.DeleteActivityEventsRequest(event_ids=["activity-2", "activity-3"])
        )
    )

    assert feed["events"][0]["event_id"] == "activity-1"
    assert detail["trace"] == [{"event_id": "activity-trace-1"}]
    assert deleted_one == {"ok": True, "deleted": True, "event_id": "activity-1"}
    assert deleted_many == {"ok": True, "deleted": 2, "requested": 2}
    assert calls == [
        (
            "list_activity_events",
            {
                "query": "terminal",
                "status": "running",
                "tool": "terminal.run",
                "phase": "tool_start",
                "session_id": "session-1",
                "task_id": "task-1",
                "limit": 25,
            },
        ),
        ("get_activity_event_detail", {"event_id": "activity-1", "limit": 50}),
        ("delete_activity_event", {"event_id": "activity-1"}),
        ("delete_activity_events", {"event_ids": ["activity-2", "activity-3"]}),
    ]


def test_model_profiles_bridge_contract_preserves_profile_lifecycle(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeModelProfileService:
        def list_profiles(self):
            calls.append(("list_profiles", {}))
            return {
                "ok": True,
                "profiles": [
                    {
                        "profile_id": "profile-chat",
                        "name": "Chat Model",
                        "capability": "chat",
                        "model": "gpt-test",
                    }
                ],
                "defaults": {"chat": "profile-chat"},
            }

        def create_profile(self, payload):
            calls.append(("create_profile", payload))
            return {
                "profile_id": "profile-chat",
                **payload,
            }

        def get_profile(self, profile_id):
            calls.append(("get_profile", {"profile_id": profile_id}))
            return {
                "profile_id": profile_id,
                "name": "Chat Model",
                "capability": "chat",
            }

        def update_profile(self, profile_id, payload):
            calls.append(("update_profile", {"profile_id": profile_id, **payload}))
            return {
                "profile_id": profile_id,
                **payload,
            }

        def set_defaults(self, payload):
            calls.append(("set_defaults", payload))
            return {"ok": True, "defaults": payload}

        def test_profile(self, profile_id):
            calls.append(("test_profile", {"profile_id": profile_id}))
            return {
                "ok": True,
                "success": True,
                "message": "OK",
                "profile": {"profile_id": profile_id, "status": "available"},
            }

        def delete_profile(self, profile_id):
            calls.append(("delete_profile", {"profile_id": profile_id}))
            return {"ok": True, "profile_id": profile_id}

    monkeypatch.setattr(model_profiles, "get_model_profile_service", lambda: FakeModelProfileService())

    listed = asyncio.run(model_profiles.list_model_profiles())
    created = asyncio.run(
        model_profiles.create_model_profile(
            model_profiles.ModelProfileRequest(
                source_id="source-openai",
                name="Chat Model",
                capability="chat",
                provider="openai_compatible",
                base_url="https://api.example.test/v1",
                model="gpt-test",
                enabled=True,
            )
        )
    )
    fetched = asyncio.run(model_profiles.get_model_profile("profile-chat"))
    updated = asyncio.run(
        model_profiles.update_model_profile(
            "profile-chat",
            model_profiles.ModelProfileRequest(name="Chat Model v2", model="gpt-test-2", enabled=False),
        )
    )
    defaults = asyncio.run(
        model_profiles.update_model_profile_defaults(
            model_profiles.ModelProfileDefaultsRequest(chat="profile-chat", vision="profile-vision")
        )
    )
    tested = asyncio.run(model_profiles.test_model_profile("profile-chat"))
    deleted = asyncio.run(model_profiles.delete_model_profile("profile-chat"))

    assert listed["defaults"] == {"chat": "profile-chat"}
    assert created["source_id"] == "source-openai"
    assert created["model"] == "gpt-test"
    assert fetched["profile_id"] == "profile-chat"
    assert updated == {
        "profile_id": "profile-chat",
        "name": "Chat Model v2",
        "model": "gpt-test-2",
        "enabled": False,
    }
    assert defaults == {"ok": True, "defaults": {"chat": "profile-chat", "vision": "profile-vision"}}
    assert tested["profile"]["status"] == "available"
    assert deleted == {"ok": True, "profile_id": "profile-chat"}
    assert calls == [
        ("list_profiles", {}),
        (
            "create_profile",
            {
                "source_id": "source-openai",
                "name": "Chat Model",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "model": "gpt-test",
                "enabled": True,
            },
        ),
        ("get_profile", {"profile_id": "profile-chat"}),
        ("update_profile", {"profile_id": "profile-chat", "name": "Chat Model v2", "model": "gpt-test-2", "enabled": False}),
        ("set_defaults", {"chat": "profile-chat", "vision": "profile-vision"}),
        ("test_profile", {"profile_id": "profile-chat"}),
        ("delete_profile", {"profile_id": "profile-chat"}),
    ]


def test_model_profiles_bridge_contract_preserves_source_lifecycle(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeModelProfileService:
        def list_sources(self):
            calls.append(("list_sources", {}))
            return {
                "ok": True,
                "sources": [
                    {
                        "source_id": "source-openai",
                        "name": "OpenAI Compatible",
                        "capability": "chat",
                        "provider": "openai_compatible",
                    }
                ],
            }

        def create_source(self, payload):
            calls.append(("create_source", payload))
            return {
                "source_id": payload.get("source_id", "source-openai"),
                **payload,
            }

        def get_source(self, source_id):
            calls.append(("get_source", {"source_id": source_id}))
            return {
                "source_id": source_id,
                "name": "OpenAI Compatible",
                "capability": "chat",
                "provider": "openai_compatible",
            }

        def update_source(self, source_id, payload):
            calls.append(("update_source", {"source_id": source_id, **payload}))
            return {
                "source_id": source_id,
                **payload,
            }

        def test_source(self, source_id, payload):
            calls.append(("test_source", {"source_id": source_id, **payload}))
            return {
                "ok": True,
                "success": True,
                "message": "OK",
                "source": {"source_id": source_id},
            }

        def fetch_source_models(self, source_id):
            calls.append(("fetch_source_models", {"source_id": source_id}))
            return {
                "ok": True,
                "models": [{"id": "gpt-test", "name": "GPT Test"}],
                "count": 1,
                "source": {"source_id": source_id},
            }

        def delete_source(self, source_id):
            calls.append(("delete_source", {"source_id": source_id}))
            return {"ok": True, "source_id": source_id}

    monkeypatch.setattr(model_profiles, "get_model_profile_service", lambda: FakeModelProfileService())

    listed = asyncio.run(model_profiles.list_model_sources())
    created = asyncio.run(
        model_profiles.create_model_source(
            model_profiles.ModelSourceRequest(
                source_id="source-openai",
                name="OpenAI Compatible",
                capability="chat",
                provider="openai_compatible",
                base_url="https://api.example.test/v1",
                api_key="placeholder-key",
                enabled=True,
                options={"timeout_seconds": 15},
            )
        )
    )
    fetched = asyncio.run(model_profiles.get_model_source("source-openai"))
    updated = asyncio.run(
        model_profiles.update_model_source(
            "source-openai",
            model_profiles.ModelSourceRequest(
                name="OpenAI Compatible v2",
                enabled=False,
                options={"timeout_seconds": 5},
            ),
        )
    )
    tested = asyncio.run(
        model_profiles.test_model_source(
            "source-openai",
            model_profiles.ModelSourceTestRequest(model="gpt-test"),
        )
    )
    models = asyncio.run(model_profiles.fetch_model_source_models("source-openai"))
    deleted = asyncio.run(model_profiles.delete_model_source("source-openai"))

    assert listed["sources"][0]["source_id"] == "source-openai"
    assert created["base_url"] == "https://api.example.test/v1"
    assert created["options"] == {"timeout_seconds": 15}
    assert fetched["provider"] == "openai_compatible"
    assert updated == {
        "source_id": "source-openai",
        "name": "OpenAI Compatible v2",
        "enabled": False,
        "options": {"timeout_seconds": 5},
    }
    assert tested["source"]["source_id"] == "source-openai"
    assert models["models"] == [{"id": "gpt-test", "name": "GPT Test"}]
    assert deleted == {"ok": True, "source_id": "source-openai"}
    assert calls == [
        ("list_sources", {}),
        (
            "create_source",
            {
                "source_id": "source-openai",
                "name": "OpenAI Compatible",
                "capability": "chat",
                "provider": "openai_compatible",
                "base_url": "https://api.example.test/v1",
                "api_key": "placeholder-key",
                "enabled": True,
                "options": {"timeout_seconds": 15},
            },
        ),
        ("get_source", {"source_id": "source-openai"}),
        (
            "update_source",
            {
                "source_id": "source-openai",
                "name": "OpenAI Compatible v2",
                "enabled": False,
                "options": {"timeout_seconds": 5},
            },
        ),
        ("test_source", {"source_id": "source-openai", "model": "gpt-test"}),
        ("fetch_source_models", {"source_id": "source-openai"}),
        ("delete_source", {"source_id": "source-openai"}),
    ]


def test_run_detail_approval_bridge_contract_preserves_approve_reject_and_cancel(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    class FakeRuntimeService:
        def approve_run_approval(self, run_id):
            calls.append(("approve", run_id, ""))
            return {"run_id": run_id, "status": "running", "pending_approval": {}}

        def reject_run_approval(self, run_id, reason):
            calls.append(("reject", run_id, reason))
            return {"run_id": run_id, "status": "cancelled", "result": reason}

        def cancel_run(self, run_id):
            calls.append(("cancel", run_id, ""))
            return {"run_id": run_id, "status": "cancelled"}

    monkeypatch.setattr(agents, "get_agent_runtime_service", lambda: FakeRuntimeService())

    approved = asyncio.run(agents.approve_run_approval("run_approval"))
    rejected = asyncio.run(
        agents.reject_run_approval(
            "run_reject",
            agents.ApprovalRejectRequest(reason="Rejected from chat"),
        )
    )
    cancelled = asyncio.run(agents.cancel_run("run_cancel"))

    assert approved == {"run_id": "run_approval", "status": "running", "pending_approval": {}}
    assert rejected == {"run_id": "run_reject", "status": "cancelled", "result": "Rejected from chat"}
    assert cancelled == {"run_id": "run_cancel", "status": "cancelled"}
    assert calls == [
        ("approve", "run_approval", ""),
        ("reject", "run_reject", "Rejected from chat"),
        ("cancel", "run_cancel", ""),
    ]


def test_agent_studio_bridge_contract_preserves_agent_definition_lifecycle(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeRuntimeService:
        def list_agents(self):
            calls.append(("list_agents", {}))
            return {
                "agents": [
                    {
                        "agent_id": "agent-1",
                        "name": "Native Agent",
                        "execution_backend": "native_profile",
                        "enabled": True,
                    }
                ]
            }

        def create_agent(self, payload):
            calls.append(("create_agent", payload))
            return {
                "agent_id": "agent-1",
                "execution_backend": "native_profile",
                **payload,
            }

        def update_agent(self, agent_id, payload):
            calls.append(("update_agent", {"agent_id": agent_id, **payload}))
            return {
                "agent_id": agent_id,
                "execution_backend": "native_profile",
                **payload,
            }

        def delete_agent(self, agent_id):
            calls.append(("delete_agent", {"agent_id": agent_id}))
            return {"ok": True, "agent_id": agent_id}

    monkeypatch.setattr(agents, "get_agent_runtime_service", lambda: FakeRuntimeService())

    agent_request = agents.AgentRequest(
        name="Native Agent",
        nickname="Worker",
        instructions="Use NativeRunEngine.",
        model_mode="profile",
        model_profile_id="profile-main",
        tool_policy={"allowed_tools": ["workspace.read"]},
        workspace_policy={"readable_scopes": ["workspace"]},
        skill_ids=["skill-1"],
        enabled=True,
    )

    listed = asyncio.run(agents.list_agents())
    created = asyncio.run(agents.create_agent(agent_request))
    updated = asyncio.run(
        agents.update_agent(
            "agent-1",
            agents.AgentRequest(
                name="Native Agent v2",
                instructions="Updated native instructions.",
                model_mode="custom_api",
                model_config={"provider": "openai_compatible", "model": "fake-model"},
                enabled=False,
            ),
        )
    )
    deleted = asyncio.run(agents.delete_agent("agent-1"))

    assert listed["agents"][0]["execution_backend"] == "native_profile"
    assert created["name"] == "Native Agent"
    assert created["tool_policy"] == {"allowed_tools": ["workspace.read"]}
    assert updated == {
        "agent_id": "agent-1",
        "execution_backend": "native_profile",
        "name": "Native Agent v2",
        "instructions": "Updated native instructions.",
        "model_mode": "custom_api",
        "model_config": {"provider": "openai_compatible", "model": "fake-model"},
        "enabled": False,
    }
    assert deleted == {"ok": True, "agent_id": "agent-1"}
    assert calls == [
        ("list_agents", {}),
        (
            "create_agent",
            {
                "name": "Native Agent",
                "nickname": "Worker",
                "instructions": "Use NativeRunEngine.",
                "model_mode": "profile",
                "model_profile_id": "profile-main",
                "tool_policy": {"allowed_tools": ["workspace.read"]},
                "workspace_policy": {"readable_scopes": ["workspace"]},
                "skill_ids": ["skill-1"],
                "enabled": True,
            },
        ),
        (
            "update_agent",
            {
                "agent_id": "agent-1",
                "name": "Native Agent v2",
                "instructions": "Updated native instructions.",
                "model_mode": "custom_api",
                "model_config": {"provider": "openai_compatible", "model": "fake-model"},
                "enabled": False,
            },
        ),
        ("delete_agent", {"agent_id": "agent-1"}),
    ]


def test_skill_library_bridge_contract_preserves_skill_lifecycle(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeRuntimeService:
        def list_skills(self):
            calls.append(("list_skills", {}))
            return {
                "skills": [
                    {
                        "skill_id": "skill-1",
                        "name": "Native Skill",
                        "source_type": "native_global",
                        "enabled": True,
                    }
                ]
            }

        def import_skill(self, source_path, folder_id=None):
            calls.append(("import_skill", {"source_path": source_path, "folder_id": folder_id}))
            return {
                "skill_id": "skill-imported",
                "name": "Imported Skill",
                "source_path": source_path,
                "folder_id": folder_id,
                "enabled": True,
            }

        def list_native_skill_sources(self):
            calls.append(("list_native_skill_sources", {}))
            return {
                "roots": [
                    {
                        "source_type": "native_global",
                        "path": "/tmp/native-skills",
                        "exists": True,
                        "skill_count": 1,
                    }
                ]
            }

        def sync_native_skills(self):
            calls.append(("sync_native_skills", {}))
            return {
                "ok": True,
                "results": [{"source": "native_global", "status": "success"}],
            }

        def install_skill_command(self, command, folder_id=None):
            calls.append(("install_skill_command", {"command": command, "folder_id": folder_id}))
            return {
                "ok": True,
                "returncode": 0,
                "stdout": "installed",
                "folder_id": folder_id,
            }

        def get_skill(self, skill_id):
            calls.append(("get_skill", {"skill_id": skill_id}))
            return {
                "skill_id": skill_id,
                "name": "Native Skill",
                "enabled": True,
            }

        def update_skill(self, skill_id, payload):
            calls.append(("update_skill", {"skill_id": skill_id, **payload}))
            return {
                "skill_id": skill_id,
                "name": "Native Skill",
                **payload,
            }

        def delete_skill(self, skill_id):
            calls.append(("delete_skill", {"skill_id": skill_id}))
            return {"ok": True, "skill_id": skill_id}

    monkeypatch.setattr(agents, "get_agent_runtime_service", lambda: FakeRuntimeService())

    listed = asyncio.run(agents.list_skills())
    imported = asyncio.run(
        agents.import_skill(
            agents.SkillImportRequest(source_path="/tmp/installed-skill", folder_id="folder-1")
        )
    )
    sources = asyncio.run(agents.list_skill_sources())
    synced = asyncio.run(agents.sync_native_skills())
    installed = asyncio.run(
        agents.install_skill(
            agents.SkillInstallRequest(command="npx skills add owner/repo", folder_id="folder-1")
        )
    )
    skill = asyncio.run(agents.get_skill("skill-1"))
    updated = asyncio.run(
        agents.update_skill(
            "skill-1",
            agents.SkillUpdateRequest(enabled=False, folder_id="folder-2"),
        )
    )
    deleted = asyncio.run(agents.delete_skill("skill-1"))

    assert listed["skills"][0]["source_type"] == "native_global"
    assert imported["source_path"] == "/tmp/installed-skill"
    assert imported["folder_id"] == "folder-1"
    assert sources["roots"][0]["path"] == "/tmp/native-skills"
    assert synced["results"][0]["status"] == "success"
    assert installed["stdout"] == "installed"
    assert skill["skill_id"] == "skill-1"
    assert updated == {
        "skill_id": "skill-1",
        "name": "Native Skill",
        "enabled": False,
        "folder_id": "folder-2",
    }
    assert deleted == {"ok": True, "skill_id": "skill-1"}
    assert calls == [
        ("list_skills", {}),
        ("import_skill", {"source_path": "/tmp/installed-skill", "folder_id": "folder-1"}),
        ("list_native_skill_sources", {}),
        ("sync_native_skills", {}),
        ("install_skill_command", {"command": "npx skills add owner/repo", "folder_id": "folder-1"}),
        ("get_skill", {"skill_id": "skill-1"}),
        ("update_skill", {"skill_id": "skill-1", "enabled": False, "folder_id": "folder-2"}),
        ("delete_skill", {"skill_id": "skill-1"}),
    ]


def test_skill_library_bridge_contract_preserves_folders_and_agent_mounts(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeRuntimeService:
        def attach_skill(self, agent_id, skill_id):
            calls.append(("attach_skill", {"agent_id": agent_id, "skill_id": skill_id}))
            return {"agent_id": agent_id, "skill_ids": [skill_id]}

        def detach_skill(self, agent_id, skill_id):
            calls.append(("detach_skill", {"agent_id": agent_id, "skill_id": skill_id}))
            return {"agent_id": agent_id, "skill_ids": []}

        def list_skill_folders(self):
            calls.append(("list_skill_folders", {}))
            return {
                "folders": [
                    {
                        "folder_id": "folder-1",
                        "name": "Installed",
                        "skill_count": 2,
                    }
                ]
            }

        def create_skill_folder(self, payload):
            calls.append(("create_skill_folder", payload))
            return {
                "folder_id": "folder-1",
                **payload,
            }

        def update_skill_folder(self, folder_id, payload):
            calls.append(("update_skill_folder", {"folder_id": folder_id, **payload}))
            return {
                "folder_id": folder_id,
                **payload,
            }

        def delete_skill_folder(self, folder_id, *, delete_skills=False):
            calls.append(("delete_skill_folder", {"folder_id": folder_id, "delete_skills": delete_skills}))
            return {
                "ok": True,
                "folder_id": folder_id,
                "delete_skills": delete_skills,
                "deleted_skill_count": 2 if delete_skills else 0,
            }

    monkeypatch.setattr(agents, "get_agent_runtime_service", lambda: FakeRuntimeService())

    attached = asyncio.run(
        agents.attach_agent_skill("agent-1", agents.AgentSkillRequest(skill_id="skill-1"))
    )
    detached = asyncio.run(agents.detach_agent_skill("agent-1", "skill-1"))
    folders = asyncio.run(agents.list_skill_folders())
    created = asyncio.run(
        agents.create_skill_folder(
            agents.SkillFolderRequest(name="Installed", description="Installed skills")
        )
    )
    updated = asyncio.run(
        agents.update_skill_folder(
            "folder-1",
            agents.SkillFolderRequest(name="Renamed", sort_order=20),
        )
    )
    deleted = asyncio.run(agents.delete_skill_folder("folder-1", delete_skills=True))

    assert attached == {"agent_id": "agent-1", "skill_ids": ["skill-1"]}
    assert detached == {"agent_id": "agent-1", "skill_ids": []}
    assert folders["folders"][0]["skill_count"] == 2
    assert created == {
        "folder_id": "folder-1",
        "name": "Installed",
        "description": "Installed skills",
    }
    assert updated == {
        "folder_id": "folder-1",
        "name": "Renamed",
        "sort_order": 20,
    }
    assert deleted == {
        "ok": True,
        "folder_id": "folder-1",
        "delete_skills": True,
        "deleted_skill_count": 2,
    }
    assert calls == [
        ("attach_skill", {"agent_id": "agent-1", "skill_id": "skill-1"}),
        ("detach_skill", {"agent_id": "agent-1", "skill_id": "skill-1"}),
        ("list_skill_folders", {}),
        ("create_skill_folder", {"name": "Installed", "description": "Installed skills"}),
        ("update_skill_folder", {"folder_id": "folder-1", "name": "Renamed", "sort_order": 20}),
        ("delete_skill_folder", {"folder_id": "folder-1", "delete_skills": True}),
    ]


def test_workflow_studio_bridge_contract_preserves_definition_lifecycle(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeRuntimeService:
        def list_workflows(self):
            calls.append(("list_workflows", {}))
            return {
                "workflows": [
                    {
                        "workflow_id": "workflow-1",
                        "name": "Native Workflow",
                        "enabled": True,
                    }
                ]
            }

        def create_workflow(self, payload):
            calls.append(("create_workflow", payload))
            return {
                "workflow_id": "workflow-1",
                **payload,
            }

        def update_workflow(self, workflow_id, payload):
            calls.append(("update_workflow", {"workflow_id": workflow_id, **payload}))
            return {
                "workflow_id": workflow_id,
                **payload,
            }

        def delete_workflow(self, workflow_id):
            calls.append(("delete_workflow", {"workflow_id": workflow_id}))
            return {"ok": True, "workflow_id": workflow_id}

    monkeypatch.setattr(agents, "get_agent_runtime_service", lambda: FakeRuntimeService())

    workflow_request = agents.WorkflowRequest(
        name="Native Workflow",
        description="Run two native Agent steps",
        nodes=[
            {"id": "start", "type": "start"},
            {"id": "agent", "type": "agent", "agent_id": "agent-1"},
        ],
        edges=[{"source": "start", "target": "agent"}],
        enabled=True,
    )

    workflows = asyncio.run(agents.list_workflows())
    created = asyncio.run(agents.create_workflow(workflow_request))
    updated = asyncio.run(
        agents.update_workflow(
            "workflow-1",
            agents.WorkflowRequest(
                name="Native Workflow v2",
                description="Updated native Agent steps",
                nodes=[{"id": "start", "type": "start"}],
                edges=[],
                enabled=False,
            ),
        )
    )
    deleted = asyncio.run(agents.delete_workflow("workflow-1"))

    assert workflows["workflows"][0]["workflow_id"] == "workflow-1"
    assert created["name"] == "Native Workflow"
    assert created["nodes"][1]["agent_id"] == "agent-1"
    assert updated == {
        "workflow_id": "workflow-1",
        "name": "Native Workflow v2",
        "description": "Updated native Agent steps",
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
        "enabled": False,
    }
    assert deleted == {"ok": True, "workflow_id": "workflow-1"}
    assert calls == [
        ("list_workflows", {}),
        (
            "create_workflow",
            {
                "name": "Native Workflow",
                "description": "Run two native Agent steps",
                "nodes": [
                    {"id": "start", "type": "start"},
                    {"id": "agent", "type": "agent", "agent_id": "agent-1"},
                ],
                "edges": [{"source": "start", "target": "agent"}],
                "enabled": True,
            },
        ),
        (
            "update_workflow",
            {
                "workflow_id": "workflow-1",
                "name": "Native Workflow v2",
                "description": "Updated native Agent steps",
                "nodes": [{"id": "start", "type": "start"}],
                "edges": [],
                "enabled": False,
            },
        ),
        ("delete_workflow", {"workflow_id": "workflow-1"}),
    ]


def test_agent_studio_bridge_contract_preserves_run_detail_workflow_artifact_and_rerun(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class FakeRuntimeService:
        def create_agent_run(self, payload):
            calls.append(("create_agent_run", payload))
            return {
                "run_id": "run_agent_1",
                "kind": "agent_run",
                "client_run_id": payload.get("client_run_id", ""),
            }

        def create_workflow_run(self, payload):
            calls.append(("create_workflow_run", payload))
            return {
                "run_id": "run_workflow_1",
                "kind": "workflow_run",
                "client_run_id": payload.get("client_run_id", ""),
                "run_group_id": "group-1",
            }

        def list_runs(self, limit):
            calls.append(("list_runs", {"limit": limit}))
            return {
                "runs": [
                    {"run_id": "run_agent_1", "kind": "agent_run"},
                    {"run_id": "run_workflow_1", "kind": "workflow_run"},
                ]
            }

        def list_run_groups(self, limit):
            calls.append(("list_run_groups", {"limit": limit}))
            return {
                "run_groups": [
                    {
                        "run_group_id": "group-1",
                        "status": "completed",
                        "child_run_ids": ["run_workflow_1", "run_agent_1"],
                    }
                ]
            }

        def get_run(self, run_id):
            calls.append(("get_run", {"run_id": run_id}))
            return {
                "run_id": run_id,
                "status": "completed",
                "timeline": [{"event": "workflow.node.artifact", "status": "completed"}],
                "artifacts": [{"path": "reports/final.md", "kind": "workflow_artifact"}],
            }

        def get_run_group(self, run_group_id):
            calls.append(("get_run_group", {"run_group_id": run_group_id}))
            return {"run_group_id": run_group_id, "status": "completed"}

        def read_run_artifact(self, run_id, artifact_path):
            calls.append(("read_run_artifact", {"run_id": run_id, "artifact_path": artifact_path}))
            return {"ok": True, "run_id": run_id, "path": artifact_path, "content": "# Final"}

        def rerun_run(self, run_id):
            calls.append(("rerun_run", {"run_id": run_id}))
            return {"run_id": "run_workflow_2", "rerun_of_run_id": run_id, "status": "completed"}

        def delete_run(self, run_id):
            calls.append(("delete_run", {"run_id": run_id}))
            return {
                "ok": True,
                "deleted_run_ids": [run_id, "run_agent_1"],
                "deleted_run_count": 2,
            }

    monkeypatch.setattr(agents, "get_agent_runtime_service", lambda: FakeRuntimeService())

    agent_run = asyncio.run(
        agents.create_agent_run(
            agents.AgentRunRequest(agent_id="agent-1", user_goal="检查 UI"),
            SimpleNamespace(headers={"idempotency-key": "agent-key-1"}),
        )
    )
    workflow_run = asyncio.run(
        agents.create_workflow_run(
            agents.WorkflowRunRequest(
                workflow_id="workflow-1",
                user_goal="产出验收报告",
                client_run_id="workflow-client-1",
            )
        )
    )
    runs = asyncio.run(agents.list_runs(limit=20))
    run_groups = asyncio.run(agents.list_run_groups(limit=20))
    run_detail = asyncio.run(agents.get_any_run("run_workflow_1"))
    workflow_detail = asyncio.run(agents.get_workflow_run("run_workflow_1"))
    group = asyncio.run(agents.get_run_group("group-1"))
    artifact = asyncio.run(agents.get_run_artifact("run_workflow_1", "reports/final.md"))
    rerun = asyncio.run(agents.rerun_run("run_workflow_1"))
    deleted = asyncio.run(agents.delete_run("run_workflow_1"))

    assert agent_run == {
        "run_id": "run_agent_1",
        "kind": "agent_run",
        "client_run_id": "agent-key-1",
    }
    assert workflow_run == {
        "run_id": "run_workflow_1",
        "kind": "workflow_run",
        "client_run_id": "workflow-client-1",
        "run_group_id": "group-1",
    }
    assert [item["run_id"] for item in runs["runs"]] == ["run_agent_1", "run_workflow_1"]
    assert run_groups["run_groups"][0]["child_run_ids"] == ["run_workflow_1", "run_agent_1"]
    assert run_detail["artifacts"][0]["path"] == "reports/final.md"
    assert workflow_detail["timeline"][0]["event"] == "workflow.node.artifact"
    assert group == {"run_group_id": "group-1", "status": "completed"}
    assert artifact["content"] == "# Final"
    assert rerun == {
        "run_id": "run_workflow_2",
        "rerun_of_run_id": "run_workflow_1",
        "status": "completed",
    }
    assert deleted == {
        "ok": True,
        "deleted_run_ids": ["run_workflow_1", "run_agent_1"],
        "deleted_run_count": 2,
    }
    assert calls == [
        (
            "create_agent_run",
            {
                "agent_id": "agent-1",
                "user_goal": "检查 UI",
                "client_run_id": "agent-key-1",
            },
        ),
        (
            "create_workflow_run",
            {
                "workflow_id": "workflow-1",
                "client_run_id": "workflow-client-1",
                "user_goal": "产出验收报告",
            },
        ),
        ("list_runs", {"limit": 20}),
        ("list_run_groups", {"limit": 20}),
        ("get_run", {"run_id": "run_workflow_1"}),
        ("get_run", {"run_id": "run_workflow_1"}),
        ("get_run_group", {"run_group_id": "group-1"}),
        ("read_run_artifact", {"run_id": "run_workflow_1", "artifact_path": "reports/final.md"}),
        ("rerun_run", {"run_id": "run_workflow_1"}),
        ("delete_run", {"run_id": "run_workflow_1"}),
    ]


def test_run_detail_bridge_contract_preserves_replay_events(monkeypatch):
    calls: list[dict] = []

    class FakeRuntimeService:
        def list_run_events(self, run_id, *, after_sequence=0, limit=200):
            calls.append({"run_id": run_id, "after_sequence": after_sequence, "limit": limit})
            return {
                "run_id": run_id,
                "after_sequence": after_sequence,
                "limit": limit,
                "events": [
                    {
                        "run_id": run_id,
                        "sequence": after_sequence + 1,
                        "event_type": "agent.tool.call",
                        "payload": {
                            "tool": "workspace.read",
                            "input_preview": {"path": "README.md"},
                            "result": {"ok": True},
                        },
                        "created_at": "2026-06-10T00:00:00+00:00",
                    }
                ],
            }

    monkeypatch.setattr(run_routes, "get_native_run_engine", lambda: FakeRuntimeService())

    replay = asyncio.run(run_routes.list_run_events("run_detail_1", after_sequence=7, limit=50))

    assert replay["run_id"] == "run_detail_1"
    assert replay["after_sequence"] == 7
    assert replay["limit"] == 50
    assert replay["events"][0]["event_type"] == "agent.tool.call"
    assert replay["events"][0]["payload"]["tool"] == "workspace.read"
    assert calls == [{"run_id": "run_detail_1", "after_sequence": 7, "limit": 50}]


def test_desktop_presence_bridge_contract_preserves_screenshot_tts_proactive_and_live2d(monkeypatch):
    config = SimpleNamespace(
        tts=SimpleNamespace(enabled=True, provider="command"),
        bubble_mode=SimpleNamespace(proactive_enabled=True),
        live2d_mode=SimpleNamespace(proactive_enabled=True),
    )
    runtime = SimpleNamespace(config=config)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ui, "get_runtime", lambda: runtime)
    ui._launcher_proactive_services.clear()
    ui._launcher_tts_services.clear()

    async def fake_capture_screenshot():
        calls.append(("screen_current", {}))
        return {
            "mime_type": "image/png",
            "data": "base64-image",
            "width": 120,
            "height": 80,
        }

    def fake_screen_permission(open_settings=False):
        calls.append(("screen_permission", {"open_settings": open_settings}))
        return {"ok": True, "allowed": True, "settings_opened": bool(open_settings)}

    class FakeTTSService:
        def __init__(self, received_config):
            assert received_config is config.tts

        def speak_sync(self, text):
            calls.append(("tts_test", {"text": text}))
            return {"ok": True, "success": True, "provider": "command", "spoken_text": text}

        def get_status(self):
            calls.append(("tts_status", {}))
            return {"ok": True, "enabled": True, "provider": "command"}

    class FakeProactiveService:
        session_id = "proactive-session"

        def __init__(self, received_runtime, mode_config):
            assert received_runtime is runtime
            self.mode_config = mode_config

        def trigger_now(self):
            calls.append(("proactive_test", {"mode_config": self.mode_config}))
            return {"ok": True, "task_id": "task-proactive-1", "status": "queued"}

    def fake_prepare_live2d(config_obj, path):
        assert config_obj is config
        calls.append(("live2d_prepare", {"path": str(path)}))
        return {
            "ok": True,
            "draft_changes": {"live2d_mode.model_path": str(path)},
        }

    def fake_import_live2d(config_obj, path):
        assert config_obj is config
        calls.append(("live2d_import", {"path": str(path)}))
        return {
            "ok": True,
            "draft_changes": {"live2d_mode.model_path": "/imported/yachiyo"},
        }

    def fake_tts_resource_info():
        calls.append(("tts_voice_resource", {}))
        return {"ok": True, "installed": True}

    def fake_import_tts(path):
        calls.append(("tts_voice_import", {"path": str(path)}))
        return {"ok": True, "draft_changes": {"tts.provider": "gpt-sovits"}}

    monkeypatch.setattr(screenshot_mod, "capture_screenshot", fake_capture_screenshot)
    monkeypatch.setattr(screenshot_mod, "check_screen_capture_permission", fake_screen_permission)
    monkeypatch.setattr(ui, "TTSService", FakeTTSService)
    monkeypatch.setattr(ui, "ProactiveDesktopService", FakeProactiveService)
    monkeypatch.setattr(ui, "prepare_live2d_model_path_draft", fake_prepare_live2d)
    monkeypatch.setattr(ui, "import_live2d_archive_draft", fake_import_live2d)
    monkeypatch.setattr(ui, "get_tts_voice_resource_info", fake_tts_resource_info)
    monkeypatch.setattr(ui, "import_tts_voice_archive_draft", fake_import_tts)

    screen_route = _load_screen_route_module()
    screen_payload = asyncio.run(screen_route.get_screen_current())
    permission = asyncio.run(
        ui.check_proactive_screen_permission(
            ui.ScreenPermissionRequest(open_settings=True)
        )
    )
    tts_test = asyncio.run(ui.test_proactive_tts(ui.TtsTestRequest(text="测试语音")))
    tts_status = asyncio.run(ui.get_proactive_tts_status())
    tts_resource = asyncio.run(ui.get_tts_voice_resource())
    tts_import = asyncio.run(
        ui.import_tts_voice_archive_path(
            ui.TtsResourcePathRequest(path="/tmp/voice.zip")
        )
    )
    proactive = asyncio.run(ui.trigger_proactive_test(ui.ProactiveTestRequest(mode="live2d")))
    live2d_prepare = asyncio.run(
        ui.prepare_live2d_model_path(
            ui.Live2DResourcePathRequest(path="/tmp/model.model3.json")
        )
    )
    live2d_import = asyncio.run(
        ui.import_live2d_archive_path(
            ui.Live2DResourcePathRequest(path="/tmp/live2d.zip")
        )
    )

    assert screen_payload["mime_type"] == "image/png"
    assert permission == {"ok": True, "allowed": True, "settings_opened": True}
    assert tts_test["tool"] == "proactive_tts"
    assert tts_test["spoken_text"] == "测试语音"
    assert tts_status == {
        "tool": "proactive_tts",
        "source": "config",
        "ok": True,
        "enabled": True,
        "provider": "command",
    }
    assert tts_resource == {"ok": True, "installed": True}
    assert tts_import["draft_changes"] == {"tts.provider": "gpt-sovits"}
    assert proactive["mode"] == "live2d"
    assert proactive["task_id"] == "task-proactive-1"
    assert live2d_prepare["draft_changes"] == {"live2d_mode.model_path": "/tmp/model.model3.json"}
    assert live2d_import["draft_changes"] == {"live2d_mode.model_path": "/imported/yachiyo"}
    assert calls == [
        ("screen_current", {}),
        ("screen_permission", {"open_settings": True}),
        ("tts_test", {"text": "测试语音"}),
        ("tts_status", {}),
        ("tts_voice_resource", {}),
        ("tts_voice_import", {"path": "/tmp/voice.zip"}),
        ("proactive_test", {"mode_config": config.live2d_mode}),
        ("live2d_prepare", {"path": "/tmp/model.model3.json"}),
        ("live2d_import", {"path": "/tmp/live2d.zip"}),
    ]
