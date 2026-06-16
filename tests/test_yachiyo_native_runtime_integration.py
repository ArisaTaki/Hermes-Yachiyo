"""Native runtime integration coverage for Yachiyo Chat and Studio facades."""

from __future__ import annotations

from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalPauseProjection
from apps.shell.agent_runtime import NativeRunEngine
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent.contracts import StartGroupRunRequest
from apps.shell.yachiyo_agent.legacy_ports import LegacyStudioPort
from apps.shell.yachiyo_agent.legacy_tasks import LegacyRuntimePort
from apps.shell.yachiyo_agent.service import YachiyoAgentService
from apps.shell.yachiyo_agent.studio_service import AgentStudioService


def test_chat_task_and_studio_timeline_share_native_runtime_snapshot(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        run_group = runtime._insert_run_group(
            title="Yachiyo native runtime smoke",
            source="yachiyo_chat",
            workspace_dir=str(tmp_path / "workspace"),
        )
        run = runtime._insert_run(
            kind="agent_run",
            runnable_id="agent-native-smoke",
            user_goal="Patch README",
            run_group_id=run_group["run_group_id"],
        )
        pending_approval = {
            "approval_id": "approval-native-1",
            "tool": "workspace.write_patch",
            "title": "Approve README patch",
            "risk_level": "write_workspace",
            "input_preview": {"path": "README.md"},
        }
        artifacts = [
            {
                "artifact_id": "artifact-native-1",
                "kind": "markdown",
                "path": "reports/native-smoke.md",
                "source_tool": "artifact.write",
            }
        ]
        timeline = [
            {
                "event_type": "agent.tool.approval_required",
                "payload": {
                    "pending_approval": pending_approval,
                    "tool": "workspace.write_patch",
                },
            },
            {
                "event_type": "artifact.created",
                "payload": {
                    "artifact": artifacts[0],
                    "artifact_path": "reports/native-smoke.md",
                },
            },
        ]
        runtime._update_run(
            run["run_id"],
            status="approval_required",
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=pending_approval,
        )
        runtime.append_run_event(
            run["run_id"],
            "agent.tool.approval_required",
            {
                "pending_approval": pending_approval,
                "tool": "workspace.write_patch",
            },
        )
        runtime.link_task_run(
            task_id="task-native-1",
            run_id=run["run_id"],
            session_id="chat-native-1",
        )

        chat = YachiyoAgentService(LegacyRuntimePort(runtime))
        studio = AgentStudioService(LegacyStudioPort(runtime))

        task = chat.get_task_snapshot("task-native-1")
        task_timeline = chat.get_task_timeline("task-native-1")
        studio_timeline = studio.get_run_timeline(run["run_id"])
        chat_events = list(chat.get_task_event_stream("task-native-1"))
        studio_events = list(studio.get_run_event_stream(run["run_id"]))
        event_page = studio.get_run_event_page(run["run_id"], limit=1)

        assert task.task_id == "task-native-1"
        assert task.conversation_id == "chat-native-1"
        assert task.status == "waiting_approval"
        assert task.needs_user_action is True
        assert task.open_in_studio_url == f"#/agents?run_id={run['run_id']}&group_run={run_group['run_group_id']}"
        assert task.pending_approvals[0].approval_id == "approval-native-1"
        assert task.pending_approvals[0].tool_name == "workspace.write_patch"
        assert task.artifacts[0].path == "reports/native-smoke.md"

        assert task_timeline.run_id == run["run_id"]
        assert task_timeline.task_id == "task-native-1"
        assert task_timeline.session_id == "chat-native-1"
        assert task_timeline.pending_approval is not None
        assert task_timeline.pending_approval.approval_id == "approval-native-1"

        assert studio_timeline.run_id == run["run_id"]
        assert studio_timeline.task_id == "task-native-1"
        assert studio_timeline.session_id == "chat-native-1"
        assert studio_timeline.pending_approval is not None
        assert studio_timeline.pending_approval.tool_name == "workspace.write_patch"
        assert studio_timeline.artifacts[0].artifact_id == "artifact-native-1"

        assert chat_events
        assert studio_events
        assert chat_events[0].run_id == run["run_id"]
        assert studio_events[0].run_id == run["run_id"]
        assert chat_events[0].event_type == "agent.tool.approval_required"
        assert studio_events[0].event_type == "agent.tool.approval_required"
        assert event_page.run_id == run["run_id"]
        assert event_page.events[0].event_type == "agent.tool.approval_required"
    finally:
        runtime.close()


def test_agent_studio_group_run_uses_native_run_group_events_and_children(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime-group.db",
        workspace_dir=tmp_path / "runtime-group",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        run_group = runtime._insert_run_group(
            title="Native review group",
            source="agent_group",
            workspace_dir=str(tmp_path / "group-workspace"),
        )
        planner_run = runtime._insert_run(
            kind="agent_run",
            runnable_id="agent-planner",
            user_goal="Compare options",
            run_group_id=run_group["run_group_id"],
        )
        reviewer_run = runtime._insert_run(
            kind="agent_run",
            runnable_id="agent-reviewer",
            user_goal="Compare options",
            run_group_id=run_group["run_group_id"],
        )
        approval = {
            "approval_id": "approval-group-native",
            "tool": "terminal.run",
            "title": "Approve planner command",
        }
        runtime._update_run(
            planner_run["run_id"],
            status="approval_required",
            artifacts=[
                {
                    "artifact_id": "artifact-group-plan",
                    "kind": "markdown",
                    "path": "team-plan.md",
                }
            ],
            pending_approval=approval,
        )
        runtime._update_run(
            reviewer_run["run_id"],
            status="completed",
            result="Looks good",
        )
        runtime._update_run_group(
            run_group["run_group_id"],
            status="running",
            summary="Compare options",
        )
        runtime.append_run_event(
            planner_run["run_id"],
            "group.run.started",
            {
                "group_id": "group-native-1",
                "group_run_id": run_group["run_group_id"],
                "run_group_id": run_group["run_group_id"],
                "objective": "Compare options",
                "participant_count": 2,
                "child_run_ids": [planner_run["run_id"], reviewer_run["run_id"]],
            },
        )
        runtime.append_run_event(
            planner_run["run_id"],
            "group.member.started",
            {
                "agent_id": "agent-planner",
                "agent_name": "Planner",
                "group_id": "group-native-1",
                "group_run_id": run_group["run_group_id"],
                "run_group_id": run_group["run_group_id"],
                "run_id": planner_run["run_id"],
                "status": "approval_required",
            },
        )
        runtime.append_run_event(
            reviewer_run["run_id"],
            "group.member.completed",
            {
                "agent_id": "agent-reviewer",
                "agent_name": "Reviewer",
                "group_id": "group-native-1",
                "group_run_id": run_group["run_group_id"],
                "run_group_id": run_group["run_group_id"],
                "run_id": reviewer_run["run_id"],
                "status": "completed",
            },
        )

        studio = AgentStudioService(LegacyStudioPort(runtime))

        group_run = studio.get_group_run(run_group["run_group_id"])
        group_events = list(studio.get_group_run_event_stream(run_group["run_group_id"]))
        event_page = studio.get_group_run_event_page(run_group["run_group_id"], limit=2)

        assert group_run.group_run_id == run_group["run_group_id"]
        assert group_run.status == "running"
        assert group_run.objective == "Compare options"
        assert group_run.child_run_ids == [planner_run["run_id"], reviewer_run["run_id"]]
        assert [run.run_id for run in group_run.runs] == [
            planner_run["run_id"],
            reviewer_run["run_id"],
        ]
        assert group_run.runs[0].pending_approval is not None
        assert group_run.runs[0].pending_approval.tool_name == "terminal.run"
        assert group_run.pending_approvals[0].approval_id == "approval-group-native"
        assert group_run.shared_artifacts[0].path == "team-plan.md"
        assert group_run.shared_artifacts[0].source_run_id == planner_run["run_id"]
        assert "group.run.started" in [event.event_type for event in group_events]
        assert "group.member.completed" in [event.event_type for event in group_events]
        assert event_page.run_id == run_group["run_group_id"]
        assert event_page.events[0].event_type == "group.run.started"
    finally:
        runtime.close()


def test_agent_studio_start_group_run_records_native_group_replay(tmp_path, monkeypatch) -> None:
    credential_store = MemoryCredentialStore()
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime-group-start.db",
        workspace_dir=tmp_path / "runtime-group-start",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        group = {
            "group_id": "native-start-group",
            "name": "Native launch team",
            "mode": "parallel",
            "memory_scope": "shared",
            "members": [
                {"agent_id": "agent-planner", "name": "Planner", "role": "planner"},
                {"agent_id": "agent-reviewer", "name": "Reviewer", "role": "reviewer"},
            ],
        }

        def get_agent_group(group_id: str) -> dict[str, object]:
            if group_id != group["group_id"]:
                raise KeyError(group_id)
            return dict(group)

        def complete_child_run(
            *,
            runnable_id: str,
            user_goal: str,
            run_group_id: str = "",
            on_complete=None,
        ) -> dict[str, object]:
            del on_complete
            target_group_id = run_group_id
            if not target_group_id:
                run_group = runtime._insert_run_group(
                    title="Native launch team",
                    source="agent_group",
                    workspace_dir=str(tmp_path / "group-start-workspace"),
                )
                target_group_id = run_group["run_group_id"]
            run = runtime._insert_run(
                kind="agent_run",
                runnable_id=runnable_id,
                user_goal=user_goal,
                run_group_id=target_group_id,
            )
            artifact = {
                "artifact_id": f"artifact-{runnable_id}",
                "kind": "markdown",
                "path": f"{runnable_id}/summary.md",
                "source_tool": "agent.result",
            }
            completed = runtime._update_run(
                run["run_id"],
                status="completed",
                result=f"{runnable_id} finished",
                artifacts=[artifact],
                pending_approval=None,
            )
            return {
                **completed,
                "agent_run_id": completed["run_id"],
                "runnable_name": runnable_id,
            }

        monkeypatch.setattr(runtime, "get_agent_group", get_agent_group, raising=False)
        monkeypatch.setattr(
            runtime,
            "create_run_for_runnable_async",
            complete_child_run,
            raising=False,
        )

        studio = AgentStudioService(LegacyStudioPort(runtime))

        started = studio.start_group_run(
            StartGroupRunRequest(
                group_id="native-start-group",
                objective="Compare launch risks",
                client_run_id="native-start-client",
            )
        )
        replayed = studio.get_group_run(started.group_run_id)
        events = list(studio.get_group_run_event_stream(started.group_run_id))
        page = studio.get_group_run_event_page(started.group_run_id, limit=10)

        event_types = [event.event_type for event in events]

        assert started.status == "completed"
        assert started.group_id == "native-start-group"
        assert started.objective == "Compare launch risks"
        assert started.child_run_ids == [run.run_id for run in started.runs]
        assert len(started.runs) == 2
        assert all(run.status == "completed" for run in started.runs)
        assert [artifact.path for artifact in started.shared_artifacts] == [
            "agent-planner/summary.md",
            "agent-reviewer/summary.md",
        ]

        assert replayed.status == "completed"
        assert replayed.group_id == "native-start-group"
        assert replayed.objective == "Compare launch risks"
        assert replayed.final_answer
        assert replayed.child_run_ids == started.child_run_ids
        assert "group.run.started" in event_types
        assert event_types.count("group.member.started") == 2
        assert event_types.count("group.member.completed") == 2
        assert "group.run.completed" in event_types
        assert page.run_id == started.group_run_id
        assert any(event.event_type == "group.run.completed" for event in page.events)
    finally:
        runtime.close()


def test_agent_studio_workflow_run_timeline_uses_native_runtime_events(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime-workflow.db",
        workspace_dir=tmp_path / "runtime-workflow",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        run_group = runtime._insert_run_group(
            title="Native workflow run",
            source="workflow",
            workspace_dir=str(tmp_path / "workflow-workspace"),
        )
        workflow_run = runtime._insert_run(
            kind="workflow_run",
            runnable_id="workflow-native-1",
            user_goal="Build workflow report",
            run_group_id=run_group["run_group_id"],
        )
        artifact = {
            "artifact_id": "artifact-workflow-native",
            "kind": "workflow_artifact",
            "path": "workflow/report.md",
            "workflow_id": "workflow-native-1",
            "workflow_run_id": workflow_run["run_id"],
            "workflow_node_id": "report",
            "workflow_node_label": "Report",
        }
        runtime._update_run(
            workflow_run["run_id"],
            status="completed",
            result="Workflow report complete",
            timeline=[
                {
                    "event_type": "workflow.node.started",
                    "payload": {
                        "workflow_id": "workflow-native-1",
                        "workflow_run_id": workflow_run["run_id"],
                        "workflow_node_id": "report",
                        "workflow_node_label": "Report",
                    },
                },
                {
                    "event_type": "workflow.node.completed",
                    "payload": {
                        "workflow_id": "workflow-native-1",
                        "workflow_run_id": workflow_run["run_id"],
                        "workflow_node_id": "report",
                        "workflow_node_label": "Report",
                    },
                },
            ],
            artifacts=[artifact],
        )
        runtime.append_run_event(
            workflow_run["run_id"],
            "workflow.node.completed",
            {
                "workflow_id": "workflow-native-1",
                "workflow_run_id": workflow_run["run_id"],
                "workflow_node_id": "report",
                "workflow_node_label": "Report",
            },
        )

        studio = AgentStudioService(LegacyStudioPort(runtime))

        timeline = studio.get_run_timeline(workflow_run["run_id"])
        events = list(studio.get_run_event_stream(workflow_run["run_id"]))
        page = studio.get_run_event_page(workflow_run["run_id"], limit=1)

        assert timeline.run_id == workflow_run["run_id"]
        assert timeline.workflow_run_id == workflow_run["run_id"]
        assert timeline.workflow_id == "workflow-native-1"
        assert timeline.objective == "Build workflow report"
        assert timeline.final_answer == "Workflow report complete"
        assert [event.event_type for event in timeline.events] == [
            "workflow.node.started",
            "workflow.node.completed",
        ]
        assert timeline.artifacts[0].artifact_id == "artifact-workflow-native"
        assert timeline.artifacts[0].workflow_node_label == "Report"
        workflow_events = [
            event for event in events if event.event_type == "workflow.node.completed"
        ]
        assert workflow_events
        assert workflow_events[0].payload["workflow_node_id"] == "report"
        assert page.run_id == workflow_run["run_id"]
        assert page.events[0].event_type == "group.run.started"
    finally:
        runtime.close()


def test_agent_studio_rejects_native_tool_approval_with_replay_events(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime-approval.db",
        workspace_dir=tmp_path / "runtime-approval",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        run = runtime._insert_run(
            kind="agent_run",
            runnable_id="agent-approval-replay",
            user_goal="Run a gated command",
        )
        pending_approval = {
            "approval_id": "approval-native-reject",
            "tool": "terminal.run",
            "input_preview": {
                "command": "printf ok",
                "API_KEY": "sk-native-reject-secret123456",
            },
            "requested_at": "2026-06-15T00:00:00+00:00",
            "tool_request": {
                "tool": "terminal.run",
                "input": {
                    "command": "printf ok",
                    "API_KEY": "sk-native-reject-secret123456",
                },
            },
        }
        runtime.approval_pause.project_tool_required(
            run["run_id"],
            pending_approval=pending_approval,
            timeline=[],
            artifacts=[],
        )

        studio = AgentStudioService(LegacyStudioPort(runtime))

        rejected = studio.reject_run_approval(run["run_id"], "No secret-bearing commands")
        timeline = studio.get_run_timeline(run["run_id"])
        events = list(studio.get_run_event_stream(run["run_id"]))
        first_page = studio.get_run_event_page(run["run_id"], limit=2)
        second_page = studio.get_run_event_page(
            run["run_id"],
            after_sequence=first_page.next_after_sequence,
            limit=2,
        )

        event_types = [event.event_type for event in events]
        rejected_events = [
            event for event in events if event.event_type == "agent.tool.approval_rejected"
        ]
        cancelled_events = [
            event for event in events if event.event_type == "agent.run.cancelled"
        ]
        serialized_events = " ".join(str(event.model_dump()) for event in events)

        assert rejected.status == "cancelled"
        assert rejected.pending_approval is None
        assert timeline.status == "cancelled"
        assert timeline.pending_approval is None
        assert "agent.tool.approval_required" in event_types
        assert "agent.tool.approval_rejected" in event_types
        assert "agent.run.cancelled" in event_types
        assert rejected_events[0].payload["tool"] == "terminal.run"
        assert rejected_events[0].payload["status"] == "cancelled"
        assert rejected_events[0].payload["reason"] == "No secret-bearing commands"
        assert cancelled_events[0].payload["result"] == (
            "工具审批已拒绝：No secret-bearing commands"
        )
        assert timeline.approvals[0].approval_id == "approval-native-reject"
        assert timeline.approvals[0].status == "rejected"
        assert first_page.events[0].event_type == "agent.tool.approval_required"
        assert second_page.events[0].sequence > first_page.events[-1].sequence
        assert {
            event.event_type for event in second_page.events
        } & {"tool.rejected", "approval.rejected", "agent.run.cancelled"}
        assert "sk-native-reject-secret123456" not in serialized_events
    finally:
        runtime.close()


def test_agent_studio_rejects_native_workflow_approval_with_group_replay_events(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime-workflow-approval.db",
        workspace_dir=tmp_path / "runtime-workflow-approval",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        run_group = runtime._insert_run_group(
            title="Native workflow approval",
            source="workflow",
            workspace_dir=str(tmp_path / "workflow-approval-workspace"),
        )
        workflow_run = runtime._insert_run(
            kind="workflow_run",
            runnable_id="workflow-approval-native",
            user_goal="Review release plan",
            run_group_id=run_group["run_group_id"],
        )
        projection = WorkflowApprovalPauseProjection.from_criteria(
            {"id": "review-gate"},
            label="Review Gate",
            kind="approval",
            criteria="Review the release plan",
            context="Release plan includes token sk-workflow-reject-secret123456",
            next_index=1,
        )
        timeline = [projection.timeline_event(runtime._timeline)]
        runtime.append_run_event(
            workflow_run["run_id"],
            "workflow.node.approval_required",
            projection.event_payload(),
        )
        runtime._update_run(
            workflow_run["run_id"],
            **projection.update_fields(timeline=timeline, artifacts=[]),
        )
        runtime._update_run_group(
            run_group["run_group_id"],
            status="approval_required",
            summary=projection.result_text(),
        )

        studio = AgentStudioService(LegacyStudioPort(runtime))

        pending = studio.get_run_timeline(workflow_run["run_id"])
        rejected = studio.reject_run_approval(workflow_run["run_id"], "Needs safer rollout")
        timeline_after = studio.get_run_timeline(workflow_run["run_id"])
        group_run = studio.get_group_run(run_group["run_group_id"])
        events = list(studio.get_run_event_stream(workflow_run["run_id"]))
        first_page = studio.get_run_event_page(workflow_run["run_id"], limit=2)
        second_page = studio.get_run_event_page(
            workflow_run["run_id"],
            after_sequence=first_page.next_after_sequence,
            limit=4,
        )

        event_types = [event.event_type for event in events]
        rejected_events = [
            event for event in events if event.event_type == "workflow.node.approval_rejected"
        ]
        cancelled_events = [
            event for event in events if event.event_type == "workflow.run.cancelled"
        ]
        serialized_events = " ".join(str(event.model_dump()) for event in events)

        assert pending.status == "approval_required"
        assert pending.pending_approval is not None
        assert pending.pending_approval.workflow_node_label == "Review Gate"
        assert rejected.status == "cancelled"
        assert rejected.pending_approval is None
        assert timeline_after.pending_approval is None
        assert timeline_after.approvals[0].approval_id == projection.approval_id
        assert timeline_after.approvals[0].status == "rejected"
        assert group_run.status == "cancelled"
        assert group_run.final_answer == "Workflow 审批已拒绝：Needs safer rollout"
        assert "workflow.node.approval_required" in event_types
        assert "workflow.node.approval_rejected" in event_types
        assert "workflow.run.cancelled" in event_types
        assert rejected_events[0].payload["workflow_node_id"] == "review-gate"
        assert rejected_events[0].payload["workflow_node_label"] == "Review Gate"
        assert rejected_events[0].payload["reason"] == "Needs safer rollout"
        assert cancelled_events[0].payload["status"] == "cancelled"
        page_event_types = [
            event.event_type for event in [*first_page.events, *second_page.events]
        ]
        assert "workflow.node.approval_required" in page_event_types
        assert second_page.events[0].sequence > first_page.events[-1].sequence
        assert {
            event.event_type for event in second_page.events
        } & {"workflow.node.approval_rejected", "approval.rejected", "workflow.run.cancelled"}
        assert "sk-workflow-reject-secret123456" not in serialized_events
    finally:
        runtime.close()


def test_agent_studio_approves_native_workflow_approval_and_replays_resume(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    runtime = NativeRunEngine(
        db_path=tmp_path / "agent-runtime-workflow-approval-resume.db",
        workspace_dir=tmp_path / "runtime-workflow-approval-resume",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        workflow = runtime.create_workflow(
            {
                "name": "Native approval resume workflow",
                "nodes": [
                    {
                        "id": "start",
                        "type": "input",
                        "data": {"kind": "start", "label": "Start"},
                    },
                    {
                        "id": "review",
                        "type": "default",
                        "data": {
                            "kind": "approval",
                            "label": "Review Gate",
                            "criteria": "Review release notes",
                        },
                    },
                    {
                        "id": "artifact",
                        "type": "output",
                        "data": {
                            "kind": "artifact",
                            "label": "Release Notes",
                            "artifact_path": "release/notes.md",
                        },
                    },
                ],
                "edges": [
                    {"id": "edge-start-review", "source": "start", "target": "review"},
                    {"id": "edge-review-artifact", "source": "review", "target": "artifact"},
                ],
            }
        )
        waiting = runtime.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Prepare release notes",
            }
        )

        studio = AgentStudioService(LegacyStudioPort(runtime))

        before = studio.get_run_timeline(waiting["run_id"])
        approved = studio.approve_run_approval(waiting["run_id"])
        after = studio.get_run_timeline(waiting["run_id"])
        group_run = studio.get_group_run(str(after.run_group_id or after.group_run_id or ""))
        events = list(studio.get_run_event_stream(waiting["run_id"]))
        page = studio.get_run_event_page(waiting["run_id"], limit=20)

        event_types = [event.event_type for event in events]
        approved_events = [
            event for event in events if event.event_type == "workflow.node.approval_approved"
        ]
        artifact_events = [
            event for event in events if event.event_type == "workflow.node.artifact"
        ]

        assert waiting["status"] == "approval_required"
        assert before.pending_approval is not None
        assert before.pending_approval.workflow_node_id == "review"
        assert before.pending_approval.workflow_node_label == "Review Gate"
        assert approved.status == "completed"
        assert approved.pending_approval is None
        assert after.status == "completed"
        assert after.pending_approval is None
        assert after.approvals[0].status == "approved"
        assert after.artifacts[0].path == "release/notes.md"
        assert after.artifacts[0].workflow_node_id == "artifact"
        assert after.artifacts[0].workflow_node_label == "Release Notes"
        assert group_run.status == "completed"
        assert "workflow.node.approval_required" in event_types
        assert "workflow.node.approval_approved" in event_types
        assert "workflow.node.artifact" in event_types
        assert "workflow.run.completed" in event_types
        assert "approval.approved" in event_types
        assert approved_events[0].payload["workflow_node_id"] == "review"
        assert approved_events[0].payload["workflow_node_label"] == "Review Gate"
        assert artifact_events[0].payload["workflow_node_id"] == "artifact"
        assert artifact_events[0].payload["artifact"]["path"] == "release/notes.md"
        assert "workflow.run.completed" in [event.event_type for event in page.events]
    finally:
        runtime.close()
