"""Fake-port tests for the Chat-facing Yachiyo Agent service."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent import (
    AgentStudioService,
    ApprovalDecision,
    StartChatTaskRequest,
    YachiyoAgentService,
)


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


class _BareStartTaskRuntimePort(_FakeRuntimePort):
    def __init__(self, *, existing_planner_events: bool = False) -> None:
        super().__init__()
        self.existing_planner_events = existing_planner_events

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_chat_task", request))
        events = []
        if self.existing_planner_events:
            events.append(
                {
                    "event_type": "agent.intent.selected",
                    "payload": {"intent": {"kind": "data_analysis"}},
                }
            )
        return _task_payload(
            status="running",
            title=request.get("title") or "Chat task",
            session_id=str(request.get("conversation_id") or ""),
            events=events,
        )


class _FakeStudioExecutionPort:
    def list_tool_catalog(self) -> dict[str, Any]:
        return {
            "tools": [
                {"tool_name": "workspace.read", "capability_id": "workspace.file_read"},
                {"tool_name": "data.analyze", "capability_id": "data.analysis"},
                {"tool_name": "terminal.run", "capability_id": "terminal.execute"},
                {"tool_name": "artifact.write", "capability_id": "artifact.output"},
            ],
            "capabilities": {},
        }


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


class _ReadinessRecoveredTaskRuntimePort(_FakeRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _task_payload(
            task_id=task_id,
            status="running",
            current_step="",
            progress_text="",
            timeline=[
                {
                    "event": "agent.desktop.readiness_recovered",
                    "detail": "desktop.list_apps",
                    "tool": "desktop.list_apps",
                    "recovery_tool": "desktop.list_apps",
                    "status": "recovered",
                    "app_name": "PixelForge",
                    "blocking_conditions": ["app_not_found"],
                }
            ],
        )


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
    assert metadata["yachiyo_candidate_intents"] == [
        {"kind": "desktop_operation", "title": "Desktop Operation", "confidence": 0.58}
    ]
    assert metadata["yachiyo_route_to_studio"] is True
    assert metadata["yachiyo_plan_tools"] == [
        "desktop.inspect_app",
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
    assert metadata["yachiyo_required_capabilities"] == [
        "desktop.app_discovery",
        "desktop.ui_operation",
    ]
    assert metadata["yachiyo_missing_capabilities"] == []


def test_yachiyo_agent_service_surfaces_desktop_execution_request_previews() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    service.start_chat_task(
        {
            "prompt": "打开 PixelForge",
            "conversation_id": "chat-1",
            "allowed_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
        }
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["yachiyo_execution_requests"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    previews = metadata["yachiyo_execution_request_previews"]
    assert [preview["tool_name"] for preview in previews] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert previews[0]["runtime_stage"] == "discover"
    assert previews[0]["input"] == {"query": "PixelForge", "limit": 20}
    assert previews[1]["runtime_stage"] == "operate"
    assert previews[1]["input"] == {
        "app_name": "PixelForge",
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
    }
    assert previews[1]["requires_post_action_verification"] is True
    assert previews[2]["runtime_stage"] == "verify"
    assert previews[2]["depends_on"] == ["open-or-focus-app"]


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
        "desktop.inspect_app",
        "app.open_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert task.metadata["yachiyo_plan_approvals_required"] == ["operate-foreground-ui"]


def test_yachiyo_agent_service_surfaces_workflow_orchestration_metadata() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="运行 Daily Summary workflow",
            conversation_id="chat-1",
            metadata={"client_message_id": "client-1"},
        )
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["client_message_id"] == "client-1"
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "workflow_orchestration"
    assert metadata["yachiyo_plan_tools"] == ["workflow.start"]
    assert metadata["yachiyo_orchestration"] is True
    assert metadata["yachiyo_orchestration_kind"] == "workflow"
    assert metadata["yachiyo_orchestration_target"] == "Daily Summary"
    assert metadata["yachiyo_orchestration_planning_reason"] == "planner_orchestration_workflow"
    assert task.metadata["yachiyo_orchestration_kind"] == "workflow"


def test_yachiyo_agent_service_surfaces_group_orchestration_metadata_without_false_positive() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="让两个 agent 分别调研 Hanako 和 Hermes 然后汇总",
            conversation_id="chat-1",
        )
    )
    conceptual = service.start_chat_task(
        StartChatTaskRequest(
            prompt="介绍一下 multi-agent 架构",
            conversation_id="chat-1",
        )
    )

    metadata = port.calls[0][1]["metadata"]
    conceptual_metadata = port.calls[1][1]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "multi_agent"
    assert metadata["yachiyo_plan_tools"] == ["group.start"]
    assert metadata["yachiyo_orchestration"] is True
    assert metadata["yachiyo_orchestration_kind"] == "group_run"
    assert metadata["yachiyo_orchestration_target"] == ""
    assert metadata["yachiyo_orchestration_planning_reason"] == "planner_orchestration_group_run"
    assert task.metadata["yachiyo_orchestration_kind"] == "group_run"
    assert conceptual.metadata["yachiyo_runtime_planner"] is True
    assert "yachiyo_orchestration_kind" not in conceptual_metadata
    assert "yachiyo_orchestration_kind" not in conceptual.metadata


def test_yachiyo_agent_service_attaches_planner_outputs_to_chat_task() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
            title="Data analysis",
        )
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "data_analysis"
    assert metadata["yachiyo_candidate_intents"] == [
        {"kind": "data_analysis", "title": "Data Analysis", "confidence": 0.56},
        {"kind": "report_generation", "title": "Report Generation", "confidence": 0.42},
    ]
    assert metadata["yachiyo_plan_tools"] == ["data.analyze"]
    assert metadata["yachiyo_plan_capabilities"] == ["data.analysis"]
    assert metadata["yachiyo_plan_approvals_required"] == []
    assert metadata["yachiyo_plan_artifacts_expected"] == ["analysis-report.md"]
    assert metadata["yachiyo_plan_open_questions"] == []
    assert metadata["yachiyo_missing_capabilities"] == []
    assert metadata["yachiyo_execution_requests"] == ["data.analyze"]
    assert metadata["yachiyo_execution_envelope"]["intent_kind"] == "data_analysis"
    assert metadata["yachiyo_execution_envelope"]["requests"][0]["tool_name"] == "data.analyze"
    assert metadata["yachiyo_execution_envelope"]["task_core"]["core_id"] == (
        metadata["yachiyo_task_core"]["core_id"]
    )
    assert metadata["yachiyo_task_core"]["workspace"]["workspace_id"].startswith(
        "task-workspace-"
    )
    assert [todo["step_id"] for todo in metadata["yachiyo_task_core"]["todos"]] == [
        "analyze-data-file"
    ]
    assert task.task_core is not None
    assert task.task_core.workspace.workspace_id == metadata["yachiyo_task_core"]["workspace"]["workspace_id"]
    assert [todo.step_id for todo in task.task_core.todos] == ["analyze-data-file"]


def test_yachiyo_agent_service_plans_shared_chat_execution_envelope() -> None:
    service = YachiyoAgentService(_FakeRuntimePort())

    envelope = service.plan_chat_execution(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )

    assert envelope.intent_kind == "data_analysis"
    assert envelope.task_core is not None
    assert envelope.task_core.workspace.workspace_id.startswith("task-workspace-")
    assert [request.tool_name for request in envelope.requests] == ["data.analyze"]
    request = envelope.requests[0]
    assert request.step_id == "analyze-data-file"
    assert request.capability_id == "data.analysis"
    assert request.replan_signal_ids
    assert request.core_id == envelope.task_core.core_id
    assert request.workspace_id == envelope.task_core.workspace.workspace_id
    assert request.task_todo["step_id"] == "analyze-data-file"
    assert request.task_checkpoints[0]["after_step_id"] == "analyze-data-file"
    assert envelope.runtime_stage_counts == {"operate": 1}
    assert request.runtime_stage == "operate"
    assert request.runtime_role == "analyze_data"
    assert envelope.replan_signal_count == len(envelope.task_core.replan_signals)


def test_yachiyo_agent_service_can_project_full_chat_execution_plan() -> None:
    service = YachiyoAgentService(_FakeRuntimePort())

    envelope = service.plan_chat_execution(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "terminal.run", "artifact.write"],
        full_plan=True,
    )

    assert envelope.intent_kind == "data_analysis"
    assert [request.tool_name for request in envelope.requests] == [
        "workspace.read",
        "terminal.run",
        "artifact.write",
    ]
    assert [request.step_id for request in envelope.requests] == [
        "inspect-data-source",
        "run-analysis",
        "write-analysis-artifact",
    ]
    assert envelope.requests[1].approval_required is True
    assert envelope.requests[1].depends_on == ["inspect-data-source"]
    assert envelope.requests[2].depends_on == ["run-analysis"]


def test_agent_studio_service_plans_shared_execution_envelope() -> None:
    service = AgentStudioService(_FakeStudioExecutionPort())

    envelope = service.plan_execution(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )

    assert envelope.intent_kind == "data_analysis"
    assert envelope.task_core is not None
    assert envelope.requests[0].tool_name == "data.analyze"
    assert envelope.requests[0].step_id == "analyze-data-file"
    assert envelope.requests[0].capability_id == "data.analysis"
    assert envelope.requests[0].replan_signal_ids
    assert envelope.requests[0].core_id == envelope.task_core.core_id
    assert envelope.requests[0].workspace_id == envelope.task_core.workspace.workspace_id
    assert envelope.requests[0].task_todo["step_id"] == "analyze-data-file"
    assert envelope.requests[0].task_checkpoints[0]["after_step_id"] == (
        "analyze-data-file"
    )
    assert envelope.runtime_stage_counts == {"operate": 1}
    assert envelope.requests[0].runtime_stage == "operate"
    assert envelope.requests[0].runtime_role == "analyze_data"


def test_agent_studio_service_plans_discovered_desktop_app_execution() -> None:
    service = AgentStudioService(_FakeStudioExecutionPort())

    envelope = service.plan_execution(
        "在一个我没提过的新应用 PixelForge 点击 Export",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.ui_elements",
            "app.focus_and_click_ui_element",
        ],
        metadata={"surface": "studio"},
    )

    assert envelope.intent_kind == "desktop_operation"
    assert [request.tool_name for request in envelope.requests] == [
        "desktop.list_apps",
        "app.focus",
        "desktop.ui_elements",
    ]
    assert envelope.requests[0].runtime_stage == "discover"
    assert envelope.requests[0].input == {"query": "PixelForge", "limit": 20}
    assert envelope.requests[1].input == {
        "app_name": "PixelForge",
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
    }
    assert envelope.requests[1].requires_post_action_verification is True
    assert envelope.requests[2].input == {
        "app_name": "PixelForge",
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
        "limit": 80,
    }
    assert envelope.requests[2].requires_post_action_verification is True


def test_yachiyo_agent_service_projects_runtime_tool_result_events() -> None:
    service = YachiyoAgentService(_FakeRuntimePort())
    decision = service.plan_chat_task(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )

    events = service.project_tool_result_events(
        decision,
        tool_request=_runtime_progress_tool_request(
            decision,
            tool="data.analyze",
            step_id="analyze-data-file",
            task_id="task-1",
            run_id="run-1",
        ),
        tool_event={
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "result": {"ok": False, "error": "unsupported chart type"},
        },
        run_id="run-1",
        task_id="task-1",
        after_sequence=40,
    )

    assert [event.event_type for event in events] == [
        "agent.task.workspace_item.updated",
        "agent.task.todo.updated",
        "agent.task.checkpoint.updated",
        "agent.replan.requested",
    ]
    assert [event.sequence for event in events] == [41, 42, 43, 44]
    assert all(event.run_id == "run-1" for event in events)
    assert events[0].core_id == decision.plan.task_core.core_id
    assert events[-1].payload["source_step_id"] == "analyze-data-file"
    assert events[-1].payload["fallback_tools"] == ["terminal.run"]


def test_agent_studio_service_projects_scoped_group_runtime_tool_result_events() -> None:
    service = AgentStudioService(_FakeStudioExecutionPort())
    decision = service.plan_task(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )

    events = service.project_tool_result_events(
        decision,
        tool_request=_runtime_progress_tool_request(
            decision,
            tool="data.analyze",
            step_id="analyze-data-file",
            task_id="task-1",
            run_id="group-run-1",
            group_run_id="group-run-1",
        ),
        tool_event={
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "result": {"ok": False, "error": "tool unavailable"},
        },
        event_scope="group.run",
        run_id="group-run-1",
        task_id="task-1",
        after_sequence=10,
    )

    assert [event.event_type for event in events] == [
        "group.run.task.workspace_item.updated",
        "group.run.task.todo.updated",
        "group.run.task.checkpoint.updated",
        "group.run.replan.requested",
    ]
    assert [event.sequence for event in events] == [11, 12, 13, 14]
    assert events[0].group_run_id == "group-run-1"
    assert events[-1].payload["planner_event_type"] == "agent.replan.requested"
    assert events[-1].payload["planner_scope"] == "group.run"


def test_agent_studio_service_infers_workflow_runtime_tool_result_scope() -> None:
    service = AgentStudioService(_FakeStudioExecutionPort())
    decision = service.plan_task(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )

    events = service.project_tool_result_events(
        decision,
        tool_request=_runtime_progress_tool_request(
            decision,
            tool="data.analyze",
            step_id="analyze-data-file",
            task_id="task-1",
            run_id="workflow-run-1",
            workflow_run_id="workflow-run-1",
        ),
        tool_event={
            "event": "agent.tool.call",
            "detail": "data.analyze",
            "result": {"ok": False, "error": "tool unavailable"},
        },
        run_id="workflow-run-1",
        task_id="task-1",
        after_sequence=20,
    )

    assert [event.event_type for event in events] == [
        "workflow.run.task.workspace_item.updated",
        "workflow.run.task.todo.updated",
        "workflow.run.task.checkpoint.updated",
        "workflow.run.replan.requested",
    ]
    assert [event.sequence for event in events] == [21, 22, 23, 24]
    assert events[0].workflow_run_id == "workflow-run-1"
    assert events[-1].payload["planner_event_type"] == "agent.replan.requested"
    assert events[-1].payload["planner_scope"] == "workflow.run"


def test_yachiyo_agent_service_enriches_bare_chat_start_payload_with_planner_events() -> None:
    port = _BareStartTaskRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
            title="Data analysis",
        )
    )

    assert [event.event_type for event in task.recent_events[:4]] == [
        "agent.intent.selected",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.plan.step",
    ]
    assert task.recent_events[0].payload["intent"]["kind"] == "data_analysis"
    assert task.task_core is not None
    assert [todo.step_id for todo in task.task_core.todos] == ["analyze-data-file"]


def test_yachiyo_agent_service_does_not_duplicate_existing_chat_planner_events() -> None:
    port = _BareStartTaskRuntimePort(existing_planner_events=True)
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
        )
    )

    assert [event.event_type for event in task.recent_events].count("agent.intent.selected") == 1


def test_yachiyo_agent_service_treats_scoped_recovery_events_as_planner_events() -> None:
    class ScopedRecoveryRuntimePort(_BareStartTaskRuntimePort):
        def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(("start_chat_task", request))
            return _task_payload(
                status="running",
                title=request.get("title") or "Chat task",
                session_id=str(request.get("conversation_id") or ""),
                events=[
                    {
                        "event_type": "group.run.replan.recovery.updated",
                        "payload": {
                            "planner_event_type": "agent.replan.recovery.updated",
                            "status": "requested",
                        },
                    }
                ],
            )

    service = YachiyoAgentService(ScopedRecoveryRuntimePort())

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
        )
    )

    assert [event.event_type for event in task.recent_events] == [
        "group.run.replan.recovery.updated"
    ]


def test_yachiyo_agent_service_defaults_main_chat_entrypoint_metadata() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
        )
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["entrypoint_source"] == "chat_window"
    assert metadata["planner_entrypoint"] == "chat_window"
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "data_analysis"
    assert metadata["yachiyo_plan_tools"] == ["data.analyze"]
    assert task.metadata["entrypoint_source"] == "chat_window"
    assert task.metadata["planner_entrypoint"] == "chat_window"


def test_yachiyo_agent_service_preserves_explicit_chat_entrypoint_metadata() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
            metadata={
                "client_message_id": "client-1",
                "source": "chat",
                "runnable_kind": "main",
                "planner_entrypoint": "chat_default",
            },
        )
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["client_message_id"] == "client-1"
    assert metadata["source"] == "chat"
    assert metadata["entrypoint_source"] == "chat_window"
    assert metadata["runnable_kind"] == "main"
    assert metadata["planner_entrypoint"] == "chat_default"
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "data_analysis"
    assert task.metadata["source"] == "chat"
    assert task.metadata["entrypoint_source"] == "chat_window"
    assert task.metadata["planner_entrypoint"] == "chat_default"


def test_yachiyo_agent_service_preserves_launcher_entrypoint_for_data_analysis() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    for mode in ("bubble", "live2d"):
        task = service.start_chat_task(
            StartChatTaskRequest(
                prompt="请分析 data/sales.csv 并输出报告",
                conversation_id=f"{mode}-chat",
                metadata={
                    "source": "launcher",
                    "launcher_mode": mode,
                },
            )
        )
        metadata = port.calls[-1][1]["metadata"]
        assert metadata["source"] == "launcher"
        assert metadata["entrypoint_source"] == "launcher"
        assert metadata["launcher_mode"] == mode
        assert metadata["launcher_surface"] == "desktop_launcher"
        assert metadata["planner_entrypoint"] == f"{mode}_default"
        assert metadata["runnable_kind"] == "main"
        assert metadata["yachiyo_runtime_planner"] is True
        assert metadata["yachiyo_intent_kind"] == "data_analysis"
        assert metadata["yachiyo_plan_tools"] == ["data.analyze"]
        assert metadata["yachiyo_plan_artifacts_expected"] == ["analysis-report.md"]
        assert task.metadata["planner_entrypoint"] == f"{mode}_default"


def test_yachiyo_agent_service_surfaces_data_analysis_open_questions_to_chat_task() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="输出一份数据分析",
            conversation_id="chat-1",
            title="Data analysis",
        )
    )

    metadata = port.calls[0][1]["metadata"]
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "data_analysis"
    assert metadata["yachiyo_candidate_intents"] == [
        {"kind": "data_analysis", "title": "Data Analysis", "confidence": 0.56}
    ]
    assert metadata["yachiyo_plan_tools"] == [
        "workspace.list",
        "python.run",
        "artifact.write",
    ]
    assert metadata["yachiyo_required_capabilities"] == [
        "file.workspace_read",
        "data.analysis",
        "artifact.write",
    ]
    assert metadata["yachiyo_plan_open_questions"] == ["data_source"]
    assert task.metadata["yachiyo_plan_open_questions"] == ["data_source"]
    assert task.metadata["yachiyo_required_capabilities"] == [
        "file.workspace_read",
        "data.analysis",
        "artifact.write",
    ]


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
    assert timeline.events[0].task_id == "task-1"
    assert timeline.pending_approval is not None
    assert timeline.pending_approval.tool_name == "workspace.write_patch"
    assert timeline.tool_calls[0].tool_name == "workspace.write_patch"
    assert timeline.tool_calls[0].task_id == "task-1"
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
        "task_id": "task-music",
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


def test_yachiyo_agent_service_preserves_readiness_recovered_timeline_event() -> None:
    port = _ReadinessRecoveredTaskRuntimePort()
    service = YachiyoAgentService(port)

    timeline = service.get_task_timeline("task-pixelforge")

    assert timeline.events[0].event_type == "agent.desktop.readiness_recovered"
    assert timeline.events[0].payload["status"] == "recovered"
    assert timeline.events[0].payload["recovery_tool"] == "desktop.list_apps"
    assert timeline.events[0].payload["blocking_conditions"] == ["app_not_found"]
    assert timeline.tool_calls == []
    assert port.calls == [("get_task_timeline", "task-pixelforge")]


def test_yachiyo_agent_service_projects_completed_desktop_intent_as_tool_call() -> None:
    port = _CompletedDesktopIntentTaskRuntimePort()
    service = YachiyoAgentService(port)

    timeline = service.get_task_timeline("task-windows")

    assert timeline.events[0].event_type == "agent.desktop.intent_completed"
    assert len(timeline.tool_calls) == 1
    assert timeline.tool_calls[0].tool_name == "desktop.windows"
    assert timeline.tool_calls[0].status == "completed"
    assert timeline.tool_calls[0].input_preview == {
        "app_name": "Google Chrome",
        "task_id": "task-windows",
    }
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
    assert timeline.tool_calls[0].input_preview == {
        "app_name": "WeChat",
        "task_id": "task-wechat",
    }
    assert timeline.tool_calls[0].output_preview["action"] == "app.open"
    assert timeline.tool_calls[1].input_preview == {
        "role_filter": "button",
        "limit": 80,
        "task_id": "task-wechat",
    }
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
    assert page.events[0].task_id == "task-1"
    assert page.events[0].payload["task_id"] == "task-1"
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
    assert page.events[0].task_id == "task-1"
    assert page.events[0].payload == {"step": "read workspace", "task_id": "task-1"}
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


def _runtime_progress_tool_request(
    decision: Any,
    *,
    tool: str,
    step_id: str,
    task_id: str,
    run_id: str,
    group_run_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, Any]:
    task_core = decision.plan.task_core
    assert task_core is not None
    workspace_id = task_core.workspace.workspace_id
    todo = next((item for item in task_core.todos if item.step_id == step_id), None)
    checkpoint = next(
        (item for item in task_core.checkpoints if item.after_step_id == step_id),
        None,
    )
    return {
        "tool": tool,
        "input": {"path": "data/sales.csv"},
        "source": "runtime_planner",
        "step_id": step_id,
        "core_id": task_core.core_id,
        "workspace_id": workspace_id,
        "decision_id": decision.decision_id,
        "plan_id": decision.plan.plan_id,
        "task_id": task_id,
        "run_id": run_id,
        "group_run_id": group_run_id,
        "workflow_run_id": workflow_run_id,
        "task_workspace_items": [
            {
                "item_id": f"workspace-{step_id}",
                "title": "data/sales.csv",
                "kind": "file",
                "status": "planned",
                "source_step_id": step_id,
            }
        ],
        "task_todo": (
            todo.model_dump(mode="python")
            if todo is not None
            else {
                "todo_id": f"todo-{step_id}",
                "title": step_id,
                "status": "pending",
                "step_id": step_id,
                "tool_name": tool,
            }
        ),
        "task_checkpoints": [
            checkpoint.model_dump(mode="python")
            if checkpoint is not None
            else {
                "checkpoint_id": f"checkpoint-{step_id}",
                "title": f"Verify {step_id}",
                "status": "planned",
                "after_step_id": step_id,
            }
        ],
    }


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
