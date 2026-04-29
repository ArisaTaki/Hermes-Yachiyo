"""System terminal helper tests."""

from __future__ import annotations

import os
from pathlib import Path

from apps.shell import terminal as terminal_mod


def test_open_terminal_command_macos_uses_command_file(tmp_path, monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, capture_output, text, timeout, check):
        calls.append(args)
        script_path = Path(args[-1])
        content = script_path.read_text(encoding="utf-8")
        assert "echo hello" in content
        assert os.access(script_path, os.X_OK)
        return Result()

    monkeypatch.setattr(terminal_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(terminal_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(terminal_mod.subprocess, "run", fake_run)

    success, error = terminal_mod.open_terminal_command("echo hello")

    assert success is True
    assert error is None
    assert calls[0][:3] == ["open", "-a", "Terminal"]


def test_open_terminal_command_macos_reports_open_failure(tmp_path, monkeypatch):
    class Result:
        returncode = 1
        stdout = ""
        stderr = "Terminal denied"

    monkeypatch.setattr(terminal_mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(terminal_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(terminal_mod.subprocess, "run", lambda *args, **kwargs: Result())

    success, error = terminal_mod.open_terminal_command("echo hello")

    assert success is False
    assert error == "Terminal denied"
