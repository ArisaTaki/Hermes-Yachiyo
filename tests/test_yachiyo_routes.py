"""Yachiyo public facade route tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.bridge.routes import yachiyo


class _FakeAgentRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.task_links: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}

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

    def rerun_run(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("rerun_run", run_id))
        return _run_payload(run_id=f"{run_id}-rerun", status="processing")

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
        return _run_payload(
            run_id="workflow-run-1",
            kind="workflow_run",
            runnable_id=payload["workflow_id"],
            user_goal=payload["user_goal"],
        )

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_group", run_group_id))
        return {
            "run_group_id": run_group_id,
            "title": "Run group",
            "source": "workflow",
            "status": "running",
            "summary": "Summary",
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
    started = await yachiyo.start_task(
        yachiyo.StartChatTaskRequest(prompt="Patch README", conversation_id="chat-1"),
        request,
    )
    tasks = await yachiyo.list_tasks("chat-1", request)
    approved = await yachiyo.approve_task("run-1", None, request)
    rejected = await yachiyo.reject_task(
        "run-1",
        yachiyo.TaskApprovalRequest(reason="No"),
        request,
    )
    cancelled = await yachiyo.cancel_task("run-1", request)

    assert readiness["ready"] is True
    assert started["task_id"] == "run-1"
    assert started["status"] == "waiting_approval"
    assert started["conversation_id"] == "chat-1"
    assert started["open_in_studio_url"] == "#/agents?run_id=run-1"
    assert tasks["tasks"][0]["task_id"] == "run-1"
    assert tasks["tasks"][0]["conversation_id"] == "chat-1"
    assert all(task["task_id"] != "studio-run" for task in tasks["tasks"])
    assert approved["status"] == "completed"
    assert rejected["status"] == "failed"
    assert cancelled["status"] == "cancelled"
    assert runtime.calls[1] == (
        "create_run_for_runnable_async",
        {"runnable_id": "builtin:yachiyo-main", "user_goal": "Patch README"},
    )
    assert runtime.calls[2] == (
        "link_task_run",
        {"task_id": "run-1", "run_id": "run-1", "session_id": "chat-1"},
    )


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
        ) -> dict[str, Any]:
            self._app_runtime.chat_calls.append(
                {
                    "session_id": session_id,
                    "text": text,
                    "runnable_id": runnable_id,
                    "client_message_id": client_message_id,
                }
            )
            return {
                "ok": True,
                "run_id": "run-1",
                "agent_run_id": "run-1",
                "session_id": "chat-1",
                "status": "processing",
            }

    monkeypatch.setattr(yachiyo, "ChatAPI", FakeChatAPI)

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
        }
    ]
    assert (
        "link_task_run",
        {"task_id": "run-1", "run_id": "run-1", "session_id": "chat-1"},
    ) in runtime.calls
    assert not any(call[0] == "create_run_for_runnable_async" for call in runtime.calls)


@pytest.mark.asyncio
async def test_yachiyo_studio_routes_wrap_legacy_runtime_shapes() -> None:
    runtime = _FakeAgentRuntime()
    request = _request(runtime)

    agents = await yachiyo.list_studio_agents(request)
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
    deleted_agent = await yachiyo.delete_studio_agent("agent-1", request)
    model_test = await yachiyo.test_studio_agent_model("agent-1", request)
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
    agent_run = await yachiyo.start_studio_agent_run(
        "agent-1",
        yachiyo.StartAgentRunBody(objective="Draft summary", client_run_id="client-agent-1"),
        request,
    )
    workflows = await yachiyo.list_studio_workflows(request)
    deleted_workflow = await yachiyo.delete_studio_workflow("workflow-1", request)
    workflow_run = await yachiyo.start_studio_workflow_run(
        "workflow-1",
        yachiyo.StartWorkflowRunBody(objective="Build report"),
        request,
    )
    runs = await yachiyo.list_studio_runs(request, limit=5)
    run_detail = await yachiyo.get_studio_run("run-1", request)
    timeline = await yachiyo.get_studio_run_timeline("run-1", request)
    group_runs = await yachiyo.list_studio_group_runs(request, limit=5)
    group_run = await yachiyo.get_studio_group_run("group-run-1", request)
    events = await yachiyo.get_studio_run_events("run-1", request, after_sequence=0, limit=1)
    rerun = await yachiyo.rerun_studio_run("run-1", request)
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
    assert groups["groups"][0]["group_id"] == "group-run-1"
    assert groups["groups"][0]["mode"] == "pipeline"
    assert groups["groups"][0]["members"][0]["agent_id"] == "agent-1"
    assert group["group_id"] == "group-run-1"
    assert started_group_run["group_id"] == "group-run-1"
    assert started_group_run["participants"][0]["agent_id"] == "agent-1"
    assert started_group_run["runs"][0]["run_id"] == "run-1"
    assert saved_agent["model_config"] == {"provider": "model_profile"}
    assert deleted_agent == {"ok": True, "agent_id": "agent-1"}
    assert agent_run["run_id"] == "agent-run-1"
    assert agent_run["agent_id"] == "agent-1"
    assert model_test == {"ok": True, "message": "Model ready"}
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
    assert workflows["workflows"][0]["workflow_id"] == "workflow-1"
    assert deleted_workflow == {"ok": True, "workflow_id": "workflow-1"}
    assert workflow_run["workflow_run_id"] == "workflow-run-1"
    assert runs["runs"][0]["run_id"] == "studio-run"
    assert run_detail["run_id"] == "run-1"
    assert timeline["run_group_id"] == "group-run-1"
    assert timeline["pending_approval"]["tool_name"] == "terminal.run"
    assert group_runs["group_runs"][0]["group_run_id"] == "group-run-1"
    assert group_runs["group_runs"][0]["runs"][0]["run_id"] == "run-1"
    assert group_run["run_group_id"] == "group-run-1"
    assert group_run["child_run_ids"] == ["run-1"]
    assert events["after_sequence"] == 0
    assert events["limit"] == 1
    assert events["events"][0]["event_type"] == "agent.started"
    assert rerun["run_id"] == "run-1-rerun"
    assert cancelled["status"] == "cancelled"
    assert deleted_run == {"ok": True, "deleted_run_ids": ["run-1"], "deleted_run_count": 1}
    assert approved["status"] == "completed"
    assert rejected["status"] == "failed"
    assert artifact["content"] == "# Report"
    assert ("rerun_run", "run-1") in runtime.calls
    assert ("cancel_run", "run-1") in runtime.calls
    assert ("delete_run", "run-1") in runtime.calls
    assert ("approve_run_approval", "run-1") in runtime.calls
    assert ("reject_run_approval", {"run_id": "run-1", "reason": "No"}) in runtime.calls
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
    assert (
        "append_run_event",
        {
            "run_id": "run-1",
            "event_type": "group.member.started",
            "payload": {
                "agent_id": "agent-1",
                "agent_name": "Planner",
                "group_id": "group-run-1",
                "member_index": 0,
                "member_role": "agent_run",
                "objective": "Compare designs",
                "run_group_id": "group-run-1",
                "run_id": "run-1",
                "status": "approval_required",
                "client_run_id": "client-group-1",
                "child_client_run_id": "client-group-1:0:agent-1",
            },
        },
    ) in runtime.calls
    assert (
        "read_run_artifact",
        {"run_id": "run-1", "artifact_path": "reports/final.md"},
    ) in runtime.calls


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
    assert '@router.get("/tasks")' in source
    assert '@router.post("/tasks")' in source
    assert '@router.get("/tasks/{task_id}")' in source
    assert '@router.post("/tasks/{task_id}/approve")' in source
    assert '@router.post("/tasks/{task_id}/reject")' in source
    assert '@router.post("/tasks/{task_id}/cancel")' in source
    assert '@router.get("/chat/readiness")' in source
    assert '@router.get("/chat/tasks")' in source
    assert '@router.post("/chat/tasks")' in source
    assert '@router.get("/chat/tasks/{task_id}")' in source
    assert '@router.post("/chat/tasks/{task_id}/approve")' in source
    assert '@router.post("/chat/tasks/{task_id}/reject")' in source
    assert '@router.post("/chat/tasks/{task_id}/cancel")' in source


def test_yachiyo_studio_routes_include_run_action_facade() -> None:
    source = Path(yachiyo.__file__).read_text(encoding="utf-8")

    assert '@router.post("/studio/agents/{agent_id}/runs")' in source
    assert '@router.delete("/studio/agents/{agent_id}")' in source
    assert '@router.post("/studio/agents/{agent_id}/test-model")' in source
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
    assert '@router.get("/studio/group-runs")' in source
    assert '@router.get("/studio/group-runs/{group_run_id}")' in source
    assert '@router.get("/studio/runs")' in source
    assert '@router.get("/studio/runs/{run_id}")' in source
    assert '@router.post("/studio/runs/{run_id}/rerun")' in source
    assert '@router.post("/studio/runs/{run_id}/cancel")' in source
    assert '@router.delete("/studio/runs/{run_id}")' in source
    assert '@router.post("/studio/runs/{run_id}/approval/approve")' in source
    assert '@router.post("/studio/runs/{run_id}/approval/reject")' in source
    assert '@router.get("/studio/runs/{run_id}/artifacts/{artifact_path:path}")' in source
    assert '@router.delete("/studio/workflows/{workflow_id}")' in source


def _request(runtime: _FakeAgentRuntime) -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(runtime=SimpleNamespace(agent_runtime_service=runtime))
        )
    )


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
