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
            {"event_type": "memory.retrieved", "sequence": 3, "payload": {"memory_id": "mem-1"}},
            {"event_type": "skill.used", "sequence": 4, "payload": {"skill_id": "skill-1"}},
            {"event_type": "agent.runtime.compiled", "sequence": 5, "payload": {"internal": True}},
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
        "memory.retrieved",
        "skill.used",
    ]
    assert runtime.requests == [{"run_id": "run-1", "limit": 500}]
    assert is_replay_enrichment_event({"event_type": "agent.desktop.intent_planned"})
    assert is_replay_enrichment_event({"event_type": "memory.retrieved"})
    assert is_replay_enrichment_event({"event_type": "skill.used"})


class _ReplayRuntime:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events
        self.requests: list[dict[str, Any]] = []

    def list_run_events(self, run_id: str, *, limit: int = 500) -> dict[str, Any]:
        self.requests.append({"run_id": run_id, "limit": limit})
        return {"run_id": run_id, "events": list(self._events)}
