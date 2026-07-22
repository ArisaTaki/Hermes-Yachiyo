"""Integration tests for internal canonical ToolOutcome projection."""

from __future__ import annotations

import json
from typing import Any

from apps.shell.agent.runtime.tool_execution import RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder


class _Budget:
    def claim_tool_call(
        self,
        _tool_name: str,
        *,
        terminal_execution: bool = False,
    ) -> None:
        del terminal_execution


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def _runner(*, append_run_event: Any, raw_result: dict[str, Any]) -> RuntimeToolRequestRunner:
    return RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline_value: _Budget(),
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=object(),
        call_agent_tool=lambda *_args, **_kwargs: raw_result,
    )


def test_runner_persists_canonical_outcome_only_as_internal_sidecar() -> None:
    events: list[tuple[str, str, dict[str, Any], str]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        visibility: str = "user",
    ) -> None:
        events.append((run_id, event_type, payload, visibility))

    raw_result = {
        "ok": True,
        "data": {
            "status": "not_found",
            "outcome": "partial",
            "query": "private query",
            "playback_started": False,
        },
    }
    messages = [{"role": "user", "content": "播放一首歌"}]
    timeline: list[dict[str, Any]] = []

    _runner(append_run_event=append_run_event, raw_result=raw_result).run(
        [
            {
                "protocol": "json_fallback",
                "tool": "media.apple_music_play",
                "tool_call_id": "call-media-miss",
                "input": {"query": "private query"},
            }
        ],
        ["media.apple_music_play"],
        broker=object(),
        messages=messages,
        timeline=timeline,
        artifacts=[],
        next_iteration=1,
        run_id="run-outcome",
        budget=_Budget(),
    )

    sidecars = [event for event in events if event[1] == "agent.tool.outcome"]
    assert len(sidecars) == 1
    _, _, payload, visibility = sidecars[0]
    assert visibility == "internal"
    assert payload == {
        "tool": "media.apple_music_play",
        "capabilities": ["media.playback"],
        "status": "partial",
        "reason": "not_found",
        "retryable": True,
        "effects": [],
        "verification": "unverified",
        "recovery_hints": [],
        "provenance": {},
        "tool_call_id": "call-media-miss",
        "run_id": "run-outcome",
        "visibility": "internal",
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
    }
    assert all(event.get("event") != "agent.tool.outcome" for event in timeline)
    assert "canonical_outcome" not in raw_result
    assert raw_result["data"]["query"] == "private query"
    assert "private query" in messages[-1]["content"]
    assert "agent.tool.outcome" not in json.dumps(messages, ensure_ascii=False)


