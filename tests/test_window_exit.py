"""Main window exit behavior tests."""

from apps.shell import chat_window, window as window_mod


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
    def __init__(self, confirm_result=True):
        self.confirm_result = confirm_result
        self.dialog_calls = []
        self.destroyed = False
        self.events = FakeEvents()

    def create_confirmation_dialog(self, title, message):
        self.dialog_calls.append((title, message))
        return self.confirm_result

    def destroy(self):
        self.destroyed = True


class FakeWebview:
    def __init__(self, windows):
        self.windows = windows


def test_main_window_close_cancel_keeps_auxiliary_windows(monkeypatch):
    main = FakeWindow(confirm_result=False)
    aux = FakeWindow()
    closed_chat = []

    monkeypatch.setattr(chat_window, "close_chat_window", lambda: closed_chat.append(True))
    monkeypatch.setattr(window_mod, "webview", FakeWebview([main, aux]), raising=False)

    handler = window_mod._bind_main_window_exit(main)

    assert main.events.closing.handler is handler
    assert handler() is False
    assert closed_chat == []
    assert aux.destroyed is False
    assert main.dialog_calls == [
        (window_mod._EXIT_DIALOG_TITLE, window_mod._EXIT_DIALOG_MESSAGE)
    ]


def test_main_window_close_confirm_closes_auxiliary_windows(monkeypatch):
    main = FakeWindow(confirm_result=True)
    aux = FakeWindow()
    closed_chat = []

    monkeypatch.setattr(chat_window, "close_chat_window", lambda: closed_chat.append(True))
    monkeypatch.setattr(window_mod, "webview", FakeWebview([main, aux]), raising=False)

    handler = window_mod._bind_main_window_exit(main)

    assert handler() is True
    assert closed_chat == [True]
    assert aux.destroyed is True
    assert main.destroyed is False


def test_close_chat_window_destroys_existing_window(monkeypatch):
    win = FakeWindow()

    monkeypatch.setattr(chat_window, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(chat_window, "_chat_window", win)

    assert chat_window.close_chat_window() is True
    assert win.destroyed is True
    assert chat_window._chat_window is None
