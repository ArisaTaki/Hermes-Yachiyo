"""Fake-port tests for the Chat-facing Yachiyo Agent service."""

from __future__ import annotations

import json
from typing import Any

from apps.shell.agent.runtime.desktop_execution_providers import (
    LOCAL_DESKTOP_PROVIDER_ID,
    LOCAL_DESKTOP_PROVIDER_KIND,
)
from apps.shell.yachiyo_agent import (
    AgentStudioService,
    ApprovalDecision,
    StartChatTaskRequest,
    YachiyoAgentService,
)
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_envelope_from_decision,
    runtime_execution_requests_from_envelope_payload,
)
from apps.shell.yachiyo_agent.replan_recovery_snapshots import (
    replan_recovery_snapshots_from_runtime_execution_envelope,
)
from apps.shell.yachiyo_agent.task_cards import agent_task_snapshot_from_payload


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
            "groups": [
                {
                    "group_id": "group-1",
                    "name": "Review group",
                    "members": [
                        {"agent_id": "agent-1", "role": "reviewer"},
                    ],
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


def _clear_test_desktop_provider_env(monkeypatch: Any) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_MUTATION_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK",
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE",
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
    ):
        monkeypatch.delenv(key, raising=False)


def _install_fake_isolated_provider_session(
    monkeypatch: Any,
    probe_calls: list[str] | None = None,
) -> list[dict[str, Any]]:
    start_calls: list[dict[str, Any]] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": True,
                    "status": "ready",
                    "version": "0.1.0",
                    "provider_id": "local-isolated-desktop",
                    "provider_kind": "sandbox_desktop",
                    "supported_tools": [
                        "desktop.list_apps",
                        "app.open",
                        "desktop.active_window",
                        "desktop.verify",
                        "app.focus_and_click_ui_element",
                        "desktop.safe_shortcut",
                        "desktop.type",
                        "desktop.safe_key",
                        "desktop.click_ui_element",
                        "desktop.ui_elements",
                        "media.music_app_open_and_play",
                    ],
                    "capabilities": [
                        "desktop_discovery",
                        "keyboard_mouse_capture",
                        "isolated_desktop",
                    ],
                    "keyboard_mouse_capture_supported": True,
                    "foreground_mutation_supported": True,
                    "desktop_session_isolated": True,
                    "foreground_takeover_required": False,
                    "desktop_session_kind": "isolated_desktop",
                    "desktop_backend_kind": "virtual_desktop",
                    "desktop_backend_is_loopback": False,
                    "desktop_backend_ready_for_public_release": True,
                    "requires_real_virtual_desktop_backend": False,
                }
            ).encode("utf-8")

        def getcode(self) -> int:
            return self.status

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        if probe_calls is not None:
            probe_calls.append(request.full_url)
        return FakeResponse()

    def fake_status() -> dict[str, Any]:
        return {
            "ok": True,
            "status": "stopped",
            "running": False,
            "provider_id": "",
            "url": "",
            "source": "test",
        }

    def fake_start(request: dict[str, Any] | None = None) -> dict[str, Any]:
        start_calls.append(dict(request or {}))
        env = {
            "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19093",
            "OHA_YACHIYO_DESKTOP_PROVIDER_ID": "local-isolated-desktop",
            "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS": (
                "desktop.list_apps,app.open,desktop.active_window,desktop.verify,"
                "app.focus_and_click_ui_element,"
                "desktop.safe_shortcut,desktop.type,desktop.safe_key,"
                "desktop.click_ui_element,desktop.ui_elements,"
                "media.music_app_open_and_play"
            ),
            "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED": "true",
            "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND": "isolated_desktop",
            "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED": "true",
            "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED": "false",
            "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_MUTATION_SUPPORTED": "true",
            "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND": "virtual_desktop",
            "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK": "false",
            "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE": "true",
            "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND": "false",
        }
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "pid": 4242,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "command": ["python", "scripts/run_isolated_desktop_provider.py"],
            "env": env,
            "provider_status": {
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "keyboard_mouse_capture_supported": True,
                "foreground_mutation_supported": True,
                "supported_tools": [
                    "desktop.list_apps",
                    "app.open",
                    "desktop.active_window",
                    "desktop.verify",
                    "app.focus_and_click_ui_element",
                    "desktop.safe_shortcut",
                    "desktop.type",
                    "desktop.safe_key",
                    "desktop.click_ui_element",
                    "desktop.ui_elements",
                    "media.music_app_open_and_play",
                ],
                "desktop_backend_kind": "virtual_desktop",
                "desktop_backend_is_loopback": False,
                "desktop_backend_ready_for_public_release": True,
                "requires_real_virtual_desktop_backend": False,
            },
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "virtual_desktop",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "source": "isolated_provider_session_manager",
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.desktop_execution_providers.urlopen_with_bundled_ca",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.isolated_provider_session."
        "isolated_desktop_provider_session_status",
        fake_status,
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.isolated_provider_session."
        "start_isolated_desktop_provider_session",
        fake_start,
    )
    return start_calls


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


class _ReplanRecoveryStudioPort(_FakeStudioExecutionPort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_timeline", run_id))
        return _replan_recovery_task_payload(task_id="task-1")

    def start_agent_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_agent_run", request))
        return _task_payload(
            task_id="studio-recovery-task",
            run_id="studio-recovery-run",
            title=request.get("title") or "Recovery",
            status="running",
        )


class _MetadataOnlyReplanRecoveryStudioPort(_ReplanRecoveryStudioPort):
    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_timeline", run_id))
        payload = _replan_recovery_task_payload(task_id="task-1")
        replan_event = payload["events"][1]
        action = replan_event["payload"]["metadata"]["recovery_actions"][0]
        action["metadata"].update(
            {
                "workspace_id": "task-workspace-1",
                "workspace_title": "Desktop Recovery Workspace",
                "task_todo": {
                    "todo_id": "todo-open-app",
                    "title": "Open Apple Music",
                    "status": "blocked",
                    "step_id": "open-app",
                    "tool_name": "desktop.open_app",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint:open-app",
                        "title": "Verify Apple Music opened",
                        "status": "blocked",
                        "after_step_id": "open-app",
                    }
                ],
                "task_workspace_items": [
                    {
                        "item_id": "workspace-open-app",
                        "title": "Apple Music app target",
                        "kind": "scratch",
                        "source_step_id": "open-app",
                        "status": "blocked",
                    }
                ],
                "task_verification_targets": [
                    {
                        "step_id": "open-app",
                        "todo": {
                            "todo_id": "todo-open-app",
                            "title": "Open Apple Music",
                            "status": "blocked",
                            "step_id": "open-app",
                        },
                        "checkpoints": [
                            {
                                "checkpoint_id": "checkpoint:open-app",
                                "title": "Verify Apple Music opened",
                                "status": "blocked",
                                "after_step_id": "open-app",
                            }
                        ],
                    }
                ],
            }
        )
        payload["events"] = [replan_event]
        return payload


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


