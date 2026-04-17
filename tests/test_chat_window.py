"""Chat window frontend contract checks."""

from apps.shell.chat_window import _CHAT_HTML


def test_chat_window_renders_messages_as_markdown():
    assert "function renderMarkdown(text)" in _CHAT_HTML
    assert "renderMarkdown(state.shown)" in _CHAT_HTML
    assert 'class="content markdown"' in _CHAT_HTML
    assert ".markdown h2" in _CHAT_HTML
    assert ".markdown pre" in _CHAT_HTML


def test_chat_window_markdown_links_use_url_protocol_whitelist():
    assert "function sanitizeMarkdownUrl(url)" in _CHAT_HTML
    assert "const parsed = new URL(value);" in _CHAT_HTML
    assert "parsed.protocol === 'http:'" in _CHAT_HTML
    assert "parsed.protocol === 'https:'" in _CHAT_HTML
    assert "parsed.protocol === 'mailto:'" in _CHAT_HTML
    assert ".replace(/&amp;/g, '&')" not in _CHAT_HTML


def test_chat_window_scroll_following_respects_user_position():
    assert "SCROLL_BOTTOM_THRESHOLD" in _CHAT_HTML
    assert "bindMessageScroll()" in _CHAT_HTML
    assert "if (event.deltaY < 0) stickToBottom = false" in _CHAT_HTML
    assert "if (currentTop < lastMessageScrollTop)" in _CHAT_HTML
    assert "return stickToBottom;" in _CHAT_HTML
    assert "if (shouldScroll) {" in _CHAT_HTML
    assert "if (container && shouldAutoScroll(container)) scrollToBottom(container)" in _CHAT_HTML
