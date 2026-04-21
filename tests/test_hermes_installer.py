"""Hermes 安装检测与安装器配置测试。"""

import inspect

from apps.installer.hermes_check import (
    check_hermes_installation,
    check_hermes_doctor_readiness,
    is_version_compatible,
)
from apps.installer.hermes_install import (
    HERMES_INSTALL_TIMEOUT_SECONDS,
    run_hermes_install,
)
from packages.protocol.enums import HermesInstallStatus, HermesReadinessLevel, Platform
from packages.protocol.install import HermesVersionInfo


def test_hermes_version_uses_numeric_segments():
    assert is_version_compatible("0.10.0") is True
    assert is_version_compatible("v0.10.0") is True
    assert is_version_compatible("0.8") is True


def test_hermes_version_rejects_older_or_invalid_values():
    assert is_version_compatible("0.7.9") is False
    assert is_version_compatible("unknown") is False
    assert is_version_compatible("") is False


def test_hermes_install_timeout_allows_slow_setup_phase():
    timeout_param = inspect.signature(run_hermes_install).parameters["timeout"]

    assert HERMES_INSTALL_TIMEOUT_SECONDS == 900.0
    assert timeout_param.default == HERMES_INSTALL_TIMEOUT_SECONDS


def test_hermes_doctor_readiness_keeps_startup_bounded():
    timeout_param = inspect.signature(check_hermes_doctor_readiness).parameters["timeout"]

    assert timeout_param.default == 5.0


def test_install_check_uses_located_hermes_binary(monkeypatch):
    hermes_path = "/Users/test/.local/bin/hermes"
    calls = []

    monkeypatch.setattr(
        "apps.installer.hermes_check.detect_platform",
        lambda: Platform.MACOS,
    )
    monkeypatch.setattr(
        "apps.installer.hermes_check.locate_hermes_binary",
        lambda: (hermes_path, True),
    )

    def fake_check_command(path="hermes"):
        calls.append(("command", path))
        return True, None

    def fake_get_version(path="hermes"):
        calls.append(("version", path))
        return HermesVersionInfo(version="0.10.0", build_date="2026.4.16")

    def fake_setup(path="hermes"):
        calls.append(("setup", path))
        return True, ""

    def fake_doctor(timeout=5.0, hermes_path="hermes"):
        calls.append(("doctor", hermes_path))
        return HermesReadinessLevel.FULL_READY, [], 0

    monkeypatch.setattr(
        "apps.installer.hermes_check.check_hermes_command",
        fake_check_command,
    )
    monkeypatch.setattr(
        "apps.installer.hermes_check.get_hermes_version",
        fake_get_version,
    )
    monkeypatch.setattr(
        "apps.installer.hermes_check.check_hermes_setup",
        fake_setup,
    )
    monkeypatch.setattr(
        "apps.installer.hermes_check.check_yachiyo_workspace",
        lambda: (True, ""),
    )
    monkeypatch.setattr(
        "apps.installer.hermes_check.check_hermes_doctor_readiness",
        fake_doctor,
    )

    info = check_hermes_installation()

    assert info.status == HermesInstallStatus.READY
    assert info.command_exists is True
    assert calls == [
        ("command", hermes_path),
        ("version", hermes_path),
        ("setup", hermes_path),
        ("doctor", hermes_path),
    ]
