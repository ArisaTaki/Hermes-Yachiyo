"""Chat window frontend contract checks."""

from apps.shell.chat_window import _CHAT_HTML


def test_chat_window_renders_messages_as_markdown():
    assert "function renderMarkdown(text)" in _CHAT_HTML
    assert "renderMarkdown(state.shown)" in _CHAT_HTML
    assert 'class="content markdown"' in _CHAT_HTML
    assert ".markdown h2" in _CHAT_HTML
    assert ".markdown pre" in _CHAT_HTML


def test_chat_window_scroll_following_respects_user_position():
    assert "SCROLL_BOTTOM_THRESHOLD" in _CHAT_HTML
    assert "bindMessageScroll()" in _CHAT_HTML
    assert "stickToBottom = isNearBottom(container)" in _CHAT_HTML
    assert "if (shouldScroll) {" in _CHAT_HTML
    assert "if (container && shouldAutoScroll(container)) scrollToBottom(container)" in _CHAT_HTML
