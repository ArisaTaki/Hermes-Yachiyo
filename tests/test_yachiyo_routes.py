"""Yachiyo public facade route tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.bridge.routes import (
    yachiyo,
    yachiyo_chat_handlers,
    yachiyo_studio_run_handlers,
    yachiyo_studio_tool_handlers,
)
from apps.core.chat_session import ChatSession, MessageStatus
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.chat_api import ChatAPI
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent import (
    AgentTaskSnapshot,
    PlannerOrchestrationStartSnapshot,
    RunTimelineSnapshot,
    WorkflowRunSnapshot,
    legacy_ports,
)
from apps.shell.yachiyo_agent.runtime_execution import runtime_execution_envelope_from_decision
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner
from packages.protocol.enums import TaskStatus


class _FakeAgentRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.task_links: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.restricted_plugins: dict[str, dict[str, Any]] = {
            "notes": _restricted_plugin_payload(enabled=False)
        }

    def list_runnables(self) -> dict[str, Any]:
        self.calls.append(("list_runnables", None))
        return {"ok": True, "runnables": [{"id": "builtin:yachiyo-main"}]}

    def create_run_for_runnable_async(self, **payload: Any) -> dict[str, Any]:
        self.calls.append(("create_run_for_runnable_async", payload))
        run = _run_payload(status="approval_required")
        self.runs[run["run_id"]] = run
        return run

    def get_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run", run_id))
        link = next(
            (item for item in self.task_links.values() if item["run_id"] == run_id),
            {},
        )
        return {
            **self.runs.get(run_id, _run_payload(run_id=run_id, status="completed", result="Done")),
            "task_id": link.get("task_id", ""),
            "session_id": link.get("session_id", ""),
            "task_run_link_created_at": link.get("created_at", ""),
            "task_run_link_updated_at": link.get("updated_at", ""),
            "task_run_link_run_status": link.get("run_status", ""),
            "task_run_link_last_event_sequence": link.get("last_event_sequence", 0),
        }

    def list_runs(self, limit: int) -> dict[str, Any]:
        self.calls.append(("list_runs", limit))
        linked_runs = [
            {
                **self.runs.get(
                    link["run_id"],
                    _run_payload(run_id=link["run_id"], status="completed", result="Done"),
                ),
                "task_id": link["task_id"],
                "session_id": link["session_id"],
                "task_run_link_created_at": link.get("created_at", ""),
                "task_run_link_updated_at": link.get("updated_at", ""),
                "task_run_link_run_status": link.get("run_status", ""),
                "task_run_link_last_event_sequence": link.get("last_event_sequence", 0),
            }
            for link in self.task_links.values()
        ]
        return {
            "ok": True,
            "runs": [
                *linked_runs,
                _run_payload(run_id="studio-run", status="completed", result="Studio"),
            ],
        }

    def link_task_run(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        self.calls.append(
            (
                "link_task_run",
                {"task_id": task_id, "run_id": run_id, "session_id": session_id},
            )
        )
        self.task_links[task_id] = {
            "task_id": task_id,
            "run_id": run_id,
            "session_id": session_id,
            "run_status": self.runs.get(run_id, {}).get("status", ""),
            "last_event_sequence": len(self.runs.get(run_id, {}).get("timeline", []) or []),
            "created_at": "2026-06-14T00:00:00Z",
            "updated_at": "2026-06-14T00:00:02Z",
        }
        return self.task_links[task_id]

    def get_task_run_link(self, task_id: str) -> dict[str, Any]:
        self.calls.append(("get_task_run_link", task_id))
        link = self.task_links.get(task_id)
        if link is None:
            raise KeyError(task_id)
        return link

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("approve_run_approval", run_id))
        return _run_payload(run_id=run_id, status="completed", result="Approved")

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        self.calls.append(("reject_run_approval", {"run_id": run_id, "reason": reason}))
        return _run_payload(run_id=run_id, status="failed", result="Rejected")

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_run", run_id))
        return _run_payload(run_id=run_id, status="cancelled")

    def rerun_run(
        self,
        run_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_request = dict(request or {})
        self.calls.append(
            (
                "rerun_run",
                {"run_id": run_id, "request": clean_request} if clean_request else run_id,
            )
        )
        payload = _run_payload(run_id=f"{run_id}-rerun", status="processing")
        rerun_scope = str(clean_request.get("scope") or "")
        payload["timeline"] = [
            _rerun_started_event(
                run_id,
                kind="agent_run",
                status="completed",
                runnable_id="agent-1",
                runnable_name="Planner",
                extra={
                    "rerun_scope": rerun_scope,
                    "workflow_node_id": clean_request.get("workflow_node_id", ""),
                    "workflow_edge_branch": clean_request.get("workflow_edge_branch", ""),
                    "workflow_node_selected_target": clean_request.get(
                        "workflow_node_selected_target",
                        "",
                    ),
                } if rerun_scope else None,
            )
        ]
        return payload

    def delete_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("delete_run", run_id))
        return {"ok": True, "deleted_run_ids": [run_id], "deleted_run_count": 1}

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        self.calls.append(
            ("read_run_artifact", {"run_id": run_id, "artifact_path": artifact_path})
        )
        return {"ok": True, "run_id": run_id, "path": artifact_path, "content": "# Report"}

    def list_agents(self) -> dict[str, Any]:
        self.calls.append(("list_agents", None))
        return {"ok": True, "agents": [_agent_payload()]}

    def list_restricted_tool_plugins(self) -> dict[str, Any]:
        self.calls.append(("list_restricted_tool_plugins", None))
        return {"ok": True, "plugins": list(self.restricted_plugins.values())}

    def install_restricted_tool_plugin(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("install_restricted_tool_plugin", payload))
        plugin_id = str(payload["plugin_id"])
        plugin = _restricted_plugin_payload(
            plugin_id=plugin_id,
            enabled=bool(payload.get("enabled", True)),
        )
        self.restricted_plugins[plugin_id] = plugin
        return plugin

    def update_restricted_tool_plugin(
        self,
        plugin_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "update_restricted_tool_plugin",
                {"plugin_id": plugin_id, "payload": payload},
            )
        )
        plugin = self.restricted_plugins[plugin_id]
        if "enabled" in payload:
            plugin = {**plugin, "enabled": bool(payload["enabled"])}
            plugin["tools"] = [
                {**tool, "enabled": bool(payload["enabled"])}
                for tool in plugin.get("tools") or []
            ]
            self.restricted_plugins[plugin_id] = plugin
        return plugin

    def uninstall_restricted_tool_plugin(self, plugin_id: str) -> dict[str, Any]:
        self.calls.append(("uninstall_restricted_tool_plugin", plugin_id))
        plugin = self.restricted_plugins.pop(plugin_id)
        return {**plugin, "enabled": False, "tools": []}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("get_agent", agent_id))
        return _agent_payload(agent_id=agent_id)

    def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_agent", payload))
        return _agent_payload(agent_id="agent-new", name=payload.get("name") or "New")

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("update_agent", {"agent_id": agent_id, "payload": payload}))
        return _agent_payload(agent_id=agent_id, name=payload.get("name") or "Updated")

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("delete_agent", agent_id))
        return {"ok": True, "agent_id": agent_id}

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("test_agent_model", agent_id))
        return {"ok": True, "message": "Model ready"}

    def attach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        self.calls.append(("attach_skill", {"agent_id": agent_id, "skill_id": skill_id}))
        return _agent_payload(agent_id=agent_id, skill_ids=[skill_id])

    def detach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        self.calls.append(("detach_skill", {"agent_id": agent_id, "skill_id": skill_id}))
        return _agent_payload(agent_id=agent_id, skill_ids=[])

    def list_skills(self) -> dict[str, Any]:
        self.calls.append(("list_skills", None))
        return {"ok": True, "skills": [_skill_payload()]}

    def update_skill(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("update_skill", {"skill_id": skill_id, "payload": payload}))
        return _skill_payload(skill_id=skill_id) | {
            "enabled": bool(payload.get("enabled", True)),
            "folder_id": str(payload.get("folder_id") or ""),
        }

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        self.calls.append(("delete_skill", skill_id))
        return {"ok": True, "skill_id": skill_id}

    def list_skill_folders(self) -> dict[str, Any]:
        self.calls.append(("list_skill_folders", None))
        return {
            "ok": True,
            "folders": [_skill_folder_payload()],
            "uncategorized": _skill_folder_payload(
                folder_id="",
                name="Uncategorized",
                source_scope="all",
                sort_order=-1,
            ),
        }

    def create_skill_folder(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_skill_folder", payload))
        return _skill_folder_payload(
            folder_id=payload.get("folder_id") or "folder-new",
            name=payload["name"],
        )

    def update_skill_folder(self, folder_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(
            ("update_skill_folder", {"folder_id": folder_id, "payload": payload})
        )
        return _skill_folder_payload(folder_id=folder_id, name=payload.get("name") or "Updated")

    def delete_skill_folder(self, folder_id: str, *, delete_skills: bool = False) -> dict[str, Any]:
        self.calls.append(
            ("delete_skill_folder", {"folder_id": folder_id, "delete_skills": delete_skills})
        )
        return {"ok": True, "deleted_skill_count": 2 if delete_skills else 0}

    def list_native_skill_sources(self) -> dict[str, Any]:
        self.calls.append(("list_native_skill_sources", None))
        return {"ok": True, "roots": [_skill_source_payload()]}

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("import_skill", {"source_path": source_path, "folder_id": folder_id}))
        return _skill_payload(skill_id="skill-imported", name="Imported Skill") | {
            "source_path": source_path,
            "folder_id": folder_id or "",
        }

    def sync_native_skills(self) -> dict[str, Any]:
        self.calls.append(("sync_native_skills", None))
        return {"ok": True, "summary": {"imported": 1}}

    def install_skill_command(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        self.calls.append(
            ("install_skill_command", {"command": command, "folder_id": folder_id})
        )
        return {"ok": True, "installer": "npx_skills", "command": command.split()}

    def list_memory_items(self, *, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        self.calls.append(
            ("list_memory_items", {"include_deleted": include_deleted, "limit": limit})
        )
        return {"ok": True, "memories": [_memory_payload()]}

    def create_memory_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_memory_item", payload))
        return _memory_payload(memory_id="memory-created", content=payload["content"])

    def update_memory_item(self, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("update_memory_item", {"memory_id": memory_id, "payload": payload}))
        return _memory_payload(memory_id=memory_id, content=payload["content"])

    def delete_memory_item(self, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        self.calls.append(("delete_memory_item", {"memory_id": memory_id, "reason": reason}))
        return {"ok": True, "memory_id": memory_id}

    def list_future_tasks(
        self,
        *,
        include_finished: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "list_future_tasks",
                {"include_finished": include_finished, "limit": limit},
            )
        )
        return {"ok": True, "future_tasks": [_future_task_payload()]}

    def cancel_future_task(self, future_task_id: str, *, reason: str = "") -> dict[str, Any]:
        self.calls.append(
            (
                "cancel_future_task",
                {"future_task_id": future_task_id, "reason": reason},
            )
        )
        return {
            "ok": True,
            "future_task": _future_task_payload(
                future_task_id=future_task_id,
                status="cancelled",
                cancelled_at="2026-06-14T00:00:02Z",
            ),
        }

    def trigger_due_future_tasks(
        self,
        *,
        now_epoch: float | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "trigger_due_future_tasks",
                {"now_epoch": now_epoch, "limit": limit},
            )
        )
        return {
            "ok": True,
            "triggered": [
                {
                    "ok": True,
                    "future_task": _future_task_payload(
                        status="triggered",
                        last_run_id="run-1",
                        run_count=1,
                    ),
                    "run": _run_payload(run_id="run-1", user_goal="Follow up"),
                }
            ],
        }

    def schedule_future_task(
        self,
        payload: dict[str, Any],
        *,
        source_run_id: str = "",
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "schedule_future_task",
                {"payload": payload, "source_run_id": source_run_id},
            )
        )
        return {
            "ok": True,
            "future_task": _future_task_payload(
                future_task_id="future-desk-1",
                title=payload["title"],
                prompt=payload["prompt"],
                runnable_id=payload["runnable_id"],
                source_run_id=source_run_id,
            ),
        }

    def create_agent_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_agent_run", payload))
        return _run_payload(
            run_id="agent-run-1",
            kind="agent_run",
            runnable_id=payload["agent_id"],
            user_goal=payload["user_goal"],
        )

    def list_workflows(self) -> dict[str, Any]:
        self.calls.append(("list_workflows", None))
        return {"ok": True, "workflows": [_workflow_payload()]}

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.calls.append(("get_workflow", workflow_id))
        return _workflow_payload(workflow_id=workflow_id)

    def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_workflow", payload))
        return _workflow_payload(workflow_id="workflow-new", name=payload.get("name") or "New")

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("update_workflow", {"workflow_id": workflow_id, "payload": payload}))
        return _workflow_payload(workflow_id=workflow_id, name=payload.get("name") or "Updated")

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.calls.append(("delete_workflow", workflow_id))
        return {"ok": True, "workflow_id": workflow_id}

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_workflow_run", payload))
        run = _run_payload(
            run_id="workflow-run-1",
            kind="workflow_run",
            runnable_id=payload["workflow_id"],
            user_goal=payload["user_goal"],
            result="Workflow final answer",
        )
        run["workflow_node_id"] = "node-start"
        run["workflow_node_label"] = "Start"
        self.runs[run["run_id"]] = run
        return run

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_group", run_group_id))
        return {
            "run_group_id": run_group_id,
            "title": "Run group",
            "source": "workflow",
            "status": "running",
            "summary": "Summary",
            "events": [
                {
                    "event": "group.member.started",
                    "run_id": run_group_id,
                    "sequence": 1,
                    "member_agent_id": "agent-1",
                    "payload": {"step": "plan"},
                },
                {
                    "event": "group.member.completed",
                    "run_id": run_group_id,
                    "sequence": 2,
                    "member_agent_id": "agent-1",
                    "payload": {"step": "plan"},
                },
            ],
            "child_run_ids": ["run-1"],
            "created_at": "2026-06-14T00:00:00Z",
            "updated_at": "2026-06-14T00:00:01Z",
        }

    def list_run_groups(self, limit: int) -> dict[str, Any]:
        self.calls.append(("list_run_groups", limit))
        return {"ok": True, "run_groups": [self.get_run_group("group-run-1")]}

    def list_run_events(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("list_run_events", run_id))
        if run_id == "missing-run":
            raise KeyError(run_id)
        return {
            "run_id": run_id,
            "after_sequence": 0,
            "limit": 200,
            "events": [
                {
                    "event_id": "event-1",
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "agent.started",
                    "payload": {"status": "running"},
                },
                {
                    "event_id": "event-2",
                    "run_id": run_id,
                    "sequence": 2,
                    "event_type": "agent.tool.call",
                    "visibility": "internal",
                    "payload": {"status": "internal", "tool": "workspace.read"},
                },
                {
                    "event_id": "event-3",
                    "run_id": run_id,
                    "sequence": 3,
                    "event_type": "agent.tool.call",
                    "sensitivity": "secret",
                    "payload": {"status": "secret", "api_key": "sk-secret"},
                },
                {
                    "event_id": "event-4",
                    "run_id": run_id,
                    "sequence": 4,
                    "event_type": "agent.completed",
                    "payload": {"status": "completed"},
                }
            ],
        }

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.calls.append(
            (
                "append_run_event",
                {"run_id": run_id, "event_type": event_type, "payload": payload},
            )
        )


@pytest.mark.asyncio
async def test_yachiyo_task_routes_use_injected_runtime_and_return_public_snapshots() -> None:
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    readiness = await yachiyo.readiness(request)
    runnables = await yachiyo.list_chat_runnables(request)
    started = await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(prompt="Patch README", conversation_id="chat-1"),
        request,
    )
    tasks = await yachiyo.list_tasks("chat-1", request)
    fetched_by_run_id = await yachiyo.get_task("run-1", request)
    task_timeline = await yachiyo.get_task_timeline("run-1", request)
    task_events = await yachiyo.get_task_events(
        "run-1",
        request,
        after_sequence=0,
        limit=1,
    )
    task_artifact = await yachiyo.get_task_artifact("run-1", "report.md", request)
    approved = await yachiyo.approve_task("run-1", None, request)
    rejected = await yachiyo.reject_task(
        "run-1",
        yachiyo.TaskApprovalRequest(reason="No"),
        request,
    )
    cancelled = await yachiyo.cancel_task("run-1", request)

    assert readiness["ready"] is True
    assert runnables["agents"][0]["runnable_id"] == "agent-1"
    assert runnables["agents"][0]["agent_id"] == "agent-1"
    assert runnables["agents"][0]["kind"] == "agent"
    assert "model_config" not in runnables["agents"][0]
    assert "tool_policy" not in runnables["agents"][0]
    assert runnables["workflows"][0]["runnable_id"] == "workflow-1"
    assert runnables["workflows"][0]["workflow_id"] == "workflow-1"
    assert runnables["workflows"][0]["kind"] == "workflow"
    assert "nodes" not in runnables["workflows"][0]
    assert "edges" not in runnables["workflows"][0]
    assert started["task_id"] == "run-1"
    assert started["status"] == "waiting_approval"
    assert started["conversation_id"] == "chat-1"
    assert started["open_in_studio_url"] == "#/agents?run_id=run-1&group_run=group-run-1"
    assert tasks["tasks"][0]["task_id"] == "run-1"
    assert tasks["tasks"][0]["conversation_id"] == "chat-1"
    assert all(task["task_id"] != "studio-run" for task in tasks["tasks"])
    assert fetched_by_run_id["task_id"] == "run-1"
    assert fetched_by_run_id["status"] == "waiting_approval"
    assert fetched_by_run_id["pending_approvals"][0]["approval_id"] == "run-1"
    assert task_timeline["run_id"] == "run-1"
    assert task_timeline["task_id"] == "run-1"
    assert task_timeline["session_id"] == "chat-1"
    assert task_timeline["events"][0]["event_type"] == "agent.tool.call"
    assert task_timeline["pending_approval"]["approval_id"] == "run-1"
    assert task_timeline["artifacts"][0]["path"] == "report.md"
    assert task_events["run_id"] == "run-1"
    assert task_events["after_sequence"] == 0
    assert task_events["limit"] == 1
    assert task_events["next_after_sequence"] == 4
    assert task_events["has_more"] is True
    assert [event["event_type"] for event in task_events["events"]] == [
        "agent.started",
        "agent.completed",
    ]
    full_task_events = await yachiyo.get_task_events(
        "run-1",
        request,
        after_sequence=0,
        limit=10,
    )
    assert [event["event_type"] for event in full_task_events["events"]] == [
        "agent.started",
        "agent.completed",
    ]
    assert all(event["visibility"] == "user" for event in full_task_events["events"])
    assert all(event["sensitivity"] == "public" for event in full_task_events["events"])
    assert task_artifact["ok"] is True
    assert task_artifact["run_id"] == "run-1"
    assert task_artifact["task_id"] == "run-1"
    assert task_artifact["path"] == "report.md"
    assert task_artifact["content"] == "# Report"
    assert approved["status"] == "completed"
    assert rejected["status"] == "failed"
    assert cancelled["status"] == "cancelled"
    assert (
        "create_run_for_runnable_async",
        {"runnable_id": "builtin:yachiyo-main", "user_goal": "Patch README"},
    ) in runtime.calls
    assert (
        "link_task_run",
        {"task_id": "run-1", "run_id": "run-1", "session_id": "chat-1"},
    ) in runtime.calls


@pytest.mark.asyncio
async def test_yachiyo_task_route_starts_replan_recovery_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAgentService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def start_replan_recovery_action(
            self,
            task_id: str,
            payload: dict[str, Any],
        ) -> AgentTaskSnapshot:
            self.calls.append(("start_replan_recovery_action", {"task_id": task_id, "payload": payload}))
            return AgentTaskSnapshot(
                task_id="recovery-task-1",
                conversation_id=payload.get("conversation_id") or "chat-1",
                title="Recover",
                status="running",
                metadata={
                    "source": "yachiyo_chat_replan_recovery",
                    "replan_request_id": payload.get("request_id"),
                    "replan_recovery_action_id": payload.get("action_id"),
                },
            )

    service = _FakeAgentService()
    monkeypatch.setattr(yachiyo_chat_handlers, "agent_service", lambda _request=None: service)

    response = await yachiyo.start_task_replan_recovery_action(
        "task-1",
        yachiyo.RunReplanRecoveryActionBody(
            request_id="replan-1",
            action_id="replan-1:action:1:desktop.list_apps",
            conversation_id="chat-1",
            metadata={"surface": "chat"},
        ),
        None,
    )

    assert response["task_id"] == "recovery-task-1"
    assert response["metadata"]["source"] == "yachiyo_chat_replan_recovery"
    assert service.calls == [
        (
            "start_replan_recovery_action",
            {
                "task_id": "task-1",
                "payload": {
                    "request_id": "replan-1",
                    "action_id": "replan-1:action:1:desktop.list_apps",
                    "conversation_id": "chat-1",
                    "continue_to_model": True,
                    "metadata": {"surface": "chat"},
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_yachiyo_task_approve_preserves_approval_decision_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ApproveRecordingService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def approve(self, task_id: str, decision: Any) -> AgentTaskSnapshot:
            payload = decision.model_dump(exclude_none=True)
            self.calls.append({"task_id": task_id, "decision": payload})
            return AgentTaskSnapshot(task_id=task_id, title="Approved", status="completed")

    service = _ApproveRecordingService()
    monkeypatch.setattr(yachiyo_chat_handlers, "agent_service", lambda _request=None: service)

    approved = await yachiyo.approve_task(
        "task-approval-1",
        yachiyo.TaskApprovalRequest(
            approval_id="approval-1",
            reason="Looks safe",
            metadata={"surface": "bubble"},
        ),
        None,
    )

    assert approved["status"] == "completed"
    assert service.calls == [
        {
            "task_id": "task-approval-1",
            "decision": {
                "approved": True,
                "reason": "Looks safe",
                "metadata": {
                    "approval_id": "approval-1",
                    "surface": "bubble",
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_task_approve_syncs_main_chat_desktop_approval_to_chat(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "agent-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    hotkey_calls: list[tuple[str, list[str] | None]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("desktop approval should not call model")
        ),
    )

    def fake_desktop_hotkey(key: str, *, modifiers: list[str] | None = None) -> dict:
        hotkey_calls.append((key, modifiers))
        return {
            "ok": True,
            "action": "desktop.hotkey",
            "summary": "Sent hotkey",
            "data": {
                "key": key,
                "modifiers": list(modifiers or []),
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_hotkey", fake_desktop_hotkey)
    try:
        sent = ChatAPI(app_runtime).send_message("按 Command+L")
        task = state.get_task(sent["task_id"])
        waiting_message = session.get_assistant_message_for_task(sent["task_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING
        assert hotkey_calls == []

        approved = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        run = service.get_run(sent["run_id"])

        assert approved["status"] == "completed"
        assert approved["summary"] == "已发送快捷键：Command+L。"
        assert hotkey_calls == [("l", ["command"])]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == "已发送快捷键：Command+L。"
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == "已发送快捷键：Command+L。"
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_message.metadata["run_status"] == "completed"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_approve_executes_foreground_submit_after_approval(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-submit.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-submit.db",
        workspace_dir=tmp_path / "agent-runtime-submit",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-submit-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    submit_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("foreground submit approval should not call model")
        ),
    )

    def fake_submit_foreground(action: str = "submit") -> dict[str, Any]:
        submit_calls.append(action)
        return {
            "ok": True,
            "action": "desktop.submit_foreground",
            "summary": f"Submitted foreground {action} action",
            "data": {"submit_action": action},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_submit_foreground",
        fake_submit_foreground,
    )
    try:
        sent = ChatAPI(app_runtime).send_message("发送当前消息")
        task = state.get_task(sent["task_id"])
        waiting_message = session.get_assistant_message_for_task(sent["task_id"])
        waiting_run = service.get_run(sent["run_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert submit_calls == []
        assert waiting_run["pending_approval"]["tool"] == "desktop.submit_foreground"
        assert waiting_run["pending_approval"]["risk_level"] == "high"
        assert waiting_run["pending_approval"]["input_preview"] == {"action": "send"}
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING

        approved = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        run = service.get_run(sent["run_id"])

        assert approved["status"] == "completed"
        assert approved["summary"] == "已确认发送前台内容。"
        assert submit_calls == ["send"]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == "已确认发送前台内容。"
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == "已确认发送前台内容。"
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_message.metadata["run_status"] == "completed"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_approve_continues_main_chat_daily_desktop_sequence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-sequence.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-sequence.db",
        workspace_dir=tmp_path / "agent-runtime-sequence",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-sequence-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily desktop sequence approval should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {"app_name": app_name, "launch_verified": True},
        }

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {
            "ok": True,
            "action": "app.focus",
            "summary": f"Focused {app_name}",
            "data": {"app_name": app_name},
        }

    def fake_desktop_hotkey(key: str, *, modifiers: list[str] | None = None) -> dict[str, Any]:
        calls.append(("hotkey", key, list(modifiers or [])))
        return {
            "ok": True,
            "action": "desktop.hotkey",
            "summary": "Sent hotkey",
            "data": {"key": key, "modifiers": list(modifiers or [])},
        }

    def fake_safe_shortcut(action: str) -> dict[str, Any]:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Sent shortcut",
            "data": {"shortcut_action": action},
        }

    def fake_active_window() -> dict[str, Any]:
        calls.append(("active_window",))
        return {
            "ok": True,
            "action": "desktop.active_window",
            "summary": "Active Notes",
            "data": {"app_name": "Notes", "frontmost_app": "Notes"},
        }

    def fake_ui_elements(
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("ui_elements", role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read Notes UI",
            "data": {
                "app_name": app_name or "Notes",
                "elements": [
                    {
                        "role": "AXTextArea",
                        "name": "Note body",
                        "center": {"x": 120, "y": 120},
                    }
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.active_window", fake_active_window)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_hotkey", fake_desktop_hotkey)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_shortcut",
        fake_safe_shortcut,
    )
    try:
        sent = ChatAPI(app_runtime).send_message("打开 Notes，然后按 Command+L，再复制")
        task = state.get_task(sent["task_id"])
        waiting_message = session.get_assistant_message_for_task(sent["task_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING
        assert calls == []

        approved = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        run = service.get_run(sent["run_id"])
        tool_events = [event for event in run["timeline"] if event.get("event") == "agent.tool.call"]
        successful_tool_events = [
            event
            for event in tool_events
            if isinstance(event.get("result"), dict) and event["result"].get("ok") is True
        ]
        approval_tool_events = [
            event
            for event in tool_events
            if isinstance(event.get("result"), dict)
            and event["result"].get("approval_required") is True
        ]
        completed_events = [
            event for event in run["timeline"] if event.get("event") == "agent.desktop.intent_completed"
        ]

        assert approved["status"] == "completed"
        assert approved["summary"] == "已打开 Notes 并发送快捷键：Command+L。 已复制选中内容。"
        assert calls == [
            ("open", "Notes"),
            ("focus", "Notes"),
            ("active_window",),
            ("hotkey", "l", ["command"]),
            ("shortcut", "copy"),
            ("ui_elements", "", 80, "Notes"),
        ]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == approved["summary"]
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == approved["summary"]
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_message.metadata["run_status"] == "completed"
        assert run["status"] == "completed"
        assert run["pending_approval"] == {}
        assert [event["detail"] for event in successful_tool_events] == [
            "app.open_and_hotkey",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ]
        assert [event["detail"] for event in approval_tool_events] == ["app.open_and_hotkey"]
        assert completed_events[-1]["tools"] == [
            "app.open_and_hotkey",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_approve_handles_consecutive_foreground_sequence_approvals(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-foreground-sequence.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-foreground-sequence.db",
        workspace_dir=tmp_path / "agent-runtime-foreground-sequence",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-foreground-sequence-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("foreground sequence approval should not call model")
        ),
    )

    def fake_desktop_hotkey(key: str, *, modifiers: list[str] | None = None) -> dict[str, Any]:
        calls.append(("hotkey", key, list(modifiers or [])))
        return {
            "ok": True,
            "action": "desktop.hotkey",
            "summary": "Sent hotkey",
            "data": {"key": key, "modifiers": list(modifiers or [])},
        }

    def fake_safe_type_text(text: str) -> dict[str, Any]:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed text",
            "data": {"text": text, "character_count": len(text), "explicit_user_text": True},
        }

    def fake_ui_elements(
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("ui_elements", role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read foreground UI",
            "data": {
                "app_name": app_name,
                "elements": [
                    {
                        "role": "AXTextField",
                        "name": "Address",
                        "value": "github.com",
                        "center": {"x": 120, "y": 60},
                    }
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_hotkey", fake_desktop_hotkey)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_type_text",
        fake_safe_type_text,
    )
    try:
        sent = ChatAPI(app_runtime).send_message("按 Command+L，再输入 github.com，再按回车")
        task = state.get_task(sent["task_id"])
        waiting_message = session.get_assistant_message_for_task(sent["task_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING
        assert calls == []

        after_first = await yachiyo.approve_task(sent["task_id"], None, request)
        first_waiting_task = state.get_task(sent["task_id"])
        first_waiting_message = session.get_assistant_message_for_task(sent["task_id"])
        first_waiting_run = service.get_run(sent["run_id"])

        assert after_first["status"] == "waiting_approval"
        assert first_waiting_task is not None
        assert first_waiting_task.status == TaskStatus.RUNNING
        assert first_waiting_message is not None
        assert first_waiting_message.status == MessageStatus.PROCESSING
        assert first_waiting_run["status"] == "approval_required"
        assert first_waiting_run["pending_approval"]["tool"] == "desktop.hotkey"
        assert first_waiting_run["pending_approval"]["input_preview"] == {
            "key": "return",
            "modifiers": [],
        }
        assert calls == [
            ("hotkey", "l", ["command"]),
            ("type", "github.com"),
        ]

        after_second = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        completed_run = service.get_run(sent["run_id"])
        completed_events = [
            event
            for event in completed_run["timeline"]
            if event.get("event") == "agent.desktop.intent_completed"
        ]

        assert after_second["status"] == "completed"
        assert (
            after_second["summary"]
            == "已发送快捷键：Command+L。 已向前台输入文字（10 个字符）。 已发送快捷键：return。"
        )
        assert calls == [
            ("hotkey", "l", ["command"]),
            ("type", "github.com"),
            ("hotkey", "return", []),
            ("ui_elements", "", 80, ""),
        ]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == after_second["summary"]
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == after_second["summary"]
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_run["status"] == "completed"
        assert completed_run["pending_approval"] == {}
        assert completed_events[-1]["tools"] == [
            "desktop.hotkey",
            "desktop.safe_type_text",
            "desktop.hotkey",
            "desktop.ui_elements",
        ]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_approve_continues_type_into_ui_element_then_return_sequence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-type-into-sequence.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-type-into-sequence.db",
        workspace_dir=tmp_path / "agent-runtime-type-into-sequence",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-type-into-sequence-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("type-into foreground sequence approval should not call model")
        ),
    )

    def fake_type_into_ui_element(
        target: str,
        text: str,
        *,
        role_filter: str = "",
        limit: int = 80,
    ) -> dict[str, Any]:
        calls.append(("type_into", target, text, role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.type_into_ui_element",
            "summary": "Typed into foreground UI element: Search",
            "data": {
                "target": target,
                "matched_label": "Search",
                "role_filter": role_filter,
                "character_count": len(text),
            },
        }

    def fake_desktop_submit_foreground(action: str = "submit") -> dict[str, Any]:
        calls.append(("submit", action))
        return {
            "ok": True,
            "action": "desktop.submit_foreground",
            "summary": "Submitted foreground",
            "data": {"action": action},
        }

    def fake_ui_elements(
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("ui_elements", role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read foreground UI",
            "data": {
                "app_name": app_name,
                "elements": [
                    {
                        "role": "AXTextField",
                        "name": "Search",
                        "value": "yachiyo",
                        "center": {"x": 140, "y": 80},
                    }
                ],
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.type_into_ui_element",
        fake_type_into_ui_element,
    )
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_submit_foreground",
        fake_desktop_submit_foreground,
    )
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    try:
        sent = ChatAPI(app_runtime).send_message("在搜索框输入 yachiyo 并回车")
        task = state.get_task(sent["task_id"])
        waiting_message = session.get_assistant_message_for_task(sent["task_id"])
        waiting_run = service.get_run(sent["run_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING
        assert waiting_run["pending_approval"]["tool"] == "desktop.type_into_ui_element"
        assert waiting_run["pending_approval"]["input_preview"] == {
            "target": "搜索",
            "text": "yachiyo",
            "role_filter": "text",
            "limit": 80,
        }
        assert calls == [("ui_elements", "text", 80, "")]

        after_first = await yachiyo.approve_task(sent["task_id"], None, request)
        first_waiting_run = service.get_run(sent["run_id"])

        assert after_first["status"] == "waiting_approval"
        assert first_waiting_run["status"] == "approval_required"
        assert first_waiting_run["pending_approval"]["tool"] == "desktop.submit_foreground"
        assert first_waiting_run["pending_approval"]["input_preview"] == {
            "action": "confirm",
        }
        assert calls == [
            ("ui_elements", "text", 80, ""),
            ("type_into", "搜索", "yachiyo", "text", 80),
            ("ui_elements", "text", 80, ""),
        ]

        after_second = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        completed_run = service.get_run(sent["run_id"])
        completed_events = [
            event
            for event in completed_run["timeline"]
            if event.get("event") == "agent.desktop.intent_completed"
        ]

        assert after_second["status"] == "completed"
        assert (
            after_second["summary"]
            == "已在前台控件 Search 输入文字（7 个字符）。 Read foreground UI。 已确认前台操作。"
        )
        assert calls == [
            ("ui_elements", "text", 80, ""),
            ("type_into", "搜索", "yachiyo", "text", 80),
            ("ui_elements", "text", 80, ""),
            ("submit", "confirm"),
            ("ui_elements", "text", 80, ""),
        ]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == after_second["summary"]
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == after_second["summary"]
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_run["status"] == "completed"
        assert completed_run["pending_approval"] == {}
        assert completed_events[-1]["tools"] == [
            "desktop.type_into_ui_element",
            "desktop.read_ui",
            "desktop.submit_foreground",
            "desktop.ui_elements",
        ]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_approve_executes_app_open_and_click_ui_element(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-open-click-ui.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-open-click-ui.db",
        workspace_dir=tmp_path / "agent-runtime-open-click-ui",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-click-ui-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app open click UI approval should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_click_ui_element(
        target: str,
        *,
        role_filter: str = "",
        limit: int = 80,
        click_count: int = 1,
        expected_app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("click_ui", target, role_filter, limit, click_count, expected_app_name))
        return {
            "ok": True,
            "action": "desktop.click_ui_element",
            "summary": "Clicked foreground UI element: 登录",
            "data": {
                "target": target,
                "matched_label": "登录",
                "role_filter": role_filter,
                "x": 120,
                "y": 240,
                "click_count": click_count,
                "expected_app_name": expected_app_name,
            },
        }

    def fake_inspect_app(
        app_name: str,
        *,
        open_if_needed: bool = True,
        focus: bool = True,
        role_filter: str = "",
        limit: Any = 80,
    ) -> dict[str, Any]:
        calls.append(("inspect", app_name, open_if_needed, focus, role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.inspect_app",
            "summary": f"Inspected {app_name}",
            "data": {
                "app_name": app_name,
                "focus_verified": True,
                "ui_elements": {
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "data": {
                        "app_name": app_name,
                        "elements": [
                            {
                                "role": "AXButton",
                                "name": "登录",
                                "center": {"x": 120, "y": 240},
                            }
                        ],
                    },
                },
            },
        }

    def fake_active_window() -> dict[str, Any]:
        calls.append(("active_window",))
        return {
            "ok": True,
            "action": "desktop.active_window",
            "summary": "Active Chrome",
            "data": {"app_name": "Google Chrome", "frontmost_app": "Google Chrome"},
        }

    def fake_ui_elements(
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("ui_elements", role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read Chrome buttons",
            "data": {
                "app_name": app_name or "Google Chrome",
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "登录",
                        "center": {"x": 120, "y": 240},
                    }
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.active_window", fake_active_window)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.inspect_app", fake_inspect_app)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.click_ui_element", fake_click_ui_element)
    try:
        sent = ChatAPI(app_runtime).send_message("打开 Chrome 并点击登录按钮")
        waiting_task = state.get_task(sent["task_id"])
        waiting_message = session.get_assistant_message_for_task(sent["task_id"])
        waiting_run = service.get_run(sent["run_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert waiting_task is not None
        assert waiting_task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.open_and_click_ui_element"
        assert waiting_run["pending_approval"]["input_preview"] == {
            "app_name": "Google Chrome",
            "target": "登录",
            "role_filter": "button",
            "limit": 80,
            "click_count": 1,
        }
        assert calls == [("inspect", "Google Chrome", True, True, "button", 80)]

        approved = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        completed_run = service.get_run(sent["run_id"])
        completed_events = [
            event
            for event in completed_run["timeline"]
            if event.get("event") == "agent.desktop.intent_completed"
        ]

        assert approved["status"] == "completed"
        assert approved["summary"] == "已打开 Google Chrome 并点击前台控件：登录（120, 240）。"
        assert calls == [
            ("inspect", "Google Chrome", True, True, "button", 80),
            ("open", "Google Chrome"),
            ("focus", "Google Chrome"),
            ("active_window",),
            ("click_ui", "登录", "button", 80, 1, "Google Chrome"),
            ("ui_elements", "button", 80, ""),
        ]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == approved["summary"]
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == approved["summary"]
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_run["status"] == "completed"
        assert completed_run["pending_approval"] == {}
        assert completed_events[-1]["summary"] == approved["summary"]
        assert any(
            event.get("tool") == "app.open_and_click_ui_element"
            for event in completed_run["timeline"]
        )
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_approve_executes_app_open_and_type_into_ui_element(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-open-type-into-ui.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-open-type-into-ui.db",
        workspace_dir=tmp_path / "agent-runtime-open-type-into-ui",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-type-into-ui-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app open type-into UI approval should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_type_into_ui_element(
        target: str,
        text: str,
        *,
        role_filter: str = "",
        limit: int = 80,
        expected_app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("type_into_ui", target, text, role_filter, limit, expected_app_name))
        return {
            "ok": True,
            "action": "desktop.type_into_ui_element",
            "summary": "Typed into foreground UI element: Search",
            "data": {
                "target": target,
                "matched_label": "Search",
                "role_filter": role_filter,
                "character_count": len(text),
                "expected_app_name": expected_app_name,
            },
        }

    def fake_inspect_app(
        app_name: str,
        *,
        open_if_needed: bool = True,
        focus: bool = True,
        role_filter: str = "",
        limit: Any = 80,
    ) -> dict[str, Any]:
        calls.append(("inspect", app_name, open_if_needed, focus, role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.inspect_app",
            "summary": f"Inspected {app_name}",
            "data": {
                "app_name": app_name,
                "focus_verified": True,
                "ui_elements": {
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "data": {
                        "app_name": app_name,
                        "elements": [
                            {
                                "role": "AXTextField",
                                "name": "Search",
                                "center": {"x": 120, "y": 80},
                            }
                        ],
                    },
                },
            },
        }

    def fake_active_window() -> dict[str, Any]:
        calls.append(("active_window",))
        return {
            "ok": True,
            "action": "desktop.active_window",
            "summary": "Active Chrome",
            "data": {"app_name": "Google Chrome", "frontmost_app": "Google Chrome"},
        }

    def fake_ui_elements(
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("ui_elements", role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read Chrome text fields",
            "data": {
                "app_name": app_name or "Google Chrome",
                "elements": [
                    {
                        "role": "AXTextField",
                        "name": "Search",
                        "value": "github.com",
                        "center": {"x": 120, "y": 80},
                    }
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.active_window", fake_active_window)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.inspect_app", fake_inspect_app)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.type_into_ui_element",
        fake_type_into_ui_element,
    )
    try:
        sent = ChatAPI(app_runtime).send_message("打开 Chrome 并在名为 URL 的输入框输入 github.com")
        waiting_task = state.get_task(sent["task_id"])
        waiting_message = session.get_assistant_message_for_task(sent["task_id"])
        waiting_run = service.get_run(sent["run_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert waiting_task is not None
        assert waiting_task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.open_and_type_into_ui_element"
        assert waiting_run["pending_approval"]["input_preview"] == {
            "app_name": "Google Chrome",
            "target": "名为 URL 的",
            "text": "github.com",
            "role_filter": "text",
            "limit": 80,
        }
        assert calls == []

        approved = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        completed_run = service.get_run(sent["run_id"])
        completed_events = [
            event
            for event in completed_run["timeline"]
            if event.get("event") == "agent.desktop.intent_completed"
        ]

        assert approved["status"] == "completed"
        assert approved["summary"] == "已打开 Google Chrome 并在前台控件 Search 输入文字（10 个字符）。"
        assert calls == [
            ("open", "Google Chrome"),
            ("focus", "Google Chrome"),
            ("active_window",),
            ("type_into_ui", "名为 URL 的", "github.com", "text", 80, "Google Chrome"),
        ]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == approved["summary"]
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == approved["summary"]
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_run["status"] == "completed"
        assert completed_run["pending_approval"] == {}
        assert completed_events[-1]["summary"] == approved["summary"]
        assert any(
            event.get("tool") == "app.open_and_type_into_ui_element"
            for event in completed_run["timeline"]
        )
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_approve_continues_app_type_into_ui_element_then_search(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-open-type-into-search.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-open-type-into-search.db",
        workspace_dir=tmp_path / "agent-runtime-open-type-into-search",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-type-into-search-approval")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app open type-into search sequence should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_type_into_ui_element(
        target: str,
        text: str,
        *,
        role_filter: str = "",
        limit: int = 80,
        expected_app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("type_into_ui", target, text, role_filter, limit, expected_app_name))
        return {
            "ok": True,
            "action": "desktop.type_into_ui_element",
            "summary": "Typed into foreground UI element: Search",
            "data": {
                "target": target,
                "matched_label": "Search",
                "role_filter": role_filter,
                "character_count": len(text),
                "expected_app_name": expected_app_name,
            },
        }

    def fake_desktop_hotkey(key: str, *, modifiers: list[str] | None = None) -> dict[str, Any]:
        calls.append(("hotkey", key, list(modifiers or [])))
        return {
            "ok": True,
            "action": "desktop.hotkey",
            "summary": "Sent hotkey",
            "data": {"key": key, "modifiers": list(modifiers or [])},
        }

    def fake_inspect_app(
        app_name: str,
        *,
        open_if_needed: bool = True,
        focus: bool = True,
        role_filter: str = "",
        limit: Any = 80,
    ) -> dict[str, Any]:
        calls.append(("inspect", app_name, open_if_needed, focus, role_filter, limit))
        return {
            "ok": True,
            "action": "desktop.inspect_app",
            "summary": f"Inspected {app_name}",
            "data": {
                "app_name": app_name,
                "focus_verified": True,
                "ui_elements": {
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "data": {
                        "app_name": app_name,
                        "elements": [
                            {
                                "role": "AXTextField",
                                "name": "Search",
                                "center": {"x": 120, "y": 80},
                            }
                        ],
                    },
                },
            },
        }

    def fake_active_window() -> dict[str, Any]:
        calls.append(("active_window",))
        return {
            "ok": True,
            "action": "desktop.active_window",
            "summary": "Active Chrome",
            "data": {"app_name": "Google Chrome", "frontmost_app": "Google Chrome"},
        }

    def fake_ui_elements(
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("ui_elements", role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read Chrome text fields",
            "data": {
                "app_name": app_name or "Google Chrome",
                "elements": [
                    {
                        "role": "AXTextField",
                        "name": "Search",
                        "value": "yachiyo",
                        "center": {"x": 120, "y": 80},
                    }
                ],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.active_window", fake_active_window)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.inspect_app", fake_inspect_app)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.type_into_ui_element",
        fake_type_into_ui_element,
    )
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_hotkey", fake_desktop_hotkey)
    try:
        sent = ChatAPI(app_runtime).send_message("打开 Chrome 并在搜索框输入 yachiyo 并搜索")
        waiting_run = service.get_run(sent["run_id"])

        assert sent["ok"] is True
        assert sent["status"] == "waiting_approval"
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == "app.open_and_type_into_ui_element"
        assert waiting_run["pending_approval"]["input_preview"] == {
            "app_name": "Google Chrome",
            "target": "搜索框",
            "text": "yachiyo",
            "role_filter": "text",
            "limit": 80,
        }
        assert calls == [("inspect", "Google Chrome", True, True, "text", 80)]

        after_first = await yachiyo.approve_task(sent["task_id"], None, request)
        first_waiting_run = service.get_run(sent["run_id"])

        assert after_first["status"] == "waiting_approval"
        assert first_waiting_run["status"] == "approval_required"
        assert first_waiting_run["pending_approval"]["tool"] == "desktop.hotkey"
        assert first_waiting_run["pending_approval"]["input_preview"] == {
            "key": "return",
            "modifiers": [],
        }
        assert calls == [
            ("inspect", "Google Chrome", True, True, "text", 80),
            ("open", "Google Chrome"),
            ("focus", "Google Chrome"),
            ("active_window",),
            ("type_into_ui", "搜索框", "yachiyo", "text", 80, "Google Chrome"),
        ]

        after_second = await yachiyo.approve_task(sent["task_id"], None, request)
        completed_task = state.get_task(sent["task_id"])
        completed_message = session.get_assistant_message_for_task(sent["task_id"])
        completed_run = service.get_run(sent["run_id"])

        assert after_second["status"] == "completed"
        assert (
            after_second["summary"]
            == "已打开 Google Chrome 并在前台控件 Search 输入文字（7 个字符）。 已发送快捷键：return。"
        )
        assert calls == [
            ("inspect", "Google Chrome", True, True, "text", 80),
            ("open", "Google Chrome"),
            ("focus", "Google Chrome"),
            ("active_window",),
            ("type_into_ui", "搜索框", "yachiyo", "text", 80, "Google Chrome"),
            ("hotkey", "return", []),
            ("ui_elements", "text", 80, ""),
        ]
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == after_second["summary"]
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == after_second["summary"]
        assert completed_run["status"] == "completed"
        assert completed_run["pending_approval"] == {}
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_main_daily_desktop_intent_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route.db",
        workspace_dir=tmp_path / "agent-runtime-route",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-daily-desktop")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    open_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily desktop public task should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        open_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.open",
            "summary": f"Opened {app_name}",
            "data": {
                "app_name": app_name,
                "launch_verified": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开 Word",
                conversation_id="chat-main-daily-desktop",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-daily-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        messages = store.load_messages("chat-main-daily-desktop", limit=10)
        user = next(message for message in messages if message.role == "user")
        assistant = next(message for message in messages if message.role == "assistant")
        user_metadata = json.loads(user.metadata_json or "{}")

        assert open_calls == ["Microsoft Word"]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开 Microsoft Word。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.open"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["app_name"] == "Microsoft Word"
        assert timeline["task_id"] == started["task_id"]
        assert timeline["status"] == "completed"
        assert timeline["tool_calls"][-1]["tool_name"] == "app.open"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["launch_verified"] is True
        event_types = [event["event_type"] for event in events["events"]]
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert user.task_id == started["task_id"]
        assert user_metadata["client_message_id"] == "route-main-daily-1"
        assert user_metadata["daily_desktop_intent"] is True
        assert user_metadata["daily_desktop_source"] == "daily_desktop_intent"
        assert user_metadata["daily_desktop_planning_reason"] == "clear_daily_desktop_intent"
        assert user_metadata["daily_desktop_tool"] == "app.open"
        assert user_metadata["daily_desktop_tools"] == ["app.open"]
        assert assistant.task_id == started["task_id"]
        assert assistant.content == "已打开 Microsoft Word。"
        assert assistant.status == MessageStatus.COMPLETED
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_app_find_sequence_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-app-find.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-app-find.db",
        workspace_dir=tmp_path / "agent-runtime-route-app-find",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-app-find")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app find public task should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_shortcut(action: str) -> dict[str, Any]:
        calls.append(("shortcut", action))
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut",
            "data": {"shortcut_action": action},
        }

    def fake_safe_type_text(text: str) -> dict[str, Any]:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed text",
            "data": {"text": text, "character_count": len(text), "explicit_user_text": True},
        }

    def fake_list_apps(query: str = "", limit: Any = 200) -> dict[str, Any]:
        calls.append(("list_apps", query, limit))
        return {
            "ok": True,
            "action": "desktop.list_apps",
            "summary": "Found Notes",
            "data": {"apps": [{"name": "Notes"}], "query": query, "limit": limit},
        }

    def fake_search_submit() -> dict[str, Any]:
        calls.append(("search_submit",))
        return {
            "ok": True,
            "action": "desktop.search_submit",
            "summary": "Submitted foreground search",
            "data": {"submitted": True},
        }

    def fake_ui_elements(
        role_filter: str = "",
        limit: Any = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        calls.append(("ui_elements", role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Read Notes UI",
            "data": {
                "app_name": app_name or "Notes",
                "elements": [{"role": "AXTextField", "name": "Search", "value": "hello"}],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.list_apps", fake_list_apps)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_shortcut", fake_safe_shortcut)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_type_text", fake_safe_type_text)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_search_submit", fake_search_submit)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开 Notes，然后搜索 hello",
                conversation_id="chat-main-app-find",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-app-find-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        assistant = next(
            message
            for message in store.load_messages("chat-main-app-find", limit=10)
            if message.role == "assistant"
        )
        event_types = [event["event_type"] for event in events["events"]]

        assert calls == [
            ("list_apps", "Notes", 20),
            ("open", "Notes"),
            ("focus", "Notes"),
            ("shortcut", "find"),
            ("type", "hello"),
            ("search_submit",),
            ("ui_elements", "", 80, "Notes"),
        ]
        assert started["status"] == "completed"
        assert (
            started["summary"]
            == "已打开 Notes 并打开查找。 已向前台输入文字（5 个字符）。 已提交前台搜索。"
        )
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert [tool_call["tool_name"] for tool_call in started["tool_calls"][-3:]] == [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ]
        assert [tool_call["tool_name"] for tool_call in timeline["tool_calls"][-3:]] == [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ]
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.task.workspace_item.updated" in event_types
        assert "agent.task.todo.updated" in event_types
        assert "agent.task.checkpoint.updated" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        todo_events = [
            event for event in events["events"] if event["event_type"] == "agent.task.todo.updated"
        ]
        assert any(event["payload"]["status"] == "completed" for event in todo_events)
        assert all(event["payload"]["core_id"].startswith("task-core-") for event in todo_events)
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_named_site_open_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-browser-open.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-browser-open.db",
        workspace_dir=tmp_path / "agent-runtime-route-browser-open",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-browser-open")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    open_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("named site public task should not call model")
        ),
    )

    def fake_open_url(url: str) -> dict[str, Any]:
        open_calls.append(url)
        return {
            "ok": True,
            "action": "browser.open_url",
            "summary": f"Opened {url}",
            "data": {
                "url": url,
                "browser": "Google Chrome",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开 ChatGPT",
                conversation_id="chat-main-browser-open",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-browser-open-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-browser-open", limit=10)
            if message.role == "assistant"
        )

        assert open_calls == ["https://chatgpt.com"]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开网页：https://chatgpt.com。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "browser.open_url"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["url"] == "https://chatgpt.com"
        assert timeline["tool_calls"][-1]["tool_name"] == "browser.open_url"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["browser"] == "Google Chrome"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_browser_search_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-browser-search.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-browser-search.db",
        workspace_dir=tmp_path / "agent-runtime-route-browser-search",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-browser-search")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    open_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser search public task should not call model")
        ),
    )

    def fake_open_url(url: str) -> dict[str, Any]:
        open_calls.append(url)
        return {
            "ok": True,
            "action": "browser.open_url",
            "summary": f"Opened {url}",
            "data": {
                "url": url,
                "browser": "Google Chrome",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.open_url", fake_open_url)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="搜一下 Yachiyo desktop agent",
                conversation_id="chat-main-browser-search",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-browser-search-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-browser-search", limit=10)
            if message.role == "assistant"
        )
        search_url = "https://www.google.com/search?q=Yachiyo+desktop+agent"

        assert open_calls == [search_url]
        assert started["status"] == "completed"
        assert started["summary"] == f"已打开网页：{search_url}。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "browser.open_url"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["url"] == search_url
        assert timeline["tool_calls"][-1]["tool_name"] == "browser.open_url"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["url"] == search_url
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_system_volume_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-system-volume.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-system-volume.db",
        workspace_dir=tmp_path / "agent-runtime-route-system-volume",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-system-volume")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    volume_calls: list[tuple[str, Any, Any]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("system volume public task should not call model")
        ),
    )

    def fake_system_volume(action: str, *, level: Any = None, step: Any = None) -> dict[str, Any]:
        volume_calls.append((action, level, step))
        return {
            "ok": True,
            "action": "system.volume",
            "summary": "System volume increased from 40% to 50%",
            "data": {
                "requested_action": action,
                "old_level": 40,
                "level": 50,
                "muted": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.system_volume", fake_system_volume)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="调大音量",
                conversation_id="chat-main-system-volume",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-system-volume-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-system-volume", limit=10)
            if message.role == "assistant"
        )

        assert volume_calls == [("up", None, None)]
        assert started["status"] == "completed"
        assert started["summary"] == "已把系统音量从 40% 调高到 50%。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "system.volume"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["action"] == "up"
        assert timeline["tool_calls"][-1]["tool_name"] == "system.volume"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["level"] == 50
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_clipboard_write_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-clipboard-write.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-clipboard-write.db",
        workspace_dir=tmp_path / "agent-runtime-route-clipboard-write",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-clipboard-write")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    clipboard_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("clipboard public task should not call model")
        ),
    )

    def fake_clipboard_write(text: str) -> dict[str, Any]:
        clipboard_calls.append(text)
        return {
            "ok": True,
            "action": "clipboard.write",
            "summary": "Copied 11 characters to clipboard",
            "data": {"text_length": len(text)},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.clipboard_write", fake_clipboard_write)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="copy hello world to clipboard",
                conversation_id="chat-main-clipboard-write",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-clipboard-write-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-clipboard-write", limit=10)
            if message.role == "assistant"
        )

        assert clipboard_calls == ["hello world"]
        assert started["status"] == "completed"
        assert started["summary"] == "已复制 11 个字符到剪贴板。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "clipboard.write"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["text"] == "hello world"
        assert timeline["tool_calls"][-1]["tool_name"] == "clipboard.write"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["text_length"] == 11
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_action", "expected_summary"),
    [
        (
            "播放一下",
            "play",
            "已继续播放 Apple Music。当前：超时空辉夜姬 - Yachiyo。",
        ),
        (
            "放一下",
            "play",
            "已继续播放 Apple Music。当前：超时空辉夜姬 - Yachiyo。",
        ),
        (
            "下一首",
            "next",
            "已切到下一首 Apple Music。当前：超时空辉夜姬 - Yachiyo。",
        ),
    ],
)
async def test_yachiyo_task_route_executes_media_control_daily_desktop_intent_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    expected_action: str,
    expected_summary: str,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-media-control.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-media-control.db",
        workspace_dir=tmp_path / "agent-runtime-route-media-control",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-media-control")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    control_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("media control daily desktop public task should not call model")
        ),
    )

    def fake_apple_music_control(action: str) -> dict[str, Any]:
        control_calls.append(action)
        return {
            "ok": True,
            "action": "media.apple_music_control",
            "summary": f"Apple Music {action} executed",
            "data": {
                "control": action,
                "player_state": "playing",
                "track": "超时空辉夜姬",
                "artist": "Yachiyo",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_control",
        fake_apple_music_control,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt=prompt,
                conversation_id="chat-main-media-control",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-media-control-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-media-control", limit=10)
            if message.role == "assistant"
        )

        assert control_calls == [expected_action]
        assert started["status"] == "completed"
        assert started["summary"] == expected_summary
        assert started["tool_calls"][-1]["tool_name"] == "media.apple_music_control"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["action"] == expected_action
        assert timeline["tool_calls"][-1]["tool_name"] == "media.apple_music_control"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["track"] == "超时空辉夜姬"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_media_play_daily_desktop_intent_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-media-play.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-media-play.db",
        workspace_dir=tmp_path / "agent-runtime-route-media-play",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-media-play")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    play_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("media play daily desktop public task should not call model")
        ),
    )

    def fake_apple_music_play(query: str) -> dict[str, Any]:
        play_calls.append(query)
        return {
            "ok": True,
            "action": "media.apple_music_play",
            "summary": f"Apple Music playing {query}",
            "data": {
                "query": query,
                "track": query,
                "artist": "Yachiyo",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_play",
        fake_apple_music_play,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="播放超时空辉夜姬",
                conversation_id="chat-main-media-play",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-media-play-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-media-play", limit=10)
            if message.role == "assistant"
        )

        assert play_calls == ["超时空辉夜姬"]
        assert started["status"] == "completed"
        assert started["summary"] == "已在 Apple Music 播放：超时空辉夜姬 - Yachiyo。"
        assert started["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["query"] == "超时空辉夜姬"
        assert timeline["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["track"] == "超时空辉夜姬"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_surfaces_music_permission_recovery_when_fallback_opens_music(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-media-permission.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-media-permission.db",
        workspace_dir=tmp_path / "agent-runtime-route-media-permission",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-media-permission")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    play_calls: list[str] = []
    recovery_actions = [
        {
            "label": "打开 Apple Music",
            "tool": "app.open",
            "input": {"app_name": "Music"},
            "permission_target": "music_app",
            "risk_level": "low",
        },
        {
            "label": "打开自动化权限",
            "tool": "system.settings_open",
            "input": {"target": "自动化权限"},
            "permission_target": "automation",
            "risk_level": "low",
        },
    ]
    expected_recovery_actions = [
        {
            **action,
            "recovery_retry_input": {"query": "超时空辉夜姬"},
            "recovery_retry_prompt": "播放超时空辉夜姬",
            "recovery_retry_tool": "media.apple_music_play",
            "retry_input": {"query": "超时空辉夜姬"},
            "retry_prompt": "播放超时空辉夜姬",
            "retry_tool": "media.apple_music_play",
        }
        for action in recovery_actions
    ]
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("music permission recovery public task should not call model")
        ),
    )

    def fake_apple_music_play(query: str) -> dict[str, Any]:
        play_calls.append(query)
        return {
            "ok": False,
            "action": "media.apple_music_play",
            "summary": "media.apple_music_play failed",
            "error": "Not authorized to send Apple events to Music.",
            "data": {"query": query, "status": "error"},
            "permission_error": True,
            "permission_targets": ["music_app", "automation"],
            "missing_permissions": ["music_app", "automation"],
            "recovery_hints": [
                "Open Music.app once, confirm the track exists in the local library.",
                "Grant Automation permission in System Settings.",
            ],
            "recovery_actions": recovery_actions,
            "fallback_used": True,
            "fallback_result": {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": "Music"},
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.apple_music_play",
        fake_apple_music_play,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="播放超时空辉夜姬",
                conversation_id="chat-main-media-permission",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-media-permission-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        messages = store.load_messages("chat-main-media-permission", limit=10)
        assistant = next(message for message in messages if message.role == "assistant")
        event_types = [event["event_type"] for event in events["events"]]
        recovery_event = next(
            event
            for event in events["events"]
            if event["event_type"] == "agent.desktop.permission_recovery"
        )
        tool_call = started["tool_calls"][-1]

        assert play_calls == ["超时空辉夜姬"]
        assert started["status"] == "completed"
        assert "桌面操作未完成：Not authorized to send Apple events to Music." in started["summary"]
        assert "缺少权限：music_app, automation" in started["summary"]
        assert "打开 Apple Music" in started["summary"]
        assert "打开自动化权限" in started["summary"]
        assert "没能直接播放" not in started["summary"]
        assert tool_call["tool_name"] == "media.apple_music_play"
        assert tool_call["status"] == "failed"
        assert tool_call["output_preview"]["permission_error"] is True
        assert tool_call["output_preview"]["permission_targets"] == ["music_app", "automation"]
        assert tool_call["output_preview"]["recovery_actions"] == expected_recovery_actions
        assert timeline["tool_calls"][-1]["tool_name"] == "media.apple_music_play"
        assert timeline["tool_calls"][-1]["status"] == "failed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.permission_recovery" in event_types
        assert recovery_event["payload"]["permission_targets"] == ["music_app", "automation"]
        assert recovery_event["payload"]["affected_tools"] == ["media.apple_music_play"]
        assert recovery_event["payload"]["recovery_actions"] == expected_recovery_actions
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_named_app_hide_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-app-hide.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-app-hide.db",
        workspace_dir=tmp_path / "agent-runtime-route-app-hide",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-app-hide")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    hide_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("named app hide public task should not call model")
        ),
    )

    def fake_app_hide(app_name: str) -> dict[str, Any]:
        hide_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.hide",
            "summary": f"Hid {app_name}",
            "data": {"app_name": app_name, "hide_status": "hidden"},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_hide", fake_app_hide)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="隐藏 Slack",
                conversation_id="chat-main-app-hide",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-app-hide-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-app-hide", limit=10)
            if message.role == "assistant"
        )

        assert hide_calls == ["Slack"]
        assert started["status"] == "completed"
        assert started["summary"] == "已隐藏 Slack。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.hide"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["app_name"] == "Slack"
        assert timeline["tool_calls"][-1]["tool_name"] == "app.hide"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["hide_status"] == "hidden"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "tool_name", "patched_tool", "action", "summary", "data_key", "data_value"),
    [
        (
            "切换到 Slack",
            "app.focus",
            "apps.shell.agent.tools.desktop.app_focus",
            "app.focus",
            "已切换到 Slack。",
            "focus_status",
            "focused",
        ),
        (
            "显示 Slack",
            "app.show",
            "apps.shell.agent.tools.desktop.app_show",
            "app.show",
            "已显示 Slack。",
            "show_status",
            "shown",
        ),
        (
            "最小化 Slack",
            "app.minimize",
            "apps.shell.agent.tools.desktop.app_minimize",
            "app.minimize",
            "已最小化 Slack。",
            "minimize_status",
            "minimized",
        ),
    ],
)
async def test_yachiyo_task_route_executes_named_app_control_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    tool_name: str,
    patched_tool: str,
    action: str,
    summary: str,
    data_key: str,
    data_value: str,
) -> None:
    store = ChatStore(db_path=str(tmp_path / f"chat-route-{tool_name}.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / f"agent-runtime-route-{tool_name}.db",
        workspace_dir=tmp_path / f"agent-runtime-route-{tool_name}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id=f"chat-main-{tool_name}")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    control_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("named app control public task should not call model")
        ),
    )

    def fake_named_app_control(app_name: str) -> dict[str, Any]:
        control_calls.append(app_name)
        return {
            "ok": True,
            "action": action,
            "summary": f"{action} {app_name}",
            "data": {"app_name": app_name, data_key: data_value},
        }

    monkeypatch.setattr(patched_tool, fake_named_app_control)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt=prompt,
                conversation_id=f"chat-main-{tool_name}",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": f"route-main-{tool_name}-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages(f"chat-main-{tool_name}", limit=10)
            if message.role == "assistant"
        )

        assert control_calls == ["Slack"]
        assert started["status"] == "completed"
        assert started["summary"] == summary
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == tool_name
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["app_name"] == "Slack"
        assert timeline["tool_calls"][-1]["tool_name"] == tool_name
        assert timeline["tool_calls"][-1]["output_preview"]["data"][data_key] == data_value
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_named_window_focus_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-window-focus.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-window-focus.db",
        workspace_dir=tmp_path / "agent-runtime-route-window-focus",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-window-focus")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    focus_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("named window focus public task should not call model")
        ),
    )

    def fake_app_focus_window(app_name: str, title_contains: str) -> dict[str, Any]:
        focus_calls.append((app_name, title_contains))
        return {
            "ok": True,
            "action": "app.focus_window",
            "summary": f"Focused {app_name} window {title_contains}",
            "data": {
                "app_name": app_name,
                "title_contains": title_contains,
                "matched_window_title": "general - Slack",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.app_focus_window",
        fake_app_focus_window,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="切到 Slack 的 general 窗口",
                conversation_id="chat-main-window-focus",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-window-focus-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-window-focus", limit=10)
            if message.role == "assistant"
        )

        assert focus_calls == [("Slack", "general")]
        assert started["status"] == "completed"
        assert started["summary"] == "已切换到 Slack 的 general 窗口。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.focus_window"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["app_name"] == "Slack"
        assert started["tool_calls"][-1]["input_preview"]["title_contains"] == "general"
        assert timeline["tool_calls"][-1]["tool_name"] == "app.focus_window"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["matched_window_title"] == "general - Slack"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_safe_type_text_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-safe-type.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-safe-type.db",
        workspace_dir=tmp_path / "agent-runtime-route-safe-type",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-safe-type")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    typed_texts: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("safe foreground input public task should not call model")
        ),
    )

    def fake_safe_type_text(text: str) -> dict[str, Any]:
        typed_texts.append(text)
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_type_text",
        fake_safe_type_text,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="输入 你好八千代",
                conversation_id="chat-main-safe-type",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-safe-type-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-safe-type", limit=10)
            if message.role == "assistant"
        )

        assert typed_texts == ["你好八千代"]
        assert started["status"] == "completed"
        assert started["summary"] == "已向前台输入文字（5 个字符）。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.safe_type_text"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["text"] == "你好八千代"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.safe_type_text"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["explicit_user_text"] is True
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_app_open_and_safe_type_text_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-open-safe-type.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-open-safe-type.db",
        workspace_dir=tmp_path / "agent-runtime-route-open-safe-type",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-safe-type")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app foreground public task should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_type_text(text: str) -> dict[str, Any]:
        calls.append(("type", text))
        return {
            "ok": True,
            "action": "desktop.safe_type_text",
            "summary": "Typed user-provided text into the foreground app",
            "data": {"character_count": len(text), "explicit_user_text": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_type_text",
        fake_safe_type_text,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开 Notes 并输入 hello yachiyo",
                conversation_id="chat-main-open-safe-type",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-open-safe-type-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-open-safe-type", limit=10)
            if message.role == "assistant"
        )

        assert calls == [("open", "Notes"), ("focus", "Notes"), ("type", "hello yachiyo")]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开 Notes 并输入文字（13 个字符）。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.open_and_safe_type_text"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["app_name"] == "Notes"
        assert input_preview["text"] == "hello yachiyo"
        assert input_preview["capability_id"] == "desktop.ui_operation"
        assert input_preview["intent_kind"] == "desktop_operation"
        assert input_preview["plan_id"].startswith("runtime-plan-")
        assert timeline["tool_calls"][-1]["tool_name"] == "app.open_and_safe_type_text"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["foreground_action"] == "safe_type_text"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_app_open_and_safe_key_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-open-safe-key.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-open-safe-key.db",
        workspace_dir=tmp_path / "agent-runtime-route-open-safe-key",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-safe-key")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app safe key public task should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict[str, Any]:
        calls.append(("key", action))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": "Pressed safe foreground key: Tab",
            "data": {
                "key_action": action,
                "key_label": "Tab",
                "key_code": 48,
                "repeat_count": repeat_count,
                "explicit_user_key": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_key", fake_safe_key)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开 Chrome 并按 Tab",
                conversation_id="chat-main-open-safe-key",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-open-safe-key-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-open-safe-key", limit=10)
            if message.role == "assistant"
        )

        assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("key", "tab")]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开 Google Chrome 并按Tab。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.open_and_safe_key"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["app_name"] == "Google Chrome"
        assert input_preview["action"] == "tab"
        assert input_preview["repeat_count"] == 1
        assert input_preview["capability_id"] == "desktop.ui_operation"
        assert input_preview["intent_kind"] == "desktop_operation"
        assert input_preview["plan_id"].startswith("runtime-plan-")
        assert timeline["tool_calls"][-1]["tool_name"] == "app.open_and_safe_key"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["foreground_action"] == "safe_key"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_app_open_and_safe_scroll_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-open-safe-scroll.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-open-safe-scroll.db",
        workspace_dir=tmp_path / "agent-runtime-route-open-safe-scroll",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-safe-scroll")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app safe scroll public task should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_scroll(direction: str, *, pages: int = 1) -> dict[str, Any]:
        calls.append(("scroll", direction))
        return {
            "ok": True,
            "action": "desktop.safe_scroll",
            "summary": "Scrolled foreground app",
            "data": {
                "direction": direction,
                "pages": pages,
                "explicit_user_scroll": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_scroll", fake_safe_scroll)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开 Chrome 并向下滚动两页",
                conversation_id="chat-main-open-safe-scroll",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-open-safe-scroll-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-open-safe-scroll", limit=10)
            if message.role == "assistant"
        )

        assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("scroll", "down")]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开 Google Chrome 并向下滚动前台界面（2 页）。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.open_and_safe_scroll"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["app_name"] == "Google Chrome"
        assert input_preview["direction"] == "down"
        assert input_preview["pages"] == 2
        assert input_preview["capability_id"] == "desktop.ui_operation"
        assert input_preview["intent_kind"] == "desktop_operation"
        assert input_preview["plan_id"].startswith("runtime-plan-")
        assert timeline["tool_calls"][-1]["tool_name"] == "app.open_and_safe_scroll"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["foreground_action"] == "safe_scroll"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_app_open_and_safe_click_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-open-safe-click.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-open-safe-click.db",
        workspace_dir=tmp_path / "agent-runtime-route-open-safe-click",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-safe-click")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app safe click public task should not call model")
        ),
    )

    def fake_app_open(app_name: str) -> dict[str, Any]:
        calls.append(("open", app_name))
        return {"ok": True, "action": "app.open", "data": {"app_name": app_name}}

    def fake_app_focus(app_name: str) -> dict[str, Any]:
        calls.append(("focus", app_name))
        return {"ok": True, "action": "app.focus", "data": {"app_name": app_name}}

    def fake_safe_click(x: Any, y: Any) -> dict[str, Any]:
        calls.append(("click", x, y))
        return {
            "ok": True,
            "action": "desktop.safe_click",
            "summary": "Clicked foreground coordinates",
            "data": {
                "x": int(x),
                "y": int(y),
                "click_count": 1,
                "explicit_user_coordinates": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_focus", fake_app_focus)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_click", fake_safe_click)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开 Chrome 并点击 120, 240",
                conversation_id="chat-main-open-safe-click",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-open-safe-click-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-open-safe-click", limit=10)
            if message.role == "assistant"
        )

        assert calls == [("open", "Google Chrome"), ("focus", "Google Chrome"), ("click", 120, 240)]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开 Google Chrome 并点击前台位置：120, 240。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.open_and_safe_click"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["app_name"] == "Google Chrome"
        assert input_preview["x"] == 120
        assert input_preview["y"] == 240
        assert input_preview["capability_id"] == "desktop.ui_operation"
        assert input_preview["intent_kind"] == "desktop_operation"
        assert input_preview["plan_id"].startswith("runtime-plan-")
        assert timeline["tool_calls"][-1]["tool_name"] == "app.open_and_safe_click"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["foreground_action"] == "safe_click"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_safe_click_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-safe-click.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-safe-click.db",
        workspace_dir=tmp_path / "agent-runtime-route-safe-click",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-safe-click")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    clicked: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("safe foreground click public task should not call model")
        ),
    )

    def fake_safe_click(x: int, y: int) -> dict[str, Any]:
        clicked.append((x, y))
        return {
            "ok": True,
            "action": "desktop.safe_click",
            "summary": "Clicked explicit foreground coordinate at (120, 240)",
            "data": {
                "x": x,
                "y": y,
                "click_count": 1,
                "explicit_user_coordinates": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_click", fake_safe_click)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="点击 120, 240",
                conversation_id="chat-main-safe-click",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-safe-click-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-safe-click", limit=10)
            if message.role == "assistant"
        )

        assert clicked == [(120, 240)]
        assert started["status"] == "completed"
        assert started["summary"] == "已点击前台位置：120, 240。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.safe_click"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["x"] == 120
        assert input_preview["y"] == 240
        assert input_preview["capability_id"] == "desktop.ui_operation"
        assert input_preview["intent_kind"] == "desktop_operation"
        assert input_preview["plan_id"].startswith("runtime-plan-")
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.safe_click"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["explicit_user_coordinates"] is True
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_safe_scroll_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-safe-scroll.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-safe-scroll.db",
        workspace_dir=tmp_path / "agent-runtime-route-safe-scroll",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-safe-scroll")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    scrolls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("safe foreground scroll public task should not call model")
        ),
    )

    def fake_safe_scroll(direction: str, *, pages: int = 1) -> dict[str, Any]:
        scrolls.append((direction, pages))
        return {
            "ok": True,
            "action": "desktop.safe_scroll",
            "summary": "Scrolled foreground desktop down 2 pages",
            "data": {
                "direction": direction,
                "pages": pages,
                "key_code": 121,
                "explicit_user_scroll": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_scroll", fake_safe_scroll)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="向下滚动两页",
                conversation_id="chat-main-safe-scroll",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-safe-scroll-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-safe-scroll", limit=10)
            if message.role == "assistant"
        )

        assert scrolls == [("down", 2)]
        assert started["status"] == "completed"
        assert started["summary"] == "已向下滚动前台界面（2 页）。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.safe_scroll"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["direction"] == "down"
        assert input_preview["pages"] == 2
        assert input_preview["capability_id"] == "desktop.ui_operation"
        assert input_preview["intent_kind"] == "desktop_operation"
        assert input_preview["plan_id"].startswith("runtime-plan-")
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.safe_scroll"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["explicit_user_scroll"] is True
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_screen_observe_then_safe_click_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-screen-click.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-screen-click.db",
        workspace_dir=tmp_path / "agent-runtime-route-screen-click",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-screen-click")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("screen observe then click daily task should not call model")
        ),
    )

    def fake_screen_capture(target_path: Path) -> dict[str, Any]:
        calls.append(("capture", str(target_path)))
        return {
            "ok": True,
            "action": "screen.capture",
            "summary": "已截取当前屏幕。",
            "data": {
                "path": str(target_path),
                "mime_type": "image/png",
                "size_bytes": 10,
                "width": 100,
                "height": 80,
            },
        }

    def fake_safe_click(x: int, y: int) -> dict[str, Any]:
        calls.append(("click", x, y))
        return {
            "ok": True,
            "action": "desktop.safe_click",
            "summary": "Clicked explicit foreground coordinate at (120, 240)",
            "data": {
                "x": x,
                "y": y,
                "click_count": 1,
                "explicit_user_coordinates": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.screen_capture", fake_screen_capture)
    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_safe_click", fake_safe_click)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="看一下屏幕，然后点击 120 240",
                conversation_id="chat-main-screen-click",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-screen-click-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-screen-click", limit=10)
            if message.role == "assistant"
        )

        assert calls[0][0] == "capture"
        assert calls[1] == ("click", 120, 240)
        assert started["status"] == "completed"
        assert started["summary"] == "已截取当前屏幕。 已点击前台位置：120, 240。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert [call["tool_name"] for call in started["tool_calls"][-2:]] == [
            "screen.capture",
            "desktop.safe_click",
        ]
        assert started["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert [call["tool_name"] for call in timeline["tool_calls"][-2:]] == [
            "screen.capture",
            "desktop.safe_click",
        ]
        assert timeline["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_surfaces_safe_click_accessibility_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-safe-click-permission.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-safe-click-permission.db",
        workspace_dir=tmp_path / "agent-runtime-route-safe-click-permission",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-safe-click-permission")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    osascript_calls: list[tuple[Any, Any]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("safe click accessibility recovery should not call model")
        ),
    )
    monkeypatch.setattr("apps.shell.agent.tools.desktop._desktop_platform", lambda: "macos")

    def fake_run_osascript(script: str, args: list[str] | None = None) -> dict[str, Any]:
        osascript_calls.append((script, args))
        return {
            "ok": False,
            "summary": "osascript failed",
            "error": "Not authorized to send Apple events to System Events. Accessibility permission denied.",
            "permission_error": True,
            "fallback_used": False,
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop._run_osascript", fake_run_osascript)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="点击 120, 240",
                conversation_id="chat-main-safe-click-permission",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-safe-click-permission-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        messages = store.load_messages("chat-main-safe-click-permission", limit=10)
        assistant = next(message for message in messages if message.role == "assistant")
        event_types = [event["event_type"] for event in events["events"]]
        recovery_event = next(
            event
            for event in events["events"]
            if event["event_type"] == "agent.desktop.permission_recovery"
        )
        tool_call = started["tool_calls"][-1]

        assert osascript_calls
        assert osascript_calls[0][1] == ["120", "240", "1"]
        assert started["status"] == "completed"
        assert "桌面操作未完成：Not authorized to send Apple events to System Events." in started["summary"]
        assert "缺少权限：accessibility" in started["summary"]
        assert "可直接打开：打开辅助功能权限。" in started["summary"]
        assert started["needs_user_action"] is True
        assert started["pending_approvals"] == []
        assert tool_call["tool_name"] == "desktop.safe_click"
        assert tool_call["status"] == "failed"
        assert tool_call["input_preview"]["x"] == 120
        assert tool_call["input_preview"]["y"] == 240
        assert tool_call["input_preview"]["capability_id"] == "desktop.ui_operation"
        assert tool_call["input_preview"]["intent_kind"] == "desktop_operation"
        assert tool_call["output_preview"]["permission_error"] is True
        assert tool_call["output_preview"]["permission_targets"] == ["accessibility"]
        assert tool_call["output_preview"]["recovery_actions"] == [
            {
                "label": "打开辅助功能权限",
                "tool": "system.settings_open",
                "input": {"target": "辅助功能权限"},
                "permission_target": "accessibility",
                "recovery_retry_input": {"x": 120, "y": 240},
                "recovery_retry_prompt": "点击 120, 240",
                "recovery_retry_tool": "desktop.safe_click",
                "risk_level": "low",
                "retry_input": {"x": 120, "y": 240},
                "retry_prompt": "点击 120, 240",
                "retry_tool": "desktop.safe_click",
            }
        ]
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.safe_click"
        assert timeline["tool_calls"][-1]["status"] == "failed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.permission_recovery" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert recovery_event["payload"]["permission_targets"] == ["accessibility"]
        assert recovery_event["payload"]["affected_tools"] == ["desktop.safe_click"]
        assert recovery_event["payload"]["recovery_actions"] == tool_call["output_preview"]["recovery_actions"]
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_safe_shortcut_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-safe-shortcut.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-safe-shortcut.db",
        workspace_dir=tmp_path / "agent-runtime-route-safe-shortcut",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-safe-shortcut")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    shortcut_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("safe shortcut public task should not call model")
        ),
    )

    def fake_safe_shortcut(action: str) -> dict[str, Any]:
        shortcut_calls.append(action)
        return {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "summary": "Executed safe shortcut: copy",
            "data": {
                "shortcut_action": action,
                "key": "c",
                "modifiers": ["command"],
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_shortcut",
        fake_safe_shortcut,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="复制选中内容",
                conversation_id="chat-main-safe-shortcut",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-safe-shortcut-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-safe-shortcut", limit=10)
            if message.role == "assistant"
        )

        assert shortcut_calls == ["copy"]
        assert started["status"] == "completed"
        assert started["summary"] == "已复制选中内容。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.safe_shortcut"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["action"] == "copy"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.safe_shortcut"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["shortcut_action"] == "copy"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_safe_key_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-safe-key.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-safe-key.db",
        workspace_dir=tmp_path / "agent-runtime-route-safe-key",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-safe-key")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    key_calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("safe key public task should not call model")
        ),
    )

    def fake_safe_key(action: str, *, repeat_count: int = 1) -> dict[str, Any]:
        key_calls.append((action, repeat_count))
        return {
            "ok": True,
            "action": "desktop.safe_key",
            "summary": "Pressed safe foreground key: Down Arrow x3",
            "data": {
                "key_action": action,
                "key_label": "Down Arrow",
                "key_code": 125,
                "repeat_count": repeat_count,
                "explicit_user_key": True,
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_safe_key",
        fake_safe_key,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="按三次下箭头",
                conversation_id="chat-main-safe-key",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-safe-key-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-safe-key", limit=10)
            if message.role == "assistant"
        )

        assert key_calls == [("arrow_down", 3)]
        assert started["status"] == "completed"
        assert started["summary"] == "已按下箭头（3 次）。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.safe_key"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["action"] == "arrow_down"
        assert input_preview["repeat_count"] == 3
        assert input_preview["capability_id"] == "desktop.ui_operation"
        assert input_preview["intent_kind"] == "desktop_operation"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.safe_key"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["explicit_user_key"] is True
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_hide_current_app_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-hide-current-app.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-hide-current-app.db",
        workspace_dir=tmp_path / "agent-runtime-route-hide-current-app",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-hide-current-app")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    hide_calls = 0
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("hide current app public task should not call model")
        ),
    )

    def fake_hide_app() -> dict[str, Any]:
        nonlocal hide_calls
        hide_calls += 1
        return {
            "ok": True,
            "action": "desktop.hide_app",
            "summary": "Hid the foreground app",
            "data": {"key": "h", "modifiers": ["command"]},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.desktop_hide_app", fake_hide_app)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="隐藏当前应用",
                conversation_id="chat-main-hide-current-app",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-hide-current-app-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-hide-current-app", limit=10)
            if message.role == "assistant"
        )

        assert hide_calls == 1
        assert started["status"] == "completed"
        assert started["summary"] == "已隐藏当前应用。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.hide_app"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert "app_name" not in input_preview
        if "intent_kind" in input_preview:
            assert input_preview["intent_kind"] == "desktop_operation"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.hide_app"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["key"] == "h"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_minimize_current_window_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-minimize-window.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-minimize-window.db",
        workspace_dir=tmp_path / "agent-runtime-route-minimize-window",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-minimize-window")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    minimize_calls = 0
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("minimize current window public task should not call model")
        ),
    )

    def fake_minimize_window() -> dict[str, Any]:
        nonlocal minimize_calls
        minimize_calls += 1
        return {
            "ok": True,
            "action": "desktop.minimize_window",
            "summary": "Minimized the foreground window",
            "data": {"key": "m", "modifiers": ["command"]},
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.desktop_minimize_window",
        fake_minimize_window,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="最小化当前窗口",
                conversation_id="chat-main-minimize-window",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-minimize-window-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-minimize-window", limit=10)
            if message.role == "assistant"
        )

        assert minimize_calls == 1
        assert started["status"] == "completed"
        assert started["summary"] == "已最小化当前窗口。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.minimize_window"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert "app_name" not in started["tool_calls"][-1]["input_preview"]
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.minimize_window"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["key"] == "m"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_open_path_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-open-path.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-open-path.db",
        workspace_dir=tmp_path / "agent-runtime-route-open-path",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-open-path")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    open_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("open path public task should not call model")
        ),
    )

    def fake_open_path(path: str) -> dict[str, Any]:
        open_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.open_path",
            "summary": f"Opened {path}",
            "data": {
                "path": path,
                "open_target": "system_open",
                "exists": True,
                "is_dir": True,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.open_path", fake_open_path)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="打开下载文件夹",
                conversation_id="chat-main-open-path",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-open-path-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-open-path", limit=10)
            if message.role == "assistant"
        )

        assert open_calls == ["~/Downloads"]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开文件夹：~/Downloads。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.open_path"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["path"] == "~/Downloads"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.open_path"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["open_target"] == "system_open"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_reveal_path_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-reveal-path.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-reveal-path.db",
        workspace_dir=tmp_path / "agent-runtime-route-reveal-path",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-reveal-path")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    reveal_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("reveal path public task should not call model")
        ),
    )

    def fake_reveal_path(path: str) -> dict[str, Any]:
        reveal_calls.append(path)
        return {
            "ok": True,
            "action": "desktop.reveal_path",
            "summary": f"Revealed {path}",
            "data": {
                "path": path,
                "open_target": "finder_reveal",
                "exists": True,
                "is_dir": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.reveal_path", fake_reveal_path)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="在 Finder 中显示 ~/Downloads/report.pdf",
                conversation_id="chat-main-reveal-path",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-reveal-path-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-reveal-path", limit=10)
            if message.role == "assistant"
        )

        assert reveal_calls == ["~/Downloads/report.pdf"]
        assert started["status"] == "completed"
        assert started["summary"] == "已在 Finder 中显示：~/Downloads/report.pdf。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.reveal_path"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["path"] == "~/Downloads/report.pdf"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.reveal_path"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["open_target"] == "finder_reveal"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_desktop_permission_diagnosis_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-permission-diagnosis.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-permission-diagnosis.db",
        workspace_dir=tmp_path / "agent-runtime-route-permission-diagnosis",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-permission-diagnosis")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    permission_calls: list[bool] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("desktop permission diagnosis public task should not call model")
        ),
    )

    def fake_permissions() -> dict[str, Any]:
        permission_calls.append(True)
        return {
            "ok": True,
            "action": "desktop.permissions",
            "summary": "Desktop permissions ready",
            "data": {
                "permission_targets": [],
                "affected_tools": [],
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.permissions", fake_permissions)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="为什么不能控制桌面？",
                conversation_id="chat-main-permission-diagnosis",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-permission-diagnosis-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-permission-diagnosis", limit=10)
            if message.role == "assistant"
        )

        assert permission_calls == [True]
        assert started["status"] == "completed"
        assert started["summary"] == "桌面执行权限已就绪。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.permissions"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert "app_name" not in input_preview
        if input_preview:
            assert input_preview["planning_reason"] == "planner_desktop_operation"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.permissions"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["permission_targets"] == []
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    ["为什么不能播放 Apple Music？", "怎么不能播放 Apple Music？"],
)
async def test_yachiyo_task_route_diagnoses_music_permission_gaps_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-music-permission-diagnosis.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-music-permission-diagnosis.db",
        workspace_dir=tmp_path / "agent-runtime-route-music-permission-diagnosis",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-music-permission-diagnosis")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    permission_calls: list[bool] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("music permission diagnosis public task should not call model")
        ),
    )

    def fake_missing_by_capability(*, use_cache: bool = True) -> dict[str, list[str]]:
        permission_calls.append(use_cache)
        return {"media_control": ["music_app", "automation"]}

    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.desktop_permissions.desktop_permission_missing_by_capability",
        fake_missing_by_capability,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt=prompt,
                conversation_id="chat-main-music-permission-diagnosis",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-music-permission-diagnosis-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        assistant = next(
            message
            for message in store.load_messages("chat-main-music-permission-diagnosis", limit=10)
            if message.role == "assistant"
        )
        event_types = [event["event_type"] for event in events["events"]]
        recovery_event = next(
            event
            for event in events["events"]
            if event["event_type"] == "agent.desktop.permission_recovery"
        )
        tool_call = started["tool_calls"][-1]

        assert permission_calls == [True]
        assert started["status"] == "completed"
        assert "桌面执行权限还缺少：music_app, automation。" in started["summary"]
        assert (
            "受影响工具：media.apple_music_play, media.apple_music_open_and_play, "
            "media.apple_music_control。"
        ) in started["summary"]
        assert "打开 Apple Music" in started["summary"]
        assert "打开自动化权限" in started["summary"]
        assert started["needs_user_action"] is True
        assert started["pending_approvals"] == []
        assert tool_call["tool_name"] == "desktop.permissions"
        assert tool_call["status"] == "completed"
        assert tool_call["output_preview"]["permission_error"] is True
        assert tool_call["output_preview"]["permission_targets"] == ["music_app", "automation"]
        assert tool_call["output_preview"]["affected_tools"][:3] == [
            "media.apple_music_play",
            "media.apple_music_open_and_play",
            "media.apple_music_control",
        ]
        recovery_actions = tool_call["output_preview"]["recovery_actions"]
        assert {
            "label": "打开 Apple Music",
            "tool": "app.open",
            "input": {"app_name": "Music"},
            "permission_target": "music_app",
            "recovery_retry_input": {},
            "recovery_retry_prompt": "检查桌面权限",
            "recovery_retry_tool": "desktop.permissions",
            "risk_level": "low",
            "retry_input": {},
            "retry_prompt": "检查桌面权限",
            "retry_tool": "desktop.permissions",
        } in recovery_actions
        assert {
            "label": "打开自动化权限",
            "tool": "system.settings_open",
            "input": {"target": "自动化权限"},
            "permission_target": "automation",
            "recovery_retry_input": {},
            "recovery_retry_prompt": "检查桌面权限",
            "recovery_retry_tool": "desktop.permissions",
            "risk_level": "low",
            "retry_input": {},
            "retry_prompt": "检查桌面权限",
            "retry_tool": "desktop.permissions",
        } in recovery_actions
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.permissions"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.permission_recovery" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert recovery_event["payload"]["permission_targets"] == ["music_app", "automation"]
        assert recovery_event["payload"]["affected_tools"] == [
            "media.apple_music_play",
            "media.apple_music_open_and_play",
            "media.apple_music_control",
            "desktop.permissions",
        ]
        assert recovery_event["payload"]["recovery_actions"] == tool_call["output_preview"]["recovery_actions"]
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_screen_capture_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-screen-capture.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-screen-capture.db",
        workspace_dir=tmp_path / "agent-runtime-route-screen-capture",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-screen-capture")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    capture_targets: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("screen capture public task should not call model")
        ),
    )

    def fake_screen_capture(target_path: Path) -> dict[str, Any]:
        capture_targets.append(str(target_path))
        return {
            "ok": True,
            "action": "screen.capture",
            "summary": "已截取当前屏幕。",
            "data": {
                "path": str(target_path),
                "mime_type": "image/png",
                "size_bytes": 10,
                "width": 100,
                "height": 80,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.screen_capture", fake_screen_capture)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="当前屏幕是什么",
                conversation_id="chat-main-screen-capture",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-screen-capture-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-screen-capture", limit=10)
            if message.role == "assistant"
        )

        assert capture_targets
        assert capture_targets[0].endswith("screenshots/current-screen.png")
        assert started["status"] == "completed"
        assert started["summary"] == "已截取当前屏幕。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "screen.capture"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert timeline["tool_calls"][-1]["tool_name"] == "screen.capture"
        assert timeline["artifacts"][-1]["path"] == "screenshots/current-screen.png"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_running_apps_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-running-apps.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-running-apps.db",
        workspace_dir=tmp_path / "agent-runtime-route-running-apps",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-running-apps")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    running_calls = 0
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("running apps public task should not call model")
        ),
    )

    def fake_running_apps() -> dict[str, Any]:
        nonlocal running_calls
        running_calls += 1
        return {
            "ok": True,
            "action": "desktop.running_apps",
            "summary": "Running apps: Finder, Google Chrome, Music",
            "data": {
                "apps": [
                    {"name": "Finder", "pid": 101, "frontmost": False},
                    {"name": "Google Chrome", "pid": 202, "frontmost": True},
                    {"name": "Music", "pid": 303, "frontmost": False},
                ],
                "frontmost": "Google Chrome",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.running_apps", fake_running_apps)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="现在开了哪些应用",
                conversation_id="chat-main-running-apps",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-running-apps-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-running-apps", limit=10)
            if message.role == "assistant"
        )

        assert running_calls == 1
        assert started["status"] == "completed"
        assert started["summary"] == "正在运行的应用：Finder, Google Chrome, Music。前台是 Google Chrome。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.running_apps"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert "app_name" not in started["tool_calls"][-1]["input_preview"]
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.running_apps"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["frontmost"] == "Google Chrome"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_active_window_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-active-window.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-active-window.db",
        workspace_dir=tmp_path / "agent-runtime-route-active-window",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-active-window")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    active_window_calls = 0
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("active window public task should not call model")
        ),
    )

    def fake_active_window() -> dict[str, Any]:
        nonlocal active_window_calls
        active_window_calls += 1
        return {
            "ok": True,
            "action": "desktop.active_window",
            "summary": "Active window: Google Chrome - ChatGPT",
            "data": {
                "app_name": "Google Chrome",
                "pid": 202,
                "title": "ChatGPT",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.active_window", fake_active_window)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="当前窗口是什么",
                conversation_id="chat-main-active-window",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-active-window-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-active-window", limit=10)
            if message.role == "assistant"
        )

        assert active_window_calls == 1
        assert started["status"] == "completed"
        assert started["summary"] == "当前前台窗口是 Google Chrome：ChatGPT。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.active_window"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert "app_name" not in started["tool_calls"][-1]["input_preview"]
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.active_window"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["title"] == "ChatGPT"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_window_list_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-window-list.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-window-list.db",
        workspace_dir=tmp_path / "agent-runtime-route-window-list",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-window-list")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    window_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("window list public task should not call model")
        ),
    )

    def fake_windows(app_name: str = "") -> dict[str, Any]:
        window_calls.append(app_name)
        return {
            "ok": True,
            "action": "desktop.windows",
            "summary": "Open windows: Google Chrome: ChatGPT",
            "data": {
                "app_name": app_name,
                "windows": [
                    {
                        "app_name": "Google Chrome",
                        "pid": 202,
                        "index": 1,
                        "frontmost": True,
                        "title": "ChatGPT",
                    }
                ],
                "count": 1,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.windows", fake_windows)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="Chrome 有哪些窗口",
                conversation_id="chat-main-window-list",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-window-list-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-window-list", limit=10)
            if message.role == "assistant"
        )

        assert window_calls == ["Google Chrome"]
        assert started["status"] == "completed"
        assert started["summary"] == "当前窗口：Google Chrome: ChatGPT。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.windows"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["app_name"] == "Google Chrome"
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.windows"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["count"] == 1
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_ui_elements_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-ui-elements.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-ui-elements.db",
        workspace_dir=tmp_path / "agent-runtime-route-ui-elements",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-ui-elements")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    ui_calls: list[tuple[str, int, str]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ui elements public task should not call model")
        ),
    )

    def fake_ui_elements(
        role_filter: str = "",
        limit: int = 80,
        app_name: str = "",
    ) -> dict[str, Any]:
        ui_calls.append((role_filter, limit, app_name))
        return {
            "ok": True,
            "action": "desktop.ui_elements",
            "summary": "Google Chrome UI elements: AXButton: Send",
            "data": {
                "app_name": "Google Chrome",
                "title": "ChatGPT",
                "role_filter": role_filter,
                "limit": limit,
                "elements": [
                    {
                        "role": "AXButton",
                        "name": "Send",
                        "description": "Send message",
                        "enabled": True,
                        "center": {"x": 120, "y": 240},
                    }
                ],
                "count": 1,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.ui_elements", fake_ui_elements)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="当前界面有哪些按钮",
                conversation_id="chat-main-ui-elements",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-ui-elements-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-ui-elements", limit=10)
            if message.role == "assistant"
        )

        assert ui_calls == [("button", 80, "")]
        assert started["status"] == "completed"
        assert started["summary"] == "当前 Google Chrome 界面控件：Button Send（120, 240）。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "desktop.ui_elements"
        assert started["tool_calls"][-1]["status"] == "completed"
        input_preview = started["tool_calls"][-1]["input_preview"]
        assert input_preview["role_filter"] == "button"
        assert input_preview["limit"] == 80
        assert timeline["tool_calls"][-1]["tool_name"] == "desktop.ui_elements"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["count"] == 1
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_app_status_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-app-status.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-app-status.db",
        workspace_dir=tmp_path / "agent-runtime-route-app-status",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-app-status")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    status_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("app status public task should not call model")
        ),
    )

    def fake_app_status(app_name: str) -> dict[str, Any]:
        status_calls.append(app_name)
        return {
            "ok": True,
            "action": "app.status",
            "summary": f"{app_name} is running",
            "data": {"app_name": app_name, "running": True},
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_status", fake_app_status)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="检查一下 Slack 是否在运行",
                conversation_id="chat-main-app-status",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-app-status-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-app-status", limit=10)
            if message.role == "assistant"
        )

        assert status_calls == ["Slack"]
        assert started["status"] == "completed"
        assert started["summary"] == "Slack 当前正在运行。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "app.status"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["tool_calls"][-1]["input_preview"]["app_name"] == "Slack"
        assert timeline["tool_calls"][-1]["tool_name"] == "app.status"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["running"] is True
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_browser_current_page_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-browser-current-page.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-browser-current-page.db",
        workspace_dir=tmp_path / "agent-runtime-route-browser-current-page",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-browser-current-page")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    page_calls = 0
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser current page public task should not call model")
        ),
    )

    def fake_current_page() -> dict[str, Any]:
        nonlocal page_calls
        page_calls += 1
        return {
            "ok": True,
            "action": "browser.current_page",
            "summary": "Current browser page: ChatGPT",
            "data": {
                "title": "ChatGPT",
                "url": "https://chatgpt.com/",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.current_page", fake_current_page)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="当前网页是什么",
                conversation_id="chat-main-browser-current-page",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-browser-current-page-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-browser-current-page", limit=10)
            if message.role == "assistant"
        )

        assert page_calls == 1
        assert started["status"] == "completed"
        assert started["summary"] == "当前网页是 ChatGPT：https://chatgpt.com/。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "browser.current_page"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert "url" not in started["tool_calls"][-1]["input_preview"]
        assert timeline["tool_calls"][-1]["tool_name"] == "browser.current_page"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["title"] == "ChatGPT"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_projects_browser_cdp_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-browser-cdp-recovery.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-browser-cdp-recovery.db",
        workspace_dir=tmp_path / "agent-runtime-route-browser-cdp-recovery",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-browser-cdp-recovery")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser cdp recovery public task should not call model")
        ),
    )
    monkeypatch.setattr("apps.shell.agent.tools.browser._configured_browser_cdp_url", lambda: "")
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="当前网页是什么",
                conversation_id="chat-main-browser-cdp-recovery",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-browser-cdp-recovery-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        tool_call = started["tool_calls"][-1]
        recovery_event = next(
            event
            for event in events["events"]
            if event["event_type"] == "agent.desktop.permission_recovery"
        )

        assert started["status"] == "completed"
        assert started["needs_user_action"] is True
        assert started["pending_approvals"] == []
        assert "桌面操作未完成：chrome_cdp_unavailable" in started["summary"]
        assert "缺少权限：chrome_cdp" in started["summary"]
        assert "可直接打开：打开 Google Chrome。" in started["summary"]
        assert tool_call["tool_name"] == "browser.current_page"
        assert tool_call["status"] == "failed"
        assert tool_call["output_preview"]["permission_targets"] == ["chrome_cdp"]
        assert tool_call["output_preview"]["recovery_actions"] == [
            {
                "label": "打开 Google Chrome",
                "tool": "app.open",
                "input": {"app_name": "Google Chrome"},
                "permission_target": "chrome_cdp",
                "recovery_retry_input": {},
                "recovery_retry_prompt": "查看当前网页",
                "recovery_retry_tool": "browser.current_page",
                "risk_level": "low",
                "retry_input": {},
                "retry_prompt": "查看当前网页",
                "retry_tool": "browser.current_page",
            }
        ]
        assert timeline["tool_calls"][-1]["tool_name"] == "browser.current_page"
        assert timeline["tool_calls"][-1]["output_preview"]["recovery_actions"] == tool_call["output_preview"]["recovery_actions"]
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.permission_recovery" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert recovery_event["payload"]["permission_targets"] == ["chrome_cdp"]
        assert recovery_event["payload"]["affected_tools"] == ["browser.current_page"]
        assert recovery_event["payload"]["recovery_actions"] == tool_call["output_preview"]["recovery_actions"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_browser_extract_text_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-browser-extract-text.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-browser-extract-text.db",
        workspace_dir=tmp_path / "agent-runtime-route-browser-extract-text",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-browser-extract-text")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    extract_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser extract text public task should not call model")
        ),
    )

    def fake_extract_text(selector: str = "") -> dict[str, Any]:
        extract_calls.append(selector)
        return {
            "ok": True,
            "action": "browser.extract_text",
            "summary": "Extracted 29 characters from browser page",
            "data": {
                "selector": selector,
                "text": "Yachiyo desktop agent runtime",
                "truncated": False,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.extract_text", fake_extract_text)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="读一下这个网页",
                conversation_id="chat-main-browser-extract-text",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-browser-extract-text-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-browser-extract-text", limit=10)
            if message.role == "assistant"
        )

        assert extract_calls == [""]
        assert started["status"] == "completed"
        assert started["summary"] == "Yachiyo desktop agent runtime"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "browser.extract_text"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert "selector" not in started["tool_calls"][-1]["input_preview"]
        assert timeline["tool_calls"][-1]["tool_name"] == "browser.extract_text"
        assert timeline["tool_calls"][-1]["output_preview"]["data"]["text"] == (
            "Yachiyo desktop agent runtime"
        )
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_browser_screenshot_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-browser-screenshot.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-browser-screenshot.db",
        workspace_dir=tmp_path / "agent-runtime-route-browser-screenshot",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-browser-screenshot")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    screenshot_targets: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser screenshot public task should not call model")
        ),
    )

    def fake_browser_screenshot(target_path: Path) -> dict[str, Any]:
        screenshot_targets.append(str(target_path))
        return {
            "ok": True,
            "action": "browser.screenshot",
            "summary": "Captured current browser page",
            "data": {
                "path": str(target_path),
                "mime_type": "image/png",
                "format": "png",
                "size": 10,
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.browser.screenshot", fake_browser_screenshot)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="截取当前网页",
                conversation_id="chat-main-browser-screenshot",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-browser-screenshot-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages("chat-main-browser-screenshot", limit=10)
            if message.role == "assistant"
        )

        assert screenshot_targets
        assert screenshot_targets[0].endswith("browser/current-page.png")
        assert started["status"] == "completed"
        assert started["summary"] == "已截取当前网页。"
        assert started["needs_user_action"] is False
        assert started["pending_approvals"] == []
        assert started["tool_calls"][-1]["tool_name"] == "browser.screenshot"
        assert started["tool_calls"][-1]["status"] == "completed"
        assert started["artifacts"][-1]["path"] == "browser/current-page.png"
        assert timeline["tool_calls"][-1]["tool_name"] == "browser.screenshot"
        assert timeline["artifacts"][-1]["path"] == "browser/current-page.png"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "artifact.created" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.intent_approval_required" not in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "tool_name", "input_preview", "patched_tool", "tool_result", "expected_summary"),
    [
        (
            "点击当前网页上的登录按钮",
            "browser.click",
            {"selector": "text=登录", "click_count": 1},
            "apps.shell.agent.tools.browser.click",
            {
                "ok": True,
                "action": "browser.click",
                "summary": "Clicked browser selector",
                "data": {"selector": "text=登录", "label": "登录", "tag": "BUTTON"},
            },
            "已点击网页元素：登录。",
        ),
        (
            "点击当前网页 120 240",
            "browser.click",
            {"selector": "point=120,240", "fallback_x": 120, "fallback_y": 240, "click_count": 1},
            "apps.shell.agent.tools.browser.click",
            {
                "ok": True,
                "action": "browser.click",
                "summary": "Clicked browser selector",
                "data": {"selector": "point=120,240", "x": 120, "y": 240, "tag": "BUTTON"},
            },
            "已点击网页位置：120, 240。",
        ),
        (
            "在网页搜索框输入 yachiyo",
            "browser.type_text",
            {
                "selector": (
                    'input[type="search"], input[name="q"], textarea[name="q"], '
                    'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                    'input[aria-label*="search" i], input[placeholder*="search" i]'
                ),
                "text": "yachiyo",
            },
            "apps.shell.agent.tools.browser.type_text",
            {
                "ok": True,
                "action": "browser.type_text",
                "summary": "Typed text into browser selector",
                "data": {
                    "selector": (
                        'input[type="search"], input[name="q"], textarea[name="q"], '
                        'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                        'input[aria-label*="search" i], input[placeholder*="search" i]'
                    ),
                    "length": 7,
                    "tag": "INPUT",
                },
            },
            "已在网页搜索框输入文字（7 个字符）。",
        ),
        (
            "在网页坐标 120 240 输入 hello",
            "browser.type_text",
            {"selector": "point=120,240", "text": "hello", "fallback_x": 120, "fallback_y": 240},
            "apps.shell.agent.tools.browser.type_text",
            {
                "ok": True,
                "action": "browser.type_text",
                "summary": "Typed text into browser selector",
                "data": {"selector": "point=120,240", "length": 5, "x": 120, "y": 240, "tag": "INPUT"},
            },
            "已在网页位置：120, 240 输入文字（5 个字符）。",
        ),
    ],
)
async def test_yachiyo_task_route_approves_browser_interaction_intent_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    tool_name: str,
    input_preview: dict[str, Any],
    patched_tool: str,
    tool_result: dict[str, Any],
    expected_summary: str,
) -> None:
    store = ChatStore(db_path=str(tmp_path / f"chat-route-{tool_name}.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / f"agent-runtime-route-{tool_name}.db",
        workspace_dir=tmp_path / f"agent-runtime-route-{tool_name}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id=f"chat-main-{tool_name}")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    tool_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser interaction public task should not call model")
        ),
    )

    def fake_tool(*args: Any, **kwargs: Any) -> dict[str, Any]:
        tool_calls.append({"args": args, "kwargs": kwargs})
        return tool_result

    monkeypatch.setattr(patched_tool, fake_tool)
    try:
        started = ChatAPI(app_runtime).send_message(prompt)
        task = state.get_task(started["task_id"])
        waiting_message = session.get_assistant_message_for_task(started["task_id"])
        waiting_run = service.get_run(started["run_id"])

        assert started["ok"] is True
        assert started["status"] == "waiting_approval"
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert waiting_message is not None
        assert waiting_message.status == MessageStatus.PROCESSING
        assert waiting_run["status"] == "approval_required"
        assert waiting_run["pending_approval"]["tool"] == tool_name
        assert waiting_run["pending_approval"]["input_preview"] == input_preview
        assert tool_calls == []

        approved = await yachiyo.approve_task(started["task_id"], None, request)
        completed_task = state.get_task(started["task_id"])
        completed_message = session.get_assistant_message_for_task(started["task_id"])
        completed_run = service.get_run(started["run_id"])

        assert approved["status"] == "completed"
        assert approved["summary"] == expected_summary
        assert len(tool_calls) == 1
        assert completed_task is not None
        assert completed_task.status == TaskStatus.COMPLETED
        assert completed_task.result == expected_summary
        assert completed_message is not None
        assert completed_message.status == MessageStatus.COMPLETED
        assert completed_message.content == expected_summary
        assert completed_message.metadata["pending_approval"] == {}
        assert completed_run["status"] == "completed"
        assert completed_run["pending_approval"] == {}
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "tool_name", "input_preview", "patched_tool"),
    [
        (
            "关闭当前窗口",
            "desktop.close_window",
            {},
            "apps.shell.agent.tools.desktop.desktop_close_window",
        ),
        (
            "退出 Slack",
            "app.quit",
            {"app_name": "Slack"},
            "apps.shell.agent.tools.desktop.app_quit",
        ),
        (
            "退出当前应用",
            "desktop.quit_app",
            {},
            "apps.shell.agent.tools.desktop.desktop_quit_app",
        ),
        (
            "双击 120 240",
            "desktop.click",
            {"x": 120, "y": 240, "click_count": 2},
            "apps.shell.agent.tools.desktop.desktop_click",
        ),
        (
            "点击发送按钮",
            "desktop.click_ui_element",
            {"target": "发送", "role_filter": "button", "limit": 80, "click_count": 1},
            "apps.shell.agent.tools.desktop.click_ui_element",
        ),
        (
            "在搜索框输入 hello",
            "desktop.type_into_ui_element",
            {"target": "搜索", "text": "hello", "role_filter": "text", "limit": 80},
            "apps.shell.agent.tools.desktop.type_into_ui_element",
        ),
        (
            "打开 Chrome 并在名为 URL 的输入框输入 github.com",
            "app.open_and_type_into_ui_element",
            {
                "app_name": "Google Chrome",
                "target": "名为 URL 的",
                "text": "github.com",
                "role_filter": "text",
                "limit": 80,
            },
            "apps.shell.agent.tools.desktop.type_into_ui_element",
        ),
    ],
)
async def test_yachiyo_task_route_pauses_medium_risk_desktop_intent_for_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
    tool_name: str,
    input_preview: dict[str, Any],
    patched_tool: str,
) -> None:
    store = ChatStore(db_path=str(tmp_path / f"chat-route-{tool_name}.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / f"agent-runtime-route-{tool_name}.db",
        workspace_dir=tmp_path / f"agent-runtime-route-{tool_name}",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id=f"chat-main-{tool_name}")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("medium-risk desktop public task should not call model")
        ),
    )
    monkeypatch.setattr(
        patched_tool,
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError(f"{tool_name} should wait for approval")
        ),
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt=prompt,
                conversation_id=f"chat-main-{tool_name}",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": f"route-main-{tool_name}-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        event_types = [event["event_type"] for event in events["events"]]
        assistant = next(
            message
            for message in store.load_messages(f"chat-main-{tool_name}", limit=10)
            if message.role == "assistant"
        )
        link = service.get_task_run_link(started["task_id"])
        run = service.get_run(link["run_id"])

        assert started["status"] == "waiting_approval"
        assert started["needs_user_action"] is True
        assert started["tool_calls"][-1]["tool_name"] == tool_name
        assert started["tool_calls"][-1]["status"] == "waiting_approval"
        assert started["pending_approvals"][0]["tool_name"] == tool_name
        for key, value in input_preview.items():
            assert started["pending_approvals"][0]["input_preview"][key] == value
        assert timeline["status"] == "approval_required"
        assert timeline["pending_approval"]["tool_name"] == tool_name
        for key, value in input_preview.items():
            assert timeline["pending_approval"]["input_preview"][key] == value
        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == tool_name
        for key, value in input_preview.items():
            assert run["pending_approval"]["input_preview"][key] == value
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.desktop.intent_approval_required" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.PROCESSING
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_projects_daily_desktop_permission_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-permission.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-permission.db",
        workspace_dir=tmp_path / "agent-runtime-route-permission",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-daily-permission")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    capture_targets: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily desktop permission recovery should not call model")
        ),
    )

    class ScreenCapturePermissionError(RuntimeError):
        pass

    def fake_capture(target_path: Path) -> dict[str, Any]:
        capture_targets.append(str(target_path))
        raise ScreenCapturePermissionError("screen recording permission denied")

    monkeypatch.setattr("apps.shell.agent.tools.desktop._desktop_platform", lambda: "macos")
    monkeypatch.setattr("apps.locald.screenshot.capture_screenshot_to_file", fake_capture)
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="截个图看看",
                conversation_id="chat-main-daily-permission",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-permission-1",
                    "source": "chat",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                },
            ),
            request,
        )
        timeline = await yachiyo.get_task_timeline(started["task_id"], request)
        events = await yachiyo.get_task_events(started["task_id"], request)
        messages = store.load_messages("chat-main-daily-permission", limit=10)
        assistant = next(message for message in messages if message.role == "assistant")
        event_types = [event["event_type"] for event in events["events"]]
        tool_call = started["tool_calls"][-1]
        recovery_event = next(
            event
            for event in events["events"]
            if event["event_type"] == "agent.desktop.permission_recovery"
        )

        assert capture_targets
        assert Path(capture_targets[0]).suffix == ".png"
        assert started["status"] == "completed"
        assert "桌面操作未完成：screen recording permission denied" in started["summary"]
        assert "缺少权限：screen_recording" in started["summary"]
        assert started["needs_user_action"] is True
        assert tool_call["tool_name"] == "screen.capture"
        assert tool_call["status"] == "failed"
        assert tool_call["output_preview"]["permission_error"] is True
        assert tool_call["output_preview"]["permission_targets"] == ["screen_recording"]
        assert tool_call["output_preview"]["recovery_actions"] == [
            {
                "label": "打开屏幕录制权限",
                "tool": "system.settings_open",
                "input": {"target": "屏幕录制权限"},
                "permission_target": "screen_recording",
                "recovery_retry_input": {"reason": "user asked to capture the screen"},
                "recovery_retry_prompt": "截图当前屏幕",
                "recovery_retry_tool": "screen.capture",
                "risk_level": "low",
                "retry_input": {"reason": "user asked to capture the screen"},
                "retry_prompt": "截图当前屏幕",
                "retry_tool": "screen.capture",
            }
        ]
        assert timeline["task_id"] == started["task_id"]
        assert timeline["status"] == "completed"
        assert timeline["tool_calls"][-1]["tool_name"] == "screen.capture"
        assert timeline["tool_calls"][-1]["status"] == "failed"
        assert "agent.desktop.intent_planned" in event_types
        assert "agent.tool.call" in event_types
        assert "agent.desktop.intent_completed" in event_types
        assert "agent.desktop.permission_recovery" in event_types
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert recovery_event["payload"]["permission_targets"] == ["screen_recording"]
        assert recovery_event["payload"]["affected_tools"] == ["screen.capture"]
        assert recovery_event["payload"]["recovery_actions"] == tool_call["output_preview"]["recovery_actions"]
        assert assistant.task_id == started["task_id"]
        assert assistant.status == MessageStatus.COMPLETED
        assert assistant.content == started["summary"]
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_route_executes_structured_recovery_action_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ChatStore(db_path=str(tmp_path / "chat-route-recovery-action.db"))
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-route-recovery-action.db",
        workspace_dir=tmp_path / "agent-runtime-route-recovery-action",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    session = ChatSession(session_id="chat-main-recovery-action")
    session.attach_store(store, load_existing=False)
    state = AppState()
    app_runtime = SimpleNamespace(
        agent_runtime_service=service,
        chat_session=session,
        state=state,
        store=store,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))
    settings_open_calls: list[str] = []
    monkeypatch.setattr(
        "apps.shell.agent_runtime.get_model_profile_service",
        lambda: SimpleNamespace(
            get_defaults=lambda: {"chat": ""},
            get_profile_private=lambda profile_id: (_ for _ in ()).throw(KeyError(profile_id)),
        ),
    )
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("structured recovery action should not call model")
        ),
    )

    def fake_system_settings_open(target: str) -> dict[str, Any]:
        settings_open_calls.append(target)
        return {
            "ok": True,
            "action": "system.settings_open",
            "summary": f"Opened System Settings: {target}",
            "data": {
                "target": target,
                "open_target": "system_settings",
            },
        }

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop.system_settings_open",
        fake_system_settings_open,
    )
    try:
        started = await yachiyo.start_task(
            yachiyo.StartChatTaskRequest(
                prompt="修复屏幕录制",
                conversation_id="chat-main-recovery-action",
                agent_id="builtin:yachiyo-main",
                metadata={
                    "client_message_id": "route-main-recovery-action-1",
                    "source": "live2d",
                    "runnable_kind": "main",
                    "daily_desktop_intent": True,
                    "desktop_permission_recovery": True,
                    "recovery_tool": "system.settings_open",
                    "recovery_input": {"target": "屏幕录制权限"},
                    "recovery_permission_target": "screen_recording",
                    "recovery_risk_level": "low",
                },
            ),
            request,
        )
        events = await yachiyo.get_task_events(started["task_id"], request)
        messages = store.load_messages("chat-main-recovery-action", limit=10)
        user = next(message for message in messages if message.role == "user")
        user_metadata = json.loads(user.metadata_json or "{}")
        planned_event = next(
            event
            for event in events["events"]
            if event["event_type"] == "agent.desktop.intent_planned"
        )
        event_types = [event["event_type"] for event in events["events"]]

        assert settings_open_calls == ["屏幕录制权限"]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开系统设置：屏幕录制权限。"
        assert started["tool_calls"][-1]["tool_name"] == "system.settings_open"
        assert started["tool_calls"][-1]["input_preview"]["target"] == "屏幕录制权限"
        assert planned_event["payload"]["input_preview"]["target"] == "屏幕录制权限"
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert user_metadata["desktop_permission_recovery"] is True
        assert user_metadata["recovery_tool"] == "system.settings_open"
        assert user_metadata["recovery_input"] == {"target": "屏幕录制权限"}
    finally:
        service.close()
        store.close()


@pytest.mark.asyncio
async def test_yachiyo_task_reject_preserves_approval_decision_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RejectRecordingService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def reject(self, task_id: str, decision: Any) -> AgentTaskSnapshot:
            payload = decision.model_dump(exclude_none=True)
            self.calls.append({"task_id": task_id, "decision": payload})
            return AgentTaskSnapshot(task_id=task_id, title="Rejected", status="failed")

    service = _RejectRecordingService()
    monkeypatch.setattr(yachiyo_chat_handlers, "agent_service", lambda _request=None: service)

    rejected = await yachiyo.reject_task(
        "task-approval-1",
        yachiyo.TaskApprovalRequest(
            approval_id="approval-1",
            reason="No",
            metadata={"surface": "bubble"},
        ),
        None,
    )

    assert rejected["status"] == "failed"
    assert service.calls == [
        {
            "task_id": "task-approval-1",
            "decision": {
                "approved": False,
                "reason": "No",
                "metadata": {
                    "approval_id": "approval-1",
                    "surface": "bubble",
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_studio_run_approve_preserves_approval_decision_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _ApproveRecordingStudioService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def approve_run_approval(self, run_id: str, decision: Any) -> RunTimelineSnapshot:
            payload = decision.model_dump(exclude_none=True)
            self.calls.append({"run_id": run_id, "decision": payload})
            return RunTimelineSnapshot(run_id=run_id, status="completed")

    service = _ApproveRecordingStudioService()
    monkeypatch.setattr(yachiyo_studio_run_handlers, "studio_service", lambda _request=None: service)

    approved = await yachiyo.approve_studio_run_approval(
        "run-approval-1",
        None,
        yachiyo.TaskApprovalRequest(
            approval_id="approval-studio-1",
            reason="Looks safe",
            metadata={"surface": "studio"},
        ),
    )

    assert approved["status"] == "completed"
    assert service.calls == [
        {
            "run_id": "run-approval-1",
            "decision": {
                "approved": True,
                "reason": "Looks safe",
                "metadata": {
                    "approval_id": "approval-studio-1",
                    "surface": "studio",
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_studio_run_reject_preserves_approval_decision_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RejectRecordingStudioService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def reject_run_approval(self, run_id: str, decision: Any) -> RunTimelineSnapshot:
            payload = decision.model_dump(exclude_none=True)
            self.calls.append({"run_id": run_id, "decision": payload})
            return RunTimelineSnapshot(run_id=run_id, status="failed")

    service = _RejectRecordingStudioService()
    monkeypatch.setattr(yachiyo_studio_run_handlers, "studio_service", lambda _request=None: service)

    rejected = await yachiyo.reject_studio_run_approval(
        "run-approval-1",
        yachiyo.TaskApprovalRequest(
            approval_id="approval-studio-1",
            reason="No",
            metadata={"surface": "studio"},
        ),
        None,
    )

    assert rejected["status"] == "failed"
    assert service.calls == [
        {
            "run_id": "run-approval-1",
            "decision": {
                "approved": False,
                "reason": "No",
                "metadata": {
                    "approval_id": "approval-studio-1",
                    "surface": "studio",
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_chat_task_link_is_visible_from_studio_timeline() -> None:
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    started = await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(
            prompt="Patch README",
            conversation_id="chat-1",
            metadata={"client_task_id": "task-chat-1"},
        ),
        request,
    )
    timeline = await yachiyo.get_studio_run_timeline("run-1", request)

    assert started["task_id"] == "task-chat-1"
    assert started["open_in_studio_url"] == "#/agents?run_id=run-1&group_run=group-run-1"
    assert timeline["run_id"] == "run-1"
    assert timeline["task_id"] == "task-chat-1"
    assert timeline["session_id"] == "chat-1"
    assert timeline["task_run_link_created_at"] == "2026-06-14T00:00:00Z"
    assert timeline["task_run_link_updated_at"] == "2026-06-14T00:00:02Z"
    assert timeline["task_run_link_run_status"] == "approval_required"
    assert timeline["task_run_link_last_event_sequence"] == 1
    assert timeline["pending_approval"]["approval_id"] == "run-1"
    assert timeline["artifacts"][0]["path"] == "report.md"
    assert timeline["events"][0]["event_type"] == "agent.tool.call"


@pytest.mark.asyncio
async def test_yachiyo_task_approval_body_id_keeps_task_link_lookup() -> None:
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(
            prompt="Patch README",
            conversation_id="chat-1",
            metadata={"client_task_id": "task-chat-1"},
        ),
        request,
    )
    approved = await yachiyo.approve_task(
        "task-chat-1",
        yachiyo.TaskApprovalRequest(approval_id="run-1"),
        request,
    )
    rejected = await yachiyo.reject_task(
        "task-chat-1",
        yachiyo.TaskApprovalRequest(approval_id="run-1", reason="No"),
        request,
    )

    assert approved["task_id"] == "task-chat-1"
    assert approved["status"] == "completed"
    assert rejected["task_id"] == "task-chat-1"
    assert rejected["status"] == "failed"
    assert ("approve_run_approval", "run-1") in runtime.calls
    assert ("reject_run_approval", {"run_id": "run-1", "reason": "No"}) in runtime.calls
    assert ("approve_run_approval", "approval-distinct") not in runtime.calls
    assert (
        "reject_run_approval",
        {"run_id": "approval-distinct", "reason": "No"},
    ) not in runtime.calls


@pytest.mark.asyncio
async def test_yachiyo_task_route_uses_chat_backed_agent_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _FakeAgentRuntime()
    runtime.runs["run-1"] = _run_payload(run_id="run-1", status="processing")
    app_runtime = SimpleNamespace(
        agent_runtime_service=runtime,
        chat_session=SimpleNamespace(session_id="chat-1"),
        chat_calls=[],
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))

    class FakeChatAPI:
        def __init__(self, app_runtime: Any) -> None:
            self._app_runtime = app_runtime

        def send_runnable_message_in_session(
            self,
            session_id: str,
            text: str,
            *,
            runnable_id: str = "",
            client_message_id: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            self._app_runtime.chat_calls.append(
                {
                    "session_id": session_id,
                    "text": text,
                    "runnable_id": runnable_id,
                    "client_message_id": client_message_id,
                    "metadata": metadata,
                }
            )
            return {
                "ok": True,
                "run_id": "run-1",
                "agent_run_id": "run-1",
                "session_id": "chat-1",
                "status": "processing",
            }

    monkeypatch.setattr(legacy_ports, "ChatAPI", FakeChatAPI)

    started = await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(
            prompt="Patch README",
            conversation_id="chat-1",
            agent_id="agent-1",
            metadata={"client_message_id": "client-1"},
        ),
        request,
    )

    assert started["task_id"] == "run-1"
    assert started["status"] == "running"
    assert started["conversation_id"] == "chat-1"
    assert app_runtime.chat_calls == [
        {
            "session_id": "chat-1",
            "text": "Patch README",
            "runnable_id": "agent-1",
            "client_message_id": "client-1",
            "metadata": {"client_message_id": "client-1"},
        }
    ]
    assert (
        "link_task_run",
        {"task_id": "run-1", "run_id": "run-1", "session_id": "chat-1"},
    ) in runtime.calls
    assert not any(call[0] == "create_run_for_runnable_async" for call in runtime.calls)


@pytest.mark.asyncio
async def test_yachiyo_task_route_uses_chat_backed_main_agent_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _FakeAgentRuntime()
    runtime.runs["run-1"] = _run_payload(run_id="run-1", status="processing")
    app_runtime = SimpleNamespace(
        agent_runtime_service=runtime,
        chat_session=SimpleNamespace(session_id="chat-1"),
        chat_calls=[],
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))

    class FakeChatAPI:
        def __init__(self, app_runtime: Any) -> None:
            self._app_runtime = app_runtime

        def send_runnable_message_in_session(
            self,
            session_id: str,
            text: str,
            *,
            runnable_id: str = "",
            client_message_id: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            self._app_runtime.chat_calls.append(
                {
                    "session_id": session_id,
                    "text": text,
                    "runnable_id": runnable_id,
                    "client_message_id": client_message_id,
                    "metadata": metadata,
                }
            )
            return {
                "ok": True,
                "task_id": "chat-task-1",
                "session_id": "chat-1",
                "status": "pending",
            }

    monkeypatch.setattr(legacy_ports, "ChatAPI", FakeChatAPI)

    started = await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(
            prompt="播放超时空辉夜姬",
            conversation_id="chat-1",
            agent_id="builtin:yachiyo-main",
            metadata={
                "client_message_id": "client-main-1",
                "daily_desktop_intent": True,
            },
        ),
        request,
    )

    assert started["task_id"] == "chat-task-1"
    assert started["status"] == "running"
    assert started["conversation_id"] == "chat-1"
    assert started["current_step"] == "准备执行 · 发现已安装应用"
    assert started["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
    assert started["recent_events"][0]["detail"] == "desktop.list_apps"
    assert started["recent_events"][0]["payload"] == {
        "input_preview": {"query": "music", "limit": 20},
        "planning_reason": "planner_fallback_media_playback",
        "source": "runtime_planner",
        "status": "planned",
        "tool": "desktop.list_apps",
    }
    assert len(app_runtime.chat_calls) == 1
    chat_call = app_runtime.chat_calls[0]
    assert chat_call["session_id"] == "chat-1"
    assert chat_call["text"] == "播放超时空辉夜姬"
    assert chat_call["runnable_id"] == "builtin:yachiyo-main"
    assert chat_call["client_message_id"] == "client-main-1"
    metadata = chat_call["metadata"]
    assert metadata["client_message_id"] == "client-main-1"
    assert metadata["daily_desktop_intent"] is True
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "media_playback"
    assert metadata["yachiyo_plan_source"] == "runtime_planner"
    assert metadata["yachiyo_plan_tools"] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
        "desktop.ui_elements",
    ]
    assert not any(call[0] == "link_task_run" for call in runtime.calls)
    assert not any(call[0] == "create_run_for_runnable_async" for call in runtime.calls)


@pytest.mark.asyncio
async def test_yachiyo_task_route_defaults_launcher_task_to_chat_backed_main_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _FakeAgentRuntime()
    runtime.runs["run-1"] = _run_payload(run_id="run-1", status="processing")
    app_runtime = SimpleNamespace(
        agent_runtime_service=runtime,
        chat_session=SimpleNamespace(session_id="chat-1"),
        chat_calls=[],
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(runtime=app_runtime)))

    class FakeChatAPI:
        def __init__(self, app_runtime: Any) -> None:
            self._app_runtime = app_runtime

        def send_runnable_message_in_session(
            self,
            session_id: str,
            text: str,
            *,
            runnable_id: str = "",
            client_message_id: str = "",
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            self._app_runtime.chat_calls.append(
                {
                    "session_id": session_id,
                    "text": text,
                    "runnable_id": runnable_id,
                    "client_message_id": client_message_id,
                    "metadata": metadata,
                }
            )
            return {
                "ok": True,
                "task_id": "launcher-chat-task-1",
                "session_id": "chat-1",
                "status": "pending",
            }

    monkeypatch.setattr(legacy_ports, "ChatAPI", FakeChatAPI)

    started = await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(
            prompt="打开 Apple Music",
            conversation_id="chat-1",
            metadata={
                "client_message_id": "launcher-main-1",
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "desktop_launcher",
            },
        ),
        request,
    )

    assert started["task_id"] == "launcher-chat-task-1"
    assert started["status"] == "running"
    assert started["conversation_id"] == "chat-1"
    assert started["current_step"] == "准备执行 · 发现已安装应用"
    assert started["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
    assert started["recent_events"][0]["detail"] == "desktop.list_apps"
    assert started["recent_events"][0]["payload"] == {
        "input_preview": {"limit": 20, "query": "Apple Music"},
        "planning_reason": "planner_fallback_desktop_operation",
        "source": "runtime_planner",
        "status": "planned",
        "tool": "desktop.list_apps",
    }
    assert len(app_runtime.chat_calls) == 1
    chat_call = app_runtime.chat_calls[0]
    assert chat_call["session_id"] == "chat-1"
    assert chat_call["text"] == "打开 Apple Music"
    assert chat_call["runnable_id"] == "builtin:yachiyo-main"
    assert chat_call["client_message_id"] == "launcher-main-1"
    metadata = chat_call["metadata"]
    assert metadata["client_message_id"] == "launcher-main-1"
    assert metadata["source"] == "launcher"
    assert metadata["launcher_mode"] == "bubble"
    assert metadata["launcher_surface"] == "desktop_launcher"
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "desktop_operation"
    assert metadata["yachiyo_plan_source"] == "runtime_planner"
    assert metadata["yachiyo_plan_tools"][:2] == ["desktop.list_apps", "app.open"]
    assert not any(call[0] == "link_task_run" for call in runtime.calls)
    assert not any(call[0] == "create_run_for_runnable_async" for call in runtime.calls)


@pytest.mark.asyncio
async def test_yachiyo_task_route_can_start_workflow_task_from_chat() -> None:
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    started = await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(
            prompt="Build report",
            conversation_id="chat-1",
            workflow_id="workflow-1",
            metadata={"client_task_id": "task-workflow-1"},
        ),
        request,
    )
    timeline = await yachiyo.get_task_timeline("task-workflow-1", request)
    approved = await yachiyo.approve_task("task-workflow-1", None, request)
    rejected = await yachiyo.reject_task(
        "task-workflow-1",
        yachiyo.TaskApprovalRequest(reason="No"),
        request,
    )

    assert started["task_id"] == "task-workflow-1"
    assert started["status"] == "waiting_approval"
    assert started["open_in_studio_url"] == "#/agents?run_id=workflow-run-1&group_run=group-run-1"
    assert timeline["workflow_run_id"] == "workflow-run-1"
    assert timeline["task_id"] == "task-workflow-1"
    assert approved["task_id"] == "task-workflow-1"
    assert approved["status"] == "completed"
    assert approved["open_in_studio_url"] == "#/agents?run_id=workflow-run-1&group_run=group-run-1"
    assert rejected["task_id"] == "task-workflow-1"
    assert rejected["status"] == "failed"
    assert rejected["open_in_studio_url"] == "#/agents?run_id=workflow-run-1&group_run=group-run-1"
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
    assert ("approve_run_approval", "workflow-run-1") in runtime.calls
    assert ("reject_run_approval", {"run_id": "workflow-run-1", "reason": "No"}) in runtime.calls


@pytest.mark.asyncio
async def test_yachiyo_studio_planner_route_returns_public_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PlannerService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def plan_task(
            self,
            prompt: str,
            *,
            allowed_tools: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
        ):
            self.calls.append(
                {
                    "prompt": prompt,
                    "allowed_tools": allowed_tools,
                    "metadata": metadata,
                }
            )
            return RuntimePlanner().decision(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata,
            )

    service = PlannerService()
    monkeypatch.setattr(
        yachiyo_studio_tool_handlers,
        "studio_service",
        lambda _request=None: service,
    )

    response = await yachiyo.plan_studio_task(
        yachiyo.PlanTaskBody(
            prompt="打开 PixelForge 并点击导出按钮",
            allowed_tools=["desktop.running_apps", "app.open", "desktop.click_ui_element"],
            metadata={"surface": "studio"},
        ),
        None,
    )

    assert response["selected_intent"]["kind"] == "desktop_operation"
    assert response["plan"]["tool_plan"]["steps"][1]["tool_name"] == "app.open"
    assert service.calls == [
        {
            "prompt": "打开 PixelForge 并点击导出按钮",
            "allowed_tools": ["desktop.running_apps", "app.open", "desktop.click_ui_element"],
            "metadata": {"surface": "studio"},
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_task_plan_route_returns_shared_execution_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PlannerService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def plan_chat_execution(
            self,
            prompt: str,
            *,
            allowed_tools: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
            direct: bool = False,
        ):
            self.calls.append(
                {
                    "prompt": prompt,
                    "allowed_tools": allowed_tools,
                    "metadata": metadata,
                    "direct": direct,
                }
            )
            decision = RuntimePlanner().decision(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata,
            )
            return runtime_execution_envelope_from_decision(
                decision,
                allowed_tools=allowed_tools,
                direct=direct,
            )

    service = PlannerService()
    monkeypatch.setattr(
        yachiyo_chat_handlers,
        "agent_service",
        lambda _request=None: service,
    )

    response = await yachiyo.plan_task_execution(
        yachiyo.PlanExecutionBody(
            prompt="请分析 data/sales.csv 并输出报告",
            allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
            metadata={"surface": "chat"},
        ),
        None,
    )

    assert response["intent_kind"] == "data_analysis"
    assert response["task_core"]["workspace"]["workspace_id"].startswith("task-workspace-")
    assert response["requests"][0]["tool_name"] == "data.analyze"
    assert response["requests"][0]["step_id"] == "analyze-data-file"
    assert response["requests"][0]["capability_id"] == "data.analysis"
    assert response["requests"][0]["replan_signal_ids"]
    assert service.calls == [
        {
            "prompt": "请分析 data/sales.csv 并输出报告",
            "allowed_tools": ["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
            "metadata": {"surface": "chat"},
            "direct": False,
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_studio_execution_route_returns_shared_execution_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PlannerService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def plan_execution(
            self,
            prompt: str,
            *,
            allowed_tools: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
            direct: bool = False,
        ):
            self.calls.append(
                {
                    "prompt": prompt,
                    "allowed_tools": allowed_tools,
                    "metadata": metadata,
                    "direct": direct,
                }
            )
            decision = RuntimePlanner().decision(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata,
            )
            return runtime_execution_envelope_from_decision(
                decision,
                allowed_tools=allowed_tools,
                direct=direct,
            )

    service = PlannerService()
    monkeypatch.setattr(
        yachiyo_studio_tool_handlers,
        "studio_service",
        lambda _request=None: service,
    )

    response = await yachiyo.plan_studio_execution(
        yachiyo.PlanExecutionBody(
            prompt="请分析 data/sales.csv 并输出报告",
            allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
            metadata={"surface": "studio"},
            direct=True,
        ),
        None,
    )

    assert response["intent_kind"] == "data_analysis"
    assert response["requests"][0]["tool_name"] == "data.analyze"
    assert response["requests"][0]["step_id"] == "analyze-data-file"
    assert response["requests"][0]["capability_id"] == "data.analysis"
    assert response["requests"][0]["replan_signal_ids"]
    assert response["task_core"]["todos"][0]["step_id"] == "analyze-data-file"
    assert service.calls == [
        {
            "prompt": "请分析 data/sales.csv 并输出报告",
            "allowed_tools": ["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
            "metadata": {"surface": "studio"},
            "direct": True,
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_studio_planner_orchestration_route_starts_public_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PlannerOrchestrationService:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def start_planner_orchestration(self, request):
            payload = request.model_dump(exclude_none=True)
            self.calls.append(payload)
            decision = RuntimePlanner().decision(
                payload["prompt"],
                allowed_tools=payload.get("allowed_tools") or ["workflow.run"],
                metadata=payload.get("metadata"),
            )
            return PlannerOrchestrationStartSnapshot(
                kind="workflow",
                status="started",
                decision=decision,
                target_id="workflow-1",
                target_name=payload.get("target_name"),
                objective=payload.get("objective") or payload["prompt"],
                title=payload.get("title") or "Workflow run",
                workflow_run=WorkflowRunSnapshot(
                    run_id="workflow-run-1",
                    workflow_run_id="workflow-run-1",
                    workflow_id="workflow-1",
                    status="running",
                    objective=payload.get("objective") or payload["prompt"],
                ),
            )

    service = PlannerOrchestrationService()
    monkeypatch.setattr(
        yachiyo_studio_tool_handlers,
        "studio_service",
        lambda _request=None: service,
    )

    response = await yachiyo.start_studio_planner_orchestration(
        yachiyo.StartPlannerOrchestrationBody(
            prompt="运行 Review workflow",
            target_name="Review workflow",
            objective="Build report",
            title="Run Review workflow",
            allowed_tools=["workflow.run"],
            client_run_id="studio-planner-1",
            metadata={"surface": "studio"},
        ),
        None,
    )

    assert response["kind"] == "workflow"
    assert response["status"] == "started"
    assert response["decision"]["selected_intent"]["kind"] == "workflow_orchestration"
    assert response["workflow_run"]["workflow_id"] == "workflow-1"
    assert service.calls == [
        {
            "prompt": "运行 Review workflow",
            "allowed_tools": ["workflow.run"],
            "metadata": {"surface": "studio"},
            "objective": "Build report",
            "title": "Run Review workflow",
            "target_name": "Review workflow",
            "client_run_id": "studio-planner-1",
        }
    ]


@pytest.mark.asyncio
async def test_yachiyo_studio_routes_wrap_legacy_runtime_shapes(tmp_path: Path) -> None:
    runtime = _FakeAgentRuntime()
    runtime.agent_workspaces_dir = tmp_path / "agent-workspaces"
    request = _request(runtime)

    agents = await yachiyo.list_studio_agents(request)
    agent = await yachiyo.get_studio_agent("agent-1", request)
    groups = await yachiyo.list_studio_groups(request)
    group = await yachiyo.get_studio_group("group-run-1", request)
    started_group_run = await yachiyo.start_studio_group_run(
        "group-run-1",
        yachiyo.StartGroupRunBody(
            objective="Compare designs",
            client_run_id="client-group-1",
        ),
        request,
    )
    saved_agent = await yachiyo.save_studio_agent(
        yachiyo.SaveAgentRequest(agent_id="agent-1", name="Writer"),
        request,
    )
    updated_agent = await yachiyo.update_studio_agent(
        "agent-1",
        yachiyo.SaveAgentRequest(name="Updated Writer"),
        request,
    )
    deleted_agent = await yachiyo.delete_studio_agent("agent-1", request)
    model_test = await yachiyo.test_studio_agent_model("agent-1", request)
    agent_desk = await yachiyo.get_studio_agent_desk("agent-1", request)
    agent_desk_note = await yachiyo.write_studio_agent_desk_note(
        "agent-1",
        yachiyo.SaveAgentDeskNoteRequest(content="# Notes"),
        request,
    )
    agent_desk_file = await yachiyo.write_studio_agent_desk_file(
        "agent-1",
        yachiyo.SaveAgentDeskFileRequest(path="inputs/brief.md", content="Brief"),
        request,
    )
    agent_desk_file_event = await yachiyo.trigger_studio_agent_desk_file_event(
        "agent-1",
        yachiyo.AgentDeskFileEventRequest(path="inputs/brief.md", event_type="modified"),
        request,
    )
    agent_with_skill = await yachiyo.attach_studio_agent_skill(
        "agent-1",
        yachiyo.AgentSkillBody(skill_id="skill-1"),
        request,
    )
    agent_without_skill = await yachiyo.detach_studio_agent_skill("agent-1", "skill-1", request)
    skills = await yachiyo.list_studio_skills(request)
    updated_skill = await yachiyo.update_studio_skill(
        "skill-1",
        yachiyo.SkillUpdateBody(enabled=False, folder_id="folder-2"),
        request,
    )
    deleted_skill = await yachiyo.delete_studio_skill("skill-1", request)
    skill_folders = await yachiyo.list_studio_skill_folders(request)
    saved_skill_folder = await yachiyo.create_studio_skill_folder(
        yachiyo.SkillFolderBody(name="New Folder"),
        request,
    )
    updated_skill_folder = await yachiyo.update_studio_skill_folder(
        "folder-1",
        yachiyo.SkillFolderBody(name="Renamed"),
        request,
    )
    deleted_skill_folder = await yachiyo.delete_studio_skill_folder(
        "folder-1",
        True,
        request,
    )
    skill_sources = await yachiyo.list_studio_skill_sources(request)
    imported_skill = await yachiyo.import_studio_skill(
        yachiyo.SkillImportBody(source_path="/skills/imported", folder_id="folder-1"),
        request,
    )
    sync_result = await yachiyo.sync_studio_native_skills(request)
    install_result = await yachiyo.install_studio_skill(
        yachiyo.SkillInstallBody(command="npx skills add reviewer", folder_id="folder-1"),
        request,
    )
    memories = await yachiyo.list_studio_memories(True, 10, request)
    created_memory = await yachiyo.create_studio_memory(
        yachiyo.MemoryBody(content="Remember concise updates"),
        request,
    )
    updated_memory = await yachiyo.update_studio_memory(
        "memory-1",
        yachiyo.MemoryBody(content="Prefer detailed updates"),
        request,
    )
    deleted_memory = await yachiyo.delete_studio_memory(
        "memory-1",
        "studio_user_delete",
        request,
    )
    future_tasks = await yachiyo.list_studio_future_tasks(False, 5, request)
    cancelled_future_task = await yachiyo.cancel_studio_future_task(
        "future-1",
        yachiyo.FutureTaskCancelBody(reason="studio_user_cancel"),
        request,
    )
    triggered_future_tasks = await yachiyo.trigger_due_studio_future_tasks(
        yachiyo.FutureTaskTriggerBody(limit=3),
        request,
    )
    agent_run = await yachiyo.start_studio_agent_run(
        "agent-1",
        yachiyo.StartAgentRunBody(objective="Draft summary", client_run_id="client-agent-1"),
        request,
    )
    workflows = await yachiyo.list_studio_workflows(request)
    workflow = await yachiyo.get_studio_workflow("workflow-1", request)
    updated_workflow = await yachiyo.update_studio_workflow(
        "workflow-1",
        yachiyo.SaveWorkflowRequest(name="Updated Workflow"),
        request,
    )
    deleted_workflow = await yachiyo.delete_studio_workflow("workflow-1", request)
    workflow_run = await yachiyo.start_studio_workflow_run(
        "workflow-1",
        yachiyo.StartWorkflowRunBody(objective="Build report"),
        request,
    )
    runs = await yachiyo.list_studio_runs(request, limit=5)
    run_detail = await yachiyo.get_studio_run("run-1", request)
    timeline = await yachiyo.get_studio_run_timeline("run-1", request)
    workflow_timeline = await yachiyo.get_studio_run_timeline("workflow-run-1", request)
    group_runs = await yachiyo.list_studio_group_runs(request, limit=5)
    group_run = await yachiyo.get_studio_group_run("group-run-1", request)
    group_run_events = await yachiyo.get_studio_group_run_events(
        "group-run-1",
        request,
        after_sequence=0,
        limit=1,
    )
    events = await yachiyo.get_studio_run_events("run-1", request, after_sequence=0, limit=1)
    rerun = await yachiyo.rerun_studio_run("run-1", request)
    scoped_rerun = await yachiyo.rerun_studio_run(
        "workflow-run-1",
        request,
        yachiyo.RerunRunBody(
            scope="workflow_branch",
            workflow_node_id="route",
            workflow_edge_branch="true",
            workflow_node_selected_target="ship",
            reason="Retry selected branch",
        ),
    )
    cancelled = await yachiyo.cancel_studio_run("run-1", request)
    deleted_run = await yachiyo.delete_studio_run("run-1", request)
    approved = await yachiyo.approve_studio_run_approval("run-1", request)
    rejected = await yachiyo.reject_studio_run_approval(
        "run-1",
        yachiyo.TaskApprovalRequest(reason="No"),
        request,
    )
    artifact = await yachiyo.get_studio_run_artifact("run-1", "reports/final.md", request)

    assert agents["agents"][0]["agent_id"] == "agent-1"
    assert agent["agent_id"] == "agent-1"
    assert groups["groups"][0]["group_id"] == "group-run-1"
    assert groups["groups"][0]["mode"] == "pipeline"
    assert groups["groups"][0]["members"][0]["agent_id"] == "agent-1"
    assert group["group_id"] == "group-run-1"
    assert started_group_run["group_id"] == "group-run-1"
    assert started_group_run["participants"][0]["agent_id"] == "agent-1"
    assert started_group_run["runs"][0]["run_id"] == "run-1"
    assert saved_agent["model_config"] == {"provider": "model_profile"}
    assert updated_agent["agent_id"] == "agent-1"
    assert updated_agent["name"] == "Updated Writer"
    assert deleted_agent == {"ok": True, "agent_id": "agent-1"}
    assert agent_run["run_id"] == "agent-run-1"
    assert agent_run["agent_id"] == "agent-1"
    assert model_test == {"ok": True, "message": "Model ready"}
    assert agent_desk["agent_id"] == "agent-1"
    assert agent_desk["root_path"].startswith(str(tmp_path / "agent-workspaces"))
    assert agent_desk_note["items"][0]["path"] == "desk-notes.md"
    assert agent_desk_note["items"][0]["kind"] == "note"
    assert agent_desk_note["items"][0]["preview_text"] == "# Notes"
    assert any(item["path"] == "inputs/brief.md" for item in agent_desk_file["items"])
    assert (Path(agent_desk_file["root_path"]) / "inputs" / "brief.md").read_text(
        encoding="utf-8"
    ) == "Brief"
    assert agent_desk_file_event["future_task_id"] == "future-desk-1"
    assert agent_desk_file_event["title"] == "Review Agent Desk file: inputs/brief.md"
    assert agent_desk_file_event["runnable_id"] == "agent-1"
    assert agent_desk_file_event["source_run_id"] == "agent_desk_file_event"
    assert agent_with_skill["skill_ids"] == ["skill-1"]
    assert agent_without_skill["skill_ids"] == []
    assert skills["skills"][0]["skill_id"] == "skill-1"
    assert skills["skills"][0]["asset_paths"] == ["assets/icon.png"]
    assert updated_skill["enabled"] is False
    assert updated_skill["folder_id"] == "folder-2"
    assert deleted_skill == {"ok": True, "skill_id": "skill-1"}
    assert skill_folders["folders"][0]["folder_id"] == "folder-1"
    assert skill_folders["uncategorized"]["folder_id"] == ""
    assert saved_skill_folder["name"] == "New Folder"
    assert updated_skill_folder["name"] == "Renamed"
    assert deleted_skill_folder == {"ok": True, "deleted_skill_count": 2}
    assert skill_sources["roots"][0]["path"] == "/skills/native"
    assert imported_skill["skill_id"] == "skill-imported"
    assert imported_skill["folder_id"] == "folder-1"
    assert sync_result == {"ok": True, "summary": {"imported": 1}}
    assert install_result["installer"] == "npx_skills"
    assert memories["memories"][0]["memory_id"] == "memory-1"
    assert memories["memories"][0]["source_run_id"] == "run-1"
    assert created_memory["memory_id"] == "memory-created"
    assert updated_memory["content"] == "Prefer detailed updates"
    assert deleted_memory == {"ok": True, "memory_id": "memory-1"}
    assert future_tasks["future_tasks"][0]["future_task_id"] == "future-1"
    assert cancelled_future_task["future_task"]["status"] == "cancelled"
    assert triggered_future_tasks["triggered"][0]["future_task"]["last_run_id"] == "run-1"
    assert triggered_future_tasks["triggered"][0]["run"]["run_id"] == "run-1"
    assert workflows["workflows"][0]["workflow_id"] == "workflow-1"
    assert workflow["workflow_id"] == "workflow-1"
    assert updated_workflow["workflow_id"] == "workflow-1"
    assert updated_workflow["name"] == "Updated Workflow"
    assert deleted_workflow == {"ok": True, "workflow_id": "workflow-1"}
    assert workflow_run["workflow_run_id"] == "workflow-run-1"
    assert workflow_run["workflow_id"] == "workflow-1"
    assert workflow_run["objective"] == "Build report"
    assert workflow_run["run_id"] == "workflow-run-1"
    assert runs["runs"][0]["run_id"] == "studio-run"
    assert run_detail["run_id"] == "run-1"
    assert timeline["run_group_id"] == "group-run-1"
    assert timeline["pending_approval"]["tool_name"] == "terminal.run"
    assert workflow_timeline["workflow_id"] == "workflow-1"
    assert workflow_timeline["objective"] == "Build report"
    assert workflow_timeline["current_node_id"] == "node-start"
    assert workflow_timeline["current_node_label"] == "Start"
    assert workflow_timeline["final_answer"] == "Workflow final answer"
    assert group_runs["group_runs"][0]["group_run_id"] == "group-run-1"
    assert group_runs["group_runs"][0]["runs"][0]["run_id"] == "run-1"
    assert group_run["run_group_id"] == "group-run-1"
    assert group_run["child_run_ids"] == ["run-1"]
    assert group_run_events["run_id"] == "group-run-1"
    assert group_run_events["after_sequence"] == 0
    assert group_run_events["limit"] == 1
    assert group_run_events["next_after_sequence"] == 1
    assert group_run_events["has_more"] is True
    assert group_run_events["events"][0]["event_type"] == "group.run.started"
    assert events["after_sequence"] == 0
    assert events["limit"] == 1
    assert events["next_after_sequence"] == 1
    assert events["has_more"] is True
    assert events["events"][0]["event_type"] == "agent.started"
    assert rerun["run_id"] == "run-1-rerun"
    assert rerun["rerun_of_run_id"] == "run-1"
    assert rerun["rerun_of_kind"] == "agent_run"
    assert rerun["rerun_of_status"] == "completed"
    assert rerun["rerun_of_runnable_id"] == "agent-1"
    assert rerun["rerun_of_runnable_name"] == "Planner"
    assert rerun["rerun_original_created_at"] == "2026-06-13T00:00:00Z"
    assert rerun["rerun_original_updated_at"] == "2026-06-13T00:00:04Z"
    assert scoped_rerun["events"][0]["payload"]["rerun_scope"] == "workflow_branch"
    assert scoped_rerun["events"][0]["payload"]["workflow_node_id"] == "route"
    assert scoped_rerun["events"][0]["payload"]["workflow_edge_branch"] == "true"
    assert scoped_rerun["events"][0]["payload"]["workflow_node_selected_target"] == "ship"
    assert cancelled["status"] == "cancelled"
    assert deleted_run == {"ok": True, "deleted_run_ids": ["run-1"], "deleted_run_count": 1}
    assert approved["status"] == "completed"
    assert rejected["status"] == "failed"
    assert artifact["ok"] is True
    assert artifact["run_id"] == "run-1"
    assert artifact["path"] == "reports/final.md"
    assert artifact["content"] == "# Report"
    assert artifact["truncated"] is False
    assert ("rerun_run", "run-1") in runtime.calls
    assert (
        "rerun_run",
        {
            "run_id": "workflow-run-1",
            "request": {
                "scope": "workflow_branch",
                "workflow_node_id": "route",
                "workflow_edge_branch": "true",
                "workflow_node_selected_target": "ship",
                "reason": "Retry selected branch",
                "metadata": {},
            },
        },
    ) in runtime.calls
    assert ("cancel_run", "run-1") in runtime.calls
    assert ("delete_run", "run-1") in runtime.calls
    assert ("approve_run_approval", "run-1") in runtime.calls
    assert ("reject_run_approval", {"run_id": "run-1", "reason": "No"}) in runtime.calls
    assert (
        "update_agent",
        {"agent_id": "agent-1", "payload": {"agent_id": "agent-1", "name": "Writer"}},
    ) in runtime.calls
    assert (
        "update_agent",
        {"agent_id": "agent-1", "payload": {"agent_id": "agent-1", "name": "Updated Writer"}},
    ) in runtime.calls
    assert ("delete_agent", "agent-1") in runtime.calls
    assert ("test_agent_model", "agent-1") in runtime.calls
    assert ("attach_skill", {"agent_id": "agent-1", "skill_id": "skill-1"}) in runtime.calls
    assert ("detach_skill", {"agent_id": "agent-1", "skill_id": "skill-1"}) in runtime.calls
    assert ("list_skills", None) in runtime.calls
    assert (
        "update_skill",
        {"skill_id": "skill-1", "payload": {"enabled": False, "folder_id": "folder-2"}},
    ) in runtime.calls
    assert ("delete_skill", "skill-1") in runtime.calls
    assert ("list_skill_folders", None) in runtime.calls
    assert ("create_skill_folder", {"name": "New Folder"}) in runtime.calls
    assert (
        "update_skill_folder",
        {"folder_id": "folder-1", "payload": {"name": "Renamed"}},
    ) in runtime.calls
    assert (
        "delete_skill_folder",
        {"folder_id": "folder-1", "delete_skills": True},
    ) in runtime.calls
    assert ("list_native_skill_sources", None) in runtime.calls
    assert (
        "import_skill",
        {"source_path": "/skills/imported", "folder_id": "folder-1"},
    ) in runtime.calls
    assert ("sync_native_skills", None) in runtime.calls
    assert (
        "install_skill_command",
        {"command": "npx skills add reviewer", "folder_id": "folder-1"},
    ) in runtime.calls
    assert ("list_memory_items", {"include_deleted": True, "limit": 10}) in runtime.calls
    assert ("create_memory_item", {"content": "Remember concise updates"}) in runtime.calls
    assert (
        "update_memory_item",
        {"memory_id": "memory-1", "payload": {"content": "Prefer detailed updates"}},
    ) in runtime.calls
    assert (
        "delete_memory_item",
        {"memory_id": "memory-1", "reason": "studio_user_delete"},
    ) in runtime.calls
    assert ("list_future_tasks", {"include_finished": False, "limit": 5}) in runtime.calls
    assert (
        "cancel_future_task",
        {"future_task_id": "future-1", "reason": "studio_user_cancel"},
    ) in runtime.calls
    assert (
        "trigger_due_future_tasks",
        {"now_epoch": None, "limit": 3},
    ) in runtime.calls
    desk_file_event_calls = [call for call in runtime.calls if call[0] == "schedule_future_task"]
    assert desk_file_event_calls
    assert desk_file_event_calls[0][1]["source_run_id"] == "agent_desk_file_event"
    assert desk_file_event_calls[0][1]["payload"]["runnable_id"] == "agent-1"
    assert desk_file_event_calls[0][1]["payload"]["delay_seconds"] == 0
    assert "Use read-only tools first" in desk_file_event_calls[0][1]["payload"]["prompt"]
    assert (
        "update_workflow",
        {"workflow_id": "workflow-1", "payload": {"workflow_id": "workflow-1", "name": "Updated Workflow"}},
    ) in runtime.calls
    assert ("delete_workflow", "workflow-1") in runtime.calls
    assert ("list_runs", 5) in runtime.calls
    assert ("list_run_groups", 5) in runtime.calls
    assert (
        "create_agent_run",
        {
            "agent_id": "agent-1",
            "user_goal": "Draft summary",
                "source": "yachiyo_studio",
                "client_run_id": "client-agent-1",
                "run_group_id": None,
                "daily_desktop_policy_overlay": True,
                "runtime_planner_entrypoint": True,
            },
        ) in runtime.calls
    group_started_events = [
        call[1]
        for call in runtime.calls
        if call[0] == "append_run_event"
        and call[1]["event_type"] == "group.member.started"
    ]
    assert group_started_events
    group_started_payload = group_started_events[0]["payload"]
    assert group_started_events[0]["run_id"] == "run-1"
    assert group_started_payload["agent_id"] == "agent-1"
    assert group_started_payload["agent_name"] == "Planner"
    assert group_started_payload["group_id"] == "group-run-1"
    assert group_started_payload["group_name"] == "Run group"
    assert group_started_payload["group_mode"] == "pipeline"
    assert group_started_payload["group_memory_scope"] == "shared"
    assert group_started_payload["member_index"] == 0
    assert group_started_payload["member_role"] == "agent_run"
    assert group_started_payload["objective"] == "Compare designs"
    assert group_started_payload["run_group_id"] == "group-run-1"
    assert group_started_payload["run_id"] == "run-1"
    assert group_started_payload["status"] == "approval_required"
    assert group_started_payload["client_run_id"] == "client-group-1"
    assert group_started_payload["child_client_run_id"] == "client-group-1:0:agent-1"
    assert (
        "read_run_artifact",
        {"run_id": "run-1", "artifact_path": "reports/final.md"},
    ) in runtime.calls


@pytest.mark.asyncio
async def test_yachiyo_studio_routes_preserve_runtime_debug_snapshot_fields() -> None:
    runtime = _FakeAgentRuntime()
    runtime.runs["run-observable"] = _observable_run_payload("run-observable")
    runtime.runs["run-1"] = _observable_run_payload("run-1")
    runtime.task_links["task-observable"] = {
        "task_id": "task-observable",
        "run_id": "run-observable",
        "session_id": "chat-observable",
        "run_status": "approval_required",
        "last_event_sequence": 4,
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:04Z",
    }
    request = _request(runtime)

    runs = await yachiyo.list_studio_runs(request, limit=5)
    timeline = await yachiyo.get_studio_run_timeline("run-observable", request)
    group_runs = await yachiyo.list_studio_group_runs(request, limit=5)
    group_run = await yachiyo.get_studio_group_run("group-run-1", request)
    workflows = await yachiyo.list_studio_workflows(request)

    listed_run = runs["runs"][0]
    assert listed_run["run_id"] == "run-observable"
    assert listed_run["task_id"] == "task-observable"
    assert listed_run["task_run_link_last_event_sequence"] == 4
    assert listed_run["planner_summary"]["intent_kind"] == "data_analysis"
    assert listed_run["planner_summary"]["plan_tools"] == [
        "workspace.read",
        "terminal.run",
        "artifact.write",
    ]
    assert listed_run["tool_calls"][0]["tool_name"] == "terminal.run"
    assert listed_run["pending_approval"]["tool_name"] == "terminal.run"
    assert listed_run["artifacts"][0]["path"] == "reports/observable.md"

    assert timeline["memory_traces"][0]["memory_id"] == "memory-observable"
    assert timeline["skill_traces"][0]["skill_id"] == "skill-observable"
    assert timeline["artifacts"][1]["artifact_id"] == "artifact-event-observable"
    assert timeline["events"][0]["event_type"] == "memory.retrieved"

    listed_group_run = group_runs["group_runs"][0]
    assert listed_group_run["group_run_id"] == "group-run-1"
    assert listed_group_run["runs"][0]["run_id"] == "run-1"
    assert listed_group_run["runs"][0]["planner_summary"]["intent_kind"] == "data_analysis"
    assert listed_group_run["tool_calls"][0]["tool_name"] == "terminal.run"
    assert listed_group_run["pending_approvals"][0]["approval_id"] == "approval-run-1"
    assert listed_group_run["shared_artifacts"][0]["group_run_id"] == "group-run-1"
    assert listed_group_run["memory_traces"][0]["memory_id"] == "memory-observable"
    assert listed_group_run["skill_traces"][0]["skill_id"] == "skill-observable"

    assert group_run["child_run_ids"] == ["run-1"]
    assert group_run["runs"][0]["artifacts"][0]["path"] == "reports/observable.md"
    assert workflows["workflows"][0]["nodes"][0]["type"] == "start"


@pytest.mark.asyncio
async def test_yachiyo_studio_tool_catalog_route_surfaces_desktop_tool_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        legacy_ports,
        "desktop_permission_missing_by_capability",
        lambda: {
            "media_control": ["music_app"],
            "browser_control": ["chrome_cdp"],
        },
    )
    monkeypatch.setattr(
        legacy_ports,
        "desktop_runtime_blocking_conditions_by_capability",
        lambda: {
            "foreground_input": ["desktop_session_locked", "screen_capture_blank"],
            "screen_capture": ["screen_capture_blank"],
        },
    )
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    catalog = await yachiyo.list_studio_tools(request)
    tools = {tool["tool_name"]: tool for tool in catalog["tools"]}
    plugins = {plugin["plugin_id"]: plugin for plugin in catalog["plugins"]}

    assert tools["media.apple_music_play"]["capability_id"] == "media_control"
    assert tools["media.apple_music_play"]["risk_level"] == "low"
    assert tools["media.apple_music_play"]["input_schema"]["required"] == ["query"]
    assert tools["media.apple_music_play"]["missing_permissions"] == ["music_app"]
    assert any("Music" in note for note in tools["media.apple_music_play"]["fallback_notes"])
    assert tools["media.apple_music_open_and_play"]["capability_id"] == "media_control"
    assert tools["media.apple_music_open_and_play"]["risk_level"] == "low"
    assert tools["media.apple_music_open_and_play"]["input_schema"].get("required", []) == []
    assert tools["media.apple_music_open_and_play"]["missing_permissions"] == ["music_app"]
    assert any("Music" in note for note in tools["media.apple_music_open_and_play"]["fallback_notes"])
    assert tools["media.apple_music_control"]["capability_id"] == "media_control"
    assert tools["media.apple_music_control"]["risk_level"] == "low"
    assert tools["media.apple_music_control"]["input_schema"]["required"] == ["action"]
    assert tools["media.apple_music_control"]["missing_permissions"] == ["music_app"]
    assert tools["media.music_app_open_and_play"]["capability_id"] == "media_control"
    assert tools["media.music_app_open_and_play"]["risk_level"] == "low"
    assert tools["media.music_app_open_and_play"]["input_schema"]["required"] == ["app_name"]
    assert tools["media.music_app_open_and_play"]["missing_permissions"] == []
    assert any(
        "media play key" in note
        for note in tools["media.music_app_open_and_play"]["fallback_notes"]
    )
    assert tools["system.settings_open"]["capability_id"] == "app_control"
    assert tools["system.settings_open"]["risk_level"] == "low"
    assert tools["system.settings_open"]["input_schema"]["required"] == ["target"]
    assert tools["system.settings_open"]["missing_permissions"] == []
    assert any(
        "does not change settings" in note
        for note in tools["system.settings_open"]["fallback_notes"]
    )
    assert tools["system.volume"]["capability_id"] == "desktop_execution"
    assert tools["system.volume"]["risk_level"] == "low"
    assert tools["system.volume"]["input_schema"]["required"] == ["action"]
    assert any("volume" in note for note in tools["system.volume"]["fallback_notes"])
    assert tools["system.brightness"]["capability_id"] == "desktop_execution"
    assert tools["system.brightness"]["risk_level"] == "low"
    assert tools["system.brightness"]["input_schema"]["required"] == ["action"]
    assert any("brightness key events" in note for note in tools["system.brightness"]["fallback_notes"])
    assert tools["system.display_sleep"]["capability_id"] == "desktop_execution"
    assert tools["system.display_sleep"]["risk_level"] == "low"
    assert tools["system.display_sleep"]["input_schema"]["required"] == []
    assert any("displaysleepnow" in note for note in tools["system.display_sleep"]["fallback_notes"])
    assert tools["system.screen_saver_start"]["capability_id"] == "desktop_execution"
    assert tools["system.screen_saver_start"]["risk_level"] == "low"
    assert tools["system.screen_saver_start"]["input_schema"]["required"] == []
    assert any("ScreenSaverEngine" in note for note in tools["system.screen_saver_start"]["fallback_notes"])
    assert tools["clipboard.write"]["capability_id"] == "desktop_execution"
    assert tools["clipboard.write"]["risk_level"] == "low"
    assert tools["clipboard.write"]["input_schema"]["required"] == ["text"]
    assert any("clipboard" in note for note in tools["clipboard.write"]["fallback_notes"])
    assert tools["desktop.running_apps"]["capability_id"] == "active_window"
    assert tools["desktop.running_apps"]["risk_level"] == "low"
    assert any("foreground app list" in note for note in tools["desktop.running_apps"]["fallback_notes"])
    assert tools["desktop.safe_type_text"]["blocking_conditions"] == [
        "desktop_session_locked",
        "screen_capture_blank",
    ]
    assert tools["screen.capture"]["blocking_conditions"] == ["screen_capture_blank"]
    assert catalog["capabilities"]["foreground_input"]["blocking_conditions"] == [
        "desktop_session_locked",
        "screen_capture_blank",
    ]
    assert catalog["capabilities"]["screen_capture"]["blocking_conditions"] == [
        "screen_capture_blank"
    ]
    assert tools["desktop.windows"]["capability_id"] == "active_window"
    assert tools["desktop.windows"]["risk_level"] == "low"
    assert any("window titles" in note for note in tools["desktop.windows"]["fallback_notes"])
    assert tools["desktop.ui_elements"]["capability_id"] == "active_window"
    assert tools["desktop.ui_elements"]["risk_level"] == "low"
    assert tools["desktop.ui_elements"]["input_schema"]["properties"]["role_filter"]["type"] == "string"
    assert any("UI controls" in note for note in tools["desktop.ui_elements"]["fallback_notes"])
    assert tools["app.status"]["capability_id"] == "app_control"
    assert tools["app.status"]["risk_level"] == "low"
    assert tools["app.status"]["input_schema"]["required"] == ["app_name"]
    assert tools["app.focus_window"]["capability_id"] == "app_control"
    assert tools["app.focus_window"]["risk_level"] == "low"
    assert tools["app.focus_window"]["input_schema"]["required"] == [
        "app_name",
        "title_contains",
    ]
    assert any(
        "matching app window" in note
        for note in tools["app.focus_window"]["fallback_notes"]
    )
    assert tools["app.open_and_safe_type_text"]["capability_id"] == "foreground_input"
    assert tools["app.open_and_safe_type_text"]["risk_level"] == "low"
    assert tools["app.open_and_safe_type_text"]["input_schema"]["required"] == [
        "app_name",
        "text",
    ]
    assert any(
        "typing only text explicitly provided" in note
        for note in tools["app.open_and_safe_type_text"]["fallback_notes"]
    )
    assert tools["app.focus_and_safe_shortcut"]["capability_id"] == "foreground_input"
    assert tools["app.focus_and_safe_shortcut"]["risk_level"] == "low"
    assert tools["app.focus_and_safe_shortcut"]["input_schema"]["required"] == [
        "app_name",
        "action",
    ]
    assert "paste" in tools["app.focus_and_safe_shortcut"]["input_schema"]["properties"]["action"]["enum"]
    assert "new_document" in tools["app.focus_and_safe_shortcut"]["input_schema"]["properties"]["action"]["enum"]
    assert "new_event" in tools["app.focus_and_safe_shortcut"]["input_schema"]["properties"]["action"]["enum"]
    assert tools["app.open_and_safe_key"]["capability_id"] == "foreground_input"
    assert tools["app.open_and_safe_key"]["risk_level"] == "low"
    assert tools["app.open_and_safe_key"]["input_schema"]["required"] == [
        "app_name",
        "action",
    ]
    assert "tab" in tools["app.open_and_safe_key"]["input_schema"]["properties"]["action"]["enum"]
    assert "return" not in tools["app.open_and_safe_key"]["input_schema"]["properties"]["action"]["enum"]
    assert any(
        "whitelisted foreground navigation keys" in note
        for note in tools["app.open_and_safe_key"]["fallback_notes"]
    )
    assert tools["app.focus_and_safe_key"]["capability_id"] == "foreground_input"
    assert tools["app.focus_and_safe_key"]["risk_level"] == "low"
    assert tools["app.focus_and_safe_key"]["input_schema"]["required"] == [
        "app_name",
        "action",
    ]
    assert "arrow_down" in tools["app.focus_and_safe_key"]["input_schema"]["properties"]["action"]["enum"]
    assert tools["app.open_and_hotkey"]["capability_id"] == "foreground_input"
    assert tools["app.open_and_hotkey"]["risk_level"] == "medium"
    assert tools["app.open_and_hotkey"]["input_schema"]["required"] == [
        "app_name",
        "key",
    ]
    assert "command" in tools["app.open_and_hotkey"]["input_schema"]["properties"]["modifiers"]["items"]["enum"]
    assert any(
        "approval is required" in note
        for note in tools["app.open_and_hotkey"]["fallback_notes"]
    )
    assert tools["app.focus_and_hotkey"]["capability_id"] == "foreground_input"
    assert tools["app.focus_and_hotkey"]["risk_level"] == "medium"
    assert tools["app.focus_and_hotkey"]["input_schema"]["required"] == [
        "app_name",
        "key",
    ]
    assert tools["app.open_and_safe_scroll"]["capability_id"] == "foreground_input"
    assert tools["app.open_and_safe_scroll"]["risk_level"] == "low"
    assert tools["app.open_and_safe_scroll"]["input_schema"]["required"] == [
        "app_name",
        "direction",
    ]
    assert tools["app.open_and_safe_scroll"]["input_schema"]["properties"]["direction"]["enum"] == [
        "up",
        "down",
    ]
    assert any(
        "explicit foreground up/down page requests" in note
        for note in tools["app.open_and_safe_scroll"]["fallback_notes"]
    )
    assert tools["app.focus_and_safe_scroll"]["capability_id"] == "foreground_input"
    assert tools["app.focus_and_safe_scroll"]["risk_level"] == "low"
    assert tools["app.focus_and_safe_scroll"]["input_schema"]["required"] == [
        "app_name",
        "direction",
    ]
    assert tools["app.focus_and_safe_scroll"]["input_schema"]["properties"]["direction"]["enum"] == [
        "up",
        "down",
    ]
    assert tools["app.open_and_safe_click"]["capability_id"] == "foreground_input"
    assert tools["app.open_and_safe_click"]["risk_level"] == "low"
    assert tools["app.open_and_safe_click"]["input_schema"]["required"] == [
        "app_name",
        "x",
        "y",
    ]
    assert tools["app.open_and_safe_click"]["input_schema"]["properties"]["x"]["type"] == "number"
    assert any(
        "coordinates explicitly provided by the user" in note
        for note in tools["app.open_and_safe_click"]["fallback_notes"]
    )
    assert tools["app.focus_and_safe_click"]["capability_id"] == "foreground_input"
    assert tools["app.focus_and_safe_click"]["risk_level"] == "low"
    assert tools["app.focus_and_safe_click"]["input_schema"]["required"] == [
        "app_name",
        "x",
        "y",
    ]
    assert tools["app.focus_and_safe_click"]["input_schema"]["properties"]["y"]["type"] == "number"
    assert tools["app.open_and_click_ui_element"]["capability_id"] == "foreground_input"
    assert tools["app.open_and_click_ui_element"]["risk_level"] == "medium"
    assert tools["app.open_and_click_ui_element"]["input_schema"]["required"] == [
        "app_name",
        "target",
    ]
    assert tools["app.open_and_click_ui_element"]["input_schema"]["properties"]["target"]["type"] == "string"
    assert any(
        "approval is required" in note
        for note in tools["app.open_and_click_ui_element"]["fallback_notes"]
    )
    assert tools["app.focus_and_click_ui_element"]["capability_id"] == "foreground_input"
    assert tools["app.focus_and_click_ui_element"]["risk_level"] == "medium"
    assert tools["app.focus_and_click_ui_element"]["input_schema"]["required"] == [
        "app_name",
        "target",
    ]
    assert tools["app.focus_and_click_ui_element"]["input_schema"]["properties"]["click_count"]["maximum"] == 3
    assert tools["app.open_and_type_into_ui_element"]["capability_id"] == "foreground_input"
    assert tools["app.open_and_type_into_ui_element"]["risk_level"] == "medium"
    assert tools["app.open_and_type_into_ui_element"]["input_schema"]["required"] == [
        "app_name",
        "target",
        "text",
    ]
    assert tools["app.open_and_type_into_ui_element"]["input_schema"]["properties"]["target"]["type"] == "string"
    assert any(
        "approval is required" in note
        for note in tools["app.open_and_type_into_ui_element"]["fallback_notes"]
    )
    assert tools["app.focus_and_type_into_ui_element"]["capability_id"] == "foreground_input"
    assert tools["app.focus_and_type_into_ui_element"]["risk_level"] == "medium"
    assert tools["app.focus_and_type_into_ui_element"]["input_schema"]["required"] == [
        "app_name",
        "target",
        "text",
    ]
    assert tools["app.show"]["capability_id"] == "app_control"
    assert tools["app.show"]["risk_level"] == "low"
    assert tools["app.show"]["input_schema"]["required"] == ["app_name"]
    assert any("show, unhide, restore" in note for note in tools["app.show"]["fallback_notes"])
    assert tools["app.hide"]["capability_id"] == "app_control"
    assert tools["app.hide"]["risk_level"] == "low"
    assert tools["app.hide"]["input_schema"]["required"] == ["app_name"]
    assert any("hides a running app" in note for note in tools["app.hide"]["fallback_notes"])
    assert tools["app.minimize"]["capability_id"] == "app_control"
    assert tools["app.minimize"]["risk_level"] == "low"
    assert tools["app.minimize"]["input_schema"]["required"] == ["app_name"]
    assert any(
        "minimizes windows for a running app" in note
        for note in tools["app.minimize"]["fallback_notes"]
    )
    assert tools["app.quit"]["capability_id"] == "app_control"
    assert tools["app.quit"]["risk_level"] == "medium"
    assert tools["app.quit"]["input_schema"]["required"] == ["app_name"]
    assert any("approval" in note for note in tools["app.quit"]["fallback_notes"])
    assert tools["desktop.quit_app"]["capability_id"] == "app_control"
    assert tools["desktop.quit_app"]["risk_level"] == "medium"
    assert tools["desktop.quit_app"]["input_schema"]["properties"] == {}
    assert any("foreground app" in note for note in tools["desktop.quit_app"]["fallback_notes"])
    assert tools["desktop.hide_app"]["capability_id"] == "foreground_input"
    assert tools["desktop.hide_app"]["risk_level"] == "low"
    assert tools["desktop.hide_app"]["input_schema"]["properties"] == {}
    assert any(
        "hides the current foreground app" in note
        for note in tools["desktop.hide_app"]["fallback_notes"]
    )
    assert tools["desktop.safe_shortcut"]["capability_id"] == "foreground_input"
    assert tools["desktop.safe_shortcut"]["risk_level"] == "low"
    assert tools["desktop.safe_shortcut"]["input_schema"]["required"] == ["action"]
    assert "copy" in tools["desktop.safe_shortcut"]["input_schema"]["properties"]["action"]["enum"]
    assert "new_document" in tools["desktop.safe_shortcut"]["input_schema"]["properties"]["action"]["enum"]
    assert "new_event" in tools["desktop.safe_shortcut"]["input_schema"]["properties"]["action"]["enum"]
    assert any(
        "whitelisted common shortcut" in note
        for note in tools["desktop.safe_shortcut"]["fallback_notes"]
    )
    assert tools["desktop.safe_key"]["capability_id"] == "foreground_input"
    assert tools["desktop.safe_key"]["risk_level"] == "low"
    assert tools["desktop.safe_key"]["input_schema"]["required"] == ["action"]
    assert "tab" in tools["desktop.safe_key"]["input_schema"]["properties"]["action"]["enum"]
    assert "return" not in tools["desktop.safe_key"]["input_schema"]["properties"]["action"]["enum"]
    assert any(
        "whitelisted foreground navigation keys" in note
        for note in tools["desktop.safe_key"]["fallback_notes"]
    )
    assert tools["desktop.safe_type_text"]["capability_id"] == "foreground_input"
    assert tools["desktop.safe_type_text"]["risk_level"] == "low"
    assert tools["desktop.safe_type_text"]["input_schema"]["required"] == ["text"]
    assert any(
        "explicitly provided by the user" in note
        for note in tools["desktop.safe_type_text"]["fallback_notes"]
    )
    assert tools["desktop.safe_click"]["capability_id"] == "foreground_input"
    assert tools["desktop.safe_click"]["risk_level"] == "low"
    assert tools["desktop.safe_click"]["input_schema"]["required"] == ["x", "y"]
    assert any(
        "coordinates explicitly provided by the user" in note
        for note in tools["desktop.safe_click"]["fallback_notes"]
    )
    assert tools["desktop.safe_scroll"]["capability_id"] == "foreground_input"
    assert tools["desktop.safe_scroll"]["risk_level"] == "low"
    assert tools["desktop.safe_scroll"]["input_schema"]["required"] == ["direction"]
    assert tools["desktop.safe_scroll"]["input_schema"]["properties"]["direction"]["enum"] == [
        "up",
        "down",
    ]
    assert any(
        "scrolls only explicit foreground up/down page requests" in note
        for note in tools["desktop.safe_scroll"]["fallback_notes"]
    )
    assert tools["desktop.click_ui_element"]["capability_id"] == "foreground_input"
    assert tools["desktop.click_ui_element"]["risk_level"] == "medium"
    assert tools["desktop.click_ui_element"]["input_schema"]["required"] == ["target"]
    assert any(
        "inferred coordinate" in note
        for note in tools["desktop.click_ui_element"]["fallback_notes"]
    )
    assert tools["desktop.type_into_ui_element"]["capability_id"] == "foreground_input"
    assert tools["desktop.type_into_ui_element"]["risk_level"] == "medium"
    assert tools["desktop.type_into_ui_element"]["input_schema"]["required"] == ["target", "text"]
    assert any(
        "types user-provided text" in note
        for note in tools["desktop.type_into_ui_element"]["fallback_notes"]
    )
    assert tools["desktop.minimize_window"]["capability_id"] == "foreground_input"
    assert tools["desktop.minimize_window"]["risk_level"] == "low"
    assert tools["desktop.minimize_window"]["input_schema"]["properties"] == {}
    assert any(
        "minimizes the current foreground window" in note
        for note in tools["desktop.minimize_window"]["fallback_notes"]
    )
    assert tools["desktop.close_window"]["capability_id"] == "foreground_input"
    assert tools["desktop.close_window"]["risk_level"] == "medium"
    assert tools["desktop.close_window"]["input_schema"]["properties"] == {}
    assert any("foreground window" in note for note in tools["desktop.close_window"]["fallback_notes"])
    assert tools["browser.open_url"]["missing_permissions"] == ["chrome_cdp"]
    assert any("Chrome CDP" in note for note in tools["browser.open_url"]["fallback_notes"])
    assert tools["browser.open_url_and_extract_text"]["capability_id"] == "browser_control"
    assert tools["browser.open_url_and_extract_text"]["risk_level"] == "low"
    assert tools["browser.open_url_and_extract_text"]["input_schema"]["required"] == ["url"]
    assert any(
        "text extraction" in note
        for note in tools["browser.open_url_and_extract_text"]["fallback_notes"]
    )
    assert tools["browser.open_url_and_screenshot"]["capability_id"] == "browser_control"
    assert tools["browser.open_url_and_screenshot"]["risk_level"] == "low"
    assert tools["browser.open_url_and_screenshot"]["input_schema"]["required"] == ["url"]
    assert any(
        "captures the page" in note
        for note in tools["browser.open_url_and_screenshot"]["fallback_notes"]
    )
    assert tools["desktop.reveal_path"]["capability_id"] == "desktop_execution"
    assert tools["desktop.reveal_path"]["risk_level"] == "low"
    assert tools["desktop.reveal_path"]["input_schema"]["required"] == ["path"]
    assert any("Finder" in note for note in tools["desktop.reveal_path"]["fallback_notes"])
    assert tools["desktop.open_path"]["capability_id"] == "desktop_execution"
    assert tools["desktop.open_path"]["risk_level"] == "low"
    assert tools["desktop.open_path"]["input_schema"]["required"] == ["path"]
    assert any("unsafe" in note for note in tools["desktop.open_path"]["fallback_notes"])
    assert tools["desktop.submit_foreground"]["capability_id"] == "foreground_input"
    assert tools["desktop.submit_foreground"]["risk_level"] == "high"
    assert tools["desktop.submit_foreground"]["approval_required"] is True
    assert tools["desktop.submit_foreground"]["input_schema"]["required"] == ["action"]
    assert tools["desktop.permissions"]["capability_id"] == "desktop_execution"
    assert tools["desktop.permissions"]["risk_level"] == "low"
    assert tools["desktop.permissions"]["input_schema"]["properties"] == {}
    assert any(
        "missing desktop permission" in note
        for note in tools["desktop.permissions"]["fallback_notes"]
    )
    assert "point=x,y" in tools["browser.click"]["input_schema"]["properties"]["selector"]["description"]
    assert "point=x,y" in tools["browser.type_text"]["input_schema"]["properties"]["selector"]["description"]
    assert any("fallback_x/fallback_y" in note for note in tools["browser.click"]["fallback_notes"])
    assert tools["terminal.run"]["risk_level"] == "high"
    assert tools["terminal.run"]["approval_required"] is True
    assert catalog["capabilities"]["browser_control"]["missing_permissions"] == ["chrome_cdp"]
    assert plugins["notes"]["enabled"] is False
    assert plugins["notes"]["tool_names"] == ["plugin.notes.echo"]
    assert plugins["notes"]["tools"][0]["risk_level"] == "medium"


@pytest.mark.asyncio
async def test_yachiyo_studio_restricted_plugin_routes_manage_port_state() -> None:
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    listed = await yachiyo.list_studio_restricted_tool_plugins(request)
    installed = await yachiyo.install_studio_restricted_tool_plugin(
        yachiyo.RestrictedToolPluginInstallBody(plugin_id="desk", enabled=True),
        request,
    )
    updated = await yachiyo.update_studio_restricted_tool_plugin(
        "desk",
        yachiyo.RestrictedToolPluginUpdateBody(enabled=False),
        request,
    )
    uninstalled = await yachiyo.uninstall_studio_restricted_tool_plugin("desk", request)

    assert listed["plugins"][0]["plugin_id"] == "notes"
    assert installed["plugin_id"] == "desk"
    assert installed["enabled"] is True
    assert updated["enabled"] is False
    assert updated["tools"][0]["enabled"] is False
    assert uninstalled["plugin_id"] == "desk"
    assert uninstalled["enabled"] is False
    assert uninstalled["tools"] == []
    assert ("list_restricted_tool_plugins", None) in runtime.calls
    assert ("install_restricted_tool_plugin", {"plugin_id": "desk", "enabled": True}) in runtime.calls
    assert (
        "update_restricted_tool_plugin",
        {"plugin_id": "desk", "payload": {"enabled": False}},
    ) in runtime.calls
    assert ("uninstall_restricted_tool_plugin", "desk") in runtime.calls


@pytest.mark.asyncio
async def test_yachiyo_studio_run_events_returns_404_for_missing_run() -> None:
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    with pytest.raises(yachiyo.HTTPException) as exc_info:
        await yachiyo.get_studio_run_events("missing-run", request)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Run 不存在"


def test_yachiyo_chat_routes_are_registered_as_light_surface_aliases() -> None:
    source = Path(yachiyo.__file__).read_text(encoding="utf-8")

    assert '@router.get("/readiness")' in source
    assert '@router.get("/runnables")' in source
    assert '@router.get("/tasks")' in source
    assert '@router.post("/tasks")' in source
    assert '@router.get("/tasks/{task_id}")' in source
    assert '@router.get("/tasks/{task_id}/timeline")' in source
    assert '@router.get("/tasks/{task_id}/events")' in source
    assert '@router.get("/tasks/{task_id}/artifacts/{artifact_path:path}")' in source
    assert '@router.post("/tasks/{task_id}/replan-recovery-actions/start")' in source
    assert '@router.post("/tasks/{task_id}/approve")' in source
    assert '@router.post("/tasks/{task_id}/reject")' in source
    assert '@router.post("/tasks/{task_id}/cancel")' in source
    assert '@router.get("/chat/readiness")' in source
    assert '@router.get("/chat/runnables")' in source
    assert '@router.get("/chat/tasks")' in source
    assert '@router.post("/chat/tasks")' in source
    assert '@router.get("/chat/tasks/{task_id}")' in source
    assert '@router.get("/chat/tasks/{task_id}/timeline")' in source
    assert '@router.get("/chat/tasks/{task_id}/events")' in source
    assert '@router.get("/chat/tasks/{task_id}/artifacts/{artifact_path:path}")' in source
    assert '@router.post("/chat/tasks/{task_id}/replan-recovery-actions/start")' in source
    assert '@router.post("/chat/tasks/{task_id}/approve")' in source
    assert '@router.post("/chat/tasks/{task_id}/reject")' in source
    assert '@router.post("/chat/tasks/{task_id}/cancel")' in source


def test_yachiyo_public_routes_delegate_to_chat_and_studio_handlers() -> None:
    source = Path(yachiyo.__file__).read_text(encoding="utf-8")
    legacy_agents_source = (Path(yachiyo.__file__).with_name("agents.py")).read_text(encoding="utf-8")
    studio_agent_handlers_source = (
        Path(yachiyo.__file__).with_name("yachiyo_studio_agent_handlers.py").read_text(encoding="utf-8")
    )
    studio_group_handlers_source = (
        Path(yachiyo.__file__).with_name("yachiyo_studio_group_handlers.py").read_text(encoding="utf-8")
    )
    studio_workflow_handlers_source = (
        Path(yachiyo.__file__).with_name("yachiyo_studio_workflow_handlers.py").read_text(encoding="utf-8")
    )

    assert "from apps.bridge.routes import yachiyo_chat_handlers" in source
    assert "from apps.bridge.routes import yachiyo_studio_handlers" in source
    assert "return await yachiyo_chat_handlers.start_task(request, http_request)" in source
    assert "return await yachiyo_chat_handlers.start_replan_recovery_action(" in source
    assert "return await yachiyo_chat_handlers.plan_task_execution(request, http_request)" in source
    assert "return await yachiyo_chat_handlers.get_task_timeline(task_id, http_request)" in source
    assert "return await yachiyo_studio_handlers.update_agent(agent_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.get_agent_desk(agent_id, http_request)" in source
    assert "return await yachiyo_studio_handlers.write_agent_desk_note(agent_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.write_agent_desk_file(agent_id, request, http_request)" in source
    assert "trigger_agent_desk_file_event(" in source
    assert "return await yachiyo_studio_handlers.list_tool_catalog(http_request)" in source
    assert "return await yachiyo_studio_handlers.plan_task(request, http_request)" in source
    assert "return await yachiyo_studio_handlers.plan_execution(request, http_request)" in source
    assert "return await yachiyo_studio_handlers.start_planner_orchestration(request, http_request)" in source
    assert "return await yachiyo_studio_handlers.list_restricted_tool_plugins(http_request)" in source
    assert "install_restricted_tool_plugin(" in source
    assert "update_restricted_tool_plugin(" in source
    assert "uninstall_restricted_tool_plugin(" in source
    assert "return await yachiyo_studio_handlers.update_group(group_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.update_workflow(workflow_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.start_agent_run(agent_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.start_group_run(group_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.start_workflow_run(workflow_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.get_run_timeline(run_id, http_request)" in source
    assert 'APIRouter(prefix="/ui", tags=["Agent Studio"])' in legacy_agents_source
    assert '@router.get("/agents")' in legacy_agents_source
    assert '@router.post("/agents")' in legacy_agents_source
    assert "_studio_service(http_request).start_agent_run" not in source
    assert "model_copy(update=" not in source
    assert 'request.model_copy(update={"agent_id": agent_id})' in studio_agent_handlers_source
    assert 'request.model_copy(update={"group_id": group_id})' in studio_group_handlers_source
    assert 'request.model_copy(update={"workflow_id": workflow_id})' in studio_workflow_handlers_source


def test_yachiyo_studio_routes_include_run_action_facade() -> None:
    source = Path(yachiyo.__file__).read_text(encoding="utf-8")

    assert '@router.get("/studio/agents")' in source
    assert '@router.post("/studio/agents")' in source
    assert '@router.post("/studio/agents/{agent_id}/runs")' in source
    assert '@router.get("/studio/tools")' in source
    assert '@router.post("/studio/planner")' in source
    assert '@router.get("/studio/agents/{agent_id}")' in source
    assert '@router.patch("/studio/agents/{agent_id}")' in source
    assert '@router.delete("/studio/agents/{agent_id}")' in source
    assert '@router.post("/studio/agents/{agent_id}/test-model")' in source
    assert '@router.get("/studio/agents/{agent_id}/desk")' in source
    assert '@router.post("/studio/agents/{agent_id}/desk/note")' in source
    assert '@router.post("/studio/agents/{agent_id}/desk/files")' in source
    assert '@router.post("/studio/agents/{agent_id}/desk/file-events")' in source
    assert '@router.post("/studio/agents/{agent_id}/skills")' in source
    assert '@router.delete("/studio/agents/{agent_id}/skills/{skill_id}")' in source
    assert '@router.get("/studio/skills")' in source
    assert '@router.get("/studio/skills/sources")' in source
    assert '@router.post("/studio/skills/import")' in source
    assert '@router.post("/studio/skills/sync")' in source
    assert '@router.post("/studio/skills/install")' in source
    assert '@router.patch("/studio/skills/{skill_id}")' in source
    assert '@router.delete("/studio/skills/{skill_id}")' in source
    assert '@router.get("/studio/skill-folders")' in source
    assert '@router.post("/studio/skill-folders")' in source
    assert '@router.patch("/studio/skill-folders/{folder_id}")' in source
    assert '@router.delete("/studio/skill-folders/{folder_id}")' in source
    assert '@router.get("/studio/memories")' in source
    assert '@router.post("/studio/memories")' in source
    assert '@router.patch("/studio/memories/{memory_id}")' in source
    assert '@router.delete("/studio/memories/{memory_id}")' in source
    assert '@router.get("/studio/future-tasks")' in source
    assert '@router.post("/studio/future-tasks/trigger-due")' in source
    assert '@router.post("/studio/future-tasks/{future_task_id}/cancel")' in source
    assert '@router.get("/studio/groups")' in source
    assert '@router.post("/studio/groups")' in source
    assert '@router.get("/studio/groups/{group_id}")' in source
    assert '@router.patch("/studio/groups/{group_id}")' in source
    assert '@router.get("/studio/group-runs")' in source
    assert '@router.get("/studio/group-runs/{group_run_id}")' in source
    assert '@router.post("/studio/group-runs/{group_run_id}/replan-recovery-actions/start")' in source
    assert '@router.post("/studio/group-runs/{group_run_id}/tool-recovery-actions/start")' in source
    assert '@router.get("/studio/group-runs/{group_run_id}/events")' in source
    assert '@router.get("/studio/runs")' in source
    assert '@router.get("/studio/runs/{run_id}")' in source
    assert '@router.post("/studio/runs/{run_id}/rerun")' in source
    assert '@router.post("/studio/runs/{run_id}/replan-recovery-actions/start")' in source
    assert '@router.post("/studio/runs/{run_id}/tool-recovery-actions/start")' in source
    assert '@router.post("/studio/runs/{run_id}/cancel")' in source
    assert '@router.delete("/studio/runs/{run_id}")' in source
    assert '@router.post("/studio/runs/{run_id}/approval/approve")' in source
    assert '@router.post("/studio/runs/{run_id}/approval/reject")' in source
    assert '@router.get("/studio/runs/{run_id}/artifacts/{artifact_path:path}")' in source
    assert '@router.get("/studio/runs/{run_id}/events")' in source
    assert '@router.get("/studio/workflows")' in source
    assert '@router.post("/studio/workflows")' in source
    assert '@router.get("/studio/workflows/{workflow_id}")' in source
    assert '@router.patch("/studio/workflows/{workflow_id}")' in source
    assert '@router.delete("/studio/workflows/{workflow_id}")' in source
    assert '@router.post("/studio/workflows/{workflow_id}/runs")' in source


def _request(runtime: _FakeAgentRuntime) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(runtime=SimpleNamespace(agent_runtime_service=runtime))
        )
    )


def _restricted_plugin_payload(
    plugin_id: str = "notes",
    enabled: bool = False,
) -> dict[str, Any]:
    return {
        "plugin_id": plugin_id,
        "enabled": enabled,
        "tool_names": [f"plugin.{plugin_id}.echo"],
        "tools": [
            {
                "tool_name": f"plugin.{plugin_id}.echo",
                "tool_id": "echo",
                "function_name": f"plugin_{plugin_id}_echo",
                "risk_level": "medium",
                "enabled": enabled,
            }
        ],
        "skill_docs": "Use echo for notes.",
        "source": "restricted_tool_plugin",
    }


def _agent_payload(
    agent_id: str = "agent-1",
    name: str = "Planner",
    skill_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "name": name,
        "model_mode": "profile",
        "execution_backend": "native_profile",
        "model_config": {"provider": "model_profile"},
        "skill_ids": [] if skill_ids is None else skill_ids,
        "enabled": True,
    }


def _skill_payload(skill_id: str = "skill-1", name: str = "Workspace Reviewer") -> dict[str, Any]:
    return {
        "skill_id": skill_id,
        "name": name,
        "description": "Reviews workspace files",
        "source_path": "/skills/workspace-reviewer",
        "local_path": "/managed/skills/workspace-reviewer",
        "folder_id": "folder-1",
        "folder_name": "Review",
        "source_type": "local_dir",
        "origin_path": "/skills/workspace-reviewer",
        "source_ref": "workspace-reviewer",
        "content_hash": "hash-1",
        "last_synced_at": "2026-06-14T00:00:00Z",
        "sync_status": "imported",
        "content_summary": "Review project files",
        "skill_markdown": "# Workspace Reviewer",
        "asset_paths": ["assets/icon.png"],
        "enabled": True,
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }


def _skill_folder_payload(
    folder_id: str = "folder-1",
    name: str = "Review",
    source_scope: str = "installed",
    sort_order: int = 2,
) -> dict[str, Any]:
    return {
        "folder_id": folder_id,
        "name": name,
        "description": "Review skills",
        "source_scope": source_scope,
        "sort_order": sort_order,
        "skill_count": 3,
        "installed_count": 2,
        "native_count": 1,
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }


def _skill_source_payload() -> dict[str, Any]:
    return {
        "path": "/skills/native",
        "source_type": "native_global",
        "library": "native",
        "exists": True,
        "skill_count": 4,
    }


def _memory_payload(
    memory_id: str = "memory-1",
    content: str = "Prefer concise status updates.",
) -> dict[str, Any]:
    return {
        "memory_id": memory_id,
        "scope": "global",
        "kind": "preference",
        "content": content,
        "source_session_id": "chat-1",
        "source_message_id": "message-1",
        "source_task_id": "task-1",
        "source_run_id": "run-1",
        "confidence": 0.9,
        "pinned": True,
        "user_confirmed": True,
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
        "deleted_at": "",
    }


def _future_task_payload(
    future_task_id: str = "future-1",
    title: str = "Follow up later",
    prompt: str = "Follow up on the report",
    runnable_id: str = "agent-1",
    status: str = "scheduled",
    last_run_id: str = "",
    run_count: int = 0,
    cancelled_at: str = "",
    source_run_id: str = "run-source-1",
) -> dict[str, Any]:
    return {
        "future_task_id": future_task_id,
        "title": title,
        "prompt": prompt,
        "runnable_id": runnable_id,
        "runnable_name": "Planner",
        "status": status,
        "scheduled_at_epoch": 1781433600.0,
        "cron": "",
        "source_run_id": source_run_id,
        "last_run_id": last_run_id,
        "run_count": run_count,
        "error": "",
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
        "cancelled_at": cancelled_at,
    }


def _workflow_payload(
    workflow_id: str = "workflow-1",
    name: str = "Review workflow",
) -> dict[str, Any]:
    return {
        "workflow_id": workflow_id,
        "name": name,
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
        "default_input_schema": {"type": "object"},
        "enabled": True,
    }


def _run_payload(
    run_id: str = "run-1",
    kind: str = "agent_run",
    runnable_id: str = "agent-1",
    user_goal: str = "Patch README",
    status: str = "approval_required",
    result: str = "",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "run_group_id": "group-run-1",
        "kind": kind,
        "runnable_id": runnable_id,
        "runnable_name": "Planner",
        "status": status,
        "user_goal": user_goal,
        "result": result,
        "timeline": [{"event": "agent.tool.call", "detail": "workspace.read"}],
        "pending_approval": {"approval_id": run_id, "tool": "terminal.run"},
        "artifacts": [{"artifact_id": "artifact-1", "kind": "markdown", "path": "report.md"}],
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }


def _observable_run_payload(run_id: str) -> dict[str, Any]:
    return _run_payload(run_id=run_id, user_goal="Analyze sales data") | {
        "status": "approval_required",
        "planner_summary": {
            "source": "runtime_planner",
            "decision_id": f"decision-{run_id}",
            "plan_id": f"plan-{run_id}",
            "intent_kind": "data_analysis",
            "intent_title": "Analyze data",
            "route_to_studio": True,
            "plan_tools": ["workspace.read", "terminal.run", "artifact.write"],
            "selected_tools": ["workspace.read", "terminal.run"],
            "plan_capabilities": ["file_read", "terminal_execution", "artifact_output"],
            "required_capabilities": ["file_read", "data_analysis"],
            "approvals_required": ["terminal.run"],
            "artifacts_expected": ["markdown_report"],
            "step_count": 3,
            "event_count": 2,
        },
        "tool_calls": [
            {
                "tool_call_id": f"tool-{run_id}",
                "tool_name": "terminal.run",
                "status": "waiting_approval",
                "risk_level": "medium",
                "input_preview": {"command": "python analyze.py"},
                "approval_id": f"approval-{run_id}",
            }
        ],
        "pending_approval": {
            "approval_id": f"approval-{run_id}",
            "tool": "terminal.run",
            "risk_level": "medium",
            "input_preview": {"command": "python analyze.py"},
        },
        "artifacts": [
            {
                "artifact_id": f"artifact-direct-{run_id}",
                "kind": "markdown",
                "path": "reports/observable.md",
                "title": "Observable report",
            }
        ],
        "events": [
            {
                "event_id": f"memory-{run_id}",
                "run_id": run_id,
                "sequence": 1,
                "event_type": "memory.retrieved",
                "payload": {
                    "count": 1,
                    "group_id": "group-run-1",
                    "run_group_id": "group-run-1",
                    "memories": [
                        {
                            "memory_id": "memory-observable",
                            "kind": "preference",
                            "scope": "shared",
                        }
                    ],
                },
            },
            {
                "event_id": f"skill-{run_id}",
                "run_id": run_id,
                "sequence": 2,
                "event_type": "skill.selected",
                "payload": {
                    "skill_id": "skill-observable",
                    "skill_name": "Data analyst",
                    "source_ref": "skills/data-analyst/SKILL.md",
                },
            },
            {
                "event_id": f"artifact-{run_id}",
                "run_id": run_id,
                "sequence": 3,
                "event_type": "artifact.created",
                "payload": {
                    "artifact_id": "artifact-event-observable",
                    "kind": "markdown",
                    "path": "reports/event-observable.md",
                    "title": "Event report",
                },
            },
            {
                "event_id": f"group-{run_id}",
                "run_id": run_id,
                "sequence": 4,
                "event_type": "group.member.started",
                "payload": {
                    "group_id": "group-run-1",
                    "run_group_id": "group-run-1",
                    "member_agent_id": "agent-1",
                    "objective": "Summary",
                },
            },
        ],
    }


def _rerun_started_event(
    original_run_id: str,
    *,
    kind: str,
    status: str,
    runnable_id: str,
    runnable_name: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event_type": "run.rerun.started",
        "payload": {
            "rerun_of_run_id": original_run_id,
            "rerun_of_kind": kind,
            "rerun_of_status": status,
            "rerun_of_runnable_id": runnable_id,
            "rerun_of_runnable_name": runnable_name,
            "original_created_at": "2026-06-13T00:00:00Z",
            "original_updated_at": "2026-06-13T00:00:04Z",
            **dict(extra or {}),
        },
    }
