"""Shared daily desktop runtime helper tests."""

from __future__ import annotations

from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_direct_metadata_request,
    daily_desktop_entrypoint_requests,
    daily_desktop_planned_timeline,
    daily_desktop_recovery_execution_prompt,
    daily_desktop_user_metadata,
)


def test_daily_desktop_entrypoint_requests_project_shared_metadata_and_timeline() -> None:
    requests = daily_desktop_entrypoint_requests("可以帮我打开 Word 吗")

    assert requests == [
        {
            "protocol": "json_fallback",
            "tool": "app.open",
            "input": {"app_name": "Microsoft Word"},
        }
    ]
    assert daily_desktop_user_metadata(requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_intent",
        "daily_desktop_planning_reason": "clear_daily_desktop_intent",
        "daily_desktop_tool": "app.open",
        "daily_desktop_tools": ["app.open"],
    }
    assert daily_desktop_planned_timeline(requests=requests) == [
        {
            "event": "agent.desktop.intent_planned",
            "detail": "app.open",
            "tool": "app.open",
            "status": "planned",
            "source": "daily_desktop_intent",
            "planning_reason": "clear_daily_desktop_intent",
            "input_preview": {"app_name": "Microsoft Word"},
        }
    ]


def test_daily_desktop_entrypoint_routes_polite_app_open_questions_to_desktop_tool() -> None:
    cases = (
        ("你能帮我打开微信吗", "WeChat"),
        ("你能启动一下备忘录吗", "Notes"),
        ("Could you launch Calendar for me?", "Calendar"),
        ("Would you open Notes please?", "Notes"),
    )

    for prompt, app_name in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": "app.open",
                "input": {"app_name": app_name},
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == "app.open"


def test_daily_desktop_entrypoint_routes_polite_focus_and_show_questions_to_desktop_tools() -> None:
    cases = (
        ("你能帮我切到Chrome吗", "app.focus", {"app_name": "Google Chrome"}),
        ("你可以帮我聚焦Chrome吗", "app.focus", {"app_name": "Google Chrome"}),
        ("你能帮我显示Finder吗", "app.show", {"app_name": "Finder"}),
        ("你能帮我还原微信吗", "app.show", {"app_name": "WeChat"}),
    )

    for prompt, tool_name, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests)["daily_desktop_tool"] == tool_name


def test_daily_desktop_entrypoint_routes_music_app_playback_questions_to_desktop_tools() -> None:
    cases = (
        ("打开网易云并播放", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
        ("可以帮我打开网易云并播放吗", "media.music_app_open_and_play", {"app_name": "网易云音乐"}),
        ("Could you launch Spotify and play music?", "media.music_app_open_and_play", {"app_name": "Spotify"}),
        ("能帮我播放 Apple Music 吗", "media.apple_music_open_and_play", {}),
    )

    for prompt, tool_name, tool_input in cases:
        requests = daily_desktop_entrypoint_requests(prompt)

        assert requests == [
            {
                "protocol": "json_fallback",
                "tool": tool_name,
                "input": tool_input,
            }
        ]
        assert daily_desktop_user_metadata(requests) == {
            "daily_desktop_intent": True,
            "daily_desktop_source": "daily_desktop_intent",
            "daily_desktop_planning_reason": "clear_daily_desktop_intent",
            "daily_desktop_tool": tool_name,
            "daily_desktop_tools": [tool_name],
        }


def test_daily_desktop_structured_recovery_metadata_projects_exact_low_risk_request() -> None:
    metadata = {
        "desktop_permission_recovery": True,
        "recovery_tool": "system.settings_open",
        "recovery_input": {"target": "屏幕录制权限"},
        "recovery_permission_target": "screen_recording",
        "recovery_risk_level": "low",
    }

    direct_request = daily_desktop_direct_metadata_request(
        metadata,
        allowed_tools=["system.settings_open"],
    )
    requests = daily_desktop_entrypoint_requests(
        "修复屏幕录制",
        metadata=metadata,
        allowed_tools=["system.settings_open"],
    )

    assert requests == [direct_request]
    assert requests[0] == {
        "protocol": "json_fallback",
        "tool": "system.settings_open",
        "input": {"target": "屏幕录制权限"},
        "source": "daily_desktop_metadata",
        "planning_reason": "structured_recovery_metadata",
    }
    assert daily_desktop_user_metadata(requests) == {
        "daily_desktop_intent": True,
        "daily_desktop_source": "daily_desktop_metadata",
        "daily_desktop_planning_reason": "structured_recovery_metadata",
        "daily_desktop_tool": "system.settings_open",
        "daily_desktop_tools": ["system.settings_open"],
    }
    assert daily_desktop_planned_timeline(
        "修复屏幕录制",
        metadata=metadata,
        allowed_tools=["system.settings_open"],
    ) == [
        {
            "event": "agent.desktop.intent_planned",
            "detail": "system.settings_open",
            "tool": "system.settings_open",
            "status": "planned",
            "source": "daily_desktop_metadata",
            "planning_reason": "structured_recovery_metadata",
            "input_preview": {"target": "屏幕录制权限"},
        }
    ]
    assert "屏幕录制权限" in daily_desktop_recovery_execution_prompt("修复屏幕录制", metadata)
