"""Main window exit behavior tests."""

import sys
import types

import apps.shell.main_api as main_api_mod
from apps.shell import chat_window
from apps.shell import window as window_mod
from apps.shell.modes.bubble import BubbleWindowAPI
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
        self.closed = FakeEvent()


class FakeWindow:
    def __init__(self):
        self.destroyed = False
        self.shown = 0
        self.events = FakeEvents()

    def destroy(self):
        self.destroyed = True

    def show(self):
        self.shown += 1


class FakeWebview:
    def __init__(self, windows):
        self.windows = windows


class FakeTimer:
    instances: list["FakeTimer"] = []

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
    monkeypatch.setattr(window_mod, "_force_exit_timer", None)

    window_mod.request_app_exit()

    assert len(FakeTimer.instances) == 2
    assert FakeTimer.instances[0].interval == window_mod._EXIT_DELAY_SECONDS
    assert FakeTimer.instances[0].started is True
    assert FakeTimer.instances[0].daemon is True
    assert FakeTimer.instances[1].interval == window_mod._EXIT_FORCE_DELAY_SECONDS
    assert FakeTimer.instances[1].started is True
    assert FakeTimer.instances[1].daemon is True
    assert closed_chat == []
    assert main.destroyed is False
    assert aux.destroyed is False

    FakeTimer.instances[0].callback()

    assert closed_chat == [True]
    assert main.destroyed is True
    assert aux.destroyed is True


def test_request_app_exit_force_timer_exits_process(monkeypatch):
    FakeTimer.instances = []
    exits = []

    monkeypatch.setattr(window_mod.threading, "Timer", FakeTimer)
    monkeypatch.setattr(window_mod, "_exit_timer", None)
    monkeypatch.setattr(window_mod, "_force_exit_timer", None)
    monkeypatch.setattr(window_mod, "_process_exit", lambda code=0: exits.append(code))

    window_mod.request_app_exit()
    FakeTimer.instances[1].callback()

    assert exits == [0]


def test_request_app_restart_is_delayed(monkeypatch):
    FakeTimer.instances = []

    monkeypatch.setattr(window_mod.threading, "Timer", FakeTimer)
    monkeypatch.setattr(window_mod, "_restart_timer", None)

    window_mod.request_app_restart()

    assert len(FakeTimer.instances) == 1
    assert FakeTimer.instances[0].interval == window_mod._RESTART_DELAY_SECONDS
    assert FakeTimer.instances[0].started is True
    assert FakeTimer.instances[0].daemon is True


def test_restart_process_exits_only_after_successful_spawn(monkeypatch):
    spawned = []
    exits = []

    def fake_popen(argv, close_fds, start_new_session):
        spawned.append((argv, close_fds, start_new_session))
        return object()

    monkeypatch.setitem(sys.modules, "subprocess", types.SimpleNamespace(Popen=fake_popen))
    monkeypatch.setattr(window_mod, "_process_exit", lambda code=0: exits.append(code))

    window_mod._restart_process()

    assert spawned
    assert exits == [0]


def test_restart_process_keeps_app_alive_when_spawn_fails(monkeypatch):
    exits = []

    def fake_popen(*_args, **_kwargs):
        raise OSError("spawn failed")

    monkeypatch.setitem(sys.modules, "subprocess", types.SimpleNamespace(Popen=fake_popen))
    monkeypatch.setattr(window_mod, "_process_exit", lambda code=0: exits.append(code))

    window_mod._restart_process()

    assert exits == []


def test_bubble_close_requests_full_app_exit(monkeypatch):
    requested = []
    api = BubbleWindowAPI(runtime=object(), config=object())

    monkeypatch.setattr(window_mod, "request_app_exit", lambda: requested.append(True))

    result = api.close_bubble()

    assert result == {"ok": True}
    assert requested == [True]


def test_quit_button_uses_in_page_dialog_and_api_exit():
    assert "class=\"exit-dialog-backdrop\"" in _STATUS_HTML
    assert "function quitApp()" in _STATUS_HTML
    assert "async function confirmQuitApp()" in _STATUS_HTML
    assert "await window.pywebview.api.quit_app()" in _STATUS_HTML
    assert "confirm('退出会关闭主界面" not in _STATUS_HTML


