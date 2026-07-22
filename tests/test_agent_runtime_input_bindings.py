from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from apps.shell.agent.runtime import custom_api_agent as custom_api_agent_module
from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.runtime.goal_contract import GoalContract
from apps.shell.agent.runtime.input_bindings import (
    InputBindingResolutionError,
    context_binding_unresolved_result,
    resolve_tool_request_input_bindings,
    resolve_workspace_file_selection,
    validate_workspace_file_resolution_receipt,
)
from apps.shell.agent.runtime.tool_execution import RuntimeToolRequestRunner
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent import planner_execution as planner_execution_module
from apps.shell.yachiyo_agent.contracts import ToolPlanStepSnapshot
from apps.shell.yachiyo_agent.planner_projection import planner_selection_payload
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_envelope_from_decision,
    runtime_execution_requests_from_envelope_payload,
)

RUN_ID = "run-context-binding"
PLAN_ID = "plan-context-binding"


def _workspace_selection_request(**overrides: Any) -> dict[str, Any]:
    return {
        "tool": "data.analyze",
        "tool_call_id": "call-analyze",
        "plan_id": PLAN_ID,
        "step_id": "analyze-discovered-data",
        "depends_on": ["inspect-data-source"],
        "input": {
            "path": "<selected file from workspace.list>",
            "selection_source": "workspace.list",
            "source_scope": "Downloads",
            "pattern": "*.csv",
            "source_kind": "csv",
            "selection": "latest",
            "artifact_path": "analysis-report.md",
        },
        **overrides,
    }


def _workspace_selection_source_event(**overrides: Any) -> dict[str, Any]:
    return {
        "event": "agent.tool.call",
        "detail": "workspace.list",
        "run_id": RUN_ID,
        "plan_id": PLAN_ID,
        "step_id": "inspect-data-source",
        "tool_call_id": "call-inspect",
        "input_preview": {
            "path": "Downloads",
            "pattern": "*.csv",
            "file_type": "csv",
            "selection": "latest",
        },
        "result": {
            "ok": True,
            "path": "Downloads",
            "entries": [
                {"name": "older.csv", "type": "file", "mtime_ns": 10},
                {"name": "latest.csv", "type": "file", "mtime_ns": 20},
            ],
        },
        **overrides,
    }


def _binding(**overrides: Any) -> dict[str, Any]:
    return {
        "binding_id": "binding-app-name",
        "source_step_id": "discover-app",
        "source_tool_name": "desktop.list_apps",
        "source_result_path": "/data/best_match/name",
        "target_input_path": "/input/app_name",
        "value_type": "string",
        "required": True,
        "max_bytes": 256,
        **overrides,
    }


def _request(**overrides: Any) -> dict[str, Any]:
    return {
        "tool": "media.music_app_open_and_play",
        "tool_call_id": "call-target",
        "plan_id": PLAN_ID,
        "step_id": "play-media",
        "depends_on": ["discover-app"],
        "input": {"query": "Moonlight"},
        "input_bindings": [_binding()],
        **overrides,
    }


def _source_event(**overrides: Any) -> dict[str, Any]:
    return {
        "event": "agent.tool.call",
        "detail": "desktop.list_apps",
        "run_id": RUN_ID,
        "plan_id": PLAN_ID,
        "step_id": "discover-app",
        "tool_call_id": "call-source",
        "result": {
            "ok": True,
            "data": {"best_match": {"name": "Music"}},
        },
        **overrides,
    }


def test_resolves_exact_source_and_emits_value_free_receipt() -> None:
    resolution = resolve_tool_request_input_bindings(
        _request(),
        [_source_event()],
        run_id=RUN_ID,
    )

    assert resolution.input == {"query": "Moonlight", "app_name": "Music"}
    assert resolution.bound_top_level_fields == frozenset({"app_name"})
    assert len(resolution.receipts) == 1
    receipt = resolution.receipts[0].to_payload()
    assert receipt["source_tool_call_id"] == "call-source"
    assert receipt["source_step_id"] == "discover-app"
    assert receipt["target_input_path"] == "/input/app_name"
    assert receipt["value_digest"].startswith("sha256:")
    assert receipt["value_bytes"] == len(json.dumps("Music").encode("utf-8"))
    assert "Music" not in json.dumps(receipt)


def test_rejects_source_that_is_not_an_explicit_dependency() -> None:
    with pytest.raises(
        InputBindingResolutionError,
        match="input_binding_source_not_dependency",
    ):
        resolve_tool_request_input_bindings(
            _request(depends_on=["some-other-step"]),
            [_source_event()],
            run_id=RUN_ID,
        )


