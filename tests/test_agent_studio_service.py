"""Fake-port tests for the Agent Studio facade."""

from __future__ import annotations

import json
from typing import Any

from apps.shell.agent.runtime.desktop_execution_providers import (
    LOCAL_DESKTOP_PROVIDER_ID,
    LOCAL_DESKTOP_PROVIDER_KIND,
)
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
    StartPlannerOrchestrationRequest,
    StartWorkflowRunRequest,
)
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort
from apps.shell.yachiyo_agent.planner_projection import planner_run_event_payloads
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


def _port_call_payload(port: Any, call_name: str) -> dict[str, Any]:
    return next(payload for name, payload in port.calls if name == call_name)


class _FakeStudioPort:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.plugins: dict[str, dict[str, Any]] = {
            "notes": _restricted_plugin_payload(enabled=False)
        }

    def list_agents(self) -> dict[str, Any]:
        self.calls.append(("list_agents", None))
        return {"ok": True, "agents": [_agent_payload()]}

    def list_tool_catalog(self) -> dict[str, Any]:
        self.calls.append(("list_tool_catalog", None))
        return {
            "source": "fake-port",
            "tools": [
                {
                    "tool_name": "media.apple_music_play",
                    "function_name": "media_apple_music_play",
                    "description": "Search and play Apple Music.",
                    "capability_id": "media_control",
                    "risk_level": "low",
                    "approval_required": False,
                    "input_schema": {"type": "object", "required": ["query"]},
                    "model_tool_schema": {"type": "function"},
                    "missing_permissions": ["music_app"],
                    "fallback_notes": ["Open Music when direct playback is unavailable."],
                    "diagnostic_route": "/ui/native-agent/diagnostics/cache",
                }
            ],
            "capabilities": {
                "media_control": {
                    "available": False,
                    "platform": "macos",
                    "missing_permissions": ["music_app"],
                    "tools": ["media.apple_music_play"],
                    "risk_default": "low",
                    "diagnostic_route": "/ui/native-agent/diagnostics/cache",
                }
            },
            "plugins": list(self.plugins.values()),
        }

    def list_restricted_tool_plugins(self) -> dict[str, Any]:
        self.calls.append(("list_restricted_tool_plugins", None))
        return {"ok": True, "plugins": list(self.plugins.values())}

    def install_restricted_tool_plugin(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("install_restricted_tool_plugin", request))
        plugin_id = str(request["plugin_id"])
        plugin = _restricted_plugin_payload(
            plugin_id=plugin_id,
            enabled=bool(request.get("enabled", True)),
        )
        self.plugins[plugin_id] = plugin
        return plugin

    def update_restricted_tool_plugin(
        self,
        plugin_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "update_restricted_tool_plugin",
                {"plugin_id": plugin_id, "request": request},
            )
        )
        plugin = self.plugins[plugin_id]
        if "enabled" in request:
            plugin = {**plugin, "enabled": bool(request["enabled"])}
            plugin["tools"] = [
                {**tool, "enabled": bool(request["enabled"])}
                for tool in plugin.get("tools") or []
            ]
            self.plugins[plugin_id] = plugin
        return plugin

    def uninstall_restricted_tool_plugin(self, plugin_id: str) -> dict[str, Any]:
        self.calls.append(("uninstall_restricted_tool_plugin", plugin_id))
        plugin = self.plugins.pop(plugin_id)
        return {**plugin, "enabled": False, "tools": []}

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


