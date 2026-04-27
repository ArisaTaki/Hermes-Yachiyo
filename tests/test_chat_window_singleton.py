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
        self.restore_calls = 0
        self.show_calls = 0
        self.bring_to_front_calls = 0
        self.focus_calls = 0
        self.destroy_calls = 0
        self.on_top = False
        self.events = _EventsStub()

    def restore(self) -> None:
        self.restore_calls += 1

    def show(self) -> None:
        self.show_calls += 1

    def bring_to_front(self) -> None:
        self.bring_to_front_calls += 1

    def focus(self) -> None:
        self.focus_calls += 1

    def destroy(self) -> None:
        self.destroy_calls += 1
        self.destroyed = True


class _WebviewStub:
    def __init__(self) -> None:
        self.create_calls = 0
        self.windows: list[_WindowStub] = []
        self.on_create = None

    def create_window(self, **_kwargs):
        self.create_calls += 1
        if self.on_create is not None:
            self.on_create()
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
    monkeypatch.setattr(chat_window, "_chat_window_creating", False)
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
    native_focus_calls = []

    assert chat_window.open_chat_window(runtime) is True
    monkeypatch.setattr(
        chat_window,
        "_focus_native_chat_window",
        lambda window: native_focus_calls.append(window) or True,
    )
    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 1
    assert native_focus_calls == [webview.windows[0]]
    assert webview.windows[0].restore_calls == 0
    assert webview.windows[0].show_calls == 0
    assert webview.windows[0].bring_to_front_calls == 0
    assert webview.windows[0].focus_calls == 0

    webview.windows[0].events.closed.fire()
    assert chat_window.is_chat_window_open() is False


def test_chat_window_focus_failure_does_not_create_blank_duplicate(monkeypatch):
    webview = _patch_webview(monkeypatch)
    runtime = _RuntimeStub()

    assert chat_window.open_chat_window(runtime) is True
    first = webview.windows[0]
    first.focus = lambda: (_ for _ in ()).throw(RuntimeError("not ready"))

    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 1
    assert chat_window.is_chat_window_open() is True


def test_chat_window_does_not_reenter_creation(monkeypatch):
    webview = _patch_webview(monkeypatch)
    runtime = _RuntimeStub()
    monkeypatch.setattr(chat_window, "_focus_native_chat_window", lambda _window: False)

    def _reenter() -> None:
        assert chat_window.open_chat_window(runtime) is True

    webview.on_create = _reenter

    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 1
    assert chat_window.is_chat_window_open() is True


def test_chat_window_creates_when_singleton_empty_even_if_native_title_exists(monkeypatch):
    webview = _patch_webview(monkeypatch)
    runtime = _RuntimeStub()
    native_focus_calls = []
    monkeypatch.setattr(
        chat_window,
        "_focus_native_chat_window",
        lambda window: native_focus_calls.append(window) or True,
    )

    assert chat_window.open_chat_window(runtime) is True

    assert webview.create_calls == 1
    assert native_focus_calls == []
    assert chat_window.is_chat_window_open() is True


def test_stale_closed_event_does_not_clear_current_window(monkeypatch):
    webview = _patch_webview(monkeypatch)
    runtime = _RuntimeStub()
    monkeypatch.setattr(chat_window, "_focus_native_chat_window", lambda _window: False)

    assert chat_window.open_chat_window(runtime) is True
    first = webview.windows[0]
    first.closed = True

    assert chat_window.open_chat_window(runtime) is True
    assert webview.create_calls == 2
    second = webview.windows[1]

    first.events.closed.fire()

    assert chat_window._chat_window is second
    assert chat_window.is_chat_window_open() is True


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
