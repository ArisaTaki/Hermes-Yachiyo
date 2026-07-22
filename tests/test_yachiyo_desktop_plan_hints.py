"""Focused tests for deterministic desktop plan hint selection."""

from __future__ import annotations

import pytest

from apps.shell.yachiyo_agent.desktop_plan_hints import (
    media_action_hint,
    media_query_hint,
    media_tool_preview,
    screen_capture_hint,
    standalone_safe_type_text_hint,
)


@pytest.mark.parametrize("action", ["pause", "next", "previous"])
def test_explicit_apple_music_control_prefers_apple_specific_tool(action: str) -> None:
    tool_name, payload = media_tool_preview(
        {"action": action, "app_name": "Music"},
        {
            "media.apple_music_control",
            "media.music_app_control",
            "media.system_control",
        },
    )

    assert tool_name == "media.apple_music_control"
    assert payload == {"action": action}


def test_explicit_apple_music_play_control_prefers_apple_specific_tool() -> None:
    tool_name, payload = media_tool_preview(
        {
            "action": "play",
            "app_name": "Music",
            "control_only": "true",
        },
        {
            "media.apple_music_control",
            "media.music_app_control",
            "media.system_control",
        },
    )

    assert tool_name == "media.apple_music_control"
    assert payload == {"action": "play"}


def test_explicit_apple_music_query_prefers_query_capable_tool() -> None:
    tool_name, payload = media_tool_preview(
        {
            "action": "play",
            "app_name": "Music",
            "query": "超时空辉夜姬",
        },
        {
            "media.apple_music_play",
            "media.music_app_open_and_play",
        },
    )

    assert tool_name == "media.apple_music_play"
    assert payload == {"query": "超时空辉夜姬"}


def test_explicit_apple_music_query_is_not_dropped_into_generic_play() -> None:
    tool_name, payload = media_tool_preview(
        {
            "action": "play",
            "app_name": "Music",
            "query": "超时空辉夜姬",
        },
        {"media.music_app_open_and_play"},
    )

    assert tool_name is None
    assert payload == {}


def test_media_capability_discovery_handles_unrestricted_tool_catalog() -> None:
    tool_name, payload = media_tool_preview(
        {
            "action": "play",
            "target_app_capability_hint": {
                "query": "music",
                "description": "音乐播放器",
            },
        },
        None,
    )

    assert tool_name is None
    assert payload == {}


def test_media_query_hint_keeps_quoted_title_before_completion_constraints() -> None:
    prompt = (
        "帮我打开 Apple Music，搜索“超时空辉夜姬”相关的音乐；"
        "尽量在后台完成，不要抢占鼠标键盘。"
        "如果只能打开搜索而不能播放，请如实说明完成到了哪一步。"
    )

    assert media_query_hint(prompt) == "超时空辉夜姬"


def test_media_query_hint_ignores_conditional_search_playback_explanation() -> None:
    assert media_query_hint("如果只能打开搜索而不能播放，请如实说明") == ""


def test_media_query_hint_preserves_negated_words_inside_quoted_title() -> None:
    assert media_query_hint("搜索“不能说的秘密”") == "不能说的秘密"


@pytest.mark.parametrize(
    "prompt",
    [
        "你能不能播放周杰伦",
        "能不能帮我播放周杰伦",
        "如果可以的话播放周杰伦",
    ],
)
def test_media_query_hint_removes_conversational_playback_scaffolding(
    prompt: str,
) -> None:
    assert media_query_hint(prompt) == "周杰伦"


def test_media_query_hint_rejects_conditional_capability_explanation_with_title() -> None:
    prompt = "如果只能在 Apple Music 搜索“周杰伦”而不能播放，请如实说明"

    assert media_query_hint(prompt) == ""


def test_media_query_hint_preserves_english_title_with_an_apostrophe() -> None:
    assert media_query_hint("play 'Don't Stop Me Now'") == "Don't Stop Me Now"


def test_media_query_hint_stops_at_first_complete_ascii_quoted_title() -> None:
    assert media_query_hint("play 'first' then play 'second'") == "first"


@pytest.mark.parametrize(
    "prompt",
    [
        "搜索 Apple Music 里的“周杰伦”并播放",
        "播放名为“周杰伦”的歌曲",
    ],
)
def test_media_query_hint_accepts_common_quoted_title_scaffolding(prompt: str) -> None:
    assert media_query_hint(prompt) == "周杰伦"


@pytest.mark.parametrize("prompt", ['play "music"', "播放“音乐”"])
def test_media_query_hint_rejects_quoted_generic_media_nouns(prompt: str) -> None:
    assert media_query_hint(prompt) == ""


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("帮我打 hello", "hello"),
        ("打字 hello", "hello"),
        ("请输入：hello world", "hello world"),
        ("type hello", "hello"),
        ("在当前界面输入 hello", "hello"),
        ("在当前输入框输入文本 hello", "hello"),
        ("type hello in current input", "hello"),
        ("type hello into the foreground text box", "hello"),
    ],
)
def test_standalone_safe_type_text_requires_explicit_whole_utterance(
    prompt: str,
    expected: str,
) -> None:
    assert standalone_safe_type_text_hint(prompt) == expected


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("在 Notes 里输入：“hello”", "hello"),
        ("在 Notes 里输入：hello", "hello"),
        ("打开 Notes 写：“一首诗”", "一首诗"),
        ("Open Notes and type: hello", "hello"),
    ],
)
def test_safe_type_text_strips_explicit_literal_delimiters(
    prompt: str,
    expected: str,
) -> None:
    from apps.shell.yachiyo_agent.desktop_plan_hints import safe_type_text_hint

    assert safe_type_text_hint(prompt) == expected


@pytest.mark.parametrize(
    "prompt",
    [
        "帮我打一个代码报告",
        "输入数据生成报告",
        "帮我打电话给 Alice",
        "点击输入按钮",
        "打字 hello，然后点击发送按钮",
        "把剪贴板内容输入当前应用",
        "create a report",
        "click the input button",
    ],
)
def test_standalone_safe_type_text_rejects_other_task_semantics(prompt: str) -> None:
    assert standalone_safe_type_text_hint(prompt) == ""


@pytest.mark.parametrize("prompt", ["Music next", "Music skip", "Apple Music next", "Apple Music skip"])
def test_media_action_hint_recognizes_app_scoped_english_next(prompt: str) -> None:
    assert media_action_hint(prompt) == "next"


def test_media_action_hint_does_not_broaden_generic_next_navigation() -> None:
    assert media_action_hint("Chrome next") == ""
    assert media_action_hint("open next tab") == ""


def test_media_action_hint_ignores_passive_cancellable_request_description() -> None:
    assert media_action_hint("请开始一个可以被停止的慢请求") == ""


@pytest.mark.parametrize("prompt", ["Chrome 观察一下", "Finder 查看", "PixelForge 看一下"])
def test_app_observation_phrase_routes_to_screen_capture(prompt: str) -> None:
    hint = screen_capture_hint(prompt)

    assert hint is not None
    assert hint["app_name"] in prompt


@pytest.mark.parametrize("prompt", ["观察一下", "这个项目观察一下", "这个页面看一下"])
def test_conversational_observation_phrase_is_not_treated_as_an_app_capture(prompt: str) -> None:
    assert screen_capture_hint(prompt) is None
