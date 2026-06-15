"""Public Yachiyo Agent contract tests."""

from __future__ import annotations

import json

from apps.shell.yachiyo_agent import (
    AgentDefinitionSnapshot,
    AgentGroupMemberSnapshot,
    AgentGroupSnapshot,
    AgentTaskSnapshot,
    ApprovalCardSnapshot,
    ArtifactSnapshot,
    GroupRunSnapshot,
    PublicRunEvent,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    SaveAgentGroupMemberRequest,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    SkillSnapshot,
    ToolCallSnapshot,
    WorkflowSnapshot,
)


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


def test_run_timeline_snapshot_json_shape_covers_runtime_debug_objects() -> None:
    snapshot = RunTimelineSnapshot(
        run_id="run-1",
        parent_run_id=None,
        group_run_id="group-run-1",
        workflow_run_id="workflow-run-1",
        agent_id="agent-1",
        status="running",
        title="Ship docs",
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
        "events",
        "tool_calls",
        "approvals",
        "pending_approval",
        "artifacts",
        "children",
        "created_at",
        "updated_at",
    ]
    assert payload["tool_calls"][0]["tool_name"] == "workspace.read"
    assert payload["children"][0]["run_id"] == "child-run-1"


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
    )
    workflow = WorkflowSnapshot(
        workflow_id="workflow-1",
        name="Review workflow",
        nodes=[{"id": "start", "type": "start"}],
        edges=[],
        default_input_schema={"type": "object"},
    )

    assert _json(group)["mode"] == "debate"
    assert _json(group)["members"][0]["role"] == "planner"
    assert _json(group_run)["participants"][0]["agent_id"] == "agent-1"
    assert _json(workflow)["default_input_schema"] == {"type": "object"}


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
