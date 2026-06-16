"""Public Yachiyo Agent contract tests."""

from __future__ import annotations

import json

from apps.shell.yachiyo_agent import (
    AgentDefinitionSnapshot,
    AgentGroupMemberSnapshot,
    AgentGroupSnapshot,
    AgentTaskSnapshot,
    ApprovalCardSnapshot,
    ArtifactContentSnapshot,
    ArtifactSnapshot,
    ChatRunnableCatalogSnapshot,
    FutureTaskSnapshot,
    FutureTaskTriggerResultSnapshot,
    GroupRunSnapshot,
    MemorySnapshot,
    PublicRunEvent,
    RunEventPageSnapshot,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    SaveAgentGroupMemberRequest,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    SkillFolderSnapshot,
    SkillSnapshot,
    SkillSourceRootSnapshot,
    StartChatTaskRequest,
    ToolCallSnapshot,
    WorkflowRunSnapshot,
    WorkflowSnapshot,
)
from apps.shell.yachiyo_agent.events import public_run_event_from_payload


def _json(model) -> dict:
    return json.loads(model.model_dump_json())


def test_agent_task_snapshot_json_shape_is_stable() -> None:
    snapshot = AgentTaskSnapshot(
        task_id="task-1",
        conversation_id="chat-1",
        title="Review README",
        status="waiting_approval",
        summary="Waiting for write approval",
        current_step="Prepare patch",
        progress_text="1 approval pending",
        needs_user_action=True,
        pending_approvals=[
            ApprovalCardSnapshot(
                approval_id="approval-1",
                run_id="run-1",
                title="Approve workspace.write_patch",
                tool_name="workspace.write_patch",
                input_preview={"path": "README.md"},
            )
        ],
        recent_events=[
            PublicRunEvent(
                event_id="event-1",
                run_id="run-1",
                sequence=1,
                event_type="agent.tool.approval_required",
                detail="workspace.write_patch",
            )
        ],
        artifacts=[
            ArtifactSnapshot(
                artifact_id="artifact-1",
                run_id="run-1",
                title="Report",
                kind="markdown",
                path="report.md",
            )
        ],
        open_in_studio_url="#/agents?run_id=run-1",
        created_at="2026-06-14T00:00:00Z",
        updated_at="2026-06-14T00:00:01Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "task_id",
        "conversation_id",
        "title",
        "status",
        "summary",
        "current_step",
        "progress_text",
        "needs_user_action",
        "pending_approvals",
        "recent_events",
        "artifacts",
        "open_in_studio_url",
        "created_at",
        "updated_at",
    ]
    assert payload["pending_approvals"][0]["approval_id"] == "approval-1"
    assert payload["recent_events"][0]["event_type"] == "agent.tool.approval_required"
    assert "event" not in payload["recent_events"][0]


def test_chat_runnable_catalog_snapshot_json_shape_is_stable() -> None:
    snapshot = ChatRunnableCatalogSnapshot(
        agents=[AgentDefinitionSnapshot(agent_id="agent-1", name="Planner")],
        workflows=[WorkflowSnapshot(workflow_id="workflow-1", name="Review workflow")],
    )

    payload = _json(snapshot)

    assert list(payload) == ["agents", "workflows"]
    assert payload["agents"][0]["agent_id"] == "agent-1"
    assert payload["workflows"][0]["workflow_id"] == "workflow-1"