class _FirstPageKeyStatusRuntimePort(_FakeRuntimePort):
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
            "run_id": "run-key-status",
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": 2,
            "has_more": True,
            "events": [
                {
                    "event_type": "task.started",
                    "sequence": 1,
                    "payload": {"status": "running"},
                },
                {
                    "event_type": "agent.plan.created",
                    "sequence": 2,
                    "payload": {"plan_id": "plan-1"},
                },
            ],
        }

    def get_task_event_stream(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_event_stream", task_id))
        return {
            "run_id": "run-key-status",
            "events": [
                {
                    "event_type": "task.started",
                    "sequence": 1,
                    "payload": {"status": "running"},
                },
                {
                    "event_type": "agent.plan.created",
                    "sequence": 2,
                    "payload": {"plan_id": "plan-1"},
                },
                {
                    "event_type": "desktop.provider_session.started",
                    "sequence": 3,
                    "payload": {
                        "desktop_provider_session": {
                            "provider_id": "isolated-vnc",
                            "desktop_execution_session_mode": "isolated_provider",
                        }
                    },
                },
                {
                    "event_type": "agent.tool.started",
                    "sequence": 4,
                    "payload": {"tool": "terminal.run"},
                },
                {
                    "event_type": "agent.tool.approval_required",
                    "sequence": 5,
                    "payload": {"tool": "terminal.run", "status": "approval_required"},
                },
            ],
        }


class _FirstPageRuntimeStateRuntimePort(_FakeRuntimePort):
    def __init__(self, *, include_replan: bool = True) -> None:
        super().__init__()
        self.include_replan = include_replan

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
            "run_id": "run-runtime-state",
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": 2,
            "has_more": True,
            "events": [
                {
                    "event_type": "task.started",
                    "sequence": 1,
                    "payload": {"status": "running"},
                },
                {
                    "event_type": "agent.plan.created",
                    "sequence": 2,
                    "payload": {"plan_id": "plan-1"},
                },
            ],
        }

    def get_task_event_stream(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_event_stream", task_id))
        events = [
            {
                "event_type": "task.started",
                "sequence": 1,
                "payload": {"status": "running"},
            },
            {
                "event_type": "agent.plan.created",
                "sequence": 2,
                "payload": {"plan_id": "plan-1"},
            },
            {
                "event_type": "agent.task_core.created",
                "sequence": 3,
                "payload": {"core_id": "task-core-1"},
            },
            {
                "event_type": "agent.task.todo.updated",
                "sequence": 4,
                "payload": {"todo_id": "todo-1", "status": "running"},
            },
            {
                "event_type": "agent.task.checkpoint.updated",
                "sequence": 5,
                "payload": {"checkpoint_id": "checkpoint-1", "status": "pending"},
            },
            {
                "event_type": "agent.tool.started",
                "sequence": 6,
                "payload": {"tool": "app.open"},
            },
        ]
        if self.include_replan:
            events.append(
                {
                    "event_type": "agent.replan.requested",
                    "sequence": 7,
                    "payload": {
                        "request_id": "replan-1",
                        "trigger": "verification_failed",
                    },
                }
            )
        return {"run_id": "run-runtime-state", "events": events}


class _FirstPageDesktopProviderRuntimePort(_FakeRuntimePort):
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
            "run_id": "run-provider-session",
            "after_sequence": after_sequence,
            "limit": limit,
            "next_after_sequence": 2,
            "has_more": True,
            "events": [
                {
                    "event_type": "task.started",
                    "sequence": 1,
                    "payload": {"status": "running"},
                },
                {
                    "event_type": "agent.plan.created",
                    "sequence": 2,
                    "payload": {"plan_id": "plan-1"},
                },
            ],
        }

    def get_task_event_stream(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_event_stream", task_id))
        return {
            "run_id": "run-provider-session",
            "events": [
                {
                    "event_type": "task.started",
                    "sequence": 1,
                    "payload": {"status": "running"},
                },
                {
                    "event_type": "agent.plan.created",
                    "sequence": 2,
                    "payload": {"plan_id": "plan-1"},
                },
                {
                    "event_type": "agent.tool.started",
                    "sequence": 3,
                    "payload": {"tool": "desktop.provider_session.start"},
                },
                {
                    "event_type": "desktop.provider_session.started",
                    "sequence": 4,
                    "payload": {
                        "desktop_provider_session": {
                            "provider_id": "isolated-vnc",
                            "desktop_execution_session_mode": "isolated_provider",
                        }
                    },
                },
                {
                    "event_type": "agent.deferred_continuation.enqueued",
                    "sequence": 5,
                    "payload": {
                        "deferred_continuation_count": 1,
                        "deferred_tools": ["desktop.safe_type_text"],
                    },
                },
                {
                    "event_type": "agent.tool.progress",
                    "sequence": 6,
                    "payload": {"tool": "app.open"},
                },
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


class _ReplanRecoveryTaskRuntimePort(_FakeRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _replan_recovery_task_payload(task_id=task_id)

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_chat_task", request))
        return _task_payload(
            task_id="recovery-task-1",
            run_id="recovery-run-1",
            session_id=request.get("conversation_id") or "chat-1",
            title=request.get("title") or "Recovery",
            status="running",
        )


class _ApprovalReplanRecoveryTaskRuntimePort(_ReplanRecoveryTaskRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        payload = super().get_task_timeline(task_id)
        action = payload["events"][1]["payload"]["metadata"]["recovery_actions"][0]
        action["approval_required"] = True
        action["risk_level"] = "medium"
        return payload


class _ProviderSessionReplanRecoveryTaskRuntimePort(_ReplanRecoveryTaskRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        payload = super().get_task_timeline(task_id)
        replan_payload = payload["events"][1]["payload"]
        replan_payload["trigger"] = "isolated_provider_required"
        replan_payload["source_tool_name"] = "app.focus_and_click_ui_element"
        replan_payload["target_capability_id"] = "desktop.ui_operation"
        replan_payload["metadata"]["recovery_actions"][0] = {
            "action_id": "replan-1:action:1:desktop.provider_session.start",
            "label": "Start isolated desktop provider",
            "tool": "desktop.provider_session.start",
            "input": {
                "provider_id": "local-isolated-desktop",
                "api_route": "/yachiyo/studio/tools/desktop-provider/session/start",
                "diagnostic_route": "/yachiyo/studio/tools",
            },
            "permission_target": "isolated_desktop_provider",
            "risk_level": "medium",
            "approval_required": True,
            "approval_status": "pending",
            "deferred_tool": "app.focus_and_click_ui_element",
            "deferred_input": {
                "app_name": "Apple Music",
                "target": "Play",
                "role_filter": "button",
            },
            "deferred_continuation": [
                {
                    "tool": "app.focus_and_click_ui_element",
                    "input": {
                        "app_name": "Apple Music",
                        "target": "Play",
                        "role_filter": "button",
                    },
                    "desktop_execution_policy": {
                        "prefer_isolated_desktop": True,
                        "avoid_user_foreground_takeover": True,
                        "require_sandbox_for_keyboard_mouse": True,
                    },
                }
            ],
            "metadata": {
                "runtime_retry_source": "desktop_provider_session",
                "runtime_stage": "operate",
            },
        }
        return payload


class _DeferredReplanRecoveryTaskRuntimePort(_ReplanRecoveryTaskRuntimePort):
    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        payload = super().get_task_timeline(task_id)
        action = payload["events"][1]["payload"]["metadata"]["recovery_actions"][0]
        action.update(
            {
                "deferred_tool": "desktop.click_ui_element",
                "deferred_input": {
                    "target": "Play",
                    "role_filter": "button",
                    "limit": 80,
                },
                "deferred_context": {"step_id": "operate-foreground-ui"},
                "deferred_continuation": [
                    {
                        "tool": "desktop.ui_elements",
                        "step_id": "verify-desktop-result",
                    }
                ],
            }
        )
        return payload


class _DesktopLoopReplanRecoveryTaskRuntimePort(_ReplanRecoveryTaskRuntimePort):
    def __init__(self, events: list[dict[str, Any]]) -> None:
        super().__init__()
        self._events = events

    def get_task_timeline(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_timeline", task_id))
        return _task_payload(
            task_id=task_id,
            run_id="run-1",
            session_id="chat-1",
            title="Open PixelForge",
            status="running",
            events=list(self._events),
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


def test_legacy_runtime_readiness_exposes_local_desktop_provider(monkeypatch) -> None:
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_permission_missing_by_capability",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_tasks.desktop_runtime_blocking_conditions_by_capability",
        lambda: {},
    )

    class Runtime:
        def list_runnables(self) -> dict[str, Any]:
            return {"runnables": [{"runnable_id": "main-chat"}]}

    readiness = LegacyRuntimePort(Runtime()).readiness()
    provider = readiness["capabilities"]["sandbox_provider"]

    assert readiness["ok"] is True
    assert readiness["capabilities"]["desktop_provider_ready"] is True
    assert provider["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert provider["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert provider["status"] == "available"
    assert provider["keyboard_mouse_capture_supported"] is False
    assert "desktop.safe_type_text" in provider["requires_real_sandbox_for"]
    assert "app.open" in readiness["capabilities"]["desktop_provider_supported_tools"]
    assert "desktop.inspect_app" in readiness["capabilities"]["desktop_provider_supported_tools"]
    assert (
        readiness["capabilities"]["desktop_provider_keyboard_mouse_capture_supported"]
        is False
    )
    assert "desktop.safe_type_text" in (
        readiness["capabilities"]["desktop_provider_requires_real_sandbox_for"]
    )


def test_yachiyo_agent_service_starts_replan_recovery_action_from_chat_task() -> None:
    port = _ReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_replan_recovery_action(
        "task-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "conversation_id": "chat-1",
        },
    )

    assert task.task_id == "recovery-task-1"
    assert task.metadata["source"] == "yachiyo_chat_replan_recovery"
    assert task.metadata["replan_request_id"] == "replan-1"
    assert [name for name, _payload in port.calls] == [
        "get_task_timeline",
        "start_chat_task",
    ]
    request = port.calls[1][1]
    assert request["prompt"] == "执行恢复动作：Find Apple Music"
    assert request["conversation_id"] == "chat-1"
    assert request["metadata"]["desktop_permission_recovery"] is True
    assert request["metadata"]["recovery_tool"] == "desktop.list_apps"
    assert request["metadata"]["source"] == "yachiyo_chat_replan_recovery"
    assert request["metadata"]["source_run_id"] == "run-1"
    assert request["metadata"]["source_task_id"] == "task-1"
    assert request["metadata"]["source_step_id"] == "open-app"
    assert request["metadata"]["source_tool_name"] == "desktop.open_app"
    assert request["metadata"]["target_capability_id"] == "desktop.app_discovery"
    assert request["metadata"]["replan_triggers"] == ["verification_failed", "tool_failure"]
    assert request["metadata"]["replan_signal_ids"] == ["signal-1"]
    assert request["metadata"]["task_core_context"]["core_id"] == "task-core-1"
    assert request["metadata"]["task_core_context"]["workspace_id"] == "task-workspace-1"
    assert request["metadata"]["task_core_context"]["todos"][0]["todo_id"] == (
        "todo-open-app"
    )
    assert (
        request["metadata"]["task_core_context"]["task_verification_targets"][0][
            "workspace_items"
        ][0]["item_id"]
        == "workspace-open-app"
    )
    direct_request = request["direct_tool_requests"][0]
    assert direct_request["tool"] == "desktop.list_apps"
    assert direct_request["input"] == {"query": "Apple Music"}
    assert direct_request["source"] == "yachiyo_chat_replan_recovery"
    assert direct_request["planning_reason"] == "planner_replan_runtime_recovery_action"
    assert direct_request["continue_to_model"] is True
    assert direct_request["replan_request_id"] == "replan-1"
    assert direct_request["replan_recovery_action_id"] == (
        "replan-1:action:1:desktop.list_apps"
    )
    assert direct_request["source_step_id"] == "open-app"
    assert direct_request["source_tool_name"] == "desktop.open_app"
    assert direct_request["target_capability_id"] == "desktop.app_discovery"
    assert direct_request["replan_triggers"] == ["verification_failed", "tool_failure"]
    assert direct_request["replan_signal_ids"] == ["signal-1"]
    assert direct_request["task_todo"]["todo_id"] == "todo-open-app"
    assert direct_request["task_verification_targets"][0]["step_id"] == "open-app"
    assert direct_request["approval_required"] is False
    assert request["metadata"]["replan_continuation_id"] == (
        "replan-continuation:replan-1:replan-1:action:1:desktop.list_apps"
    )
    assert request["metadata"]["replan_auto_start_eligible"] is True


def test_yachiyo_agent_service_plans_replan_continuation_without_bypassing_approval() -> None:
    port = _ApprovalReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    continuation = service.plan_replan_recovery_action(
        "task-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "conversation_id": "chat-1",
        },
    )

    assert [name for name, _payload in port.calls] == ["get_task_timeline"]
    assert continuation.request_id == "replan-1"
    assert continuation.action_id == "replan-1:action:1:desktop.list_apps"
    assert continuation.tool_name == "desktop.list_apps"
    assert continuation.conversation_id == "chat-1"
    assert continuation.approval_required is True
    assert continuation.auto_start_eligible is False
    assert continuation.auto_start_reason == "manual_replan_continuation_required"
    assert continuation.auto_start_blockers == ["approval_required"]
    assert continuation.metadata["recovery_action_approval_required"] is True
    assert continuation.metadata["replan_auto_start_eligible"] is False
    assert continuation.metadata["replan_auto_start_blockers"] == ["approval_required"]
    assert continuation.direct_tool_requests[0]["approval_required"] is True
    assert continuation.direct_tool_requests[0]["replan_recovery_action_id"] == (
        "replan-1:action:1:desktop.list_apps"
    )
    assert continuation.task_context["task_todo"]["todo_id"] == "todo-open-app"


def test_yachiyo_agent_service_marks_provider_session_recovery_as_control_action() -> None:
    port = _ProviderSessionReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    continuation = service.plan_replan_recovery_action(
        "task-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.provider_session.start",
            "conversation_id": "chat-1",
        },
    )

    direct_request = continuation.direct_tool_requests[0]
    assert continuation.tool_name == "desktop.provider_session.start"
    assert continuation.approval_required is True
    assert continuation.auto_start_eligible is False
    assert "approval_required" in continuation.auto_start_blockers
    assert "tool_not_auto_safe" in continuation.auto_start_blockers
    assert continuation.metadata["control_action"] == "desktop_provider_session.start"
    assert continuation.metadata["api_route"] == (
        "/yachiyo/studio/tools/desktop-provider/session/start"
    )
    assert continuation.metadata["diagnostic_route"] == "/yachiyo/studio/tools"
    assert continuation.metadata["recovery_action_approval_required"] is True
    assert direct_request["tool"] == "desktop.provider_session.start"
    assert direct_request["control_action"] == "desktop_provider_session.start"
    assert direct_request["api_route"] == (
        "/yachiyo/studio/tools/desktop-provider/session/start"
    )
    assert direct_request["diagnostic_route"] == "/yachiyo/studio/tools"
    assert direct_request["approval_required"] is True
    assert direct_request["target_capability_id"] == "desktop.ui_operation"
    assert direct_request["deferred_tool"] == "app.focus_and_click_ui_element"
    assert direct_request["deferred_input"] == {
        "app_name": "Apple Music",
        "target": "Play",
        "role_filter": "button",
    }
    continuation = direct_request["deferred_continuation"][0]
    assert continuation["tool"] == "app.focus_and_click_ui_element"
    assert continuation["input"] == direct_request["deferred_input"]
    assert continuation["desktop_execution_policy"]["prefer_isolated_desktop"] is True
    assert (
        continuation["desktop_execution_policy"]["avoid_user_foreground_takeover"]
        is True
    )
    assert (
        continuation["desktop_execution_policy"]["require_sandbox_for_keyboard_mouse"]
        is True
    )


def test_yachiyo_agent_service_preserves_deferred_replan_recovery_context() -> None:
    port = _DeferredReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_replan_recovery_action(
        "task-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "conversation_id": "chat-1",
        },
    )

    assert task.task_id == "recovery-task-1"
    direct_request = port.calls[1][1]["direct_tool_requests"][0]
    assert direct_request["deferred_tool"] == "desktop.click_ui_element"
    assert direct_request["deferred_input"] == {
        "target": "Play",
        "role_filter": "button",
        "limit": 80,
    }
    assert direct_request["deferred_context"] == {"step_id": "operate-foreground-ui"}
    continuation = direct_request["deferred_continuation"][0]
    assert continuation["tool"] == "desktop.ui_elements"
    assert continuation["step_id"] == "verify-desktop-result"
    assert continuation["source"] == "yachiyo_chat_replan_recovery"
    assert continuation["planning_reason"] == "planner_replan_deferred_continuation"
    assert continuation["replan_request_id"] == "replan-1"
    assert continuation["replan_recovery_action_id"] == (
        "replan-1:action:1:desktop.list_apps"
    )
    assert continuation["task_todo"]["todo_id"] == "todo-open-app"
    assert continuation["task_verification_targets"][0]["step_id"] == "open-app"


def test_yachiyo_agent_service_blocks_auto_start_for_deferred_approval_replan() -> None:
    port = _DeferredReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    continuation = service.plan_replan_recovery_action(
        "task-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "conversation_id": "chat-1",
        },
    )

    assert continuation.approval_required is True
    assert continuation.auto_start_eligible is False
    assert continuation.auto_start_blockers == [
        "approval_required",
        "deferred_tool_not_auto_safe",
    ]
    assert continuation.metadata["replan_auto_start_eligible"] is False
    assert continuation.metadata["replan_auto_start_blockers"] == [
        "approval_required",
        "deferred_tool_not_auto_safe",
    ]

    port = _DeferredReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)
    assert service.start_next_replan_continuation(
        "task-1",
        {"conversation_id": "chat-1"},
    ) is None
    assert [name for name, _payload in port.calls] == ["get_task_timeline"]


def test_yachiyo_agent_service_can_plan_manual_next_replan_continuation() -> None:
    port = _DeferredReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    continuation = service.plan_next_replan_continuation(
        "task-1",
        {
            "conversation_id": "chat-1",
            "include_manual": True,
        },
    )

    assert continuation is not None
    assert continuation.auto_start_eligible is False
    assert continuation.auto_start_reason == "manual_replan_continuation_required"
    assert continuation.auto_start_blockers == [
        "approval_required",
        "deferred_tool_not_auto_safe",
    ]
    assert continuation.direct_tool_requests[0]["tool"] == "desktop.list_apps"
    assert continuation.direct_tool_requests[0]["deferred_tool"] == (
        "desktop.click_ui_element"
    )
    assert [name for name, _payload in port.calls] == ["get_task_timeline"]

    port = _DeferredReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)
    assert service.start_next_replan_continuation(
        "task-1",
        {
            "conversation_id": "chat-1",
            "include_manual": True,
        },
    ) is None
    assert [name for name, _payload in port.calls] == ["get_task_timeline"]


def test_yachiyo_agent_service_auto_starts_next_safe_replan_continuation() -> None:
    port = _ReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_next_replan_continuation(
        "task-1",
        {"conversation_id": "chat-1"},
    )

    assert task is not None
    assert task.task_id == "recovery-task-1"
    assert [name for name, _payload in port.calls] == [
        "get_task_timeline",
        "start_chat_task",
    ]
    request = port.calls[1][1]
    assert request["metadata"]["source"] == "yachiyo_chat_replan_auto_continuation"
    assert request["metadata"]["replan_auto_start_eligible"] is True
    assert request["metadata"]["replan_auto_start_reason"] == (
        "safe_low_risk_replan_continuation"
    )
    assert request["direct_tool_requests"][0]["tool"] == "desktop.list_apps"
    assert request["direct_tool_requests"][0]["approval_required"] is False


def test_yachiyo_agent_service_auto_continuation_preserves_desktop_loop_context() -> None:
    planner_service = YachiyoAgentService(_FakeRuntimePort())
    allowed_tools = ["desktop.list_apps", "app.open", "desktop.active_window"]
    decision = planner_service.plan_chat_task("打开 PixelForge", allowed_tools=allowed_tools)
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
    )
    assert envelope is not None
    request = envelope.requests[0].model_dump(mode="json")
    events = planner_service.project_tool_result_events(
        decision,
        tool_request={
            **request,
            "task_id": "task-1",
            "run_id": "run-1",
        },
        tool_event={
            "event": "agent.tool.call",
            "detail": "desktop.list_apps",
            "result": {"ok": False, "error": "desktop_observation_failed"},
        },
        run_id="run-1",
        task_id="task-1",
        after_sequence=20,
    )
    port = _DesktopLoopReplanRecoveryTaskRuntimePort(
        [event.model_dump(mode="json") for event in events]
    )
    service = YachiyoAgentService(port)

    task = service.start_next_replan_continuation(
        "task-1",
        {"conversation_id": "chat-1"},
    )

    assert task is not None
    assert [name for name, _payload in port.calls] == [
        "get_task_timeline",
        "start_chat_task",
    ]
    chat_request = port.calls[1][1]
    assert chat_request["metadata"]["source"] == "yachiyo_chat_replan_auto_continuation"
    assert chat_request["metadata"]["replan_auto_start_eligible"] is True
    assert chat_request["metadata"]["desktop_loop"]["can_auto_retry"] is True
    assert chat_request["metadata"]["runtime_stage"] == "discover"
    direct_request = chat_request["direct_tool_requests"][0]
    assert direct_request["tool"] == "desktop.list_apps"
    assert direct_request["planning_reason"] == "planner_desktop_loop_auto_retry"
    assert direct_request["approval_required"] is False
    assert direct_request["desktop_loop"]["retry_tool"] == "desktop.list_apps"
    assert direct_request["desktop_loop"]["can_auto_retry"] is True
    assert direct_request["runtime_stage"] == "discover"


