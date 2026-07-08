"""Tests for main chat run lifecycle split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.main_chat_runs import MainChatRunLifecycle
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent.run_snapshots import run_timeline_snapshot_from_payload


class FakeTaskRunLinks:
    def __init__(self) -> None:
        self.links: dict[str, dict[str, str]] = {}

    def for_run(self, run_id: str) -> dict[str, str] | None:
        return self.links.get(run_id)


class FakeTaskEvents:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def started(self, run_id: str, **payload: Any) -> None:
        self.events.append(("started", {"run_id": run_id, **payload}))

    def completed(self, run_id: str, **payload: Any) -> None:
        self.events.append(("completed", {"run_id": run_id, **payload}))

    def failed(self, run_id: str, **payload: Any) -> None:
        self.events.append(("failed", {"run_id": run_id, **payload}))


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def test_main_chat_run_lifecycle_projects_task_events() -> None:
    links = FakeTaskRunLinks()
    events = FakeTaskEvents()
    runs: dict[str, dict[str, Any]] = {}

    def insert_run(**payload: Any) -> dict[str, Any]:
        run = {"run_id": "run-1", "status": "created", "timeline": [], **payload}
        runs[run["run_id"]] = run
        return run

    def link_task_run(*, task_id: str, run_id: str, session_id: str) -> None:
        links.links[run_id] = {"task_id": task_id, "session_id": session_id}

    def update_run(run_id: str, **payload: Any) -> dict[str, Any]:
        runs[run_id] = {**runs[run_id], **payload}
        return runs[run_id]

    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=insert_run,
        link_task_run=link_task_run,
        get_run=lambda run_id: runs[run_id],
        update_run=update_run,
        task_run_links=links,
        task_events=events,
        timeline_factory=_timeline,
        redact_secrets=lambda value: str(value).replace("secret", "[redacted]"),
        final_statuses={"completed", "failed", "cancelled"},
    )

    started = lifecycle.start(task_id="task-1", session_id="session-1", user_goal="keep secret")
    completed = lifecycle.complete("run-1", "done secret")

    assert started["kind"] == "main_chat_run"
    assert started["runnable_id"] == "builtin:yachiyo-main"
    assert started["user_goal"] == "keep [redacted]"
    assert [item["event"] for item in started["timeline"]] == [
        "run.started",
        "task.created",
        "task.started",
        "task.linked",
    ]
    assert completed["status"] == "completed"
    assert completed["result"] == "done [redacted]"
    assert events.events == [
        ("started", {"run_id": "run-1", "task_id": "task-1", "session_id": "session-1"}),
        (
            "completed",
            {
                "run_id": "run-1",
                "task_id": "task-1",
                "session_id": "session-1",
                "result": "done [redacted]",
            },
        ),
    ]


def test_main_chat_run_lifecycle_records_runtime_context_on_start() -> None:
    runs: dict[str, dict[str, Any]] = {}
    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **payload: runs.setdefault(
            "run-1",
            {"run_id": "run-1", "status": "created", "timeline": [], **payload},
        ),
        link_task_run=lambda **_payload: None,
        get_run=lambda run_id: runs[run_id],
        update_run=lambda run_id, **payload: runs.__setitem__(
            run_id,
            {**runs[run_id], **payload},
        )
        or runs[run_id],
        task_run_links=FakeTaskRunLinks(),
        task_events=FakeTaskEvents(),
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
    )
    envelope = {"envelope_id": "env-main", "requests": [{"tool_name": "app.open"}]}
    direct_request = {"tool": "app.open", "input": {"app_name": "Music"}}

    run = lifecycle.start(
        task_id="task-1",
        session_id="session-1",
        user_goal="open music",
        metadata={"yachiyo_runtime_planner": True},
        runtime_execution_envelope=envelope,
        direct_tool_requests=[direct_request],
    )

    started = run["timeline"][0]
    assert started["event"] == "run.started"
    assert started["metadata"]["yachiyo_runtime_planner"] is True
    assert started["runtime_execution_envelope"] == envelope
    assert started["direct_tool_requests"] == [direct_request]


def test_main_chat_run_lifecycle_records_desktop_provider_session_event() -> None:
    runs: dict[str, dict[str, Any]] = {}
    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **payload: runs.setdefault(
            "run-1",
            {"run_id": "run-1", "status": "created", "timeline": [], **payload},
        ),
        link_task_run=lambda **_payload: None,
        get_run=lambda run_id: runs[run_id],
        update_run=lambda run_id, **payload: runs.__setitem__(
            run_id,
            {**runs[run_id], **payload},
        )
        or runs[run_id],
        task_run_links=FakeTaskRunLinks(),
        task_events=FakeTaskEvents(),
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
    )
    envelope = {
        "envelope_id": "env-main",
        "requests": [
            {
                "request_id": "request-click",
                "tool_name": "app.focus_and_click_ui_element",
            }
        ],
        "desktop_provider_session": {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "needed": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "env": {"SECRET": "not-for-timeline"},
            "command": ["python", "scripts/run_isolated_desktop_provider.py"],
            "request_ids": ["request-click"],
            "tool_names": ["app.focus_and_click_ui_element"],
        },
    }

    run = lifecycle.start(
        task_id="task-1",
        session_id="session-1",
        user_goal="click export",
        runtime_execution_envelope=envelope,
    )

    assert [item["event"] for item in run["timeline"]] == [
        "run.started",
        "desktop.provider_session.started",
        "task.created",
        "task.started",
        "task.linked",
    ]
    provider_event = run["timeline"][1]
    assert provider_event["task_id"] == "task-1"
    assert provider_event["session_id"] == "session-1"
    assert provider_event["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert provider_event["desktop_provider_session"]["started"] is True
    assert provider_event["desktop_provider_session"][
        "desktop_execution_session_mode"
    ] == "isolated_desktop"
    assert provider_event["desktop_provider_session"][
        "desktop_execution_session_label"
    ] == "isolated desktop provider"
    assert provider_event["desktop_provider_session"]["request_ids"] == [
        "request-click"
    ]
    assert "env" not in provider_event["desktop_provider_session"]
    assert "command" not in provider_event["desktop_provider_session"]
    snapshot = run_timeline_snapshot_from_payload(run)
    projected_event = next(
        event
        for event in snapshot.events
        if event.event_type == "desktop.provider_session.started"
    )
    assert projected_event.task_id == "task-1"
    assert projected_event.payload["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert projected_event.payload["desktop_provider_session"][
        "desktop_execution_session_mode"
    ] == "isolated_desktop"
    assert "env" not in projected_event.payload["desktop_provider_session"]


def test_main_chat_run_lifecycle_keeps_terminal_run_idempotent() -> None:
    events = FakeTaskEvents()
    run = {"run_id": "run-1", "status": "cancelled", "timeline": []}
    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **_payload: run,
        link_task_run=lambda **_payload: None,
        get_run=lambda _run_id: run,
        update_run=lambda _run_id, **payload: {**run, **payload},
        task_run_links=FakeTaskRunLinks(),
        task_events=events,
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
    )

    assert lifecycle.complete("run-1", "late") is run
    assert lifecycle.fail("run-1", "late") is run
    assert events.events == []


def test_native_runtime_installs_main_chat_run_lifecycle(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.MainChatRunLifecycle is MainChatRunLifecycle
        assert isinstance(service.main_chat_runs, MainChatRunLifecycle)

        run = service.start_main_chat_run(
            task_id="task-main",
            session_id="session-main",
            user_goal="hello",
        )
        completed = service.complete_main_chat_run(run["run_id"], "done")

        assert run["kind"] == "main_chat_run"
        assert completed["status"] == "completed"
    finally:
        service.close()
