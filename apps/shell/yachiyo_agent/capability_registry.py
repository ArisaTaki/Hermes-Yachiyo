"""Capability registry for the next Yachiyo task planner.

The registry describes what the runtime can do. Apps are parameters of
desktop capabilities, not the top-level planning primitive.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import CapabilitySnapshot


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    title: str
    category: str
    description: str
    tools: tuple[str, ...] = ()
    risk_level: str = "low"
    approval_required: bool = False
    discovery_actions: tuple[str, ...] = ()
    execution_actions: tuple[str, ...] = ()
    output_kinds: tuple[str, ...] = ()

    def to_snapshot(self, allowed_tools: Iterable[str] | None = None) -> CapabilitySnapshot:
        allowed_provided = allowed_tools is not None
        allowed = {str(tool or "").strip() for tool in allowed_tools or [] if str(tool or "").strip()}
        tools = [*self.tools]
        for tool in _dynamic_tools_for_capability(self.capability_id, allowed if allowed_provided else set()):
            if tool not in tools:
                tools.append(tool)
        available_tools = [tool for tool in tools if not allowed_provided or tool in allowed]
        missing_tools = [tool for tool in tools if allowed_provided and tool not in allowed]
        return CapabilitySnapshot(
            capability_id=self.capability_id,
            title=self.title,
            category=self.category,
            description=self.description,
            tools=tools,
            available_tools=available_tools,
            missing_tools=missing_tools,
            risk_level=self.risk_level,
            approval_required=self.approval_required,
            discovery_actions=list(self.discovery_actions),
            execution_actions=list(self.execution_actions),
            output_kinds=list(self.output_kinds),
        )


CAPABILITY_DEFINITIONS: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        capability_id="desktop.app_discovery",
        title="Discover Desktop Apps",
        category="desktop",
        description="Inspect running apps, windows, foreground state, and available UI.",
        tools=(
            "desktop.list_apps",
            "desktop.running_apps",
            "desktop.active_window",
            "desktop.permissions",
            "desktop.windows",
            "desktop.ui_elements",
            "screen.capture",
        ),
        discovery_actions=("list_apps", "list_windows", "capture", "read_ui", "diagnose_permissions"),
        output_kinds=("desktop_state", "screenshot"),
    ),
    CapabilityDefinition(
        capability_id="desktop.app_control",
        title="Open And Focus Desktop Apps",
        category="desktop",
        description="Open, focus, show, hide, minimize, close, or quit local desktop apps and foreground windows.",
        tools=(
            "app.open",
            "app.focus",
            "app.status",
            "app.show",
            "app.hide",
            "app.minimize",
            "app.quit",
            "desktop.hide_app",
            "desktop.show_all_apps",
            "desktop.minimize_window",
            "desktop.close_window",
            "desktop.quit_app",
        ),
        risk_level="medium",
        approval_required=True,
        discovery_actions=("resolve_app_name",),
        execution_actions=("open_app", "focus_app", "manage_app", "manage_foreground"),
        output_kinds=("desktop_state",),
    ),
    CapabilityDefinition(
        capability_id="desktop.ui_operation",
        title="Operate Desktop UI",
        category="desktop",
        description="Click, type, scroll, press shortcuts, and verify foreground UI state.",
        tools=(
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
            "desktop.safe_shortcut",
            "desktop.safe_key",
            "desktop.safe_type_text",
            "desktop.safe_click",
            "desktop.safe_scroll",
            "desktop.search_submit",
            "desktop.click_ui_element",
            "desktop.type_into_ui_element",
            "desktop.hotkey",
            "desktop.submit_foreground",
            "desktop.type_text",
            "desktop.click",
        ),
        risk_level="medium",
        approval_required=True,
        discovery_actions=("read_ui", "capture"),
        execution_actions=("click", "type", "shortcut", "scroll", "submit", "verify"),
        output_kinds=("desktop_state",),
    ),
    CapabilityDefinition(
        capability_id="file.workspace_read",
        title="Read Workspace Files",
        category="file",
        description="List and read files inside the configured workspace.",
        tools=("workspace.list", "workspace.read"),
        discovery_actions=("list_files", "read_file"),
        output_kinds=("text", "table", "source_file"),
    ),
    CapabilityDefinition(
        capability_id="file.desktop_access",
        title="Open Or Reveal Local Files",
        category="file",
        description="Open safe local paths or reveal them in Finder through desktop file tools.",
        tools=("desktop.open_path", "desktop.reveal_path"),
        execution_actions=("open_path", "reveal_path"),
        output_kinds=("desktop_state",),
    ),
    CapabilityDefinition(
        capability_id="file.organization",
        title="Organize Files",
        category="file",
        description="Plan and apply explicit file organization, renaming, moving, or cleanup work.",
        tools=("workspace.list", "desktop.reveal_path", "desktop.open_path", "terminal.run", "artifact.write"),
        risk_level="high",
        approval_required=True,
        discovery_actions=("list_files", "inspect_paths"),
        execution_actions=("move_files", "rename_files", "archive_files", "cleanup_files"),
        output_kinds=("file_plan", "desktop_state", "report"),
    ),
    CapabilityDefinition(
        capability_id="terminal.execution",
        title="Run Local Commands",
        category="terminal",
        description="Run approved commands in the Agent workdir for analysis, scripts, or diagnostics.",
        tools=("terminal.run",),
        risk_level="high",
        approval_required=True,
        execution_actions=("run_command", "run_python"),
        output_kinds=("terminal_output",),
    ),
    CapabilityDefinition(
        capability_id="data.analysis",
        title="Analyze Data",
        category="data",
        description="Inspect structured data, compute summaries, and generate charts or tables.",
        tools=("data.analyze", "workspace.list", "workspace.read", "terminal.run", "artifact.write"),
        risk_level="medium",
        approval_required=True,
        discovery_actions=("find_dataset", "inspect_schema"),
        execution_actions=("analyze_data_file", "run_python_analysis", "summarize_data"),
        output_kinds=("markdown", "csv", "chart", "json"),
    ),
    CapabilityDefinition(
        capability_id="artifact.write",
        title="Write Run Artifacts",
        category="artifact",
        description="Write markdown, text, report, or generated output artifacts for the current run.",
        tools=("artifact.write",),
        execution_actions=("write_artifact",),
        output_kinds=("markdown", "text", "report"),
    ),
    CapabilityDefinition(
        capability_id="browser.research",
        title="Research Web Pages",
        category="browser",
        description="Open, read, screenshot, click, or type in browser pages.",
        tools=(
            "browser.open_url",
            "browser.open_url_and_extract_text",
            "browser.open_url_and_screenshot",
            "browser.current_page",
            "browser.extract_text",
            "browser.screenshot",
            "browser.click",
            "browser.type_text",
        ),
        risk_level="medium",
        approval_required=True,
        discovery_actions=("open_url", "extract_text", "screenshot"),
        execution_actions=("click", "type"),
        output_kinds=("web_text", "screenshot", "report"),
    ),
    CapabilityDefinition(
        capability_id="schedule.reminder",
        title="Create Reminders And Calendar Events",
        category="schedule",
        description="Create reminders, calendar events, or scheduled future tasks.",
        tools=("reminders.create", "calendar.create_event", "future_task.schedule"),
        risk_level="medium",
        approval_required=True,
        execution_actions=("create_reminder", "create_event", "schedule_task"),
        output_kinds=("schedule_item",),
    ),
    CapabilityDefinition(
        capability_id="information.capture",
        title="Capture Information",
        category="capture",
        description="Capture explicit text or inspected context into a local note.",
        tools=(
            "notes.create",
            "artifact.write",
            "clipboard.read",
            "desktop.safe_shortcut",
            "browser.current_page",
            "browser.extract_text",
            "desktop.ui_elements",
            "screen.capture",
        ),
        discovery_actions=("read_clipboard", "copy_selection", "extract_text", "read_ui"),
        execution_actions=("create_note", "write_artifact"),
        output_kinds=("note", "text", "artifact"),
    ),
    CapabilityDefinition(
        capability_id="clipboard.read_write",
        title="Read And Write Clipboard",
        category="clipboard",
        description="Read explicitly requested clipboard contents, write explicit text, or copy the current selection.",
        tools=("clipboard.read", "clipboard.write", "desktop.safe_shortcut"),
        risk_level="low",
        discovery_actions=("read_clipboard",),
        execution_actions=("write_clipboard", "copy_selection"),
        output_kinds=("text", "clipboard_state"),
    ),
    CapabilityDefinition(
        capability_id="media.playback",
        title="Control Media Playback",
        category="media",
        description="Open music apps, start playback, search Apple Music, and control playback.",
        tools=(
            "media.apple_music_play",
            "media.apple_music_status",
            "media.apple_music_open_and_play",
            "media.apple_music_control",
            "media.music_app_open_and_play",
            "media.music_app_control",
            "media.system_control",
        ),
        discovery_actions=("read_playback_status",),
        execution_actions=("play", "pause", "next", "previous", "open_music_app"),
        output_kinds=("media_state",),
    ),
    CapabilityDefinition(
        capability_id="system.control",
        title="Control System State",
        category="system",
        description="Perform explicit low-risk system controls such as opening settings, volume, brightness, display sleep, or screen saver.",
        tools=(
            "system.settings_open",
            "system.volume",
            "system.brightness",
            "system.display_sleep",
            "system.screen_saver_start",
        ),
        discovery_actions=("read_system_state",),
        execution_actions=("open_settings", "set_volume", "adjust_brightness", "sleep_display", "start_screen_saver"),
        output_kinds=("system_state",),
    ),
    CapabilityDefinition(
        capability_id="communication.compose",
        title="Compose Communication",
        category="communication",
        description="Draft messages or email through available apps, UI tools, or artifacts.",
        tools=(
            "app.open_and_safe_shortcut",
            "app.focus_and_safe_shortcut",
            "app.open_and_type_into_ui_element",
            "app.focus_and_type_into_ui_element",
            "app.open_and_safe_type_text",
            "app.focus_and_safe_type_text",
            "desktop.type_into_ui_element",
            "desktop.safe_type_text",
            "desktop.search_submit",
            "desktop.submit_foreground",
            "artifact.write",
        ),
        risk_level="medium",
        approval_required=True,
        discovery_actions=("resolve_recipient", "read_ui"),
        execution_actions=("draft_message", "prepare_send"),
        output_kinds=("message_draft", "desktop_state", "text"),
    ),
    CapabilityDefinition(
        capability_id="workflow.orchestration",
        title="Run Workflow Orchestration",
        category="workflow",
        description="Use Agent Studio workflows, approvals, branches, and artifacts for multi-step work.",
        tools=("workflow.run",),
        risk_level="medium",
        approval_required=True,
        discovery_actions=("select_workflow",),
        execution_actions=("start_workflow", "resume_workflow"),
        output_kinds=("workflow_run", "artifact"),
    ),
    CapabilityDefinition(
        capability_id="group.multi_agent",
        title="Coordinate Multiple Agents",
        category="group",
        description="Coordinate multi-agent group runs for parallel or role-based tasks.",
        tools=("group.run",),
        risk_level="medium",
        approval_required=True,
        discovery_actions=("select_group",),
        execution_actions=("start_group_run", "merge_artifacts"),
        output_kinds=("group_run", "artifact"),
    ),
)


_DYNAMIC_CAPABILITY_TOOL_PREFIXES: dict[str, tuple[str, ...]] = {
    "artifact.write": ("artifact.",),
    "browser.research": ("browser.",),
    "media.playback": ("media.",),
    "system.control": ("system.",),
    "information.capture": ("notes.",),
    "communication.compose": ("communication.", "mail.", "messages.", "email."),
    "clipboard.read_write": ("clipboard.",),
    "terminal.execution": ("terminal.",),
    "file.desktop_access": ("file.",),
    "file.organization": ("file.",),
    "workflow.orchestration": ("workflow.",),
    "group.multi_agent": ("group.",),
}

_DYNAMIC_CAPABILITY_TOOL_NAMES: dict[str, tuple[str, ...]] = {
    "data.analysis": ("data.analyze", "workspace.list", "workspace.read", "terminal.run", "artifact.write"),
    "file.workspace_read": ("workspace.list", "workspace.read"),
    "file.desktop_access": ("desktop.open_path", "desktop.reveal_path"),
    "file.organization": ("workspace.list", "desktop.reveal_path", "desktop.open_path", "terminal.run", "artifact.write"),
    "schedule.reminder": ("reminders.create", "calendar.create_event", "future_task.schedule"),
    "information.capture": (
        "notes.create",
        "clipboard.read",
        "desktop.safe_shortcut",
        "browser.current_page",
        "browser.extract_text",
        "desktop.ui_elements",
        "screen.capture",
    ),
    "clipboard.read_write": ("clipboard.read", "clipboard.write", "desktop.safe_shortcut"),
    "system.control": ("system.volume", "system.brightness", "system.display_sleep", "system.screen_saver_start"),
}


def capability_definitions() -> tuple[CapabilityDefinition, ...]:
    return CAPABILITY_DEFINITIONS


def capability_definition_map() -> dict[str, CapabilityDefinition]:
    return {definition.capability_id: definition for definition in CAPABILITY_DEFINITIONS}


def _dynamic_tools_for_capability(capability_id: str, allowed_tools: Iterable[str]) -> list[str]:
    allowed = sorted({str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()})
    if not allowed:
        return []
    exact = set(_DYNAMIC_CAPABILITY_TOOL_NAMES.get(capability_id, ()))
    prefixes = _DYNAMIC_CAPABILITY_TOOL_PREFIXES.get(capability_id, ())
    return [
        tool
        for tool in allowed
        if tool in exact or any(tool.startswith(prefix) for prefix in prefixes)
    ]


def capability_snapshots(
    *,
    allowed_tools: Iterable[str] | None = None,
    capability_ids: Iterable[str] | None = None,
) -> list[CapabilitySnapshot]:
    ids = {str(value or "").strip() for value in capability_ids or [] if str(value or "").strip()}
    return [
        definition.to_snapshot(allowed_tools)
        for definition in CAPABILITY_DEFINITIONS
        if not ids or definition.capability_id in ids
    ]