def test_yachiyo_agent_service_does_not_auto_start_approval_replan_continuation() -> None:
    port = _ApprovalReplanRecoveryTaskRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_next_replan_continuation(
        "task-1",
        {"conversation_id": "chat-1"},
    )

    assert task is None
    assert [name for name, _payload in port.calls] == ["get_task_timeline"]


def test_agent_studio_service_plans_and_starts_replan_continuation() -> None:
    port = _ReplanRecoveryStudioPort()
    service = AgentStudioService(port)

    continuation = service.plan_replan_recovery_action(
        "run-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "agent_id": "agent-1",
            "client_run_id": "client-recovery-1",
        },
    )
    timeline = service.start_replan_recovery_action(
        "run-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "agent_id": "agent-1",
            "client_run_id": "client-recovery-2",
        },
    )

    assert continuation.agent_id == "agent-1"
    assert continuation.client_run_id == "client-recovery-1"
    assert continuation.direct_tool_requests[0]["source"] == "agent_studio_replan_recovery"
    assert continuation.auto_start_eligible is True
    assert timeline.run_id == "studio-recovery-run"
    assert [name for name, _payload in port.calls] == [
        "get_run_timeline",
        "get_run_timeline",
        "start_agent_run",
    ]
    request = port.calls[-1][1]
    assert request["agent_id"] == "agent-1"
    assert request["objective"] == "执行恢复动作：Find Apple Music"
    assert request["client_run_id"] == "client-recovery-2"
    assert request["metadata"]["replan_continuation_id"] == (
        "replan-continuation:replan-1:replan-1:action:1:desktop.list_apps"
    )
    assert request["direct_tool_requests"][0]["approval_required"] is False


def test_agent_studio_service_uses_replan_action_metadata_task_context() -> None:
    port = _MetadataOnlyReplanRecoveryStudioPort()
    service = AgentStudioService(port)

    continuation = service.plan_replan_recovery_action(
        "run-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "agent_id": "agent-1",
        },
    )

    direct_request = continuation.direct_tool_requests[0]
    assert continuation.task_context["workspace_id"] == "task-workspace-1"
    assert continuation.task_context["task_todo"]["todo_id"] == "todo-open-app"
    assert continuation.task_context["task_checkpoints"][0]["checkpoint_id"] == (
        "checkpoint:open-app"
    )
    assert continuation.task_context["task_workspace_items"][0]["item_id"] == (
        "workspace-open-app"
    )
    assert direct_request["workspace_id"] == "task-workspace-1"
    assert direct_request["task_todo"]["todo_id"] == "todo-open-app"
    assert direct_request["task_checkpoints"][0]["checkpoint_id"] == "checkpoint:open-app"
    assert direct_request["task_workspace_items"][0]["item_id"] == "workspace-open-app"
    assert direct_request["task_verification_targets"][0]["step_id"] == "open-app"


def test_agent_studio_service_auto_starts_next_safe_replan_continuation() -> None:
    port = _ReplanRecoveryStudioPort()
    service = AgentStudioService(port)

    timeline = service.start_next_replan_continuation(
        "run-1",
        {"agent_id": "agent-1", "client_run_id": "client-auto-1"},
    )

    assert timeline is not None
    assert timeline.run_id == "studio-recovery-run"
    assert [name for name, _payload in port.calls] == [
        "get_run_timeline",
        "start_agent_run",
    ]
    request = port.calls[-1][1]
    assert request["metadata"]["source"] == "agent_studio_replan_auto_continuation"
    assert request["metadata"]["replan_auto_start_eligible"] is True
    assert request["metadata"]["replan_auto_start_reason"] == (
        "safe_low_risk_replan_continuation"
    )
    assert request["direct_tool_requests"][0]["tool"] == "desktop.list_apps"


def test_yachiyo_agent_service_attaches_runtime_planner_metadata_to_chat_task(
    monkeypatch,
) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
    ):
        monkeypatch.delenv(key, raising=False)
    _install_fake_isolated_provider_session(monkeypatch)
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
    assert "desktop.inspect_app" in port.calls[0][1]["allowed_tools"]
    assert "app.open_and_click_ui_element" in port.calls[0][1]["allowed_tools"]
    assert metadata["yachiyo_entrypoint_allowed_tools"] == port.calls[0][1][
        "allowed_tools"
    ]
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


def test_yachiyo_agent_service_surfaces_desktop_execution_request_previews(
    monkeypatch,
) -> None:
    _clear_test_desktop_provider_env(monkeypatch)
    _install_fake_isolated_provider_session(monkeypatch)
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    service.start_chat_task(
        {
            "prompt": "打开 PixelForge",
            "conversation_id": "chat-1",
            "allowed_tools": ["desktop.list_apps", "app.open", "desktop.active_window"],
        }
    )

    request = port.calls[0][1]
    assert [item["tool"] for item in request["direct_tool_requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert request["direct_tool_requests"][0]["input"] == {
        "query": "PixelForge",
        "limit": 20,
    }
    assert request["direct_tool_requests"][0]["desktop_loop"]["can_auto_retry"] is True
    assert request["direct_tool_requests"][1]["desktop_loop"]["retry_tool"] == (
        "desktop.list_apps"
    )
    assert request["direct_tool_requests"][2]["runtime_stage"] == "verify"
    assert request["direct_tool_requests"][2]["desktop_loop"]["stage"] == "verify"
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
    assert previews[0]["desktop_loop"] == {
        "stage": "discover",
        "role": "find_target_app",
        "action": "discover_apps",
        "target_kind": "desktop_discovery",
        "selection_source": "desktop.list_apps",
        "app_name": "",
        "query": "PixelForge",
        "source_tool": "desktop.list_apps",
        "retry_tool": "desktop.list_apps",
        "retry_reason": "resolve_desktop_app",
        "retry_input": {"query": "PixelForge", "limit": 20},
        "verification_target_step_ids": [],
        "requires_observation": True,
        "requires_post_action_verification": False,
        "can_auto_retry": True,
        "source": "desktop_execution_loop",
    }
    assert previews[1]["runtime_stage"] == "operate"
    assert previews[1]["input"] == {
        "app_name": "PixelForge",
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
    }
    assert previews[1]["requires_post_action_verification"] is True
    assert previews[1]["desktop_loop"]["action"] == "open_app"
    assert previews[1]["desktop_loop"]["retry_tool"] == "desktop.list_apps"
    assert previews[2]["runtime_stage"] == "verify"
    assert previews[2]["depends_on"] == ["open-or-focus-app"]
    assert previews[2]["desktop_loop"]["verification_target_step_ids"] == [
        "open-or-focus-app"
    ]


def test_yachiyo_agent_service_plans_media_query_with_generic_desktop_tools(
    monkeypatch,
) -> None:
    _clear_test_desktop_provider_env(monkeypatch)
    _install_fake_isolated_provider_session(monkeypatch)
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    service.start_chat_task(
        {
            "prompt": "用 Apple Music 播放超时空辉夜姬",
            "conversation_id": "chat-1",
            "allowed_tools": [
                "desktop.list_apps",
                "app.open",
                "desktop.safe_shortcut",
                "desktop.type",
                "desktop.safe_key",
                "desktop.click_ui_element",
                "desktop.ui_elements",
            ],
        }
    )

    request = port.calls[0][1]
    tools = [item["tool"] for item in request["direct_tool_requests"]]
    assert tools == [
        "desktop.list_apps",
        "app.open",
        "desktop.safe_shortcut",
        "desktop.type",
        "desktop.safe_key",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    assert "desktop.type_into_ui_element" not in tools
    direct_requests = request["direct_tool_requests"]
    assert direct_requests[0]["input"] == {"query": "Music", "limit": 20}
    assert direct_requests[1]["input"] == {
        "app_name": "Music",
        "selection_source": "desktop.list_apps",
        "query": "Music",
    }
    assert direct_requests[2]["input"] == {"action": "find"}
    assert direct_requests[3]["input"] == {"text": "超时空辉夜姬"}
    assert direct_requests[4]["input"] == {"key": "return", "modifiers": []}
    assert direct_requests[5]["input"]["target"] == "first result"
    assert direct_requests[-1]["runtime_stage"] == "verify"
    assert request["metadata"]["yachiyo_intent_kind"] == "media_playback"
    assert request["metadata"]["yachiyo_execution_requests"] == tools


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
    assert metadata["yachiyo_plan_tools"] == ["workspace.read", "data.analyze"]
    assert metadata["yachiyo_plan_capabilities"] == ["file.workspace_read", "data.analysis"]
    assert metadata["yachiyo_plan_approvals_required"] == []
    assert metadata["yachiyo_plan_artifacts_expected"] == ["analysis-report.md"]
    assert metadata["yachiyo_plan_open_questions"] == []
    assert metadata["yachiyo_missing_capabilities"] == []
    assert metadata["yachiyo_execution_requests"] == ["workspace.read", "data.analyze"]
    assert metadata["yachiyo_execution_envelope"]["intent_kind"] == "data_analysis"
    assert metadata["yachiyo_execution_envelope"]["requests"][0]["tool_name"] == (
        "workspace.read"
    )
    assert metadata["yachiyo_execution_envelope"]["task_core"]["core_id"] == (
        metadata["yachiyo_task_core"]["core_id"]
    )
    assert metadata["yachiyo_task_core"]["workspace"]["workspace_id"].startswith(
        "task-workspace-"
    )
    assert metadata["yachiyo_task_progress"]["workspace_id"] == (
        metadata["yachiyo_task_core"]["workspace"]["workspace_id"]
    )
    assert metadata["yachiyo_task_progress"]["total_todos"] == 2
    assert metadata["yachiyo_task_progress"]["current_step_id"] == "read-data-source"
    assert [todo["step_id"] for todo in metadata["yachiyo_task_core"]["todos"]] == [
        "read-data-source",
        "analyze-data-file",
    ]
    assert task.task_core is not None
    assert task.task_core.workspace.workspace_id == metadata["yachiyo_task_core"]["workspace"]["workspace_id"]
    assert [todo.step_id for todo in task.task_core.todos] == [
        "read-data-source",
        "analyze-data-file",
    ]
    assert task.task_progress is not None
    assert task.task_progress.workspace_id == metadata["yachiyo_task_progress"]["workspace_id"]


def test_yachiyo_agent_service_starts_chat_with_full_runtime_execution_envelope() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="请分析 data/sales.csv 并输出报告",
            conversation_id="chat-1",
            title="Data analysis",
        )
    )

    request_payload = port.calls[0][1]
    metadata = request_payload["metadata"]
    envelope = request_payload["runtime_execution_envelope"]
    assert [request["tool_name"] for request in envelope["requests"]] == [
        "workspace.read",
        "data.analyze",
    ]
    assert [request["runtime_stage"] for request in envelope["requests"]] == [
        "discover",
        "operate",
    ]
    assert [request["tool_name"] for request in metadata["yachiyo_execution_envelope"]["requests"]] == [
        "workspace.read",
        "data.analyze",
    ]
    assert task.runtime_execution_envelope is not None
    assert [request.tool_name for request in task.runtime_execution_envelope.requests] == [
        "workspace.read",
        "data.analyze",
    ]
    assert task.runtime_execution_envelope.task_progress is not None
    assert task.runtime_execution_envelope.task_progress.total_todos == 2
    assert task.runtime_debug is not None
    assert task.runtime_debug.intent_kind == "data_analysis"
    assert task.runtime_debug.total_todos == 2
    assert task.runtime_debug.runtime_stage_counts == {
        "discover": 1,
        "operate": 1,
    }
    assert task.runtime_debug.runtime_doctrine == "discover_operate_verify"
    assert task.runtime_debug.runtime_stage == "discover"
    assert task.runtime_debug.runtime_role == "inspect_workspace"
    assert task.runtime_debug.current_capability_id == "file.workspace_read"
    assert task.runtime_debug.runtime_request_count == 2
    assert (
        task.runtime_debug.pending_runtime_request_count
        + task.runtime_debug.waiting_runtime_request_count
    ) == 2
    assert task.runtime_debug.current_request_id
    assert task.runtime_debug.current_request_tool_name == "workspace.read"
    assert task.runtime_debug.current_request_status == "waiting_approval"
    assert task.runtime_debug.latest_request_id
    assert task.runtime_debug.latest_request_tool_name == "data.analyze"
    assert task.runtime_debug.latest_request_status == "planned"
    assert task.runtime_debug.latest_tool_name == "workspace.write_patch"
    assert task.runtime_debug.latest_tool_status == "waiting_approval"
    assert task.runtime_debug.latest_approval_tool_name == "workspace.write_patch"
    assert task.runtime_debug.latest_approval_status == "pending"
    assert task.runtime_debug.latest_artifact_id == "artifact-1"
    assert task.runtime_debug.latest_artifact_kind == "markdown"
    assert task.runtime_debug.plan_tools == ["workspace.read", "data.analyze"]
    assert task.runtime_debug.plan_capabilities == ["file.workspace_read", "data.analysis"]
    assert "planner" in task.runtime_debug.debug_surfaces
    assert "task" in task.runtime_debug.debug_surfaces


