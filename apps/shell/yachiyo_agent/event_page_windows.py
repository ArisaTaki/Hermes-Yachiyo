"""Shared public RunEvent page window helpers."""

from __future__ import annotations

from .contracts import PublicRunEvent, RunEventPageSnapshot


FIRST_PAGE_GROUP_RUN_KEY_EVENT_TYPES = {
    "group.run.approval_required",
    "group.run.completed",
    "group.run.failed",
    "group.run.cancelled",
}

FIRST_PAGE_RUN_KEY_EVENT_TYPES = {
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
    "tool.approval_required",
}

FIRST_PAGE_WORKFLOW_RUN_KEY_EVENT_TYPES = {
    "workflow.run.approval_required",
    "workflow.run.completed",
    "workflow.run.failed",
    "workflow.run.cancelled",
    "workflow.run.tool.approval_required",
    "workflow.run.desktop.intent_approval_required",
    "workflow.node.approval_required",
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
    key_event_sequence = 0
    for event in stream:
        if event.event_type in event_types:
            key_event_sequence = int(event.sequence or 0)
            break
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