def test_run_timeline_snapshot_json_shape_covers_runtime_debug_objects() -> None:
    snapshot = RunTimelineSnapshot(
        run_id="run-1",
        parent_run_id=None,
        group_run_id="group-run-1",
        workflow_run_id="workflow-run-1",
        agent_id="agent-1",
        status="running",
        title="Ship docs",
        task_id="task-1",
        session_id="chat-1",
        task_run_link_created_at="2026-06-14T00:00:00Z",
        task_run_link_updated_at="2026-06-14T00:00:02Z",
        task_run_link_run_status="running",
        task_run_link_last_event_sequence=7,
        events=[
            PublicRunEvent(
                event_id="event-1",
                run_id="run-1",
                sequence=1,
                event_type="workflow.node.agent",
            )
        ],
        tool_calls=[
            ToolCallSnapshot(
                tool_call_id="tool-1",
                run_id="run-1",
                tool_name="workspace.read",
                status="completed",
                input_preview={"path": "README.md"},
            )
        ],
        approvals=[
            ApprovalCardSnapshot(approval_id="approval-1", run_id="run-1", title="Approve")
        ],
        artifacts=[
            ArtifactSnapshot(
                artifact_id="artifact-1",
                run_id="run-1",
                title="Report",
                kind="markdown",
            )
        ],
        children=[RunTimelineChildSnapshot(run_id="child-run-1", status="completed")],
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "run_id",
        "parent_run_id",
        "group_run_id",
        "run_group_id",
        "workflow_run_id",
        "agent_id",
        "status",
        "title",
        "task_id",
        "session_id",
        "task_run_link_created_at",
        "task_run_link_updated_at",
        "task_run_link_run_status",
        "task_run_link_last_event_sequence",
        "events",
        "tool_calls",
        "approvals",
        "pending_approval",
        "artifacts",
        "children",
        "created_at",
        "updated_at",
    ]
    assert payload["task_id"] == "task-1"
    assert payload["session_id"] == "chat-1"
    assert payload["task_run_link_last_event_sequence"] == 7
    assert payload["tool_calls"][0]["tool_name"] == "workspace.read"
    assert payload["children"][0]["run_id"] == "child-run-1"


def test_run_event_page_snapshot_json_shape_is_stable() -> None:
    snapshot = RunEventPageSnapshot(
        run_id="run-1",
        after_sequence=1,
        limit=2,
        next_after_sequence=3,
        has_more=True,
        events=[
            PublicRunEvent(
                event_id="event-2",
                run_id="run-1",
                sequence=2,
                event_type="agent.tool.call",
                title="Tool call",
            )
        ],
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "run_id",
        "after_sequence",
        "limit",
        "next_after_sequence",
        "has_more",
        "events",
    ]
    assert payload["run_id"] == "run-1"
    assert payload["after_sequence"] == 1
    assert payload["next_after_sequence"] == 3
    assert payload["has_more"] is True
    assert payload["events"][0]["event_type"] == "agent.tool.call"


def test_artifact_content_snapshot_json_shape_is_stable() -> None:
    snapshot = ArtifactContentSnapshot(
        run_id="run-1",
        task_id="task-1",
        path="reports/out.md",
        content="# Report",
        mime_type="text/markdown",
        truncated=True,
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "ok",
        "run_id",
        "task_id",
        "path",
        "content",
        "mime_type",
        "truncated",
    ]
    assert payload["ok"] is True
    assert payload["run_id"] == "run-1"
    assert payload["task_id"] == "task-1"
    assert payload["path"] == "reports/out.md"
    assert payload["content"] == "# Report"
    assert payload["truncated"] is True


def test_artifact_snapshot_keeps_runtime_trace_fields() -> None:
    snapshot = ArtifactSnapshot(
        artifact_id="artifact-1",
        run_id="run-1",
        source_run_id="run-source-1",
        source_tool="artifact.write",
        source_runnable_id="agent-1",
        source_runnable_name="Planner",
        workflow_id="workflow-1",
        workflow_run_id="workflow-run-1",
        workflow_node_id="report",
        workflow_node_label="Report",
        group_id="group-1",
        group_run_id="group-run-1",
        title="Report",
        kind="workflow_artifact",
        path="reports/out.md",
        mime_type="text/markdown",
        size_bytes=42,
        preview_text="# Report",
        url="/ui/runs/run-1/artifacts/reports/out.md",
        created_at="2026-06-14T00:00:00Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "artifact_id",
        "run_id",
        "source_run_id",
        "source_tool",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
        "title",
        "kind",
        "path",
        "mime_type",
        "size_bytes",
        "preview_text",
        "url",
        "created_at",
    ]
    assert payload["source_tool"] == "artifact.write"
    assert payload["workflow_node_id"] == "report"
    assert payload["group_run_id"] == "group-run-1"