def test_yachiyo_agent_service_starts_data_analysis_with_observable_read_step() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    service.start_chat_task(
        {
            "prompt": "请分析 data/sales.csv 并输出报告",
            "conversation_id": "chat-1",
            "allowed_tools": [
                "workspace.read",
                "data.analyze",
                "terminal.run",
                "artifact.write",
            ],
        }
    )

    request_payload = port.calls[0][1]
    direct_requests = request_payload["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == [
        "workspace.read",
        "data.analyze",
    ]
    assert direct_requests[0]["step_id"] == "read-data-source"
    assert direct_requests[0]["input"] == {"path": "data/sales.csv", "source_kind": "csv"}
    assert direct_requests[0]["runtime_stage"] == "discover"
    assert direct_requests[0]["runtime_role"] == "inspect_workspace"
    assert direct_requests[1]["step_id"] == "analyze-data-file"
    assert direct_requests[1]["depends_on"] == ["read-data-source"]
    assert direct_requests[1]["runtime_stage"] == "operate"
    assert direct_requests[1]["runtime_role"] == "analyze_data"
    metadata = request_payload["metadata"]
    assert metadata["yachiyo_execution_requests"] == ["workspace.read", "data.analyze"]
    assert [
        todo["step_id"]
        for todo in metadata["yachiyo_execution_envelope"]["task_core"]["todos"]
    ] == ["read-data-source", "analyze-data-file"]


def test_yachiyo_agent_service_plans_csv_summary_artifact() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    service.start_chat_task(
        {
            "prompt": "读取 ~/Downloads/sales.xlsx 做数据分析，输出 markdown 报告和 csv 摘要",
            "conversation_id": "chat-1",
            "allowed_tools": [
                "workspace.read",
                "data.analyze",
                "terminal.run",
                "artifact.write",
            ],
        }
    )

    request_payload = port.calls[0][1]
    direct_requests = request_payload["direct_tool_requests"]
    assert [request["tool"] for request in direct_requests] == [
        "workspace.read",
        "data.analyze",
    ]
    analysis_input = direct_requests[1]["input"]
    assert analysis_input["requested_outputs"] == ["report", "table"]
    assert analysis_input["artifact_paths"] == [
        "analysis-report.md",
        "analysis-summary.csv",
    ]
    assert analysis_input["artifact_manifest"] == [
        {"path": "analysis-report.md", "kind": "markdown"},
        {"path": "analysis-summary.csv", "kind": "csv"},
    ]
    metadata = request_payload["metadata"]
    assert metadata["yachiyo_plan_artifacts_expected"] == [
        "analysis-report.md",
        "analysis-summary.csv",
    ]
    assert [
        item["path"]
        for item in metadata["yachiyo_task_core"]["workspace"]["items"]
        if item["kind"] == "artifact"
    ] == ["analysis-report.md", "analysis-summary.csv"]


def test_yachiyo_agent_service_plans_shared_chat_execution_envelope() -> None:
    service = YachiyoAgentService(_FakeRuntimePort())

    envelope = service.plan_chat_execution(
        "请分析 data/sales.csv 并输出报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )

    assert envelope.intent_kind == "data_analysis"
    assert envelope.task_core is not None
    assert envelope.task_progress is not None
    assert envelope.task_core.workspace.workspace_id.startswith("task-workspace-")
    assert envelope.task_progress.workspace_id == envelope.task_core.workspace.workspace_id
    assert envelope.task_progress.total_todos == len(envelope.task_core.todos)
    assert [request.tool_name for request in envelope.requests] == [
        "workspace.read",
        "data.analyze",
    ]
    read_request = envelope.requests[0]
    analyze_request = envelope.requests[1]
    assert read_request.step_id == "read-data-source"
    assert read_request.capability_id == "file.workspace_read"
    assert read_request.core_id == envelope.task_core.core_id
    assert read_request.workspace_id == envelope.task_core.workspace.workspace_id
    assert read_request.task_todo["step_id"] == "read-data-source"
    assert read_request.task_checkpoints[0]["after_step_id"] == "read-data-source"
    assert analyze_request.step_id == "analyze-data-file"
    assert analyze_request.capability_id == "data.analysis"
    assert analyze_request.depends_on == ["read-data-source"]
    assert analyze_request.replan_signal_ids
    assert analyze_request.core_id == envelope.task_core.core_id
    assert analyze_request.workspace_id == envelope.task_core.workspace.workspace_id
    assert analyze_request.task_todo["step_id"] == "analyze-data-file"
    assert analyze_request.task_checkpoints[0]["after_step_id"] == "analyze-data-file"
    assert analyze_request.checkpoint_policy is not None
    assert analyze_request.checkpoint_policy.checkpoint_ids == [
        checkpoint["checkpoint_id"] for checkpoint in analyze_request.task_checkpoints
    ]
    assert analyze_request.checkpoint_policy.replan_on_failure is True
    assert analyze_request.checkpoint_policy.replan_signal_ids == (
        analyze_request.replan_signal_ids
    )
    assert analyze_request.checkpoint_policy.fallback_tools == ["terminal.run"]
    assert envelope.runtime_stage_counts == {"discover": 1, "operate": 1}
    assert read_request.runtime_stage == "discover"
    assert read_request.runtime_role == "inspect_workspace"
    assert analyze_request.runtime_stage == "operate"
    assert analyze_request.runtime_role == "analyze_data"
    assert envelope.replan_signal_count == len(envelope.task_core.replan_signals)


def test_yachiyo_chat_execution_uses_local_provider_for_app_open(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    service = YachiyoAgentService(_FakeRuntimePort())

    envelope = service.plan_chat_execution(
        "打开 PixelForge",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.active_window"],
    )
    requests = {request.tool_name: request for request in envelope.requests}

    assert requests["app.open"].sandbox_provider is not None
    assert requests["app.open"].sandbox_provider.provider_kind == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert requests["app.open"].sandbox_provider.provider_id == (
        LOCAL_DESKTOP_PROVIDER_ID
    )
    assert requests["app.open"].sandbox_provider.status == "available"
    assert requests["app.open"].sandbox_provider.available is True
    assert requests["app.open"].desktop_execution_route is not None
    assert requests["app.open"].desktop_execution_route.status == "provider_ready"
    assert requests["app.open"].desktop_execution_route.selected_provider_kind == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert requests["app.open"].desktop_execution_route.can_execute is True
    assert requests["app.open"].desktop_execution_route.sandbox_required is False
    assert requests["app.open"].desktop_execution_route.isolated_desktop_preferred is True
    assert requests["app.open"].desktop_execution_route.foreground_takeover_allowed is False
    assert requests["app.open"].desktop_execution_route.blocking_conditions == []
    assert requests["desktop.list_apps"].desktop_execution_route is not None
    assert requests["desktop.list_apps"].desktop_execution_route.status == (
        "provider_ready"
    )
    assert requests["desktop.active_window"].desktop_execution_route is not None
    assert requests["desktop.active_window"].desktop_execution_route.status == (
        "provider_ready"
    )


def test_yachiyo_chat_execution_routes_running_isolated_provider_session() -> None:
    allowed_tools = ["desktop.list_apps", "app.open", "desktop.active_window"]
    service = YachiyoAgentService(_FakeRuntimePort())

    envelope = service.plan_chat_execution(
        "打开 PixelForge",
        allowed_tools=allowed_tools,
        metadata={
            "desktop_provider_session": {
                "needed": True,
                "started": True,
                "running": True,
                "url": "http://127.0.0.1:19093",
                "provider_id": "local-isolated-desktop",
                "provider_kind": "sandbox_desktop",
                "tool_names": allowed_tools,
                "supported_tools": allowed_tools,
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "keyboard_mouse_capture_supported": True,
            },
        },
    )
    requests = {request.tool_name: request for request in envelope.requests}

    assert envelope.desktop_provider_session["provider_id"] == (
        "local-isolated-desktop"
    )
    assert envelope.task_progress is not None
    assert envelope.task_progress.desktop_provider_session_needed is True
    assert envelope.task_progress.desktop_provider_session_running is True
    assert envelope.task_progress.desktop_provider_session_provider_id == (
        "local-isolated-desktop"
    )
    assert envelope.task_progress.desktop_provider_session_tool_names == allowed_tools
    assert envelope.task_progress.desktop_provider_session_needs_user_action is False
    assert "desktop provider ready" in envelope.task_progress.progress_text
    for tool_name in allowed_tools:
        assert requests[tool_name].desktop_provider_session["provider_id"] == (
            "local-isolated-desktop"
        )
        assert requests[tool_name].sandbox_provider is not None
        assert requests[tool_name].sandbox_provider.status == "available"
        assert requests[tool_name].desktop_execution_route is not None
        assert requests[tool_name].desktop_execution_route.status == "sandbox_ready"


def test_yachiyo_chat_execution_blocks_provider_session_without_keyboard_capture() -> None:
    service = YachiyoAgentService(_FakeRuntimePort())

    envelope = service.plan_chat_execution(
        "在当前应用输入 hello",
        allowed_tools=["desktop.safe_type_text"],
        metadata={
            "desktop_provider_session": {
                "needed": True,
                "started": True,
                "running": True,
                "url": "http://127.0.0.1:19093",
                "provider_id": "local-isolated-desktop",
                "provider_kind": "sandbox_desktop",
                "tool_names": ["desktop.safe_type_text"],
                "supported_tools": ["desktop.safe_type_text"],
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "keyboard_mouse_capture_supported": False,
            },
        },
    )
    request = next(
        request
        for request in envelope.requests
        if request.tool_name == "desktop.safe_type_text"
    )

    assert request.sandbox_provider is not None
    assert request.sandbox_provider.keyboard_mouse_capture_supported is False
    assert request.desktop_execution_route is not None
    assert request.desktop_execution_route.status == (
        "sandbox_keyboard_mouse_provider_required"
    )
    assert request.desktop_execution_route.can_execute is False


def test_yachiyo_chat_execution_uses_local_provider_for_music_playback(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    service = YachiyoAgentService(_FakeRuntimePort())

    envelope = service.plan_chat_execution(
        "播放 Apple Music",
        allowed_tools=[
            "media.music_app_open_and_play",
            "media.apple_music_open_and_play",
            "media.apple_music_play",
            "desktop.active_window",
        ],
    )
    requests = {request.tool_name: request for request in envelope.requests}
    playback_request = requests["media.music_app_open_and_play"]

    assert envelope.intent_kind == "media_playback"
    assert playback_request.input == {"app_name": "Music"}
    assert playback_request.sandbox_provider is not None
    assert playback_request.sandbox_provider.provider_kind == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert playback_request.sandbox_provider.provider_id == LOCAL_DESKTOP_PROVIDER_ID
    assert playback_request.sandbox_provider.status == "available"
    assert playback_request.desktop_execution_route is not None
    assert playback_request.desktop_execution_route.status == "provider_ready"
    assert playback_request.desktop_execution_route.selected_provider_kind == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert playback_request.desktop_execution_route.can_execute is True
    assert playback_request.desktop_execution_route.sandbox_required is False
    assert playback_request.desktop_execution_route.isolated_desktop_preferred is True
    assert playback_request.desktop_execution_route.foreground_takeover_allowed is False
    assert playback_request.desktop_execution_route.blocking_conditions == []
    assert requests["desktop.active_window"].desktop_execution_route is not None
    assert requests["desktop.active_window"].desktop_execution_route.status == (
        "provider_ready"
    )


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
    assert envelope.task_progress is not None
    assert [request.tool_name for request in envelope.requests] == [
        "workspace.read",
        "data.analyze",
    ]
    assert envelope.task_progress.core_id == envelope.task_core.core_id
    assert envelope.requests[0].step_id == "read-data-source"
    assert envelope.requests[0].capability_id == "file.workspace_read"
    assert envelope.requests[0].core_id == envelope.task_core.core_id
    assert envelope.requests[0].workspace_id == envelope.task_core.workspace.workspace_id
    assert envelope.requests[0].task_todo["step_id"] == "read-data-source"
    assert envelope.requests[0].task_checkpoints[0]["after_step_id"] == (
        "read-data-source"
    )
    assert envelope.requests[1].step_id == "analyze-data-file"
    assert envelope.requests[1].capability_id == "data.analysis"
    assert envelope.requests[1].depends_on == ["read-data-source"]
    assert envelope.requests[1].replan_signal_ids
    assert envelope.requests[1].task_todo["step_id"] == "analyze-data-file"
    assert envelope.requests[1].task_checkpoints[0]["after_step_id"] == (
        "analyze-data-file"
    )
    assert envelope.requests[1].checkpoint_policy is not None
    assert envelope.requests[1].checkpoint_policy.replan_signal_ids == (
        envelope.requests[1].replan_signal_ids
    )
    assert envelope.requests[1].checkpoint_policy.fallback_tools == ["terminal.run"]
    assert envelope.runtime_stage_counts == {"discover": 1, "operate": 1}
    assert envelope.requests[0].runtime_stage == "discover"
    assert envelope.requests[0].runtime_role == "inspect_workspace"
    assert envelope.requests[1].runtime_stage == "operate"
    assert envelope.requests[1].runtime_role == "analyze_data"


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
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert envelope.requests[0].runtime_stage == "discover"
    assert envelope.requests[0].input == {"query": "PixelForge", "limit": 20}
    assert envelope.requests[1].input == {
        "app_name": "PixelForge",
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
    }
    assert envelope.requests[2].step_id == "read-foreground-ui"
    assert envelope.requests[2].runtime_stage == "discover"
    assert envelope.requests[2].depends_on == ["open-or-focus-app"]
    assert envelope.requests[2].input == {
        "target": "Export",
        "limit": 80,
        "app_name": "PixelForge",
    }
    assert envelope.requests[3].input == {
        "app_name": "PixelForge",
        "target": "Export",
        "role_filter": "",
        "click_count": 1,
        "limit": 80,
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
    }
    assert envelope.requests[3].requires_post_action_verification is True
    assert envelope.requests[4].input == {
        "app_name": "PixelForge",
        "selection_source": "desktop.list_apps",
        "query": "PixelForge",
        "limit": 80,
    }
    assert envelope.requests[4].runtime_stage == "verify"
    assert envelope.requests[4].requires_observation is True
    assert envelope.requests[4].requires_post_action_verification is False


def test_agent_studio_service_projects_provider_session_recovery_without_autostart(
    monkeypatch,
) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK",
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE",
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
    ):
        monkeypatch.delenv(key, raising=False)
    start_calls = _install_fake_isolated_provider_session(monkeypatch)
    service = AgentStudioService(_FakeStudioExecutionPort())

    envelope = service.plan_execution(
        "在一个我没提过的新应用 PixelForge 点击 Export",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        metadata={"surface": "studio"},
    )

    operation_request = next(
        request
        for request in envelope.requests
        if request.tool_name == "app.focus_and_click_ui_element"
    )
    recoveries = replan_recovery_snapshots_from_runtime_execution_envelope(
        envelope,
        run_id="run-1",
        task_id="task-1",
    )
    provider_recovery = next(
        snapshot
        for snapshot in recoveries
        if snapshot.selected_tool_name == "desktop.provider_session.start"
    )
    action = provider_recovery.recovery_actions[0]

    assert start_calls == []
    assert envelope.desktop_provider_session["needed"] is True
    assert envelope.desktop_provider_session["auto_start"] is False
    assert envelope.desktop_provider_session["running"] is False
    assert envelope.task_progress is not None
    assert envelope.task_progress.status == "provider_required"
    assert envelope.task_progress.needs_user_action is True
    assert envelope.task_progress.needs_replan is True
    assert envelope.task_progress.desktop_provider_session_needed is True
    assert envelope.task_progress.desktop_provider_session_running is False
    assert envelope.task_progress.desktop_provider_session_needs_user_action is True
    assert envelope.task_progress.desktop_provider_session_needs_replan is True
    assert "desktop provider required" in envelope.task_progress.progress_text
    assert operation_request.desktop_provider_session["needed"] is True
    assert operation_request.desktop_execution_route is not None
    assert operation_request.desktop_execution_route.can_execute is False
    assert provider_recovery.status == "requested"
    assert provider_recovery.approval_status == "pending"
    assert provider_recovery.permission_target == "isolated_desktop_provider"
    assert action.approval_required is True
    assert action.tool == "desktop.provider_session.start"
    assert action.input["api_route"] == (
        "/yachiyo/studio/tools/desktop-provider/session/start"
    )
    assert set(action.input["tool_names"]) == {
        "app.focus_and_click_ui_element",
        "desktop.list_apps",
        "desktop.ui_elements",
    }
    assert [request["tool"] for request in action.deferred_continuation] == [
        "desktop.list_apps",
        "desktop.ui_elements",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]


def test_agent_studio_service_probes_desktop_provider_health_for_execution(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": True,
                    "status": "ready",
                        "version": "0.1.0",
                        "supported_tools": ["app.focus_and_click_ui_element"],
                        "capabilities": ["desktop_discovery", "sandbox_foreground"],
                        "keyboard_mouse_capture_supported": True,
                        "desktop_session_kind": "isolated_desktop",
                        "desktop_session_isolated": True,
                        "foreground_takeover_required": False,
                        "desktop_backend_kind": "virtual_desktop",
                        "desktop_backend_is_loopback": False,
                        "desktop_backend_ready_for_public_release": True,
                        "requires_real_virtual_desktop_backend": False,
                    }
                ).encode("utf-8")

        def getcode(self) -> int:
            return self.status

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        calls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(
        "apps.shell.agent.runtime.desktop_execution_providers.urlopen_with_bundled_ca",
        fake_urlopen,
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19091")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "local-headless-desktop")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "app.focus_and_click_ui_element",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND", "isolated_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED", "true")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "false",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND", "virtual_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK", "false")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE",
        "true",
    )
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
        "false",
    )
    service = AgentStudioService(_FakeStudioExecutionPort())

    envelope = service.plan_execution(
        "在 PixelForge 点击 Export",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        metadata={"surface": "studio"},
    )

    operation_request = next(
        request
        for request in envelope.requests
        if request.tool_name == "app.focus_and_click_ui_element"
    )
    assert calls
    assert operation_request.sandbox_provider is not None
    assert operation_request.sandbox_provider.status == "available"
    assert operation_request.sandbox_provider.health is not None
    assert operation_request.sandbox_provider.health.checked is True
    assert operation_request.sandbox_provider.health.status == "ready"
    assert operation_request.sandbox_provider.health.provider_version == "0.1.0"
    assert operation_request.desktop_execution_route is not None
    assert operation_request.desktop_execution_route.status == "sandbox_ready"
    assert operation_request.desktop_execution_route.selected_provider_id == (
        "local-headless-desktop"
    )
    assert envelope.sandbox_provider is not None
    assert envelope.sandbox_provider.health is not None
    assert envelope.sandbox_provider.health.checked is True


