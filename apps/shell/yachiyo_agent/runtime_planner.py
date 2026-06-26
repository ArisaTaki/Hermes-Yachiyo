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

from .capture_plan_hints import capture_note_hint, capture_tool_preview
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
        ):
            return _empty_intent("desktop_operation", text)
        focus_window = focus_window_hint(text)
        window_list = window_list_hint(text)
        app_name_hint = str(
            (focus_window or {}).get("app_name")
            or (window_list or {}).get("app_name")
            or (ui_inspection or {}).get("app_name")
            or (screen_capture or {}).get("app_name")
            or (app_management or {}).get("app_name")
            or _app_name_hint(text)
            or ""
        ).strip()
        operation_hint = _desktop_operation_hint(text)
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
        score = _score_terms(
            text,
            ["research", "search web", "website", "url", "http", "web page", "网页", "网站", "搜索", "调研"],
        )
        if score <= 0:
            return _empty_intent("web_research", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "web_research", text),
            kind="web_research",
            title="Web Research",
            user_goal=text,
            confidence=min(0.9, 0.38 + score),
            description="Open, read, and summarize web content.",
            inputs={"url_hint": _url_hint(text)},
            expected_outputs=_expected_outputs(text, default=["summary"]),
            required_capabilities=["browser.research"],
            preferred_capabilities=["artifact.write"],
            risk_level="medium",
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
        score = _score_terms(text, ["email", "message", "mail", "send to", "邮件", "消息", "发给", "发送"])
        if score <= 0:
            return _empty_intent("communication", text)
        return TaskIntentSnapshot(
            intent_id=_stable_id("intent", "communication", text),
            kind="communication",
            title="Communication",
            user_goal=text,
            confidence=min(0.82, 0.34 + score),
            description="Draft or send communication through available apps or tools.",
            required_capabilities=["communication.compose"],
            preferred_capabilities=[
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
                        "Use the built-in local parser for straightforward CSV, TSV, JSON, XLSX, "
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
        app_name = str(
            (focus_window or {}).get("app_name")
            or (window_list or {}).get("app_name")
            or (ui_inspection or {}).get("app_name")
            or (screen_capture or {}).get("app_name")
            or (app_management or {}).get("app_name")
            or intent.inputs.get("app_name_hint")
            or ""
        ).strip()
        mode = app_control_mode(intent.user_goal)
        click_target = click_target_hint(intent.user_goal)
        hotkey = hotkey_hint(intent.user_goal)
        type_target = type_into_ui_hint(intent.user_goal, app_name=app_name)
        safe_type_text = "" if type_target else safe_type_text_hint(intent.user_goal)
        submit_action = submit_action_hint(intent.user_goal)
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
        if (
            not app_name
            and screen_capture is not None
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
                        _first_allowed(app_control_tool_candidates("focus"), allowed),
                        input_preview={"app_name": app_name},
                        depends_on=["discover-desktop-state"],
                        reason="Focus the requested app before reading its foreground UI.",
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
                        _first_allowed(app_control_tool_candidates("focus"), allowed),
                        input_preview={"app_name": app_name},
                        depends_on=["discover-desktop-state"],
                        reason="Focus the requested app before capturing its visible state.",
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
                    depends_on=["discover-desktop-state"],
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
            steps.append(
                _step(
                    intent,
                    "open-or-focus-app",
                    "Open or focus app",
                    "desktop.app_control",
                    _first_allowed(app_control_tool_candidates(mode), allowed),
                    input_preview={"app_name": app_name},
                    depends_on=["discover-desktop-state"],
                    reason="Resolve the requested app by name at runtime.",
                )
            )
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
        url = str(intent.inputs.get("url_hint") or "").strip()
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
    if capability_id == "data.analysis":
        return "analyze_data_file" if tool_name == "data.analyze" else "run_python_analysis"
    if capability_id == "artifact.write":
        return "write_artifact"
    if capability_id in {"file.workspace_read", "file.organization"}:
        return "inspect_paths" if capability_id == "file.organization" else "read_file"
    if capability_id == "browser.research":
        return "extract_text" if tool_name and "extract_text" in tool_name else "open_url"
    if capability_id == "media.playback":
        return "play"
    if capability_id == "system.control":
        return "control_system"
    if capability_id == "schedule.reminder":
        return "schedule_task"
    if capability_id == "information.capture":
        return _information_capture_action(tool_name)
    if capability_id == "communication.compose":
        return "draft_message"
    if capability_id == "clipboard.read_write":
        return "read_clipboard" if tool_name == "clipboard.read" else "write_clipboard"
    return ""


def _information_capture_action(tool_name: str | None) -> str:
    clean_tool = str(tool_name or "")
    if clean_tool == "notes.create":
        return "create_note"
    if clean_tool == "clipboard.read":
        return "read_clipboard"
    if clean_tool == "desktop.safe_shortcut":
        return "shortcut"
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
    if source_kind not in {"csv", "tsv", "json", "xlsx", "text", "text_table"}:
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
    if intent.kind in _TASK_INTENT_KINDS and _contains_any(text, _TASK_DELIVERABLE_TERMS):
        score += 0.06
    if intent.kind == "web_research" and _contains_any(text, _UI_CONTROL_TERMS):
        score -= 0.24
    if intent.kind == "web_research" and _contains_any(
        text,
        ["http://", "https://", "research", "search", "调研", "搜索", "网页", "网站"],
    ):
        score += 0.14
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
    match = re.search(r"https?://[^\s)]+", text)
    return match.group(0) if match else ""


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
        r"(?:并|然后|再|接着|之后|后|and|then|to|播放|点击|点按|按|输入|搜索|创建|新建|写|发送|分析|操作|查看|看看|看一下|看下|观察|识别|有没有|是否|可以|可不可以|行不行|好不好|好吗|好么|谢谢|thanks)",
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
        "屏幕",
        "界面",
        "画面",
    }
    return "" if app.lower() in generic else app


def _desktop_operation_hint(text: str) -> str:
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
    if safe_shortcut_hint(text):
        return "safe_shortcut"
    if safe_key_hint(text):
        return "safe_key"
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