def test_public_run_event_mapping_preserves_runtime_trace_payload_fields() -> None:
    event = public_run_event_from_payload(
        {
            "event": "memory.write.add",
            "run_id": "run-1",
            "sequence": 7,
            "memory_id": "memory-1",
            "memory_kind": "preference",
            "skill_id": "skill-1",
            "skill_name": "Workspace Reviewer",
            "workflow_node_id": "node-1",
            "workflow_node_label": "Review",
            "member_agent_id": "agent-2",
            "group_id": "group-1",
            "artifact_path": "reports/out.md",
            "payload": {
                "skill_id": "skill-from-payload",
                "result": {"ok": True},
            },
            "visibility": "internal",
            "sensitivity": "secret",
            "created_at": "2026-06-14T00:00:00Z",
        }
    )

    assert event.event_type == "memory.write.add"
    assert event.run_id == "run-1"
    assert event.sequence == 7
    assert event.visibility == "internal"
    assert event.sensitivity == "secret"
    assert event.payload["memory_id"] == "memory-1"
    assert event.payload["memory_kind"] == "preference"
    assert event.payload["skill_id"] == "skill-from-payload"
    assert event.payload["skill_name"] == "Workspace Reviewer"
    assert event.payload["workflow_node_id"] == "node-1"
    assert event.payload["workflow_node_label"] == "Review"
    assert event.payload["member_agent_id"] == "agent-2"
    assert event.payload["group_id"] == "group-1"
    assert event.payload["artifact_path"] == "reports/out.md"
    assert event.payload["result"] == {"ok": True}
    assert "event" not in event.payload
    assert "visibility" not in event.payload


def test_agent_definition_snapshot_keeps_editing_fields() -> None:
    snapshot = AgentDefinitionSnapshot(
        agent_id="agent-1",
        name="Planner",
        description="Plans work",
        instructions="Use concise steps.",
        persona_prompt="You are Yachiyo.",
        model_config={"provider": "model_profile"},
        skill_ids=["skill-1"],
    )

    payload = _json(snapshot)

    assert payload["instructions"] == "Use concise steps."
    assert payload["persona_prompt"] == "You are Yachiyo."
    assert payload["model_config"] == {"provider": "model_profile"}


def test_group_run_and_workflow_snapshots_keep_group_and_workflow_fields() -> None:
    member = AgentGroupMemberSnapshot(agent_id="agent-1", name="Planner", role="planner")
    group = AgentGroupSnapshot(
        group_id="group-1",
        name="Research team",
        description="Multi-agent research group",
        members=[member],
        mode="debate",
        moderator_agent_id="agent-1",
        default_model="gpt-test",
        memory_scope="hybrid",
        tool_policy_id="policy-1",
    )
    group_run = GroupRunSnapshot(
        group_run_id="group-run-1",
        group_id="group-1",
        title="Compare options",
        status="running",
        objective="Find the safest option",
        participants=[member],
        events=[
            PublicRunEvent(
                run_id="group-run-1",
                event_type="group.member.started",
                detail="Planner started",
            )
        ],
    )
    workflow = WorkflowSnapshot(
        workflow_id="workflow-1",
        name="Review workflow",
        nodes=[{"id": "start", "type": "start"}],
        edges=[],
        default_input_schema={"type": "object"},
    )
    workflow_run = WorkflowRunSnapshot(
        run_id="workflow-run-1",
        workflow_run_id="workflow-run-1",
        workflow_id="workflow-1",
        status="running",
        title="Review docs",
        objective="Review docs",
        events=[
            PublicRunEvent(
                run_id="workflow-run-1",
                event_type="workflow.node.started",
                detail="Start",
            )
        ],
        children=[RunTimelineChildSnapshot(run_id="agent-run-1", status="running")],
    )

    assert _json(group)["mode"] == "debate"
    assert _json(group)["members"][0]["role"] == "planner"
    assert _json(group_run)["participants"][0]["agent_id"] == "agent-1"
    assert _json(group_run)["events"][0]["event_type"] == "group.member.started"
    assert _json(workflow)["default_input_schema"] == {"type": "object"}
    assert _json(workflow_run)["run_id"] == "workflow-run-1"
    assert _json(workflow_run)["workflow_id"] == "workflow-1"
    assert _json(workflow_run)["events"][0]["event_type"] == "workflow.node.started"
    assert _json(workflow_run)["children"][0]["run_id"] == "agent-run-1"