class _ReplanRecoveryActionPort(_FakeStudioPort):
    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        self.calls.append(("get_run_timeline", run_id))
        if run_id == "runtime-run-1":
            return _run_payload(run_id=run_id, user_goal="Open Apple Music") | {
                "agent_id": "agent-1",
                "events": [self._task_core_event()],
                "runtime_execution_envelope": self._runtime_retry_envelope(),
            }
        if run_id == "workflow-run-1":
            return _run_payload(
                run_id=run_id,
                runnable_id="workflow-1",
                kind="workflow_run",
                user_goal="Open Apple Music",
            ) | {
                "workflow_run_id": run_id,
                "workflow_id": "workflow-1",
                "children": [
                    {
                        "run_id": "child-run-1",
                        "kind": "agent_run",
                        "agent_id": "agent-2",
                    }
                ],
                "events": [
                    self._task_core_event(event_type="workflow.run.task_core.created"),
                    self._replan_event(source_run_id="child-run-1"),
                ],
            }
        return _run_payload(run_id=run_id, user_goal="Open Apple Music") | {
            "agent_id": "agent-1",
            "events": [
                self._task_core_event(),
                self._replan_event(source_run_id=run_id),
            ],
            "tool_calls": [self._tool_recovery_call(run_id)],
        }

    def get_group_run(self, group_run_id: str) -> dict[str, Any]:
        self.calls.append(("get_group_run", group_run_id))
        return _group_run_payload(group_run_id=group_run_id) | {
            "runs": [
                _run_payload(
                    run_id="child-run-1",
                    runnable_id="agent-2",
                    user_goal="Open Apple Music",
                )
                | {
                    "agent_id": "agent-2",
                    "tool_calls": [self._tool_recovery_call("child-run-1")],
                }
            ],
            "participants": [
                {
                    "agent_id": "agent-2",
                    "name": "Operator",
                    "role": "operator",
                    "run_id": "child-run-1",
                }
            ],
            "events": [
                self._task_core_event(event_type="group.run.task_core.created"),
                self._replan_event(source_run_id="child-run-1"),
            ],
        }

    def start_agent_run(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("start_agent_run", request))
        return _run_payload(
            run_id="recovery-run-1",
            runnable_id=request["agent_id"],
            user_goal=request["objective"],
        ) | {
            "status": "running",
            "timeline": [],
        }

    @staticmethod
    def _replan_event(source_run_id: str) -> dict[str, Any]:
        return {
            "event_type": "agent.replan.requested",
            "payload": {
                "request_id": "replan-1",
                "trigger": "tool_failure",
                "run_id": source_run_id,
                "task_id": "task-1",
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
        }

    @staticmethod
    def _task_core_event(event_type: str = "agent.task_core.created") -> dict[str, Any]:
        return {
            "event_type": event_type,
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
        }

    @staticmethod
    def _runtime_retry_envelope() -> dict[str, Any]:
        return {
            "envelope_id": "runtime-envelope-1",
            "decision_id": "decision-runtime-1",
            "plan_id": "runtime-plan-1",
            "intent_kind": "desktop_operation",
            "requests": [
                {
                    "request_id": "runtime-request-open-app",
                    "step_id": "open-app",
                    "capability_id": "desktop.app_control",
                    "decision_id": "decision-runtime-1",
                    "plan_id": "runtime-plan-1",
                    "core_id": "task-core-1",
                    "tool_name": "desktop.open_app",
                    "input": {"app_name": "Apple Music"},
                    "planning_reason": "planner_desktop_app_control",
                    "runtime_stage": "operate",
                    "status": "blocked",
                    "action_target": {
                        "action": "open_app",
                        "app_name": "Apple Music",
                    },
                    "observation_evidence": {
                        "blocking_condition": "foreground_focus_unavailable",
                        "foreground_required": True,
                        "foreground_ready": False,
                    },
                    "observation_retry": {
                        "tool": "desktop.open_app",
                        "input": {"app_name": "Music"},
                        "reason": "foreground_focus_unavailable",
                    },
                    "task_verification_targets": [
                        {
                            "step_id": "open-app",
                            "todo_id": "todo-open-app",
                        }
                    ],
                }
            ],
            "runtime_stage_counts": {"operate": 1},
            "replan_signal_count": 1,
        }

    @staticmethod
    def _tool_recovery_call(run_id: str) -> dict[str, Any]:
        return {
            "tool_call_id": "tool-call-1",
            "run_id": run_id,
            "tool_name": "desktop.open_app",
            "status": "failed",
            "risk_level": "low",
            "input_preview": {"app_name": "Apple Music"},
            "output_preview": {
                "error": "Application not found",
                "recovery_actions": [
                    {
                        "action_id": "tool-action-1",
                        "label": "Find Apple Music",
                        "tool": "desktop.list_apps",
                        "input": {"query": "Apple Music"},
                        "permission_target": "app_discovery",
                        "risk_level": "low",
                        "recovery_retry_tool": "desktop.open_app",
                        "recovery_retry_input": {"app_name": "Music"},
                        "desktop_execution_policy": {
                            "mode": "supervised_live",
                            "allow_live_foreground": True,
                            "source": "agent_studio_tool_recovery",
                        },
                        "sandbox_provider": {
                            "available": False,
                            "status": "provider_required",
                            "blocking_conditions": ["sandbox_desktop_provider_required"],
                        },
                        "desktop_execution_route": {
                            "status": "provider_required",
                            "can_execute": False,
                            "blocking_conditions": ["sandbox_desktop_provider_required"],
                        },
                    }
                ],
            },
        }


class _DeferredReplanRecoveryActionPort(_ReplanRecoveryActionPort):
    @staticmethod
    def _replan_event(source_run_id: str) -> dict[str, Any]:
        event = _ReplanRecoveryActionPort._replan_event(source_run_id)
        action = event["payload"]["metadata"]["recovery_actions"][0]
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
        return event


def _planner_events_with_failed_analysis() -> list[dict[str, Any]]:
    decision = RuntimePlanner().decision(
        "请分析 sales.csv 并输出一份数据分析报告",
        allowed_tools=["workspace.read", "data.analyze", "terminal.run", "artifact.write"],
    )
    analysis_step = next(
        step for step in decision.plan.tool_plan.steps if step.tool_name == "data.analyze"
    )
    events = [
        {"event_type": event_type, "payload": payload}
        for event_type, payload in planner_run_event_payloads(decision)
    ]
    events.append(
        {
            "event_id": "analysis-failed",
            "sequence": len(events) + 1,
            "event_type": "agent.tool.call",
            "payload": {
                "step_id": analysis_step.step_id,
                "tool_name": "data.analyze",
                "status": "failed",
                "result": {"ok": False, "error": "empty result"},
            },
        }
    )
    return events


def test_agent_studio_service_maps_agent_group_workflow_snapshots() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    agents = service.list_agents()
    tool_catalog = service.list_tool_catalog()
    restricted_plugins = service.list_restricted_tool_plugins()
    installed_plugin = service.install_restricted_tool_plugin(
        {"plugin_id": "desk", "enabled": True}
    )
    updated_plugin = service.update_restricted_tool_plugin("desk", {"enabled": False})
    uninstalled_plugin = service.uninstall_restricted_tool_plugin("desk")
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
    assert tool_catalog.source == "fake-port"
    assert tool_catalog.tools[0].tool_name == "media.apple_music_play"
    assert tool_catalog.tools[0].risk_level == "low"
    assert tool_catalog.tools[0].input_schema["required"] == ["query"]
    assert tool_catalog.tools[0].missing_permissions == ["music_app"]
    assert tool_catalog.capabilities["media_control"].available is False
    assert tool_catalog.plugins[0].plugin_id == "notes"
    assert tool_catalog.plugins[0].enabled is False
    assert tool_catalog.plugins[0].tools[0].risk_level == "medium"
    assert tool_catalog.legacy_cleanup_coverage is not None
    assert tool_catalog.legacy_cleanup_coverage.planner_owner == "runtime_planner"
    assert tool_catalog.legacy_cleanup_coverage.total_samples >= 57
    assert "app_launch" in tool_catalog.legacy_cleanup_coverage.areas
    assert "desktop_operation" in tool_catalog.legacy_cleanup_coverage.covered_intents
    assert "desktop.app_discovery" in tool_catalog.legacy_cleanup_coverage.covered_capabilities
    assert "desktop.list_apps" in tool_catalog.legacy_cleanup_coverage.covered_tools
    assert tool_catalog.legacy_cleanup_coverage.area_contracts[0].planner_tools
    assert tool_catalog.legacy_cleanup_coverage.sample_contracts[0].cleanup_status == "planner_covered"
    assert len(tool_catalog.legacy_cleanup_coverage.planner_owned_entrypoints) >= 5
    assert tool_catalog.legacy_cleanup_coverage.planner_owned_entrypoints[0].owner == "runtime_planner"
    assert tool_catalog.legacy_cleanup_coverage.planner_owned_entrypoints[0].legacy_shape_preserved is True
    assert len(tool_catalog.legacy_cleanup_coverage.remaining_fallback_contracts) >= 4
    assert tool_catalog.legacy_cleanup_coverage.remaining_fallback_contracts[0].status == (
        "planner_covered_compat_cleanup_pending"
    )
    assert tool_catalog.legacy_cleanup_coverage.remaining_fallback_contracts[0].required_before_delete
    assert restricted_plugins[0].plugin_id == "notes"
    assert installed_plugin.plugin_id == "desk"
    assert installed_plugin.enabled is True
    assert updated_plugin.enabled is False
    assert updated_plugin.tools[0].enabled is False
    assert uninstalled_plugin.plugin_id == "desk"
    assert uninstalled_plugin.enabled is False
    assert uninstalled_plugin.tools == []
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
    assert ("list_restricted_tool_plugins", None) in port.calls
    assert ("install_restricted_tool_plugin", {"plugin_id": "desk", "enabled": True}) in port.calls
    assert (
        "update_restricted_tool_plugin",
        {"plugin_id": "desk", "request": {"enabled": False}},
    ) in port.calls
    assert ("uninstall_restricted_tool_plugin", "desk") in port.calls
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
    assert ("list_tool_catalog", None) in port.calls
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


def test_legacy_studio_tool_catalog_exposes_local_desktop_provider(monkeypatch) -> None:
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    monkeypatch.delenv("OHA_YACHIYO_SANDBOX_DESKTOP_PROVIDER_EXECUTE_URL", raising=False)
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_ports.desktop_permission_missing_by_capability",
        lambda: {},
    )
    monkeypatch.setattr(
        "apps.shell.yachiyo_agent.legacy_ports.desktop_runtime_blocking_conditions_by_capability",
        lambda: {},
    )

    class Runtime:
        def list_restricted_tool_plugins(self) -> dict[str, Any]:
            return {"plugins": []}

    catalog = LegacyStudioPort(Runtime()).list_tool_catalog()
    provider = catalog["sandbox_provider"]
    tools = {tool["tool_name"]: tool for tool in catalog["tools"]}

    assert provider["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert provider["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert provider["status"] == "available"
    assert provider["keyboard_mouse_capture_supported"] is False
    assert provider["desktop_session_kind"] == "user_foreground"
    assert provider["desktop_session_isolated"] is False
    assert provider["foreground_takeover_required"] is True
    assert "desktop.safe_type_text" in provider["requires_real_sandbox_for"]
    assert "app.open" in provider["supported_tools"]
    assert "desktop.inspect_app" in provider["supported_tools"]
    assert tools["app.open"]["provider_ready"] is True
    assert tools["desktop.inspect_app"]["provider_ready"] is True
    assert tools["desktop.safe_type_text"]["provider_supported"] is False
    assert tools["app.open"]["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    controlled = catalog["controlled_provider_diagnostics"]
    assert controlled["ready"] is False
    assert controlled["configured"] is False
    assert controlled["status"] == "isolated_provider_required"
    assert controlled["provider_id"] == "local-isolated-desktop"
    assert "isolated_desktop_provider_required" in controlled["blocking_conditions"]
    assert controlled["keyboard_mouse_capture_supported"] is True
    assert controlled["desktop_session_kind"] == "isolated_desktop"
    assert controlled["desktop_session_isolated"] is True
    assert controlled["foreground_takeover_required"] is False
    assert controlled["launch_command"] == [
        "python",
        "scripts/run_isolated_desktop_provider.py",
        "--host",
        "127.0.0.1",
        "--port",
        "19093",
    ]
    assert controlled["smoke_command"] == [
        "python",
        "scripts/smoke_isolated_desktop_provider.py",
    ]
    assert (
        controlled["env"]["OHA_YACHIYO_DESKTOP_PROVIDER_URL"]
        == "http://127.0.0.1:19093"
    )


def test_agent_studio_service_plans_task_from_tool_catalog() -> None:
    class PlannerCatalogPort(_FakeStudioPort):
        def list_tool_catalog(self) -> dict[str, Any]:
            self.calls.append(("list_tool_catalog", None))
            return {
                "source": "planner-catalog",
                "tools": [
                    {"tool_name": "workspace.read", "function_name": "workspace_read"},
                    {"tool_name": "terminal.run", "function_name": "terminal_run"},
                    {"tool_name": "artifact.write", "function_name": "artifact_write"},
                ],
                "capabilities": {},
                "plugins": [],
            }

    port = PlannerCatalogPort()
    service = AgentStudioService(port)

    decision = service.plan_task("请分析 sales.csv 并输出数据分析报告")

    assert decision.selected_intent.kind == "data_analysis"
    assert decision.plan.tool_plan.missing_capabilities == []
    assert [step.tool_name for step in decision.plan.tool_plan.steps] == [
        "workspace.read",
        "terminal.run",
        "artifact.write",
    ]
    assert port.calls == [("list_tool_catalog", None)]


def test_agent_studio_plan_execution_projects_catalog_provider_to_runtime_requests(
    monkeypatch,
) -> None:
    for name in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
    ):
        monkeypatch.delenv(name, raising=False)

    class ProviderCatalogPort(_FakeStudioPort):
        def list_tool_catalog(self) -> dict[str, Any]:
            self.calls.append(("list_tool_catalog", None))
            return {
                "source": "planner-catalog",
                "tools": [
                    {
                        "tool_name": "desktop.list_apps",
                        "function_name": "desktop_list_apps",
                    },
                    {
                        "tool_name": "app.focus_and_click_ui_element",
                        "function_name": "app_focus_and_click_ui_element",
                    },
                    {
                        "tool_name": "desktop.ui_elements",
                        "function_name": "desktop_ui_elements",
                    },
                ],
                "capabilities": {},
                "sandbox_provider": {
                    "available": True,
                    "provider_id": "catalog-provider",
                    "provider_kind": "sandbox_desktop",
                    "adapter_ready": True,
                    "supported_tools": [
                        "desktop.list_apps",
                        "app.focus_and_click_ui_element",
                    ],
                },
                "plugins": [],
            }

    port = ProviderCatalogPort()
    service = AgentStudioService(port)

    envelope = service.plan_execution(
        "在 PixelForge 点击 Export",
        allowed_tools=[
            "desktop.list_apps",
            "app.focus_and_click_ui_element",
            "desktop.ui_elements",
        ],
        metadata={"surface": "studio"},
    )
    requests = {request.tool_name: request for request in envelope.requests}

    assert requests["desktop.list_apps"].sandbox_provider is not None
    assert (
        requests["desktop.list_apps"].sandbox_provider.provider_id
        == "catalog-provider"
    )
    assert requests["desktop.list_apps"].desktop_execution_route is not None
    assert requests["desktop.list_apps"].desktop_execution_route.status == "sandbox_ready"
    assert requests["app.focus_and_click_ui_element"].sandbox_provider is not None
    assert requests["app.focus_and_click_ui_element"].sandbox_provider.provider_id == (
        "catalog-provider"
    )
    assert requests["app.focus_and_click_ui_element"].desktop_execution_route is not None
    assert (
        requests["app.focus_and_click_ui_element"].desktop_execution_route.status
        == "sandbox_ready"
    )
    assert port.calls == [("list_tool_catalog", None)]


def test_agent_studio_service_planner_uses_tool_catalog_readiness_blockers() -> None:
    class PlannerCatalogPort(_FakeStudioPort):
        def list_tool_catalog(self) -> dict[str, Any]:
            self.calls.append(("list_tool_catalog", None))
            return {
                "source": "planner-catalog",
                "tools": [
                    {"tool_name": "desktop.list_apps", "function_name": "desktop_list_apps"},
                    {
                        "tool_name": "app.open_and_click_ui_element",
                        "function_name": "app_open_and_click_ui_element",
                    },
                    {"tool_name": "screen.capture", "function_name": "screen_capture"},
                ],
                "capabilities": {
                    "foreground_activation": {
                        "available": False,
                        "platform": "macos",
                        "blocking_conditions": ["foreground_focus_unavailable"],
                        "tools": ["app.open_and_click_ui_element"],
                        "available_tools": [],
                        "unavailable_tools": ["app.open_and_click_ui_element"],
                    }
                },
                "plugins": [],
            }

    port = PlannerCatalogPort()
    service = AgentStudioService(port)

    decision = service.plan_task("打开 PixelForge 并点击导出按钮")
    steps = {step.step_id: step for step in decision.plan.tool_plan.steps}

    assert decision.selected_intent.kind == "desktop_operation"
    assert steps["discover-desktop-state"].status == "planned"
    assert steps["operate-foreground-ui"].status == "unavailable"
    assert steps["operate-foreground-ui"].input_preview["blocking_conditions"] == [
        "foreground_focus_unavailable"
    ]
    assert decision.plan.tool_plan.missing_capabilities == ["desktop.ui_operation"]
    assert port.calls == [("list_tool_catalog", None)]


def test_agent_studio_service_prefers_port_planner_when_available() -> None:
    class PlannerPort(_FakeStudioPort):
        def plan_task(
            self,
            prompt: str,
            *,
            allowed_tools: list[str] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            self.calls.append(
                (
                    "plan_task",
                    {
                        "prompt": prompt,
                        "allowed_tools": allowed_tools,
                        "metadata": metadata,
                    },
                )
            )
            return RuntimePlanner().decision(
                prompt,
                allowed_tools=allowed_tools,
                metadata=metadata,
            ).model_dump(mode="json")

    port = PlannerPort()
    service = AgentStudioService(port)

    decision = service.plan_task(
        "打开 PixelForge 并点击导出按钮",
        allowed_tools=["desktop.running_apps", "app.open", "desktop.click_ui_element"],
        metadata={"surface": "studio"},
    )

    assert decision.selected_intent.kind == "desktop_operation"
    assert port.calls == [
        (
            "plan_task",
            {
                "prompt": "打开 PixelForge 并点击导出按钮",
                "allowed_tools": ["desktop.running_apps", "app.open", "desktop.click_ui_element"],
                    "metadata": {
                        "surface": "studio",
                        "desktop_provider_health_probe": True,
                        "desktop_provider_route_readonly": True,
                        "desktop_provider_route_foreground": True,
                        "desktop_provider_local_native": True,
                        "desktop_execution_policy": {
                            "mode": "supervised_live",
                            "allow_live_foreground": True,
                        "source": "agent_studio",
                        "reason": "Agent Studio is the supervised desktop execution and debugging surface.",
                    },
                },
            },
        )
    ]


def test_agent_studio_start_agent_run_uses_catalog_provider_without_env(
    monkeypatch,
) -> None:
    for name in (
        "OHA_YACHIYO_DESKTOP_PROVIDER_URL",
        "OHA_YACHIYO_DESKTOP_PROVIDER_ID",
        "OHA_YACHIYO_DESKTOP_PROVIDER_TOOLS",
    ):
        monkeypatch.delenv(name, raising=False)

    class ProviderCatalogPort(_FakeStudioPort):
        def list_tool_catalog(self) -> dict[str, Any]:
            self.calls.append(("list_tool_catalog", None))
            return {
                "source": "planner-catalog",
                "tools": [
                    {
                        "tool_name": "desktop.list_apps",
                        "function_name": "desktop_list_apps",
                    },
                    {
                        "tool_name": "app.focus_and_click_ui_element",
                        "function_name": "app_focus_and_click_ui_element",
                    },
                    {
                        "tool_name": "desktop.ui_elements",
                        "function_name": "desktop_ui_elements",
                    },
                ],
                "capabilities": {},
                "sandbox_provider": {
                    "available": True,
                    "provider_id": "catalog-provider",
                    "provider_kind": "sandbox_desktop",
                    "adapter_ready": True,
                    "supported_tools": [
                        "desktop.list_apps",
                        "app.focus_and_click_ui_element",
                    ],
                },
                "plugins": [],
            }

    port = ProviderCatalogPort()
    service = AgentStudioService(port)

    started = service.start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "在 PixelForge 点击 Export",
            "title": "PixelForge export",
            "allowed_tools": [
                "desktop.list_apps",
                "app.focus_and_click_ui_element",
                "desktop.ui_elements",
            ],
            "metadata": {"surface": "agent_studio"},
        }
    )

    start_payload = _port_call_payload(port, "start_agent_run")
    operation_request = next(
        request
        for request in start_payload["direct_tool_requests"]
        if request["tool"] == "app.focus_and_click_ui_element"
    )
    envelope_request = next(
        request
        for request in start_payload["metadata"]["yachiyo_execution_envelope"][
            "requests"
        ]
        if request["tool_name"] == "app.focus_and_click_ui_element"
    )
    plan_event = next(
        event for event in started.events if event.event_type == "agent.plan.created"
    )
    event_request = next(
        request
        for request in plan_event.payload["runtime_execution_envelope"]["requests"]
        if request["tool_name"] == "app.focus_and_click_ui_element"
    )

    assert [name for name, _payload in port.calls] == [
        "list_tool_catalog",
        "start_agent_run",
    ]
    assert operation_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert operation_request["sandbox_provider"]["provider_id"] == "catalog-provider"
    assert envelope_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert event_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert event_request["sandbox_provider"]["provider_id"] == "catalog-provider"