@pytest.mark.parametrize(
    "event_override",
    [
        {"run_id": "run-other"},
        {"plan_id": "plan-other"},
        {"step_id": "step-other"},
        {"detail": "desktop.running_apps"},
        {"event": "agent.tool.failed"},
        {"result": {"ok": False, "error": "failed"}},
        {"tool_call_id": ""},
    ],
)
def test_rejects_uncorrelated_or_unsuccessful_source(
    event_override: dict[str, Any],
) -> None:
    with pytest.raises(
        InputBindingResolutionError,
        match="input_binding_source_unresolved",
    ):
        resolve_tool_request_input_bindings(
            _request(),
            [_source_event(**event_override)],
            run_id=RUN_ID,
        )


def test_rejects_ambiguous_successful_source_events() -> None:
    with pytest.raises(
        InputBindingResolutionError,
        match="input_binding_source_ambiguous",
    ):
        resolve_tool_request_input_bindings(
            _request(),
            [
                _source_event(),
                _source_event(tool_call_id="call-source-retry"),
            ],
            run_id=RUN_ID,
        )


def test_persisted_payload_identity_cannot_be_overridden_by_public_wrapper() -> None:
    authoritative = _source_event()
    authoritative.pop("event")
    persisted = {
        "event_type": "agent.tool.call",
        "run_id": "public-wrapper-run",
        "plan_id": "public-wrapper-plan",
        "step_id": "public-wrapper-step",
        "detail": "public.wrapper.tool",
        "payload": authoritative,
    }

    resolution = resolve_tool_request_input_bindings(
        _request(),
        [persisted],
        run_id=RUN_ID,
    )

    assert resolution.input["app_name"] == "Music"
    assert resolution.receipts[0].source_tool_call_id == "call-source"


@pytest.mark.parametrize(
    ("binding_override", "reason"),
    [
        ({"source_result_path": "data/best_match/name"}, "json_pointer_invalid"),
        ({"source_result_path": "/_private/value"}, "json_pointer_invalid"),
        ({"target_input_path": "/approval_required"}, "target_path_invalid"),
        ({"target_input_path": "/input/../tool"}, "target_path_invalid"),
        ({"value_type": "mapping"}, "value_type_invalid"),
        ({"max_bytes": 0}, "max_bytes_invalid"),
    ],
)
def test_rejects_unsafe_binding_contract(
    binding_override: dict[str, Any],
    reason: str,
) -> None:
    with pytest.raises(InputBindingResolutionError, match=reason):
        resolve_tool_request_input_bindings(
            _request(input_bindings=[_binding(**binding_override)]),
            [_source_event()],
            run_id=RUN_ID,
        )


@pytest.mark.parametrize(
    ("request_override", "event_override", "reason"),
    [
        (
            {"input": {"query": "Moonlight", "app_name": "Forged"}},
            {},
            "target_conflict",
        ),
        ({}, {"result": {"ok": True, "data": {"best_match": {"name": 42}}}}, "type_mismatch"),
        (
            {"input_bindings": [_binding(max_bytes=4)]},
            {},
            "value_too_large",
        ),
    ],
)
def test_rejects_conflicting_wrong_type_or_oversized_value(
    request_override: dict[str, Any],
    event_override: dict[str, Any],
    reason: str,
) -> None:
    with pytest.raises(InputBindingResolutionError, match=reason):
        resolve_tool_request_input_bindings(
            _request(**request_override),
            [_source_event(**event_override)],
            run_id=RUN_ID,
        )


class _Budget:
    def __init__(self) -> None:
        self.claims: list[str] = []

    def claim_tool_call(self, tool_name: str, **_kwargs: Any) -> None:
        self.claims.append(tool_name)


