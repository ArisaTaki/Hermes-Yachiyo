"""Vertical acceptance coverage for the generic Runtime-owned agent loop."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.goal_runtime import (
    pending_semantic_artifact_assessment_candidates,
    runtime_goal_assessment,
    runtime_goal_contract,
)
from apps.shell.agent.runtime.main_chat_model_loop import MainChatModelLoopRunner
from apps.shell.agent.runtime.model_intent_planning import (
    MODEL_INTENT_PLANNING_TOOL_NAME,
)
from apps.shell.agent.runtime.semantic_artifact_verification import (
    SEMANTIC_ARTIFACT_VERIFICATION_TOOL_NAME,
)
from apps.shell.agent.runtime.tool_approvals import ToolPendingApprovalBuilder
from apps.shell.agent.runtime.tool_execution import (
    RuntimeToolCallExecutor,
    RuntimeToolRequestRunner,
)
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.tool_requests import normalize_tool_name
from apps.shell.agent.tools.policy import PolicyGate
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_envelope_from_decision,
)
from apps.shell.yachiyo_agent.runtime_planner import RuntimePlanner


RUN_ID = "run-generic-vertical"
ORIGINAL_GOAL = (
    "Generate a research report about Python examples using web search."
)
REPORT_PATH = "report.md"
REPORT_TEXT = "# Python examples\n\nUse small, executable examples and cite their source."
BROWSER_TEXT = "Python examples: prefer minimal reproducible programs."
ALLOWED_TOOLS = [
    "browser.open_url_and_extract_text",
    "browser.search",
    "artifact.write",
]


def _timeline(event: str, detail: str = "", **payload: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **payload}


class _Budget:
    def __init__(self) -> None:
        self.model_calls = 0
        self.tool_calls: list[str] = []

    def claim_model_call(self) -> None:
        self.model_calls += 1

    def claim_tool_call(
        self,
        tool_name: str,
        *,
        terminal_execution: bool = False,
    ) -> None:
        del terminal_execution
        self.tool_calls.append(tool_name)


class _RuntimeTimeline:
    @staticmethod
    def compiled(**payload: Any) -> dict[str, Any]:
        return {"event": "agent.runtime.compiled", **payload}


class _TaskModelEvents:
    @staticmethod
    def model_request_started_payload(**payload: Any) -> dict[str, Any]:
        return payload

    @staticmethod
    def model_request_failed_payload(error: str) -> dict[str, Any]:
        return {"error": error}

    @staticmethod
    def model_output_completed_payload(
        content: str,
        *,
        truncated: bool,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {"content": content, "truncated": truncated, **metadata}


class _ToolCallEvents:
    def requested(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def started(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def result(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def failed(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def denied(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def agent_tool_call(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _TraceEvents:
    @staticmethod
    def memory_skill_trace_event(*_args: Any, **_kwargs: Any) -> None:
        return None

    @staticmethod
    def artifact_created_payload(
        tool_result: dict[str, Any],
        *,
        run_id: str,
        source_tool: str,
    ) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "path": str(tool_result.get("path") or ""),
            "source_tool": source_tool,
        }


class _Model:
    def __init__(self, *, artifacts: list[dict[str, Any]]) -> None:
        self.artifacts = artifacts
        self.planning_calls = 0
        self.replan_calls = 0
        self.report_calls = 0
        self.final_calls = 0

    def __call__(
        self,
        _base_url: str,
        _model: str,
        _api_key: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_names = {
            str(
                tool.get("function", {}).get("name")
                if isinstance(tool.get("function"), dict)
                else tool.get("name")
                or ""
            ).strip()
            for tool in tools
            if isinstance(tool, dict)
        }
        if MODEL_INTENT_PLANNING_TOOL_NAME in tool_names:
            self.planning_calls += 1
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "model-intent-plan",
                        "type": "function",
                        "function": {
                            "name": MODEL_INTENT_PLANNING_TOOL_NAME,
                            "arguments": json.dumps(
                                {
                                    "intent_kind": "report_generation",
                                    "planning_goal": ORIGINAL_GOAL,
                                    "action_evidence": "Generate a research report",
                                    "rationale": (
                                        "The user requested researched content and a durable report."
                                    ),
                                }
                            ),
                        },
                    }
                ],
            }

        latest_user = next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        if "Runtime replan context" in latest_user and self.replan_calls == 0:
            self.replan_calls += 1
            assert "browser.open_url_and_extract_text" in latest_user
            assert "browser_search" in tool_names
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "alternate-browser-search",
                        "type": "function",
                        "function": {
                            "name": "browser_search",
                            "arguments": json.dumps({"query": "Python examples"}),
                        },
                    }
                ],
            }

        visible_transcript = "\n".join(
            str(message.get("content") or "") for message in messages
        )
        if self.report_calls == 0:
            self.report_calls += 1
            assert BROWSER_TEXT in visible_transcript
            assert self.artifacts == []
            assert "artifact_write" in tool_names
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "write-researched-report",
                        "type": "function",
                        "function": {
                            "name": "artifact_write",
                            "arguments": json.dumps(
                                {"path": REPORT_PATH, "content": REPORT_TEXT}
                            ),
                        },
                    }
                ],
            }

        self.final_calls += 1
        assert len(self.artifacts) == 1
        assert self.artifacts[0]["path"] == REPORT_PATH
        return {"role": "assistant", "content": REPORT_TEXT}


class _Broker:
    def __init__(
        self,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> None:
        self.timeline = timeline
        self.artifacts = artifacts
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.completed_before_artifact = False
        self.closed = 0

    def call(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        assert approved is False
        assert tool_name in ALLOWED_TOOLS
        self.calls.append((tool_name, dict(payload)))
        if tool_name == "browser.open_url_and_extract_text":
            return {
                "ok": False,
                "status": "failed",
                "error": "primary browser adapter timed out",
                "retryable": True,
                "replan_allowed": True,
            }
        if tool_name == "browser.search":
            assert self.artifacts == []
            return {
                "ok": True,
                "action": "browser.search",
                "summary": BROWSER_TEXT,
                "data": {
                    "query": payload["query"],
                    "text": BROWSER_TEXT,
                    "results": [
                        {
                            "title": "Python examples",
                            "url": "https://example.invalid/python",
                            "snippet": BROWSER_TEXT,
                        }
                    ],
                },
            }
        if tool_name == "artifact.write":
            self.completed_before_artifact = any(
                event.get("event") == "agent.goal.assessed"
                and event.get("status") == "completed"
                for event in self.timeline
            )
            assert payload == {"path": REPORT_PATH, "content": REPORT_TEXT}
            return {
                "ok": True,
                "action": "artifact.write",
                "path": REPORT_PATH,
                "content": REPORT_TEXT,
                "postcondition_verified": True,
                "state": "persisted",
                "target": {
                    "kind": "workspace_file",
                    "action": "write_artifact",
                    "path": REPORT_PATH,
                },
                "data": {
                    "path": REPORT_PATH,
                    "postcondition_verified": True,
                },
            }
        raise AssertionError(f"Runtime executed a tool outside the acceptance plan: {tool_name}")

    def close_owned_browser_target(self) -> None:
        self.closed += 1


class _ToolBrokers:
    def __init__(self, broker: _Broker) -> None:
        self.broker = broker

    def for_main_chat(self, **_kwargs: Any) -> _Broker:
        return self.broker


def test_main_chat_generic_loop_replans_once_and_completes_only_exact_artifact() -> None:
    budget = _Budget()
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, dict[str, Any]]] = []
    model = _Model(artifacts=artifacts)
    broker = _Broker(timeline=timeline, artifacts=artifacts)

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_fence: Any,
    ) -> dict[str, Any]:
        run_events.append((event_type, dict(payload)))
        return {"event_type": event_type, "payload": payload}

    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=_ToolCallEvents(),
        trace_events=_TraceEvents(),
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
    )

    def execute_tool(
        tool_request: dict[str, Any],
        allowed_tools: list[str],
        active_broker: _Broker,
        active_timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        active_artifacts = artifacts if artifacts is not None else []
        broker.timeline = active_timeline
        broker.artifacts = active_artifacts
        model.artifacts = active_artifacts
        return executor.execute(
            tool_request,
            allowed_tools,
            active_broker,
            active_timeline,
            artifacts=active_artifacts,
            **kwargs,
        )

    projection = RuntimeToolLoopProjectionBuilder()
    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda messages: next(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=projection,
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "unexpected-approval",
            now=lambda: "2026-07-20T00:00:00Z",
        ),
        call_agent_tool=execute_tool,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(ALLOWED_TOOLS)}
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Research, recover, persist, and verify.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(
            message.get("content") or ""
        ),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )

    state: dict[str, Any] = {
        "run": {
            "run_id": RUN_ID,
            "kind": "main_chat_run",
            "user_goal": ORIGINAL_GOAL,
            "status": "running",
            "updated_at": "version-0",
            "timeline": timeline,
            "artifacts": artifacts,
            "pending_approval": {},
        }
    }
    version = 0

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any] | None:
        nonlocal version
        current = state["run"]
        if (
            payload.get("expected_status") is not None
            and payload["expected_status"] != current.get("status")
        ):
            return None
        if (
            payload.get("expected_updated_at") is not None
            and payload["expected_updated_at"] != current.get("updated_at")
        ):
            return None
        if payload.get("expected_pending_approval_absent") and current.get(
            "pending_approval"
        ):
            return None
        current.update(
            {
                key: value
                for key, value in payload.items()
                if not key.startswith("expected_")
            }
        )
        version += 1
        current["updated_at"] = f"version-{version}"
        return dict(current)

    runner = MainChatModelLoopRunner(
        get_run=lambda _run_id: state["run"],
        default_profile_id=lambda: "profile-test",
        model_profile_config_private=lambda _profile_id: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        main_chat_agent_config=lambda **kwargs: {
            "agent_id": "builtin:yachiyo-main",
            "name": "Yachiyo",
            **kwargs,
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(ALLOWED_TOOLS)},
            "workspace_policy": {"default_workdir": "/workspace"},
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        runtime_agent_timeline=_RuntimeTimeline(),
        timeline_factory=_timeline,
        update_run=update_run,
        append_run_event=append_run_event,
        task_model_events=_TaskModelEvents(),
        tool_brokers=_ToolBrokers(broker),
        continue_custom_api_agent=loop.run,
        main_chat_pending_approval=lambda *_args, **_kwargs: {},
        approval_pause=object(),
        terminal_run_or_none=lambda _run_id: None,
        fail_main_chat_run=lambda run_id, error, **_kwargs: {
            "run_id": run_id,
            "status": "failed",
            "result": str(error),
        },
        redact_secrets=str,
        model_output_metadata=lambda _value: {"finish_reason": "stop"},
        error_type=agent_runtime.AgentRuntimeError,
        resolve_initial_model_plan=loop.resolve_initial_model_plan,
    )

    result = runner.execute(
        RUN_ID,
        [{"role": "user", "content": ORIGINAL_GOAL}],
    )

    timeline = result["timeline"]
    broker.timeline = timeline
    contract_events = [
        event for event in timeline if event.get("event") == "agent.goal.contract"
    ]
    assert len(contract_events) == 1
    contract = contract_events[0]["goal_contract"]
    assert contract["original_goal"] == ORIGINAL_GOAL
    assert result["user_goal"] == ORIGINAL_GOAL
    assert contract["intent_kind"] == "report_generation"
    assert contract["criteria"][0]["expected"]["target"]["path"] == REPORT_PATH

    replan_events = [
        event for event in timeline if event.get("event") == "agent.replan.requested"
    ]
    assert len(replan_events) == 1
    assert replan_events[0]["payload"]["source_tool_name"] == (
        "browser.open_url_and_extract_text"
    )
    assert model.planning_calls == 1
    assert model.replan_calls == 1
    assert model.report_calls == 1
    assert model.final_calls == 1

    assert [tool for tool, _payload in broker.calls] == [
        "browser.open_url_and_extract_text",
        "browser.search",
        "artifact.write",
    ]
    assert all(tool in ALLOWED_TOOLS for tool, _payload in broker.calls)
    assert broker.completed_before_artifact is False
    assert str(result["result"]) == REPORT_TEXT

    initial_failure_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "browser.open_url_and_extract_text"
    )
    assert initial_failure_event["result"]["retryable"] is True
    assert initial_failure_event["result"]["replan_allowed"] is True

    artifact_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "artifact.write"
    )
    assert artifact_event["run_id"] == RUN_ID
    assert artifact_event["step_id"] == "write-report-artifact"
    assert artifact_event["action_target"]["path"] == REPORT_PATH
    assert artifact_event["input_preview"] == {
        "path": REPORT_PATH,
        "content": REPORT_TEXT,
    }
    assert artifact_event["result"]["postcondition_verified"] is True
    assert artifact_event["result"][RUNTIME_EXECUTION_PROVENANCE_KEY]["source"] == (
        RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE
    )
    assert result["artifacts"][0]["path"] == REPORT_PATH
    completed_assessment_index = next(
        index
        for index, event in enumerate(timeline)
        if event.get("event") == "agent.goal.assessed"
        and event.get("status") == "completed"
    )
    assert completed_assessment_index > timeline.index(artifact_event)


def test_main_chat_generic_loop_researches_then_retries_final_media_action_with_new_input() -> None:
    run_id = "run-generic-media-retry"
    original_goal = "Play Moonlight"
    allowed_tools = [
        "media.apple_music_play",
        "browser.search",
    ]
    initial_query = "Moonlight"
    canonical_query = "Moonlight canonical alias"
    final_reply = "Started playback for Moonlight."

    class _MediaModel:
        def __init__(self) -> None:
            self.planning_calls = 0
            self.replan_calls = 0
            self.retry_calls = 0
            self.final_calls = 0

        def __call__(
            self,
            _base_url: str,
            _model: str,
            _api_key: str,
            messages: list[dict[str, Any]],
            *,
            tools: list[dict[str, Any]],
            **_kwargs: Any,
        ) -> dict[str, Any]:
            tool_names = {
                str(
                    tool.get("function", {}).get("name")
                    if isinstance(tool.get("function"), dict)
                    else tool.get("name")
                    or ""
                ).strip()
                for tool in tools
                if isinstance(tool, dict)
            }
            if MODEL_INTENT_PLANNING_TOOL_NAME in tool_names:
                self.planning_calls += 1
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "model-intent-plan",
                            "type": "function",
                            "function": {
                                "name": MODEL_INTENT_PLANNING_TOOL_NAME,
                                "arguments": json.dumps(
                                    {
                                        "intent_kind": "media_playback",
                                        "planning_goal": original_goal,
                                        "action_evidence": original_goal,
                                        "rationale": "The user asked to play a song.",
                                    }
                                ),
                            },
                        }
                    ],
                }

            latest_user = next(
                (
                    str(message.get("content") or "")
                    for message in reversed(messages)
                    if message.get("role") == "user"
                ),
                "",
            )
            if "Runtime replan context" in latest_user and self.replan_calls == 0:
                self.replan_calls += 1
                assert "browser_search" in tool_names
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "resolve-canonical-alias",
                            "type": "function",
                            "function": {
                                "name": "browser_search",
                                "arguments": json.dumps({"query": "Moonlight song alias"}),
                            },
                        }
                    ],
                }

            visible_transcript = "\n".join(
                str(message.get("content") or "") for message in messages
            )
            if self.retry_calls == 0:
                self.retry_calls += 1
                assert canonical_query in visible_transcript
                assert "media_apple_music_play" in tool_names
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "retry-media-playback",
                            "type": "function",
                            "function": {
                                "name": "media_apple_music_play",
                                "arguments": json.dumps({"query": canonical_query}),
                            },
                        }
                    ],
                }

            self.final_calls += 1
            return {"role": "assistant", "content": final_reply}

    class _MediaBroker:
        def __init__(self, *, timeline: list[dict[str, Any]]) -> None:
            self.timeline = timeline
            self.calls: list[tuple[str, dict[str, Any]]] = []
            self.completed_before_retry = False

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            assert approved is False
            assert tool_name in allowed_tools
            self.calls.append((tool_name, dict(payload)))
            if tool_name == "media.apple_music_play" and len(
                [name for name, _ in self.calls if name == "media.apple_music_play"]
            ) == 1:
                assert payload == {"query": initial_query}
                return {
                    "ok": False,
                    "status": "failed",
                    "error": "catalog miss",
                    "retryable": True,
                    "replan_allowed": True,
                }
            if tool_name == "browser.search":
                return {
                    "ok": True,
                    "action": "browser.search",
                    "summary": canonical_query,
                    "postcondition_verified": True,
                    "data": {
                        "query": payload["query"],
                        "text": canonical_query,
                        "results": [
                            {
                                "title": canonical_query,
                                "url": "https://example.invalid/moonlight",
                                "snippet": canonical_query,
                            }
                        ],
                    },
                }
            if tool_name == "media.apple_music_play":
                self.completed_before_retry = any(
                    event.get("event") == "agent.goal.assessed"
                    and event.get("status") == "completed"
                    for event in self.timeline
                )
                assert payload == {"query": canonical_query}
                return {
                    "ok": True,
                    "action": "media.apple_music_play",
                    "postcondition_verified": True,
                    "data": {
                        "query": canonical_query,
                        "track": canonical_query,
                        "track_identity_verified": True,
                        "player_state": "playing",
                        "playback_started": True,
                        "postcondition_verified": True,
                    },
                }
            raise AssertionError(f"Unexpected tool call: {tool_name}")

        def close_owned_browser_target(self) -> None:
            return None

    budget = _Budget()
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, dict[str, Any]]] = []
    model = _MediaModel()
    broker = _MediaBroker(timeline=timeline)

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_fence: Any,
    ) -> dict[str, Any]:
        run_events.append((event_type, dict(payload)))
        return {"event_type": event_type, "payload": payload}

    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=_ToolCallEvents(),
        trace_events=_TraceEvents(),
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
    )

    def execute_tool(
        tool_request: dict[str, Any],
        allowed_tools_value: list[str],
        active_broker: _MediaBroker,
        active_timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del artifacts
        broker.timeline = active_timeline
        return executor.execute(
            tool_request,
            allowed_tools_value,
            active_broker,
            active_timeline,
            artifacts=[],
            **kwargs,
        )

    projection = RuntimeToolLoopProjectionBuilder()
    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda messages: next(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=projection,
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "unexpected-approval",
            now=lambda: "2026-07-20T00:00:00Z",
        ),
        call_agent_tool=execute_tool,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)}
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Recover through research, then retry the exact goal.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(
            message.get("content") or ""
        ),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )

    state: dict[str, Any] = {
        "run": {
            "run_id": run_id,
            "kind": "main_chat_run",
            "user_goal": original_goal,
            "status": "running",
            "updated_at": "version-0",
            "timeline": timeline,
            "artifacts": artifacts,
            "pending_approval": {},
        }
    }
    version = 0

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any] | None:
        nonlocal version
        current = state["run"]
        if (
            payload.get("expected_status") is not None
            and payload["expected_status"] != current.get("status")
        ):
            return None
        if (
            payload.get("expected_updated_at") is not None
            and payload["expected_updated_at"] != current.get("updated_at")
        ):
            return None
        if payload.get("expected_pending_approval_absent") and current.get(
            "pending_approval"
        ):
            return None
        current.update(
            {
                key: value
                for key, value in payload.items()
                if not key.startswith("expected_")
            }
        )
        version += 1
        current["updated_at"] = f"version-{version}"
        return dict(current)

    runner = MainChatModelLoopRunner(
        get_run=lambda _run_id: state["run"],
        default_profile_id=lambda: "profile-test",
        model_profile_config_private=lambda _profile_id: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        main_chat_agent_config=lambda **kwargs: {
            "agent_id": "builtin:yachiyo-main",
            "name": "Yachiyo",
            **kwargs,
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)},
            "workspace_policy": {"default_workdir": "/workspace"},
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        runtime_agent_timeline=_RuntimeTimeline(),
        timeline_factory=_timeline,
        update_run=update_run,
        append_run_event=append_run_event,
        task_model_events=_TaskModelEvents(),
        tool_brokers=_ToolBrokers(broker),  # type: ignore[arg-type]
        continue_custom_api_agent=loop.run,
        main_chat_pending_approval=lambda *_args, **_kwargs: {},
        approval_pause=object(),
        terminal_run_or_none=lambda _run_id: None,
        fail_main_chat_run=lambda active_run_id, error, **_kwargs: {
            "run_id": active_run_id,
            "status": "failed",
            "result": str(error),
        },
        redact_secrets=str,
        model_output_metadata=lambda _value: {"finish_reason": "stop"},
        error_type=agent_runtime.AgentRuntimeError,
        resolve_initial_model_plan=loop.resolve_initial_model_plan,
    )

    result = runner.execute(
        run_id,
        [{"role": "user", "content": original_goal}],
    )

    timeline = result["timeline"]
    assert [tool for tool, _payload in broker.calls] == [
        "media.apple_music_play",
        "browser.search",
        "media.apple_music_play",
    ]
    assert broker.completed_before_retry is False
    assert str(result["result"]) == final_reply
    assert model.planning_calls == 1
    assert model.replan_calls == 1
    assert model.retry_calls == 1
    assert model.final_calls == 1

    failed_media_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "media.apple_music_play"
        and event.get("result", {}).get("ok") is False
    )
    retry_media_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "media.apple_music_play"
        and event.get("result", {}).get("ok") is True
    )
    search_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "browser.search"
    )
    assert timeline.index(failed_media_event) < timeline.index(search_event)
    assert timeline.index(search_event) < timeline.index(retry_media_event)
    assert search_event["goal_contract_id"] == failed_media_event["goal_contract_id"]
    assert search_event["goal_criterion_id"] == failed_media_event["goal_criterion_id"]
    assert search_event["step_id"] != failed_media_event["step_id"]
    assert search_event["source_step_id"] == failed_media_event["step_id"]
    assert search_event["observation_only"] is True
    assert search_event["goal_completion_authority"] is False
    assert retry_media_event["input_preview"] == {"query": canonical_query}
    assert retry_media_event["goal_contract_id"] == failed_media_event["goal_contract_id"]
    assert retry_media_event["goal_criterion_id"] == failed_media_event["goal_criterion_id"]
    assert retry_media_event["step_id"] == failed_media_event["step_id"]
    assert retry_media_event["root_goal_unchanged"] is True
    assert retry_media_event["result"]["postcondition_verified"] is True
    assert retry_media_event["result"]["data"]["track_identity_verified"] is True
    assert retry_media_event["result"]["data"]["player_state"] == "playing"
    completed_assessment_index = next(
        index
        for index, event in enumerate(timeline)
        if event.get("event") == "agent.goal.assessed"
        and event.get("status") == "completed"
    )
    assert completed_assessment_index > timeline.index(retry_media_event)
    assert completed_assessment_index > timeline.index(failed_media_event)


def _run_media_replan_retry_scenario(
    *,
    run_id: str,
    original_goal: str,
    initial_query: str,
    retry_query: str,
    replan_model_tool_name: str,
    replan_runtime_tool_name: str,
    replan_tool_arguments: dict[str, Any],
    replan_tool_result: dict[str, Any],
    allowed_tools: list[str],
    final_reply: str,
) -> tuple[dict[str, Any], Any, Any]:
    class _ScenarioModel:
        def __init__(self) -> None:
            self.planning_calls = 0
            self.replan_calls = 0
            self.final_calls = 0

        def __call__(
            self,
            _base_url: str,
            _model: str,
            _api_key: str,
            messages: list[dict[str, Any]],
            *,
            tools: list[dict[str, Any]],
            **_kwargs: Any,
        ) -> dict[str, Any]:
            tool_names = {
                str(
                    tool.get("function", {}).get("name")
                    if isinstance(tool.get("function"), dict)
                    else tool.get("name")
                    or ""
                ).strip()
                for tool in tools
                if isinstance(tool, dict)
            }
            if MODEL_INTENT_PLANNING_TOOL_NAME in tool_names:
                self.planning_calls += 1
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "model-intent-plan",
                            "type": "function",
                            "function": {
                                "name": MODEL_INTENT_PLANNING_TOOL_NAME,
                                "arguments": json.dumps(
                                    {
                                        "intent_kind": "media_playback",
                                        "planning_goal": original_goal,
                                        "action_evidence": original_goal,
                                        "rationale": "The user asked to play a song.",
                                    }
                                ),
                            },
                        }
                    ],
                }

            latest_user = next(
                (
                    str(message.get("content") or "")
                    for message in reversed(messages)
                    if message.get("role") == "user"
                ),
                "",
            )
            if "Runtime replan context" in latest_user and self.replan_calls == 0:
                self.replan_calls += 1
                assert replan_model_tool_name in tool_names
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "replan-step",
                            "type": "function",
                            "function": {
                                "name": replan_model_tool_name,
                                "arguments": json.dumps(replan_tool_arguments),
                            },
                        }
                    ],
                }

            self.final_calls += 1
            assert "media_apple_music_play" in tool_names
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "retry-media-playback",
                        "type": "function",
                        "function": {
                            "name": "media_apple_music_play",
                            "arguments": json.dumps({"query": retry_query}),
                        },
                    }
                ],
            }

    class _ScenarioBroker:
        def __init__(self, *, timeline: list[dict[str, Any]]) -> None:
            self.timeline = timeline
            self.calls: list[tuple[str, dict[str, Any]]] = []
            self.completed_before_retry = False

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            assert approved is False
            assert tool_name in allowed_tools
            self.calls.append((tool_name, dict(payload)))
            if tool_name == "media.apple_music_play" and len(
                [name for name, _ in self.calls if name == "media.apple_music_play"]
            ) == 1:
                assert payload == {"query": initial_query}
                return {
                    "ok": False,
                    "status": "failed",
                    "error": "catalog miss",
                    "retryable": True,
                    "replan_allowed": True,
                }
            if tool_name == replan_runtime_tool_name:
                return dict(replan_tool_result)
            if tool_name == "media.apple_music_play":
                self.completed_before_retry = any(
                    event.get("event") == "agent.goal.assessed"
                    and event.get("status") == "completed"
                    for event in self.timeline
                )
                assert payload == {"query": retry_query}
                return {
                    "ok": True,
                    "action": "media.apple_music_play",
                    "postcondition_verified": True,
                    "data": {
                        "query": retry_query,
                        "track": retry_query,
                        "track_identity_verified": True,
                        "player_state": "playing",
                        "playback_started": True,
                        "postcondition_verified": True,
                    },
                }
            raise AssertionError(f"Unexpected tool call: {tool_name}")

        def close_owned_browser_target(self) -> None:
            return None

    budget = _Budget()
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, dict[str, Any]]] = []
    model = _ScenarioModel()
    broker = _ScenarioBroker(timeline=timeline)

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_fence: Any,
    ) -> dict[str, Any]:
        run_events.append((event_type, dict(payload)))
        return {"event_type": event_type, "payload": payload}

    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=_ToolCallEvents(),
        trace_events=_TraceEvents(),
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
    )

    def execute_tool(
        tool_request: dict[str, Any],
        allowed_tools_value: list[str],
        active_broker: _ScenarioBroker,
        active_timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del artifacts
        broker.timeline = active_timeline
        return executor.execute(
            tool_request,
            allowed_tools_value,
            active_broker,
            active_timeline,
            artifacts=[],
            **kwargs,
        )

    projection = RuntimeToolLoopProjectionBuilder()
    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda messages: next(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=projection,
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "unexpected-approval",
            now=lambda: "2026-07-20T00:00:00Z",
        ),
        call_agent_tool=execute_tool,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)}
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Recover through grounded research, then retry the exact goal.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(
            message.get("content") or ""
        ),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )

    state: dict[str, Any] = {
        "run": {
            "run_id": run_id,
            "kind": "main_chat_run",
            "user_goal": original_goal,
            "status": "running",
            "updated_at": "version-0",
            "timeline": timeline,
            "artifacts": artifacts,
            "pending_approval": {},
        }
    }
    version = 0

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any] | None:
        nonlocal version
        current = state["run"]
        if (
            payload.get("expected_status") is not None
            and payload["expected_status"] != current.get("status")
        ):
            return None
        if (
            payload.get("expected_updated_at") is not None
            and payload["expected_updated_at"] != current.get("updated_at")
        ):
            return None
        if payload.get("expected_pending_approval_absent") and current.get(
            "pending_approval"
        ):
            return None
        current.update(
            {
                key: value
                for key, value in payload.items()
                if not key.startswith("expected_")
            }
        )
        version += 1
        current["updated_at"] = f"version-{version}"
        return dict(current)

    runner = MainChatModelLoopRunner(
        get_run=lambda _run_id: state["run"],
        default_profile_id=lambda: "profile-test",
        model_profile_config_private=lambda _profile_id: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        main_chat_agent_config=lambda **kwargs: {
            "agent_id": "builtin:yachiyo-main",
            "name": "Yachiyo",
            **kwargs,
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)},
            "workspace_policy": {"default_workdir": "/workspace"},
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        runtime_agent_timeline=_RuntimeTimeline(),
        timeline_factory=_timeline,
        update_run=update_run,
        append_run_event=append_run_event,
        task_model_events=_TaskModelEvents(),
        tool_brokers=_ToolBrokers(broker),  # type: ignore[arg-type]
        continue_custom_api_agent=loop.run,
        main_chat_pending_approval=lambda *_args, **_kwargs: {},
        approval_pause=object(),
        terminal_run_or_none=lambda _run_id: None,
        fail_main_chat_run=lambda active_run_id, error, **_kwargs: {
            "run_id": active_run_id,
            "status": "failed",
            "result": str(error),
        },
        redact_secrets=str,
        model_output_metadata=lambda _value: {"finish_reason": "stop"},
        error_type=agent_runtime.AgentRuntimeError,
        resolve_initial_model_plan=loop.resolve_initial_model_plan,
    )

    try:
        result = runner.execute(
            run_id,
            [{"role": "user", "content": original_goal}],
        )
    except agent_runtime.AgentRuntimeError as exc:
        result = {
            "run_id": run_id,
            "status": "failed",
            "result": str(exc),
            "timeline": state["run"].get("timeline") or broker.timeline,
            "artifacts": artifacts,
            "user_goal": original_goal,
        }
    return result, model, broker


def test_main_chat_generic_loop_does_not_bind_changed_query_without_grounding_observation() -> None:
    initial_query = "Moonlight"
    changed_query = "Moonlight canonical alias"
    result, model, broker = _run_media_replan_retry_scenario(
        run_id="run-generic-media-retry-without-grounding",
        original_goal="Play Moonlight",
        initial_query=initial_query,
        retry_query=changed_query,
        replan_model_tool_name="media_apple_music_play",
        replan_runtime_tool_name="media.apple_music_play",
        replan_tool_arguments={"query": changed_query},
        replan_tool_result={
            "ok": True,
            "action": "media.apple_music_play",
            "postcondition_verified": True,
            "data": {
                "query": changed_query,
                "track": changed_query,
                "track_identity_verified": True,
                "player_state": "playing",
                "playback_started": True,
                "postcondition_verified": True,
            },
        },
        allowed_tools=["media.apple_music_play", "browser.search"],
        final_reply="Started playback for Moonlight.",
    )

    timeline = result["timeline"]
    assert broker.calls[0] == ("media.apple_music_play", {"query": initial_query})
    assert broker.calls[1:] == [
        ("media.apple_music_play", {"query": changed_query})
        for _ in broker.calls[1:]
    ]
    assert model.planning_calls == 1
    assert model.replan_calls == 1
    retry_events = [
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "media.apple_music_play"
        and event.get("result", {}).get("ok") is True
    ]
    assert retry_events
    assert all(
        event.get("input_preview") == {"query": changed_query}
        for event in retry_events
    )
    assert all(
        event.get("goal_contract_id") in (None, "")
        and event.get("goal_criterion_id") in (None, "")
        and event.get("root_goal_unchanged") is not True
        for event in retry_events
    )
    assert not any(
        event.get("event") == "agent.goal.assessed"
        and event.get("status") == "completed"
        for event in timeline
    )
    assert result["status"] == "failed"
    assert "工具循环超过上限" in str(result["result"])


def test_main_chat_generic_loop_does_not_bind_changed_query_when_observation_lacks_new_target() -> None:
    initial_query = "Moonlight"
    changed_query = "Moonlight canonical alias"
    result, _model, broker = _run_media_replan_retry_scenario(
        run_id="run-generic-media-retry-ungrounded-observation",
        original_goal="Play Moonlight",
        initial_query=initial_query,
        retry_query=changed_query,
        replan_model_tool_name="browser_search",
        replan_runtime_tool_name="browser.search",
        replan_tool_arguments={"query": "Moonlight song alias"},
        replan_tool_result={
            "ok": True,
            "action": "browser.search",
            "summary": "Moonlight search results",
            "postcondition_verified": True,
            "data": {
                "query": "Moonlight song alias",
                "text": "Moonlight search results",
                "results": [
                    {
                        "title": "Moonlight",
                        "url": "https://example.invalid/moonlight",
                        "snippet": "Moonlight search results",
                    }
                ],
            },
        },
        allowed_tools=["media.apple_music_play", "browser.search"],
        final_reply="Started playback for Moonlight.",
    )

    timeline = result["timeline"]
    assert broker.calls[:2] == [
        ("media.apple_music_play", {"query": initial_query}),
        ("browser.search", {"query": "Moonlight song alias"}),
    ]
    assert broker.calls[2:] == [
        ("media.apple_music_play", {"query": changed_query})
        for _ in broker.calls[2:]
    ]
    retry_events = [
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "media.apple_music_play"
        and event.get("result", {}).get("ok") is True
    ]
    assert retry_events
    assert all(
        event.get("input_preview") == {"query": changed_query}
        for event in retry_events
    )
    assert all(
        event.get("goal_contract_id") in (None, "")
        and event.get("goal_criterion_id") in (None, "")
        and event.get("root_goal_unchanged") is not True
        for event in retry_events
    )
    assert not any(
        event.get("event") == "agent.goal.assessed"
        and event.get("status") == "completed"
        for event in timeline
    )
    assert result["status"] == "failed"
    assert "工具循环超过上限" in str(result["result"])


def test_main_chat_generic_loop_does_not_bind_changed_query_from_non_grounding_tool_result() -> None:
    initial_query = "Moonlight"
    changed_query = "Moonlight canonical alias"
    result, _model, broker = _run_media_replan_retry_scenario(
        run_id="run-generic-media-retry-non-grounding-tool",
        original_goal="Play Moonlight",
        initial_query=initial_query,
        retry_query=changed_query,
        replan_model_tool_name="artifact_write",
        replan_runtime_tool_name="artifact.write",
        replan_tool_arguments={"path": "alias.txt", "content": changed_query},
        replan_tool_result={
            "ok": True,
            "action": "artifact.write",
            "path": "alias.txt",
            "content": changed_query,
            "postcondition_verified": True,
            "data": {
                "path": "alias.txt",
                "content": changed_query,
                "postcondition_verified": True,
            },
        },
        allowed_tools=["media.apple_music_play", "artifact.write"],
        final_reply="Started playback for Moonlight.",
    )

    timeline = result["timeline"]
    assert broker.calls[:2] == [
        ("media.apple_music_play", {"query": initial_query}),
        ("artifact.write", {"path": "alias.txt", "content": changed_query}),
    ]
    assert broker.calls[2:] == [
        ("media.apple_music_play", {"query": changed_query})
        for _ in broker.calls[2:]
    ]
    retry_events = [
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "media.apple_music_play"
        and event.get("result", {}).get("ok") is True
    ]
    assert retry_events
    assert all(
        event.get("input_preview") == {"query": changed_query}
        for event in retry_events
    )
    assert all(
        event.get("goal_contract_id") in (None, "")
        and event.get("goal_criterion_id") in (None, "")
        and event.get("root_goal_unchanged") is not True
        for event in retry_events
    )
    assert not any(
        event.get("event") == "agent.goal.assessed"
        and event.get("status") == "completed"
        for event in timeline
    )
    assert result["status"] == "failed"
    assert "工具循环超过上限" in str(result["result"])


def test_main_chat_generic_loop_prefers_native_data_analysis_over_terminal_support_path() -> None:
    run_id = "run-generic-native-data-preference"
    original_goal = "请分析 sales.csv 并输出一份数据分析报告"
    allowed_tools = [
        "workspace.read",
        "data.analyze",
        "terminal.run",
        "artifact.write",
    ]
    class _NativeDataBroker:
        def __init__(self, *, timeline: list[dict[str, Any]]) -> None:
            self.timeline = timeline
            self.calls: list[tuple[str, dict[str, Any]]] = []
            self.completed_before_native = False

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            assert approved is False
            self.calls.append((tool_name, dict(payload)))
            if tool_name == "workspace.read":
                assert payload == {"path": "sales.csv", "source_kind": "csv"}
                return {
                    "ok": True,
                    "path": "sales.csv",
                    "content": "month,revenue\njan,10\nfeb,12\n",
                }
            if tool_name == "data.analyze":
                self.completed_before_native = any(
                    event.get("event") == "agent.goal.assessed"
                    and event.get("status") == "completed"
                    for event in self.timeline
                )
                assert payload["path"] == "sales.csv"
                assert payload["artifact_path"] == "analysis-report.md"
                return {
                    "ok": True,
                    "action": "data.analyze",
                    "postcondition_verified": True,
                    "path": "sales.csv",
                    "artifact_path": "analysis-report.md",
                    "data": {
                        "artifact_path": "analysis-report.md",
                        "postcondition_verified": True,
                    },
                }
            raise AssertionError(f"Unexpected tool call: {tool_name}")

        def close_owned_browser_target(self) -> None:
            return None

    decision = RuntimePlanner().decision(original_goal, allowed_tools=allowed_tools)
    assert decision.selected_intent.kind == "data_analysis"
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
    )
    planner_requests = [request.model_dump(mode="json") for request in envelope.requests]
    for request in planner_requests:
        request["tool"] = request["tool_name"]
    contract = runtime_goal_contract(
        run_id=run_id,
        runtime_execution_envelope={
            "task_core": decision.plan.task_core.model_dump(),  # type: ignore[union-attr]
        },
        runtime_execution_metadata=None,
        messages=(),
        timeline=[],
    )
    assert contract is not None

    budget = _Budget()
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, dict[str, Any]]] = []
    broker = _NativeDataBroker(timeline=timeline)

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_fence: Any,
    ) -> dict[str, Any]:
        run_events.append((event_type, dict(payload)))
        return {"event_type": event_type, "payload": payload}

    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=_ToolCallEvents(),
        trace_events=_TraceEvents(),
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
    )

    def execute_tool(
        tool_request: dict[str, Any],
        allowed_tools_value: list[str],
        active_broker: _NativeDataBroker,
        active_timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del artifacts
        broker.timeline = active_timeline
        return executor.execute(
            tool_request,
            allowed_tools_value,
            active_broker,
            active_timeline,
            artifacts=[],
            **kwargs,
        )

    projection = RuntimeToolLoopProjectionBuilder()
    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda messages: next(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=projection,
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "unexpected-approval",
            now=lambda: "2026-07-20T00:00:00Z",
        ),
        call_agent_tool=execute_tool,
    )
    messages = [{"role": "user", "content": original_goal}]
    request_runner.run(
        planner_requests[:2],
        allowed_tools,
        broker,
        messages,
        timeline,
        artifacts,
        next_iteration=1,
        run_id=run_id,
        budget=budget,
    )

    assert [tool for tool, _payload in broker.calls] == ["workspace.read", "data.analyze"]
    assert broker.completed_before_native is False
    assert not any(tool == "terminal.run" for tool, _payload in broker.calls)
    assert runtime_goal_assessment(contract, timeline).completed is True
    native_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "data.analyze"
    )
    assert native_event["action_target"]["artifact_path"] == "analysis-report.md"


def test_generic_loop_terminal_support_method_completes_only_after_semantic_assessment() -> None:
    run_id = "run-generic-terminal-readback"
    original_goal = "请分析 sales.csv 并输出一份数据分析报告"
    allowed_tools = ["workspace.read", "terminal.run", "artifact.write"]
    exact_report = (
        "# Analysis Report\n\nRevenue rose 20%. Churn is the main risk. "
        "Keep the current launch plan and monitor weekly retention.\n"
    )
    decision = RuntimePlanner().decision(original_goal, allowed_tools=allowed_tools)
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        full_plan=True,
    )
    planner_requests = [request.model_dump(mode="json") for request in envelope.requests]
    for request in planner_requests:
        request["tool"] = request["tool_name"]
        if request["tool_name"] == "terminal.run":
            request["approval_required"] = False
            request["input"] = {
                "command": str(request.get("input", {}).get("command") or "")
            }
        elif request["tool_name"] == "artifact.write":
            request["input"] = {
                "path": "analysis-report.md",
                "content": exact_report,
            }
    contract = runtime_goal_contract(
        run_id=run_id,
        runtime_execution_envelope={
            "task_core": decision.plan.task_core.model_dump(),  # type: ignore[union-attr]
        },
        runtime_execution_metadata=None,
        messages=(),
        timeline=[],
    )
    assert contract is not None

    class _ExactReadbackBroker:
        def __init__(self, *, timeline: list[dict[str, Any]]) -> None:
            self.timeline = timeline
            self.calls: list[tuple[str, dict[str, Any], bool]] = []
            self.completed_before_verify = False

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            self.calls.append((tool_name, dict(payload), approved))
            if tool_name == "workspace.read" and payload == {"path": "sales.csv"}:
                return {
                    "ok": True,
                    "path": "sales.csv",
                    "content": "month,revenue\njan,10\nfeb,12\n",
                    "truncated": False,
                    "size_bytes": 28,
                    "content_bytes": 28,
                    "decoding_lossy": False,
                }
            if tool_name == "terminal.run":
                self.completed_before_verify = any(
                    event.get("event") == "agent.goal.assessed"
                    and event.get("status") == "completed"
                    for event in self.timeline
                )
                return {
                    "ok": True,
                    "exit_code": 0,
                }
            if tool_name == "artifact.write":
                return {
                    "ok": True,
                    "action": "artifact.write",
                    "paths": ["analysis-report.md"],
                    "path": "analysis-report.md",
                }
            if tool_name == "workspace.read" and payload == {"path": "analysis-report.md"}:
                report_bytes = exact_report.encode("utf-8")
                return {
                    "ok": True,
                    "path": "analysis-report.md",
                    "content": exact_report,
                    "truncated": False,
                    "size_bytes": len(report_bytes),
                    "content_bytes": len(report_bytes),
                    "decoding_lossy": False,
                }
            raise AssertionError(f"Unexpected tool call: {tool_name} {payload}")

        def close_owned_browser_target(self) -> None:
            return None

    budget = _Budget()
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, dict[str, Any]]] = []
    broker = _ExactReadbackBroker(timeline=timeline)

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_fence: Any,
    ) -> dict[str, Any]:
        run_events.append((event_type, dict(payload)))
        return {"event_type": event_type, "payload": payload}

    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=_ToolCallEvents(),
        trace_events=_TraceEvents(),
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
    )

    def execute_tool(
        tool_request: dict[str, Any],
        allowed_tools_value: list[str],
        active_broker: _ExactReadbackBroker,
        active_timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        active_artifacts = artifacts if artifacts is not None else []
        broker.timeline = active_timeline
        return executor.execute(
            tool_request,
            allowed_tools_value,
            active_broker,
            active_timeline,
            artifacts=active_artifacts,
            **kwargs,
        )

    projection = RuntimeToolLoopProjectionBuilder()
    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda messages: next(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=projection,
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "unexpected-approval",
            now=lambda: "2026-07-20T00:00:00Z",
        ),
        call_agent_tool=execute_tool,
    )
    messages = [{"role": "user", "content": original_goal}]
    request_runner.run(
        planner_requests,
        allowed_tools,
        broker,
        messages,
        timeline,
        artifacts,
        next_iteration=1,
        run_id=run_id,
        budget=budget,
    )

    assert [tool for tool, _payload, _approved in broker.calls] == [
        "workspace.read",
        "terminal.run",
        "artifact.write",
        "workspace.read",
    ]
    assert broker.completed_before_verify is False
    assert broker.calls[1][2] is False
    assert runtime_goal_assessment(contract, timeline).completed is False
    pending_semantic_candidates = (
        pending_semantic_artifact_assessment_candidates(contract, timeline)
    )
    assert pending_semantic_candidates
    terminal_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "terminal.run"
    )
    verify_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "workspace.read"
        and event.get("step_id") == "verify-analysis-artifact"
    )
    assert verify_event["result"]["ok"] is True
    assert timeline.index(verify_event) > timeline.index(terminal_event)

    semantic_calls: list[dict[str, Any]] = []

    def semantic_model(
        base_url: str,
        model_name: str,
        api_key: str,
        model_messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        semantic_calls.append(
            {
                "base_url": base_url,
                "model": model_name,
                "api_key": api_key,
                "messages": model_messages,
                "tools": tools,
                **kwargs,
            }
        )
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "semantic-verdict",
                    "type": "function",
                    "function": {
                        "name": SEMANTIC_ARTIFACT_VERIFICATION_TOOL_NAME,
                        "arguments": json.dumps(
                            {
                                "verdict": "fulfilled",
                                "reason": (
                                    "The report states the finding, main risk, "
                                    "and a concrete recommendation."
                                ),
                                "missing_requirements": [],
                            }
                        ),
                    },
                }
            ],
        }

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)}
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Research, persist, and verify.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=semantic_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(
            message.get("content") or ""
        ),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )
    gated_output = loop._goal_gated_model_output(
        "The report is ready.",
        {"role": "assistant", "content": "The report is ready."},
        contract=contract,
        messages=messages,
        timeline=timeline,
        run_id=run_id,
        base_url="https://model.invalid",
        model="test-model",
        api_key="test-key",
        budget=budget,
    )

    assert str(gated_output) == "The report is ready."
    assert runtime_goal_assessment(contract, timeline).completed is True
    semantic_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.goal.semantic_artifact.assessed"
    )
    assert timeline.index(semantic_event) > timeline.index(verify_event)
    assert semantic_event["verdict"] == "fulfilled"
    assert "content" not in semantic_event
    assert len(semantic_calls) == len(pending_semantic_candidates)
    assert all(
        [tool["function"]["name"] for tool in call["tools"]]
        == [SEMANTIC_ARTIFACT_VERIFICATION_TOOL_NAME]
        for call in semantic_calls
    )
    assert all(
        call["tool_choice"]
        == {
            "type": "function",
            "function": {"name": SEMANTIC_ARTIFACT_VERIFICATION_TOOL_NAME},
        }
        for call in semantic_calls
    )
    semantic_run_event = next(
        payload
        for event_type, payload in run_events
        if event_type == "agent.goal.semantic_artifact.assessed"
    )
    assert "content" not in semantic_run_event


def test_generic_loop_run_rewrites_semantically_insufficient_artifact_with_fresh_lineage() -> None:
    run_id = "run-generic-semantic-rewrite"
    original_goal = "请生成一份可供决策的销售分析报告"
    allowed_tools = ["workspace.list", "terminal.run", "workspace.read"]
    report_path = "analysis-report.md"
    first_content = "# 报告\n\n销售额增长了 20%。\n"
    second_content = (
        "# 决策报告\n\n销售额增长了 20%。主要风险是流失率上升；"
        "建议保持当前发布计划，并每周监测留存率。\n"
    )
    first_materialization = "```sh\nprintf semantic-first > analysis-report.md\n```"
    second_materialization = "```sh\nprintf semantic-second > analysis-report.md\n```"
    goal_contract = {
        "contract_id": "goal-contract-semantic-rewrite",
        "original_goal": original_goal,
        "intent_kind": "report_generation",
        "criteria": [
            {
                "criterion_id": "criterion-semantic-rewrite",
                "description": "产出一份包含结论、风险和建议的决策报告",
                "effectful": True,
                "required": True,
                "response_satisfiable": False,
                "required_capabilities": ["data.analysis"],
                "required_verification_predicates": [
                    "exact_file_content_present",
                    "semantic_artifact_adequacy",
                ],
                "expected": {
                    "state": "fulfilled",
                    "target": {
                        "kind": "data_analysis",
                        "action": "analyze",
                        "artifact_path": report_path,
                    },
                },
                "source_step_ids": ["run-analysis"],
                "verifier_step_ids": ["verify-analysis-artifact"],
            }
        ],
        "max_total_attempts": 12,
        "max_subgoal_attempts": 2,
    }
    envelope = {
        "envelope_id": "execution-envelope-semantic-rewrite",
        "source": "runtime_planner",
        "decision_id": "decision-semantic-rewrite",
        "plan_id": "plan-semantic-rewrite",
        "intent_kind": "report_generation",
        "goal_contract": goal_contract,
        "task_core": {"goal_contract": goal_contract},
        "requests": [
            {
                "request_id": "request-inspect-report-context",
                "step_id": "inspect-report-context",
                "tool_name": "workspace.list",
                "capability_id": "file.workspace_read",
                "input": {"path": "."},
                "status": "planned",
                "continue_to_model": True,
                "plan_id": "plan-semantic-rewrite",
            },
            {
                "request_id": "request-run-analysis",
                "step_id": "run-analysis",
                "tool_name": "terminal.run",
                "capability_id": "data.analysis",
                "input": {
                    "command": "# inspect data, compute summary, generate charts",
                    "artifact_path": report_path,
                },
                "status": "planned",
                "depends_on": ["inspect-report-context"],
                "continue_to_model": True,
                "plan_id": "plan-semantic-rewrite",
                "runtime_stage": "operate",
                "runtime_role": "execute",
                "requires_post_action_verification": True,
                "action_target": {
                    "kind": "data_analysis",
                    "action": "analyze",
                    "artifact_path": report_path,
                },
            },
            {
                "request_id": "request-verify-analysis-artifact",
                "step_id": "verify-analysis-artifact",
                "tool_name": "workspace.read",
                "capability_id": "file.workspace_read",
                "input": {"path": report_path},
                "status": "planned",
                "depends_on": ["run-analysis"],
                "continue_to_model": True,
                "plan_id": "plan-semantic-rewrite",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "requires_observation": True,
                "verified_step_ids": ["run-analysis"],
                "verification_target_step_ids": ["run-analysis"],
                "action_target": {
                    "kind": "verification",
                    "action": "read_file",
                    "path": report_path,
                    "verified_step_ids": ["run-analysis"],
                },
            },
        ],
    }

    class _SemanticRewriteModel:
        def __init__(self) -> None:
            self.materializations = [first_materialization, second_materialization]
            self.semantic_verdicts = ["insufficient", "fulfilled"]
            self.semantic_calls: list[dict[str, Any]] = []

        def __call__(
            self,
            _base_url: str,
            _model: str,
            _api_key: str,
            _messages: list[dict[str, Any]],
            *,
            tools: list[dict[str, Any]],
            **kwargs: Any,
        ) -> dict[str, Any]:
            tool_names = {
                str(tool.get("function", {}).get("name") or "")
                for tool in tools
                if isinstance(tool, dict)
                and isinstance(tool.get("function"), dict)
            }
            if SEMANTIC_ARTIFACT_VERIFICATION_TOOL_NAME in tool_names:
                assert self.semantic_verdicts, "unexpected semantic verifier call"
                verdict = self.semantic_verdicts.pop(0)
                self.semantic_calls.append(dict(kwargs))
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"semantic-{verdict}",
                            "type": "function",
                            "function": {
                                "name": SEMANTIC_ARTIFACT_VERIFICATION_TOOL_NAME,
                                "arguments": json.dumps(
                                    {
                                        "verdict": verdict,
                                        "reason": (
                                            "缺少风险和决策建议。"
                                            if verdict == "insufficient"
                                            else "报告包含结论、风险和建议。"
                                        ),
                                        "missing_requirements": (
                                            ["补充主要风险和明确建议。"]
                                            if verdict == "insufficient"
                                            else []
                                        ),
                                    },
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                }
            assert self.materializations, "Runtime requested an unexecuted rewrite"
            return {
                "role": "assistant",
                "content": self.materializations.pop(0),
            }

    class _SemanticRewriteBroker:
        def __init__(self) -> None:
            self.current_content = ""
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            assert approved is False
            self.calls.append((tool_name, dict(payload)))
            if tool_name == "workspace.list":
                return {"ok": True, "path": ".", "entries": []}
            if tool_name == "terminal.run":
                command = str(payload["command"])
                self.current_content = (
                    first_content if "semantic-first" in command else second_content
                )
                return {
                    "ok": True,
                    "exit_code": 0,
                    "returncode": 0,
                }
            if tool_name == "workspace.read" and payload == {"path": report_path}:
                encoded = self.current_content.encode("utf-8")
                return {
                    "ok": True,
                    "path": report_path,
                    "content": self.current_content,
                    "truncated": False,
                    "size_bytes": len(encoded),
                    "content_bytes": len(encoded),
                    "decoding_lossy": False,
                }
            raise AssertionError(f"Unexpected tool call: {tool_name} {payload}")

        def close_owned_browser_target(self) -> None:
            return None

    budget = _Budget()
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, dict[str, Any]]] = []
    broker = _SemanticRewriteBroker()
    model = _SemanticRewriteModel()

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_fence: Any,
    ) -> dict[str, Any]:
        run_events.append((event_type, dict(payload)))
        return {"event_type": event_type, "payload": payload}

    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=_ToolCallEvents(),
        trace_events=_TraceEvents(),
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
    )

    def execute_tool(
        tool_request: dict[str, Any],
        allowed_tools_value: list[str],
        active_broker: _SemanticRewriteBroker,
        active_timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return executor.execute(
            tool_request,
            allowed_tools_value,
            active_broker,
            active_timeline,
            artifacts=artifacts if artifacts is not None else [],
            **kwargs,
        )

    projection = RuntimeToolLoopProjectionBuilder()
    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda messages: next(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=projection,
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "unexpected-approval",
            now=lambda: "2026-07-21T00:00:00Z",
        ),
        call_agent_tool=execute_tool,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)}
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=4,
        operating_doctrine="Materialize, verify, and rewrite until adequate.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )

    result = loop.run(
        {"name": "Yachiyo"},
        original_goal,
        broker=broker,
        timeline=timeline,
        artifacts=artifacts,
        runtime_execution_envelope=envelope,
        run_id=run_id,
        budget=budget,
    )

    assert str(result) == second_materialization
    assert model.materializations == []
    assert model.semantic_verdicts == []
    semantic_events = [
        event
        for event in timeline
        if event.get("event") == "agent.goal.semantic_artifact.assessed"
    ]
    assert [event["verdict"] for event in semantic_events] == [
        "insufficient",
        "fulfilled",
    ]
    assert [event["content_sha256"] for event in semantic_events] == [
        hashlib.sha256(first_content.encode("utf-8")).hexdigest(),
        hashlib.sha256(second_content.encode("utf-8")).hexdigest(),
    ]
    artifact_events = [
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "terminal.run"
    ]
    assert len(artifact_events) == 2
    assert artifact_events[0]["request_id"] != artifact_events[1]["request_id"]
    assert artifact_events[0]["tool_call_id"] != artifact_events[1]["tool_call_id"]
    assert budget.model_calls == 4
    assert all(
        call["tool_choice"]
        == {
            "type": "function",
            "function": {"name": SEMANTIC_ARTIFACT_VERIFICATION_TOOL_NAME},
        }
        for call in model.semantic_calls
    )


def test_main_chat_generic_loop_budget_exhaustion_stays_truthful_while_recoverable_retry_remains() -> None:
    run_id = "run-generic-budget-truthful"
    original_goal = "Play Moonlight"
    allowed_tools = ["media.apple_music_play", "browser.search"]

    class _BudgetTruthfulModel:
        def __init__(self) -> None:
            self.planning_calls = 0
            self.replan_calls = 0

        def __call__(
            self,
            _base_url: str,
            _model: str,
            _api_key: str,
            messages: list[dict[str, Any]],
            *,
            tools: list[dict[str, Any]],
            **_kwargs: Any,
        ) -> dict[str, Any]:
            tool_names = {
                str(
                    tool.get("function", {}).get("name")
                    if isinstance(tool.get("function"), dict)
                    else tool.get("name")
                    or ""
                ).strip()
                for tool in tools
                if isinstance(tool, dict)
            }
            if MODEL_INTENT_PLANNING_TOOL_NAME in tool_names:
                self.planning_calls += 1
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "model-intent-plan",
                            "type": "function",
                            "function": {
                                "name": MODEL_INTENT_PLANNING_TOOL_NAME,
                                "arguments": json.dumps(
                                    {
                                        "intent_kind": "media_playback",
                                        "planning_goal": original_goal,
                                        "action_evidence": original_goal,
                                        "rationale": "The user asked to play a song.",
                                    }
                                ),
                            },
                        }
                    ],
                }
            latest_user = next(
                (
                    str(message.get("content") or "")
                    for message in reversed(messages)
                    if message.get("role") == "user"
                ),
                "",
            )
            if "Runtime replan context" in latest_user and self.replan_calls == 0:
                self.replan_calls += 1
                assert "browser_search" in tool_names
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "resolve-canonical-alias",
                            "type": "function",
                            "function": {
                                "name": "browser_search",
                                "arguments": json.dumps({"query": "Moonlight song alias"}),
                            },
                        }
                    ],
                }
            return {"role": "assistant", "content": "unexpected final"}

    class _BudgetTruthfulBroker:
        def __init__(self, *, timeline: list[dict[str, Any]]) -> None:
            self.timeline = timeline
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            assert approved is False
            self.calls.append((tool_name, dict(payload)))
            if tool_name == "media.apple_music_play":
                return {
                    "ok": False,
                    "status": "failed",
                    "error": "catalog miss",
                    "retryable": True,
                    "replan_allowed": True,
                }
            if tool_name == "browser.search":
                return {
                    "ok": True,
                    "action": "browser.search",
                    "summary": "Moonlight canonical alias",
                    "postcondition_verified": True,
                    "data": {
                        "query": payload["query"],
                        "text": "Moonlight canonical alias",
                        "results": [
                            {
                                "title": "Moonlight canonical alias",
                                "url": "https://example.invalid/moonlight",
                                "snippet": "Moonlight canonical alias",
                            }
                        ],
                    },
                }
            raise AssertionError(f"Unexpected tool call: {tool_name}")

        def close_owned_browser_target(self) -> None:
            return None

    budget = _Budget()
    artifacts: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, dict[str, Any]]] = []
    model = _BudgetTruthfulModel()
    broker = _BudgetTruthfulBroker(timeline=timeline)

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_fence: Any,
    ) -> dict[str, Any]:
        run_events.append((event_type, dict(payload)))
        return {"event_type": event_type, "payload": payload}

    executor = RuntimeToolCallExecutor(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
        limit_tool_result=lambda value: value,
        timeline_factory=_timeline,
        tool_call_events=_ToolCallEvents(),
        trace_events=_TraceEvents(),
        append_run_event=append_run_event,
        allows_tool=PolicyGate.allows_tool,
    )

    def execute_tool(
        tool_request: dict[str, Any],
        allowed_tools_value: list[str],
        active_broker: _BudgetTruthfulBroker,
        active_timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del artifacts
        broker.timeline = active_timeline
        return executor.execute(
            tool_request,
            allowed_tools_value,
            active_broker,
            active_timeline,
            artifacts=[],
            **kwargs,
        )

    projection = RuntimeToolLoopProjectionBuilder()
    request_runner = RuntimeToolRequestRunner(
        normalize_tool_name=normalize_tool_name,
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda messages: next(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "user"
        ),
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=projection,
        pending_approval_builder=ToolPendingApprovalBuilder(
            approval_id_factory=lambda: "unexpected-approval",
            now=lambda: "2026-07-20T00:00:00Z",
        ),
        call_agent_tool=execute_tool,
    )
    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)}
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=RuntimeToolOperations.model_tool_schemas,
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=2,
        operating_doctrine="Stop truthfully when budget ends mid-recovery.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(
            message.get("content") or ""
        ),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=RuntimeToolOperations.tool_requests_from_message,
        timeline_factory=_timeline,
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=agent_runtime._ModelOutputText,
        tool_loop_projection=projection,
        run_tool_requests=request_runner.run,
        error_type=agent_runtime.AgentRuntimeError,
        append_run_event=append_run_event,
    )

    state: dict[str, Any] = {
        "run": {
            "run_id": run_id,
            "kind": "main_chat_run",
            "user_goal": original_goal,
            "status": "running",
            "updated_at": "version-0",
            "timeline": timeline,
            "artifacts": artifacts,
            "pending_approval": {},
        }
    }
    version = 0

    def update_run(_run_id: str, **payload: Any) -> dict[str, Any] | None:
        nonlocal version
        current = state["run"]
        if (
            payload.get("expected_status") is not None
            and payload["expected_status"] != current.get("status")
        ):
            return None
        if (
            payload.get("expected_updated_at") is not None
            and payload["expected_updated_at"] != current.get("updated_at")
        ):
            return None
        if payload.get("expected_pending_approval_absent") and current.get(
            "pending_approval"
        ):
            return None
        current.update(
            {
                key: value
                for key, value in payload.items()
                if not key.startswith("expected_")
            }
        )
        version += 1
        current["updated_at"] = f"version-{version}"
        return dict(current)

    runner = MainChatModelLoopRunner(
        get_run=lambda _run_id: state["run"],
        default_profile_id=lambda: "profile-test",
        model_profile_config_private=lambda _profile_id: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        main_chat_agent_config=lambda **kwargs: {
            "agent_id": "builtin:yachiyo-main",
            "name": "Yachiyo",
            **kwargs,
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": list(allowed_tools)},
            "workspace_policy": {"default_workdir": "/workspace"},
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        runtime_agent_timeline=_RuntimeTimeline(),
        timeline_factory=_timeline,
        update_run=update_run,
        append_run_event=append_run_event,
        task_model_events=_TaskModelEvents(),
        tool_brokers=_ToolBrokers(broker),  # type: ignore[arg-type]
        continue_custom_api_agent=loop.run,
        main_chat_pending_approval=lambda *_args, **_kwargs: {},
        approval_pause=object(),
        terminal_run_or_none=lambda _run_id: None,
        fail_main_chat_run=lambda active_run_id, error, **_kwargs: {
            "run_id": active_run_id,
            "status": "failed",
            "result": str(error),
        },
        redact_secrets=str,
        model_output_metadata=lambda _value: {"finish_reason": "stop"},
        error_type=agent_runtime.AgentRuntimeError,
        resolve_initial_model_plan=loop.resolve_initial_model_plan,
    )

    with pytest.raises(
        agent_runtime.AgentRuntimeError,
        match="工具循环超过上限",
    ):
        runner.execute(run_id, [{"role": "user", "content": original_goal}])

    timeline = state["run"]["timeline"]
    assert [tool for tool, _payload in broker.calls] == [
        "media.apple_music_play",
        "browser.search",
    ]
    assert not any(
        event.get("event") == "agent.goal.assessed"
        and event.get("status") == "completed"
        for event in timeline
    )
    assert not any(
        event.get("event") == "agent.awaiting_user"
        for event in timeline
    )
    assert any(
        event.get("event") == "agent.replan.requested"
        and event.get("payload", {}).get("source_tool_name") == "media.apple_music_play"
        for event in timeline
    )
