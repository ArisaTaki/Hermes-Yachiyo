"""Native runtime integration coverage for Yachiyo Chat and Studio facades."""

from __future__ import annotations

from apps.shell.agent_runtime import NativeRunEngine
from apps.shell.credential_store import MemoryCredentialStore
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