def test_control_center_html_keeps_chat_window_as_external_full_session():
    assert "打开 Chat Window" in _STATUS_HTML
    assert "id=\"chat-summary-list\"" in _STATUS_HTML
    assert "openModeSettings('bubble')" in _STATUS_HTML
    assert "id=\"s-assistant-user-address\"" in _STATUS_HTML
    assert "assistant.user_address" in _STATUS_HTML
    assert "id=\"s-assistant-persona\"" in _STATUS_HTML
    assert "assistant.persona_prompt" in _STATUS_HTML
    assert "id=\"common-settings-apply-btn\"" in _STATUS_HTML
    assert "applyPendingCommonSettings()" in _STATUS_HTML
    assert "const committedCommonSettings = {}" in _STATUS_HTML
    assert "function isCommittedCommonSettingValue(key, value)" in _STATUS_HTML
    assert "delete pendingCommonSettings[key];" in _STATUS_HTML
    assert "onDeferredSettingInput('assistant.user_address'" in _STATUS_HTML
    assert "onDeferredSettingInput('assistant.persona_prompt'" in _STATUS_HTML
    assert "onDeferredSettingInput('bridge_host'" in _STATUS_HTML
    assert "onDeferredSettingInput('bridge_port'" in _STATUS_HTML
    assert "setControlValue('s-bridge-host', 'bridge_host', d.bridge.host || '');" in _STATUS_HTML
    assert "setControlValue('s-bridge-port', 'bridge_port', d.bridge.port);" in _STATUS_HTML
    assert (
        "setControlValue('s-bridge-host', 'bridge_host', state.bridge.host || '');"
        in _STATUS_HTML
    )
    assert "setControlValue('s-bridge-port', 'bridge_port', state.bridge.port);" in _STATUS_HTML
    assert "onSettingChange('display_mode'" in _STATUS_HTML
    assert "窗口模式" not in _STATUS_HTML
    assert "id=\"msg-input\"" not in _STATUS_HTML


def test_control_center_formats_workspace_created_time_for_display():
    assert "function formatReadableDateTime(value)" in _STATUS_HTML
    assert "formatReadableDateTime(d.workspace.created_at)" in _STATUS_HTML
    assert "formatReadableDateTime(data.workspace.created_at)" in _STATUS_HTML
    assert "d.workspace.created_at || '—'" not in _STATUS_HTML
    assert "data.workspace.created_at || '—'" not in _STATUS_HTML


def test_control_center_html_exposes_hermes_diagnostics():
    assert "id=\"hermes-doctor-row\"" in _STATUS_HTML
    assert "id=\"s-hermes-doctor-row\"" in _STATUS_HTML
    assert "formatHermesDiagnostics" in _STATUS_HTML
    assert "shouldShowHermesEnhance" in _STATUS_HTML
    assert "maybeAutoRecheckHermes" in _STATUS_HTML
    assert "能力诊断尚未运行" in _STATUS_HTML
    assert "检测 / 补全 Hermes 能力" in _STATUS_HTML


def test_control_center_html_exposes_uninstall_flow():
    assert "id=\"s-backup-create-btn\"" in _STATUS_HTML
    assert "id=\"s-backup-auto-cleanup\"" in _STATUS_HTML
    assert "id=\"s-backup-retention-count\"" in _STATUS_HTML
    assert "id=\"s-backup-restore-btn\"" in _STATUS_HTML
    assert "id=\"s-backup-manage-btn\"" in _STATUS_HTML
    assert "id=\"s-backup-overwrite-btn\"" in _STATUS_HTML
    assert "id=\"s-backup-manager\"" in _STATUS_HTML
    assert "id=\"s-backup-manager-list\"" in _STATUS_HTML
    assert "get_backup_status" in _STATUS_HTML
    assert "create_backup" in _STATUS_HTML
    assert "update_backup_settings" in _STATUS_HTML
    assert "restore_backup" in _STATUS_HTML
    assert "delete_backup" in _STATUS_HTML
    assert "open_backup_location" in _STATUS_HTML
    assert "id=\"s-uninstall-scope\"" in _STATUS_HTML
    assert "value=\"yachiyo_only\"" in _STATUS_HTML
    assert "value=\"include_hermes\"" in _STATUS_HTML
    assert "id=\"s-uninstall-keep-config\"" in _STATUS_HTML
    assert "id=\"s-uninstall-preview\"" in _STATUS_HTML
    assert "id=\"uninstall-dialog\"" in _STATUS_HTML
    assert "get_uninstall_preview" in _STATUS_HTML
    assert "run_uninstall" in _STATUS_HTML
    assert "UNINSTALL" in _STATUS_HTML


def test_installer_html_exposes_backup_import():
    from apps.shell.window import _generate_installer_html
    from packages.protocol.enums import HermesInstallStatus, Platform
    from packages.protocol.install import HermesInstallInfo

    html = _generate_installer_html(
        HermesInstallInfo(
            status=HermesInstallStatus.INSTALLED_NOT_INITIALIZED,
            platform=Platform.MACOS,
        )
    )

    assert "导入备份" in html
    assert "get_backup_status" in html
    assert "import_backup" in html
    section_start = html.index("function setBackupImportStatus")
    section_end = html.index(
        "document.addEventListener('DOMContentLoaded', refreshBackupImportStatus);"
    )
    backup_import_js = html[section_start:section_end]
    assert "textContent" in backup_import_js
    assert "appendChild(document.createTextNode" in backup_import_js
    assert "innerHTML" not in backup_import_js
    assert "result.latest.display_path" in backup_import_js
    assert "result.backup_root_display" in backup_import_js
    assert "get_config_snapshot_status" not in html
    assert "import_config_snapshot" not in html