def test_agent_studio_start_agent_run_preserves_provider_routes(
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
                    "supported_tools": [
                        "desktop.list_apps",
                        "app.focus_and_click_ui_element",
                    ],
                    "capabilities": [
                        "desktop_discovery",
                        "sandbox_foreground",
                        "read_only_observation",
                    ],
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
        "desktop.list_apps,app.focus_and_click_ui_element",
    )
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    started = service.start_agent_run(
        {
            "agent_id": "agent-1",
            "objective": "在一个我没提过的新应用 PixelForge 点击 Export",
            "title": "PixelForge export",
            "allowed_tools": [
                "desktop.list_apps",
                "app.focus",
                "desktop.ui_elements",
                "app.focus_and_click_ui_element",
            ],
            "metadata": {"surface": "agent_studio"},
        }
    )

    start_payload = _port_call_payload(port, "start_agent_run")
    discovery_request = next(
        request
        for request in start_payload["direct_tool_requests"]
        if request["tool"] == "desktop.list_apps"
    )
    operation_request = next(
        request
        for request in start_payload["direct_tool_requests"]
        if request["tool"] == "app.focus_and_click_ui_element"
    )
    envelope_request = next(
        request
        for request in start_payload["metadata"]["yachiyo_execution_envelope"]["requests"]
        if request["tool_name"] == "desktop.list_apps"
    )
    assert calls
    assert discovery_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert discovery_request["desktop_execution_route"]["selected_provider_id"] == (
        "local-headless-desktop"
    )
    assert discovery_request["sandbox_provider"]["provider_id"] == "local-headless-desktop"
    assert operation_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert operation_request["desktop_execution_route"]["selected_provider_id"] == (
        "local-headless-desktop"
    )
    assert operation_request["sandbox_provider"]["provider_id"] == "local-headless-desktop"
    assert envelope_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert start_payload["runtime_execution_envelope"] == (
        start_payload["metadata"]["yachiyo_execution_envelope"]
    )
    plan_event = next(
        event for event in started.events if event.event_type == "agent.plan.created"
    )
    event_request = next(
        request
        for request in plan_event.payload["runtime_execution_envelope"]["requests"]
        if request["tool_name"] == "desktop.list_apps"
    )
    assert event_request["desktop_execution_route"]["status"] == "sandbox_ready"


