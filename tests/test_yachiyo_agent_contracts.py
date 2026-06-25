"""Public Yachiyo Agent contract tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from apps.shell.agent.tools.plugins import (
    RestrictedPluginTool,
    RestrictedToolPluginManager,
    RestrictedToolPlugin,
    clear_restricted_tool_plugins,
    register_restricted_tool_plugin,
    unregister_restricted_tool_plugin,
)
from apps.shell.yachiyo_agent import (
    AgentDefinitionSnapshot,
    AgentDeskFileEventRequest,
    AgentDeskItemSnapshot,
    AgentDeskSnapshot,
    AgentGroupMemberSnapshot,
    AgentGroupSnapshot,
    AgentTaskLightSnapshot,
    AgentTaskSnapshot,
    ApprovalCardSnapshot,
    ArtifactContentSnapshot,
    ArtifactSnapshot,
    ChatRunnableCatalogSnapshot,
    ChatRunnableParticipantSnapshot,
    ChatRunnableSnapshot,
    DesktopActionRiskSnapshot,
    DesktopExecutionCapabilitySnapshot,
    DesktopRecoveryActionMetadataSnapshot,
    FutureTaskSnapshot,
    FutureTaskTriggerResultSnapshot,
    GroupRunSnapshot,
    InstallRestrictedToolPluginRequest,
    MemorySnapshot,
    MemoryTraceSnapshot,
    PublicRunEvent,
    RunEventPageSnapshot,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    RestrictedPluginToolSnapshot,
    RestrictedToolPluginSnapshot,
    SaveAgentDeskFileRequest,
    SaveAgentDeskNoteRequest,
    SaveAgentGroupMemberRequest,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    SkillFolderSnapshot,
    SkillSnapshot,
    SkillSourceRootSnapshot,
    SkillTraceSnapshot,
    StartChatTaskRequest,
    ToolCatalogItemSnapshot,
    ToolCatalogSnapshot,
    ToolCallSnapshot,
    UpdateRestrictedToolPluginRequest,
    WorkflowRunSnapshot,
    WorkflowSnapshot,
    approval_is_pending,
    desktop_action_risk_level,
    desktop_action_risk_snapshots,
    desktop_execution_capability_snapshots,
    desktop_tool_risk_level,
    is_high_risk_desktop_action,
    task_requires_user_action,
)
from apps.shell.yachiyo_agent.events import public_run_event_from_payload
from apps.shell.yachiyo_agent.group_run_snapshots import group_run_snapshot_from_payload
from apps.shell.yachiyo_agent.task_cards import agent_task_light_snapshot_from_task
from apps.shell.yachiyo_agent.tool_catalog import runtime_tool_catalog_snapshot


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
        tool_calls=[
            ToolCallSnapshot(
                tool_call_id="call-1",
                run_id="run-1",
                tool_name="workspace.write_patch",
                status="waiting_approval",
                input_preview={"path": "README.md"},
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
        "tool_calls",
        "artifacts",
        "open_in_studio_url",
        "created_at",
        "updated_at",
    ]
    assert payload["pending_approvals"][0]["approval_id"] == "approval-1"
    assert payload["recent_events"][0]["event_type"] == "agent.tool.approval_required"
    assert payload["tool_calls"][0]["tool_name"] == "workspace.write_patch"
    assert "event" not in payload["recent_events"][0]


def test_agent_task_light_snapshot_json_shape_is_stable() -> None:
    pending = ApprovalCardSnapshot(
        approval_id="approval-1",
        run_id="run-1",
        title="Approve workspace.write_patch",
        tool_name="workspace.write_patch",
        input_preview={"path": "README.md"},
    )
    snapshot = AgentTaskLightSnapshot(
        task_id="task-1",
        conversation_id="chat-1",
        title="Review README",
        status="waiting_approval",
        detail="Prepare patch",
        needs_user_action=True,
        pending_approval=pending,
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
        "detail",
        "needs_user_action",
        "pending_approval",
        "open_in_studio_url",
        "created_at",
        "updated_at",
    ]
    assert payload["pending_approval"]["approval_id"] == "approval-1"
    assert payload["open_in_studio_url"] == "#/agents?run_id=run-1"


def test_agent_task_light_snapshot_projects_full_task_for_launcher_surfaces() -> None:
    approved = ApprovalCardSnapshot(
        approval_id="approval-approved",
        run_id="run-1",
        title="Approved read",
        tool_name="workspace.read",
        status="approved",
    )
    pending = ApprovalCardSnapshot(
        approval_id="approval-pending",
        run_id="run-1",
        title="Approve write",
        tool_name="workspace.write_patch",
    )
    task = AgentTaskSnapshot(
        task_id="task-1",
        conversation_id="chat-1",
        title="Review README",
        status="waiting_approval",
        summary="Waiting",
        current_step="Prepare patch",
        progress_text="1 approval pending",
        needs_user_action=False,
        pending_approvals=[approved, pending],
        open_in_studio_url="#/agents?run_id=run-1",
        created_at="2026-06-14T00:00:00Z",
        updated_at="2026-06-14T00:00:01Z",
    )

    light = agent_task_light_snapshot_from_task(task)

    assert light.task_id == "task-1"
    assert light.detail == "Prepare patch"
    assert light.needs_user_action is True
    assert light.pending_approval is not None
    assert light.pending_approval.approval_id == "approval-pending"
    assert light.open_in_studio_url == "#/agents?run_id=run-1"


def test_approval_card_snapshot_keeps_runtime_trace_fields() -> None:
    snapshot = ApprovalCardSnapshot(
        approval_id="approval-1",
        run_id="run-1",
        source_run_id="child-run-1",
        source_runnable_id="agent-1",
        source_runnable_name="Planner",
        workflow_id="workflow-1",
        workflow_run_id="workflow-run-1",
        workflow_node_id="review",
        workflow_node_label="Review Gate",
        group_id="group-1",
        group_run_id="group-run-1",
        title="Approve Review Gate",
        description="Needs review",
        status="pending",
        tool_name="workflow.approval",
        risk_level="medium",
        input_preview={"checkpoint": "Review Gate"},
        policy_reason="manual checkpoint",
        requested_at="2026-06-14T00:00:00Z",
        resolved_at=None,
        open_in_studio_url="#/agents?run_id=run-1&group_run=group-run-1",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "approval_id",
        "run_id",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
        "title",
        "description",
        "status",
        "tool_name",
        "risk_level",
        "input_preview",
        "policy_reason",
        "requested_at",
        "resolved_at",
        "open_in_studio_url",
    ]
    assert payload["workflow_node_id"] == "review"
    assert payload["source_runnable_name"] == "Planner"
    assert payload["group_run_id"] == "group-run-1"


def test_product_policy_helpers_use_public_snapshots() -> None:
    pending = ApprovalCardSnapshot(
        approval_id="approval-pending",
        run_id="run-1",
        title="Approve write",
        tool_name="workspace.write_patch",
    )
    approved = ApprovalCardSnapshot(
        approval_id="approval-approved",
        run_id="run-1",
        title="Approved read",
        tool_name="workspace.read",
        status="approved",
    )
    task = AgentTaskSnapshot(
        task_id="task-1",
        title="Review README",
        status="running",
        pending_approvals=[approved, pending],
    )

    assert approval_is_pending(pending) is True
    assert approval_is_pending(approved) is False
    assert task_requires_user_action(task) is True

    cleared = task.model_copy(update={"pending_approvals": [approved]})
    assert task_requires_user_action(cleared) is False


def test_desktop_execution_capability_snapshot_json_shape_is_stable() -> None:
    snapshot = DesktopExecutionCapabilitySnapshot(
        available=True,
        platform="macos",
        missing_permissions=["accessibility"],
        tools=["desktop.type_text"],
        risk_default="medium",
        diagnostic_route="/ui/native-agent/diagnostics/cache",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "available",
        "platform",
        "missing_permissions",
        "tools",
        "available_tools",
        "degraded_tools",
        "unavailable_tools",
        "risk_default",
        "diagnostic_route",
    ]
    assert payload["available"] is True
    assert payload["risk_default"] == "medium"
    with pytest.raises(ValidationError):
        DesktopExecutionCapabilitySnapshot(
            available=True,
            platform="macos",
            unknown=True,
        )


def test_desktop_recovery_action_metadata_snapshot_json_shape_is_stable() -> None:
    snapshot = DesktopRecoveryActionMetadataSnapshot(
        recovery_tool="system.settings_open",
        recovery_input={"target": "屏幕录制权限"},
        recovery_permission_target="screen_recording",
        recovery_risk_level="low",
        recovery_retry_tool="screen.capture",
        recovery_retry_input={"display_id": "main"},
        recovery_retry_prompt="截图当前屏幕",
        recovery_retry_source_event_type="agent.desktop.permission_recovery",
        recovery_retry_source_tool_call_id="tool-call-1",
        source_task_id="task-source-screen",
        source_task_title="截图当前桌面",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "daily_desktop_intent",
        "desktop_permission_recovery",
        "desktop_permission_retry",
        "recovery_action_kind",
        "recovery_tool",
        "recovery_input",
        "recovery_permission_target",
        "recovery_risk_level",
        "recovery_retry_tool",
        "recovery_retry_input",
        "recovery_retry_prompt",
        "recovery_retry_source_event_type",
        "recovery_retry_source_tool_call_id",
        "source_task_id",
        "source_task_title",
    ]
    assert payload["daily_desktop_intent"] is True
    assert payload["desktop_permission_recovery"] is True
    assert payload["recovery_tool"] == "system.settings_open"
    assert payload["recovery_retry_tool"] == "screen.capture"
    with pytest.raises(ValidationError):
        DesktopRecoveryActionMetadataSnapshot(
            recovery_tool="system.settings_open",
            unknown=True,
        )


def test_desktop_action_risk_snapshot_json_shape_is_stable() -> None:
    snapshot = DesktopActionRiskSnapshot(
        action_id="foreground_type_text",
        risk_level="medium",
        title="Type into foreground UI",
        description="Enter text into the current foreground target.",
        tools=["desktop.type_text"],
        requires_approval=False,
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "action_id",
        "risk_level",
        "title",
        "description",
        "tools",
        "requires_approval",
    ]
    assert payload["risk_level"] == "medium"
    with pytest.raises(ValidationError):
        DesktopActionRiskSnapshot(
            action_id="read_screen",
            risk_level="low",
            title="Read screen",
            unknown=True,
        )


def test_desktop_execution_capability_policy_marks_registered_tools_available() -> None:
    capabilities = desktop_execution_capability_snapshots(
        platform_name="Darwin",
        registered_tools={
            "screen.capture",
            "desktop.permissions",
            "desktop.active_window",
            "desktop.windows",
            "desktop.ui_elements",
            "app.status",
            "app.open",
            "system.settings_open",
            "app.focus",
            "app.focus_window",
            "app.show",
            "app.hide",
            "app.minimize",
            "app.quit",
            "desktop.quit_app",
            "media.apple_music_play",
            "media.apple_music_open_and_play",
            "media.apple_music_control",
            "media.music_app_open_and_play",
        },
    )

    assert list(capabilities) == [
        "desktop_execution",
        "screen_capture",
        "active_window",
        "app_control",
        "media_control",
        "foreground_input",
        "browser_control",
    ]
    assert capabilities["desktop_execution"]["available"] is True
    assert "desktop.permissions" in capabilities["desktop_execution"]["available_tools"]
    assert capabilities["screen_capture"]["available"] is True
    assert capabilities["screen_capture"]["available_tools"] == ["screen.capture"]
    assert capabilities["foreground_input"]["available"] is False
    assert capabilities["foreground_input"]["unavailable_tools"] == [
        "app.open_and_safe_type_text",
        "app.focus_and_safe_type_text",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.focus_and_safe_key",
        "app.open_and_hotkey",
        "app.focus_and_hotkey",
        "app.open_and_safe_scroll",
        "app.focus_and_safe_scroll",
        "app.open_and_safe_click",
        "app.focus_and_safe_click",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.hide_app",
        "desktop.minimize_window",
        "desktop.close_window",
        "desktop.safe_shortcut",
        "desktop.safe_key",
        "desktop.safe_type_text",
        "desktop.safe_click",
        "desktop.safe_scroll",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
        "desktop.hotkey",
        "desktop.submit_foreground",
        "desktop.type_text",
        "desktop.click",
    ]
    assert capabilities["foreground_input"]["risk_default"] == "medium"
    assert capabilities["browser_control"]["available"] is False
    assert capabilities["screen_capture"]["diagnostic_route"] == "/screen/current"


def test_desktop_execution_capability_policy_applies_missing_permissions() -> None:
    capabilities = desktop_execution_capability_snapshots(
        platform_name="Darwin",
        registered_tools={
            "screen.capture",
            "desktop.active_window",
            "app.open",
            "system.settings_open",
            "app.focus",
            "app.show",
            "app.hide",
            "app.minimize",
            "media.apple_music_play",
            "media.apple_music_open_and_play",
            "media.apple_music_control",
            "media.music_app_open_and_play",
            "desktop.hotkey",
            "desktop.type_text",
            "desktop.click",
        },
        missing_permissions={
            "screen_capture": ["screen_recording"],
            "foreground_input": ["accessibility"],
        },
    )

    assert capabilities["desktop_execution"]["available"] is True
    assert capabilities["screen_capture"]["available"] is False
    assert capabilities["screen_capture"]["missing_permissions"] == ["screen_recording"]
    assert capabilities["foreground_input"]["available"] is False
    assert capabilities["foreground_input"]["missing_permissions"] == ["accessibility"]
    assert capabilities["media_control"]["available"] is True
    assert capabilities["media_control"]["available_tools"] == [
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
    ]
    assert capabilities["media_control"]["degraded_tools"] == [
        "media.music_app_open_and_play",
    ]


def test_desktop_execution_capability_policy_reports_tool_level_degradation() -> None:
    capabilities = desktop_execution_capability_snapshots(
        platform_name="Darwin",
        registered_tools={
            "screen.capture",
            "desktop.active_window",
            "app.open",
            "system.settings_open",
            "app.focus",
            "app.hide",
            "app.minimize",
            "media.apple_music_play",
            "media.apple_music_open_and_play",
            "media.apple_music_control",
            "media.music_app_open_and_play",
            "desktop.hotkey",
            "desktop.type_text",
            "desktop.click",
            "browser.open_url",
            "browser.open_url_and_extract_text",
            "browser.open_url_and_screenshot",
            "browser.current_page",
            "browser.click",
            "browser.type_text",
            "browser.extract_text",
            "browser.screenshot",
        },
        missing_permissions={
            "app_control": ["automation"],
            "media_control": ["automation"],
            "browser_control": ["chrome_cdp"],
        },
    )

    app_control = capabilities["app_control"]
    media_control = capabilities["media_control"]
    browser_control = capabilities["browser_control"]
    root = capabilities["desktop_execution"]

    assert app_control["available"] is False
    assert app_control["available_tools"] == [
        "app.open",
        "system.settings_open",
        "app.hide",
        "app.minimize",
    ]
    assert app_control["unavailable_tools"] == [
        "app.status",
        "app.focus",
        "app.focus_window",
        "app.show",
        "app.quit",
        "notes.create",
        "reminders.create",
        "calendar.create_event",
    ]
    assert media_control["available"] is False
    assert media_control["degraded_tools"] == [
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
    ]
    assert browser_control["available"] is False
    assert browser_control["degraded_tools"] == [
        "browser.open_url",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
        "browser.click",
        "browser.type_text",
        "browser.screenshot",
    ]
    assert "browser.current_page" in browser_control["unavailable_tools"]
    assert "browser.extract_text" in browser_control["unavailable_tools"]
    assert "app.open" in root["available_tools"]
    assert "media.apple_music_play" in root["degraded_tools"]
    assert "media.apple_music_open_and_play" in root["degraded_tools"]
    assert "media.apple_music_control" in root["degraded_tools"]


def test_desktop_execution_policy_records_risk_boundaries() -> None:
    assert desktop_tool_risk_level("screen.capture") == "low"
    assert desktop_tool_risk_level("desktop.permissions") == "low"
    assert desktop_tool_risk_level("desktop.running_apps") == "low"
    assert desktop_tool_risk_level("desktop.windows") == "low"
    assert desktop_tool_risk_level("desktop.ui_elements") == "low"
    assert desktop_tool_risk_level("app.status") == "low"
    assert desktop_tool_risk_level("app.show") == "low"
    assert desktop_tool_risk_level("app.focus_window") == "low"
    assert desktop_tool_risk_level("app.open_and_safe_type_text") == "low"
    assert desktop_tool_risk_level("app.focus_and_safe_type_text") == "low"
    assert desktop_tool_risk_level("app.open_and_safe_shortcut") == "low"
    assert desktop_tool_risk_level("app.focus_and_safe_shortcut") == "low"
    assert desktop_tool_risk_level("app.open_and_safe_key") == "low"
    assert desktop_tool_risk_level("app.focus_and_safe_key") == "low"
    assert desktop_tool_risk_level("app.open_and_hotkey") == "medium"
    assert desktop_tool_risk_level("app.focus_and_hotkey") == "medium"
    assert desktop_tool_risk_level("app.open_and_safe_scroll") == "low"
    assert desktop_tool_risk_level("app.focus_and_safe_scroll") == "low"
    assert desktop_tool_risk_level("app.open_and_safe_click") == "low"
    assert desktop_tool_risk_level("app.focus_and_safe_click") == "low"
    assert desktop_tool_risk_level("app.open_and_click_ui_element") == "medium"
    assert desktop_tool_risk_level("app.focus_and_click_ui_element") == "medium"
    assert desktop_tool_risk_level("app.open_and_type_into_ui_element") == "medium"
    assert desktop_tool_risk_level("app.focus_and_type_into_ui_element") == "medium"
    assert desktop_tool_risk_level("app.hide") == "low"
    assert desktop_tool_risk_level("app.minimize") == "low"
    assert desktop_tool_risk_level("app.quit") == "medium"
    assert desktop_tool_risk_level("desktop.quit_app") == "medium"
    assert desktop_tool_risk_level("desktop.hide_app") == "low"
    assert desktop_tool_risk_level("desktop.minimize_window") == "low"
    assert desktop_tool_risk_level("desktop.safe_shortcut") == "low"
    assert desktop_tool_risk_level("desktop.safe_key") == "low"
    assert desktop_tool_risk_level("desktop.safe_type_text") == "low"
    assert desktop_tool_risk_level("desktop.safe_click") == "low"
    assert desktop_tool_risk_level("desktop.safe_scroll") == "low"
    assert desktop_tool_risk_level("desktop.close_window") == "medium"
    assert desktop_tool_risk_level("desktop.click_ui_element") == "medium"
    assert desktop_tool_risk_level("desktop.type_into_ui_element") == "medium"
    assert desktop_tool_risk_level("desktop.submit_foreground") == "high"
    assert desktop_tool_risk_level("desktop.type_text") == "medium"
    assert desktop_tool_risk_level("desktop.click") == "medium"
    assert desktop_tool_risk_level("desktop.reveal_path") == "low"
    assert desktop_tool_risk_level("desktop.open_path") == "low"
    assert desktop_tool_risk_level("media.music_app_open_and_play") == "low"
    assert desktop_tool_risk_level("system.settings_open") == "low"
    assert desktop_tool_risk_level("system.volume") == "low"
    assert desktop_tool_risk_level("system.brightness") == "low"
    assert desktop_tool_risk_level("system.display_sleep") == "low"
    assert desktop_tool_risk_level("system.screen_saver_start") == "low"
    assert desktop_tool_risk_level("clipboard.write") == "low"
    assert desktop_tool_risk_level("notes.create") == "low"
    assert desktop_tool_risk_level("reminders.create") == "low"
    assert desktop_tool_risk_level("calendar.create_event") == "low"
    assert desktop_tool_risk_level("browser.open_url") == "low"
    assert desktop_tool_risk_level("browser.open_url_and_extract_text") == "low"
    assert desktop_tool_risk_level("browser.open_url_and_screenshot") == "low"
    assert desktop_tool_risk_level("browser.click") == "medium"
    assert desktop_tool_risk_level("terminal.run") is None
    assert desktop_action_risk_level("read_screen") == "low"
    assert desktop_action_risk_level("diagnose_permissions") == "low"
    assert desktop_action_risk_level("open_path") == "low"
    assert desktop_action_risk_level("create_note") == "low"
    assert desktop_action_risk_level("create_reminder") == "low"
    assert desktop_action_risk_level("create_calendar_event") == "low"
    assert desktop_action_risk_level("control_system_volume") == "low"
    assert desktop_action_risk_level("control_system_brightness") == "low"
    assert desktop_action_risk_level("control_display_sleep") == "low"
    assert desktop_action_risk_level("control_screen_saver") == "low"
    assert desktop_action_risk_level("write_clipboard") == "low"
    assert desktop_action_risk_level("show_app") == "low"
    assert desktop_action_risk_level("focus_app_window") == "low"
    assert desktop_action_risk_level("hide_app") == "low"
    assert desktop_action_risk_level("minimize_app") == "low"
    assert desktop_action_risk_level("foreground_hide_app") == "low"
    assert desktop_action_risk_level("foreground_minimize_window") == "low"
    assert desktop_action_risk_level("foreground_safe_shortcut") == "low"
    assert desktop_action_risk_level("foreground_safe_key") == "low"
    assert desktop_action_risk_level("foreground_safe_type_text") == "low"
    assert desktop_action_risk_level("foreground_safe_click") == "low"
    assert desktop_action_risk_level("foreground_safe_scroll") == "low"
    assert desktop_action_risk_level("quit_app") == "medium"
    assert desktop_action_risk_level("foreground_close_window") == "medium"
    assert desktop_action_risk_level("foreground_click_ui_element") == "medium"
    assert desktop_action_risk_level("foreground_type_into_ui_element") == "medium"
    assert desktop_action_risk_level("foreground_type_text") == "medium"
    assert desktop_action_risk_level("foreground_submit") == "high"
    assert desktop_action_risk_level("send_message") == "high"
    assert is_high_risk_desktop_action("raw_shell") is True
    assert is_high_risk_desktop_action("system_settings") is True
    assert is_high_risk_desktop_action("play_music") is False


def test_desktop_action_risk_catalog_covers_product_boundaries() -> None:
    catalog = {item.action_id: item for item in desktop_action_risk_snapshots()}

    assert list(catalog)[:30] == [
        "read_screen",
        "diagnose_permissions",
        "read_active_window",
        "read_running_apps",
        "read_windows",
        "read_ui_elements",
        "read_app_status",
        "open_app",
        "focus_app",
        "focus_app_window",
        "show_app",
        "hide_app",
        "minimize_app",
        "quit_app",
        "reveal_path",
        "open_path",
        "play_or_pause_media",
        "control_system_volume",
        "control_system_brightness",
        "control_display_sleep",
        "control_screen_saver",
        "write_clipboard",
        "create_note",
        "create_reminder",
        "create_calendar_event",
        "foreground_safe_shortcut",
        "foreground_safe_key",
        "foreground_safe_type_text",
        "foreground_safe_click",
        "foreground_safe_scroll",
    ]
    assert catalog["read_screen"].risk_level == "low"
    assert catalog["read_screen"].tools == ["screen.capture"]
    assert catalog["diagnose_permissions"].risk_level == "low"
    assert catalog["diagnose_permissions"].tools == ["desktop.permissions"]
    assert catalog["read_running_apps"].risk_level == "low"
    assert catalog["read_running_apps"].tools == ["desktop.running_apps"]
    assert catalog["read_windows"].risk_level == "low"
    assert catalog["read_windows"].tools == ["desktop.windows"]
    assert catalog["read_ui_elements"].risk_level == "low"
    assert catalog["read_ui_elements"].tools == ["desktop.ui_elements"]
    assert catalog["read_app_status"].risk_level == "low"
    assert catalog["read_app_status"].tools == ["app.status"]
    assert catalog["focus_app_window"].risk_level == "low"
    assert catalog["focus_app_window"].tools == ["app.focus_window"]
    assert catalog["show_app"].risk_level == "low"
    assert catalog["show_app"].tools == ["app.show"]
    assert catalog["hide_app"].risk_level == "low"
    assert catalog["hide_app"].tools == ["app.hide"]
    assert catalog["minimize_app"].risk_level == "low"
    assert catalog["minimize_app"].tools == ["app.minimize"]
    assert catalog["quit_app"].risk_level == "medium"
    assert catalog["quit_app"].tools == ["app.quit", "desktop.quit_app"]
    assert catalog["reveal_path"].risk_level == "low"
    assert catalog["reveal_path"].tools == ["desktop.reveal_path"]
    assert catalog["open_path"].risk_level == "low"
    assert catalog["open_path"].tools == ["desktop.open_path"]
    assert catalog["play_or_pause_media"].tools == [
        "media.apple_music_play",
        "media.apple_music_open_and_play",
        "media.apple_music_control",
        "media.music_app_open_and_play",
        "media.music_app_control",
        "media.system_control",
    ]
    assert catalog["system_settings"].tools == ["system.settings_open"]
    assert catalog["control_system_volume"].tools == ["system.volume"]
    assert catalog["control_system_brightness"].tools == ["system.brightness"]
    assert catalog["control_display_sleep"].tools == ["system.display_sleep"]
    assert catalog["control_screen_saver"].tools == ["system.screen_saver_start"]
    assert catalog["write_clipboard"].tools == ["clipboard.write"]
    assert catalog["create_note"].tools == ["notes.create"]
    assert catalog["create_reminder"].tools == ["reminders.create"]
    assert catalog["create_calendar_event"].tools == ["calendar.create_event"]
    assert catalog["foreground_safe_shortcut"].risk_level == "low"
    assert catalog["foreground_safe_shortcut"].tools == ["desktop.safe_shortcut"]
    assert catalog["foreground_safe_key"].risk_level == "low"
    assert catalog["foreground_safe_key"].tools == ["desktop.safe_key"]
    assert catalog["foreground_safe_type_text"].risk_level == "low"
    assert catalog["foreground_safe_type_text"].tools == ["desktop.safe_type_text"]
    assert catalog["foreground_safe_click"].risk_level == "low"
    assert catalog["foreground_safe_click"].tools == ["desktop.safe_click"]
    assert catalog["foreground_safe_scroll"].risk_level == "low"
    assert catalog["foreground_safe_scroll"].tools == ["desktop.safe_scroll"]
    assert catalog["foreground_hide_app"].risk_level == "low"
    assert catalog["foreground_hide_app"].tools == ["desktop.hide_app"]
    assert catalog["foreground_minimize_window"].risk_level == "low"
    assert catalog["foreground_minimize_window"].tools == ["desktop.minimize_window"]
    assert catalog["foreground_click_ui_element"].risk_level == "medium"
    assert catalog["foreground_click_ui_element"].tools == [
        "desktop.click_ui_element",
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
    ]
    assert catalog["foreground_type_into_ui_element"].risk_level == "medium"
    assert catalog["foreground_type_into_ui_element"].tools == [
        "desktop.type_into_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
    ]
    assert catalog["foreground_click"].risk_level == "medium"
    assert catalog["foreground_click"].requires_approval is False
    assert catalog["foreground_close_window"].risk_level == "medium"
    assert catalog["foreground_close_window"].tools == ["desktop.close_window"]
    assert catalog["foreground_submit"].risk_level == "high"
    assert catalog["foreground_submit"].requires_approval is True
    assert catalog["foreground_submit"].tools == ["desktop.submit_foreground"]
    assert catalog["delete_or_overwrite_user_file"].risk_level == "high"
    assert catalog["delete_or_overwrite_user_file"].requires_approval is True
    assert catalog["credential_access"].requires_approval is True


def test_tool_catalog_snapshot_json_shape_is_stable() -> None:
    snapshot = ToolCatalogSnapshot(
        tools=[
            ToolCatalogItemSnapshot(
                tool_name="media.apple_music_play",
                function_name="media_apple_music_play",
                description="Play music",
                capability_id="media_control",
                risk_level="low",
                approval_required=False,
                input_schema={"type": "object"},
                model_tool_schema={"type": "function"},
                missing_permissions=["music_app"],
                fallback_notes=["Open Music when direct playback is unavailable."],
                diagnostic_route="/ui/native-agent/diagnostics/cache",
            )
        ],
        capabilities={
            "media_control": DesktopExecutionCapabilitySnapshot(
                available=False,
                platform="macos",
                missing_permissions=["music_app"],
                tools=["media.apple_music_play"],
                risk_default="low",
                diagnostic_route="/ui/native-agent/diagnostics/cache",
            )
        },
        plugins=[
            RestrictedToolPluginSnapshot(
                plugin_id="notes",
                enabled=False,
                tool_names=["plugin.notes.echo"],
                tools=[
                    RestrictedPluginToolSnapshot(
                        tool_name="plugin.notes.echo",
                        tool_id="echo",
                        function_name="plugin_notes_echo",
                        risk_level="medium",
                    )
                ],
                skill_docs="Use echo for notes.",
            )
        ],
    )

    payload = _json(snapshot)

    assert list(payload) == ["tools", "capabilities", "plugins", "source"]
    assert payload["tools"][0]["tool_name"] == "media.apple_music_play"
    assert payload["tools"][0]["input_schema"] == {"type": "object"}
    assert payload["tools"][0]["fallback_notes"] == [
        "Open Music when direct playback is unavailable."
    ]
    assert payload["plugins"][0]["plugin_id"] == "notes"
    assert payload["plugins"][0]["enabled"] is False
    assert payload["plugins"][0]["tools"][0]["risk_level"] == "medium"
    with pytest.raises(ValidationError):
        ToolCatalogItemSnapshot(
            tool_name="terminal.run",
            function_name="terminal_run",
            unknown=True,
        )
    with pytest.raises(ValidationError):
        RestrictedToolPluginSnapshot(plugin_id="notes", unknown=True)

    install_request = _json(
        InstallRestrictedToolPluginRequest(plugin_id="notes", enabled=False)
    )
    update_request = _json(UpdateRestrictedToolPluginRequest(enabled=True))
    assert install_request == {"plugin_id": "notes", "enabled": False}
    assert update_request == {"enabled": True}
    with pytest.raises(ValidationError):
        InstallRestrictedToolPluginRequest(plugin_id="notes", unknown=True)
    with pytest.raises(ValidationError):
        UpdateRestrictedToolPluginRequest(enabled=True, unknown=True)


def test_runtime_tool_catalog_surfaces_desktop_risk_schema_and_fallbacks() -> None:
    catalog = runtime_tool_catalog_snapshot(
        platform_name="Darwin",
        missing_permissions={
            "media_control": ["music_app"],
            "browser_control": ["chrome_cdp"],
        },
    )
    tools = {tool.tool_name: tool for tool in catalog.tools}

    music = tools["media.apple_music_play"]
    music_app = tools["media.music_app_open_and_play"]
    settings = tools["system.settings_open"]
    brightness = tools["system.brightness"]
    display_sleep = tools["system.display_sleep"]
    screen_saver = tools["system.screen_saver_start"]
    permissions = tools["desktop.permissions"]
    quit_app = tools["app.quit"]
    named_show_app = tools["app.show"]
    named_focus_window = tools["app.focus_window"]
    open_safe_type_text = tools["app.open_and_safe_type_text"]
    focus_safe_shortcut = tools["app.focus_and_safe_shortcut"]
    open_safe_key = tools["app.open_and_safe_key"]
    focus_safe_key = tools["app.focus_and_safe_key"]
    open_hotkey = tools["app.open_and_hotkey"]
    focus_hotkey = tools["app.focus_and_hotkey"]
    open_safe_scroll = tools["app.open_and_safe_scroll"]
    focus_safe_scroll = tools["app.focus_and_safe_scroll"]
    open_safe_click = tools["app.open_and_safe_click"]
    focus_safe_click = tools["app.focus_and_safe_click"]
    open_click_ui_element = tools["app.open_and_click_ui_element"]
    focus_click_ui_element = tools["app.focus_and_click_ui_element"]
    open_type_into_ui_element = tools["app.open_and_type_into_ui_element"]
    focus_type_into_ui_element = tools["app.focus_and_type_into_ui_element"]
    named_hide_app = tools["app.hide"]
    named_minimize_app = tools["app.minimize"]
    note_tool = tools["notes.create"]
    reminder = tools["reminders.create"]
    calendar_event = tools["calendar.create_event"]
    hide_app = tools["desktop.hide_app"]
    safe_shortcut = tools["desktop.safe_shortcut"]
    safe_key = tools["desktop.safe_key"]
    safe_type_text = tools["desktop.safe_type_text"]
    safe_click = tools["desktop.safe_click"]
    safe_scroll = tools["desktop.safe_scroll"]
    click_ui_element = tools["desktop.click_ui_element"]
    type_into_ui_element = tools["desktop.type_into_ui_element"]
    minimize_window = tools["desktop.minimize_window"]
    close_window = tools["desktop.close_window"]
    browser = tools["browser.open_url"]
    browser_open_extract = tools["browser.open_url_and_extract_text"]
    browser_open_screenshot = tools["browser.open_url_and_screenshot"]
    terminal = tools["terminal.run"]

    assert music.capability_id == "media_control"
    assert music.risk_level == "low"
    assert music.input_schema["required"] == ["query"]
    assert music.missing_permissions == ["music_app"]
    assert any("Music" in note for note in music.fallback_notes)
    assert music_app.capability_id == "media_control"
    assert music_app.risk_level == "low"
    assert music_app.input_schema["required"] == ["app_name"]
    assert music_app.missing_permissions == []
    assert any("media play key" in note for note in music_app.fallback_notes)
    assert settings.capability_id == "app_control"
    assert settings.risk_level == "low"
    assert settings.input_schema["required"] == ["target"]
    assert settings.missing_permissions == []
    assert any("does not change settings" in note for note in settings.fallback_notes)
    assert brightness.capability_id == "desktop_execution"
    assert brightness.risk_level == "low"
    assert brightness.input_schema["required"] == ["action"]
    assert any("brightness key events" in note for note in brightness.fallback_notes)
    assert display_sleep.capability_id == "desktop_execution"
    assert display_sleep.risk_level == "low"
    assert display_sleep.input_schema["required"] == []
    assert any("displaysleepnow" in note for note in display_sleep.fallback_notes)
    assert screen_saver.capability_id == "desktop_execution"
    assert screen_saver.risk_level == "low"
    assert screen_saver.input_schema["required"] == []
    assert any("ScreenSaverEngine" in note for note in screen_saver.fallback_notes)
    assert permissions.capability_id == "desktop_execution"
    assert permissions.risk_level == "low"
    assert any("missing desktop permission" in note for note in permissions.fallback_notes)
    assert quit_app.capability_id == "app_control"
    assert quit_app.risk_level == "medium"
    assert quit_app.approval_required is False
    assert quit_app.input_schema["required"] == ["app_name"]
    assert any("approval" in note for note in quit_app.fallback_notes)
    foreground_quit_app = tools["desktop.quit_app"]
    assert foreground_quit_app.capability_id == "app_control"
    assert foreground_quit_app.risk_level == "medium"
    assert foreground_quit_app.input_schema["properties"] == {}
    assert any("foreground app" in note for note in foreground_quit_app.fallback_notes)
    assert named_show_app.capability_id == "app_control"
    assert named_show_app.risk_level == "low"
    assert named_show_app.input_schema["required"] == ["app_name"]
    assert any("show, unhide, restore" in note for note in named_show_app.fallback_notes)
    assert named_focus_window.capability_id == "app_control"
    assert named_focus_window.risk_level == "low"
    assert named_focus_window.input_schema["required"] == ["app_name", "title_contains"]
    assert any(
        "matching app window" in note for note in named_focus_window.fallback_notes
    )
    assert note_tool.capability_id == "app_control"
    assert note_tool.risk_level == "low"
    assert note_tool.input_schema["required"] == ["body"]
    assert any("Notes" in note for note in note_tool.fallback_notes)
    assert reminder.capability_id == "app_control"
    assert reminder.risk_level == "low"
    assert reminder.input_schema["required"] == ["title"]
    assert any("Reminders" in note for note in reminder.fallback_notes)
    assert calendar_event.capability_id == "app_control"
    assert calendar_event.risk_level == "low"
    assert calendar_event.input_schema["required"] == ["title", "start_at"]
    assert any("Calendar" in note for note in calendar_event.fallback_notes)
    assert open_safe_type_text.capability_id == "foreground_input"
    assert open_safe_type_text.risk_level == "low"
    assert open_safe_type_text.input_schema["required"] == ["app_name", "text"]
    assert any("typing only text explicitly provided" in note for note in open_safe_type_text.fallback_notes)
    assert focus_safe_shortcut.capability_id == "foreground_input"
    assert focus_safe_shortcut.risk_level == "low"
    assert focus_safe_shortcut.input_schema["required"] == ["app_name", "action"]
    assert "paste" in focus_safe_shortcut.input_schema["properties"]["action"]["enum"]
    assert "new_document" in focus_safe_shortcut.input_schema["properties"]["action"]["enum"]
    assert "new_event" in focus_safe_shortcut.input_schema["properties"]["action"]["enum"]
    assert any("whitelisted safe shortcuts" in note for note in focus_safe_shortcut.fallback_notes)
    assert open_safe_key.capability_id == "foreground_input"
    assert open_safe_key.risk_level == "low"
    assert open_safe_key.input_schema["required"] == ["app_name", "action"]
    assert "tab" in open_safe_key.input_schema["properties"]["action"]["enum"]
    assert "shift_tab" in open_safe_key.input_schema["properties"]["action"]["enum"]
    assert "return" not in open_safe_key.input_schema["properties"]["action"]["enum"]
    assert any("whitelisted foreground navigation keys" in note for note in open_safe_key.fallback_notes)
    assert focus_safe_key.capability_id == "foreground_input"
    assert focus_safe_key.risk_level == "low"
    assert focus_safe_key.input_schema["required"] == ["app_name", "action"]
    assert "arrow_down" in focus_safe_key.input_schema["properties"]["action"]["enum"]
    assert "shift_tab" in focus_safe_key.input_schema["properties"]["action"]["enum"]
    assert open_hotkey.capability_id == "foreground_input"
    assert open_hotkey.risk_level == "medium"
    assert open_hotkey.input_schema["required"] == ["app_name", "key"]
    assert "command" in open_hotkey.input_schema["properties"]["modifiers"]["items"]["enum"]
    assert any("approval is required" in note for note in open_hotkey.fallback_notes)
    assert focus_hotkey.capability_id == "foreground_input"
    assert focus_hotkey.risk_level == "medium"
    assert focus_hotkey.input_schema["required"] == ["app_name", "key"]
    assert open_safe_scroll.capability_id == "foreground_input"
    assert open_safe_scroll.risk_level == "low"
    assert open_safe_scroll.input_schema["required"] == ["app_name", "direction"]
    assert open_safe_scroll.input_schema["properties"]["direction"]["enum"] == ["up", "down"]
    assert any("explicit foreground up/down page requests" in note for note in open_safe_scroll.fallback_notes)
    assert focus_safe_scroll.capability_id == "foreground_input"
    assert focus_safe_scroll.risk_level == "low"
    assert focus_safe_scroll.input_schema["required"] == ["app_name", "direction"]
    assert focus_safe_scroll.input_schema["properties"]["direction"]["enum"] == ["up", "down"]
    assert open_safe_click.capability_id == "foreground_input"
    assert open_safe_click.risk_level == "low"
    assert open_safe_click.input_schema["required"] == ["app_name", "x", "y"]
    assert open_safe_click.input_schema["properties"]["x"]["type"] == "number"
    assert any("coordinates explicitly provided by the user" in note for note in open_safe_click.fallback_notes)
    assert focus_safe_click.capability_id == "foreground_input"
    assert focus_safe_click.risk_level == "low"
    assert focus_safe_click.input_schema["required"] == ["app_name", "x", "y"]
    assert focus_safe_click.input_schema["properties"]["y"]["type"] == "number"
    assert open_click_ui_element.capability_id == "foreground_input"
    assert open_click_ui_element.risk_level == "medium"
    assert open_click_ui_element.input_schema["required"] == ["app_name", "target"]
    assert open_click_ui_element.input_schema["properties"]["target"]["type"] == "string"
    assert any("approval is required" in note for note in open_click_ui_element.fallback_notes)
    assert focus_click_ui_element.capability_id == "foreground_input"
    assert focus_click_ui_element.risk_level == "medium"
    assert focus_click_ui_element.input_schema["required"] == ["app_name", "target"]
    assert focus_click_ui_element.input_schema["properties"]["click_count"]["maximum"] == 3
    assert open_type_into_ui_element.capability_id == "foreground_input"
    assert open_type_into_ui_element.risk_level == "medium"
    assert open_type_into_ui_element.input_schema["required"] == ["app_name", "target", "text"]
    assert open_type_into_ui_element.input_schema["properties"]["target"]["type"] == "string"
    assert any("approval is required" in note for note in open_type_into_ui_element.fallback_notes)
    assert focus_type_into_ui_element.capability_id == "foreground_input"
    assert focus_type_into_ui_element.risk_level == "medium"
    assert focus_type_into_ui_element.input_schema["required"] == ["app_name", "target", "text"]
    assert named_hide_app.capability_id == "app_control"
    assert named_hide_app.risk_level == "low"
    assert named_hide_app.input_schema["required"] == ["app_name"]
    assert any("hides a running app" in note for note in named_hide_app.fallback_notes)
    assert named_minimize_app.capability_id == "app_control"
    assert named_minimize_app.risk_level == "low"
    assert named_minimize_app.input_schema["required"] == ["app_name"]
    assert any("minimizes windows for a running app" in note for note in named_minimize_app.fallback_notes)
    assert hide_app.capability_id == "foreground_input"
    assert hide_app.risk_level == "low"
    assert hide_app.input_schema["properties"] == {}
    assert any("hides the current foreground app" in note for note in hide_app.fallback_notes)
    assert safe_shortcut.capability_id == "foreground_input"
    assert safe_shortcut.risk_level == "low"
    assert safe_shortcut.input_schema["required"] == ["action"]
    assert "copy" in safe_shortcut.input_schema["properties"]["action"]["enum"]
    assert "new_document" in safe_shortcut.input_schema["properties"]["action"]["enum"]
    assert "new_event" in safe_shortcut.input_schema["properties"]["action"]["enum"]
    assert any("whitelisted common shortcut" in note for note in safe_shortcut.fallback_notes)
    assert safe_key.capability_id == "foreground_input"
    assert safe_key.risk_level == "low"
    assert safe_key.input_schema["required"] == ["action"]
    assert "tab" in safe_key.input_schema["properties"]["action"]["enum"]
    assert "shift_tab" in safe_key.input_schema["properties"]["action"]["enum"]
    assert "return" not in safe_key.input_schema["properties"]["action"]["enum"]
    assert any("whitelisted foreground navigation keys" in note for note in safe_key.fallback_notes)
    assert safe_type_text.capability_id == "foreground_input"
    assert safe_type_text.risk_level == "low"
    assert safe_type_text.input_schema["required"] == ["text"]
    assert any("explicitly provided by the user" in note for note in safe_type_text.fallback_notes)
    assert safe_click.capability_id == "foreground_input"
    assert safe_click.risk_level == "low"
    assert safe_click.input_schema["required"] == ["x", "y"]
    assert any("coordinates explicitly provided by the user" in note for note in safe_click.fallback_notes)
    assert safe_scroll.capability_id == "foreground_input"
    assert safe_scroll.risk_level == "low"
    assert safe_scroll.input_schema["required"] == ["direction"]
    assert safe_scroll.input_schema["properties"]["direction"]["enum"] == ["up", "down"]
    assert any("scrolls only explicit foreground up/down page requests" in note for note in safe_scroll.fallback_notes)
    assert click_ui_element.capability_id == "foreground_input"
    assert click_ui_element.risk_level == "medium"
    assert click_ui_element.input_schema["required"] == ["target"]
    assert any("inferred coordinate" in note for note in click_ui_element.fallback_notes)
    assert type_into_ui_element.capability_id == "foreground_input"
    assert type_into_ui_element.risk_level == "medium"
    assert type_into_ui_element.input_schema["required"] == ["target", "text"]
    assert any("types user-provided text" in note for note in type_into_ui_element.fallback_notes)
    assert minimize_window.capability_id == "foreground_input"
    assert minimize_window.risk_level == "low"
    assert minimize_window.input_schema["properties"] == {}
    assert any("minimizes the current foreground window" in note for note in minimize_window.fallback_notes)
    assert close_window.capability_id == "foreground_input"
    assert close_window.risk_level == "medium"
    assert close_window.input_schema["properties"] == {}
    assert any("foreground window" in note for note in close_window.fallback_notes)
    submit_foreground = tools["desktop.submit_foreground"]
    assert submit_foreground.capability_id == "foreground_input"
    assert submit_foreground.risk_level == "high"
    assert submit_foreground.approval_required is True
    assert submit_foreground.input_schema["required"] == ["action"]
    assert submit_foreground.input_schema["properties"]["action"]["enum"] == [
        "send",
        "submit",
        "confirm",
    ]
    assert any("Always requires approval" in note for note in submit_foreground.fallback_notes)
    assert browser.capability_id == "browser_control"
    assert browser.risk_level == "low"
    assert browser.missing_permissions == ["chrome_cdp"]
    assert any("Chrome CDP" in note for note in browser.fallback_notes)
    assert browser_open_extract.capability_id == "browser_control"
    assert browser_open_extract.risk_level == "low"
    assert browser_open_extract.input_schema["required"] == ["url"]
    assert any("text extraction" in note for note in browser_open_extract.fallback_notes)
    assert browser_open_screenshot.capability_id == "browser_control"
    assert browser_open_screenshot.risk_level == "low"
    assert browser_open_screenshot.input_schema["required"] == ["url"]
    assert any("captures the page" in note for note in browser_open_screenshot.fallback_notes)
    assert terminal.risk_level == "high"
    assert terminal.approval_required is True


def test_runtime_tool_catalog_surfaces_restricted_plugin_metadata_and_uninstall() -> None:
    clear_restricted_tool_plugins()

    def echo_tool(payload, context):
        return {"ok": True, "text": payload["text"], "plugin_id": context.plugin_id}

    try:
        register_restricted_tool_plugin(
            RestrictedToolPlugin(
                plugin_id="notes",
                tools=(
                    RestrictedPluginTool(
                        tool_id="echo",
                        description="Echo text through a restricted test plugin.",
                        properties={"text": {"type": "string"}},
                        required=("text",),
                        risk_level="medium",
                        execute=echo_tool,
                    ),
                ),
                skill_docs="Use this plugin when an Agent Desk note needs a short echo.",
            )
        )
        tools = {tool.tool_name: tool for tool in runtime_tool_catalog_snapshot().tools}
        plugins = {
            plugin.plugin_id: plugin
            for plugin in runtime_tool_catalog_snapshot().plugins
        }
        plugin_tool = tools["plugin.notes.echo"]

        assert plugin_tool.capability_id == "plugin_tool"
        assert plugin_tool.risk_level == "medium"
        assert plugin_tool.approval_required is False
        assert plugin_tool.source == "plugin:notes"
        assert plugin_tool.input_schema["required"] == ["text"]
        assert "Restricted tool-only plugin: notes." in plugin_tool.fallback_notes
        assert any("Agent Desk note" in note for note in plugin_tool.fallback_notes)
        assert plugins["notes"].enabled is True
        assert plugins["notes"].tool_names == ["plugin.notes.echo"]
        assert plugins["notes"].tools[0].function_name == "plugin_notes_echo"
        assert plugins["notes"].tools[0].risk_level == "medium"

        unregister_restricted_tool_plugin("notes")
        tools_after_unregister = {
            tool.tool_name for tool in runtime_tool_catalog_snapshot().tools
        }
        assert "plugin.notes.echo" not in tools_after_unregister
    finally:
        clear_restricted_tool_plugins()


def test_runtime_tool_catalog_surfaces_restricted_plugin_install_state() -> None:
    clear_restricted_tool_plugins()
    manager = RestrictedToolPluginManager()

    def echo_tool(payload, context):
        return {"ok": True, "text": payload["text"], "plugin_id": context.plugin_id}

    plugin = RestrictedToolPlugin(
        plugin_id="notes",
        tools=(
            RestrictedPluginTool(
                tool_id="echo",
                description="Echo text through a managed restricted test plugin.",
                properties={"text": {"type": "string"}},
                required=("text",),
                risk_level="medium",
                execute=echo_tool,
            ),
        ),
        skill_docs="Use this plugin when an Agent Desk note needs a short echo.",
    )

    try:
        manager.install(plugin, enabled=False)
        disabled_catalog = runtime_tool_catalog_snapshot(
            plugin_states=manager.list_installed()
        )
        disabled_plugins = {
            plugin.plugin_id: plugin for plugin in disabled_catalog.plugins
        }

        assert "plugin.notes.echo" not in {
            tool.tool_name for tool in disabled_catalog.tools
        }
        assert disabled_plugins["notes"].enabled is False
        assert disabled_plugins["notes"].tool_names == ["plugin.notes.echo"]
        assert disabled_plugins["notes"].tools == []
        assert "Agent Desk note" in disabled_plugins["notes"].skill_docs

        manager.enable("notes")
        enabled_catalog = runtime_tool_catalog_snapshot(
            plugin_states=manager.list_installed()
        )
        enabled_plugins = {
            plugin.plugin_id: plugin for plugin in enabled_catalog.plugins
        }

        assert "plugin.notes.echo" in {
            tool.tool_name for tool in enabled_catalog.tools
        }
        assert enabled_plugins["notes"].enabled is True
        assert enabled_plugins["notes"].tools[0].tool_name == "plugin.notes.echo"
        assert enabled_plugins["notes"].tools[0].risk_level == "medium"

        manager.uninstall("notes")
        uninstalled_catalog = runtime_tool_catalog_snapshot(
            plugin_states=manager.list_installed()
        )
        assert uninstalled_catalog.plugins == []
        assert "plugin.notes.echo" not in {
            tool.tool_name for tool in uninstalled_catalog.tools
        }
    finally:
        clear_restricted_tool_plugins()


def test_agent_desk_snapshot_json_shape_is_stable() -> None:
    snapshot = AgentDeskSnapshot(
        agent_id="agent-1",
        root_path="/workspace/agent-1",
        items=[
            AgentDeskItemSnapshot(
                path="desk-notes.md",
                name="desk-notes.md",
                kind="note",
                size_bytes=12,
                mime_type="text/markdown",
                preview_text="# Notes",
                updated_at="2026-06-22T00:00:00Z",
            ),
            AgentDeskItemSnapshot(
                path="inputs/brief.md",
                name="brief.md",
                kind="file",
                size_bytes=20,
                mime_type="text/markdown",
                preview_text="Brief",
                updated_at="2026-06-22T00:00:01Z",
            ),
        ],
        updated_at="2026-06-22T00:00:02Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "agent_id",
        "root_path",
        "notes_path",
        "metadata_path",
        "items",
        "updated_at",
    ]
    assert payload["notes_path"] == "desk-notes.md"
    assert payload["metadata_path"] == ".yachiyo-desk.json"
    assert payload["items"][0]["kind"] == "note"
    assert payload["items"][1]["path"] == "inputs/brief.md"
    with pytest.raises(ValidationError):
        AgentDeskSnapshot(agent_id="agent-1", root_path="/workspace", unknown=True)
    with pytest.raises(ValidationError):
        SaveAgentDeskNoteRequest(content="note", unknown=True)
    with pytest.raises(ValidationError):
        SaveAgentDeskFileRequest(path="brief.md", content="body", unknown=True)
    with pytest.raises(ValidationError):
        AgentDeskFileEventRequest(path="brief.md", unknown=True)
    file_event = _json(
        AgentDeskFileEventRequest(
            path="inputs/brief.md",
            event_type="modified",
            delay_seconds=0,
        )
    )
    assert file_event == {
        "path": "inputs/brief.md",
        "event_type": "modified",
        "delay_seconds": 0,
    }


def test_chat_runnable_catalog_snapshot_json_shape_is_stable() -> None:
    snapshot = ChatRunnableCatalogSnapshot(
        agents=[
            ChatRunnableSnapshot(
                runnable_id="agent-1",
                agent_id="agent-1",
                kind="agent",
                name="Planner",
                tool_capabilities=["workspace.read", "workspace.write_patch"],
                approval_required_tools=["workspace.write_patch"],
            )
        ],
        workflows=[
            ChatRunnableSnapshot(
                runnable_id="workflow-1",
                workflow_id="workflow-1",
                kind="workflow",
                name="Review workflow",
                output_contract="workflow",
                participants=[
                    ChatRunnableParticipantSnapshot(
                        runnable_id="agent-1",
                        agent_id="agent-1",
                        kind="agent",
                        name="Planner",
                    )
                ],
            )
        ],
    )

    payload = _json(snapshot)

    assert list(payload) == ["agents", "workflows"]
    assert list(payload["agents"][0]) == [
        "runnable_id",
        "agent_id",
        "workflow_id",
        "kind",
        "name",
        "nickname",
        "description",
        "avatar_url",
        "category",
        "output_contract",
        "enabled",
        "tool_capabilities",
        "approval_required_tools",
        "participants",
    ]
    assert payload["agents"][0]["agent_id"] == "agent-1"
    assert payload["agents"][0]["tool_capabilities"] == ["workspace.read", "workspace.write_patch"]
    assert payload["agents"][0]["approval_required_tools"] == ["workspace.write_patch"]
    assert payload["workflows"][0]["workflow_id"] == "workflow-1"
    assert payload["workflows"][0]["participants"][0]["agent_id"] == "agent-1"
    assert "tool_policy" not in payload["agents"][0]
    assert "nodes" not in payload["workflows"][0]
    assert "edges" not in payload["workflows"][0]


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
        rerun_of_run_id="original-run-1",
        rerun_of_kind="agent_run",
        rerun_of_status="completed",
        rerun_of_runnable_id="agent-1",
        rerun_of_runnable_name="Planner",
        rerun_original_created_at="2026-06-13T00:00:00Z",
        rerun_original_updated_at="2026-06-13T00:00:03Z",
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
        memory_traces=[
            MemoryTraceSnapshot(
                trace_id="memory-trace-1",
                run_id="run-1",
                event_type="memory.retrieved",
                title="Memory retrieved",
            )
        ],
        skill_traces=[
            SkillTraceSnapshot(
                trace_id="skill-trace-1",
                run_id="run-1",
                event_type="skill.selected",
                title="Demo Skill",
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
        children=[
            RunTimelineChildSnapshot(
                run_id="child-run-1",
                status="completed",
                kind="agent_run",
                parent_run_id="run-1",
                group_run_id="group-run-1",
                run_group_id="group-run-1",
                workflow_run_id="workflow-run-1",
                workflow_node_id="review",
                workflow_node_label="Review",
                agent_id="agent-2",
                workflow_id="workflow-1",
            )
        ],
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
        "rerun_of_run_id",
        "rerun_of_kind",
        "rerun_of_status",
        "rerun_of_runnable_id",
        "rerun_of_runnable_name",
        "rerun_original_created_at",
        "rerun_original_updated_at",
        "events",
        "tool_calls",
        "memory_traces",
        "skill_traces",
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
    assert payload["rerun_of_run_id"] == "original-run-1"
    assert payload["tool_calls"][0]["tool_name"] == "workspace.read"
    assert payload["memory_traces"][0]["event_type"] == "memory.retrieved"
    assert payload["skill_traces"][0]["event_type"] == "skill.selected"
    assert payload["children"][0]["run_id"] == "child-run-1"
    assert payload["children"][0]["parent_run_id"] == "run-1"
    assert payload["children"][0]["group_run_id"] == "group-run-1"
    assert payload["children"][0]["workflow_node_id"] == "review"


def test_tool_call_snapshot_keeps_runtime_trace_fields() -> None:
    snapshot = ToolCallSnapshot(
        tool_call_id="tool-1",
        run_id="run-1",
        source_run_id="child-run-1",
        source_runnable_id="agent-1",
        source_runnable_name="Planner",
        workflow_id="workflow-1",
        workflow_run_id="workflow-run-1",
        workflow_node_id="read",
        workflow_node_label="Read Files",
        group_id="group-1",
        group_run_id="group-run-1",
        tool_name="workspace.read",
        status="completed",
        risk_level="low",
        input_preview={"path": "README.md"},
        output_preview={"ok": True},
        approval_id="approval-1",
        started_at="2026-06-14T00:00:00Z",
        completed_at="2026-06-14T00:00:01Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "tool_call_id",
        "run_id",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
        "tool_name",
        "status",
        "risk_level",
        "input_preview",
        "output_preview",
        "foreground_lock_busy",
        "foreground_lock_holder",
        "approval_id",
        "started_at",
        "completed_at",
    ]
    assert payload["foreground_lock_busy"] is False
    assert payload["foreground_lock_holder"] is None
    assert payload["source_runnable_name"] == "Planner"
    assert payload["workflow_node_id"] == "read"
    assert payload["group_run_id"] == "group-run-1"


def test_memory_trace_snapshot_keeps_runtime_trace_fields() -> None:
    snapshot = MemoryTraceSnapshot(
        trace_id="trace-1",
        run_id="run-1",
        event_id="event-1",
        sequence=3,
        event_type="memory.retrieved",
        status="completed",
        action="retrieved",
        memory_id="memory-1",
        memory_kind="preference",
        memory_scope="global",
        count=1,
        source_run_id="child-run-1",
        source_runnable_id="agent-1",
        source_runnable_name="Researcher",
        workflow_id="workflow-1",
        workflow_run_id="workflow-run-1",
        workflow_node_id="retrieve",
        workflow_node_label="Retrieve Context",
        group_id="group-1",
        group_run_id="group-run-1",
        title="Memory retrieved",
        detail="retrieved · preference · global",
        payload_preview={"count": 1},
        created_at="2026-06-14T00:00:00Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "trace_id",
        "run_id",
        "event_id",
        "sequence",
        "event_type",
        "status",
        "action",
        "memory_id",
        "memory_kind",
        "memory_scope",
        "count",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
        "title",
        "detail",
        "payload_preview",
        "created_at",
    ]
    assert payload["memory_id"] == "memory-1"
    assert payload["workflow_node_id"] == "retrieve"
    assert payload["group_run_id"] == "group-run-1"


def test_skill_trace_snapshot_keeps_runtime_trace_fields() -> None:
    snapshot = SkillTraceSnapshot(
        trace_id="trace-1",
        run_id="run-1",
        event_id="event-1",
        sequence=4,
        event_type="skill.dispatch.read",
        status="completed",
        skill_id="skill-1",
        skill_name="Demo Skill",
        source_ref="skills/demo/SKILL.md",
        source_type="local_dir",
        tool_name="skill.read",
        source_run_id="child-run-1",
        source_runnable_id="agent-1",
        source_runnable_name="Researcher",
        workflow_id="workflow-1",
        workflow_run_id="workflow-run-1",
        workflow_node_id="read-skill",
        workflow_node_label="Read Skill",
        group_id="group-1",
        group_run_id="group-run-1",
        title="Demo Skill",
        detail="Read project docs · skills/demo/SKILL.md · local_dir",
        payload_preview={"tool": "skill.read"},
        created_at="2026-06-14T00:00:01Z",
    )

    payload = _json(snapshot)

    assert list(payload) == [
        "trace_id",
        "run_id",
        "event_id",
        "sequence",
        "event_type",
        "status",
        "skill_id",
        "skill_name",
        "source_ref",
        "source_type",
        "tool_name",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
        "title",
        "detail",
        "payload_preview",
        "created_at",
    ]
    assert payload["skill_id"] == "skill-1"
    assert payload["source_ref"] == "skills/demo/SKILL.md"
    assert payload["workflow_node_id"] == "read-skill"


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
            "sensitivity": "public",
            "created_at": "2026-06-14T00:00:00Z",
        }
    )

    assert event.event_type == "memory.write.add"
    assert event.run_id == "run-1"
    assert event.sequence == 7
    assert event.visibility == "internal"
    assert event.sensitivity == "public"
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
        tool_calls=[
            ToolCallSnapshot(
                tool_call_id="tool-1",
                run_id="agent-run-1",
                source_runnable_id="agent-1",
                group_run_id="group-run-1",
                tool_name="workspace.read",
                status="completed",
            )
        ],
        memory_traces=[
            MemoryTraceSnapshot(
                trace_id="memory-trace-1",
                run_id="agent-run-1",
                event_type="memory.retrieved",
                source_runnable_id="agent-1",
                group_run_id="group-run-1",
                title="Memory retrieved",
            )
        ],
        skill_traces=[
            SkillTraceSnapshot(
                trace_id="skill-trace-1",
                run_id="agent-run-1",
                event_type="skill.selected",
                source_runnable_id="agent-1",
                group_run_id="group-run-1",
                title="Skill selected",
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
    assert _json(group_run)["tool_calls"][0]["tool_name"] == "workspace.read"
    assert _json(group_run)["memory_traces"][0]["event_type"] == "memory.retrieved"
    assert _json(group_run)["skill_traces"][0]["event_type"] == "skill.selected"
    assert _json(workflow)["default_input_schema"] == {"type": "object"}
    assert _json(workflow_run)["run_id"] == "workflow-run-1"
    assert _json(workflow_run)["workflow_id"] == "workflow-1"
    assert _json(workflow_run)["events"][0]["event_type"] == "workflow.node.started"
    assert _json(workflow_run)["children"][0]["run_id"] == "agent-run-1"


def test_group_run_snapshot_rolls_child_debug_state_into_participants() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-1",
            "group_id": "group-1",
            "title": "Desktop team",
            "status": "approval_required",
            "objective": "Open Music and report back",
            "participants": [
                {"agent_id": "agent-1", "name": "Music Agent", "role": "operator"},
                {"agent_id": "agent-2", "name": "Reviewer", "role": "reviewer"},
            ],
            "runs": [
                {
                    "run_id": "run-1",
                    "agent_id": "agent-1",
                    "status": "approval_required",
                    "user_goal": "Play a song",
                    "tool_calls": [
                        {
                            "tool_call_id": "tool-1",
                            "tool_name": "media.apple_music_play",
                            "status": "completed",
                            "source_runnable_id": "agent-1",
                        }
                    ],
                    "pending_approval": {
                        "approval_id": "approval-1",
                        "title": "Approve message send",
                        "tool_name": "desktop.type_text",
                        "status": "pending",
                    },
                    "artifacts": [
                        {
                            "artifact_id": "artifact-1",
                            "title": "Music search",
                            "kind": "screenshot",
                            "path": "music.png",
                        }
                    ],
                }
            ],
        }
    )

    music_agent = group_run.participants[0]
    reviewer = group_run.participants[1]
    assert music_agent.run_id == "run-1"
    assert music_agent.run_status == "approval_required"
    assert music_agent.tool_calls[0].tool_name == "media.apple_music_play"
    assert music_agent.pending_approvals[0].approval_id == "approval-1"
    assert music_agent.artifacts[0].path == "music.png"
    assert reviewer.tool_calls == []
    assert [approval.approval_id for approval in group_run.pending_approvals] == ["approval-1"]
    assert [artifact.path for artifact in group_run.shared_artifacts] == ["music.png"]


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