def test_agent_definition_snapshot_serializes_model_config_alias() -> None:
    snapshot = AgentDefinitionSnapshot(
        agent_id="agent-1",
        name="Planner",
        model_settings={"provider": "model_profile"},
    )

    payload = _json(snapshot)

    assert "model_config" in payload
    assert "model_settings" not in payload
    assert payload["model_config"] == {"provider": "model_profile"}


def test_skill_snapshot_keeps_skill_library_fields() -> None:
    snapshot = SkillSnapshot(
        skill_id="skill-1",
        name="Workspace Reviewer",
        description="Reviews workspace files",
        source_path="/skills/workspace-reviewer",
        local_path="/managed/skills/workspace-reviewer",
        folder_id="folder-1",
        folder_name="Review",
        source_type="local_dir",
        origin_path="/skills/workspace-reviewer",
        source_ref="workspace-reviewer",
        content_hash="hash-1",
        last_synced_at="2026-06-14T00:00:00Z",
        sync_status="imported",
        content_summary="Review project files",
        skill_markdown="# Workspace Reviewer",
        asset_paths=["assets/icon.png"],
        enabled=True,
        created_at="2026-06-14T00:00:00Z",
        updated_at="2026-06-14T00:00:01Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "skill_id",
        "name",
        "description",
        "source_path",
        "local_path",
        "folder_id",
        "folder_name",
        "source_type",
        "origin_path",
        "source_ref",
        "content_hash",
        "last_synced_at",
        "sync_status",
        "content_summary",
        "skill_markdown",
        "asset_paths",
        "enabled",
        "created_at",
        "updated_at",
    ]
    assert payload["asset_paths"] == ["assets/icon.png"]


def test_skill_folder_snapshot_keeps_skill_library_grouping_fields() -> None:
    snapshot = SkillFolderSnapshot(
        folder_id="folder-1",
        name="Review",
        description="Review skills",
        source_scope="installed",
        sort_order=2,
        skill_count=3,
        installed_count=2,
        native_count=1,
        created_at="2026-06-14T00:00:00Z",
        updated_at="2026-06-14T00:00:01Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "folder_id",
        "name",
        "description",
        "source_scope",
        "sort_order",
        "skill_count",
        "installed_count",
        "native_count",
        "created_at",
        "updated_at",
    ]
    assert payload["source_scope"] == "installed"


def test_skill_source_root_snapshot_keeps_skill_discovery_fields() -> None:
    snapshot = SkillSourceRootSnapshot(
        path="/skills/native",
        source_type="native_global",
        library="native",
        exists=True,
        skill_count=4,
    )

    payload = _json(snapshot)

    assert list(payload) == ["path", "source_type", "library", "exists", "skill_count"]
    assert payload["library"] == "native"


