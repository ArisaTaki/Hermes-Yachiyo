"""Chat-facing AgentTask public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .approval_event_snapshots import (
    approval_snapshots_from_events,
    merge_approval_snapshot_lists,
)
from .approvals import approval_cards_from_payloads
from .artifact_event_snapshots import (
    artifact_snapshots_from_events,
    merge_artifact_snapshot_lists,
)
from .artifacts import artifact_snapshots_from_payloads
from .contracts import AgentTaskSnapshot, PublicRunEvent
from .events import public_run_event_from_payload
from .links import studio_run_url
from .tool_call_snapshots import tool_call_snapshots_from_payloads

_ACTIVE_TASK_STATUSES = {"queued", "running", "waiting_approval"}
_PLANNED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_planned"
_UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_unavailable"
_APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_approval_required"
_COMPLETED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_completed"
_TOOL_CALL_EVENT_TYPE = "agent.tool.call"
_DESKTOP_TOOL_PROGRESS_LABELS = {
    "screen.capture": "截取屏幕",
    "desktop.permissions": "检查桌面权限",
    "desktop.active_window": "读取当前窗口",
    "desktop.running_apps": "读取运行中应用",
    "desktop.windows": "读取窗口列表",
    "app.status": "检查应用状态",
    "app.open": "打开应用",
    "app.focus": "聚焦应用",
    "app.focus_window": "聚焦应用窗口",
    "app.show": "显示应用",
    "app.hide": "隐藏应用",
    "app.minimize": "最小化应用",
    "app.quit": "退出应用",
    "desktop.reveal_path": "在 Finder 中显示",
    "desktop.open_path": "打开本地路径",
    "media.apple_music_play": "播放 Apple Music",
    "media.apple_music_control": "控制 Apple Music",
    "desktop.hide_app": "隐藏当前应用",
    "desktop.minimize_window": "最小化当前窗口",
    "desktop.close_window": "关闭当前窗口",
    "desktop.hotkey": "发送快捷键",
    "desktop.type_text": "输入前台文字",
    "desktop.click": "点击前台界面",
    "browser.open_url": "打开网页",
    "browser.current_page": "读取当前网页",
    "browser.extract_text": "提取网页文本",
    "browser.screenshot": "截取网页",
    "browser.click": "点击网页元素",
    "browser.type_text": "填写网页输入",
}


def agent_task_snapshot_from_payload(
    payload: Mapping[str, Any] | AgentTaskSnapshot,
) -> AgentTaskSnapshot:
    if isinstance(payload, AgentTaskSnapshot):
        return payload

    task_id = _text(payload.get("task_id") or payload.get("run_id"))
    run_id = _text(payload.get("run_id") or task_id)
    group_run_id = _group_run_id(payload)
    recent_events = _chat_visible_events(
        run_events_from_payload(
            payload,
            run_id=run_id,
            keys=("recent_events", "events", "timeline"),
        )
    )
    approvals = [
        approval
        for approval in approval_snapshots_from_payload(
            payload,
            run_id=run_id,
            group_run_id=group_run_id,
            keys=("pending_approvals", "pending_approval"),
            events=recent_events,
        )
        if approval.status == "pending"
    ]
    status = task_status_from_value(payload.get("status"))
    current_step = _optional_text(payload.get("current_step"))
    progress_text = _optional_text(payload.get("progress_text"))
    derived_progress = _desktop_intent_progress_text(
        recent_events,
        task_status=status,
        has_explicit_progress=bool(current_step or progress_text),
    )

    return AgentTaskSnapshot(
        task_id=task_id,
        conversation_id=_optional_text(payload.get("conversation_id") or payload.get("session_id")),
        title=_text(payload.get("title") or payload.get("user_goal") or "Yachiyo task"),
        status=status,
        summary=_optional_text(payload.get("summary") or payload.get("result")),
        current_step=current_step or derived_progress,
        progress_text=progress_text or derived_progress,
        needs_user_action=bool(payload.get("needs_user_action") or approvals),
        pending_approvals=approvals,
        recent_events=recent_events,
        tool_calls=tool_call_snapshots_from_payloads(
            payload.get("tool_calls"),
            run_id=run_id,
            events=recent_events,
        ),
        artifacts=artifact_snapshots_from_task_payload(
            payload,
            run_id=run_id,
            events=recent_events,
        ),
        open_in_studio_url=_optional_text(payload.get("open_in_studio_url"))
        or studio_run_url(run_id, group_run_id=group_run_id),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def agent_task_snapshots_from_payloads(payloads: Any) -> list[AgentTaskSnapshot]:
    if not isinstance(payloads, list):
        return []
    return [agent_task_snapshot_from_payload(item) for item in payloads]


def run_events_from_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    keys: tuple[str, ...],
) -> list[PublicRunEvent]:
    raw_events = []
    for key in keys:
        value = payload.get(key)
        if value:
            raw_events = value
            break
    return [
        public_run_event_from_payload(event, run_id=run_id, sequence=index + 1)
        for index, event in enumerate(raw_events if isinstance(raw_events, list) else [])
    ]


def approval_snapshots_from_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    group_run_id: str = "",
    keys: tuple[str, ...],
    events: list[PublicRunEvent] | None = None,
):
    for key in keys:
        approvals = approval_cards_from_payloads(
            payload.get(key),
            run_id=run_id,
            group_run_id=group_run_id,
        )
        if approvals:
            return merge_approval_snapshot_lists(
                approvals,
                approval_snapshots_from_events(events or [], group_run_id=group_run_id),
            )
    return approval_snapshots_from_events(events or [], group_run_id=group_run_id)


def artifact_snapshots_from_task_payload(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    events: list[PublicRunEvent] | None = None,
):
    return merge_artifact_snapshot_lists(
        artifact_snapshots_from_payloads(payload.get("artifacts"), run_id=run_id),
        artifact_snapshots_from_events(events or []),
    )


def task_status_from_value(value: Any) -> str:
    status = _text(value)
    status_map = {
        "approval_required": "waiting_approval",
        "pending_approval": "waiting_approval",
        "processing": "running",
        "success": "completed",
        "succeeded": "completed",
        "done": "completed",
        "error": "failed",
        "canceled": "cancelled",
    }
    normalized = status_map.get(status, status)
    if normalized in {"queued", "running", "waiting_approval", "completed", "failed", "cancelled"}:
        return normalized
    return "running"


def _chat_visible_events(events: list[PublicRunEvent]) -> list[PublicRunEvent]:
    return [
        event
        for event in events
        if event.visibility == "user" and event.sensitivity == "public"
    ]


def _desktop_intent_progress_text(
    events: list[PublicRunEvent],
    *,
    task_status: str,
    has_explicit_progress: bool,
) -> str | None:
    if has_explicit_progress or task_status not in _ACTIVE_TASK_STATUSES:
        return None

    for event in reversed(events):
        if event.event_type not in {
            _PLANNED_DESKTOP_INTENT_EVENT_TYPE,
            _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE,
            _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE,
            _COMPLETED_DESKTOP_INTENT_EVENT_TYPE,
            _TOOL_CALL_EVENT_TYPE,
        }:
            continue
        tool_name = _event_tool_name(event)
        if tool_name not in _DESKTOP_TOOL_PROGRESS_LABELS:
            continue
        label = _DESKTOP_TOOL_PROGRESS_LABELS.get(tool_name, tool_name)
        if event.event_type == _TOOL_CALL_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            return _desktop_tool_result_progress_text(label, result)
        if event.event_type == _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE:
            return f"等待批准 · {label}" if label else "等待批准桌面动作"
        if event.event_type == _COMPLETED_DESKTOP_INTENT_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            return _desktop_tool_result_progress_text(label, result)
        if event.event_type == _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            return _progress_text(
                "无法执行",
                label,
                "无法执行桌面动作",
                detail=_unavailable_desktop_intent_detail(payload),
            )
        if event.event_type == _PLANNED_DESKTOP_INTENT_EVENT_TYPE:
            return f"准备执行 · {label}" if label else "准备执行桌面动作"
    return None


def _desktop_tool_result_progress_text(label: str, result: Mapping[str, Any]) -> str:
    if result.get("approval_required"):
        return _progress_text("等待批准", label, "等待批准桌面动作")
    if result.get("foreground_lock_busy"):
        holder = _foreground_lock_holder(result)
        return _progress_text("前台被占用", label, "前台动作被占用", detail=holder)
    permission_targets = _result_text_list(result, "permission_targets", "missing_permissions")
    if result.get("permission_error") or permission_targets:
        return _progress_text(
            "需要权限",
            label,
            "需要桌面权限",
            detail=", ".join(permission_targets),
        )
    if _text(result.get("error_code")) == "app_not_found":
        return _progress_text("应用未找到", label, "应用未找到")
    if result.get("fallback_used"):
        return _progress_text(
            "已回退执行",
            label,
            "已回退执行桌面动作",
            detail=_fallback_detail(result),
        )
    if result.get("ok") is False:
        return _progress_text(
            "执行失败",
            label,
            "桌面动作失败",
            detail=_failure_detail(result),
        )
    return _progress_text("已执行", label, "已执行桌面动作")


def _progress_text(
    status: str,
    label: str,
    fallback: str,
    *,
    detail: str = "",
) -> str:
    if not label:
        return fallback
    parts = [status, label]
    clean_detail = _short_detail(detail)
    if clean_detail:
        parts.append(clean_detail)
    return " · ".join(parts)


def _foreground_lock_holder(result: Mapping[str, Any]) -> str:
    holder = _text(result.get("locked_by"))
    if holder:
        return holder
    foreground_lock = result.get("foreground_lock")
    if isinstance(foreground_lock, Mapping):
        return _text(foreground_lock.get("holder") or foreground_lock.get("locked_by"))
    return ""


def _fallback_detail(result: Mapping[str, Any]) -> str:
    fallback = _text(result.get("fallback") or result.get("fallback_tool"))
    fallback_labels = {
        "system_browser": "系统浏览器",
        "desktop.permissions": "权限诊断",
        "desktop.click": "桌面点击",
        "desktop.type_text": "桌面输入",
        "desktop.running_apps": "运行中应用",
        "desktop.windows": "窗口列表",
        "app.status": "应用状态",
        "app.open": "打开应用",
        "app.focus_window": "聚焦应用窗口",
        "app.show": "显示应用",
        "app.hide": "隐藏应用",
        "app.minimize": "最小化应用",
        "app.quit": "退出应用",
        "desktop.reveal_path": "Finder 定位",
        "desktop.open_path": "打开本地路径",
        "desktop.hide_app": "隐藏当前应用",
        "desktop.minimize_window": "最小化当前窗口",
        "desktop.close_window": "关闭当前窗口",
    }
    if fallback:
        return fallback_labels.get(fallback, fallback)
    fallback_result = result.get("fallback_result")
    if isinstance(fallback_result, Mapping):
        action = _text(fallback_result.get("action"))
        if action:
            return fallback_labels.get(action, action)
    return ""


def _failure_detail(result: Mapping[str, Any]) -> str:
    error_code = _text(result.get("error_code"))
    error_labels = {
        "chrome_cdp_unavailable": "chrome_cdp",
        "app_not_found": "应用未找到",
    }
    if error_code:
        return error_labels.get(error_code, error_code)
    error = _text(result.get("error") or result.get("summary"))
    return error_labels.get(error, error)


def _unavailable_desktop_intent_detail(payload: Mapping[str, Any]) -> str:
    if _text(payload.get("reason")) == "tool_not_allowed":
        return "工具未开启"
    blocked_by = _text(payload.get("blocked_by"))
    if blocked_by:
        return blocked_by
    return _text(payload.get("reason"))


def _result_text_list(result: Mapping[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = result.get(key)
        if isinstance(value, list):
            items = [_text(item) for item in value]
        elif isinstance(value, tuple):
            items = [_text(item) for item in value]
        else:
            items = [_text(value)] if value is not None else []
        items = [item for item in items if item]
        if items:
            return items
    return []


def _short_detail(value: str, *, limit: int = 80) -> str:
    text = _text(value)
    if not text:
        return ""
    compact = " ".join(text.split())
    if len(compact) > limit:
        return f"{compact[:limit]}..."
    return compact


def _event_tool_name(event: PublicRunEvent) -> str:
    payload = event.payload if isinstance(event.payload, Mapping) else {}
    return _text(payload.get("tool") or payload.get("tool_name") or event.detail)


def _group_run_id(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("group_run_id") or payload.get("run_group_id"))


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
