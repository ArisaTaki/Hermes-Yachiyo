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
