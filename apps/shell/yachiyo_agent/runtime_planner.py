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
    media_playback_hint,
    media_tool_preview,
    safe_click_hint,
    safe_key_hint,
    safe_scroll_hint,
    safe_type_text_hint,
    safe_shortcut_hint,
    screen_capture_hint,
    submit_action_hint,
    type_into_ui_hint,
    ui_inspection_hint,
    window_list_hint,
)
from .file_access_plan_hints import file_access_hint
from .schedule_plan_hints import schedule_context_source_hint, schedule_tool_preview
from .system_plan_hints import system_control_hint, system_tool_preview


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
        has_source = bool(source_hint)
        if score <= 0 and has_source and _contains_any(text, ["分析", "统计", "汇总", "可视化"]):
            score = 0.16
        if score <= 0:
            return _empty_intent("data_analysis", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "data_analysis", text),
            kind="data_analysis",
            title="Data Analysis",
            user_goal=text,
            confidence=min(0.95, 0.48 + score),
            description="Analyze structured data and produce a report or artifact.",
            inputs={
                "data_source_hint": source_hint,
                "data_source_kind": data_source_kind_hint(source_hint, text),
            },
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
        ui_inspection = ui_inspection_hint(text)
        screen_capture = screen_capture_hint(text)
        app_management = app_management_hint(text)
        foreground_management = foreground_management_hint(text)
        safe_shortcut = safe_shortcut_hint(text)
        safe_key = safe_key_hint(text)
        safe_scroll = safe_scroll_hint(text)
        safe_click = safe_click_hint(text)
        desktop_discovery = _desktop_discovery_hint(text)
        context_source = context_source_hint(text)
        app_scoped_desktop_operation = _app_scoped_desktop_operation_hint(text)
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
            ],
        )
        if score <= 0 and app_scoped_desktop_operation:
            score = 0.18
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
            and safe_key is None
            and safe_scroll is None
            and safe_click is None
            and desktop_discovery is None
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
        app_name_hint = str(
            (focus_window or {}).get("app_name")
            or (window_list or {}).get("app_name")
            or (ui_inspection or {}).get("app_name")
            or (screen_capture or {}).get("app_name")
            or (app_management or {}).get("app_name")
            or _app_name_hint(text)
            or ""
        ).strip()
        if _safe_shortcut_targets_foreground(text, safe_shortcut, app_name_hint):
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
        if not app_name_hint and app_search.get("app_name"):
            app_name_hint = str(app_search.get("app_name") or "").strip()
        operation_hint = str((desktop_discovery or {}).get("action") or "") or _desktop_operation_hint(text)
        if (
            context_source in {"selection", "clipboard"}
            and _dynamic_context_browser_action_hint(text, context_source)
            and ui_inspection is None
            and screen_capture is None
            and app_management is None
            and foreground_management is None
            and safe_shortcut is None
            and safe_key is None
            and safe_scroll is None
            and safe_click is None
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
            and safe_key is None
            and safe_scroll is None
            and safe_click is None
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
        if spotlight_search_query:
            inputs["spotlight_search_hint"] = {"query": spotlight_search_query}
        if foreground_management is not None:
            inputs["foreground_management_hint"] = foreground_management
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
        if _app_scoped_desktop_operation_hint(text):
            return _empty_intent("web_research", text)
        dynamic_source = source if source in {"clipboard", "selection"} else ""
        browser_action = (
            _browser_current_page_find_hint(text, dynamic_source)
            or _browser_current_page_hint(text)
            or _dynamic_context_browser_action_hint(text, dynamic_source)
            or _browser_url_action_hint(text, dynamic_source)
            or _web_search_hint(text, dynamic_source)
        )
        score = _score_terms(
            text,
            [
                "research",
                "search web",
                "search",
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
            risk_level="low" if browser_action else "medium",
        )

    def _report_generation_intent(
        self,
        text: str,
        metadata: Mapping[str, Any],
    ) -> TaskIntentSnapshot:
        score = _score_terms(text, ["report", "write up", "summary", "deck", "报告", "总结", "汇报", "文档"])
        if score <= 0:
            return _empty_intent("report_generation", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "report_generation", text),
            kind="report_generation",
            title="Report Generation",
            user_goal=text,
            confidence=min(0.85, 0.34 + score),
            description="Produce a written artifact from available context or gathered inputs.",
            expected_outputs=_expected_outputs(text, default=["report"]),
            required_capabilities=["artifact.write"],
            preferred_capabilities=["file.workspace_read", "browser.research", "data.analysis"],
            risk_level="low",
        )

    def _code_task_intent(self, text: str, metadata: Mapping[str, Any]) -> TaskIntentSnapshot:
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
        if _explicit_browser_url_hint(text):
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
        source = context_source_hint(text)
        direct_hint = (
            _direct_context_communication_hint(text, source)
            if source
            else _direct_communication_hint(text)
        )
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
        return [
            _step(
                intent,
                "inspect-data-source",
                "Inspect data source",
                "file.workspace_read",
                _first_allowed(("workspace.read", "workspace.list"), allowed),
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
        safe_key = safe_key_hint(intent.user_goal)
        safe_scroll = safe_scroll_hint(intent.user_goal)
        safe_click = safe_click_hint(intent.user_goal)
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
        spotlight_search = intent.inputs.get("spotlight_search_hint")
        if not isinstance(spotlight_search, Mapping):
            spotlight_query = _spotlight_search_query_hint(intent.user_goal)
            spotlight_search = {"query": spotlight_query} if spotlight_query else {}
        app_name = str(
            (focus_window or {}).get("app_name")
            or (window_list or {}).get("app_name")
            or (ui_inspection or {}).get("app_name")
            or (screen_capture or {}).get("app_name")
            or (app_management or {}).get("app_name")
            or intent.inputs.get("app_name_hint")
            or app_search.get("app_name")
            or ""
        ).strip()
        if _safe_shortcut_targets_foreground(intent.user_goal, safe_shortcut, app_name):
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
        click_target = click_target_hint(intent.user_goal)
        hotkey = hotkey_hint(intent.user_goal)
        type_target = type_into_ui_hint(intent.user_goal, app_name=app_name)
        safe_type_text = "" if type_target else safe_type_text_hint(intent.user_goal)
        submit_action = submit_action_hint(intent.user_goal)
        if click_target and not any((type_target, safe_type_text, app_search)):
            submit_action = ""
        followup_safe_shortcut = safe_shortcut if safe_type_text and safe_shortcut else None
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
        if app_search:
            search_query = str(app_search.get("query") or "").strip()
            search_target = str(app_search.get("target") or "").strip() or "Search"
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
            steps.append(
                _step(
                    intent,
                    "submit-app-search",
                    "Submit app search",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.search_submit",), allowed),
                    input_preview={},
                    depends_on=["type-app-search-query"],
                    action="submit",
                    risk_level="low",
                    approval_required=False,
                    reason="Submit the app search with the dedicated safe search submit tool.",
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
                        operation_preview={},
                    ),
                    depends_on=["submit-app-search"],
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
        ):
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
        if followup_safe_shortcut and any(step.step_id == "operate-foreground-ui" for step in steps):
            steps.append(
                _step(
                    intent,
                    "operate-foreground-ui-followup",
                    "Operate foreground UI",
                    "desktop.ui_operation",
                    _first_allowed(("desktop.safe_shortcut",), allowed),
                    input_preview=dict(followup_safe_shortcut),
                    depends_on=["operate-foreground-ui"],
                    reason="Run the requested follow-up safe shortcut after the explicit foreground input.",
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
        elif any(step.step_id == "operate-foreground-ui-followup" for step in steps):
            verify_depends_on = ["operate-foreground-ui-followup"]
        elif any(step.step_id == "operate-foreground-ui" for step in steps):
            verify_depends_on = ["operate-foreground-ui"]
        elif any(step.step_id == "focus-app-window" for step in steps):
            verify_depends_on = ["focus-app-window"]
        elif any(step.step_id == "open-or-focus-app" for step in steps):
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
                "open_search": "browser.open_url",
                "open_url": "browser.open_url",
                "open_url_extract": "browser.open_url_and_extract_text",
                "open_url_screenshot": "browser.open_url_and_screenshot",
            }.get(browser_action)
            input_preview: dict[str, Any] = {}
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
            return [
                _step(
                    intent,
                    {
                        "current_page": "read-current-page",
                        "extract_text": "extract-current-page-text",
                        "screenshot": "capture-current-page",
                        "open_search": "open-web-search",
                        "open_url": "open-web-url",
                        "open_url_extract": "extract-web-url-text",
                        "open_url_screenshot": "capture-web-url",
                    }.get(browser_action, "read-current-page"),
                    {
                        "current_page": "Read current page",
                        "extract_text": "Extract current page text",
                        "screenshot": "Capture current page",
                        "open_search": "Open web search",
                        "open_url": "Open web URL",
                        "open_url_extract": "Open and extract web URL",
                        "open_url_screenshot": "Open and capture web URL",
                    }.get(browser_action, "Read current page"),
                    "browser.research",
                    _first_allowed((tool_name,), allowed) if tool_name else None,
                    input_preview=input_preview,
                    risk_level="low",
                    approval_required=False,
                    reason="Use the explicit current-page browser tool instead of desktop screen automation.",
                )
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
    if not source_hint or source_hint.startswith(("/", "~")):
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


def _intent_rank_score(intent: TaskIntentSnapshot, text: str) -> float:
    score = float(intent.confidence or 0)
    if (
        intent.kind == "desktop_operation"
        and _contains_any(text, _TASK_DELIVERABLE_TERMS)
        and not _looks_like_ui_operation(text)
    ):
        score -= 0.16
    if intent.kind == "desktop_operation" and _looks_like_ui_operation(text):
        score += 0.08
    if (
        intent.kind == "desktop_operation"
        and _foreground_safe_shortcut_hint(intent.inputs.get("safe_shortcut_hint"))
    ):
        score += 0.24
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
    if intent.kind in _TASK_INTENT_KINDS and _contains_any(text, _TASK_DELIVERABLE_TERMS):
        score += 0.06
    if intent.kind == "web_research" and _contains_any(text, _UI_CONTROL_TERMS):
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
    if intent.kind == "web_research" and _contains_any(
        text,
        ["http://", "https://", "research", "search", "调研", "搜索", "网页", "网站"],
    ):
        score += 0.14
    if intent.kind == "web_research" and _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        score -= 0.18
    if intent.kind == "report_generation":
        if _contains_any(text, ["report", "summary", "报告", "总结", "文档", "输出", "生成"]):
            score += 0.04
        if _contains_any(text, ["http://", "https://", "research", "search", "调研", "搜索"]):
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
        r"(?:in|inside|within|using|with)\s+(?P<app>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)(?:\s+(?:to|and|then|click|press|type|search|open|create|write|play|analyze|analyse)|[.!?,]|$)",
        r"(?:^|[\s，,。])(?:在|用|通过)\s*(?P<app>[\w .·-]{1,40}?)(?:里|中|上|内|来|去|打开|启动|点击|点按|按|输入|搜索|播放|创建|新建|写|发送|分析|操作|帮|$)",
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
        r"(?:并|然后|再|接着|之后|后|and|then|to|播放|点击|点按|按|输入|粘贴|搜索|创建|新建|写|发送|分析|操作|查看|看看|看一下|看下|观察|识别|有没有|是否|可以|可不可以|行不行|好不好|好吗|好么|paste|thanks)",
        str(value or "").strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    app = re.sub(r"^(?:the\s+)?", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"\s*(?:吗|嘛|呢|吧|么|\?|？)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"\s*(?:please|pls)$", "", app, flags=re.IGNORECASE).strip(" .，,。")
    app = re.sub(r"\s*(?:一下|下)$", "", app).strip(" .，,。")
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


def _desktop_operation_hint(text: str) -> str:
    safe_key = safe_key_hint(text)
    if safe_key:
        return "safe_key"
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
        "new_private_window",
        "close_tab",
        "next_tab",
        "previous_tab",
        "reopen_closed_tab",
        "browser_forward",
        "browser_back",
        "bookmark_page",
        "show_history",
        "open_devtools",
        "focus_address_bar",
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
            rf"(?:在|用|通过)\s*{re.escape(app_name)}(?:里|中|上|内|来|去|打开|启动|点击|点按|按|输入|搜索|播放|创建|新建|写|发送|分析|操作|帮|$)",
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


def _direct_communication_hint(text: str) -> dict[str, str]:
    value = _clean_prompt(text)
    patterns = (
        (
            r"^(?:打开|启动|开启)?\s*(?P<app>[\w .·-]{1,40}?)\s*"
            r"(?:发消息|发送|发)\s*(?:给|到)?\s*(?P<recipient>[^：:，,。]+?)"
            r"\s*[:：]\s*(?P<body>.+)$"
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
        app_name = _clean_app_name_hint(groups.get("app") or "")
        recipient = _clean_communication_hint_text(groups.get("recipient") or "")
        body = _clean_communication_hint_text(groups.get("body") or "")
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
        rf"^(?P<app>[\w .·-]{{1,40}}?)\s*(?:给|发给|发送给)\s*(?P<recipient>[^：:，,。]+?)\s*(?:发送|发|发消息)\s*{source_pattern}$",
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
        app_name = _clean_app_name_hint(groups.get("app") or "")
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
            return surface, value[len(surface) :].strip()
        if value.startswith(surface) and len(value) > len(surface):
            return surface, value[len(surface) :].strip()
    parts = value.split(None, 1)
    if len(parts) == 2:
        return _clean_app_name_hint(parts[0]), _clean_communication_hint_text(parts[1])
    return "", ""


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


def _app_scoped_desktop_operation_hint(text: str) -> bool:
    app_name = _app_name_hint(text)
    if app_name and _is_browser_or_search_app_name(app_name):
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


def _app_search_hint(text: str, app_name: str) -> dict[str, str]:
    if _contains_any(text, _COMMUNICATION_ACTION_TERMS):
        return {}
    if _looks_like_app_search_field_input(text):
        return {}
    app = str(app_name or "").strip()
    if app and _is_browser_or_search_app_name(app):
        return {}
    query = _app_search_query_hint(text, app)
    if not query and not app:
        parsed = _leading_app_search_hint(text)
        if parsed:
            return parsed
    if not query:
        return {}
    return {
        "query": query,
        "target": "搜索" if _contains_any(text, ("搜索", "查找", "检索", "找")) else "Search",
    }


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
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if not match:
            continue
        app_name = _clean_app_name_hint(match.group("app"))
        if not app_name or _is_browser_or_search_app_name(app_name):
            continue
        query = _clean_app_search_query(match.group("query"))
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
        rf"(?:打开|启动|切到|聚焦)\s*{app_pattern}\s*(?:并|然后|再|接着|之后)?\s*(?:搜索|查找|检索|找)\s*(?P<query>[^。！？!?，,]+)$",
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
    value = re.sub(r"\s+(?:please|pls)$", "", value, flags=re.IGNORECASE).strip()
    return value


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
    return {
        "browser_action": "open_search",
        "query": query,
        "url_hint": _web_search_url(engine, query),
    }


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
    if app_name and not _is_browser_or_search_app_name(app_name):
        return ""
    lowered = text.lower()
    patterns = (
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


def _web_search_url(engine: str, query: str) -> str:
    if str(engine or "").strip().lower() == "baidu":
        return f"https://www.baidu.com/s?wd={quote_plus(query)}"
    return f"https://www.google.com/search?q={quote_plus(query)}"


def _web_search_surface_hint(text: str) -> str:
    match = re.search(
        r"\b(?:can\s+you\s+)?search\s+(?P<surface>[A-Za-z][A-Za-z0-9 ._-]{1,40}?)\s+for\s+.+$",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return str(match.group("surface") or "").strip()


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
        "spotlight",
    }


def _clean_web_search_query(query: str) -> str:
    value = re.sub(r"^[：:，,\s]+", "", str(query or "").strip())
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
        or re.search(r"\bextract\s+(?:the\s+)?(?:current|this)\s+page\s+text\b", lowered)
    )


def _looks_like_browser_current_page_summary(value: str, lowered: str) -> bool:
    return _contains_any(value, ("总结", "摘要", "概括")) or bool(
        re.search(r"\bsummari[sz]e|summary\b", lowered)
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
        or re.search(r"\bshow\s+installed\s+apps?\b", lowered)
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