def test_agent_studio_service_routes_readonly_desktop_discovery_through_provider(
    monkeypatch,
) -> None:
    calls: list[str] = []

    class FakeResponse:
        status = 200

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "ok": True,
                    "status": "ready",
                    "version": "0.1.0",
                    "supported_tools": ["desktop.list_apps"],
                    "capabilities": [
                        "desktop_discovery",
                        "read_only_observation",
                        "no_foreground_mutation",
                    ],
                    "desktop_session_kind": "isolated_desktop",
                    "desktop_session_isolated": True,
                    "foreground_takeover_required": False,
                    "desktop_backend_kind": "virtual_desktop",
                    "desktop_backend_is_loopback": False,
                    "desktop_backend_ready_for_public_release": True,
                    "requires_real_virtual_desktop_backend": False,
                }
            ).encode("utf-8")

        def getcode(self) -> int:
            return self.status

    def fake_urlopen(request: Any, *, timeout: float) -> FakeResponse:
        calls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr(
        "apps.shell.agent.runtime.desktop_execution_providers.urlopen_with_bundled_ca",
        fake_urlopen,
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19091")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "local-headless-desktop")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "desktop.list_apps",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND", "isolated_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED", "true")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "false",
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND", "virtual_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK", "false")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_READY_FOR_PUBLIC_RELEASE",
        "true",
    )
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
        "false",
    )
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

    discovery_request = next(
        request for request in envelope.requests if request.tool_name == "desktop.list_apps"
    )
    operation_request = next(
        request
        for request in envelope.requests
        if request.tool_name == "app.focus_and_click_ui_element"
    )
    assert calls
    assert discovery_request.sandbox_provider is not None
    assert discovery_request.sandbox_provider.provider_id == "local-headless-desktop"
    assert discovery_request.sandbox_provider.health is not None
    assert discovery_request.sandbox_provider.health.checked is True
    assert discovery_request.desktop_execution_route is not None
    assert discovery_request.desktop_execution_route.status == "sandbox_ready"
    assert discovery_request.desktop_execution_route.selected_provider_kind == (
        "sandbox_desktop"
    )
    assert operation_request.desktop_execution_route is not None
    assert operation_request.desktop_execution_route.status == "supervised_live"
    assert envelope.sandbox_provider is not None
    assert envelope.sandbox_provider.provider_id == "local-headless-desktop"
    projected = runtime_execution_requests_from_envelope_payload(
        envelope.model_dump(mode="json"),
        allowed_tools=["desktop.list_apps"],
    )
    assert projected[0]["tool"] == "desktop.list_apps"
    assert projected[0]["desktop_execution_route"]["status"] == "sandbox_ready"
    assert projected[0]["sandbox_provider"]["provider_id"] == "local-headless-desktop"


def test_yachiyo_chat_entrypoint_routes_provider_supported_desktop_actions(
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19091")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "local-headless-desktop")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "desktop.list_apps,app.focus_and_click_ui_element",
    )
    start_calls = _install_fake_isolated_provider_session(monkeypatch, calls)
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="在 PixelForge 点击 Export",
            conversation_id="chat-1",
            metadata={"launcher_mode": "bubble"},
            allowed_tools=[
                "desktop.list_apps",
                "app.focus_and_click_ui_element",
                "desktop.ui_elements",
            ],
        )
    )

    request_payload = port.calls[0][1]
    operation_request = next(
        request
        for request in request_payload["direct_tool_requests"]
        if request["tool"] == "app.focus_and_click_ui_element"
    )
    envelope_request = next(
        request
        for request in request_payload["metadata"]["yachiyo_execution_envelope"][
            "requests"
        ]
        if request["tool_name"] == "app.focus_and_click_ui_element"
    )

    assert calls
    assert request_payload["metadata"]["desktop_provider_health_probe"] is True
    assert request_payload["metadata"]["desktop_provider_route_readonly"] is True
    assert request_payload["metadata"]["desktop_provider_route_foreground"] is True
    assert request_payload["metadata"]["desktop_execution_policy"]["mode"] == (
        "preview_input"
    )
    assert start_calls == []
    assert operation_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert operation_request["sandbox_provider"]["provider_id"] == (
        "local-headless-desktop"
    )
    assert envelope_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert task.runtime_execution_envelope is not None
    routed_request = next(
        request
        for request in task.runtime_execution_envelope.requests
        if request.tool_name == "app.focus_and_click_ui_element"
    )
    assert routed_request.desktop_execution_route is not None
    assert routed_request.desktop_execution_route.status == "sandbox_ready"


