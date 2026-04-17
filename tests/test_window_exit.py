"""Main window exit behavior tests."""

from apps.shell import chat_window, window as window_mod
from apps.shell.window import _STATUS_HTML


class FakeEvent:
    def __init__(self):
        self.handler = None

    def __iadd__(self, handler):
        self.handler = handler
        return self


class FakeEvents:
    def __init__(self):
        self.closing = FakeEvent()


class FakeWindow:
    def __init__(self):
        self.destroyed = False
        self.events = FakeEvents()

    def destroy(self):
        self.destroyed = True


class FakeWebview:
    def __init__(self, windows):
        self.windows = windows


def test_main_window_native_close_closes_auxiliary_windows_without_dialog(monkeypatch):
    main = FakeWindow()
    aux = FakeWindow()
    closed_chat = []

    monkeypatch.setattr(chat_window, "close_chat_window", lambda: closed_chat.append(True))
    monkeypatch.setattr(window_mod, "webview", FakeWebview([main, aux]), raising=False)

    handler = window_mod._bind_main_window_exit(main)

    assert handler() is True
    assert closed_chat == [True]
    assert aux.destroyed is True
    assert main.destroyed is False


def test_request_app_exit_prepares_exit_without_destroying_current_window(monkeypatch):
    main = FakeWindow()
    aux = FakeWindow()
    closed_chat = []

    monkeypatch.setattr(chat_window, "close_chat_window", lambda: closed_chat.append(True))
    monkeypatch.setattr(window_mod, "webview", FakeWebview([main, aux]), raising=False)

    window_mod.request_app_exit()

    assert closed_chat == [True]
    assert main.destroyed is False
    assert aux.destroyed is False


def test_quit_button_closes_window_after_api_returns():
    assert "await window.pywebview.api.quit_app()" in _STATUS_HTML
    assert "setTimeout(function() { window.close(); }, 0)" in _STATUS_HTML


def test_close_chat_window_destroys_existing_window(monkeypatch):
    win = FakeWindow()

    monkeypatch.setattr(chat_window, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(chat_window, "_chat_window", win)

    assert chat_window.close_chat_window() is True
    assert win.destroyed is True
    assert chat_window._chat_window is None
