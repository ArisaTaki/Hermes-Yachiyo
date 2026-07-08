"""Legacy RunEvent replay pagination helper regressions."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent.legacy_event_pages import (
    is_replay_enrichment_event,
    run_event_page_from_legacy_stream,
    run_with_replay_events,
)


def test_legacy_run_event_page_filters_by_sequence_and_clamps_limit() -> None:
    page = run_event_page_from_legacy_stream(
        {
            "run_id": "legacy-run",
            "events": [
                {"event_type": "run.started", "sequence": 1},
                {"event_type": "agent.tool.call", "sequence": 3},
                {"event_type": "agent.run.completed", "sequence": 7},
            ],
        },
        run_id="fallback-run",
        after_sequence=2,
        limit=1,
    )

    assert page == {
        "run_id": "legacy-run",
        "after_sequence": 2,
        "limit": 1,
        "next_after_sequence": 3,
        "has_more": True,
        "events": [{"event_type": "agent.tool.call", "sequence": 3}],
    }


def test_legacy_run_event_page_first_page_includes_key_status_window() -> None:
    page = run_event_page_from_legacy_stream(
        {
            "run_id": "legacy-run",
            "events": [
                {"event_type": "run.started", "sequence": 1},
                {"event_type": "agent.tool.call", "sequence": 3},
                {"event_type": "desktop.provider_session.started", "sequence": 5},
                {"event_type": "agent.run.completed", "sequence": 7},
            ],
        },
        run_id="fallback-run",
        after_sequence=0,
        limit=1,
    )

    assert page == {
        "run_id": "legacy-run",
        "after_sequence": 0,
        "limit": 1,
        "next_after_sequence": 7,
        "has_more": True,
        "events": [
            {"event_type": "run.started", "sequence": 1},
            {"event_type": "agent.tool.call", "sequence": 3},
            {"event_type": "desktop.provider_session.started", "sequence": 5},
            {"event_type": "agent.run.completed", "sequence": 7},
        ],
    }


def test_legacy_run_event_page_first_page_includes_provider_session_window() -> None:
    page = run_event_page_from_legacy_stream(
        {
            "run_id": "legacy-run",
            "events": [
                {"event_type": "run.started", "sequence": 1},
                {"event_type": "agent.plan.created", "sequence": 2},
                {"event_type": "agent.tool.started", "sequence": 3},
                {"event_type": "desktop.provider_session.started", "sequence": 4},
                {"event_type": "agent.tool.progress", "sequence": 5},
            ],
        },
        run_id="fallback-run",
        after_sequence=0,
        limit=2,
    )

    assert page == {
        "run_id": "legacy-run",
        "after_sequence": 0,
        "limit": 2,
        "next_after_sequence": 4,
        "has_more": True,
        "events": [
            {"event_type": "run.started", "sequence": 1},
            {"event_type": "agent.plan.created", "sequence": 2},
            {"event_type": "agent.tool.started", "sequence": 3},
            {"event_type": "desktop.provider_session.started", "sequence": 4},
        ],
    }


def test_legacy_run_event_page_first_page_includes_provider_execution_window() -> None:
    page = run_event_page_from_legacy_stream(
        {
            "run_id": "legacy-run",
            "events": [
                {"event_type": "run.started", "sequence": 1},
                {"event_type": "agent.plan.created", "sequence": 2},
                {"event_type": "agent.tool.started", "sequence": 3},
                {
                    "event_type": "desktop.provider_execution.routed",
                    "sequence": 4,
                    "payload": {
                        "desktop_execution_provider": {"provider_id": "sandbox-1"}
                    },
                },
                {"event_type": "agent.tool.progress", "sequence": 5},
            ],
        },
        run_id="fallback-run",
        after_sequence=0,
        limit=2,
    )

    assert page["next_after_sequence"] == 4
    assert [event["event_type"] for event in page["events"]] == [
        "run.started",
        "agent.plan.created",
        "agent.tool.started",
        "desktop.provider_execution.routed",
    ]
    assert page["events"][-1]["payload"]["desktop_execution_provider"] == {
        "provider_id": "sandbox-1"
    }


def test_legacy_run_event_page_first_page_includes_workspace_state_window() -> None:
    page = run_event_page_from_legacy_stream(
        {
            "run_id": "legacy-run",
            "events": [
                {"event_type": "run.started", "sequence": 1},
                {"event_type": "agent.plan.created", "sequence": 2},
                {"event_type": "agent.task_core.created", "sequence": 3},
                {
                    "event_type": "agent.task.workspace_item.updated",
                    "sequence": 4,
                    "payload": {"workspace_item_id": "input-sales"},
                },
                {
                    "event_type": "agent.task.todo.updated",
                    "sequence": 5,
                    "payload": {"todo_id": "todo-read"},
                },
                {
                    "event_type": "agent.task.checkpoint.updated",
                    "sequence": 6,
                    "payload": {"checkpoint_id": "checkpoint-read"},
                },
                {"event_type": "agent.tool.started", "sequence": 7},
            ],
        },
        run_id="fallback-run",
        after_sequence=0,
        limit=2,
    )

    assert page["next_after_sequence"] == 6
    assert [event["event_type"] for event in page["events"]] == [
        "run.started",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.task.workspace_item.updated",
        "agent.task.todo.updated",
        "agent.task.checkpoint.updated",
    ]


def test_legacy_run_event_page_normalizes_empty_legacy_stream() -> None:
    page = run_event_page_from_legacy_stream(
        {"events": [{"event_type": "run.started", "sequence": 0}]},
        run_id="fallback-run",
        after_sequence=-5,
        limit=999,
    )

    assert page["run_id"] == "fallback-run"
    assert page["after_sequence"] == 0
    assert page["limit"] == 500
    assert page["next_after_sequence"] == 0
    assert page["has_more"] is False
    assert page["events"] == []


def test_legacy_run_replay_enrichment_merges_observable_runtime_facts() -> None:
    runtime = _ReplayRuntime(
        [
            {"event_type": "run.started", "sequence": 1, "payload": {"source": "replay"}},
            {
                "event_type": "agent.desktop.intent_planned",
                "sequence": 2,
                "payload": {
                    "tool": "media.apple_music_play",
                    "status": "planned",
                    "input_preview": {"query": "超时空辉夜姬"},
                },
            },
            {
                "event_type": "agent.desktop.intent_unavailable",
                "sequence": 3,
                "payload": {
                    "tool": "desktop.hotkey",
                    "status": "unavailable",
                    "reason": "tool_not_allowed",
                },
            },
            {"event_type": "memory.retrieved", "sequence": 4, "payload": {"memory_id": "mem-1"}},
            {"event_type": "skill.used", "sequence": 5, "payload": {"skill_id": "skill-1"}},
            {
                "event_type": "agent.plan.created",
                "sequence": 6,
                "payload": {"plan_id": "plan-1"},
            },
            {
                "event_type": "agent.task_core.created",
                "sequence": 7,
                "payload": {"core_id": "task-core-1"},
            },
            {
                "event_type": "agent.task.todo.updated",
                "sequence": 8,
                "payload": {"todo_id": "todo-1", "status": "completed"},
            },
            {
                "event_type": "agent.replan.requested",
                "sequence": 9,
                "payload": {"request_id": "replan-1"},
            },
            {
                "event_type": "agent.artifact.write",
                "sequence": 10,
                "payload": {"artifact": {"path": "report.md"}},
            },
            {
                "event_type": "desktop.provider_session.started",
                "sequence": 11,
                "payload": {"desktop_provider_session": {"provider_id": "vnc"}},
            },
            {
                "event_type": "desktop.provider_execution.routed",
                "sequence": 12,
                "payload": {
                    "desktop_execution_provider": {"provider_id": "vnc"},
                    "desktop_execution_route": {"status": "sandbox_ready"},
                },
            },
            {
                "event_type": "agent.deferred_continuation.enqueued",
                "sequence": 13,
                "payload": {
                    "deferred_continuation_count": 1,
                    "deferred_tools": ["desktop.safe_type_text"],
                },
            },
            {
                "event_type": "workflow.run.task_core.created",
                "sequence": 14,
                "payload": {"core_id": "workflow-task-core-1"},
            },
            {"event_type": "agent.runtime.compiled", "sequence": 15, "payload": {"internal": True}},
        ]
    )
    run = {
        "run_id": "run-1",
        "events": [{"event_type": "run.started", "sequence": 1, "payload": {"source": "legacy"}}],
    }

    enriched = run_with_replay_events(run, runtime)

    assert [event["event_type"] for event in enriched["events"]] == [
        "run.started",
        "agent.desktop.intent_planned",
        "agent.desktop.intent_unavailable",
        "memory.retrieved",
        "skill.used",
        "agent.plan.created",
        "agent.task_core.created",
        "agent.task.todo.updated",
        "agent.replan.requested",
        "agent.artifact.write",
        "desktop.provider_session.started",
        "desktop.provider_execution.routed",
        "agent.deferred_continuation.enqueued",
        "workflow.run.task_core.created",
    ]
    assert runtime.requests == [{"run_id": "run-1", "limit": 500}]
    assert is_replay_enrichment_event({"event_type": "agent.desktop.intent_planned"})
    assert is_replay_enrichment_event({"event_type": "agent.desktop.intent_unavailable"})
    assert is_replay_enrichment_event({"event_type": "memory.retrieved"})
    assert is_replay_enrichment_event({"event_type": "skill.used"})
    assert is_replay_enrichment_event({"event_type": "agent.plan.created"})
    assert is_replay_enrichment_event({"event_type": "agent.task.todo.updated"})
    assert is_replay_enrichment_event({"event_type": "agent.replan.requested"})
    assert is_replay_enrichment_event({"event_type": "agent.artifact.write"})
    assert is_replay_enrichment_event({"event_type": "desktop.provider_session.started"})
    assert is_replay_enrichment_event({"event_type": "desktop.provider_execution.routed"})
    assert is_replay_enrichment_event({"event_type": "agent.deferred_continuation.enqueued"})
    assert is_replay_enrichment_event({"event_type": "workflow.run.task_core.created"})
    assert not is_replay_enrichment_event({"event_type": "agent.runtime.compiled"})


class _ReplayRuntime:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.requests: list[dict[str, Any]] = []

    def list_run_events(self, run_id: str, *, limit: int = 500) -> dict[str, Any]:
        self.requests.append({"run_id": run_id, "limit": limit})
        return {"run_id": run_id, "events": list(self._events)}
