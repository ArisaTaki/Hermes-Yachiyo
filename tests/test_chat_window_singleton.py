"""Chat Window singleton state tests."""

from __future__ import annotations

import apps.shell.chat_window as chat_window
from apps.core.chat_session import ChatSession
from apps.core.state import AppState


class _EventHookStub:
    def __init__(self) -> None:
        self.handler = None
        self._is_set = False

    def __iadd__(self, handler):
        self.handler = handler
        return self

    def is_set(self) -> bool:
        return self._is_set

    def fire(self) -> None:
        self._is_set = True
        if self.handler is not None:
            self.handler()


class _EventsStub:
    def __init__(self) -> None:
        self.closed = _EventHookStub()


class _WindowStub:
    def __init__(self) -> None:
        self.closed = False
        self.destroyed = False
        self.show_calls = 0
        self.destroy_calls = 0
        self.on_top = False
        self.events = _EventsStub()

    def show(self) -> None:
        self.show_calls += 1

    def destroy(self) -> None:
        self.destroy_calls += 1
        self.destroyed = True


class _WebviewStub:
    def __init__(self) -> None:
        self.create_calls = 0
        self.windows: list[_WindowStub] = []

    def create_window(self, **_kwargs):
        self.create_calls += 1
        window = _WindowStub()
        self.windows.append(window)
        return window


class _RuntimeStub:
    def __init__(self) -> None:
        self.state = AppState()
        self.chat_session = ChatSession(session_id="s1")
        self.task_runner = None

    def cancel_task_runner_task(self, _task_id: str) -> bool:
        return True


def _patch_webview(monkeypatch) -> _WebviewStub:
    webview = _WebviewStub()
    monkeypatch.setattr(chat_window, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(chat_window, "webview", webview, raising=False)
    monkeypatch.setattr(chat_window, "_chat_window", None)
    return webview


def test_chat_window_recreates_after_closed_flag(monkeypatch):
    webview = _patch_webview(monkeypatch)
    runtime = _RuntimeStub()

    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 1
    first = webview.windows[0]
    first.closed = True

    assert chat_window.is_chat_window_open() is False
    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 2


def test_chat_window_reuses_live_window_and_clears_on_closed_event(monkeypatch):
    webview = _patch_webview(monkeypatch)
    runtime = _RuntimeStub()

    assert chat_window.open_chat_window(runtime) is True
    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 1
    assert webview.windows[0].show_calls == 1

    webview.windows[0].events.closed.fire()
    assert chat_window.is_chat_window_open() is False


def test_toggle_after_close_does_not_reopen_until_click(monkeypatch):
    webview = _patch_webview(monkeypatch)
    runtime = _RuntimeStub()

    assert chat_window.open_chat_window(runtime) is True
    assert chat_window.close_chat_window() is True
    assert webview.windows[0].destroy_calls == 1
    assert chat_window.is_chat_window_open() is False

    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 2


def test_close_stale_window_is_noop(monkeypatch):
    _patch_webview(monkeypatch)
    stale = _WindowStub()
    stale.closed = True
    monkeypatch.setattr(chat_window, "_chat_window", stale)

    assert chat_window.close_chat_window() is False
    assert stale.destroy_calls == 0
    assert chat_window.is_chat_window_open() is False
