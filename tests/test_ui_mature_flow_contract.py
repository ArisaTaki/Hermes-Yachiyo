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
from apps.bridge.routes import agents, runs as run_routes, ui


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
    run_detail = asyncio.run(agents.get_any_run("run_workflow_1"))
    workflow_detail = asyncio.run(agents.get_workflow_run("run_workflow_1"))
    group = asyncio.run(agents.get_run_group("group-1"))
    artifact = asyncio.run(agents.get_run_artifact("run_workflow_1", "reports/final.md"))
    rerun = asyncio.run(agents.rerun_run("run_workflow_1"))

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
    assert run_detail["artifacts"][0]["path"] == "reports/final.md"
    assert workflow_detail["timeline"][0]["event"] == "workflow.node.artifact"
    assert group == {"run_group_id": "group-1", "status": "completed"}
    assert artifact["content"] == "# Final"
    assert rerun == {
        "run_id": "run_workflow_2",
        "rerun_of_run_id": "run_workflow_1",
        "status": "completed",
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
        ("get_run", {"run_id": "run_workflow_1"}),
        ("get_run", {"run_id": "run_workflow_1"}),
        ("get_run_group", {"run_group_id": "group-1"}),
        ("read_run_artifact", {"run_id": "run_workflow_1", "artifact_path": "reports/final.md"}),
        ("rerun_run", {"run_id": "run_workflow_1"}),
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