def test_agent_studio_service_starts_workflow_from_planner_orchestration() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    started = service.start_planner_orchestration(
        StartPlannerOrchestrationRequest(
            prompt="运行 Review workflow",
            target_name="Review workflow",
            objective="Build report",
            title="Run Review workflow",
            client_run_id="studio-planner-workflow-1",
            metadata={"surface": "agent_studio"},
        )
    )

    assert started.kind == "workflow"
    assert started.status == "started"
    assert started.target_id == "workflow-1"
    assert started.target_name == "Review workflow"
    assert started.decision.selected_intent.kind == "workflow_orchestration"
    assert started.workflow_run is not None
    assert started.workflow_run.workflow_run_id == "workflow-run-1"
    assert started.group_run is None
    workflow_payload = _port_call_payload(port, "start_workflow_run")
    assert workflow_payload["workflow_id"] == "workflow-1"
    assert workflow_payload["objective"] == "Build report"
    assert workflow_payload["title"] == "Run Review workflow"
    assert workflow_payload["client_run_id"] == "studio-planner-workflow-1"
    metadata = workflow_payload["metadata"]
    assert metadata["surface"] == "agent_studio"
    assert metadata["source"] == "agent_studio_planner_orchestration"
    assert metadata["desktop_execution_policy"]["mode"] == "supervised_live"
    assert metadata["desktop_execution_policy"]["allow_live_foreground"] is True
    assert metadata["planner_orchestration"] is True
    assert metadata["planner_orchestration_kind"] == "workflow"
    assert metadata["planner_orchestration_target_id"] == "workflow-1"
    assert metadata["planner_orchestration_target"] == "Review workflow"
    assert metadata["decision_id"] == started.decision.decision_id
    assert metadata["plan_id"] == started.decision.plan.plan_id
    assert metadata["intent_kind"] == "workflow_orchestration"
    assert metadata["route_to_studio"] is True
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "workflow_orchestration"
    assert metadata["yachiyo_execution_requests"] == ["workflow.run"]
    assert metadata["yachiyo_execution_envelope"]["intent_kind"] == "workflow_orchestration"
    assert metadata["yachiyo_execution_envelope"]["desktop_execution_policy"]["mode"] == (
        "supervised_live"
    )
    assert metadata["yachiyo_execution_envelope"]["requests"][0][
        "desktop_execution_policy"
    ]["mode"] == "supervised_live"
    assert workflow_payload["runtime_execution_envelope"] == metadata["yachiyo_execution_envelope"]
    assert workflow_payload["direct_tool_requests"][0]["tool"] == "workflow.run"
    assert workflow_payload["direct_tool_requests"][0]["workflow_id"] == "workflow-1"
    assert workflow_payload["direct_tool_requests"][0]["task_todo"]["tool_name"] == "workflow.run"
    assert workflow_payload["direct_tool_requests"][0]["checkpoint_policy"][
        "requires_post_action_verification"
    ] is True
    metadata_request = metadata["yachiyo_execution_envelope"]["requests"][0]
    assert metadata_request["workflow_id"] == "workflow-1"
    planner_events = [
        event
        for event in started.workflow_run.events
        if event.payload.get("planner_event_type") == "agent.intent.selected"
    ]
    assert planner_events[0].event_type == "workflow.run.intent.selected"
    assert planner_events[0].payload["intent"]["kind"] == "workflow_orchestration"
    plan_event = next(
        event
        for event in started.workflow_run.events
        if event.payload.get("planner_event_type") == "agent.plan.created"
    )
    assert isinstance(plan_event.payload["plan"]["tool_plan"]["steps"][0], dict)
    assert isinstance(plan_event.payload["plan"]["capabilities"][0]["tools"], list)
    assert isinstance(
        plan_event.payload["runtime_execution_envelope"]["requests"][0]["input"],
        dict,
    )
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert plan_event.payload["workflow_id"] == "workflow-1"
    assert plan_event.payload["workflow_run_id"] == "workflow-run-1"
    assert event_request["workflow_id"] == "workflow-1"
    assert event_request["workflow_run_id"] == "workflow-run-1"
    assert workflow_payload["direct_tool_requests"][0]["desktop_execution_policy"][
        "mode"
    ] == "supervised_live"


