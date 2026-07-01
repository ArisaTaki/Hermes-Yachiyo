"""Studio-facing catalog snapshots for runtime tools."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

from apps.shell.agent.tools.policy import (
    HIGH_RISK_AGENT_TOOLS,
    LOW_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    TOOL_DESCRIPTORS,
    TOOL_FUNCTION_NAMES,
)
from apps.shell.agent.tools.plugins import list_restricted_plugin_tools, restricted_plugin_tool_risk

from .contracts import (
    DesktopExecutionCapabilitySnapshot,
    RestrictedPluginToolSnapshot,
    RestrictedToolPluginSnapshot,
    ToolCatalogItemSnapshot,
    ToolCatalogSnapshot,
)
from .policy import (
    DESKTOP_CAPABILITY_DIAGNOSTIC_ROUTES,
    DESKTOP_CAPABILITY_TOOLS,
    desktop_tool_blocking_conditions,
    desktop_tool_missing_permissions,
    desktop_execution_capability_snapshots,
    desktop_tool_risk_level,
)


def runtime_tool_catalog_snapshot(
    *,
    registered_tools: Iterable[str] | None = None,
    platform_name: str | None = None,
    missing_permissions: Mapping[str, Iterable[str]] | None = None,
    blocking_conditions: Mapping[str, Iterable[str]] | None = None,
    plugin_states: Iterable[Any] | None = None,
) -> ToolCatalogSnapshot:
    """Build the public Studio tool catalog from runtime descriptors."""

    clean_registered = _clean_tool_names(registered_tools or TOOL_DESCRIPTORS)
    capabilities = _capability_snapshots(
        registered_tools=clean_registered,
        platform_name=platform_name,
        missing_permissions=missing_permissions,
        blocking_conditions=blocking_conditions,
    )
    capability_payloads = {
        capability_id: snapshot.model_dump(mode="json")
        for capability_id, snapshot in capabilities.items()
    }
    tools = [
        _catalog_item_from_descriptor(
            tool_name,
            capabilities=capability_payloads,
            missing_permissions=missing_permissions or {},
            blocking_conditions=blocking_conditions or {},
        )
        for tool_name in sorted(clean_registered)
        if tool_name in TOOL_DESCRIPTORS
    ]
    return ToolCatalogSnapshot(
        tools=tools,
        capabilities=capabilities,
        plugins=_restricted_plugin_snapshots(plugin_states),
    )


def tool_catalog_snapshot_from_payload(payload: Any) -> ToolCatalogSnapshot:
    if isinstance(payload, ToolCatalogSnapshot):
        return payload
    if not isinstance(payload, Mapping):
        return runtime_tool_catalog_snapshot()

    raw_tools = payload.get("tools")
    if isinstance(raw_tools, Iterable) and not isinstance(raw_tools, (str, bytes, Mapping)):
        tools = [
            _catalog_item_from_payload(item)
            for item in raw_tools
            if isinstance(item, Mapping)
        ]
    else:
        tools = runtime_tool_catalog_snapshot().tools

    raw_capabilities = payload.get("capabilities")
    capabilities: dict[str, DesktopExecutionCapabilitySnapshot] = {}
    if isinstance(raw_capabilities, Mapping):
        for capability_id, capability_payload in raw_capabilities.items():
            if not isinstance(capability_payload, Mapping):
                continue
            capabilities[str(capability_id)] = DesktopExecutionCapabilitySnapshot.model_validate(
                dict(capability_payload)
            )

    return ToolCatalogSnapshot(
        tools=tools,
        capabilities=capabilities,
        plugins=_restricted_plugin_snapshots_from_payload(payload.get("plugins")),
        source=str(payload.get("source") or "runtime"),
    )


def restricted_tool_plugin_snapshot_from_payload(
    payload: Any,
) -> RestrictedToolPluginSnapshot:
    if isinstance(payload, RestrictedToolPluginSnapshot):
        return payload
    if isinstance(payload, Mapping):
        snapshots = _restricted_plugin_snapshots_from_payload([payload])
        if snapshots:
            return snapshots[0]
    return RestrictedToolPluginSnapshot(plugin_id="")


def _catalog_item_from_descriptor(
    tool_name: str,
    *,
    capabilities: Mapping[str, Mapping[str, Any]],
    missing_permissions: Mapping[str, Iterable[str]],
    blocking_conditions: Mapping[str, Iterable[str]],
) -> ToolCatalogItemSnapshot:
    descriptor = TOOL_DESCRIPTORS[tool_name]
    model_tool_schema = descriptor.to_model_tool_schema()
    capability_id = _capability_id_for_tool(tool_name)
    return ToolCatalogItemSnapshot(
        tool_name=tool_name,
        function_name=descriptor.function_name,
        description=descriptor.description,
        capability_id=capability_id,
        risk_level=_risk_level_for_tool(tool_name),
        approval_required=_approval_required_for_tool(tool_name),
        input_schema=deepcopy(model_tool_schema["function"]["parameters"]),
        model_tool_schema=deepcopy(model_tool_schema),
        missing_permissions=_missing_permissions_for_tool(
            tool_name,
            capability_id=capability_id,
            capabilities=capabilities,
            missing_permissions=missing_permissions,
        ),
        blocking_conditions=_blocking_conditions_for_tool(
            tool_name,
            capability_id=capability_id,
            capabilities=capabilities,
            blocking_conditions=blocking_conditions,
        ),
        fallback_notes=_fallback_notes_for_tool(tool_name),
        diagnostic_route=_diagnostic_route_for_tool(capability_id),
        source=_source_for_tool(tool_name),
    )


def _catalog_item_from_payload(payload: Mapping[str, Any]) -> ToolCatalogItemSnapshot:
    tool_name = str(payload.get("tool_name") or payload.get("name") or "").strip()
    descriptor = TOOL_DESCRIPTORS.get(tool_name)
    model_tool_schema = (
        descriptor.to_model_tool_schema()
        if descriptor is not None
        else dict(payload.get("model_tool_schema") or {})
    )
    input_schema = payload.get("input_schema")
    if not isinstance(input_schema, Mapping):
        function_schema = model_tool_schema.get("function") if isinstance(model_tool_schema, Mapping) else None
        input_schema = (
            function_schema.get("parameters")
            if isinstance(function_schema, Mapping)
            and isinstance(function_schema.get("parameters"), Mapping)
            else {}
        )
    return ToolCatalogItemSnapshot(
        tool_name=tool_name,
        function_name=str(
            payload.get("function_name")
            or TOOL_FUNCTION_NAMES.get(tool_name)
            or ""
        ),
        description=str(payload.get("description") or (descriptor.description if descriptor else "")),
        capability_id=_optional_string(payload.get("capability_id")),
        risk_level=_optional_string(payload.get("risk_level")),
        approval_required=bool(payload.get("approval_required", _approval_required_for_tool(tool_name))),
        input_schema=dict(input_schema),
        model_tool_schema=dict(model_tool_schema),
        missing_permissions=_string_list(payload.get("missing_permissions")),
        blocking_conditions=_string_list(payload.get("blocking_conditions")),
        fallback_notes=_string_list(payload.get("fallback_notes")),
        diagnostic_route=_optional_string(payload.get("diagnostic_route")),
        source=str(payload.get("source") or "runtime"),
    )


def _capability_snapshots(
    *,
    registered_tools: Iterable[str],
    platform_name: str | None,
    missing_permissions: Mapping[str, Iterable[str]] | None,
    blocking_conditions: Mapping[str, Iterable[str]] | None,
) -> dict[str, DesktopExecutionCapabilitySnapshot]:
    payload = desktop_execution_capability_snapshots(
        registered_tools=registered_tools,
        platform_name=platform_name,
        missing_permissions=missing_permissions,
        blocking_conditions=blocking_conditions,
    )
    return {
        capability_id: DesktopExecutionCapabilitySnapshot.model_validate(snapshot)
        for capability_id, snapshot in payload.items()
        if isinstance(snapshot, Mapping)
    }


def _clean_tool_names(values: Iterable[str]) -> set[str]:
    return {str(value or "").strip() for value in values if str(value or "").strip()}


def _capability_id_for_tool(tool_name: str) -> str | None:
    for capability_id, tools in DESKTOP_CAPABILITY_TOOLS.items():
        if capability_id == "desktop_execution":
            continue
        if tool_name in tools:
            return capability_id
    if tool_name in DESKTOP_CAPABILITY_TOOLS["desktop_execution"]:
        return "desktop_execution"
    if tool_name.startswith("memory."):
        return "memory"
    if tool_name.startswith("future_task."):
        return "future_task"
    if tool_name.startswith("workspace."):
        return "workspace"
    if tool_name in {"fs.find_files", "fs.read_file", "file.search", "file.read"}:
        return "workspace"
    if tool_name.startswith("fs."):
        return "file.organization"
    if tool_name.startswith("file."):
        return "file.organization"
    if tool_name.startswith("browser."):
        return "browser_control"
    if tool_name.startswith("terminal."):
        return "terminal"
    if tool_name.startswith("python."):
        return "terminal"
    if tool_name.startswith("data."):
        return "data"
    if tool_name.startswith("skill."):
        return "skill"
    if tool_name.startswith("artifact."):
        return "artifact"
    if tool_name.startswith("plugin."):
        return "plugin_tool"
    return None


def _risk_level_for_tool(tool_name: str) -> str | None:
    if tool_name in HIGH_RISK_AGENT_TOOLS:
        return "high"
    plugin_risk = restricted_plugin_tool_risk(tool_name)
    if plugin_risk is not None:
        return plugin_risk
    desktop_risk = desktop_tool_risk_level(tool_name)
    if desktop_risk is not None:
        return desktop_risk
    if tool_name in LOW_RISK_BROWSER_TOOL_NAMES:
        return "low"
    if tool_name in MEDIUM_RISK_BROWSER_TOOL_NAMES:
        return "medium"
    if tool_name in {"fs.move_file", "fs.rename_file", "fs.delete_file", "fs.write_file"}:
        return "high"
    if tool_name == "python.run":
        return "high"
    if tool_name in {
        "workspace.list",
        "workspace.read",
        "fs.find_files",
        "fs.read_file",
        "file.search",
        "file.read",
        "artifact.write",
        "data.analyze",
        "browser.search",
        "browser.open",
        "browser.extract",
        "skill.read",
    }:
        return "low"
    if tool_name.startswith("memory.") or tool_name.startswith("future_task."):
        return "low"
    return None


def _approval_required_for_tool(tool_name: str) -> bool:
    return (
        tool_name in HIGH_RISK_AGENT_TOOLS
        or tool_name == "python.run"
        or tool_name in {"fs.move_file", "fs.rename_file", "fs.delete_file", "fs.write_file"}
        or desktop_tool_risk_level(tool_name) == "high"
    )


def _missing_permissions_for_tool(
    tool_name: str,
    *,
    capability_id: str | None,
    capabilities: Mapping[str, Mapping[str, Any]],
    missing_permissions: Mapping[str, Iterable[str]],
) -> list[str]:
    if not _is_desktop_or_browser_tool(tool_name):
        return []
    return desktop_tool_missing_permissions(
        tool_name,
        capability_id=capability_id or "",
        missing_permissions=missing_permissions,
    )


def _blocking_conditions_for_tool(
    tool_name: str,
    *,
    capability_id: str | None,
    capabilities: Mapping[str, Mapping[str, Any]],
    blocking_conditions: Mapping[str, Iterable[str]],
) -> list[str]:
    if not _is_desktop_or_browser_tool(tool_name) or not capability_id:
        return []
    return desktop_tool_blocking_conditions(
        tool_name,
        capability_id=capability_id,
        blocking_conditions=blocking_conditions,
    )


def _fallback_notes_for_tool(tool_name: str) -> list[str]:
    notes_by_tool = {
        "media.apple_music_play": [
            "Direct Apple Music playback falls back to opening Music when playback is unavailable.",
        ],
        "media.apple_music_status": [
            "Reads Apple Music playback state without changing playback; permission failures are returned as tool results.",
        ],
        "media.apple_music_open_and_play": [
            "Opens Music first, then starts playback through the same Apple Music automation path.",
        ],
        "media.apple_music_control": [
            "Apple Music playback controls fall back to opening Music when direct control is unavailable.",
        ],
        "media.music_app_open_and_play": [
            "Opens the named music app, then sends a system media play key; track selection is not verified.",
        ],
        "media.music_app_control": [
            "Focuses the named music app, then sends a system media key; playback state is not verified.",
        ],
        "media.system_control": [
            "Sends a system media key to the current media session; the receiving app and playback state are not verified.",
        ],
        "system.settings_open": [
            "Opens macOS System Settings with a safe system URL; it does not change settings by itself.",
        ],
        "system.volume": [
            "Uses the local system volume interface and records only volume state metadata.",
        ],
        "system.brightness": [
            "Uses local brightness key events for relative up/down changes; exact brightness percentages are not read or stored.",
        ],
        "system.display_sleep": [
            "Uses pmset displaysleepnow to sleep only the display; it does not shut down, restart, log out, or sleep the whole Mac.",
        ],
        "system.screen_saver_start": [
            "Opens macOS ScreenSaverEngine to start the screen saver without changing screen saver settings.",
        ],
        "clipboard.write": [
            "Writes explicit user-provided text to the system clipboard and records only character count.",
        ],
        "clipboard.read": [
            "Reads a bounded preview of the system clipboard only when explicitly requested by the user.",
        ],
        "notes.create": [
            "Creates a macOS Notes note from explicit user-provided content through local automation.",
        ],
        "reminders.create": [
            "Creates a macOS Reminders item through local automation and reports permission failures as tool results.",
        ],
        "calendar.create_event": [
            "Creates a macOS Calendar event only when the title and local start time are deterministic.",
        ],
        "browser.open_url": [
            "Falls back to the system browser when Chrome CDP is unavailable.",
        ],
        "browser.open_url_and_extract_text": [
            "Opens the URL first; text extraction requires a reachable Chrome CDP endpoint.",
        ],
        "browser.open_url_and_screenshot": [
            "Opens the URL first, then captures the page through the browser screenshot path.",
        ],
        "browser.click": [
            "Can fall back to foreground desktop clicking when fallback_x/fallback_y are provided.",
        ],
        "screen.capture": [
            "Requires Screen Recording permission; denial is reported in readiness diagnostics.",
        ],
        "desktop.permissions": [
            "Reports missing desktop permission targets and the tools affected by them.",
        ],
        "desktop.active_window": [
            "Requires Automation or Accessibility permission to read the foreground window.",
        ],
        "desktop.running_apps": [
            "Requires Automation or Accessibility permission to read the foreground app list.",
        ],
        "desktop.list_apps": [
            "Discovers installed app bundles without opening them; use before app.open when the exact app name is uncertain.",
        ],
        "desktop.open_app": [
            "Generic desktop operation alias for app.open; launch failures are surfaced as tool results.",
        ],
        "desktop.focus_app": [
            "Generic desktop operation alias for app.focus; Automation failures are surfaced as tool results.",
        ],
        "desktop.list_windows": [
            "Generic desktop operation alias for desktop.windows; requires Automation or Accessibility permission.",
        ],
        "desktop.read_ui": [
            "Generic desktop operation alias for desktop.ui_elements; reads foreground or named-app UI controls.",
        ],
        "desktop.windows": [
            "Requires Automation or Accessibility permission to read desktop window titles.",
        ],
        "desktop.ui_elements": [
            "Requires Automation or Accessibility permission to read foreground or named-app UI controls.",
        ],
        "desktop.inspect_app": [
            "Combines app discovery, optional open/focus, windows, and named-app UI inspection into one observable readiness snapshot.",
        ],
        "desktop.verify": [
            "Read-only post-operation verification; with app_name it inspects without opening or focusing the app.",
        ],
        "app.status": [
            "Checks whether a local desktop app is running without opening or focusing it.",
        ],
        "app.open": [
            "Uses the local app launcher and surfaces launch failures as tool results.",
        ],
        "app.focus": [
            "Uses desktop automation and surfaces focus failures as tool results.",
        ],
        "app.focus_window": [
            "Requires Automation and Accessibility permission to raise a matching app window by title substring.",
        ],
        "app.open_and_safe_type_text": [
            "Opens and focuses the app before typing only text explicitly provided by the user.",
        ],
        "app.focus_and_safe_type_text": [
            "Focuses the app before typing only text explicitly provided by the user.",
        ],
        "app.open_and_safe_shortcut": [
            "Opens and focuses the app before executing only whitelisted safe shortcuts.",
        ],
        "app.focus_and_safe_shortcut": [
            "Focuses the app before executing only whitelisted safe shortcuts.",
        ],
        "app.open_and_safe_key": [
            "Opens and focuses the app before pressing only whitelisted foreground navigation keys.",
        ],
        "app.focus_and_safe_key": [
            "Focuses the app before pressing only whitelisted foreground navigation keys.",
        ],
        "app.open_and_hotkey": [
            "Opens and focuses the app before sending an explicit keyboard shortcut; approval is required.",
        ],
        "app.focus_and_hotkey": [
            "Focuses the app before sending an explicit keyboard shortcut; approval is required.",
        ],
        "app.open_and_safe_scroll": [
            "Opens and focuses the app before scrolling only explicit foreground up/down page requests.",
        ],
        "app.focus_and_safe_scroll": [
            "Focuses the app before scrolling only explicit foreground up/down page requests.",
        ],
        "app.open_and_safe_click": [
            "Opens and focuses the app before single-clicking only coordinates explicitly provided by the user.",
        ],
        "app.focus_and_safe_click": [
            "Focuses the app before single-clicking only coordinates explicitly provided by the user.",
        ],
        "app.open_and_click_ui_element": [
            "Opens and focuses the app before clicking an inferred coordinate from a visible UI control match; approval is required.",
        ],
        "app.focus_and_click_ui_element": [
            "Focuses the app before clicking an inferred coordinate from a visible UI control match; approval is required.",
        ],
        "app.open_and_type_into_ui_element": [
            "Opens and focuses the app before typing into an inferred input coordinate from a visible UI control match; approval is required.",
        ],
        "app.focus_and_type_into_ui_element": [
            "Focuses the app before typing into an inferred input coordinate from a visible UI control match; approval is required.",
        ],
        "app.show": [
            "Requires Automation and Accessibility permission to show, unhide, restore, and activate a local app.",
        ],
        "app.hide": [
            "Requires Accessibility permission and hides a running app without quitting it.",
        ],
        "app.minimize": [
            "Requires Accessibility permission and minimizes windows for a running app without quitting it.",
        ],
        "app.quit": [
            "Requires approval because quitting an app can discard unsaved work; Automation failures are surfaced as tool results.",
        ],
        "desktop.quit_app": [
            "Requires approval and Accessibility permission because it quits the current foreground app.",
        ],
        "desktop.reveal_path": [
            "Reveals a local file or folder in Finder without opening or executing it.",
        ],
        "desktop.open_path": [
            "Opens folders and safe document/media files; unsafe executable, script, app bundle, and unknown file types are blocked.",
        ],
        "desktop.open_path_with_app": [
            "Opens folders and safe document/media files with a specific discovered app; unsafe executable, script, app bundle, and unknown file types are blocked.",
        ],
        "desktop.hide_app": [
            "Requires Accessibility permission and hides the current foreground app without closing it.",
        ],
        "desktop.show_all_apps": [
            "Requires Accessibility permission and shows all hidden desktop apps without launching or closing apps.",
        ],
        "desktop.minimize_window": [
            "Requires Accessibility permission and minimizes the current foreground window without closing it.",
        ],
        "desktop.close_window": [
            "Requires approval and Accessibility permission because it closes the current foreground window.",
        ],
        "desktop.safe_shortcut": [
            "Requires Accessibility permission and only accepts whitelisted common shortcut actions, including copy current page link, browser utility shortcuts, app switching, hide other apps, toggle full screen, new window, and browser back/forward.",
        ],
        "desktop.safe_key": [
            "Requires Accessibility permission and only accepts whitelisted foreground navigation keys.",
        ],
        "desktop.safe_type_text": [
            "Requires Accessibility permission and only types text explicitly provided by the user.",
        ],
        "desktop.search_submit": [
            "Submits only an explicit foreground search/find query; message sending and form submission must use approval-gated desktop.submit_foreground.",
        ],
        "desktop.safe_click": [
            "Requires Accessibility permission and only single-clicks coordinates explicitly provided by the user.",
        ],
        "desktop.safe_scroll": [
            "Requires Accessibility permission and scrolls only explicit foreground up/down page requests.",
        ],
        "desktop.click_ui_element": [
            "Requires approval plus Automation or Accessibility permission because it observes foreground UI controls and clicks an inferred coordinate.",
            "When the Accessibility tree cannot find the requested target, returns a screen.capture recovery action and recommends desktop.click for a coordinate-based retry.",
        ],
        "desktop.type_into_ui_element": [
            "Requires approval plus Automation or Accessibility permission because it observes foreground UI controls, focuses an inferred input coordinate, and types user-provided text.",
        ],
        "desktop.hotkey": [
            "Requires Accessibility permission and is recorded in the Run Timeline.",
        ],
        "desktop.shortcut": [
            "Generic desktop operation alias for desktop.hotkey; requires Accessibility permission and is recorded in the Run Timeline.",
        ],
        "desktop.submit_foreground": [
            "Always requires approval because it sends, submits, or confirms the current foreground input by pressing Return.",
        ],
        "desktop.type": [
            "Generic desktop operation alias for desktop.type_text; requires Accessibility permission and is recorded in the Run Timeline.",
        ],
        "desktop.type_text": [
            "Requires Accessibility permission and is recorded in the Run Timeline.",
        ],
        "desktop.click": [
            "Requires Accessibility permission, should be used after observing the screen, "
            "and is recorded in the Run Timeline.",
        ],
        "terminal.run": [
            "Always requires approval before command execution.",
        ],
        "workspace.write_patch": [
            "Always requires approval before modifying workspace files.",
        ],
    }
    notes = list(notes_by_tool.get(tool_name, []))
    if tool_name in {
        "browser.current_page",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
        "browser.click",
        "browser.type_text",
        "browser.extract_text",
        "browser.screenshot",
    }:
        notes.append("Requires a reachable Chrome CDP endpoint.")
    plugin_tool = _registered_plugin_tool(tool_name)
    if plugin_tool is not None:
        notes.append(f"Restricted tool-only plugin: {plugin_tool.plugin_id}.")
        if plugin_tool.skill_docs:
            notes.append(f"Plugin skill docs: {_truncate_note(plugin_tool.skill_docs)}")
    return notes


def _diagnostic_route_for_tool(capability_id: str | None) -> str | None:
    if not capability_id:
        return None
    return DESKTOP_CAPABILITY_DIAGNOSTIC_ROUTES.get(capability_id)


def _is_desktop_or_browser_tool(tool_name: str) -> bool:
    return tool_name in DESKTOP_CAPABILITY_TOOLS["desktop_execution"]


def _source_for_tool(tool_name: str) -> str:
    plugin_tool = _registered_plugin_tool(tool_name)
    if plugin_tool is not None:
        return f"plugin:{plugin_tool.plugin_id}"
    return "runtime"


def _registered_plugin_tool(tool_name: str) -> Any | None:
    clean_tool_name = str(tool_name or "").strip()
    for plugin_tool in list_restricted_plugin_tools():
        if plugin_tool.name == clean_tool_name:
            return plugin_tool
    return None


def _restricted_plugin_snapshots(
    plugin_states: Iterable[Any] | None,
) -> list[RestrictedToolPluginSnapshot]:
    by_plugin: dict[str, dict[str, Any]] = {}
    for state in plugin_states or ():
        plugin_id = _optional_string(_field_value(state, "plugin_id"))
        if plugin_id is None:
            continue
        tools = _restricted_plugin_tools_from_payload(_field_value(state, "tools"))
        by_plugin[plugin_id] = {
            "plugin_id": plugin_id,
            "enabled": bool(_field_value(state, "enabled")),
            "tool_names": _unique([
                *_string_list(_field_value(state, "tool_names")),
                *(tool.tool_name for tool in tools),
            ]),
            "tools": tools,
            "skill_docs": str(_field_value(state, "skill_docs") or ""),
            "source": "restricted_tool_plugin",
        }

    for plugin_tool in list_restricted_plugin_tools():
        plugin_id = _optional_string(getattr(plugin_tool, "plugin_id", None))
        if plugin_id is None:
            continue
        record = by_plugin.setdefault(
            plugin_id,
            {
                "plugin_id": plugin_id,
                "enabled": True,
                "tool_names": [],
                "tools": [],
                "skill_docs": "",
                "source": "restricted_tool_plugin",
            },
        )
        record["enabled"] = True
        tool_name = str(getattr(plugin_tool, "name", "") or "").strip()
        if tool_name:
            record["tool_names"] = _unique([*record["tool_names"], tool_name])
        if not record["skill_docs"]:
            record["skill_docs"] = str(getattr(plugin_tool, "skill_docs", "") or "")
        if not any(tool.tool_name == tool_name for tool in record["tools"]):
            record["tools"].append(
                RestrictedPluginToolSnapshot(
                    tool_name=tool_name,
                    tool_id=str(getattr(plugin_tool, "tool_id", "") or ""),
                    function_name=str(getattr(plugin_tool, "function_name", "") or ""),
                    risk_level=_optional_string(getattr(plugin_tool, "risk_level", None)),
                    enabled=True,
                )
            )

    return [
        RestrictedToolPluginSnapshot(
            plugin_id=record["plugin_id"],
            enabled=bool(record["enabled"]),
            tool_names=_unique(record["tool_names"]),
            tools=sorted(record["tools"], key=lambda tool: tool.tool_name),
            skill_docs=str(record["skill_docs"] or ""),
            source=str(record["source"] or "restricted_tool_plugin"),
        )
        for record in (by_plugin[plugin_id] for plugin_id in sorted(by_plugin))
    ]


def _restricted_plugin_snapshots_from_payload(
    payload: Any,
) -> list[RestrictedToolPluginSnapshot]:
    if not isinstance(payload, Iterable) or isinstance(payload, (str, bytes, Mapping)):
        return []

    snapshots: list[RestrictedToolPluginSnapshot] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        plugin_id = _optional_string(item.get("plugin_id"))
        if plugin_id is None:
            continue
        tools = _restricted_plugin_tools_from_payload(item.get("tools"))
        tool_names = _unique([
            *_string_list(item.get("tool_names")),
            *(tool.tool_name for tool in tools),
        ])
        snapshots.append(
            RestrictedToolPluginSnapshot(
                plugin_id=plugin_id,
                enabled=bool(item.get("enabled", False)),
                tool_names=tool_names,
                tools=tools,
                skill_docs=str(item.get("skill_docs") or ""),
                source=str(item.get("source") or "restricted_tool_plugin"),
            )
        )
    return snapshots


def _restricted_plugin_tools_from_payload(
    payload: Any,
) -> list[RestrictedPluginToolSnapshot]:
    if not isinstance(payload, Iterable) or isinstance(payload, (str, bytes, Mapping)):
        return []

    tools: list[RestrictedPluginToolSnapshot] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        tool_name = _optional_string(item.get("tool_name") or item.get("name"))
        if tool_name is None:
            continue
        tools.append(
            RestrictedPluginToolSnapshot(
                tool_name=tool_name,
                tool_id=str(item.get("tool_id") or ""),
                function_name=str(item.get("function_name") or ""),
                risk_level=_optional_string(item.get("risk_level")),
                enabled=bool(item.get("enabled", False)),
            )
        )
    return tools


def _field_value(value: Any, field_name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(field_name)
    return getattr(value, field_name, None)


def _truncate_note(value: str, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