def test_legacy_event_adapter_cannot_accidentally_publish_internal_outcome() -> None:
    events: list[tuple[str, str, dict[str, Any]]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        events.append((run_id, event_type, payload))

    _runner(
        append_run_event=append_run_event,
        raw_result={"ok": True, "content": "done"},
    ).run(
        [
            {
                "protocol": "json_fallback",
                "tool": "workspace.read",
                "tool_call_id": "call-workspace-read",
                "input": {"path": "README.md"},
            }
        ],
        ["workspace.read"],
        broker=object(),
        messages=[{"role": "user", "content": "读取 README"}],
        timeline=[],
        artifacts=[],
        next_iteration=1,
        run_id="run-legacy-adapter",
        budget=_Budget(),
    )

    assert all(event_type != "agent.tool.outcome" for _, event_type, _ in events)


def test_canonical_outcome_sidecar_preserves_internal_execution_identity() -> None:
    events: list[tuple[str, str, dict[str, Any], str]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        visibility: str = "user",
    ) -> None:
        events.append((run_id, event_type, payload, visibility))

    _runner(
        append_run_event=append_run_event,
        raw_result={"ok": True, "content": "done"},
    ).run(
        [
            {
                "protocol": "json_fallback",
                "tool": "workspace.read",
                "tool_call_id": "workspace-recovery-call",
                "source_tool_call_id": "workspace-source-call",
                "request_id": "request-recovery",
                "source_request_id": "request-source",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "step_id": "resolve-workspace-file",
                "replan_request_id": "replan-1",
                "source": "runtime_replan_recovery",
                "input": {"path": "README.md"},
            }
        ],
        ["workspace.read"],
        broker=object(),
        messages=[{"role": "user", "content": "读取 README"}],
        timeline=[],
        artifacts=[],
        next_iteration=1,
        run_id="run-identity-sidecar",
        budget=_Budget(),
    )

    payload = next(payload for _, event_type, payload, _ in events if event_type == "agent.tool.outcome")
    assert {
        key: payload.get(key)
        for key in (
            "tool_call_id",
            "source_tool_call_id",
            "request_id",
            "source_request_id",
            "decision_id",
            "plan_id",
            "step_id",
            "replan_request_id",
            "source",
        )
    } == {
        "tool_call_id": "workspace-recovery-call",
        "source_tool_call_id": "workspace-source-call",
        "request_id": "request-recovery",
        "source_request_id": "request-source",
        "decision_id": "decision-1",
        "plan_id": "plan-1",
        "step_id": "resolve-workspace-file",
        "replan_request_id": "replan-1",
        "source": "runtime_replan_recovery",
    }
    assert payload["visibility"] == "internal"


def test_canonical_outcome_sidecar_marks_user_goal_skip_as_model_continuation() -> None:
    events: list[tuple[str, str, dict[str, Any], str]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        visibility: str = "user",
    ) -> None:
        events.append((run_id, event_type, payload, visibility))

    _runner(
        append_run_event=append_run_event,
        raw_result={
            "ok": False,
            "blocked_by_user_goal": True,
            "error": "user constraint",
        },
    ).run(
        [
            {
                "protocol": "json_fallback",
                "tool": "terminal.run",
                "tool_call_id": "terminal-blocked-by-goal",
                "input": {"command": "echo blocked"},
            }
        ],
        ["terminal.run"],
        broker=object(),
        messages=[{"role": "user", "content": "不要运行命令"}],
        timeline=[],
        artifacts=[],
        next_iteration=1,
        run_id="run-goal-constraint-sidecar",
        budget=_Budget(),
    )

    payload = next(payload for _, event_type, payload, _ in events if event_type == "agent.tool.outcome")
    assert payload["completion_impact"] == "continue_without_tool"


def test_canonical_outcome_sidecar_preserves_trusted_recovery_contract() -> None:
    events: list[tuple[str, str, dict[str, Any], str]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        visibility: str = "user",
    ) -> None:
        events.append((run_id, event_type, payload, visibility))

    _runner(
        append_run_event=append_run_event,
        raw_result={
            "ok": False,
            "reason": "workspace_boundary_refusal",
            "policy_refusal": True,
            "completion_impact": "report_refusal",
            "suggested_tool": "terminal.run",
        },
    ).run(
        [
            {
                "protocol": "tool_calls",
                "tool": "workspace.write_patch",
                "tool_call_id": "workspace-refusal",
                "recovery_link_kind": "suggested_tool",
                "recovery_source_tool": "workspace.read",
                "recovery_suggested_tool": "workspace.write_patch",
                "input": {"path": "../outside.txt"},
            }
        ],
        ["workspace.write_patch"],
        broker=object(),
        messages=[{"role": "user", "content": "Try outside write"}],
        timeline=[],
        artifacts=[],
        next_iteration=1,
        run_id="run-policy-refusal-sidecar",
        budget=_Budget(),
    )

    payload = next(payload for _, event_type, payload, _ in events if event_type == "agent.tool.outcome")
    assert payload["completion_impact"] == "report_refusal"
    assert payload["suggested_tools"] == ["terminal.run"]
    assert payload["recovery_link_kind"] == "suggested_tool"
    assert payload["recovery_source_tool"] == "workspace.read"
    assert payload["recovery_suggested_tool"] == "workspace.write_patch"