def test_agent_studio_service_starts_group_run_from_planner_orchestration() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    started = service.start_planner_orchestration(
        {
            "prompt": "运行 Research Team group 调研 Hanako",
            "target_name": "Research Team",
            "objective": "调研 Hanako",
            "title": "Research Team GroupRun",
            "client_run_id": "studio-planner-group-1",
            "metadata": {"surface": "agent_studio"},
        }
    )

    assert started.kind == "group_run"
    assert started.status == "started"
    assert started.target_id == "group-1"
    assert started.target_name == "Research Team"
    assert started.decision.selected_intent.kind == "multi_agent"
    assert started.group_run is not None
    assert started.group_run.group_run_id == "group-run-1"
    assert started.workflow_run is None
    group_payload = _port_call_payload(port, "start_group_run")
    assert group_payload["group_id"] == "group-1"
    assert group_payload["objective"] == "调研 Hanako"
    assert group_payload["title"] == "Research Team GroupRun"
    assert group_payload["client_run_id"] == "studio-planner-group-1"
    metadata = group_payload["metadata"]
    assert metadata["surface"] == "agent_studio"
    assert metadata["source"] == "agent_studio_planner_orchestration"
    assert metadata["desktop_execution_policy"]["mode"] == "supervised_live"
    assert metadata["desktop_execution_policy"]["allow_live_foreground"] is True
    assert metadata["planner_orchestration"] is True
    assert metadata["planner_orchestration_kind"] == "group_run"
    assert metadata["planner_orchestration_target_id"] == "group-1"
    assert metadata["planner_orchestration_target"] == "Research Team"
    assert metadata["decision_id"] == started.decision.decision_id
    assert metadata["plan_id"] == started.decision.plan.plan_id
    assert metadata["intent_kind"] == "multi_agent"
    assert metadata["route_to_studio"] is True
    assert metadata["yachiyo_runtime_planner"] is True
    assert metadata["yachiyo_intent_kind"] == "multi_agent"
    assert metadata["yachiyo_execution_requests"] == ["group.run"]
    assert metadata["yachiyo_execution_envelope"]["intent_kind"] == "multi_agent"
    assert metadata["yachiyo_execution_envelope"]["desktop_execution_policy"]["mode"] == (
        "supervised_live"
    )
    assert metadata["yachiyo_execution_envelope"]["requests"][0][
        "desktop_execution_policy"
    ]["mode"] == "supervised_live"
    assert group_payload["runtime_execution_envelope"] == metadata["yachiyo_execution_envelope"]
    assert group_payload["direct_tool_requests"][0]["tool"] == "group.run"
    assert group_payload["direct_tool_requests"][0]["desktop_execution_policy"]["mode"] == (
        "supervised_live"
    )
    assert group_payload["direct_tool_requests"][0]["group_id"] == "group-1"
    assert group_payload["direct_tool_requests"][0]["task_todo"]["tool_name"] == "group.run"
    assert group_payload["direct_tool_requests"][0]["checkpoint_policy"][
        "requires_post_action_verification"
    ] is True
    metadata_request = metadata["yachiyo_execution_envelope"]["requests"][0]
    assert metadata_request["group_id"] == "group-1"
    planner_events = [
        event
        for event in started.group_run.events
        if event.payload.get("planner_event_type") == "agent.intent.selected"
    ]
    assert planner_events[0].event_type == "group.run.intent.selected"
    assert planner_events[0].payload["intent"]["kind"] == "multi_agent"
    plan_event = next(
        event
        for event in started.group_run.events
        if event.payload.get("planner_event_type") == "agent.plan.created"
    )
    assert isinstance(plan_event.payload["plan"]["tool_plan"]["steps"][0], dict)
    assert isinstance(plan_event.payload["plan"]["capabilities"][0]["tools"], list)
    assert isinstance(
        plan_event.payload["runtime_execution_envelope"]["requests"][0]["input"],
        dict,
    )
    event_request = plan_event.payload["runtime_execution_envelope"]["requests"][0]
    assert plan_event.payload["group_id"] == "group-1"
    assert plan_event.payload["group_run_id"] == "group-run-1"
    assert plan_event.payload["run_group_id"] == "group-run-1"
    assert event_request["group_id"] == "group-1"
    assert event_request["group_run_id"] == "group-run-1"
    assert event_request["run_group_id"] == "group-run-1"


def test_agent_studio_service_returns_structured_handoff_when_planner_target_missing() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    handoff = service.start_planner_orchestration(
        {
            "prompt": "运行 Missing workflow",
            "target_name": "Missing workflow",
        }
    )

    assert handoff.kind == "workflow"
    assert handoff.status == "target_not_found"
    assert handoff.target_name == "Missing workflow"
    assert handoff.decision.selected_intent.kind == "workflow_orchestration"
    assert handoff.workflow_run is None
    assert handoff.group_run is None
    assert "Workflow target not found" in handoff.message
    assert not any(call[0] == "start_workflow_run" for call in port.calls)


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
    assert group_run.tool_calls[0].group_run_id == "group-run-1"
    assert group_run.tool_calls[0].group_id == "group-1"
    assert group_run.tool_calls[0].source_run_id == "run-1"
    assert group_run.participants[0].pending_approvals[0].approval_id == "approval-1"
    assert group_run.participants[0].artifacts[0].path == "report.md"
    assert group_run.pending_approvals[0].approval_id == "approval-1"
    assert group_run.pending_approvals[0].group_id == "group-1"
    assert [artifact.path for artifact in group_run.shared_artifacts] == ["team.md", "report.md"]
    assert group_run.shared_artifacts[1].source_run_id == "run-1"
    assert group_run.shared_artifacts[1].group_run_id == "group-run-1"
    assert group_run.shared_artifacts[1].group_id == "group-1"
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
    assert workflow_run.tool_calls[0].workflow_id == "workflow-1"
    assert workflow_run.tool_calls[0].workflow_run_id == "workflow-run-1"
    assert workflow_run.pending_approval is not None
    assert workflow_run.pending_approval.workflow_id == "workflow-1"
    assert workflow_run.pending_approval.workflow_run_id == "workflow-run-1"
    assert workflow_run.artifacts[0].workflow_id == "workflow-1"
    assert workflow_run.artifacts[0].workflow_run_id == "workflow-run-1"
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
    group_request = _port_call_payload(port, "start_group_run")
    assert group_request["group_id"] == "group-1"
    assert group_request["objective"] == "Compare designs"
    assert group_request["client_run_id"] == "client-group-1"
    assert group_request["metadata"]["runtime_planner_entrypoint"] is True
    assert group_request["metadata"]["yachiyo_runtime_planner"] is True
    group_envelope = group_request["metadata"]["yachiyo_execution_envelope"]
    assert group_envelope["intent_kind"]
    assert ("list_group_runs", 5) in port.calls
    assert ("list_run_timelines", 10) in port.calls


