"""Startup 决策层测试"""

from apps.shell.startup import StartupMode, resolve_startup_mode
from packages.protocol.enums import HermesInstallStatus


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