def test_yachiyo_chat_entrypoint_auto_starts_isolated_provider_for_input(
    monkeypatch,
) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
    ):
        monkeypatch.delenv(key, raising=False)
    start_calls = _install_fake_isolated_provider_session(monkeypatch)
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="在 PixelForge 点击 Export",
            conversation_id="chat-1",
            metadata={"launcher_mode": "bubble"},
            allowed_tools=[
                "desktop.list_apps",
                "app.focus_and_click_ui_element",
                "desktop.ui_elements",
            ],
        )
    )

    request_payload = port.calls[0][1]
    envelope = request_payload["runtime_execution_envelope"]
    session = envelope["desktop_provider_session"]
    operation_request = next(
        request
        for request in request_payload["direct_tool_requests"]
        if request["tool"] == "app.focus_and_click_ui_element"
    )
    discovery_request = next(
        request
        for request in request_payload["direct_tool_requests"]
        if request["tool"] == "desktop.list_apps"
    )
    read_request = next(
        request
        for request in request_payload["direct_tool_requests"]
        if request["tool"] == "desktop.ui_elements"
    )

    assert start_calls == [
        {
            "tools": [
                "app.focus_and_click_ui_element",
                "desktop.list_apps",
                "desktop.ui_elements",
            ]
        }
    ]
    assert session["needed"] is True
    assert session["started"] is True
    assert session["running"] is True
    assert session["provider_id"] == "local-isolated-desktop"
    assert session["tool_names"] == [
        "app.focus_and_click_ui_element",
        "desktop.list_apps",
        "desktop.ui_elements",
    ]
    assert session["desktop_session_kind"] == "isolated_desktop"
    assert session["desktop_session_isolated"] is True
    assert session["foreground_takeover_required"] is False
    assert discovery_request["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert discovery_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert operation_request["sandbox_provider"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert operation_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert operation_request["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert read_request["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert read_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert request_payload["metadata"]["yachiyo_execution_envelope"][
        "desktop_provider_session"
    ]["started"] is True
    assert task.runtime_execution_envelope is not None
    assert task.runtime_execution_envelope.desktop_provider_session["started"] is True
    assert task.runtime_execution_envelope.task_progress is not None
    assert (
        task.runtime_execution_envelope.task_progress.desktop_provider_session_needed
        is True
    )
    assert (
        task.runtime_execution_envelope.task_progress.desktop_provider_session_running
        is True
    )
    assert (
        task.runtime_execution_envelope.task_progress.desktop_provider_session_started
        is True
    )
    assert (
        task.runtime_execution_envelope.task_progress.desktop_provider_session_provider_id
        == "local-isolated-desktop"
    )
    assert task.runtime_debug is not None
    assert task.runtime_debug.desktop_provider_session_needed is True
    assert task.runtime_debug.desktop_provider_session_running is True
    assert task.runtime_debug.desktop_provider_session_started is True
    assert task.runtime_debug.desktop_provider_session_provider_id == (
        "local-isolated-desktop"
    )
    assert task.runtime_debug.desktop_provider_session_tool_names == [
        "app.focus_and_click_ui_element",
        "desktop.list_apps",
        "desktop.ui_elements",
    ]
    assert task.runtime_debug.desktop_provider_session_kind == "isolated_desktop"
    assert task.runtime_debug.desktop_provider_session_isolated is True
    assert (
        task.runtime_debug.desktop_provider_session_foreground_takeover_required
        is False
    )
    assert (
        task.runtime_debug.desktop_provider_session_keyboard_mouse_capture_supported
        is True
    )
    assert task.runtime_debug.desktop_execution_session_mode == "isolated_desktop"
    assert task.runtime_debug.desktop_execution_session_label == (
        "isolated desktop provider"
    )
    assert "desktop_provider" in task.runtime_debug.debug_surfaces


def test_yachiyo_chat_entrypoint_uses_local_provider_for_app_open(
    monkeypatch,
) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
    ):
        monkeypatch.delenv(key, raising=False)
    start_calls = _install_fake_isolated_provider_session(monkeypatch)
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="打开 PixelForge",
            conversation_id="chat-1",
            metadata={"launcher_mode": "bubble"},
            allowed_tools=[
                "desktop.list_apps",
                "app.open",
                "desktop.active_window",
            ],
        )
    )

    request_payload = port.calls[0][1]
    envelope = request_payload["runtime_execution_envelope"]
    session = envelope["desktop_provider_session"]
    open_request = next(
        request
        for request in request_payload["direct_tool_requests"]
        if request["tool"] == "app.open"
    )

    assert start_calls == []
    assert session["needed"] is False
    assert session["status"] == "not_needed"
    assert session["started"] is False
    assert session["running"] is False
    assert open_request["input"] == {
        "app_name": "PixelForge",
        "query": "PixelForge",
        "selection_source": "desktop.list_apps",
    }
    assert open_request["sandbox_provider"]["provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert open_request["sandbox_provider"]["provider_id"] == (
        LOCAL_DESKTOP_PROVIDER_ID
    )
    assert open_request["desktop_execution_route"]["status"] == "provider_ready"
    assert open_request["desktop_execution_route"]["selected_provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert open_request["desktop_execution_route"]["sandbox_required"] is False
    assert "desktop_provider_session" not in open_request
    assert task.runtime_debug is not None
    assert task.runtime_debug.desktop_provider_session_needed is False
    assert task.runtime_debug.desktop_provider_session_tool_names == []
    assert task.runtime_debug.desktop_provider_requires_real_virtual_backend is False
    assert task.runtime_debug.desktop_execution_session_mode == "user_foreground"
    assert task.runtime_debug.desktop_execution_session_label == (
        "real desktop foreground"
    )


def test_yachiyo_chat_entrypoint_allows_explicit_user_foreground_app_open(
    monkeypatch,
) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
    ):
        monkeypatch.delenv(key, raising=False)
    start_calls = _install_fake_isolated_provider_session(monkeypatch)
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="打开 PixelForge",
            conversation_id="chat-1",
            metadata={
                "launcher_mode": "bubble",
                "allow_user_foreground_takeover": True,
            },
            allowed_tools=[
                "desktop.list_apps",
                "app.open",
                "desktop.active_window",
            ],
        )
    )

    request_payload = port.calls[0][1]
    envelope = request_payload["runtime_execution_envelope"]
    session = envelope["desktop_provider_session"]
    open_request = next(
        request
        for request in request_payload["direct_tool_requests"]
        if request["tool"] == "app.open"
    )

    assert start_calls == []
    assert session["needed"] is False
    assert session["started"] is False
    assert session["running"] is False
    assert open_request["desktop_execution_route"]["status"] == "provider_ready"
    assert open_request["desktop_execution_route"]["selected_provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert "desktop_provider_session" not in open_request
    assert task.runtime_debug is not None
    assert task.runtime_debug.desktop_provider_session_needed is False
    assert task.runtime_debug.desktop_execution_session_mode == "user_foreground"


def test_yachiyo_chat_entrypoint_uses_local_provider_for_music_playback(
    monkeypatch,
) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
    ):
        monkeypatch.delenv(key, raising=False)
    start_calls = _install_fake_isolated_provider_session(monkeypatch)
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="播放 Apple Music",
            conversation_id="chat-1",
            metadata={"launcher_mode": "bubble"},
            allowed_tools=[
                "media.music_app_open_and_play",
                "desktop.ui_elements",
            ],
        )
    )

    request_payload = port.calls[0][1]
    envelope = request_payload["runtime_execution_envelope"]
    session = envelope["desktop_provider_session"]
    playback_request = next(
        request
        for request in request_payload["direct_tool_requests"]
        if request["tool"] == "media.music_app_open_and_play"
    )

    assert start_calls == []
    assert session["needed"] is False
    assert session["status"] == "not_needed"
    assert session["started"] is False
    assert session["running"] is False
    assert playback_request["input"] == {"app_name": "Music"}
    assert playback_request["sandbox_provider"]["provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert playback_request["sandbox_provider"]["provider_id"] == (
        LOCAL_DESKTOP_PROVIDER_ID
    )
    assert playback_request["desktop_execution_route"]["status"] == "provider_ready"
    assert playback_request["desktop_execution_route"]["selected_provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert playback_request["desktop_execution_route"]["sandbox_required"] is False
    assert "desktop_provider_session" not in playback_request
    assert task.runtime_debug is not None
    assert task.runtime_debug.desktop_provider_session_needed is False
    assert task.runtime_debug.desktop_provider_session_tool_names == []
    assert task.runtime_debug.desktop_provider_requires_real_virtual_backend is False
    assert task.runtime_debug.desktop_execution_session_mode == "user_foreground"
    assert task.runtime_debug.desktop_execution_session_label == (
        "real desktop foreground"
    )


def test_yachiyo_chat_entrypoint_surfaces_partial_blocked_desktop_plan(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", "http://127.0.0.1:19093")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_ID", "local-isolated-desktop")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        (
            "desktop.list_apps,app.open_and_safe_shortcut,desktop.safe_type_text,"
            "desktop.search_submit,media.music_app_open_and_play,desktop.ui_elements"
        ),
    )
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_KIND", "sandbox_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND", "isolated_desktop")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED", "true")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED", "false")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_KIND", "loopback_session_harness")
    monkeypatch.setenv("OHA_YACHIYO_DESKTOP_PROVIDER_BACKEND_IS_LOOPBACK", "true")
    monkeypatch.setenv(
        "OHA_YACHIYO_DESKTOP_PROVIDER_REQUIRES_REAL_VIRTUAL_DESKTOP_BACKEND",
        "true",
    )
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="帮我打开 Apple Music 播放超时空辉夜姬",
            conversation_id="chat-1",
            metadata={"launcher_mode": "bubble"},
        )
    )

    request_payload = port.calls[0][1]
    direct_tools = [request["tool"] for request in request_payload["direct_tool_requests"]]
    blocked_tools = [
        request["tool"] for request in request_payload["blocked_direct_tool_requests"]
    ]

    assert "media.music_app_open_and_play" in direct_tools
    assert "desktop.safe_type_text" in blocked_tools
    assert request_payload["metadata"]["yachiyo_runtime_blocked"] is True
    assert request_payload["metadata"]["yachiyo_blocked_execution_requests"] == (
        blocked_tools
    )
    assert task.runtime_debug is not None
    assert task.runtime_debug.blocked_runtime_request_count >= 1
    assert task.runtime_debug.blocked_direct_request_count == len(blocked_tools)
    assert "desktop.safe_type_text" in task.runtime_debug.blocked_runtime_request_tools
    assert task.runtime_debug.latest_blocked_request_tool_name in blocked_tools
    assert task.runtime_debug.latest_blocked_request_status in {
        "provider_required",
        "real_virtual_desktop_provider_required",
    }
    assert task.runtime_debug.needs_user_action is True
    assert task.runtime_debug.needs_replan is True
    assert "runtime_blockers" in task.runtime_debug.debug_surfaces
    assert task.task_core is not None
    blocked_todos = [
        todo
        for todo in task.task_core.todos
        if todo.tool_name in set(blocked_tools)
    ]
    assert blocked_todos
    assert all(todo.status == "blocked" for todo in blocked_todos)
    blocked_step_ids = {todo.step_id for todo in blocked_todos}
    assert any(
        signal.trigger == "runtime_blocked"
        and signal.source_step_id in blocked_step_ids
        for signal in task.task_core.replan_signals
    )
    assert task.task_progress is not None
    assert task.task_progress.needs_replan is True
    assert set(task.task_progress.blocked_step_ids).issuperset(blocked_step_ids)


def test_yachiyo_chat_entrypoint_does_not_direct_execute_blocked_provider_route(
    monkeypatch,
) -> None:
    for key in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KEYBOARD_MOUSE_CAPTURE_SUPPORTED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_KIND",
        "OHA_YACHIYO_DESKTOP_PROVIDER_SESSION_ISOLATED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_FOREGROUND_TAKEOVER_REQUIRED",
        "OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_STATUS_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_KIND",
    ):
        monkeypatch.delenv(key, raising=False)
    start_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.isolated_provider_session."
        "isolated_desktop_provider_session_status",
        lambda: {
            "ok": True,
            "status": "stopped",
            "running": False,
            "provider_id": "",
            "url": "",
            "source": "test",
        },
    )

    def fake_start(request: dict[str, Any] | None = None) -> dict[str, Any]:
        start_calls.append(dict(request or {}))
        return {
            "ok": False,
            "status": "real_virtual_desktop_provider_required",
            "running": False,
            "started": False,
            "provider_id": "real-virtual-desktop",
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "requires_real_virtual_desktop_backend": True,
            "blocking_conditions": [
                "configured_virtual_desktop_provider_required",
                "real_virtual_desktop_backend_required",
            ],
        }

    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.isolated_provider_session."
        "start_isolated_desktop_provider_session",
        fake_start,
    )
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="在 PixelForge 点击 Export",
            conversation_id="chat-1",
            metadata={"launcher_mode": "bubble"},
            allowed_tools=[
                "app.focus_and_click_ui_element",
                "desktop.ui_elements",
            ],
        )
    )

    request_payload = port.calls[0][1]
    envelope = request_payload["runtime_execution_envelope"]
    direct_tools = [
        request["tool"] for request in request_payload.get("direct_tool_requests", [])
    ]

    assert start_calls == [
        {"tools": ["app.focus_and_click_ui_element", "desktop.ui_elements"]}
    ]
    assert "app.focus_and_click_ui_element" not in direct_tools
    session = envelope["desktop_provider_session"]
    assert session["status"] == "real_virtual_desktop_provider_required"
    assert session["running"] is False
    assert session["requires_real_virtual_desktop_backend"] is True
    assert task.runtime_debug is not None
    assert task.runtime_debug.desktop_provider_session_status == (
        "real_virtual_desktop_provider_required"
    )