def test_agent_studio_service_projects_workflow_child_debug_items_with_context() -> None:
    class WorkflowChildDebugPort(_FakeStudioPort):
        def start_workflow_run(self, request: dict[str, Any]) -> dict[str, Any]:
            self.calls.append(("start_workflow_run", request))
            return {
                "run_id": "workflow-run-debug",
                "workflow_id": request["workflow_id"],
                "runnable_id": request["workflow_id"],
                "kind": "workflow_run",
                "status": "approval_required",
                "user_goal": request["objective"],
                "child_runs": [
                    {
                        "run_id": "workflow-child-debug",
                        "agent_id": "agent-1",
                        "status": "approval_required",
                        "tool_calls": [
                            {
                                "tool_call_id": "tool-child-debug",
                                "tool": "workspace.read",
                                "status": "completed",
                            }
                        ],
                        "pending_approval": {
                            "approval_id": "approval-child-debug",
                            "tool": "terminal.run",
                        },
                        "artifacts": [
                            {
                                "artifact_id": "artifact-child-debug",
                                "kind": "markdown",
                                "path": "child-report.md",
                            }
                        ],
                    }
                ],
            }

    service = AgentStudioService(WorkflowChildDebugPort())

    workflow_run = service.start_workflow_run(
        StartWorkflowRunRequest(workflow_id="workflow-1", objective="Build child report")
    )

    assert workflow_run.tool_calls[0].source_run_id == "workflow-child-debug"
    assert workflow_run.tool_calls[0].workflow_id == "workflow-1"
    assert workflow_run.tool_calls[0].workflow_run_id == "workflow-run-debug"
    assert workflow_run.pending_approval is not None
    assert workflow_run.pending_approval.source_run_id == "workflow-child-debug"
    assert workflow_run.pending_approval.workflow_id == "workflow-1"
    assert workflow_run.pending_approval.workflow_run_id == "workflow-run-debug"
    assert workflow_run.artifacts[0].source_run_id == "workflow-child-debug"
    assert workflow_run.artifacts[0].workflow_id == "workflow-1"
    assert workflow_run.artifacts[0].workflow_run_id == "workflow-run-debug"


def test_agent_studio_service_starts_replan_recovery_action_direct_run() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_replan_recovery_action(
        "run-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
        },
    )

    assert run.run_id == "recovery-run-1"
    assert run.recovery_source is not None
    assert run.recovery_source.kind == "replan"
    assert run.recovery_source.source_run_id == "run-1"
    assert run.recovery_source.replan_request_id == "replan-1"
    assert run.recovery_source.recovery_action_id == "replan-1:action:1:desktop.list_apps"
    assert run.recovery_source.recovery_tool == "desktop.list_apps"
    assert run.recovery_source.task_core_context["core_id"] == "task-core-1"
    request = _port_call_payload(port, "start_agent_run")
    assert request["agent_id"] == "agent-1"
    assert request["metadata"]["desktop_permission_recovery"] is True
    assert request["metadata"]["recovery_tool"] == "desktop.list_apps"
    assert request["metadata"]["replan_request_id"] == "replan-1"
    assert request["metadata"]["source_run_id"] == "run-1"
    assert request["metadata"]["source_step_id"] == "open-app"
    assert request["metadata"]["source_tool_name"] == "desktop.open_app"
    assert request["metadata"]["target_capability_id"] == "desktop.app_discovery"
    assert request["metadata"]["replan_triggers"] == ["verification_failed", "tool_failure"]
    assert request["metadata"]["replan_signal_ids"] == ["signal-1"]
    assert request["metadata"]["task_core_context"]["core_id"] == "task-core-1"
    assert request["metadata"]["task_core_context"]["workspace_id"] == "task-workspace-1"
    assert request["metadata"]["task_core_context"]["todos"][0]["todo_id"] == "todo-open-app"
    assert (
        request["metadata"]["task_core_context"]["task_verification_targets"][0][
            "workspace_items"
        ][0]["item_id"]
        == "workspace-open-app"
    )
    direct_request = request["direct_tool_requests"][0]
    assert direct_request["tool"] == "desktop.list_apps"
    assert direct_request["input"] == {"query": "Apple Music"}
    assert direct_request["source"] == "agent_studio_replan_recovery"
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
    assert direct_request["core_id"] == "task-core-1"
    assert direct_request["workspace_id"] == "task-workspace-1"
    assert direct_request["task_todo"]["todo_id"] == "todo-open-app"
    assert direct_request["task_checkpoints"][0]["checkpoint_id"] == "checkpoint:open-app"
    assert direct_request["task_workspace_items"][0]["item_id"] == "workspace-open-app"
    assert any(
        target.get("todo_id") == "todo-open-app"
        for target in direct_request["verification_targets"]
    )
    assert any(
        target.get("tool_name") == "desktop.open_app"
        for target in direct_request["verification_targets"]
    )
    assert direct_request["task_verification_targets"][0]["todo"]["todo_id"] == "todo-open-app"
    assert direct_request["task_verification_targets"][0]["checkpoints"][0]["checkpoint_id"] == "checkpoint:open-app"
    assert (
        direct_request["task_verification_targets"][0]["workspace_items"][0]["item_id"]
        == "workspace-open-app"
    )


def test_agent_studio_service_preserves_deferred_replan_recovery_context() -> None:
    port = _DeferredReplanRecoveryActionPort()
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
    assert continuation["source"] == "agent_studio_replan_recovery"
    assert continuation["planning_reason"] == "planner_replan_deferred_continuation"
    assert continuation["replan_request_id"] == "replan-1"
    assert continuation["replan_recovery_action_id"] == (
        "replan-1:action:1:desktop.list_apps"
    )
    assert continuation["core_id"] == "task-core-1"
    assert continuation["task_verification_targets"][0]["step_id"] == "open-app"


def test_agent_studio_service_blocks_auto_start_for_deferred_approval_replan() -> None:
    port = _DeferredReplanRecoveryActionPort()
    service = AgentStudioService(port)

    continuation = service.plan_replan_recovery_action(
        "run-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
            "agent_id": "agent-1",
        },
    )

    assert continuation.approval_required is True
    assert continuation.auto_start_eligible is False
    assert continuation.auto_start_blockers == [
        "approval_required",
        "deferred_tool_not_auto_safe",
    ]

    port = _DeferredReplanRecoveryActionPort()
    service = AgentStudioService(port)
    assert service.start_next_replan_continuation(
        "run-1",
        {"agent_id": "agent-1", "client_run_id": "client-auto-1"},
    ) is None
    assert [name for name, _payload in port.calls] == ["get_run_timeline"]


def test_agent_studio_service_starts_runtime_envelope_retry_action_direct_run() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_replan_recovery_action(
        "runtime-run-1",
        {
            "request_id": "runtime-retry:runtime-request-open-app",
            "action_id": "runtime-retry:runtime-request-open-app:action:1:desktop.open_app",
        },
    )

    assert run.run_id == "recovery-run-1"
    assert run.recovery_source is not None
    assert run.recovery_source.kind == "replan"
    assert run.recovery_source.source_run_id == "runtime-run-1"
    assert run.recovery_source.replan_request_id == "runtime-retry:runtime-request-open-app"
    assert run.recovery_source.recovery_tool == "desktop.open_app"
    assert run.recovery_source.recovery_input_preview == {"app_name": "Music"}
    request = _port_call_payload(port, "start_agent_run")
    assert request["agent_id"] == "agent-1"
    assert request["metadata"]["recovery_permission_target"] == "foreground_focus"
    assert request["metadata"]["recovery_tool"] == "desktop.open_app"
    direct_request = request["direct_tool_requests"][0]
    assert direct_request["tool"] == "desktop.open_app"
    assert direct_request["input"] == {"app_name": "Music"}
    assert direct_request["planning_reason"] == "runtime_execution_observation_retry"
    assert direct_request["permission_target"] == "foreground_focus"
    assert direct_request["observation_evidence"]["blocking_condition"] == (
        "foreground_focus_unavailable"
    )
    assert direct_request["observation_retry"]["reason"] == "foreground_focus_unavailable"
    assert direct_request["task_todo"]["todo_id"] == "todo-open-app"
    assert direct_request["task_verification_targets"][0]["step_id"] == "open-app"


