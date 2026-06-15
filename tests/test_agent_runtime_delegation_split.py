"""Tests for Chat delegation parsing split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.delegation import ChatRunnableMentionParser


def test_chat_runnable_mention_parser_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.ChatRunnableMentionParser is ChatRunnableMentionParser


def test_chat_runnable_mention_parser_matches_known_nickname_and_goal() -> None:
    parser = _parser()

    assert parser.parse_known("@Design 做一版视觉方向\n要求移动端优先") == (
        "Design",
        "做一版视觉方向\n要求移动端优先",
    )


def test_chat_runnable_mention_parser_prefers_long_known_names() -> None:
    parser = _parser()

    assert parser.parse_known("请 @Web Flow 跑一下流程") == ("Web Flow", "请 跑一下流程")


def test_chat_runnable_mention_parser_ignores_generic_fallback_names() -> None:
    parser = _parser()

    assert parser.parse_known("@workflow 跑一下") is None
    assert parser.parse_known("@agent 做事") is None


def test_legacy_static_chat_runnable_parser_delegates_to_split_parser() -> None:
    assert agent_runtime.NativeRunEngine.parse_chat_runnable('@"Web Flow" 跑一下') == (
        "Web Flow",
        "跑一下",
    )
    assert agent_runtime.NativeRunEngine._chat_mention_goal(
        "请",
        "继续",
        ["第二行"],
    ) == ChatRunnableMentionParser.mention_goal("请", "继续", ["第二行"])


def _parser() -> ChatRunnableMentionParser:
    return ChatRunnableMentionParser(
        list_runnables=lambda: [
            {"name": "Design Agent", "nickname": "Design"},
            {"name": "Web Flow", "nickname": ""},
        ]
    )