def test_memory_snapshot_keeps_runtime_memory_fields() -> None:
    snapshot = MemorySnapshot(
        memory_id="memory-1",
        scope="global",
        kind="preference",
        content="Prefer concise status updates.",
        source_session_id="chat-1",
        source_message_id="message-1",
        source_task_id="task-1",
        source_run_id="run-1",
        confidence=0.9,
        pinned=True,
        user_confirmed=True,
        created_at="2026-06-14T00:00:00Z",
        updated_at="2026-06-14T00:00:01Z",
        deleted_at=None,
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "memory_id",
        "scope",
        "kind",
        "content",
        "source_session_id",
        "source_message_id",
        "source_task_id",
        "source_run_id",
        "confidence",
        "pinned",
        "user_confirmed",
        "created_at",
        "updated_at",
        "deleted_at",
    ]
    assert payload["source_run_id"] == "run-1"
    assert payload["pinned"] is True


def test_future_task_snapshots_keep_runtime_schedule_fields() -> None:
    future_task = FutureTaskSnapshot(
        future_task_id="future-1",
        title="Follow up later",
        prompt="Follow up on the report",
        runnable_id="agent-1",
        runnable_name="Planner",
        scheduled_at_epoch=1781433600.0,
        source_run_id="run-source-1",
        last_run_id="run-1",
        run_count=1,
    )
    triggered = FutureTaskTriggerResultSnapshot(
        future_task=future_task,
        run=RunTimelineSnapshot(run_id="run-1", status="completed"),
    )

    payload = _json(future_task)
    triggered_payload = _json(triggered)

    assert list(payload) == [
        "future_task_id",
        "title",
        "prompt",
        "runnable_id",
        "runnable_name",
        "status",
        "scheduled_at_epoch",
        "cron",
        "source_run_id",
        "last_run_id",
        "run_count",
        "error",
        "created_at",
        "updated_at",
        "cancelled_at",
    ]
    assert payload["last_run_id"] == "run-1"
    assert triggered_payload["future_task"]["future_task_id"] == "future-1"
    assert triggered_payload["run"]["run_id"] == "run-1"


def test_start_chat_task_request_keeps_workflow_target_field() -> None:
    request = StartChatTaskRequest(
        prompt="Build report",
        conversation_id="chat-1",
        workflow_id="workflow-1",
        metadata={"client_task_id": "task-workflow-1"},
    )

    payload = request.model_dump(mode="json", exclude_none=True)

    assert payload == {
        "prompt": "Build report",
        "conversation_id": "chat-1",
        "workflow_id": "workflow-1",
        "metadata": {"client_task_id": "task-workflow-1"},
    }


def test_studio_save_requests_keep_public_field_names() -> None:
    agent = SaveAgentRequest(
        agent_id="agent-1",
        name="Planner",
        model_config={"provider": "model_profile"},
        tool_policy={"allowed_tools": ["workspace.read"]},
        skill_ids=["skill-1"],
    )
    group = SaveAgentGroupRequest(
        group_id="group-1",
        name="Research Team",
        members=[SaveAgentGroupMemberRequest(agent_id="agent-1", role="planner")],
        mode="debate",
        memory_scope="hybrid",
    )
    workflow = SaveWorkflowRequest(
        workflow_id="workflow-1",
        name="Review workflow",
        nodes=[{"id": "start", "type": "start"}],
        edges=[],
        default_input_schema={"type": "object"},
    )

    agent_payload = agent.model_dump(mode="json", by_alias=True, exclude_none=True)
    group_payload = group.model_dump(mode="json", exclude_none=True)
    workflow_payload = workflow.model_dump(mode="json", exclude_none=True)

    assert "model_config" in agent_payload
    assert "model_settings" not in agent_payload
    assert agent_payload["model_config"] == {"provider": "model_profile"}
    assert group_payload["members"][0]["agent_id"] == "agent-1"
    assert group_payload["mode"] == "debate"
    assert workflow_payload["nodes"][0]["type"] == "start"
    assert workflow_payload["default_input_schema"] == {"type": "object"}