def test_agent_studio_service_starts_tool_recovery_action_direct_run() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_tool_recovery_action(
        "run-1",
        {
            "tool_call_id": "tool-call-1",
            "action_id": "tool-action-1",
        },
    )

    assert run.run_id == "recovery-run-1"
    assert run.recovery_source is not None
    assert run.recovery_source.kind == "tool"
    assert run.recovery_source.source_run_id == "run-1"
    assert run.recovery_source.source_tool_call_id == "tool-call-1"
    assert run.recovery_source.recovery_action_id == "tool-action-1"
    assert run.recovery_source.recovery_tool == "desktop.list_apps"
    request = _port_call_payload(port, "start_agent_run")
    assert request["agent_id"] == "agent-1"
    assert request["metadata"]["desktop_permission_recovery"] is True
    assert request["metadata"]["recovery_tool"] == "desktop.list_apps"
    assert request["metadata"]["tool_recovery_action_id"] == "tool-action-1"
    assert request["metadata"]["desktop_execution_policy"]["mode"] == "supervised_live"
    assert request["metadata"]["sandbox_provider"]["status"] == "provider_required"
    assert request["metadata"]["desktop_execution_route"]["status"] == "provider_required"
    assert request["metadata"]["source_run_id"] == "run-1"
    assert request["metadata"]["source_tool_call_id"] == "tool-call-1"
    direct_request = request["direct_tool_requests"][0]
    assert direct_request["tool"] == "desktop.list_apps"
    assert direct_request["input"] == {"query": "Apple Music"}
    assert direct_request["source"] == "agent_studio_tool_recovery"
    assert direct_request["tool_call_id"] == "tool-call-1"
    assert direct_request["desktop_execution_policy"]["mode"] == "supervised_live"
    assert direct_request["sandbox_provider"]["status"] == "provider_required"
    assert direct_request["desktop_execution_route"]["status"] == "provider_required"
    assert direct_request["continue_to_model"] is True


def test_agent_studio_service_starts_tool_recovery_retry_direct_run() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_tool_recovery_action(
        "run-1",
        {
            "tool_call_id": "tool-call-1",
            "action_id": "tool-action-1",
            "action_kind": "retry_original",
            "input_override": {"app_name": "Music"},
        },
    )

    assert run.run_id == "recovery-run-1"
    assert run.recovery_source is not None
    assert run.recovery_source.recovery_action_kind == "retry_original"
    assert run.recovery_source.recovery_tool == "desktop.open_app"
    assert run.recovery_source.recovery_input_preview == {"app_name": "Music"}
    request = _port_call_payload(port, "start_agent_run")
    assert request["metadata"]["desktop_permission_retry"] is True
    assert request["metadata"]["recovery_action_kind"] == "retry_original"
    assert request["metadata"]["recovery_tool"] == "desktop.open_app"
    direct_request = request["direct_tool_requests"][0]
    assert direct_request["tool"] == "desktop.open_app"
    assert direct_request["input"] == {"app_name": "Music"}
    assert direct_request["action_kind"] == "retry_original"


def test_agent_studio_service_starts_group_replan_recovery_action_from_child_agent() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_group_replan_recovery_action(
        "group-run-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
        },
    )

    assert run.run_id == "recovery-run-1"
    assert run.recovery_source is not None
    assert run.recovery_source.source_run_id == "group-run-1"
    assert run.recovery_source.source_group_run_id == "group-run-1"
    assert run.recovery_source.replan_request_id == "replan-1"
    request = _port_call_payload(port, "start_agent_run")
    assert request["agent_id"] == "agent-2"
    assert request["metadata"]["source_run_id"] == "group-run-1"
    assert request["metadata"]["source_group_run_id"] == "group-run-1"
    assert request["metadata"]["task_core_context"]["core_id"] == "task-core-1"
    assert request["direct_tool_requests"][0]["tool"] == "desktop.list_apps"
    assert request["direct_tool_requests"][0]["core_id"] == "task-core-1"
    assert request["direct_tool_requests"][0]["task_verification_targets"][0]["step_id"] == "open-app"


def test_agent_studio_service_auto_starts_group_replan_continuation_from_child_agent() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_next_group_replan_continuation(
        "group-run-1",
        {"client_run_id": "client-group-auto-1"},
    )

    assert run is not None
    assert run.run_id == "recovery-run-1"
    assert [name for name, _payload in port.calls] == [
        "get_group_run",
        "list_tool_catalog",
        "start_agent_run",
    ]
    request = _port_call_payload(port, "start_agent_run")
    assert request["agent_id"] == "agent-2"
    assert request["client_run_id"] == "client-group-auto-1"
    assert request["metadata"]["source"] == "agent_studio_group_replan_auto_continuation"
    assert request["metadata"]["source_group_run_id"] == "group-run-1"
    assert request["metadata"]["replan_auto_start_eligible"] is True
    assert request["direct_tool_requests"][0]["tool"] == "desktop.list_apps"
    assert request["direct_tool_requests"][0]["approval_required"] is False


def test_agent_studio_service_starts_group_tool_recovery_action_from_child_agent() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_group_tool_recovery_action(
        "group-run-1",
        {
            "tool_call_id": "tool-call-1",
            "action_id": "tool-action-1",
        },
    )

    assert run.run_id == "recovery-run-1"
    assert run.recovery_source is not None
    assert run.recovery_source.source_run_id == "group-run-1"
    assert run.recovery_source.source_group_run_id == "group-run-1"
    assert run.recovery_source.source_tool_call_id == "tool-call-1"
    request = _port_call_payload(port, "start_agent_run")
    assert request["agent_id"] == "agent-2"
    assert request["metadata"]["source_run_id"] == "group-run-1"
    assert request["metadata"]["source_group_run_id"] == "group-run-1"
    assert request["metadata"]["source_tool_call_id"] == "tool-call-1"
    assert request["direct_tool_requests"][0]["tool"] == "desktop.list_apps"


def test_agent_studio_service_starts_workflow_replan_recovery_action_from_child_agent() -> None:
    port = _ReplanRecoveryActionPort()
    service = AgentStudioService(port)

    run = service.start_replan_recovery_action(
        "workflow-run-1",
        {
            "request_id": "replan-1",
            "action_id": "replan-1:action:1:desktop.list_apps",
        },
    )

    assert run.run_id == "recovery-run-1"
    assert run.recovery_source is not None
    assert run.recovery_source.source_run_id == "workflow-run-1"
    assert run.recovery_source.source_workflow_run_id == "workflow-run-1"
    assert run.recovery_source.replan_request_id == "replan-1"
    request = _port_call_payload(port, "start_agent_run")
    assert request["agent_id"] == "agent-2"
    assert request["metadata"]["source_run_id"] == "workflow-run-1"
    assert request["metadata"]["source_workflow_run_id"] == "workflow-run-1"
    assert request["direct_tool_requests"][0]["replan_request_id"] == "replan-1"
    assert request["direct_tool_requests"][0]["core_id"] == "task-core-1"
    assert request["direct_tool_requests"][0]["task_todo"]["todo_id"] == "todo-open-app"


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