def test_agent_studio_service_normalizes_known_app_submit_execution() -> None:
    service = AgentStudioService(_FakeStudioExecutionPort())

    envelope = service.plan_execution(
        "在 Slack 给 Alice 发 hello",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ],
    )

    assert envelope.intent_kind == "communication"
    assert [request.tool_name for request in envelope.requests] == [
        "desktop.list_apps",
        "app.focus",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert envelope.runtime_stage_counts == {
        "discover": 1,
        "operate": 6,
        "verify": 1,
    }
    assert envelope.requests[0].runtime_stage == "discover"
    assert envelope.requests[0].runtime_role == "find_target_app"
    assert envelope.requests[0].input == {"query": "Slack", "limit": 20}
    assert envelope.requests[1].input == {
        "app_name": "Slack",
        "selection_source": "desktop.list_apps",
        "query": "Slack",
    }
    assert envelope.requests[6].approval_required is True
    assert envelope.requests[6].runtime_stage == "operate"
    assert envelope.requests[6].runtime_role == "send_message"
    assert envelope.requests[7].source == "runtime_verification"
    assert envelope.requests[7].runtime_stage == "verify"
    assert envelope.requests[7].runtime_role == "verify_result"
    assert envelope.requests[7].continue_to_model is True
    assert envelope.requests[7].requires_observation is True
    assert envelope.requests[7].input == {
        "app_name": "Slack",
        "selection_source": "desktop.list_apps",
        "query": "Slack",
        "role_filter": "text",
        "limit": 80,
    }


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
    assert "recovery_actions" not in events[-1].payload["metadata"]


def test_yachiyo_agent_service_projects_replan_recovery_actions_from_fallback_tools() -> None:
    service = YachiyoAgentService(_FakeRuntimePort())
    decision = service.plan_chat_task(
        "打开一个能看 PDF 的应用",
        allowed_tools=["desktop.list_apps", "app.open", "desktop.active_window"],
    )
    task_core = decision.plan.task_core
    assert task_core is not None

    step_id = "open-selected-discovered-app"
    todo = next(todo for todo in task_core.todos if todo.step_id == step_id)
    checkpoint = next(
        checkpoint for checkpoint in task_core.checkpoints if checkpoint.after_step_id == step_id
    )
    events = service.project_tool_result_events(
        decision,
        tool_request={
            "tool": "app.open",
            "input": {
                "app_name": "<selected app from desktop.list_apps>",
                "selection_source": "desktop.list_apps",
                "query": "pdf",
            },
            "source": "runtime_planner",
            "step_id": step_id,
            "core_id": task_core.core_id,
            "workspace_id": task_core.workspace.workspace_id,
            "decision_id": decision.decision_id,
            "plan_id": decision.plan.plan_id,
            "task_id": "task-1",
            "run_id": "run-1",
            "task_todo": todo.model_dump(mode="python"),
            "task_checkpoints": [checkpoint.model_dump(mode="python")],
        },
        tool_event={
            "event": "agent.tool.call",
            "detail": "app.open",
            "result": {"ok": False, "error": "app_resolution_failed"},
        },
        run_id="run-1",
        task_id="task-1",
        after_sequence=20,
    )

    replan_event = events[-1]
    assert replan_event.event_type == "agent.replan.requested"
    assert replan_event.payload["source_step_id"] == step_id
    assert replan_event.payload["fallback_tools"] == ["desktop.list_apps"]
    recovery_actions = replan_event.payload["metadata"]["recovery_actions"]
    assert replan_event.payload["recovery_actions"] == recovery_actions
    assert recovery_actions == [
        {
            "label": "重新发现应用",
            "tool": "desktop.list_apps",
            "input": {"query": "pdf", "limit": 20},
            "planning_reason": "planner_replan_runtime_recovery_action",
            "permission_target": "app_discovery",
            "risk_level": "low",
            "approval_required": False,
            "source_step_id": step_id,
            "target_capability_id": "desktop.app_control",
            "verification_targets": [
                {
                    "step_id": step_id,
                    "todo_id": todo.todo_id,
                    "todo_title": todo.title,
                    "checkpoint_ids": [checkpoint.checkpoint_id],
                }
            ],
            "task_verification_targets": [
                {
                    "step_id": step_id,
                    "todo_id": todo.todo_id,
                    "todo_title": todo.title,
                    "checkpoint_ids": [checkpoint.checkpoint_id],
                }
            ],
        }
    ]

    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-1",
            "run_id": "run-1",
            "status": "running",
            "events": [event.model_dump(mode="json") for event in events],
        }
    )
    assert task.replan_recoveries
    recovery = task.replan_recoveries[0]
    assert recovery.request_id == replan_event.payload["request_id"]
    assert recovery.recovery_actions[0].tool == "desktop.list_apps"
    assert recovery.recovery_actions[0].input == {"query": "pdf", "limit": 20}
    assert recovery.recovery_actions[0].approval_required is False


def test_yachiyo_agent_service_projects_desktop_loop_auto_retry_recovery_action() -> None:
    service = YachiyoAgentService(_FakeRuntimePort())
    allowed_tools = ["desktop.list_apps", "app.open", "desktop.active_window"]
    decision = service.plan_chat_task("打开 PixelForge", allowed_tools=allowed_tools)
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
    )
    assert envelope is not None
    request = envelope.requests[0].model_dump(mode="json")

    events = service.project_tool_result_events(
        decision,
        tool_request={
            **request,
            "task_id": "task-1",
            "run_id": "run-1",
        },
        tool_event={
            "event": "agent.tool.call",
            "detail": "desktop.list_apps",
            "result": {"ok": False, "error": "desktop_observation_failed"},
        },
        run_id="run-1",
        task_id="task-1",
        after_sequence=20,
    )

    replan_event = events[-1]
    assert replan_event.event_type == "agent.replan.requested"
    assert replan_event.payload["source_step_id"] == "discover-desktop-state"
    assert replan_event.payload["fallback_tools"] == ["desktop.list_apps"]
    assert replan_event.payload["metadata"]["desktop_loop"]["can_auto_retry"] is True
    recovery_actions = replan_event.payload["metadata"]["recovery_actions"]
    assert replan_event.payload["recovery_actions"] == recovery_actions
    assert len(recovery_actions) == 1
    action = recovery_actions[0]
    assert action["tool"] == "desktop.list_apps"
    assert action["input"] == {"limit": 20, "query": "PixelForge"}
    assert action["planning_reason"] == "planner_desktop_loop_auto_retry"
    assert action["approval_required"] is False
    assert action["observation_retry"] == {
        "from_tool": "desktop.list_apps",
        "tool": "desktop.list_apps",
        "input": {"limit": 20, "query": "PixelForge"},
        "reason": "resolve_desktop_app",
    }
    assert action["metadata"]["desktop_loop_retry_reason"] == "resolve_desktop_app"
    assert action["metadata"]["runtime_stage"] == "discover"
    assert action["metadata"]["replan_signal_ids"] == request["replan_signal_ids"]

    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-1",
            "run_id": "run-1",
            "status": "running",
            "events": [event.model_dump(mode="json") for event in events],
        }
    )
    recovery = task.replan_recoveries[0]
    assert recovery.recovery_actions[0].tool == "desktop.list_apps"
    assert recovery.recovery_actions[0].planning_reason == (
        "planner_desktop_loop_auto_retry"
    )
    assert recovery.recovery_actions[0].metadata["desktop_loop"]["can_auto_retry"] is True


def test_agent_task_snapshot_links_deferred_approval_to_replan_recovery() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-1",
            "run_id": "run-1",
            "status": "approval_required",
            "events": [
                {
                    "event_type": "agent.replan.requested",
                    "sequence": 1,
                    "run_id": "run-1",
                    "payload": {
                        "request_id": "replan-1",
                        "trigger": "verification_failed",
                        "source_step_id": "operate-foreground-ui",
                        "source_tool_name": "desktop.ui_elements",
                        "target_capability_id": "desktop.ui_operation",
                        "fallback_tools": ["desktop.click_ui_element"],
                        "decision_id": "decision-1",
                        "plan_id": "runtime-plan-1",
                        "core_id": "task-core-1",
                    },
                },
                {
                    "event_type": "agent.desktop.intent_planned",
                    "sequence": 2,
                    "run_id": "run-1",
                    "payload": {
                        "tool": "desktop.ui_elements",
                        "step_id": "operate-foreground-ui",
                        "planner_step_id": "operate-foreground-ui",
                        "capability_id": "desktop.ui_operation",
                        "replan_request_id": "replan-1",
                        "replan_trigger": "verification_failed",
                        "deferred_tool": "desktop.click_ui_element",
                        "deferred_input": {
                            "target": "Export",
                            "role_filter": "",
                            "click_count": 1,
                            "limit": 80,
                        },
                        "deferred_context": {"step_id": "operate-foreground-ui"},
                        "deferred_continuation": [
                            {"tool": "desktop.ui_elements", "step_id": "verify-desktop-result"}
                        ],
                        "recovery_actions": [
                            {
                                "label": "Click observed Export control",
                                "tool": "desktop.click_ui_element",
                                "input": {"target": "Export", "limit": 80},
                                "approval_required": True,
                                "selected": True,
                            }
                        ],
                    },
                },
                {
                    "event_type": "agent.desktop.intent_approval_required",
                    "sequence": 3,
                    "run_id": "run-1",
                    "payload": {
                        "tool": "desktop.click_ui_element",
                        "step_id": "operate-foreground-ui",
                        "replan_request_id": "replan-1",
                        "approval_id": "approval-1",
                        "status": "approval_required",
                    },
                },
                {
                    "event_type": "agent.tool.approval_approved",
                    "sequence": 4,
                    "run_id": "run-1",
                    "payload": {
                        "tool": "desktop.click_ui_element",
                        "step_id": "operate-foreground-ui",
                        "replan_request_id": "replan-1",
                        "approval_id": "approval-1",
                    },
                },
                {
                    "event_type": "agent.tool.call",
                    "sequence": 5,
                    "run_id": "run-1",
                    "payload": {
                        "tool": "desktop.click_ui_element",
                        "step_id": "operate-foreground-ui",
                        "replan_request_id": "replan-1",
                        "approval_id": "approval-1",
                        "runtime_doctrine": "discover_operate_verify",
                        "runtime_stage": "operate",
                        "runtime_role": "desktop_ui_action",
                        "requires_observation": True,
                        "requires_post_action_verification": True,
                        "replan_triggers": ["verification_failed"],
                        "replan_signal_ids": ["signal-1"],
                        "deferred_tool": "desktop.click_ui_element",
                        "deferred_input": {
                            "target": "Export",
                            "role_filter": "",
                            "click_count": 1,
                            "limit": 80,
                        },
                        "deferred_context": {"step_id": "operate-foreground-ui"},
                        "deferred_continuation": [
                            {"tool": "desktop.ui_elements", "step_id": "verify-desktop-result"}
                        ],
                        "input_preview": {"target": "Export", "limit": 80},
                        "result": {"ok": True, "summary": "Clicked Export"},
                    },
                },
            ],
        }
    )

    assert task.replan_recoveries
    recovery = task.replan_recoveries[0]
    assert recovery.request_id == "replan-1"
    assert recovery.approval_id == "approval-1"
    assert recovery.approval_status == "approved"
    assert recovery.deferred_tool == "desktop.click_ui_element"
    assert recovery.deferred_input["target"] == "Export"
    assert recovery.deferred_context == {"step_id": "operate-foreground-ui"}
    assert recovery.deferred_continuation == [
        {"tool": "desktop.ui_elements", "step_id": "verify-desktop-result"}
    ]
    assert recovery.selected_tool_name == "desktop.click_ui_element"
    assert recovery.tool_status == "completed"
    assert task.runtime_debug is not None
    assert task.runtime_debug.replan_recovery_count == 1
    assert task.runtime_debug.current_capability_id == "desktop.ui_operation"
    assert task.runtime_debug.latest_replan_request_id == "replan-1"
    assert task.runtime_debug.latest_replan_trigger == "verification_failed"
    assert task.runtime_debug.latest_recovery_action_id == (
        "replan-1:action:1:desktop.click_ui_element"
    )
    assert task.runtime_debug.latest_recovery_tool == "desktop.click_ui_element"
    assert task.runtime_debug.latest_recovery_action_label == "Click observed Export control"
    assert task.runtime_debug.latest_recovery_action_count == 1
    assert task.runtime_debug.latest_deferred_tool == "desktop.click_ui_element"
    assert task.runtime_debug.runtime_stage == "operate"
    assert task.runtime_debug.runtime_role == "desktop_ui_action"
    assert recovery.recovery_actions[0].approval_id == "approval-1"
    assert recovery.recovery_actions[0].approval_status == "approved"
    assert recovery.recovery_actions[0].deferred_tool == "desktop.click_ui_element"
    tool_call = next(
        call
        for call in task.tool_calls
        if call.tool_name == "desktop.click_ui_element"
        and call.status == "completed"
    )
    assert tool_call.runtime_stage == "operate"
    assert tool_call.runtime_role == "desktop_ui_action"
    assert tool_call.requires_observation is True
    assert tool_call.requires_post_action_verification is True
    assert tool_call.replan_triggers == ["verification_failed"]
    assert tool_call.replan_signal_ids == ["signal-1"]
    assert tool_call.deferred_tool == "desktop.click_ui_element"
    assert tool_call.deferred_input["target"] == "Export"
    assert tool_call.deferred_context == {"step_id": "operate-foreground-ui"}
    assert tool_call.deferred_continuation == [
        {"tool": "desktop.ui_elements", "step_id": "verify-desktop-result"}
    ]
    assert "deferred_tool" not in tool_call.input_preview