def test_close_chat_window_destroys_existing_window(monkeypatch):
    win = FakeWindow()

    monkeypatch.setattr(chat_window, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(chat_window, "_chat_window", win)

    assert chat_window.close_chat_window() is True
    assert win.destroyed is True
    assert chat_window._chat_window is None


def test_open_main_window_reuses_existing_window(monkeypatch):
    created = []

    class FakeWebviewModule:
        def create_window(self, **_kwargs):
            window = FakeWindow()
            created.append(window)
            return window

    monkeypatch.setattr(window_mod, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(window_mod, "webview", FakeWebviewModule(), raising=False)
    monkeypatch.setattr(window_mod, "_main_window", None)
    monkeypatch.setattr(window_mod, "_main_window_creating", False)
    monkeypatch.setattr(main_api_mod, "MainWindowAPI", lambda *_args, **_kwargs: object())

    runtime = object()
    config = type("Config", (), {
        "bridge_host": "127.0.0.1",
        "bridge_port": 8420,
        "window_mode": type("WindowMode", (), {"width": 960, "height": 720})(),
    })()

    assert window_mod.open_main_window(runtime, config) is True
    assert window_mod.open_main_window(runtime, config) is True
    assert len(created) == 1
    assert created[0].shown == 1


def test_open_main_window_does_not_reenter_while_creating(monkeypatch):
    created = []
    runtime = object()
    config = type("Config", (), {
        "bridge_host": "127.0.0.1",
        "bridge_port": 8420,
        "window_mode": type("WindowMode", (), {"width": 960, "height": 720})(),
    })()

    class FakeWebviewModule:
        def __init__(self):
            self.reentered = False

        def create_window(self, **_kwargs):
            if not self.reentered:
                self.reentered = True
                assert window_mod.open_main_window(runtime, config) is True
            window = FakeWindow()
            created.append(window)
            return window

    webview_stub = FakeWebviewModule()
    monkeypatch.setattr(window_mod, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(window_mod, "webview", webview_stub, raising=False)
    monkeypatch.setattr(window_mod, "_main_window", None)
    monkeypatch.setattr(window_mod, "_main_window_creating", False)
    monkeypatch.setattr(window_mod, "_focus_macos_window_by_title", lambda _title: False)
    monkeypatch.setattr(main_api_mod, "MainWindowAPI", lambda *_args, **_kwargs: object())

    assert window_mod.open_main_window(runtime, config) is True
    assert webview_stub.reentered is True
    assert len(created) == 1


def test_open_main_window_focus_fallback_failure_does_not_duplicate(monkeypatch):
    created = []

    class FocusFallbackWindow(FakeWindow):
        def __init__(self):
            super().__init__()
            self.focused = 0

        def show(self):
            raise RuntimeError("show failed")

        def focus(self):
            self.focused += 1

    class FakeWebviewModule:
        def create_window(self, **_kwargs):
            window = FocusFallbackWindow()
            created.append(window)
            return window

    monkeypatch.setattr(window_mod, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(window_mod, "webview", FakeWebviewModule(), raising=False)
    monkeypatch.setattr(window_mod, "_main_window", None)
    monkeypatch.setattr(window_mod, "_main_window_creating", False)
    monkeypatch.setattr(window_mod, "_focus_macos_window_by_title", lambda _title: False)
    monkeypatch.setattr(main_api_mod, "MainWindowAPI", lambda *_args, **_kwargs: object())

    runtime = object()
    config = type("Config", (), {
        "bridge_host": "127.0.0.1",
        "bridge_port": 8420,
        "window_mode": type("WindowMode", (), {"width": 960, "height": 720})(),
    })()

    assert window_mod.open_main_window(runtime, config) is True
    assert window_mod.open_main_window(runtime, config) is True
    assert len(created) == 1
    assert created[0].focused == 1


def test_open_main_window_recreates_after_close(monkeypatch):
    created = []

    class FakeWebviewModule:
        def create_window(self, **_kwargs):
            window = FakeWindow()
            created.append(window)
            return window

    monkeypatch.setattr(window_mod, "_HAS_WEBVIEW", True)
    monkeypatch.setattr(window_mod, "webview", FakeWebviewModule(), raising=False)
    monkeypatch.setattr(window_mod, "_main_window", None)
    monkeypatch.setattr(window_mod, "_main_window_creating", False)
    monkeypatch.setattr(main_api_mod, "MainWindowAPI", lambda *_args, **_kwargs: object())

    runtime = object()
    config = type("Config", (), {
        "bridge_host": "127.0.0.1",
        "bridge_port": 8420,
        "window_mode": type("WindowMode", (), {"width": 960, "height": 720})(),
    })()

    assert window_mod.open_main_window(runtime, config) is True
    assert created[0].events.closed.handler is not None
    created[0].events.closed.handler()

    assert window_mod.open_main_window(runtime, config) is True
    assert len(created) == 2
