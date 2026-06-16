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
                    "tool_policy": {"allowed_tools": ["workspace.read"]},
                }
            ],
            "workflows": [
                {
                    "workflow_id": "workflow-1",
                    "name": "Review workflow",
                    "nodes": [{"id": "review", "type": "agent"}],
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

    def approve(self, approval_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("approve", {"approval_id": approval_id, "decision": decision}))
        return _task_payload(status="completed", result="Approved")

    def reject(self, approval_id: str, reason: str | None = None) -> dict[str, Any]:
        self.calls.append(("reject", {"approval_id": approval_id, "reason": reason}))
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


def test_yachiyo_agent_service_maps_chat_runnable_catalog() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    catalog = service.list_runnable_catalog()

    assert catalog.agents[0].agent_id == "agent-1"
    assert catalog.agents[0].tool_policy == {"allowed_tools": ["workspace.read"]}
    assert catalog.workflows[0].workflow_id == "workflow-1"
    assert catalog.workflows[0].nodes == [{"id": "review", "type": "agent"}]
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
        "approval-1",
        ApprovalDecision(approved=True, reason="Looks safe"),
    )
    rejected = service.reject("approval-2", "No")
    cancelled = service.cancel("task-1")

    assert approved.status == "completed"
    assert rejected.status == "failed"
    assert cancelled.status == "cancelled"
    assert port.calls == [
        (
            "approve",
            {
                "approval_id": "approval-1",
                "decision": {"approved": True, "reason": "Looks safe", "metadata": {}},
            },
        ),
        ("reject", {"approval_id": "approval-2", "reason": "No"}),
        ("cancel", "task-1"),
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
