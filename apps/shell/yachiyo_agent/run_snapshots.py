"""Shared public run snapshot mapping for Chat tasks and Agent Studio timelines."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload, redact_secrets

from .approval_event_snapshots import (
    approval_snapshots_from_events as _approval_snapshots_from_events,
    merge_approval_snapshots as _merge_approval_snapshots,
)
from .approvals import approval_cards_from_payloads
from .artifacts import artifact_snapshot_from_payload, artifact_snapshots_from_payloads
from .contracts import (
    AgentTaskSnapshot,
    ArtifactSnapshot,
    MemoryTraceSnapshot,
    PublicRunEvent,
    RunTimelineChildSnapshot,
    RunTimelineSnapshot,
    SkillTraceSnapshot,
    ToolCallSnapshot,
)
from .events import public_run_event_from_payload
from .links import studio_run_url
from .trace_snapshots import (
    memory_trace_snapshots_from_events as _memory_trace_snapshots_from_events,
    skill_trace_snapshots_from_events as _skill_trace_snapshots_from_events,
)


class RunSnapshotProjector:
    """Projects runtime-like run payloads into public Chat and Studio snapshots."""

    def task_snapshot_from_payload(
        self,
        payload: Mapping[str, Any] | AgentTaskSnapshot,
    ) -> AgentTaskSnapshot:
        if isinstance(payload, AgentTaskSnapshot):
            return payload

        task_id = _text(payload.get("task_id") or payload.get("run_id"))
        run_id = _text(payload.get("run_id") or task_id)
        group_run_id = _group_run_id(payload)
        recent_events = self.events_from_payload(
            payload,
            run_id=run_id,
            keys=("recent_events", "events", "timeline"),
        )
        recent_events = _chat_visible_events(recent_events)
        approvals = [
            approval
            for approval in self.approvals_from_payload(
                payload,
                run_id=run_id,
                group_run_id=group_run_id,
                keys=("pending_approvals", "pending_approval"),
                events=recent_events,
            )
            if approval.status == "pending"
        ]

        return AgentTaskSnapshot(
            task_id=task_id,
            conversation_id=_optional_text(payload.get("conversation_id") or payload.get("session_id")),
            title=_text(payload.get("title") or payload.get("user_goal") or "Yachiyo task"),
            status=_task_status(payload.get("status")),
            summary=_optional_text(payload.get("summary") or payload.get("result")),
            current_step=_optional_text(payload.get("current_step")),
            progress_text=_optional_text(payload.get("progress_text")),
            needs_user_action=bool(payload.get("needs_user_action") or approvals),
            pending_approvals=approvals,
            recent_events=recent_events,
            artifacts=self.artifacts_from_payload(payload, run_id=run_id, events=recent_events),
            open_in_studio_url=_optional_text(payload.get("open_in_studio_url"))
            or _studio_url(run_id, group_run_id),
            created_at=_text(payload.get("created_at")),
            updated_at=_text(payload.get("updated_at")),
        )

    def task_snapshots_from_payloads(self, payloads: Any) -> list[AgentTaskSnapshot]:
        if not isinstance(payloads, list):
            return []
        return [self.task_snapshot_from_payload(item) for item in payloads]

    def timeline_snapshot_from_payload(
        self,
        payload: Mapping[str, Any] | RunTimelineSnapshot,
    ) -> RunTimelineSnapshot:
        if isinstance(payload, RunTimelineSnapshot):
            return payload

        run_id = _text(payload.get("run_id") or payload.get("workflow_run_id"))
        events = self.events_from_payload(
            payload,
            run_id=run_id,
            keys=("events", "run_events", "timeline"),
        )
        legacy_run_group_id = _optional_text(payload.get("run_group_id"))
        group_run_id = _optional_text(payload.get("group_run_id")) or legacy_run_group_id
        approvals = self.approvals_from_payload(
            payload,
            run_id=run_id,
            group_run_id=group_run_id or "",
            keys=("approvals", "pending_approval"),
            events=events,
        )
        pending_approval = None
        if (
            isinstance(payload.get("pending_approval"), Mapping)
            and payload.get("pending_approval")
            and approvals
        ):
            pending_approval = next(
                (approval for approval in approvals if approval.status == "pending"),
                None,
            )
        elif _task_status(payload.get("status")) == "waiting_approval" and approvals:
            pending_approval = next(
                (approval for approval in approvals if approval.status == "pending"),
                None,
            )
        rerun_provenance = _rerun_provenance_from_payload(payload, events)

        return RunTimelineSnapshot(
            run_id=run_id,
            parent_run_id=_optional_text(payload.get("parent_run_id")),
            group_run_id=group_run_id,
            run_group_id=legacy_run_group_id or group_run_id,
            workflow_run_id=_workflow_run_id(payload, run_id),
            agent_id=_optional_text(payload.get("agent_id") or _agent_id_from_run(payload)),
            status=_text(payload.get("status") or "unknown"),
            title=_optional_text(payload.get("title") or payload.get("user_goal")),
            task_id=_optional_text(payload.get("task_id")),
            session_id=_optional_text(payload.get("session_id")),
            task_run_link_created_at=_optional_text(payload.get("task_run_link_created_at")),
            task_run_link_updated_at=_optional_text(payload.get("task_run_link_updated_at")),
            task_run_link_run_status=_optional_text(payload.get("task_run_link_run_status")),
            task_run_link_last_event_sequence=_optional_int(
                payload.get("task_run_link_last_event_sequence")
            ),
            rerun_of_run_id=rerun_provenance.get("rerun_of_run_id"),
            rerun_of_kind=rerun_provenance.get("rerun_of_kind"),
            rerun_of_status=rerun_provenance.get("rerun_of_status"),
            rerun_of_runnable_id=rerun_provenance.get("rerun_of_runnable_id"),
            rerun_of_runnable_name=rerun_provenance.get("rerun_of_runnable_name"),
            rerun_original_created_at=rerun_provenance.get("rerun_original_created_at"),
            rerun_original_updated_at=rerun_provenance.get("rerun_original_updated_at"),
            events=events,
            tool_calls=self.tool_calls_from_payload(
                payload.get("tool_calls"),
                run_id=run_id,
                events=events,
            ),
            memory_traces=self.memory_traces_from_events(events),
            skill_traces=self.skill_traces_from_events(events),
            approvals=approvals,
            pending_approval=pending_approval,
            artifacts=self.artifacts_from_payload(payload, run_id=run_id, events=events),
            children=self.timeline_children_from_payloads(
                payload.get("children") or payload.get("child_run_ids")
            ),
            created_at=_text(payload.get("created_at")),
            updated_at=_text(payload.get("updated_at")),
        )

    def events_from_payload(
        self,
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

    def approvals_from_payload(
        self,
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
                return _merge_approvals(
                    approvals,
                    self.approvals_from_events(events or [], group_run_id=group_run_id),
                )
        return self.approvals_from_events(events or [], group_run_id=group_run_id)

    def artifacts_from_payload(
        self,
        payload: Mapping[str, Any],
        *,
        run_id: str,
        events: list[PublicRunEvent] | None = None,
    ):
        return _merge_artifacts(
            self.artifacts_from_payloads(payload.get("artifacts"), run_id=run_id),
            self.artifacts_from_events(events or []),
        )

    def approvals_from_payloads(
        self,
        payloads: Any,
        *,
        run_id: str = "",
        group_run_id: str = "",
    ):
        return approval_cards_from_payloads(
            payloads,
            run_id=run_id,
            group_run_id=group_run_id,
        )

    def artifacts_from_payloads(self, payloads: Any, *, run_id: str = ""):
        return artifact_snapshots_from_payloads(payloads, run_id=run_id)

    def approvals_from_events(
        self,
        events: list[PublicRunEvent],
        *,
        group_run_id: str = "",
    ):
        return _approval_snapshots_from_events(events, group_run_id=group_run_id)

    def artifacts_from_events(self, events: list[PublicRunEvent]):
        artifacts = []
        for event in events:
            if _public_run_event_is_secret(event):
                continue
            artifact_payload = _artifact_payload_from_event(event)
            if artifact_payload:
                artifacts.append(
                    artifact_snapshot_from_payload(artifact_payload, run_id=event.run_id)
                )
        return artifacts

    def tool_calls_from_payload(
        self,
        payloads: Any,
        *,
        run_id: str = "",
        events: list[PublicRunEvent] | None = None,
    ) -> list[ToolCallSnapshot]:
        if isinstance(payloads, list):
            return [self.tool_call_from_payload(item, run_id=run_id) for item in payloads]
        return self.tool_calls_from_events(events or [])

    def tool_call_from_payload(
        self,
        payload: Mapping[str, Any] | ToolCallSnapshot,
        *,
        run_id: str = "",
    ) -> ToolCallSnapshot:
        if isinstance(payload, ToolCallSnapshot):
            return _redacted_tool_call_snapshot(payload)
        tool_name = _text(payload.get("tool_name") or payload.get("tool") or "tool")
        tool_call_id = _text(payload.get("tool_call_id") or payload.get("id"))
        if not tool_call_id:
            tool_call_id = f"{run_id or 'run'}:{tool_name}:{payload.get('sequence') or 0}"
        input_preview = _mapping(
            payload.get("input_preview")
            or payload.get("input")
            or payload.get("arguments")
            or payload.get("args")
        )
        status = _text(payload.get("status") or "completed")
        completed_at = _optional_text(payload.get("completed_at"))
        if not completed_at and _tool_call_status_is_terminal(status):
            completed_at = _optional_text(payload.get("created_at") or payload.get("started_at"))
        return ToolCallSnapshot(
            tool_call_id=tool_call_id,
            run_id=_optional_text(payload.get("run_id") or run_id),
            source_run_id=_optional_text(
                payload.get("source_run_id") or input_preview.get("source_run_id")
            ),
            source_runnable_id=_optional_text(
                payload.get("source_runnable_id")
                or payload.get("source_agent_id")
                or payload.get("member_agent_id")
                or payload.get("agent_id")
                or input_preview.get("source_runnable_id")
                or input_preview.get("member_agent_id")
                or input_preview.get("agent_id")
            ),
            source_runnable_name=_optional_text(
                payload.get("source_runnable_name")
                or payload.get("source_agent_name")
                or payload.get("member_agent_name")
                or payload.get("agent_name")
                or input_preview.get("source_runnable_name")
                or input_preview.get("member_agent_name")
                or input_preview.get("agent_name")
            ),
            workflow_id=_optional_text(payload.get("workflow_id") or input_preview.get("workflow_id")),
            workflow_run_id=_optional_text(
                payload.get("workflow_run_id") or input_preview.get("workflow_run_id")
            ),
            workflow_node_id=_optional_text(
                payload.get("workflow_node_id") or input_preview.get("workflow_node_id")
            ),
            workflow_node_label=_optional_text(
                payload.get("workflow_node_label") or input_preview.get("workflow_node_label")
            ),
            group_id=_optional_text(payload.get("group_id") or input_preview.get("group_id")),
            group_run_id=_optional_text(
                payload.get("group_run_id")
                or payload.get("run_group_id")
                or input_preview.get("group_run_id")
                or input_preview.get("run_group_id")
            ),
            tool_name=tool_name,
            status=status,
            risk_level=_optional_text(payload.get("risk_level") or payload.get("risk")),
            input_preview=input_preview,
            output_preview=_tool_output_preview(payload),
            approval_id=_optional_text(payload.get("approval_id")),
            started_at=_text(payload.get("started_at") or payload.get("created_at")),
            completed_at=completed_at,
        )

    def tool_calls_from_events(self, events: list[PublicRunEvent]) -> list[ToolCallSnapshot]:
        calls: list[ToolCallSnapshot] = []
        active_by_key: dict[str, int] = {}
        for event in events:
            if _public_run_event_is_secret(event):
                continue
            if not _is_tool_event(event.event_type):
                continue
            payload = _tool_call_payload_from_event(event)
            call = self.tool_call_from_payload(payload, run_id=event.run_id)
            key = _tool_call_correlation_key(payload, call)
            active_index = active_by_key.get(key) if key else None
            if active_index is None:
                active_index = len(calls)
                calls.append(call)
            else:
                calls[active_index] = _merge_tool_call_snapshots(calls[active_index], call)
            if key:
                if _tool_call_status_is_terminal(call.status):
                    active_by_key.pop(key, None)
                else:
                    active_by_key[key] = active_index
        return calls

    def memory_traces_from_events(self, events: list[PublicRunEvent]) -> list[MemoryTraceSnapshot]:
        return _memory_trace_snapshots_from_events(events)

    def skill_traces_from_events(self, events: list[PublicRunEvent]) -> list[SkillTraceSnapshot]:
        return _skill_trace_snapshots_from_events(events)

    def timeline_children_from_payloads(self, payloads: Any) -> list[RunTimelineChildSnapshot]:
        if not isinstance(payloads, list):
            return []
        children: list[RunTimelineChildSnapshot] = []
        for item in payloads:
            if isinstance(item, Mapping):
                kind = _optional_text(item.get("kind"))
                runnable_id = _optional_text(item.get("runnable_id"))
                children.append(
                    RunTimelineChildSnapshot(
                        run_id=_text(item.get("run_id")),
                        title=_optional_text(item.get("title") or item.get("user_goal")),
                        status=_text(item.get("status")),
                        kind=kind,
                        parent_run_id=_optional_text(item.get("parent_run_id")),
                        group_run_id=_optional_text(item.get("group_run_id") or item.get("run_group_id")),
                        run_group_id=_optional_text(item.get("run_group_id") or item.get("group_run_id")),
                        workflow_run_id=_optional_text(item.get("workflow_run_id")),
                        workflow_node_id=_optional_text(item.get("workflow_node_id")),
                        workflow_node_label=_optional_text(item.get("workflow_node_label")),
                        agent_id=_optional_text(
                            item.get("agent_id")
                            or item.get("member_agent_id")
                            or (runnable_id if kind == "agent_run" else "")
                        ),
                        workflow_id=_optional_text(
                            item.get("workflow_id")
                            or (runnable_id if kind == "workflow_run" else "")
                        ),
                    )
                )
            else:
                children.append(RunTimelineChildSnapshot(run_id=_text(item)))
        return children


_PROJECTOR = RunSnapshotProjector()


def agent_task_snapshot_from_payload(
    payload: Mapping[str, Any] | AgentTaskSnapshot,
) -> AgentTaskSnapshot:
    return _PROJECTOR.task_snapshot_from_payload(payload)


def agent_task_snapshots_from_payloads(payloads: Any) -> list[AgentTaskSnapshot]:
    return _PROJECTOR.task_snapshots_from_payloads(payloads)


def run_timeline_snapshot_from_payload(
    payload: Mapping[str, Any] | RunTimelineSnapshot,
) -> RunTimelineSnapshot:
    return _PROJECTOR.timeline_snapshot_from_payload(payload)


def tool_call_snapshots_from_payloads(payloads: Any, *, run_id: str = "") -> list[ToolCallSnapshot]:
    return _PROJECTOR.tool_calls_from_payload(payloads, run_id=run_id)


def tool_call_snapshot_from_payload(
    payload: Mapping[str, Any] | ToolCallSnapshot,
    *,
    run_id: str = "",
) -> ToolCallSnapshot:
    return _PROJECTOR.tool_call_from_payload(payload, run_id=run_id)


def timeline_children_from_payloads(payloads: Any) -> list[RunTimelineChildSnapshot]:
    return _PROJECTOR.timeline_children_from_payloads(payloads)


def memory_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[MemoryTraceSnapshot]:
    return _memory_trace_snapshots_from_events(events)


def skill_trace_snapshots_from_events(events: list[PublicRunEvent]) -> list[SkillTraceSnapshot]:
    return _skill_trace_snapshots_from_events(events)


def _tool_call_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    approval = _nested_mapping(payload, "pending_approval") or _nested_mapping(payload, "approval")
    approval_id = (
        _text(payload.get("approval_id"))
        or _text(approval.get("approval_id"))
        or _text(approval.get("id"))
    )
    risk_level = (
        _text(payload.get("risk_level"))
        or _text(payload.get("risk"))
        or _text(approval.get("risk_level"))
        or _text(approval.get("risk"))
    )
    policy_reason = (
        _text(payload.get("policy_reason"))
        or _text(approval.get("policy_reason"))
        or _text(approval.get("reason"))
    )
    normalized = {
        **payload,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "tool_name": _tool_name_from_event(event),
        "status": payload.get("status") or _tool_status_from_event_type(event.event_type),
        "created_at": event.created_at,
    }
    if approval_id:
        normalized.setdefault("approval_id", approval_id)
    if risk_level:
        normalized.setdefault("risk_level", risk_level)
    _merge_tool_trace_context(normalized, payload)
    _merge_tool_trace_into_input_preview(
        normalized,
        {
            "approval_id": approval_id,
            "risk_level": risk_level,
            "policy_reason": policy_reason,
            "group_id": payload.get("group_id"),
            "group_run_id": payload.get("group_run_id") or payload.get("run_group_id"),
            "member_agent_id": payload.get("member_agent_id"),
            "member_agent_name": payload.get("member_agent_name"),
            "workflow_id": payload.get("workflow_id"),
            "workflow_run_id": payload.get("workflow_run_id"),
            "workflow_node_id": payload.get("workflow_node_id"),
            "workflow_node_label": payload.get("workflow_node_label"),
        },
    )
    return normalized


def _merge_tool_trace_context(source: dict[str, Any], payload: dict[str, Any]) -> None:
    for key in (
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
        "group_id",
        "group_run_id",
    ):
        if payload.get(key):
            source.setdefault(key, payload.get(key))
    if payload.get("run_group_id"):
        source.setdefault("group_run_id", payload.get("run_group_id"))
    if payload.get("member_agent_id"):
        source.setdefault("source_runnable_id", payload.get("member_agent_id"))
    if payload.get("member_agent_name"):
        source.setdefault("source_runnable_name", payload.get("member_agent_name"))
    if payload.get("agent_id"):
        source.setdefault("source_runnable_id", payload.get("agent_id"))
    if payload.get("agent_name"):
        source.setdefault("source_runnable_name", payload.get("agent_name"))


def _merge_tool_trace_into_input_preview(
    source: dict[str, Any],
    context: dict[str, Any],
) -> None:
    clean_context = {key: value for key, value in context.items() if value}
    if not clean_context:
        return
    input_preview = (
        source.get("input_preview")
        or source.get("input")
        or source.get("arguments")
        or source.get("args")
    )
    preview = dict(input_preview) if isinstance(input_preview, Mapping) else {}
    for key, value in clean_context.items():
        preview.setdefault(key, value)
    source["input_preview"] = preview


def _artifact_payload_from_event(event: PublicRunEvent) -> dict[str, Any]:
    payload = dict(event.payload)
    if event.event_type in {"artifact.created", "agent.artifact.write"}:
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else payload
        if event.event_type == "agent.artifact.write":
            artifact_payload.setdefault("kind", "agent_artifact")
            if event.detail:
                artifact_payload.setdefault("path", event.detail)
        elif payload.get("workflow_node_id") or payload.get("workflow_node_label"):
            artifact_payload.setdefault("kind", payload.get("kind") or "workflow_artifact")
            artifact_payload.setdefault(
                "title",
                payload.get("title")
                or payload.get("workflow_node_label")
                or artifact_payload.get("path")
                or artifact_payload.get("artifact_path")
                or "Workflow Artifact",
            )
            artifact_payload.setdefault("workflow_id", payload.get("workflow_id"))
            artifact_payload.setdefault("workflow_run_id", payload.get("workflow_run_id") or event.run_id)
            artifact_payload.setdefault("workflow_node_id", payload.get("workflow_node_id"))
            artifact_payload.setdefault("workflow_node_label", payload.get("workflow_node_label"))
        elif payload.get("group_id") or payload.get("group_run_id") or payload.get("run_group_id"):
            artifact_payload.setdefault("kind", "group_artifact")
            artifact_payload.setdefault("group_id", payload.get("group_id"))
            artifact_payload.setdefault(
                "group_run_id",
                payload.get("group_run_id") or payload.get("run_group_id") or event.run_id,
            )
            if payload.get("member_agent_name"):
                artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))
            if payload.get("member_agent_id"):
                artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
            if payload.get("member_agent_name") and not artifact_payload.get("title"):
                artifact_path = _text(artifact_payload.get("path") or artifact_payload.get("artifact_path"))
                artifact_payload["title"] = (
                    f"{payload['member_agent_name']} / {artifact_path or 'Artifact'}"
                )
    elif event.event_type in {"group.artifact.created", "group.shared_artifact.created"}:
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else payload
        artifact_payload.setdefault("kind", "group_artifact")
        artifact_payload.setdefault("group_id", payload.get("group_id"))
        artifact_payload.setdefault(
            "group_run_id",
            payload.get("group_run_id") or payload.get("run_group_id") or event.run_id,
        )
        if payload.get("member_agent_name"):
            artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))
        if payload.get("member_agent_id"):
            artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
        if payload.get("member_agent_name") and not artifact_payload.get("title"):
            artifact_path = _text(artifact_payload.get("path") or artifact_payload.get("artifact_path"))
            artifact_payload["title"] = (
                f"{payload['member_agent_name']} / {artifact_path or 'Artifact'}"
            )
    elif event.event_type == "workflow.node.artifact":
        artifact = payload.get("artifact")
        artifact_payload = dict(artifact) if isinstance(artifact, Mapping) else {}
        artifact_payload.setdefault("path", payload.get("artifact_path") or payload.get("path") or event.detail)
        artifact_payload.setdefault("kind", payload.get("kind") or "workflow_artifact")
        artifact_payload.setdefault(
            "title",
            payload.get("title")
            or payload.get("workflow_node_label")
            or artifact_payload.get("path")
            or "Workflow Artifact",
        )
        artifact_payload.setdefault("workflow_id", payload.get("workflow_id"))
        artifact_payload.setdefault("workflow_run_id", payload.get("workflow_run_id") or event.run_id)
        artifact_payload.setdefault("workflow_node_id", payload.get("workflow_node_id"))
        artifact_payload.setdefault("workflow_node_label", payload.get("workflow_node_label"))
        for key in (
            "artifact_id",
            "id",
            "size_bytes",
            "bytes",
            "mime_type",
            "content_type",
            "preview_text",
            "content_preview",
            "url",
        ):
            if payload.get(key) is not None:
                artifact_payload.setdefault(key, payload.get(key))
        if not (
            artifact_payload.get("path")
            or artifact_payload.get("artifact_id")
            or artifact_payload.get("id")
        ):
            return {}
    else:
        return {}
    _merge_artifact_trace_context(artifact_payload, payload)
    artifact_payload.setdefault("source_run_id", event.run_id)
    artifact_payload.setdefault("run_id", event.run_id)
    artifact_payload.setdefault("created_at", event.created_at)
    return artifact_payload


def _merge_artifact_trace_context(
    artifact_payload: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    for key in (
        "group_id",
        "group_run_id",
        "run_group_id",
        "source_tool",
        "source_runnable_id",
        "source_runnable_name",
        "workflow_id",
        "workflow_run_id",
        "workflow_node_id",
        "workflow_node_label",
    ):
        if payload.get(key):
            artifact_payload.setdefault(key, payload.get(key))
    if payload.get("member_agent_id"):
        artifact_payload.setdefault("source_runnable_id", payload.get("member_agent_id"))
    if payload.get("member_agent_name"):
        artifact_payload.setdefault("source_runnable_name", payload.get("member_agent_name"))


def _merge_approvals(*approval_lists):
    by_key = {}
    ordered_keys = []
    for approvals in approval_lists:
        for approval in approvals or []:
            key = approval.approval_id or approval.run_id or approval.title
            if not key:
                continue
            if key not in by_key:
                by_key[key] = approval
                ordered_keys.append(key)
            else:
                by_key[key] = _merge_approval_snapshots(by_key[key], approval)
    return [by_key[key] for key in ordered_keys]


def _merge_artifacts(*artifact_lists):
    by_key = {}
    ordered_keys = []
    for artifacts in artifact_lists:
        for artifact in artifacts or []:
            key = artifact.artifact_id or artifact.path or artifact.title
            if not key:
                continue
            if key not in by_key:
                by_key[key] = artifact
                ordered_keys.append(key)
            else:
                by_key[key] = _merge_artifact_snapshots(by_key[key], artifact)
    return [by_key[key] for key in ordered_keys]


def _merge_artifact_snapshots(
    current: ArtifactSnapshot,
    next_artifact: ArtifactSnapshot,
) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        artifact_id=current.artifact_id or next_artifact.artifact_id,
        run_id=current.run_id or next_artifact.run_id,
        source_run_id=current.source_run_id or next_artifact.source_run_id,
        source_tool=current.source_tool or next_artifact.source_tool,
        source_runnable_id=current.source_runnable_id or next_artifact.source_runnable_id,
        source_runnable_name=current.source_runnable_name or next_artifact.source_runnable_name,
        workflow_id=current.workflow_id or next_artifact.workflow_id,
        workflow_run_id=current.workflow_run_id or next_artifact.workflow_run_id,
        workflow_node_id=current.workflow_node_id or next_artifact.workflow_node_id,
        workflow_node_label=current.workflow_node_label or next_artifact.workflow_node_label,
        group_id=current.group_id or next_artifact.group_id,
        group_run_id=current.group_run_id or next_artifact.group_run_id,
        title=current.title or next_artifact.title,
        kind=current.kind or next_artifact.kind,
        path=current.path or next_artifact.path,
        mime_type=current.mime_type or next_artifact.mime_type,
        size_bytes=current.size_bytes if current.size_bytes is not None else next_artifact.size_bytes,
        preview_text=current.preview_text or next_artifact.preview_text,
        url=current.url or next_artifact.url,
        created_at=current.created_at or next_artifact.created_at,
    )


def _merge_tool_call_snapshots(
    current: ToolCallSnapshot,
    next_call: ToolCallSnapshot,
) -> ToolCallSnapshot:
    output_preview = dict(current.output_preview)
    output_preview.update(next_call.output_preview)
    completed_at = next_call.completed_at or current.completed_at
    if _tool_call_status_is_terminal(next_call.status) and not completed_at:
        completed_at = next_call.started_at or current.completed_at
    return ToolCallSnapshot(
        tool_call_id=current.tool_call_id or next_call.tool_call_id,
        run_id=current.run_id or next_call.run_id,
        source_run_id=current.source_run_id or next_call.source_run_id,
        source_runnable_id=current.source_runnable_id or next_call.source_runnable_id,
        source_runnable_name=current.source_runnable_name or next_call.source_runnable_name,
        workflow_id=current.workflow_id or next_call.workflow_id,
        workflow_run_id=current.workflow_run_id or next_call.workflow_run_id,
        workflow_node_id=current.workflow_node_id or next_call.workflow_node_id,
        workflow_node_label=current.workflow_node_label or next_call.workflow_node_label,
        group_id=current.group_id or next_call.group_id,
        group_run_id=current.group_run_id or next_call.group_run_id,
        tool_name=current.tool_name or next_call.tool_name,
        status=next_call.status or current.status,
        risk_level=current.risk_level or next_call.risk_level,
        input_preview={**current.input_preview, **next_call.input_preview},
        output_preview=output_preview,
        approval_id=current.approval_id or next_call.approval_id,
        started_at=current.started_at or next_call.started_at,
        completed_at=completed_at,
    )


def _redacted_tool_call_snapshot(snapshot: ToolCallSnapshot) -> ToolCallSnapshot:
    return snapshot.model_copy(
        update={
            "tool_call_id": _text(snapshot.tool_call_id),
            "run_id": _optional_text(snapshot.run_id),
            "source_run_id": _optional_text(snapshot.source_run_id),
            "source_runnable_id": _optional_text(snapshot.source_runnable_id),
            "source_runnable_name": _optional_text(snapshot.source_runnable_name),
            "workflow_id": _optional_text(snapshot.workflow_id),
            "workflow_run_id": _optional_text(snapshot.workflow_run_id),
            "workflow_node_id": _optional_text(snapshot.workflow_node_id),
            "workflow_node_label": _optional_text(snapshot.workflow_node_label),
            "group_id": _optional_text(snapshot.group_id),
            "group_run_id": _optional_text(snapshot.group_run_id),
            "tool_name": _text(snapshot.tool_name),
            "status": _text(snapshot.status),
            "risk_level": _optional_text(snapshot.risk_level),
            "input_preview": _mapping(snapshot.input_preview),
            "output_preview": _mapping(snapshot.output_preview),
            "approval_id": _optional_text(snapshot.approval_id),
            "started_at": _text(snapshot.started_at),
            "completed_at": _optional_text(snapshot.completed_at),
        }
    )


def _tool_call_correlation_key(
    payload: Mapping[str, Any],
    call: ToolCallSnapshot,
) -> str:
    explicit_id = _text(payload.get("tool_call_id") or payload.get("id"))
    run_id = call.run_id or _text(payload.get("run_id"))
    if explicit_id:
        return f"{run_id}:id:{explicit_id}"
    preview = _tool_call_correlation_preview(call.input_preview)
    return f"{run_id}:tool:{call.tool_name}:{_stable_json(preview)}"


def _tool_call_correlation_preview(preview: Mapping[str, Any]) -> dict[str, Any]:
    trace_keys = {
        "agent_id",
        "agent_name",
        "approval_id",
        "group_id",
        "group_run_id",
        "member_agent_id",
        "member_agent_name",
        "policy_reason",
        "risk_level",
        "run_id",
        "run_group_id",
        "source_agent_id",
        "source_agent_name",
        "source_run_id",
        "source_runnable_id",
        "source_runnable_name",
        "source_tool",
        "tool_call_id",
        "workflow_id",
        "workflow_node_id",
        "workflow_node_kind",
        "workflow_node_label",
        "workflow_run_id",
        "workflow_step_label",
    }
    return {key: value for key, value in preview.items() if key not in trace_keys}


def _tool_call_status_is_terminal(status: str) -> bool:
    return status in {"completed", "failed", "denied", "skipped", "expired", "cancelled"}


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _task_status(value: Any) -> str:
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


def _agent_id_from_run(payload: Mapping[str, Any]) -> str:
    if _text(payload.get("kind")) == "agent_run":
        return _text(payload.get("runnable_id"))
    return ""


def _workflow_run_id(payload: Mapping[str, Any], run_id: str) -> str | None:
    explicit = _optional_text(payload.get("workflow_run_id"))
    if explicit:
        return explicit
    if _text(payload.get("kind")) == "workflow_run":
        return run_id or None
    return None


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_run_event_payload(dict(value))
    result = dict(redacted) if isinstance(redacted, Mapping) else {}
    return _restore_configured_flags(value, result)


def _restore_configured_flags(source: Any, target: Any) -> dict[str, Any]:
    if not isinstance(source, Mapping) or not isinstance(target, Mapping):
        return dict(target) if isinstance(target, Mapping) else {}
    result = dict(target)
    for key, item in source.items():
        key_text = _text(key)
        target_item = result.get(key_text)
        if key_text.endswith("_configured") and isinstance(item, bool):
            result[key_text] = item
        elif isinstance(item, Mapping) and isinstance(target_item, Mapping):
            result[key_text] = _restore_configured_flags(item, target_item)
        elif isinstance(item, list) and isinstance(target_item, list):
            result[key_text] = [
                _restore_configured_flags(source_item, redacted_item)
                if isinstance(source_item, Mapping) and isinstance(redacted_item, Mapping)
                else redacted_item
                for source_item, redacted_item in zip(item, target_item, strict=False)
            ]
    return result


def _public_run_event_is_secret(event: PublicRunEvent) -> bool:
    return event.sensitivity == "secret"


def _chat_visible_events(events: list[PublicRunEvent]) -> list[PublicRunEvent]:
    return [
        event
        for event in events
        if event.visibility == "user" and event.sensitivity == "public"
    ]


def _nested_mapping(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _tool_output_preview(payload: Mapping[str, Any]) -> dict[str, Any]:
    explicit = _mapping(
        payload.get("output_preview")
        or payload.get("output")
        or payload.get("result")
    )
    if explicit:
        return explicit
    error = payload.get("error")
    return _mapping({"error": error}) if error is not None else {}


def _is_tool_event(event_type: str) -> bool:
    return event_type in {
        "agent.tool.call",
        "agent.tool.denied",
        "agent.tool.started",
        "agent.tool.failed",
        "agent.tool.skipped",
        "agent.tool.approval_required",
        "agent.tool.approval_approved",
        "agent.tool.approval_rejected",
        "agent.tool.approval_timeout",
        "agent.tool.approval_cancelled",
        "agent.tool.completed",
        "approval.cancelled",
        "approval.timeout",
        "tool.approved",
        "tool.approval_approved",
        "tool.approval_cancelled",
        "tool.approval_rejected",
        "tool.requested",
        "tool.started",
        "tool.approval_required",
        "tool.approval_timeout",
        "tool.denied",
        "tool.rejected",
        "tool.skipped",
        "tool.completed",
        "tool.failed",
        "tool.cancelled",
    }


def _tool_name_from_event(event: PublicRunEvent) -> str:
    return _text(
        event.payload.get("tool_name")
        or event.payload.get("tool")
        or event.detail
        or "tool"
    )


def _tool_status_from_event_type(event_type: str) -> str:
    if event_type in {"tool.requested"}:
        return "requested"
    if event_type in {"tool.started", "agent.tool.started"}:
        return "running"
    if event_type in {"tool.approval_required", "agent.tool.approval_required"}:
        return "waiting_approval"
    if event_type in {"agent.tool.approval_approved", "tool.approved", "tool.approval_approved"}:
        return "approved"
    if event_type in {
        "agent.tool.approval_rejected",
        "agent.tool.denied",
        "tool.approval_rejected",
        "tool.denied",
        "tool.rejected",
    }:
        return "denied"
    if event_type in {"agent.tool.approval_timeout", "approval.timeout", "tool.approval_timeout"}:
        return "expired"
    if event_type in {
        "agent.tool.approval_cancelled",
        "approval.cancelled",
        "tool.approval_cancelled",
    }:
        return "cancelled"
    if event_type in {"tool.completed", "agent.tool.call", "agent.tool.completed"}:
        return "completed"
    if event_type in {"tool.failed", "agent.tool.failed"}:
        return "failed"
    if event_type in {"agent.tool.skipped", "tool.skipped"}:
        return "skipped"
    if event_type in {"tool.cancelled"}:
        return "cancelled"
    return "completed"


def _group_run_id(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("group_run_id") or payload.get("run_group_id"))


def _rerun_provenance_from_payload(
    payload: Mapping[str, Any],
    events: list[PublicRunEvent],
) -> dict[str, str | None]:
    keys = (
        "rerun_of_run_id",
        "rerun_of_kind",
        "rerun_of_status",
        "rerun_of_runnable_id",
        "rerun_of_runnable_name",
    )
    direct = {key: _optional_text(payload.get(key)) for key in keys}
    direct["rerun_original_created_at"] = _optional_text(
        payload.get("rerun_original_created_at") or payload.get("original_created_at")
    )
    direct["rerun_original_updated_at"] = _optional_text(
        payload.get("rerun_original_updated_at") or payload.get("original_updated_at")
    )
    if direct.get("rerun_of_run_id"):
        return direct
    event = next((item for item in events if item.event_type == "run.rerun.started"), None)
    if event is None:
        return direct
    source = event.payload
    return {
        **{key: _optional_text(source.get(key)) for key in keys},
        "rerun_original_created_at": _optional_text(source.get("original_created_at")),
        "rerun_original_updated_at": _optional_text(source.get("original_updated_at")),
    }


def _studio_url(run_id: str, group_run_id: str = "") -> str | None:
    return studio_run_url(run_id, group_run_id=group_run_id)


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