class _PendingApprovalBuilder:
    def build(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("binding tests must not request approval")


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def _runner(
    calls: list[dict[str, Any]],
    *,
    pending_approval_builder: Any | None = None,
    enforce_request_approval: bool = False,
) -> RuntimeToolRequestRunner:
    def call_agent_tool(
        request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if enforce_request_approval and request.get("approval_required") is True:
            return {
                "ok": False,
                "approval_required": True,
                "tool": request.get("tool"),
                "status": "approval_required",
                "policy_reason": request.get("policy_reason") or "planner approval",
            }
        calls.append(dict(request))
        return {"ok": True, "status": "success"}

    return RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: _Budget(),
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=lambda *_args, **_kwargs: None,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=pending_approval_builder or _PendingApprovalBuilder(),
        call_agent_tool=call_agent_tool,
    )


def test_runner_injects_bound_input_before_target_tool_execution() -> None:
    calls: list[dict[str, Any]] = []
    timeline = [
        _source_event(),
        # A later legacy discovery result would win the old timeline scan.
        # The explicit source-step binding must remain authoritative.
        _source_event(
            step_id="unrelated-discovery",
            tool_call_id="call-unrelated",
            input_preview={"query": "Music"},
            result={
                "ok": True,
                "data": {
                    "best_match": {
                        "name": "Spotify",
                        "match_score": 100,
                    }
                },
            },
        ),
    ]
    messages = [{"role": "user", "content": "Play the discovered title"}]

    _runner(calls).run(
        [_request()],
        ["media.music_app_open_and_play"],
        object(),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    assert len(calls) == 1
    assert calls[0]["input"] == {"query": "Moonlight", "app_name": "Music"}
    resolved = next(
        event for event in timeline if event.get("event") == "agent.tool.input_resolved"
    )
    assert resolved["resolution_kind"] == "runtime_input_binding"
    assert resolved["input_binding_receipts"][0]["source_tool_call_id"] == "call-source"
    assert "Music" not in json.dumps(resolved["input_binding_receipts"])


def test_runner_transfers_browser_text_to_desktop_input_without_receipt_leak() -> None:
    page_text = "A concise research summary from the current page."
    source_event = {
        "event": "agent.tool.call",
        "detail": "browser.extract_text",
        "run_id": RUN_ID,
        "plan_id": PLAN_ID,
        "step_id": "read-page",
        "tool_call_id": "call-read-page",
        "result": {"ok": True, "data": {"text": page_text}},
    }
    request = {
        "tool": "app.open_and_type_into_ui_element",
        "tool_call_id": "call-write-page",
        "plan_id": PLAN_ID,
        "step_id": "write-page-summary",
        "depends_on": ["read-page"],
        "input": {"app_name": "Notes", "target": "Body"},
        "input_bindings": [
            _binding(
                binding_id="binding-page-text",
                source_step_id="read-page",
                source_tool_name="browser.extract_text",
                source_result_path="/data/text",
                target_input_path="/input/text",
                max_bytes=1024,
            )
        ],
    }
    calls: list[dict[str, Any]] = []
    timeline = [source_event]

    _runner(calls).run(
        [request],
        ["app.open_and_type_into_ui_element"],
        object(),
        [{"role": "user", "content": "Put the page summary in my note"}],
        timeline,
        [],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    assert len(calls) == 1
    assert calls[0]["input"]["text"] == page_text
    resolved = next(
        event for event in timeline if event.get("event") == "agent.tool.input_resolved"
    )
    assert page_text not in json.dumps(resolved["input_binding_receipts"])


def test_runner_reads_exact_artifact_after_path_binding(tmp_path) -> None:
    artifact_text = "Verified research summary from the broker-owned artifact."
    (tmp_path / "research-summary.md").write_text(artifact_text, encoding="utf-8")
    source_event = {
        "event": "agent.tool.call",
        "detail": "artifact.write",
        "run_id": RUN_ID,
        "plan_id": PLAN_ID,
        "step_id": "write-research-artifact",
        "tool_call_id": "call-write-artifact",
        "result": {"ok": True, "path": "research-summary.md", "bytes": 64},
    }
    request = {
        "tool": "desktop.safe_type_text",
        "tool_call_id": "call-insert-artifact",
        "plan_id": PLAN_ID,
        "step_id": "insert-research-into-target-app",
        "depends_on": [
            "prepare-research-target-app",
            "write-research-artifact",
        ],
        "input": {
            "body_source": "research_artifact",
            "artifact_path": "research-summary.md",
            "target_action": "app_paste",
        },
        "input_bindings": [
            _binding(
                binding_id="binding-research-artifact",
                source_step_id="write-research-artifact",
                source_tool_name="artifact.write",
                source_result_path="/path",
                target_input_path="/input/artifact_path",
                max_bytes=1024,
            )
        ],
    }
    calls: list[dict[str, Any]] = []

    class Broker:
        artifact_root = tmp_path

    timeline = [source_event]
    _runner(calls).run(
        [request],
        ["desktop.safe_type_text"],
        Broker(),
        [{"role": "user", "content": "Put the research in my note"}],
        timeline,
        [{"path": "research-summary.md", "source_tool": "artifact.write"}],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    assert len(calls) == 1
    assert calls[0]["input"]["artifact_path"] == "research-summary.md"
    assert calls[0]["input"]["text"] == artifact_text
    resolved = next(
        event for event in timeline if event.get("event") == "agent.tool.input_resolved"
    )
    assert artifact_text not in json.dumps(resolved)


def test_runner_rejects_oversized_workspace_content_before_desktop_call() -> None:
    source_event = {
        "event": "agent.tool.call",
        "detail": "workspace.read",
        "run_id": RUN_ID,
        "plan_id": PLAN_ID,
        "step_id": "read-file",
        "tool_call_id": "call-read-file",
        "result": {"ok": True, "content": "too long for this binding"},
    }
    request = {
        "tool": "app.open_and_type_into_ui_element",
        "tool_call_id": "call-write-file",
        "plan_id": PLAN_ID,
        "step_id": "write-file-content",
        "depends_on": ["read-file"],
        "input": {"app_name": "Notes", "target": "Body"},
        "input_bindings": [
            _binding(
                binding_id="binding-file-content",
                source_step_id="read-file",
                source_tool_name="workspace.read",
                source_result_path="/content",
                target_input_path="/input/text",
                max_bytes=8,
            )
        ],
    }
    calls: list[dict[str, Any]] = []
    timeline = [source_event]

    _runner(calls).run(
        [request],
        ["app.open_and_type_into_ui_element"],
        object(),
        [{"role": "user", "content": "Put the file in my note"}],
        timeline,
        [],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    assert calls == []
    skipped = next(
        event for event in timeline if event.get("event") == "agent.tool.skipped"
    )
    assert skipped["result"]["error"] == "context_binding_unresolved"
    assert skipped["result"]["reason"] == "input_binding_value_too_large"
    assert any(event.get("event") == "agent.replan.requested" for event in timeline)


def test_runner_fails_closed_without_calling_target_and_requests_replan() -> None:
    calls: list[dict[str, Any]] = []
    timeline = [_source_event(plan_id="wrong-plan")]
    messages = [{"role": "user", "content": "Play the discovered title"}]

    _runner(calls).run(
        [_request()],
        ["media.music_app_open_and_play"],
        object(),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    assert calls == []
    skipped = next(
        event
        for event in reversed(timeline)
        if event.get("event") == "agent.tool.skipped"
    )
    assert skipped["result"] == context_binding_unresolved_result(
        InputBindingResolutionError(
            "input_binding_source_unresolved",
            binding_id="binding-app-name",
        )
    )
    assert any(event.get("event") == "agent.replan.requested" for event in timeline)


def test_runtime_execution_envelope_preserves_binding_contract() -> None:
    binding = _binding()
    envelope = {
        "envelope_id": "envelope-context-binding",
        "requests": [
            {
                "request_id": "request-source",
                "plan_id": PLAN_ID,
                "step_id": "discover-app",
                "tool_name": "desktop.list_apps",
                "input": {"query": "music"},
                "status": "planned",
            },
            {
                "request_id": "request-target",
                "plan_id": PLAN_ID,
                "step_id": "play-media",
                "tool_name": "media.music_app_open_and_play",
                "input": {"query": "Moonlight"},
                "depends_on": ["discover-app"],
                "input_bindings": [binding],
                "status": "planned",
            }
        ],
    }

    projected = runtime_execution_requests_from_envelope_payload(
        envelope,
        allowed_tools=["desktop.list_apps", "media.music_app_open_and_play"],
    )

    assert len(projected) == 2
    assert projected[1]["depends_on"] == ["discover-app"]
    assert projected[1]["input_bindings"] == [binding]


def test_planner_trace_annotation_preserves_step_binding_contract() -> None:
    binding = _binding()
    step = ToolPlanStepSnapshot(
        step_id="play-media",
        title="Play media",
        capability_id="media.playback",
        tool_name="media.music_app_open_and_play",
        depends_on=["discover-app"],
        input_bindings=[binding],
    )
    decision = SimpleNamespace(
        decision_id="decision-context-binding",
        selected_intent=SimpleNamespace(kind="media_playback"),
        plan=SimpleNamespace(
            plan_id=PLAN_ID,
            tool_plan=SimpleNamespace(plan_id=PLAN_ID),
            task_core=None,
        ),
    )
    request = {
        "tool": "media.music_app_open_and_play",
        "input": {"query": "Moonlight"},
        "depends_on": ["model-forged-source"],
        "input_bindings": [
            _binding(
                binding_id="model-forged-binding",
                source_step_id="model-forged-source",
            )
        ],
    }

    planner_execution_module._annotate_request_trace(
        request,
        decision,
        step,
        include_trace=True,
    )

    assert request["depends_on"] == ["discover-app"]
    assert request["input_bindings"] == [binding]


def test_model_followup_replaces_binding_metadata_with_trusted_pending_step() -> None:
    trusted = _binding(binding_id="trusted-binding")
    request = {
        "tool": "media.music_app_open_and_play",
        "input": {"query": "Moonlight"},
        "input_bindings": [
            _binding(
                binding_id="model-forged-binding",
                source_result_path="/data/private_value",
            )
        ],
    }

    custom_api_agent_module._attach_model_followup_pending_plan_trace_metadata(
        request,
        {
            "step_id": "play-media",
            "depends_on": ["discover-app"],
            "input_bindings": [trusted],
        },
        {"plan_id": PLAN_ID},
    )

    assert request["input_bindings"] == [trusted]


def test_artifact_bound_followup_does_not_copy_model_text_into_desktop_input() -> None:
    artifact_binding = _binding(
        binding_id="binding-research-artifact",
        source_step_id="write-research-artifact",
        source_tool_name="artifact.write",
        source_result_path="/path",
        target_input_path="/input/artifact_path",
        max_bytes=1024,
    )

    requests = custom_api_agent_module._model_followup_pending_plan_requests(
        {
            "plan_id": PLAN_ID,
            "pending_plan_steps": [
                {
                    "step_id": "insert-research-into-target-app",
                    "tool_name": "desktop.safe_type_text",
                    "capability_id": "desktop.ui_operation",
                    "depends_on": [
                        "prepare-research-target-app",
                        "write-research-artifact",
                    ],
                    "input_preview": {
                        "body_source": "research_artifact",
                        "artifact_path": "research-summary.md",
                        "target_action": "app_paste",
                    },
                    "input_bindings": [artifact_binding],
                }
            ],
        },
        ["desktop.safe_type_text"],
        generated_content="model-authored summary must not bypass the artifact",
    )

    assert len(requests) == 1
    assert requests[0]["input"] == {
        "body_source": "research_artifact",
        "artifact_path": "research-summary.md",
        "target_action": "app_paste",
    }
    assert requests[0]["input_bindings"] == [artifact_binding]


def test_real_planner_artifact_handoff_survives_followup_and_runner(tmp_path) -> None:
    prompt = "搜索上海明天天气，并把结果写入备忘录"
    allowed_tools = [
        "browser.search",
        "browser.extract_text",
        "artifact.write",
        "app.open",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    planned_requests = planner_execution_module.planner_tool_requests_for_decision(
        decision,
        allowed_tools,
    )
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
    )
    assert envelope is not None
    envelope_payload = envelope.model_dump(mode="json")
    selection_payload = planner_selection_payload(
        decision=decision,
        planner_requests=planned_requests,
        legacy_requests=[],
        selected_requests=planned_requests,
        selected_source="runtime_planner",
        selected_reason="planner_selected",
    )
    selection_payload["yachiyo_execution_envelope"] = envelope_payload
    observation_request = next(
        request for request in planned_requests if request.get("continue_to_model") is True
    )
    assert observation_request["continue_to_model"] is True
    observation_event = {
        "event": "agent.tool.call",
        "detail": observation_request["tool"],
        "run_id": RUN_ID,
        "plan_id": decision.plan.plan_id,
        "step_id": observation_request["step_id"],
        "tool_call_id": "call-web-observation",
        "result": {"ok": True, "data": {"text": "Raw weather search results"}},
    }

    followup_context = custom_api_agent_module._model_followup_context_payload(
        planned_requests,
        selection_payload,
        allowed_tools=allowed_tools,
        timeline=[observation_event],
    )
    sink_step = next(
        request
        for request in followup_context["pending_execution_requests"]
        if request["step_id"] == "insert-research-into-target-app"
    )
    trusted_sink = next(
        request
        for request in envelope_payload["requests"]
        if request["step_id"] == "insert-research-into-target-app"
    )
    assert sink_step["input_bindings"] == trusted_sink["input_bindings"]
    assert sink_step["action_target"] == trusted_sink["action_target"]

    fallback_selection = dict(selection_payload)
    fallback_selection.pop("yachiyo_execution_envelope")
    fallback_context = custom_api_agent_module._model_followup_context_payload(
        planned_requests,
        fallback_selection,
        allowed_tools=allowed_tools,
        timeline=[observation_event],
    )
    fallback_sink = next(
        step
        for step in fallback_context["pending_plan_steps"]
        if step["step_id"] == "insert-research-into-target-app"
    )
    assert fallback_sink["input_bindings"] == trusted_sink["input_bindings"]

    model_text = "Exact broker-owned weather summary for the Notes sink."
    followup_context["run_id"] = RUN_ID
    inspect_step = next(
        step
        for step in followup_context["pending_execution_requests"]
        if step["step_id"] == "inspect-web-search-results"
    )
    inspect_call_id = "call-inspect-web-search-results"
    inspect_terminal = {
        "event": "agent.tool.call",
        "detail": inspect_step["tool_name"],
        "run_id": RUN_ID,
        "decision_id": decision.decision_id,
        "plan_id": decision.plan.plan_id,
        "step_id": inspect_step["step_id"],
        "tool_call_id": inspect_call_id,
        "result": {"ok": True, "data": {"text": "Grounded weather details"}},
    }
    inspect_completed = {
        "event": "agent.task.todo.updated",
        "run_id": RUN_ID,
        "decision_id": decision.decision_id,
        "plan_id": decision.plan.plan_id,
        "step_id": inspect_step["step_id"],
        "tool": inspect_step["tool_name"],
        "status": "completed",
        "source": "runtime_planner",
        "source_event": {
            "event": "agent.tool.call",
            "detail": inspect_step["tool_name"],
            "tool_call_id": inspect_call_id,
        },
        "result_preview": {"ok": True},
    }
    materialization_timeline = [observation_event, inspect_terminal, inspect_completed]
    canonical_tail = custom_api_agent_module._model_followup_pending_plan_requests(
        followup_context,
        allowed_tools,
        generated_content=model_text,
        timeline=materialization_timeline,
        allow_materialization_rebind=True,
    )
    goal_contract = GoalContract.from_payload(
        decision.plan.task_core.goal_contract.model_dump()
    )
    fresh_tail = custom_api_agent_module._fresh_materialized_execution_bindings(
        canonical_tail,
        followup_context,
        generated_content=model_text,
        goal_contract=goal_contract,
        run_id=RUN_ID,
    )
    assert [request["tool"] for request in fresh_tail] == [
        "artifact.write",
        "app.open",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    artifact_request, _prepare_request, sink_request, _verify_request = fresh_tail
    assert artifact_request["input"]["content"] == model_text
    assert sink_request["request_id"] != trusted_sink["request_id"]
    assert sink_request["materialized_from_request_id"] == trusted_sink["request_id"]
    assert sink_request["materialization_binding_id"] == artifact_request[
        "materialization_binding_id"
    ]
    assert sink_request["materialized_content_sha256"] == hashlib.sha256(
        model_text.encode("utf-8")
    ).hexdigest()
    assert sink_request["approval_required"] is True
    assert sink_request["depends_on"] == [
        "prepare-research-target-app",
        "write-research-artifact",
    ]
    assert "text" not in sink_request["input"]
    assert sink_request["input_bindings"] == trusted_sink["input_bindings"]

    artifact_text = model_text
    artifact_path = str(trusted_sink["input"]["artifact_path"])
    (tmp_path / artifact_path).write_text(artifact_text, encoding="utf-8")

    class Broker:
        artifact_root = tmp_path

    calls: list[dict[str, Any]] = []
    pending_requests: list[dict[str, Any]] = []

    class PendingApprovalBuilder:
        def build(self, tool_request, **_kwargs):
            pending_requests.append(dict(tool_request))
            return {
                "approval_id": "approval-research-sink",
                "tool": tool_request["tool"],
                "tool_request": dict(tool_request),
            }

    timeline = [
        {
            "event": "agent.tool.call",
            "detail": "artifact.write",
            "run_id": RUN_ID,
            "decision_id": decision.decision_id,
            "plan_id": decision.plan.plan_id,
            "step_id": "write-research-artifact",
            "tool_call_id": "call-write-research-artifact",
            "result": {
                "ok": True,
                "path": artifact_path,
                "postcondition_verified": True,
            },
        },
        {
            "event": "agent.tool.call",
            "detail": "app.open",
            "run_id": RUN_ID,
            "decision_id": decision.decision_id,
            "plan_id": decision.plan.plan_id,
            "step_id": "prepare-research-target-app",
            "tool_call_id": "call-prepare-research-target-app",
            "result": {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": "Notes", "launch_verified": True},
                "postcondition_verified": True,
            },
        },
    ]
    with pytest.raises(AgentApprovalRequired):
        _runner(
            calls,
            pending_approval_builder=PendingApprovalBuilder(),
            enforce_request_approval=True,
        ).run(
            [sink_request],
            allowed_tools,
            Broker(),
            [{"role": "user", "content": prompt}],
            timeline,
            [{"path": artifact_path, "source_tool": "artifact.write"}],
            next_iteration=1,
            run_id=RUN_ID,
            budget=_Budget(),
        )

    assert calls == []
    assert len(pending_requests) == 1
    approved_request = pending_requests[0]
    assert approved_request["input"]["artifact_path"] == artifact_path
    assert approved_request["input"]["text"] == artifact_text
    assert approved_request["materialization_binding_id"] == sink_request[
        "materialization_binding_id"
    ]
    assert approved_request["materialized_content_sha256"] == hashlib.sha256(
        artifact_text.encode("utf-8")
    ).hexdigest()


def test_workspace_file_selection_receipt_binds_exact_discovery_lineage() -> None:
    resolution = resolve_workspace_file_selection(
        _workspace_selection_request(),
        [_workspace_selection_source_event()],
        run_id=RUN_ID,
    )

    assert resolution.resolved_path == "Downloads/latest.csv"
    assert resolution.resolved_paths == ("Downloads/latest.csv",)
    assert resolution.receipt.to_payload() == {
        "version": 1,
        "resolution_kind": "workspace_file_selection",
        "run_id": RUN_ID,
        "plan_id": PLAN_ID,
        "target_step_id": "analyze-discovered-data",
        "target_tool_name": "data.analyze",
        "target_tool_call_id": "call-analyze",
        "source_step_id": "inspect-data-source",
        "source_tool_name": "workspace.list",
        "source_tool_call_id": "call-inspect",
        "requested_path": "<selected file from workspace.list>",
        "resolved_path": "Downloads/latest.csv",
        "resolved_paths": ["Downloads/latest.csv"],
        "source_scope": "Downloads",
        "pattern": "*.csv",
        "file_type": "csv",
        "selection": "latest",
    }


@pytest.mark.parametrize(
    "source_override",
    [
        {"run_id": "other-run"},
        {"plan_id": "other-plan"},
        {"step_id": "other-step"},
        {"tool_call_id": ""},
    ],
)
def test_workspace_file_selection_rejects_uncorrelated_discovery(
    source_override: dict[str, Any],
) -> None:
    with pytest.raises(
        InputBindingResolutionError,
        match="workspace_file_resolution_source_unresolved",
    ):
        resolve_workspace_file_selection(
            _workspace_selection_request(),
            [_workspace_selection_source_event(**source_override)],
            run_id=RUN_ID,
        )


def test_workspace_file_selection_rejects_out_of_scope_result() -> None:
    source = _workspace_selection_source_event(
        result={
            "ok": True,
            "path": "Downloads",
            "entries": [
                {
                    "path": "../private.csv",
                    "name": "private.csv",
                    "type": "file",
                    "mtime_ns": 20,
                }
            ],
        }
    )

    with pytest.raises(
        InputBindingResolutionError,
        match="workspace_file_resolution_path_unsafe",
    ):
        resolve_workspace_file_selection(
            _workspace_selection_request(),
            [source],
            run_id=RUN_ID,
        )


def test_workspace_file_selection_receipt_replays_against_source_and_target() -> None:
    request = _workspace_selection_request()
    source = _workspace_selection_source_event()
    resolution = resolve_workspace_file_selection(
        request,
        [source],
        run_id=RUN_ID,
    )
    receipt = resolution.receipt.to_payload()
    target_event = {
        "event": "agent.tool.call",
        "detail": "data.analyze",
        "run_id": RUN_ID,
        "plan_id": PLAN_ID,
        "step_id": "analyze-discovered-data",
        "tool_call_id": "call-analyze",
        "input_preview": {
            "path": "Downloads/latest.csv",
            "artifact_path": "analysis-report.md",
        },
        "action_target": {
            "kind": "workspace_file",
            "action": "analyze_data_file",
            "expected_path": "<selected file from workspace.list>",
            "path": "Downloads/latest.csv",
            "resolution_required": True,
            "workspace_file_resolution": receipt,
        },
        "result": {
            "ok": True,
            "path": "Downloads/latest.csv",
            "postcondition_verified": True,
        },
    }

    assert validate_workspace_file_resolution_receipt(
        receipt,
        target_event,
        [source, target_event],
        run_id=RUN_ID,
    ) is True
    assert validate_workspace_file_resolution_receipt(
        {**receipt, "source_tool_call_id": "forged-call"},
        target_event,
        [source, target_event],
        run_id=RUN_ID,
    ) is False
    assert validate_workspace_file_resolution_receipt(
        receipt,
        {
            **target_event,
            "input_preview": {
                "path": "Downloads/older.csv",
                "artifact_path": "analysis-report.md",
            },
        },
        [source, target_event],
        run_id=RUN_ID,
    ) is False
    assert validate_workspace_file_resolution_receipt(
        receipt,
        target_event,
        [target_event],
        run_id=RUN_ID,
    ) is False


def test_runner_projects_resolved_workspace_target_and_receipt_to_tool_event_context() -> None:
    calls: list[dict[str, Any]] = []
    request = {
        **_workspace_selection_request(),
        "action_target": {
            "kind": "workspace_file",
            "action": "analyze_data_file",
            "selection_source": "workspace.list",
            "path": "<selected file from workspace.list>",
            "source_scope": "Downloads",
            "pattern": "*.csv",
            "source_kind": "csv",
            "selection": "latest",
            "artifact_path": "analysis-report.md",
            "step_id": "analyze-discovered-data",
        },
    }
    timeline = [_workspace_selection_source_event()]

    _runner(calls).run(
        [request],
        ["data.analyze"],
        object(),
        [{"role": "user", "content": "Analyze the latest CSV"}],
        timeline,
        [],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    assert len(calls) == 1
    executed = calls[0]
    assert executed["input"]["path"] == "Downloads/latest.csv"
    assert executed["action_target"]["expected_path"] == (
        "<selected file from workspace.list>"
    )
    assert executed["action_target"]["path"] == "Downloads/latest.csv"
    assert executed["action_target"]["resolution_required"] is True
    receipt = executed["workspace_file_resolution"]
    assert receipt["source_tool_call_id"] == "call-inspect"
    assert receipt["source_step_id"] == "inspect-data-source"
    assert receipt["plan_id"] == PLAN_ID
    assert executed["action_target"]["workspace_file_resolution"] == receipt
    resolved_event = next(
        event for event in timeline if event.get("event") == "agent.tool.input_resolved"
    )
    assert resolved_event["workspace_file_resolution"] == receipt


def test_runner_rejects_partial_planned_workspace_lineage_without_legacy_scan() -> None:
    calls: list[dict[str, Any]] = []
    request = _workspace_selection_request(step_id="")
    timeline = [_workspace_selection_source_event()]

    _runner(calls).run(
        [request],
        ["data.analyze"],
        object(),
        [{"role": "user", "content": "Analyze the latest CSV"}],
        timeline,
        [],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    assert calls == []
    skipped = next(
        event for event in timeline if event.get("event") == "agent.tool.skipped"
    )
    assert skipped["result"]["error"] == "file_resolution_failed"
    assert not any(
        event.get("event") == "agent.tool.input_resolved" for event in timeline
    )


def test_runner_projects_multiple_workspace_paths_from_one_correlated_discovery() -> None:
    calls: list[dict[str, Any]] = []
    request = _workspace_selection_request(
        input={
            "path": "<selected files from workspace.list>",
            "selection_source": "workspace.list",
            "source_scope": "Downloads",
            "pattern": "*.csv",
            "source_kind": "csv",
            "selection": "all",
            "artifact_path": "analysis-report.md",
        },
        action_target={
            "kind": "workspace_file",
            "action": "analyze_data_file",
            "selection_source": "workspace.list",
            "path": "<selected files from workspace.list>",
            "source_scope": "Downloads",
            "pattern": "*.csv",
            "source_kind": "csv",
            "selection": "all",
            "artifact_path": "analysis-report.md",
            "step_id": "analyze-discovered-data",
        },
    )
    source = _workspace_selection_source_event(
        input_preview={
            "path": "Downloads",
            "pattern": "*.csv",
            "file_type": "csv",
            "selection": "all",
        },
        result={
            "ok": True,
            "path": "Downloads",
            "entries": [
                {"name": "east.csv", "type": "file"},
                {"name": "west.csv", "type": "file"},
            ],
        },
    )

    _runner(calls).run(
        [request],
        ["data.analyze"],
        object(),
        [{"role": "user", "content": "Analyze all CSV files"}],
        [source],
        [],
        next_iteration=1,
        run_id=RUN_ID,
        budget=_Budget(),
    )

    executed = calls[0]
    assert executed["input"]["paths"] == [
        "Downloads/east.csv",
        "Downloads/west.csv",
    ]
    assert "path" not in executed["input"]
    assert executed["action_target"]["paths"] == executed["input"]["paths"]
    assert executed["workspace_file_resolution"]["resolved_paths"] == (
        executed["input"]["paths"]
    )
