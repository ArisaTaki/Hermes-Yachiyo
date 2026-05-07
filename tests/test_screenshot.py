"""截图适配器测试。"""

from __future__ import annotations

import subprocess

import pytest

import apps.locald.screenshot as screenshot_mod


def test_capture_screenshot_to_file_rejects_empty_output(monkeypatch, tmp_path):
    target = tmp_path / "screen.png"

    def fake_run(*_args, **_kwargs):
        target.write_bytes(b"")
        return subprocess.CompletedProcess(["screencapture"], 0, stdout="", stderr="could not create image from display")

    monkeypatch.setattr(screenshot_mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="未生成有效图片"):
        screenshot_mod.capture_screenshot_to_file(target)


def test_capture_screenshot_to_file_reports_screen_recording_permission(monkeypatch, tmp_path):
    target = tmp_path / "screen.png"

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["screencapture"],
            1,
            stdout="",
            stderr="could not create image from display",
        )

    monkeypatch.setattr(screenshot_mod.subprocess, "run", fake_run)

    with pytest.raises(screenshot_mod.ScreenCapturePermissionError) as exc_info:
        screenshot_mod.capture_screenshot_to_file(target)

    message = str(exc_info.value)
    assert "屏幕录制权限" in message
    assert "重启 Hermes-Yachiyo 或 Bridge" in message
    assert "could not create image from display" in message


def test_check_screen_capture_permission_opens_settings_on_permission_error(monkeypatch):
    opened = []

    def fake_capture(_target):
        raise screenshot_mod.ScreenCapturePermissionError("没有屏幕录制权限")

    monkeypatch.setattr(screenshot_mod, "capture_screenshot_to_file", fake_capture)
    monkeypatch.setattr(screenshot_mod, "open_screen_recording_settings", lambda: opened.append(True) or True)
    monkeypatch.setattr(screenshot_mod.platform, "system", lambda: "Darwin")

    result = screenshot_mod.check_screen_capture_permission(open_settings=True)

    assert result["ok"] is False
    assert result["allowed"] is False
    assert result["permission_denied"] is True
    assert result["settings_opened"] is True
    assert opened == [True]


def test_check_screen_capture_permission_reports_allowed(monkeypatch):
    monkeypatch.setattr(
        screenshot_mod,
        "capture_screenshot_to_file",
        lambda _target: {"path": str(_target), "width": 1, "height": 1},
    )

    result = screenshot_mod.check_screen_capture_permission(open_settings=True)

    assert result["ok"] is True
    assert result["allowed"] is True
    assert "可用" in str(result["message"])


def test_capture_screenshot_to_file_rejects_invalid_image(monkeypatch, tmp_path):
    target = tmp_path / "screen.png"

    def fake_run(*_args, **_kwargs):
        target.write_bytes(b"not a png")
        return subprocess.CompletedProcess(["screencapture"], 0, stdout="", stderr="")

    monkeypatch.setattr(screenshot_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(screenshot_mod, "_image_size", lambda _path: (0, 0))

    with pytest.raises(RuntimeError, match="不是有效图片"):
        screenshot_mod.capture_screenshot_to_file(target)


def test_capture_screenshot_to_file_returns_metadata(monkeypatch, tmp_path):
    target = tmp_path / "screen.png"

    def fake_run(*_args, **_kwargs):
        target.write_bytes(b"png-data")
        return subprocess.CompletedProcess(["screencapture"], 0, stdout="", stderr="")

    monkeypatch.setattr(screenshot_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(screenshot_mod, "_image_size", lambda _path: (120, 80))

    meta = screenshot_mod.capture_screenshot_to_file(target)

    assert meta["path"] == str(target)
    assert meta["mime_type"] == "image/png"
    assert meta["width"] == 120
    assert meta["height"] == 80
    assert meta["size"] == len(b"png-data")


def test_png_image_size_reads_header(tmp_path):
    target = tmp_path / "screen.png"
    target.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        + (3024).to_bytes(4, "big")
        + (1964).to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )

    assert screenshot_mod._image_size(target) == (3024, 1964)
