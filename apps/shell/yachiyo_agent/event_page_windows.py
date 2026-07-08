"""Shared public RunEvent page window helpers."""

from __future__ import annotations

from .contracts import PublicRunEvent, RunEventPageSnapshot


FIRST_PAGE_DESKTOP_PROVIDER_SESSION_EVENT_TYPES = {
    "desktop.provider_session.required",
    "desktop.provider_session.started",
    "desktop.provider_session.ready",
    "desktop.provider_session.failed",
}

FIRST_PAGE_DESKTOP_PROVIDER_EXECUTION_EVENT_TYPES = {
    "desktop.provider_execution.routed",
}

FIRST_PAGE_DESKTOP_PROVIDER_EVENT_TYPES = (
    FIRST_PAGE_DESKTOP_PROVIDER_SESSION_EVENT_TYPES
    | FIRST_PAGE_DESKTOP_PROVIDER_EXECUTION_EVENT_TYPES
)

FIRST_PAGE_DEFERRED_CONTINUATION_EVENT_TYPES = {
    "agent.deferred_continuation.enqueued",
    "group.run.deferred_continuation.enqueued",
    "workflow.run.deferred_continuation.enqueued",
}

FIRST_PAGE_GROUP_RUN_KEY_EVENT_TYPES = {
    *FIRST_PAGE_DEFERRED_CONTINUATION_EVENT_TYPES,
    *FIRST_PAGE_DESKTOP_PROVIDER_EVENT_TYPES,
    "group.run.approval_required",
    "group.run.completed",
    "group.run.failed",
    "group.run.cancelled",
    "group.run.replan.requested",
    "group.run.replan.recovery.updated",
    "group.run.task_core.created",
    "group.run.task.workspace_item.updated",
    "group.run.task.todo.updated",
    "group.run.task.checkpoint.updated",
}

FIRST_PAGE_RUN_KEY_EVENT_TYPES = {
    *FIRST_PAGE_DEFERRED_CONTINUATION_EVENT_TYPES,
    *FIRST_PAGE_DESKTOP_PROVIDER_EVENT_TYPES,
    "run.completed",
    "run.failed",
    "run.cancelled",
    "agent.completed",
    "agent.failed",
    "agent.cancelled",
    "agent.run.completed",
    "agent.run.failed",
    "agent.run.cancelled",
    "agent.tool.approval_required",
    "agent.desktop.intent_approval_required",
    "agent.replan.requested",
    "agent.replan.recovery.updated",
    "agent.task_core.created",
    "agent.task.workspace_item.updated",
    "agent.task.todo.updated",
    "agent.task.checkpoint.updated",
    "tool.approval_required",
}

FIRST_PAGE_WORKFLOW_RUN_KEY_EVENT_TYPES = {
    *FIRST_PAGE_DEFERRED_CONTINUATION_EVENT_TYPES,
    *FIRST_PAGE_DESKTOP_PROVIDER_EVENT_TYPES,
    "workflow.run.approval_required",
    "workflow.run.completed",
    "workflow.run.failed",
    "workflow.run.cancelled",
    "workflow.run.tool.approval_required",
    "workflow.run.desktop.intent_approval_required",
    "workflow.node.approval_required",
    "workflow.run.replan.requested",
    "workflow.run.replan.recovery.updated",
    "workflow.task_core.created",
    "workflow.task.workspace_item.updated",
    "workflow.task.todo.updated",
    "workflow.task.checkpoint.updated",
    "workflow.run.task_core.created",
    "workflow.run.task.workspace_item.updated",
    "workflow.run.task.todo.updated",
    "workflow.run.task.checkpoint.updated",
}

FIRST_PAGE_TASK_KEY_EVENT_TYPES = {
    "task.completed",
    "task.failed",
    "task.cancelled",
    *FIRST_PAGE_RUN_KEY_EVENT_TYPES,
    "workflow.run.approval_required",
}

