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

from apps.shell.agent.runtime.app_aliases import APP_ALIASES as _APP_ALIASES
from apps.shell.agent.runtime.app_aliases import compact_app_alias as _compact_app_alias
from apps.shell.agent.runtime.web_destinations import known_web_destination_url_hint

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
    type_into_ui_hint,
    ui_inspection_hint,
    window_list_hint,
)
from .file_access_plan_hints import file_access_hint
from .schedule_plan_hints import schedule_context_source_hint, schedule_tool_preview
from .system_plan_hints import system_control_hint, system_tool_preview
from .terminal_plan_hints import terminal_command_hint


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
        context_source = context_source_hint(text)
        can_discover_source = _contains_any(
            text,
            ["数据", "数据集", "表格", "data", "dataset", "table", "csv", "xlsx", "json"],
        )
        has_source = bool(source_hint or source_scope or context_source or can_discover_source)
        if score <= 0 and has_source and _contains_any(text, ["分析", "统计", "汇总", "可视化"]):
            score = 0.16
        if (
            score <= 0
            and context_source in {"selection", "clipboard"}
            and _contains_any(text, ["分析", "统计", "汇总", "可视化", "数据", "表格", "data", "table"])
        ):
            score = 0.22
        if score <= 0:
            return _empty_intent("data_analysis", text)
        inputs = {
            "data_source_hint": source_hint,
            "data_source_kind": data_source_kind_hint(source_hint, text),
        }
        if context_source:
            inputs["context_source"] = context_source
        if source_scope and not source_hint:
            inputs["data_source_scope_hint"] = source_scope
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "data_analysis", text),
            kind="data_analysis",
            title="Data Analysis",
            user_goal=text,
            confidence=min(0.95, 0.48 + score),
            description="Analyze structured data and produce a report or artifact.",
            inputs=inputs,
            expected_outputs=_expected_outputs(text, default=["analysis_report"]),
            required_capabilities=["file.workspace_read", "terminal.execution", "artifact.write"],
            preferred_capabilities=["data.analysis", "desktop.app_control"],
            missing_inputs=[] if has_source else ["data_source"],
            risk_level="medium",
        )

    def _desktop_operation_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        if _direct_communication_candidate_hint(text):
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
        app_scoped_safe_operation = _app_scoped_safe_operation_hint(text)
        if safe_shortcut is None and app_scoped_safe_operation.get("safe_shortcut"):
            safe_shortcut = app_scoped_safe_operation["safe_shortcut"]
        if safe_key is None and app_scoped_safe_operation.get("safe_key"):
            safe_key = app_scoped_safe_operation["safe_key"]
        if safe_scroll is None and app_scoped_safe_operation.get("safe_scroll"):
            safe_scroll = app_scoped_safe_operation["safe_scroll"]
        safe_click = safe_click_hint(text)
        foreground_compose_text = _foreground_compose_text_hint(text)
        foreground_paste = _foreground_paste_hint(text)
        if foreground_paste and safe_shortcut is None:
            safe_shortcut = {"action": "paste"}
        desktop_discovery = _desktop_discovery_hint(text)
        context_source = context_source_hint(text)
        app_scoped_desktop_operation = _app_scoped_desktop_operation_hint(text)
        if (
            _browser_type_text_hint(text) or _browser_click_hint(text)
        ) and not app_scoped_desktop_operation:
            return _empty_intent("desktop_operation", text)
        foreground_submit_action = _foreground_submit_action_hint(text)
        command_palette = _app_command_palette_hint(text)
        browser_internal_page = _browser_internal_page_hint(text)
        app_preferences = _app_preferences_hint(text)
        app_scoped_safe_shortcut_app = _app_scoped_safe_shortcut_app_name_hint(text, safe_shortcut)
        spotlight_search_query = _spotlight_search_query_hint(text)
        score = _score_terms(
            text,
            [
                "open ",
                "launch ",
                "focus ",
                "switch ",
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
        if score <= 0 and (foreground_submit_action or foreground_compose_text or foreground_paste):
            score = 0.18
        if score <= 0 and (app_scoped_desktop_operation or command_palette):
            score = 0.18
        if score <= 0 and browser_internal_page:
            score = 0.24
        if score <= 0 and app_preferences:
            score = 0.2
        if score <= 0 and spotlight_search_query:
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
            and not foreground_compose_text
            and not foreground_paste
            and desktop_discovery is None
            and not foreground_submit_action
            and not command_palette
            and not browser_internal_page
            and not app_preferences
        ):
            return _empty_intent("desktop_operation", text)
        focus_window = focus_window_hint(text)
        window_list = window_list_hint(text)
        foreground_app_windows_shortcut = (
            str((safe_shortcut or {}).get("action") or "").strip() == "application_windows"
        )
        if safe_key:
            screen_capture = None
        if foreground_app_windows_shortcut:
            window_list = None
            app_management = None
            screen_capture = None
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
            or _foreground_compose_app_name_hint(text)
            or _foreground_submit_app_name_hint(text, foreground_submit_action)
            or _app_name_hint(text)
            or ""
        ).strip()
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
        app_search = _app_search_hint(text, app_name_hint)
        app_search_app_name = str(app_search.get("app_name") or "").strip()
        if app_search_app_name and (
            not app_name_hint
            or _looks_like_app_search_followup_app(app_name_hint)
            or _compact_app_alias(app_name_hint).startswith(
                _compact_app_alias(app_search_app_name)
            )
        ):
            app_name_hint = app_search_app_name
        operation_hint = (
            str((desktop_discovery or {}).get("action") or "")
            or ("submit_foreground" if foreground_submit_action else "")
            or ("browser_internal_page" if browser_internal_page else "")
            or ("app_preferences" if app_preferences else "")
            or ("safe_shortcut_sequence" if safe_shortcut_sequence else "")
            or ("safe_shortcut" if safe_shortcut else "")
            or ("safe_key" if safe_key else "")
            or ("safe_scroll" if safe_scroll else "")
            or _desktop_operation_hint(text)
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
            and desktop_discovery is None
            and not foreground_compose_text
            and not foreground_paste
            and not app_search
            and not spotlight_search_query
            and not foreground_submit_action
            and not command_palette
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
            and not app_search
            and not command_palette
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
            and not app_search
            and not command_palette
        ):
            return _empty_intent("desktop_operation", text)
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
        if spotlight_search_query:
            inputs["spotlight_search_hint"] = {"query": spotlight_search_query}
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
        if desktop_discovery is not None:
            inputs["desktop_discovery_hint"] = desktop_discovery
        if foreground_compose_text:
            inputs["foreground_compose_text_hint"] = foreground_compose_text
        if foreground_paste:
            inputs["foreground_paste_hint"] = {"action": "paste"}
        if foreground_submit_action:
            inputs["foreground_submit_action_hint"] = foreground_submit_action
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
                "minimize_window",
                "safe_shortcut",
                "safe_key",
                "safe_scroll",
                "safe_click",
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
            expected_outputs=["desktop_state"],
            required_capabilities=["desktop.app_discovery"],
            preferred_capabilities=["desktop.app_control", "desktop.ui_operation"],
            risk_level=risk_level,
        )

    def _media_playback_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
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
            preferred_capabilities=["desktop.app_control"],
            risk_level="low",
        )

    def _system_control_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        if metadata.get("desktop_permission_recovery") and metadata.get("recovery_tool"):
            return _empty_intent("system_control", text)
        if _browser_internal_page_hint(text) or _app_preferences_hint(text):
            return _empty_intent("system_control", text)
        hint = system_control_hint(text)
        if not hint:
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
        source = context_source_hint(text)
        if source and safe_shortcut_hint(text):
            return _empty_intent("web_research", text)
        if _spotlight_search_query_hint(text):
            return _empty_intent("web_research", text)
        if _direct_communication_hint(text):
            return _empty_intent("web_research", text)
        dynamic_source = source if source in {"clipboard", "selection"} else ""
        web_search = _web_search_hint(text, dynamic_source)
        browser_interaction = _browser_type_text_hint(text) or _browser_click_hint(text)
        if _app_scoped_desktop_operation_hint(text):
            return _empty_intent("web_research", text)
        browser_action = (
            web_search
            if str(web_search.get("followup_action") or "").strip()
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
        inputs.update(browser_action)
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
                "artifact.write",
            ],
            risk_level=risk_level,
        )

    def _report_generation_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        score = _score_terms(text, ["report", "write up", "summary", "deck", "报告", "总结", "汇报", "文档"])
        if score <= 0:
            return _empty_intent("report_generation", text)
        context_source = context_source_hint(text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "report_generation", text),
            kind="report_generation",
            title="Report Generation",
            user_goal=text,
            confidence=min(0.85, 0.34 + score),
            description="Produce a written artifact from available context or gathered inputs.",
            inputs={"context_source": context_source} if context_source else {},
            expected_outputs=_expected_outputs(text, default=["report"]),
            required_capabilities=["artifact.write"],
            preferred_capabilities=[
                *(
                    ["clipboard.read_write", "desktop.ui_operation"]
                    if context_source
                    else ["file.workspace_read", "browser.research", "data.analysis"]
                ),
                "artifact.write",
            ],
            risk_level="low",
        )

    def _code_task_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        if _app_command_palette_hint(text):
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
        score = _score_terms(text, ["code", "test", "bug", "build", "repo", "代码", "测试", "修复", "仓库"])
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
                "整理文件",
                "整理文件夹",
                "文件整理",
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
        destructive = _contains_any(text, ["delete", "remove", "trash", "删除", "移除", "清空"])
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "file_organization", text),
            kind="file_organization",
            title="File Organization",
            user_goal=text,
            confidence=min(0.88, 0.42 + score),
            description="Inspect files, produce a file organization plan, and apply explicit changes only after approval.",
            inputs={"location_hint": _file_location_hint(text), "operation_hint": _file_operation_hint(text)},
            expected_outputs=["file_plan", "report"],
            required_capabilities=["file.organization"],
            preferred_capabilities=["file.workspace_read", "artifact.write", "desktop.app_control"],
            missing_inputs=[] if _file_location_hint(text) else ["file_location"],
            risk_level="high" if destructive else "medium",
        )

    def _file_access_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        if _explicit_browser_url_hint(text) or _browser_internal_page_hint(text):
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
        if score <= 0 and metadata.get("runnable_kind") != "workflow":
            return _empty_intent("workflow_orchestration", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "workflow_orchestration", text),
            kind="workflow_orchestration",
            title="Workflow Orchestration",
            user_goal=text,
            confidence=min(0.92, 0.5 + score),
            description="Run or debug an Agent Studio workflow.",
            required_capabilities=["workflow.orchestration"],
            preferred_capabilities=["artifact.write"],
            risk_level="medium",
        )

    def _multi_agent_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        score = _score_terms(text, ["multi-agent", "group", "agents", "群组", "多 agent", "多Agent", "协作"])
        if score <= 0 and _looks_like_multi_agent_request(text):
            score = 0.24
        if score <= 0 and metadata.get("runnable_kind") != "group":
            return _empty_intent("multi_agent", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "multi_agent", text),
            kind="multi_agent",
            title="Multi-Agent Coordination",
            user_goal=text,
            confidence=min(0.9, 0.48 + score),
            description="Coordinate multiple agents or group runs.",
            required_capabilities=["group.multi_agent"],
            preferred_capabilities=["artifact.write"],
            risk_level="medium",
        )

    def _communication_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
        direct_hint = _direct_communication_candidate_hint(text)
        if _foreground_submit_action_hint(text) and not direct_hint:
            return _empty_intent("communication", text)
        source = context_source_hint(text)
        score = _score_terms(text, ["email", "message", "mail", "send to", "send ", "邮件", "消息", "发给", "发送"])
        if score <= 0 and direct_hint:
            score = 0.24
        if score <= 0:
            return _empty_intent("communication", text)
        inputs = {"context_source": source} if source else {}
        if direct_hint:
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
        hint = capture_note_hint(text)
        if not hint:
            return _empty_intent("information_capture", text)
        has_body = bool(str(hint.get("body") or "").strip())
        source = str(hint.get("source") or "").strip()
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
        plan = self.plan_intent(selected, allowed_tools=allowed_tools)
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
    ) -> RuntimePlanSnapshot:
        allowed = _allowed_tool_set(allowed_tools)
        steps = self._steps_for_intent(intent, allowed)
        required_capabilities = _required_capabilities_for_plan(intent, steps)
        capabilities = [*required_capabilities, *intent.preferred_capabilities]
        snapshots = capability_snapshots(
            allowed_tools=allowed_tools,
            capability_ids=capabilities,
        )
        missing = _missing_capabilities(snapshots, required_capability_ids=required_capabilities)
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
            return [_service_step(intent, "workflow.orchestration", "Select or start workflow")]
        if intent.kind == "multi_agent":
            return [_service_step(intent, "group.multi_agent", "Select or start group run")]
        return self._report_steps(intent, allowed)

    def _data_analysis_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        source_hint = str(intent.inputs.get("data_source_hint") or "").strip()
        context_source = str(intent.inputs.get("context_source") or "").strip()
        source_scope = str(intent.inputs.get("data_source_scope_hint") or "").strip()
        if context_source and not source_hint:
            context_steps = _context_source_steps(
                intent,
                allowed,
                context_source,
                step_prefix="data",
                capability_id="data.analysis",
            )
            depends_on = [step.step_id for step in context_steps]
            return [
                *context_steps,
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
                        "paths": data_analysis_artifacts_expected(
                            intent.expected_outputs,
                            intent.user_goal,
                        ),
                        "body_source": context_source,
                    },
                    depends_on=["run-analysis"],
                    reason="Return a durable data-analysis artifact that Studio and Chat can replay.",
                ),
            ]
        if _can_use_builtin_data_analysis(intent, allowed):
            artifact_paths = data_analysis_artifacts_expected(
                intent.expected_outputs,
                intent.user_goal,
            )
            artifact_path = artifact_paths[0] if artifact_paths else "analysis-report.md"
            input_preview = {
                "path": source_hint,
                "artifact_path": artifact_path,
            }
            if len(artifact_paths) > 1:
                input_preview["artifact_paths"] = artifact_paths
            return [
                _step(
                    intent,
                    "analyze-data-file",
                    "Analyze data file",
                    "data.analysis",
                    _first_allowed(("data.analyze",), allowed),
                    input_preview=input_preview,
                    reason=(
                        "Use the built-in local parser for straightforward CSV, TSV, JSON, JSONL, XLSX, "
                        "text-table, and standard report artifacts before escalating to terminal.run."
                    ),
                )
            ]
        inspect_tool_candidates = (
            ("workspace.read", "workspace.list")
            if source_hint
            else ("workspace.list", "workspace.read")
        )
        return [
            _step(
                intent,
                "inspect-data-source",
                "Inspect data source",
                "file.workspace_read",
                _first_allowed(inspect_tool_candidates, allowed),
                input_preview={"path": source_hint or source_scope} if source_hint or source_scope else {},
                reason="Find and inspect the dataset before analysis.",
                fallback_tools=["desktop.open_path", "browser.current_page"],
            ),
            _step(
                intent,
                "run-analysis",
                "Run reproducible data analysis",
                "data.analysis",
                _first_allowed(("terminal.run",), allowed),
                input_preview={"command": "python - <<'PY'\n# inspect data, compute summary, generate charts\nPY"},
                risk_level="high",
                approval_required=True,
                depends_on=["inspect-data-source"],
                reason="Use local Python/pandas-style analysis instead of manually operating a spreadsheet app.",
            ),
            _step(
                intent,
                "write-analysis-artifact",
                "Write analysis artifact",
                "artifact.write",
                _first_allowed(("artifact.write",), allowed),
                input_preview={
                    "paths": data_analysis_artifacts_expected(
                        intent.expected_outputs,
                        intent.user_goal,
                    )
                },
                depends_on=["run-analysis"],
                reason="Return a durable report artifact that Studio and Chat can replay.",
            ),
        ]

    def _desktop_operation_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        focus_window = focus_window_hint(intent.user_goal)
        window_list = window_list_hint(intent.user_goal)
        ui_inspection = ui_inspection_hint(intent.user_goal)
        screen_capture = screen_capture_hint(intent.user_goal)
        app_management = app_management_hint(intent.user_goal)
        foreground_management = foreground_management_hint(intent.user_goal)
        safe_shortcut = safe_shortcut_hint(intent.user_goal)
        safe_shortcut_sequence = safe_shortcut_sequence_hint(intent.user_goal)
        if safe_shortcut_sequence:
            safe_shortcut = dict(safe_shortcut_sequence[0])
        safe_key = safe_key_hint(intent.user_goal)
        safe_scroll = safe_scroll_hint(intent.user_goal)
        app_scoped_safe_operation = _app_scoped_safe_operation_hint(intent.user_goal)
        if safe_shortcut is None and app_scoped_safe_operation.get("safe_shortcut"):
            safe_shortcut = app_scoped_safe_operation["safe_shortcut"]
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
        desktop_discovery = intent.inputs.get("desktop_discovery_hint")
        if not isinstance(desktop_discovery, Mapping):
            desktop_discovery = _desktop_discovery_hint(intent.user_goal)
        app_search = intent.inputs.get("app_search_hint")
        if not isinstance(app_search, Mapping):
            app_search = _app_search_hint(
                intent.user_goal,
                str(intent.inputs.get("app_name_hint") or ""),
            )
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
            spotlight_search = {"query": spotlight_query} if spotlight_query else {}
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
            or _app_scoped_safe_shortcut_app_name_hint(intent.user_goal, safe_shortcut)
            or (app_management or {}).get("app_name")
            or _foreground_compose_app_name_hint(intent.user_goal)
            or ""
        ).strip()
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
        click_target = click_target_hint(intent.user_goal)
        hotkey = hotkey_hint(intent.user_goal)
        type_target = type_into_ui_hint(intent.user_goal, app_name=app_name)
        foreground_compose_text = str(
            intent.inputs.get("foreground_compose_text_hint")
            or _foreground_compose_text_hint(intent.user_goal)
            or ""
        ).strip()
        safe_type_text = "" if type_target else (safe_type_text_hint(intent.user_goal) or foreground_compose_text)
        foreground_submit_action = str(
            intent.inputs.get("foreground_submit_action_hint")
            or _foreground_submit_action_hint(intent.user_goal)
            or ""
        ).strip()
        if (
            app_name
            and (foreground_submit_action or foreground_compose_text or foreground_paste)
            and not _explicit_app_open_request(intent.user_goal)
        ):
            mode = "focus"
        if foreground_submit_action:
            click_target = None
        submit_action = submit_action_hint(intent.user_goal)
        if click_target and not any((type_target, safe_type_text, app_search)):
            submit_action = ""
        followup_safe_shortcut = safe_shortcut if safe_type_text and safe_shortcut else None
        followup_safe_shortcut_sequence = [
            dict(item) for item in safe_shortcut_sequence[1:] if isinstance(item, Mapping)
        ]
        primary_safe_shortcut = None if followup_safe_shortcut else safe_shortcut
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
            safe_type_text=safe_type_text,
            allow_app_tools=not bool(focus_window),
        )
        operation_uses_app_tool = bool(operation_tool and operation_tool.startswith("app."))
        if spotlight_search:
            query = str(spotlight_search.get("query") or "").strip()
            return [
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
                ),
            ]
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
            and not app_search
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
        if foreground_management:
            action = str(foreground_management.get("action") or "").strip()
            tool_name = {
                "hide_app": "desktop.hide_app",
                "minimize_window": "desktop.minimize_window",
                "close_window": "desktop.close_window",
                "quit_app": "desktop.quit_app",
            }.get(action)
            requires_approval = action in {"close_window", "quit_app"}
            steps.append(
                _step(
                    intent,
                    "manage-foreground",
                    "Manage foreground",
                    "desktop.app_control",
                    _first_allowed((tool_name,), allowed) if tool_name else None,
                    risk_level="high" if requires_approval else "low",
                    approval_required=requires_approval,
                    depends_on=["discover-desktop-state"],
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
        if screen_capture is not None and not any(
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
            steps.append(
                _step(
                    intent,
                    "open-app-preferences",
                    "Open app preferences",
                    "desktop.app_control",
                    _first_allowed(
                        app_foreground_tool_candidates(preferences_mode, "safe_shortcut"),
                        allowed,
                    ),
                    input_preview={"app_name": preferences_app, "action": "preferences"},
                    depends_on=["discover-desktop-state"],
                    action="shortcut",
                    risk_level="low",
                    approval_required=False,
                    reason="Open the requested app preferences through an app-scoped safe shortcut.",
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
                steps.append(
                    _step(
                        intent,
                        "open-browser-internal-page",
                        "Open browser internal page",
                        "desktop.app_control",
                        _first_allowed(
                            app_foreground_tool_candidates(page_mode, "safe_shortcut"),
                            allowed,
                        ),
                        input_preview={"app_name": browser_app, "action": page_action},
                        depends_on=[previous_step_id],
                        action="shortcut",
                        risk_level="low",
                        approval_required=False,
                        reason="Open the requested browser surface through an app-scoped safe shortcut.",
                    )
                )
                previous_step_id = "open-browser-internal-page"
            elif page_url:
                steps.append(
                    _step(
                        intent,
                        "focus-browser-address-bar",
                        "Focus browser address bar",
                        "desktop.app_control",
                        _first_allowed(
                            app_foreground_tool_candidates(page_mode, "safe_shortcut"),
                            allowed,
                        ),
                        input_preview={"app_name": browser_app, "action": "focus_address_bar"},
                        depends_on=[previous_step_id],
                        action="shortcut",
                        risk_level="low",
                        approval_required=False,
                        reason="Focus the browser address bar before opening the requested internal surface.",
                    )
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
            shortcut_tool = _first_allowed(
                (f"app.{palette_mode}_and_safe_shortcut", "app.focus_and_safe_shortcut"),
                allowed,
            )
            steps.append(
                _step(
                    intent,
                    "open-app-command-palette",
                    "Open app command palette",
                    "desktop.app_control",
                    shortcut_tool,
                    input_preview={"app_name": palette_app, "action": shortcut_action},
                    depends_on=["discover-desktop-state"],
                    action="shortcut",
                    risk_level="low",
                    approval_required=False,
                    reason="Open the requested app command palette with a safe app-scoped shortcut.",
                )
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
        if app_name and not operation_uses_app_tool and not focus_step_added:
            prepare_mode = _app_search_prepare_mode(intent.user_goal, mode) if app_search else mode
            steps.append(
                _step(
                    intent,
                    "open-or-focus-app",
                    "Open or focus app",
                    "desktop.app_control",
                    _first_allowed(app_control_tool_candidates(prepare_mode), allowed),
                    input_preview={"app_name": app_name},
                    depends_on=["discover-desktop-state"],
                    reason="Resolve the requested app by name at runtime.",
                )
            )
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
            search_focus_tool = _first_allowed(("desktop.safe_shortcut", "desktop.click_ui_element"), allowed)
            search_focus_preview = (
                {
                    "target": search_target,
                    "role_filter": "text",
                    "click_count": 1,
                    "limit": 80,
                }
                if search_focus_tool == "desktop.click_ui_element"
                else {"action": "find"}
            )
            search_depends_on = ["discover-desktop-state"]
            if focus_step_added:
                search_depends_on = ["focus-app-window"]
            elif app_name:
                search_depends_on = ["open-or-focus-app"]
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
            steps.append(
                _step(
                    intent,
                    "type-app-search-query",
                    "Type app search query",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.safe_type_text",), allowed),
                    input_preview={"text": search_query},
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
            else:
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
                if search_followup.get("action") == "click_first_result":
                    click_tool = _first_allowed(("desktop.click_ui_element",), allowed)
                    steps.append(
                        _step(
                            intent,
                            "select-app-search-result",
                            "Select app search result",
                            "desktop.ui_operation",
                            click_tool,
                            input_preview={
                                "target": str(search_followup.get("target") or "第一个结果"),
                                "role_filter": "",
                                "limit": 80,
                                "click_count": int(search_followup.get("click_count") or 1),
                            },
                            depends_on=[search_terminal_step_id],
                            action="click",
                            risk_level=_desktop_operation_risk_level(click_tool),
                            approval_required=_desktop_operation_approval_required(click_tool),
                            reason="Click the requested app search result after submitting the search.",
                        )
                    )
                    search_terminal_step_id = "select-app-search-result"
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
            or primary_safe_shortcut
            or safe_key
            or safe_scroll
            or safe_click
            or safe_type_text
        ) and (not foreground_submit_action or pre_submit_operation):
            operation_depends_on = ["discover-desktop-state"]
            if focus_step_added:
                operation_depends_on = ["focus-app-window"]
            elif not operation_uses_app_tool and app_name:
                operation_depends_on = ["open-or-focus-app"]
            steps.append(
                _step(
                    intent,
                    "operate-foreground-ui",
                    "Operate foreground UI",
                    "desktop.ui_operation",
                    operation_tool
                    or _first_allowed(
                        (
                            "desktop.click_ui_element",
                            "desktop.type_into_ui_element",
                            "desktop.safe_shortcut",
                            "desktop.safe_key",
                            "desktop.safe_type_text",
                        ),
                        allowed,
                    ),
                    input_preview=operation_preview,
                    risk_level=_desktop_operation_risk_level(operation_tool),
                    approval_required=_desktop_operation_approval_required(operation_tool),
                    depends_on=operation_depends_on,
                    reason="Use observable UI operations after discovery, then verify.",
                )
            )
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
                if tool_name in {"app.open", "app.focus"}:
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
                    capability_id = "desktop.app_control"
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
        return [
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
                return [
                    main_step,
                    _step(
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
                    ),
                ]
            return [
                main_step
            ]
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
        return [
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
            _step(
                intent,
                "write-research-artifact",
                "Write research artifact",
                "artifact.write",
                _first_allowed(("artifact.write",), allowed),
                input_preview={"path": "research-summary.md"},
                depends_on=["open-or-read-web"],
                reason="Persist research output for replay.",
            ),
        ]

    def _report_steps(
        self,
        intent: TaskIntentSnapshot,
        allowed: set[str] | None,
    ) -> list[ToolPlanStepSnapshot]:
        context_source = str(intent.inputs.get("context_source") or "").strip()
        if context_source:
            context_steps = _context_source_steps(
                intent,
                allowed,
                context_source,
                step_prefix="report",
                capability_id="artifact.write",
            )
            depends_on = [step.step_id for step in context_steps]
            return [
                *context_steps,
                _step(
                    intent,
                    "write-report-artifact",
                    "Write report artifact",
                    "artifact.write",
                    _first_allowed(("artifact.write",), allowed),
                    input_preview={"path": "report.md", "body_source": context_source},
                    depends_on=depends_on,
                    reason="Produce the requested durable output from the inspected source.",
                ),
            ]
        return [
            _step(
                intent,
                "gather-context",
                "Gather available context",
                "file.workspace_read",
                _first_allowed(("workspace.list", "browser.current_page", "workspace.read"), allowed),
                reason="Inspect available context before writing.",
            ),
            _step(
                intent,
                "write-report-artifact",
                "Write report artifact",
                "artifact.write",
                _first_allowed(("artifact.write",), allowed),
                input_preview={"path": "report.md"},
                depends_on=["gather-context"],
                reason="Produce the requested durable output.",
            ),
        ]

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
                "run-code-command",
                "Run code command",
                "terminal.execution",
                _first_allowed(("terminal.run",), allowed),
                risk_level="high",
                approval_required=True,
                depends_on=["inspect-workspace"],
                reason="Use terminal only when the task needs tests, builds, or scripts.",
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
        return [
            _step(
                intent,
                "inspect-file-scope",
                "Inspect file scope",
                "file.organization",
                _first_allowed(("workspace.list", "desktop.reveal_path", "desktop.open_path"), allowed),
                input_preview={"path": location_hint} if location_hint else {},
                reason="List or reveal the requested file scope before planning changes.",
            ),
            _step(
                intent,
                "write-file-organization-plan",
                "Write file organization plan",
                "artifact.write",
                _first_allowed(("artifact.write",), allowed),
                input_preview={"path": "file-organization-plan.md"},
                depends_on=["inspect-file-scope"],
                reason="Create a reviewable plan before moving, renaming, archiving, or deleting files.",
            ),
            _step(
                intent,
                "apply-file-organization",
                "Apply file organization",
                "file.organization",
                _first_allowed(("terminal.run",), allowed),
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
                tool_name
                or _first_allowed(("reminders.create", "calendar.create_event", "future_task.schedule"), allowed),
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
        if isinstance(direct_message, Mapping):
            direct_steps = _direct_communication_steps(intent, allowed, direct_message)
            if direct_steps:
                return direct_steps
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
        if context_source:
            context_steps = _context_source_steps(
                intent,
                allowed,
                context_source,
                step_prefix="communication",
                capability_id="communication.compose",
            )
            depends_on = [step.step_id for step in context_steps]
            return [
                *context_steps,
                _step(
                    intent,
                    "draft-communication-from-context",
                    "Draft communication from captured context",
                    "communication.compose",
                    compose_tool,
                    input_preview={"body_source": context_source},
                    risk_level="medium",
                    approval_required=True,
                    depends_on=depends_on,
                    reason=(
                        "Inspect the requested source before drafting the communication; "
                        "final sending remains approval-gated."
                    ),
                ),
            ]
        depends_on = [] if compose_tool == "artifact.write" else ["discover-communication-surface"]
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


def _service_step(
    intent: TaskIntentSnapshot,
    capability_id: str,
    title: str,
) -> ToolPlanStepSnapshot:
    return ToolPlanStepSnapshot(
        step_id=capability_id.replace(".", "-"),
        title=title,
        capability_id=capability_id,
        action=_service_action(capability_id),
        reason="Handled by Agent Studio service orchestration rather than a model-visible tool.",
    )


def _first_allowed(tools: Iterable[str], allowed: set[str] | None) -> str | None:
    for tool in tools:
        if allowed is None or tool in allowed:
            return tool
    return None


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
                    capability_id,
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
                    capability_id,
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
                capability_id,
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
                capability_id,
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
                capability_id,
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
                capability_id,
                tool_name,
                input_preview=_information_capture_context_payload(tool_name),
                reason="Inspect visible text before using it as task context.",
            )
        ]

    return []


def _direct_communication_steps(
    intent: TaskIntentSnapshot,
    allowed: set[str] | None,
    direct_message: Mapping[str, Any],
) -> list[ToolPlanStepSnapshot]:
    app_name = str(direct_message.get("app_name") or "").strip()
    recipient = str(direct_message.get("recipient") or "").strip()
    body = str(direct_message.get("body") or "").strip()
    body_source = str(direct_message.get("body_source") or "").strip()
    mode = str(direct_message.get("mode") or "focus").strip() or "focus"
    if (
        not app_name
        or not recipient
        or (not body and body_source not in {"clipboard", "selection", "current_page_link"})
    ):
        return []
    shortcut_tool = _first_allowed(
        app_foreground_tool_candidates(mode, "safe_shortcut"),
        allowed,
    )
    type_tool = _first_allowed(("desktop.safe_type_text",), allowed)
    search_submit_tool = _first_allowed(("desktop.search_submit",), allowed)
    send_tool = _first_allowed(("desktop.submit_foreground",), allowed)
    steps: list[ToolPlanStepSnapshot] = []
    source_step_id = ""
    if body_source == "selection":
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
    steps.extend(
        [
            _step(
                intent,
                "focus-communication-recipient-search",
                "Focus communication recipient search",
                "communication.compose",
                shortcut_tool,
                input_preview={"app_name": app_name, "action": "find"},
                action="resolve_recipient",
                depends_on=focus_depends_on,
                reason="Open the app's recipient search with a safe shortcut before drafting the message.",
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
        ]
    )
    if body_source in {"clipboard", "selection", "current_page_link"}:
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
        steps.append(
            _step(
                intent,
                "draft-communication-message",
                "Draft communication message",
                "communication.compose",
                type_tool,
                input_preview={"text": body},
                depends_on=["submit-communication-recipient-search"],
                action="draft_message",
                reason="Type only the explicit message body before the approval-gated send step.",
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
    steps.append(
        _step(
            intent,
            "focus-browser-address-bar",
            "Focus browser address bar",
            "desktop.ui_operation",
            shortcut_tool,
            input_preview={"action": "focus_address_bar"},
            depends_on=focus_depends_on,
            action="shortcut",
            reason="Use the foreground browser address bar so selected or clipboard text can be opened or searched.",
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


def _service_action(capability_id: str) -> str:
    if capability_id == "workflow.orchestration":
        return "start_workflow"
    if capability_id == "group.multi_agent":
        return "start_group_run"
    return ""


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


def _required_capabilities_for_plan(
    intent: TaskIntentSnapshot,
    steps: list[ToolPlanStepSnapshot],
) -> list[str]:
    if intent.kind == "data_analysis" and any(step.tool_name == "data.analyze" for step in steps):
        return ["data.analysis"]
    return list(intent.required_capabilities)


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
    if intent.kind == "web_research":
        browser_action = str(intent.inputs.get("browser_action") or "").strip()
        if browser_action in {"screenshot", "open_url_screenshot"}:
            return ["browser/current-page.png"]
        if browser_action:
            return []
    if not any(step.tool_name == "artifact.write" for step in steps):
        return []
    if intent.kind == "data_analysis":
        return data_analysis_artifacts_expected(intent.expected_outputs, intent.user_goal)
    if intent.kind == "web_research":
        return ["research-summary.md"]
    if intent.kind == "code_task":
        return ["code-task-summary.md"]
    if intent.kind == "file_organization":
        return ["file-organization-plan.md"]
    return ["report.md"]


def _route_to_studio(intent: TaskIntentSnapshot, steps: list[ToolPlanStepSnapshot]) -> bool:
    return (
        intent.kind in {"workflow_orchestration", "multi_agent", "data_analysis", "code_task"}
        or any(step.approval_required for step in steps)
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
        and _foreground_safe_shortcut_hint(intent.inputs.get("safe_shortcut_hint"))
    ):
        score += 0.24
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
    if intent.kind == "desktop_operation" and "window_list_hint" in intent.inputs:
        score += 0.2
    if intent.kind == "media_playback" and _contains_any(
        text,
        ["music", "song", "songs", "音乐", "歌曲", "歌"],
    ):
        score += 0.08
    if intent.kind == "media_playback" and str(intent.inputs.get("query") or "").strip():
        score += 0.08
    if intent.kind == "information_capture" and _contains_any(
        text,
        ["note", "notes", "备忘录", "笔记", "记一下", "记录一下", "记下"],
    ):
        score += 0.08
    if intent.kind == "communication" and _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        score += 0.16
    if intent.kind == "communication" and isinstance(intent.inputs.get("direct_message_hint"), Mapping):
        score += 0.18
    if intent.kind == "workflow_orchestration" and _contains_any(
        text,
        ["workflow", "flow", "工作流", "流程"],
    ):
        score += 0.26
    if intent.kind == "multi_agent" and (
        _contains_any(text, ["multi-agent", "group", "agents", "群组", "多 agent", "多Agent", "协作"])
        or _looks_like_multi_agent_request(text)
    ):
        score += 0.28
    if intent.kind in _TASK_INTENT_KINDS and _contains_any(text, _TASK_DELIVERABLE_TERMS):
        score += 0.06
    if (
        intent.kind == "data_analysis"
        and str(intent.inputs.get("context_source") or "").strip()
        and _contains_any(text, ["数据", "表格", "data", "table", "csv", "统计", "分析"])
    ):
        score += 0.38
    if (
        intent.kind == "web_research"
        and _contains_any(text, _UI_CONTROL_TERMS)
        and str(intent.inputs.get("browser_action") or "").strip() != "type_text"
    ):
        score -= 0.24
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
    if intent.kind == "web_research" and _contains_any(
        text,
        ["http://", "https://", "research", "search", "latest", "news", "调研", "研究", "新闻", "搜索", "网页", "网站"],
    ):
        score += 0.14
    if intent.kind == "web_research" and _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        score -= 0.18
    if intent.kind == "report_generation":
        if _contains_any(text, ["report", "summary", "报告", "总结", "文档", "输出", "生成"]):
            score += 0.04
        if str(intent.inputs.get("context_source") or "").strip():
            score += 0.34
        if _contains_any(text, ["http://", "https://", "research", "search", "latest", "news", "调研", "研究", "新闻", "搜索"]):
            score -= 0.04
    if intent.kind == "data_analysis" and (
        data_source_hint(text)
        or _contains_any(text, ["data analysis", "analyze data", "数据分析", "分析数据", "csv", "xlsx", "表格"])
    ):
        score += 0.08
    if intent.kind == "code_task" and _contains_any(
        text,
        ["code", "test", "bug", "build", "repo", "代码", "测试", "修复", "仓库"],
    ):
        score += 0.08
    return max(score, 0.0)


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
        ("desktop", "Desktop"),
        ("桌面", "Desktop"),
        ("documents", "Documents"),
        ("文档", "Documents"),
    )
    for marker, location in known_locations:
        if marker in lowered:
            return location
    return ""


def _looks_like_file_organization_request(text: str) -> bool:
    return _contains_any(
        text,
        [
            "organize",
            "sort",
            "clean up",
            "整理",
            "分类",
            "清理",
        ],
    ) and _contains_any(
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


def _looks_like_multi_agent_request(text: str) -> bool:
    value = _clean_prompt(text)
    lowered = value.lower()
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
        and _contains_any(value, ("分别", "各自", "并行", "协作", "汇总", "对比", "分工"))
    )


def _file_operation_hint(text: str) -> str:
    if _contains_any(text, ["delete", "remove", "trash", "删除", "移除", "清空"]):
        return "delete"
    if _contains_any(text, ["rename", "重命名", "改名"]):
        return "rename"
    if _contains_any(text, ["archive", "归档", "压缩"]):
        return "archive"
    if _contains_any(text, ["move", "移动"]):
        return "move"
    if _contains_any(text, ["sort", "organize", "整理", "分类"]):
        return "organize"
    return "inspect"


def _url_hint(text: str) -> str:
    return _explicit_browser_url_hint(text)


def _app_name_hint(text: str) -> str:
    patterns = [
        r"(?:把|将)\s*(?P<app>[\w .·-]{1,40}?)\s*(?:打开|启动|开启|切到|聚焦)(?:起来|到前台|前台)?",
        r"(?:open|launch|focus|start)\s+(?:the\s+)?(?:app|application)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"(?:bring|switch)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:to\s+(?:the\s+)?(?:front|foreground)|forward)",
        r"(?:activate)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"(?:open|launch|focus|start)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40})",
        r"(?:打开|启动|切到|聚焦)\s*(?P<app>[\w .·-]{1,40})",
        r"^(?!(?:can|could|would|please|pls|search|find|open|launch|focus|start)\b)"
        r"(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+"
        r"(?:点击|点按|按|输入|搜索|查找|click|press|tap|type|enter|search)\b",
        r"^(?!(?:在|用|通过|点击|点按))(?P<app>[\w .·-]{1,40}?)(?:点击|点按)",
        r"(?:in|inside|within|using|with)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)(?:\s+(?:to|and|then|click|press|type|search|open|create|write|play|analyze|analyse)|[.!?,]|$)",
        r"(?:^|[\s，,。])(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|来|去|打开|启动|点击|点按|按|输入|搜索|查找|检索|找|播放|创建|新建|写|发送|分析|操作|帮|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        app = _clean_app_name_hint(match.group("app"))
        if app:
            return app
    return ""


def _clean_app_name_hint(value: str) -> str:
    app = re.split(
        r"(?:并|然后|再|接着|之后|后|播放|点击|点按|按|输入|粘贴|搜索|创建|新建|重命名|上一级|显示简介|查看简介|快速查看|快速预览|预览|复制选中|写|发送|回车|确认|提交|分析|操作|查看|看看|看一下|看下|观察|识别|有没有|是否|可以|可不可以|行不行|好不好|好吗|好么|\b(?:and|then|to|paste|thanks)\b)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    app = re.sub(r"^(?:the\s+)?", "", app, flags=re.IGNORECASE).strip(" .，,。")
    called_app_match = re.match(
        r"^(?:一个|一款|这个|那个)?(?:叫|名叫|名称是|名字是)\s*(?P<app>.+?)\s*(?:的)?(?:应用(?:程序)?|软件)$",
        app,
        flags=re.IGNORECASE,
    )
    if called_app_match:
        app = called_app_match.group("app")
    app = re.sub(
        r"^(?:一个|一款|这个|那个)?(?:我(?:没|没有)提过的|新的|未知的)?"
        r"(?:应用(?:程序)?|软件|\b(?:app|application)\b)(?:叫|名叫|名称是|名字是|called|named)?\s*",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(
        r"^(?:在|用|通过|in|inside|within|using|with)\s+",
        "",
        app,
        flags=re.IGNORECASE,
    ).strip(" .，,。")
    app = re.sub(r"\s*(?:吗|嘛|呢|吧|么|\?|？)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"\s*(?:please|pls)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"\s*(?:一下|下)$", "", app).strip(" .，,。")
    app = re.sub(r"\s*(?:在|里|中|上|内)$", "", app).strip(" .，,。")
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
        "当前",
        "当前app",
        "当前应用",
        "前台应用",
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
    }
    if context_source_hint(app):
        return ""
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
    if _contains_any(value, ("发送", "send")) and _looks_like_foreground_submit_scope(value, lowered):
        return "send"
    if _contains_any(value, ("提交", "submit")) and _looks_like_foreground_submit_scope(value, lowered):
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


def _foreground_compose_text_hint(text: str) -> str:
    value = _clean_prompt(text)
    if re.search(r"(?:粘贴|paste)", value, flags=re.IGNORECASE):
        return ""
    if _looks_like_recipient_message_request(value):
        return ""
    patterns = (
        r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:打开|启动|切到|聚焦)?\s*"
        r"(?P<app>[\w .·-]{1,40}?)\s*(?:输入|键入|填写|写入|写)\s*(?P<text>[^。！？!?，,]+?)"
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


def _foreground_paste_hint(text: str) -> bool:
    value = _clean_prompt(text)
    if not re.search(r"(?:粘贴|paste)", value, flags=re.IGNORECASE):
        return False
    return bool(
        _contains_any(value, ("发送", "提交", "send", "submit"))
        or _looks_like_foreground_submit_scope(value, value.lower())
    )


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
        app = _canonical_app_name_hint(raw_app)
        if app and not _is_generic_foreground_app_label(app):
            return app
    return ""


def _clean_foreground_compose_text(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^[\"'`“”‘’]+|[\"'`“”‘’]+$", "", text).strip()
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
        or re.search(r"\b(?:send|message)\s+.+?\s+(?:to|for)\s+", value, flags=re.IGNORECASE)
    )


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


def _canonical_app_name_hint(value: str) -> str:
    app = _clean_app_name_hint(value)
    if not app:
        return ""
    return _APP_ALIASES.get(_compact_app_alias(app), app)


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
        "浏览器",
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
    compact = _compact_app_alias(app_name)
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
    compact = _compact_app_alias(app_name)
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
        "browser_forward",
        "browser_back",
        "bookmark_page",
        "show_history",
        "open_devtools",
        "focus_address_bar",
        "paste",
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


def _direct_communication_candidate_hint(text: str) -> dict[str, str]:
    source = context_source_hint(text)
    if source:
        direct_context_hint = _direct_context_communication_hint(text, source)
        if direct_context_hint:
            return direct_context_hint
    return _direct_paste_communication_hint(text) or _direct_communication_hint(text)


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
    return {}


def _direct_context_communication_hint(text: str, source: str) -> dict[str, str]:
    if source not in {"clipboard", "selection", "current_page_link"}:
        return {}
    value = _clean_prompt(text)
    source_pattern = {
        "clipboard": r"(?:剪贴板内容|粘贴板内容|clipboard\s+contents?|the\s+clipboard)",
        "selection": r"(?:选中的内容|选中内容|选中文字|选中文本|selected\s+text|selected\s+content|selection)",
        "current_page_link": r"(?:当前网页链接|当前页面链接|当前链接|current\s+page\s+link|current\s+url)",
    }[source]
    patterns = (
        rf"^(?:打开|启动|开启)?\s*(?:在|用|通过)?\s*"
        rf"(?P<app>[\w .·-]{{1,40}}?)(?:里|中|上|内)?\s*"
        rf"(?:给|发给|发送给)\s*(?P<recipient>[^：:，,。]+?)\s*"
        rf"(?:发送|发|发消息)\s*{source_pattern}$",
        rf"^(?:把|将)?\s*{source_pattern}\s*(?:通过|用|在)\s*(?P<app>[\w .·-]{{1,40}}?)\s*(?:发给|发送给|发到|发送到)\s*(?P<recipient>[^：:，,。]+)$",
        rf"^(?:把|将)?\s*{source_pattern}\s*(?:发给|发送给|发到|发送到)\s*(?P<target>[^：:，,。]+)$",
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
            return _canonical_app_name_hint(surface), value[len(surface) :].strip()
        if value.startswith(surface) and len(value) > len(surface):
            return _canonical_app_name_hint(surface), value[len(surface) :].strip()
    parts = value.split(None, 1)
    if len(parts) == 2:
        return _canonical_app_name_hint(parts[0]), _clean_communication_hint_text(parts[1])
    return "", ""


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
    return _clean_foreground_compose_text(_clean_communication_hint_text(value))


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
    if not safe_key and not safe_scroll and not safe_shortcut:
        return {}
    app_name = str(parsed.get("app_name") or "").strip()
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


def _app_scoped_followup_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    safe_followup = (
        r"(?P<followup>(?:按一下|按下|按|发送|触发|"
        r"向下|往下|朝下|向上|往上|朝上|下滑|上滑|下滚|上滚|"
        r"下翻|上翻|下一页|上一页|滚动|滚|滑动|滑|翻页|翻|拉|"
        r"复制|粘贴|全选|撤销|重做|查找|刷新|后退|前进|最大化|全屏|"
        r"新建标签页|新建窗口|新建文件夹|关闭标签页|关闭当前标签页|"
        r"显示简介|查看简介|快速查看|快速预览|预览|重命名|上一级目录|上一级|"
        r"打开开发者工具|显示开发者工具|开发者工具|"
        r"打开当前网页开发者工具|打开当前网页的开发者工具|"
        r"copy|paste|select\s+all|undo|redo|find|refresh|back|forward|"
        r"new\s+tab|new\s+window|close\s+tab|fullscreen|maximi[sz]e|"
        r"open\s+dev\s*tools|show\s+dev\s*tools|dev\s*tools|developer\s+tools).*)"
    )
    patterns: tuple[tuple[str, str], ...] = (
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?(?:把|将)\s*"
            r"(?P<app>[\w .·-]{1,40}?)\s*(?P<mode>打开|启动|开启|切到|聚焦)\s*"
            r"(?:(?:并且|并|然后|之后|后(?!退)|再|接着)\s*)?"
            rf"{safe_followup}$",
            "",
        ),
        (
            r"^(?:帮我|请|麻烦|能否|能不能|可以)?(?:直接)?"
            r"(?P<mode>打开|启动|开启|切到|聚焦)\s*(?P<app>[\w .·-]{1,40}?)\s*"
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
        app_name = _clean_app_name_hint(groups.get("app") or "")
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
        "打开",
        "启动",
        "开启",
        "切到",
        "聚焦",
        "在",
        "用",
        "通过",
        "把",
        "将",
        "please",
        "can",
        "canyou",
        "couldyou",
        "wouldyou",
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
    if not re.search(r"命令面板|指令面板|command\s+palette", value, flags=re.IGNORECASE):
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
    return {}


def _command_palette_mode(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if lowered in {"打开", "启动", "开启", "open", "launch", "start"}:
        return "open"
    return "focus"


def _command_palette_action_for_app(app_name: str) -> str:
    if _compact_app_alias(app_name) == "obsidian":
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


def _app_search_hint(text: str, app_name: str) -> dict[str, str]:
    if _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        return {}
    if _looks_like_app_search_field_input(text):
        return {}
    app = str(app_name or "").strip()
    if app and _is_browser_or_search_app_name(app):
        return {}
    query = _app_search_query_hint(text, app)
    if not query:
        parsed = _leading_app_search_hint(text)
        parsed_app = str(parsed.get("app_name") or "").strip() if parsed else ""
        if parsed and (
            not app
            or _looks_like_app_search_followup_app(app)
            or parsed_app.lower() == app.lower()
            or _compact_app_alias(app).startswith(_compact_app_alias(parsed_app))
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


def _leading_app_search_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    patterns = (
        r"^(?P<app>[\w .·-]{1,40}?)\s*(?:搜索|查找|检索|找)\s*(?P<query>[^。！？!?，,]+)$",
        r"^(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        r"^(?:search|find|look\s+up)\s+(?:in|inside|within|using|with)\s+(?:the\s+)?"
        r"(?P<app_in>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+(?:for\s+)?(?P<query_in>[^.!?,]+)$",
        r"^(?:search|find|look\s+up)\s+(?:the\s+)?"
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
    chinese_patterns = (
        rf"(?:在|用|通过)\s*{app_pattern}\s*(?:里|中|上|内)?\s*(?:搜索|查找|检索|找)\s*(?P<query>[^。！？!?，,]+)$",
        rf"(?:打开|启动|切到|聚焦)\s*{app_pattern}\s*(?:[，,]\s*)?"
        rf"(?:并|然后|再|接着|之后)?\s*(?:搜索|查找|检索|找)\s*(?P<query>[^。！？!?，,]+)$",
    )
    for pattern in chinese_patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            query = _clean_app_search_query(match.group("query"))
            if query:
                return query

    lowered = value.lower()
    english_patterns = (
        rf"\b(?:in|inside|within|using|with)\s+(?:the\s+)?{app_pattern}\s+(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        rf"\b(?:open|launch|focus|start)\s+(?:the\s+)?{app_pattern}\s+(?:and|then)?\s*(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?,]+)$",
        rf"\b(?:search|find|look\s+up)\s+(?:for\s+)?(?P<query>[^.!?,]+?)\s+(?:in|inside|within|using|with)\s+(?:the\s+)?{app_pattern}\b",
    )
    for pattern in english_patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            query = _clean_app_search_query(match.group("query"))
            if query:
                return query
    return ""


def _clean_app_search_query(query: str) -> str:
    value = re.sub(r"^[：:，,\s]+", "", str(query or "").strip())
    value = re.sub(r"[。.,，；;！!？?]+$", "", value).strip()
    value = re.split(
        r"\s*(?:并|然后|再|接着|之后|后|and\s+then|then)\s*"
        r"(?:选择|选中|点击|点按|打开|按|choose|select|click|open|press)(?:\b)?",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = re.sub(r"\s+(?:please|pls)$", "", value, flags=re.IGNORECASE).strip()
    return value


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


def _dynamic_context_browser_action_hint(text: str, context_source: str) -> dict[str, Any]:
    if context_source not in {"selection", "clipboard"}:
        return {}
    value = _clean_prompt(text)
    lowered = value.lower()
    if _looks_like_browser_current_page_find(value, lowered):
        return {}
    if _looks_like_dynamic_context_url_open(value, lowered):
        return {"browser_action": "open_url"}
    if _looks_like_dynamic_context_web_search(value, lowered):
        return {"browser_action": "open_search"}
    return {}


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
        return known_web_destination_url_hint(value)
    candidate = _clean_browser_url(domain_match.group(0))
    if not _browser_url_context_allows_domain(value, candidate):
        return ""
    return _with_browser_url_scheme(candidate)


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
    return hint


def _web_search_query(text: str) -> str:
    if _url_hint(text):
        return ""
    direct_engine_query = _direct_web_search_query(text)
    if direct_engine_query:
        return direct_engine_query
    search_surface = _web_search_surface_hint(text)
    if search_surface and not _is_browser_or_search_app_name(search_surface):
        return ""
    app_name = _app_name_hint(text)
    if app_name and not search_surface and not _is_browser_or_search_app_name(app_name):
        return ""
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
        r"(?:研究|调研|了解|查)(?:一下|下|查)?\s*(.+)$",
        r"(?:用\s*)?(?:浏览器|Google|谷歌)\s*(?:搜索|查找)\s*(.+)$",
        r"(?:搜索|查找|检索)\s*(.+)$",
    )
    for pattern in chinese_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            query = _clean_web_search_query(match.group(1))
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
        r"\b(?:google|baidu)\s+(?P<query>[^.!?,]+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        query = _clean_web_search_query(match.group("query"))
        if query:
            return query
    return ""


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
        r"\b(?:and|then)\s+(?:open|click|visit|select|choose)\s+(?:the\s+)?"
        r"(?P<rank_en>first|1st)\s+(?:search\s+)?(?:result|link|item)\b",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return {}
    rank = match.groupdict().get("rank") or match.groupdict().get("rank_en") or ""
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
            return str(match.group("surface") or "").strip()
    return ""


def _is_browser_or_search_app_name(app_name: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(app_name or "").strip().lower())
    return normalized in {
        "browser",
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


def _clean_web_search_query(query: str) -> str:
    value = re.sub(r"^[：:，,\s]+", "", str(query or "").strip())
    value = re.sub(
        r"\s+(?:and|then)\s+(?:write|create|generate|produce|summari[sz]e).*$",
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
        r"\s*(?:并|然后|并且|再|接着|之后|后)?\s*"
        r"(?:打开|点击|点一下|点按|进入|访问|选择|选中)\s*"
        r"(?:第?一个|第一条|首个|第1个|第1条|1)\s*(?:搜索结果|结果|链接|条目).*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(
        r"(?:并|然后|并且|再)?(?:输出|生成|写|写出|整理|总结|汇总)(?:一份|一下|成)?"
        r"(?:报告|总结|文档|结果)?$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    value = re.sub(r"[。.,，；;！!？?]+$", "", value).strip()
    value = re.sub(r"\s+(?:please|pls)$", "", value, flags=re.IGNORECASE).strip()
    if not value:
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
    if rank_match:
        rank = rank_match.groupdict().get("rank") or rank_match.groupdict().get("rank_en") or ""
        index = _browser_search_result_rank_index(rank)
        if index:
            return {
                "browser_action": "click",
                "selector": f"search-result={index}",
                "click_count": 1,
            }
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
        return {
            "browser_action": "type_text",
            "selector": _browser_input_selector_from_target(target),
            "text": typed_text,
        }
    return {}


def _has_browser_page_context(text: str) -> bool:
    return bool(
        re.search(r"(?:网页|页面|浏览器|当前页)", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:browser|page|webpage|web\s+page)\b", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:search\s+)?(?:result|link)s?\b", text, flags=re.IGNORECASE)
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
            r"\bwhat(?:'s|\s+is)\s+(?:this|the\s+current|current)"
            r"\s+(?:web\s*)?page\s+about\b",
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
        return "desktop.list_apps", {}
    return None, {}


def _looks_like_desktop_permissions_request(value: str, lowered: str) -> bool:
    return bool(
        re.search(r"(?:桌面|本地|自动化|辅助功能|屏幕录制|读取屏幕).{0,16}(?:权限|授权|permission)", value, flags=re.IGNORECASE)
        or re.search(r"(?:需要|缺少|检查|诊断|修复).{0,16}(?:权限|授权)", value)
        or re.search(r"(?:为什么|为何|why).{0,24}(?:不能|无法|can't|cannot).{0,24}(?:打开|点击|读取屏幕|控制|操作|open|click|control)", value, flags=re.IGNORECASE)
        or re.search(r"\b(?:desktop|local|accessibility|screen recording)\s+permissions?\b", lowered)
    )


def _looks_like_active_window_request(value: str, lowered: str) -> bool:
    if re.search(r"我现在是不是在家", value):
        return False
    return bool(
        re.search(r"(?:当前|现在|前台).{0,8}(?:窗口|应用|app).{0,8}(?:是什么|是哪个|是不是)", value, flags=re.IGNORECASE)
        or re.search(r"(?:当前|现在)?前台是不是\s*.+", value, flags=re.IGNORECASE)
        or re.search(r"现在是不是在\s*.+", value, flags=re.IGNORECASE)
        or re.search(r"我正在用什么(?:应用|app|软件)?", value, flags=re.IGNORECASE)
        or re.search(r"\bwhat\s+app\s+am\s+i\s+using\b", lowered)
        or re.search(r"\bwhat\s+is\s+(?:the\s+)?(?:frontmost|active|foreground)\s+window\b", lowered)
        or re.search(r"\bwhich\s+(?:app|application)\s+is\s+(?:frontmost|active|foreground)\b", lowered)
        or re.search(r"\bis\s+.+\s+(?:frontmost|the\s+active\s+app|the\s+active\s+application)\b", lowered)
        or re.search(r"\bis\s+(?:the\s+)?(?:active|frontmost|foreground)\s+(?:app|application)\s+.+", lowered)
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


def _looks_like_ui_operation(text: str) -> bool:
    return _contains_any(
        text,
        ["click", "type", "press", "shortcut", "scroll", "点击", "输入", "按", "快捷键", "滚动", "发送"],
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
        shortcut_tool = _first_allowed(("desktop.safe_shortcut",), allowed)
        if shortcut_tool:
            return shortcut_tool, dict(safe_shortcut)
    if safe_key:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "safe_key"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **safe_key}
        key_tool = _first_allowed(("desktop.safe_key",), allowed)
        if key_tool:
            return key_tool, dict(safe_key)
    if safe_scroll:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "safe_scroll"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **safe_scroll}
        scroll_tool = _first_allowed(("desktop.safe_scroll",), allowed)
        if scroll_tool:
            return scroll_tool, dict(safe_scroll)
    if safe_click:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "safe_click"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **safe_click}
        click_tool = _first_allowed(("desktop.safe_click",), allowed)
        if click_tool:
            return click_tool, dict(safe_click)
    if hotkey:
        if app_name and allow_app_tools:
            app_tool = _first_allowed(app_foreground_tool_candidates(mode, "hotkey"), allowed)
            if app_tool:
                return app_tool, {"app_name": app_name, **hotkey}
        return _first_allowed(("desktop.hotkey",), allowed), dict(hotkey)
    if app_name and type_target:
        if allow_app_tools:
            app_tool = _first_allowed(
                app_foreground_tool_candidates(mode, "type_into_ui_element"),
                allowed,
            )
            if app_tool:
                return app_tool, {"app_name": app_name, **type_target, "limit": 80}
        return _first_allowed(("desktop.type_into_ui_element",), allowed), {**type_target, "limit": 80}
    if app_name and safe_type_text:
        if allow_app_tools:
            app_tool = _first_allowed(
                app_foreground_tool_candidates(mode, "safe_type_text"),
                allowed,
            )
            if app_tool:
                return app_tool, {"app_name": app_name, "text": safe_type_text}
        return _first_allowed(("desktop.safe_type_text",), allowed), {"text": safe_type_text}
    if app_name and click_target:
        if allow_app_tools:
            app_tool = _first_allowed(
                app_foreground_tool_candidates(mode, "click_ui_element"),
                allowed,
            )
            if app_tool:
                return app_tool, {"app_name": app_name, **click_target, "limit": 80}
        return _first_allowed(("desktop.click_ui_element",), allowed), {**click_target, "limit": 80}
    if type_target:
        return _first_allowed(("desktop.type_into_ui_element",), allowed), {**type_target, "limit": 80}
    if safe_type_text:
        return _first_allowed(("desktop.safe_type_text",), allowed), {"text": safe_type_text}
    if click_target:
        return _first_allowed(("desktop.click_ui_element",), allowed), {**click_target, "limit": 80}
    return None, {}


def _expected_outputs(text: str, *, default: list[str]) -> list[str]:
    outputs = []
    if _contains_any(text, ["chart", "plot", "图表", "可视化"]):
        outputs.append("chart")
    if _contains_any(text, ["report", "报告"]):
        outputs.append("report")
    if _contains_any(text, ["output csv", "export csv", "csv 汇总", "输出 csv", "导出 csv", "表格汇总"]):
        outputs.append("table")
    return outputs or list(default)