def test_agent_studio_service_group_stream_fallback_first_page_includes_key_status_window() -> None:
    class GroupRunStreamOnlyPort(_FakeStudioPort):
        def get_group_run_event_stream(self, group_run_id: str) -> dict[str, Any]:
            self.calls.append(("get_group_run_event_stream", group_run_id))
            return {
                "run_id": group_run_id,
                "events": [
                    {
                        "event_id": "group-stream-1",
                        "run_id": group_run_id,
                        "sequence": 1,
                        "event_type": "group.member.started",
                        "payload": {"member_agent_id": "agent-1"},
                    },
                    {
                        "event_id": "group-stream-2",
                        "run_id": group_run_id,
                        "sequence": 2,
                        "event_type": "group.member.completed",
                        "payload": {"member_agent_id": "agent-1"},
                    },
                    {
                        "event_id": "group-stream-3",
                        "run_id": group_run_id,
                        "sequence": 3,
                        "event_type": "group.run.completed",
                        "payload": {"group_run_id": group_run_id},
                    },
                ],
            }

    port = GroupRunStreamOnlyPort()
    service = AgentStudioService(port)

    page = service.get_group_run_event_page("group-run-1", after_sequence=0, limit=1)

    assert [event.event_type for event in page.events] == [
        "group.member.started",
        "group.member.completed",
        "group.run.completed",
    ]
    assert page.next_after_sequence == 3
    assert page.has_more is True
    assert port.calls == [("get_group_run_event_stream", "group-run-1")]


def test_agent_studio_service_projects_group_run_replan_events_from_port_stream() -> None:
    class ReplanGroupRunEventPort(_FakeStudioPort):
        def get_group_run_event_stream(self, group_run_id: str) -> dict[str, Any]:
            self.calls.append(("get_group_run_event_stream", group_run_id))
            return {
                "run_id": group_run_id,
                "events": _planner_events_with_failed_analysis(),
            }

    port = ReplanGroupRunEventPort()
    service = AgentStudioService(port)

    stream = list(service.get_group_run_event_stream("group-run-1"))
    event_types = [event.event_type for event in stream]
    replan_event = next(
        event for event in stream if event.event_type == "group.run.replan.requested"
    )

    assert "group.run.started" not in event_types
    assert "group.run.intent.selected" in event_types
    assert "group.run.plan.created" in event_types
    assert replan_event.payload["planner_event_type"] == "agent.replan.requested"
    assert replan_event.payload["planner_scope"] == "group_run"
    assert replan_event.payload["run_id"] == "group-run-1"
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


def test_agent_studio_service_run_stream_fallback_first_page_includes_key_status_window() -> None:
    port = _FakeStudioPort()
    service = AgentStudioService(port)

    page = service.get_run_event_page("run-1", after_sequence=0, limit=1)

    assert [event.event_type for event in page.events] == [
        "agent.started",
        "agent.tool.call",
        "agent.completed",
    ]
    assert page.next_after_sequence == 3
    assert page.has_more is True
    assert port.calls == [("get_run_event_stream", "run-1")]


def test_agent_studio_service_run_event_first_page_includes_key_status_window() -> None:
    class FirstPageRunEventPort(_FakeStudioPort):
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
                "next_after_sequence": 2,
                "has_more": True,
                "events": [
                    {
                        "event_id": "event-page-1",
                        "run_id": run_id,
                        "sequence": 1,
                        "event_type": "agent.started",
                        "payload": {"status": "running"},
                    },
                    {
                        "event_id": "event-page-2",
                        "run_id": run_id,
                        "sequence": 2,
                        "event_type": "agent.plan.created",
                        "payload": {"plan_id": "plan-1"},
                    },
                ],
            }

        def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
            self.calls.append(("get_run_event_stream", run_id))
            return {
                "run_id": run_id,
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
                        "event_type": "agent.plan.created",
                        "payload": {"plan_id": "plan-1"},
                    },
                    {
                        "event_id": "event-stream-3",
                        "run_id": run_id,
                        "sequence": 3,
                        "event_type": "agent.tool.started",
                        "payload": {"tool": "terminal.run"},
                    },
                    {
                        "event_id": "event-stream-4",
                        "run_id": run_id,
                        "sequence": 4,
                        "event_type": "agent.tool.approval_required",
                        "payload": {"tool": "terminal.run", "status": "approval_required"},
                    },
                ],
            }

    port = FirstPageRunEventPort()
    service = AgentStudioService(port)

    page = service.get_run_event_page("run-1", after_sequence=0, limit=2)
    event_types = [event.event_type for event in page.events]

    assert event_types == [
        "agent.started",
        "agent.plan.created",
        "agent.tool.started",
        "agent.tool.approval_required",
    ]
    assert page.next_after_sequence == 4
    assert ("get_run_event_stream", "run-1") in port.calls


def test_agent_studio_service_workflow_event_first_page_includes_key_status_window() -> None:
    class FirstPageWorkflowRunEventPort(_FakeStudioPort):
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
                "workflow_run_id": run_id,
                "after_sequence": after_sequence,
                "limit": limit,
                "next_after_sequence": 1,
                "has_more": True,
                "events": [
                    {
                        "event_id": "workflow-page-1",
                        "run_id": run_id,
                        "sequence": 1,
                        "event_type": "workflow.run.started",
                        "payload": {"status": "running"},
                    }
                ],
            }

        def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
            self.calls.append(("get_run_event_stream", run_id))
            return {
                "workflow_run_id": run_id,
                "events": [
                    {
                        "event_id": "workflow-stream-1",
                        "run_id": run_id,
                        "sequence": 1,
                        "event_type": "workflow.run.started",
                        "payload": {"status": "running"},
                    },
                    {
                        "event_id": "workflow-stream-2",
                        "run_id": run_id,
                        "sequence": 2,
                        "event_type": "workflow.node.started",
                        "payload": {"workflow_node_id": "node-1"},
                    },
                    {
                        "event_id": "workflow-stream-3",
                        "run_id": run_id,
                        "sequence": 3,
                        "event_type": "workflow.run.approval_required",
                        "payload": {"status": "approval_required"},
                    },
                ],
            }

    port = FirstPageWorkflowRunEventPort()
    service = AgentStudioService(port)

    page = service.get_run_event_page("workflow-run-1", after_sequence=0, limit=1)
    event_types = [event.event_type for event in page.events]

    assert event_types == [
        "workflow.run.started",
        "workflow.node.started",
        "workflow.run.approval_required",
    ]
    assert page.next_after_sequence == 3
    assert ("get_run_event_stream", "workflow-run-1") in port.calls


def test_agent_studio_service_projects_workflow_replan_events_from_port_page() -> None:
    class WorkflowRunEventPagePort(_FakeStudioPort):
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
                "workflow_run_id": run_id,
                "after_sequence": after_sequence,
                "limit": limit,
                "next_after_sequence": 6,
                "has_more": False,
                "events": _planner_events_with_failed_analysis(),
            }

    port = WorkflowRunEventPagePort()
    service = AgentStudioService(port)

    page = service.get_run_event_page("workflow-run-1", after_sequence=0, limit=200)
    event_types = [event.event_type for event in page.events]
    replan_event = next(
        event for event in page.events if event.event_type == "workflow.run.replan.requested"
    )

    assert "workflow.run.started" not in event_types
    assert "workflow.run.intent.selected" in event_types
    assert "workflow.run.plan.created" in event_types
    assert replan_event.payload["planner_event_type"] == "agent.replan.requested"
    assert replan_event.payload["planner_scope"] == "workflow_run"
    assert replan_event.payload["run_id"] == "workflow-run-1"
    assert page.next_after_sequence == max(int(event.sequence or 0) for event in page.events)
    assert ("get_run_event_stream", "workflow-run-1") not in port.calls


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