FIRST_PAGE_RUN_OR_WORKFLOW_KEY_EVENT_TYPES = (
    FIRST_PAGE_RUN_KEY_EVENT_TYPES | FIRST_PAGE_WORKFLOW_RUN_KEY_EVENT_TYPES
)

FIRST_PAGE_LEGACY_KEY_EVENT_TYPES = (
    FIRST_PAGE_TASK_KEY_EVENT_TYPES
    | FIRST_PAGE_GROUP_RUN_KEY_EVENT_TYPES
    | FIRST_PAGE_WORKFLOW_RUN_KEY_EVENT_TYPES
)

FIRST_PAGE_RUNTIME_STATE_EVENT_TYPES = {
    "agent.task_core.created",
    "agent.task.workspace_item.updated",
    "agent.task.todo.updated",
    "agent.task.checkpoint.updated",
    "group.run.task_core.created",
    "group.run.task.workspace_item.updated",
    "group.run.task.todo.updated",
    "group.run.task.checkpoint.updated",
    "workflow.task_core.created",
    "workflow.task.workspace_item.updated",
    "workflow.task.todo.updated",
    "workflow.task.checkpoint.updated",
    "workflow.run.task_core.created",
    "workflow.run.task.workspace_item.updated",
    "workflow.run.task.todo.updated",
    "workflow.run.task.checkpoint.updated",
}


def run_event_page_with_projected_events(
    page: RunEventPageSnapshot,
    events: list[PublicRunEvent],
) -> RunEventPageSnapshot:
    next_after_sequence = max(
        [int(event.sequence or 0) for event in events] or [int(page.next_after_sequence or 0)]
    )
    return page.model_copy(
        update={
            "events": events,
            "next_after_sequence": max(int(page.next_after_sequence or 0), next_after_sequence),
        }
    )


def events_with_first_page_key_event_window(
    events: list[PublicRunEvent],
    full_stream: list[PublicRunEvent],
    *,
    page: RunEventPageSnapshot,
    event_types: set[str],
) -> list[PublicRunEvent]:
    if not events or not event_types:
        return events
    next_after_sequence = int(page.next_after_sequence or 0)
    stream = sorted(
        [
            event
            for event in full_stream
            if int(event.sequence or 0) > next_after_sequence
        ],
        key=lambda event: int(event.sequence or 0),
    )
    key_event_sequence = _first_page_key_event_sequence(stream, event_types)
    if key_event_sequence <= next_after_sequence:
        return events
    existing_sequences = {int(event.sequence or 0) for event in events}
    enriched = list(events)
    for event in stream:
        sequence = int(event.sequence or 0)
        if sequence > key_event_sequence:
            break
        if sequence not in existing_sequences:
            enriched.append(event)
            existing_sequences.add(sequence)
    return sorted(enriched, key=lambda event: int(event.sequence or 0))


def _first_page_key_event_sequence(
    stream: list[PublicRunEvent],
    event_types: set[str],
) -> int:
    preferred_event_types = (
        set(event_types)
        - FIRST_PAGE_RUNTIME_STATE_EVENT_TYPES
        - FIRST_PAGE_DESKTOP_PROVIDER_EVENT_TYPES
    )
    for event in stream:
        if event.event_type in preferred_event_types:
            return int(event.sequence or 0)

    provider_event_types = set(event_types) & FIRST_PAGE_DESKTOP_PROVIDER_EVENT_TYPES
    for event in stream:
        if event.event_type in provider_event_types:
            return int(event.sequence or 0)

    state_event_types = set(event_types) & FIRST_PAGE_RUNTIME_STATE_EVENT_TYPES
    state_sequence = 0
    capturing_state_block = False
    for event in stream:
        if event.event_type in state_event_types:
            state_sequence = int(event.sequence or 0)
            capturing_state_block = True
            continue
        if capturing_state_block:
            break
    return state_sequence
