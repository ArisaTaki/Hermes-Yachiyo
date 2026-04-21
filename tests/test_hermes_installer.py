"""Hermes 安装检测与安装器配置测试。"""

import inspect

from apps.installer.hermes_check import (
    check_hermes_doctor_readiness,
    is_version_compatible,
)
from apps.installer.hermes_install import (
    HERMES_INSTALL_TIMEOUT_SECONDS,
    run_hermes_install,
)


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
