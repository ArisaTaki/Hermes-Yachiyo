"""Tests for the generic recovery action execution seam."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.shell.agent.runtime.custom_api_agent import (
    RuntimeCustomApiAgentLoop,
    _CustomApiRecoveryRuntimePort,
)
from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionContext,
    RecoveryActionDisposition,
    RecoveryActionRegistry,
    RecoveryActionResult,
    RecoveryActionScope,
)
from apps.shell.agent.runtime.recovery_policies import RecoveryAssessment
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus, from_tool_result


class _UnusedRuntimePort:
    pass


def _context(capability: str) -> RecoveryActionContext:
    outcome = from_tool_result(
        f"{capability}.tool",
        {
            "ok": False,
            "error": "not_found",
            "retryable": True,
            "recovery_hints": ["entity_not_found"],
        },
        capabilities=(capability,),
    )
    return RecoveryActionContext(
        plan=RecoveryPlan(
            strategy_id="resolve-entity",
            action="resolve_entity",
            recovery_hint="entity_not_found",
            required_capabilities=(capability,),
            source_status=OutcomeStatus.FAILED,
            source_reason="not_found",
            scope_id=f"scope:{capability}",
        ),
        source_outcome=outcome,
        source_tool_call_id=f"call:{capability}",
        scope=RecoveryActionScope(
            allowed_tools=frozenset({f"{capability}.tool"}),
            iteration=1,
        ),
        runtime=_UnusedRuntimePort(),
    )


@dataclass
class _FakeAdapter:
    capability: str
    result: str | RecoveryActionResult
    error: Exception | None = None
    action: str = "resolve_entity"
    calls: int = 0

    def supports(self, context: RecoveryActionContext) -> bool:
        return self.capability in context.source_outcome.capabilities

    def execute(self, _context: RecoveryActionContext) -> RecoveryActionResult | str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def test_structured_result_distinguishes_terminal_completion_from_continuation() -> None:
    terminal = RecoveryActionResult.complete("media recovered")
    continuation = RecoveryActionResult.continue_plan(reason="discovery_completed")
    handoff = RecoveryActionResult.await_user(reason="discovery_no_match")

    assert terminal.disposition is RecoveryActionDisposition.TERMINAL_COMPLETION
    assert terminal.terminal_output == "media recovered"
    assert continuation.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    assert handoff.disposition is RecoveryActionDisposition.AWAIT_USER
    assert continuation.terminal_output == ""
    assert continuation.reason == "discovery_completed"
    assert handoff.reason == "discovery_no_match"


def test_terminal_completion_requires_nonempty_terminal_output() -> None:
    with pytest.raises(ValueError, match="terminal output"):
        RecoveryActionResult.complete("")


def test_terminal_completion_preserves_annotated_string_output() -> None:
    class _AnnotatedOutput(str):
        pass

    output = _AnnotatedOutput("recovered")
    output.metadata = {"source": "recovery"}

    result = RecoveryActionResult.complete(output)

    assert result.terminal_output is output
    assert result.terminal_output.metadata == {"source": "recovery"}


def test_registry_returns_not_handled_when_no_adapter_uniquely_owns_context() -> None:
    absent = _FakeAdapter("calendar.events", "unexpected")

    result = RecoveryActionRegistry((absent,)).execute(_context("media.playback"))

    assert result.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert result.reason == "no_unique_adapter"
    assert absent.calls == 0


def test_registry_preserves_adapter_execution_failure_intent() -> None:
    adapter = _FakeAdapter(
        "media.playback",
        RecoveryActionResult.failed(reason="retry_tool_failed"),
    )

    result = RecoveryActionRegistry((adapter,)).execute(_context("media.playback"))

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "retry_tool_failed"
    assert result.terminal_output == ""


def test_runtime_seam_journals_structured_failure_without_completed_event() -> None:
    source = _context("media.playback")
    adapter = _FakeAdapter(
        "media.playback",
        RecoveryActionResult.failed(reason="retry_tool_failed"),
    )
    loop = object.__new__(RuntimeCustomApiAgentLoop)
    loop._recovery_action_registry = RecoveryActionRegistry((adapter,))
    loop._timeline = lambda event, detail="", **payload: {
        "event": event,
        "detail": detail,
        **payload,
    }
    persisted: list[tuple[str, dict[str, object]]] = []
    loop._append_run_event = lambda _run_id, event, payload, **_kwargs: persisted.append(
        (event, payload)
    )
    timeline: list[dict[str, object]] = []

    result = loop._execute_runtime_recovery_plan(
        RecoveryAssessment(
            outcome=source.source_outcome,
            plan=source.plan,
            tool_call_id=source.source_tool_call_id,
        ),
        model_config={},
        allowed_tools=["media.playback.tool"],
        broker=object(),
        messages=[],
        timeline=timeline,
        artifacts=[],
        budget=object(),
        iteration=1,
        run_id="run-recovery",
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert [event["event"] for event in timeline] == [
        "agent.recovery.planned",
        "agent.recovery.failed",
    ]
    assert [event for event, _payload in persisted] == [
        "agent.recovery.planned",
        "agent.recovery.failed",
    ]


def test_same_action_resolves_different_media_and_file_adapters() -> None:
    media = _FakeAdapter("media.playback", "media recovered")
    files = _FakeAdapter("files.read", "file recovered")
    registry = RecoveryActionRegistry((media, files))

    assert (
        registry.execute(_context("media.playback")).terminal_output
        == "media recovered"
    )
    assert registry.execute(_context("files.read")).terminal_output == "file recovered"
    assert media.calls == 1
    assert files.calls == 1


def test_registry_fails_closed_for_zero_or_multiple_supporting_adapters() -> None:
    absent = _FakeAdapter("calendar.events", "unexpected")
    duplicate_a = _FakeAdapter("media.playback", "unexpected-a")
    duplicate_b = _FakeAdapter("media.playback", "unexpected-b")

    absent_result = RecoveryActionRegistry((absent,)).execute(
        _context("media.playback")
    )
    duplicate_result = RecoveryActionRegistry((duplicate_a, duplicate_b)).execute(
        _context("media.playback")
    )

    assert absent_result.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert duplicate_result.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert absent.calls == duplicate_a.calls == duplicate_b.calls == 0


def test_resolved_action_executes_failed_plan_at_most_once() -> None:
    adapter = _FakeAdapter("media.playback", "recovered")
    resolved = RecoveryActionRegistry((adapter,)).resolve(_context("media.playback"))

    assert resolved is not None
    assert resolved.context.plan.source_status is OutcomeStatus.FAILED
    first = resolved.execute()
    repeated = resolved.execute()

    assert first.terminal_output == "recovered"
    assert repeated.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert repeated.reason == "already_executed"
    assert adapter.calls == 1


def test_registry_does_not_swallow_adapter_exceptions() -> None:
    expected = RuntimeError("adapter failed")
    adapter = _FakeAdapter("media.playback", "", error=expected)

    with pytest.raises(RuntimeError, match="adapter failed") as exc_info:
        RecoveryActionRegistry((adapter,)).execute(_context("media.playback"))

    assert exc_info.value is expected
    assert adapter.calls == 1


class _PortOwner:
    def __init__(self, appended_events=()) -> None:
        self.appended_events = tuple(appended_events)
        self.calls = 0

    def _run_tool_requests(
        self,
        _requests,
        _allowed_tools,
        _broker,
        _messages,
        timeline,
        _artifacts,
        **_kwargs,
    ) -> None:
        self.calls += 1
        timeline.extend(dict(event) for event in self.appended_events)


def _runtime_port(owner: _PortOwner) -> _CustomApiRecoveryRuntimePort:
    return _CustomApiRecoveryRuntimePort(
        owner=owner,
        model_config={},
        allowed_tools=["workspace.list"],
        broker={},
        messages=[],
        timeline=[],
        artifacts=[],
        budget=object(),
        run_id="run-recovery",
    )


@pytest.mark.parametrize(
    "requests",
    [
        ({"tool": "workspace.list", "tool_call_id": "", "input": {}},),
        (
            {"tool": "workspace.list", "tool_call_id": "duplicate", "input": {}},
            {"tool": "workspace.list", "tool_call_id": "duplicate", "input": {}},
        ),
    ],
)
def test_runtime_port_rejects_empty_or_duplicate_tool_call_ids_before_execution(
    requests,
) -> None:
    owner = _PortOwner()

    with pytest.raises(ValueError, match="tool_call_id"):
        _runtime_port(owner).execute_tools(
            requests,
            allowed_tools=("workspace.list",),
            next_iteration=2,
        )

    assert owner.calls == 0


def test_runtime_port_correlates_only_terminal_event_for_expected_tool() -> None:
    owner = _PortOwner(
        (
            {
                "event": "agent.progress",
                "tool": "workspace.list",
                "tool_call_id": "list-files",
                "result": {"ok": True, "value": "progress-decoy"},
            },
            {
                "event": "agent.tool.call",
                "tool": "desktop.list_apps",
                "tool_call_id": "list-files",
                "result": {"ok": True, "value": "wrong-tool-decoy"},
            },
            {
                "event": "agent.tool.call",
                "tool": "workspace.list",
                "tool_call_id": "list-files",
                "result": {"ok": True, "value": "expected"},
            },
        )
    )

    batch = _runtime_port(owner).execute_tools(
        ({"tool": "workspace.list", "tool_call_id": "list-files", "input": {}},),
        allowed_tools=("workspace.list",),
        next_iteration=2,
    )

    assert batch.result_for("list-files") == {"ok": True, "value": "expected"}
    assert batch.tool_result_for("list-files") is not None
    assert batch.tool_result_for("list-files").event_type == "agent.tool.call"
    assert owner.calls == 1


def test_runtime_port_preserves_fatal_tool_event_for_recovery_classification() -> None:
    owner = _PortOwner(
        (
            {
                "event": "agent.tool.failed",
                "tool": "workspace.list",
                "tool_call_id": "list-files",
                "result": {"ok": True, "value": "misleading-payload"},
            },
        )
    )

    batch = _runtime_port(owner).execute_tools(
        ({"tool": "workspace.list", "tool_call_id": "list-files", "input": {}},),
        allowed_tools=("workspace.list",),
        next_iteration=2,
    )

    correlated = batch.tool_result_for("list-files")
    assert correlated is not None
    assert correlated.failed is True
