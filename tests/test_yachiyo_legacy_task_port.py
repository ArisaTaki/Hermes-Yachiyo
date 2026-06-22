"""Legacy Chat task runtime port adapter tests."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent.legacy_ports import LegacyRuntimePort as CompatLegacyRuntimePort
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort


def test_legacy_runtime_port_starts_and_links_chat_task() -> None:
    runtime = _FakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    assert CompatLegacyRuntimePort is LegacyRuntimePort
    assert task["task_id"] == "task-1"
    assert task["conversation_id"] == "chat-1"
    assert task["open_in_studio_url"] == "#/agents?run_id=run-1"
    assert runtime.calls == [
        (
            "create_run_for_runnable_async",
            {"runnable_id": "builtin:yachiyo-main", "user_goal": "Patch README"},
        ),
        ("link_task_run", {"task_id": "task-1", "run_id": "run-1", "session_id": "chat-1"}),
        ("get_run", "run-1"),
    ]


def test_legacy_runtime_port_readiness_includes_desktop_execution_capabilities() -> None:
    runtime = _FakeRuntime()

    readiness = LegacyRuntimePort(runtime).readiness()
    capabilities = readiness["capabilities"]

    assert readiness["ok"] is True
    assert capabilities["tasks"] is True
    assert capabilities["runnables"] == 1
    assert capabilities["desktop_execution"]["platform"] in {
        "macos",
        "windows",
        "linux",
        "unknown",
    }
    assert capabilities["desktop_execution"]["available"] is (
        capabilities["desktop_execution"]["platform"] == "macos"
    )
    assert "screen.capture" in capabilities["screen_capture"]["tools"]
    assert capabilities["foreground_input"]["risk_default"] == "medium"
    assert runtime.calls == [("list_runnables", None)]


def test_legacy_runtime_port_starts_and_links_chat_workflow_task() -> None:
    runtime = _FakeRuntime()

    task = LegacyRuntimePort(runtime).start_chat_task(
        {
            "prompt": "Build report",
            "conversation_id": "chat-1",
            "client_task_id": "task-workflow-1",
            "workflow_id": "workflow-1",
        }
    )

    assert task["task_id"] == "task-workflow-1"
    assert task["conversation_id"] == "chat-1"
    assert task["open_in_studio_url"] == "#/agents?run_id=workflow-run-1"
    assert (
        "create_workflow_run",
        {
            "workflow_id": "workflow-1",
            "user_goal": "Build report",
            "source": "yachiyo_chat",
            "client_run_id": "task-workflow-1",
        },
    ) in runtime.calls
    assert (
        "link_task_run",
        {"task_id": "task-workflow-1", "run_id": "workflow-run-1", "session_id": "chat-1"},
    ) in runtime.calls


def test_legacy_runtime_port_preserves_workflow_identity_after_task_approval() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Build report",
            "conversation_id": "chat-1",
            "client_task_id": "task-workflow-1",
            "workflow_id": "workflow-1",
        }
    )

    approved = port.approve("task-workflow-1")
    rejected = port.reject(
        "task-workflow-1",
        {
            "approved": False,
            "reason": "No",
            "metadata": {"approval_id": "approval-workflow-1"},
        },
    )

    assert approved["task_id"] == "task-workflow-1"
    assert approved["status"] == "completed"
    assert approved["kind"] == "workflow_run"
    assert approved["workflow_run_id"] == "workflow-run-1"
    assert approved["workflow_id"] == "workflow-1"
    assert rejected["task_id"] == "task-workflow-1"
    assert rejected["status"] == "failed"
    assert rejected["kind"] == "workflow_run"
    assert rejected["workflow_run_id"] == "workflow-run-1"
    assert rejected["workflow_id"] == "workflow-1"
    assert ("approve_run_approval", "workflow-run-1") in runtime.calls
    assert ("reject_run_approval", {"run_id": "workflow-run-1", "reason": "No"}) in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_approval_actions() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    approved = port.approve("task-1")

    assert approved["task_id"] == "task-1"
    assert approved["session_id"] == "chat-1"
    assert approved["task_run_link_run_status"] == "running"
    assert ("approve_run_approval", "run-1") in runtime.calls
    assert ("get_task_run_link", "task-1") in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_timeline() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    timeline = port.get_task_timeline("task-1")

    assert timeline["run_id"] == "run-1"
    assert timeline["task_id"] == "task-1"
    assert timeline["session_id"] == "chat-1"
    assert timeline["task_run_link_run_status"] == "running"
    assert timeline["task_run_link_last_event_sequence"] == 1
    assert timeline["timeline"][0]["event"] == "run.started"
    assert ("get_task_run_link", "task-1") in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_event_stream() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    events = port.get_task_event_stream("task-1")

    assert events["run_id"] == "run-1"
    assert events["events"][0]["event"] == "run.started"
    assert ("list_run_events", "run-1") in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_event_page_fallback() -> None:
    runtime = _FakeRuntime()
    runtime.runs["run-1"]["timeline"] = [
        {"event": "run.started"},
        {"event": "agent.progress"},
    ]
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    page = port.get_task_event_page("task-1", after_sequence=1, limit=1)

    assert page["run_id"] == "run-1"
    assert page["after_sequence"] == 1
    assert page["limit"] == 1
    assert page["next_after_sequence"] == 2
    assert page["has_more"] is False
    assert page["events"] == [{"event": "agent.progress"}]
    assert ("list_run_events", "run-1") in runtime.calls


def test_legacy_runtime_port_prefers_runtime_event_page_for_task_events() -> None:
    runtime = _PagedFakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    page = port.get_task_event_page("task-1", after_sequence=-2, limit=999)

    assert page["run_id"] == "run-1"
    assert page["after_sequence"] == 0
    assert page["limit"] == 500
    assert page["next_after_sequence"] == 5
    assert page["has_more"] is True
    assert page["events"] == [{"event": "agent.progress", "sequence": 5}]
    assert (
        "get_run_event_page",
        {"run_id": "run-1", "after_sequence": 0, "limit": 500},
    ) in runtime.calls
    assert ("list_run_events", "run-1") not in runtime.calls


def test_legacy_runtime_port_resolves_task_link_for_artifact_read() -> None:
    runtime = _FakeRuntime()
    port = LegacyRuntimePort(runtime)
    port.start_chat_task(
        {
            "prompt": "Patch README",
            "conversation_id": "chat-1",
            "client_task_id": "task-1",
        }
    )

    artifact = port.read_task_artifact("task-1", "reports/out.md")

    assert artifact["run_id"] == "run-1"
    assert artifact["task_id"] == "task-1"
    assert artifact["path"] == "reports/out.md"
    assert artifact["content"] == "# Report"
    assert ("read_run_artifact", {"run_id": "run-1", "artifact_path": "reports/out.md"}) in runtime.calls


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.runs = {
            "run-1": {
                "run_id": "run-1",
                "user_goal": "Patch README",
                "status": "running",
                "timeline": [{"event": "run.started"}],
            },
            "workflow-run-1": {
                "run_id": "workflow-run-1",
                "kind": "workflow_run",
                "workflow_run_id": "workflow-run-1",
                "workflow_id": "workflow-1",
                "user_goal": "Build report",
                "status": "running",
                "timeline": [{"event": "workflow.run.started"}],
            },
        }
        self.task_links: dict[str, dict[str, Any]] = {}

    def list_runnables(self) -> dict[str, Any]:
        self.calls.append(("list_runnables", None))
        return {"runnables": [{"id": "builtin:yachiyo-main"}]}

    def create_run_for_runnable_async(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(("create_run_for_runnable_async", payload))
        return dict(self.runs["run-1"])

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_workflow_run", payload))
        return dict(self.runs["workflow-run-1"])

    def get_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run", run_id))
        return dict(self.runs[run_id])

    def list_run_events(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("list_run_events", run_id))
        return {"events": list(self.runs[run_id]["timeline"])}

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        self.calls.append(
            ("read_run_artifact", {"run_id": run_id, "artifact_path": artifact_path})
        )
        return {
            "ok": True,
            "run_id": run_id,
            "path": artifact_path,
            "content": "# Report",
        }

    def link_task_run(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        self.calls.append(
            ("link_task_run", {"task_id": task_id, "run_id": run_id, "session_id": session_id})
        )
        self.task_links[task_id] = {
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "run_status": self.runs[run_id]["status"],
            "last_event_sequence": 1,
            "created_at": "2026-06-14T00:00:00Z",
            "updated_at": "2026-06-14T00:00:02Z",
        }
        return self.task_links[task_id]

    def get_task_run_link(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_run_link", task_id))
        try:
            return self.task_links[task_id]
        except KeyError:
            raise KeyError(task_id) from None

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("approve_run_approval", run_id))
        return {
            "run_id": run_id,
            "user_goal": "Patch README",
            "status": "completed",
        }

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        self.calls.append(("reject_run_approval", {"run_id": run_id, "reason": reason}))
        return {
            "run_id": run_id,
            "user_goal": "Patch README",
            "status": "failed",
        }


class _PagedFakeRuntime(_FakeRuntime):
    def get_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "get_run_event_page",
                {
                    "run_id": run_id,
                    "after_sequence": after_sequence,
                    "limit": limit,
                },
            )
        )
        return {
            "run_id": run_id,
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": 5,
            "has_more": True,
            "events": [{"event": "agent.progress", "sequence": 5}],
        }