def test_agent_task_snapshot_merges_replan_recovery_action_execution_update() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-1",
            "run_id": "run-1",
            "status": "running",
            "events": [
                {
                    "event_type": "agent.replan.requested",
                    "sequence": 1,
                    "run_id": "run-1",
                    "payload": {
                        "request_id": "replan-1",
                        "trigger": "tool_failure",
                        "source_step_id": "open-app",
                        "source_tool_name": "desktop.open_app",
                        "target_capability_id": "desktop.app_discovery",
                        "metadata": {
                            "recovery_actions": [
                                {
                                    "action_id": "replan-1:action:1:desktop.list_apps",
                                    "label": "Find Apple Music",
                                    "tool": "desktop.list_apps",
                                    "input": {"query": "Apple Music"},
                                    "permission_target": "app_discovery",
                                    "risk_level": "low",
                                }
                            ]
                        },
                    },
                },
                {
                    "event_type": "agent.replan.recovery.updated",
                    "sequence": 2,
                    "run_id": "run-1",
                    "payload": {
                        "request_id": "replan-1",
                        "replan_request_id": "replan-1",
                        "trigger": "tool_failure",
                        "replan_trigger": "tool_failure",
                        "status": "completed",
                        "selected_tool_name": "desktop.list_apps",
                        "replan_recovery_action_id": "replan-1:action:1:desktop.list_apps",
                        "replan_signal_ids": ["signal-1"],
                        "verification_targets": [{"step_id": "open-app"}],
                        "recovery_actions": [
                            {
                                "action_id": "replan-1:action:1:desktop.list_apps",
                                "tool": "desktop.list_apps",
                                "input": {"query": "Apple Music"},
                                "selected": True,
                                "metadata": {
                                    "replan_signal_ids": ["signal-1"],
                                    "runtime_stage": "verify",
                                    "verification_target_step_ids": ["open-app"],
                                },
                                "verification_targets": [{"step_id": "open-app"}],
                            }
                        ],
                    },
                },
            ],
        }
    )

    recovery = task.replan_recoveries[0]
    assert recovery.status == "completed"
    assert recovery.tool_status == "completed"
    assert len(recovery.recovery_actions) == 1
    action = recovery.recovery_actions[0]
    assert action.action_id == "replan-1:action:1:desktop.list_apps"
    assert action.label == "Find Apple Music"
    assert action.risk_level == "low"
    assert action.selected is True
    assert action.metadata["replan_signal_ids"] == ["signal-1"]
    assert action.metadata["runtime_stage"] == "verify"
    assert action.metadata["verification_target_step_ids"] == ["open-app"]
    assert action.verification_targets == [{"step_id": "open-app"}]


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
    event_types = [event.event_type for event in task.recent_events]
    assert "agent.task.todo.updated" in event_types
    assert "agent.task.checkpoint.updated" in event_types
    assert task.recent_events[0].payload["intent"]["kind"] == "data_analysis"
    assert task.task_core is not None
    assert [todo.step_id for todo in task.task_core.todos] == [
        "read-data-source",
        "analyze-data-file",
    ]


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


def test_yachiyo_agent_service_keeps_provider_session_event_with_existing_planner_events(
) -> None:
    class ProviderSessionRuntimePort(_BareStartTaskRuntimePort):
        def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(("start_chat_task", request))
            return _task_payload(
                status="running",
                title=request.get("title") or "Chat task",
                session_id=str(request.get("conversation_id") or ""),
                events=[
                    {
                        "event_type": "agent.intent.selected",
                        "payload": {"intent": {"kind": "desktop_operation"}},
                    }
                ],
                runtime_execution_envelope={
                    "envelope_id": "envelope-provider-session",
                    "requests": [
                        {
                            "request_id": "request-click-ui",
                            "tool_name": "app.focus_and_click_ui_element",
                        }
                    ],
                    "desktop_provider_session": {
                        "ok": False,
                        "status": "start_failed",
                        "needed": True,
                        "running": False,
                        "provider_id": "local-isolated-desktop",
                        "reason": "sandbox_desktop_provider_required",
                        "tool_names": ["app.focus_and_click_ui_element"],
                        "desktop_session_kind": "isolated_desktop",
                        "desktop_session_isolated": True,
                        "foreground_takeover_required": False,
                    },
                },
            )

    service = YachiyoAgentService(ProviderSessionRuntimePort(existing_planner_events=True))

    task = service.start_chat_task(
        StartChatTaskRequest(
            prompt="在 PixelForge 点击 Export",
            conversation_id="chat-1",
            allowed_tools=["app.focus_and_click_ui_element", "desktop.ui_elements"],
        )
    )

    event_types = [event.event_type for event in task.recent_events]
    assert event_types.count("agent.intent.selected") == 1
    assert "desktop.provider_session.failed" in event_types
    provider_event = next(
        event
        for event in task.recent_events
        if event.event_type == "desktop.provider_session.failed"
    )
    assert provider_event.sequence == 2
    assert provider_event.payload["desktop_provider_session"]["provider_id"] == (
        "local-isolated-desktop"
    )
    assert task.runtime_debug is not None
    assert task.runtime_debug.desktop_provider_session_status == "start_failed"
    assert task.runtime_debug.needs_replan is True


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
    assert metadata["yachiyo_plan_tools"] == ["workspace.read", "data.analyze"]
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
        assert metadata["yachiyo_plan_tools"] == ["workspace.read", "data.analyze"]
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
    assert catalog.groups[0].runnable_id == "group-1"
    assert catalog.groups[0].group_id == "group-1"
    assert catalog.groups[0].kind == "group"
    assert catalog.groups[0].output_contract == "group_run"
    assert catalog.groups[0].participants[0].runnable_id == "agent-1"
    assert port.calls == [("list_runnable_catalog", None)]


def test_yachiyo_agent_service_falls_back_to_port_groups_for_runnable_catalog() -> None:
    class _PortWithGroups(_FakeRuntimePort):
        def list_runnable_catalog(self) -> dict[str, Any]:
            self.calls.append(("list_runnable_catalog", None))
            payload = super().list_runnable_catalog()
            self.calls.pop()
            payload.pop("groups", None)
            return payload

        def list_groups(self) -> dict[str, Any]:
            self.calls.append(("list_groups", None))
            return {
                "groups": [
                    {
                        "group_id": "group-fallback",
                        "name": "Fallback group",
                        "members": [{"agent_id": "agent-1"}],
                    }
                ]
            }

    port = _PortWithGroups()
    service = YachiyoAgentService(port)

    catalog = service.list_runnable_catalog()

    assert catalog.groups[0].group_id == "group-fallback"
    assert catalog.groups[0].participants[0].agent_id == "agent-1"
    assert port.calls == [("list_runnable_catalog", None), ("list_groups", None)]


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


def test_yachiyo_agent_service_stream_fallback_first_page_includes_key_status_window() -> None:
    port = _FakeRuntimePort()
    service = YachiyoAgentService(port)

    page = service.get_task_event_page("task-1", after_sequence=0, limit=1)

    assert [event.event_type for event in page.events] == [
        "task.started",
        "tool.requested",
        "task.completed",
    ]
    assert page.next_after_sequence == 3
    assert page.has_more is True
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
        ),
        ("get_task_event_stream", "task-1"),
    ]


def test_yachiyo_agent_service_task_event_first_page_includes_key_status_window() -> None:
    port = _FirstPageKeyStatusRuntimePort()
    service = YachiyoAgentService(port)

    page = service.get_task_event_page("task-1", after_sequence=0, limit=2)
    event_types = [event.event_type for event in page.events]

    assert event_types == [
        "task.started",
        "agent.plan.created",
        "desktop.provider_session.started",
        "agent.tool.started",
        "agent.tool.approval_required",
    ]
    assert page.next_after_sequence == 5
    assert page.events[-1].task_id == "task-1"
    assert page.events[-1].payload["task_id"] == "task-1"
    assert port.calls == [
        (
            "get_task_event_page",
            {
                "task_id": "task-1",
                "after_sequence": 0,
                "limit": 2,
            },
        ),
        ("get_task_event_stream", "task-1"),
    ]


def test_yachiyo_agent_service_task_event_first_page_prefers_replan_window() -> None:
    port = _FirstPageRuntimeStateRuntimePort(include_replan=True)
    service = YachiyoAgentService(port)

    page = service.get_task_event_page("task-1", after_sequence=0, limit=2)
    event_types = [event.event_type for event in page.events]

    assert event_types == [
        "task.started",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.task.todo.updated",
        "agent.task.checkpoint.updated",
        "agent.tool.started",
        "agent.replan.requested",
    ]
    assert page.next_after_sequence == 7
    assert page.events[-1].payload["request_id"] == "replan-1"
    assert port.calls == [
        (
            "get_task_event_page",
            {
                "task_id": "task-1",
                "after_sequence": 0,
                "limit": 2,
            },
        ),
        ("get_task_event_stream", "task-1"),
    ]


def test_yachiyo_agent_service_task_event_first_page_includes_runtime_state_block() -> None:
    port = _FirstPageRuntimeStateRuntimePort(include_replan=False)
    service = YachiyoAgentService(port)

    page = service.get_task_event_page("task-1", after_sequence=0, limit=2)
    event_types = [event.event_type for event in page.events]

    assert event_types == [
        "task.started",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.task.todo.updated",
        "agent.task.checkpoint.updated",
    ]
    assert page.next_after_sequence == 5
    assert page.events[2].payload["core_id"] == "task-core-1"
    assert page.events[3].payload["todo_id"] == "todo-1"
    assert page.events[4].payload["checkpoint_id"] == "checkpoint-1"
    assert port.calls == [
        (
            "get_task_event_page",
            {
                "task_id": "task-1",
                "after_sequence": 0,
                "limit": 2,
            },
        ),
        ("get_task_event_stream", "task-1"),
    ]


def test_yachiyo_agent_service_task_event_first_page_includes_provider_session_window() -> None:
    port = _FirstPageDesktopProviderRuntimePort()
    service = YachiyoAgentService(port)

    page = service.get_task_event_page("task-1", after_sequence=0, limit=2)
    event_types = [event.event_type for event in page.events]

    assert event_types == [
        "task.started",
        "agent.plan.created",
        "agent.tool.started",
        "desktop.provider_session.started",
        "agent.deferred_continuation.enqueued",
    ]
    assert page.next_after_sequence == 5
    assert page.events[-2].payload["desktop_provider_session"]["provider_id"] == "isolated-vnc"
    assert page.events[-1].payload["deferred_tools"] == ["desktop.safe_type_text"]
    assert port.calls == [
        (
            "get_task_event_page",
            {
                "task_id": "task-1",
                "after_sequence": 0,
                "limit": 2,
            },
        ),
        ("get_task_event_stream", "task-1"),
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


def test_yachiyo_agent_service_preserves_group_target_when_starting_chat_task() -> None:
    port = _FakeRuntimePort()
    starter = _FakeChatTaskStarter()
    service = YachiyoAgentService(port, chat_task_starter=starter)

    service.start_chat_task(
        StartChatTaskRequest(
            prompt="一起整理调研结论",
            conversation_id="chat-1",
            group_id="group-1",
        )
    )

    assert starter.calls[0]["group_id"] == "group-1"
    assert port.calls[0][0] == "start_chat_task"
    assert port.calls[0][1]["group_id"] == "group-1"


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


def _replan_recovery_task_payload(**overrides: Any) -> dict[str, Any]:
    task_id = str(overrides.get("task_id") or "task-1")
    payload_overrides = dict(overrides)
    payload_overrides.pop("task_id", None)
    return _task_payload(
        task_id=task_id,
        run_id="run-1",
        session_id="chat-1",
        title="Open Apple Music",
        status="running",
        events=[
            {
                "event_type": "agent.task_core.created",
                "payload": {
                    "core_id": "task-core-1",
                    "workspace_id": "task-workspace-1",
                    "task_core": {
                        "core_id": "task-core-1",
                        "workspace": {
                            "workspace_id": "task-workspace-1",
                            "title": "Desktop Recovery Workspace",
                            "items": [
                                {
                                    "item_id": "workspace-open-app",
                                    "title": "Apple Music app target",
                                    "kind": "scratch",
                                    "source_step_id": "open-app",
                                    "status": "blocked",
                                }
                            ],
                        },
                        "todos": [
                            {
                                "todo_id": "todo-open-app",
                                "title": "Open Apple Music",
                                "status": "blocked",
                                "step_id": "open-app",
                                "tool_name": "desktop.open_app",
                            }
                        ],
                        "checkpoints": [
                            {
                                "checkpoint_id": "checkpoint:open-app",
                                "title": "Verify Apple Music opened",
                                "status": "blocked",
                                "after_step_id": "open-app",
                            }
                        ],
                        "replan_signals": [],
                    },
                },
            },
            {
                "event_type": "agent.replan.requested",
                "payload": {
                    "request_id": "replan-1",
                    "trigger": "tool_failure",
                    "run_id": "run-1",
                    "task_id": task_id,
                    "core_id": "task-core-1",
                    "source_step_id": "open-app",
                    "source_tool_name": "desktop.open_app",
                    "target_capability_id": "desktop.app_discovery",
                    "planning_reason": "planner_replan_runtime_recovery_action",
                    "verification_targets": [
                        {
                            "step_id": "open-app",
                            "todo_id": "todo-open-app",
                            "todo_title": "Open Apple Music",
                            "tool_name": "desktop.open_app",
                            "checkpoint_ids": ["checkpoint:open-app"],
                            "checkpoint_titles": ["Verify Apple Music opened"],
                        }
                    ],
                    "metadata": {
                        "recovery_actions": [
                            {
                                "action_id": "replan-1:action:1:desktop.list_apps",
                                "label": "Find Apple Music",
                                "tool": "desktop.list_apps",
                                "input": {"query": "Apple Music"},
                                "permission_target": "app_discovery",
                                "risk_level": "low",
                                "metadata": {
                                    "replan_signal_ids": ["signal-1"],
                                    "replan_triggers": ["verification_failed"],
                                    "runtime_stage": "verify",
                                    "verification_target_step_ids": ["open-app"],
                                },
                            }
                        ],
                    },
                },
            },
        ],
        **payload_overrides,
    )


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
