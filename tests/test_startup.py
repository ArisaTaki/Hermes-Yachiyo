"""Startup 决策层测试"""

import importlib

from apps.shell.config import AppConfig
from apps.shell.modes import DisplayMode, resolve_display_mode
from apps.shell.startup import StartupMode, resolve_startup_mode, run_normal_mode
from packages.protocol.enums import HermesInstallStatus, Platform
from packages.protocol.install import HermesInstallInfo


class _FakeInstallInfo:
    def __init__(self, status: HermesInstallStatus):
        self.status = status


class TestResolveStartupMode:
    def test_ready_to_normal(self):
        info = _FakeInstallInfo(HermesInstallStatus.READY)
        assert resolve_startup_mode(info) == StartupMode.NORMAL

    def test_not_initialized_to_init_wizard(self):
        info = _FakeInstallInfo(HermesInstallStatus.INSTALLED_NOT_INITIALIZED)
        assert resolve_startup_mode(info) == StartupMode.INIT_WIZARD

    def test_not_installed_to_installer(self):
        info = _FakeInstallInfo(HermesInstallStatus.NOT_INSTALLED)
        assert resolve_startup_mode(info) == StartupMode.INSTALLER

    def test_incompatible_to_installer(self):
        info = _FakeInstallInfo(HermesInstallStatus.INCOMPATIBLE_VERSION)
        assert resolve_startup_mode(info) == StartupMode.INSTALLER

    def test_wsl2_required_to_installer(self):
        info = _FakeInstallInfo(HermesInstallStatus.WSL2_REQUIRED)
        assert resolve_startup_mode(info) == StartupMode.INSTALLER

    def test_not_checked_to_installer(self):
        info = _FakeInstallInfo(HermesInstallStatus.NOT_CHECKED)
        assert resolve_startup_mode(info) == StartupMode.INSTALLER

    def test_needs_setup_to_installer(self):
        info = _FakeInstallInfo(HermesInstallStatus.INSTALLED_NEEDS_SETUP)
        assert resolve_startup_mode(info) == StartupMode.INSTALLER

    def test_setup_in_progress_to_installer(self):
        info = _FakeInstallInfo(HermesInstallStatus.SETUP_IN_PROGRESS)
        assert resolve_startup_mode(info) == StartupMode.INSTALLER


def test_run_normal_mode_reuses_startup_install_info(monkeypatch):
    install_info = HermesInstallInfo(
        status=HermesInstallStatus.READY,
        platform=Platform.MACOS,
        command_exists=True,
    )
    started_with = []
    stopped = []
    runtime_instances = []

    class FakeRuntime:
        def __init__(self, config):
            self.config = config
            runtime_instances.append(self)

        def start(self, install_info=None):
            started_with.append(install_info)

        def stop(self):
            stopped.append(True)

    config = AppConfig()
    config.bridge_enabled = False
    config.tray_enabled = False

    bridge_deps = importlib.import_module("apps.bridge.deps")
    shell_modes = importlib.import_module("apps.shell.modes")

    monkeypatch.setattr("apps.core.runtime.HermesRuntime", FakeRuntime)
    monkeypatch.setattr(bridge_deps, "set_runtime", lambda runtime: None, raising=False)
    monkeypatch.setattr(shell_modes, "resolve_display_mode", lambda config: "bubble")
    monkeypatch.setattr(shell_modes, "launch_mode", lambda runtime, config: None)

    run_normal_mode(config, install_info=install_info)

    assert len(runtime_instances) == 1
    assert started_with == [install_info]
    assert stopped == [True]


def test_legacy_window_display_mode_resolves_to_bubble():
    config = AppConfig()
    config.display_mode = "window"  # type: ignore[assignment]

    assert resolve_display_mode(config) == DisplayMode.BUBBLE
