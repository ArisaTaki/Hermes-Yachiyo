"""Chat window frontend contract checks."""

from apps.core.chat_session import ChatSession
from apps.core.chat_store import ChatStore
import apps.core.chat_store as _store_mod
from apps.shell.chat_window import ChatWindowAPI, _CHAT_HTML


class _RuntimeStub:
    def __init__(self, chat_session):
        self.chat_session = chat_session
        self.task_runner = None


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


def test_chat_window_messages_are_selectable_and_copyable():
    assert "user-select: text" in _CHAT_HTML
    assert "-webkit-user-select: text" in _CHAT_HTML
    assert "const messageContentById = new Map()" in _CHAT_HTML
    assert "function copyMessage(id)" in _CHAT_HTML
    assert "function copyIconSvg()" in _CHAT_HTML
    assert "function checkIconSvg()" in _CHAT_HTML
    assert "setCopyFeedback(id)" in _CHAT_HTML
    assert "data-copy-message-id" in _CHAT_HTML
    assert "function bindMessageActions()" in _CHAT_HTML
    assert "container.addEventListener('pointerdown', stopButtonSelection);" in _CHAT_HTML
    assert "button.getAttribute('data-copy-message-id')" in _CHAT_HTML
    assert "onclick=\"copyMessage" not in _CHAT_HTML
    assert "window.pywebview.api.copy_text(text)" in _CHAT_HTML
    assert "navigator.clipboard.writeText(text)" in _CHAT_HTML
    assert "document.execCommand('copy')" in _CHAT_HTML
    assert "const title = copied ? '已复制' : '复制内容';" in _CHAT_HTML


def test_chat_window_reedit_control_removed():
    assert "function editMessage" not in _CHAT_HTML
    assert "重新编辑" not in _CHAT_HTML
    assert "重编" not in _CHAT_HTML


def test_chat_window_api_copy_text_uses_clipboard_backend(monkeypatch):
    copied: list[str] = []

    monkeypatch.setattr(
        "apps.shell.chat_window._copy_text_to_clipboard",
        lambda text: copied.append(text),
    )

    result = ChatWindowAPI(_RuntimeStub(ChatSession())).copy_text("hello")

    assert result == {"ok": True}
    assert copied == ["hello"]


def test_chat_window_api_copy_text_rejects_empty_text():
    result = ChatWindowAPI(_RuntimeStub(ChatSession())).copy_text("")

    assert result["ok"] is False
    assert "没有可复制内容" in result["error"]


def test_list_sessions_includes_current_empty_session(tmp_path, monkeypatch):
    store = ChatStore(db_path=str(tmp_path / "chat.db"))
    try:
        current = ChatSession(session_id="current-empty")
        current.attach_store(store, load_existing=False)

        history = ChatSession(session_id="history")
        history.attach_store(store, load_existing=False)
        history.add_user_message("历史会话")

        monkeypatch.setattr(_store_mod, "get_chat_store", lambda: store)

        result = ChatWindowAPI(_RuntimeStub(current)).list_sessions()

        assert result["ok"] is True
        assert result["current_session_id"] == "current-empty"
        session_ids = [item["session_id"] for item in result["sessions"]]
        assert "current-empty" in session_ids
        assert "history" in session_ids

        current_item = next(
            item for item in result["sessions"]
            if item["session_id"] == "current-empty"
        )
        assert current_item["title"] == "新对话"
        assert current_item["message_count"] == 0
    finally:
        store.close()
