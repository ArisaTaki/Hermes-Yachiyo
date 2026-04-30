"""Hermes 安装检测与安装器配置测试。"""

import inspect
from types import SimpleNamespace

import pytest

from apps.installer.hermes_check import (
    check_hermes_installation,
    check_hermes_doctor_readiness,
    is_version_compatible,
)
from apps.installer.hermes_install import (
    HERMES_INSTALL_TIMEOUT_SECONDS,
    clean_terminal_line,
    run_hermes_install,
    summarize_install_failure,
)
from packages.protocol.enums import HermesInstallStatus, HermesReadinessLevel, Platform
from packages.protocol.install import HermesVersionInfo


class _FakeInstallStdout:
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeInstallProcess:
    def __init__(self, returncode: int, lines: list[bytes]):
        self.stdout = _FakeInstallStdout(lines)
        self.returncode = returncode
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True

    async def communicate(self):
        return b"", b""


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


def test_hermes_install_summarizes_git_clone_disconnect():
    output = """
Cloning into '/Users/test/.hermes/hermes-agent'...
error: RPC failed; curl 18 transfer closed with outstanding read data remaining
fetch-pack: unexpected disconnect while reading sideband packet
fatal: early EOF
fatal: fetch-pack: invalid index-pack output
"""

    message = summarize_install_failure(output, 128)

    assert "GitHub" in message
    assert "网络" in message
    assert "Releases" in message


def test_hermes_install_cleans_ansi_without_dropping_text():
    line = "\x1b[32mInstalling Hermes\x1b[0m\r"

    assert clean_terminal_line(line) == "Installing Hermes"


@pytest.mark.asyncio
async def test_run_install_keeps_sanitized_ansi_error_output(monkeypatch):
    process = _FakeInstallProcess(
        1,
        [
            b"\x1b[31mERROR: Package installation failed.\x1b[0m\n",
            b"plain context line\n",
        ],
    )
    seen_lines = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    monkeypatch.setattr(
        "apps.installer.hermes_check.detect_platform",
        lambda: Platform.MACOS,
    )
    monkeypatch.setattr(
        "apps.installer.hermes_check.locate_hermes_binary",
        lambda: (None, False),
    )
    monkeypatch.setattr(
        "apps.installer.hermes_install.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await run_hermes_install(on_output=seen_lines.append, timeout=1.0)

    assert result.success is False
    assert "ERROR: Package installation failed." in result.stdout
    assert "plain context line" in result.stdout
    assert "\x1b[" not in result.stdout
    assert "ERROR: Package installation failed." in seen_lines
    assert "错误详情" in result.message


@pytest.mark.asyncio
async def test_run_install_accepts_located_hermes_after_script_failure(monkeypatch):
    hermes_path = "/Users/test/.local/bin/hermes"
    process = _FakeInstallProcess(
        1,
        [b"everything's installed!\n"],
    )
    version_calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        return process

    def fake_run(args, capture_output, text, timeout):
        version_calls.append((args, capture_output, text, timeout))
        return SimpleNamespace(returncode=0, stdout="hermes 0.10.0\n", stderr="")

    monkeypatch.setattr(
        "apps.installer.hermes_check.detect_platform",
        lambda: Platform.MACOS,
    )
    monkeypatch.setattr(
        "apps.installer.hermes_check.locate_hermes_binary",
        lambda: (hermes_path, True),
    )
    monkeypatch.setattr(
        "apps.installer.hermes_install.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "apps.installer.hermes_install.subprocess.run",
        fake_run,
    )

    result = await run_hermes_install(timeout=1.0)

    assert result.success is True
    assert result.returncode == 0
    assert "已修复当前应用 PATH" in result.message
    assert version_calls == [([hermes_path, "--version"], True, True, 10)]


def test_hermes_doctor_readiness_keeps_startup_bounded():
    timeout_param = inspect.signature(check_hermes_doctor_readiness).parameters["timeout"]

    assert timeout_param.default == 5.0


def test_hermes_doctor_readiness_parses_limited_tools(monkeypatch):
    class Result:
        stdout = """
◆ Tool Availability
  ✓ terminal
  ⚠ browser (system dependency not met)
  ❌ image_gen (system dependency not met)
  ✗ agent-browser (missing binary)

────────────────────────────────────────────────────────────
  Found 3 issue(s) to address:
"""
        stderr = ""

    calls = []

    def fake_run(args, capture_output, text, timeout):
        calls.append((args, capture_output, text, timeout))
        return Result()

    monkeypatch.setattr("apps.installer.hermes_check.subprocess.run", fake_run)

    readiness, tools, issues = check_hermes_doctor_readiness(
        timeout=1.5,
        hermes_path="/tmp/hermes",
    )

    assert readiness == HermesReadinessLevel.BASIC_READY
    assert tools == ["browser", "image_gen", "agent-browser"]
    assert issues == 3
    assert calls == [(["/tmp/hermes", "doctor"], True, True, 1.5)]


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
