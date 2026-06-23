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

_ACTIVE_TASK_STATUSES = {"queued", "running", "waiting_approval"}
_PLANNED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_planned"
_UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_unavailable"
_APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_approval_required"
_COMPLETED_DESKTOP_INTENT_EVENT_TYPE = "agent.desktop.intent_completed"
_DESKTOP_TOOL_PROGRESS_LABELS = {
    "screen.capture": "截取屏幕",
    "desktop.active_window": "读取当前窗口",
    "app.open": "打开应用",
    "app.focus": "聚焦应用",
    "media.apple_music_play": "播放 Apple Music",
    "media.apple_music_control": "控制 Apple Music",
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
        }:
            continue
        tool_name = _event_tool_name(event)
        label = _DESKTOP_TOOL_PROGRESS_LABELS.get(tool_name, tool_name)
        if event.event_type == _APPROVAL_REQUIRED_DESKTOP_INTENT_EVENT_TYPE:
            return f"等待批准 · {label}" if label else "等待批准桌面动作"
        if event.event_type == _COMPLETED_DESKTOP_INTENT_EVENT_TYPE:
            payload = event.payload if isinstance(event.payload, Mapping) else {}
            result = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
            if result.get("permission_error"):
                return f"需要权限 · {label}" if label else "需要桌面权限"
            if result.get("ok") is False:
                return f"执行失败 · {label}" if label else "桌面动作失败"
            return f"已执行 · {label}" if label else "已执行桌面动作"
        if event.event_type == _UNAVAILABLE_DESKTOP_INTENT_EVENT_TYPE:
            return f"无法执行 · {label}" if label else "无法执行桌面动作"
        if event.event_type == _PLANNED_DESKTOP_INTENT_EVENT_TYPE:
            return f"准备执行 · {label}" if label else "准备执行桌面动作"
    return None


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
