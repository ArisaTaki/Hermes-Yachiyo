"""Fake-port tests for the Agent Studio facade."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent import (
    AgentDeskFileEventRequest,
    AgentStudioService,
    ApprovalDecision,
    RerunRunRequest,
    SaveAgentDeskFileRequest,
    SaveAgentDeskNoteRequest,
    SaveAgentGroupMemberRequest,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    StartAgentRunRequest,
    StartGroupRunRequest,
    StartWorkflowRunRequest,
)


class _FakeStudioPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def list_agents(self) -> dict[str, Any]:
        self.calls.append(("list_agents", None))
        return {"ok": True, "agents": [_agent_payload()]}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("get_agent", agent_id))
        return _agent_payload(agent_id=agent_id, name="Fetched")

    def save_agent(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("save_agent", request))
        return _agent_payload(agent_id=request.get("agent_id") or "agent-new", name=request["name"])

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("delete_agent", agent_id))
        return {"ok": True, "agent_id": agent_id}

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("test_agent_model", agent_id))
        return {"ok": True, "message": "Model ready"}

    def get_agent_desk(self, agent_id: str) -> dict[str, Any]:
        self.calls.append(("get_agent_desk", agent_id))
        return _desk_payload(agent_id=agent_id)

    def write_agent_desk_note(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("write_agent_desk_note", {"agent_id": agent_id, "request": request}))
        return _desk_payload(agent_id=agent_id, note=request.get("content") or "")

    def write_agent_desk_file(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("write_agent_desk_file", {"agent_id": agent_id, "request": request}))
        return _desk_payload(
            agent_id=agent_id,
            file_path=request.get("path") or "inputs/brief.md",
            file_text=request.get("content") or "",
        )

    def trigger_agent_desk_file_event(
        self,
        agent_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            ("trigger_agent_desk_file_event", {"agent_id": agent_id, "request": request})
        )
        return {
            "ok": True,
            "future_task": _future_task_payload(
                future_task_id="future-desk-1",
                prompt=f"Review {request.get('path')}",
            ) | {
                "title": "Review Agent Desk file: inputs/brief.md",
                "runnable_id": agent_id,
                "source_run_id": "agent_desk_file_event",
            },
        }

    def attach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        self.calls.append(("attach_skill", {"agent_id": agent_id, "skill_id": skill_id}))
        return _agent_payload(agent_id=agent_id, skill_ids=[skill_id])

    def detach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        self.calls.append(("detach_skill", {"agent_id": agent_id, "skill_id": skill_id}))
        return _agent_payload(agent_id=agent_id, skill_ids=[])

    def list_skills(self) -> dict[str, Any]:
        self.calls.append(("list_skills", None))
        return {"ok": True, "skills": [_skill_payload()]}

    def update_skill(self, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("update_skill", {"skill_id": skill_id, "request": request}))
        return _skill_payload(skill_id=skill_id) | {
            "enabled": bool(request.get("enabled", True)),
            "folder_id": str(request.get("folder_id") or ""),
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

    def create_skill_folder(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_skill_folder", request))
        return _skill_folder_payload(
            folder_id=request.get("folder_id") or "folder-new",
            name=request["name"],
        )

    def update_skill_folder(self, folder_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(
            ("update_skill_folder", {"folder_id": folder_id, "request": request})
        )
        return _skill_folder_payload(folder_id=folder_id, name=request.get("name") or "Updated")

    def delete_skill_folder(self, folder_id: str, delete_skills: bool = False) -> dict[str, Any]:
        self.calls.append(
            ("delete_skill_folder", {"folder_id": folder_id, "delete_skills": delete_skills})
        )
        return {"ok": True, "deleted_skill_count": 2 if delete_skills else 0}

    def list_skill_sources(self) -> dict[str, Any]:
        self.calls.append(("list_skill_sources", None))
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

    def list_memories(self, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        self.calls.append(
            ("list_memories", {"include_deleted": include_deleted, "limit": limit})
        )
        return {"ok": True, "memories": [_memory_payload()]}

    def create_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create_memory", request))
        return _memory_payload(memory_id="memory-created", content=request["content"])

    def update_memory(self, memory_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("update_memory", {"memory_id": memory_id, "request": request}))
        return _memory_payload(memory_id=memory_id, content=request["content"])

    def delete_memory(self, memory_id: str, reason: str = "") -> dict[str, Any]:
        self.calls.append(("delete_memory", {"memory_id": memory_id, "reason": reason}))
        return {"ok": True, "memory_id": memory_id}

    def list_future_tasks(
        self,
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

    def cancel_future_task(self, future_task_id: str, reason: str = "") -> dict[str, Any]:
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

    def start_agent_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_agent_run", request))
        return _run_payload(
            run_id="agent-run-1",
            runnable_id=request["agent_id"],
            kind="agent_run",
            user_goal=request["objective"],
        )

    def list_groups(self) -> list[dict[str, Any]]:
        self.calls.append(("list_groups", None))
        return [_group_payload()]

    def get_group(self, group_id: str) -> dict[str, Any]:
        self.calls.append(("get_group", group_id))
        return _group_payload(group_id=group_id)

    def save_group(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("save_group", request))
        return _group_payload(group_id=request.get("group_id") or "group-new", name=request["name"])

    def start_group_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_group_run", request))
        return _group_run_payload(group_id=request["group_id"], objective=request["objective"])

    def list_group_runs(self, limit: int = 50) -> dict[str, Any]:
        self.calls.append(("list_group_runs", limit))
        return {"ok": True, "group_runs": [_group_run_payload(group_run_id="group-run-listed")]}

    def get_group_run(self, group_run_id: str) -> dict[str, Any]:
        self.calls.append(("get_group_run", group_run_id))
        return _group_run_payload(group_run_id=group_run_id) | {
            "run_group_id": group_run_id,
            "title": "Legacy run group",
            "status": "running",
            "summary": "Legacy summary",
            "child_run_ids": ["child-run-1"],
        }

    def list_workflows(self) -> dict[str, Any]:
        self.calls.append(("list_workflows", None))
        return {"ok": True, "workflows": [_workflow_payload()]}

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.calls.append(("get_workflow", workflow_id))
        return _workflow_payload(workflow_id=workflow_id)

    def save_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("save_workflow", request))
        return _workflow_payload(
            workflow_id=request.get("workflow_id") or "workflow-new",
            name=request["name"],
        )

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        self.calls.append(("delete_workflow", workflow_id))
        return {"ok": True, "workflow_id": workflow_id}

    def start_workflow_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_workflow_run", request))
        return _run_payload(
            run_id="workflow-run-1",
            runnable_id=request["workflow_id"],
            kind="workflow_run",
            user_goal=request["objective"],
        )

    def list_run_timelines(self, limit: int = 50) -> dict[str, Any]:
        self.calls.append(("list_run_timelines", limit))
        return {"ok": True, "runs": [_run_payload(run_id="run-listed")]}

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_timeline", run_id))
        return _run_payload(run_id=run_id)

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
        payload = _run_payload(run_id=f"{run_id}-rerun", user_goal="Rerun task")
        payload["timeline"] = [
            _rerun_started_event(
                run_id,
                kind="agent_run",
                status="completed",
                runnable_id="agent-1",
                runnable_name="Planner",
            )
        ]
        return payload

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_run", run_id))
        return _run_payload(run_id=run_id, user_goal="Cancelled task") | {"status": "cancelled"}

    def delete_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("delete_run", run_id))
        return {"ok": True, "deleted_run_ids": [run_id], "deleted_run_count": 1}

    def approve_run_approval(self, run_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("approve_run_approval", {"run_id": run_id, "decision": decision}))
        return _run_payload(run_id=run_id, user_goal="Approved task") | {"status": "completed"}

    def reject_run_approval(self, run_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("reject_run_approval", {"run_id": run_id, "decision": decision}))
        return _run_payload(run_id=run_id, user_goal="Rejected task") | {"status": "failed"}

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        self.calls.append(
            ("read_run_artifact", {"run_id": run_id, "artifact_path": artifact_path})
        )
        return {"ok": True, "run_id": run_id, "path": artifact_path, "content": "# Report"}

    def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_event_stream", run_id))
        return {
            "run_id": run_id,
            "after_sequence": 0,
            "limit": 200,
            "events": [
                {
                    "event_id": "event-stream-1",
                    "run_id": run_id,
                    "sequence": 1,
                    "event_type": "agent.started",
                    "payload": {"status": "running"},
                },
                {
                    "event_id": "event-stream-2",
                    "run_id": run_id,
                    "sequence": 2,
                    "event_type": "agent.tool.call",
                    "payload": {"tool": "workspace.read"},
                },
                {
                    "event_id": "event-stream-3",
                    "run_id": run_id,
                    "sequence": 3,
                    "event_type": "agent.completed",
                    "payload": {"status": "completed"},
                }
            ],
        }


def test_agent_studio_service_maps_agent_group_workflow_snapshots() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    agents = service.list_agents()
    agent = service.get_agent("agent-1")
    saved_agent = service.save_agent(
        SaveAgentRequest(
            agent_id="agent-2",
            name="Writer",
            model_config={"provider": "model_profile"},
            tool_policy={"allowed_tools": ["workspace.read"]},
            skill_ids=["skill-1"],
        )
    )
    deleted_agent = service.delete_agent("agent-2")
    model_test = service.test_agent_model("agent-2")
    desk = service.get_agent_desk("agent-2")
    desk_with_note = service.write_agent_desk_note(
        "agent-2",
        SaveAgentDeskNoteRequest(content="# Notes"),
    )
    desk_with_file = service.write_agent_desk_file(
        "agent-2",
        SaveAgentDeskFileRequest(path="inputs/brief.md", content="Brief"),
    )
    desk_file_event_task = service.trigger_agent_desk_file_event(
        "agent-2",
        AgentDeskFileEventRequest(
            path="inputs/brief.md",
            event_type="modified",
            delay_seconds=0,
        ),
    )
    agent_with_skill = service.attach_skill("agent-2", "skill-2")
    agent_without_skill = service.detach_skill("agent-2", "skill-2")
    skills = service.list_skills()
    updated_skill = service.update_skill("skill-1", {"enabled": False, "folder_id": "folder-2"})
    deleted_skill = service.delete_skill("skill-1")
    skill_folders_payload = service.list_skill_folders()
    saved_skill_folder = service.create_skill_folder({"name": "New Folder"})
    updated_skill_folder = service.update_skill_folder("folder-1", {"name": "Renamed"})
    deleted_skill_folder = service.delete_skill_folder("folder-1", delete_skills=True)
    skill_sources = service.list_skill_sources()
    imported_skill = service.import_skill("/skills/imported", "folder-1")
    sync_result = service.sync_native_skills()
    install_result = service.install_skill_command("npx skills add reviewer", "folder-1")
    memories = service.list_memories(include_deleted=True, limit=10)
    created_memory = service.create_memory({"content": "Remember concise updates"})
    updated_memory = service.update_memory("memory-1", {"content": "Prefer detailed updates"})
    deleted_memory = service.delete_memory("memory-1", reason="studio_user_delete")
    future_tasks = service.list_future_tasks(include_finished=False, limit=5)
    cancelled_future_task = service.cancel_future_task("future-1", reason="studio_user_cancel")
    triggered_future_tasks = service.trigger_due_future_tasks(limit=3)
    groups = service.list_groups()
    group = service.get_group("group-1")
    saved_group = service.save_group(
        SaveAgentGroupRequest(
            group_id="group-2",
            name="Team",
            members=[
                SaveAgentGroupMemberRequest(
                    agent_id="agent-1",
                    role="planner",
                    sort_order=1,
                )
            ],
            mode="pipeline",
            memory_scope="hybrid",
        )
    )
    workflows = service.list_workflows()
    workflow = service.get_workflow("workflow-1")
    saved_workflow = service.save_workflow(
        SaveWorkflowRequest(
            workflow_id="workflow-2",
            name="Saved workflow",
            nodes=[{"id": "start", "type": "start"}],
            edges=[],
            default_input_schema={"type": "object"},
        )
    )
    deleted_workflow = service.delete_workflow("workflow-2")

    assert agents[0].agent_id == "agent-1"
    assert agent.name == "Fetched"
    assert saved_agent.agent_id == "agent-2"
    assert deleted_agent == {"ok": True, "agent_id": "agent-2"}
    assert model_test == {"ok": True, "message": "Model ready"}
    assert desk.agent_id == "agent-2"
    assert desk.items[0].path == "desk-notes.md"
    assert desk_with_note.items[0].preview_text == "# Notes"
    assert desk_with_file.items[-1].path == "inputs/brief.md"
    assert desk_with_file.items[-1].preview_text == "Brief"
    assert desk_file_event_task.future_task_id == "future-desk-1"
    assert desk_file_event_task.title == "Review Agent Desk file: inputs/brief.md"
    assert desk_file_event_task.runnable_id == "agent-2"
    assert desk_file_event_task.source_run_id == "agent_desk_file_event"
    assert agent_with_skill.skill_ids == ["skill-2"]
    assert agent_without_skill.skill_ids == []
    assert skills[0].skill_id == "skill-1"
    assert skills[0].asset_paths == ["assets/icon.png"]
    assert updated_skill.enabled is False
    assert updated_skill.folder_id == "folder-2"
    assert deleted_skill == {"ok": True, "skill_id": "skill-1"}
    assert skill_folders_payload["folders"][0].folder_id == "folder-1"
    assert skill_folders_payload["uncategorized"].folder_id == ""
    assert saved_skill_folder.name == "New Folder"
    assert updated_skill_folder.name == "Renamed"
    assert deleted_skill_folder == {"ok": True, "deleted_skill_count": 2}
    assert skill_sources[0].path == "/skills/native"
    assert imported_skill.skill_id == "skill-imported"
    assert imported_skill.folder_id == "folder-1"
    assert sync_result == {"ok": True, "summary": {"imported": 1}}
    assert install_result["installer"] == "npx_skills"
    assert memories[0].memory_id == "memory-1"
    assert memories[0].source_run_id == "run-1"
    assert created_memory.memory_id == "memory-created"
    assert updated_memory.content == "Prefer detailed updates"
    assert deleted_memory == {"ok": True, "memory_id": "memory-1"}
    assert future_tasks[0].future_task_id == "future-1"
    assert cancelled_future_task.status == "cancelled"
    assert triggered_future_tasks[0].future_task.last_run_id == "run-1"
    assert triggered_future_tasks[0].run.run_id == "run-1"
    assert groups[0].members[0].agent_id == "agent-1"
    assert group.mode == "debate"
    assert saved_group.name == "Team"
    assert workflows[0].nodes[0]["type"] == "start"
    assert workflow.workflow_id == "workflow-1"
    assert saved_workflow.name == "Saved workflow"
    assert deleted_workflow == {"ok": True, "workflow_id": "workflow-2"}
    assert (
        "save_agent",
        {
            "agent_id": "agent-2",
            "name": "Writer",
            "model_config": {"provider": "model_profile"},
            "tool_policy": {"allowed_tools": ["workspace.read"]},
            "skill_ids": ["skill-1"],
        },
    ) in port.calls
    assert ("delete_agent", "agent-2") in port.calls
    assert ("test_agent_model", "agent-2") in port.calls
    assert ("get_agent_desk", "agent-2") in port.calls
    assert (
        "write_agent_desk_note",
        {"agent_id": "agent-2", "request": {"content": "# Notes"}},
    ) in port.calls
    assert (
        "write_agent_desk_file",
        {"agent_id": "agent-2", "request": {"path": "inputs/brief.md", "content": "Brief"}},
    ) in port.calls
    assert (
        "trigger_agent_desk_file_event",
        {
            "agent_id": "agent-2",
            "request": {
                "path": "inputs/brief.md",
                "event_type": "modified",
                "delay_seconds": 0,
            },
        },
    ) in port.calls
    assert ("attach_skill", {"agent_id": "agent-2", "skill_id": "skill-2"}) in port.calls
    assert ("detach_skill", {"agent_id": "agent-2", "skill_id": "skill-2"}) in port.calls
    assert ("list_skills", None) in port.calls
    assert (
        "update_skill",
        {"skill_id": "skill-1", "request": {"enabled": False, "folder_id": "folder-2"}},
    ) in port.calls
    assert ("delete_skill", "skill-1") in port.calls
    assert ("list_skill_folders", None) in port.calls
    assert ("create_skill_folder", {"name": "New Folder"}) in port.calls
    assert (
        "update_skill_folder",
        {"folder_id": "folder-1", "request": {"name": "Renamed"}},
    ) in port.calls
    assert (
        "delete_skill_folder",
        {"folder_id": "folder-1", "delete_skills": True},
    ) in port.calls
    assert ("list_skill_sources", None) in port.calls
    assert (
        "import_skill",
        {"source_path": "/skills/imported", "folder_id": "folder-1"},
    ) in port.calls
    assert ("sync_native_skills", None) in port.calls
    assert (
        "install_skill_command",
        {"command": "npx skills add reviewer", "folder_id": "folder-1"},
    ) in port.calls
    assert ("list_memories", {"include_deleted": True, "limit": 10}) in port.calls
    assert ("create_memory", {"content": "Remember concise updates"}) in port.calls
    assert (
        "update_memory",
        {"memory_id": "memory-1", "request": {"content": "Prefer detailed updates"}},
    ) in port.calls
    assert (
        "delete_memory",
        {"memory_id": "memory-1", "reason": "studio_user_delete"},
    ) in port.calls
    assert ("list_future_tasks", {"include_finished": False, "limit": 5}) in port.calls
    assert (
        "cancel_future_task",
        {"future_task_id": "future-1", "reason": "studio_user_cancel"},
    ) in port.calls
    assert (
        "trigger_due_future_tasks",
        {"now_epoch": None, "limit": 3},
    ) in port.calls
    assert (
        "save_group",
        {
            "group_id": "group-2",
            "name": "Team",
            "members": [
                {
                    "agent_id": "agent-1",
                    "role": "planner",
                    "sort_order": 1,
                    "enabled": True,
                }
            ],
            "mode": "pipeline",
            "memory_scope": "hybrid",
        },
    ) in port.calls
    assert ("delete_workflow", "workflow-2") in port.calls
    assert (
        "save_workflow",
        {
            "workflow_id": "workflow-2",
            "name": "Saved workflow",
            "nodes": [{"id": "start", "type": "start"}],
            "edges": [],
            "default_input_schema": {"type": "object"},
        },
    ) in port.calls


def test_agent_studio_service_redacts_sensitive_public_memory_and_future_task_text() -> None:
    class _SensitiveStudioPort:
        def list_memories(
            self,
            include_deleted: bool = False,
            limit: int = 100,
        ) -> dict[str, Any]:
            return {
                "memories": [
                    _memory_payload(
                        content="Never store token sk-sensitive-value in public memory."
                    )
                ]
            }

        def list_future_tasks(
            self,
            include_finished: bool = True,
            limit: int = 100,
        ) -> dict[str, Any]:
            return {
                "future_tasks": [
                    _future_task_payload(
                        prompt="Follow up with bearer sensitive-token-value.",
                        error="authorization: bearer sensitive-token-value failed",
                    )
                ]
            }

    service = AgentStudioService(_SensitiveStudioPort())

    memories = service.list_memories()
    future_tasks = service.list_future_tasks()

    assert "sk-sensitive-value" not in memories[0].content
    assert "[redacted]" in memories[0].content
    assert "sensitive-token-value" not in future_tasks[0].prompt
    assert "sensitive-token-value" not in str(future_tasks[0].error)
    assert "[redacted]" in future_tasks[0].prompt


def test_agent_studio_service_redacts_sensitive_public_skill_text() -> None:
    class _SensitiveSkillPort:
        def list_skills(self) -> dict[str, Any]:
            return {
                "skills": [
                    _skill_payload()
                    | {
                        "description": "Uses bearer sensitive-token-value internally.",
                        "content_summary": "Never expose sk-sensitive-value.",
                        "skill_markdown": "# Skill\nAPI key: sk-sensitive-value",
                        "asset_paths": ["assets/sk-sensitive-value.png"],
                    }
                ]
            }

    service = AgentStudioService(_SensitiveSkillPort())

    skill = service.list_skills()[0]
    rendered = str(skill.model_dump(mode="json"))

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert "[redacted]" in rendered
    assert skill.skill_id == "skill-1"


def test_agent_studio_service_redacts_sensitive_public_agent_configuration() -> None:
    class _SensitiveAgentPort:
        def list_agents(self) -> dict[str, Any]:
            return {
                "agents": [
                    _agent_payload()
                    | {
                        "instructions": "Use bearer sensitive-token-value only privately.",
                        "model_config": {
                            "provider": "openai_compatible",
                            "api_key": "sk-sensitive-value",
                            "api_key_configured": True,
                            "headers": {"authorization": "bearer sensitive-token-value"},
                        },
                        "tool_policy": {
                            "allowed_tools": ["workspace.read"],
                            "api_key": "secret-tool-key-value",
                        },
                        "workspace_policy": {
                            "default_workdir": "/workspace",
                            "token": "secret-workspace-token",
                        },
                    }
                ]
            }

    service = AgentStudioService(_SensitiveAgentPort())

    agent = service.list_agents()[0]
    rendered = str(agent.model_dump(mode="json"))

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert "secret-tool-key-value" not in rendered
    assert "secret-workspace-token" not in rendered
    assert agent.model_settings["api_key"] == "[redacted]"
    assert agent.model_settings["api_key_configured"] is True
    assert agent.tool_policy["allowed_tools"] == ["workspace.read"]
    assert agent.workspace_policy["default_workdir"] == "/workspace"


def test_agent_studio_service_redacts_sensitive_public_workflow_configuration() -> None:
    class _SensitiveWorkflowPort(_FakeStudioPort):
        def list_workflows(self) -> dict[str, Any]:
            return {
                "workflows": [
                    _workflow_payload()
                    | {
                        "description": "Calls bearer sensitive-token-value internally.",
                        "nodes": [
                            {
                                "id": "tool",
                                "type": "tool",
                                "data": {
                                    "api_key": "sk-sensitive-value",
                                    "api_key_configured": True,
                                    "headers": {
                                        "authorization": "bearer sensitive-token-value",
                                    },
                                },
                            }
                        ],
                        "edges": [
                            {
                                "source": "start",
                                "target": "tool",
                                "data": {"token": "secret-edge-token"},
                            }
                        ],
                        "default_input_schema": {
                            "type": "object",
                            "properties": {
                                "api_key": {
                                    "type": "string",
                                    "default": "sk-sensitive-value",
                                }
                            },
                        },
                    }
                ]
            }

    service = AgentStudioService(_SensitiveWorkflowPort())

    workflow = service.list_workflows()[0]
    rendered = str(workflow.model_dump(mode="json"))

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert "secret-edge-token" not in rendered
    assert workflow.nodes[0]["data"]["api_key"] == "[redacted]"
    assert workflow.nodes[0]["data"]["api_key_configured"] is True
    assert "api_key" in workflow.default_input_schema["properties"]
    assert workflow.default_input_schema["properties"]["api_key"]["default"] == "[redacted]"


def test_agent_studio_service_redacts_sensitive_public_group_snapshots() -> None:
    class _SensitiveGroupPort:
        def list_groups(self) -> dict[str, Any]:
            return {
                "groups": [
                    _group_payload()
                    | {
                        "name": "Research sk-sensitive-value",
                        "description": "Uses bearer sensitive-token-value internally.",
                        "members": [
                            {
                                "agent_id": "agent-1",
                                "name": "Planner sk-sensitive-value",
                                "role": "token sk-sensitive-value",
                            }
                        ],
                    }
                ]
            }

        def get_group_run(self, group_run_id: str) -> dict[str, Any]:
            return _group_run_payload(group_run_id=group_run_id) | {
                "title": "Group run sk-sensitive-value",
                "objective": "Compare bearer sensitive-token-value",
                "summary": "token sk-sensitive-value",
                "participants": [
                    {
                        "agent_id": "agent-1",
                        "name": "Planner sk-sensitive-value",
                    }
                ],
                "events": [
                    {
                        "event_type": "group.member.started",
                        "detail": "Planner sk-sensitive-value started",
                        "payload": {"member_agent_id": "agent-1"},
                    }
                ],
            }

    service = AgentStudioService(_SensitiveGroupPort())

    group = service.list_groups()[0]
    group_run = service.get_group_run("group-run-sensitive")
    rendered = str({
        "group": group.model_dump(mode="json"),
        "group_run": group_run.model_dump(mode="json"),
    })

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert "[redacted]" in rendered
    assert group.members[0].agent_id == "agent-1"
    assert group_run.runs[0].run_id == "run-1"
    assert group_run.events[0].event_type == "group.run.started"


def test_agent_studio_service_maps_group_run_workflow_run_timeline_and_events() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    agent_run = service.start_agent_run(
        StartAgentRunRequest(agent_id="agent-1", objective="Draft summary")
    )
    group_run = service.start_group_run(
        StartGroupRunRequest(
            group_id="group-1",
            objective="Compare designs",
            client_run_id="client-group-1",
        )
    )
    group_runs = service.list_group_runs(5)
    fetched_group_run = service.get_group_run("group-run-1")
    group_events = list(service.get_group_run_event_stream("group-run-1"))
    group_event_page = service.get_group_run_event_page("group-run-1", after_sequence=0, limit=1)
    workflow_run = service.start_workflow_run(
        StartWorkflowRunRequest(workflow_id="workflow-1", objective="Build report")
    )
    timelines = service.list_run_timelines(10)
    timeline = service.get_run_timeline("run-1")
    events = list(service.get_run_event_stream("run-1"))
    event_page = service.get_run_event_page("run-1", after_sequence=1, limit=1)

    assert agent_run.run_id == "agent-run-1"
    assert agent_run.agent_id == "agent-1"
    assert agent_run.title == "Draft summary"
    assert group_run.group_id == "group-1"
    assert group_run.run_group_id == "group-run-1"
    assert group_run.objective == "Compare designs"
    assert [event.event_type for event in group_run.events[:2]] == [
        "group.run.started",
        "group.member.started",
    ]
    assert group_run.events[0].payload["group_run_id"] == "group-run-1"
    assert group_run.events[1].payload["member_agent_id"] == "agent-1"
    assert group_run.runs[0].events[0].event_type == "agent.tool.call"
    assert group_run.participants[0].run_id == "run-1"
    assert group_run.participants[0].run_status == "approval_required"
    assert group_run.participants[0].tool_calls[0].tool_name == "workspace.read"
    assert group_run.participants[0].pending_approvals[0].approval_id == "approval-1"
    assert group_run.participants[0].artifacts[0].path == "report.md"
    assert group_run.pending_approvals[0].approval_id == "approval-1"
    assert [artifact.path for artifact in group_run.shared_artifacts] == ["team.md", "report.md"]
    assert group_run.shared_artifacts[1].source_run_id == "run-1"
    assert group_run.shared_artifacts[1].group_run_id == "group-run-1"
    assert group_runs[0].group_run_id == "group-run-listed"
    assert fetched_group_run.group_run_id == "group-run-1"
    assert fetched_group_run.run_group_id == "group-run-1"
    assert fetched_group_run.child_run_ids == ["child-run-1"]
    assert group_events[0].event_type == "group.run.started"
    assert group_events[0].payload["group_run_id"] == "group-run-1"
    assert group_events[1].event_type == "group.member.started"
    assert group_events[1].payload["member_agent_id"] == "agent-1"
    assert group_event_page.run_id == "group-run-1"
    assert group_event_page.events[0].event_type == "group.run.started"
    assert group_event_page.has_more is True
    assert workflow_run.workflow_run_id == "workflow-run-1"
    assert workflow_run.run_id == "workflow-run-1"
    assert workflow_run.title == "Build report"
    assert timelines[0].run_id == "run-listed"
    assert timeline.task_id == "task-1"
    assert timeline.session_id == "chat-1"
    assert timeline.task_run_link_created_at == "2026-06-14T00:00:00Z"
    assert timeline.task_run_link_last_event_sequence == 7
    assert timeline.tool_calls[0].tool_name == "workspace.read"
    assert timeline.run_group_id == "group-run-1"
    assert timeline.approvals[0].tool_name == "terminal.run"
    assert timeline.pending_approval is not None
    assert timeline.artifacts[0].path == "report.md"
    assert timeline.children[0].run_id == "child-run-1"
    assert events[0].event_type == "agent.started"
    assert event_page.run_id == "run-1"
    assert event_page.after_sequence == 1
    assert event_page.limit == 1
    assert event_page.next_after_sequence == 2
    assert event_page.has_more is True
    assert event_page.events[0].sequence == 2
    assert event_page.events[0].event_type == "agent.tool.call"
    assert (
        "start_group_run",
        {
            "group_id": "group-1",
            "objective": "Compare designs",
            "client_run_id": "client-group-1",
        },
    ) in port.calls
    assert ("list_group_runs", 5) in port.calls
    assert ("list_run_timelines", 10) in port.calls


def test_agent_studio_service_paginates_group_run_events_after_child_sequence_renumbering() -> None:
    class SequencedGroupRunPort(_FakeStudioPort):
        def get_group_run(self, group_run_id: str) -> dict[str, Any]:
            return _group_run_payload(group_run_id=group_run_id) | {
                "events": [
                    {
                        "event_type": "group.member.started",
                        "run_id": "child-run-1",
                        "sequence": 7,
                        "payload": {"member_agent_id": "agent-1"},
                    },
                    {
                        "event_type": "group.member.completed",
                        "run_id": "child-run-2",
                        "sequence": 3,
                        "payload": {"member_agent_id": "agent-2"},
                    },
                ],
            }

    service = AgentStudioService(SequencedGroupRunPort())

    first_child_page = service.get_group_run_event_page(
        "group-run-1",
        after_sequence=1,
        limit=1,
    )
    second_child_page = service.get_group_run_event_page(
        "group-run-1",
        after_sequence=2,
        limit=1,
    )

    assert first_child_page.events[0].sequence == 2
    assert first_child_page.events[0].event_type == "group.member.started"
    assert first_child_page.events[0].payload["source_run_id"] == "child-run-1"
    assert first_child_page.events[0].payload["source_sequence"] == 7
    assert first_child_page.next_after_sequence == 2
    assert first_child_page.has_more is True
    assert second_child_page.events[0].sequence == 3
    assert second_child_page.events[0].event_type == "group.member.completed"
    assert second_child_page.events[0].payload["source_run_id"] == "child-run-2"
    assert second_child_page.events[0].payload["source_sequence"] == 3
    assert second_child_page.next_after_sequence == 3
    assert second_child_page.has_more is False


def test_agent_studio_service_prefers_runtime_group_run_event_page_port() -> None:
    class PagedGroupRunEventPort(_FakeStudioPort):
        def get_group_run_event_stream(self, group_run_id: str) -> dict[str, Any]:
            self.calls.append(("get_group_run_event_stream", group_run_id))
            return {
                "events": [
                    {
                        "event_id": "group-event-4",
                        "run_id": group_run_id,
                        "sequence": 4,
                        "event_type": "group.member.started",
                        "payload": {"member_agent_id": "agent-1"},
                    }
                ],
            }

        def get_group_run_event_page(
            self,
            group_run_id: str,
            *,
            after_sequence: int = 0,
            limit: int = 200,
        ) -> dict[str, Any]:
            self.calls.append(
                (
                    "get_group_run_event_page",
                    {
                        "group_run_id": group_run_id,
                        "after_sequence": after_sequence,
                        "limit": limit,
                    },
                )
            )
            return {
                "run_id": group_run_id,
                "after_sequence": after_sequence,
                "limit": limit,
                "next_after_sequence": 9,
                "has_more": True,
                "events": [
                    {
                        "event_id": "group-event-9",
                        "run_id": group_run_id,
                        "sequence": 9,
                        "event_type": "group.run.completed",
                        "payload": {"group_run_id": group_run_id},
                    }
                ],
            }

    port = PagedGroupRunEventPort()
    service = AgentStudioService(port)

    stream = list(service.get_group_run_event_stream("group-run-1"))
    page = service.get_group_run_event_page("group-run-1", after_sequence=3, limit=1)

    assert stream[0].sequence == 4
    assert stream[0].event_type == "group.member.started"
    assert page.run_id == "group-run-1"
    assert page.after_sequence == 3
    assert page.limit == 1
    assert page.next_after_sequence == 9
    assert page.has_more is True
    assert page.events[0].sequence == 9
    assert page.events[0].event_type == "group.run.completed"
    assert ("get_group_run_event_stream", "group-run-1") in port.calls
    assert (
        "get_group_run_event_page",
        {"group_run_id": "group-run-1", "after_sequence": 3, "limit": 1},
    ) in port.calls
    assert ("get_group_run", "group-run-1") not in port.calls


def test_agent_studio_service_prefers_runtime_run_event_page_port() -> None:
    class PagedRunEventPort(_FakeStudioPort):
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
                "next_after_sequence": 7,
                "has_more": True,
                "events": [
                    {
                        "event_id": "event-page-7",
                        "run_id": run_id,
                        "sequence": 7,
                        "event_type": "agent.tool.call",
                        "payload": {"tool": "workspace.read"},
                    }
                ],
            }

    port = PagedRunEventPort()
    service = AgentStudioService(port)

    page = service.get_run_event_page("run-1", after_sequence=3, limit=1)

    assert page.run_id == "run-1"
    assert page.after_sequence == 3
    assert page.limit == 1
    assert page.next_after_sequence == 7
    assert page.has_more is True
    assert page.events[0].sequence == 7
    assert page.events[0].event_type == "agent.tool.call"
    assert (
        "get_run_event_page",
        {"run_id": "run-1", "after_sequence": 3, "limit": 1},
    ) in port.calls
    assert ("get_run_event_stream", "run-1") not in port.calls


def test_agent_studio_service_run_actions_return_public_timeline_snapshots() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    rerun = service.rerun_run("run-1")
    cancelled = service.cancel_run("run-1")
    deleted = service.delete_run("run-1")
    approved = service.approve_run_approval(
        "run-1",
        ApprovalDecision(
            approved=True,
            reason="Looks safe",
            metadata={"approval_id": "approval-1"},
        ),
    )
    rejected = service.reject_run_approval(
        "run-1",
        ApprovalDecision(
            approved=False,
            reason="No",
            metadata={"approval_id": "approval-1"},
        ),
    )

    assert rerun.run_id == "run-1-rerun"
    assert rerun.rerun_of_run_id == "run-1"
    assert rerun.rerun_of_kind == "agent_run"
    assert rerun.rerun_of_status == "completed"
    assert rerun.rerun_of_runnable_id == "agent-1"
    assert rerun.rerun_of_runnable_name == "Planner"
    assert rerun.rerun_original_created_at == "2026-06-13T00:00:00Z"
    assert rerun.rerun_original_updated_at == "2026-06-13T00:00:04Z"
    assert cancelled.status == "cancelled"
    assert deleted == {"ok": True, "deleted_run_ids": ["run-1"], "deleted_run_count": 1}
    assert approved.status == "completed"
    assert rejected.status == "failed"
    assert ("rerun_run", "run-1") in port.calls
    assert ("cancel_run", "run-1") in port.calls
    assert ("delete_run", "run-1") in port.calls
    assert (
        "approve_run_approval",
        {
            "run_id": "run-1",
            "decision": {
                "approved": True,
                "reason": "Looks safe",
                "metadata": {"approval_id": "approval-1"},
            },
        },
    ) in port.calls
    assert (
        "reject_run_approval",
        {
            "run_id": "run-1",
            "decision": {
                "approved": False,
                "reason": "No",
                "metadata": {"approval_id": "approval-1"},
            },
        },
    ) in port.calls


def test_agent_studio_service_passes_scoped_rerun_request_to_port() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    service.rerun_run(
        "workflow-run-1",
        RerunRunRequest(
            scope="workflow_branch",
            workflow_node_id="route",
            workflow_edge_branch="true",
            workflow_node_selected_target="ship",
            reason="Retry selected branch",
        ),
    )

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
    ) in port.calls


def test_agent_studio_service_run_actions_preserve_workflow_run_snapshots() -> None:
    class _WorkflowActionPort(_FakeStudioPort):
        def rerun_run(
            self,
            run_id: str,
            request: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            clean_request = dict(request or {})
            self.calls.append(
                (
                    "rerun_run",
                    {"run_id": run_id, "request": clean_request}
                    if clean_request
                    else run_id,
                )
            )
            payload = _workflow_run_payload(run_id=f"{run_id}-rerun", status="running")
            payload["timeline"] = [
                _rerun_started_event(
                    run_id,
                    kind="workflow_run",
                    status="completed",
                    runnable_id="workflow-1",
                    runnable_name="Review workflow",
                )
            ]
            return payload

        def cancel_run(self, run_id: str) -> dict[str, Any]:
            self.calls.append(("cancel_run", run_id))
            return _workflow_run_payload(run_id=run_id, status="cancelled")

        def approve_run_approval(self, run_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
            self.calls.append(("approve_run_approval", {"run_id": run_id, "decision": decision}))
            return _workflow_run_payload(
                run_id=run_id,
                status="completed",
                final_answer="Workflow approved",
            )

        def reject_run_approval(self, run_id: str, decision: dict[str, Any] | None = None) -> dict[str, Any]:
            reason = str((decision or {}).get("reason") or "")
            self.calls.append(("reject_run_approval", {"run_id": run_id, "decision": decision}))
            return _workflow_run_payload(
                run_id=run_id,
                status="failed",
                final_answer=f"Rejected: {reason}",
            )

    port = _WorkflowActionPort()
    service = AgentStudioService(port)

    rerun = service.rerun_run("workflow-run-1")
    cancelled = service.cancel_run("workflow-run-1")
    approved = service.approve_run_approval("workflow-run-1")
    rejected = service.reject_run_approval("workflow-run-1", "No")

    assert rerun.workflow_run_id == "workflow-run-1-rerun"
    assert rerun.workflow_id == "workflow-1"
    assert rerun.current_node_id == "review"
    assert rerun.rerun_of_run_id == "workflow-run-1"
    assert rerun.rerun_of_kind == "workflow_run"
    assert rerun.rerun_of_status == "completed"
    assert rerun.rerun_of_runnable_id == "workflow-1"
    assert rerun.rerun_of_runnable_name == "Review workflow"
    assert cancelled.status == "cancelled"
    assert cancelled.objective == "Review docs"
    assert approved.final_answer == "Workflow approved"
    assert rejected.final_answer == "Rejected: No"
    assert ("rerun_run", "workflow-run-1") in port.calls
    assert ("cancel_run", "workflow-run-1") in port.calls
    assert (
        "approve_run_approval",
        {"run_id": "workflow-run-1", "decision": None},
    ) in port.calls
    assert (
        "reject_run_approval",
        {"run_id": "workflow-run-1", "decision": {"approved": False, "reason": "No"}},
    ) in port.calls


def test_agent_studio_service_reads_run_artifact_through_port() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    artifact = service.read_run_artifact("run-1", "reports/final.md")

    assert artifact.ok is True
    assert artifact.run_id == "run-1"
    assert artifact.task_id is None
    assert artifact.path == "reports/final.md"
    assert artifact.content == "# Report"
    assert artifact.truncated is False
    assert (
        "read_run_artifact",
        {"run_id": "run-1", "artifact_path": "reports/final.md"},
    ) in port.calls


def test_agent_studio_service_redacts_sensitive_run_artifact_content() -> None:
    class _SensitiveArtifactPort(_FakeStudioPort):
        def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
            return {
                "ok": True,
                "run_id": run_id,
                "path": "reports/sk-sensitive-value.md",
                "content": "token sk-sensitive-value",
                "mime_type": "text/markdown",
                "truncated": False,
            }

    service = AgentStudioService(_SensitiveArtifactPort())

    artifact = service.read_run_artifact("run-1", "reports/sk-sensitive-value.md")
    rendered = str(artifact.model_dump(mode="json"))

    assert "sk-sensitive-value" not in rendered
    assert "[redacted]" in rendered
    assert artifact.run_id == "run-1"
    assert artifact.mime_type == "text/markdown"


def _desk_payload(
    agent_id: str = "agent-1",
    note: str = "# Desk Notes",
    file_path: str = "inputs/brief.md",
    file_text: str = "Brief",
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "root_path": f"/workspace/{agent_id}",
        "notes_path": "desk-notes.md",
        "metadata_path": ".yachiyo-desk.json",
        "items": [
            {
                "path": "desk-notes.md",
                "name": "desk-notes.md",
                "kind": "note",
                "size_bytes": len(note.encode("utf-8")),
                "mime_type": "text/markdown",
                "preview_text": note,
                "updated_at": "2026-06-22T00:00:00Z",
            },
            {
                "path": file_path,
                "name": file_path.rsplit("/", 1)[-1],
                "kind": "file",
                "size_bytes": len(file_text.encode("utf-8")),
                "mime_type": "text/markdown",
                "preview_text": file_text,
                "updated_at": "2026-06-22T00:00:01Z",
            },
        ],
        "updated_at": "2026-06-22T00:00:02Z",
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
        "skill_ids": ["skill-1"] if skill_ids is None else skill_ids,
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
    prompt: str = "Follow up on the report",
    error: str = "",
    status: str = "scheduled",
    last_run_id: str = "",
    run_count: int = 0,
    cancelled_at: str = "",
) -> dict[str, Any]:
    return {
        "future_task_id": future_task_id,
        "title": "Follow up later",
        "prompt": prompt,
        "runnable_id": "agent-1",
        "runnable_name": "Planner",
        "status": status,
        "scheduled_at_epoch": 1781433600.0,
        "cron": "",
        "source_run_id": "run-source-1",
        "last_run_id": last_run_id,
        "run_count": run_count,
        "error": error,
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
        "cancelled_at": cancelled_at,
    }


def _group_payload(group_id: str = "group-1", name: str = "Research Team") -> dict[str, Any]:
    return {
        "group_id": group_id,
        "name": name,
        "members": [{"agent_id": "agent-1", "name": "Planner", "role": "planner"}],
        "mode": "debate",
        "memory_scope": "hybrid",
        "enabled": True,
    }


def _group_run_payload(
    group_run_id: str = "group-run-1",
    group_id: str = "group-1",
    objective: str = "Compare options",
) -> dict[str, Any]:
    return {
        "group_run_id": group_run_id,
        "group_id": group_id,
        "title": "Group run",
        "status": "running",
        "objective": objective,
        "participants": [{"agent_id": "agent-1", "name": "Planner"}],
        "events": [
            {
                "event_type": "group.member.started",
                "detail": "Planner started",
                "payload": {"member_agent_id": "agent-1"},
            }
        ],
        "runs": [_run_payload()],
        "shared_artifacts": [{"artifact_id": "shared-1", "kind": "markdown", "path": "team.md"}],
        "pending_approvals": [{"approval_id": "approval-1", "tool": "terminal.run"}],
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
    runnable_id: str = "agent-1",
    kind: str = "agent_run",
    user_goal: str = "Read README",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "run_group_id": "group-run-1",
        "kind": kind,
        "runnable_id": runnable_id,
        "status": "approval_required",
        "user_goal": user_goal,
        "task_id": "task-1",
        "session_id": "chat-1",
        "task_run_link_created_at": "2026-06-14T00:00:00Z",
        "task_run_link_updated_at": "2026-06-14T00:00:02Z",
        "task_run_link_run_status": "approval_required",
        "task_run_link_last_event_sequence": 7,
        "timeline": [
            {
                "event": "agent.tool.call",
                "detail": "workspace.read",
                "input_preview": {"path": "README.md"},
            }
        ],
        "pending_approval": {"approval_id": "approval-1", "tool": "terminal.run"},
        "artifacts": [{"artifact_id": "artifact-1", "kind": "markdown", "path": "report.md"}],
        "children": [{"run_id": "child-run-1", "status": "completed"}],
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }


def _workflow_run_payload(
    run_id: str = "workflow-run-1",
    status: str = "approval_required",
    final_answer: str = "",
) -> dict[str, Any]:
    return _run_payload(
        run_id=run_id,
        runnable_id="workflow-1",
        kind="workflow_run",
        user_goal="Review docs",
    ) | {
        "status": status,
        "workflow_id": "workflow-1",
        "workflow_run_id": run_id,
        "current_node_id": "review",
        "current_node_label": "Review",
        "final_answer": final_answer,
    }


def _rerun_started_event(
    original_run_id: str,
    *,
    kind: str,
    status: str,
    runnable_id: str,
    runnable_name: str,
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
        },
    }
