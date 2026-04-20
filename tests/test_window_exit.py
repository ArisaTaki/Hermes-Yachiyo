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


class FakeTimer:
    instances = []

    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.daemon = False
        self.started = False
        FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def is_alive(self):
        return False


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
    FakeTimer.instances = []

    monkeypatch.setattr(chat_window, "close_chat_window", lambda: closed_chat.append(True))
    monkeypatch.setattr(window_mod, "webview", FakeWebview([main, aux]), raising=False)
    monkeypatch.setattr(window_mod.threading, "Timer", FakeTimer)
    monkeypatch.setattr(window_mod, "_exit_timer", None)

    window_mod.request_app_exit()

    assert len(FakeTimer.instances) == 1
    assert FakeTimer.instances[0].interval == window_mod._EXIT_DELAY_SECONDS
    assert FakeTimer.instances[0].started is True
    assert FakeTimer.instances[0].daemon is True
    assert closed_chat == []
    assert main.destroyed is False
    assert aux.destroyed is False

    FakeTimer.instances[0].callback()

    assert closed_chat == [True]
    assert main.destroyed is True
    assert aux.destroyed is True


def test_quit_button_uses_in_page_dialog_and_api_exit():
    assert "class=\"exit-dialog-backdrop\"" in _STATUS_HTML
    assert "function quitApp()" in _STATUS_HTML
    assert "async function confirmQuitApp()" in _STATUS_HTML
    assert "await window.pywebview.api.quit_app()" in _STATUS_HTML
    assert "confirm('退出会关闭主界面" not in _STATUS_HTML


def test_close_chat_window_destroys_existing_window(monkeypatch):
    win = FakeWindow()

    monkeypatch.setattr(chat_window, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(chat_window, "_chat_window", win)

    assert chat_window.close_chat_window() is True
    assert win.destroyed is True
    assert chat_window._chat_window is None
