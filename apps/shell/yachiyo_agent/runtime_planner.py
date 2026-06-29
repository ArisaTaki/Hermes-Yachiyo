"""Task-intent router and capability planner for Yachiyo.

This is the first stable boundary for the Hanako/Hermes-style runtime:
understand the user task, select capabilities, then produce observable tool
steps. Execution remains owned by the existing runtime and policy gates.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from .app_name_hints import (
    compact_app_name_hint,
    legacy_app_name_hint,
    supports_new_message_app_hint,
)
from .capture_plan_hints import capture_note_hint, capture_tool_preview, context_source_hint
from .capability_registry import capability_snapshots
from .clipboard_plan_hints import clipboard_operation_hint, clipboard_tool_preview
from .contracts import (
    PlannerDecisionSnapshot,
    RuntimePlanSnapshot,
    TaskIntentSnapshot,
    ToolPlanSnapshot,
    ToolPlanStepSnapshot,
)
from .data_analysis_plan_hints import (
    data_analysis_artifact_manifest,
    data_analysis_artifacts_expected,
    data_source_hint,
    data_source_kind_hint,
    data_source_scope_hint,
)
from .desktop_plan_hints import (
    app_management_hint,
    app_control_mode,
    app_control_tool_candidates,
    app_foreground_tool_candidates,
    click_target_hint,
    focus_window_hint,
    foreground_management_hint,
    hotkey_hint,
    media_app_query_search_plan,
    media_playback_hint,
    media_tool_preview,
    safe_click_hint,
    safe_key_hint,
    safe_scroll_hint,
    safe_type_text_hint,
    safe_shortcut_hint,
    safe_shortcut_sequence_hint,
    screen_capture_hint,
    submit_action_hint,
    clean_followup_text,
    clean_type_target,
    type_into_ui_hint,
    ui_inspection_hint,
    window_list_hint,
)
from .file_access_plan_hints import file_access_hint
from .policy import (
    DESKTOP_CAPABILITY_TOOLS,
    desktop_tool_blocking_conditions,
    desktop_tool_missing_permissions,
)
from .schedule_plan_hints import schedule_context_source_hint, schedule_tool_preview
from .system_plan_hints import system_control_hint, system_tool_preview
from .terminal_plan_hints import terminal_command_hint
from .web_destination_hints import (
    legacy_known_web_destination_search_url,
    legacy_known_web_destination_url_hint,
)
from packages.security import contains_sensitive_text


class TaskIntentRouter:
    """Deterministic first-pass task intent router.

    Later phases can add model-assisted classification. This conservative
    router gives Chat, Bubble, Live2D, and Studio the same public intent shape.
    """

    def candidate_intents(
        self,
        prompt: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> list[TaskIntentSnapshot]:
        text = _clean_prompt(prompt)
        metadata = metadata or {}
        candidates = [
            self._data_analysis_intent(text, metadata),
            self._media_playback_intent(text, metadata),
            self._system_control_intent(text, metadata),
            self._file_access_intent(text, metadata),
            self._desktop_operation_intent(text, metadata),
            self._web_research_intent(text, metadata),
            self._report_generation_intent(text, metadata),
            self._code_task_intent(text, metadata),
            self._file_organization_intent(text, metadata),
            self._workflow_intent(text, metadata),
            self._multi_agent_intent(text, metadata),
            self._communication_intent(text, metadata),
            self._information_capture_intent(text, metadata),
            self._clipboard_intent(text, metadata),
            self._schedule_intent(text, metadata),
        ]
        return sorted(
            [intent for intent in candidates if intent.confidence > 0],
            key=lambda intent: (_intent_rank_score(intent, text), intent.confidence),
            reverse=True,
        )

    def route(self, prompt: str, metadata: Mapping[str, Any] | None = None) -> TaskIntentSnapshot:
        candidates = self.candidate_intents(prompt, metadata)
        if candidates:
            return candidates[0]
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "general", prompt),
            kind="general",
            title="General Task",
            user_goal=_clean_prompt(prompt),
            confidence=0.25,
            description="General task without a stronger specialized route.",
            preferred_capabilities=["artifact.write"],
        )

    def _data_analysis_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        score = _score_terms(
            text,
            [
                "data analysis",
                "analyze data",
                "analyse data",
                "dataset",
                "csv",
                "xlsx",
                "excel",
                "spreadsheet",
                "table",
                "pandas",
                "chart",
                "plot",
                "visualization",
                "数据分析",
                "分析数据",
                "数据集",
                "表格",
                "电子表格",
                "可视化",
                "图表",
                "统计",
            ],
        )
        source_hint = data_source_hint(text, metadata)
        source_scope = data_source_scope_hint(text, metadata)
        context_source = _task_context_source_hint(text)
        current_page_context = _looks_like_current_page_data_context_source(text)
        visible_context = _looks_like_visible_data_context_source(text)
        desktop_visible_context = _looks_like_desktop_visible_data_context_source(text)
        if desktop_visible_context:
            context_source = "visible_text"
            if source_scope == "Desktop" and not source_hint:
                source_scope = ""
        elif not context_source and current_page_context:
            context_source = "current_page_content"
        elif (
            visible_context
            and not current_page_context
            and context_source not in {"selection", "clipboard"}
        ):
            context_source = "visible_text"
        can_discover_source = _contains_any(
            text,
            ["数据", "数据集", "表格", "data", "dataset", "table", "csv", "xlsx", "json"],
        )
        has_source = bool(source_hint or source_scope or context_source)
        if score <= 0 and has_source and _contains_any(text, ["分析", "统计", "汇总", "可视化"]):
            score = 0.16
        if (
            score <= 0
            and can_discover_source
            and _data_analysis_action_requested(text)
        ):
            score = 0.14
        if (
            score <= 0
            and context_source in {"selection", "clipboard"}
            and _contains_any(text, ["分析", "统计", "汇总", "可视化", "数据", "表格", "data", "table"])
        ):
            score = 0.22
        if _looks_like_data_delivery_without_analysis(text):
            return _empty_intent("data_analysis", text)
        if score <= 0:
            return _empty_intent("data_analysis", text)
        spreadsheet_app_hint = _spreadsheet_ui_app_hint(text)
        source_scope_is_output = bool(
            source_scope and source_scope == _artifact_output_location_hint(text)
        )
        scoped_source_hint = (
            source_hint
            if source_scope_is_output
            else _scoped_data_source_path(source_hint, source_scope)
        )
        inputs = {
            "data_source_hint": scoped_source_hint,
            "data_source_kind": data_source_kind_hint(source_hint, text),
        }
        if spreadsheet_app_hint:
            inputs["spreadsheet_app_hint"] = spreadsheet_app_hint
        if context_source:
            inputs["context_source"] = context_source
        if (
            source_scope
            and not source_hint
            and not (
                context_source
                and source_scope == _artifact_output_location_hint(text)
            )
        ):
            inputs["data_source_scope_hint"] = source_scope
        communication_target = _data_analysis_communication_target_hint(text)
        if communication_target:
            inputs["communication_target_hint"] = communication_target
        app_write_target = (
            {}
            if communication_target
            else _app_write_followup_target_hint(text)
        )
        if app_write_target:
            inputs.update(app_write_target)
        preferred_capabilities = [
            "data.analysis",
            *(["desktop.app_control"] if spreadsheet_app_hint else []),
        ]
        if app_write_target:
            preferred_capabilities.append("desktop.app_control")
        if communication_target:
            if str(communication_target.get("app_name") or "").strip() or (
                str(communication_target.get("channel") or "").strip() == "email"
            ):
                preferred_capabilities.append("desktop.app_control")
            preferred_capabilities.append("communication.compose")
        preferred_capabilities = list(dict.fromkeys(preferred_capabilities))
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "data_analysis", text),
            kind="data_analysis",
            title="Data Analysis",
            user_goal=text,
            confidence=min(0.95, 0.48 + score),
            description="Analyze structured data and produce a report or artifact.",
            inputs=inputs,
            expected_outputs=_expected_outputs(text, default=["analysis_report"]),
            required_capabilities=[
                "file.workspace_read",
                "terminal.execution",
                "artifact.write",
                *(["desktop.app_control"] if app_write_target else []),
            ],
            preferred_capabilities=preferred_capabilities,
            missing_inputs=[] if has_source else ["data_source"],
            risk_level="medium",
        )

    def _desktop_operation_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        if _chat_status_meta_text_hint(text):
            return _empty_intent("desktop_operation", text)
        if _direct_communication_candidate_hint(text):
            return _empty_intent("desktop_operation", text)
        if _known_web_destination_search_hint(text):
            return _empty_intent("desktop_operation", text)
        app_search_app_hint = _app_name_hint(text)
        if (
            _explicit_system_settings_request(text)
            and not (app_search_app_hint and _app_search_hint(text, app_search_app_hint))
        ):
            return _empty_intent("desktop_operation", text)
        if (
            _report_file_context_hint(text)
            and _desktop_content_artifact_requested(text)
            and not _app_name_hint(text)
        ):
            return _empty_intent("desktop_operation", text)
        ui_inspection = ui_inspection_hint(text)
        screen_capture = screen_capture_hint(text)
        app_management = app_management_hint(text)
        foreground_management = foreground_management_hint(text)
        safe_shortcut = safe_shortcut_hint(text)
        safe_shortcut_sequence = safe_shortcut_sequence_hint(text)
        if safe_shortcut_sequence:
            safe_shortcut = dict(safe_shortcut_sequence[0])
        safe_key = safe_key_hint(text)
        safe_scroll = safe_scroll_hint(text)
        hotkey = hotkey_hint(text)
        hotkey_overrides_safe_shortcut = _explicit_hotkey_should_override_safe_shortcut(
            text,
            hotkey,
            safe_shortcut,
        )
        if hotkey_overrides_safe_shortcut:
            safe_shortcut = None
            safe_shortcut_sequence = []
        if str((safe_shortcut or {}).get("action") or "").strip() in {
            "screenshot_selection",
            "screenshot_toolbar",
        }:
            screen_capture = None
        finder_special_location = _finder_special_location_hint(text)
        app_scoped_safe_operation = finder_special_location or _app_scoped_safe_operation_hint(text)
        if _standalone_hotkey_request(text):
            app_scoped_safe_operation = {}
        if (
            not hotkey_overrides_safe_shortcut
            and safe_shortcut is None
            and app_scoped_safe_operation.get("safe_shortcut")
        ):
            safe_shortcut = app_scoped_safe_operation["safe_shortcut"]
        if (
            str((safe_shortcut or {}).get("action") or "").strip() == "copy_current_page_link"
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_scoped_safe_operation = {}
        if _foreground_safe_shortcut_hint(safe_shortcut):
            app_management = None
        if safe_key is None and app_scoped_safe_operation.get("safe_key"):
            safe_key = app_scoped_safe_operation["safe_key"]
        if safe_scroll is None and app_scoped_safe_operation.get("safe_scroll"):
            safe_scroll = app_scoped_safe_operation["safe_scroll"]
        safe_click = safe_click_hint(text)
        foreground_compose_text = _foreground_compose_text_hint(text)
        if str((safe_shortcut or {}).get("action") or "").strip() == "new_message":
            foreground_compose_text = ""
        container_action = _dynamic_context_target_container_action_hint(text)
        if (
            container_action
            and safe_shortcut is None
            and foreground_compose_text
            and not _dynamic_context_source_hint(text)
            and not _dynamic_context_transform_target_hint(text)
        ):
            safe_shortcut = {"action": container_action}
        foreground_paste = _foreground_paste_hint(text)
        if foreground_paste and safe_shortcut is None:
            safe_shortcut = {"action": "paste"}
        desktop_discovery = _desktop_discovery_hint(text)
        if str((foreground_management or {}).get("action") or "").strip() == "show_all_apps":
            desktop_discovery = None
        context_source = context_source_hint(text)
        dynamic_context_transfer = _dynamic_context_ui_transfer_hint(text)
        if dynamic_context_transfer:
            foreground_compose_text = ""
        app_scoped_desktop_operation = _app_scoped_desktop_operation_hint(text)
        browser_interaction_hint = (
            None
            if _explicit_hotkey_request(text)
            else (_browser_type_text_hint(text) or _browser_click_hint(text))
        )
        app_scoped_desktop_mapping = (
            app_scoped_desktop_operation
            if isinstance(app_scoped_desktop_operation, Mapping)
            else {}
        )
        browser_scoped_app = str(
            app_scoped_desktop_mapping.get("app_name") or _app_name_hint(text) or ""
        ).strip()
        if (
            browser_interaction_hint
            and (
                (
                    not app_scoped_desktop_mapping
                    and (
                        not browser_scoped_app
                        or _is_browser_or_search_app_name(browser_scoped_app)
                    )
                )
                or _is_browser_or_search_app_name(browser_scoped_app)
            )
            and not dynamic_context_transfer
        ):
            return _empty_intent("desktop_operation", text)
        foreground_submit_action = _foreground_submit_action_hint(text)
        if hotkey and not _contains_any(text, ("发送", "提交", "send", "submit")):
            foreground_submit_action = ""
        foreground_search_submit = _foreground_search_submit_hint(text)
        foreground_app_search = _foreground_app_search_hint(text)
        command_palette = _app_command_palette_hint(text)
        browser_internal_page = _browser_internal_page_hint(text)
        app_preferences = _app_preferences_hint(text)
        app_scoped_safe_shortcut_app = _app_scoped_safe_shortcut_app_name_hint(text, safe_shortcut)
        app_click_scope = _app_first_click_scope_hint(text)
        app_type_scope = _app_first_type_scope_hint(text)
        if app_type_scope or _target_first_foreground_type_hint(text):
            foreground_compose_text = ""
        if _standalone_hotkey_request(text):
            app_scoped_safe_shortcut_app = ""
        spotlight_search_query = _spotlight_search_query_hint(text)
        spotlight_open = _spotlight_open_hint(text)
        score = _score_terms(
            text,
            [
                "open ",
                "launch ",
                "focus ",
                "switch ",
                "go back to",
                "switch back to",
                "back to",
                "activate ",
                "bring ",
                "click ",
                "type ",
                "press ",
                "play ",
                "pause ",
                "desktop",
                "app",
                "window",
                "finder",
                "browser",
                "music",
                "打开",
                "启动",
                "开启",
                "开起来",
                "切到",
                "聚焦",
                "点击",
                "输入",
                "播放",
                "暂停",
                "窗口",
                "应用",
                "桌面",
                "界面",
                "控件",
                "按钮",
                "屏幕",
                "截图",
                "截屏",
                "screenshot",
                "screen capture",
                "隐藏",
                "最小化",
                "退出",
                "hide ",
                "minimize",
                "quit ",
                "前台",
                "current window",
                "current app",
                "粘贴",
                "全选",
                "撤销",
                "重做",
                "刷新",
                "新建标签页",
                "new tab",
                "refresh",
                "滚动",
                "滑动",
                "scroll",
                "page down",
                "page up",
                "发送",
                "提交",
                "回车提交",
                "回车发送",
            ],
        )
        if score <= 0 and (
            foreground_search_submit
            or foreground_submit_action
            or foreground_compose_text
            or foreground_paste
            or foreground_app_search
        ):
            score = 0.18
        if score <= 0 and (app_scoped_desktop_operation or command_palette):
            score = 0.18
        if score <= 0 and browser_internal_page:
            score = 0.24
        if score <= 0 and app_preferences:
            score = 0.2
        if (
            score <= 0
            and _app_name_hint(text)
            and _contains_any(text, ("搜索", "查找", "检索", "search", "find", "look up"))
        ):
            score = 0.18
        if score <= 0 and (spotlight_search_query or spotlight_open):
            score = 0.18
        if score <= 0 and dynamic_context_transfer:
            score = 0.24
        if score <= 0 and _app_first_control_app_name_hint(text):
            score = 0.18
        if score <= 0 and app_type_scope:
            score = 0.18
        if (
            score <= 0
            and click_target_hint(text)
            and not _looks_like_generic_media_control_request(text)
            and not str(media_playback_hint(text).get("action") or "").strip()
            and not _looks_like_file_organization_request(text)
        ):
            score = 0.18
        if (
            score <= 0
            and not metadata.get("daily_desktop_intent")
            and ui_inspection is None
            and screen_capture is None
            and app_management is None
            and foreground_management is None
            and safe_shortcut is None
            and not safe_shortcut_sequence
            and safe_key is None
            and safe_scroll is None
            and safe_click is None
            and not hotkey
            and not foreground_compose_text
            and not foreground_paste
            and desktop_discovery is None
            and not foreground_search_submit
            and not foreground_submit_action
            and not foreground_app_search
            and not command_palette
            and not browser_internal_page
            and not app_preferences
            and not spotlight_search_query
            and not spotlight_open
            and not dynamic_context_transfer
        ):
            return _empty_intent("desktop_operation", text)
        focus_window = focus_window_hint(text)
        window_list = window_list_hint(text)
        if window_list is not None:
            ui_inspection = None
        elif ui_inspection is not None and not focus_window:
            window_list = None
        foreground_app_windows_shortcut = (
            str((safe_shortcut or {}).get("action") or "").strip() == "application_windows"
        )
        if safe_key:
            screen_capture = None
        if foreground_app_windows_shortcut:
            window_list = None
            app_management = None
            screen_capture = None
        if screen_capture is not None and not str((screen_capture or {}).get("app_name") or "").strip():
            app_management = None
        if screen_capture is not None:
            safe_shortcut = None
            safe_shortcut_sequence = []
        if window_list is not None:
            app_management = None
        app_name_hint = str(
            (focus_window or {}).get("app_name")
            or (window_list or {}).get("app_name")
            or (ui_inspection or {}).get("app_name")
            or (screen_capture or {}).get("app_name")
            or browser_internal_page.get("app_name")
            or app_preferences.get("app_name")
            or (command_palette or {}).get("app_name")
            or app_scoped_safe_operation.get("app_name")
            or app_scoped_safe_shortcut_app
            or (app_management or {}).get("app_name")
            or _foreground_submit_app_name_hint(text, foreground_submit_action)
            or dynamic_context_transfer.get("app_name")
            or app_type_scope.get("app_name")
            or ("" if dynamic_context_transfer else _foreground_compose_app_name_hint(text))
            or _app_name_hint(text)
            or ""
        ).strip()
        direct_app_name_hint = _app_name_hint(text)
        if (
            direct_app_name_hint
            and screen_capture is not None
            and _contains_any(app_name_hint, ("搜索", "查找", "检索", "search", "find", "look up"))
        ):
            app_name_hint = direct_app_name_hint
        if not app_type_scope and _target_first_foreground_type_hint(text):
            app_name_hint = ""
        if str((foreground_management or {}).get("action") or "").strip() == "show_all_apps":
            app_name_hint = ""
        if (
            str((safe_shortcut or {}).get("action") or "").strip() == "copy_current_page_link"
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_name_hint = ""
            app_management = None
        if (
            _system_foreground_safe_shortcut_hint(safe_shortcut)
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_name_hint = ""
            app_management = None
        if safe_key and not app_scoped_safe_operation.get("safe_key"):
            app_name_hint = ""
            app_management = None
        if (
            window_list is not None
            and not str((window_list or {}).get("app_name") or "").strip()
        ):
            app_name_hint = ""
        safe_shortcut_missing_required_scope = False
        if _safe_shortcut_requires_finder_scope_for_text(text, safe_shortcut):
            if _is_finder_app_name(app_name_hint):
                app_name_hint = "Finder"
                app_management = None
                safe_key = None
            else:
                safe_shortcut = None
                safe_shortcut_sequence = []
                safe_shortcut_missing_required_scope = True
        if (
            _safe_shortcut_targets_foreground(text, safe_shortcut, app_name_hint)
            and not (foreground_paste and _foreground_compose_app_name_hint(text))
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_management = None
            app_name_hint = ""
        if foreground_app_windows_shortcut:
            app_name_hint = ""
        if desktop_discovery is not None:
            app_name_hint = ""
        app_management_prepare_mode = _app_management_prepare_mode(
            text,
            app_name_hint,
            app_management,
        )
        app_search: Mapping[str, str] = {}
        if foreground_app_search:
            app_name_hint = ""
            app_search = foreground_app_search
        elif not (
            app_click_scope
            or (app_type_scope and not _app_search_field_input_allows_safe_search(text))
        ):
            app_search = _app_search_hint(text, app_name_hint)
        app_search_app_name = str(app_search.get("app_name") or "").strip()
        if app_search_app_name and (
            not app_name_hint
            or _looks_like_app_search_followup_app(app_name_hint)
            or compact_app_name_hint(app_name_hint).startswith(
                compact_app_name_hint(app_search_app_name)
            )
        ):
            app_name_hint = app_search_app_name
        operation_hint = (
            str((desktop_discovery or {}).get("action") or "")
            or ("submit_search" if foreground_search_submit else "")
            or ("submit_foreground" if foreground_submit_action else "")
            or ("browser_internal_page" if browser_internal_page else "")
            or ("app_preferences" if app_preferences else "")
            or ("dynamic_context_ui_transfer" if dynamic_context_transfer else "")
            or ("safe_shortcut_sequence" if safe_shortcut_sequence else "")
            or ("safe_shortcut" if safe_shortcut else "")
            or ("safe_key" if safe_key else "")
            or ("safe_scroll" if safe_scroll else "")
            or ("hotkey" if hotkey and foreground_management is None else "")
            or _desktop_operation_hint(text)
            or ("type" if app_type_scope else "")
        )
        if safe_shortcut_missing_required_scope and operation_hint == "safe_shortcut":
            operation_hint = ""
        if _safe_shortcut_requires_finder_scope_for_text(text, safe_shortcut) and operation_hint == "safe_key":
            operation_hint = "safe_shortcut"
        if (
            safe_shortcut_missing_required_scope
            and score <= 0
            and ui_inspection is None
            and screen_capture is None
            and app_management is None
            and foreground_management is None
            and safe_key is None
            and safe_scroll is None
            and safe_click is None
            and not hotkey
            and desktop_discovery is None
            and not foreground_compose_text
            and not foreground_paste
            and not app_search
            and not foreground_app_search
            and not spotlight_search_query
            and not spotlight_open
            and not foreground_search_submit
            and not foreground_submit_action
            and not command_palette
            and not dynamic_context_transfer
        ):
            return _empty_intent("desktop_operation", text)
        if (
            context_source in {"selection", "clipboard"}
            and _dynamic_context_browser_action_hint(text, context_source)
            and ui_inspection is None
            and screen_capture is None
            and app_management is None
            and foreground_management is None
            and safe_shortcut is None
            and not safe_shortcut_sequence
            and safe_key is None
            and safe_scroll is None
            and safe_click is None
            and not hotkey
            and not app_search
            and not foreground_app_search
            and not command_palette
            and not dynamic_context_transfer
        ):
            return _empty_intent("desktop_operation", text)
        if (
            context_source
            and not app_name_hint
            and operation_hint == "open"
            and ui_inspection is None
            and screen_capture is None
            and app_management is None
            and foreground_management is None
            and safe_shortcut is None
            and not safe_shortcut_sequence
            and safe_key is None
            and safe_scroll is None
            and safe_click is None
            and not hotkey
            and not app_search
            and not command_palette
            and not dynamic_context_transfer
        ):
            return _empty_intent("desktop_operation", text)
        if _standalone_hotkey_request(text):
            app_name_hint = ""
            app_management = None
            app_search = {}
        inputs: dict[str, Any] = {
            "app_name_hint": app_name_hint,
            "operation_hint": operation_hint,
        }
        if window_list is not None:
            inputs["window_list_hint"] = window_list
        if focus_window:
            inputs["focus_window_hint"] = focus_window
        if ui_inspection is not None:
            inputs["ui_inspection_hint"] = ui_inspection
        if screen_capture is not None:
            inputs["screen_capture_hint"] = screen_capture
        if app_management is not None:
            inputs["app_management_hint"] = app_management
        if app_management_prepare_mode:
            inputs["app_management_prepare_mode"] = app_management_prepare_mode
        if app_search:
            inputs["app_search_hint"] = app_search
        if command_palette:
            inputs["command_palette_hint"] = command_palette
        if browser_internal_page:
            inputs["browser_internal_page_hint"] = browser_internal_page
        if app_preferences:
            inputs["app_preferences_hint"] = app_preferences
        if spotlight_search_query or spotlight_open:
            inputs["spotlight_search_hint"] = {"query": spotlight_search_query}
        if dynamic_context_transfer:
            inputs["dynamic_context_ui_transfer_hint"] = dynamic_context_transfer
        if foreground_search_submit:
            inputs["foreground_search_submit_hint"] = {"action": "search"}
        if foreground_management is not None:
            inputs["foreground_management_hint"] = foreground_management
        if safe_shortcut_sequence:
            inputs["safe_shortcut_sequence_hint"] = safe_shortcut_sequence
        if safe_shortcut is not None:
            inputs["safe_shortcut_hint"] = safe_shortcut
        if safe_key is not None:
            inputs["safe_key_hint"] = safe_key
        if safe_scroll is not None:
            inputs["safe_scroll_hint"] = safe_scroll
        if safe_click is not None:
            inputs["safe_click_hint"] = safe_click
        if hotkey and operation_hint == "hotkey":
            inputs["hotkey_hint"] = hotkey
        if desktop_discovery is not None:
            inputs["desktop_discovery_hint"] = desktop_discovery
        finder_operation_mode = str(finder_special_location.get("mode") or "").strip()
        if finder_operation_mode:
            inputs["operation_mode_hint"] = finder_operation_mode
        if foreground_compose_text:
            inputs["foreground_compose_text_hint"] = foreground_compose_text
        if foreground_paste:
            inputs["foreground_paste_hint"] = {"action": "paste"}
        if foreground_submit_action:
            inputs["foreground_submit_action_hint"] = foreground_submit_action
        desktop_content_artifact = _desktop_content_artifact_hint(text)
        if desktop_content_artifact and app_search:
            inputs["desktop_content_artifact_hint"] = desktop_content_artifact
        risk_level = (
            "medium"
            if operation_hint
            not in {
                "focus_window",
                "list_windows",
                "read_ui",
                "capture_screen",
                "show_app",
                "hide_app",
                "minimize_app",
                "status_app",
                "minimize_window",
                "submit_search",
                "safe_shortcut",
                "safe_key",
                "safe_scroll",
                "safe_click",
                "dynamic_context_ui_transfer",
            }
            and _looks_like_ui_operation(text)
            else "low"
        )
        if operation_hint in {"quit_app", "close_window"}:
            risk_level = "high"
        if operation_hint == "submit_foreground":
            risk_level = "high"
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "desktop_operation", text),
            kind="desktop_operation",
            title="Desktop Operation",
            user_goal=text,
            confidence=min(0.95, 0.42 + score),
            description="Discover and operate local desktop apps through runtime tools.",
            inputs=inputs,
            expected_outputs=(
                _expected_outputs(text, default=["report"])
                if desktop_content_artifact and app_search
                else ["desktop_state"]
            ),
            required_capabilities=["desktop.app_discovery"],
            preferred_capabilities=[
                "desktop.app_control",
                "desktop.ui_operation",
                *(["artifact.write"] if desktop_content_artifact and app_search else []),
            ],
            risk_level=risk_level,
        )

    def _media_playback_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        if _looks_like_desktop_permissions_request(text, text.lower()):
            return _empty_intent("media_playback", text)
        score = _score_terms(
            text,
            [
                "play music",
                "apple music",
                "spotify",
                "music",
                "currently playing",
                "播放",
                "暂停",
                "继续播放",
                "下一首",
                "上一首",
                "当前播放",
                "音乐",
                "网易云",
                "QQ 音乐",
            ],
        )
        hint = media_playback_hint(text)
        system_hint = system_control_hint(text)
        if str(system_hint.get("kind") or "").strip() in {"volume", "brightness"}:
            return _empty_intent("media_playback", text)
        if not hint.get("action") and not hint.get("query"):
            return _empty_intent("media_playback", text)
        if score <= 0 and not hint.get("action"):
            return _empty_intent("media_playback", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "media_playback", text),
            kind="media_playback",
            title="Media Playback",
            user_goal=text,
            confidence=min(0.94, 0.46 + score),
            description="Control local media playback through existing runtime media tools.",
            inputs=hint,
            expected_outputs=["media_state"],
            required_capabilities=["media.playback"],
            preferred_capabilities=[],
            risk_level="low",
        )

    def _system_control_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        if metadata.get("desktop_permission_recovery") and metadata.get("recovery_tool"):
            return _empty_intent("system_control", text)
        if _finder_special_location_hint(text):
            return _empty_intent("system_control", text)
        if _browser_internal_page_hint(text):
            return _empty_intent("system_control", text)
        app_hint = _app_name_hint(text)
        if app_hint and _app_search_hint(text, app_hint):
            return _empty_intent("system_control", text)
        hint = system_control_hint(text)
        if not hint:
            return _empty_intent("system_control", text)
        settings_target = str((hint.get("payload") or {}).get("target") or "").strip()
        if _app_preferences_hint(text) and settings_target in {"", "系统设置"}:
            return _empty_intent("system_control", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "system_control", text),
            kind="system_control",
            title="System Control",
            user_goal=text,
            confidence=0.82,
            description="Perform an explicit low-risk system control through dedicated runtime tools.",
            inputs=hint,
            expected_outputs=["system_state"],
            required_capabilities=["system.control"],
            preferred_capabilities=["desktop.app_discovery"],
            risk_level="low",
        )

    def _web_research_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        if _explicit_hotkey_request(text):
            return _empty_intent("web_research", text)
        if _browser_internal_page_hint(text):
            return _empty_intent("web_research", text)
        if _foreground_app_search_hint(text):
            return _empty_intent("web_research", text)
        if _foreground_find_query_hint(text) and not _looks_like_external_info_lookup(text):
            return _empty_intent("web_research", text)
        if _desktop_window_text_context_hint(text):
            return _empty_intent("web_research", text)
        if (
            _dynamic_context_transform_target_hint(text)
            or _dynamic_context_ui_transfer_hint(text)
            or _blocked_dynamic_context_ui_transfer_hint(text)
        ):
            return _empty_intent("web_research", text)
        source = _task_context_source_hint(text)
        if source and safe_shortcut_hint(text):
            return _empty_intent("web_research", text)
        if _spotlight_search_query_hint(text):
            return _empty_intent("web_research", text)
        if _spotlight_open_hint(text) or _foreground_search_submit_hint(text):
            return _empty_intent("web_research", text)
        communication_target = _web_research_communication_target_hint(text)
        if _direct_communication_hint(text) and not communication_target:
            return _empty_intent("web_research", text)
        dynamic_source = source if source in {"clipboard", "selection"} else ""
        web_search = _web_search_hint(text, dynamic_source)
        browser_interaction = _browser_type_text_hint(text) or _browser_click_hint(text)
        app_scoped_safe_operation = _app_scoped_safe_operation_hint(text)
        app_scoped_desktop_operation = _app_scoped_desktop_operation_hint(text)
        if app_scoped_safe_operation and not _looks_like_external_info_lookup(text) and not browser_interaction:
            return _empty_intent("web_research", text)
        if app_scoped_desktop_operation and not web_search and not browser_interaction:
            return _empty_intent("web_research", text)
        web_search_action = str(web_search.get("browser_action") or "").strip()
        browser_action = (
            web_search
            if (
                str(web_search.get("followup_action") or "").strip()
                or web_search_action in {"open_url_extract", "open_url_screenshot"}
            )
            else browser_interaction
            or _browser_current_page_find_hint(text, dynamic_source)
            or _browser_current_page_hint(text)
            or _dynamic_context_browser_action_hint(text, dynamic_source)
            or _browser_url_action_hint(text, dynamic_source)
            or web_search
        )
        score = _score_terms(
            text,
            [
                "research",
                "search web",
                "search",
                "latest",
                "news",
                "pricing",
                "price",
                "website",
                "url",
                "link",
                "http",
                "web page",
                "网页",
                "网站",
                "链接",
                "网址",
                "搜索",
                "查找",
                "查询",
                "检索",
                "最新",
                "价格",
                "定价",
                "报价",
                "调研",
                "研究",
                "新闻",
            ],
        )
        if (
            score <= 0
            and dynamic_source
            and not _app_name_hint(text)
            and _contains_any(text, ["open", "打开", "search", "find", "查找", "搜索"])
        ):
            score = 0.16
        if score <= 0 and browser_action:
            score = 0.28
        if score <= 0:
            return _empty_intent("web_research", text)
        browser_action_name = str(browser_action.get("browser_action") or "")
        inputs = {"url_hint": _url_hint(text)}
        if dynamic_source and browser_action_name != "find_current_page":
            inputs["context_source"] = dynamic_source
        output_target = _task_output_target_hint(text)
        if output_target:
            inputs["output_target_hint"] = output_target
        if communication_target:
            inputs["communication_target_hint"] = communication_target
        app_write_target = {} if communication_target else _app_write_followup_target_hint(text)
        if app_write_target:
            inputs.update(app_write_target)
        inputs.update(browser_action)
        existing_browser_app_name = str(inputs.get("app_name") or "").strip()
        browser_app_name = existing_browser_app_name or _browser_action_app_name_hint(
            text,
            browser_action_name,
        )
        if browser_app_name and not existing_browser_app_name:
            inputs["app_name"] = browser_app_name
        if (
            browser_app_name
            and not existing_browser_app_name
            and _browser_app_prepare_needed(text, browser_action_name)
        ):
            inputs["app_mode"] = _browser_app_prepare_mode(text)
        uses_dynamic_browser_context = (
            dynamic_source in {"selection", "clipboard"}
            and browser_action_name in {"open_search", "open_url"}
        )
        required_capabilities = (
            ["desktop.ui_operation"]
            if browser_action_name == "find_current_page" or uses_dynamic_browser_context
            else ["browser.research"]
        )
        risk_level = (
            "medium"
            if browser_action_name in {"click", "type_text"}
            else ("low" if browser_action else "medium")
        )
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "web_research", text),
            kind="web_research",
            title="Web Research",
            user_goal=text,
            confidence=min(0.9, 0.38 + score),
            description="Open, read, and summarize web content.",
            inputs=inputs,
            expected_outputs=_expected_outputs(text, default=["summary"]),
            required_capabilities=required_capabilities,
            preferred_capabilities=[
                *(
                    ["clipboard.read_write", "browser.research", "desktop.ui_operation"]
                    if dynamic_source
                    else []
                ),
                "clipboard.read_write" if output_target == "clipboard" else "artifact.write",
                *(
                    ["desktop.app_control"]
                    if communication_target.get("app_name")
                    or str(app_write_target.get("target_app_hint") or "").strip()
                    else []
                ),
                *(["communication.compose"] if communication_target else []),
            ],
            risk_level=risk_level,
        )

    def _report_generation_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        shortcut = safe_shortcut_hint(text)
        shortcut_action = str((shortcut or {}).get("action") or "").strip()
        if (
            (
                _looks_like_file_organization_request(text)
                and not _looks_like_context_artifact_request(text)
            )
            or shortcut_action in {"new_document", "new_note"}
            or _looks_like_schedule_request(text)
        ):
            return _empty_intent("report_generation", text)
        score = _score_terms(
            text,
            [
                "report",
                "write up",
                "summary",
                "brief",
                "deck",
                "报告",
                "总结",
                "摘要",
                "汇报",
                "文档",
                "周报",
                "日报",
                "月报",
                "年报",
                "纪要",
                "简报",
                "复盘",
            ],
        )
        transform_target = _dynamic_context_transform_target_hint(text)
        artifact_context_source = _context_artifact_source_hint(text)
        context_source = (
            str(transform_target.get("context_source") or "").strip()
            or (
                ""
                if artifact_context_source == "current_page_content"
                else artifact_context_source
            )
        )
        file_context = {} if artifact_context_source else _report_file_context_hint(text)
        if score <= 0 and transform_target:
            score = 0.24
        if score <= 0 and file_context and _contains_any(
            text,
            ["生成", "输出", "写", "总结", "摘要", "summarize", "write", "report"],
        ):
            score = 0.16
        if score <= 0:
            return _empty_intent("report_generation", text)
        inputs: dict[str, Any] = {}
        if context_source:
            inputs["context_source"] = context_source
        target_app = str(transform_target.get("target_app_hint") or "").strip()
        if target_app:
            inputs["target_app_hint"] = target_app
            inputs["target_action_hint"] = "app_paste"
            container_action = str(
                transform_target.get("target_container_action_hint") or ""
            ).strip()
            if container_action:
                inputs["target_container_action_hint"] = container_action
        if file_context:
            inputs["file_context_hint"] = file_context
        output_target = _task_output_target_hint(text)
        if output_target:
            inputs["output_target_hint"] = output_target
        output_capability = (
            "desktop.app_control"
            if target_app
            else ("clipboard.read_write" if output_target == "clipboard" else "artifact.write")
        )
        if target_app and context_source:
            file_context_capabilities = _unique_capabilities(
                [_context_source_required_capability(context_source), output_capability]
            )
        else:
            file_context_capabilities = (
                (
                    [
                        "file.workspace_read",
                        "terminal.execution",
                        output_capability,
                    ]
                )
                if file_context
                else [output_capability]
            )
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "report_generation", text),
            kind="report_generation",
            title="Report Generation",
            user_goal=text,
            confidence=min(0.85, 0.34 + score),
            description="Produce a written artifact from available context or gathered inputs.",
            inputs=inputs,
            expected_outputs=_expected_outputs(text, default=["report"]),
            required_capabilities=file_context_capabilities,
            preferred_capabilities=[
                *(
                    ["clipboard.read_write", "desktop.ui_operation"]
                    if context_source
                    else ["file.workspace_read", "browser.research", "data.analysis", "terminal.execution"]
                ),
                *(
                    ["desktop.app_control", "desktop.ui_operation", "clipboard.read_write"]
                    if target_app
                    else [
                        "clipboard.read_write"
                        if output_target == "clipboard"
                        else "artifact.write"
                    ]
                ),
            ],
            risk_level="low",
        )

    def _code_task_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        if _app_command_palette_hint(text):
            return _empty_intent("code_task", text)
        media_hint = media_playback_hint(text)
        if (
            str(media_hint.get("action") or "").strip() == "play"
            and str(media_hint.get("app_name") or "").strip()
            and str(media_hint.get("query") or "").strip()
        ):
            return _empty_intent("code_task", text)
        app_hint = _app_name_hint(text)
        if app_hint and (
            _app_search_hint(text, app_hint)
            or screen_capture_hint(text)
            or _looks_like_ui_operation(text)
        ):
            return _empty_intent("code_task", text)
        if _looks_like_app_scoped_ticket_or_creation_request(text):
            return _empty_intent("code_task", text)
        terminal_hint = terminal_command_hint(text)
        if terminal_hint:
            return TaskIntentSnapshot(
                intent_id=_stable_id("intent", "code_task", text),
                kind="code_task",
                title="Terminal Command",
                user_goal=text,
                confidence=0.93,
                description="Run the explicit terminal command requested by the user.",
                inputs={"terminal_command_hint": terminal_hint},
                expected_outputs=["command_output"],
                required_capabilities=["terminal.execution"],
                preferred_capabilities=["artifact.write"],
                risk_level="high",
            )
        score = _score_terms(
            text,
            [
                "code",
                "test",
                "bug",
                "build",
                "repo",
                "script",
                "python",
                "javascript",
                "typescript",
                "代码",
                "测试",
                "修复",
                "仓库",
                "脚本",
                "程序",
                "编程",
                "实现",
                "开发",
            ],
        )
        if score <= 0:
            return _empty_intent("code_task", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "code_task", text),
            kind="code_task",
            title="Code Task",
            user_goal=text,
            confidence=min(0.88, 0.4 + score),
            description="Read, modify, or test code in the configured workspace.",
            required_capabilities=["file.workspace_read"],
            preferred_capabilities=["terminal.execution", "artifact.write"],
            risk_level="high" if _contains_any(text, ["改", "写", "fix", "change", "modify"]) else "medium",
        )

    def _file_organization_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        scoped_operation = _app_scoped_safe_operation_hint(text)
        if scoped_operation and not _file_duplicate_hint(text):
            return _empty_intent("file_organization", text)
        if _looks_like_context_artifact_request(text):
            return _empty_intent("file_organization", text)
        score = _score_terms(
            text,
            [
                "organize files",
                "sort files",
                "move files",
                "rename files",
                "archive files",
                "clean up files",
                "delete files",
                "duplicate files",
                "duplicates",
                "deduplicate",
                "file inventory",
                "file list",
                "整理文件",
                "整理文件夹",
                "文件整理",
                "重复文件",
                "重复项",
                "文件清单",
                "文件列表",
                "列出文件",
                "盘点文件",
                "归档",
                "重命名",
                "移动文件",
                "分类文件",
                "清理文件",
                "删除文件",
            ],
        )
        if score <= 0 and _looks_like_file_organization_request(text):
            score = 0.16
        if score <= 0:
            return _empty_intent("file_organization", text)
        location_hint = _file_location_hint(text)
        operation_hint = _file_operation_hint(text)
        file_type_hint = _file_type_hint(text)
        file_pattern_hint = _file_pattern_hint(file_type_hint)
        destination_hint = _file_destination_hint(text, source_hint=location_hint)
        inputs: dict[str, Any] = {
            "location_hint": location_hint,
            "operation_hint": operation_hint,
        }
        if file_type_hint:
            inputs["file_type_hint"] = file_type_hint
        if file_pattern_hint:
            inputs["file_pattern_hint"] = file_pattern_hint
        if destination_hint:
            inputs["destination_hint"] = destination_hint
        inventory_only = operation_hint in {"inventory", "duplicate_inventory"}
        destructive = operation_hint in {
            "delete",
            "delete_duplicates",
            "deduplicate",
        } or _contains_any(text, ["delete", "remove", "trash", "删除", "移除", "清空", "废纸篓"])
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "file_organization", text),
            kind="file_organization",
            title="File Organization",
            user_goal=text,
            confidence=min(0.88, 0.42 + score),
            description="Inspect files, produce a file organization plan, and apply explicit changes only after approval.",
            inputs=inputs,
            expected_outputs=(
                ["duplicate_file_report", "report"]
                if operation_hint == "duplicate_inventory"
                else ["file_inventory", "report"]
                if inventory_only
                else ["file_plan", "report"]
            ),
            required_capabilities=["file.organization"],
            preferred_capabilities=["file.workspace_read", "artifact.write", "desktop.app_control"],
            missing_inputs=[] if location_hint else ["file_location"],
            risk_level="low" if inventory_only else ("high" if destructive else "medium"),
        )

    def _file_access_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        if _explicit_browser_url_hint(text) or _browser_internal_page_hint(text):
            return _empty_intent("file_access", text)
        if _looks_like_scoped_data_analysis_request(text):
            return _empty_intent("file_access", text)
        if _finder_search_then_ui_action_hint(text):
            return _empty_intent("file_access", text)
        hint = file_access_hint(text)
        if not hint:
            return _empty_intent("file_access", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "file_access", text),
            kind="file_access",
            title="File Access",
            user_goal=text,
            confidence=0.86,
            description="Open a local path or reveal it in Finder through desktop file tools.",
            inputs=hint,
            expected_outputs=["desktop_state"],
            required_capabilities=["file.desktop_access"],
            preferred_capabilities=["desktop.app_discovery"],
            risk_level="low",
        )

    def _workflow_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        score = _score_terms(text, ["workflow", "flow", "工作流", "流程"])
        known_target_hint = _known_orchestration_target_hint(
            text,
            metadata,
            keys=("available_workflows", "workflow_names", "known_workflows"),
        )
        if score <= 0 and known_target_hint:
            score = 0.24
        if score <= 0 and metadata.get("runnable_kind") != "workflow":
            return _empty_intent("workflow_orchestration", text)
        target_hint = _workflow_target_hint(text) or known_target_hint
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "workflow_orchestration", text),
            kind="workflow_orchestration",
            title="Workflow Orchestration",
            user_goal=text,
            confidence=min(0.92, 0.5 + score),
            description="Run or debug an Agent Studio workflow.",
            inputs={"target_name_hint": target_hint} if target_hint else {},
            required_capabilities=["workflow.orchestration"],
            preferred_capabilities=["artifact.write"],
            risk_level="medium",
        )

    def _multi_agent_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        known_target_hint = _known_orchestration_target_hint(
            text,
            metadata,
            keys=(
                "available_agent_groups",
                "available_groups",
                "agent_group_names",
                "group_names",
                "known_agent_groups",
            ),
        )
        explicit_multi_agent = _looks_like_multi_agent_request(text) or bool(known_target_hint)
        if not explicit_multi_agent and metadata.get("runnable_kind") != "group":
            return _empty_intent("multi_agent", text)
        score = _score_terms(text, ["multi-agent", "group", "agents", "群组", "多 agent", "多Agent", "协作"])
        if score <= 0 and known_target_hint:
            score = 0.24
        if score <= 0 and explicit_multi_agent:
            score = 0.24
        target_hint = _group_target_hint(text) or known_target_hint
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "multi_agent", text),
            kind="multi_agent",
            title="Multi-Agent Coordination",
            user_goal=text,
            confidence=min(0.9, 0.48 + score),
            description="Coordinate multiple agents or group runs.",
            inputs={"target_name_hint": target_hint} if target_hint else {},
            required_capabilities=["group.multi_agent"],
            preferred_capabilities=["artifact.write"],
            risk_level="medium",
        )

    def _communication_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        scoped_new_item = _app_scoped_safe_operation_hint(text)
        scoped_action = str(
            (scoped_new_item.get("safe_shortcut") or {}).get("action") or ""
        ).strip()
        if scoped_action == "new_message":
            return _empty_intent("communication", text)
        app_search_result_hint = _app_search_result_communication_hint(text)
        file_context_hint = _communication_file_context_hint(text, metadata)
        direct_hint = app_search_result_hint or _direct_communication_candidate_hint(
            text,
            metadata,
        )
        if not direct_hint and click_target_hint(text) and _app_name_hint(text):
            return _empty_intent("communication", text)
        if _foreground_submit_action_hint(text) and not direct_hint:
            return _empty_intent("communication", text)
        source = (
            "app_search_result"
            if app_search_result_hint
            else ("file" if file_context_hint else _communication_context_source_hint(text))
        )
        score = _score_terms(text, ["email", "message", "mail", "send to", "send ", "邮件", "消息", "发给", "发送"])
        if score <= 0 and direct_hint:
            score = 0.24
        if score <= 0:
            return _empty_intent("communication", text)
        inputs = {"context_source": source} if source else {}
        if source == "file" and file_context_hint:
            inputs["file_context_hint"] = file_context_hint
        transform = _communication_content_transform_hint(text)
        if transform:
            inputs["content_transform_hint"] = transform
        if direct_hint:
            if transform:
                direct_hint = {**direct_hint, "content_transform_hint": transform}
            inputs["direct_message_hint"] = direct_hint
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "communication", text),
            kind="communication",
            title="Communication",
            user_goal=text,
            confidence=min(0.82, 0.34 + score),
            description="Draft or send communication through available apps or tools.",
            inputs=inputs,
            required_capabilities=["communication.compose"],
            preferred_capabilities=[
                *(
                    ["clipboard.read_write", "browser.research", "desktop.ui_operation"]
                    if source
                    else []
                ),
                "desktop.app_discovery",
                "desktop.app_control",
                "desktop.ui_operation",
                "artifact.write",
            ],
            risk_level="medium",
        )

    def _information_capture_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        scoped_new_item = _app_scoped_safe_operation_hint(text)
        scoped_action = str(
            (scoped_new_item.get("safe_shortcut") or {}).get("action") or ""
        ).strip()
        if scoped_action == "new_note":
            return _empty_intent("information_capture", text)
        if _dynamic_context_source_hint(text) and _non_notes_dynamic_context_target_app(text):
            return _empty_intent("information_capture", text)
        hint = capture_note_hint(text)
        if not hint:
            return _empty_intent("information_capture", text)
        has_body = bool(str(hint.get("body") or "").strip())
        source = str(hint.get("source") or "").strip()
        if (
            not has_body
            and not source
            and str((safe_shortcut_hint(text) or {}).get("action") or "").strip() == "new_note"
        ):
            return _empty_intent("information_capture", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "information_capture", text),
            kind="information_capture",
            title="Information Capture",
            user_goal=text,
            confidence=0.84 if has_body else 0.72,
            description="Capture explicit text or inspected context into a local note.",
            inputs=hint,
            expected_outputs=["note"],
            required_capabilities=["information.capture"],
            preferred_capabilities=[
                capability
                for capability in ("clipboard.read_write", "browser.research", "desktop.ui_operation")
                if source
            ],
            missing_inputs=[] if has_body or source else ["note_body"],
            risk_level="low",
        )

    def _schedule_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        scoped_new_item = _app_scoped_safe_operation_hint(text)
        scoped_action = str(
            (scoped_new_item.get("safe_shortcut") or {}).get("action") or ""
        ).strip()
        if scoped_action in {"new_reminder", "new_event"}:
            return _empty_intent("schedule", text)
        if _looks_like_meeting_content_task(text):
            return _empty_intent("schedule", text)
        score = _score_terms(text, ["remind", "calendar", "schedule", "event", "提醒", "日历", "日程", "会议", "安排"])
        if score <= 0:
            return _empty_intent("schedule", text)
        context_source = schedule_context_source_hint(text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "schedule", text),
            kind="schedule",
            title="Schedule Or Reminder",
            user_goal=text,
            confidence=min(0.86, 0.38 + score),
            description="Create reminders, calendar events, or future tasks.",
            inputs={"context_source": context_source} if context_source else {},
            required_capabilities=["schedule.reminder"],
            preferred_capabilities=[
                *(
                    ["clipboard.read_write", "browser.research", "desktop.ui_operation"]
                    if context_source
                    else []
                ),
                "artifact.write",
            ],
            risk_level="medium",
        )

    def _clipboard_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        if _dynamic_context_transform_target_hint(text):
            return _empty_intent("clipboard_operation", text)
        hint = clipboard_operation_hint(text)
        if not hint:
            return _empty_intent("clipboard_operation", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "clipboard_operation", text),
            kind="clipboard_operation",
            title="Clipboard Operation",
            user_goal=text,
            confidence=0.76,
            description="Read explicitly requested clipboard contents, write explicit text, or inspect selected text.",
            inputs=hint,
            expected_outputs=["text"] if hint.get("action") in {"read", "copy_selection_read"} else ["clipboard_state"],
            required_capabilities=["clipboard.read_write"],
            preferred_capabilities=["desktop.ui_operation"],
            risk_level="low",
        )


class RuntimePlanner:
    def __init__(self, intent_router: TaskIntentRouter | None = None) -> None:
        self._intent_router = intent_router or TaskIntentRouter()

    def decision(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlannerDecisionSnapshot:
        candidates = self._intent_router.candidate_intents(prompt, metadata)
        selected = candidates[0] if candidates else self._intent_router.route(prompt, metadata)
        selected = _normalize_intent_for_allowed_tools(
            selected,
            _allowed_tool_set(allowed_tools),
        )
        plan = self.plan_intent(selected, allowed_tools=allowed_tools, metadata=metadata)
        return PlannerDecisionSnapshot(
            decision_id=_stable_id("decision", selected.kind, prompt),
            prompt=_clean_prompt(prompt),
            selected_intent=selected,
            candidate_intents=candidates,
            plan=plan,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    def plan(
        self,
        prompt: str,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimePlanSnapshot:
        return self.decision(prompt, allowed_tools=allowed_tools, metadata=metadata).plan

    def plan_intent(
        self,
        intent: TaskIntentSnapshot,
        *,
        allowed_tools: Iterable[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RuntimePlanSnapshot:
        allowed = _allowed_tool_set(allowed_tools)
        intent = _normalize_intent_for_allowed_tools(intent, allowed)
        steps = self._steps_for_intent(intent, allowed)
        readiness = _planner_readiness_context(metadata)
        if readiness:
            steps = _apply_readiness_to_steps(steps, readiness)
        required_capabilities = _required_capabilities_for_plan(intent, steps)
        capabilities = [*required_capabilities, *intent.preferred_capabilities]
        snapshots = capability_snapshots(
            allowed_tools=allowed_tools,
            capability_ids=capabilities,
        )
        missing = _missing_capabilities(snapshots, required_capability_ids=required_capabilities)
        for capability_id in _unavailable_required_step_capabilities(
            steps,
            required_capability_ids=required_capabilities,
        ):
            if capability_id not in missing:
                missing.append(capability_id)
        tool_plan = ToolPlanSnapshot(
            plan_id=_stable_id("tool-plan", intent.kind, intent.user_goal),
            title=f"{intent.title} Tool Plan",
            steps=steps,
            required_capabilities=required_capabilities,
            missing_capabilities=missing,
            approvals_required=[step.step_id for step in steps if step.approval_required],
            artifacts_expected=_artifacts_expected(intent, steps),
            open_questions=list(intent.missing_inputs),
        )
        return RuntimePlanSnapshot(
            plan_id=_stable_id("runtime-plan", intent.kind, intent.user_goal),
            intent=intent,
            capabilities=snapshots,
            tool_plan=tool_plan,
            route_to_studio=_route_to_studio(intent, steps),
            timeline_preview=_timeline_preview(intent, steps),
        )

    def _steps_for_intent(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        if intent.kind == "data_analysis":
            return self._data_analysis_steps(intent, allowed)
        if intent.kind == "desktop_operation":
            return self._desktop_operation_steps(intent, allowed)
        if intent.kind == "media_playback":
            return self._media_playback_steps(intent, allowed)
        if intent.kind == "system_control":
            return self._system_control_steps(intent, allowed)
        if intent.kind == "web_research":
            return self._web_research_steps(intent, allowed)
        if intent.kind == "report_generation":
            return self._report_steps(intent, allowed)
        if intent.kind == "code_task":
            return self._code_steps(intent, allowed)
        if intent.kind == "file_access":
            return self._file_access_steps(intent, allowed)
        if intent.kind == "file_organization":
            return self._file_organization_steps(intent, allowed)
        if intent.kind == "schedule":
            return self._schedule_steps(intent, allowed)
        if intent.kind == "communication":
            return self._communication_steps(intent, allowed)
        if intent.kind == "information_capture":
            return self._information_capture_steps(intent, allowed)
        if intent.kind == "clipboard_operation":
            return self._clipboard_steps(intent, allowed)
        if intent.kind == "workflow_orchestration":
            return [
                _service_step(
                    intent,
                    "workflow.orchestration",
                    "Select or start workflow",
                    allowed,
                )
            ]
        if intent.kind == "multi_agent":
            return [
                _service_step(
                    intent,
                    "group.multi_agent",
                    "Select or start group run",
                    allowed,
                )
            ]
        return self._report_steps(intent, allowed)

    def _data_analysis_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        source_hint = str(intent.inputs.get("data_source_hint") or "").strip()
        context_source = str(intent.inputs.get("context_source") or "").strip()
        source_scope = str(intent.inputs.get("data_source_scope_hint") or "").strip()
        source_kind = str(intent.inputs.get("data_source_kind") or "").strip()
        spreadsheet_app_step = _spreadsheet_app_open_step(intent, allowed)
        data_file_open_step = _data_file_open_step(
            intent,
            allowed,
            source_hint=source_hint,
            depends_on=[spreadsheet_app_step.step_id] if spreadsheet_app_step is not None else [],
        )
        if context_source and not source_hint:
            spreadsheet_first_steps = (
                [spreadsheet_app_step]
                if spreadsheet_app_step is not None and context_source == "visible_text"
                else []
            )
            context_step_dependencies = [step.step_id for step in spreadsheet_first_steps]
            context_steps = [
                _with_step_dependencies(step, context_step_dependencies)
                if context_step_dependencies
                else step
                for step in _data_analysis_context_source_steps(
                    intent,
                    allowed,
                    context_source,
                )
            ]
            context_depends_on = [step.step_id for step in context_steps]
            spreadsheet_steps = (
                [_with_step_dependencies(spreadsheet_app_step, context_depends_on)]
                if spreadsheet_app_step is not None and not spreadsheet_first_steps
                else []
            )
            depends_on = [
                *[step.step_id for step in spreadsheet_first_steps],
                *context_depends_on,
                *[step.step_id for step in spreadsheet_steps],
            ]
            artifact_paths = _artifact_output_paths(
                intent.user_goal,
                data_analysis_artifacts_expected(
                    intent.expected_outputs,
                    intent.user_goal,
                ),
            )
            analysis_tool = _first_allowed(("data.analyze", "terminal.run"), allowed)
            if analysis_tool == "data.analyze":
                artifact_path = artifact_paths[0] if artifact_paths else "analysis-report.md"
                source_kind = str(
                    intent.inputs.get("data_source_kind")
                    or data_source_kind_hint("", intent.user_goal)
                    or "text_table"
                ).strip()
                input_preview = {
                    "content": f"<captured {context_source}>",
                    "display_path": f"captured:{context_source}",
                    "artifact_path": artifact_path,
                    "source_kind": source_kind,
                    "requested_outputs": list(intent.expected_outputs),
                    "artifact_manifest": data_analysis_artifact_manifest(artifact_paths),
                }
                if len(artifact_paths) > 1:
                    input_preview["artifact_paths"] = artifact_paths
                steps = [
                    *spreadsheet_first_steps,
                    *context_steps,
                    *spreadsheet_steps,
                    _step(
                        intent,
                        "analyze-data-context",
                        "Analyze captured data",
                        "data.analysis",
                        analysis_tool,
                        input_preview=input_preview,
                        depends_on=depends_on,
                        reason=(
                            "Analyze captured visible, selected, clipboard, or page data with "
                            "the built-in local parser before escalating to terminal.run."
                        ),
                    ),
                ]
                return _append_data_analysis_followup_steps(
                    intent,
                    allowed,
                    steps,
                    artifact_paths=artifact_paths,
                    depends_on="analyze-data-context",
                )
            steps = [
                *spreadsheet_first_steps,
                *context_steps,
                *spreadsheet_steps,
                _step(
                    intent,
                    "run-analysis",
                    "Run reproducible data analysis",
                    "data.analysis",
                    _first_allowed(("terminal.run",), allowed),
                    input_preview={"command": "python - <<'PY'\n# analyze captured tabular data\nPY"},
                    risk_level="high",
                    approval_required=True,
                    depends_on=depends_on,
                    reason="Analyze the captured selection or clipboard data after inspecting it.",
                ),
                _step(
                    intent,
                    "write-analysis-artifact",
                    "Write analysis artifact",
                    "artifact.write",
                    _first_allowed(("artifact.write",), allowed),
                    input_preview={
                        "paths": artifact_paths,
                        "body_source": context_source,
                    },
                    depends_on=["run-analysis"],
                    reason="Return a durable data-analysis artifact that Studio and Chat can replay.",
                ),
            ]
            return _append_data_analysis_followup_steps(
                intent,
                allowed,
                steps,
                artifact_paths=artifact_paths,
                depends_on="write-analysis-artifact",
            )
        if _can_use_builtin_data_analysis(intent, allowed):
            artifact_paths = _artifact_output_paths(
                intent.user_goal,
                data_analysis_artifacts_expected(
                    intent.expected_outputs,
                    intent.user_goal,
                ),
            )
            artifact_path = artifact_paths[0] if artifact_paths else "analysis-report.md"
            source_kind = str(
                intent.inputs.get("data_source_kind")
                or data_source_kind_hint(source_hint, intent.user_goal)
                or "unknown"
            ).strip()
            input_preview = {
                "path": source_hint,
                "artifact_path": artifact_path,
                "source_kind": source_kind,
                "requested_outputs": list(intent.expected_outputs),
                "artifact_manifest": data_analysis_artifact_manifest(artifact_paths),
            }
            if len(artifact_paths) > 1:
                input_preview["artifact_paths"] = artifact_paths
            prepare_steps = [
                *([spreadsheet_app_step] if spreadsheet_app_step is not None else []),
                *([data_file_open_step] if data_file_open_step is not None else []),
            ]
            depends_on = [step.step_id for step in prepare_steps]
            steps = [
                *prepare_steps,
                _step(
                    intent,
                    "analyze-data-file",
                    "Analyze data file",
                    "data.analysis",
                    _first_allowed(("data.analyze",), allowed),
                    input_preview=input_preview,
                    depends_on=depends_on,
                    reason=(
                        "Use the built-in local parser for straightforward CSV, TSV, JSON, JSONL, XLSX, "
                        "text-table, and standard report artifacts before escalating to terminal.run."
                    ),
                )
            ]
            return _append_data_analysis_followup_steps(
                intent,
                allowed,
                steps,
                artifact_paths=artifact_paths,
                depends_on="analyze-data-file",
            )
        inspect_tool_candidates = (
            ("workspace.read", "workspace.list")
            if source_hint
            else ("workspace.list", "workspace.read")
        )
        spreadsheet_steps = (
            [_with_step_dependencies(spreadsheet_app_step, ["inspect-data-source"])]
            if spreadsheet_app_step is not None
            else []
        )
        fallback_data_file_open_step = _data_file_open_step(
            intent,
            allowed,
            source_hint=source_hint,
            depends_on=[
                "inspect-data-source",
                *[step.step_id for step in spreadsheet_steps],
            ],
        )
        file_open_steps = (
            [fallback_data_file_open_step]
            if fallback_data_file_open_step is not None
            else []
        )
        artifact_paths = _artifact_output_paths(
            intent.user_goal,
            data_analysis_artifacts_expected(
                intent.expected_outputs,
                intent.user_goal,
            ),
        )
        steps = [
            _step(
                intent,
                "inspect-data-source",
                "Inspect data source",
                "file.workspace_read",
                _first_allowed(inspect_tool_candidates, allowed),
                input_preview=_data_source_inspect_input_preview(
                    source_hint or source_scope,
                    source_kind,
                ),
                reason="Find and inspect the dataset before analysis.",
                fallback_tools=["desktop.open_path", "browser.current_page"],
            ),
            *spreadsheet_steps,
            *file_open_steps,
            _step(
                intent,
                "run-analysis",
                "Run reproducible data analysis",
                "data.analysis",
                _first_allowed(("terminal.run",), allowed),
                input_preview={"command": "python - <<'PY'\n# inspect data, compute summary, generate charts\nPY"},
                risk_level="high",
                approval_required=True,
                depends_on=[
                    "inspect-data-source",
                    *[step.step_id for step in spreadsheet_steps],
                    *[step.step_id for step in file_open_steps],
                ],
                reason="Use local Python/pandas-style analysis instead of manually operating a spreadsheet app.",
            ),
            _step(
                intent,
                "write-analysis-artifact",
                "Write analysis artifact",
                "artifact.write",
                _first_allowed(("artifact.write",), allowed),
                input_preview={
                    "paths": artifact_paths
                },
                depends_on=["run-analysis"],
                reason="Return a durable report artifact that Studio and Chat can replay.",
            ),
        ]
        return _append_data_analysis_followup_steps(
            intent,
            allowed,
            steps,
            artifact_paths=artifact_paths,
            depends_on="write-analysis-artifact",
        )

    def _desktop_operation_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        focus_window = focus_window_hint(intent.user_goal)
        window_list = window_list_hint(intent.user_goal)
        ui_inspection = ui_inspection_hint(intent.user_goal)
        if window_list is not None:
            ui_inspection = None
        elif ui_inspection is not None and not focus_window:
            window_list = None
        screen_capture = screen_capture_hint(intent.user_goal)
        app_management = app_management_hint(intent.user_goal)
        foreground_management = foreground_management_hint(intent.user_goal)
        safe_shortcut = safe_shortcut_hint(intent.user_goal)
        intent_safe_shortcut = intent.inputs.get("safe_shortcut_hint")
        if isinstance(intent_safe_shortcut, Mapping):
            safe_shortcut = dict(intent_safe_shortcut)
        safe_shortcut_sequence = safe_shortcut_sequence_hint(intent.user_goal)
        if safe_shortcut_sequence:
            safe_shortcut = dict(safe_shortcut_sequence[0])
        safe_key = safe_key_hint(intent.user_goal)
        safe_scroll = safe_scroll_hint(intent.user_goal)
        if str((safe_shortcut or {}).get("action") or "").strip() in {
            "screenshot_selection",
            "screenshot_toolbar",
        }:
            screen_capture = None
        app_scoped_safe_operation = _finder_special_location_hint(
            intent.user_goal
        ) or _app_scoped_safe_operation_hint(intent.user_goal)
        if _standalone_hotkey_request(intent.user_goal):
            app_scoped_safe_operation = {}
        if safe_shortcut is None and app_scoped_safe_operation.get("safe_shortcut"):
            safe_shortcut = app_scoped_safe_operation["safe_shortcut"]
        if (
            str((safe_shortcut or {}).get("action") or "").strip() == "copy_current_page_link"
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_scoped_safe_operation = {}
        if _foreground_safe_shortcut_hint(safe_shortcut):
            app_management = None
        if safe_key is None and app_scoped_safe_operation.get("safe_key"):
            safe_key = app_scoped_safe_operation["safe_key"]
        if safe_scroll is None and app_scoped_safe_operation.get("safe_scroll"):
            safe_scroll = app_scoped_safe_operation["safe_scroll"]
        safe_click = safe_click_hint(intent.user_goal)
        foreground_paste = _foreground_paste_hint(intent.user_goal)
        if foreground_paste and safe_shortcut is None:
            safe_shortcut = {"action": "paste"}
        foreground_app_windows_shortcut = (
            str((safe_shortcut or {}).get("action") or "").strip() == "application_windows"
        )
        if safe_key:
            screen_capture = None
        if foreground_app_windows_shortcut:
            window_list = None
            app_management = None
            screen_capture = None
        if screen_capture is not None and not str((screen_capture or {}).get("app_name") or "").strip():
            app_management = None
        if screen_capture is not None:
            safe_shortcut = None
            safe_shortcut_sequence = []
        desktop_discovery = intent.inputs.get("desktop_discovery_hint")
        if not isinstance(desktop_discovery, Mapping):
            desktop_discovery = _desktop_discovery_hint(intent.user_goal)
        if str((foreground_management or {}).get("action") or "").strip() == "show_all_apps":
            desktop_discovery = {}
        app_search = intent.inputs.get("app_search_hint")
        if not isinstance(app_search, Mapping):
            app_search = _app_search_hint(
                intent.user_goal,
                str(intent.inputs.get("app_name_hint") or ""),
            )
        app_type_scope_hint = _app_first_type_scope_hint(intent.user_goal)
        if _app_first_click_scope_hint(intent.user_goal) or (
            app_type_scope_hint
            and not _app_search_field_input_allows_safe_search(intent.user_goal)
        ):
            app_search = {}
        app_search_context_source = _app_search_query_context_source(app_search)
        command_palette = intent.inputs.get("command_palette_hint")
        if not isinstance(command_palette, Mapping):
            command_palette = _app_command_palette_hint(intent.user_goal)
        browser_internal_page = intent.inputs.get("browser_internal_page_hint")
        if not isinstance(browser_internal_page, Mapping):
            browser_internal_page = _browser_internal_page_hint(intent.user_goal)
        app_preferences = intent.inputs.get("app_preferences_hint")
        if not isinstance(app_preferences, Mapping):
            app_preferences = _app_preferences_hint(intent.user_goal)
        spotlight_search = intent.inputs.get("spotlight_search_hint")
        if not isinstance(spotlight_search, Mapping):
            spotlight_query = _spotlight_search_query_hint(intent.user_goal)
            spotlight_search = (
                {"query": spotlight_query}
                if spotlight_query
                else ({"query": ""} if _spotlight_open_hint(intent.user_goal) else {})
            )
        app_name = str(
            (focus_window or {}).get("app_name")
            or (window_list or {}).get("app_name")
            or (ui_inspection or {}).get("app_name")
            or (screen_capture or {}).get("app_name")
            or command_palette.get("app_name")
            or browser_internal_page.get("app_name")
            or app_preferences.get("app_name")
            or app_scoped_safe_operation.get("app_name")
            or app_search.get("app_name")
            or intent.inputs.get("app_name_hint")
            or (
                ""
                if _standalone_hotkey_request(intent.user_goal)
                else _app_scoped_safe_shortcut_app_name_hint(intent.user_goal, safe_shortcut)
            )
            or (app_management or {}).get("app_name")
            or _app_first_type_scope_hint(intent.user_goal).get("app_name")
            or _foreground_compose_app_name_hint(intent.user_goal)
            or ""
        ).strip()
        direct_app_name = _app_name_hint(intent.user_goal)
        if (
            direct_app_name
            and screen_capture is not None
            and _contains_any(app_name, ("搜索", "查找", "检索", "search", "find", "look up"))
        ):
            app_name = direct_app_name
        if not _app_first_type_scope_hint(intent.user_goal) and _target_first_foreground_type_hint(intent.user_goal):
            app_name = ""
        if _standalone_hotkey_request(intent.user_goal):
            app_name = ""
            app_management = None
            app_search = {}
        if str((foreground_management or {}).get("action") or "").strip() == "show_all_apps":
            app_name = ""
        if (
            str((safe_shortcut or {}).get("action") or "").strip() == "copy_current_page_link"
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_name = ""
            app_management = None
        if (
            _system_foreground_safe_shortcut_hint(safe_shortcut)
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_name = ""
            app_management = None
        if safe_key and not app_scoped_safe_operation.get("safe_key"):
            app_name = ""
            app_management = None
        if safe_scroll and not app_scoped_safe_operation.get("safe_scroll"):
            app_name = ""
            app_management = None
        if _safe_shortcut_requires_finder_scope_for_text(intent.user_goal, safe_shortcut):
            if _is_finder_app_name(app_name):
                app_name = "Finder"
                app_management = None
                safe_key = None
            else:
                safe_shortcut = None
                safe_shortcut_sequence = []
        if (
            _safe_shortcut_targets_foreground(intent.user_goal, safe_shortcut, app_name)
            and not (foreground_paste and _foreground_compose_app_name_hint(intent.user_goal))
            and not app_scoped_safe_operation.get("safe_shortcut")
        ):
            app_management = None
            app_name = ""
        if foreground_app_windows_shortcut:
            app_name = ""
        if desktop_discovery:
            app_name = ""
        app_management_prepare_mode = str(
            intent.inputs.get("app_management_prepare_mode")
            or _app_management_prepare_mode(intent.user_goal, app_name, app_management)
            or ""
        ).strip()
        mode = app_control_mode(intent.user_goal)
        if app_name and safe_shortcut and not _contains_any(
            intent.user_goal,
            ["打开", "启动", "开启", "运行", "拉起", "open ", "launch ", "start "],
        ):
            mode = "focus"
        operation_mode_hint = str(
            intent.inputs.get("operation_mode_hint")
            or app_scoped_safe_operation.get("mode")
            or ""
        ).strip()
        if operation_mode_hint in {"open", "focus"}:
            mode = operation_mode_hint
        click_target = click_target_hint(intent.user_goal)
        app_click_scope = _app_first_click_scope_hint(intent.user_goal)
        scoped_click_app = str(app_click_scope.get("app_name") or "").strip()
        scoped_click_target = app_click_scope.get("click_target")
        if scoped_click_app and isinstance(scoped_click_target, Mapping):
            if not app_name or compact_app_name_hint(app_name).startswith(
                compact_app_name_hint(scoped_click_app)
            ):
                app_name = scoped_click_app
                click_target = dict(scoped_click_target)
        if app_search and click_target and not str(app_search.get("query") or "").strip():
            app_search = {}
        hotkey = hotkey_hint(intent.user_goal)
        hotkey_overrides_safe_shortcut = _explicit_hotkey_should_override_safe_shortcut(
            intent.user_goal,
            hotkey,
            safe_shortcut,
        )
        if hotkey_overrides_safe_shortcut:
            safe_shortcut = None
            if app_scoped_safe_operation.get("safe_shortcut"):
                app_scoped_safe_operation = {
                    key: value
                    for key, value in app_scoped_safe_operation.items()
                    if key != "safe_shortcut"
                }
        if (
            hotkey
            and "desktop.hotkey" in (allowed or set())
            and _explicit_hotkey_request(intent.user_goal)
            and str((foreground_management or {}).get("action") or "").strip()
            in {"quit_app", "close_window"}
        ):
            foreground_management = None
        if app_name and hotkey and not _explicit_app_open_request(intent.user_goal):
            mode = "focus"
        if app_name and click_target and not _explicit_app_open_request(intent.user_goal):
            mode = "focus"
        type_target = type_into_ui_hint(intent.user_goal, app_name=app_name)
        app_type_scope = _app_first_type_scope_hint(intent.user_goal)
        scoped_type_app = str(app_type_scope.get("app_name") or "").strip()
        scoped_type_target = app_type_scope.get("type_target")
        if scoped_type_app and isinstance(scoped_type_target, Mapping):
            if not app_name or compact_app_name_hint(app_name).startswith(
                compact_app_name_hint(scoped_type_app)
            ):
                app_name = scoped_type_app
                type_target = dict(scoped_type_target)
        if app_name and type_target and not _explicit_app_open_request(intent.user_goal):
            mode = "focus"
        if (
            app_search
            and type_target
            and _looks_like_app_search_field_input(intent.user_goal)
            and not _app_search_safe_sequence_available(
                intent.user_goal,
                app_search,
                allowed,
                app_name=app_name,
                mode=mode,
            )
        ):
            app_search = {}
        foreground_compose_text = (
            ""
            if type_target
            else str(
                intent.inputs.get("foreground_compose_text_hint")
                or _foreground_compose_text_hint(intent.user_goal)
                or ""
            ).strip()
        )
        if str((safe_shortcut or {}).get("action") or "").strip() == "new_message":
            foreground_compose_text = ""
        safe_shortcut_action = str((safe_shortcut or {}).get("action") or "").strip()
        safe_type_text = (
            ""
            if type_target or str((safe_shortcut or {}).get("action") or "").strip() == "new_message"
            else (
                foreground_compose_text
                if safe_shortcut_action in {"new_note", "new_document"} and foreground_compose_text
                else safe_type_text_hint(intent.user_goal) or foreground_compose_text
            )
        )
        foreground_submit_action = str(
            intent.inputs.get("foreground_submit_action_hint")
            or _foreground_submit_action_hint(intent.user_goal)
            or ""
        ).strip()
        foreground_search_submit = bool(
            intent.inputs.get("foreground_search_submit_hint")
        ) or _foreground_search_submit_hint(intent.user_goal)
        if (
            app_name
            and (foreground_submit_action or foreground_compose_text or foreground_paste)
            and not _explicit_app_open_request(intent.user_goal)
        ):
            mode = "focus"
        if foreground_submit_action:
            click_target = None
        submit_action = submit_action_hint(intent.user_goal) or foreground_submit_action
        if hotkey and not _contains_any(intent.user_goal, ("发送", "提交", "send", "submit")):
            submit_action = ""
        if click_target and not any((type_target, safe_type_text, app_search)):
            submit_action = ""
        followup_return_hotkey = (
            _return_hotkey_followup_hint(intent.user_goal)
            if any((type_target, safe_type_text, hotkey))
            else None
        )
        if not followup_return_hotkey and hotkey and safe_type_text:
            followup_return_hotkey = _explicit_return_key_followup_hint(intent.user_goal)
        if followup_return_hotkey:
            submit_action = ""
        if (
            not app_search
            and app_type_scope
            and type_target
            and _looks_like_app_search_field_input(intent.user_goal)
            and not _type_into_ui_element_tool_available(app_name, mode, allowed)
        ):
            fallback_app_search = _app_search_from_type_target(type_target, intent.user_goal)
            if _app_search_safe_sequence_available(
                intent.user_goal,
                fallback_app_search,
                allowed,
                app_name=app_name,
                mode=mode,
            ):
                app_search = fallback_app_search
                type_target = None
        create_first_safe_shortcut = (
            safe_shortcut_action in {"new_note", "new_document"}
            and bool(safe_type_text)
        )
        followup_safe_shortcut = (
            safe_shortcut
            if safe_type_text and safe_shortcut and not create_first_safe_shortcut
            else None
        )
        followup_safe_shortcut_sequence = [
            dict(item) for item in safe_shortcut_sequence[1:] if isinstance(item, Mapping)
        ]
        primary_safe_shortcut = None if followup_safe_shortcut else safe_shortcut
        if (
            str((primary_safe_shortcut or {}).get("action") or "").strip() == "spotlight_search"
            and not any((app_search, type_target, safe_type_text, foreground_submit_action))
        ):
            submit_action = ""
        if (
            str((primary_safe_shortcut or {}).get("action") or "").strip() == "find"
            and not any((type_target, safe_type_text, app_search))
        ):
            submit_action = ""
        browser_search_url_after_shortcut = ""
        if (
            app_name
            and _is_browser_or_search_app_name(app_name)
            and str((primary_safe_shortcut or {}).get("action") or "").strip() == "new_tab"
        ):
            browser_search_query = _web_search_query(intent.user_goal)
            if browser_search_query and (allowed is None or "browser.open_url" in allowed):
                browser_search_url_after_shortcut = _web_search_url(
                    _web_search_engine_hint(intent.user_goal),
                    browser_search_query,
                )
        operation_safe_type_text = (
            ""
            if (click_target and safe_type_text) or create_first_safe_shortcut
            else safe_type_text
        )
        operation_tool, operation_preview = _desktop_operation_tool_preview(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            click_target=click_target,
            safe_shortcut=primary_safe_shortcut,
            safe_key=safe_key,
            safe_scroll=safe_scroll,
            safe_click=safe_click,
            hotkey=hotkey,
            type_target=type_target,
            safe_type_text=operation_safe_type_text,
            allow_app_tools=not bool(focus_window),
        )
        operation_uses_app_tool = bool(operation_tool and operation_tool.startswith("app."))
        if foreground_search_submit:
            return [
                _step(
                    intent,
                    "submit-foreground-search",
                    "Submit current search",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.search_submit",), allowed),
                    input_preview={},
                    action="submit",
                    risk_level="low",
                    approval_required=False,
                    reason="Submit the current search field with the dedicated safe search submit tool.",
                )
            ]
        if spotlight_search:
            query = str(spotlight_search.get("query") or "").strip()
            steps = [
                _step(
                    intent,
                    "open-spotlight-search",
                    "Open Spotlight search",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.safe_shortcut",), allowed),
                    input_preview={"action": "spotlight_search"},
                    action="shortcut",
                    risk_level="low",
                    approval_required=False,
                    reason="Open Spotlight with the dedicated safe shortcut.",
                ),
            ]
            if query:
                steps.append(
                    _step(
                        intent,
                        "type-spotlight-search-query",
                        "Type Spotlight search query",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.safe_type_text",), allowed),
                        input_preview={"text": query},
                        depends_on=["open-spotlight-search"],
                        action="type",
                        risk_level="low",
                        approval_required=False,
                        reason="Type only the explicit Spotlight query from the user prompt.",
                    )
                )
            return steps
        dynamic_context_transfer = intent.inputs.get("dynamic_context_ui_transfer_hint")
        if not isinstance(dynamic_context_transfer, Mapping):
            dynamic_context_transfer = _dynamic_context_ui_transfer_hint(intent.user_goal)
        if (
            desktop_discovery
            and not app_name
            and not app_search
            and not any(item for item in (hotkey, type_target, safe_type_text, submit_action) if item)
        ):
            action = str(desktop_discovery.get("action") or "").strip()
            tool_name, input_preview = _desktop_discovery_tool_preview(action, desktop_discovery)
            return [
                _step(
                    intent,
                    f"{action}-desktop-state" if action else "discover-desktop-state",
                    "Discover desktop state",
                    "desktop.app_discovery",
                    _first_allowed((tool_name,), allowed) if tool_name else None,
                    input_preview=input_preview,
                    reason="Run the explicit desktop discovery or permission diagnostic request.",
                )
            ]
        if (
            not app_name
            and screen_capture is not None
            and ui_inspection is None
            and not app_search
            and not safe_click
            and not any(item for item in (hotkey, type_target, safe_type_text, submit_action) if item)
        ):
            capture_payload = {
                key: screen_capture[key]
                for key in ("reason",)
                if key in screen_capture and screen_capture[key] not in (None, "")
            }
            return [
                _step(
                    intent,
                    "capture-screen",
                    "Capture screen",
                    "desktop.app_discovery",
                    _first_allowed(("screen.capture",), allowed),
                    input_preview=capture_payload,
                    reason="Capture visible desktop state for visual inspection before any action.",
                )
            ]
        discovery_tool = _first_allowed(
            (
                "desktop.list_apps",
                "desktop.running_apps",
                "desktop.active_window",
                "screen.capture",
            )
            if app_name
            else ("desktop.running_apps", "desktop.active_window", "screen.capture"),
            allowed,
        )
        discovery_preview = (
            {"query": app_name, "limit": 20}
            if discovery_tool == "desktop.list_apps" and app_name
            else {}
        )
        discovery_reason = (
            "Discover installed apps matching the requested name before opening or operating."
            if discovery_tool == "desktop.list_apps"
            else "Inspect the current app/window state before acting."
        )
        steps = [
            _step(
                intent,
                "discover-desktop-state",
                "Discover desktop state",
                "desktop.app_discovery",
                discovery_tool,
                input_preview=discovery_preview,
                reason=discovery_reason,
            )
        ]
        if dynamic_context_transfer:
            return _dynamic_context_ui_transfer_steps(
                intent,
                allowed,
                dict(dynamic_context_transfer),
                steps,
            )
        if screen_capture is not None and safe_click:
            capture_payload = {
                key: screen_capture[key]
                for key in ("reason",)
                if key in screen_capture and screen_capture[key] not in (None, "")
            }
            steps.append(
                _step(
                    intent,
                    "capture-screen",
                    "Capture screen",
                    "desktop.app_discovery",
                    _first_allowed(("screen.capture",), allowed),
                    input_preview=capture_payload,
                    depends_on=["discover-desktop-state"],
                    reason="Capture visible desktop state before the requested coordinate click.",
                )
            )
        if foreground_management:
            action = str(foreground_management.get("action") or "").strip()
            tool_name = {
                "hide_app": "desktop.hide_app",
                "show_all_apps": "desktop.show_all_apps",
                "minimize_window": "desktop.minimize_window",
                "close_window": "desktop.close_window",
                "quit_app": "desktop.quit_app",
            }.get(action)
            requires_approval = action in {"close_window", "quit_app"}
            manage_depends_on = ["discover-desktop-state"]
            if app_name:
                steps.append(
                    _step(
                        intent,
                        "open-or-focus-app",
                        "Open or focus app",
                        "desktop.app_control",
                        _first_allowed(app_control_tool_candidates("focus"), allowed),
                        input_preview={"app_name": app_name},
                        depends_on=["discover-desktop-state"],
                        reason="Focus the named app before running the foreground window management action.",
                    )
                )
                manage_depends_on = ["open-or-focus-app"]
            steps.append(
                _step(
                    intent,
                    "manage-foreground",
                    "Manage foreground",
                    "desktop.app_control",
                    _first_allowed((tool_name,), allowed) if tool_name else None,
                    risk_level="high" if requires_approval else "low",
                    approval_required=requires_approval,
                    depends_on=manage_depends_on,
                    reason="Run the requested foreground app/window management action through the desktop policy gate.",
                )
            )
            steps.append(
                _step(
                    intent,
                    "verify-desktop-result",
                    "Verify desktop result",
                    "desktop.app_discovery",
                    _first_allowed(
                        ("desktop.active_window", "desktop.running_apps", "desktop.windows"),
                        allowed,
                    ),
                    input_preview={},
                    depends_on=["manage-foreground"],
                    reason="Observe desktop state after the foreground management action.",
                )
            )
            return steps
        if window_list is not None and not focus_window and not _looks_like_ui_operation(intent.user_goal):
            steps.append(
                _step(
                    intent,
                    "list-app-windows",
                    "List app windows",
                    "desktop.app_discovery",
                    _first_allowed(("desktop.windows",), allowed),
                    input_preview=window_list,
                    depends_on=["discover-desktop-state"],
                    reason="List matching desktop windows through runtime discovery.",
                )
            )
            return steps
        focus_step_added = False
        if focus_window:
            steps.append(
                _step(
                    intent,
                    "list-app-windows",
                    "List app windows",
                    "desktop.app_discovery",
                    _first_allowed(("desktop.windows",), allowed),
                    input_preview={"app_name": app_name} if app_name else {},
                    depends_on=["discover-desktop-state"],
                    reason="Inspect matching app windows before raising one by title.",
                )
            )
            steps.append(
                _step(
                    intent,
                    "focus-app-window",
                    "Focus app window",
                    "desktop.app_control",
                    _first_allowed(("app.focus_window",), allowed),
                    input_preview=focus_window,
                    depends_on=["list-app-windows"],
                    reason="Raise the matching app window by title substring after discovery.",
                )
            )
            focus_step_added = True
        if ui_inspection is not None and not any(
            item for item in (hotkey, type_target, safe_type_text, submit_action) if item
        ):
            ui_payload = {
                key: ui_inspection[key]
                for key in ("role_filter", "limit")
                if key in ui_inspection and ui_inspection[key] not in (None, "")
            }
            inspect_tool = _first_allowed(("desktop.inspect_app",), allowed)
            if app_name and not focus_step_added and inspect_tool:
                return [
                    _step(
                        intent,
                        "inspect-app",
                        "Inspect app",
                        "desktop.app_discovery",
                        inspect_tool,
                        input_preview=_desktop_inspect_app_input_preview(
                            app_name,
                            ui_payload,
                            open_if_needed=True,
                            focus=True,
                        ),
                        reason=(
                            "Inspect the requested app with discovery, optional open/focus, "
                            "windows, and named-app UI readiness in one observable step."
                        ),
                    )
                ]
            if app_name and not focus_step_added:
                steps.append(
                    _step(
                        intent,
                        "open-or-focus-app",
                        "Open or focus app",
                        "desktop.app_control",
                        _first_allowed(
                            app_control_tool_candidates(
                                _desktop_observation_prepare_mode(intent.user_goal)
                            ),
                            allowed,
                        ),
                        input_preview={"app_name": app_name},
                        depends_on=["discover-desktop-state"],
                        reason="Prepare the requested app before reading its foreground UI.",
                    )
                )
            steps.append(
                _step(
                    intent,
                    "read-foreground-ui",
                    "Read foreground UI",
                    "desktop.app_discovery",
                    _first_allowed(("desktop.ui_elements",), allowed),
                    input_preview=ui_payload,
                    depends_on=(
                        ["focus-app-window"]
                        if focus_step_added
                        else (["open-or-focus-app"] if app_name else ["discover-desktop-state"])
                    ),
                    reason="Read visible UI controls or text as a discovery step before any action.",
                )
            )
            return steps
        if screen_capture is not None and not safe_click and not any(
            item for item in (hotkey, type_target, safe_type_text, submit_action) if item
        ):
            capture_payload = {
                key: screen_capture[key]
                for key in ("reason",)
                if key in screen_capture and screen_capture[key] not in (None, "")
            }
            if app_name and not focus_step_added:
                steps.append(
                    _step(
                        intent,
                        "open-or-focus-app",
                        "Open or focus app",
                        "desktop.app_control",
                        _first_allowed(
                            app_control_tool_candidates(
                                _desktop_observation_prepare_mode(intent.user_goal)
                            ),
                            allowed,
                        ),
                        input_preview={"app_name": app_name},
                        depends_on=["discover-desktop-state"],
                        reason="Prepare the requested app before capturing its visible state.",
                    )
                )
            steps.append(
                _step(
                    intent,
                    "capture-screen",
                    "Capture screen",
                    "desktop.app_discovery",
                    _first_allowed(("screen.capture",), allowed),
                    input_preview=capture_payload,
                    depends_on=(
                        ["focus-app-window"]
                        if focus_step_added
                        else (["open-or-focus-app"] if app_name else ["discover-desktop-state"])
                    ),
                    reason="Capture visible desktop state for visual inspection before any action.",
                )
            )
            return steps
        if app_management:
            action = str(app_management.get("action") or "").strip()
            tool_name = {
                "status": "app.status",
                "show": "app.show",
                "hide": "app.hide",
                "minimize": "app.minimize",
                "quit": "app.quit",
            }.get(action)
            is_quit = action == "quit"
            manage_depends_on = ["discover-desktop-state"]
            if app_management_prepare_mode in {"open", "focus"}:
                steps.append(
                    _step(
                        intent,
                        "open-or-focus-app",
                        "Open or focus app",
                        "desktop.app_control",
                        _first_allowed(
                            app_control_tool_candidates(app_management_prepare_mode),
                            allowed,
                        ),
                        input_preview={"app_name": app_name},
                        depends_on=["discover-desktop-state"],
                        reason="Resolve the requested app before the follow-up management action.",
                    )
                )
                manage_depends_on = ["open-or-focus-app"]
            steps.append(
                _step(
                    intent,
                    "manage-app",
                    "Manage app",
                    "desktop.app_control",
                    _first_allowed((tool_name,), allowed) if tool_name else None,
                    input_preview={"app_name": app_name},
                    risk_level="high" if is_quit else "low",
                    approval_required=is_quit,
                    depends_on=manage_depends_on,
                    reason="Run the requested app management action through the desktop app-control policy gate.",
                )
            )
            steps.append(
                _step(
                    intent,
                    "verify-desktop-result",
                    "Verify desktop result",
                    "desktop.app_discovery",
                    _first_allowed(
                        ("desktop.running_apps", "desktop.active_window", "desktop.windows"),
                        allowed,
                    ),
                    input_preview={},
                    depends_on=["manage-app"],
                    reason="Observe desktop state after the app management action.",
                )
            )
            return steps
        if app_preferences:
            preferences_app = str(app_preferences.get("app_name") or app_name or "").strip()
            preferences_mode = str(app_preferences.get("mode") or mode or "focus").strip()
            _append_app_scoped_safe_shortcut_steps(
                steps,
                intent,
                step_id="open-app-preferences",
                title="Open app preferences",
                app_name=preferences_app,
                mode=preferences_mode,
                shortcut_action="preferences",
                allowed=allowed,
                depends_on=["discover-desktop-state"],
                prepare_reason="Prepare the requested app before opening its preferences.",
                shortcut_reason="Open the requested app preferences with a generic foreground safe shortcut.",
                fallback_reason="Open the requested app preferences through an app-scoped safe shortcut.",
            )
            verify_tool = _first_allowed(
                ("desktop.ui_elements", "desktop.active_window", "screen.capture"),
                allowed,
            )
            steps.append(
                _step(
                    intent,
                    "verify-desktop-result",
                    "Verify desktop result",
                    "desktop.app_discovery",
                    verify_tool,
                    input_preview=_desktop_verify_input_preview(
                        verify_tool,
                        app_name=preferences_app,
                        operation_preview={},
                    ),
                    depends_on=["open-app-preferences"],
                    reason="Observe the app after opening its preferences.",
                )
            )
            return steps
        if browser_internal_page:
            browser_app = str(browser_internal_page.get("app_name") or app_name or "").strip()
            page_mode = str(browser_internal_page.get("mode") or mode or "focus").strip()
            page_action = str(browser_internal_page.get("action") or "").strip()
            page_url = str(browser_internal_page.get("url") or "").strip()
            previous_step_id = "discover-desktop-state"
            if page_action:
                _append_app_scoped_safe_shortcut_steps(
                    steps,
                    intent,
                    step_id="open-browser-internal-page",
                    title="Open browser internal page",
                    app_name=browser_app,
                    mode=page_mode,
                    shortcut_action=page_action,
                    allowed=allowed,
                    depends_on=[previous_step_id],
                    prepare_reason="Prepare the requested browser before opening its internal surface.",
                    shortcut_reason="Open the requested browser surface with a generic foreground safe shortcut.",
                    fallback_reason="Open the requested browser surface through an app-scoped safe shortcut.",
                )
                previous_step_id = "open-browser-internal-page"
            elif page_url:
                _append_app_scoped_safe_shortcut_steps(
                    steps,
                    intent,
                    step_id="focus-browser-address-bar",
                    title="Focus browser address bar",
                    app_name=browser_app,
                    mode=page_mode,
                    shortcut_action="focus_address_bar",
                    allowed=allowed,
                    depends_on=[previous_step_id],
                    prepare_reason="Prepare the requested browser before focusing its address bar.",
                    shortcut_reason="Focus the browser address bar with a generic foreground safe shortcut.",
                    fallback_reason=(
                        "Focus the browser address bar before opening the requested internal surface."
                    ),
                )
                steps.append(
                    _step(
                        intent,
                        "type-browser-internal-url",
                        "Type browser internal URL",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.safe_type_text",), allowed),
                        input_preview={"text": page_url},
                        depends_on=["focus-browser-address-bar"],
                        action="type",
                        risk_level="low",
                        approval_required=False,
                        reason="Type only the internal browser URL for the requested surface.",
                    )
                )
                steps.append(
                    _step(
                        intent,
                        "submit-browser-internal-url",
                        "Submit browser internal URL",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.search_submit",), allowed),
                        input_preview={},
                        depends_on=["type-browser-internal-url"],
                        action="submit",
                        risk_level="low",
                        approval_required=False,
                        reason="Submit the internal browser URL with the safe search submit tool.",
                    )
                )
                previous_step_id = "submit-browser-internal-url"
            verify_tool = _first_allowed(
                ("desktop.ui_elements", "desktop.active_window", "screen.capture"),
                allowed,
            )
            steps.append(
                _step(
                    intent,
                    "verify-desktop-result",
                    "Verify desktop result",
                    "desktop.app_discovery",
                    verify_tool,
                    input_preview=_desktop_verify_input_preview(
                        verify_tool,
                        app_name=browser_app,
                        operation_preview={},
                    ),
                    depends_on=[previous_step_id],
                    reason="Observe the browser after opening the requested internal surface.",
                )
            )
            return steps
        if command_palette:
            palette_app = str(command_palette.get("app_name") or app_name or "").strip()
            command_text = str(command_palette.get("text") or "").strip()
            palette_mode = str(command_palette.get("mode") or mode or "focus").strip()
            shortcut_action = str(
                command_palette.get("action")
                or _command_palette_action_for_app(palette_app)
                or "command_palette"
            ).strip()
            _append_app_scoped_safe_shortcut_steps(
                steps,
                intent,
                step_id="open-app-command-palette",
                title="Open app command palette",
                app_name=palette_app,
                mode=palette_mode,
                shortcut_action=shortcut_action,
                allowed=allowed,
                depends_on=["discover-desktop-state"],
                prepare_reason="Prepare the requested app before opening its command palette.",
                shortcut_reason="Open the requested command palette with a generic foreground safe shortcut.",
                fallback_reason="Open the requested app command palette with a safe app-scoped shortcut.",
            )
            previous_step_id = "open-app-command-palette"
            if command_text:
                steps.append(
                    _step(
                        intent,
                        "type-command-palette-query",
                        "Type command palette query",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.safe_type_text",), allowed),
                        input_preview={"text": command_text},
                        depends_on=["open-app-command-palette"],
                        action="type",
                        risk_level="low",
                        approval_required=False,
                        reason="Type only the explicit command text from the user prompt.",
                    )
                )
                previous_step_id = "type-command-palette-query"
            safe_key = command_palette.get("safe_key")
            if isinstance(safe_key, Mapping) and safe_key:
                steps.append(
                    _step(
                        intent,
                        "navigate-command-palette-result",
                        "Navigate command palette result",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.safe_key",), allowed),
                        input_preview=dict(safe_key),
                        depends_on=[previous_step_id],
                        action="key",
                        risk_level="low",
                        approval_required=False,
                        reason="Navigate command palette results with the explicit safe key from the prompt.",
                    )
                )
                previous_step_id = "navigate-command-palette-result"
            if command_palette.get("submit"):
                steps.append(
                    _step(
                        intent,
                        "submit-command-palette",
                        "Submit command palette",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.submit_foreground",), allowed),
                        input_preview={"action": "confirm"},
                        depends_on=[previous_step_id],
                        action="submit",
                        risk_level="high",
                        approval_required=True,
                        reason="Confirm the command palette selection only when the prompt asks to run or confirm it.",
                    )
                )
                previous_step_id = "submit-command-palette"
            steps.append(
                _step(
                    intent,
                    "verify-desktop-result",
                    "Verify desktop result",
                    "desktop.app_discovery",
                    _first_allowed(
                        ("desktop.ui_elements", "desktop.active_window", "screen.capture"),
                        allowed,
                    ),
                    input_preview={},
                    depends_on=[previous_step_id],
                    reason="Observe the app after the command palette operation.",
                )
            )
            return steps
        if (
            app_name
            and not operation_uses_app_tool
            and not focus_step_added
            and not (app_search and app_search_context_source == "selection")
        ):
            prepare_mode = _app_search_prepare_mode(intent.user_goal, mode) if app_search else mode
            prepare_tool = _first_allowed(app_control_tool_candidates(prepare_mode), allowed)
            steps.append(
                _step(
                    intent,
                    "open-or-focus-app",
                    "Open or focus app",
                    "desktop.app_control",
                    prepare_tool,
                    input_preview={"app_name": app_name},
                    depends_on=["discover-desktop-state"],
                    reason="Resolve the requested app by name at runtime.",
                )
            )
            focus_tool = _first_allowed(("app.focus",), allowed)
            if (
                prepare_tool == "app.open"
                and focus_tool
                and (
                    not app_search
                    or _contains_any(
                        intent.user_goal,
                        ["打开", "启动", "开启", "open ", "launch ", "start "],
                    )
                )
                and any(
                    item
                    for item in (
                        app_search,
                        click_target,
                        type_target,
                        safe_type_text,
                        hotkey,
                        primary_safe_shortcut,
                        safe_key,
                        safe_scroll,
                        safe_click,
                    )
                    if item
                )
            ):
                steps.append(
                    _step(
                        intent,
                        "focus-opened-app",
                        "Focus opened app",
                        "desktop.app_control",
                        focus_tool,
                        input_preview={"app_name": app_name},
                        depends_on=["open-or-focus-app"],
                        reason="Bring the opened app to the foreground before running the generic desktop operation.",
                    )
                )
        inspect_preflight_step_id = ""
        if (
            app_name
            and operation_uses_app_tool
            and operation_tool
            in {
                "app.focus_and_click_ui_element",
                "app.open_and_click_ui_element",
                "app.focus_and_type_into_ui_element",
                "app.open_and_type_into_ui_element",
            }
            and not focus_step_added
            and not app_search
        ):
            inspect_tool = _first_allowed(("desktop.inspect_app",), allowed)
            if inspect_tool:
                inspect_depends_on = (
                    []
                    if len(steps) == 1 and steps[0].step_id == "discover-desktop-state"
                    else [steps[-1].step_id]
                )
                inspect_step = _step(
                    intent,
                    "inspect-app",
                    "Inspect app",
                    "desktop.app_discovery",
                    inspect_tool,
                    input_preview=_desktop_inspect_app_input_preview(
                        app_name,
                        operation_preview,
                        open_if_needed=True,
                        focus=True,
                    ),
                    reason=(
                        "Inspect the requested app with discovery, optional open/focus, "
                        "windows, and named-app UI readiness before the approval-gated operation."
                    ),
                    depends_on=inspect_depends_on,
                )
                if len(steps) == 1 and steps[0].step_id == "discover-desktop-state":
                    steps = [inspect_step]
                elif not any(step.step_id == "inspect-app" for step in steps):
                    steps.append(inspect_step)
                inspect_preflight_step_id = "inspect-app"
        pre_submit_operation = any(
            item
            for item in (
                app_search,
                click_target,
                type_target,
                safe_type_text,
                hotkey,
                primary_safe_shortcut,
                safe_key,
                safe_scroll,
                safe_click,
                browser_search_url_after_shortcut,
            )
            if item
        )
        if foreground_submit_action and not pre_submit_operation:
            steps.append(
                _step(
                    intent,
                    "submit-foreground-ui",
                    "Submit foreground UI",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.submit_foreground",), allowed),
                    input_preview={"action": foreground_submit_action},
                    risk_level="high",
                    approval_required=True,
                    depends_on=["open-or-focus-app"] if app_name else ["discover-desktop-state"],
                    reason="Submit the current foreground input only through the approval-gated submit tool.",
                )
            )
        if app_search:
            search_query = str(app_search.get("query") or "").strip()
            search_target = str(app_search.get("target") or "").strip() or "Search"
            search_followup = _app_search_followup_hint(intent.user_goal)
            app_search_needs_verify = False
            app_search_context_source = _app_search_query_context_source(app_search)
            context_shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
            app_search_prepare_step_id = "open-or-focus-app"
            if app_search_context_source == "selection":
                if not context_shortcut_tool:
                    return steps
                steps.append(
                    _step(
                        intent,
                        "copy-selected-app-search-query",
                        "Copy selected app-search query",
                        "desktop.ui_operation",
                        context_shortcut_tool,
                        input_preview={"action": "copy"},
                        depends_on=["discover-desktop-state"],
                        action="shortcut",
                        reason="Copy the current selection before focusing the app search field.",
                    )
                )
                app_search_prepare_step_id = "copy-selected-app-search-query"
            if (
                app_name
                and not any(step.step_id == "open-or-focus-app" for step in steps)
                and not focus_step_added
            ):
                prepare_mode = _app_search_prepare_mode(intent.user_goal, mode)
                steps.append(
                    _step(
                        intent,
                        "open-or-focus-app",
                        "Open or focus app",
                        "desktop.app_control",
                        _first_allowed(app_control_tool_candidates(prepare_mode), allowed),
                        input_preview={"app_name": app_name},
                        depends_on=[app_search_prepare_step_id],
                        reason="Resolve the requested app by name after preserving the dynamic search query.",
                    )
                )
                app_search_prepare_step_id = "open-or-focus-app"
            search_focus_tool = _first_allowed(("desktop.safe_shortcut", "desktop.click_ui_element"), allowed)
            if not search_focus_tool and app_name:
                search_focus_tool = _first_allowed(
                    app_foreground_tool_candidates(
                        _app_search_prepare_mode(intent.user_goal, mode),
                        "safe_shortcut",
                    ),
                    allowed,
                )
            search_focus_tool_name = str(search_focus_tool or "")
            if search_focus_tool_name == "desktop.click_ui_element":
                search_focus_preview = {
                    "target": search_target,
                    "role_filter": "text",
                    "click_count": 1,
                    "limit": 80,
                }
            elif search_focus_tool_name.startswith("app."):
                search_focus_preview = {"app_name": app_name, "action": "find"}
            else:
                search_focus_preview = {"action": "find"}
            search_depends_on = ["discover-desktop-state"]
            if focus_step_added:
                search_depends_on = ["focus-app-window"]
            elif app_name:
                search_depends_on = [app_search_prepare_step_id]
            steps.append(
                _step(
                    intent,
                    "focus-app-search-field",
                    "Focus app search field",
                    "desktop.ui_operation",
                    search_focus_tool,
                    input_preview=search_focus_preview,
                    depends_on=search_depends_on,
                    action="click" if search_focus_tool == "desktop.click_ui_element" else "shortcut",
                    reason="Focus the requested app's search affordance without relying on app-specific aliases.",
                )
            )
            if app_search_context_source in {"selection", "clipboard"}:
                if not context_shortcut_tool:
                    return steps
                steps.append(
                    _step(
                        intent,
                        "paste-app-search-query",
                        "Paste app search query",
                        "desktop.ui_operation",
                        context_shortcut_tool,
                        input_preview={"action": "paste"},
                        depends_on=["focus-app-search-field"],
                        action="shortcut",
                        reason="Paste the dynamic app-search query instead of typing its source label.",
                    )
                )
                search_terminal_step_id = "paste-app-search-query"
            else:
                search_type_tool = _first_allowed(("desktop.safe_type_text",), allowed)
                if not search_type_tool and app_name:
                    search_type_tool = _first_allowed(
                        app_foreground_tool_candidates(
                            _app_search_prepare_mode(intent.user_goal, mode),
                            "safe_type_text",
                        ),
                        allowed,
                    )
                search_type_payload = {"text": search_query}
                if str(search_type_tool or "").startswith("app."):
                    search_type_payload = {"app_name": app_name, **search_type_payload}
                steps.append(
                    _step(
                        intent,
                        "type-app-search-query",
                        "Type app search query",
                        "desktop.ui_operation",
                        search_type_tool,
                        input_preview=search_type_payload,
                        depends_on=["focus-app-search-field"],
                        action="type",
                        reason="Type only the explicit app-search query from the user prompt.",
                    )
                )
                search_terminal_step_id = "type-app-search-query"
            if search_followup.get("action") == "arrow_down_confirm":
                steps.append(
                    _step(
                        intent,
                        "select-app-search-result-with-key",
                        "Select app search result",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.safe_key",), allowed),
                        input_preview={"action": "arrow_down", "repeat_count": 1},
                        depends_on=[search_terminal_step_id],
                        action="key",
                        risk_level="low",
                        approval_required=False,
                        reason="Move to the requested search result with a safe arrow-key operation.",
                    )
                )
                search_terminal_step_id = "select-app-search-result-with-key"
                steps.append(
                    _step(
                        intent,
                        "confirm-app-search-result",
                        "Confirm app search result",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.submit_foreground",), allowed),
                        input_preview={"action": "confirm"},
                        depends_on=[search_terminal_step_id],
                        action="submit",
                        risk_level="high",
                        approval_required=True,
                        reason="Confirm the selected search result only after the explicit arrow-key selection.",
                    )
                )
                search_terminal_step_id = "confirm-app-search-result"
                app_search_needs_verify = True
            elif _app_search_should_submit(intent.user_goal, search_followup):
                steps.append(
                    _step(
                        intent,
                        "submit-app-search",
                        "Submit app search",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.search_submit",), allowed),
                        input_preview={},
                        depends_on=[search_terminal_step_id],
                        action="submit",
                        risk_level="low",
                        approval_required=False,
                        reason="Submit the app search with the dedicated safe search submit tool.",
                    )
                )
                search_terminal_step_id = "submit-app-search"
                app_search_needs_verify = True
                if search_followup.get("action") == "click_first_result":
                    click_tool = _first_allowed(("desktop.click_ui_element",), allowed)
                    click_payload = {
                        "target": str(search_followup.get("target") or "第一个结果"),
                        "role_filter": "",
                        "limit": 80,
                        "click_count": int(search_followup.get("click_count") or 1),
                    }
                    if not click_tool and app_name:
                        click_tool = _first_allowed(
                            app_foreground_tool_candidates(
                                _app_search_prepare_mode(intent.user_goal, mode),
                                "click_ui_element",
                            ),
                            allowed,
                        )
                    if str(click_tool or "").startswith("app."):
                        click_payload = {"app_name": app_name, **click_payload}
                    steps.append(
                        _step(
                            intent,
                            "select-app-search-result",
                            "Select app search result",
                            "desktop.ui_operation",
                            click_tool,
                            input_preview=click_payload,
                            depends_on=[search_terminal_step_id],
                            action="click",
                            risk_level=_desktop_operation_risk_level(click_tool),
                            approval_required=_desktop_operation_approval_required(click_tool),
                            reason="Click the requested app search result after submitting the search.",
                        )
                    )
                    search_terminal_step_id = "select-app-search-result"
                    app_search_needs_verify = True
            desktop_content_artifact = _desktop_content_artifact_hint(intent.user_goal)
            if desktop_content_artifact:
                return _append_desktop_content_artifact_steps(
                    intent,
                    allowed,
                    steps,
                    depends_on=search_terminal_step_id,
                    app_name=app_name,
                    artifact_hint=desktop_content_artifact,
                )
            if _desktop_content_model_followup_requested(intent.user_goal):
                return _append_desktop_content_followup_steps(
                    intent,
                    allowed,
                    steps,
                    depends_on=search_terminal_step_id,
                    app_name=app_name,
                )
            if screen_capture is not None:
                capture_payload = {
                    key: screen_capture[key]
                    for key in ("reason",)
                    if key in screen_capture and screen_capture[key] not in (None, "")
                }
                steps.append(
                    _step(
                        intent,
                        "capture-screen",
                        "Capture screen",
                        "desktop.app_discovery",
                        _first_allowed(("screen.capture",), allowed),
                        input_preview=capture_payload,
                        depends_on=[search_terminal_step_id],
                        reason="Capture the visible app state after submitting the requested app search.",
                    )
                )
                return steps
            if not app_search_needs_verify or not app_name:
                return steps
            verify_tool = _first_allowed(
                ("desktop.ui_elements", "desktop.active_window", "screen.capture"),
                allowed,
            )
            steps.append(
                _step(
                    intent,
                    "verify-desktop-result",
                    "Verify desktop result",
                    "desktop.app_discovery",
                    verify_tool,
                    input_preview=_desktop_verify_input_preview(
                        verify_tool,
                        app_name=app_name,
                        operation_preview={},
                    ),
                    depends_on=[search_terminal_step_id],
                    reason="Observe the app after submitting the search.",
                )
            )
            return steps
        if (
            _looks_like_ui_operation(intent.user_goal)
            or click_target
            or type_target
            or primary_safe_shortcut
            or safe_key
            or safe_scroll
            or safe_click
            or hotkey
            or safe_type_text
        ) and (not foreground_submit_action or pre_submit_operation):
            operation_depends_on = ["discover-desktop-state"]
            if inspect_preflight_step_id:
                operation_depends_on = [inspect_preflight_step_id]
            elif focus_step_added:
                operation_depends_on = ["focus-app-window"]
            elif any(step.step_id == "focus-opened-app" for step in steps):
                operation_depends_on = ["focus-opened-app"]
            elif any(step.step_id == "capture-screen" for step in steps):
                operation_depends_on = ["capture-screen"]
            elif not operation_uses_app_tool and app_name:
                operation_depends_on = ["open-or-focus-app"]
            resolved_operation_tool = operation_tool or _desktop_operation_fallback_tool(
                allowed=allowed,
                click_target=click_target,
                hotkey=hotkey,
                safe_shortcut=primary_safe_shortcut,
                safe_key=safe_key,
                safe_scroll=safe_scroll,
                safe_click=safe_click,
                type_target=type_target,
                safe_type_text=operation_safe_type_text,
            )
            steps.append(
                _step(
                    intent,
                    "operate-foreground-ui",
                    "Operate foreground UI",
                    "desktop.ui_operation",
                    resolved_operation_tool,
                    input_preview=operation_preview,
                    risk_level=_desktop_operation_risk_level(resolved_operation_tool),
                    approval_required=_desktop_operation_approval_required(resolved_operation_tool),
                    depends_on=operation_depends_on,
                    reason="Use observable UI operations after discovery, then verify.",
                )
            )
        if (
            browser_search_url_after_shortcut
            and any(step.step_id == "operate-foreground-ui" for step in steps)
        ):
            steps.append(
                _step(
                    intent,
                    "open-browser-search-url",
                    "Open browser search URL",
                    "browser.research",
                    _first_allowed(("browser.open_url",), allowed),
                    input_preview={"url": browser_search_url_after_shortcut},
                    depends_on=["operate-foreground-ui"],
                    risk_level="low",
                    approval_required=False,
                    reason="Open the planned browser search URL after creating the requested browser tab.",
                )
            )
            return steps
        followup_safe_shortcuts = []
        if followup_safe_shortcut:
            followup_safe_shortcuts.append(dict(followup_safe_shortcut))
        followup_safe_shortcuts.extend(followup_safe_shortcut_sequence)
        if followup_safe_shortcuts and any(step.step_id == "operate-foreground-ui" for step in steps):
            previous_step_id = "operate-foreground-ui"
            for index, followup in enumerate(followup_safe_shortcuts):
                followup_step_id = (
                    "operate-foreground-ui-followup"
                    if index == 0
                    else f"operate-foreground-ui-followup-{index + 1}"
                )
                steps.append(
                    _step(
                        intent,
                        followup_step_id,
                        "Operate foreground UI",
                        "desktop.ui_operation",
                        _first_allowed(("desktop.safe_shortcut",), allowed),
                        input_preview=dict(followup),
                        depends_on=[previous_step_id],
                        reason="Run the requested follow-up safe shortcut after the previous foreground operation.",
                    )
                )
                previous_step_id = followup_step_id
        if click_target and safe_type_text and any(step.step_id == "operate-foreground-ui" for step in steps):
            steps.append(
                _step(
                    intent,
                    "operate-foreground-ui-followup-type",
                    "Type after foreground click",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.safe_type_text", "desktop.type_text"), allowed),
                    input_preview={"text": safe_type_text},
                    depends_on=["operate-foreground-ui"],
                    reason="Type the explicit text only after the requested UI target is selected.",
                )
            )
        if (
            create_first_safe_shortcut
            and safe_type_text
            and any(step.step_id == "operate-foreground-ui" for step in steps)
        ):
            steps.append(
                _step(
                    intent,
                    "operate-foreground-ui-followup-type",
                    "Type after foreground create action",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.safe_type_text", "desktop.type_text"), allowed),
                    input_preview={"text": safe_type_text},
                    depends_on=["operate-foreground-ui"],
                    reason="Type the explicit text only after creating the requested foreground item.",
                )
            )
        if (
            hotkey
            and not click_target
            and safe_type_text
            and any(step.step_id == "operate-foreground-ui" for step in steps)
        ):
            followup_step_ids = [
                step.step_id
                for step in steps
                if step.step_id.startswith("operate-foreground-ui-followup")
            ]
            steps.append(
                _step(
                    intent,
                    "operate-foreground-ui-followup-type",
                    "Type after foreground hotkey",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.safe_type_text", "desktop.type_text"), allowed),
                    input_preview={"text": safe_type_text},
                    depends_on=[followup_step_ids[-1] if followup_step_ids else "operate-foreground-ui"],
                    reason="Type the explicit text only after the requested foreground hotkey is sent.",
                )
            )
        if followup_return_hotkey and any(step.step_id == "operate-foreground-ui" for step in steps):
            followup_step_ids = [
                step.step_id
                for step in steps
                if step.step_id.startswith("operate-foreground-ui-followup")
            ]
            steps.append(
                _step(
                    intent,
                    "operate-foreground-ui-followup-return",
                    "Press Return after foreground input",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.hotkey",), allowed),
                    input_preview=dict(followup_return_hotkey),
                    risk_level="high",
                    approval_required=True,
                    depends_on=[followup_step_ids[-1] if followup_step_ids else "operate-foreground-ui"],
                    reason="Press Return only after the explicit foreground input sequence is complete.",
                )
            )
        if submit_action and any(step.step_id == "operate-foreground-ui" for step in steps):
            steps.append(
                _step(
                    intent,
                    "submit-foreground-ui",
                    "Submit foreground UI",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.submit_foreground",), allowed),
                    input_preview={"action": submit_action},
                    risk_level="high",
                    approval_required=True,
                    depends_on=["operate-foreground-ui"],
                    reason="Submit only after the explicit foreground input operation is planned.",
                )
            )
        verify_depends_on = []
        if any(step.step_id == "submit-foreground-ui" for step in steps):
            verify_depends_on = ["submit-foreground-ui"]
        else:
            followup_step_ids = [
                step.step_id
                for step in steps
                if step.step_id.startswith("operate-foreground-ui-followup")
            ]
            if followup_step_ids:
                verify_depends_on = [followup_step_ids[-1]]
        if not verify_depends_on and any(step.step_id == "operate-foreground-ui" for step in steps):
            verify_depends_on = ["operate-foreground-ui"]
        elif not verify_depends_on and any(step.step_id == "focus-app-window" for step in steps):
            verify_depends_on = ["focus-app-window"]
        elif not verify_depends_on and any(step.step_id == "open-or-focus-app" for step in steps):
            verify_depends_on = ["open-or-focus-app"]
        if verify_depends_on:
            verify_tools = _desktop_verify_tool_candidates(verify_depends_on)
            verify_tool = _first_allowed(verify_tools, allowed)
            steps.append(
                _step(
                    intent,
                    "verify-desktop-result",
                    "Verify desktop result",
                    "desktop.app_discovery",
                    verify_tool,
                    input_preview=_desktop_verify_input_preview(
                        verify_tool,
                        app_name=app_name,
                        operation_preview=operation_preview,
                    ),
                    depends_on=verify_depends_on,
                    reason=_desktop_verify_reason(verify_depends_on),
                )
            )
        return steps

    def _media_playback_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        app_query_plan = media_app_query_search_plan(intent.inputs, allowed)
        if app_query_plan:
            steps: list[ToolPlanStepSnapshot] = []
            previous_step_id = ""
            for tool_name, input_preview in app_query_plan:
                if tool_name == "desktop.list_apps":
                    step_id = "discover-media-app"
                    title = "Discover media app"
                    capability_id = "desktop.app_discovery"
                    action = "discover"
                    reason = (
                        "Resolve the requested media app through desktop discovery before opening "
                        "or operating it."
                    )
                elif tool_name in {"app.open", "app.focus"}:
                    step_id = "open-media-app" if tool_name == "app.open" else "focus-media-app"
                    title = "Open media app" if tool_name == "app.open" else "Focus media app"
                    capability_id = "desktop.app_control"
                    action = "open" if tool_name == "app.open" else "focus"
                    reason = (
                        "Open or focus the requested media app before searching because "
                        "the generic media playback tool cannot search for a specific query."
                    )
                elif tool_name.startswith("app."):
                    step_id = "focus-media-app-search"
                    title = "Focus media app search"
                    capability_id = "desktop.ui_operation"
                    action = "shortcut" if tool_name.endswith("_safe_shortcut") else "open"
                    reason = (
                        "Open the requested media app and focus its search affordance because "
                        "the generic media playback tool cannot search for a specific query."
                    )
                elif tool_name == "desktop.safe_shortcut":
                    step_id = "focus-media-app-search"
                    title = "Focus media app search"
                    capability_id = "desktop.ui_operation"
                    action = "shortcut"
                    reason = "Focus the media app search affordance with a safe shortcut."
                elif tool_name == "desktop.safe_type_text":
                    step_id = "type-media-search-query"
                    title = "Type media search query"
                    capability_id = "desktop.ui_operation"
                    action = "type"
                    reason = "Type only the explicit media query from the user prompt."
                elif tool_name == "media.music_app_open_and_play":
                    step_id = "play-media-search-result"
                    title = "Play media search result"
                    capability_id = "media.playback"
                    action = "play"
                    reason = "Start playback from the media app results after submitting the explicit search."
                elif tool_name in {"desktop.ui_elements", "desktop.active_window", "screen.capture"}:
                    step_id = "verify-media-search"
                    title = "Verify media search"
                    capability_id = "desktop.app_discovery"
                    action = _desktop_discovery_action(tool_name)
                    reason = "Observe the media app after submitting the search/play request."
                else:
                    step_id = "submit-media-search"
                    title = "Submit media search"
                    capability_id = "desktop.ui_operation"
                    action = "submit"
                    reason = "Submit the media app search with the dedicated safe submit tool."
                steps.append(
                    _step(
                        intent,
                        step_id,
                        title,
                        capability_id,
                        tool_name,
                        input_preview=input_preview,
                        depends_on=[previous_step_id] if previous_step_id else [],
                        action=action,
                        reason=reason,
                    )
                )
                previous_step_id = step_id
            return steps

        tool_name, input_preview = media_tool_preview(intent.inputs, allowed)
        steps = [
            _step(
                intent,
                "control-media-playback",
                "Control media playback",
                "media.playback",
                tool_name,
                input_preview=input_preview,
                reason="Use dedicated media tools for playback instead of explaining manual steps.",
            )
        ]
        verify_step = _media_playback_verify_step(intent, allowed)
        if verify_step is not None:
            steps.append(verify_step)
        return steps

    def _system_control_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        tool_name, input_preview = system_tool_preview(intent.inputs, allowed)
        if tool_name == "system.settings_open":
            steps = [
                _step(
                    intent,
                    "open-system-settings",
                    "Open system settings",
                    "system.control",
                    tool_name,
                    input_preview=input_preview,
                    reason="Use the dedicated System Settings tool instead of treating settings panes as apps.",
                )
            ]
            if bool(intent.inputs.get("inspect_ui")):
                steps.append(
                    _step(
                        intent,
                        "read-system-settings-ui",
                        "Read system settings UI",
                        "desktop.app_discovery",
                        _first_allowed(("desktop.ui_elements",), allowed),
                        input_preview={"role_filter": "", "limit": 80},
                        depends_on=["open-system-settings"],
                        reason="Read the opened settings pane when the user asks what options or controls are visible.",
                    )
                )
            return steps
        return [
            _step(
                intent,
                "control-system-state",
                "Control system state",
                "system.control",
                tool_name,
                input_preview=input_preview,
                reason="Use dedicated system tools for explicit low-risk controls instead of app-specific rules.",
            )
        ]

    def _web_research_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        browser_action = str(intent.inputs.get("browser_action") or "").strip()
        target_app = str(intent.inputs.get("target_app_hint") or "").strip()
        if browser_action == "find_current_page":
            return _current_page_find_steps(intent, allowed)
        context_source = str(intent.inputs.get("context_source") or "").strip()
        url = str(intent.inputs.get("url_hint") or "").strip()
        if (
            browser_action in {"open_search", "open_url"}
            and context_source in {"selection", "clipboard"}
            and not url
        ):
            return _dynamic_context_browser_steps(intent, allowed)
        if browser_action:
            app_name = str(intent.inputs.get("app_name") or "").strip()
            app_mode = str(intent.inputs.get("app_mode") or "focus").strip() or "focus"
            prepare_step_id = ""
            prepare_step: ToolPlanStepSnapshot | None = None
            discover_step: ToolPlanStepSnapshot | None = None
            if app_name and browser_action != "find_current_page":
                discover_step = _step(
                    intent,
                    "discover-browser-app",
                    "Discover browser app",
                    "desktop.app_discovery",
                    _first_allowed(
                        ("desktop.list_apps", "desktop.running_apps", "desktop.active_window"),
                        allowed,
                    ),
                    input_preview={"query": app_name, "limit": 20},
                    reason="Resolve the requested browser app before opening or focusing it.",
                )
                prepare_step_id = "open-or-focus-browser"
                prepare_step = _step(
                    intent,
                    prepare_step_id,
                    "Open or focus browser",
                    "desktop.app_control",
                    _first_allowed(app_control_tool_candidates(app_mode), allowed),
                    input_preview={"app_name": app_name},
                    depends_on=["discover-browser-app"],
                    reason="Prepare the requested browser before running the browser tool.",
                )
            tool_name = {
                "current_page": "browser.current_page",
                "extract_text": "browser.extract_text",
                "screenshot": "browser.screenshot",
                "click": "browser.click",
                "type_text": "browser.type_text",
                "open_search": "browser.open_url",
                "open_url": "browser.open_url",
                "open_url_extract": "browser.open_url_and_extract_text",
                "open_url_screenshot": "browser.open_url_and_screenshot",
            }.get(browser_action)
            input_preview: dict[str, Any] = {}
            if browser_action == "click":
                selector = str(intent.inputs.get("selector") or "").strip()
                click_count = intent.inputs.get("click_count")
                if selector:
                    input_preview["selector"] = selector
                if click_count not in (None, ""):
                    input_preview["click_count"] = click_count
            if browser_action == "type_text":
                selector = str(intent.inputs.get("selector") or "").strip()
                text = str(intent.inputs.get("text") or "")
                if selector:
                    input_preview["selector"] = selector
                if text:
                    input_preview["text"] = text
                for key in ("fallback_x", "fallback_y"):
                    value = intent.inputs.get(key)
                    if value not in (None, ""):
                        input_preview[key] = value
            reason = str(intent.inputs.get("reason") or "").strip()
            if browser_action in {"screenshot", "open_url_screenshot"} and reason:
                input_preview["reason"] = reason
            if browser_action in {
                "open_search",
                "open_url",
                "open_url_extract",
                "open_url_screenshot",
            }:
                if url:
                    input_preview["url"] = url
            main_step = _step(
                intent,
                {
                    "current_page": "read-current-page",
                    "extract_text": "extract-current-page-text",
                    "screenshot": "capture-current-page",
                    "click": "click-current-page-element",
                    "type_text": "type-current-page-input",
                    "open_search": "open-web-search",
                    "open_url": "open-web-url",
                    "open_url_extract": "extract-web-url-text",
                    "open_url_screenshot": "capture-web-url",
                }.get(browser_action, "read-current-page"),
                {
                    "current_page": "Read current page",
                    "extract_text": "Extract current page text",
                    "screenshot": "Capture current page",
                    "click": "Click current page element",
                    "type_text": "Type into current page input",
                    "open_search": "Open web search",
                    "open_url": "Open web URL",
                    "open_url_extract": "Open and extract web URL",
                    "open_url_screenshot": "Open and capture web URL",
                }.get(browser_action, "Read current page"),
                "browser.research",
                _first_allowed((tool_name,), allowed) if tool_name else None,
                input_preview=input_preview,
                risk_level="medium" if browser_action in {"click", "type_text"} else "low",
                approval_required=browser_action in {"click", "type_text"},
                depends_on=[prepare_step_id] if prepare_step_id else [],
                reason=(
                    "Use the browser interaction tool so the runtime can enforce browser approval."
                    if browser_action in {"click", "type_text"}
                    else "Use the explicit current-page browser tool instead of desktop screen automation."
                ),
            )
            if (
                browser_action == "open_search"
                and str(intent.inputs.get("followup_action") or "").strip()
                == "click_search_result"
            ):
                click_preview = {
                    "selector": str(intent.inputs.get("selector") or "search-result=1"),
                    "click_count": int(intent.inputs.get("click_count") or 1),
                }
                click_step = _step(
                    intent,
                    "click-web-search-result",
                    "Click web search result",
                    "browser.research",
                    _first_allowed(("browser.click",), allowed),
                    input_preview=click_preview,
                    risk_level="medium",
                    approval_required=True,
                    depends_on=["open-web-search"],
                    reason="Click the requested search result only after opening the planned search URL.",
                )
                steps = [
                    *([discover_step] if discover_step is not None else []),
                    *([prepare_step] if prepare_step is not None else []),
                    main_step,
                    click_step,
                ]
                artifact_depends_on = click_step.step_id
                if str(intent.inputs.get("post_followup_action") or "").strip() == "extract_text":
                    post_step = _step(
                        intent,
                        "extract-clicked-web-result-text",
                        "Extract clicked web result text",
                        "browser.research",
                        _first_allowed(("browser.extract_text", "browser.current_page"), allowed),
                        input_preview={},
                        depends_on=[click_step.step_id],
                        reason="Read the clicked result page before producing the requested summary or report.",
                    )
                    steps.append(post_step)
                    artifact_depends_on = post_step.step_id
                if (
                    not target_app
                    and _web_research_artifact_requested(intent)
                    and (allowed is None or "artifact.write" in allowed)
                ):
                    artifact_path = _artifact_output_path(
                        intent.user_goal,
                        "research-summary.md",
                    )
                    steps.append(
                        _step(
                            intent,
                            "write-research-artifact",
                            "Write research artifact",
                            "artifact.write",
                            _first_allowed(("artifact.write",), allowed),
                            input_preview={"path": artifact_path},
                            depends_on=[artifact_depends_on],
                            reason="Persist the requested browser-derived report as a replayable artifact.",
                        )
                    )
                if target_app:
                    return _append_web_research_app_write_target_steps(
                        intent,
                        allowed,
                        steps,
                        depends_on=artifact_depends_on,
                    )
                return steps
            steps = [
                *([discover_step] if discover_step is not None else []),
                *([prepare_step] if prepare_step is not None else []),
                main_step,
            ]
            artifact_path = ""
            if (
                not target_app
                and (
                    _web_research_artifact_requested(intent)
                    or isinstance(intent.inputs.get("communication_target_hint"), Mapping)
                )
            ) and (
                allowed is None or "artifact.write" in allowed
            ):
                artifact_path = _artifact_output_path(
                    intent.user_goal,
                    "research-summary.md",
                )
                steps.append(
                    _step(
                        intent,
                        "write-research-artifact",
                        "Write research artifact",
                        "artifact.write",
                        _first_allowed(("artifact.write",), allowed),
                        input_preview={
                            "path": artifact_path
                        },
                        depends_on=[main_step.step_id],
                        reason="Persist the requested browser-derived report as a replayable artifact.",
                    )
                )
            if target_app:
                return _append_web_research_app_write_target_steps(
                    intent,
                    allowed,
                    steps,
                    depends_on=main_step.step_id,
                )
            if _task_output_target_hint(intent.user_goal) == "clipboard":
                steps.append(
                    _clipboard_output_step(
                        intent,
                        allowed,
                        depends_on=[main_step.step_id],
                        body_source=_web_clipboard_body_source(browser_action),
                    )
                )
            followup_steps = _append_artifact_reveal_step(
                intent,
                allowed,
                steps,
                artifact_paths=[artifact_path] if artifact_path else [],
                depends_on="write-research-artifact",
            )
            return _append_web_research_communication_steps(
                intent,
                allowed,
                followup_steps,
                artifact_path=artifact_path,
                depends_on="write-research-artifact",
            )
        if context_source and not url:
            context_steps = _context_source_steps(
                intent,
                allowed,
                context_source,
                step_prefix="web",
                capability_id="browser.research",
            )
            depends_on = [step.step_id for step in context_steps]
            return [
                *context_steps,
                _step(
                    intent,
                    "open-or-read-web-from-context",
                    "Open or read web content from captured context",
                    "browser.research",
                    _first_allowed(
                        (
                            "browser.open_url_and_extract_text",
                            "browser.open_url_and_screenshot",
                            "browser.open_url",
                            "browser.current_page",
                            "browser.extract_text",
                        ),
                        allowed,
                    ),
                    input_preview={"body_source": context_source},
                    risk_level="medium",
                    approval_required=True,
                    depends_on=depends_on,
                    reason="Inspect the requested source before deciding which URL or query to open.",
                ),
            ]
        steps = [
            _step(
                intent,
                "open-or-read-web",
                "Open or read web content",
                "browser.research",
                _first_allowed(
                    (
                        "browser.open_url_and_extract_text",
                        "browser.open_url_and_screenshot",
                        "browser.current_page",
                        "browser.extract_text",
                        "browser.screenshot",
                        "browser.open_url",
                    ),
                    allowed,
                ),
                input_preview={"url": url} if url else {},
                risk_level="medium",
                approval_required=True,
                reason="Use browser tools for web content instead of desktop clicking when possible.",
            ),
        ]
        if target_app:
            return _append_web_research_app_write_target_steps(
                intent,
                allowed,
                steps,
                depends_on="open-or-read-web",
            )
        if _task_output_target_hint(intent.user_goal) == "clipboard":
            steps.append(
                _clipboard_output_step(
                    intent,
                    allowed,
                    depends_on=["open-or-read-web"],
                    body_source="web_content",
                )
            )
        else:
            artifact_path = _artifact_output_path(intent.user_goal, "research-summary.md")
            steps.append(
                _step(
                    intent,
                    "write-research-artifact",
                    "Write research artifact",
                    "artifact.write",
                    _first_allowed(("artifact.write",), allowed),
                    input_preview={
                        "path": artifact_path
                    },
                    depends_on=["open-or-read-web"],
                    reason="Persist research output for replay.",
                )
            )
            steps = _append_artifact_reveal_step(
                intent,
                allowed,
                steps,
                artifact_paths=[artifact_path],
                depends_on="write-research-artifact",
            )
            steps = _append_web_research_communication_steps(
                intent,
                allowed,
                steps,
                artifact_path=artifact_path,
                depends_on="write-research-artifact",
            )
        return steps

    def _report_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        context_source = str(intent.inputs.get("context_source") or "").strip()
        file_context = intent.inputs.get("file_context_hint")
        if isinstance(file_context, Mapping) and file_context:
            location = str(file_context.get("location") or "").strip()
            file_type = str(file_context.get("file_type") or "").strip()
            pattern = str(file_context.get("pattern") or "").strip()
            list_preview = {
                key: value
                for key, value in {
                    "path": location,
                    "file_type": file_type,
                    "pattern": pattern,
                }.items()
                if value
            }
            artifact_path = _artifact_output_path(intent.user_goal, "report.md")
            steps = [
                _step(
                    intent,
                    "inspect-report-file-scope",
                    "Inspect report file scope",
                    "file.workspace_read",
                    _first_allowed(("workspace.list", "workspace.read"), allowed),
                    input_preview=list_preview,
                    reason="Discover candidate local files before extracting or summarizing them.",
                ),
                _step(
                    intent,
                    "extract-report-file-context",
                    "Extract report file context",
                    "terminal.execution",
                    _first_allowed(("terminal.run",), allowed),
                    input_preview={
                        key: value
                        for key, value in {
                            "path": location,
                            "file_type": file_type,
                            "pattern": pattern,
                            "operation": "extract_text_for_report",
                        }.items()
                        if value
                    },
                    risk_level="medium",
                    approval_required=True,
                    depends_on=["inspect-report-file-scope"],
                    reason="Use an approved local extraction step for non-tabular report sources such as PDFs.",
                ),
                (
                    _clipboard_output_step(
                        intent,
                        allowed,
                        depends_on=["extract-report-file-context"],
                        body_source="local_file_context",
                    )
                    if _task_output_target_hint(intent.user_goal) == "clipboard"
                    else _step(
                        intent,
                        "write-report-artifact",
                        "Write report artifact",
                        "artifact.write",
                        _first_allowed(("artifact.write",), allowed),
                        input_preview={
                            "path": artifact_path,
                            "body_source": "local_file_context",
                        },
                        depends_on=["extract-report-file-context"],
                        reason="Produce the requested durable output from the inspected local files.",
                    )
                ),
            ]
            return _append_artifact_reveal_step(
                intent,
                allowed,
                steps,
                artifact_paths=[] if _task_output_target_hint(intent.user_goal) == "clipboard" else [artifact_path],
                depends_on="write-report-artifact",
            )
        if context_source:
            context_steps = _context_source_steps(
                intent,
                allowed,
                context_source,
                step_prefix="report",
                capability_id="artifact.write",
            )
            depends_on = [step.step_id for step in context_steps]
            target_app = str(intent.inputs.get("target_app_hint") or "").strip()
            if target_app:
                container_action = str(
                    intent.inputs.get("target_container_action_hint") or ""
                ).strip()
                return [
                    *context_steps,
                    _step(
                        intent,
                        "prepare-report-target-app",
                        "Prepare target app",
                        "desktop.app_control",
                        _first_allowed(
                            ("app.focus", "app.open", "app.open_and_safe_shortcut"),
                            allowed,
                        ),
                        input_preview={
                            "app_name": target_app,
                            "target_action": str(
                                intent.inputs.get("target_action_hint") or "app_paste"
                            ).strip(),
                            **(
                                {"container_action": container_action}
                                if container_action
                                else {}
                            ),
                            "body_source": "model_generated_content",
                        },
                        depends_on=depends_on,
                        reason=(
                            "After context is inspected and transformed by the model, "
                            "focus the requested app before inserting the generated content."
                        ),
                    ),
                ]
            artifact_path = _artifact_output_path(intent.user_goal, "report.md")
            steps = [
                *context_steps,
                (
                    _clipboard_output_step(
                        intent,
                        allowed,
                        depends_on=depends_on,
                        body_source=context_source,
                    )
                    if _task_output_target_hint(intent.user_goal) == "clipboard"
                    else _step(
                        intent,
                        "write-report-artifact",
                        "Write report artifact",
                        "artifact.write",
                        _first_allowed(("artifact.write",), allowed),
                        input_preview={
                            "path": artifact_path,
                            "body_source": context_source,
                        },
                        depends_on=depends_on,
                        reason="Produce the requested durable output from the inspected source.",
                    )
                ),
            ]
            return _append_artifact_reveal_step(
                intent,
                allowed,
                steps,
                artifact_paths=[] if _task_output_target_hint(intent.user_goal) == "clipboard" else [artifact_path],
                depends_on="write-report-artifact",
            )
        steps = [
            _step(
                intent,
                "gather-context",
                "Gather available context",
                "file.workspace_read",
                _first_allowed(("workspace.list", "browser.current_page", "workspace.read"), allowed),
                reason="Inspect available context before writing.",
            ),
        ]
        if _task_output_target_hint(intent.user_goal) == "clipboard":
            steps.append(
                _clipboard_output_step(
                    intent,
                    allowed,
                    depends_on=["gather-context"],
                    body_source="gathered_context",
                )
            )
        else:
            artifact_path = _artifact_output_path(intent.user_goal, "report.md")
            steps.append(
                _step(
                    intent,
                    "write-report-artifact",
                    "Write report artifact",
                    "artifact.write",
                    _first_allowed(("artifact.write",), allowed),
                    input_preview={"path": artifact_path},
                    depends_on=["gather-context"],
                    reason="Produce the requested durable output.",
                )
            )
            steps = _append_artifact_reveal_step(
                intent,
                allowed,
                steps,
                artifact_paths=[artifact_path],
                depends_on="write-report-artifact",
            )
        return steps

    def _code_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        terminal_hint = intent.inputs.get("terminal_command_hint")
        if isinstance(terminal_hint, Mapping) and str(terminal_hint.get("command") or "").strip():
            return [
                _step(
                    intent,
                    "run-terminal-command",
                    "Run terminal command",
                    "terminal.execution",
                    _first_allowed(("terminal.run",), allowed),
                    input_preview={"command": str(terminal_hint.get("command") or "").strip()},
                    risk_level="high",
                    approval_required=True,
                    reason="Run exactly the terminal command explicitly requested by the user.",
                )
            ]
        return [
            _step(
                intent,
                "inspect-workspace",
                "Inspect workspace",
                "file.workspace_read",
                _first_allowed(("workspace.list", "workspace.read"), allowed),
                reason="Understand the repo before editing or testing.",
            ),
            _step(
                intent,
                "write-code-report",
                "Write result artifact",
                "artifact.write",
                _first_allowed(("artifact.write",), allowed),
                input_preview={"path": "code-task-summary.md"},
                depends_on=["inspect-workspace"],
                reason="Summarize changes or findings for replay.",
            ),
        ]

    def _file_organization_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        location_hint = str(intent.inputs.get("location_hint") or "").strip()
        operation_hint = str(intent.inputs.get("operation_hint") or "").strip()
        file_type_hint = str(intent.inputs.get("file_type_hint") or "").strip()
        file_pattern_hint = str(intent.inputs.get("file_pattern_hint") or "").strip()
        destination_hint = str(intent.inputs.get("destination_hint") or "").strip()
        inventory_only = operation_hint in {"inventory", "duplicate_inventory"}
        duplicate_inventory = operation_hint == "duplicate_inventory"
        artifact_path = "file-organization-plan.md"
        if duplicate_inventory:
            artifact_path = "duplicate-file-report.md"
        elif inventory_only:
            artifact_path = "file-inventory.md"
        plan_title = (
            "Write duplicate file report"
            if duplicate_inventory
            else "Write file inventory"
            if inventory_only
            else "Write file organization plan"
        )
        plan_reason = (
            "Create a replayable duplicate-file report without changing files."
            if duplicate_inventory
            else "Create a replayable file inventory artifact without changing files."
            if inventory_only
            else "Create a reviewable plan before moving, renaming, archiving, or deleting files."
        )
        steps = [
            _step(
                intent,
                "inspect-file-scope",
                "Inspect file scope",
                "file.organization",
                _first_allowed(("workspace.list", "desktop.reveal_path", "desktop.open_path"), allowed),
                input_preview=_file_scope_input_preview(
                    location_hint,
                    file_type_hint,
                    file_pattern_hint,
                ),
                reason="List or reveal the requested file scope before planning changes.",
            ),
            _step(
                intent,
                "write-file-organization-plan",
                plan_title,
                "artifact.write",
                _first_allowed(("artifact.write",), allowed),
                input_preview={"path": artifact_path},
                depends_on=["inspect-file-scope"],
                reason=plan_reason,
            ),
        ]
        if inventory_only:
            return steps
        return [
            *steps,
            _step(
                intent,
                "apply-file-organization",
                "Apply file organization",
                "file.organization",
                _first_allowed(_file_apply_tool_candidates(operation_hint), allowed),
                input_preview=_file_apply_input_preview(
                    location_hint,
                    operation_hint,
                    file_type_hint,
                    file_pattern_hint,
                    destination_hint,
                ),
                action="apply_file_changes",
                risk_level="high",
                approval_required=True,
                depends_on=["write-file-organization-plan"],
                reason="Apply file changes only through an approval-gated execution step.",
            ),
        ]

    def _file_access_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        action = str(intent.inputs.get("action") or "").strip()
        path = str(intent.inputs.get("path") or "").strip()
        reveal = action == "reveal_path"
        tool_name = "desktop.reveal_path" if reveal else "desktop.open_path"
        return [
            _step(
                intent,
                "reveal-local-path" if reveal else "open-local-path",
                "Reveal local path in Finder" if reveal else "Open local path",
                "file.desktop_access",
                _first_allowed((tool_name,), allowed),
                input_preview={"path": path} if path else {},
                reason="Use the dedicated local file tool instead of treating paths as apps.",
            )
        ]

    def _schedule_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        tool_name, input_preview = schedule_tool_preview(intent.user_goal, allowed)
        context_source = str(intent.inputs.get("context_source") or "").strip()
        if context_source and not input_preview:
            context_steps = _context_source_steps(
                intent,
                allowed,
                context_source,
                step_prefix="schedule",
                capability_id="schedule.reminder",
            )
            depends_on = [step.step_id for step in context_steps]
            return [
                *context_steps,
                _step(
                    intent,
                    "create-schedule-item-from-context",
                    "Create schedule item from captured context",
                    "schedule.reminder",
                    _first_allowed(("reminders.create", "calendar.create_event", "future_task.schedule"), allowed),
                    input_preview={"body_source": context_source},
                    risk_level="medium",
                    approval_required=True,
                    depends_on=depends_on,
                    reason="Inspect the requested source before creating the reminder or calendar item.",
                ),
            ]
        return [
            _step(
                intent,
                "create-schedule-item",
                "Create schedule item",
                "schedule.reminder",
                tool_name,
                input_preview=input_preview,
                risk_level="medium",
                approval_required=True,
                reason="Create only explicit user-requested reminders, calendar events, or future tasks.",
            )
        ]

    def _information_capture_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        tool_name, input_preview = capture_tool_preview(intent.inputs, allowed)
        if tool_name:
            return [
                _step(
                    intent,
                    "create-note",
                    "Create note",
                    "information.capture",
                    tool_name,
                    input_preview=input_preview,
                    reason="Use the note creation tool for explicit user-provided content.",
                )
            ]
        body = str(intent.inputs.get("body") or "").strip()
        artifact_tool = _first_allowed(("artifact.write",), allowed)
        if body and artifact_tool:
            return [
                _step(
                    intent,
                    "write-note-artifact",
                    "Write note artifact",
                    "information.capture",
                    artifact_tool,
                    input_preview={"path": "captured-note.md", "content": body},
                    reason="Capture explicit user-provided note text as a replayable artifact.",
                )
            ]

        source = str(intent.inputs.get("source") or "").strip()
        context_steps = _context_source_steps(
            intent,
            allowed,
            source,
            step_prefix="note",
            capability_id="information.capture",
        )
        depends_on = [step.step_id for step in context_steps]
        return [
            *context_steps,
            _step(
                intent,
                "create-note-from-context",
                "Create note from captured context",
                "information.capture",
                _first_allowed(("notes.create",), allowed),
                input_preview={"body_source": source} if source else {},
                depends_on=depends_on,
                reason="Inspect the requested source before creating a note from it.",
            ),
        ]

    def _communication_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        context_source = str(intent.inputs.get("context_source") or "").strip()
        direct_message = intent.inputs.get("direct_message_hint")
        draft_preview = (
            _communication_draft_input_preview(direct_message)
            if isinstance(direct_message, Mapping)
            else {}
        )
        compose_tool = _first_allowed(
            (
                "app.open_and_type_into_ui_element",
                "app.focus_and_type_into_ui_element",
                "desktop.type_into_ui_element",
                "app.open_and_safe_type_text",
                "app.focus_and_safe_type_text",
                "desktop.safe_type_text",
                "artifact.write",
            ),
            allowed,
        )
        if _communication_draft_should_use_artifact(direct_message, allowed):
            compose_tool = "artifact.write"
        if isinstance(direct_message, Mapping):
            direct_steps = _direct_communication_steps(intent, allowed, direct_message)
            if direct_steps:
                return direct_steps
            if str(direct_message.get("body_source") or "").strip() == "app_search_result":
                context_steps = _app_search_result_context_steps(
                    intent,
                    allowed,
                    direct_message,
                    step_prefix="communication",
                    capability_id="communication.compose",
                )
                if context_steps:
                    draft_input = _communication_draft_input_preview(direct_message)
                    draft_input.setdefault("body_source", "app_search_result")
                    return [
                        *context_steps,
                        _step(
                            intent,
                            "draft-communication-from-context",
                            "Draft communication from captured context",
                            "communication.compose",
                            compose_tool,
                            input_preview=draft_input,
                            risk_level="medium",
                            approval_required=True,
                            depends_on=[context_steps[-1].step_id],
                            reason=(
                                "Inspect the requested app search result before drafting "
                                "the communication; final sending remains approval-gated."
                            ),
                        ),
                    ]
        if context_source:
            context_steps = _context_source_steps(
                intent,
                allowed,
                context_source,
                step_prefix="communication",
                capability_id="communication.compose",
            )
            depends_on = [step.step_id for step in context_steps]
            draft_input = {"body_source": context_source}
            transform = str(intent.inputs.get("content_transform_hint") or "").strip()
            if transform:
                draft_input["transform"] = transform
            return [
                *context_steps,
                _step(
                    intent,
                    "draft-communication-from-context",
                    "Draft communication from captured context",
                    "communication.compose",
                    compose_tool,
                    input_preview=draft_input,
                    risk_level="medium",
                    approval_required=True,
                    depends_on=depends_on,
                    reason=(
                        "Inspect the requested source before drafting the communication; "
                        "final sending remains approval-gated."
                    ),
                ),
            ]
        if compose_tool == "artifact.write":
            return [
                _step(
                    intent,
                    "draft-communication",
                    "Draft communication",
                    "communication.compose",
                    compose_tool,
                    input_preview=draft_preview,
                    risk_level="medium",
                    approval_required=True,
                    reason=(
                        "Prepare the user-requested communication as a draft artifact; "
                        "final sending remains approval-gated."
                    ),
                )
            ]
        depends_on = ["discover-communication-surface"]
        return [
            _step(
                intent,
                "discover-communication-surface",
                "Discover communication surface",
                "desktop.app_discovery",
                _first_allowed(("desktop.running_apps", "desktop.active_window", "screen.capture"), allowed),
                reason="Inspect the current app/window before preparing a message.",
            ),
            _step(
                intent,
                "draft-communication",
                "Draft communication",
                "communication.compose",
                compose_tool,
                input_preview=draft_preview,
                risk_level="medium",
                approval_required=True,
                depends_on=depends_on,
                reason="Prepare the user-requested communication through observable tools; final sending remains approval-gated.",
            ),
        ]

    def _clipboard_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        action = str(intent.inputs.get("action") or "").strip()
        tool_name, input_preview = clipboard_tool_preview(intent.inputs, allowed)
        if action == "copy_selection_read":
            return [
                _step(
                    intent,
                    "copy-selected-text",
                    "Copy selected text",
                    "clipboard.read_write",
                    _first_allowed(("desktop.safe_shortcut",), allowed),
                    input_preview={"action": "copy"},
                    reason="Use the standard copy shortcut only for an explicit selected-text read request.",
                ),
                _step(
                    intent,
                    "read-clipboard",
                    "Read clipboard",
                    "clipboard.read_write",
                    tool_name,
                    depends_on=["copy-selected-text"],
                    reason="Read the clipboard after copying the selected text.",
                ),
            ]
        if action == "write":
            return [
                _step(
                    intent,
                    "write-clipboard",
                    "Write clipboard",
                    "clipboard.read_write",
                    tool_name,
                    input_preview=input_preview,
                    reason="Write only explicit user-provided text to the clipboard.",
                )
            ]
        return [
            _step(
                intent,
                "read-clipboard",
                "Read clipboard",
                "clipboard.read_write",
                tool_name,
                reason="Read the clipboard only because the user explicitly requested it.",
            )
        ]


def _empty_intent(kind: str, text: str) -> TaskIntentSnapshot:
    return TaskIntentSnapshot(
        intent_id=_stable_id("intent", kind, text),
        kind=kind,
        title=kind.replace("_", " ").title(),
        user_goal=text,
        confidence=0.0,
    )


def _step(
    intent: TaskIntentSnapshot,
    step_key: str,
    title: str,
    capability_id: str,
    tool_name: str | None,
    *,
    input_preview: dict[str, Any] | None = None,
    risk_level: str = "low",
    approval_required: bool = False,
    depends_on: list[str] | None = None,
    reason: str = "",
    fallback_tools: list[str] | None = None,
    action: str = "",
) -> ToolPlanStepSnapshot:
    return ToolPlanStepSnapshot(
        step_id=step_key,
        title=title,
        capability_id=capability_id,
        action=action or _step_action(step_key, capability_id, tool_name),
        tool_name=tool_name,
        input_preview=input_preview or {},
        risk_level=risk_level,
        approval_required=approval_required,
        depends_on=depends_on or [],
        reason=reason,
        fallback_tools=fallback_tools or [],
        status="planned" if tool_name else "unavailable",
    )


def _spreadsheet_app_open_step(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
) -> ToolPlanStepSnapshot | None:
    app_name = str(intent.inputs.get("spreadsheet_app_hint") or "").strip()
    if not app_name:
        return None
    return _step(
        intent,
        "open-spreadsheet-app",
        "Open requested spreadsheet app",
        "desktop.app_control",
        _first_allowed(("app.open",), allowed),
        input_preview={"app_name": app_name},
        action="open_app",
        reason=(
            "The user explicitly requested a spreadsheet app; open it while keeping "
            "analysis on reproducible local data tools."
        ),
    )


def _data_file_open_step(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    *,
    source_hint: str,
    depends_on: Iterable[str] = (),
) -> ToolPlanStepSnapshot | None:
    if not str(intent.inputs.get("spreadsheet_app_hint") or "").strip():
        return None
    clean_source_hint = str(source_hint or "").strip()
    if not clean_source_hint:
        return None
    tool_name = _first_allowed(("desktop.open_path",), allowed)
    if not tool_name:
        return None
    return _step(
        intent,
        "open-data-file",
        "Open data file",
        "file.desktop_access",
        tool_name,
        input_preview={"path": clean_source_hint},
        depends_on=list(depends_on),
        action="open_path",
        risk_level="low",
        approval_required=False,
        reason=(
            "Open the explicit local data file on the desktop so the requested spreadsheet app "
            "path is observable while data.analyze keeps the reproducible analysis artifact."
        ),
    )


def _with_step_dependencies(
    step: ToolPlanStepSnapshot,
    depends_on: Iterable[str],
) -> ToolPlanStepSnapshot:
    clean_depends_on = [
        str(item or "").strip()
        for item in depends_on
        if str(item or "").strip()
    ]
    return step.model_copy(update={"depends_on": clean_depends_on})


def _service_step(
    intent: TaskIntentSnapshot,
    capability_id: str,
    title: str,
    allowed: set[str] | None = None,
) -> ToolPlanStepSnapshot:
    target_name = str(intent.inputs.get("target_name_hint") or "").strip()
    tool_name = _first_allowed(_service_tool_candidates(capability_id), allowed)
    return ToolPlanStepSnapshot(
        step_id=capability_id.replace(".", "-"),
        title=title,
        capability_id=capability_id,
        action=_service_action(capability_id),
        tool_name=tool_name,
        input_preview={"target_name": target_name} if target_name else {},
        reason=(
            "Use the shared Agent Studio service orchestration entrypoint when available; "
            "otherwise keep this as an observable Studio-managed step."
        ),
    )


def _first_allowed(tools: Iterable[str], allowed: set[str] | None) -> str | None:
    for tool in tools:
        if allowed is None or tool in allowed:
            return tool
    return None


def _app_scoped_safe_shortcut_split_tools(
    app_name: str,
    mode: str,
    allowed: set[str] | None,
) -> tuple[str | None, str | None]:
    return _app_scoped_operation_split_tools(
        app_name,
        mode,
        ("desktop.safe_shortcut",),
        allowed,
    )


def _app_scoped_operation_split_tools(
    app_name: str,
    mode: str,
    operation_tools: Iterable[str],
    allowed: set[str] | None,
) -> tuple[str | None, str | None]:
    if not app_name:
        return None, None
    app_tool = _first_allowed(app_control_tool_candidates(mode or "focus"), allowed)
    operation_tool = _first_allowed(operation_tools, allowed)
    if not app_tool or not operation_tool:
        return None, None
    return app_tool, operation_tool


def _append_app_scoped_safe_shortcut_steps(
    steps: list[ToolPlanStepSnapshot],
    intent: TaskIntentSnapshot,
    *,
    step_id: str,
    title: str,
    app_name: str,
    mode: str,
    shortcut_action: str,
    allowed: set[str] | None,
    depends_on: list[str],
    prepare_reason: str,
    shortcut_reason: str,
    fallback_reason: str,
) -> str:
    clean_mode = mode or "focus"
    app_foreground_tool = _first_allowed(
        app_foreground_tool_candidates(clean_mode, "safe_shortcut"),
        allowed,
    )
    if app_name and app_foreground_tool:
        steps.append(
            _step(
                intent,
                step_id,
                title,
                "desktop.app_control",
                app_foreground_tool,
                input_preview={"app_name": app_name, "action": shortcut_action},
                depends_on=depends_on,
                action="shortcut",
                risk_level="low",
                approval_required=False,
                reason=fallback_reason,
            )
        )
        return step_id

    app_tool, shortcut_tool = _app_scoped_safe_shortcut_split_tools(
        app_name,
        clean_mode,
        allowed,
    )
    if app_name and app_tool and shortcut_tool:
        steps.append(
            _step(
                intent,
                "open-or-focus-app",
                "Open or focus app",
                "desktop.app_control",
                app_tool,
                input_preview={"app_name": app_name},
                depends_on=depends_on,
                reason=prepare_reason,
            )
        )
        steps.append(
            _step(
                intent,
                step_id,
                title,
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": shortcut_action},
                depends_on=["open-or-focus-app"],
                action="shortcut",
                risk_level="low",
                approval_required=False,
                reason=shortcut_reason,
            )
        )
        return step_id

    steps.append(
        _step(
            intent,
            step_id,
            title,
            "desktop.app_control",
            app_foreground_tool,
            input_preview={"app_name": app_name, "action": shortcut_action},
            depends_on=depends_on,
            action="shortcut",
            risk_level="low",
            approval_required=False,
            reason=fallback_reason,
        )
    )
    return step_id


def _context_source_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    source: str,
    *,
    step_prefix: str,
    capability_id: str,
) -> list[ToolPlanStepSnapshot]:
    if source == "selection":
        steps = []
        copy_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
        if copy_tool:
            steps.append(
                _step(
                    intent,
                    f"copy-selected-{step_prefix}-context",
                    "Copy selected context",
                    _context_source_capability_id(source, copy_tool, capability_id),
                    copy_tool,
                    input_preview={"action": "copy"},
                    reason="Copy the explicit user-selected text before using it as task context.",
                )
            )
        read_tool = _first_allowed(("clipboard.read",), allowed)
        if read_tool:
            steps.append(
                _step(
                    intent,
                    f"read-{step_prefix}-context",
                    "Read captured context",
                    _context_source_capability_id(source, read_tool, capability_id),
                    read_tool,
                    depends_on=[f"copy-selected-{step_prefix}-context"] if copy_tool else [],
                    reason="Read the copied text so the next step uses inspected context.",
                )
            )
        return steps

    if source == "clipboard":
        tool_name = _first_allowed(("clipboard.read",), allowed)
        return [
            _step(
                intent,
                f"read-{step_prefix}-context",
                "Read captured context",
                _context_source_capability_id(source, tool_name, capability_id),
                tool_name,
                reason="Read the explicitly requested clipboard contents before using them as task context.",
            )
        ]

    if source == "current_page_link":
        tool_name = _first_allowed(("browser.current_page", "desktop.safe_shortcut"), allowed)
        payload = {"action": "copy_current_page_link"} if tool_name == "desktop.safe_shortcut" else {}
        return [
            _step(
                intent,
                f"read-{step_prefix}-context",
                "Read captured context",
                _context_source_capability_id(source, tool_name, capability_id),
                tool_name,
                input_preview=payload,
                reason="Capture the current page reference before using it as task context.",
            )
        ]

    if source == "current_page_content":
        tool_name = _first_allowed(
            ("browser.extract_text", "browser.current_page", "desktop.ui_elements", "screen.capture"),
            allowed,
        )
        return [
            _step(
                intent,
                f"read-{step_prefix}-context",
                "Read captured context",
                _context_source_capability_id(source, tool_name, capability_id),
                tool_name,
                input_preview=_information_capture_context_payload(tool_name),
                reason="Inspect the current page or window text before using it as task context.",
            )
        ]

    if source == "visible_text":
        tool_name = _first_allowed(("desktop.ui_elements", "screen.capture"), allowed)
        return [
            _step(
                intent,
                f"read-{step_prefix}-context",
                "Read captured context",
                _context_source_capability_id(source, tool_name, capability_id),
                tool_name,
                input_preview=_information_capture_context_payload(tool_name),
                reason="Inspect visible text before using it as task context.",
            )
        ]

    if source == "file":
        file_context = intent.inputs.get("file_context_hint")
        if not isinstance(file_context, Mapping):
            return []
        path = str(file_context.get("path") or "").strip()
        if not path:
            return []
        pattern = str(file_context.get("pattern") or "").strip()
        file_type = str(file_context.get("file_type") or "").strip()
        tool_candidates = (
            ("workspace.list", "workspace.read")
            if pattern and not _looks_like_specific_data_source_path(path)
            else ("workspace.read", "workspace.list")
        )
        tool_name = _first_allowed(tool_candidates, allowed)
        input_preview: dict[str, str] = {"path": path}
        if tool_name == "workspace.list":
            if pattern:
                input_preview["pattern"] = pattern
            if file_type:
                input_preview["file_type"] = file_type
        return [
            _step(
                intent,
                f"read-{step_prefix}-context",
                "Read file context",
                _context_source_capability_id(source, tool_name, capability_id),
                tool_name,
                input_preview=input_preview,
                reason="Read or list the explicit local file context before using it in the task.",
            )
        ]

    return []


def _app_search_result_context_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    direct_message: Mapping[str, Any],
    *,
    step_prefix: str,
    capability_id: str,
) -> list[ToolPlanStepSnapshot]:
    source_app = str(direct_message.get("source_app_name") or "").strip()
    source_scope = str(direct_message.get("source_scope") or "").strip()
    query = _clean_app_search_query(
        str(direct_message.get("source_app_search_query") or "")
    )
    if not query:
        return []

    steps: list[ToolPlanStepSnapshot] = []
    depends_on: list[str] = []
    source_mode = str(direct_message.get("source_app_mode") or "focus").strip() or "focus"
    if source_app:
        discover_tool = _first_allowed(("desktop.list_apps", "desktop.running_apps"), allowed)
        discover_input = (
            {"query": source_app, "limit": 20}
            if discover_tool == "desktop.list_apps"
            else {}
        )
        steps.append(
            _step(
                intent,
                "discover-app-search-source",
                "Discover source app",
                "desktop.app_discovery",
                discover_tool,
                input_preview=discover_input,
                action="list_apps",
                reason="Discover the requested source app before searching inside it.",
            )
        )
        depends_on = ["discover-app-search-source"]
        source_tool_candidates = (
            ("app.open", "app.focus") if source_mode == "open" else ("app.focus", "app.open")
        )
        source_tool = _first_allowed(source_tool_candidates, allowed)
        steps.append(
            _step(
                intent,
                "open-app-search-source",
                "Open or focus source app",
                "desktop.app_control",
                source_tool,
                input_preview={"app_name": source_app},
                depends_on=depends_on,
                action="open_app" if source_tool == "app.open" else "focus_app",
                reason="Prepare the source app before using its in-app search.",
            )
        )
        depends_on = ["open-app-search-source"]
        if source_tool == "app.open" and "app.focus" in (allowed or set()):
            steps.append(
                _step(
                    intent,
                    "focus-app-search-source",
                    "Focus source app",
                    "desktop.app_control",
                    "app.focus",
                    input_preview={"app_name": source_app},
                    depends_on=depends_on,
                    action="focus_app",
                    reason="Focus the source app after opening it.",
                )
            )
            depends_on = ["focus-app-search-source"]
    elif source_scope == "foreground":
        discover_tool = _first_allowed(("desktop.running_apps", "desktop.active_window"), allowed)
        steps.append(
            _step(
                intent,
                "discover-app-search-source",
                "Discover foreground app",
                "desktop.app_discovery",
                discover_tool,
                input_preview={},
                action="active_window" if discover_tool == "desktop.active_window" else "list_apps",
                reason="Inspect the foreground app before searching inside it.",
            )
        )
        depends_on = ["discover-app-search-source"]

    shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
    shortcut_input = {"action": "find"}
    if not shortcut_tool and source_app:
        shortcut_tool = _first_allowed(
            app_foreground_tool_candidates(source_mode, "safe_shortcut"),
            allowed,
        )
        if shortcut_tool:
            shortcut_input = {"app_name": source_app, "action": "find"}
    type_tool, type_input = _safe_type_text_operation_preview(
        app_name=source_app,
        mode=source_mode,
        allowed=allowed,
        payload={"text": query},
    )
    submit_tool = _first_allowed(("desktop.search_submit",), allowed)
    read_tool = _first_allowed(("desktop.ui_elements", "screen.capture"), allowed)
    read_input = (
        {"role_filter": "text", "limit": 120}
        if read_tool == "desktop.ui_elements"
        else {"reason": "Read the source app search result before composing."}
        if read_tool == "screen.capture"
        else {}
    )
    if source_app and read_tool == "desktop.ui_elements":
        read_input["app_name"] = source_app

    steps.extend(
        [
            _step(
                intent,
                "focus-app-search-field",
                "Focus app search field",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview=shortcut_input,
                depends_on=depends_on,
                action="shortcut",
                reason="Open the source app search field with a safe shortcut.",
            ),
            _step(
                intent,
                "type-app-search-query",
                "Type app search query",
                "desktop.ui_operation",
                type_tool,
                input_preview=type_input,
                depends_on=["focus-app-search-field"],
                action="type",
                reason="Type only the explicit source-app search query.",
            ),
            _step(
                intent,
                "submit-app-search",
                "Submit app search",
                "desktop.ui_operation",
                submit_tool,
                input_preview={},
                depends_on=["type-app-search-query"],
                action="submit_search",
                reason="Submit the source-app search before reading the result.",
            ),
            _step(
                intent,
                f"read-{step_prefix}-context",
                "Read app search result",
                _context_source_capability_id("app_search_result", read_tool, capability_id),
                read_tool,
                input_preview=read_input,
                depends_on=["submit-app-search"],
                action="read_ui",
                reason=(
                    "Read the app search result so the model can generate the requested "
                    "message body from observed content."
                ),
            ),
        ]
    )
    return steps


def _data_analysis_context_source_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    source: str,
) -> list[ToolPlanStepSnapshot]:
    if (
        source in {"current_page_content", "visible_text"}
        and _contains_any(
            intent.user_goal,
            ("表格", "数据", "table", "tabular", "spreadsheet", "data", "csv"),
        )
    ):
        if source == "visible_text":
            visible_context_tool = _first_allowed(("desktop.ui_elements", "screen.capture"), allowed)
            if visible_context_tool:
                return _context_source_steps(
                    intent,
                    allowed,
                    source,
                    step_prefix="data",
                    capability_id="data.analysis",
                )
        browser_context_tool = (
            _first_allowed(("browser.extract_text", "browser.current_page"), allowed)
            if source == "current_page_content"
            else None
        )
        if source == "current_page_content" and browser_context_tool:
            return _context_source_steps(
                intent,
                allowed,
                source,
                step_prefix="data",
                capability_id="data.analysis",
            )
        shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
        read_tool = _first_allowed(("clipboard.read",), allowed)
        if shortcut_tool and read_tool:
            return [
                _step(
                    intent,
                    "select-current-data-context",
                    "Select current data context",
                    "desktop.ui_operation",
                    shortcut_tool,
                    input_preview={"action": "select_all"},
                    reason="Select visible foreground data before copying it for local analysis.",
                ),
                _step(
                    intent,
                    "copy-current-data-context",
                    "Copy current data context",
                    "clipboard.read_write",
                    shortcut_tool,
                    input_preview={"action": "copy"},
                    depends_on=["select-current-data-context"],
                    reason="Copy the selected foreground table or data into the clipboard.",
                ),
                _step(
                    intent,
                    "read-data-context",
                    "Read captured context",
                    "clipboard.read_write",
                    read_tool,
                    depends_on=["copy-current-data-context"],
                    reason="Read the copied foreground data before running analysis.",
                ),
            ]
    return _context_source_steps(
        intent,
        allowed,
        source,
        step_prefix="data",
        capability_id="data.analysis",
    )


def _dynamic_context_ui_transfer_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    hint: Mapping[str, Any],
    base_steps: list[ToolPlanStepSnapshot],
) -> list[ToolPlanStepSnapshot]:
    source = str(hint.get("source") or "").strip()
    action = str(hint.get("action") or "").strip()
    target_kind = str(hint.get("target_kind") or "").strip()
    target = str(hint.get("target") or "").strip()
    app_name = str(hint.get("app_name") or "").strip()
    mode = str(hint.get("mode") or "focus").strip() or "focus"
    source_requires_shortcut = source in {
        "selection",
        "current_page_link",
        "current_page_content",
    }
    target_requires_paste = target_kind in {"app_paste", "current_input", "ui_field"}
    shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
    if (source_requires_shortcut or target_requires_paste) and not shortcut_tool:
        return list(base_steps)

    app_paste_tool: str | None = None
    field_click_app_tool: str | None = None
    field_click_tool: str | None = None
    if target_kind == "app_paste":
        if not app_name:
            return list(base_steps)
        app_paste_app_tool, app_paste_shortcut_tool = _app_scoped_safe_shortcut_split_tools(
            app_name,
            mode,
            allowed,
        )
        app_paste_tool = _first_allowed(
            app_foreground_tool_candidates(mode, "safe_shortcut"),
            allowed,
        )
        if not ((app_paste_app_tool and app_paste_shortcut_tool) or app_paste_tool):
            return list(base_steps)
    elif target_kind == "ui_field":
        if not target:
            return list(base_steps)
        if app_name:
            field_click_app_tool, field_click_tool = _app_scoped_operation_split_tools(
                app_name,
                mode,
                ("desktop.click_ui_element",),
                allowed,
            )
            field_click_app_scoped_tool = _first_allowed(
                app_foreground_tool_candidates(mode, "click_ui_element"),
                allowed,
            )
            if not field_click_tool:
                field_click_tool = field_click_app_scoped_tool
        else:
            field_click_tool = _first_allowed(("desktop.click_ui_element",), allowed)
        if not field_click_tool:
            return list(base_steps)
    elif action != "copy_context" and target_kind != "current_input":
        return list(base_steps)

    steps = list(base_steps)
    previous_step_id = steps[-1].step_id if steps else ""

    def append_step(step: ToolPlanStepSnapshot) -> None:
        nonlocal previous_step_id
        steps.append(step)
        previous_step_id = step.step_id

    if source == "selection":
        append_step(
            _step(
                intent,
                "copy-selected-dynamic-context",
                "Copy selected context",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "copy"},
                depends_on=[previous_step_id] if previous_step_id else [],
                reason="Copy the selected content before transferring it to the requested UI target.",
            )
        )
    elif source == "current_page_link":
        append_step(
            _step(
                intent,
                "copy-current-page-link-context",
                "Copy current page link",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "copy_current_page_link"},
                depends_on=[previous_step_id] if previous_step_id else [],
                reason="Copy the current page link before transferring it to the requested UI target.",
            )
        )
    elif source == "current_page_content":
        append_step(
            _step(
                intent,
                "select-current-page-content",
                "Select current page content",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "select_all"},
                depends_on=[previous_step_id] if previous_step_id else [],
                reason="Select the current page content before copying it for transfer.",
            )
        )
        append_step(
            _step(
                intent,
                "copy-current-page-content",
                "Copy current page content",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "copy"},
                depends_on=["select-current-page-content"],
                reason="Copy the selected page content before transferring it to the requested UI target.",
            )
        )
    elif source != "clipboard":
        return list(base_steps)

    if action == "copy_context":
        return steps

    if target_kind == "app_paste":
        if app_paste_app_tool and app_paste_shortcut_tool:
            append_step(
                _step(
                    intent,
                    "open-or-focus-app",
                    "Open or focus app",
                    "desktop.app_control",
                    app_paste_app_tool,
                    input_preview={"app_name": app_name},
                    depends_on=[previous_step_id] if previous_step_id else [],
                    reason="Prepare the requested app before pasting the captured context.",
                )
            )
            append_step(
                _step(
                    intent,
                    "paste-context-into-app",
                    "Paste context into app",
                    "desktop.ui_operation",
                    app_paste_shortcut_tool,
                    input_preview={"action": "paste"},
                    depends_on=[previous_step_id],
                    action="shortcut",
                    reason="Paste the captured context into the foreground app.",
                )
            )
        else:
            append_step(
                _step(
                    intent,
                    "paste-context-into-app",
                    "Paste context into app",
                    "desktop.app_control",
                    app_paste_tool,
                    input_preview={"app_name": app_name, "action": "paste"},
                    depends_on=[previous_step_id] if previous_step_id else [],
                    action="shortcut",
                    reason="Focus or open the requested app and paste the captured context.",
                )
            )
    else:
        if target_kind == "ui_field":
            field_payload = {
                "target": target,
                "role_filter": "text",
                "limit": 80,
                "click_count": 1,
            }
            if field_click_app_tool:
                append_step(
                    _step(
                        intent,
                        "open-or-focus-app",
                        "Open or focus app",
                        "desktop.app_control",
                        field_click_app_tool,
                        input_preview={"app_name": app_name},
                        depends_on=[previous_step_id] if previous_step_id else [],
                        reason="Prepare the requested app before focusing the transfer field.",
                    )
                )
            elif field_click_tool and field_click_tool.startswith("app."):
                field_payload = {"app_name": app_name, **field_payload}
            append_step(
                _step(
                    intent,
                    "focus-context-transfer-field",
                    "Focus transfer field",
                    "desktop.ui_operation",
                    field_click_tool,
                    input_preview=field_payload,
                    depends_on=[previous_step_id] if previous_step_id else [],
                    action="click",
                    reason="Focus the requested text field before pasting the captured context.",
                )
            )
        append_step(
            _step(
                intent,
                "paste-context-into-field",
                "Paste context",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "paste"},
                depends_on=[previous_step_id] if previous_step_id else [],
                action="shortcut",
                reason="Paste the captured context into the focused input.",
            )
        )

    verify_tool = _first_allowed(
        ("desktop.ui_elements", "desktop.active_window", "screen.capture"),
        allowed,
    )
    steps.append(
        _step(
            intent,
            "verify-desktop-result",
            "Verify desktop result",
            "desktop.app_discovery",
            verify_tool,
            input_preview=_desktop_verify_input_preview(
                verify_tool,
                app_name=app_name,
                operation_preview={"target": target} if target else {},
            ),
            depends_on=[previous_step_id] if previous_step_id else [],
            reason="Observe the destination UI after transferring context.",
        )
    )
    return steps


def _file_scope_input_preview(
    location_hint: str,
    file_type_hint: str,
    file_pattern_hint: str,
) -> dict[str, str]:
    preview: dict[str, str] = {}
    if location_hint:
        preview["path"] = location_hint
    if file_type_hint:
        preview["file_type"] = file_type_hint
    if file_pattern_hint:
        preview["pattern"] = file_pattern_hint
    return preview


def _data_source_inspect_input_preview(path: str, source_kind: str) -> dict[str, str]:
    preview: dict[str, str] = {}
    clean_path = str(path or "").strip()
    if clean_path:
        preview["path"] = clean_path
    pattern = _data_source_pattern_hint(source_kind)
    if pattern and not _looks_like_specific_data_source_path(clean_path):
        preview["pattern"] = pattern
        preview["file_type"] = str(source_kind or "").strip()
    return preview


def _scoped_data_source_path(source_hint: str, source_scope: str) -> str:
    clean_source = str(source_hint or "").strip()
    clean_scope = str(source_scope or "").strip()
    if (
        clean_source
        and clean_scope
        and not re.match(r"^(?:~|/|\.{1,2}/)", clean_source)
        and "/" not in clean_source
        and "\\" not in clean_source
    ):
        return f"{clean_scope.rstrip('/')}/{clean_source}"
    return clean_source


def _data_source_pattern_hint(source_kind: str) -> str:
    return {
        "csv": "*.csv",
        "tsv": "*.tsv",
        "xlsx": "*.xlsx",
        "xls": "*.xls",
        "jsonl": "*.jsonl",
        "json": "*.json",
        "parquet": "*.parquet",
        "text": "*.txt",
        "text_table": "*.{csv,tsv,xls,xlsx,json,jsonl,txt,md,markdown}",
    }.get(str(source_kind or "").strip().lower(), "")


def _looks_like_specific_data_source_path(path: str) -> bool:
    return bool(
        re.search(
            r"\.(?:csv|tsv|xlsx|xls|jsonl|json|parquet|txt|md|markdown)$",
            str(path or "").strip(),
            flags=re.IGNORECASE,
        )
    )


def _file_apply_input_preview(
    location_hint: str,
    operation_hint: str,
    file_type_hint: str = "",
    file_pattern_hint: str = "",
    destination_hint: str = "",
) -> dict[str, str]:
    preview: dict[str, str] = {}
    if location_hint:
        preview["path"] = location_hint
    if operation_hint:
        preview["operation"] = operation_hint
    if file_type_hint:
        preview["file_type"] = file_type_hint
    if file_pattern_hint:
        preview["pattern"] = file_pattern_hint
    if destination_hint:
        preview["destination"] = destination_hint
    return preview


def _file_apply_tool_candidates(operation_hint: str) -> tuple[str, ...]:
    operation = str(operation_hint or "").strip()
    if operation in {"organize", "archive", "move"}:
        return ("file.organize", "terminal.run")
    return ("terminal.run",)


def _context_source_capability_id(source: str, tool_name: str | None, fallback: str) -> str:
    clean_tool = str(tool_name or "").strip()
    if source in {"selection", "clipboard"}:
        return "clipboard.read_write"
    if source == "app_search_result":
        return "desktop.app_discovery"
    if source in {"current_page_link", "current_page_content"}:
        if clean_tool.startswith("browser."):
            return "browser.research"
        if clean_tool == "desktop.safe_shortcut":
            return "desktop.ui_operation"
        if clean_tool in {"desktop.ui_elements", "screen.capture"}:
            return "desktop.app_discovery"
    if source == "visible_text":
        return "desktop.app_discovery"
    if source == "file":
        return "file.workspace_read"
    return fallback


def _context_source_required_capability(source: str) -> str:
    clean_source = str(source or "").strip()
    if clean_source in {"selection", "clipboard"}:
        return "clipboard.read_write"
    if clean_source in {"current_page_link", "current_page_content"}:
        return "browser.research"
    if clean_source == "visible_text":
        return "desktop.app_discovery"
    if clean_source == "file":
        return "file.workspace_read"
    return "artifact.write"


def _unique_capabilities(capabilities: Iterable[str]) -> list[str]:
    result: list[str] = []
    for capability in capabilities:
        clean_capability = str(capability or "").strip()
        if clean_capability and clean_capability not in result:
            result.append(clean_capability)
    return result


def _direct_communication_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    direct_message: Mapping[str, Any],
) -> list[ToolPlanStepSnapshot]:
    app_name = str(direct_message.get("app_name") or "").strip()
    recipient = str(direct_message.get("recipient") or "").strip()
    body = str(direct_message.get("body") or "").strip()
    body_source = str(direct_message.get("body_source") or "").strip()
    transform = str(direct_message.get("content_transform_hint") or "").strip()
    channel = str(direct_message.get("channel") or "").strip()
    send_action = str(direct_message.get("send_action") or "send").strip() or "send"
    mode = str(direct_message.get("mode") or "focus").strip() or "focus"
    if not app_name and send_action == "send":
        app_name = _default_communication_app_for_channel(channel, mode, allowed)
    if (
        not app_name
        or not recipient
        or (
            not body
            and body_source
            not in {
                "app_search_result",
                "clipboard",
                "selection",
                "current_page_link",
                "current_page_content",
                "visible_text",
                "file",
            }
        )
    ):
        return []
    app_shortcut_tool = _first_allowed(
        app_foreground_tool_candidates(mode, "safe_shortcut"),
        allowed,
    )
    app_tool, shortcut_tool = _app_scoped_safe_shortcut_split_tools(app_name, mode, allowed)
    type_tool, recipient_type_input = _safe_type_text_operation_preview(
        app_name=app_name,
        mode=mode,
        allowed=allowed,
        payload={"text": recipient},
    )
    search_submit_tool = _first_allowed(("desktop.search_submit",), allowed)
    send_tool = _first_allowed(("desktop.submit_foreground",), allowed)
    steps: list[ToolPlanStepSnapshot] = []
    source_step_id = ""
    generated_body = _direct_message_requires_generated_body(direct_message)
    if generated_body and body_source:
        context_steps = (
            _app_search_result_context_steps(
                intent,
                allowed,
                direct_message,
                step_prefix="communication",
                capability_id="communication.compose",
            )
            if body_source == "app_search_result"
            else _context_source_steps(
                intent,
                allowed,
                body_source,
                step_prefix="communication",
                capability_id="communication.compose",
            )
        )
        steps.extend(context_steps)
        if context_steps:
            source_step_id = context_steps[-1].step_id
    elif body_source == "selection":
        source_step_id = "copy-communication-body-source"
        steps.append(
            _step(
                intent,
                source_step_id,
                "Copy communication body source",
                "communication.compose",
                _first_allowed(("desktop.safe_shortcut",), allowed),
                input_preview={"action": "copy"},
                action="copy_selection",
                reason="Copy the explicit selection before using it as the message body.",
            )
        )
    elif body_source == "current_page_link":
        source_step_id = "copy-communication-body-source"
        steps.append(
            _step(
                intent,
                source_step_id,
                "Copy communication body source",
                "communication.compose",
                _first_allowed(("desktop.safe_shortcut",), allowed),
                input_preview={"action": "copy_current_page_link"},
                action="copy_current_page_link",
                reason="Copy the current page link before using it as the message body.",
            )
        )

    focus_depends_on = [source_step_id] if source_step_id else []
    if app_tool and shortcut_tool:
        steps.append(
            _step(
                intent,
                "open-or-focus-app",
                "Open or focus app",
                "desktop.app_control",
                app_tool,
                input_preview={"app_name": app_name},
                depends_on=focus_depends_on,
                reason="Prepare the requested communication app before resolving the recipient.",
            )
        )
        focus_depends_on = ["open-or-focus-app"]
        focus_tool = shortcut_tool
        focus_input = {"action": _communication_recipient_focus_action(channel)}
        focus_capability = "communication.compose"
        focus_reason = "Open foreground recipient search with a generic safe shortcut."
    else:
        focus_tool = app_shortcut_tool
        focus_input = {
            "app_name": app_name,
            "action": _communication_recipient_focus_action(channel),
        }
        focus_capability = "communication.compose"
        focus_reason = "Open the app's recipient search with a safe shortcut before drafting the message."
    steps.extend(
        [
            _step(
                intent,
                "focus-communication-recipient-search",
                "Focus communication recipient search",
                focus_capability,
                focus_tool,
                input_preview=focus_input,
                action="resolve_recipient",
                depends_on=focus_depends_on,
                reason=focus_reason,
            ),
            _step(
                intent,
                "type-communication-recipient",
                "Type communication recipient",
                "communication.compose",
                type_tool,
                input_preview=recipient_type_input,
                depends_on=["focus-communication-recipient-search"],
                action="type",
                reason="Type only the explicit recipient from the user prompt.",
            ),
            _step(
                intent,
                "submit-communication-recipient-search",
                "Submit communication recipient search",
                "communication.compose",
                search_submit_tool,
                input_preview={},
                depends_on=["type-communication-recipient"],
                action="submit_search",
                reason="Select or search the recipient with the dedicated safe search submit tool.",
            ),
        ]
    )
    if body_source in {"clipboard", "selection", "current_page_link"} and not generated_body:
        steps.append(
            _step(
                intent,
                "paste-communication-message",
                "Paste communication message",
                "communication.compose",
                _first_allowed(("desktop.safe_shortcut",), allowed),
                input_preview={"action": "paste"},
                depends_on=["submit-communication-recipient-search"],
                action="paste",
                reason="Paste the requested clipboard-backed context into the message draft.",
            )
        )
        send_depends_on = ["paste-communication-message"]
    else:
        if generated_body and body_source:
            draft_input = {"body_source": body_source}
            if body:
                draft_input["instruction"] = body
        else:
            draft_input = {"text": body} if body else {"body_source": body_source}
        if transform:
            draft_input["transform"] = transform
        draft_tool, draft_input = _safe_type_text_operation_preview(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            payload=draft_input,
        )
        steps.append(
            _step(
                intent,
                "draft-communication-message",
                "Draft communication message",
                "communication.compose",
                draft_tool,
                input_preview=draft_input,
                depends_on=["submit-communication-recipient-search"],
                action="draft_message",
                reason=(
                    "Draft the generated message body from inspected context before the approval-gated send step."
                    if generated_body
                    else "Type only the explicit message body before the approval-gated send step."
                ),
            )
        )
        send_depends_on = ["draft-communication-message"]

    steps.append(
        _step(
            intent,
            "send-communication-message",
            "Send communication message",
            "communication.compose",
            send_tool,
            input_preview={"action": "send"},
            risk_level="high",
            approval_required=True,
            depends_on=send_depends_on,
            action="send_message",
            reason="Final message sending remains approval-gated.",
        )
    )
    return steps


def _communication_draft_input_preview(direct_message: Mapping[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in ("app_name", "recipient", "body", "body_source", "content_transform_hint", "channel"):
        value = str(direct_message.get(key) or "").strip()
        if value:
            preview[key] = value
    return preview


def _communication_draft_should_use_artifact(
    direct_message: Any,
    allowed: set[str] | None,
) -> bool:
    if not isinstance(direct_message, Mapping):
        return False
    if str(direct_message.get("send_action") or "").strip() != "draft":
        return False
    if str(direct_message.get("app_name") or "").strip():
        return False
    return bool(_first_allowed(("artifact.write",), allowed))


def _default_communication_app_for_channel(
    channel: str,
    mode: str,
    allowed: set[str] | None,
) -> str:
    if channel != "email":
        return ""
    if not _communication_desktop_send_tools_available(mode, allowed):
        return ""
    return "Mail"


def _communication_desktop_send_tools_available(
    mode: str,
    allowed: set[str] | None,
) -> bool:
    if allowed is None:
        return True
    app_shortcut_tool = _first_allowed(
        app_foreground_tool_candidates(mode, "safe_shortcut"),
        allowed,
    )
    app_tool, shortcut_tool = _app_scoped_safe_shortcut_split_tools("Mail", mode, allowed)
    if not app_shortcut_tool and not (app_tool and shortcut_tool):
        return False
    return bool(
        _first_allowed(
            _safe_type_text_operation_candidates("Mail", mode),
            allowed,
        )
        and _first_allowed(("desktop.search_submit",), allowed)
        and _first_allowed(("desktop.submit_foreground",), allowed)
    )


def _communication_recipient_focus_action(channel: str) -> str:
    if channel == "email":
        return "new_message"
    return "find"


def _direct_message_requires_generated_body(direct_message: Mapping[str, Any]) -> bool:
    body_source = str(direct_message.get("body_source") or "").strip()
    transform = str(direct_message.get("content_transform_hint") or "").strip()
    if transform and body_source:
        return True
    return body_source in {"app_search_result", "current_page_content", "visible_text", "file"}


def _current_page_find_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
) -> list[ToolPlanStepSnapshot]:
    source = str(intent.inputs.get("context_source") or "").strip()
    query = str(intent.inputs.get("query") or "").strip()
    shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
    type_tool = _first_allowed(("desktop.safe_type_text",), allowed)
    steps: list[ToolPlanStepSnapshot] = []

    if source == "selection":
        steps.append(
            _step(
                intent,
                "copy-selected-page-find-query",
                "Copy selected page find query",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "copy"},
                action="shortcut",
                reason="Copy the explicit selection before using it as the current-page find query.",
            )
        )

    steps.append(
        _step(
            intent,
            "open-current-page-find",
            "Open current page find",
            "desktop.ui_operation",
            shortcut_tool,
            input_preview={"action": "find"},
            depends_on=["copy-selected-page-find-query"] if source == "selection" else [],
            action="shortcut",
            reason="Open the foreground browser page find box with the standard safe shortcut.",
        )
    )

    if source in {"selection", "clipboard"}:
        steps.append(
            _step(
                intent,
                "paste-current-page-find-query",
                "Paste current page find query",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "paste"},
                depends_on=["open-current-page-find"],
                action="shortcut",
                reason="Paste the selected or clipboard text into the current-page find box.",
            )
        )
        return steps

    steps.append(
        _step(
            intent,
            "type-current-page-find-query",
            "Type current page find query",
            "desktop.ui_operation",
            type_tool,
            input_preview={"text": query} if query else {},
            depends_on=["open-current-page-find"],
            action="type",
            reason="Type the explicit query into the current-page find box.",
        )
    )
    return steps


def _dynamic_context_browser_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
) -> list[ToolPlanStepSnapshot]:
    source = str(intent.inputs.get("context_source") or "").strip()
    app_name = str(intent.inputs.get("app_name") or "").strip()
    shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
    submit_tool = _first_allowed(("desktop.search_submit",), allowed)
    steps: list[ToolPlanStepSnapshot] = []

    if source == "selection":
        steps.append(
            _step(
                intent,
                "copy-selected-browser-context",
                "Copy selected browser context",
                "desktop.ui_operation",
                shortcut_tool,
                input_preview={"action": "copy"},
                action="shortcut",
                reason="Copy the explicit selection before searching or opening it in the browser.",
            )
        )

    focus_depends_on = ["copy-selected-browser-context"] if source == "selection" else []
    focus_tool = shortcut_tool
    focus_payload = {"action": "focus_address_bar"}
    focus_capability = "desktop.ui_operation"
    if app_name:
        app_tool, app_shortcut_tool = _app_scoped_safe_shortcut_split_tools(
            app_name,
            "open",
            allowed,
        )
        app_focus_tool = _first_allowed(
            app_foreground_tool_candidates("open", "safe_shortcut"),
            allowed,
        )
        if app_tool and app_shortcut_tool:
            steps.append(
                _step(
                    intent,
                    "open-or-focus-app",
                    "Open or focus app",
                    "desktop.app_control",
                    app_tool,
                    input_preview={"app_name": app_name},
                    depends_on=focus_depends_on,
                    reason="Prepare the requested browser before focusing its address bar.",
                )
            )
            focus_depends_on = ["open-or-focus-app"]
            focus_tool = app_shortcut_tool
        elif app_focus_tool:
            focus_tool = app_focus_tool
            focus_payload = {"app_name": app_name, "action": "focus_address_bar"}
            focus_capability = "desktop.app_control"
    steps.append(
        _step(
            intent,
            "focus-browser-address-bar",
            "Focus browser address bar",
            focus_capability,
            focus_tool,
            input_preview=focus_payload,
            depends_on=focus_depends_on,
            action="shortcut",
            reason="Use the requested browser address bar so selected or clipboard text can be opened or searched.",
        )
    )
    steps.append(
        _step(
            intent,
            "paste-browser-context",
            "Paste browser context",
            "desktop.ui_operation",
            shortcut_tool,
            input_preview={"action": "paste"},
            depends_on=["focus-browser-address-bar"],
            action="shortcut",
            reason="Paste the selected or clipboard text into the browser address bar.",
        )
    )
    steps.append(
        _step(
            intent,
            "submit-browser-context",
            "Submit browser context",
            "desktop.ui_operation",
            submit_tool,
            input_preview={},
            depends_on=["paste-browser-context"],
            action="submit",
            risk_level="low",
            approval_required=False,
            reason="Submit the browser address bar query with the dedicated safe search submit tool.",
        )
    )
    return steps


def _information_capture_context_payload(tool_name: str | None) -> dict[str, Any]:
    if tool_name == "desktop.ui_elements":
        return {"role_filter": "text", "limit": 80}
    if tool_name == "screen.capture":
        return {"reason": "capture note context"}
    return {}


def _step_action(step_key: str, capability_id: str, tool_name: str | None) -> str:
    if step_key == "discover-desktop-state":
        return "list_apps"
    if step_key == "inspect-app":
        return "inspect_app"
    if step_key == "open-or-focus-app":
        return "focus_app" if tool_name == "app.focus" else "open_app"
    if step_key == "list-app-windows":
        return "list_windows"
    if step_key == "focus-app-window":
        return "focus_window"
    if step_key == "read-foreground-ui":
        return "read_ui"
    if step_key == "capture-screen":
        return "capture_screen"
    if step_key == "manage-app":
        return _app_management_action(tool_name)
    if step_key == "manage-foreground":
        return _foreground_management_action(tool_name)
    if step_key == "verify-desktop-result":
        return "read_ui" if tool_name == "desktop.ui_elements" else "verify"
    if step_key.startswith("operate-foreground-ui"):
        return _desktop_operation_action(tool_name)
    if step_key == "submit-foreground-ui":
        return "submit"
    if step_key == "submit-foreground-search":
        return "submit"
    if step_key == "focus-app-search-field":
        return _desktop_operation_action(tool_name)
    if step_key == "type-app-search-query":
        return "type"
    if step_key == "submit-app-search":
        return "submit"
    if step_key == "open-spotlight-search":
        return "shortcut"
    if step_key == "type-spotlight-search-query":
        return "type"
    if step_key == "submit-browser-context":
        return "submit"
    if step_key == "open-system-settings":
        return "open_settings"
    if step_key == "read-system-settings-ui":
        return "read_ui"
    if capability_id == "desktop.app_discovery":
        return _desktop_discovery_action(tool_name)
    if capability_id == "data.analysis":
        return "analyze_data_file" if tool_name == "data.analyze" else "run_python_analysis"
    if capability_id == "artifact.write":
        return "write_artifact"
    if capability_id in {"file.workspace_read", "file.organization"}:
        return "inspect_paths" if capability_id == "file.organization" else "read_file"
    if capability_id == "file.desktop_access":
        return "reveal_path" if tool_name == "desktop.reveal_path" else "open_path"
    if capability_id == "browser.research":
        if _is_context_source_tool(tool_name):
            return _context_source_action(tool_name)
        if tool_name == "browser.current_page":
            return "read_current_page"
        if tool_name == "browser.screenshot":
            return "screenshot"
        return "extract_text" if tool_name and "extract_text" in tool_name else "open_url"
    if capability_id == "media.playback":
        return "play"
    if capability_id == "system.control":
        if tool_name == "system.settings_open":
            return "open_settings"
        return "control_system"
    if capability_id == "schedule.reminder":
        if _is_context_source_tool(tool_name):
            return _context_source_action(tool_name)
        return "schedule_task"
    if capability_id == "information.capture":
        if tool_name == "artifact.write":
            return "write_artifact"
        return _context_source_action(tool_name)
    if capability_id == "communication.compose":
        if _is_context_source_tool(tool_name):
            return _context_source_action(tool_name)
        if tool_name == "desktop.submit_foreground":
            return "send_message"
        if tool_name == "desktop.search_submit":
            return "submit_search"
        if tool_name in {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"}:
            return "resolve_recipient"
        return "draft_message"
    if capability_id == "clipboard.read_write":
        return "read_clipboard" if tool_name == "clipboard.read" else "write_clipboard"
    return ""


def _is_context_source_tool(tool_name: str | None) -> bool:
    clean_tool = str(tool_name or "")
    return clean_tool in {
        "clipboard.read",
        "desktop.safe_shortcut",
        "browser.current_page",
        "browser.extract_text",
        "desktop.ui_elements",
        "screen.capture",
    }


def _context_source_action(tool_name: str | None) -> str:
    clean_tool = str(tool_name or "")
    if clean_tool == "notes.create":
        return "create_note"
    if clean_tool == "clipboard.read":
        return "read_clipboard"
    if clean_tool == "desktop.safe_shortcut":
        return "shortcut"
    if clean_tool == "browser.current_page":
        return "read_current_page"
    if clean_tool.startswith("browser."):
        return "extract_text"
    if clean_tool == "desktop.ui_elements":
        return "read_ui"
    if clean_tool == "screen.capture":
        return "capture_screen"
    return "capture"


def _desktop_operation_action(tool_name: str | None) -> str:
    clean_tool = str(tool_name or "")
    if "click" in clean_tool:
        return "click"
    if "type" in clean_tool:
        return "type"
    if "shortcut" in clean_tool or "hotkey" in clean_tool:
        return "shortcut"
    if "scroll" in clean_tool:
        return "scroll"
    if "key" in clean_tool:
        return "key"
    return "operate_ui"


def _desktop_operation_risk_level(tool_name: str | None) -> str:
    clean_tool = str(tool_name or "")
    if (
        "safe_shortcut" in clean_tool
        or "safe_key" in clean_tool
        or "safe_scroll" in clean_tool
        or "safe_click" in clean_tool
    ):
        return "low"
    return "medium"


def _desktop_operation_approval_required(tool_name: str | None) -> bool:
    return _desktop_operation_risk_level(tool_name) != "low"


def _app_management_action(tool_name: str | None) -> str:
    clean_tool = str(tool_name or "")
    if clean_tool == "app.show":
        return "show_app"
    if clean_tool == "app.status":
        return "status_app"
    if clean_tool == "app.hide":
        return "hide_app"
    if clean_tool == "app.minimize":
        return "minimize_app"
    if clean_tool == "app.quit":
        return "quit_app"
    return "manage_app"


def _foreground_management_action(tool_name: str | None) -> str:
    clean_tool = str(tool_name or "")
    if clean_tool == "desktop.hide_app":
        return "hide_app"
    if clean_tool == "desktop.show_all_apps":
        return "show_all_apps"
    if clean_tool == "desktop.minimize_window":
        return "minimize_window"
    if clean_tool == "desktop.close_window":
        return "close_window"
    if clean_tool == "desktop.quit_app":
        return "quit_app"
    return "manage_foreground"


def _desktop_verify_tool_candidates(depends_on: list[str]) -> tuple[str, ...]:
    if _desktop_verify_depends_on_ui_operation(depends_on):
        return ("desktop.ui_elements", "desktop.windows", "desktop.active_window", "screen.capture")
    return ("desktop.active_window", "desktop.windows", "desktop.ui_elements", "screen.capture")


def _desktop_verify_reason(depends_on: list[str]) -> str:
    if _desktop_verify_depends_on_ui_operation(depends_on):
        return "Read foreground UI or windows after the UI action to verify the visible result."
    return "Observe the foreground state after desktop execution."


def _desktop_verify_depends_on_ui_operation(depends_on: list[str]) -> bool:
    return any(
        step_id.startswith("operate-foreground-ui") or step_id == "submit-foreground-ui"
        for step_id in depends_on
    )


def _desktop_verify_input_preview(
    tool_name: str | None,
    *,
    app_name: str,
    operation_preview: Mapping[str, Any],
) -> dict[str, Any]:
    if tool_name == "desktop.windows":
        return {"app_name": app_name} if app_name else {}
    if tool_name != "desktop.ui_elements":
        return {}
    preview = {
        key: operation_preview[key]
        for key in ("role_filter", "limit")
        if key in operation_preview and operation_preview[key] not in (None, "")
    }
    return preview


def _desktop_inspect_app_input_preview(
    app_name: str,
    ui_payload: Mapping[str, Any],
    *,
    open_if_needed: bool,
    focus: bool,
) -> dict[str, Any]:
    preview: dict[str, Any] = {
        "app_name": app_name,
        "open_if_needed": open_if_needed,
        "focus": focus,
    }
    for key in ("role_filter", "limit"):
        if key in ui_payload and ui_payload[key] not in (None, ""):
            preview[key] = ui_payload[key]
    return preview


def _media_playback_verify_step(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
) -> ToolPlanStepSnapshot | None:
    action = str(intent.inputs.get("action") or "").strip() or "play"
    if action == "status":
        return None
    tool_name = _first_allowed(
        ("desktop.ui_elements", "desktop.active_window", "screen.capture"),
        allowed,
    )
    if not tool_name:
        return None
    return _step(
        intent,
        "verify-media-playback",
        "Verify media playback",
        "desktop.app_discovery",
        tool_name,
        input_preview=_media_playback_verify_input_preview(tool_name),
        depends_on=["control-media-playback"],
        action=_desktop_discovery_action(tool_name),
        reason="Observe the media app after changing playback state.",
    )


def _media_playback_verify_input_preview(tool_name: str | None) -> dict[str, Any]:
    if tool_name == "desktop.ui_elements":
        return {"role_filter": "", "limit": 80}
    if tool_name == "screen.capture":
        return {"reason": "verify media playback"}
    return {}


def _service_action(capability_id: str) -> str:
    if capability_id == "workflow.orchestration":
        return "start_workflow"
    if capability_id == "group.multi_agent":
        return "start_group_run"
    return ""


def _service_tool_candidates(capability_id: str) -> tuple[str, ...]:
    if capability_id == "workflow.orchestration":
        return ("workflow.start", "workflow.run", "workflow.list")
    if capability_id == "group.multi_agent":
        return ("group.start", "group.run", "group.list")
    return ()


def _desktop_discovery_action(tool_name: str | None) -> str:
    clean_tool = str(tool_name or "")
    if clean_tool == "desktop.permissions":
        return "diagnose_permissions"
    if clean_tool == "desktop.active_window":
        return "read_active_window"
    if clean_tool == "desktop.running_apps":
        return "read_running_apps"
    if clean_tool == "desktop.list_apps":
        return "list_apps"
    if clean_tool == "desktop.inspect_app":
        return "inspect_app"
    if clean_tool == "desktop.windows":
        return "list_windows"
    if clean_tool == "desktop.ui_elements":
        return "read_ui"
    if clean_tool == "screen.capture":
        return "capture_screen"
    return "discover"


def _allowed_tool_set(allowed_tools: Iterable[str] | None) -> set[str] | None:
    if allowed_tools is None:
        return None
    return {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}


def _planner_readiness_context(
    metadata: Mapping[str, Any] | None,
) -> dict[str, dict[str, list[str]]]:
    if not isinstance(metadata, Mapping):
        return {}
    missing = _merge_issue_maps(
        _metadata_issue_map(
            metadata,
            "desktop_missing_permissions_by_capability",
            "desktop_missing_permissions",
        ),
        _capability_snapshot_issues(metadata, "missing_permissions"),
        _flat_issue_tokens_by_capability(
            metadata.get("missing_permissions"),
            issue_kind="missing",
        ),
    )
    blocking = _merge_issue_maps(
        _metadata_issue_map(
            metadata,
            "desktop_blocking_conditions_by_capability",
            "desktop_runtime_blocking_conditions_by_capability",
            "desktop_runtime_blocking_conditions",
            "desktop_blocking_conditions",
        ),
        _capability_snapshot_issues(metadata, "blocking_conditions"),
        _flat_issue_tokens_by_capability(
            metadata.get("blocking_conditions"),
            issue_kind="blocking",
        ),
    )
    context: dict[str, dict[str, list[str]]] = {}
    if missing:
        context["missing_permissions"] = missing
    if blocking:
        context["blocking_conditions"] = blocking
    return context


def _apply_readiness_to_steps(
    steps: list[ToolPlanStepSnapshot],
    readiness: Mapping[str, Mapping[str, Iterable[str]]],
) -> list[ToolPlanStepSnapshot]:
    updated: list[ToolPlanStepSnapshot] = []
    for step in steps:
        issues = _step_readiness_issues(step, readiness)
        if not issues["missing_permissions"] and not issues["blocking_conditions"]:
            updated.append(step)
            continue
        input_preview = dict(step.input_preview or {})
        if issues["missing_permissions"]:
            input_preview["missing_permissions"] = issues["missing_permissions"]
        if issues["blocking_conditions"]:
            input_preview["blocking_conditions"] = issues["blocking_conditions"]
        reason_suffix = _readiness_reason_suffix(issues)
        updated.append(
            step.model_copy(
                update={
                    "input_preview": input_preview,
                    "reason": f"{step.reason} {reason_suffix}".strip(),
                    "status": "unavailable",
                }
            )
        )
    return updated


def _step_readiness_issues(
    step: ToolPlanStepSnapshot,
    readiness: Mapping[str, Mapping[str, Iterable[str]]],
) -> dict[str, list[str]]:
    tool_name = str(step.tool_name or "").strip()
    if not tool_name:
        return {"missing_permissions": [], "blocking_conditions": []}
    policy_capability_id = _desktop_policy_capability_id_for_tool(tool_name)
    if not policy_capability_id:
        return {"missing_permissions": [], "blocking_conditions": []}
    missing_by_capability = readiness.get("missing_permissions") or {}
    blocking_by_capability = readiness.get("blocking_conditions") or {}
    return {
        "missing_permissions": desktop_tool_missing_permissions(
            tool_name,
            capability_id=policy_capability_id,
            missing_permissions=missing_by_capability,
        ),
        "blocking_conditions": desktop_tool_blocking_conditions(
            tool_name,
            capability_id=policy_capability_id,
            blocking_conditions=blocking_by_capability,
        ),
    }


def _desktop_policy_capability_id_for_tool(tool_name: str) -> str:
    clean_tool = str(tool_name or "").strip()
    if not clean_tool:
        return ""
    for capability_id, tools in DESKTOP_CAPABILITY_TOOLS.items():
        if capability_id == "desktop_execution":
            continue
        if clean_tool in tools:
            return capability_id
    return (
        "desktop_execution"
        if clean_tool in DESKTOP_CAPABILITY_TOOLS["desktop_execution"]
        else ""
    )


def _readiness_reason_suffix(issues: Mapping[str, Iterable[str]]) -> str:
    missing = _issue_tokens(issues.get("missing_permissions"))
    blocking = _issue_tokens(issues.get("blocking_conditions"))
    parts = []
    if missing:
        parts.append(f"missing permissions: {', '.join(missing)}")
    if blocking:
        parts.append(f"runtime blockers: {', '.join(blocking)}")
    if not parts:
        return ""
    return f"Current desktop readiness marks this step unavailable ({'; '.join(parts)})."


def _metadata_issue_map(metadata: Mapping[str, Any], *keys: str) -> dict[str, list[str]]:
    for key in keys:
        payload = metadata.get(key)
        if isinstance(payload, Mapping):
            return _clean_issue_map(payload)
    return {}


def _capability_snapshot_issues(
    metadata: Mapping[str, Any],
    issue_field: str,
) -> dict[str, list[str]]:
    issue_map: dict[str, list[str]] = {}
    capability_sources = []
    for key in ("desktop_capabilities", "desktop_execution_capabilities", "capabilities"):
        payload = metadata.get(key)
        if isinstance(payload, Mapping):
            capability_sources.append(payload)
    readiness = metadata.get("readiness")
    if isinstance(readiness, Mapping) and isinstance(readiness.get("capabilities"), Mapping):
        capability_sources.append(readiness["capabilities"])
    for capabilities in capability_sources:
        for capability_id, capability in capabilities.items():
            if not isinstance(capability, Mapping):
                continue
            tokens = _issue_tokens(capability.get(issue_field))
            if tokens:
                issue_map[str(capability_id or "").strip()] = tokens
    return _clean_issue_map(issue_map)


def _flat_issue_tokens_by_capability(value: Any, *, issue_kind: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for token in _issue_tokens(value):
        capability_id = _capability_id_for_flat_issue_token(token, issue_kind=issue_kind)
        if not capability_id:
            continue
        result.setdefault(capability_id, [])
        if token not in result[capability_id]:
            result[capability_id].append(token)
    return result


def _capability_id_for_flat_issue_token(token: str, *, issue_kind: str) -> str:
    clean = str(token or "").strip()
    if issue_kind == "blocking":
        if clean == "foreground_focus_unavailable":
            return "foreground_activation"
        if clean == "desktop_session_locked":
            return "desktop_execution"
    return {
        "accessibility": "foreground_input",
        "automation": "app_control",
        "automation_or_accessibility": "active_window",
        "chrome_cdp": "browser_control",
        "foreground_focus": "foreground_activation",
        "music_app": "media_control",
        "open_command": "app_control",
        "screen_capture_probe_failed": "screen_capture",
        "screen_recording": "screen_capture",
        "unsupported_platform": "desktop_execution",
    }.get(clean, "")


def _merge_issue_maps(*maps: Mapping[str, Iterable[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for issue_map in maps:
        for capability_id, raw_tokens in issue_map.items():
            clean_capability_id = str(capability_id or "").strip()
            if not clean_capability_id:
                continue
            for token in _issue_tokens(raw_tokens):
                values = merged.setdefault(clean_capability_id, [])
                if token not in values:
                    values.append(token)
    return merged


def _clean_issue_map(value: Mapping[str, Any]) -> dict[str, list[str]]:
    return _merge_issue_maps(
        {
            str(capability_id or "").strip(): _issue_tokens(tokens)
            for capability_id, tokens in value.items()
        }
    )


def _issue_tokens(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = re.split(r"[,\s]+", value)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        raw_values = []
        for item in value:
            raw_values.extend(_issue_tokens(item))
    else:
        raw_values = [str(value)]
    tokens: list[str] = []
    for item in raw_values:
        clean = str(item or "").strip()
        if clean and clean not in tokens:
            tokens.append(clean)
    return tokens


def _normalize_intent_for_allowed_tools(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
) -> TaskIntentSnapshot:
    if allowed is None or intent.kind != "web_research":
        return intent
    browser_action = str(intent.inputs.get("browser_action") or "").strip()
    if (
        browser_action == "open_url_extract"
        and "browser.open_url_and_extract_text" not in allowed
        and "browser.open_url" in allowed
    ):
        inputs = dict(intent.inputs)
        inputs["browser_action"] = "open_search" if inputs.get("query") else "open_url"
        return intent.model_copy(update={"inputs": inputs})
    return intent


def _missing_capabilities(
    snapshots: list[Any],
    *,
    required_capability_ids: Iterable[str] | None = None,
) -> list[str]:
    required = {
        str(capability_id or "").strip()
        for capability_id in required_capability_ids or []
        if str(capability_id or "").strip()
    }
    missing = []
    for snapshot in snapshots:
        capability_id = str(getattr(snapshot, "capability_id", "") or "")
        if required and capability_id not in required:
            continue
        tools = list(getattr(snapshot, "tools", []) or [])
        available_tools = list(getattr(snapshot, "available_tools", []) or [])
        if tools and not available_tools:
            missing.append(capability_id)
    return [item for item in missing if item]


def _unavailable_required_step_capabilities(
    steps: Iterable[ToolPlanStepSnapshot],
    *,
    required_capability_ids: Iterable[str] | None = None,
) -> list[str]:
    required = {
        str(capability_id or "").strip()
        for capability_id in required_capability_ids or []
        if str(capability_id or "").strip()
    }
    missing: list[str] = []
    for step in steps:
        if str(step.status or "").strip() != "unavailable":
            continue
        if str(step.step_id or "").strip() == "verify-desktop-result":
            continue
        capability_id = str(step.capability_id or "").strip()
        if not capability_id:
            continue
        if required and capability_id not in required:
            continue
        if capability_id not in missing:
            missing.append(capability_id)
    return missing


def _required_capabilities_for_plan(
    intent: TaskIntentSnapshot,
    steps: list[ToolPlanStepSnapshot],
) -> list[str]:
    if intent.kind == "data_analysis":
        required = (
            ["data.analysis"]
            if any(step.tool_name == "data.analyze" for step in steps)
            else (_step_required_capabilities(steps) or list(intent.required_capabilities))
        )
        if any(step.step_id == "open-spreadsheet-app" for step in steps) and (
            "desktop.app_control" not in required
        ):
            required.insert(0, "desktop.app_control")
        for capability_id in _step_required_capabilities(steps):
            if capability_id not in required:
                required.append(capability_id)
        return required
    return _step_required_capabilities(steps) or list(intent.required_capabilities)


def _step_required_capabilities(steps: Iterable[ToolPlanStepSnapshot]) -> list[str]:
    required: list[str] = []
    for step in steps:
        capability_id = str(step.capability_id or "").strip()
        if capability_id and capability_id not in required:
            required.append(capability_id)
    return required


def _artifacts_expected(intent: TaskIntentSnapshot, steps: list[ToolPlanStepSnapshot]) -> list[str]:
    for step in steps:
        if step.tool_name == "data.analyze":
            artifact_paths = step.input_preview.get("artifact_paths")
            if isinstance(artifact_paths, list):
                return [
                    str(path or "").strip()
                    for path in artifact_paths
                    if str(path or "").strip()
                ]
            artifact_path = str(step.input_preview.get("artifact_path") or "").strip()
            return [artifact_path or "analysis-report.md"]
    artifact_write_paths = _artifact_write_paths_from_steps(steps)
    if intent.kind == "web_research":
        browser_action = str(intent.inputs.get("browser_action") or "").strip()
        if browser_action in {"screenshot", "open_url_screenshot"}:
            return ["browser/current-page.png"]
        if browser_action and artifact_write_paths:
            return artifact_write_paths
        if browser_action:
            return []
    if not any(step.tool_name == "artifact.write" for step in steps):
        return []
    if artifact_write_paths:
        return artifact_write_paths
    if intent.kind == "data_analysis":
        return data_analysis_artifacts_expected(intent.expected_outputs, intent.user_goal)
    if intent.kind == "web_research":
        return ["research-summary.md"]
    if intent.kind == "code_task":
        return ["code-task-summary.md"]
    if intent.kind == "file_organization":
        operation_hint = str(intent.inputs.get("operation_hint") or "").strip()
        if operation_hint == "duplicate_inventory":
            return ["duplicate-file-report.md"]
        if operation_hint == "inventory":
            return ["file-inventory.md"]
        return ["file-organization-plan.md"]
    if intent.kind == "information_capture":
        return ["captured-note.md"]
    return ["report.md"]


def _artifact_write_paths_from_steps(steps: Iterable[ToolPlanStepSnapshot]) -> list[str]:
    for step in steps:
        if step.tool_name != "artifact.write":
            continue
        paths = step.input_preview.get("paths")
        if isinstance(paths, list):
            return [
                str(path or "").strip()
                for path in paths
                if str(path or "").strip()
            ]
        path = str(step.input_preview.get("path") or "").strip()
        if path:
            return [path]
    return []


def _append_artifact_reveal_step(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    artifact_paths: Iterable[str],
    depends_on: str,
) -> list[ToolPlanStepSnapshot]:
    if not _artifact_reveal_requested(intent.user_goal):
        return steps
    path = _artifact_reveal_path(intent.user_goal, artifact_paths)
    if not path:
        return steps
    return [
        *steps,
        _step(
            intent,
            "reveal-artifact-in-finder",
            "Reveal artifact in Finder",
            "file.desktop_access",
            _first_allowed(("desktop.reveal_path",), allowed),
            input_preview={"path": path},
            depends_on=[depends_on],
            reason="Reveal the generated artifact through Finder only after the artifact-producing step finishes.",
        ),
    ]


def _append_data_analysis_followup_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    artifact_paths: Iterable[str],
    depends_on: str,
) -> list[ToolPlanStepSnapshot]:
    paths = [str(path or "").strip() for path in artifact_paths if str(path or "").strip()]
    followup_steps = _append_artifact_reveal_step(
        intent,
        allowed,
        steps,
        artifact_paths=paths,
        depends_on=depends_on,
    )
    followup_steps = _append_analysis_app_write_target_steps(
        intent,
        allowed,
        followup_steps,
        depends_on=depends_on,
    )
    return _append_analysis_communication_steps(
        intent,
        allowed,
        followup_steps,
        artifact_paths=paths,
        depends_on=depends_on,
    )


def _append_analysis_app_write_target_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    depends_on: str,
) -> list[ToolPlanStepSnapshot]:
    target_app = str(intent.inputs.get("target_app_hint") or "").strip()
    target_action = str(intent.inputs.get("target_action_hint") or "").strip()
    if not target_app or target_action != "app_paste":
        return steps
    container_action = str(
        intent.inputs.get("target_container_action_hint") or ""
    ).strip()
    return [
        *steps,
        _step(
            intent,
            "prepare-analysis-target-app",
            "Prepare target app",
            "desktop.app_control",
            _first_allowed(
                (
                    "app.focus",
                    "app.open",
                    "app.focus_and_safe_shortcut",
                    "app.open_and_safe_shortcut",
                ),
                allowed,
            ),
            input_preview={
                "app_name": target_app,
                "target_action": target_action,
                **(
                    {"container_action": container_action}
                    if container_action
                    else {}
                ),
                "body_source": "model_generated_content",
            },
            depends_on=[depends_on],
            reason=(
                "After the local data analysis artifact is available, focus the requested app "
                "before inserting the model-generated report."
            ),
        ),
    ]


def _append_analysis_communication_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    artifact_paths: Iterable[str],
    depends_on: str,
) -> list[ToolPlanStepSnapshot]:
    target = intent.inputs.get("communication_target_hint")
    if not isinstance(target, Mapping):
        return steps
    recipient = str(target.get("recipient") or "").strip()
    if not recipient:
        return steps
    artifact_path = _analysis_communication_artifact_path(intent.user_goal, artifact_paths)
    if not artifact_path:
        return steps
    app_name = str(target.get("app_name") or "").strip()
    channel = str(target.get("channel") or "").strip()
    transform = str(target.get("content_transform_hint") or "").strip()
    mode = str(target.get("mode") or "focus").strip() or "focus"
    if not app_name:
        app_name = _default_communication_app_for_channel(channel, mode, allowed)
    if not app_name:
        draft_input = {
            "recipient": recipient,
            "body_source": "analysis_artifact",
            "artifact_path": artifact_path,
        }
        if transform:
            draft_input["transform"] = transform
        return [
            *steps,
            _step(
                intent,
                "draft-analysis-communication",
                "Draft analysis communication",
                "communication.compose",
                _first_allowed(("artifact.write",), allowed),
                input_preview=draft_input,
                approval_required=True,
                risk_level="medium",
                depends_on=[depends_on],
                action="draft_message",
                reason=(
                    "Create a reviewable communication draft from the analysis artifact when the target app "
                    "cannot be resolved deterministically."
                ),
            ),
        ]

    app_shortcut_tool = _first_allowed(
        app_foreground_tool_candidates(mode, "safe_shortcut"),
        allowed,
    )
    app_tool, shortcut_tool = _app_scoped_safe_shortcut_split_tools(app_name, mode, allowed)
    type_tool = _first_allowed(("desktop.safe_type_text",), allowed)
    search_submit_tool = _first_allowed(("desktop.search_submit",), allowed)
    send_tool = _first_allowed(("desktop.submit_foreground",), allowed)
    communication_steps: list[ToolPlanStepSnapshot] = []
    focus_depends_on = [depends_on]
    if app_tool and shortcut_tool:
        communication_steps.append(
            _step(
                intent,
                "open-or-focus-app",
                "Open or focus app",
                "desktop.app_control",
                app_tool,
                input_preview={"app_name": app_name},
                depends_on=focus_depends_on,
                reason="Prepare the requested communication app after the analysis artifact is available.",
            )
        )
        focus_depends_on = ["open-or-focus-app"]
        focus_tool = shortcut_tool
        focus_input = {"action": _communication_recipient_focus_action(channel)}
        focus_capability = "communication.compose"
        focus_reason = "Open foreground recipient search with a generic safe shortcut."
    else:
        focus_tool = app_shortcut_tool
        focus_input = {
            "app_name": app_name,
            "action": _communication_recipient_focus_action(channel),
        }
        focus_capability = "communication.compose"
        focus_reason = "Open the app's recipient search after the analysis artifact is available."

    draft_input = {
        "body_source": "analysis_artifact",
        "artifact_path": artifact_path,
    }
    if transform:
        draft_input["transform"] = transform
    communication_steps.extend(
        [
            _step(
                intent,
                "focus-communication-recipient-search",
                "Focus communication recipient search",
                focus_capability,
                focus_tool,
                input_preview=focus_input,
                action="resolve_recipient",
                depends_on=focus_depends_on,
                reason=focus_reason,
            ),
            _step(
                intent,
                "type-communication-recipient",
                "Type communication recipient",
                "communication.compose",
                type_tool,
                input_preview={"text": recipient},
                depends_on=["focus-communication-recipient-search"],
                action="type",
                reason="Type only the explicit recipient from the user prompt.",
            ),
            _step(
                intent,
                "submit-communication-recipient-search",
                "Submit communication recipient search",
                "communication.compose",
                search_submit_tool,
                input_preview={},
                depends_on=["type-communication-recipient"],
                action="submit_search",
                reason="Select or search the recipient with the dedicated safe search submit tool.",
            ),
            _step(
                intent,
                "draft-analysis-communication-message",
                "Draft analysis communication message",
                "communication.compose",
                type_tool,
                input_preview=draft_input,
                depends_on=["submit-communication-recipient-search"],
                action="draft_message",
                reason="Draft the message from the generated analysis artifact before the approval-gated send step.",
            ),
            _step(
                intent,
                "send-analysis-communication-message",
                "Send analysis communication message",
                "communication.compose",
                send_tool,
                input_preview={"action": "send"},
                risk_level="high",
                approval_required=True,
                depends_on=["draft-analysis-communication-message"],
                action="send_message",
                reason="Final message sending remains approval-gated.",
            ),
        ]
    )
    return [*steps, *communication_steps]


def _append_web_research_app_write_target_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    depends_on: str,
) -> list[ToolPlanStepSnapshot]:
    target_app = str(intent.inputs.get("target_app_hint") or "").strip()
    target_action = str(intent.inputs.get("target_action_hint") or "").strip()
    if not target_app or target_action != "app_paste":
        return steps
    container_action = str(
        intent.inputs.get("target_container_action_hint") or ""
    ).strip()
    return [
        *steps,
        _step(
            intent,
            "prepare-research-target-app",
            "Prepare target app",
            "desktop.app_control",
            _first_allowed(
                (
                    "app.focus",
                    "app.open",
                    "app.focus_and_safe_shortcut",
                    "app.open_and_safe_shortcut",
                ),
                allowed,
            ),
            input_preview={
                "app_name": target_app,
                "target_action": target_action,
                **(
                    {"container_action": container_action}
                    if container_action
                    else {}
                ),
                "body_source": "model_generated_content",
            },
            depends_on=[depends_on],
            reason=(
                "After the browser content is inspected, focus the requested app "
                "before inserting the model-generated research output."
            ),
        ),
    ]


def _append_web_research_communication_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    artifact_path: str,
    depends_on: str,
) -> list[ToolPlanStepSnapshot]:
    target = intent.inputs.get("communication_target_hint")
    if not isinstance(target, Mapping):
        return steps
    recipient = str(target.get("recipient") or "").strip()
    if not recipient or not artifact_path:
        return steps
    app_name = str(target.get("app_name") or "").strip()
    transform = str(target.get("content_transform_hint") or "").strip()
    mode = str(target.get("mode") or "focus").strip() or "focus"
    if not app_name:
        draft_input = {
            "recipient": recipient,
            "body_source": "research_artifact",
            "artifact_path": artifact_path,
        }
        if transform:
            draft_input["transform"] = transform
        return [
            *steps,
            _step(
                intent,
                "draft-research-communication",
                "Draft research communication",
                "communication.compose",
                _first_allowed(("artifact.write",), allowed),
                input_preview=draft_input,
                approval_required=True,
                risk_level="medium",
                depends_on=[depends_on],
                action="draft_message",
                reason=(
                    "Create a reviewable communication draft from the research artifact "
                    "when the target app cannot be resolved deterministically."
                ),
            ),
        ]

    app_shortcut_tool = _first_allowed(
        app_foreground_tool_candidates(mode, "safe_shortcut"),
        allowed,
    )
    app_tool, shortcut_tool = _app_scoped_safe_shortcut_split_tools(app_name, mode, allowed)
    type_tool = _first_allowed(("desktop.safe_type_text",), allowed)
    search_submit_tool = _first_allowed(("desktop.search_submit",), allowed)
    send_tool = _first_allowed(("desktop.submit_foreground",), allowed)
    communication_steps: list[ToolPlanStepSnapshot] = []
    focus_depends_on = [depends_on]
    if app_tool and shortcut_tool:
        communication_steps.append(
            _step(
                intent,
                "open-or-focus-research-communication-app",
                "Open or focus communication app",
                "desktop.app_control",
                app_tool,
                input_preview={"app_name": app_name},
                depends_on=focus_depends_on,
                reason="Prepare the requested communication app after the research artifact is available.",
            )
        )
        focus_depends_on = ["open-or-focus-research-communication-app"]
        focus_tool = shortcut_tool
        focus_input = {"action": "find"}
        focus_capability = "communication.compose"
        focus_reason = "Open foreground recipient search with a generic safe shortcut."
    else:
        focus_tool = app_shortcut_tool
        focus_input = {"app_name": app_name, "action": "find"}
        focus_capability = "communication.compose"
        focus_reason = "Open the app's recipient search after the research artifact is available."

    draft_input = {
        "body_source": "research_artifact",
        "artifact_path": artifact_path,
    }
    if transform:
        draft_input["transform"] = transform
    communication_steps.extend(
        [
            _step(
                intent,
                "focus-research-communication-recipient-search",
                "Focus communication recipient search",
                focus_capability,
                focus_tool,
                input_preview=focus_input,
                action="resolve_recipient",
                depends_on=focus_depends_on,
                reason=focus_reason,
            ),
            _step(
                intent,
                "type-research-communication-recipient",
                "Type communication recipient",
                "communication.compose",
                type_tool,
                input_preview={"text": recipient},
                depends_on=["focus-research-communication-recipient-search"],
                action="type",
                reason="Type only the explicit recipient from the user prompt.",
            ),
            _step(
                intent,
                "submit-research-communication-recipient-search",
                "Submit communication recipient search",
                "communication.compose",
                search_submit_tool,
                input_preview={},
                depends_on=["type-research-communication-recipient"],
                action="submit_search",
                reason="Select or search the recipient with the dedicated safe search submit tool.",
            ),
            _step(
                intent,
                "draft-research-communication-message",
                "Draft research communication message",
                "communication.compose",
                type_tool,
                input_preview=draft_input,
                depends_on=["submit-research-communication-recipient-search"],
                action="draft_message",
                reason="Draft the message from the generated research artifact before the approval-gated send step.",
            ),
            _step(
                intent,
                "send-research-communication-message",
                "Send research communication message",
                "communication.compose",
                send_tool,
                input_preview={"action": "send"},
                risk_level="high",
                approval_required=True,
                depends_on=["draft-research-communication-message"],
                action="send_message",
                reason="Final message sending remains approval-gated.",
            ),
        ]
    )
    return [*steps, *communication_steps]


def _append_desktop_content_artifact_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    depends_on: str,
    app_name: str,
    artifact_hint: Mapping[str, Any],
) -> list[ToolPlanStepSnapshot]:
    read_tool = _first_allowed(("desktop.ui_elements", "screen.capture"), allowed)
    read_input = (
        {"role_filter": "text", "limit": 120}
        if read_tool == "desktop.ui_elements"
        else {"reason": "Read the foreground app content after app search."}
        if read_tool == "screen.capture"
        else {}
    )
    if app_name and read_tool == "desktop.ui_elements":
        read_input["app_name"] = app_name
    artifact_path = str(artifact_hint.get("path") or "").strip() or _artifact_output_path(
        intent.user_goal,
        "desktop-content-report.md",
    )
    body_source = str(artifact_hint.get("body_source") or "").strip() or "desktop_content"
    next_steps = [
        *steps,
        _step(
            intent,
            "read-desktop-content",
            "Read desktop content",
            "desktop.app_discovery",
            read_tool,
            input_preview=read_input,
            depends_on=[depends_on],
            reason=(
                "Inspect the foreground app content after the app search before writing "
                "the requested artifact."
            ),
        ),
        _step(
            intent,
            "write-desktop-content-artifact",
            "Write desktop content artifact",
            "artifact.write",
            _first_allowed(("artifact.write",), allowed),
            input_preview={
                "path": artifact_path,
                "body_source": body_source,
            },
            depends_on=["read-desktop-content"],
            reason="Produce a durable artifact from the inspected desktop app content.",
        ),
    ]
    return _append_artifact_reveal_step(
        intent,
        allowed,
        next_steps,
        artifact_paths=[artifact_path],
        depends_on="write-desktop-content-artifact",
    )


def _append_desktop_content_followup_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    steps: list[ToolPlanStepSnapshot],
    *,
    depends_on: str,
    app_name: str,
) -> list[ToolPlanStepSnapshot]:
    read_tool = _first_allowed(("desktop.ui_elements", "screen.capture"), allowed)
    read_input = (
        {"role_filter": "text", "limit": 120}
        if read_tool == "desktop.ui_elements"
        else {"reason": "Read the foreground app content after app search."}
        if read_tool == "screen.capture"
        else {}
    )
    if app_name and read_tool == "desktop.ui_elements":
        read_input["app_name"] = app_name
    return [
        *steps,
        _step(
            intent,
            "read-desktop-content",
            "Read desktop content",
            "desktop.app_discovery",
            read_tool,
            input_preview=read_input,
            depends_on=[depends_on],
            reason=(
                "Inspect the foreground app content after the app search before returning "
                "the result to the model for the requested judgment or next step."
            ),
        ),
    ]


def _desktop_content_model_followup_requested(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    return bool(
        re.search(
            r"(?:并|然后|再|接着|之后|后).{0,8}"
            r"(?:读|读取|查看|看看|看一下|看下|判断|决定|分析|识别|告诉|说明|"
            r"下一步|该点哪里|该点哪个|能否|能不能|可以点|是否可以)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:and|then)\s+(?:read|inspect|check|judge|decide|analy[sz]e|"
            r"tell|explain|summari[sz]e|determine)\b",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:what|which|where|whether|can|should)\b.{0,40}"
            r"\b(?:click|press|tap|next|do)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _artifact_reveal_requested(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if not re.search(r"(?:Finder|访达)", value, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:显示|定位|找出|找一下|打开|查看|show|reveal|locate|view).{0,40}(?:Finder|访达)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:Finder|访达).{0,40}(?:显示|定位|找出|找一下|打开|查看|show|reveal|locate|view)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _artifact_reveal_path(text: str, artifact_paths: Iterable[str]) -> str:
    paths = [
        str(path or "").strip()
        for path in artifact_paths
        if str(path or "").strip()
    ]
    if not paths:
        return ""
    value = _clean_prompt(text)
    if _contains_any(value, ("csv", "表格", "汇总表", "table")):
        csv_path = _first_path_with_suffix(paths, (".csv", ".tsv"))
        if csv_path:
            return csv_path
    if _contains_any(value, ("图表", "趋势图", "chart", "plot")):
        chart_path = _first_path_with_suffix(paths, (".png", ".jpg", ".jpeg", ".svg"))
        if chart_path:
            return chart_path
    if _contains_any(value, ("报告", "摘要", "markdown", "md", "文档", "report", "summary", "document")):
        report_path = _first_path_with_suffix(paths, (".md", ".html", ".pdf", ".docx"))
        if report_path:
            return report_path
    return paths[0]


def _analysis_communication_artifact_path(text: str, artifact_paths: Iterable[str]) -> str:
    paths = [
        str(path or "").strip()
        for path in artifact_paths
        if str(path or "").strip()
    ]
    if not paths:
        return ""
    value = _clean_prompt(text)
    if _contains_any(value, ("报告", "report", "markdown", "md", "html", "文档", "document")):
        report_path = _first_path_with_suffix(paths, (".md", ".html", ".pdf", ".docx"))
        if report_path:
            return report_path
    if _contains_any(
        value,
        (
            "csv",
            "表格",
            "汇总表",
            "table",
            "spreadsheet",
            "导出",
            "输出表格",
            "整理成表格",
        ),
    ):
        table_path = _first_path_with_suffix(paths, (".csv", ".tsv", ".xlsx"))
        if table_path:
            return table_path
    if _contains_any(value, ("图表", "趋势图", "chart", "plot", "graph", "可视化")):
        chart_path = _first_path_with_suffix(paths, (".png", ".jpg", ".jpeg", ".svg"))
        if chart_path:
            return chart_path
    return paths[0]


def _first_path_with_suffix(paths: Iterable[str], suffixes: tuple[str, ...]) -> str:
    for path in paths:
        lowered = str(path or "").strip().lower()
        if lowered.endswith(suffixes):
            return str(path or "").strip()
    return ""


def _route_to_studio(intent: TaskIntentSnapshot, steps: list[ToolPlanStepSnapshot]) -> bool:
    return (
        intent.kind in {"workflow_orchestration", "multi_agent", "data_analysis", "code_task"}
        or any(step.approval_required for step in steps)
        or any(step.tool_name == "desktop.inspect_app" for step in steps)
        or len(steps) >= 3
    )


def _can_use_builtin_data_analysis(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
) -> bool:
    if _first_allowed(("data.analyze",), allowed) != "data.analyze":
        return False
    source_hint = str(intent.inputs.get("data_source_hint") or "").strip()
    source_kind = str(intent.inputs.get("data_source_kind") or "").strip()
    if not source_hint:
        return False
    if re.search(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", source_hint):
        return False
    if any(part == ".." for part in source_hint.replace("\\", "/").split("/")):
        return False
    if source_kind not in {"csv", "tsv", "json", "jsonl", "xlsx", "text", "text_table"}:
        return False
    return True


def _timeline_preview(intent: TaskIntentSnapshot, steps: list[ToolPlanStepSnapshot]) -> list[dict[str, Any]]:
    events = [
        {
            "event_type": "agent.intent.selected",
            "detail": intent.kind,
            "payload": {
                "intent_id": intent.intent_id,
                "confidence": intent.confidence,
                "required_capabilities": list(intent.required_capabilities),
            },
        }
    ]
    events.append(
        {
            "event_type": "agent.plan.created",
            "detail": f"{intent.title} Tool Plan",
            "payload": {
                "plan_id": _stable_id("runtime-plan", intent.kind, intent.user_goal),
                "tool_plan_id": _stable_id("tool-plan", intent.kind, intent.user_goal),
                "step_count": len(steps),
                "approvals_required": [step.step_id for step in steps if step.approval_required],
                "artifacts_expected": _artifacts_expected(intent, steps),
                "route_to_studio": _route_to_studio(intent, steps),
            },
        }
    )
    for index, step in enumerate(steps, start=1):
        events.append(
            {
                "event_type": "agent.plan.step",
                "detail": step.title,
                "payload": {
                    "sequence": index,
                    "step_id": step.step_id,
                    "capability_id": step.capability_id,
                    "tool": step.tool_name,
                    "status": step.status,
                    "approval_required": step.approval_required,
                },
            }
        )
    return events


def _clean_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", str(prompt or "").strip())


_ARTIFACT_OUTPUT_LOCATION_ALIASES = {
    "download": "Downloads",
    "downloads": "Downloads",
    "download folder": "Downloads",
    "downloads folder": "Downloads",
    "下载": "Downloads",
    "下载文件夹": "Downloads",
    "下载目录": "Downloads",
    "desktop": "Desktop",
    "桌面": "Desktop",
    "documents": "Documents",
    "documents folder": "Documents",
    "文档": "Documents",
    "文档文件夹": "Documents",
    "文档目录": "Documents",
    "文稿": "Documents",
}

_ARTIFACT_OUTPUT_LOCATION_PATTERNS = (
    re.compile(
        r"(?:保存|存到|另存|另存为|输出|导出|写入|放到|放进|生成|save|export|output|write|put)\s*"
        r"(?:到|至|在|进|为|成|to|in|into|as)?\s*"
        r"(?P<target>~/[^\s，。；,;]+|/[^\s，。；,;]+|[A-Za-z]:[\\/][^\s，。；,;]+|"
        r"Downloads?\b|downloads?\b|Desktop\b|desktop\b|Documents?\b|documents?\b|"
        r"下载文件夹|下载目录|下载|桌面|文档文件夹|文档目录|文档|文稿)"
    ),
    re.compile(
        r"(?:到|至|在|进|to|in|into)\s*"
        r"(?P<target>~/[^\s，。；,;]+|/[^\s，。；,;]+|[A-Za-z]:[\\/][^\s，。；,;]+|"
        r"Downloads?\b|downloads?\b|Desktop\b|desktop\b|Documents?\b|documents?\b|"
        r"下载文件夹|下载目录|下载|桌面|文档文件夹|文档目录|文档|文稿)"
        r"\s*(?:$|[，。；,;])"
    ),
)


def _artifact_output_path(text: str, filename: str) -> str:
    path = str(filename or "").strip()
    if not path:
        return path
    location = _artifact_output_location_hint(text)
    if not location or _artifact_path_has_directory(path):
        return path
    return f"{location.rstrip('/')}/{path.lstrip('/')}"


def _artifact_output_paths(text: str, filenames: Iterable[str]) -> list[str]:
    return [_artifact_output_path(text, filename) for filename in filenames]


def _artifact_output_location_hint(text: str) -> str:
    value = _clean_prompt(text)
    if not value:
        return ""
    for pattern in _ARTIFACT_OUTPUT_LOCATION_PATTERNS:
        for match in pattern.finditer(value):
            target = str(match.group("target") or "").strip()
            normalized = _normalize_artifact_output_location(target)
            if normalized:
                return normalized
    return ""


def _normalize_artifact_output_location(target: str) -> str:
    value = str(target or "").strip().rstrip("/\\")
    if not value:
        return ""
    if value.startswith(("~/", "/")) or re.match(r"^[A-Za-z]:[\\/]", value):
        return value
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    return _ARTIFACT_OUTPUT_LOCATION_ALIASES.get(normalized, "")


def _artifact_path_has_directory(path: str) -> bool:
    value = str(path or "").strip()
    if value.startswith(("/", "~/", "./", "../")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", value):
        return True
    return "/" in value or "\\" in value


def _stable_id(prefix: str, kind: Any, text: str) -> str:
    digest = hashlib.sha1(f"{kind}\n{text}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


_TASK_DELIVERABLE_TERMS = (
    "analyze",
    "analysis",
    "report",
    "summary",
    "research",
    "search",
    "test",
    "bug",
    "build",
    "分析",
    "数据分析",
    "统计",
    "汇总",
    "报告",
    "总结",
    "文档",
    "调研",
    "搜索",
    "输出",
    "生成",
    "测试",
    "修复",
    "代码",
)

_TASK_INTENT_KINDS = {"data_analysis", "web_research", "report_generation", "code_task", "file_organization"}

_COMMUNICATION_ACTION_TERMS = (
    "send to",
    "send ",
    "message ",
    "email ",
    "mail ",
    "发给",
    "发到",
    "发送",
    "发消息",
    "发邮件",
)

_SCHEDULE_ACTION_TERMS = (
    "remind",
    "calendar",
    "schedule",
    "event",
    "提醒",
    "日历",
    "日程",
    "安排",
)

_UI_CONTROL_TERMS = (
    "search box",
    "search field",
    "address bar",
    "input field",
    "text box",
    "搜索框",
    "搜索栏",
    "地址栏",
    "输入框",
    "输入栏",
    "文本框",
)

_BROWSER_SEARCH_INPUT_SELECTOR = (
    'input[type="search"], input[name="q"], textarea[name="q"], '
    'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
    'input[aria-label*="search" i], input[placeholder*="search" i]'
)

_BROWSER_TEXT_INPUT_SELECTOR = (
    'input:not([type]), input[type="text"], input[type="search"], '
    'textarea, [contenteditable="true"]'
)


def _intent_rank_score(intent: TaskIntentSnapshot, text: str) -> float:
    score = float(intent.confidence or 0)
    external_info_lookup = _looks_like_external_info_lookup(text)
    app_scoped_ui_operation = _app_scoped_ui_operation_hint(text)
    if intent.kind == "desktop_operation" and _looks_like_file_organization_request(text):
        score -= 0.3
    if intent.kind == "desktop_operation" and _looks_like_recipient_message_request(text):
        score -= 0.3
    if intent.kind == "desktop_operation" and _looks_like_communication_task_request(text):
        score -= 0.3
    if intent.kind == "desktop_operation" and _looks_like_schedule_request(text):
        score -= 0.2
    if (
        intent.kind == "desktop_operation"
        and _contains_any(text, _TASK_DELIVERABLE_TERMS)
        and not _looks_like_ui_operation(text)
        and not intent.inputs.get("app_search_hint")
    ):
        score -= 0.16
    if intent.kind == "desktop_operation" and _looks_like_ui_operation(text):
        score += 0.08
    if (
        intent.kind == "desktop_operation"
        and isinstance(intent.inputs.get("desktop_discovery_hint"), Mapping)
        and str(intent.inputs["desktop_discovery_hint"].get("action") or "").strip()
        == "discover_apps"
        and str(intent.inputs["desktop_discovery_hint"].get("query") or "").strip()
    ):
        score += 0.34
    if (
        intent.kind == "desktop_operation"
        and app_scoped_ui_operation
        and intent.inputs.get("app_name_hint")
    ):
        score += 0.28
    if (
        intent.kind == "desktop_operation"
        and intent.inputs.get("app_search_hint")
        and _desktop_content_artifact_requested(text)
    ):
        score += 0.32
    if intent.kind == "desktop_operation" and external_info_lookup:
        score -= 0.42
    if intent.kind == "desktop_operation" and intent.inputs.get("foreground_submit_action_hint"):
        score += 0.28 if intent.inputs.get("app_name_hint") else 0.14
    if intent.kind == "desktop_operation" and intent.inputs.get("app_management_hint"):
        score += -0.18 if _looks_like_generic_media_control_request(text) else 0.24
    if intent.kind == "desktop_operation" and _looks_like_generic_media_playback_request(text):
        score -= 0.42
    if (
        intent.kind == "desktop_operation"
        and str(intent.inputs.get("operation_hint") or "").strip() == "play"
        and str(media_playback_hint(text).get("action") or "").strip() == "play"
    ):
        score -= 0.2
    if (
        intent.kind == "desktop_operation"
        and _foreground_safe_shortcut_hint(intent.inputs.get("safe_shortcut_hint"))
    ):
        score += 0.24
    desktop_discovery = intent.inputs.get("desktop_discovery_hint")
    if (
        intent.kind == "desktop_operation"
        and isinstance(desktop_discovery, Mapping)
        and str(desktop_discovery.get("action") or "").strip() == "diagnose_permissions"
    ):
        score += 0.42
    if (
        intent.kind == "desktop_operation"
        and isinstance(desktop_discovery, Mapping)
        and str(desktop_discovery.get("action") or "").strip() == "read_active_window"
    ):
        score += 0.32
    if (
        intent.kind == "desktop_operation"
        and str(
            (intent.inputs.get("safe_shortcut_hint") or {}).get("action") or ""
        ).strip()
        == "new_document"
    ):
        score += 0.12
    if (
        intent.kind == "desktop_operation"
        and intent.inputs.get("app_search_hint")
        and not _looks_like_media_search_play_request(text)
    ):
        score += 0.26
    if (
        intent.kind == "desktop_operation"
        and intent.inputs.get("app_search_hint")
        and _web_search_query(text)
    ):
        score -= 0.36
    if intent.kind == "desktop_operation" and "window_list_hint" in intent.inputs:
        score += 0.2
    if intent.kind == "media_playback" and _contains_any(
        text,
        ["music", "song", "songs", "音乐", "歌曲", "歌"],
    ):
        score += 0.08
    if intent.kind == "media_playback" and str(intent.inputs.get("query") or "").strip():
        score += 0.08
    if (
        intent.kind == "media_playback"
        and str(intent.inputs.get("action") or "").strip() == "play"
        and not str(intent.inputs.get("query") or "").strip()
    ):
        score += 0.12
    if intent.kind == "media_playback" and _looks_like_generic_media_playback_request(text):
        score += 0.18
    if intent.kind == "information_capture" and _contains_any(
        text,
        ["note", "notes", "备忘录", "笔记", "记一下", "记录一下", "记下"],
    ):
        score += 0.08
    if intent.kind == "communication" and _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        score += 0.16
    if intent.kind == "communication" and _looks_like_recipient_message_request(text):
        score += 0.28
    if intent.kind == "communication" and _looks_like_communication_task_request(text):
        score += 0.26
    if intent.kind == "communication" and isinstance(intent.inputs.get("direct_message_hint"), Mapping):
        score += 0.18
    if intent.kind == "communication" and _looks_like_data_analysis_delivery_request(text):
        score -= 0.32
    if (
        intent.kind == "communication"
        and (
            external_info_lookup
            or bool(_url_hint(text))
            or _contains_any(
                text,
                ["research", "search", "调研", "研究", "搜索", "查询", "检索"],
            )
        )
        and not isinstance(intent.inputs.get("direct_message_hint"), Mapping)
        and not str(intent.inputs.get("context_source") or "").strip()
    ):
        score -= 0.42
    if intent.kind == "schedule" and _looks_like_communication_task_request(text):
        score -= 0.18
    if intent.kind == "schedule" and _looks_like_schedule_request(text):
        score += 0.22
    if intent.kind == "workflow_orchestration" and _contains_any(
        text,
        ["workflow", "flow", "工作流", "流程"],
    ):
        score += 0.26
    if intent.kind == "multi_agent" and (
        _contains_any(text, ["multi-agent", "group", "agents", "群组", "多 agent", "多Agent", "协作"])
        or _looks_like_multi_agent_request(text)
        or bool(intent.inputs.get("target_name_hint"))
    ):
        score += 0.28
        if _looks_like_explicit_group_run_request(text):
            score += 0.24
    if intent.kind in _TASK_INTENT_KINDS and _contains_any(text, _TASK_DELIVERABLE_TERMS):
        score += 0.06
    if intent.kind == "file_organization" and _looks_like_file_organization_request(text):
        score += 0.18
    if (
        intent.kind == "data_analysis"
        and not external_info_lookup
        and str(intent.inputs.get("context_source") or "").strip()
        and _contains_any(text, ["数据", "表格", "data", "table", "csv", "统计", "分析"])
    ):
        score += 0.38
    if (
        intent.kind == "data_analysis"
        and isinstance(intent.inputs.get("communication_target_hint"), Mapping)
    ):
        score += 0.34
    if intent.kind == "data_analysis" and external_info_lookup:
        score -= 0.36
    if (
        intent.kind == "data_analysis"
        and _data_source_or_output_mentioned(text)
        and _data_analysis_action_requested(text)
    ):
        score += 0.22
    if (
        intent.kind == "data_analysis"
        and _contains_any(text, ["workflow", "flow", "工作流", "流程"])
        and _contains_any(text, ["run", "start", "create", "启动", "运行", "创建", "执行"])
    ):
        score -= 0.5
    if intent.kind == "data_analysis" and _looks_like_current_page_data_context_source(text):
        score += 0.28
    if (
        intent.kind == "report_generation"
        and _data_source_or_output_mentioned(text)
        and _data_analysis_action_requested(text)
    ):
        score -= 0.22
    if (
        intent.kind == "web_research"
        and _contains_any(text, _UI_CONTROL_TERMS)
        and str(intent.inputs.get("browser_action") or "").strip() != "type_text"
    ):
        score -= 0.24
    if intent.kind == "web_research" and _local_app_discovery_query(text):
        score -= 0.42
    if (
        intent.kind == "web_research"
        and app_management_hint(text)
        and not _looks_like_generic_media_control_request(text)
    ):
        score -= 0.32
    if (
        intent.kind == "web_research"
        and _desktop_content_artifact_requested(text)
        and _app_name_hint(text)
        and not _is_browser_or_search_app_name(_app_name_hint(text))
    ):
        score -= 0.28
    if (
        intent.kind == "web_research"
        and not str(intent.inputs.get("url_hint") or "").strip()
        and not str(intent.inputs.get("context_source") or "").strip()
        and not str(intent.inputs.get("browser_action") or "").strip()
        and _foreground_safe_shortcut_hint(safe_shortcut_hint(text))
    ):
        score -= 0.36
    if (
        intent.kind == "web_research"
        and str(intent.inputs.get("browser_action") or "").strip() == "find_current_page"
    ):
        score += 0.28
    if (
        intent.kind == "web_research"
        and str(intent.inputs.get("browser_action") or "").strip() == "type_text"
    ):
        score += 0.34
    if (
        intent.kind == "web_research"
        and str(intent.inputs.get("browser_action") or "").strip() == "click"
    ):
        score += 0.34
        if app_scoped_ui_operation:
            score -= 0.38
    if (
        intent.kind == "web_research"
        and str(intent.inputs.get("browser_action") or "").strip()
        in {"open_url", "open_url_extract", "open_url_screenshot"}
    ):
        score += 0.42
    if intent.kind == "web_research" and _contains_any(
        text,
        [
            "http://",
            "https://",
            "research",
            "search",
            "latest",
            "news",
            "pricing",
            "price",
            "调研",
            "研究",
            "新闻",
            "搜索",
            "查找",
            "查询",
            "检索",
            "最新",
            "价格",
            "定价",
            "报价",
            "网页",
            "网站",
        ],
    ):
        score += 0.14
    if intent.kind == "web_research" and external_info_lookup:
        score += 0.34
    if intent.kind == "web_research" and _looks_like_explicit_group_run_request(text):
        score -= 0.36
    if intent.kind == "web_research" and _looks_like_schedule_request(text):
        score -= 0.24
    if intent.kind == "web_research" and _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        score -= 0.18
    if (
        intent.kind == "web_research"
        and isinstance(intent.inputs.get("communication_target_hint"), Mapping)
    ):
        score += 0.42
    if (
        intent.kind == "web_research"
        and str(intent.inputs.get("target_app_hint") or "").strip()
    ):
        score += 0.28
    if (
        intent.kind == "web_research"
        and _report_file_context_hint(text)
        and not _contains_any(text, ["http://", "https://", "网页", "网站", "url", "link"])
    ):
        score -= 0.28
    if intent.kind == "report_generation":
        if _contains_any(text, ["report", "summary", "报告", "总结", "文档", "输出", "生成"]):
            score += 0.04
        if _foreground_app_search_hint(text):
            score -= 0.32
        if _looks_like_schedule_request(text):
            score -= 0.24
        if str(intent.inputs.get("context_source") or "").strip():
            score += 0.34
        file_context = intent.inputs.get("file_context_hint")
        if isinstance(file_context, Mapping):
            score += 0.3 if str(file_context.get("file_type") or "").strip() else 0.08
            if _contains_any(
                text,
                [
                    "data",
                    "dataset",
                    "csv",
                    "xlsx",
                    "excel",
                    "spreadsheet",
                    "数据",
                    "数据集",
                    "表格",
                    "销售数据",
                    "分析",
                    "统计",
                ],
            ):
                score -= 0.32
        if _contains_any(text, ["http://", "https://", "research", "search", "latest", "news", "调研", "研究", "新闻", "搜索"]):
            score -= 0.04
    if intent.kind == "data_analysis" and (
        data_source_hint(text)
        or _contains_any(text, ["data analysis", "analyze data", "数据分析", "分析数据", "csv", "xlsx", "表格"])
    ):
        score += 0.08 if not external_info_lookup else 0.0
    if intent.kind == "code_task" and _contains_any(
        text,
        ["code", "test", "bug", "build", "repo", "代码", "测试", "修复", "仓库"],
    ):
        score += 0.08
    return max(score, 0.0)


def _web_research_artifact_requested(intent: TaskIntentSnapshot) -> bool:
    outputs = {
        str(item or "").strip()
        for item in intent.expected_outputs
        if str(item or "").strip()
    }
    if outputs.intersection({"report", "table"}):
        return True
    return _contains_any(
        intent.user_goal,
        [
            "write up",
            "write a report",
            "report",
            "table",
            "markdown",
            "md file",
            "document",
            "artifact",
            "报告",
            "文档",
            "文件",
            "产物",
            "生成报告",
            "输出报告",
            "整理成表格",
            "整理为表格",
            "输出表格",
            "生成表格",
        ],
    )


def _score_terms(text: str, terms: Iterable[str]) -> float:
    lowered = text.lower()
    score = 0.0
    for term in terms:
        if str(term).lower() in lowered:
            score += 0.08
    return min(score, 0.45)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(str(term).lower() in lowered for term in terms)


def _context_artifact_source_hint(text: str) -> str:
    if _looks_like_visible_text_artifact_source(text):
        return "visible_text"
    source = _task_context_source_hint(text)
    if source:
        return source
    if _looks_like_current_page_artifact_source(text):
        return "current_page_content"
    return ""


def _communication_context_source_hint(text: str) -> str:
    if _looks_like_visible_text_artifact_source(text):
        return "visible_text"
    source = _task_context_source_hint(text)
    if source:
        return source
    if _communication_file_context_hint(text):
        return "file"
    if _looks_like_current_page_artifact_source(text):
        return "current_page_content"
    return ""


def _communication_file_context_hint(
    text: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    source_hint = str(data_source_hint(text, metadata) or "").strip()
    if not source_hint:
        return {}
    source_scope = str(data_source_scope_hint(text, metadata) or "").strip()
    source_kind = data_source_kind_hint(source_hint, text)
    path = _scoped_data_source_path(source_hint, source_scope)
    hint = _data_source_inspect_input_preview(path, source_kind)
    if source_kind:
        hint.setdefault("source_kind", source_kind)
    return hint


def _communication_content_transform_hint(text: str) -> str:
    value = _clean_prompt(text)
    if not value:
        return ""
    if _contains_any(value, ("报告", "report", "文档", "document", "markdown", "md")):
        return "report"
    if _contains_any(value, ("摘要", "总结", "概括", "summary", "summarize")):
        return "summary"
    return ""


def _app_search_result_communication_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not value or not _contains_any(value, _COMMUNICATION_ACTION_TERMS):
        return {}
    if not _contains_any(
        value,
        (
            "搜索结果",
            "当前结果",
            "查询结果",
            "检索结果",
            "结果",
            "search result",
            "search results",
            "results",
        ),
    ):
        return {}
    target = _app_search_result_communication_target_text(value)
    if not target:
        return {}

    foreground_search = _foreground_app_search_hint(value)
    source_app = ""
    source_scope = ""
    query = ""
    if foreground_search:
        source_scope = "foreground"
        query = str(foreground_search.get("query") or "").strip()
    else:
        source_search = _app_search_result_source_hint(value)
        if source_search:
            source_app = str(source_search.get("app_name") or "").strip()
            query = str(source_search.get("query") or "").strip()
        else:
            leading_search = _leading_app_search_hint(value)
            source_app = str(leading_search.get("app_name") or "").strip()
            query = str(leading_search.get("query") or "").strip()
            if not source_app:
                source_app = _app_name_hint(value)
            if source_app and not query:
                query = _app_search_query_hint(value, source_app)

    query = _clean_app_search_query(query)
    if not query:
        return {}

    target_app, recipient = _split_communication_surface_and_recipient(target)
    if not recipient:
        recipient = _clean_communication_recipient_text(target)
    if not target_app and recipient:
        target_app = _communication_surface_for_recipient_hint(recipient)
    if (
        not target_app
        and source_app
        and supports_new_message_app_hint(source_app)
    ):
        target_app = source_app
    if not recipient:
        return {}

    hint: dict[str, str] = {
        "recipient": recipient,
        "body_source": "app_search_result",
        "source_app_search_query": query,
        "mode": _communication_app_mode(value),
        "send_action": "send",
    }
    if target_app:
        hint["app_name"] = target_app
    if source_app:
        hint["source_app_name"] = source_app
        hint["source_app_mode"] = _app_search_result_source_mode(value)
    if source_scope:
        hint["source_scope"] = source_scope
    transform = _communication_content_transform_hint(value)
    if transform:
        hint["content_transform_hint"] = transform
    return hint


def _app_search_result_source_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not value:
        return {}
    search_verb = r"(?:搜索|查找|查询|检索|找(?:到)?)"
    result_noun = r"(?:搜索结果|查询结果|检索结果|结果)"
    delivery_verb = r"(?:发给|发送给|发到|发送到|转发给|转发到)"
    patterns = (
        rf"^(?:把|将)\s*(?:在\s*)?(?P<app>[\w .·-]{{1,60}}?)"
        rf"(?:\s*(?:里|中|上|内))?\s*{search_verb}\s*"
        rf"(?P<query>[^。！？!?，,]+?)\s*(?:的)?{result_noun}"
        rf"[^。！？!?]{{0,40}}?{delivery_verb}",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _canonical_app_name_hint(match.group("app"))
        query = _clean_app_search_query(match.group("query"))
        if (
            app_name
            and query
            and not _invalid_app_scoped_followup_app(app_name)
            and not _is_generic_foreground_app_label(app_name)
        ):
            return {"app_name": app_name, "query": query}
    return {}


def _app_search_result_communication_target_text(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"(?:把|将)?.{0,40}?(?:搜索结果|当前结果|查询结果|检索结果|结果).{0,30}?"
        r"(?:发给|发送给|发到|发送到|转发给|转发到)\s*(?P<target>[^。！？!?]+)$",
        r"(?:send|message|forward)\s+(?:the\s+)?(?:search\s+)?results?\s+"
        r"(?:to|for)\s+(?P<target_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        return _clean_communication_hint_text(
            match.groupdict().get("target")
            or match.groupdict().get("target_en")
            or ""
        )
    return ""


def _app_search_result_source_mode(text: str) -> str:
    value = _clean_prompt(text)
    if re.search(r"(?:打开|启动|开启|open|launch|start)", value, flags=re.IGNORECASE):
        return "open"
    return "focus"


def _web_research_communication_target_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not value or not _contains_any(value, _COMMUNICATION_ACTION_TERMS):
        return {}
    if not (
        _looks_like_external_info_lookup(value)
        or _contains_any(value, ("调研", "研究", "搜索", "查找", "查询", "检索", "research", "search"))
    ):
        return {}
    target = _web_research_delivery_target_text(value)
    if not target:
        return {}
    app_name, recipient = _split_communication_surface_and_recipient(target)
    if not recipient:
        recipient = _clean_communication_recipient_text(target)
        if recipient and not app_name:
            app_name = _communication_surface_for_recipient_hint(recipient)
    if not recipient:
        return {}
    hint: dict[str, str] = {
        "recipient": recipient,
        "body_source": "research_artifact",
        "mode": _communication_app_mode(value),
        "send_action": "send",
    }
    if app_name:
        hint["app_name"] = app_name
    channel = _data_analysis_delivery_channel_hint(value)
    if channel:
        hint["channel"] = channel
    transform = _communication_content_transform_hint(value)
    if transform:
        hint["content_transform_hint"] = transform
    return hint


def _web_research_delivery_target_text(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"(?:把|将)?.{0,80}?(?:报告|摘要|总结|表格|结果|内容|调研|研究|research|report|summary)?"
        r".{0,30}?(?:发给|发送给|发到|发送到|转发给|转发到)\s*(?P<target>[^。！？!?]+)$",
        r"(?:send|message|forward)\s+(?:the\s+)?"
        r"(?:research|report|summary|results?|content)?\s*"
        r"(?:to|for)\s+(?P<target_en>[^.!?]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        return _clean_communication_hint_text(
            match.groupdict().get("target")
            or match.groupdict().get("target_en")
            or ""
        )
    return ""


def _data_analysis_communication_target_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not _looks_like_data_analysis_delivery_request(value):
        return {}
    target = _data_analysis_delivery_target_text(value)
    if not target:
        return {}
    app_name, recipient = _split_communication_surface_and_recipient(target)
    if not recipient:
        recipient = _clean_communication_recipient_text(target)
        if recipient and not app_name:
            app_name = _communication_surface_for_recipient_hint(recipient)
    if not recipient:
        return {}
    hint: dict[str, str] = {
        "recipient": recipient,
        "body_source": "analysis_artifact",
        "mode": _communication_app_mode(value),
        "send_action": "send",
    }
    if app_name:
        hint["app_name"] = app_name
    channel = _data_analysis_delivery_channel_hint(value)
    if channel:
        hint["channel"] = channel
    transform = _communication_content_transform_hint(value)
    if transform:
        hint["content_transform_hint"] = transform
    return hint


def _looks_like_data_analysis_delivery_request(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if not _data_delivery_send_requested(value):
        return False
    return _data_source_or_output_mentioned(value) and _data_analysis_action_requested(value)


def _looks_like_data_delivery_without_analysis(text: str) -> bool:
    value = _clean_prompt(text)
    if not _data_delivery_send_requested(value):
        return False
    if _data_analysis_action_requested(value):
        return False
    return _data_source_or_output_mentioned(value)


def _data_delivery_send_requested(text: str) -> bool:
    return _contains_any(
        text,
        (
            "发给",
            "发到",
            "发送给",
            "发送到",
            "发邮件",
            "发送邮件",
            "分享给",
            "转发给",
            "send ",
            "email ",
            "share ",
        ),
    )


def _data_source_or_output_mentioned(text: str) -> bool:
    return _contains_any(
        text,
        (
            "数据",
            "数据集",
            "表格",
            "csv",
            "tsv",
            "xlsx",
            "xls",
            "json",
            "parquet",
            "dataset",
            "table",
            "spreadsheet",
        ),
    )


def _data_analysis_action_requested(text: str) -> bool:
    value = _clean_prompt(text)
    return _contains_any(
        value,
        (
            "分析",
            "数据分析",
            "统计",
            "汇总",
            "趋势",
            "可视化",
            "图表",
            "报告",
            "分析成",
            "分析为",
            "chart",
            "plot",
            "graph",
            "analyze",
            "analyse",
            "analysis",
            "summary",
            "summarize",
            "trend",
            "report",
        ),
    )


def _data_analysis_delivery_target_text(text: str) -> str:
    value = _clean_prompt(text)
    recipient_stop = (
        r"(?=(?:\s*(?:并|然后|再|之后|后)?\s*"
        r"(?:说明|说|附上|备注|告诉|解释|汇报|概括)|[，,。；;！!？?]|$))"
    )
    patterns = (
        r"(?:然后|并|再|之后|后|同时)?\s*(?:把|将)?"
        r"(?:生成的|这份|这个|分析的|分析)?"
        r"(?:数据分析)?(?:报告|结果|图表报告|图表|csv|CSV|汇总|分析结果|产物|文件)?"
        r"\s*"
        r"(?:(?:发|发送|分享|转发)\s*"
        r"(?:邮件|电子邮件|消息|微信|email|e-mail|mail|message)?\s*"
        r"(?:给|到|发给|发送给|向|对)|(?:发给|发送给|发到|发送到|分享给|转发给))\s*"
        rf"(?P<target>[^，,。；;！!？?\n]+?){recipient_stop}",
        r"(?:send|share)\s+(?:the\s+)?"
        r"(?:(?:analysis|data)\s+)?(?:report|result|results|artifact|chart|csv|table|summary)?"
        r"\s*(?:to|with)\s+(?P<target>[^.!?,;\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        target = _clean_communication_hint_text(match.group("target") or "")
        target = re.sub(
            r"\s*(?:并|然后|再|之后|后)\s*(?:发送|发出|send)?$",
            "",
            target,
            flags=re.IGNORECASE,
        ).strip()
        if target:
            return target
    return ""


def _data_analysis_delivery_channel_hint(text: str) -> str:
    value = _clean_prompt(text)
    if re.search(
        r"(?:发|发送|写|撰写|起草|草拟)\s*(?:一封|封)?\s*(?:邮件|电子邮件)"
        r"|(?:send|email|mail)\b",
        value,
        flags=re.IGNORECASE,
    ):
        return "email"
    return ""


def _task_context_source_hint(text: str) -> str:
    source = context_source_hint(text)
    if (
        source == "clipboard"
        and _clipboard_output_target_requested(text)
        and not _clipboard_context_source_requested(text)
    ):
        return ""
    return source


def _task_output_target_hint(text: str) -> str:
    return "clipboard" if _clipboard_output_target_requested(text) else ""


def _clipboard_output_target_requested(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    return bool(
        re.search(
            r"(?:复制|拷贝|写入|放到|放进|保存到|输出到|输出至|复制到|拷贝到|存到|设为|设置为)"
            r"(?:一下|下)?\s*(?:到|进|至)?\s*(?:系统)?(?:剪贴板|粘贴板)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:到|进|至)\s*(?:系统)?(?:剪贴板|粘贴板)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:copy|write|put|save|output)\b.{0,80}\b(?:to|into)\s+"
            r"(?:the\s+)?(?:system\s+)?clipboard\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _clipboard_context_source_requested(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    return bool(
        re.search(
            r"(?:剪贴板|粘贴板).{0,8}(?:内容|里|里面|中的|上|中|里的)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:根据|使用|用|读取|读|从).{0,8}(?:剪贴板|粘贴板)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:clipboard\s+contents?|contents?\s+of\s+(?:the\s+)?clipboard|"
            r"from\s+(?:the\s+)?clipboard|using\s+(?:the\s+)?clipboard)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _clipboard_output_step(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    *,
    depends_on: list[str],
    body_source: str,
) -> ToolPlanStepSnapshot:
    return _step(
        intent,
        "write-clipboard-output",
        "Write clipboard output",
        "clipboard.read_write",
        _first_allowed(("clipboard.write",), allowed),
        input_preview={
            "body_source": body_source,
            "transform": _clipboard_output_transform_hint(intent.user_goal),
        },
        depends_on=depends_on,
        reason="Write the generated task result to the clipboard after inspecting the requested source.",
    )


def _clipboard_output_transform_hint(text: str) -> str:
    value = _clean_prompt(text)
    if _contains_any(value, ("摘要", "总结", "summary", "summarize")):
        return "summary"
    if _contains_any(value, ("报告", "report", "文档", "document")):
        return "report"
    return "text"


def _web_clipboard_body_source(browser_action: str) -> str:
    action = str(browser_action or "").strip()
    if action in {"current_page", "extract_text", "screenshot"}:
        return "current_page_content"
    if action in {"open_url_extract", "open_url_screenshot", "open_url"}:
        return "web_url_content"
    if action == "open_search":
        return "web_search_result"
    return "web_content"


def _looks_like_visible_data_context_source(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if _contains_any(
        value,
        [
            "current page",
            "current webpage",
            "this page",
            "this webpage",
            "当前网页",
            "当前页面",
            "当前页",
            "这个网页",
            "这个页面",
        ],
    ):
        return False
    return _visible_context_marker_matches(value) and _visible_data_marker_matches(value)


def _looks_like_desktop_visible_data_context_source(text: str) -> bool:
    value = _clean_prompt(text)
    if not value or not _contains_any(value, ["桌面", "desktop"]):
        return False
    if _contains_any(
        value,
        [
            "桌面文件",
            "桌面文件夹",
            "桌面目录",
            "Desktop folder",
            "desktop folder",
            "Desktop directory",
            "desktop directory",
        ],
    ):
        return False
    data_marker = r"(?:表格|表|数据|数据集|电子表格|table|data|dataset|spreadsheet)"
    deictic_marker = r"(?:这个|这张|这份|这条|这组|当前|可见|正在显示(?:的)?)"
    desktop_marker = r"(?:桌面(?:上|里|中|内)?|desktop)"
    return bool(
        re.search(
            rf"{desktop_marker}.{{0,12}}{deictic_marker}.{{0,12}}{data_marker}",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"{deictic_marker}.{{0,12}}{data_marker}.{{0,12}}{desktop_marker}",
            value,
            flags=re.IGNORECASE,
        )
    )


def _visible_context_marker_matches(value: str) -> bool:
    if _contains_any(
        value,
        [
            "current window",
            "current app",
            "current application",
            "current screen",
            "foreground window",
            "foreground app",
            "visible table",
            "visible data",
            "visible spreadsheet",
            "on screen",
            "onscreen",
            "shown on screen",
            "当前窗口",
            "当前应用",
            "当前 app",
            "当前App",
            "当前软件",
            "前台窗口",
            "前台应用",
            "前台",
            "当前界面",
            "当前屏幕",
            "屏幕上",
            "屏幕里",
            "屏幕中的",
            "界面上",
            "界面里",
            "界面中的",
            "窗口里",
            "窗口中的",
            "可见",
            "正在显示",
            "显示的",
        ],
    ):
        return True
    return bool(
        re.search(
            r"(?:当前|前台|打开的|正在显示的|屏幕上|界面上).{0,24}"
            r"(?:表格|电子表格|数据)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:表格|电子表格|数据).{0,24}"
            r"(?:当前|前台|打开的|正在显示的|屏幕上|界面上)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _visible_data_marker_matches(value: str) -> bool:
    return _contains_any(
        value,
        [
            "table",
            "tabular",
            "spreadsheet",
            "worksheet",
            "sheet",
            "data",
            "dataset",
            "csv",
            "tsv",
            "xlsx",
            "xls",
            "json",
            "表格",
            "数据",
            "电子表格",
            "这张表",
            "这个表",
            "当前表",
            "前台表",
        ],
    )


def _looks_like_current_page_data_context_source(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    return _contains_any(
        value,
        [
            "current page",
            "current webpage",
            "this page",
            "this webpage",
            "当前网页",
            "当前页面",
            "当前页",
            "这个网页",
            "这个页面",
            "这页",
        ],
    ) and _contains_any(
        value,
        [
            "table",
            "tabular",
            "spreadsheet",
            "data",
            "dataset",
            "csv",
            "tsv",
            "xlsx",
            "xls",
            "json",
            "price table",
            "pricing table",
            "表格",
            "数据",
            "数据集",
            "电子表格",
            "价格表",
            "销售表",
            "数据表",
            "明细表",
            "报表",
        ],
    )


def _looks_like_visible_text_artifact_source(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if _contains_any(
        value,
        [
            "current page",
            "current webpage",
            "this page",
            "this webpage",
            "当前网页",
            "当前页面",
            "当前页",
            "这个网页",
            "这个页面",
        ],
    ):
        return False
    return _contains_any(
        value,
        [
            "current window",
            "current app",
            "current application",
            "current screen",
            "foreground window",
            "foreground app",
            "visible text",
            "当前窗口",
            "当前应用",
            "当前 app",
            "当前App",
            "当前软件",
            "前台窗口",
            "前台应用",
            "当前界面",
            "当前屏幕",
            "屏幕内容",
            "界面内容",
        ],
    ) and _contains_any(
        value,
        [
            "content",
            "text",
            "summarize",
            "summary",
            "write",
            "report",
            "document",
            "markdown",
            "md",
            "内容",
            "文字",
            "文本",
            "总结",
            "摘要",
            "整理",
            "报告",
            "文档",
            "文件",
            "保存",
            "产物",
        ],
    )


def _looks_like_current_page_artifact_source(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if _contains_any(
        value,
        [
            "current page link",
            "current url",
            "当前网页链接",
            "当前页面链接",
            "当前链接",
            "当前页地址",
        ],
    ):
        return False
    return _contains_any(
        value,
        [
            "current page",
            "current webpage",
            "this page",
            "this webpage",
            "当前网页",
            "当前页面",
            "当前页",
            "这个网页",
            "这个页面",
            "这页",
        ],
    ) and _contains_any(
        value,
        [
            "summarize",
            "summary",
            "write",
            "report",
            "document",
            "markdown",
            "md",
            "总结",
            "摘要",
            "整理",
            "报告",
            "文档",
            "文件",
            "产物",
        ],
    )


def _looks_like_context_artifact_request(text: str) -> bool:
    source = _context_artifact_source_hint(text)
    if not source:
        return False
    return _contains_any(
        text,
        [
            "summarize",
            "summary",
            "write",
            "report",
            "document",
            "artifact",
            "markdown",
            "md",
            "整理成",
            "整理为",
            "整理",
            "总结",
            "摘要",
            "报告",
            "文档",
            "文件",
            "产物",
            "周报",
            "日报",
            "简报",
        ],
    )


def _looks_like_scoped_data_analysis_request(text: str) -> bool:
    if not data_source_scope_hint(text, {}):
        return False
    return _contains_any(
        text,
        [
            "csv",
            "tsv",
            "xlsx",
            "xls",
            "json",
            "parquet",
            "数据",
            "数据集",
            "表格",
            "电子表格",
        ],
    ) and _contains_any(
        text,
        [
            "analyze",
            "analyse",
            "analysis",
            "summarize",
            "summary",
            "trend",
            "report",
            "chart",
            "plot",
            "分析",
            "统计",
            "汇总",
            "总结",
            "摘要",
            "趋势",
            "报告",
            "图表",
            "可视化",
        ],
    )


def _looks_like_local_observation_or_control_request(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if _finder_special_location_hint(value) or screen_capture_hint(value):
        return True
    media_hint = media_playback_hint(value)
    if str(media_hint.get("action") or "").strip() == "status":
        return True
    if _contains_any(
        value,
        [
            "屏幕",
            "界面",
            "窗口",
            "当前播放",
            "播放状态",
            "播放进度",
            "在播状态",
            "screen",
            "my screen",
            "window",
            "interface",
            "currently playing",
            "playback status",
        ],
    ) and not _contains_any(
        value,
        ["网页", "页面", "网站", "浏览器", "webpage", "web page", "page", "browser", "website"],
    ):
        return True
    return False


def _looks_like_external_info_lookup(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if _looks_like_local_observation_or_control_request(value):
        return False
    if context_source_hint(value) or data_source_hint(value) or data_source_scope_hint(value):
        return False
    lookup_action = re.search(
        r"(?:research|search|look\s+up|find\s+out|find|查找|查询|检索|搜索|调研|研究|了解|找一下|找下|查一下|查查|查(?!看)|看一下|看看)",
        value,
        flags=re.IGNORECASE,
    )
    external_subject = _contains_any(
        value,
        [
            "latest",
            "current",
            "recent",
            "news",
            "pricing",
            "price",
            "cost",
            "release",
            "version",
            "official",
            "website",
            "web",
            "最新",
            "当前",
            "现在",
            "最近",
            "新闻",
            "价格",
            "定价",
            "报价",
            "费用",
            "官网",
            "网站",
            "网页",
            "发布",
            "版本",
        ],
    )
    if lookup_action and external_subject:
        return True
    return bool(
        _contains_any(value, ["latest", "最新", "最近", "news", "新闻"])
        and _contains_any(value, ["pricing", "price", "价格", "定价", "报价", "release", "版本"])
    )


def _spreadsheet_ui_app_hint(text: str) -> str:
    value = _clean_prompt(text)
    app_pattern = r"(?P<app>Microsoft\s+Excel|Apple\s+Numbers|Excel|Numbers)"
    blocked_pattern = r"(?:Microsoft\s+Excel|Apple\s+Numbers|Excel|Numbers)"
    if re.search(
        rf"(?:不要|别|无需|不需要|不用|不要用|不要打开|别打开|无需打开|不打开)\s*{blocked_pattern}",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        rf"(?:do\s+not|don't|dont|without|no\s+need\s+to)\s+"
        rf"(?:open|launch|use)?\s*(?:the\s+)?{blocked_pattern}",
        value,
        flags=re.IGNORECASE,
    ):
        return ""
    patterns = (
        rf"(?:用|通过|在)\s*{app_pattern}\s*(?:里|中|上|来|去)?\s*(?:分析|统计|汇总|打开|查看|编辑)",
        rf"(?:打开|启动|开启)\s*{app_pattern}\s*(?:来|去)?\s*(?:分析|统计|汇总|打开|查看|编辑)?",
        rf"\b(?:use|using|with|in|open|launch|start)\s+(?:the\s+)?{app_pattern}\b"
        r".{0,40}\b(?:analy[sz]e|summari[sz]e|open|view|edit)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app = re.sub(r"\s+", " ", str(match.group("app") or "").strip())
        if app.lower() == "microsoft excel":
            return "Excel"
        if app.lower() == "apple numbers":
            return "Numbers"
        return "Numbers" if app.lower() == "numbers" else "Excel"
    return ""


def _file_location_hint(text: str) -> str:
    path_match = re.search(r"((?:~|/)[^\s，,。]+)", text)
    if path_match:
        return path_match.group(1).rstrip("。.,")
    lowered = text.lower()
    known_locations = (
        ("downloads", "Downloads"),
        ("download folder", "Downloads"),
        ("下载文件夹", "Downloads"),
        ("下载目录", "Downloads"),
        ("下载", "Downloads"),
        ("desktop", "Desktop"),
        ("桌面", "Desktop"),
        ("documents", "Documents"),
        ("文档", "Documents"),
    )
    for marker, location in known_locations:
        if marker in lowered:
            return location
    return ""


def _file_destination_hint(text: str, *, source_hint: str = "") -> str:
    value = _clean_prompt(text)
    if not value:
        return ""
    patterns = (
        re.compile(
            r"(?:整理|分类|移动|搬|挪|归档|复制|放|放入|放进|移到|移入)"
            r".{0,24}?(?:到|至|进|入)\s*(?P<target>[^，。；,;]+)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:to|into|under|inside)\s+(?:the\s+)?(?P<target>[^，。；,;]+)",
            flags=re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        match = pattern.search(value)
        if not match:
            continue
        destination = _normalize_file_destination(match.group("target"))
        if destination and destination != source_hint:
            return destination
    return ""


def _normalize_file_destination(target: str) -> str:
    value = str(target or "").strip().strip("\"'`“”‘’")
    value = re.sub(
        r"\s*(?:folder|directory|dir|文件夹|目录|中|里|内|下)\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = value.rstrip("/\\。.,，；;")
    if not value:
        return ""
    generic = {
        "a",
        "a folder",
        "one folder",
        "new folder",
        "folder",
        "directory",
        "dir",
        "一个",
        "一个新",
        "一个新的",
        "一个文件夹",
        "新文件夹",
    }
    if value.casefold() in generic:
        return ""
    if value.startswith(("~/", "/")) or re.match(r"^[A-Za-z]:[\\/]", value):
        return value
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    aliases = {
        "download": "Downloads",
        "downloads": "Downloads",
        "desktop": "Desktop",
        "documents": "Documents",
        "document": "Documents",
        "docs": "Documents",
        "screenshots": "Screenshots",
        "screenshot": "Screenshots",
        "screen shots": "Screenshots",
        "pictures": "Pictures",
        "picture": "Pictures",
        "images": "Pictures",
        "image": "Pictures",
        "movies": "Movies",
        "videos": "Movies",
        "video": "Movies",
        "music": "Music",
        "audio": "Music",
        "下载": "Downloads",
        "桌面": "Desktop",
        "文档": "Documents",
        "文稿": "Documents",
        "截图": "Screenshots",
        "截屏": "Screenshots",
        "图片": "Pictures",
        "照片": "Pictures",
        "影片": "Movies",
        "视频": "Movies",
        "音乐": "Music",
        "音频": "Music",
    }
    return aliases.get(normalized, value)


def _file_type_hint(text: str) -> str:
    lowered = _text_before_file_destination(text).lower()
    file_types = (
        (("screenshot", "screenshots", "screen shot", "screen shots", "截图", "截屏"), "screenshot"),
        (("image", "images", "photo", "photos", "picture", "pictures", "图片", "照片", "图像"), "image"),
        (("pdf",), "pdf"),
        (("invoice", "invoices", "receipt", "receipts", "发票", "票据", "收据"), "invoice"),
        (("docx", "word", ".doc", ".docx", "word 文档", "文档文件", "文档资料"), "document"),
        (("spreadsheet", "spreadsheets", "xlsx", "xls", "csv", "tsv", "表格", "电子表格"), "spreadsheet"),
        (("archive", "archives", "zip", "rar", "7z", "压缩包", "归档包"), "archive"),
        (("audio", "music", "mp3", "wav", "音频", "音乐"), "audio"),
        (("video", "movie", ".mp4", ".mov", ".m4v", ".avi", ".mkv", "视频", "影片"), "video"),
    )
    for markers, file_type in file_types:
        if _contains_any(lowered, markers):
            return file_type
    return ""


def _text_before_file_destination(text: str) -> str:
    value = str(text or "")
    patterns = (
        re.compile(
            r"(?:整理|分类|移动|搬|挪|归档|复制|放|放入|放进|移到|移入)"
            r".{0,24}?(?:到|至|进|入)\s*(?P<target>[^，。；,;]+)",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:to|into|under|inside)\s+(?:the\s+)?(?P<target>[^，。；,;]+)",
            flags=re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        match = pattern.search(value)
        if match:
            return value[: match.start("target")]
    return value


def _file_pattern_hint(file_type: str) -> str:
    return {
        "screenshot": "*.{png,jpg,jpeg,heic,gif,webp}",
        "image": "*.{png,jpg,jpeg,heic,gif,webp}",
        "pdf": "*.pdf",
        "document": "*.{doc,docx,pages,rtf,txt,md}",
        "spreadsheet": "*.{csv,tsv,xls,xlsx,numbers}",
        "archive": "*.{zip,rar,7z,tar,gz}",
        "audio": "*.{mp3,wav,aac,m4a,flac}",
        "video": "*.{mp4,mov,m4v,avi,mkv}",
    }.get(file_type, "")


def _report_file_context_hint(text: str) -> dict[str, str]:
    if not _contains_any(
        text,
        [
            "file",
            "files",
            "folder",
            "directory",
            "pdf",
            "docx",
            "downloads",
            "文件",
            "文件夹",
            "目录",
            "下载",
        ],
    ):
        return {}
    location = _file_location_hint(text)
    if location == "Documents" and not _contains_any(
        text,
        ["documents", "document folder", "documents folder", "文档文件夹", "文档目录"],
    ):
        location = ""
    file_type = _report_file_type_hint(text)
    if not location and not file_type:
        return {}
    hint: dict[str, str] = {}
    if location:
        hint["location"] = location
    if file_type:
        hint["file_type"] = file_type
        pattern = _report_file_pattern(file_type)
        if pattern:
            hint["pattern"] = pattern
    return hint


def _report_file_type_hint(text: str) -> str:
    lowered = text.lower()
    file_types = (
        ("pdf", "pdf"),
        ("docx", "docx"),
        ("word", "docx"),
        ("markdown", "markdown"),
        ("md", "markdown"),
        ("txt", "text"),
        ("text", "text"),
        ("文本文档", "text"),
        ("文本", "text"),
    )
    for marker, file_type in file_types:
        if marker in lowered:
            return file_type
    return ""


def _report_file_pattern(file_type: str) -> str:
    return {
        "pdf": "*.pdf",
        "docx": "*.docx",
        "markdown": "*.md",
        "text": "*.txt",
    }.get(file_type, "")


def _looks_like_file_organization_request(text: str) -> bool:
    file_type = _file_type_hint(text)
    file_scope = _contains_any(
        text,
        [
            "file",
            "files",
            "folder",
            "folders",
            "directory",
            "downloads",
            "desktop",
            "documents",
            "文件",
            "文件夹",
            "目录",
            "下载",
            "桌面",
            "文档",
        ],
    )
    if not file_scope:
        return False
    inventory_query = _contains_any(
        text,
        [
            "inventory",
            "file list",
            "list files",
            "show files",
            "find files",
            "what files",
            "which files",
            "清单",
            "列表",
            "列出",
            "盘点",
            "查一下",
            "查看",
            "有哪些",
            "有什么",
            "哪些文件",
            "什么文件",
        ],
    )
    explicit_file_inventory_scope = _contains_any(
        text,
        [
            "file",
            "files",
            "folder",
            "folders",
            "directory",
            "downloads",
            "documents",
            "文件",
            "文件夹",
            "目录",
            "下载",
            "文档",
        ],
    )
    file_operation = _contains_any(
        text,
        [
            "organize",
            "sort",
            "clean up",
            "delete",
            "remove",
            "trash",
            "move",
            "rename",
            "archive",
            "deduplicate",
            "整理",
            "分类",
            "清理",
            "删除",
            "移除",
            "移动",
            "重命名",
            "归档",
            "废纸篓",
        ],
    )
    return (
        file_operation
        or _file_duplicate_hint(text)
        or (inventory_query and (explicit_file_inventory_scope or bool(file_type)))
    )


def _file_duplicate_hint(text: str) -> bool:
    return _contains_any(
        text,
        [
            "duplicate",
            "duplicates",
            "duplicated",
            "deduplicate",
            "same file",
            "same files",
            "重复文件",
            "重复项",
            "重复的文件",
            "相同文件",
            "重复截图",
            "重复图片",
            "重复照片",
            "重复文档",
            "重复 pdf",
            "重复PDF",
        ],
    )


def _looks_like_multi_agent_request(text: str) -> bool:
    value = _clean_prompt(text)
    lowered = value.lower()
    if re.search(
        r"(?:group|群组|小组|团队)",
        value,
        flags=re.IGNORECASE,
    ) and re.search(
        r"(?:让|安排|派发|派活|委派|分配|指派|运行|启动|执行|协作|"
        r"coordinate|delegate|dispatch|assign|run|start|execute)",
        value,
        flags=re.IGNORECASE,
    ):
        if _looks_like_timed_schedule_request(value) and not re.search(
            r"(?:agent|Agent|AI|智能体|代理|group|群组|小组|多\s*agent|多Agent)",
            value,
            flags=re.IGNORECASE,
        ):
            return False
        return True
    if re.search(
        r"(?:two|three|multiple|several)\s+(?:agents?|ai\s+agents?)",
        lowered,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        r"(?:两个|两个以上|多个|多位|几位|一组)\s*(?:agent|Agent|AI|智能体|代理)",
        value,
        flags=re.IGNORECASE,
    ):
        return True
    return bool(
        re.search(r"(?:agent|Agent|智能体|代理)", value, flags=re.IGNORECASE)
        and _contains_any(value, ("分别", "各自", "并行", "协作", "分工", "委派", "分配", "指派", "派发"))
    )


def _workflow_target_hint(text: str) -> str:
    return _orchestration_target_hint(
        text,
        nouns=("workflow", "Workflow", "工作流", "流程"),
        reject_prefixes=(
            "分析",
            "调研",
            "研究",
            "生成",
            "输出",
            "整理",
            "创建",
            "新建",
            "发",
            "发送",
            "做",
            "执行",
            "处理",
            "analyze",
            "research",
            "generate",
            "create",
            "send",
            "run ",
        ),
    )


def _known_orchestration_target_hint(
    text: str,
    metadata: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> str:
    value = _clean_prompt(text)
    if not value or not isinstance(metadata, Mapping):
        return ""
    matches = [
        target
        for target in _metadata_orchestration_targets(metadata, keys=keys)
        if _text_mentions_orchestration_target(value, target)
    ]
    if not matches:
        return ""
    return max(matches, key=len)[:80]


def _metadata_orchestration_targets(
    metadata: Mapping[str, Any],
    *,
    keys: tuple[str, ...],
) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for key in keys:
        values = metadata.get(key)
        if values is None:
            continue
        for value in _iter_orchestration_target_values(values):
            target = _clean_known_orchestration_target(value)
            if not target:
                continue
            target_key = target.casefold()
            if target_key in seen:
                continue
            seen.add(target_key)
            targets.append(target)
    return targets


def _iter_orchestration_target_values(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for key in ("name", "title", "nickname", "workflow_id", "group_id", "agent_group_id", "id"):
            if value.get(key):
                yield value.get(key)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_orchestration_target_values(item)
        return
    yield value


def _clean_known_orchestration_target(value: Any) -> str:
    target = " ".join(str(value or "").strip().split())
    target = target.strip(" \t\r\n:：,，.。;；\"'“”‘’「」『』")
    if len(target) < 2 or contains_sensitive_text(target):
        return ""
    lowered = target.casefold()
    if lowered in {"workflow", "flow", "group", "team", "agent", "agents", "工作流", "流程", "群组", "小组", "团队"}:
        return ""
    return target[:120]


def _text_mentions_orchestration_target(text: str, target: str) -> bool:
    target_text = _clean_known_orchestration_target(target)
    if not target_text:
        return False
    if re.search(r"[\u4e00-\u9fff]", target_text):
        return target_text in text
    return re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(target_text)}(?![A-Za-z0-9_])",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _group_target_hint(text: str) -> str:
    return _orchestration_target_hint(
        text,
        nouns=("group", "Group", "群组", "小组"),
        reject_prefixes=(
            "两个",
            "多个",
            "多位",
            "一组",
            "agent",
            "Agent",
            "AI",
            "智能体",
            "代理",
        ),
    )


def _orchestration_target_hint(
    text: str,
    *,
    nouns: tuple[str, ...],
    reject_prefixes: tuple[str, ...],
) -> str:
    value = _clean_prompt(text)
    if not value:
        return ""
    noun_pattern = "|".join(re.escape(noun) for noun in nouns)
    patterns = (
        rf"(?:名为|叫做|叫|named)\s*[\"'“”‘’「」『』]?(?P<target>[^\"'“”‘’「」『』,，。；;]+?)[\"'“”‘’「」『』]?\s*(?:的)?\s*(?:{noun_pattern})",
        rf"(?:{noun_pattern})\s*[\"'“”‘’「」『』](?P<target>[^\"'“”‘’「」『』,，。；;]+)[\"'“”‘’「」『』]",
        rf"(?:运行|启动|执行|打开|run|start)\s*(?P<target>[\w\u4e00-\u9fff ._-]{{2,48}}?)\s*(?:{noun_pattern})",
        rf"(?:运行|启动|执行|打开|run|start)\s*(?:{noun_pattern})\s*(?P<target>[\w\u4e00-\u9fff ._-]{{2,48}})$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        target = _clean_orchestration_target_hint(
            match.group("target"),
            reject_prefixes=reject_prefixes,
        )
        if target:
            return target
    return ""


def _clean_orchestration_target_hint(
    value: str,
    *,
    reject_prefixes: tuple[str, ...],
) -> str:
    target = " ".join(str(value or "").strip().split())
    target = target.strip(" \t\r\n:：,，.。;；\"'“”‘’「」『』")
    if not target:
        return ""
    lowered = target.lower()
    generic = {
        "workflow",
        "flow",
        "工作流",
        "流程",
        "group",
        "群组",
        "小组",
    }
    if lowered in generic or target in generic:
        return ""
    if any(lowered.startswith(prefix.lower()) for prefix in reject_prefixes):
        return ""
    return target[:80]


def _file_operation_hint(text: str) -> str:
    duplicate = _file_duplicate_hint(text)
    destructive = _contains_any(text, ["delete", "remove", "trash", "删除", "移除", "清空", "废纸篓"])
    if duplicate and destructive:
        return "delete_duplicates"
    if duplicate and _contains_any(
        text,
        ["find", "list", "show", "inspect", "找出", "查找", "列出", "盘点", "识别"],
    ):
        return "duplicate_inventory"
    if duplicate and _contains_any(text, ["clean up", "deduplicate", "清理", "整理"]):
        return "deduplicate"
    if destructive:
        return "delete"
    if _contains_any(text, ["rename", "重命名", "改名"]):
        return "rename"
    if _contains_any(text, ["archive", "归档", "压缩"]):
        return "archive"
    if _contains_any(text, ["move", "移动"]):
        return "move"
    if _contains_any(
        text,
        [
            "inventory",
            "file list",
            "list files",
            "show files",
            "find files",
            "what files",
            "which files",
            "清单",
            "列表",
            "列出",
            "盘点",
            "查一下",
            "查看",
            "有哪些",
            "有什么",
            "哪些文件",
            "什么文件",
        ],
    ):
        return "inventory"
    if _contains_any(text, ["sort", "organize", "整理", "分类"]):
        return "organize"
    return "inspect"


def _url_hint(text: str) -> str:
    return _explicit_browser_url_hint(text)


def _app_name_hint(text: str) -> str:
    if re.fullmatch(
        r"(?:press|hit|tap)\s+(?:the\s+)?(?:enter|return|"
        r"(?:command|cmd|control|ctrl|option|alt|shift)(?:\s*[+ ]\s*\w+)?)",
        str(text or "").strip(),
        flags=re.IGNORECASE,
    ):
        return ""
    if _foreground_app_search_hint(text):
        return ""
    app_click_scope = _app_first_click_scope_hint(text)
    if app_click_scope:
        return str(app_click_scope.get("app_name") or "").strip()
    app_type_scope = _app_first_type_scope_hint(text)
    if app_type_scope:
        return str(app_type_scope.get("app_name") or "").strip()
    if _target_first_foreground_click_hint(text):
        return ""
    if _target_first_foreground_type_hint(text):
        return ""
    patterns = [
        r"(?:把|将)\s*(?P<app>[\w .·-]{1,40}?)\s*(?:打开|启动|开启|切到|聚焦)(?:起来|到前台|前台)?",
        r"^(?!(?:在|用|通过|点击|点按|把|将))(?P<app>[\w .·-]{1,40}?)\s*"
        r"(?:打开起来|启动起来|开启起来|开起来|打开|启动|开启|运行|拉起|开)"
        r"(?:一下|下|起来)?\s*(?:吗|嘛|呢|吧|么|可以|可不可以|行不行|好不好|好吗|好么)?[?？。！!]*$",
        r"^(?!(?:在|用|通过|点击|点按|把|将))(?P<app>[\w .·-]{1,40}?)\s*"
        r"(?:切到|切回|聚焦|激活)(?:一下|下|到前台|前台)?\s*"
        r"(?:吗|嘛|呢|吧|么|可以|可不可以|行不行|好不好|好吗|好么)?[?？。！!]*$",
        r"(?:go\s+back\s+to|switch\s+back\s+to|back\s+to)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"(?:can|could|would)\s+you\s+(?:please\s+)?"
        r"(?:open|launch|focus|start)\s+(?P<polite_app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"(?:open|launch|focus|start)\s+(?:the\s+)?(?:app|application)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"(?:bring|switch)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:to\s+(?:the\s+)?(?:front|foreground)|forward)",
        r"(?:activate)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"^(?!(?:can|could|would|please|pls|search|find|press|hit|tap|type|enter|click|send|submit)\b)"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:open|launch|start|focus|activate)(?:\s+(?:please|pls))?[.!?]*$",
        r"(?:open|launch|focus|start)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"(?:打开|启动|切到|聚焦)\s*(?P<app>[\w .·-]{1,40})",
        r"^(?!(?:在|用|通过|点击|点按))(?P<app>[\w .·-]{2,40}?)\s*点\s*[^。！？!?，,]+",
        r"^(?!(?:在|用|通过|点击|点按|把|将))(?P<app>[\w .·-]{1,40}?)"
        r"(?:关闭|隐藏|最小化|退出)(?:窗口|应用|app|application)?",
        r"^(?!(?:在|用|通过|点击|点按))(?P<app>[\w .·-]{1,40}?)"
        r"(?:按|敲|tap|press|hit).{0,8}(?:回车|return|enter)",
        r"(?:in|inside|within|using|with)\s+"
        r"(?:(?:an?|the)\s+)?(?:app|application|software)\s+"
        r"(?:called|named)\s+(?P<named_app_en_early>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)"
        r"(?:\s+(?:to|and|then|click|press|type|search|open|create|write|play|analyze|analyse)|[.!?,]|$)",
        r"^(?!(?:can|could|would|please|pls|search|find|open|launch|focus|start|"
        r"press|hit|tap|type|enter|click|send|submit)\b)"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:点击|点按|按|输入|搜索|查找|click|press|tap|type|enter|search)\b",
        r"^(?!(?:在|用|通过|点击|点按))(?P<app>[\w .·-]{1,40}?)(?:点击|点按)",
        r"(?:^|[\s，,。])(?:在|用|通过)\s*(?:一个|一款|这个|那个)?"
        r"(?:叫|名叫|名称是|名字是)\s*(?P<named_app_cn>[\w .·-]{1,40}?)"
        r"\s*(?:的)?(?:应用(?:程序)?|软件)?(?:里|中|上|内)?"
        r"(?:打开|启动|点击|点按|按|输入|搜索|查找|检索|找|播放|创建|新建|写|发送|分析|操作|帮|$)",
        r"(?:in|inside|within|using|with)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)(?:\s+(?:to|and|then|click|press|type|search|open|create|write|play|analyze|analyse)|[.!?,]|$)",
        r"(?:^|[\s，,。])(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|来|去|打开|启动|点击|点按|按|输入|搜索|查找|检索|找|播放|创建|新建|写|发送|分析|操作|帮|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = next(
            (
                item
                for item in match.groupdict().values()
                if item is not None and str(item).strip()
            ),
            "",
        )
        app = _clean_app_name_hint(raw_app)
        if (
            app
            and not _invalid_app_scoped_followup_app(app)
            and not _is_generic_foreground_app_label(app)
        ):
            return app
    return ""


def _app_first_click_scope_hint(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    patterns = (
        r"^(?!(?:in|inside|within|using|with)\b)(?P<app>[A-Za-z][A-Za-z0-9_-]{1,40})\s+"
        r"(?P<target>[^。！？!?，,]{1,40}?"
        r"(?:button|menu\s+item|menu|checkbox))\s*"
        r"(?P<verb>click|press|tap)$",
        r"^(?!(?:in|inside|within|using|with)\b)(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?P<target>[^。！？!?，,]{1,40}?"
        r"(?:按钮|控件|元素|菜单项|菜单|复选框|button|menu\s+item|menu|checkbox))\s*"
        r"(?P<verb>双击|点击|点一下|点按|单击|click|press|tap)$",
        r"^(?!(?:在|用|通过|点击|点按))(?P<app>[\w .·-]{2,40}?)\s+"
        r"(?P<target>[^。！？!?，,]{1,40}?"
        r"(?:按钮|控件|元素|菜单项|菜单|复选框))\s*"
        r"(?P<verb>双击|点击|点一下|点按|单击)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _canonical_app_name_hint(match.group("app"))
        if not app_name:
            continue
        raw_target = match.group("target")
        target = clean_type_target(raw_target, app_name=app_name) or raw_target.strip()
        target = re.sub(r"^(?:的|上(?:的)?|里(?:的)?|中(?:的)?|内(?:的)?)\s*", "", target).strip()
        if _generic_click_target_label(target):
            continue
        verb = match.group("verb")
        target_request = (
            click_target_hint(f"{verb} {raw_target}")
            if re.fullmatch(r"(?:click|press|tap)", verb, flags=re.IGNORECASE)
            else click_target_hint(f"{raw_target} {verb}")
        )
        if not target_request:
            continue
        return {"app_name": app_name, "click_target": target_request}
    return {}


def _target_first_foreground_click_hint(text: str) -> bool:
    value = str(text or "").strip()
    return bool(
        re.fullmatch(
            r"[A-Za-z][A-Za-z0-9 ._-]{1,40}?\s+"
            r"(?:button|menu\s+item|menu|checkbox)\s+"
            r"(?:click|press|tap)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _app_first_type_scope_hint(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    patterns = (
        r"^(?:打开|启动|开启|切到|聚焦)\s*(?P<app>[\w .·-]{1,40}?)(?:的|里|中|上|内|在)\s*"
        r"(?P<target>[^。！？!?，,]{0,40}?"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*"
        r"(?:输入|键入|填写|填入|写入|写|填)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?:打开|启动|开启|切到|聚焦)\s*(?P<app>[\w .·-]{1,40}?)"
        r"(?P<target>搜索框|搜索栏|消息框|聊天框|地址栏)\s*"
        r"(?:输入|键入|填写|填入|写入|写|填)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?:打开|启动|开启|切到|聚焦)\s*(?P<app>[\w .·-]{1,40}?)\s+"
        r"(?P<target>[^。！？!?，,]{0,40}?"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*"
        r"(?:输入|键入|填写|填入|写入|写|填)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|的|上的)\s*"
        r"(?P<target>[^。！？!?，,]{0,40}?"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*"
        r"(?:输入|键入|填写|填入|写入|写|填)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?:在|用|通过)\s+(?P<app>[\w .·-]{2,40}?)\s+"
        r"(?P<target>[^。！？!?，,]{0,40}?"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*"
        r"(?:输入|键入|填写|填入|写入|写|填)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?!(?:在|用|通过|点击|点按|把|将))(?P<app>[\w .·-]{2,40}?)(?:的|里|中|上|内|在)\s*"
        r"(?P<target>[^。！？!?，,]{0,40}?"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*"
        r"(?:输入|键入|填写|填入|写入|写|填)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?!(?:在|用|通过|点击|点按|把|将))(?P<app>[\w .·-]{2,40}?)\s+"
        r"(?P<target>[^。！？!?，,]{0,40}?"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏))\s*"
        r"(?:输入|键入|填写|填入|写入|写|填)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?!(?:in|inside|within|using|with)\b)(?P<app>[A-Za-z][A-Za-z0-9_-]{1,40})\s+"
        r"(?P<target>[^.!?,]{0,40}?"
        r"(?:search box|search field|message field|address bar|input field|text box|input|field))\s+"
        r"(?:type|enter|fill)\s+(?P<text>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _canonical_app_name_hint(match.group("app"))
        if not app_name:
            continue
        raw_target = match.group("target")
        target = _clean_app_first_type_target(raw_target, app_name=app_name)
        if _generic_type_target_label(target):
            continue
        typed_text = clean_followup_text(match.group("text"))
        if not target or not typed_text:
            continue
        return {
            "app_name": app_name,
            "type_target": {
                "target": target,
                "text": typed_text,
                "role_filter": "text",
            },
        }
    return {}


def _clean_app_first_type_target(value: str, *, app_name: str) -> str:
    target = str(value or "").strip(" .，,。")
    clean_app = str(app_name or "").strip()
    if clean_app and target.lower().startswith(clean_app.lower()):
        target = target[len(clean_app) :].strip(" .，,。")
    target = re.sub(
        r"^(?:打开|启动|开启|切到|聚焦|open|launch|focus|switch\s+to)\s*",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    target = re.sub(
        r"^(?:(?:在|用|通过)\s+|(?:in|inside|within|using|with)\s+)",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    target = re.sub(r"^(?:的|在|里|中|上|内|上的|里的|中的|内的)\s*", "", target)
    target = re.sub(
        r"^(?:点击|点一下|点按|单击|按一下|按|click|press|tap)\s*",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    if re.fullmatch(
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|input field|search box|search field|message field|address bar|text box)",
        target,
        flags=re.IGNORECASE,
    ):
        return clean_type_target(f"{app_name} {target}", app_name=app_name) or target
    target = re.sub(
        r"\s*(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search box|search field|message field|address bar|input field|text box|input|field)$",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    if not target:
        return clean_type_target(value, app_name=app_name)
    if re.fullmatch(r"(?:搜索|search)", target, flags=re.IGNORECASE):
        return "search" if re.search(r"[A-Za-z]", target) else "搜索"
    if re.fullmatch(r"(?:消息|message)", target, flags=re.IGNORECASE):
        return "message" if re.search(r"[A-Za-z]", target) else "消息"
    if re.fullmatch(r"(?:地址|address)", target, flags=re.IGNORECASE):
        return "address" if re.search(r"[A-Za-z]", target) else "地址"
    return target


def _target_first_foreground_type_hint(text: str) -> bool:
    value = str(text or "").strip()
    return bool(
        re.fullmatch(
            r"[A-Za-z][A-Za-z0-9 ._-]{1,40}?\s+"
            r"(?:search box|search field|message field|address bar|input field|text box|input|field)\s+"
            r"(?:type|enter|fill)\s+[^.!?,]+",
            value,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            r"[\w .·-]{1,40}?"
            r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏)\s*"
            r"(?:输入|键入|填写|填入|写入|写|填)\s*[^。！？!?，,]+",
            value,
            flags=re.IGNORECASE,
        )
    )


def _generic_click_target_label(value: str) -> bool:
    compact = re.sub(r"[\s._·-]+", "", str(value or "").strip().lower())
    return compact in {"", "button", "menu", "menuitem", "checkbox", "按钮", "控件", "元素", "菜单", "菜单项", "复选框"}


def _generic_type_target_label(value: str) -> bool:
    compact = re.sub(r"[\s._·-]+", "", str(value or "").strip().lower())
    return compact in {
        "",
        "input",
        "field",
        "inputfield",
        "textbox",
        "输入框",
        "文本框",
        "输入栏",
    }


def _app_first_control_app_name_hint(text: str) -> str:
    value = str(text or "").strip()
    if re.search(r"://|(?:^|\s)[\w-]+\.[A-Za-z]{2,}(?:/|\s|$)", value):
        return ""
    if not re.search(
        r"(?:打开起来|启动起来|开启起来|开起来|打开|启动|开启|运行|拉起|开|"
        r"切到|切回|聚焦|激活|open|launch|start|focus|activate)\s*"
        r"(?:一下|下|起来|到前台|前台|please|pls)?[?？。！!.]*$",
        value,
        flags=re.IGNORECASE,
    ):
        return ""
    return _app_name_hint(value)


def _clean_app_name_hint(value: str) -> str:
    app = re.split(
        r"(?:并|然后|再|接着|之后|后|播放|点击|点按|点|按|输入|粘贴|搜索|创建|新建|重命名|上一级|显示简介|查看简介|快速查看|快速预览|预览|复制选中|写|发送|回车|确认|提交|分析|操作|查看|看看|看一下|看下|观察|识别|有没有|是否|可以|可不可以|行不行|好不好|好吗|好么|\b(?:and|then|to|paste|thanks)\b)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    app = re.sub(r"\s*(?:并|然后|再|接着|之后|后|and|then)\s*$", "", app, flags=re.IGNORECASE).strip()
    app = re.sub(r"^(?:the\s+)?", "", app, flags=re.IGNORECASE).strip(" .，,。")
    scoped_called_app_match = re.match(
        r"^(?:一个|一款|这个|那个)?"
        r"(?:(?:我(?:的)?(?:电脑|mac|机器|系统)?|本机|本地)(?:上|里|中|内)?(?:的)?\s*)?"
        r"(?:叫|名叫|名称是|名字是)\s*(?P<app>.+?)\s*(?:的)?(?:应用(?:程序)?|软件)?$",
        app,
        flags=re.IGNORECASE,
    )
    if scoped_called_app_match:
        app = scoped_called_app_match.group("app")
    app = re.sub(
        r"^(?:我(?:的)?(?:电脑|mac|机器|系统)(?:上|里|中|内)?(?:的)?|"
        r"本机(?:上|里|中|内)?(?:的)?|本地(?:的)?)\s*",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    called_app_match = re.match(
        r"^(?:一个|一款|这个|那个)?(?:叫|名叫|名称是|名字是)\s*(?P<app>.+?)\s*(?:的)?(?:应用(?:程序)?|软件)$",
        app,
        flags=re.IGNORECASE,
    )
    if called_app_match:
        app = called_app_match.group("app")
    english_called_app_match = re.match(
        r"^(?:(?:an?|the)\s+)?(?:app|application|software)\s+"
        r"(?:called|named)\s+(?P<app>.+?)$",
        app,
        flags=re.IGNORECASE,
    )
    if english_called_app_match:
        app = english_called_app_match.group("app")
    app = re.split(
        r"\s*(?:(?:的|里(?:的)?|中(?:的)?|上(?:的)?|内(?:的)?)\s*)?"
        r"(?:搜索框|搜索栏|消息框|聊天框|地址栏|输入框|文本框|输入栏|"
        r"search box|search field|message field|address bar|input field|text box)",
        app,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .，,。")
    app = re.sub(
        r"^(?:一个|一款|这个|那个)?(?:我(?:没|没有)提过的|新的|未知的)?"
        r"(?:应用(?:程序)?|软件|\b(?:app|application)\b)"
        r"(?:\s*(?:叫|名叫|名称是|名字是|called|named))?\s*",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(r"^(?:called|named)\s+", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"^(?:在|用|通过)\s*", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(
        r"^(?:in|inside|within|using|with)\s+",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(r"\s*(?:吗|嘛|呢|吧|么|\?|？)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"\s*(?:帮我|请|麻烦)$", "", app).strip(" .，,。")
    app = re.sub(r"\s*(?:please|pls)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"\s*(?:for\s+me)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(
        r"\s*(?:客户端|桌面客户端|桌面版|desktop\s+client|client)$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(r"\s*(?:搜索|查找|检索|找)\s*.+$", "", app).strip(" .，,。")
    app = re.sub(
        r"\s+\b(?:search|find|look\s+up|look)\b\s+.+$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(r"\s*(?:一下|下|起来)$", "", app).strip(" .，,。")
    app = re.sub(r"\s*(?:的|里(?:的)?|里面(?:的)?|中(?:的)?|上(?:的)?|内(?:的)?)$", "", app).strip(" .，,。")
    app = re.sub(r"\s*(?:在|里|里面|中|上|内)$", "", app).strip(" .，,。")
    app = re.sub(r"\s+(?:app|application)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"(?:应用(?:程序)?|软件)$", "", app).strip(" .，,。")
    app = re.sub(r"^(?:一下|下|这个|那个)\s*", "", app).strip()
    generic = {
        "app",
        "application",
        "desktop",
        "window",
        "应用",
        "应用程序",
        "桌面",
        "窗口",
        "当前窗口",
        "现在窗口",
        "前台窗口",
        "这个窗口",
        "该窗口",
        "当前界面",
        "现在界面",
        "前台界面",
        "屏幕",
        "当前屏幕",
        "现在屏幕",
        "界面",
        "画面",
        "页面",
        "网页",
        "标签页",
        "新标签",
        "新标签页",
        "打开新标签",
        "打开新标签页",
        "当前页面",
        "当前网页",
        "这个页面",
        "这个网页",
        "关闭的标签页",
        "刚才关闭的标签页",
        "刚关闭的标签页",
        "当前",
        "任意当前",
        "任意当前应用",
        "当前所有",
        "当前全部",
        "当前app",
        "当前应用",
        "前台应用",
        "前台",
        "现在",
        "这个",
        "该",
        "current",
        "current app",
        "foreground app",
        "current window",
        "active window",
        "foreground window",
        "this window",
        "current interface",
        "active interface",
        "foreground interface",
        "new tab",
        "button",
        "buttons",
        "control",
        "controls",
        "element",
        "elements",
        "field",
        "fields",
        "click",
        "click the",
        "type",
        "type the",
        "press",
        "press the",
        "can you",
        "could you",
        "would you",
        "你",
        "我",
        "帮我",
        "请",
        "点",
        "点击",
    }
    if context_source_hint(app):
        return ""
    if compact_app_name_hint(app) in {
        "folder",
        "folders",
        "afolder",
        "directory",
        "directories",
        "文件夹",
        "目录",
    }:
        return "Finder"
    return "" if app.lower() in generic else app


def _app_scoped_safe_shortcut_app_name_hint(
    text: str,
    safe_shortcut: Mapping[str, Any] | None = None,
) -> str:
    hint = safe_shortcut or safe_shortcut_hint(text)
    action = str((hint or {}).get("action") or "").strip()
    if not action:
        return ""
    value = _clean_prompt(text)
    if _safe_shortcut_requires_finder_scope_for_text(value, hint):
        patterns = (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|切到|聚焦)?\s*"
            r"(?P<app>Finder|访达)\s*(?:然后|并|再|接着|之后|后)?\s*.+$",
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在|用|通过)\s*"
            r"(?P<app>Finder|访达)\s*(?:里|中|上|内)?\s*.+$",
            r"^(?:open|launch|focus|start)?\s*(?:the\s+)?(?P<app>Finder)\b.+$",
        )
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if not match:
                continue
            app = _clean_app_name_hint(match.group("app"))
            if _is_finder_app_name(app):
                return "Finder"
        return ""
    if action != "toggle_full_screen":
        return ""
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:把|将)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)\s*(?:窗口)?"
        r"(?:最大化|全屏|进入全屏(?:模式)?)"
        r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
        r"^(?:please\s+)?(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:maximize|fullscreen|full\s*screen)(?:\s+(?:window|app))?(?:\s+please)?$",
        r"^(?:please\s+)?(?:maximize|fullscreen|full\s*screen|enter\s+full\s*screen)\s+"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)(?:\s+(?:window|app))?(?:\s+please)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app = _clean_app_name_hint(match.group("app"))
        if not app or _contains_any(app, ["音量", "声音", "亮度", "volume", "sound", "brightness"]):
            continue
        return app
    return ""


def _safe_shortcut_requires_finder_scope(hint: Mapping[str, Any] | None) -> bool:
    return str((hint or {}).get("action") or "").strip() in {
        "finder_quick_look",
        "finder_get_info",
        "finder_airdrop",
        "finder_network",
        "finder_recents",
        "new_folder",
        "rename_selected",
        "parent_folder",
    }


def _safe_shortcut_requires_finder_scope_for_text(
    text: str,
    hint: Mapping[str, Any] | None,
) -> bool:
    if _safe_shortcut_requires_finder_scope(hint):
        return True
    if str((hint or {}).get("action") or "").strip() != "copy":
        return False
    return _contains_any(
        text,
        (
            "复制选中项",
            "复制选中文件",
            "复制当前选中项",
            "复制当前选中文件",
            "copy selected file",
            "copy selected item",
        ),
    )


def _is_finder_app_name(value: str) -> bool:
    return str(value or "").strip().lower() in {"finder", "访达"}


def _foreground_submit_action_hint(text: str) -> str:
    value = _clean_prompt(text)
    lowered = value.lower()
    app_scoped_submit = bool(_app_scoped_foreground_submit_app_name_hint(value))
    looks_like_send = _contains_any(value, ("发送", "发出", "send")) or bool(
        _looks_like_chinese_foreground_send_verb(value)
    )
    if looks_like_send and (
        _looks_like_foreground_submit_scope(value, lowered) or app_scoped_submit
        or bool(_foreground_compose_text_hint(value))
    ):
        return "send"
    if _contains_any(value, ("提交", "submit")) and (
        _looks_like_foreground_submit_scope(value, lowered) or app_scoped_submit
    ):
        return "submit"
    if re.search(r"(?:按|敲|点|tap|press|hit).{0,8}(?:回车|return|enter).{0,8}(?:发送|send)", value, flags=re.IGNORECASE):
        return "send"
    if re.search(r"(?:按|敲|点|tap|press|hit).{0,8}(?:回车|return|enter).{0,8}(?:提交|submit)", value, flags=re.IGNORECASE):
        return "submit"
    if re.search(r"(?:发送|send).{0,8}(?:回车|return|enter)", value, flags=re.IGNORECASE):
        return "send"
    if re.search(r"(?:提交|submit).{0,8}(?:回车|return|enter)", value, flags=re.IGNORECASE):
        return "submit"
    return ""


def _looks_like_chinese_foreground_send_verb(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    return bool(
        re.search(
            r"(?:发给|发到|发往|发去|发一下|发下|发出去|发消息|发信息|发这条|发这个)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:并|然后|再|接着|之后|后|把|将)\s*发(?:给|到|出去|一下|下)?",
            value,
            flags=re.IGNORECASE,
        )
    )


def _foreground_search_submit_hint(text: str) -> bool:
    value = _clean_prompt(text)
    lowered = value.lower()
    return bool(
        re.fullmatch(r"(?:提交|确认|执行)?\s*(?:当前|这个|前台)?\s*(?:搜索|查询|查找)", value)
        or re.fullmatch(r"(?:按|敲|点)?\s*(?:回车|enter|return)\s*(?:搜索|查询|查找)", value, flags=re.IGNORECASE)
        or re.fullmatch(r"(?:press|hit|tap)\s+(?:enter|return)\s+to\s+(?:search|find)", lowered)
    )


def _return_hotkey_followup_hint(text: str) -> dict[str, Any] | None:
    value = _clean_prompt(text)
    if not re.search(
        r"(?:并|再|然后|接着|之后|后)\s*(?:搜索|查找|检索)(?:一下|下)?\s*$",
        value,
        flags=re.IGNORECASE,
    ):
        return None
    return {"key": "return", "modifiers": []}


def _explicit_return_key_followup_hint(text: str) -> dict[str, Any] | None:
    value = _clean_prompt(text)
    if not re.search(
        r"(?:并|再|然后|接着|之后|后|and\s+then|then)?.{0,8}"
        r"(?:按|敲|触发|press|hit|tap)?\s*(?:回车键?|enter|return)(?:\s|$|[。！？!?，,])",
        value,
        flags=re.IGNORECASE,
    ):
        return None
    if re.search(r"(?:发送|提交|send|submit).{0,8}(?:回车|enter|return)", value, flags=re.IGNORECASE):
        return None
    return {"key": "return", "modifiers": []}


def _foreground_compose_text_hint(text: str) -> str:
    value = _clean_prompt(text)
    if re.search(r"(?:粘贴|paste)", value, flags=re.IGNORECASE):
        return ""
    if _looks_like_recipient_message_request(value):
        return ""
    create_text = _app_scoped_create_text_hint(value)
    if create_text:
        return create_text
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|切到|聚焦)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)\s*(?:输入|键入|填写|写入|写下|记录下|记下|写)\s*(?P<text>[^。！？!?，,]+?)"
        r"\s*(?:并|然后|再|后)?\s*(?:发送|发出|send)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|切到|聚焦)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)\s*(?:发送|发出|(?<!开)发)\s*(?P<text>[^。！？!?，,]+)$",
        r"^(?:open|launch|focus|switch\s+to)?\s*(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:type|enter|write|send)\s+(?P<text>[^.!?]+?)(?:\s+(?:and|then)\s+send)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.groupdict().get("app") or ""
        if _looks_like_too_short_cjk_app_label(raw_app):
            continue
        if re.search(r"(?:回车|return|enter)", raw_app, flags=re.IGNORECASE):
            continue
        app = _canonical_app_name_hint(raw_app)
        if _is_generic_foreground_app_label(raw_app) or _is_generic_foreground_app_label(app):
            continue
        typed_text = _clean_foreground_compose_text(match.group("text"))
        if not typed_text:
            continue
        if not app and not _looks_like_foreground_text_scope(value):
            continue
        if not app and not re.search(r"(?:输入|键入|填写|写入|type|enter|write)", value, flags=re.IGNORECASE):
            continue
        if typed_text in {"框", "栏", "送"}:
            continue
        if typed_text:
            return typed_text
    return ""


def _app_scoped_create_text_hint(text: str) -> str:
    value = _clean_prompt(text)
    parsed = _app_scoped_followup_hint(value)
    followup = str(parsed.get("followup") or "").strip()
    if not followup:
        return ""
    if not _looks_like_app_scoped_create_followup(followup):
        return ""
    patterns = (
        r"(?:标题|名称|名字|题目)\s*(?:是|为|叫|:|：)\s*(?P<text>[^。！？!?，,]+)",
        r"(?:名为|叫做|叫)\s*(?P<text>[^。！？!?，,]+)",
        r"(?:关于|有关)\s*(?P<text>.+?)\s*的\s*"
        r"(?:页面|页|笔记|备忘录|日志|日记|文档|文件|项目|任务|卡片)",
        r"\b(?:titled|called|named)\s+(?P<text_en>[^.!?,]+)",
        r"\babout\s+(?P<text_en>[^.!?,]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, followup, flags=re.IGNORECASE)
        if not match:
            continue
        text_value = _clean_foreground_compose_text(
            match.groupdict().get("text") or match.groupdict().get("text_en") or ""
        )
        if text_value:
            return text_value
    return ""


def _looks_like_app_scoped_create_followup(text: str) -> bool:
    value = _clean_prompt(text)
    return bool(
        re.search(
            r"(?:新建|创建|新增)\s*(?:一个|一条|一篇|一份)?\s*"
            r"(?:今天的|今日的|新的|新|关于.+?的)?\s*"
            r"(?:页面|页|笔记|备忘录|日志|日记|文档|文件(?!夹)|项目|任务|卡片)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:new|create|make)\b.{0,40}\b"
            r"(?:page|note|document|file|project|task|card)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _foreground_paste_hint(text: str) -> bool:
    value = _clean_prompt(text)
    if not re.search(r"(?:粘贴|paste)", value, flags=re.IGNORECASE):
        return False
    return bool(
        _contains_any(value, ("发送", "提交", "send", "submit"))
        or _looks_like_foreground_submit_scope(value, value.lower())
    )


def _dynamic_context_ui_transfer_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    if _dynamic_context_transform_target_hint(value):
        return {}
    source = _dynamic_context_source_hint(value)
    if source not in {"selection", "clipboard", "current_page_link", "current_page_content"}:
        return {}
    target_kind, target = _dynamic_context_ui_target_hint(value)
    app_name = _dynamic_context_transfer_app_name_hint(value)
    if app_name and target_kind == "current_input":
        target_kind = "app_paste"
        target = ""
    if app_name and not target_kind and _looks_like_dynamic_context_transfer(value):
        target_kind = "app_paste"
    if (
        target_kind == "current_input"
        and source == "current_page_content"
    ):
        return {}
    if _looks_like_dynamic_context_copy_only(value):
        if source != "current_page_content":
            return {}
        return {
            "source": source,
            "action": "copy_context",
            "target_kind": "",
            "target": "",
            "app_name": "",
            "mode": "focus",
        }
    if not target_kind:
        return {}
    if not _looks_like_dynamic_context_transfer(value):
        return {}
    return {
        "source": source,
        "action": "transfer_context",
        "target_kind": target_kind,
        "target": target,
        "app_name": app_name,
        "mode": "open" if _explicit_app_open_request(value) else "focus",
    }


def _dynamic_context_transform_target_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not _dynamic_context_transform_requested(value):
        return {}
    if not _looks_like_dynamic_context_transfer(value):
        return {}
    source = _dynamic_context_source_hint(value)
    if not source and _browser_current_page_hint(value):
        source = "current_page_content"
    if not source and re.search(r"\bcurrent\s+page\b|当前网页|当前页面", value, flags=re.IGNORECASE):
        source = "current_page_content"
    if source not in {"selection", "clipboard", "current_page_link", "current_page_content"}:
        return {}
    app_name = _non_notes_dynamic_context_target_app(value)
    if not app_name:
        return {}
    if _normalize_artifact_output_location(app_name):
        return {}
    container_action = _dynamic_context_target_container_action_hint(value)
    return {
        "context_source": source,
        "target_app_hint": app_name,
        "target_action_hint": "app_paste",
        **(
            {"target_container_action_hint": container_action}
            if container_action
            else {}
        ),
    }


def _app_write_followup_target_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not _looks_like_dynamic_context_transfer(value):
        return {}
    app_name = _non_notes_dynamic_context_target_app(value)
    if not app_name:
        return {}
    if (
        _normalize_artifact_output_location(app_name)
        or _looks_like_file_output_target(app_name)
        or _looks_like_non_app_dynamic_context_target(app_name)
    ):
        return {}
    container_action = _dynamic_context_target_container_action_hint(value)
    return {
        "target_app_hint": app_name,
        "target_action_hint": "app_paste",
        **(
            {"target_container_action_hint": container_action}
            if container_action
            else {}
        ),
    }


def _looks_like_file_output_target(value: str) -> bool:
    target = str(value or "").strip()
    if not target:
        return False
    if target.startswith(("~", ".", "/")) or "/" in target or "\\" in target:
        return True
    return bool(re.search(r"\.[A-Za-z0-9]{1,8}$", target))


def _looks_like_non_app_dynamic_context_target(app_name: str) -> bool:
    normalized = re.sub(r"[\s._·-]+", " ", str(app_name or "").strip().lower())
    if not normalized:
        return True
    if normalized in {
        "current page",
        "current webpage",
        "current web page",
        "current window",
        "current app",
        "selected text",
        "clipboard",
        "research current page",
        "research current webpage",
        "research current web page",
    }:
        return True
    return bool(
        re.search(
            r"\b(?:current\s+(?:web\s+)?page|current\s+window|selected\s+text|clipboard)\b",
            normalized,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_context_target_container_action_hint(text: str) -> str:
    value = _clean_prompt(text)
    if re.search(
        r"(?:新笔记|新建笔记|创建笔记|新备忘录|新建备忘录|创建备忘录|"
        r"\bnew\s+note\b|\bcreate\s+(?:a\s+)?new\s+note\b|\bmake\s+(?:a\s+)?new\s+note\b)",
        value,
        flags=re.IGNORECASE,
    ):
        return "new_note"
    if re.search(
        r"(?:新页面|新建页面|创建页面|新文档|新建文档|创建文档|新文件|新建文件|创建文件|"
        r"新表格|新建表格|创建表格|"
        r"\bnew\s+(?:page|document|file|table|spreadsheet)\b|"
        r"\bcreate\s+(?:a\s+)?new\s+(?:page|document|file|table|spreadsheet)\b|"
        r"\bmake\s+(?:a\s+)?new\s+(?:page|document|file|table|spreadsheet)\b)",
        value,
        flags=re.IGNORECASE,
    ):
        return "new_document"
    return ""


def _dynamic_context_transform_requested(text: str) -> bool:
    value = _clean_prompt(text)
    return bool(
        re.search(
            r"(?:总结|摘要|概括|归纳|整理|提炼|改写|润色|翻译|转成|转换成|"
            r"变成|做成|生成|待办|任务清单|清单|"
            r"summarize|summary|summarise|brief|organize|organise|rewrite|"
            r"polish|translate|convert|format|todo|to-do|task list)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _blocked_dynamic_context_ui_transfer_hint(text: str) -> bool:
    value = _clean_prompt(text)
    source = _dynamic_context_source_hint(value)
    target_kind, _target = _dynamic_context_ui_target_hint(value)
    return source == "current_page_content" and target_kind == "current_input"


def _dynamic_context_source_hint(text: str) -> str:
    lowered = _clean_prompt(text).lower()
    if _contains_any(
        lowered,
        (
            "current page link",
            "current url",
            "当前网页链接",
            "当前页面链接",
            "当前链接",
            "当前页地址",
        ),
    ):
        return "current_page_link"
    if _contains_any(
        lowered,
        (
            "current page content",
            "current page text",
            "current window content",
            "copy current window content",
            "current page table",
            "current page data",
            "current window table",
            "current window data",
            "当前网页内容",
            "当前页面内容",
            "当前网页正文",
            "当前页面正文",
            "当前网页表格",
            "当前页面表格",
            "当前网页数据",
            "当前页面数据",
            "当前窗口表格",
            "当前窗口数据",
            "当前窗口内容",
            "当前应用内容",
        ),
    ):
        return "current_page_content"
    if _contains_any(
        lowered,
        (
            "selected text",
            "highlighted text",
            "selection",
            "selected link",
            "selected url",
            "选中文字",
            "选中文本",
            "选中链接",
            "选中网址",
            "选中的文字",
            "选中的文本",
            "选中的内容",
            "选中的数据",
            "选中内容",
            "选中数据",
        ),
    ):
        return "selection"
    return context_source_hint(lowered)


def _dynamic_context_ui_target_hint(text: str) -> tuple[str, str]:
    value = _clean_prompt(text)
    lowered = value.lower()
    if _contains_any(
        lowered,
        (
            "address bar",
            "url bar",
            "location bar",
            "地址栏",
            "网址栏",
        ),
    ):
        return "ui_field", "地址"
    if _contains_any(
        lowered,
        (
            "search box",
            "search field",
            "search bar",
            "搜索框",
            "搜索栏",
            "查找框",
            "检索框",
        ),
    ):
        return "ui_field", "搜索"
    if _contains_any(
        lowered,
        (
            "current input",
            "current field",
            "current text box",
            "foreground input",
            "当前输入框",
            "当前文本框",
            "前台输入框",
            "前台文本框",
            "这里",
            "此处",
            "here",
        ),
    ):
        return "current_input", ""
    return "", ""


def _looks_like_dynamic_context_copy_only(text: str) -> bool:
    value = _clean_prompt(text)
    if not re.search(r"(?:复制|copy)", value, flags=re.IGNORECASE):
        return False
    return not re.search(
        r"(?:粘贴|贴到|输入到|输入进|填到|填入|填写到|paste|type|enter|insert|put)",
        value,
        flags=re.IGNORECASE,
    )


def _looks_like_dynamic_context_transfer(text: str) -> bool:
    value = _clean_prompt(text)
    return bool(
        re.search(
            r"(?:粘贴|贴到|输入到|输入进|输入|键入|填到|填入|填写到|填写|"
            r"写进|写入|写到|保存到|记录到|记到|放到|"
            r"paste|type|enter|insert|put|write|save|record)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_context_transfer_app_name_hint(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"(?:粘贴到|粘贴在|贴到|输入到|输入进|填到|填入|填写到|放到)\s*"
        r"(?P<app>[\w .·-]{1,40}?)(?:$|[。！？!?，,])",
        r"(?:写进|写入|写到|保存到|记录到|记到|放到)\s*"
        r"(?P<app>[\w .·-]{1,40}?)(?:\s*(?:新笔记|新备忘录|新便签|"
        r"新页面|新文档|新文件|笔记|备忘录|便签|页面|文档|文件|"
        r"new\s+note|new\s+page|new\s+document|new\s+file|"
        r"note|page|document|file))?(?:$|[。！？!?，,])",
        r"(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内)?\s*"
        r"(?:粘贴|贴|输入|填入|填写|写进|写入|写到|保存|记录|记下)",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|开启|切到|聚焦)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内)?\s*"
        r"(?:粘贴|贴|输入|填入|填写|写进|写入|写到|保存|记录|记下)\s*"
        r"(?:当前|选中|剪贴板|粘贴板|网页|页面|窗口|链接|内容|文本|文字|clipboard|current|selected)",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|开启|切到|聚焦)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)(?:的)?\s*"
        r"(?:搜索框|搜索栏|查找框|检索框|地址栏|输入框|文本框)\s*"
        r"(?:粘贴|贴|输入|填入|填写)",
        r"(?:paste|type|enter|insert|put|write|save|record)\b.+?\b(?:in|into|to)\s+"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)(?:$|[.!?,])",
        r"\b(?:in|inside|within|using|with)\s+"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:paste|type|enter|insert|put|write|save|record)\b",
        r"^(?:open|launch|focus|switch\s+to)?\s*"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:(?:search|input|text)\s+(?:box|field)|address\s+bar)?\s*"
        r"(?:paste|type|enter|insert|put|write|save|record)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app = _clean_dynamic_context_target_app(match.group("app"))
        if app:
            return app
    return ""


def _non_notes_dynamic_context_target_app(text: str) -> str:
    app = _dynamic_context_transfer_app_name_hint(text)
    return app if app and not _is_structured_notes_app_target(app) else ""


def _is_structured_notes_app_target(app_name: str) -> bool:
    normalized = re.sub(r"[\s._·-]+", "", str(app_name or "").strip().lower())
    return normalized in {"notes", "applenotes", "备忘录", "笔记"}


def _clean_dynamic_context_target_app(value: str) -> str:
    app = str(value or "").strip(" .，,。")
    app = re.sub(
        r"(?:的)?\s*(?:搜索框|搜索栏|查找框|检索框|地址栏|网址栏|输入框|文本框)$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(
        r"\s*(?:(?:search|input|text)\s+(?:box|field)|search\s+bar|address\s+bar|url\s+bar|location\s+bar)$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(
        r"\s*(?:new\s+)?(?:note|page|document|file|table|spreadsheet)$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(
        r"\s*(?:新笔记|新备忘录|新便签|新页面|新文档|新文件|新表格|新建表格|"
        r"笔记|备忘录|便签|页面|文档|文件|表格)$",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    normalized_named_app = _clean_app_name_hint(app)
    if normalized_named_app:
        app = normalized_named_app
    if not app or context_source_hint(app) or _is_generic_foreground_app_label(app):
        return ""
    return _canonical_app_name_hint(app)


def _foreground_compose_app_name_hint(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|切到|聚焦)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)\s*(?:输入|键入|填写|写入|写|发送|发出|(?<!开)发|粘贴|paste)",
        r"^(?:open|launch|focus|switch\s+to)?\s*(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:type|enter|write|send|paste)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.group("app")
        if _looks_like_too_short_cjk_app_label(raw_app):
            continue
        app = _clean_dynamic_context_target_app(raw_app)
        if app and not _is_generic_foreground_app_label(app):
            return app
    return ""


def _clean_foreground_compose_text(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[\"'`“”‘’]+|[\"'`“”‘’]+$", "", text).strip()
    text = re.sub(r"^(?:[:：]\s*)+", "", text).strip()
    text = re.sub(r"\s*(?:并|然后|再|后)?\s*(?:发送|发出|send)$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"[。！？!?]+$", "", text).strip()
    return text


def _looks_like_foreground_text_scope(value: str) -> bool:
    return _contains_any(
        value,
        (
            "当前输入框",
            "当前文本框",
            "前台输入框",
            "前台文本框",
            "current input",
            "current field",
            "foreground input",
        ),
    )


def _is_generic_foreground_app_label(value: str) -> bool:
    clean = str(value or "").strip().lower()
    normalized = re.sub(r"[\s._·-]+", "", clean)
    if any(
        term in normalized
        for term in (
            "当前窗口",
            "前台窗口",
            "当前应用",
            "前台应用",
            "当前输入框",
            "前台输入框",
            "currentwindow",
            "foregroundwindow",
            "currentapp",
            "foregroundapp",
        )
    ):
        return True
    return normalized in {
        "当前",
        "在当前",
        "前台",
        "在前台",
        "当前输入框",
        "前台输入框",
        "当前文本框",
        "前台文本框",
        "当前消息",
        "前台消息",
        "current",
        "foreground",
        "currentinput",
        "foregroundinput",
        "currentfield",
        "foregroundfield",
        "currentmessage",
        "foregroundmessage",
    }


def _looks_like_too_short_cjk_app_label(value: str) -> bool:
    clean = str(value or "").strip()
    return bool(re.fullmatch(r"[\u4e00-\u9fff]", clean))


def _looks_like_recipient_message_request(value: str) -> bool:
    return bool(
        re.search(r"(?:发消息|发送|发)\s*(?:给|到)", value, flags=re.IGNORECASE)
        or re.search(
            r"(?:给|向|对)\s*[^：:，,。]+?\s*(?:发送|发消息|发)\s*(?:说|[:：]|内容是|内容为)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(r"\b(?:send|message)\s+.+?\s+(?:to|for)\s+", value, flags=re.IGNORECASE)
    )


def _looks_like_communication_task_request(value: str) -> bool:
    text = _clean_prompt(value)
    return bool(
        _looks_like_recipient_message_request(text)
        or re.search(
            r"(?:给|向|对)\s*[^：:，,。]+?\s*"
            r"(?:写|撰写|起草|草拟|发|发送|回复|回)\s*"
            r"(?:一封|封|条)?\s*(?:邮件|消息|短信|微信|email|mail|message)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:写|撰写|起草|草拟|发|发送|回复|回)\s*"
            r"(?:一封|封|条)?\s*(?:邮件|消息|短信|微信|email|mail|message)\s*"
            r"(?:给|发给|发送给|向|对)\s*[^：:，,。]+",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:write|draft|compose|send|reply)\s+(?:an?\s+)?"
            r"(?:email|e-mail|mail|message)\s+(?:to|for)\s+",
            text,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_schedule_request(value: str) -> bool:
    return bool(
        _contains_any(value, _SCHEDULE_ACTION_TERMS)
        or (
            "会议" in value
            and _contains_any(
                value,
                ("今天", "明天", "后天", "上午", "下午", "晚上", "点", "时间", "日程"),
            )
        )
    )


def _looks_like_timed_schedule_request(value: str) -> bool:
    text = _clean_prompt(value)
    if not text or not _looks_like_schedule_request(text):
        return False
    return bool(
        re.search(
            r"(?:今天|今日|今晚|明天|明日|明晚|后天|下周[一二三四五六日天]|"
            r"下星期[一二三四五六日天]|上午|早上|下午|晚上|中午|凌晨|"
            r"\d{1,2}\s*点|\d{1,2}\s*[:：]\s*\d{1,2}|"
            r"\b(?:today|tomorrow|tonight)\b|\bat\s+\d{1,2}(?::\d{2})?\b)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_meeting_content_task(value: str) -> bool:
    text = _clean_prompt(value)
    if not text:
        return False
    return bool(
        _contains_any(
            text,
            (
                "会议笔记",
                "会议纪要",
                "会议记录",
                "会议内容",
                "meeting note",
                "meeting notes",
                "meeting transcript",
                "meeting minutes",
            ),
        )
        and _contains_any(
            text,
            (
                "打开",
                "找到",
                "查找",
                "读取",
                "总结",
                "摘要",
                "整理",
                "报告",
                "open",
                "find",
                "read",
                "summarize",
                "summary",
                "report",
            ),
        )
    )


def _looks_like_explicit_group_run_request(value: str) -> bool:
    text = _clean_prompt(value)
    if not text:
        return False
    if _looks_like_timed_schedule_request(text) and not re.search(
        r"(?:agent|Agent|AI|智能体|代理|group|群组|小组|多\s*agent|多Agent)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(r"(?:group|群组|小组|团队)", text, flags=re.IGNORECASE)
        and re.search(
            r"(?:运行|启动|执行|让|安排|委派|分配|指派|协作|run|start|execute|delegate|assign)",
            text,
            flags=re.IGNORECASE,
        )
    )


def _desktop_content_artifact_requested(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    return _contains_any(
        value,
        (
            "报告",
            "总结",
            "摘要",
            "整理",
            "markdown",
            "md",
            "report",
            "summary",
            "summarize",
            "write up",
            "document",
        ),
    )


def _desktop_content_artifact_hint(text: str) -> dict[str, str]:
    if not _desktop_content_artifact_requested(text):
        return {}
    return {
        "path": _artifact_output_path(text, "desktop-content-report.md"),
        "body_source": "desktop_content",
    }


def _explicit_app_open_request(text: str) -> bool:
    return _contains_any(text, ("打开", "启动", "开启", "运行", "拉起", "open ", "launch ", "start "))


def _looks_like_foreground_submit_scope(value: str, lowered: str) -> bool:
    return bool(
        _contains_any(
            value,
            (
                "前台",
                "当前输入框",
                "当前文本框",
                "当前消息",
                "当前内容",
                "foreground",
                "current input",
                "current field",
                "current text box",
                "current message",
            ),
        )
        or re.search(r"(?:按|敲|点|tap|press|hit).{0,8}(?:回车|return|enter)", lowered, flags=re.IGNORECASE)
    )


def _foreground_submit_app_name_hint(text: str, action: str) -> str:
    if not action:
        return ""
    value = _clean_prompt(text)
    app_scoped_submit = _app_scoped_foreground_submit_app_name_hint(value)
    if app_scoped_submit:
        return app_scoped_submit
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<app>[\w .·-]{1,40}?)"
        r"(?:按|敲|点|tap|press|hit).{0,8}(?:回车|return|enter).{0,8}(?:发送|提交|send|submit)",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?P<app>[\w .·-]{1,40}?)"
        r"(?:发送|提交|send|submit).{0,8}(?:回车|return|enter)",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app = _canonical_app_name_hint(match.group("app"))
        if app:
            return app
    return ""


def _app_scoped_foreground_submit_app_name_hint(text: str) -> str:
    value = _clean_prompt(text)
    if not value or _looks_like_recipient_message_request(value):
        return ""
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|开启|切到|聚焦)?"
        r"(?:在|到|用|通过)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内)?\s*(?:确认)?(?:发送|提交)\s*$",
        r"^(?:please\s+)?(?:open|launch|focus|switch\s+to)?\s*"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:confirm\s+)?(?:send|submit)\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = str(match.group("app") or "").strip()
        if not raw_app or raw_app.startswith(("给", "向", "对")):
            continue
        if re.search(
            r"(?:粘贴|输入|键入|填写|写入|点击|搜索|查找|复制|剪贴板|"
            r"paste|type|enter|click|search|copy|clipboard)",
            raw_app,
            flags=re.IGNORECASE,
        ):
            continue
        if _is_generic_foreground_app_label(raw_app):
            continue
        app = _canonical_app_name_hint(raw_app)
        if app and not _is_generic_foreground_app_label(app):
            return app
    return ""


def _canonical_app_name_hint(value: str) -> str:
    app = _clean_app_name_hint(value)
    if not app:
        return ""
    return legacy_app_name_hint(app)


def _browser_internal_page_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    surface = (
        r"(?:下载内容|下载页面|下载页|下载记录|下载|书签|收藏夹|扩展程序|扩展|插件|"
        r"历史记录|浏览历史|设置|偏好设置|"
        r"downloads?|download\s+page|bookmarks?|favorites?|extensions?|add-?ons?|addons?|"
        r"history|settings|preferences)"
    )
    patterns: tuple[tuple[str, str], ...] = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<mode>打开|启动|开启|切到|聚焦)\s*"
            rf"(?P<app>[\w .·-]{{1,40}}?)\s*(?:的)?\s*(?P<surface>{surface})"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            "",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?P<app>[\w .·-]{{1,40}}?)\s*(?:打开|显示|查看|进入|切到|聚焦)\s*"
            rf"(?P<surface>{surface})(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            "focus",
        ),
        (
            r"^(?P<mode>open|launch|start|focus|switch\s+to|activate)\s+"
            rf"(?:the\s+)?(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+"
            rf"(?:the\s+)?(?P<surface>{surface})$",
            "",
        ),
        (
            rf"^(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+"
            rf"(?P<surface>{surface})$",
            "focus",
        ),
    )
    for pattern, default_mode in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _clean_app_name_hint(groups.get("app") or "")
        if (
            not app_name
            or _is_generic_browser_app_label(app_name)
            or not _is_browser_or_search_app_name(app_name)
        ):
            continue
        surface_kind = _browser_internal_surface_kind(groups.get("surface") or "")
        if not surface_kind:
            continue
        result: dict[str, str] = {
            "app_name": app_name,
            "surface": surface_kind,
            "mode": _command_palette_mode(groups.get("mode") or default_mode),
        }
        shortcut_action = _browser_internal_shortcut_action(surface_kind)
        if shortcut_action:
            result["action"] = shortcut_action
            return result
        url = _browser_internal_surface_url(app_name, surface_kind)
        if url:
            result["url"] = url
            return result
    return {}


def _browser_internal_surface_kind(value: str) -> str:
    normalized = re.sub(r"[\s_-]+", "", str(value or "").strip().lower())
    if "下载" in normalized or "download" in normalized:
        return "downloads"
    if "书签" in normalized or "收藏" in normalized or "bookmark" in normalized or "favorite" in normalized:
        return "bookmarks"
    if "扩展" in normalized or "插件" in normalized or "extension" in normalized or "addon" in normalized:
        return "extensions"
    if "历史" in normalized or "history" in normalized:
        return "history"
    if "设置" in normalized or "偏好" in normalized or "setting" in normalized or "preference" in normalized:
        return "settings"
    return ""


def _is_generic_browser_app_label(app_name: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(app_name or "").strip().lower())
    return normalized in {
        "browser",
        "any browser",
        "default browser",
        "浏览器",
        "任意浏览器",
        "任何浏览器",
        "默认浏览器",
        "网页",
        "页面",
        "当前网页",
        "当前页面",
        "current page",
        "current webpage",
        "web page",
    }


def _browser_internal_shortcut_action(surface: str) -> str:
    if surface == "history":
        return "show_history"
    if surface == "settings":
        return "preferences"
    return ""


def _browser_internal_surface_url(app_name: str, surface: str) -> str:
    family = _browser_family(app_name)
    urls = {
        "chrome": {
            "downloads": "chrome://downloads/",
            "bookmarks": "chrome://bookmarks/",
            "extensions": "chrome://extensions/",
        },
        "edge": {
            "downloads": "edge://downloads/",
            "bookmarks": "edge://favorites/",
            "extensions": "edge://extensions/",
        },
        "brave": {
            "downloads": "brave://downloads/",
            "bookmarks": "brave://bookmarks/",
            "extensions": "brave://extensions/",
        },
        "firefox": {
            "downloads": "about:downloads",
            "extensions": "about:addons",
        },
    }
    return urls.get(family, {}).get(surface, "")


def _browser_family(app_name: str) -> str:
    compact = compact_app_name_hint(app_name)
    if compact in {"chrome", "googlechrome", "chromium"}:
        return "chrome"
    if compact in {"edge", "microsoftedge"}:
        return "edge"
    if compact in {"brave", "bravebrowser"}:
        return "brave"
    if compact == "firefox":
        return "firefox"
    return ""


def _app_preferences_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    surface = r"(?:偏好设置|设置|preferences|settings)"
    patterns: tuple[tuple[str, str], ...] = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<mode>打开|启动|开启|切到|聚焦)\s*"
            rf"(?P<app>[\w .·-]{{1,40}}?)\s*(?:的)?\s*(?P<surface>{surface})"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            "",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            rf"(?:在|用|通过)\s*(?P<app>[\w .·-]{{1,40}}?)(?:里|中|上|内|里面)?\s*"
            rf"(?:打开|显示|查看|进入|切到|聚焦)\s*(?P<surface>{surface})"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            "focus",
        ),
        (
            r"^(?P<mode>open|launch|start|focus|switch\s+to|activate)\s+"
            rf"(?:the\s+)?(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+"
            rf"(?P<surface>{surface})$",
            "",
        ),
        (
            r"^(?!(?:open|launch|start|focus|switch\s+to|activate)\b)"
            rf"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+(?P<surface>{surface})$",
            "focus",
        ),
    )
    for pattern, default_mode in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _clean_app_name_hint(groups.get("app") or "")
        if (
            not app_name
            or _is_browser_or_search_app_name(app_name)
            or _is_system_settings_app_label(app_name)
        ):
            continue
        return {
            "app_name": app_name,
            "mode": _command_palette_mode(groups.get("mode") or default_mode),
            "action": "preferences",
        }
    return {}


def _is_system_settings_app_label(app_name: str) -> bool:
    compact = compact_app_name_hint(app_name)
    return compact in {
        "system",
        "systemsettings",
        "systempreferences",
        "settings",
        "preferences",
        "系统",
        "系统设置",
        "系统偏好",
        "系统偏好设置",
        "设置",
        "偏好",
        "偏好设置",
        "bluetooth",
        "蓝牙",
        "wifi",
        "wi-fi",
        "无线网络",
        "无线局域网",
        "network",
        "网络",
        "display",
        "displays",
        "显示器",
        "sound",
        "audio",
        "声音",
        "音频",
        "keyboard",
        "键盘",
        "notification",
        "notifications",
        "通知",
        "battery",
        "电池",
        "mouse",
        "鼠标",
        "trackpad",
        "触控板",
        "printer",
        "printers",
        "打印机",
        "focus",
        "专注模式",
        "wallpaper",
        "墙纸",
        "壁纸",
        "dock",
        "程序坞",
        "desktopdock",
        "桌面与程序坞",
        "screensaver",
        "屏幕保护程序",
        "屏幕保护",
        "siri",
        "language",
        "languageandregion",
        "语言与地区",
        "dateandtime",
        "日期与时间",
        "softwareupdate",
        "软件更新",
        "storage",
        "储存空间",
        "存储空间",
        "loginitems",
        "登录项",
        "usersandgroups",
        "用户与群组",
        "privacy",
        "security",
        "隐私",
        "隐私与安全性",
    }


def _desktop_operation_hint(text: str) -> str:
    safe_key = safe_key_hint(text)
    if safe_key:
        return "safe_key"
    if safe_shortcut_sequence_hint(text):
        return "safe_shortcut_sequence"
    safe_shortcut = safe_shortcut_hint(text)
    if str((safe_shortcut or {}).get("action") or "").strip() == "application_windows":
        return "safe_shortcut"
    if focus_window_hint(text):
        return "focus_window"
    if window_list_hint(text) is not None:
        return "list_windows"
    if ui_inspection_hint(text) is not None:
        return "read_ui"
    if screen_capture_hint(text) is not None:
        return "capture_screen"
    foreground_management = foreground_management_hint(text)
    if foreground_management:
        return str(foreground_management.get("action") or "")
    if safe_shortcut:
        return "safe_shortcut"
    if safe_scroll_hint(text):
        return "safe_scroll"
    if safe_click_hint(text):
        return "safe_click"
    if click_target_hint(text):
        return "click"
    app_management = app_management_hint(text)
    if app_management:
        return f"{app_management.get('action')}_app"
    if _contains_any(text, ["click", "点击"]):
        return "click"
    if _contains_any(text, ["type", "input", "输入"]):
        return "type"
    if _contains_any(text, ["play", "播放"]):
        return "play"
    if _contains_any(text, ["open", "launch", "打开", "启动"]):
        return "open"
    return ""


def _desktop_observation_prepare_mode(text: str) -> str:
    if _contains_any(
        text,
        ["切到", "聚焦", "focus", "switch to", "switch ", "activate ", "bring "],
    ):
        return "focus"
    if _contains_any(text, ["open", "launch", "start", "打开", "启动", "开启", "拉起"]):
        return "open"
    return "focus"


def _foreground_safe_shortcut_hint(hint: Mapping[str, Any] | None) -> bool:
    if not isinstance(hint, Mapping):
        return False
    return str(hint.get("action") or "").strip() in {
        "refresh",
        "new_tab",
        "new_window",
        "new_document",
        "new_private_window",
        "close_tab",
        "next_tab",
        "previous_tab",
        "reopen_closed_tab",
        "next_window",
        "previous_window",
        "switch_next_app",
        "switch_previous_app",
        "hide_other_apps",
        "mission_control",
        "spotlight_search",
        "emoji_picker",
        "lock_screen",
        "force_quit_dialog",
        "browser_forward",
        "browser_back",
        "bookmark_page",
        "show_history",
        "open_devtools",
        "focus_address_bar",
        "copy_current_page_link",
        "screenshot_selection",
        "screenshot_toolbar",
        "paste",
    }


def _system_foreground_safe_shortcut_hint(hint: Mapping[str, Any] | None) -> bool:
    if not isinstance(hint, Mapping):
        return False
    return str(hint.get("action") or "").strip() in {
        "hide_other_apps",
        "mission_control",
        "spotlight_search",
        "emoji_picker",
        "lock_screen",
        "force_quit_dialog",
    }


def _app_management_prepare_mode(
    text: str,
    app_name_hint: str,
    hint: Mapping[str, Any] | None,
) -> str:
    if not isinstance(hint, Mapping):
        return ""
    app_name = str(app_name_hint or hint.get("app_name") or "").strip()
    if not app_name:
        return ""
    connector = r"(?:然后|再|接着|之后|后|\bthen\b|\band\b)"
    management = r"(?:隐藏|藏起来|收起|最小化|退出|关闭|关掉|结束|终止|hide|minimi[sz]e|quit|close|exit|terminate)"
    app = re.escape(app_name)
    if (
        re.search(rf"(?:切到|聚焦)\s*{app}.*{connector}.*{management}", text, flags=re.IGNORECASE)
        or re.search(rf"{app}\s*(?:切到|聚焦).*(?:{connector}).*{management}", text, flags=re.IGNORECASE)
        or re.search(
            rf"(?:focus|switch\s+to|activate|bring)\s+{app}\b.*{connector}.*{management}",
            text,
            flags=re.IGNORECASE,
        )
    ):
        return "focus"
    if (
        re.search(rf"(?:打开|启动|开启|运行|拉起)\s*{app}.*{connector}.*{management}", text, flags=re.IGNORECASE)
        or re.search(rf"{app}\s*(?:打开|启动|开启|运行|拉起).*{connector}.*{management}", text, flags=re.IGNORECASE)
        or re.search(
            rf"(?:open|launch|start)\s+{app}\b.*{connector}.*{management}",
            text,
            flags=re.IGNORECASE,
        )
    ):
        return "open"
    return ""


def _app_search_prepare_mode(text: str, fallback: str) -> str:
    if _contains_any(text, ["打开", "启动", "开启", "open ", "launch ", "start "]):
        return fallback
    return "focus"


def _safe_shortcut_targets_foreground(
    text: str,
    hint: Mapping[str, Any] | None,
    app_name_hint: str,
) -> bool:
    if not _foreground_safe_shortcut_hint(hint):
        return False
    return not _safe_shortcut_has_explicit_app_scope(text, app_name_hint)


def _safe_shortcut_has_explicit_app_scope(text: str, app_name_hint: str) -> bool:
    app_name = str(app_name_hint or "").strip()
    if not app_name:
        return False
    normalized = _normalized_shortcut_target_name(app_name)
    generic_targets = {
        "anewtab",
        "newtab",
        "tab",
        "currenttab",
        "thistab",
        "anewwindow",
        "newwindow",
        "privatewindow",
        "incognitowindow",
        "incogni",
        "currentpage",
        "thispage",
        "page",
        "nextwindow",
        "previouswindow",
        "nextapp",
        "previousapp",
        "browserhistory",
        "browsinghistory",
        "history",
        "dev",
        "devtools",
        "developertools",
        "addressbar",
        "urlbar",
        "一个新窗口",
        "新窗口",
        "标签页",
        "新标签页",
        "当前标签页",
        "当前网页",
        "网页",
        "一个窗口",
        "下一个窗口",
        "上一个窗口",
        "一个应用",
        "下一个应用",
        "上一个应用",
        "一个",
        "浏览器历史记录",
        "历史记录",
        "开发者工具",
        "当前网页开发者工具",
        "当前网页的开发者工具",
        "地址栏",
        "截图工具",
        "截图面板",
        "屏幕截图工具",
        "屏幕截图面板",
        "录屏工具",
        "录屏面板",
        "screenshottool",
        "screenshottoolbar",
        "screenshotpanel",
        "screencapturetool",
        "screencapturetoolbar",
        "screencapturepanel",
        "screenrecordingtool",
        "screenrecordingtoolbar",
        "screenrecordingpanel",
    }
    if normalized in generic_targets:
        return False
    return bool(
        re.search(
            rf"(?:把|将)\s*{re.escape(app_name)}\s*(?:打开|启动|开启|切到|聚焦)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"(?:打开|启动|开启|切到|聚焦)\s*{re.escape(app_name)}\s*",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"(?:open|launch|focus|start|activate)\s+(?:the\s+)?{re.escape(app_name)}\b",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"(?:bring|switch)\s+{re.escape(app_name)}\s+(?:to\s+(?:the\s+)?(?:front|foreground)|forward)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"(?:在|用|通过)\s*{re.escape(app_name)}\s*"
            r"(?:里|中|上|内|来|去|打开|启动|点击|点按|按|输入|搜索|播放|创建|新建|写|发送|分析|操作|帮|$)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(
            rf"(?:in|inside|within|using|with)\s+{re.escape(app_name)}\b",
            text,
            flags=re.IGNORECASE,
        )
    )


def _normalized_shortcut_target_name(value: str) -> str:
    return re.sub(r"[\s._·-]+", "", str(value or "").strip().lower())


def _browser_url_action_hint(text: str, context_source: str) -> dict[str, Any]:
    if context_source in {"selection", "clipboard"}:
        return {}
    value = _clean_prompt(text)
    url = _explicit_browser_url_hint(value)
    if not url:
        return {}
    if _looks_like_url_screenshot_request(value):
        return {
            "browser_action": "open_url_screenshot",
            "url_hint": url,
            "reason": "user asked to capture the browser page after opening a URL",
        }
    if _looks_like_direct_url_text_request(value):
        hint = {"browser_action": "open_url_extract", "url_hint": url}
        if _looks_like_url_summary_request(value):
            hint["presentation"] = "summary"
        return hint
    if not _looks_like_plain_url_open(value):
        return {}
    return {"browser_action": "open_url", "url_hint": url}


def _direct_communication_candidate_hint(
    text: str,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    file_context = _communication_file_context_hint(text, metadata)
    if file_context:
        return _direct_file_context_communication_hint(text, file_context)
    source = _communication_context_source_hint(text)
    if source:
        direct_context_hint = _direct_context_communication_hint(text, source)
        if direct_context_hint:
            return direct_context_hint
    generic_hint = _generic_direct_communication_hint(text)
    if str(generic_hint.get("channel") or "").strip() == "email":
        return generic_hint
    return _direct_paste_communication_hint(text) or _direct_communication_hint(text) or generic_hint


def _direct_file_context_communication_hint(
    text: str,
    file_context: Mapping[str, Any],
) -> dict[str, str]:
    if not file_context:
        return {}
    value = _clean_prompt(text)
    if not value or not _contains_any(value, _COMMUNICATION_ACTION_TERMS):
        return {}
    tail = _communication_tail_after_data_source(value)
    candidates = [tail]
    if tail != value:
        candidates.append(value)
    recipient_stop = (
        r"(?=(?:\s*(?:并|然后|再|之后|后)\s*(?:说明|说|附上|备注|告诉|解释)|"
        r"\s*(?:说明|说|附上|备注|告诉|解释)|[，,。；;！!？?]|$))"
    )
    patterns = (
        rf"^(?:[，,。；;\s]+)?(?:(?:并|然后|再|之后|后)\s*)?"
        rf"(?:请|帮我|麻烦)?(?:通过|用|在)\s*(?P<app>[\w .·-]{{1,40}}?)(?:里|中|上|内)?\s*"
        rf"(?:(?:发送|发出|发消息|发)\s*(?P<channel>邮件|电子邮件|消息|短信|微信|email|e-mail|mail|message)?\s*"
        rf"(?:给|到|发给|发送给|向|对)|(?:发给|发送给|发到|发送到))\s*"
        rf"(?P<target>[^，,。；;！!？?]+?){recipient_stop}",
        rf"^(?:[，,。；;\s]+)?(?:(?:并|然后|再|之后|后)\s*)?"
        rf"(?:请|帮我|麻烦)?(?:(?:发送|发出|发消息|发)\s*"
        rf"(?P<channel>邮件|电子邮件|消息|短信|微信|email|e-mail|mail|message)?\s*"
        rf"(?:给|到|发给|发送给|向|对)|(?:发给|发送给|发到|发送到))\s*"
        rf"(?P<target>[^，,。；;！!？?]+?){recipient_stop}",
        r"^(?:\s+)?(?:send|email|message)\s+(?:it|this|the\s+file)?\s*"
        r"(?:to|for)\s+(?P<target>[^.!?,]+?)(?:\s+(?:saying|about|with|and)\b.*)?$",
    )
    for candidate in candidates:
        for pattern in patterns:
            match = re.search(pattern, candidate, flags=re.IGNORECASE)
            if not match:
                continue
            groups = match.groupdict()
            app_name = _canonical_app_name_hint(groups.get("app") or "")
            if _is_generic_communication_app_label(groups.get("app") or ""):
                app_name = ""
            target = _clean_communication_hint_text(groups.get("target") or "")
            recipient = _clean_communication_recipient_text(groups.get("recipient") or "")
            if target and (not app_name or not recipient):
                split_app, split_recipient = _split_communication_surface_and_recipient(target)
                app_name = app_name or split_app
                recipient = recipient or split_recipient or _clean_communication_recipient_text(target)
            if not app_name and recipient:
                app_name = _communication_surface_for_recipient_hint(recipient)
            if not recipient:
                continue
            channel = _canonical_communication_channel(groups.get("channel") or "")
            hint = {
                "recipient": recipient,
                "body_source": "file",
                "mode": _communication_app_mode(value),
                "send_action": (
                    "draft" if _looks_like_communication_draft_request(value) else "send"
                ),
            }
            if app_name:
                hint["app_name"] = app_name
            if channel:
                hint["channel"] = channel
            return hint
    return {}


def _communication_tail_after_data_source(text: str) -> str:
    value = _clean_prompt(text)
    source_hint = str(data_source_hint(value) or "").strip()
    candidates = [source_hint]
    if "/" in source_hint or "\\" in source_hint:
        candidates.append(re.split(r"[/\\]", source_hint)[-1])
    for candidate in sorted({item for item in candidates if item}, key=len, reverse=True):
        match = re.search(re.escape(candidate), value, flags=re.IGNORECASE)
        if match:
            return value[match.end() :].strip()
    return value


def _direct_paste_communication_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not re.search(r"(?:粘贴|paste)", value, flags=re.IGNORECASE):
        return {}
    patterns = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|开启)?\s*(?:在|用|通过)?\s*"
            r"(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内)?\s*"
            r"(?:给|发给|发送给|发到|发送到)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:粘贴|paste)\s*(?:并|然后|再|后|之后)?\s*(?:发送|发出|send)?$"
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:把|将)?(?:剪贴板内容|粘贴板内容)?\s*(?:粘贴|paste)\s*"
            r"(?:到|给|发给|发送给)\s*(?P<target>[^：:，,。]+?)\s*"
            r"(?:并|然后|再|后|之后)?\s*(?:发送|发出|send)?$"
        ),
        (
            r"^(?:paste|send)\s+(?:clipboard(?:\s+contents?)?|the\s+clipboard)?\s*"
            r"(?:in|with|using|through)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?:to|for)\s+(?P<recipient>[^.!?,]+?)(?:\s+(?:and|then)\s+send)?$"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _canonical_app_name_hint(groups.get("app") or "")
        recipient = _clean_communication_recipient_text(groups.get("recipient") or "")
        if (not app_name or not recipient) and groups.get("target"):
            app_name, recipient = _split_communication_surface_and_recipient(
                str(groups.get("target") or "")
            )
        if not app_name or not recipient:
            continue
        return {
            "app_name": app_name,
            "recipient": recipient,
            "body_source": "clipboard",
            "mode": _communication_app_mode(value),
            "send_action": "send",
        }
    return {}


def _direct_communication_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    patterns = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|开启)?\s*(?:在|用|通过)?\s*"
            r"(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内)?\s*"
            r"(?:给|向|对|发给|发送给|发到|发送到)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:发送|发出|发消息|发|说|message|send)\s*(?P<body>.+)$"
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:发送|发消息|发)\s*(?P<app>[\w .·-]{1,40}?)\s*"
            r"(?:给|到|发给|发送给)\s*(?P<recipient>[^：:，,。]+?)"
            r"\s*[:：]\s*(?P<body>.+)$"
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:给|向|对)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:发送|发消息|发)\s*(?P<app>[\w .·-]{1,40}?)\s*"
            r"(?:说|内容是|内容为)\s*(?P<body>.+)$"
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:给|向|对)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:发送|发消息|发)\s*(?P<app>[\w .·-]{1,40}?)"
            r"\s*[:：]\s*(?P<body>.+)$"
        ),
        (
            r"^(?:打开|启动|开启)?\s*(?P<app>[\w .·-]{1,40}?)\s*"
            r"(?:发消息|发送|发)\s*(?:给|到)?\s*(?P<recipient>[^：:，,。]+?)"
            r"\s*[:：]\s*(?P<body>.+)$"
        ),
        (
            r"^(?:打开|启动|开启)?\s*(?P<app>[\w .·-]{1,40}?)\s*"
            r"(?:发消息|发送|发)\s*(?:给|到)?\s*(?P<recipient_message_tail>[^：:，,。]+)$"
        ),
        (
            r"^(?:在|用|通过)?\s*(?P<app>[\w .·-]{1,40}?)\s*"
            r"(?:搜索|查找|找)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:并|然后|再)\s*(?:发送|发消息|发)\s*(?P<body>.+)$"
        ),
        (
            r"^(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?:search|find|look\s+up)\s+(?P<recipient>[^.!?,]+?)\s+"
            r"(?:and|then)\s+(?:send|message)\s+(?P<body>[^.!?]+)$"
        ),
        (
            r"^(?:open|launch|start)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?:and\s+)?(?:send|message)\s+(?P<body>[^.!?]+?)\s+"
            r"(?:to|for)\s+(?P<recipient>[^.!?,]+)$"
        ),
        (
            r"^(?:please\s+)?(?:send|message)\s+(?P<body>[^.!?]+?)\s+"
            r"(?:in|with|using|through)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?:to|for)\s+(?P<recipient>[^.!?,]+)$"
        ),
        (
            r"^(?:please\s+)?(?:message|send)\s+(?P<recipient>[^.!?,]+?)\s+"
            r"(?:in|with|using|through)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?P<body>[^.!?]+)$"
        ),
        (
            r"^(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?:send|message)\s+(?P<body>[^.!?]+?)\s+"
            r"(?:to|for)\s+(?P<recipient>[^.!?,]+)$"
        ),
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _canonical_app_name_hint(groups.get("app") or "")
        recipient_tail = str(groups.get("recipient_message_tail") or "").strip()
        if recipient_tail:
            split_tail = _split_communication_implicit_recipient_message(recipient_tail)
            if not split_tail:
                continue
            recipient, body = split_tail
        else:
            recipient = _clean_communication_recipient_text(groups.get("recipient") or "")
            body = _clean_communication_body_text(groups.get("body") or "")
        if _is_generic_communication_app_label(groups.get("app") or ""):
            continue
        if not app_name or not recipient or not body:
            continue
        return {
            "app_name": app_name,
            "recipient": recipient,
            "body": body,
            "mode": _communication_app_mode(value),
            "send_action": "send",
        }
    return _generic_direct_communication_hint(value)


def _generic_direct_communication_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    patterns = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:发送|发出|发消息|发)\s*(?:消息|短信|微信|message)?\s*"
            r"(?:给|发给|发送给|到|向|对)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:说|内容是|内容为|[:：])\s*(?P<body>.+)$",
            "message",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:给|向|对|发给|发送给)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:发送|发出|发消息|发)\s*(?:消息|短信|微信|message)?\s*"
            r"(?:说|内容是|内容为|[:：])\s*(?P<body>.+)$",
            "message",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:给|向|对)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?:写|撰写|起草|草拟|发|发送)\s*(?:一封|封|条)?\s*"
            r"(?P<channel>邮件|电子邮件|短信|消息|email|e-mail|mail|message)\s*"
            r"(?P<body>(?:说|说明|关于|内容是|内容为|[:：]).+)$",
            "",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:写|撰写|起草|草拟|发|发送)\s*(?:一封|封|条)?\s*"
            r"(?P<channel>邮件|电子邮件|短信|消息|email|e-mail|mail|message)\s*"
            r"(?:给|发给|发送给|向|对)\s*(?P<recipient>[^：:，,。]+?)\s*"
            r"(?P<body>(?:说|说明|关于|内容是|内容为|[:：]).+)$",
            "",
        ),
        (
            r"^(?:please\s+)?(?:send|message)\s+(?P<body>[^.!?]+?)\s+"
            r"(?:to|for)\s+(?P<recipient>[^.!?,]+)$",
            "message",
        ),
        (
            r"^(?:please\s+)?(?:write|draft|compose)\s+(?:an?\s+)?"
            r"(?P<channel>email|e-mail|mail|message)\s+"
            r"(?:to|for)\s+(?P<recipient>[^.!?,]+?)\s+"
            r"(?P<body>(?:about|saying|that)\s+[^.!?]+)$",
            "",
        ),
    )
    for pattern, channel_hint in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        recipient = _clean_communication_recipient_text(groups.get("recipient") or "")
        body = _clean_communication_body_text(groups.get("body") or "")
        if not recipient or not body:
            continue
        channel = _canonical_communication_channel(groups.get("channel") or channel_hint)
        hint = {
            "recipient": recipient,
            "body": body,
            "mode": _communication_app_mode(value),
            "send_action": (
                "draft" if _looks_like_communication_draft_request(value) else "send"
            ),
        }
        if channel:
            hint["channel"] = channel
        return hint
    return {}


def _direct_context_communication_hint(text: str, source: str) -> dict[str, str]:
    if source not in {
        "clipboard",
        "selection",
        "current_page_link",
        "current_page_content",
        "visible_text",
    }:
        return {}
    value = _clean_prompt(text)
    source_pattern = {
        "clipboard": r"(?:剪贴板内容|粘贴板内容|clipboard\s+contents?|the\s+clipboard)",
        "selection": (
            r"(?:当前选中的内容|当前选中内容|当前选中的文字|当前选中文字|当前选中文本|"
            r"选中的内容|选中内容|选中的文字|选中文字|选中文本|"
            r"selected\s+text|selected\s+content|selection)"
        ),
        "current_page_link": r"(?:当前网页链接|当前页面链接|当前链接|current\s+page\s+link|current\s+url)",
        "current_page_content": (
            r"(?:当前网页|当前页面|当前页|这个网页|这个页面|"
            r"current\s+page|current\s+webpage|this\s+page|this\s+webpage)"
            r"(?:的|里的)?(?:内容|正文|文本|文字|摘要|总结|报告|content|text|summary|report)?"
        ),
        "visible_text": (
            r"(?:当前窗口|当前应用|当前界面|当前屏幕|前台窗口|前台应用|"
            r"current\s+window|current\s+app|foreground\s+window|foreground\s+app)"
            r"(?:的|里的)?(?:内容|文本|文字|摘要|总结|报告|content|text|summary|report)?"
        ),
    }[source]
    patterns = (
        rf"^(?:打开|启动|开启)?\s*(?:在|用|通过)?\s*"
        rf"(?P<app>[\w .·-]{{1,40}}?)(?:里|中|上|内)?\s*"
        rf"(?:给|发给|发送给)\s*(?P<recipient>[^：:，,。]+?)\s*"
        rf"(?:发送|发|发消息)\s*{source_pattern}$",
        rf"^(?:把|将)?\s*(?:(?:读取|阅读|读一下|读下|查看|看看|read|inspect)\s*)?"
        rf"{source_pattern}.{{0,50}}?"
        rf"(?:发给|发送给|发到|发送到)\s*(?P<target>[^：:，,。]+)$",
        rf"^(?:把|将)?\s*(?:(?:读取|阅读|读一下|读下|查看|看看|read|inspect)\s*)?"
        rf"{source_pattern}\s*(?:通过|用|在)\s*(?P<app>[\w .·-]{{1,40}}?)\s*(?:发给|发送给|发到|发送到)\s*(?P<recipient>[^：:，,。]+)$",
        rf"^(?:把|将)?\s*(?:(?:读取|阅读|读一下|读下|查看|看看|read|inspect)\s*)?"
        rf"{source_pattern}\s*(?:发给|发送给|发到|发送到)\s*(?P<target>[^：:，,。]+)$",
        rf"^(?:给|发给|发送给|发到|发送到)\s*(?P<target>[^：:，,。]+?)\s*(?:发送|发|发消息)\s*{source_pattern}$",
        rf"^(?:send|message)\s+{source_pattern}\s+(?:in|with|using|through)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+(?:to|for)\s+(?P<recipient>[^.!?,]+)$",
        rf"^(?:in|with|using|through)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+(?:send|message)\s+{source_pattern}\s+(?:to|for)\s+(?P<recipient>[^.!?,]+)$",
        rf"^(?:send|message)\s+{source_pattern}\s+(?:to|for)\s+(?P<target>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _canonical_app_name_hint(groups.get("app") or "")
        recipient = _clean_communication_hint_text(groups.get("recipient") or "")
        if (not app_name or not recipient) and groups.get("target"):
            app_name, recipient = _split_communication_surface_and_recipient(
                str(groups.get("target") or "")
            )
        if not app_name and recipient:
            app_name = _communication_surface_for_recipient_hint(recipient)
        if not app_name or not recipient:
            continue
        return {
            "app_name": app_name,
            "recipient": recipient,
            "body_source": source,
            "mode": _communication_app_mode(value),
            "send_action": "send",
        }
    return {}


def _split_communication_surface_and_recipient(target: str) -> tuple[str, str]:
    value = _clean_communication_hint_text(target)
    known_surfaces = (
        "Microsoft Teams",
        "Google Chat",
        "企业微信",
        "Apple Messages",
        "Messages",
        "Telegram",
        "WhatsApp",
        "Discord",
        "Slack",
        "WeChat",
        "微信",
        "飞书",
        "钉钉",
        "QQ",
        "Mail",
    )
    lowered = value.lower()
    for surface in known_surfaces:
        if lowered == surface.lower():
            return "", ""
        if lowered.startswith(surface.lower() + " "):
            recipient = _strip_communication_surface_connector(value[len(surface) :])
            return (
                _canonical_app_name_hint(surface),
                _clean_communication_recipient_text(recipient),
            )
        if value.startswith(surface) and len(value) > len(surface):
            recipient = _strip_communication_surface_connector(value[len(surface) :])
            return (
                _canonical_app_name_hint(surface),
                _clean_communication_recipient_text(recipient),
            )
    parts = value.split(None, 1)
    if len(parts) == 2:
        return _canonical_app_name_hint(parts[0]), _clean_communication_hint_text(parts[1])
    app_name = _communication_surface_for_recipient_hint(value)
    return (app_name, value) if app_name else ("", "")


def _strip_communication_surface_connector(value: str) -> str:
    return re.sub(
        r"^(?:的|里(?:的)?|中(?:的)?|上(?:的)?|内(?:的)?|里面(?:的)?|中的)?\s*",
        "",
        _clean_communication_hint_text(value),
    )


def _communication_surface_for_recipient_hint(recipient: str) -> str:
    normalized = re.sub(
        r"[\s._·《》<>「」『』“”\"'`-]+",
        "",
        _clean_communication_recipient_text(recipient).lower(),
    )
    if normalized in {
        "文件传输助手",
        "微信文件传输助手",
        "filetransferassistant",
        "filehelper",
        "wechatfiletransfer",
    }:
        return "WeChat"
    return ""


def _split_communication_implicit_recipient_message(value: str) -> tuple[str, str] | None:
    text = _clean_communication_hint_text(value)
    explicit = re.search(
        r"^(?P<recipient>.+?)\s*(?:说|内容是|内容为|:|：)\s*(?P<body>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if explicit:
        recipient = _clean_communication_recipient_text(explicit.group("recipient"))
        body = _clean_communication_body_text(explicit.group("body"))
        return (recipient, body) if recipient and body else None

    greeting_pattern = r"hello\b.*|hi\b.*|hey\b.*|thanks\b.*|thank\s+you\b.*|ok\b.*|okay\b.*"
    spaced = re.search(
        rf"^(?P<recipient>.+?)\s+(?P<body>{greeting_pattern})$",
        text,
        flags=re.IGNORECASE,
    )
    if spaced:
        recipient = _clean_communication_recipient_text(spaced.group("recipient"))
        body = _clean_communication_body_text(spaced.group("body"))
        return (recipient, body) if recipient and body else None

    compact = re.search(
        r"^(?P<recipient>.+?)(?P<body>"
        r"你好.*|您好.*|在吗.*|早上好.*|中午好.*|下午好.*|晚上好.*|"
        r"晚安.*|早安.*|谢谢.*|辛苦了.*|收到.*|好的.*|测试(?:一下)?"
        r")$",
        text,
        flags=re.IGNORECASE,
    )
    if compact:
        recipient = _clean_communication_recipient_text(compact.group("recipient"))
        body = _clean_communication_body_text(compact.group("body"))
        return (recipient, body) if recipient and body else None
    return None


def _communication_app_mode(text: str) -> str:
    value = _clean_prompt(text)
    if re.search(r"^(?:打开|启动|开启)\s*", value, flags=re.IGNORECASE):
        return "open"
    if re.search(r"^(?:open|launch|start)\s+", value, flags=re.IGNORECASE):
        return "open"
    return "focus"


def _clean_communication_hint_text(value: str) -> str:
    text = re.sub(r"^[：:，,\s]+", "", str(value or "").strip())
    text = re.sub(r"[。.,，；;！!？?]+$", "", text).strip()
    return text.strip("「」\"'“”‘’")


def _clean_communication_recipient_text(value: str) -> str:
    text = _clean_communication_hint_text(value)
    text = re.sub(r"\s*(?:聊天|会话|对话|chat|conversation)$", "", text, flags=re.IGNORECASE)
    return text.strip(" 「」『』“”\"'`")


def _clean_communication_body_text(value: str) -> str:
    text = _clean_foreground_compose_text(_clean_communication_hint_text(value))
    return re.sub(r"^(?:说(?!明)|内容是|内容为)\s*", "", text, flags=re.IGNORECASE).strip()


def _canonical_communication_channel(value: str) -> str:
    normalized = re.sub(r"[\s._·-]+", "", str(value or "").strip().lower())
    if normalized in {"邮件", "电子邮件", "email", "mail"}:
        return "email"
    if normalized in {"消息", "短信", "微信", "message", "messages"}:
        return "message"
    return ""


def _looks_like_communication_draft_request(value: str) -> bool:
    return bool(
        re.search(
            r"(?:写|撰写|起草|草拟|draft|compose|write)",
            _clean_prompt(value),
            flags=re.IGNORECASE,
        )
    )


def _is_generic_communication_app_label(value: str) -> bool:
    normalized = re.sub(r"[\s._·-]+", "", str(value or "").strip().lower())
    return normalized in {
        "消息",
        "送消息",
        "信息",
        "私信",
        "邮件",
        "电子邮件",
        "mail",
        "email",
        "message",
        "messages",
        "msg",
        "dm",
    }


def _app_scoped_desktop_operation_hint(text: str) -> bool:
    safe_shortcut = safe_shortcut_hint(text)
    if _app_scoped_safe_shortcut_app_name_hint(text, safe_shortcut):
        return True
    if _app_scoped_safe_operation_hint(text):
        return True
    app_name = _app_name_hint(text)
    if app_name and _is_browser_or_search_app_name(app_name):
        return False
    if app_name and _looks_like_non_app_operation_fragment(app_name):
        return False
    if _app_search_hint(text, app_name):
        return True
    if not app_name:
        return False
    return bool(
        click_target_hint(text)
        or type_into_ui_hint(text, app_name=app_name)
        or safe_type_text_hint(text)
        or _contains_any(
            text,
            ("click", "press", "tap", "type", "enter", "fill", "点击", "点按", "按", "输入"),
        )
    )


def _app_scoped_ui_operation_hint(text: str) -> bool:
    app_name = _app_name_hint(text)
    if not app_name or _is_browser_or_search_app_name(app_name):
        return False
    if _looks_like_non_app_operation_fragment(app_name):
        return False
    return bool(
        click_target_hint(text)
        or type_into_ui_hint(text, app_name=app_name)
        or _app_first_click_scope_hint(text)
        or _app_first_type_scope_hint(text)
    )


def _looks_like_app_scoped_ticket_or_creation_request(text: str) -> bool:
    value = _clean_prompt(text)
    if not value or not _app_name_hint(value):
        return False
    if not re.search(
        r"(?:ticket|issue|bug|task|card|工单|事项|任务|卡片|项目|workspace)",
        value,
        flags=re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(
            r"(?:打开|启动|开启|运行|拉起|在|用|通过|open|launch|start|in|inside|within|using|with)"
            r".{0,80}(?:创建|新建|新增|添加|create|new|add)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_non_app_operation_fragment(app_name: str) -> bool:
    value = _clean_prompt(app_name)
    lowered = value.lower()
    if re.match(r"^(?:click|press|tap|type|enter|fill|open|visit)\b", lowered):
        return True
    return _contains_any(
        lowered,
        (
            "current page",
            "current webpage",
            "search field",
            "search box",
            "search input",
            "search result",
            "webpage search",
            "browser search",
        ),
    )


def _finder_search_then_ui_action_hint(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if not re.search(r"(?:Finder|访达)", value, flags=re.IGNORECASE):
        return False
    if not re.search(r"(?:搜索|查找|检索|找|search|find)", value, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:然后|并|再|接着|之后|后|and\s+then|then).{0,12}"
            r"(?:打开|点击|点开|进入|open|click).{0,8}"
            r"(?:第?一个|第一条|首个|第1个|第1条|first|1st)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _finder_special_location_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    if not value:
        return {}
    normalized = re.sub(r"[\s._·-]+", "", value.lower())
    finder_explicit = bool(
        re.search(r"(?:^|\b)finder(?:\b|$)", value, flags=re.IGNORECASE)
        or "访达" in value
    )
    action = ""
    if "隔空投送" in value or "airdrop" in normalized:
        action = "finder_airdrop"
    elif (
        "网络位置" in value
        or "networklocation" in normalized
        or (finder_explicit and ("网络" in value or "network" in normalized))
    ):
        action = "finder_network"
    elif (
        "最近使用" in value
        or "最近项目" in value
        or "最近使用项目" in value
        or any(marker in normalized for marker in ("recents", "recentitems", "recentfiles"))
    ):
        action = "finder_recents"
    if not action:
        return {}
    focus_prefix = bool(
        re.match(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:在|用|通过)?\s*(?:Finder|访达)\b",
            value,
            flags=re.IGNORECASE,
        )
        or any(
            normalized.startswith(prefix)
            for prefix in (
                "finder",
                "infinder",
                "usingfinder",
                "withfinder",
                "访达",
                "在访达",
                "用访达",
                "通过访达",
            )
        )
    )
    return {
        "app_name": "Finder",
        "mode": "focus" if focus_prefix else "open",
        "safe_shortcut": {"action": action},
    }


def _app_scoped_safe_operation_hint(text: str) -> dict[str, Any]:
    parsed = _app_scoped_followup_hint(text)
    if not parsed:
        return {}
    followup = str(parsed.get("followup") or "").strip()
    if not followup:
        return {}
    safe_key = safe_key_hint(followup)
    safe_scroll = safe_scroll_hint(followup)
    safe_shortcut = safe_shortcut_hint(followup)
    app_name = str(parsed.get("app_name") or "").strip()
    canonical_app_name = _canonical_app_name_hint(app_name)
    if safe_shortcut is None:
        default_new_action = _app_default_new_item_shortcut_action(canonical_app_name, followup)
        if default_new_action:
            safe_shortcut = {"action": default_new_action}
    if safe_shortcut:
        new_item_app_name = _app_new_item_shortcut_target_name(
            canonical_app_name,
            safe_shortcut,
        )
        if new_item_app_name:
            app_name = new_item_app_name
    if not safe_key and not safe_scroll and not safe_shortcut:
        return {}
    if (
        safe_shortcut
        and _safe_shortcut_requires_finder_scope(safe_shortcut)
        and not _is_finder_app_name(app_name)
    ):
        safe_shortcut = None
        if not safe_key and not safe_scroll:
            return {}
    result = {
        "app_name": app_name,
        "mode": str(parsed.get("mode") or "").strip() or "focus",
    }
    if safe_key:
        result["safe_key"] = safe_key
    if safe_scroll:
        result["safe_scroll"] = safe_scroll
    if safe_shortcut and (
        not _safe_shortcut_requires_finder_scope(safe_shortcut)
        or _is_finder_app_name(str(result.get("app_name") or ""))
    ):
        result["safe_shortcut"] = safe_shortcut
    return result


def _app_default_new_item_shortcut_action(app_name: str, followup: str) -> str:
    normalized = re.sub(r"[\s._·-]+", "", _clean_prompt(followup).lower())
    if normalized not in {"新建", "创建", "new", "compose"}:
        return ""
    return {
        "Notes": "new_note",
        "Reminders": "new_reminder",
        "Calendar": "new_event",
    }.get(app_name, "")


def _app_new_item_shortcut_target_name(
    canonical_app_name: str,
    safe_shortcut: Mapping[str, Any],
) -> str:
    action = str(safe_shortcut.get("action") or "").strip()
    app_by_action = {
        "new_note": "Notes",
        "new_reminder": "Reminders",
        "new_event": "Calendar",
    }
    if action == "new_message" and _app_supports_new_message_shortcut(canonical_app_name):
        return canonical_app_name
    expected_app_name = app_by_action.get(action, "")
    if canonical_app_name == expected_app_name:
        return expected_app_name
    return ""


def _app_supports_new_message_shortcut(app_name: str) -> bool:
    return supports_new_message_app_hint(app_name)


def _app_scoped_followup_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    safe_followup = (
        r"(?P<followup>(?:按一下|按下|按|发送|触发|"
        r"向下|往下|朝下|向上|往上|朝上|下滑|上滑|下滚|上滚|"
        r"下翻|上翻|下一页|上一页|滚动|滚|滑动|滑|翻页|翻|拉|"
        r"复制|粘贴|全选|撤销|重做|查找|搜索|打开搜索|刷新|后退|前进|最大化|全屏|"
        r"打开(?:一个)?(?:新标签页|新窗口|无痕窗口|隐身窗口|私密窗口)|"
        r"开(?:一个)?新标签页|新开(?:一个)?标签页|"
        r"新建|创建|"
        r"新建标签页|新建窗口|新建文件夹|关闭标签页|关闭当前标签页|"
        r"下一个标签|下一个标签页|切到下一个标签页|切换到下一个标签页|"
        r"上一个标签|上一个标签页|切到上一个标签页|切换到上一个标签页|"
        r"新建提醒事项|新建提醒|新提醒|创建提醒事项|创建提醒|"
        r"新建日程|新建日历事件|新建事件|新建会议|新日程|新事件|新会议|创建日程|创建事件|"
        r"新建备忘录|新建笔记|新笔记|新备忘录|创建备忘录|创建笔记|"
        r"新建项目|新建一个项目|创建项目|创建一个项目|新项目|"
        r"新建工单|创建工单|新建任务|创建任务|新建卡片|创建卡片|"
        r"新建\s*(?:ticket|issue|bug|bug\s*ticket)|"
        r"创建(?:一个|一条|一张)?\s*(?:ticket|issue|bug|bug\s*ticket)|"
        r"新建工作区|新建一个工作区|创建工作区|创建一个工作区|"
        r"新建\s*workspace|创建\s*workspace|创建新\s*workspace|新\s*workspace|"
        r"新建消息|新消息|创建消息|写消息|撰写消息|新建聊天|新聊天|创建聊天|新建会话|新会话|"
        r"新建邮件|新邮件|创建邮件|写邮件|写新邮件|撰写邮件|撰写新邮件|发邮件|发送邮件|"
        r"显示简介|查看简介|快速查看|快速预览|预览|重命名|上一级目录|上一级|"
        r"打开开发者工具|显示开发者工具|开发者工具|"
        r"打开当前网页开发者工具|打开当前网页的开发者工具|"
        r"(?:press|send|hit)\s+(?:the\s+)?[A-Za-z0-9 +_.-]+|"
        r"(?:scroll|page)\s+(?:down|up|to\s+(?:the\s+)?(?:bottom|top)|(?:a\s+)?(?:little|bit))|"
        r"go\s+(?:back|forward)|"
        r"copy|paste|select\s+all|undo|redo|find|refresh|reload|back|forward|new|compose|"
        r"new\s+tab|new\s+window|close\s+tab|fullscreen|maximi[sz]e|"
        r"new\s+note|new\s+reminder|new\s+event|new\s+meeting|compose(?:\s+(?:note|reminder|event|meeting))?|"
        r"new\s+project|create\s+(?:a\s+)?new\s+project|create\s+project|"
        r"new\s+(?:ticket|issue|task|card|bug|bug\s*ticket)|"
        r"create\s+(?:a\s+)?(?:new\s+)?(?:ticket|issue|task|card|bug|bug\s*ticket)|"
        r"new\s+workspace|create\s+(?:a\s+)?new\s+workspace|create\s+workspace|"
        r"new\s+message|new\s+chat|new\s+conversation|compose\s+message|compose\s+email|"
        r"new\s+email|new\s+mail|write\s+email|write\s+mail|"
        r"open\s+dev\s*tools|show\s+dev\s*tools|dev\s*tools|developer\s+tools).*)"
    )
    patterns: tuple[tuple[str, str], ...] = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            r"(?P<app>[\w .·-]{1,40}?)\s*(?P<mode>打开|启动|开启|切到|聚焦)\s*"
            r"(?:起来|到前台|前台)?\s*(?:[，,]\s*)?"
            r"(?:(?:并且|并|然后|之后|后(?!退)|再|接着)\s*)?"
            rf"{safe_followup}$",
            "",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<mode>打开|启动|开启|切到|聚焦)\s*(?P<app>[\w .·-]{1,40}?)\s*"
            r"(?:起来|到前台|前台)?\s*(?:[，,]\s*)?"
            r"(?:(?:并且|并|然后|之后|后(?!退)|再|接着)\s*)?"
            rf"{safe_followup}$",
            "",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|里面)?\s*"
            rf"{safe_followup}$",
            "focus",
        ),
        (
            rf"^{safe_followup}\s+(?:in|inside|within|on)\s+"
            r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})$",
            "focus",
        ),
        (
            r"^(?P<followup>refresh|reload)\s+"
            r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})$",
            "focus",
        ),
        (
            r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
            r"(?P<mode>open|launch|start|focus|switch\s+to|activate)\s+"
            r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?:(?:and|then)\s+)?(?P<followup>.+?)(?:\s+please)?[.!?]?$",
            "",
        ),
        (
            r"^(?P<mode>open|launch|start|focus|switch\s+to|activate)\s+"
            r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?:(?:and|then)\s+)?(?P<followup>.+)$",
            "",
        ),
        (
            rf"^(?P<app>[\w .·-]{{1,40}}?)\s*{safe_followup}$",
            "focus",
        ),
    )
    for pattern, default_mode in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_app_name = groups.get("app") or ""
        if re.search(r"(?:点击|点按|点)\s*$", raw_app_name, flags=re.IGNORECASE):
            continue
        app_name = _clean_app_name_hint(raw_app_name)
        followup = _clean_app_scoped_followup(groups.get("followup") or "")
        if not app_name or _invalid_app_scoped_followup_app(app_name) or not followup:
            continue
        return {
            "app_name": app_name,
            "mode": _command_palette_mode(groups.get("mode") or default_mode),
            "followup": followup,
        }
    return {}


def _invalid_app_scoped_followup_app(app_name: str) -> bool:
    normalized = re.sub(r"[\s._·-]+", "", str(app_name or "").strip().lower())
    if normalized.endswith(("点", "点击", "点按")):
        return True
    return normalized in {
        "",
        "你",
        "你能",
        "你能帮我",
        "帮我",
        "请",
        "麻烦",
        "可以",
        "能否",
        "能不能",
        "打",
        "开",
        "打开",
        "启动",
        "开启",
        "切到",
        "聚焦",
        "浏览器",
        "网页",
        "页面",
        "当前页",
        "当前页地址",
        "当前页链接",
        "当前页面",
        "当前页面地址",
        "当前页面链接",
        "当前网页地址",
        "当前网页链接",
        "当前链接",
        "当前网址",
        "链接",
        "网址",
        "地址",
        "标签",
        "标签页",
        "当前标签",
        "当前标签页",
        "关闭的标签",
        "关闭的标签页",
        "刚关闭的标签",
        "刚关闭的标签页",
        "在",
        "用",
        "通过",
        "把",
        "将",
        "向",
        "往",
        "朝",
        "一个",
        "一个标签",
        "一个标签页",
        "下一个",
        "下一个标签",
        "下一个标签页",
        "下一个输入框",
        "上一个",
        "上一个标签",
        "上一个标签页",
        "上一个输入框",
        "翻到",
        "滚动",
        "滑动",
        "please",
        "can",
        "canyou",
        "couldyou",
        "wouldyou",
        "browser",
        "webbrowser",
        "page",
        "currentpage",
        "currentpageaddress",
        "currentpagelink",
        "currentpageurl",
        "currenttab",
        "currenturl",
        "tab",
        "link",
        "url",
        "address",
        "closedtab",
        "lastclosedtab",
    }


def _clean_app_scoped_followup(value: str) -> str:
    return re.sub(
        r"^(?:并且|并|然后|之后|后(?!退)|再|接着|and\s+then|and|then)\s*",
        "",
        _clean_prompt(value),
        flags=re.IGNORECASE,
    ).strip()


def _app_command_palette_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    if not re.search(
        r"命令面板|指令面板|command\s+palette|(?:执行|运行|打开)\s*命令|\b(?:run|execute|open)\s+(?:the\s+)?command\b",
        value,
        flags=re.IGNORECASE,
    ):
        return {}
    palette = r"(?:命令面板|指令面板|命令\s*palette|command\s+palette)"
    verb = (
        r"(?P<verb>输入|打字|键入|敲入|打入|打上|搜索|查找|找|执行|运行|打开|启动|"
        r"type|enter|search|find|run|execute|open|launch)"
    )
    open_patterns: tuple[tuple[str, str], ...] = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|里面)?\s*"
            rf"(?:打开|调出|唤起|显示|open|show)\s*{palette}"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            "focus",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<mode>打开|启动|开启|切到|聚焦)\s*(?P<app>[\w .·-]{1,40}?)\s*"
            rf"(?:的)?(?:打开|调出|唤起|显示)?\s*{palette}"
            r"(?:一下|下)?(?:可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            "",
        ),
        (
            rf"^(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+{palette}$",
            "focus",
        ),
        (
            r"^(?P<mode>open|launch|start|focus|switch\s+to|activate)\s+"
            r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            rf"(?:(?:and|then)\s+)?(?:open|show)?\s*{palette}$",
            "",
        ),
    )
    for pattern, default_mode in open_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _canonical_app_name_hint(groups.get("app") or "")
        if not app_name:
            continue
        return {
            "app_name": app_name,
            "mode": _command_palette_mode(groups.get("mode") or default_mode),
            "action": _command_palette_action_for_app(app_name),
        }
    patterns: tuple[tuple[str, str], ...] = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|里面)?\s*"
            rf"(?:打开|调出|唤起|显示|open|show)?\s*{palette}\s*"
            r"(?:(?:并且|并|然后|之后|后(?!退)|再|and\s+then|and|then)\s*)?"
            rf"{verb}\s*(?P<command>[^。！？!?]+)$",
            "focus",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<mode>打开|启动|开启|切到|聚焦)\s*(?P<app>[\w .·-]{1,40}?)\s*"
            rf"(?:的)?(?:打开|调出|唤起|显示|open|show)?\s*{palette}\s*"
            r"(?:(?:并且|并|然后|之后|后(?!退)|再|and\s+then|and|then)\s*)?"
            rf"{verb}\s*(?P<command>[^。！？!?]+)$",
            "",
        ),
        (
            rf"^(?P<app>[A-Za-z][A-Za-z0-9 ._-]{{1,40}}?)\s+{palette}\s+"
            rf"{verb}\s+(?P<command>[^.!?]+)$",
            "focus",
        ),
        (
            r"^(?P<mode>open|launch|start|focus|switch\s+to|activate)\s+"
            r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            rf"(?:(?:and|then)\s+)?(?:open|show)?\s*{palette}\s+"
            rf"(?:(?:and|then)\s+)?{verb}\s+(?P<command>[^.!?]+)$",
            "",
        ),
    )
    for pattern, default_mode in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _canonical_app_name_hint(groups.get("app") or "")
        command_text = _clean_command_palette_text(groups.get("command") or "")
        if not app_name or not command_text:
            continue
        mode = _command_palette_mode(groups.get("mode") or default_mode)
        raw_command = str(groups.get("command") or "")
        result: dict[str, Any] = {
            "app_name": app_name,
            "mode": mode,
            "action": _command_palette_action_for_app(app_name),
            "text": command_text,
        }
        safe_key = _command_palette_safe_key_hint(raw_command)
        if safe_key:
            result["safe_key"] = safe_key
        if _command_palette_should_submit(raw_command, str(groups.get("verb") or "")):
            result["submit"] = True
        return result
    implicit_patterns: tuple[tuple[str, str], ...] = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|里面)?\s*"
            r"(?P<verb>执行|运行|打开|run|execute|open)\s*命令\s*(?P<command>[^。！？!?]+)$",
            "focus",
        ),
        (
            r"^(?:in|inside|within|using|with)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
            r"(?P<verb>run|execute|open)\s+(?:the\s+)?command\s+(?P<command>[^.!?]+)$",
            "focus",
        ),
    )
    for pattern, default_mode in implicit_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        app_name = _canonical_app_name_hint(groups.get("app") or "")
        command_text = _clean_command_palette_text(groups.get("command") or "")
        if not app_name or not command_text:
            continue
        result = {
            "app_name": app_name,
            "mode": default_mode,
            "action": _command_palette_action_for_app(app_name),
            "text": command_text,
        }
        if _command_palette_should_submit(
            str(groups.get("command") or ""),
            str(groups.get("verb") or ""),
        ):
            result["submit"] = True
        return result
    return {}


def _command_palette_mode(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"打开", "启动", "开启", "open", "launch", "start"}:
        return "open"
    return "focus"


def _command_palette_action_for_app(app_name: str) -> str:
    if compact_app_name_hint(app_name) == "obsidian":
        return "obsidian_command_palette"
    return "command_palette"


def _clean_command_palette_text(value: str) -> str:
    text = _clean_prompt(value)
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?:(?:按一下|按下|按|发送|触发)\s*)?"
        r"(?:回车|enter|return|确认|确定)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and\s+then|then|and)\s*(?:(?:press|hit|send)\s+)?(?:the\s+)?"
        r"(?:enter|return|confirm|ok)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?:(?:按一下|按下|按|发送|触发)\s*)?"
        r"(?:下箭头|向下箭头|down\s+arrow)\s*"
        r"(?:再|然后|并|and\s+then|then|and)?\s*(?:确认|确定|回车|enter|return)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s*(?:并且|并|然后|之后|随后|后(?!退)|再|接着)\s*"
        r"(?:选择|选中|打开|点击|点一下|点按|单击|点|进入|访问|执行|确认)?\s*"
        r"(?:搜索结果|结果|命令|指令|条目|项目)?(?:中|里|里的|的)?\s*"
        r"(?:第?一个|第一条|首个|第1个|第1条|1)\s*"
        r"(?:搜索结果|结果|命令|指令|条目|项目)?$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\s+(?:and\s+then|then|and)\s*"
        r"(?:select|choose|open|click|run|execute|confirm)\s+"
        r"(?:the\s+)?(?:first|1st)\s+(?:result|item|command|match)$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip(" .，,。 「」『』“”\"'`")


def _command_palette_safe_key_hint(value: str) -> dict[str, Any]:
    if re.search(r"(?:下箭头|向下箭头|down\s+arrow)", str(value or ""), flags=re.IGNORECASE):
        return {"action": "arrow_down", "repeat_count": 1}
    return {}


def _command_palette_should_submit(value: str, verb: str) -> bool:
    raw = str(value or "")
    lowered_verb = str(verb or "").strip().lower()
    if lowered_verb in {"执行", "运行", "打开", "启动", "run", "execute", "open", "launch"}:
        return True
    return bool(
        re.search(r"(?:回车|确认|确定|enter|return|confirm|ok)", raw, flags=re.IGNORECASE)
        or re.search(
            r"(?:选择|选中|打开|点击|执行|select|choose|open|click|run|execute).{0,12}"
            r"(?:第?一个|第一条|首个|第1个|第1条|1|first|1st)",
            raw,
            flags=re.IGNORECASE,
        )
    )


def _foreground_app_search_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    if not value:
        return {}
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?\s*"
        r"(?:在|用|通过)?\s*(?:(?:当前|现在|前台|这个|该)\s*){1,2}"
        r"(?:应用|app|application|窗口|界面|ui)"
        r"(?:里|中|上|内)?\s*(?:搜索|查找|检索|找)(?:一下|下)?\s*"
        r"(?P<query>.+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?\s*(?:把|将)?\s*"
        r"(?:(?:当前|现在|前台|这个|该)\s*){1,2}"
        r"(?:应用|app|application|窗口|界面|ui)"
        r"(?:里|中|上|内)?\s*(?:搜索|查找|检索|找)(?:一下|下)?\s*"
        r"(?P<query_result>.+?)\s*(?:的)?(?:搜索结果|结果|内容).*$",
        r"^(?:search|find)\s+(?P<query_en>.+?)\s+"
        r"(?:in|inside|within)\s+(?:the\s+)?(?:current|active|foreground)\s+"
        r"(?:app|application|window|ui)$",
        r"^(?:in|inside|within)\s+(?:the\s+)?(?:current|active|foreground)\s+"
        r"(?:app|application|window|ui)\s+(?:search|find)\s+(?P<query_en2>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = _clean_app_search_query(
            match.groupdict().get("query")
            or match.groupdict().get("query_result")
            or match.groupdict().get("query_en")
            or match.groupdict().get("query_en2")
            or ""
        ).strip(" .，,。?？!！")
        if not query:
            continue
        return {
            "query": query,
            "target": "搜索" if _contains_any(value, ("搜索", "查找", "检索", "找")) else "Search",
            "scope": "foreground",
        }
    return {}


def _app_search_hint(text: str, app_name: str) -> dict[str, str]:
    if _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        return {}
    field_query = ""
    app = str(app_name or "").strip()
    foreground_query = _foreground_find_query_hint(text)
    if foreground_query and not app:
        return {
            "query": foreground_query,
            "target": "搜索",
            "scope": "foreground",
        }
    if _looks_like_app_search_field_input(text):
        if _app_search_field_input_allows_safe_search(text):
            field_query = _app_search_field_input_submit_query(text)
            if not field_query and app:
                field_query = _app_search_field_input_query(text)
        if not field_query:
            return {}
    if app and _is_browser_or_search_app_name(app) and not field_query:
        return {}
    query = field_query or _app_search_query_hint(text, app)
    if not query:
        parsed = _leading_app_search_hint(text)
        parsed_app = str(parsed.get("app_name") or "").strip() if parsed else ""
        if parsed and (
            not app
            or _looks_like_app_search_followup_app(app)
            or parsed_app.lower() == app.lower()
            or compact_app_name_hint(app).startswith(compact_app_name_hint(parsed_app))
        ):
            return parsed
    if not query:
        return {}
    return {
        "query": query,
        "target": "搜索" if _contains_any(text, ("搜索", "查找", "检索", "找")) else "Search",
    }


def _looks_like_app_search_followup_app(app_name: str) -> bool:
    value = _clean_prompt(app_name)
    return bool(
        re.fullmatch(
            r"(?:第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)?",
            value,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_app_search_field_input(text: str) -> bool:
    value = _clean_prompt(text)
    lowered = value.lower()
    return bool(
        (
            _contains_any(
                lowered,
                (
                    "search field",
                    "search box",
                    "search input",
                    "search bar",
                ),
            )
            and _contains_any(lowered, ("type", "enter", "input", "write", "fill"))
        )
        or (
            re.search(r"(?:搜索框|搜索栏|搜索输入框|搜索输入栏)", value, flags=re.IGNORECASE)
            and _contains_any(value, ("输入", "键入", "填写", "填入", "写入", "写"))
        )
    )


def _app_search_field_input_allows_safe_search(text: str) -> bool:
    value = _clean_prompt(text)
    lowered = value.lower()
    return bool(
        re.search(
            r"(?:点击|点按|点一下|点|单击|选中|选择|聚焦|定位).{0,12}"
            r"(?:搜索框|搜索栏|搜索输入框|搜索输入栏)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:click|tap|focus|select)\b.{0,36}"
            r"(?:search field|search box|search input|search bar)",
            lowered,
        )
    )


def _app_search_field_input_submit_query(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"(?:搜索框|搜索栏|搜索输入框|搜索输入栏)\s*"
        r"(?:输入|键入|填写|填入|写入|写)\s*"
        r"(?P<query>[^。！？!?，,]+?)\s*"
        r"(?:并|然后|再|后|之后)?\s*(?:搜索|查找|检索|提交|确认|回车)$",
        r"(?:type|enter|fill)\s+(?P<query_en>[^.!?,]+?)\s+"
        r"(?:into|in|inside)\s+(?:the\s+)?"
        r"(?:search field|search box|search input|search bar)\s+"
        r"(?:and|then)?\s*(?:search|submit|confirm|press\s+enter|hit\s+enter)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = _clean_app_search_query(
            match.groupdict().get("query") or match.groupdict().get("query_en") or ""
        )
        if query:
            return query
    return ""


def _app_search_field_input_query(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"(?:搜索框|搜索栏|搜索输入框|搜索输入栏)\s*"
        r"(?:输入|键入|填写|填入|写入|写)\s*"
        r"(?P<query>[^。！？!?，,]+?)(?:\s*(?:并|然后|再|后|之后)?\s*(?:搜索|查找|检索|提交|确认|回车))?$",
        r"(?:type|enter|fill)\s+(?P<query_en>[^.!?,]+?)\s+"
        r"(?:into|in|inside)\s+(?:the\s+)?"
        r"(?:search field|search box|search input|search bar)"
        r"(?:\s+(?:and|then)?\s*(?:search|submit|confirm|press\s+enter|hit\s+enter))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = _clean_app_search_query(
            match.groupdict().get("query") or match.groupdict().get("query_en") or ""
        )
    if query:
        return query
    return ""


def _foreground_find_query_hint(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:查找|检索)(?!框|栏|输入|结果)\s*(?:一下|下)?\s*"
        r"(?P<query>[^。！？!?，,]+)$",
        r"^(?:find|look\s+up)\s+(?:for\s+)?(?P<query_en>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = _clean_app_search_query(
            match.groupdict().get("query") or match.groupdict().get("query_en") or ""
        )
        if query:
            return query
    return ""


def _chat_status_meta_text_hint(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    return bool(
        _contains_any(value, ("消息状态", "任务状态", "会话状态", "message status", "task status"))
        and _contains_any(value, ("取消", "已取消", "刷新", "同步", "cancel", "cancelled", "refresh", "sync"))
    )


def _leading_app_search_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    patterns = (
        r"^(?P<app>[\w .·-]{1,40}?)\s*(?:搜索|查找|检索|找)\s*(?P<query>[^。！？!?，,]+)$",
        r"^(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:search|find|look\s+up|look)\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        r"^(?:search|find|look\s+up|look)\s+(?:in|inside|within|using|with)\s+(?:the\s+)?"
        r"(?P<app_in>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:for\s+)?(?P<query_in>[^.!?,]+)$",
        r"^(?:search|find|look\s+up|look)\s+(?:the\s+)?"
        r"(?P<app_prefix>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+for\s+(?P<query_prefix>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_app = groups.get("app") or groups.get("app_in") or groups.get("app_prefix") or ""
        raw_query = groups.get("query") or groups.get("query_in") or groups.get("query_prefix") or ""
        app_name = _clean_app_name_hint(raw_app)
        if not app_name or _is_browser_or_search_app_name(app_name):
            continue
        query = _clean_app_search_query(raw_query)
        if not query or _invalid_leading_app_search_match(value, app_name, query):
            continue
        return {
            "app_name": app_name,
            "query": query,
            "target": "搜索" if _contains_any(value, ("搜索", "查找", "检索", "找")) else "Search",
        }
    return {}


def _invalid_leading_app_search_match(value: str, app_name: str, query: str) -> bool:
    lowered = value.lower()
    normalized_query = str(query or "").strip().lower()
    if re.fullmatch(r"(?:please|can\s+you|could\s+you|would\s+you)", app_name, flags=re.IGNORECASE):
        return True
    if app_name in {"查", "找", "搜", "搜索", "查找", "检索"}:
        return True
    if normalized_query in {
        "field",
        "search field",
        "box",
        "search box",
        "input",
        "search input",
        "result",
        "results",
        "search result",
        "search results",
        "框",
        "栏",
        "搜索框",
        "搜索栏",
        "输入框",
        "结果",
        "搜索结果",
    }:
        return True
    if _contains_any(
        app_name,
        ("click", "press", "tap", "type", "enter", "fill", "点击", "点按", "按", "输入", "填写"),
    ):
        return True
    return bool(
        _contains_any(lowered, ("click", "press", "tap", "type", "enter", "fill"))
        and _contains_any(
            lowered,
            ("search field", "search box", "search input", "search result", "search results"),
        )
    )


def _app_search_query_hint(text: str, app_name: str) -> str:
    value = _clean_prompt(text)
    app = str(app_name or "").strip()
    app_pattern = (
        re.escape(app)
        if app
        else r"(?:当前\s*(?:app|应用|软件)|current\s+app|foreground\s+app)"
    )
    named_scope_query = _named_app_search_query_hint(value, app)
    if named_scope_query:
        return named_scope_query
    chinese_search_verb = r"(?:搜索|查找|检索|找(?:到)?)(?!框|栏|输入|结果)"
    chinese_patterns = (
        rf"(?:在|用|通过)\s*{app_pattern}\s*(?:里|中|上|内)?\s*{chinese_search_verb}\s*(?P<query>[^。！？!?]+)$",
        rf"(?:打开|启动|切到|聚焦)\s*{app_pattern}\s*(?:[，,]\s*)?"
        rf"(?:并|然后|再|接着|之后)?\s*{chinese_search_verb}\s*(?P<query>[^。！？!?]+)$",
        rf"(?:打开|启动|切到|聚焦).{{0,30}}{app_pattern}.{{0,20}}"
        rf"{chinese_search_verb}\s*(?P<query>[^。！？!?]+)$",
    )
    for pattern in chinese_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            query = _clean_app_search_query(match.group("query"))
            if query:
                return query

    lowered = value.lower()
    english_search_verb = r"(?:search|find|look\s+up)(?!\s+(?:box|field|bar|input|result|results)\b)"
    english_patterns = (
        rf"\b(?:in|inside|within|using|with)\s+(?:the\s+)?{app_pattern}\s+{english_search_verb}\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        rf"\b(?:open|launch|focus|start)\s+(?:the\s+)?{app_pattern}\s+(?:and|then)?\s*{english_search_verb}\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        rf"\b(?:open|launch|focus|start)\b.{{0,60}}\b{app_pattern}\b.{{0,40}}\b{english_search_verb}\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        rf"\b{english_search_verb}\s+(?:for\s+)?(?P<query>[^.!?,]+?)\s+(?:in|inside|within|using|with)\s+(?:the\s+)?{app_pattern}\b",
    )
    for pattern in english_patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            query = _clean_app_search_query(match.group("query"))
            if query:
                return query
    return ""


def _named_app_search_query_hint(text: str, app_name: str) -> str:
    value = _clean_prompt(text)
    if not value:
        return ""
    chinese_patterns = (
        r"(?:在|用|通过)\s*(?:一个|一款|这个|那个)?"
        r"(?:叫|名叫|名称是|名字是)\s*(?P<app>[^。！？!?，,]+?)\s*"
        r"(?:的)?(?:应用(?:程序)?|软件)?(?:里|中|上|内)?\s*"
        r"(?:搜索|查找|检索|找(?:到)?)(?!框|栏|输入|结果)\s*(?P<query>[^。！？!?]+)$",
    )
    for pattern in chinese_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = match.groupdict().get("app") or ""
        if not _app_search_scope_matches_app(raw_app, app_name):
            continue
        query = _clean_app_search_query(match.groupdict().get("query") or "")
        if query:
            return query

    scope_first = re.search(
        r"^(?:in|inside|within|using|with)\s+"
        r"(?:(?:a|an|the)\s+)?(?:app|application|software)\s+"
        r"(?:called|named)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,80}?)\s+"
        r"(?P<tail>(?:search|find|look\s+up)\b.+)$",
        value,
        flags=re.IGNORECASE,
    )
    if scope_first and _app_search_scope_matches_app(scope_first.group("app"), app_name):
        tail_match = re.search(
            r"^(?:search|find|look\s+up)(?!\s+(?:box|field|bar|input|result|results)\b)\s+"
            r"(?:for\s+)?(?P<query>[^!?,]+)$",
            scope_first.group("tail"),
            flags=re.IGNORECASE,
        )
        if tail_match:
            query = _clean_app_search_query(tail_match.group("query"))
            if query:
                return query

    search_first_patterns = (
        r"\b(?:search|find|look\s+up)(?!\s+(?:box|field|bar|input|result|results)\b)\s+"
        r"(?:for\s+)?(?P<query_en2>[^!?,]+?)\s+"
        r"(?:in|inside|within|using|with)\s+"
        r"(?:(?:a|an|the)\s+)?(?:app|application|software)\s+"
        r"(?:called|named)\s+(?P<app_en2>[A-Za-z][A-Za-z0-9 ._-]{1,80})\b",
    )
    for pattern in search_first_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        raw_app = groups.get("app_en2") or ""
        if not _app_search_scope_matches_app(raw_app, app_name):
            continue
        query = _clean_app_search_query(
            groups.get("query_en2") or ""
        )
        if query:
            return query
    return ""


def _app_search_scope_matches_app(raw_app: str, app_name: str) -> bool:
    scoped_app = _clean_app_name_hint(raw_app)
    expected_app = str(app_name or "").strip()
    if not scoped_app:
        return False
    if not expected_app:
        return True
    compact_scoped = compact_app_name_hint(scoped_app)
    compact_expected = compact_app_name_hint(expected_app)
    if not compact_scoped or not compact_expected:
        return False
    return compact_scoped == compact_expected or compact_expected.startswith(compact_scoped)


def _clean_app_search_query(query: str) -> str:
    value = re.sub(r"^[：:，,\s]+", "", str(query or "").strip())
    value = re.sub(r"[。.,，；;！!？?]+$", "", value).strip()
    value = re.split(
        r"\s*(?:[，,]\s*|并|然后|再|接着|之后|后|and\s+then|then)\s*"
        r"(?:选择|选中|点击|点按|打开|按|"
        r"(?:把|将)?(?:当前|前台|这份|这个|这些|搜索结果|结果|内容|文本)?"
        r"(?:内容|结果|文本)?\s*(?:总结|摘要|整理|生成|输出|写成|写|做成|"
        r"读|读取|查看|看看|看一下|看下|判断|决定|分析|识别|告诉|说明|"
        r"发给|发送给|发到|发送到|转发给|转发到)|"
        r"发给|发送给|发到|发送到|转发给|转发到|"
        r"下一步|该点哪里|该点哪个|能否|能不能|可以点|是否可以|"
        r"截图|截屏|screen\s*capture|screenshot|"
        r"choose|select|click|open|press|summari[sz]e|write|generate|output|"
        r"read|inspect|check|judge|decide|determine|tell|explain|send|message|forward)(?:\b)?",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = re.sub(r"[。.,，；;！!？?]+$", "", value).strip()
    value = re.sub(r"\s+(?:please|pls)$", "", value, flags=re.IGNORECASE).strip()
    return value


def _app_search_query_context_source(app_search: Mapping[str, Any]) -> str:
    query = _clean_app_search_query(str(app_search.get("query") or ""))
    normalized = re.sub(r"[\s._-]+", "", query.lower())
    if normalized in {
        "选中内容",
        "选中的内容",
        "选中文本",
        "选中的文本",
        "选中文字",
        "选中的文字",
        "当前选中内容",
        "当前选中的内容",
        "当前选中文本",
        "当前选中文字",
        "selection",
        "selected",
        "selectedtext",
        "selectedcontent",
        "currentselection",
        "currentselectedtext",
    }:
        return "selection"
    if normalized in {
        "剪贴板",
        "剪贴板内容",
        "粘贴板",
        "粘贴板内容",
        "clipboard",
        "clipboardcontent",
        "clipboardcontents",
        "clipboardtext",
        "theclipboard",
        "systemclipboard",
    }:
        return "clipboard"
    return ""


def _app_search_safe_sequence_available(
    text: str,
    app_search: Mapping[str, Any],
    allowed: set[str] | None,
    *,
    app_name: str = "",
    mode: str = "focus",
) -> bool:
    allowed_tools = allowed
    context_source = _app_search_query_context_source(app_search)
    if context_source in {"selection", "clipboard"}:
        if _first_allowed(("desktop.safe_shortcut",), allowed_tools) is None:
            return False
    elif _first_allowed(
        _app_search_operation_candidates(
            "safe_shortcut",
            app_name=app_name,
            mode=mode,
            generic=("desktop.safe_shortcut",),
        ),
        allowed_tools,
    ) is None:
        return False
    if (
        context_source not in {"selection", "clipboard"}
        and _first_allowed(
            _app_search_operation_candidates(
                "safe_type_text",
                app_name=app_name,
                mode=mode,
                generic=("desktop.safe_type_text",),
            ),
            allowed_tools,
        )
        is None
    ):
        return False
    followup = _app_search_followup_hint(text)
    if followup.get("action") == "arrow_down_confirm":
        return (
            _first_allowed(("desktop.safe_key",), allowed_tools) is not None
            and _first_allowed(("desktop.submit_foreground",), allowed_tools) is not None
        )
    if (
        _app_search_should_submit(text, followup)
        and _first_allowed(("desktop.search_submit",), allowed_tools) is None
    ):
        return False
    if (
        followup.get("action") == "click_first_result"
        and _first_allowed(
            _app_search_operation_candidates(
                "click_ui_element",
                app_name=app_name,
                mode=mode,
                generic=("desktop.click_ui_element",),
            ),
            allowed_tools,
        )
        is None
    ):
        return False
    return True


def _app_search_operation_candidates(
    action: str,
    *,
    app_name: str,
    mode: str,
    generic: tuple[str, ...],
) -> tuple[str, ...]:
    if not str(app_name or "").strip():
        return generic
    return (*generic, *app_foreground_tool_candidates(mode, action))


def _safe_type_text_operation_candidates(app_name: str, mode: str) -> tuple[str, ...]:
    return _app_search_operation_candidates(
        "safe_type_text",
        app_name=app_name,
        mode=mode,
        generic=("desktop.safe_type_text",),
    )


def _safe_type_text_operation_preview(
    *,
    app_name: str,
    mode: str,
    allowed: set[str] | None,
    payload: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    tool_name = _first_allowed(
        _safe_type_text_operation_candidates(app_name, mode),
        allowed,
    )
    input_preview = dict(payload)
    if str(tool_name or "").startswith("app."):
        input_preview = {"app_name": app_name, **input_preview}
    return tool_name, input_preview


def _type_into_ui_element_tool_available(
    app_name: str,
    mode: str,
    allowed: set[str] | None,
) -> bool:
    if allowed is None:
        return True
    candidates = ["desktop.type_into_ui_element"]
    if str(app_name or "").strip():
        candidates = [
            *app_foreground_tool_candidates(mode, "type_into_ui_element"),
            *candidates,
        ]
    return any(tool in allowed for tool in candidates)


def _app_search_from_type_target(
    type_target: Mapping[str, Any],
    text: str,
) -> dict[str, str]:
    query = _clean_app_search_query(str(type_target.get("text") or ""))
    target_value = str(type_target.get("target") or "").strip()
    return {
        "query": query,
        "target": "搜索" if _contains_any(target_value or text, ("搜索", "查找", "检索", "找")) else "Search",
    }


def _app_search_should_submit(text: str, search_followup: Mapping[str, Any]) -> bool:
    if _foreground_find_query_hint(text):
        return False
    if search_followup:
        return True
    value = _clean_prompt(text)
    lowered = value.lower()
    return bool(
        re.search(r"(?:搜索|查找|检索)(?!框|栏|输入|结果)", value)
        or re.search(r"\b(?:search|find|look\s+up|look)\b", lowered)
        or (
            not _contains_any(value, ("打开", "启动", "开启", "open ", "launch ", "start "))
            and re.search(r"^[\w .·-]{1,40}?\s*找\s*\S+", value)
        )
        or re.search(r"(?:并|然后|再|后|之后)?\s*(?:搜索|查找|检索|提交|确认|回车)$", value)
        or re.search(
            r"\b(?:and|then)?\s*(?:search|submit|confirm|press\s+enter|hit\s+enter)$",
            lowered,
        )
    )


def _app_search_followup_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    lowered = value.lower()
    if re.search(
        r"(?:按|press).{0,8}(?:下箭头|向下箭头|down\s+arrow).{0,16}(?:确认|回车|enter|return|confirm)",
        value,
        flags=re.IGNORECASE,
    ):
        return {"action": "arrow_down_confirm"}
    if re.search(
        r"(?:选择|选中|点击|点按|打开).{0,8}(?:第一个|首个|第1个).{0,8}(?:结果|项)?",
        value,
        flags=re.IGNORECASE,
    ):
        click_count = 2 if _contains_any(value, ("打开", "open")) else 1
        return {"action": "click_first_result", "target": "第一个结果", "click_count": click_count}
    if re.search(
        r"\b(?:choose|select|click|open)\s+(?:the\s+)?first\s+(?:result|item)\b",
        lowered,
    ):
        click_count = 2 if re.search(r"\bopen\b", lowered) else 1
        return {"action": "click_first_result", "target": "first result", "click_count": click_count}
    return {}


def _spotlight_search_query_hint(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"^(?:Spotlight|spotlight|聚焦搜索|系统搜索)\s*(?:搜索|查找|检索)?\s*(?P<query>[^。！？!?，,]+)$",
        r"\b(?:open|launch|start|show)\s+(?:spotlight|system\s+search)\s+(?:and\s+)?(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        r"\b(?:use\s+)?(?:spotlight|system\s+search)\s+(?:to\s+)?(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = _clean_app_search_query(match.group("query"))
        if query and query.lower() not in {"search", "spotlight", "spotlight search"}:
            return query
    return ""


def _spotlight_open_hint(text: str) -> bool:
    value = _clean_prompt(text)
    if _spotlight_search_query_hint(value):
        return False
    return bool(
        re.fullmatch(r"(?:打开|启动|显示|呼出|唤起)\s*(?:Spotlight|spotlight|聚焦搜索|系统搜索)", value)
        or re.fullmatch(r"(?:open|launch|start|show)\s+(?:spotlight|system\s+search)", value, flags=re.IGNORECASE)
    )


def _dynamic_context_browser_action_hint(text: str, context_source: str) -> dict[str, Any]:
    if context_source not in {"selection", "clipboard"}:
        return {}
    value = _clean_prompt(text)
    lowered = value.lower()
    if _looks_like_browser_current_page_find(value, lowered):
        return {}
    app_name = _dynamic_context_browser_app_name_hint(value)
    app_payload = {"app_name": app_name} if app_name else {}
    if _looks_like_dynamic_context_url_open(value, lowered):
        return {"browser_action": "open_url", **app_payload}
    if _looks_like_dynamic_context_web_search(value, lowered):
        return {"browser_action": "open_search", **app_payload}
    return {}


def _desktop_window_text_context_hint(text: str) -> bool:
    value = _clean_prompt(text)
    if not value:
        return False
    if re.search(r"(?:网页|页面|浏览器|标签页)", value, flags=re.IGNORECASE):
        return False
    if re.search(r"\b(?:browser|web\s*page|webpage|page|tab)\b", value, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:读取|查看|看看|看下|读|提取|识别|列出).{0,8}"
            r"(?:当前|现在|这个|前台)?窗口.{0,6}(?:内容|文本|文字)?",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|extract|show|list|inspect)\s+"
            r"(?:the\s+)?(?:current|active|foreground|this)\s+window\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _dynamic_context_browser_app_name_hint(text: str) -> str:
    app_name = _app_name_hint(text)
    if (
        app_name
        and _is_browser_or_search_app_name(app_name)
        and not _is_generic_browser_app_label(app_name)
    ):
        return app_name
    return ""


def _looks_like_dynamic_context_url_open(value: str, lowered: str) -> bool:
    if not _contains_any(value, ("open", "visit", "go to", "browse", "打开", "访问", "浏览器")):
        return False
    return bool(
        _contains_any(
            value,
            (
                "selected link",
                "selected url",
                "current selection link",
                "current selection url",
                "clipboard link",
                "clipboard url",
                "link in clipboard",
                "url in clipboard",
                "选中链接",
                "选中网址",
                "选中的链接",
                "选中的网址",
                "剪贴板链接",
                "剪贴板网址",
                "剪贴板里的链接",
                "剪贴板里的网址",
                "链接",
                "网址",
            ),
        )
        or re.search(
            r"\bopen\s+(?:the\s+)?(?:selected|highlighted|clipboard|current\s+selection)"
            r"(?:\s+(?:link|url|contents?))?\b",
            lowered,
        )
    )


def _looks_like_dynamic_context_web_search(value: str, lowered: str) -> bool:
    return bool(
        (
            _contains_any(value, ("search", "google", "查找", "搜索", "检索"))
            and _contains_any(
                value,
                (
                    "selected",
                    "selection",
                    "highlighted",
                    "clipboard",
                    "选中",
                    "选取",
                    "高亮",
                    "剪贴板",
                    "粘贴板",
                ),
            )
        )
        or re.search(
            r"\b(?:search|google|look\s+up)\s+(?:the\s+)?"
            r"(?:selected|highlighted|clipboard|current\s+selection)",
            lowered,
        )
    )


def _explicit_browser_url_hint(text: str) -> str:
    value = _clean_prompt(text)
    match = re.search(r"https?://[^\s)）]+", value, flags=re.IGNORECASE)
    if match:
        return _clean_browser_url(match.group(0))

    host_match = re.search(
        r"\b(?:localhost|(?:\d{1,3}\.){3}\d{1,3})(?::\d{1,5})?(?:/[^\s，,。)）]*)?",
        value,
        flags=re.IGNORECASE,
    )
    if host_match:
        return _with_browser_url_scheme(_clean_browser_url(host_match.group(0)))

    domain_match = re.search(
        r"(?<!@)\b(?:[a-z0-9-]+\.)+[a-z]{2,24}(?::\d{1,5})?(?:/[^\s，,。)）]*)?",
        value,
        flags=re.IGNORECASE,
    )
    if not domain_match:
        return _known_web_destination_request_url_hint(value)
    candidate = _clean_browser_url(domain_match.group(0))
    if not _browser_url_context_allows_domain(value, candidate):
        return ""
    return _with_browser_url_scheme(candidate)


def _known_web_destination_request_url_hint(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:把|将)?\s*"
        r"(?P<site>[\w .·-]{1,60}?)\s*"
        r"(?:打开|访问|浏览|前往|去|上)(?:一下|下|起来|看看)?$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)?\s*(?:任意|任何|默认|当前)?"
        r"(?:浏览器|chrome|google\s*chrome|google|谷歌|safari)?(?:里|中|上|内)?\s*"
        r"(?:打开|访问|浏览|前往|去|上)\s*"
        r"(?P<site>[\w .·-]{1,60}?)\s*"
        r"(?:看看|看一下|看下|读一下|读取|提取|概括|总结|摘要|内容).*$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)?\s*(?:任意|任何|默认|当前)?"
        r"(?:浏览器|chrome|google\s*chrome|google|谷歌|safari)?(?:里|中|上|内)?\s*"
        r"(?:打开|访问|浏览|前往|去|上)\s*"
        r"(?P<site>[\w .·-]{1,60}?)(?:\s*(?:并|然后|再|接着|之后|后).*)?$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:open|visit|browse|go\s+to)\s+(?:the\s+)?"
        r"(?P<site>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)(?:\s+(?:and|then).*)?$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:summari[sz]e|read|extract|screenshot)\s+(?:the\s+)?"
        r"(?P<site>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)(?:\s+after\s+opening\s+it)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        site = _clean_web_destination_site_hint(match.group("site"))
        url = legacy_known_web_destination_url_hint(f"打开 {site}")
        if url:
            return url
    return legacy_known_web_destination_url_hint(value)


def _clean_browser_url(url: str) -> str:
    return str(url or "").strip().rstrip("。.,，；;！!？?)）")


def _with_browser_url_scheme(url: str) -> str:
    if not url:
        return ""
    if re.match(r"^https?://", url, flags=re.IGNORECASE):
        return url
    return f"http://{url}" if _looks_like_localhost_url(url) else f"https://{url}"


def _looks_like_localhost_url(url: str) -> bool:
    return bool(
        re.match(
            r"^(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|(?:\d{1,3}\.){3}\d{1,3})(?::|/|$)",
            url,
            flags=re.IGNORECASE,
        )
    )


def _browser_url_context_allows_domain(text: str, candidate: str) -> bool:
    if not candidate or _looks_like_local_file_name(candidate):
        return False
    return _contains_any(
        text,
        (
            "open",
            "visit",
            "go to",
            "browse",
            "summarize",
            "summary",
            "read",
            "research",
            "screenshot",
            "打开",
            "访问",
            "上",
            "地址栏",
            "网页",
            "网址",
            "链接",
            "浏览器",
            "总结",
            "概括",
            "读取",
            "读一下",
            "调研",
            "截图",
            "截屏",
        ),
    )


def _looks_like_local_file_name(candidate: str) -> bool:
    path = candidate.split("/", 1)[0]
    host = path.split(":", 1)[0].lower()
    suffix = host.rsplit(".", 1)[-1] if "." in host else ""
    return suffix in {
        "csv",
        "tsv",
        "xlsx",
        "xls",
        "json",
        "jsonl",
        "txt",
        "md",
        "py",
        "js",
        "ts",
        "tsx",
        "jsx",
        "toml",
        "yaml",
        "yml",
    }


def _looks_like_url_screenshot_request(text: str) -> bool:
    return _contains_any(
        text,
        ("screenshot", "screen capture", "截图", "截屏"),
    )


def _looks_like_direct_url_text_request(text: str) -> bool:
    if _contains_any(text, ("research", "report", "调研", "报告")):
        return False
    return _contains_any(
        text,
        (
            "summarize",
            "summary",
            "read",
            "extract",
            "content",
            "总结",
            "概括",
            "摘要",
            "读取",
            "读一下",
            "提取",
            "内容",
            "看看",
        ),
    )


def _looks_like_url_summary_request(text: str) -> bool:
    return _contains_any(
        text,
        ("summarize", "summary", "总结", "概括", "摘要"),
    )


def _looks_like_plain_url_open(text: str) -> bool:
    if _contains_any(
        text,
        (
            "summarize",
            "summary",
            "read",
            "extract",
            "research",
            "report",
            "总结",
            "概括",
            "摘要",
            "读取",
            "读一下",
            "提取",
            "调研",
            "报告",
            "内容",
        ),
    ):
        return False
    return _contains_any(
        text,
        (
            "open",
            "visit",
            "go to",
            "browse",
            "打开",
            "访问",
            "上",
            "地址栏",
            "网页",
            "网址",
            "链接",
            "浏览器",
        ),
    )


def _web_search_hint(text: str, context_source: str) -> dict[str, Any]:
    if context_source in {"selection", "clipboard"}:
        return {}
    value = _clean_prompt(text)
    destination_search = _known_web_destination_search_hint(value)
    if destination_search:
        hint: dict[str, Any] = {
            "browser_action": "open_search",
            "query": destination_search["query"],
            "url_hint": destination_search["url_hint"],
            "destination": destination_search["destination"],
        }
        followup = _web_search_followup_hint(value)
        if followup:
            hint.update(followup)
            hint.update(_web_search_post_followup_hint(value))
        else:
            hint.update(_web_search_results_output_hint(value))
        return hint
    query = _web_search_query(value)
    if not query:
        return {}
    engine = _web_search_engine_hint(value)
    hint: dict[str, Any] = {
        "browser_action": "open_search",
        "query": query,
        "url_hint": _web_search_url(engine, query),
    }
    followup = _web_search_followup_hint(value)
    if followup:
        hint.update(followup)
        hint.update(_web_search_post_followup_hint(value))
    else:
        hint.update(_web_search_results_output_hint(value))
    return hint


def _web_search_post_followup_hint(text: str) -> dict[str, Any]:
    output_hint = _web_search_results_output_hint(text)
    browser_action = str(output_hint.get("browser_action") or "").strip()
    if browser_action == "open_url_extract":
        hint: dict[str, Any] = {"post_followup_action": "extract_text"}
        presentation = str(output_hint.get("presentation") or "").strip()
        if presentation:
            hint["presentation"] = presentation
        return hint
    return {}


def _web_search_results_output_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    if _looks_like_url_screenshot_request(value):
        return {
            "browser_action": "open_url_screenshot",
            "reason": "user asked to capture the browser page after opening a URL",
        }
    if re.search(
        r"(?:并|然后|并且|再|接着|之后|后).{0,4}"
        r"(?:读|读取|看看|看一下|看下|概括|总结|摘要).{0,8}(?:结果|内容|搜索结果)$",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"(?:并|然后|并且|再|接着|之后|后).{0,4}"
        r"(?:读|读取|看看|看一下|看下|概括|总结|摘要).{0,8}"
        r"(?:当前|这个|该)?(?:网页|页面|页|current\s+page)$",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:and|then)\s+(?:read|extract|summari[sz]e)\s+results?\b",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:and|then)\s+(?:read|extract|summari[sz]e)\s+(?:the\s+)?(?:current\s+)?page\b",
        value,
        flags=re.IGNORECASE,
    ):
        hint: dict[str, Any] = {"browser_action": "open_url_extract"}
        if _looks_like_url_summary_request(value):
            hint["presentation"] = "summary"
        return hint
    if _browser_search_deliverable_extract_requested(value):
        return {"browser_action": "open_url_extract"}
    return {}


def _browser_search_deliverable_extract_requested(text: str) -> bool:
    surface = _web_search_surface_hint(text)
    if not _desktop_content_artifact_requested(text):
        return False
    if not surface:
        return _plain_web_search_deliverable_extract_requested(text)
    return bool(
        _is_browser_or_search_app_name(surface)
        and not _is_generic_browser_app_label(surface)
    )


def _plain_web_search_deliverable_extract_requested(text: str) -> bool:
    value = _clean_prompt(text)
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:搜索|查找|查询|检索|找一下|找下|查一下|查查|查(?!看))\s*",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:打开|启动|开启|新建|开)?\s*(?:一个|个)?\s*"
            r"(?:Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave|浏览器)"
            r"(?:里|中|上|内)?\s*(?:搜索|查找|检索)\s*",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
            r"(?:search|look\s+up|find\s+out\s+about)\s+",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:研究|调研|查研究|做(?:一份)?(?:调研|研究)|写(?:一份)?(?:关于)?.*?(?:分析|报告))",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
            r"(?:research|investigate|write\s+(?:a\s+)?(?:research\s+)?report|"
            r"write\s+(?:a\s+)?competitive\s+analysis)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _web_search_query(text: str) -> str:
    if _url_hint(text):
        return ""
    direct_engine_query = _direct_web_search_query(text)
    if direct_engine_query:
        return direct_engine_query
    if _looks_like_local_observation_or_control_request(text):
        return ""
    if (
        (data_source_hint(text) or data_source_scope_hint(text) or context_source_hint(text))
        and not _looks_like_external_info_lookup(text)
    ):
        return ""
    search_surface = _web_search_surface_hint(text)
    if search_surface and not _is_browser_or_search_app_name(search_surface):
        return ""
    app_name = _app_name_hint(text)
    explicit_browser_app = _explicit_browser_app_name_hint(text)
    if (
        app_name
        and not search_surface
        and not explicit_browser_app
        and not _is_browser_or_search_app_name(app_name)
    ):
        return ""
    research_report_query = _external_research_report_query(text)
    if research_report_query:
        return research_report_query
    lowered = text.lower()
    patterns = (
        r"\b(?:can\s+you\s+)?(?:research|look\s+up|find\s+out\s+about)\s+(.+)$",
        r"\b(?:can\s+you\s+)?search\s+(?:google\s+chrome|chrome|safari|browser|web|google)\s+for\s+(.+)$",
        r"\b(?:can\s+you\s+)?search\s+for\s+(.+)$",
        r"\b(?:google|search)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            query = _clean_web_search_query(match.group(1))
            if query:
                return query

    chinese_patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:研究|调研|了解|查找|查询|检索|搜索|找一下|找下|查一下|查查|查(?!看)|看一下|看看)"
        r"(?:一下|下|查)?\s*(.+)$",
        r"(?:在|用|通过)?\s*(?:任意|任何|默认|当前)?(?:浏览器|Google|谷歌)\s*(?:搜索|查找)\s*(.+)$",
        r"(?:搜索|查找|检索)\s*(.+)$",
    )
    for pattern in chinese_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            query = _clean_web_search_query(match.group(1))
            if query:
                return query
    return ""


def _external_research_report_query(text: str) -> str:
    value = _clean_prompt(text)
    if not value:
        return ""
    chinese_patterns = (
        r"(?:写|生成|输出|整理|做|制作)\s*(?:一份|一个|篇)?\s*"
        r"(?:关于|有关)\s*(?P<query>.+?)\s*(?:的)?"
        r"(?:竞品分析|竞品|竞争分析|产品分析|产品能力|调研|研究|分析)?"
        r"(?:报告|简报|文档)$",
        r"(?:关于|有关)\s*(?P<query>.+?)\s*(?:的)?"
        r"(?:竞品分析|竞品|竞争分析|产品分析|产品能力|调研|研究|分析)"
        r"(?:报告|简报|文档)$",
    )
    for pattern in chinese_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            query = _clean_web_search_query(match.group("query"))
            if query:
                return query
    english_patterns = (
        r"\b(?:write|create|generate|produce)\s+(?:a\s+)?"
        r"(?:competitive|competitor|market|research|analysis)[\w\s-]{0,30}?"
        r"report\s+(?:about|on)\s+(?P<query>.+)$",
        r"\b(?:about|on)\s+(?P<query>.+?)\s+"
        r"(?:competitive|competitor|market|research|analysis)[\w\s-]{0,30}?report$",
    )
    for pattern in english_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            query = _clean_web_search_query(match.group("query"))
            if query:
                return query
    return ""


def _direct_web_search_query(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"search\s+(?:google|baidu|chrome|google\s+chrome|browser|safari)\s+"
        r"for\s+(?P<query>[^.!?,。！？]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:百度|baidu)\s*(?:搜索|搜一下|搜|查一下|查查|检索|一下)?\s*(?P<query>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:google|谷歌)\s*(?:搜索|搜一下|搜|查一下|查查|检索|一下)?\s*(?P<query>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|新建|开)\s*(?:一个|个)?\s*(?:新标签页?|新标签|new\s+tab)\s*"
        r"(?:并|然后|再)?\s*(?:搜索|查找|检索)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?:在|用|通过|打开|启动|开启)\s*)?"
        r"(?:Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave|浏览器)"
        r"(?:里|中|上|内)?\s*"
        r"(?:打开|访问|浏览|搜索|查找|检索)\s*"
        r"(?!新标签页?|新标签|new\s+tab)(?P<query>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)?\s*"
        r"(?:Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave|浏览器)"
        r"(?:里|中|上|内)?\s*"
        r"(?:(?:打开|启动|开启|新建|开)\s*(?:一个|个)?\s*"
        r"(?:新标签页?|新标签|new\s+tab)?\s*)?"
        r"(?:并|然后|再)?\s*(?:搜索|查找|检索)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:搜索|查找|查询|检索|找一下|找下|查一下|查查|查(?!看))\s*"
        r"(?P<query>[^。！？!?]+)$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"search\s+"
        r"(?P<query>[^.!?]+)$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:(?:open|launch|start|in|with|using)\s+)?"
        r"(?:google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave|browser)\s+"
        r"(?:and\s+)?(?:open|visit|browse|search|find|look\s+up)\s+(?:for\s+)?"
        r"(?P<query>[^.!?]+)$",
        r"\b(?:google|baidu)\s+(?P<query>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = _clean_web_search_query(match.group("query"))
        if (
            query
            and not _looks_like_local_search_query(query)
            and not _looks_like_non_browser_search_surface(value)
        ):
            return query
    return ""


def _looks_like_local_search_query(query: str) -> bool:
    return bool(
        context_source_hint(query)
        or data_source_hint(query)
        or data_source_scope_hint(query)
    )


def _looks_like_non_browser_search_surface(text: str) -> bool:
    surface = _web_search_surface_hint(text)
    return bool(surface and not _is_browser_or_search_app_name(surface))


def _web_search_engine_hint(text: str) -> str:
    return "baidu" if re.search(r"(?:百度|baidu)", text, flags=re.IGNORECASE) else "google"


def _web_search_followup_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    match = re.search(
        r"(?:并|然后|再|接着|之后|后)?\s*"
        r"(?:打开|点击|点一下|点按|进入|访问|选择|选中)\s*"
        r"(?P<rank>第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"(?:并|然后|再|接着|之后|后)\s*(?:播放|打开播放|点开播放)\s*$",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:and|then)\s+(?:play|open\s+and\s+play)\b",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:and|then)\s+(?:open|click|visit|select|choose)\s+(?:the\s+)?"
        r"(?P<rank_en>first|1st)\s+(?:search\s+)?(?:result|link|item)\b",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return {}
    rank = match.groupdict().get("rank") or match.groupdict().get("rank_en") or "first"
    index = _browser_search_result_rank_index(rank)
    if not index:
        return {}
    return {
        "followup_action": "click_search_result",
        "selector": f"search-result={index}",
        "click_count": 1,
    }


def _web_search_url(engine: str, query: str) -> str:
    if str(engine or "").strip().lower() == "baidu":
        return f"https://www.baidu.com/s?wd={quote_plus(query)}"
    return f"https://www.google.com/search?q={quote_plus(query)}"


def _known_web_destination_search_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)?\s*(?:任意|任何|默认|当前)?"
        r"(?:浏览器|chrome|google\s*chrome|google|谷歌|safari)?"
        r"(?:里|中|上|内)?\s*(?:打开|访问|浏览|前往|去|上)?\s*"
        r"(?P<site>[\w .·-]{1,60}?)(?:里|中|上|内)?\s*"
        r"(?:搜索|搜一下|搜|查找|检索|找)\s*(?P<query>[^。！？!?]+)$",
        r"^(?P<site>[\w .·-]{1,60}?)(?:里|中|上|内)?\s*"
        r"(?:搜索|搜一下|搜|查找|检索|找)\s*(?P<query>[^。！？!?]+)$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:(?:use|using|in|on|with)\s+(?:the\s+)?"
        r"(?:browser|chrome|google\s+chrome|google|safari)\s+(?:to\s+)?)?"
        r"(?:open|visit|browse|go\s+to)\s+(?:the\s+)?"
        r"(?P<site>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)\s+"
        r"(?:and\s+|then\s+)?(?:search|find|look\s+up)\s+(?:for\s+)?"
        r"(?P<query>[^.!?,]+)$",
        r"^(?:(?:please|can\s+you|could\s+you|would\s+you)\s+)?"
        r"(?:search|find|look\s+up)\s+(?:the\s+)?"
        r"(?P<site>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)\s+for\s+"
        r"(?P<query>[^.!?,]+)$",
        r"^(?P<site>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)\s+"
        r"(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        destination = _clean_web_destination_site_hint(match.group("site"))
        query = _clean_web_search_query(match.group("query"))
        url = legacy_known_web_destination_search_url(destination, query)
        if url:
            return {
                "destination": destination,
                "query": query,
                "url_hint": url,
            }
    return {}


def _clean_web_destination_site_hint(site_name: str) -> str:
    value = str(site_name or "").strip(" .，,。")
    value = re.sub(
        r"^(?:打开|访问|浏览|前往|去|上|open|visit|browse|go\s+to)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    value = re.sub(r"^(?:the\s+)?", "", value, flags=re.IGNORECASE).strip(" .，,。")
    return value


def _web_search_surface_hint(text: str) -> str:
    patterns = (
        r"\b(?:can\s+you\s+)?search\s+(?P<surface>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+for\s+.+$",
        r"^(?P<surface>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s*(?:搜索|查找|检索)\s*.+$",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:在|用|通过)\s*"
        r"(?P<surface>[\w .·-]{1,40}?)\s*(?:里|中|上|内)?\s*"
        r"(?:搜索|查找|检索)\s*.+$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_web_search_surface_hint(str(match.group("surface") or ""))
    return ""


def _clean_web_search_surface_hint(surface: str) -> str:
    value = _clean_prompt(surface)
    if not value:
        return ""
    value = re.split(
        r"\s*(?:打开|启动|开启|新建|开|"
        r"\b(?:open|launch|start|new\s+tab)\b)\s*",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .，,。")
    value = _clean_app_name_hint(value)
    if not value:
        return ""
    if _is_generic_browser_app_label(value):
        return value
    if _is_browser_or_search_app_name(value):
        return value
    return legacy_app_name_hint(value)


def _is_browser_or_search_app_name(app_name: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(app_name or "").strip().lower())
    return normalized in {
        "browser",
        "any browser",
        "default browser",
        "chrome",
        "google chrome",
        "safari",
        "firefox",
        "edge",
        "microsoft edge",
        "brave",
        "google",
        "谷歌",
        "浏览器",
        "任意浏览器",
        "任何浏览器",
        "默认浏览器",
        "网页",
        "页面",
        "当前网页",
        "当前页面",
        "current page",
        "current webpage",
        "web page",
        "spotlight",
    }


def _looks_like_media_search_play_request(text: str) -> bool:
    hint = media_playback_hint(text)
    return bool(
        str(hint.get("action") or "").strip() == "play"
        and str(hint.get("query") or "").strip()
        and (
            str(hint.get("app_name") or "").strip()
            or _contains_any(text, ("apple music", "spotify", "网易云", "qq music", "QQ 音乐"))
        )
    )


def _looks_like_generic_media_playback_request(text: str) -> bool:
    hint = media_playback_hint(text)
    return bool(
        str(hint.get("action") or "").strip() == "play"
        and not str(hint.get("query") or "").strip()
        and _contains_any(text, ("music", "song", "songs", "音乐", "歌曲", "歌"))
    )


def _looks_like_generic_media_control_request(text: str) -> bool:
    hint = media_playback_hint(text)
    action = str(hint.get("action") or "").strip()
    if str(hint.get("control_only") or "").strip().lower() == "true":
        return True
    if action not in {"pause", "next", "previous", "status"}:
        return False
    return bool(
        not str(hint.get("app_name") or "").strip()
        and _contains_any(text, ("music", "song", "songs", "音乐", "歌曲"))
    )


def _clean_web_search_query(query: str) -> str:
    value = re.sub(r"^[：:，,\s]+", "", str(query or "").strip())
    value = re.sub(
        r"^(?:网页|网上|网络|web)\s*(?:上|里|中|内)?\s*"
        r"(?:研究|调研|了解|查找|查询|检索|搜索)(?:一下|下)?\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s+(?:and|then)\s+(?:write|create|generate|produce|make|format|organize|summari[sz]e).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s+(?:and|then)\s+(?:send|message|forward).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s+(?:and|then)\s+(?:open|click|visit|select|choose)\s+(?:the\s+)?"
        r"(?:first|1st)\s+(?:search\s+)?(?:result|link|item).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s+(?:and|then)\s+(?:play|open\s+and\s+play).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s*(?:并|然后|并且|再|接着|之后|后)?\s*"
        r"(?:打开|点击|点一下|点按|进入|访问|选择|选中)\s*"
        r"(?:第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s*(?:并|然后|并且|再|接着|之后|后)\s*(?:播放|打开播放|点开播放).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s*(?:并|然后|并且|再|接着|之后|后|\b(?:and|then)\b)?\s*"
        r"(?:截图|截屏|screen\s*capture|screenshot)(?:\s+results?)?$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s*(?:并|然后|并且|再|接着|之后|后|\b(?:and|then)\b)?\s*"
        r"(?:读|读取|看看|看一下|看下|概括|总结|摘要|做总结|做摘要)(?:一下|下)?"
        r"(?:搜索)?(?:结果|内容|当前页面|当前网页|网页|页面|current\s+page)?$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"(?:[，,]\s*|并|然后|并且|再)(?:输出|生成|写|写出|整理|总结|做总结|汇总)(?:一份|一下|成)?"
        r"[^。；;！!？?]{0,24}(?:报告|总结|文档|结果|表格|清单|table)$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"(?:并|然后|并且|再|接着|之后|后)?\s*"
        r"(?:把|将)?(?:报告|总结|摘要|结果|内容|表格|清单|文档)?"
        r"\s*(?:发给|发送给|发到|发送到|转发给|转发到).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(r"[。.,，；;！!？?]+$", "", value).strip()
    value = re.sub(
        r"(?:[，,]\s*|并|然后|并且|再)(?:输出|生成|写|写出|整理|总结|汇总)(?:一份|一下|成)?"
        r"[^。；;！!？?]{0,24}(?:报告|总结|文档|结果|表格|清单|table)$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"(?:并|然后|并且|再)?(?:输出|生成|写|写出|整理|总结|汇总)(?:一份|一下|成)?"
        r"(?:报告|总结|文档|结果|表格|清单|table)?$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"\s+(?:in|on|with)\s+(?:chrome|google\s+chrome|safari|browser)$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(r"[。.,，；;！!？?]+$", "", value).strip()
    value = re.sub(r"\s+(?:please|pls)$", "", value, flags=re.IGNORECASE).strip()
    if not value:
        return ""
    if value.casefold() in {
        "一下",
        "下",
        "查",
        "找",
        "搜索",
        "查找",
        "查询",
        "current page",
        "this page",
        "current webpage",
        "this webpage",
        "当前网页",
        "当前页面",
        "当前页",
        "这个网页",
        "这个页面",
    }:
        return ""
    if _contains_any(
        value,
        (
            "selected text",
            "current selection",
            "剪贴板内容",
            "选中的内容",
            "当前选中文字",
        ),
    ):
        return ""
    return value


def _browser_click_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    rank_match = re.search(
        r"(?:点击|点一下|点按|单击|打开|进入|访问)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?P<rank>第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目)$",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:click|open|visit|press)\s+(?:the\s+)?"
        r"(?P<rank_en>first|1st)\s+"
        r"(?:search\s+)?(?:result|link)\b",
        value,
        flags=re.IGNORECASE,
    )
    if rank_match and _has_browser_page_context(value):
        rank = rank_match.groupdict().get("rank") or rank_match.groupdict().get("rank_en") or ""
        index = _browser_search_result_rank_index(rank)
        if index:
            return {
                "browser_action": "click",
                "selector": f"search-result={index}",
                "click_count": 1,
            }
    if _looks_like_browser_app_field_typing(value):
        return {}
    if not _has_browser_page_context(value):
        return {}
    point = _browser_click_point(value)
    if point:
        return {
            "browser_action": "click",
            "selector": f"point={point['x']},{point['y']}",
            "fallback_x": point["x"],
            "fallback_y": point["y"],
            "click_count": point["click_count"],
        }
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)?\s*"
        r"(?:google\s*chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave|浏览器|谷歌)"
        r"(?:里|中|上|内|上面)?\s*"
        r"(?:点击|点一下|点按|单击|点)\s*"
        r"(?P<label>[^。！？!?，,]+?)\s*(?:按钮|链接|元素)?$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:点击|点一下|点按|单击|点)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?P<label>[^。！？!?，,]+?)\s*(?:按钮|链接|元素)?$",
        r"\b(?:click|press)\s+(?:the\s+)?(?P<label>[^.!?]+?)"
        r"(?:\s+(?:button|link|element))?"
        r"(?:\s+(?:on|in)\s+(?:the\s+)?(?:current\s+)?(?:page|browser))?$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        label = _clean_browser_element_label(match.group("label"))
        if not label or _looks_like_click_coordinate_label(label):
            continue
        return {
            "browser_action": "click",
            "selector": _browser_selector_from_label(label),
            "click_count": 1,
        }
    return {}


def _looks_like_browser_app_field_typing(text: str) -> bool:
    return bool(
        _explicit_browser_app_name_hint(text)
        and re.search(
            r"(?:搜索框|搜索栏|地址栏|search\s+(?:box|field|bar)|address\s+bar|url\s+bar).{0,20}"
            r"(?:输入|键入|填写|填入|搜索|type|enter|fill|search)",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )


def _browser_click_point(text: str) -> dict[str, Any]:
    patterns = (
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double>双击|double\s+click)|点击|点一下|点按|单击|click)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)(?:上|里|中|内|的|上的)?\s*"
        r"(?:坐标|位置|coordinate|point)?\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:(?P<double2>双击|double\s+click)|点击|点一下|点按|单击|click)\s*"
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?:坐标|位置|coordinate|point)\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
        r"(?:当前)?(?:网页|页面|浏览器|当前页)?(?:上|里|中|内|的|上的)?\s*"
        r"(?:坐标|位置|coordinate|point)\s*"
        r"(?P<x>\d+(?:\.\d+)?)\s*(?:,|，|\s)\s*(?P<y>\d+(?:\.\d+)?)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        groups = match.groupdict()
        return {
            "x": _number_value(match.group("x")),
            "y": _number_value(match.group("y")),
            "click_count": 2 if groups.get("double") or groups.get("double2") else 1,
        }
    return {}


def _browser_search_result_rank_index(value: str) -> int:
    compact = re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
    if compact in {"第一个", "第一条", "首个", "第1个", "第1条", "1", "first", "1st"}:
        return 1
    return 0


def _browser_selector_from_label(label: str) -> str:
    clean = str(label or "").strip()
    if _looks_like_css_selector(clean):
        return clean
    return f"text={clean}"


def _looks_like_click_coordinate_label(value: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?\s*(?:,|，|\s)\s*\d+(?:\.\d+)?", str(value or "").strip()))


def _number_value(value: str) -> int | float:
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _browser_type_text_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    if not _has_browser_page_context(value):
        return {}
    patterns = (
        r"\b(?:type|enter|fill)\s+(?P<text>[^.!?]+?)\s+"
        r"(?:into|in)\s+(?:the\s+)?(?:current|this)?\s*"
        r"(?:web\s*page|webpage|page|browser)\s+(?P<target>[^.!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|向|给)?\s*(?:当前)?(?:网页|页面|浏览器|当前页)"
        r"(?:上|里|中|内)?(?:的)?\s*(?P<target>[^。！？!?，,]*?)"
        r"(?:输入|填写|键入|打入|填入)\s*(?P<text>[^。！？!?]+)$",
        r"(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:填写|填入|输入)\s*(?:当前)?(?:网页|页面|浏览器|当前页)?(?:的)?"
        r"(?P<target>[^。！？!?，,]+?)\s*(?:为|成|:|：)\s*(?P<text>[^。！？!?]+)$",
        r"\b(?:type|enter|fill)\s+(?P<text>[^.!?]+?)\s+"
        r"(?:into|in)\s+(?P<target>[^.!?]+?)\s+"
        r"(?:on|in)\s+(?:the\s+)?(?:current\s+)?(?:page|browser)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        typed_text = _clean_browser_typed_text(match.group("text"))
        if not typed_text:
            continue
        target = _clean_browser_element_label(match.group("target"))
        point = _browser_click_point(target)
        if point:
            return {
                "browser_action": "type_text",
                "selector": f"point={point['x']},{point['y']}",
                "text": typed_text,
                "fallback_x": point["x"],
                "fallback_y": point["y"],
            }
        return {
            "browser_action": "type_text",
            "selector": _browser_input_selector_from_target(target),
            "text": typed_text,
        }
    return {}


def _has_browser_page_context(text: str) -> bool:
    return bool(
        re.search(r"(?:网页|页面|浏览器|当前页)", text, flags=re.IGNORECASE)
        or re.search(r"(?:搜索结果|链接)", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:browser|page|webpage|web\s+page)\b", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:search\s+)?(?:result|link)s?\b", text, flags=re.IGNORECASE)
    )


def _browser_action_app_name_hint(text: str, browser_action: str) -> str:
    if browser_action not in {
        "click",
        "type_text",
        "open_search",
        "open_url",
        "open_url_extract",
        "open_url_screenshot",
        "extract_text",
        "current_page",
        "screenshot",
    }:
        return ""
    explicit_browser_app = _explicit_browser_app_name_hint(text)
    if explicit_browser_app and _browser_app_prepare_needed(text, browser_action):
        return explicit_browser_app
    app_name = _app_name_hint(text)
    if (
        app_name
        and _is_browser_or_search_app_name(app_name)
        and not _is_generic_browser_app_label(app_name)
        and (browser_action in {"click", "type_text"} or _browser_app_prepare_needed(text, browser_action))
    ):
        return app_name
    search_surface = _web_search_surface_hint(text)
    if (
        search_surface
        and _is_browser_or_search_app_name(search_surface)
        and not _is_generic_browser_app_label(search_surface)
        and _browser_app_prepare_needed(text, browser_action)
    ):
        return search_surface
    return ""


def _explicit_browser_app_name_hint(text: str) -> str:
    value = str(text or "")
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:在|用|通过)\s*"
        r"(?P<app>Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave)"
        r"(?:里|中|上|内)?",
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
        r"(?:打开|启动|开启|切到|聚焦)\s*"
        r"(?P<app>Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave)\b",
        r"^(?P<app>Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave)\s*"
        r"(?:点击|点一下|点按|单击|点|输入|填写|键入)",
        r"\b(?:open|launch|start|focus|switch\s+to|activate)\s+"
        r"(?P<app>google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave)\b",
        r"^(?P<app>google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave)\s+"
        r"(?:click|press|tap|type|enter|fill)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = legacy_app_name_hint(match.group("app"))
        if app_name and not _is_generic_browser_app_label(app_name):
            return app_name
    return ""


def _browser_app_prepare_needed(text: str, browser_action: str) -> bool:
    if browser_action in {"click", "type_text"}:
        return True
    if browser_action in {"open_search", "open_url", "open_url_extract", "open_url_screenshot"}:
        if browser_action == "open_search" and not _web_search_followup_hint(text):
            return False
        if browser_action in {"open_url_extract", "open_url_screenshot"} and _explicit_browser_app_name_hint(text):
            return True
        if browser_action != "open_search":
            return False
        value = str(text or "")
        return bool(
            re.search(
                r"(?:在|用|通过)\s*"
                r"(?:Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave)"
                r"(?:里|中|上|内)?",
                value,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
                r"(?:打开|启动|开启|切到|聚焦)\s*"
                r"(?:Chrome|Google\s*Chrome|谷歌浏览器|浏览器|Safari|Firefox|Edge|Brave)\b",
                value,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"^(?:Chrome|Google\s*Chrome|谷歌浏览器|浏览器|Safari|Firefox|Edge|Brave)\s*"
                r"(?:搜索|查找|检索)",
                value,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\b(?:in|with|using)\s+"
                r"(?:google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave)\b",
                value,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"^(?:google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave|browser)\s+"
                r"(?:search|find|look\s+up)\b",
                value,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\b(?:open|launch|start|focus|switch\s+to|activate)\s+"
                r"(?:google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave|browser)\b",
                value,
                flags=re.IGNORECASE,
            )
        )
    value = str(text or "")
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|开启|切到|聚焦)\s*"
            r"(?:Chrome|Google\s*Chrome|谷歌浏览器|浏览器|Safari|Firefox|Edge|Brave)\b",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:open|launch|start|focus|switch\s+to|activate)\s+"
            r"(?:google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave|browser)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _browser_app_prepare_mode(text: str) -> str:
    value = str(text or "")
    if re.search(
        r"(?:在|用|通过)\s*"
        r"(?:Chrome|Google\s*Chrome|谷歌浏览器|Safari|Firefox|Edge|Brave)"
        r"(?:里|中|上|内)?",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"\b(?:in|with|using)\s+"
        r"(?:google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave)\b",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"^(?:Chrome|Google\s*Chrome|谷歌浏览器|浏览器|Safari|Firefox|Edge|Brave)\s*"
        r"(?:搜索|查找|检索)",
        value,
        flags=re.IGNORECASE,
    ) or re.search(
        r"^(?:google\s+chrome|chrome|safari|firefox|edge|microsoft\s+edge|brave|browser)\s+"
        r"(?:search|find|look\s+up)\b",
        value,
        flags=re.IGNORECASE,
    ):
        return "focus"
    return (
        "open"
        if re.search(r"(?:打开|启动|开启|\bopen\b|\blaunch\b|\bstart\b)", value, flags=re.IGNORECASE)
        else "focus"
    )


def _clean_browser_typed_text(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[\"'`“”‘’]+|[\"'`“”‘’]+$", "", text).strip()
    text = re.sub(r"^(?:text|内容)\s*[:：]\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s+(?:please|pls)$", "", text, flags=re.IGNORECASE).strip()
    return re.sub(r"[。！？!?]+$", "", text).strip()


def _clean_browser_element_label(value: str) -> str:
    label = str(value or "").strip()
    label = re.sub(r"^[：:，,\s]+", "", label)
    label = re.sub(r"[。.,，；;！!？?]+$", "", label).strip()
    label = re.sub(r"^(?:当前)?(?:网页|页面|浏览器|当前页)(?:上的|上|里|中|内|的)?\s*", "", label)
    label = re.sub(r"^(?:上的|的|上|里|中|内)\s*", "", label)
    label = re.sub(
        r"^(?:the\s+)?(?:current|this)?\s*(?:web\s*page|webpage|page|browser)\s+",
        "",
        label,
        flags=re.IGNORECASE,
    )
    label = re.sub(r"\s*(?:按钮|链接|元素|button|link|element|field|input|box)$", "", label, flags=re.IGNORECASE)
    return label.strip()


def _browser_input_selector_from_target(target: str) -> str:
    clean = str(target or "").strip()
    if _looks_like_css_selector(clean):
        return clean
    lowered = clean.lower()
    if re.search(r"(?:搜索|查找|search|query|q)", lowered):
        return _BROWSER_SEARCH_INPUT_SELECTOR
    if re.search(r"(?:密码|password)", lowered):
        return 'input[type="password"]'
    if re.search(r"(?:邮箱|邮件|email|e-mail)", lowered):
        return 'input[type="email"], input[name*="email" i], input[autocomplete="email"]'
    if re.search(r"(?:用户名|账号|账户|user|username|login)", lowered):
        return 'input[name*="user" i], input[autocomplete="username"], input[type="text"]'
    return _BROWSER_TEXT_INPUT_SELECTOR


def _looks_like_css_selector(value: str) -> bool:
    stripped = str(value or "").strip()
    return bool(
        stripped.startswith(("#", ".", "[", "input", "textarea", "select", "button"))
        or re.search(r"^(?:[a-z][a-z0-9_-]*)(?:[#.\[:][^\s]+)$", stripped, flags=re.IGNORECASE)
    )


def _browser_current_page_find_hint(text: str, context_source: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    lowered = value.lower()
    if _looks_like_browser_field_input(value, lowered):
        return {}
    if not _looks_like_browser_current_page_find(value, lowered):
        return {}
    source = context_source if context_source in {"selection", "clipboard"} else ""
    query = _current_page_find_query(value, lowered)
    if not source and not query:
        return {}
    hint = {"browser_action": "find_current_page"}
    if source:
        hint["context_source"] = source
    if query:
        hint["query"] = query
    return hint


def _looks_like_browser_field_input(value: str, lowered: str) -> bool:
    return bool(
        (
            _contains_any(
                lowered,
                (
                    "search field",
                    "search box",
                    "search input",
                    "input field",
                    "text field",
                    "text box",
                ),
            )
            and _contains_any(lowered, ("type ", "enter ", "input ", "write "))
        )
        or re.search(
            r"(?:输入|键入|填写).{0,24}(?:搜索框|搜索栏|输入框|输入栏|文本框)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_browser_current_page_find(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:当前|这个|本页).{0,8}(?:网页|页面|页|标签页).{0,12}(?:查找|搜索|检索)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:查找|搜索|检索).{0,16}(?:当前|这个|本页).{0,8}(?:网页|页面|页|标签页)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:search|find)\s+(?:the\s+)?(?:current|this)\s+(?:web\s*)?page\b",
            lowered,
        )
        or re.search(
            r"\b(?:search|find)\s+.+?\s+(?:on|in)\s+(?:the\s+)?(?:current|this)"
            r"\s+(?:web\s*)?page\b",
            lowered,
        )
        or re.search(
            r"\bfind\s+(?:selected\s+text|current\s+selection|clipboard\s+contents|"
            r"the\s+clipboard)\s+(?:on|in)\s+(?:current\s+)?page\b",
            lowered,
        )
    )


def _current_page_find_query(value: str, lowered: str) -> str:
    patterns = (
        r"\b(?:search|find)\s+(?:the\s+)?(?:current|this)\s+(?:web\s*)?page\s+for\s+(.+)$",
        r"\b(?:search|find)\s+(.+?)\s+(?:on|in)\s+(?:the\s+)?(?:current|this)\s+(?:web\s*)?page\b",
        r"\b(?:current|this)\s+(?:web\s*)?page\s+(?:search|find)\s+(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            query = _clean_current_page_find_query(match.group(1))
            if query:
                return query

    chinese_patterns = (
        r"(?:当前|这个|本页).{0,8}(?:网页|页面|页|标签页).{0,4}(?:查找|搜索|检索)\s*(.+)$",
        r"(?:查找|搜索|检索)\s*(.+?)\s*(?:在|于|到).{0,4}(?:当前|这个|本页).{0,8}(?:网页|页面|页|标签页)",
        r"(?:在|于).{0,4}(?:当前|这个|本页).{0,8}(?:网页|页面|页|标签页).{0,4}(?:查找|搜索|检索)\s*(.+)$",
    )
    for pattern in chinese_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            query = _clean_current_page_find_query(match.group(1))
            if query:
                return query
    return ""


def _clean_current_page_find_query(query: str) -> str:
    value = re.sub(r"^[：:，,\s]+", "", str(query or "").strip())
    value = re.sub(r"[。.,，；;！!？?]+$", "", value).strip()
    lowered = value.lower()
    if not value:
        return ""
    context_terms = (
        "选中的内容",
        "选中内容",
        "当前选中文字",
        "当前选择",
        "剪贴板内容",
        "selected text",
        "current selection",
        "clipboard contents",
        "the clipboard",
        "clipboard",
    )
    if _contains_any(value, context_terms):
        return ""
    if lowered in {"current page", "this page", "current webpage", "this webpage"}:
        return ""
    return value


def _browser_current_page_hint(text: str) -> dict[str, Any]:
    value = _clean_prompt(text)
    lowered = value.lower()
    if safe_shortcut_hint(value):
        return {}
    if _looks_like_browser_current_page_screenshot(value, lowered):
        return {
            "browser_action": "screenshot",
            "reason": "user asked to capture the browser page",
        }
    if (
        _looks_like_browser_current_page_text(value, lowered)
        and _looks_like_browser_current_page_summary(value, lowered)
    ):
        return {"browser_action": "extract_text", "presentation": "summary"}
    if _looks_like_browser_current_page_metadata(value, lowered):
        return {"browser_action": "current_page"}
    if _looks_like_browser_current_page_text(value, lowered):
        hint = {"browser_action": "extract_text"}
        if _looks_like_browser_current_page_summary(value, lowered):
            hint["presentation"] = "summary"
        return hint
    return {}


def _looks_like_browser_current_page_screenshot(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:当前|这个|本页).{0,8}(?:网页|页面|标签页).{0,8}(?:截图|截屏)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"^(?:网页|页面|标签页).{0,4}(?:截图|截屏|截一下|截下|截个图|截个屏)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:截图|截屏).{0,8}(?:当前|这个|本页).{0,8}(?:网页|页面|标签页)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(r"\bscreenshot\s+(?:this|current)\s+(?:web\s*)?page\b", lowered)
    )


def _looks_like_browser_current_page_text(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:读|读取|提取|总结|摘要|概括).{0,8}"
            r"(?:当前|这个|本页).{0,8}(?:网页|页面|标签页|页|正文|内容)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|这个|本页).{0,8}(?:网页|页面|标签页|页|正文|内容)"
            r".{0,8}(?:读|读取|提取|总结|摘要|概括)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:read|extract|summari[sz]e)\s+(?:the\s+)?(?:current|this)"
            r"\s+(?:web\s*)?page(?:\s+text)?\b",
            lowered,
        )
        or re.search(
            r"\b(?:read|extract|summari[sz]e)\s+(?:the\s+)?(?:web\s*)?page\s+(?:text|content)\b",
            lowered,
        )
        or re.search(
            r"\bwhat(?:'s|\s+is)\s+(?:this|the\s+current|current)"
            r"\s+(?:web\s*)?page\s+about\b",
            lowered,
        )
        or re.search(
            r"(?:根据|基于|用|使用).{0,6}(?:当前|这个|本页).{0,8}"
            r"(?:网页|页面|标签页|页).{0,16}(?:写|生成|输出|整理|做|制作|总结|调研|分析)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:研究|调研|分析|整理|总结|摘要|写|生成|输出|制作|做).{0,8}"
            r"(?:当前|这个|本页).{0,8}(?:网页|页面|标签页|页)"
            r"(?:.{0,24}(?:写|生成|输出|整理|做|制作|报告|分析|总结|摘要))?",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:research|analy[sz]e|write|create|generate|produce|summari[sz]e)"
            r".{0,24}\b(?:from|based\s+on|using)?\s*(?:the\s+)?(?:current|this)"
            r"\s+(?:web\s*)?page\b",
            lowered,
        )
        or re.search(r"\bextract\s+(?:the\s+)?(?:current|this)\s+page\s+text\b", lowered)
    )


def _looks_like_browser_current_page_summary(value: str, lowered: str) -> bool:
    return _contains_any(value, ("总结", "摘要", "概括")) or bool(
        re.search(r"\bsummari[sz]e|summary\b", lowered)
        or re.search(
            r"\bwhat(?:'s|\s+is)\s+(?:this|the\s+current|current)"
            r"\s+(?:web\s*)?page\s+about\b",
            lowered,
        )
    )


def _looks_like_browser_current_page_metadata(value: str, lowered: str) -> bool:
    return bool(
        re.search(
            r"(?:当前|这个|本页).{0,8}(?:网址|链接|地址).{0,8}(?:是什么|多少|读取|读|打开)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:读取|读|打开).{0,8}(?:当前|这个|本页).{0,8}(?:网址|链接|地址)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"(?:当前|这个|本页).{0,8}(?:网页|页面|标签页).{0,8}(?:是什么|是啥|标题)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:what(?:'s| is)|read|open)\s+(?:the\s+)?(?:current|this)"
            r"\s+(?:page|tab)\s+(?:url|link|address)\b",
            lowered,
        )
        or re.search(r"\b(?:current|this)\s+(?:page|tab)\s+(?:url|link|address)\b", lowered)
        or re.search(
            r"\bwhat(?:'s| is)\s+(?:the\s+)?(?:current|this)\s+(?:page|tab)\b",
            lowered,
        )
    )


def _desktop_discovery_hint(text: str) -> dict[str, Any] | None:
    value = _clean_prompt(text)
    lowered = value.lower()
    if _looks_like_desktop_permissions_request(value, lowered):
        return {"action": "diagnose_permissions"}
    if _looks_like_active_window_request(value, lowered):
        return {"action": "read_active_window"}
    if _looks_like_running_apps_request(value, lowered):
        return {"action": "read_running_apps"}
    app_query = _local_app_discovery_query(value)
    if app_query:
        return {"action": "discover_apps", "query": app_query}
    if _looks_like_installed_apps_request(value, lowered):
        return {"action": "discover_apps"}
    return None


def _desktop_discovery_tool_preview(
    action: str,
    hint: Mapping[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    if action == "diagnose_permissions":
        return "desktop.permissions", {}
    if action == "read_active_window":
        return "desktop.active_window", {}
    if action == "read_running_apps":
        return "desktop.running_apps", {}
    if action == "discover_apps":
        query = str(hint.get("query") or "").strip()
        return (
            "desktop.list_apps",
            {"query": query, "limit": 20} if query else {},
        )
    return None, {}


def _looks_like_desktop_permissions_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(r"(?:桌面|本地|自动化|辅助功能|屏幕录制|读取屏幕).{0,16}(?:权限|授权|permission)", value, flags=re.IGNORECASE)
        or re.search(r"(?:需要|缺少|检查|诊断|修复).{0,16}(?:权限|授权)", value)
        or re.search(r"(?:为什么|为何|怎么|why).{0,24}(?:不能|无法|can't|cannot).{0,24}(?:打开|点击|读取屏幕|控制|操作|播放|open|click|control|play)", value, flags=re.IGNORECASE)
        or re.search(r"\b(?:desktop|local|accessibility|screen recording)\s+permissions?\b", lowered)
    )


def _explicit_system_settings_request(text: str) -> bool:
    if (
        _finder_special_location_hint(text)
        or _browser_internal_page_hint(text)
        or _app_preferences_hint(text)
    ):
        return False
    hint = system_control_hint(text)
    if str(hint.get("kind") or "").strip() != "settings_open":
        return False
    payload = hint.get("payload") if isinstance(hint.get("payload"), Mapping) else {}
    return bool(str(payload.get("target") or "").strip())


def _looks_like_active_window_request(value: str, lowered: str) -> bool:
    if re.search(r"我现在是不是在家", value):
        return False
    return bool(
        re.search(r"(?:当前|现在|前台).{0,8}(?:窗口|应用|app).{0,8}(?:是什么|是哪个|是不是)", value, flags=re.IGNORECASE)
        or _looks_like_current_window_observation_request(value, lowered)
        or re.search(r"(?:(?:当前|现在)\s*)?前台\s*(?:窗口|应用|app)?\s*(?:是什么|是啥|哪个|什么)", value, flags=re.IGNORECASE)
        or re.search(r"(?:当前|现在)?前台是不是\s*.+", value, flags=re.IGNORECASE)
        or re.search(r"现在是不是在\s*.+", value, flags=re.IGNORECASE)
        or re.search(r"我正在用什么(?:应用|app|软件)?", value, flags=re.IGNORECASE)
        or re.search(r"\bwhat\s+app\s+am\s+i\s+using\b", lowered)
        or re.search(r"\bwhat\s+is\s+(?:the\s+)?(?:frontmost|active|foreground)\s+window\b", lowered)
        or re.search(r"\bwhich\s+(?:app|application)\s+is\s+(?:frontmost|active|foreground)\b", lowered)
        or re.search(r"\bis\s+.+\s+(?:frontmost|the\s+active\s+app|the\s+active\s+application)\b", lowered)
        or re.search(r"\bis\s+(?:the\s+)?(?:active|frontmost|foreground)\s+(?:app|application)\s+.+", lowered)
    )


def _looks_like_current_window_observation_request(value: str, lowered: str) -> bool:
    if re.search(
        r"(?:列表|清单|所有|全部|哪些|几个|多少|list|all|windows)",
        value,
        flags=re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?:查看|看看|看一下|看下|显示|读取)?\s*"
            r"(?:当前|现在|前台|这个|该)\s*(?:窗口|window)"
            r"\s*(?:是什么|是啥|哪个|什么|标题|名称|名字)?"
            r"(?:一下|下|可以吗|好吗|好么|行吗|吗|嘛|吧|呢)?$",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:show|read|inspect|look\s+at|check)\s+"
            r"(?:the\s+)?(?:current|active|foreground|frontmost|this)\s+window\b",
            lowered,
        )
    )


def _looks_like_running_apps_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(r"(?:现在|当前).{0,8}(?:开了|打开|运行).{0,8}(?:哪些|什么).{0,8}(?:应用|app|软件|程序)", value, flags=re.IGNORECASE)
        or re.search(r"(?:现在|当前).{0,8}(?:哪些|什么).{0,8}(?:应用|app|软件|程序).{0,8}(?:开着|打开|运行|在运行)", value, flags=re.IGNORECASE)
        or re.search(r"(?:列|列出|列一下|看看|查看).{0,8}(?:打开|运行|正在运行).{0,8}(?:应用|app|软件|程序)", value, flags=re.IGNORECASE)
        or re.search(r"\b(?:what|which|list|show)\s+(?:apps?|applications?)\s+(?:are\s+)?(?:running|open)\b", lowered)
    )


def _looks_like_installed_apps_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(r"(?:列出|列一下|查看|看看|有哪些).{0,8}(?:已安装|可用).{0,8}(?:应用|app|软件|程序)", value, flags=re.IGNORECASE)
        or re.search(r"(?:列出|列一下|查看|看看|显示).{0,8}(?:所有|全部).{0,4}(?:应用|app|软件|程序)", value, flags=re.IGNORECASE)
        or re.search(r"(?:有哪些|有什么|有啥).{0,4}(?:应用|app|软件|程序)", value, flags=re.IGNORECASE)
        or re.search(r"\bshow\s+installed\s+apps?\b", lowered)
        or re.search(r"\b(?:list|show)\s+all\s+(?:apps?|applications?)\b", lowered)
        or re.search(r"\blist\s+(?:installed|available)\s+(?:apps?|applications?)\b", lowered)
    )


def _local_app_discovery_query(text: str) -> str:
    value = _clean_prompt(text)
    patterns = (
        r"(?:机器|电脑|mac|系统|本机|本地).{0,8}(?:有没有|是否有|有无|装了|安装了|有没有安装)\s*(?P<app>[^。！？!?，,]+)",
        r"(?:有没有|是否有|有无|装了|安装了|有没有安装).{0,8}(?P<app>[\w .·-]{2,40})(?:\s*(?:这个|这款|这个应用|这个软件|app|application|应用|软件))?$",
        r"\b(?:is|do\s+i\s+have|have)\s+(?P<app_en>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:installed|on\s+(?:this\s+)?mac|on\s+(?:this\s+)?machine)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_app = (
            match.groupdict().get("app")
            or match.groupdict().get("app_en")
            or ""
        )
        app = _clean_app_name_hint(raw_app)
        if app and not _is_generic_foreground_app_label(app):
            return app
    return ""


def _looks_like_ui_operation(text: str) -> bool:
    return _contains_any(
        text,
        ["click", "type", "press", "shortcut", "scroll", "点击", "输入", "按", "快捷键", "滚动", "发送"],
    )


def _generic_app_foreground_operation_tool(
    *,
    app_name: str,
    mode: str,
    allowed: set[str] | None,
    operation_tools: Iterable[str],
) -> str | None:
    if not app_name:
        return None
    if not _first_allowed(app_control_tool_candidates(mode), allowed):
        return None
    return _first_allowed(operation_tools, allowed)


def _explicit_hotkey_should_override_safe_shortcut(
    text: str,
    hotkey: Mapping[str, Any] | None,
    safe_shortcut: Mapping[str, Any] | None,
) -> bool:
    if not hotkey or not safe_shortcut:
        return False
    if str((safe_shortcut or {}).get("action") or "").strip() != "focus_address_bar":
        return False
    return not _contains_any(text, ["地址栏", "address bar", "omnibox"])


def _explicit_hotkey_request(text: str) -> bool:
    value = _clean_prompt(text)
    return bool(
        re.search(r"(?:按|按下|发送|触发|press|hit|send)\s*", value, flags=re.IGNORECASE)
        and re.search(
            r"(?:command|cmd|⌘|control|ctrl|option|alt|shift|回车|enter|return|space|空格)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _standalone_hotkey_request(text: str) -> bool:
    value = _clean_prompt(text)
    if not hotkey_hint(value):
        return False
    return bool(
        re.fullmatch(
            r"(?:按|按下|敲|敲一下|触发)\s*(?:回车键?|enter|return|space|空格|"
            r"(?:command|cmd|⌘|control|ctrl|option|alt|shift)\s*[+ ]?\s*\w+)",
            value,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            r"(?:press|hit|tap)\s+(?:the\s+)?(?:enter|return|space|spacebar|"
            r"(?:command|cmd|control|ctrl|option|alt|shift)(?:\s*[+ ]\s*\w+)?)",
            value,
            flags=re.IGNORECASE,
        )
        or re.fullmatch(
            r"(?:can|could|would)\s+you\s+(?:please\s+)?(?:press|hit|tap)\s+"
            r"(?:the\s+)?(?:enter|return|space|spacebar|"
            r"(?:command|cmd|control|ctrl|option|alt|shift)(?:\s*[+ ]\s*\w+)?)\??",
            value,
            flags=re.IGNORECASE,
        )
    )


def _desktop_operation_tool_preview(
    *,
    app_name: str,
    mode: str,
    allowed: set[str] | None,
    click_target: dict[str, Any] | None,
    hotkey: dict[str, Any] | None,
    safe_shortcut: dict[str, str] | None,
    safe_key: dict[str, Any] | None,
    safe_scroll: dict[str, Any] | None,
    safe_click: dict[str, Any] | None,
    type_target: dict[str, Any] | None,
    safe_type_text: str,
    allow_app_tools: bool = True,
) -> tuple[str | None, dict[str, Any]]:
    if safe_shortcut:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "safe_shortcut"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **safe_shortcut}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.safe_shortcut",),
        )
        if generic_tool:
            return generic_tool, dict(safe_shortcut)
        shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
        if shortcut_tool:
            return shortcut_tool, dict(safe_shortcut)
    if safe_key:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "safe_key"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **safe_key}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.safe_key",),
        )
        if generic_tool:
            return generic_tool, dict(safe_key)
        key_tool = _first_allowed(("desktop.safe_key",), allowed)
        if key_tool:
            return key_tool, dict(safe_key)
    if safe_scroll:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "safe_scroll"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **safe_scroll}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.safe_scroll",),
        )
        if generic_tool:
            return generic_tool, dict(safe_scroll)
        scroll_tool = _first_allowed(("desktop.safe_scroll",), allowed)
        if scroll_tool:
            return scroll_tool, dict(safe_scroll)
    if safe_click:
        click_count = int(safe_click.get("click_count") or 1)
        if click_count != 1:
            raw_click_tool = _first_allowed(("desktop.click",), allowed)
            if raw_click_tool:
                return raw_click_tool, dict(safe_click)
        safe_click_payload = {
            key: value
            for key, value in safe_click.items()
            if key in {"x", "y"}
        }
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "safe_click"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **safe_click_payload}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.safe_click", "desktop.click"),
        )
        if generic_tool:
            return generic_tool, safe_click_payload if generic_tool == "desktop.safe_click" else dict(safe_click)
        click_tool = _first_allowed(("desktop.safe_click",), allowed)
        if click_tool:
            return click_tool, safe_click_payload
        raw_click_tool = _first_allowed(("desktop.click",), allowed)
        if raw_click_tool:
            return raw_click_tool, dict(safe_click)
    if hotkey:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "hotkey"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **hotkey}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.hotkey",),
        )
        if generic_tool:
            return generic_tool, dict(hotkey)
        return _first_allowed(("desktop.hotkey",), allowed), dict(hotkey)
    if app_name and type_target:
        if allow_app_tools:
            app_tool = _first_allowed(
                app_foreground_tool_candidates(mode, "type_into_ui_element"),
                allowed,
            )
            if app_tool:
                return app_tool, {"app_name": app_name, **type_target, "limit": 80}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.type_into_ui_element",),
        )
        if generic_tool:
            return generic_tool, {**type_target, "limit": 80}
        return _first_allowed(("desktop.type_into_ui_element",), allowed), {**type_target, "limit": 80}
    if app_name and safe_type_text:
        if allow_app_tools:
            app_tool = _first_allowed(
                app_foreground_tool_candidates(mode, "safe_type_text"),
                allowed,
            )
            if app_tool:
                return app_tool, {"app_name": app_name, "text": safe_type_text}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.safe_type_text", "desktop.type_text"),
        )
        if generic_tool:
            return generic_tool, {"text": safe_type_text}
        type_tool = _first_allowed(("desktop.safe_type_text", "desktop.type_text"), allowed)
        return type_tool, {"text": safe_type_text}
    if app_name and click_target:
        if allow_app_tools:
            app_tool = _first_allowed(
                app_foreground_tool_candidates(mode, "click_ui_element"),
                allowed,
            )
            if app_tool:
                return app_tool, {"app_name": app_name, **click_target, "limit": 80}
        generic_tool = _generic_app_foreground_operation_tool(
            app_name=app_name,
            mode=mode,
            allowed=allowed,
            operation_tools=("desktop.click_ui_element",),
        )
        if generic_tool:
            return generic_tool, {**click_target, "limit": 80}
        return _first_allowed(("desktop.click_ui_element",), allowed), {**click_target, "limit": 80}
    if type_target:
        return _first_allowed(("desktop.type_into_ui_element",), allowed), {**type_target, "limit": 80}
    if safe_type_text:
        type_tool = _first_allowed(("desktop.safe_type_text", "desktop.type_text"), allowed)
        return type_tool, {"text": safe_type_text}
    if click_target:
        return _first_allowed(("desktop.click_ui_element",), allowed), {**click_target, "limit": 80}
    return None, {}


def _desktop_operation_fallback_tool(
    *,
    allowed: set[str] | None,
    click_target: Mapping[str, Any] | None,
    hotkey: Mapping[str, Any] | None,
    safe_shortcut: Mapping[str, Any] | None,
    safe_key: Mapping[str, Any] | None,
    safe_scroll: Mapping[str, Any] | None,
    safe_click: Mapping[str, Any] | None,
    type_target: Mapping[str, Any] | None,
    safe_type_text: str,
) -> str | None:
    if hotkey:
        return _first_allowed(("desktop.hotkey",), allowed)
    if safe_shortcut:
        return _first_allowed(("desktop.safe_shortcut",), allowed)
    if safe_key:
        return _first_allowed(("desktop.safe_key",), allowed)
    if safe_scroll:
        return _first_allowed(("desktop.safe_scroll",), allowed)
    if safe_click:
        return _first_allowed(("desktop.safe_click", "desktop.click"), allowed)
    if type_target:
        return _first_allowed(("desktop.type_into_ui_element",), allowed)
    if safe_type_text:
        return _first_allowed(("desktop.safe_type_text", "desktop.type_text"), allowed)
    if click_target:
        return _first_allowed(("desktop.click_ui_element",), allowed)
    return _first_allowed(
        (
            "desktop.click_ui_element",
            "desktop.type_into_ui_element",
            "desktop.safe_shortcut",
            "desktop.safe_key",
            "desktop.hotkey",
            "desktop.safe_type_text",
        ),
        allowed,
    )


def _expected_outputs(text: str, *, default: list[str]) -> list[str]:
    outputs = []
    if _contains_any(text, ["chart", "plot", "graph", "trend chart", "图表", "趋势图", "折线图", "可视化"]):
        outputs.append("chart")
    if _contains_any(text, ["report", "报告"]):
        outputs.append("report")
    if _contains_any(
        text,
        [
            "output csv",
            "export csv",
            "export as csv",
            "csv file",
            "csv 汇总",
            "输出 csv",
            "生成 csv",
            "做成 csv",
            "分析成 csv",
            "分析为 csv",
            "转成 csv",
            "转换成 csv",
            "导出 csv",
            "导出成 csv",
            "导出为 csv",
            "提取成 csv",
            "提取为 csv",
            "csv 文件",
            "表格汇总",
            "整理成表格",
            "整理为表格",
            "输出表格",
            "生成表格",
            "make a table",
            "as a table",
        ],
    ):
        outputs.append("table")
    return outputs or list(default)
