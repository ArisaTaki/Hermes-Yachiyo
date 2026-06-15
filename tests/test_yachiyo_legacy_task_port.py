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


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.runs = {
            "run-1": {
                "run_id": "run-1",
                "user_goal": "Patch README",
                "status": "running",
                "timeline": [{"event": "run.started"}],
            }
        }
        self.task_links: dict[str, dict[str, Any]] = {}

    def list_runnables(self) -> dict[str, Any]:
        self.calls.append(("list_runnables", None))
        return {"runnables": [{"id": "builtin:yachiyo-main"}]}

    def create_run_for_runnable_async(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(("create_run_for_runnable_async", payload))
        return dict(self.runs["run-1"])

    def get_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run", run_id))
        return dict(self.runs[run_id])

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
