"""Fake-port tests for the Chat-facing Yachiyo Agent service."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent import ApprovalDecision, StartChatTaskRequest, YachiyoAgentService


class _FakeRuntimePort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def readiness(self) -> dict[str, Any]:
        self.calls.append(("readiness", None))
        return {"ok": True, "status": "ready", "capabilities": {"tasks": True}}

    def list_runnable_catalog(self) -> dict[str, Any]:
        self.calls.append(("list_runnable_catalog", None))
        return {
            "agents": [
                {
                    "agent_id": "agent-1",
                    "name": "Planner",
                    "tool_policy": {
                        "allowed_tools": ["workspace.read", "workspace.write_patch"],
                        "approval_required": {"workspace.write_patch": True},
                    },
                    "workspace_policy": {"allowed_roots": ["/private"]},
                }
            ],
            "workflows": [
                {
                    "workflow_id": "workflow-1",
                    "name": "Review workflow",
                    "nodes": [
                        {
                            "id": "review",
                            "type": "agent",
                            "data": {"agent_id": "agent-1"},
                        }
                    ],
                    "edges": [{"source": "start", "target": "review"}],
                }
            ],
        }

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_chat_task", request))
        return _task_payload(
            status="approval_required",
            pending_approval={
                "approval_id": "approval-1",
                "tool": "workspace.write_patch",
                "input_preview": {"path": "README.md"},
            },
            timeline=[
                {
                    "event": "agent.tool.approval_required",
                    "detail": "workspace.write_patch",
                }
            ],
        )

    def get_task_snapshot(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_snapshot", task_id))
        return _task_payload(task_id=task_id, status="completed", result="Done")

    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _task_payload(
            task_id=task_id,
            status="approval_required",
            pending_approval={
                "approval_id": "approval-1",
                "tool": "workspace.write_patch",
            },
            timeline=[
                {
                    "event": "agent.tool.approval_required",
                    "detail": "workspace.write_patch",
                },
                {"event": "tool.approval_required", "tool": "workspace.write_patch"},
            ],
        )

    def get_task_event_stream(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_event_stream", task_id))
        return {
            "run_id": "run-1",
            "events": [
                {"event": "task.started", "sequence": 1},
                {"event": "tool.requested", "sequence": 2, "tool": "workspace.read"},
                {"event": "task.completed", "sequence": 3},
            ],
        }

    def read_task_artifact(self, task_id: str, artifact_path: str) -> dict[str, Any]:
        self.calls.append(("read_task_artifact", {"task_id": task_id, "path": artifact_path}))
        return {
            "ok": True,
            "run_id": "run-1",
            "task_id": task_id,
            "path": artifact_path,
            "content": "# Report",
            "mime_type": "text/markdown",
            "truncated": False,
        }

    def list_recent_tasks(self, conversation_id: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("list_recent_tasks", conversation_id))
        return [_task_payload(task_id="task-recent", status="running")]

    def approve(self, task_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("approve", {"task_id": task_id, "decision": decision}))
        return _task_payload(status="completed", result="Approved")

    def reject(self, task_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("reject", {"task_id": task_id, "decision": decision}))
        return _task_payload(status="failed", result="Rejected")

    def cancel(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("cancel", task_id))
        return _task_payload(task_id=task_id, status="cancelled")


class _FakeChatTaskStarter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any] | None:
        self.calls.append(request)
        if not request.get("agent_id"):
            return None
        return _task_payload(
            task_id="chat-backed-task",
            run_id="chat-backed-run",
            status="processing",
            session_id=str(request.get("conversation_id") or ""),
        )


class _PagedRuntimePort(_FakeRuntimePort):
    def get_task_event_page(
        self,
        task_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.calls.append((
            "get_task_event_page",
            {
                "task_id": task_id,
                "after_sequence": after_sequence,
                "limit": limit,
            },
        ))
        return {
            "run_id": "run-paged",
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": 7,
            "has_more": True,
            "events": [
                {
                    "event_type": "task.progress",
                    "sequence": 7,
                    "payload": {"step": "read workspace"},
                }
            ],
        }


class _SensitiveTaskRuntimePort(_FakeRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _task_payload(
            task_id=task_id,
            status="running",
            timeline=[
                {
                    "event_type": "task.started",
                    "sequence": 1,
                    "payload": {"step": "visible"},
                },
                {
                    "event_type": "agent.tool.call",
                    "sequence": 2,
                    "sensitivity": "secret",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf sk-secret-value"},
                    },
                },
                {
                    "event_type": "agent.runtime.compiled",
                    "sequence": 3,
                    "visibility": "internal",
                    "payload": {"step": "internal"},
                },
                {
                    "event_type": "agent.tool.call",
                    "sequence": 4,
                    "visibility": "internal",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "internal.md"},
                    },
                },
            ],
        )

    def get_task_event_stream(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_event_stream", task_id))
        return {
            "run_id": "run-sensitive",
            "events": [
                {"event_type": "task.started", "sequence": 1, "payload": {"step": "visible"}},
                {
                    "event_type": "agent.tool.call",
                    "sequence": 2,
                    "sensitivity": "secret",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf sk-secret-value"},
                    },
                },
                {
                    "event_type": "agent.runtime.compiled",
                    "sequence": 3,
                    "visibility": "internal",
                    "payload": {"step": "internal"},
                },
                {
                    "event_type": "agent.tool.call",
                    "sequence": 4,
                    "visibility": "internal",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "internal.md"},
                    },
                },
                {"event_type": "task.completed", "sequence": 5, "payload": {"step": "done"}},
            ],
        }


class _DesktopIntentTaskRuntimePort(_FakeRuntimePort):
    def get_task_snapshot(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_snapshot", task_id))
        return _desktop_intent_task_payload(task_id=task_id)

    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _desktop_intent_task_payload(task_id=task_id)


class _CompletedDesktopIntentTaskRuntimePort(_FakeRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _task_payload(
            task_id=task_id,
            status="running",
            current_step="",
            progress_text="",
            timeline=[
                {
                    "event": "agent.desktop.intent_completed",
                    "detail": "desktop.windows",
                    "tool": "desktop.windows",
                    "source": "daily_desktop_intent",
                    "input_preview": {"app_name": "Google Chrome"},
                    "result": {
                        "ok": True,
                        "action": "desktop.windows",
                        "data": {
                            "count": 1,
                            "windows": [
                                {
                                    "app_name": "Google Chrome",
                                    "title": "ChatGPT",
                                    "frontmost": True,
                                }
                            ],
                        },
                    },
                    "summary": "当前窗口：Google Chrome: ChatGPT。",
                }
            ],
        )


class _CompletedDesktopIntentSequenceTaskRuntimePort(_FakeRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _task_payload(
            task_id=task_id,
            status="running",
            current_step="",
            progress_text="",
            timeline=[
                {
                    "event": "agent.desktop.intent_completed",
                    "detail": "desktop.ui_elements",
                    "tool": "desktop.ui_elements",
                    "tools": ["app.open", "desktop.ui_elements"],
                    "source": "daily_desktop_intent",
                    "input_preview": {"role_filter": "button", "limit": 80},
                    "result": {
                        "ok": True,
                        "action": "desktop.ui_elements",
                        "data": {"count": 2},
                    },
                    "steps": [
                        {
                            "tool": "app.open",
                            "input_preview": {"app_name": "WeChat"},
                            "result": {
                                "ok": True,
                                "action": "app.open",
                                "summary": "已打开 WeChat。",
                            },
                            "summary": "已打开 WeChat。",
                        },
                        {
                            "tool": "desktop.ui_elements",
                            "input_preview": {"role_filter": "button", "limit": 80},
                            "result": {
                                "ok": True,
                                "action": "desktop.ui_elements",
                                "data": {"count": 2},
                            },
                            "summary": "当前 WeChat 界面控件：2 个。",
                        },
                    ],
                    "summary": "已打开 WeChat。 当前 WeChat 界面控件：2 个。",
                }
            ],
        )


def test_yachiyo_agent_service_maps_fake_runtime_to_task_snapshots() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    readiness = service.readiness()
    task = service.start_chat_task(
        StartChatTaskRequest(prompt="Patch README", conversation_id="chat-1", title="Patch")
    )
    fetched = service.get_task_snapshot("task-1")
    recent = service.list_recent_tasks("chat-1")

    assert readiness.ready is True
    assert readiness.capabilities == {"tasks": True}
    assert task.task_id == "task-1"
    assert task.conversation_id == "chat-1"
    assert task.status == "waiting_approval"
    assert task.needs_user_action is True
    assert task.pending_approvals[0].tool_name == "workspace.write_patch"
    assert task.recent_events[0].event_type == "agent.tool.approval_required"
    assert task.open_in_studio_url == "#/agents?run_id=run-1"
    assert fetched.status == "completed"
    assert recent[0].task_id == "task-recent"
    assert port.calls[1][1]["prompt"] == "Patch README"


def test_yachiyo_agent_service_attaches_runtime_planner_metadata_to_chat_task() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    service.start_chat_task(
        StartChatTaskRequest(
            prompt="打开 PixelForge 并点击导出",
            conversation_id="chat-1",
            title="Desktop task",
        )
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "desktop_operation"
    assert metadata["yachiyo_route_to_studio"] is True
    assert metadata["yachiyo_plan_tools"] == [
        "desktop.list_apps",
        "app.open_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert metadata["yachiyo_plan_capabilities"] == [
        "desktop.app_discovery",
        "desktop.app_control",
        "desktop.ui_operation",
    ]
    assert metadata["yachiyo_plan_approvals_required"] == ["operate-foreground-ui"]
    assert metadata["yachiyo_plan_artifacts_expected"] == []
    assert metadata["yachiyo_plan_open_questions"] == []
    assert metadata["yachiyo_required_capabilities"] == ["desktop.app_discovery"]
    assert metadata["yachiyo_missing_capabilities"] == []


def test_yachiyo_agent_service_returns_runtime_planner_metadata_on_chat_task() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="打开 PixelForge 并点击导出",
            conversation_id="chat-1",
            metadata={"client_message_id": "client-1"},
        )
    )

    assert task.metadata["client_message_id"] == "client-1"
    assert task.metadata["yachiyo_runtime_planner"] is True
    assert task.metadata["yachiyo_intent_kind"] == "desktop_operation"
    assert task.metadata["yachiyo_plan_tools"] == [
        "desktop.list_apps",
        "app.open_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert task.metadata["yachiyo_plan_approvals_required"] == ["operate-foreground-ui"]


def test_yachiyo_agent_service_attaches_planner_outputs_to_chat_task() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
            title="Data analysis",
        )
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "data_analysis"
    assert metadata["yachiyo_plan_tools"] == ["data.analyze"]
    assert metadata["yachiyo_plan_capabilities"] == ["data.analysis"]
    assert metadata["yachiyo_plan_approvals_required"] == []
    assert metadata["yachiyo_plan_artifacts_expected"] == ["analysis-report.md"]
    assert metadata["yachiyo_plan_open_questions"] == []
    assert metadata["yachiyo_missing_capabilities"] == []


def test_yachiyo_agent_service_maps_chat_runnable_catalog() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    catalog = service.list_runnable_catalog()

    assert catalog.agents[0].runnable_id == "agent-1"
    assert catalog.agents[0].agent_id == "agent-1"
    assert catalog.agents[0].kind == "agent"
    assert catalog.agents[0].tool_capabilities == ["workspace.read", "workspace.write_patch"]
    assert catalog.agents[0].approval_required_tools == ["workspace.write_patch"]
    assert catalog.workflows[0].runnable_id == "workflow-1"
    assert catalog.workflows[0].workflow_id == "workflow-1"
    assert catalog.workflows[0].kind == "workflow"
    assert catalog.workflows[0].participants[0].runnable_id == "agent-1"
    assert port.calls == [("list_runnable_catalog", None)]


def test_yachiyo_agent_service_maps_task_timeline_snapshot() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    timeline = service.get_task_timeline("task-1")

    assert timeline.run_id == "run-1"
    assert timeline.task_id == "task-1"
    assert timeline.status == "approval_required"
    assert timeline.events[0].event_type == "agent.tool.approval_required"
    assert timeline.pending_approval is not None
    assert timeline.pending_approval.tool_name == "workspace.write_patch"
    assert timeline.tool_calls[0].tool_name == "workspace.write_patch"
    assert port.calls == [("get_task_timeline", "task-1")]


def test_yachiyo_agent_service_preserves_desktop_intent_planning_event() -> None:
    port = _DesktopIntentTaskRuntimePort()
    service = YachiyoAgentService(port)

    task = service.get_task_snapshot("task-music")
    timeline = service.get_task_timeline("task-music")

    assert task.recent_events[0].event_type == "agent.desktop.intent_planned"
    assert task.recent_events[0].detail == "media.apple_music_play"
    assert task.recent_events[0].payload == {
        "input_preview": {"query": "超时空辉夜姬"},
        "planning_reason": "clear_daily_desktop_intent",
        "source": "daily_desktop_intent",
        "status": "planned",
        "tool": "media.apple_music_play",
    }
    assert task.current_step == "准备执行 · 播放 Apple Music"
    assert task.progress_text == "准备执行 · 播放 Apple Music"
    assert timeline.events[0].event_type == "agent.desktop.intent_planned"
    assert timeline.events[0].payload["tool"] == "media.apple_music_play"
    assert timeline.tool_calls == []
    assert port.calls == [
        ("get_task_snapshot", "task-music"),
        ("get_task_timeline", "task-music"),
    ]


def test_yachiyo_agent_service_projects_completed_desktop_intent_as_tool_call() -> None:
    port = _CompletedDesktopIntentTaskRuntimePort()
    service = YachiyoAgentService(port)

    timeline = service.get_task_timeline("task-windows")

    assert timeline.events[0].event_type == "agent.desktop.intent_completed"
    assert len(timeline.tool_calls) == 1
    assert timeline.tool_calls[0].tool_name == "desktop.windows"
    assert timeline.tool_calls[0].status == "completed"
    assert timeline.tool_calls[0].input_preview == {"app_name": "Google Chrome"}
    assert timeline.tool_calls[0].output_preview["action"] == "desktop.windows"
    assert timeline.tool_calls[0].output_preview["data"]["count"] == 1
    assert port.calls == [("get_task_timeline", "task-windows")]


def test_yachiyo_agent_service_projects_completed_desktop_intent_sequence_tool_calls() -> None:
    port = _CompletedDesktopIntentSequenceTaskRuntimePort()
    service = YachiyoAgentService(port)

    timeline = service.get_task_timeline("task-wechat")

    assert timeline.events[0].event_type == "agent.desktop.intent_completed"
    assert [tool_call.tool_name for tool_call in timeline.tool_calls] == [
        "app.open",
        "desktop.ui_elements",
    ]
    assert [tool_call.status for tool_call in timeline.tool_calls] == [
        "completed",
        "completed",
    ]
    assert timeline.tool_calls[0].input_preview == {"app_name": "WeChat"}
    assert timeline.tool_calls[0].output_preview["action"] == "app.open"
    assert timeline.tool_calls[1].input_preview == {"role_filter": "button", "limit": "80"}
    assert timeline.tool_calls[1].output_preview["action"] == "desktop.ui_elements"
    assert port.calls == [("get_task_timeline", "task-wechat")]


def test_yachiyo_agent_service_pages_task_events() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    page = service.get_task_event_page("task-1", after_sequence=1, limit=1)

    assert page.run_id == "run-1"
    assert page.after_sequence == 1
    assert page.limit == 1
    assert page.next_after_sequence == 2
    assert page.has_more is True
    assert [event.event_type for event in page.events] == ["tool.requested"]
    assert port.calls == [("get_task_event_stream", "task-1")]


def test_yachiyo_agent_service_prefers_runtime_port_task_event_pages() -> None:
    port = _PagedRuntimePort()
    service = YachiyoAgentService(port)

    page = service.get_task_event_page("task-1", after_sequence=-4, limit=999)

    assert page.run_id == "run-paged"
    assert page.after_sequence == 0
    assert page.limit == 500
    assert page.next_after_sequence == 7
    assert page.has_more is True
    assert [event.event_type for event in page.events] == ["task.progress"]
    assert page.events[0].payload == {"step": "read workspace"}
    assert port.calls == [
        (
            "get_task_event_page",
            {
                "task_id": "task-1",
                "after_sequence": 0,
                "limit": 500,
            },
        )
    ]


def test_yachiyo_agent_service_filters_secret_and_internal_chat_events() -> None:
    port = _SensitiveTaskRuntimePort()
    service = YachiyoAgentService(port)

    timeline = service.get_task_timeline("task-sensitive")
    page = service.get_task_event_page("task-sensitive", after_sequence=0, limit=10)

    assert [event.event_type for event in timeline.events] == ["task.started"]
    assert timeline.tool_calls == []
    assert [event.event_type for event in page.events] == ["task.started", "task.completed"]
    assert all(event.sensitivity == "public" for event in page.events)
    assert all(event.visibility == "user" for event in page.events)


def test_yachiyo_agent_service_reads_task_artifact_content() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    artifact = service.read_task_artifact("task-1", "reports/out.md")

    assert artifact.ok is True
    assert artifact.run_id == "run-1"
    assert artifact.task_id == "task-1"
    assert artifact.path == "reports/out.md"
    assert artifact.content == "# Report"
    assert artifact.mime_type == "text/markdown"
    assert port.calls == [("read_task_artifact", {"task_id": "task-1", "path": "reports/out.md"})]


def test_yachiyo_agent_service_prefers_chat_backed_starter_when_available() -> None:
    port = _FakeRuntimePort()
    starter = _FakeChatTaskStarter()
    service = YachiyoAgentService(port, chat_task_starter=starter)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="Patch README",
            conversation_id="chat-1",
            agent_id="agent-1",
        )
    )

    assert task.task_id == "chat-backed-task"
    assert task.status == "running"
    assert task.conversation_id == "chat-1"
    assert starter.calls[0]["agent_id"] == "agent-1"
    assert port.calls == []


def test_yachiyo_agent_service_falls_back_to_runtime_port_without_chat_backed_task() -> None:
    port = _FakeRuntimePort()
    starter = _FakeChatTaskStarter()
    service = YachiyoAgentService(port, chat_task_starter=starter)

    task = service.start_chat_task(StartChatTaskRequest(prompt="Patch README"))

    assert task.task_id == "task-1"
    assert task.status == "waiting_approval"
    assert starter.calls[0]["prompt"] == "Patch README"
    assert port.calls[0][0] == "start_chat_task"


def test_yachiyo_agent_service_delegates_approval_and_cancel_to_runtime_port() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    approved = service.approve(
        "task-1",
        ApprovalDecision(
            approved=True,
            reason="Looks safe",
            metadata={"approval_id": "approval-1"},
        ),
    )
    rejected = service.reject(
        "task-2",
        ApprovalDecision(
            approved=False,
            reason="No",
            metadata={"approval_id": "approval-2"},
        ),
    )
    cancelled = service.cancel("task-1")

    assert approved.status == "completed"
    assert rejected.status == "failed"
    assert cancelled.status == "cancelled"
    assert port.calls == [
        (
            "approve",
            {
                "task_id": "task-1",
                "decision": {
                    "approved": True,
                    "reason": "Looks safe",
                    "metadata": {"approval_id": "approval-1"},
                },
            },
        ),
        (
            "reject",
            {
                "task_id": "task-2",
                "decision": {
                    "approved": False,
                    "reason": "No",
                    "metadata": {"approval_id": "approval-2"},
                },
            },
        ),
        ("cancel", "task-1"),
    ]


def test_yachiyo_agent_service_keeps_string_reject_reason_compatible() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    rejected = service.reject("task-2", "No")

    assert rejected.status == "failed"
    assert port.calls == [
        ("reject", {"task_id": "task-2", "decision": {"approved": False, "reason": "No"}})
    ]


def _task_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "task_id": "task-1",
        "run_id": "run-1",
        "session_id": "chat-1",
        "title": "Patch README",
        "status": "running",
        "summary": "",
        "current_step": "Reading workspace",
        "artifacts": [{"artifact_id": "artifact-1", "kind": "markdown", "path": "report.md"}],
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }
    payload.update(overrides)
    return payload


def _desktop_intent_task_payload(**overrides: Any) -> dict[str, Any]:
    return _task_payload(
        status="running",
        current_step="",
        progress_text="",
        timeline=[
            {
                "event": "agent.desktop.intent_planned",
                "detail": "media.apple_music_play",
                "tool": "media.apple_music_play",
                "status": "planned",
                "source": "daily_desktop_intent",
                "planning_reason": "clear_daily_desktop_intent",
                "input_preview": {"query": "超时空辉夜姬"},
            }
        ],
        **overrides,
    )
