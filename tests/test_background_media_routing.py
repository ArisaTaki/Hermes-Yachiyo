"""Background-routing contracts for daily music playback intents."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell.agent.runtime.cua_background_provider import (
    CUA_BACKGROUND_PROVIDER_KIND,
)
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_EXECUTION_PROVENANCE_VERSION,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.outcome_evaluator import evaluate_main_chat_outcome
from apps.shell.yachiyo_agent.daily_desktop import daily_desktop_entrypoint_requests
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    daily_entrypoint_desktop_execution_policy,
    desktop_execution_route_decision,
)
from apps.shell.yachiyo_agent.policy import desktop_tool_execution_mode_for_input


_MEDIA_ACTION_TOOLS = {
    "media.apple_music_play",
    "media.music_app_open_and_play",
}

_MEDIA_TOOLS_WITH_FOREGROUND_FALLBACKS = (
    "media.apple_music_open_and_play",
    "media.music_app_open_and_play",
    "media.music_app_control",
)


def _primitive_background_provider() -> dict[str, Any]:
    """A Cua provider that exposes input primitives but no media composite."""

    return {
        "available": True,
        "adapter_ready": True,
        "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "provider_id": "cua-driver",
        "status": "available",
        "supported_tools": [
            "desktop.list_apps",
            "app.open",
            "desktop.safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.read_ui",
            "desktop.verify",
        ],
        "desktop_session_kind": "background_desktop",
        "desktop_session_isolated": False,
        "foreground_takeover_required": False,
        "keyboard_mouse_capture_supported": True,
    }


def _route(request: dict[str, Any]) -> dict[str, Any]:
    return desktop_execution_route_decision(
        str(request.get("tool") or ""),
        policy=daily_entrypoint_desktop_execution_policy(surface="chat"),
        execution_mode=desktop_tool_execution_mode_for_input(
            str(request.get("tool") or ""),
            request.get("input") if isinstance(request.get("input"), dict) else {},
        ),
        metadata={"sandbox_provider": _primitive_background_provider()},
    )


def _background_safe_library_miss_event(
    *,
    data_overrides: dict[str, Any] | None = None,
    remove_data: tuple[str, ...] = (),
    result_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = {
        "query": "超时空辉夜姬",
        "status": "not_found",
        "background_safe": True,
        "library_search_completed": True,
        "foreground_action_taken": False,
        "target_app": "Music",
        "search_opened": False,
        "playback_started": False,
        "outcome": "partial",
        "user_action_required": False,
    }
    data.update(data_overrides or {})
    for key in remove_data:
        data.pop(key, None)
    result = {
        "ok": True,
        "action": "media.apple_music_play",
        "data": data,
        "permission_error": False,
        "fallback_used": False,
        RUNTIME_EXECUTION_PROVENANCE_KEY: {
            "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
            "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
        },
    }
    result.update(result_overrides or {})
    return {
        "event_type": "agent.tool.call",
        "payload": {
            "tool": "media.apple_music_play",
            "input_preview": {"query": "超时空辉夜姬"},
            "result": result,
        },
    }


def test_daily_media_planner_characterizes_current_music_tool_selection() -> None:
    simple = daily_desktop_entrypoint_requests("播放 Apple Music")
    generic_query = daily_desktop_entrypoint_requests("播放某首歌")
    named_query = daily_desktop_entrypoint_requests(
        "用 Apple Music 播放超时空辉夜姬"
    )

    assert [request["tool"] for request in simple] == [
        "media.music_app_open_and_play"
    ]
    assert simple[0]["input"] == {"app_name": "Music"}
    assert [request["tool"] for request in generic_query] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
        "desktop.ui_elements",
    ]
    assert generic_query[2]["input"] == {"text": "某首歌"}
    assert [request["tool"] for request in named_query] == [
        "media.apple_music_play"
    ]
    assert named_query[0]["input"] == {"query": "超时空辉夜姬"}


def test_background_safe_apple_music_play_routes_tool_native_without_cua_support() -> None:
    request = daily_desktop_entrypoint_requests(
        "用 Apple Music 播放超时空辉夜姬"
    )[0]

    route = _route(request)

    assert request["tool"] == "media.apple_music_play"
    assert route["selected_provider_kind"] == "process"
    assert route["status"] == "ready"
    assert route["can_execute"] is True
    assert route["blocking_conditions"] == []


def test_daily_policy_routes_explicit_apple_music_control_through_structured_runtime() -> None:
    tool_name = "media.apple_music_control"

    route = desktop_execution_route_decision(
        tool_name,
        policy=daily_entrypoint_desktop_execution_policy(surface="chat"),
        execution_mode=desktop_tool_execution_mode_for_input(tool_name, {}),
        metadata={"sandbox_provider": _primitive_background_provider()},
    )

    assert route["selected_provider_kind"] == "process"
    assert route["status"] == "ready"
    assert route["can_execute"] is True
    assert route["blocking_conditions"] == []


def test_daily_policy_without_media_permission_keeps_apple_music_control_fail_closed() -> None:
    tool_name = "media.apple_music_control"
    policy = daily_entrypoint_desktop_execution_policy(surface="chat")
    policy["allow_media_control"] = False

    route = desktop_execution_route_decision(
        tool_name,
        policy=policy,
        execution_mode=desktop_tool_execution_mode_for_input(tool_name, {}),
        metadata={"sandbox_provider": _primitive_background_provider()},
    )

    assert route["selected_provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert route["can_execute"] is False
    assert route["fallback_mode"] == "user_handoff"


@pytest.mark.parametrize(
    "prompt",
    [
        "播放 Apple Music",
        "播放某首歌",
    ],
    ids=("simple-apple-music", "generic-track"),
)
def test_primitive_background_provider_blocks_uncompiled_media_action(
    prompt: str,
) -> None:
    requests = daily_desktop_entrypoint_requests(prompt)
    media_requests = [
        request for request in requests if request.get("tool") in _MEDIA_ACTION_TOOLS
    ]
    assert media_requests, "Playback plans need an explicit media action or composite."

    for request in media_requests:
        route = _route(request)
        # A primitive-only background driver cannot execute a semantic playback
        # tool directly. It must remain on the background lane and fail closed;
        # a later compiler may instead replace this request with a trusted
        # background composite before route selection.
        assert route["selected_provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
        assert route["selected_provider_id"] == "cua-driver"
        assert route["can_execute"] is False
        assert route["can_auto_start"] is False
        assert route["fallback_mode"] == "user_handoff"
        assert route["blocking_conditions"]


@pytest.mark.parametrize("tool_name", _MEDIA_TOOLS_WITH_FOREGROUND_FALLBACKS)
def test_daily_background_policy_never_bypasses_provider_for_media_fallbacks(
    tool_name: str,
) -> None:
    route = desktop_execution_route_decision(
        tool_name,
        policy=daily_entrypoint_desktop_execution_policy(surface="chat"),
        execution_mode=desktop_tool_execution_mode_for_input(tool_name, {}),
        metadata={"sandbox_provider": _primitive_background_provider()},
    )

    assert route["selected_provider_kind"] == CUA_BACKGROUND_PROVIDER_KIND
    assert route["can_execute"] is False
    assert route["fallback_mode"] == "user_handoff"


def test_opening_music_without_playback_evidence_is_not_playback_success() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "step_id": "control-media-playback",
                    "tool": "media.music_app_open_and_play",
                    "input_preview": {"app_name": "Music"},
                    "requires_post_action_verification": True,
                    "result": {
                        "ok": True,
                        "action": "media.music_app_open_and_play",
                        "data": {
                            "app_name": "Music",
                            "opened": True,
                            "launch_verified": True,
                            "playback_started": False,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_verified_search_only_result_is_reported_as_partial_not_playback() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "tool": "media.apple_music_play",
                    "input_preview": {"query": "超时空辉夜姬"},
                    "result": {
                        "ok": True,
                        "action": "media.apple_music_play",
                        "data": {
                            "query": "超时空辉夜姬",
                            "status": "not_found",
                            "search_opened": True,
                            "target_app": "Music",
                            "dispatch_verified": True,
                            "foreground_verified": False,
                            "focus_changed_after_search": True,
                            "search_query_verified": True,
                            "search_result_changed_from_nonmatching_baseline": True,
                            "playback_started": False,
                            "outcome": "partial",
                            "user_action_required": True,
                        },
                    },
                },
            }
        ],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_user_action_required"
    assert outcome.desktop_observed is True


def test_background_safe_library_miss_is_reported_as_partial_not_verification_failure() -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [_background_safe_library_miss_event()],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"
    assert outcome.desktop_observed is True


def test_background_safe_library_miss_without_runtime_provenance_fails_closed() -> None:
    event = _background_safe_library_miss_event()
    result = event["payload"]["result"]
    result.pop(RUNTIME_EXECUTION_PROVENANCE_KEY)

    outcome = evaluate_main_chat_outcome({}, [event])

    assert RUNTIME_EXECUTION_PROVENANCE_KEY not in result
    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_background_partial_dedupes_in_memory_tool_call_and_aggregate_step() -> None:
    run_id = "run-background-music-aggregate"
    tool_call_id = "call-background-music-aggregate"
    tool_call = _background_safe_library_miss_event()
    tool_call["payload"].update(
        {
            "run_id": run_id,
            "plan_id": "plan-background-music",
            "step_id": "play-background-music",
            "tool_call_id": tool_call_id,
        }
    )
    aggregate = {
        "event_type": "agent.desktop.intent_completed",
        "payload": {
            "run_id": run_id,
            "plan_id": "plan-background-music",
            "step_id": "play-background-music",
            "steps": [
                {
                    "tool": "media.apple_music_play",
                    "tool_call_id": tool_call_id,
                    "step_id": "play-background-music",
                    "input_preview": {"query": "超时空辉夜姬"},
                    "result": dict(tool_call["payload"]["result"]),
                }
            ],
        },
    }

    outcome = evaluate_main_chat_outcome(
        {"run_id": run_id, "status": "completed"},
        [tool_call, aggregate],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"


def test_background_partial_dedupes_durable_completed_and_agent_tool_call() -> None:
    run_id = "run-background-music-durable"
    tool_call_id = "call-background-music-durable"
    agent_tool_call = _background_safe_library_miss_event()
    agent_tool_call["payload"].update(
        {
            "run_id": run_id,
            "step_id": "play-background-music",
            "tool_call_id": tool_call_id,
        }
    )
    durable_completed = {
        "event_type": "tool.completed",
        "payload": {
            "run_id": run_id,
            "step_id": "play-background-music",
            "tool_call_id": tool_call_id,
            "tool": "media.apple_music_play",
            "input_preview": {"query": "超时空辉夜姬"},
            "status": "completed",
            "result": dict(agent_tool_call["payload"]["result"]),
        },
    }

    outcome = evaluate_main_chat_outcome(
        {"run_id": run_id, "status": "completed"},
        [durable_completed, agent_tool_call],
    )

    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"


def test_background_partial_does_not_hide_another_unverified_media_action() -> None:
    run_id = "run-background-music-with-unverified-action"
    partial = _background_safe_library_miss_event()
    partial["payload"].update(
        {
            "run_id": run_id,
            "step_id": "search-missing-track",
            "tool_call_id": "call-missing-track",
        }
    )
    unrelated_action = {
        "event_type": "agent.tool.call",
        "payload": {
            "run_id": run_id,
            "step_id": "play-another-track",
            "tool_call_id": "call-another-track",
            "source_tool_call_id": "call-missing-track",
            "tool": "media.apple_music_play",
            "input_preview": {"query": "Another Track"},
            "result": {
                "ok": True,
                "action": "media.apple_music_play",
                "data": {
                    "query": "Another Track",
                    "playback_started": False,
                },
            },
        },
    }

    outcome = evaluate_main_chat_outcome(
        {"run_id": run_id, "status": "completed"},
        [partial, unrelated_action],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_background_partial_does_not_hide_action_reusing_primary_identity() -> None:
    run_id = "run-background-music-reused-primary-id"
    tool_call_id = "call-reused-by-another-action"
    partial = _background_safe_library_miss_event()
    partial["payload"].update(
        {
            "run_id": run_id,
            "step_id": "search-missing-track",
            "tool_call_id": tool_call_id,
        }
    )
    unrelated_action = {
        "event_type": "agent.tool.call",
        "payload": {
            "run_id": run_id,
            "step_id": "play-another-track",
            "tool_call_id": tool_call_id,
            "tool": "media.apple_music_play",
            "input_preview": {"query": "Another Track"},
            "result": {
                "ok": True,
                "action": "media.apple_music_play",
                "data": {
                    "query": "Another Track",
                    "playback_started": False,
                },
            },
        },
    }

    outcome = evaluate_main_chat_outcome(
        {"run_id": run_id, "status": "completed"},
        [partial, unrelated_action],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_background_partial_does_not_hide_untrusted_matching_action() -> None:
    run_id = "run-background-music-untrusted-matching-action"
    tool_call_id = "call-reused-with-matching-input"
    partial = _background_safe_library_miss_event()
    partial["payload"].update(
        {
            "run_id": run_id,
            "step_id": "search-missing-track",
            "tool_call_id": tool_call_id,
        }
    )
    unrelated_action = {
        "event_type": "agent.tool.call",
        "payload": {
            "run_id": run_id,
            "step_id": "retry-missing-track",
            "tool_call_id": tool_call_id,
            "tool": "media.apple_music_play",
            "input_preview": {"query": "超时空辉夜姬"},
            "result": {
                "ok": True,
                "action": "media.apple_music_play",
                "data": {
                    "query": "超时空辉夜姬",
                    "playback_started": False,
                },
            },
        },
    }

    outcome = evaluate_main_chat_outcome(
        {"run_id": run_id, "status": "completed"},
        [partial, unrelated_action],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_background_partial_without_primary_identity_does_not_dedupe_mirror() -> None:
    first = _background_safe_library_miss_event()
    second = _background_safe_library_miss_event()

    outcome = evaluate_main_chat_outcome(
        {"status": "completed"},
        [first, second],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_background_partial_ignores_provider_reported_receipt_identity() -> None:
    run_id = "run-background-music-provider-receipt-id"
    partial = _background_safe_library_miss_event()
    partial["payload"].update(
        {
            "run_id": run_id,
            "tool_call_id": "call-trusted-partial",
        }
    )
    unrelated_action = {
        "event_type": "agent.tool.call",
        "payload": {
            "run_id": run_id,
            "tool": "media.apple_music_play",
            "result": {
                "ok": True,
                "tool_call_id": "call-trusted-partial",
                "data": {"playback_started": False},
            },
        },
    }

    outcome = evaluate_main_chat_outcome(
        {"run_id": run_id, "status": "completed"},
        [partial, unrelated_action],
    )

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


_INVALID_BACKGROUND_LIBRARY_EVIDENCE = {
    "status": "played",
    "background_safe": False,
    "library_search_completed": False,
    "foreground_action_taken": True,
    "target_app": "Spotify",
    "search_opened": True,
    "playback_started": True,
    "outcome": "completed",
    "user_action_required": True,
}


@pytest.mark.parametrize("field", tuple(_INVALID_BACKGROUND_LIBRARY_EVIDENCE))
@pytest.mark.parametrize("missing", [True, False], ids=("missing", "invalid"))
def test_background_safe_library_miss_requires_every_strict_evidence_field(
    field: str,
    missing: bool,
) -> None:
    event = _background_safe_library_miss_event(
        remove_data=(field,) if missing else (),
        data_overrides=(
            {}
            if missing
            else {field: _INVALID_BACKGROUND_LIBRARY_EVIDENCE[field]}
        ),
    )

    outcome = evaluate_main_chat_outcome({}, [event])

    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


@pytest.mark.parametrize(
    "result_overrides",
    [
        {"ok": False},
        {"error": "library search failed"},
        {"permission_error": True},
        {"blocking_condition": "automation_unavailable"},
    ],
    ids=("not-ok", "error", "permission", "blocker"),
)
def test_background_safe_library_miss_rejects_failure_or_permission_receipts(
    result_overrides: dict[str, Any],
) -> None:
    outcome = evaluate_main_chat_outcome(
        {},
        [
            _background_safe_library_miss_event(
                result_overrides=result_overrides,
            )
        ],
    )

    assert outcome.kind == "failed"
    assert outcome.reason != "partial_background_library_not_found"
