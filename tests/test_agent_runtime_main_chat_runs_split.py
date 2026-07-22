"""Tests for main chat run lifecycle split out of the legacy runtime."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import RuntimeTaskEventRecorder
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
        self.fences: list[dict[str, Any]] = []

    def started(self, run_id: str, **payload: Any) -> None:
        self.events.append(("started", {"run_id": run_id, **payload}))

    def completed(self, run_id: str, **payload: Any) -> dict[str, Any]:
        self.fences.append(
            {
                key: payload.pop(key)
                for key in ("expected_status", "expected_updated_at")
                if key in payload
            }
        )
        self.events.append(("completed", {"run_id": run_id, **payload}))
        return {"event_type": "run.completed"}

    def failed(self, run_id: str, **payload: Any) -> dict[str, Any]:
        self.fences.append(
            {
                key: payload.pop(key)
                for key in ("expected_status", "expected_updated_at")
                if key in payload
            }
        )
        self.events.append(("failed", {"run_id": run_id, **payload}))
        return {"event_type": "run.failed"}


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


def test_main_chat_run_lifecycle_complete_preserves_pending_approval() -> None:
    for status in ("approval_required", "running"):
        run = {
            "run_id": f"run-{status}",
            "kind": "main_chat_run",
            "status": status,
            "result": "等待审批",
            "pending_approval": {
                "approval_id": f"approval-{status}",
                "tool": "desktop.verify",
            },
            "timeline": [],
        }
        events = FakeTaskEvents()
        lifecycle = MainChatRunLifecycle(
            main_chat_agent_id="builtin:yachiyo-main",
            insert_run=lambda **_payload: {},
            link_task_run=lambda **_payload: None,
            get_run=lambda _run_id, current=run: current,
            update_run=lambda *_args, **_payload: (_ for _ in ()).throw(
                AssertionError("pending approval must not be completed")
            ),
            task_run_links=FakeTaskRunLinks(),
            task_events=events,
            timeline_factory=_timeline,
            redact_secrets=str,
            final_statuses={"completed", "failed", "cancelled"},
        )

        preserved = lifecycle.complete(run["run_id"], "model says done")

        assert preserved == run
        assert events.events == []


def test_main_chat_run_lifecycle_complete_preserves_awaiting_user() -> None:
    run = {
        "run_id": "run-awaiting-user",
        "kind": "main_chat_run",
        "status": "awaiting_user",
        "result": "请问要整理哪个目录？",
        "pending_approval": {},
        "timeline": [],
    }
    events = FakeTaskEvents()
    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **_payload: {},
        link_task_run=lambda **_payload: None,
        get_run=lambda _run_id: run,
        update_run=lambda *_args, **_payload: pytest.fail(
            "awaiting_user must not be completed"
        ),
        task_run_links=FakeTaskRunLinks(),
        task_events=events,
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
    )

    preserved = lifecycle.complete(run["run_id"], "model says done")

    assert preserved == run
    assert events.events == []


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
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "virtual_desktop_backend",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "env": {"SECRET": "not-for-timeline"},
            "command": ["python", "scripts/run_isolated_desktop_provider.py"],
            "request_ids": ["request-click"],
            "tool_names": ["app.focus_and_click_ui_element"],
            "supported_tools": [
                "app.focus_and_click_ui_element",
                "desktop.inspect_app",
            ],
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
    assert provider_event["desktop_provider_session"]["desktop_session_kind"] == (
        "isolated_desktop"
    )
    assert provider_event["desktop_provider_session"]["desktop_session_isolated"] is True
    assert provider_event["desktop_provider_session"]["foreground_takeover_required"] is False
    assert (
        provider_event["desktop_provider_session"]["keyboard_mouse_capture_supported"]
        is True
    )
    assert provider_event["desktop_provider_session"]["desktop_backend_kind"] == (
        "virtual_desktop_backend"
    )
    assert provider_event["desktop_provider_session"]["desktop_backend_is_loopback"] is False
    assert (
        provider_event["desktop_provider_session"][
            "desktop_backend_ready_for_public_release"
        ]
        is True
    )
    assert (
        provider_event["desktop_provider_session"][
            "requires_real_virtual_desktop_backend"
        ]
        is False
    )
    assert provider_event["desktop_provider_session"]["request_ids"] == [
        "request-click"
    ]
    assert provider_event["desktop_provider_session"]["supported_tools"] == [
        "app.focus_and_click_ui_element",
        "desktop.inspect_app",
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
    assert projected_event.payload["desktop_provider_session"][
        "desktop_session_isolated"
    ] is True
    assert projected_event.payload["desktop_provider_session"][
        "foreground_takeover_required"
    ] is False
    assert projected_event.payload["desktop_provider_session"][
        "keyboard_mouse_capture_supported"
    ] is True
    assert projected_event.payload["desktop_provider_session"][
        "desktop_backend_kind"
    ] == "virtual_desktop_backend"
    assert projected_event.payload["desktop_provider_session"]["supported_tools"] == [
        "app.focus_and_click_ui_element",
        "desktop.inspect_app",
    ]
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


def test_main_chat_completion_cas_preserves_approval_created_during_completion() -> None:
    events = FakeTaskEvents()
    current = {
        "run_id": "run-race",
        "status": "running",
        "result": "",
        "pending_approval": {},
        "timeline": [],
        "updated_at": "2026-07-11T10:00:00+00:00",
    }

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any] | None:
        assert payload["expected_status"] == "running"
        assert payload["expected_updated_at"] == "2026-07-11T10:00:00+00:00"
        assert payload["expected_pending_approval_absent"] is True
        current.update(
            status="approval_required",
            result="等待审批：desktop.verify",
            pending_approval={
                "approval_id": "approval-new",
                "tool": "desktop.verify",
            },
            updated_at="2026-07-11T10:00:01+00:00",
        )
        return None

    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **_payload: current,
        link_task_run=lambda **_payload: None,
        get_run=lambda _run_id: dict(current),
        update_run=update_run,
        task_run_links=FakeTaskRunLinks(),
        task_events=events,
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
    )

    preserved = lifecycle.complete("run-race", "model says done")

    assert preserved["status"] == "approval_required"
    assert preserved["pending_approval"]["approval_id"] == "approval-new"
    assert events.events == []


def test_main_chat_failure_cas_preserves_concurrent_cancellation() -> None:
    events = FakeTaskEvents()
    current = {
        "run_id": "run-fail-race",
        "status": "running",
        "result": "",
        "pending_approval": {},
        "timeline": [],
        "updated_at": "2026-07-11T10:00:00+00:00",
    }

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any] | None:
        assert payload["expected_status"] == "running"
        assert payload["expected_updated_at"] == "2026-07-11T10:00:00+00:00"
        assert payload["expected_pending_approval_absent"] is True
        current.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="2026-07-11T10:00:01+00:00",
        )
        return None

    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **_payload: current,
        link_task_run=lambda **_payload: None,
        get_run=lambda _run_id: dict(current),
        update_run=update_run,
        task_run_links=FakeTaskRunLinks(),
        task_events=events,
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
    )

    preserved = lifecycle.fail("run-fail-race", "late model failure")

    assert preserved["status"] == "cancelled"
    assert preserved["result"] == "cancelled by user"
    assert events.events == []


def test_main_chat_failure_cas_preserves_concurrent_approval() -> None:
    events = FakeTaskEvents()
    current = {
        "run_id": "run-fail-approval-race",
        "status": "running",
        "result": "",
        "pending_approval": {},
        "timeline": [],
        "updated_at": "2026-07-11T10:00:00+00:00",
    }

    def update_run(_run_id: str, **_payload: Any) -> None:
        current.update(
            status="approval_required",
            result="waiting for approval",
            pending_approval={
                "approval_id": "approval-during-fail",
                "tool": "terminal.run",
            },
            updated_at="2026-07-11T10:00:01+00:00",
        )
        return None

    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **_payload: current,
        link_task_run=lambda **_payload: None,
        get_run=lambda _run_id: dict(current),
        update_run=update_run,
        task_run_links=FakeTaskRunLinks(),
        task_events=events,
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
    )

    preserved = lifecycle.fail("run-fail-approval-race", "late model failure")

    assert preserved["status"] == "approval_required"
    assert preserved["pending_approval"]["approval_id"] == "approval-during-fail"
    assert events.events == []


def test_main_chat_failure_rolls_back_row_and_events_when_second_event_fails() -> None:
    run = {
        "run_id": "run-fail-atomic",
        "kind": "main_chat_run",
        "status": "running",
        "result": "",
        "pending_approval": None,
        "timeline": [],
        "updated_at": "version-1",
    }
    appended_events: list[str] = []

    @contextmanager
    def transaction_scope() -> Any:
        run_snapshot = deepcopy(run)
        events_snapshot = list(appended_events)
        try:
            yield
        except BaseException:
            run.clear()
            run.update(run_snapshot)
            appended_events[:] = events_snapshot
            raise

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any] | None:
        if run["status"] != payload.pop("expected_status"):
            return None
        if run["updated_at"] != payload.pop("expected_updated_at"):
            return None
        payload.pop("expected_pending_approval_absent")
        run.update(payload)
        run["updated_at"] = "version-2"
        return dict(run)

    def append_run_event(
        _run_id: str,
        event_type: str,
        _payload: dict[str, Any],
        **fence: Any,
    ) -> dict[str, Any] | None:
        assert fence == {
            "expected_status": "failed",
            "expected_updated_at": "version-2",
        }
        appended_events.append(event_type)
        if len(appended_events) == 2:
            return None
        return {"event_type": event_type}

    lifecycle = MainChatRunLifecycle(
        main_chat_agent_id="builtin:yachiyo-main",
        insert_run=lambda **_payload: run,
        link_task_run=lambda **_payload: None,
        get_run=lambda _run_id: dict(run),
        update_run=update_run,
        task_run_links=FakeTaskRunLinks(),
        task_events=RuntimeTaskEventRecorder(append_run_event=append_run_event),
        append_run_event=append_run_event,
        timeline_factory=_timeline,
        redact_secrets=str,
        final_statuses={"completed", "failed", "cancelled"},
        transaction_scope=transaction_scope,
    )

    with pytest.raises(AgentRuntimeError, match="run_event_fence_mismatch"):
        lifecycle.fail(
            run["run_id"],
            "model failed",
            timeline=[
                _timeline("model.request.failed", "model failed"),
            ],
            run_events=[
                ("model.request.failed", {"error": "model failed"}),
            ],
        )

    assert run == {
        "run_id": "run-fail-atomic",
        "kind": "main_chat_run",
        "status": "running",
        "result": "",
        "pending_approval": None,
        "timeline": [],
        "updated_at": "version-1",
    }
    assert appended_events == []


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
