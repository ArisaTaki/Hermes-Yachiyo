"""Yachiyo public facade route tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.bridge.routes import yachiyo, yachiyo_chat_handlers, yachiyo_studio_run_handlers
from apps.core.chat_session import ChatSession, MessageStatus
from apps.core.chat_store import ChatStore
from apps.core.state import AppState
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.chat_api import ChatAPI
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent import AgentTaskSnapshot, RunTimelineSnapshot, legacy_ports
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
    assert task_events["next_after_sequence"] == 1
    assert task_events["has_more"] is True
    assert task_events["events"][0]["event_type"] == "agent.started"
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
        assert assistant.task_id == started["task_id"]
        assert assistant.content == "已打开 Microsoft Word。"
        assert assistant.status == MessageStatus.COMPLETED
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
        assert capture_targets[0].endswith("screenshots/current-screen.png")
        assert started["status"] == "completed"
        assert "桌面操作未完成：screen recording permission denied" in started["summary"]
        assert "缺少权限：screen_recording" in started["summary"]
        assert started["needs_user_action"] is False
        assert tool_call["tool_name"] == "screen.capture"
        assert tool_call["status"] == "failed"
        assert tool_call["output_preview"]["permission_error"] is True
        assert tool_call["output_preview"]["permission_targets"] == ["screen_recording"]
        assert tool_call["output_preview"]["recovery_actions"] == [
            {
                "label": "打开屏幕录制权限",
                "tool": "app.open",
                "input": {"app_name": "屏幕录制权限"},
                "permission_target": "screen_recording",
                "risk_level": "low",
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
            AssertionError("structured recovery action should not call model")
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
                "open_target": "system_settings",
            },
        }

    monkeypatch.setattr("apps.shell.agent.tools.desktop.app_open", fake_app_open)
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
                    "recovery_tool": "app.open",
                    "recovery_input": {"app_name": "屏幕录制权限"},
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

        assert open_calls == ["屏幕录制权限"]
        assert started["status"] == "completed"
        assert started["summary"] == "已打开 屏幕录制权限。"
        assert started["tool_calls"][-1]["tool_name"] == "app.open"
        assert started["tool_calls"][-1]["input_preview"]["app_name"] == "屏幕录制权限"
        assert planned_event["payload"]["input_preview"]["app_name"] == "屏幕录制权限"
        assert "model.request.started" not in event_types
        assert "model.requested" not in event_types
        assert user_metadata["desktop_permission_recovery"] is True
        assert user_metadata["recovery_tool"] == "app.open"
        assert user_metadata["recovery_input"] == {"app_name": "屏幕录制权限"}
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
    assert started["current_step"] == "准备执行 · 播放 Apple Music"
    assert started["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
    assert started["recent_events"][0]["detail"] == "media.apple_music_play"
    assert started["recent_events"][0]["payload"] == {
        "input_preview": {"query": "超时空辉夜姬"},
        "planning_reason": "clear_daily_desktop_intent",
        "source": "daily_desktop_intent",
        "status": "planned",
        "tool": "media.apple_music_play",
    }
    assert app_runtime.chat_calls == [
        {
            "session_id": "chat-1",
            "text": "播放超时空辉夜姬",
            "runnable_id": "builtin:yachiyo-main",
            "client_message_id": "client-main-1",
            "metadata": {
                "client_message_id": "client-main-1",
                "daily_desktop_intent": True,
            },
        }
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
    assert started["current_step"] == "准备执行 · 打开应用"
    assert started["recent_events"][0]["event_type"] == "agent.desktop.intent_planned"
    assert started["recent_events"][0]["detail"] == "app.open"
    assert app_runtime.chat_calls == [
        {
            "session_id": "chat-1",
            "text": "打开 Apple Music",
            "runnable_id": "builtin:yachiyo-main",
            "client_message_id": "launcher-main-1",
            "metadata": {
                "client_message_id": "launcher-main-1",
                "source": "launcher",
                "launcher_mode": "bubble",
                "launcher_surface": "desktop_launcher",
            },
        }
    ]
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
    assert tools["media.apple_music_control"]["capability_id"] == "media_control"
    assert tools["media.apple_music_control"]["risk_level"] == "low"
    assert tools["media.apple_music_control"]["input_schema"]["required"] == ["action"]
    assert tools["media.apple_music_control"]["missing_permissions"] == ["music_app"]
    assert tools["system.volume"]["capability_id"] == "desktop_execution"
    assert tools["system.volume"]["risk_level"] == "low"
    assert tools["system.volume"]["input_schema"]["required"] == ["action"]
    assert any("volume" in note for note in tools["system.volume"]["fallback_notes"])
    assert tools["clipboard.write"]["capability_id"] == "desktop_execution"
    assert tools["clipboard.write"]["risk_level"] == "low"
    assert tools["clipboard.write"]["input_schema"]["required"] == ["text"]
    assert any("clipboard" in note for note in tools["clipboard.write"]["fallback_notes"])
    assert tools["desktop.running_apps"]["capability_id"] == "active_window"
    assert tools["desktop.running_apps"]["risk_level"] == "low"
    assert any("foreground app list" in note for note in tools["desktop.running_apps"]["fallback_notes"])
    assert tools["desktop.windows"]["capability_id"] == "active_window"
    assert tools["desktop.windows"]["risk_level"] == "low"
    assert any("window titles" in note for note in tools["desktop.windows"]["fallback_notes"])
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
    assert any(
        "whitelisted common shortcut" in note
        for note in tools["desktop.safe_shortcut"]["fallback_notes"]
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
    assert tools["desktop.reveal_path"]["capability_id"] == "desktop_execution"
    assert tools["desktop.reveal_path"]["risk_level"] == "low"
    assert tools["desktop.reveal_path"]["input_schema"]["required"] == ["path"]
    assert any("Finder" in note for note in tools["desktop.reveal_path"]["fallback_notes"])
    assert tools["desktop.open_path"]["capability_id"] == "desktop_execution"
    assert tools["desktop.open_path"]["risk_level"] == "low"
    assert tools["desktop.open_path"]["input_schema"]["required"] == ["path"]
    assert any("unsafe" in note for note in tools["desktop.open_path"]["fallback_notes"])
    assert tools["desktop.permissions"]["capability_id"] == "desktop_execution"
    assert tools["desktop.permissions"]["risk_level"] == "low"
    assert tools["desktop.permissions"]["input_schema"]["properties"] == {}
    assert any(
        "missing desktop permission" in note
        for note in tools["desktop.permissions"]["fallback_notes"]
    )
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
    assert "return await yachiyo_chat_handlers.get_task_timeline(task_id, http_request)" in source
    assert "return await yachiyo_studio_handlers.update_agent(agent_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.get_agent_desk(agent_id, http_request)" in source
    assert "return await yachiyo_studio_handlers.write_agent_desk_note(agent_id, request, http_request)" in source
    assert "return await yachiyo_studio_handlers.write_agent_desk_file(agent_id, request, http_request)" in source
    assert "trigger_agent_desk_file_event(" in source
    assert "return await yachiyo_studio_handlers.list_tool_catalog(http_request)" in source
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

    assert '@router.post("/studio/agents/{agent_id}/runs")' in source
    assert '@router.get("/studio/tools")' in source
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
    assert '@router.get("/studio/groups/{group_id}")' in source
    assert '@router.patch("/studio/groups/{group_id}")' in source
    assert '@router.get("/studio/group-runs")' in source
    assert '@router.get("/studio/group-runs/{group_run_id}")' in source
    assert '@router.get("/studio/group-runs/{group_run_id}/events")' in source
    assert '@router.get("/studio/runs")' in source
    assert '@router.get("/studio/runs/{run_id}")' in source
    assert '@router.post("/studio/runs/{run_id}/rerun")' in source
    assert '@router.post("/studio/runs/{run_id}/cancel")' in source
    assert '@router.delete("/studio/runs/{run_id}")' in source
    assert '@router.post("/studio/runs/{run_id}/approval/approve")' in source
    assert '@router.post("/studio/runs/{run_id}/approval/reject")' in source
    assert '@router.get("/studio/runs/{run_id}/artifacts/{artifact_path:path}")' in source
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
