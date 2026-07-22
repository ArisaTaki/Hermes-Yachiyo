"""Focused adapter tests for correlated Apple Music alias recovery."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import quote_plus

import pytest

from apps.shell.agent.runtime.errors import (
    AgentApprovalRequired,
    AgentDirectOutcomeUnverified,
    AgentRuntimeError,
)
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_EXECUTION_PROVENANCE_VERSION,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionContext,
    RecoveryActionDisposition,
    RecoveryActionRegistry,
    RecoveryActionScope,
    RecoveryModelTurn,
    RecoveryToolBatch,
    RecoveryToolResult,
)
from apps.shell.agent.runtime.recovery_adapters import (
    AppleMusicAliasRecoveryAdapter,
    EntityAliasRecoveryAdapter,
)
from apps.shell.agent.runtime.recovery_adapters.entity_alias import (
    entity_alias_recovery_source,
)
from apps.shell.agent.runtime.recovery_policies import assess_latest_tool_recovery
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus, from_tool_result

_ALLOWED_TOOLS = frozenset(
    {
        "media.apple_music_play",
        "browser.search",
        "browser.extract_text",
    }
)


def _partial_result(
    query: str,
    *,
    tool_name: str = "media.apple_music_play",
    status: str = "not_found",
    request_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "query": query,
        "status": status,
        "outcome": "partial",
        "background_safe": True,
        "library_search_completed": True,
        "foreground_action_taken": False,
        "playback_started": False,
        "search_opened": False,
        "user_action_required": False,
    }
    if request_input is not None:
        data["request_input"] = dict(request_input)
    return {
        "ok": True,
        "action": tool_name,
        RUNTIME_EXECUTION_PROVENANCE_KEY: {
            "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
            "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
        },
        "data": data,
    }


def _provider_routed_partial_result(query: str) -> dict[str, Any]:
    result = _partial_result(query)
    result.pop(RUNTIME_EXECUTION_PROVENANCE_KEY, None)
    result.update(
        {
            "tool": "media.apple_music_play",
            "desktop_execution_provider_routed": True,
            "desktop_execution_provider": {
                "provider_id": "background-media-provider",
                "provider_kind": "background_desktop",
                "route_id": "desktop-route:media.apple_music_play",
            },
            "desktop_execution_route": {
                "selected_provider_id": "background-media-provider",
                "selected_provider_kind": "background_desktop",
                "route_id": "desktop-route:media.apple_music_play",
                "can_execute": True,
                "status": "provider_ready",
            },
            "desktop_execution_evidence": {
                "ok": True,
                "permission_error": False,
                "effect": "media_control",
                "transport": "runtime_tool_broker",
                "tool": "media.apple_music_play",
                "query": query,
            },
        }
    )
    return result


def _source_scope_id(tool_name: str, source_tool_call_id: str) -> str:
    identity = f"{tool_name}\0{source_tool_call_id}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"tool-attempt:{digest}"


def _context(
    runtime: Any,
    *,
    query: str = "超时空辉夜姬",
    source_tool: str = "media.apple_music_play",
    source_tool_call_id: str = "source-media",
    scope_id: str | None = None,
    source_result: dict[str, Any] | None = None,
    allowed_tools: Iterable[str] | None = None,
) -> RecoveryActionContext:
    outcome = from_tool_result(
        source_tool,
        source_result if source_result is not None else _partial_result(query),
        capabilities=("media.playback",),
    )
    return RecoveryActionContext(
        plan=RecoveryPlan(
            strategy_id="resolve-entity-alias",
            action="resolve_entity_alias",
            recovery_hint="entity_not_found",
            required_capabilities=(
                "browser.research",
                "information.capture",
                "media.playback",
            ),
            source_status=OutcomeStatus.PARTIAL,
            source_reason=outcome.reason,
            scope_id=(
                scope_id
                if scope_id is not None
                else _source_scope_id(source_tool, source_tool_call_id)
            ),
        ),
        source_outcome=outcome,
        source_tool_call_id=source_tool_call_id,
        scope=RecoveryActionScope(
            allowed_tools=(
                allowed_tools
                if allowed_tools is not None
                else {source_tool, "browser.search", "browser.extract_text"}
            ),
            iteration=1,
        ),
        runtime=runtime,
    )


class _FakeRuntimePort:
    def __init__(
        self,
        *,
        exception_stage: str = "",
        exception: Exception | None = None,
        false_stage: str = "",
        selection_mode: str = "valid",
        completion: str = "played",
        source_tool: str = "media.apple_music_play",
        original_query: str = "超时空辉夜姬",
        alias: str = "Cho Kaguya Hime",
        selected_extra_input: Mapping[str, Any] | None = None,
        retry_result: Mapping[str, Any] | None = None,
        evidence_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.exception_stage = exception_stage
        self.exception = exception
        self.false_stage = false_stage
        self.selection_mode = selection_mode
        self.completion = completion
        self.source_tool = source_tool
        self.original_query = original_query
        self.alias = alias
        self.selected_extra_input = dict(selected_extra_input or {})
        self.retry_result = dict(retry_result) if retry_result is not None else None
        self.evidence_records = (
            [dict(record) for record in evidence_records]
            if evidence_records is not None
            else None
        )
        self.allowed_tools = {
            source_tool,
            "browser.search",
            "browser.extract_text",
        }
        self.tools: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.tool_call_ids: list[str] = []
        self.search_queries: list[str] = []
        self.system_prompts: list[str] = []
        self.user_prompts: list[str] = []
        self.commit_count = 0
        self.committed_turns: list[RecoveryModelTurn] = []
        self.release_count = 0

    def execute_tools(
        self,
        tool_requests: Sequence[Mapping[str, Any]],
        *,
        allowed_tools: Iterable[str],
        next_iteration: int,
    ) -> RecoveryToolBatch:
        assert set(allowed_tools).issubset(self.allowed_tools)
        assert next_iteration == 2
        request = dict(tool_requests[0])
        self.requests.append(request)
        tool = str(request.get("tool") or "")
        self.tools.append(tool)
        self.tool_call_ids.append(str(request.get("tool_call_id") or ""))
        stage = (
            "search"
            if tool == "browser.search"
            else "extract"
            if tool == "browser.extract_text"
            else "media"
        )
        if stage == self.exception_stage and self.exception is not None:
            raise self.exception
        if stage == "search":
            self.search_queries.append(str(request["input"]["query"]))
            result = (
                {"ok": False, "error": "unavailable"}
                if self.false_stage == "search"
                else {"ok": True, "data": {"target_owned_by_run": True}}
            )
        elif stage == "extract":
            result = (
                {"ok": False, "error": "unavailable"}
                if self.false_stage == "extract"
                else {
                    "ok": True,
                    "data": {
                        "page_url": (
                            "https://www.google.com/search?q="
                            + quote_plus(
                                f"{self.original_query} official title "
                                "alternate title romanization"
                            )
                        ),
                        "link_contexts": [],
                    },
                }
                if self.false_stage == "evidence"
                else {
                    "ok": True,
                    "data": {
                        "page_url": (
                            "https://www.google.com/search?q="
                            + quote_plus(
                                f"{self.original_query} official title "
                                "alternate title romanization"
                            )
                        ),
                        "link_contexts": (
                            self.evidence_records
                            if self.evidence_records is not None
                            else [
                                {
                                    "href": "https://zh.wikipedia.org/wiki/entity",
                                    "text": (
                                        f"{self.original_query} · 英文名称: {self.alias}"
                                    ),
                                }
                            ]
                        ),
                    },
                }
            )
        else:
            result = self.retry_result or {
                "ok": True,
                "action": self.source_tool,
                "data": {
                    "query": self.alias,
                    "status": "played",
                    "track": self.alias,
                    "track_identity_verified": True,
                    "player_state": "playing",
                    "playback_started": True,
                },
            }
        return RecoveryToolBatch(
            requests=(request,),
            results=(
                RecoveryToolResult(
                    tool_call_id=str(request.get("tool_call_id") or ""),
                    result=result,
                ),
            ),
            completion_token=len(self.tools),
        )

    def select_tool(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        allowed_tools: Iterable[str],
    ) -> RecoveryModelTurn:
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        assert "untrusted web evidence" in system_prompt
        assert self.alias in user_prompt
        assert tuple(allowed_tools) == (self.source_tool,)
        if self.exception_stage == "model" and self.exception is not None:
            raise self.exception
        request = {
            "protocol": "tool_calls",
            "tool": (
                "browser.search"
                if self.selection_mode == "wrong_tool"
                else self.source_tool
            ),
            "tool_call_id": "alias-media",
            "input": {
                "query": (
                    "Invented Alias"
                    if self.selection_mode == "unsupported_alias"
                    else self.alias
                ),
                **self.selected_extra_input,
            },
        }
        return RecoveryModelTurn(
            message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": request["tool_call_id"],
                        "type": "function",
                        "function": {
                            "name": request["tool"],
                            "arguments": f'{{"query":"{self.alias}"}}',
                        },
                    }
                ],
            },
            visible_content="",
            tool_requests=() if self.selection_mode == "none" else (request,),
        )

    def commit_model_turn(
        self,
        *,
        user_prompt: str,
        turn: RecoveryModelTurn,
    ) -> None:
        assert user_prompt
        assert len(turn.tool_requests) == 1
        self.commit_count += 1
        self.committed_turns.append(turn)

    def project_completion(self, _batch: RecoveryToolBatch) -> str:
        return self.completion

    def release_owned_resources(self) -> None:
        self.release_count += 1


@pytest.mark.parametrize("stage", ["search", "extract", "model"])
@pytest.mark.parametrize(
    "exception",
    [
        AgentApprovalRequired({"tool": "test"}),
        AgentDirectOutcomeUnverified("unverified"),
        AgentRuntimeError("budget or lease stopped"),
    ],
)
def test_control_exceptions_propagate_from_optional_stages(
    stage: str,
    exception: Exception,
) -> None:
    runtime = _FakeRuntimePort(exception_stage=stage, exception=exception)

    with pytest.raises(type(exception)) as exc_info:
        RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(_context(runtime))

    assert exc_info.value is exception
    assert runtime.release_count == 1


@pytest.mark.parametrize("stage", ["search", "extract", "model"])
def test_optional_timeouts_fall_back_quietly(stage: str) -> None:
    runtime = _FakeRuntimePort(
        exception_stage=stage,
        exception=TimeoutError("optional recovery timed out"),
    )

    result = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == f"{stage}_timeout"
    assert runtime.release_count == 1


@pytest.mark.parametrize("stage", ["search", "extract"])
def test_structured_browser_failures_fall_back_quietly(stage: str) -> None:
    runtime = _FakeRuntimePort(false_stage=stage)

    result = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == f"{stage}_tool_failed"
    assert len(result.attempts) == (1 if stage == "search" else 2)
    assert runtime.release_count == 1


def test_missing_alias_evidence_is_an_explicit_failed_recovery_attempt() -> None:
    runtime = _FakeRuntimePort(false_stage="evidence")

    result = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "alias_evidence_unavailable"
    assert len(result.attempts) == 2
    assert runtime.release_count == 1


@pytest.mark.parametrize(
    ("selection_mode", "expected_reason"),
    [
        ("none", "alias_selection_unavailable"),
        ("wrong_tool", "alias_selection_unavailable"),
        ("unsupported_alias", "alias_not_supported_by_evidence"),
    ],
)
def test_invalid_alias_selection_is_an_explicit_failed_recovery_attempt(
    selection_mode: str,
    expected_reason: str,
) -> None:
    runtime = _FakeRuntimePort(selection_mode=selection_mode)

    result = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == expected_reason
    assert len(result.attempts) == 2
    assert runtime.release_count == 1


def test_retry_without_terminal_projection_is_an_execution_failure() -> None:
    runtime = _FakeRuntimePort(completion="")

    result = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "retry_not_completed"
    assert len(result.attempts) == 3
    assert runtime.release_count == 1


def test_media_retry_exception_propagates_and_resources_release_once() -> None:
    expected = AgentRuntimeError("Music Automation denied")
    runtime = _FakeRuntimePort(exception_stage="media", exception=expected)

    with pytest.raises(AgentRuntimeError, match="Automation denied") as exc_info:
        RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(_context(runtime))

    assert exc_info.value is expected
    assert runtime.commit_count == 1
    assert runtime.release_count == 1


def test_missing_chat_profile_uses_single_evidence_bound_alias_without_crashing() -> None:
    runtime = _FakeRuntimePort(
        exception_stage="model",
        exception=AgentRuntimeError(
            "Agent 缺少可运行的 Chat Profile；请在 Agent Studio 为该岗位选择已测试的文本模型。"
        ),
    )

    result = RecoveryActionRegistry((EntityAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.TERMINAL_COMPLETION
    assert result.terminal_output == "played"
    assert runtime.tools == [
        "browser.search",
        "browser.extract_text",
        "media.apple_music_play",
    ]
    assert runtime.requests[-1]["input"]["query"] == "Cho Kaguya Hime"
    assert runtime.commit_count == 0
    assert runtime.release_count == 1


def test_missing_chat_profile_does_not_guess_between_ambiguous_grounded_aliases() -> None:
    runtime = _FakeRuntimePort(
        exception_stage="model",
        exception=AgentRuntimeError(
            "Agent 缺少可运行的 Chat Profile；请在 Agent Studio 为该岗位选择已测试的文本模型。"
        ),
        evidence_records=(
            {
                "href": "https://zh.wikipedia.org/wiki/entity",
                "text": "超时空辉夜姬 · 英文名称: Cho Kaguya Hime",
            },
            {
                "href": "https://musicbrainz.org/work/example",
                "text": "超时空辉夜姬 · alternate title: Cosmic Princess Kaguya!",
            },
        ),
    )

    result = RecoveryActionRegistry((EntityAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "alias_selection_model_unavailable"
    assert runtime.tools == ["browser.search", "browser.extract_text"]
    assert runtime.commit_count == 0
    assert runtime.release_count == 1


@pytest.mark.parametrize(
    ("retry_result", "expected_reason"),
    [
        (
            {
                "ok": True,
                "action": "media.apple_music_play",
                "data": {
                    "query": "Cho Kaguya Hime",
                    "status": "played",
                    "track": "Different Song",
                    "track_identity_verified": False,
                    "player_state": "playing",
                    "playback_started": True,
                },
            },
            "retry_track_identity_unverified",
        ),
        (
            _partial_result("Cho Kaguya Hime"),
            "retry_entity_not_found",
        ),
        (
            {
                "ok": True,
                "action": "media.apple_music_play",
                "data": {
                    "query": "Cho Kaguya Hime",
                    "status": "played",
                    "track": "Cho Kaguya Hime",
                    "track_identity_verified": True,
                    "player_state": "paused",
                    "playback_started": True,
                },
            },
            "retry_playback_not_playing",
        ),
    ],
    ids=("wrong-track", "second-miss", "not-playing"),
)
def test_retry_completion_text_never_overrides_unverified_media_state(
    retry_result: Mapping[str, Any],
    expected_reason: str,
) -> None:
    runtime = _FakeRuntimePort(retry_result=retry_result, completion="played")

    result = RecoveryActionRegistry((EntityAliasRecoveryAdapter(),)).execute(
        _context(runtime)
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == expected_reason
    assert len(result.attempts) == 3
    assert runtime.tools.count("media.apple_music_play") == 1
    assert runtime.release_count == 1


def test_adapter_consumes_only_assessment_correlated_source_outcome() -> None:
    timeline = [
        {
            "event": "agent.tool.call",
            "tool": "media.apple_music_play",
            "tool_call_id": "first-media",
            "result": _partial_result("first query"),
        },
        {
            "event": "agent.tool.call",
            "tool": "media.apple_music_play",
            "tool_call_id": "second-media",
            "result": _partial_result("超时空辉夜姬"),
        },
    ]
    assessment = assess_latest_tool_recovery(
        timeline,
        start_index=0,
        allowed_tools=_ALLOWED_TOOLS,
    )
    assert assessment is not None
    assert assessment.plan is not None
    runtime = _FakeRuntimePort()
    context = RecoveryActionContext(
        plan=assessment.plan,
        source_outcome=assessment.outcome,
        source_tool_call_id=assessment.tool_call_id,
        scope=RecoveryActionScope(allowed_tools=_ALLOWED_TOOLS, iteration=1),
        runtime=runtime,
    )

    result = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(context)

    assert result.disposition is RecoveryActionDisposition.TERMINAL_COMPLETION
    assert result.terminal_output == "played"
    assert len(result.attempts) == 3
    assert assessment.tool_call_id == "second-media"
    assert runtime.search_queries == [
        "超时空辉夜姬 official title alternate title romanization"
    ]
    assert runtime.requests[-1]["source"] == "runtime_internal_recovery"
    assert runtime.requests[-1]["planning_reason"] == "entity_alias_retry"
    assert runtime.release_count == 1


@pytest.mark.parametrize(
    "source_result",
    [
        {
            key: value
            for key, value in _partial_result("超时空辉夜姬").items()
            if key != RUNTIME_EXECUTION_PROVENANCE_KEY
        },
        {
            **{
                key: value
                for key, value in _partial_result("超时空辉夜姬").items()
                if key != RUNTIME_EXECUTION_PROVENANCE_KEY
            },
            "desktop_execution_provider_routed": True,
            "desktop_execution_provider_kind": "background_desktop",
        },
    ],
    ids=("missing-provenance", "provider-routed"),
)
def test_adapter_rejects_nonlocal_source_locus(
    source_result: dict[str, Any],
) -> None:
    runtime = _FakeRuntimePort()

    result = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(runtime, source_result=source_result)
    )

    assert result.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert result.reason == "no_unique_adapter"
    assert runtime.requests == []
    assert runtime.commit_count == 0
    assert runtime.release_count == 0


def test_provider_routed_source_requires_an_exact_background_safe_receipt() -> None:
    result = _provider_routed_partial_result("超时空辉夜姬")
    outcome = from_tool_result(
        "media.apple_music_play",
        result,
        capabilities=("media.playback",),
    )

    source = entity_alias_recovery_source(outcome)

    assert source is not None
    assert source.query == "超时空辉夜姬"
    assert source.provenance == {
        "source": "desktop_execution_provider",
        "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
        "provider_id": "background-media-provider",
        "provider_kind": "background_desktop",
        "route_id": "desktop-route:media.apple_music_play",
        "transport": "runtime_tool_broker",
    }


@pytest.mark.parametrize(
    "tamper",
    ("query", "transport", "provider", "route", "foreground"),
)
def test_provider_routed_source_rejects_mismatched_or_foreground_receipts(
    tamper: str,
) -> None:
    result = _provider_routed_partial_result("超时空辉夜姬")
    if tamper == "query":
        result["desktop_execution_evidence"]["query"] = "Different Song"
    elif tamper == "transport":
        result["desktop_execution_evidence"]["transport"] = "user_supplied"
    elif tamper == "provider":
        result["desktop_execution_provider"]["provider_id"] = "other-provider"
    elif tamper == "route":
        result["desktop_execution_route"]["status"] = "unverified"
    else:
        result["data"]["foreground_action_taken"] = True
    outcome = from_tool_result(
        "media.apple_music_play",
        result,
        capabilities=("media.playback",),
    )

    assert entity_alias_recovery_source(outcome) is None


def test_internal_request_ids_are_scoped_for_same_iteration() -> None:
    first_runtime = _FakeRuntimePort()
    second_runtime = _FakeRuntimePort()

    first = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(first_runtime, source_tool_call_id="source:first")
    )
    second = RecoveryActionRegistry((AppleMusicAliasRecoveryAdapter(),)).execute(
        _context(second_runtime, source_tool_call_id="source:second")
    )

    assert first.terminal_output == "played"
    assert second.terminal_output == "played"

    assert first_runtime.tool_call_ids[:2] != second_runtime.tool_call_ids[:2]
    assert all(first_runtime.tool_call_ids[:2])
    assert all(second_runtime.tool_call_ids[:2])


def test_legacy_adapter_name_is_the_generic_adapter_alias() -> None:
    assert AppleMusicAliasRecoveryAdapter is EntityAliasRecoveryAdapter


def test_generic_adapter_retries_non_apple_media_source_with_bound_input() -> None:
    source_tool = "media.catalog_play"
    source_call_id = "source-catalog"
    original_query = "星际歌姬"
    source_input = {
        "query": original_query,
        "device_id": "living-room",
        "quality": "lossless",
    }
    runtime = _FakeRuntimePort(
        source_tool=source_tool,
        original_query=original_query,
        alias="Stellar Diva",
        selected_extra_input={
            "device_id": "untrusted-model-change",
            "quality": "low",
        },
    )
    context = _context(
        runtime,
        query=original_query,
        source_tool=source_tool,
        source_tool_call_id=source_call_id,
        source_result=_partial_result(
            original_query,
            tool_name=source_tool,
            status="no_match",
            request_input=source_input,
        ),
    )

    result = RecoveryActionRegistry((EntityAliasRecoveryAdapter(),)).execute(context)

    assert result.disposition is RecoveryActionDisposition.TERMINAL_COMPLETION
    assert result.terminal_output == "played"
    assert runtime.tools == [
        "browser.search",
        "browser.extract_text",
        source_tool,
    ]
    assert runtime.requests[-1]["input"] == {
        **source_input,
        "query": "Stellar Diva",
    }
    committed_call = runtime.committed_turns[0].message["tool_calls"][0]
    assert committed_call["id"] == runtime.requests[-1]["tool_call_id"]
    assert json.loads(committed_call["function"]["arguments"]) == {
        **source_input,
        "query": "Stellar Diva",
    }
    assert all(
        request["source_tool_call_id"] == source_call_id
        and request["recovery_scope_id"] == context.plan.scope_id
        and request["recovery_source_provenance"]
        == {
            "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
            "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
        }
        for request in runtime.requests
    )
    assert all(
        "apple music" not in str(value).casefold()
        for value in (
            *runtime.search_queries,
            *runtime.system_prompts,
            *runtime.user_prompts,
            *(request["planning_reason"] for request in runtime.requests),
            *(request["tool_call_id"] for request in runtime.requests),
        )
    )


def test_generic_adapter_rejects_scope_not_bound_to_source_attempt() -> None:
    runtime = _FakeRuntimePort()

    result = RecoveryActionRegistry((EntityAliasRecoveryAdapter(),)).execute(
        _context(runtime, scope_id="tool-attempt:wrong-source")
    )

    assert result.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert runtime.requests == []
