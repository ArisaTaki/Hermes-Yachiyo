"""Build metadata guard tests."""

from __future__ import annotations

import json
import sys

import pytest

from apps.core import build_metadata


def _write_metadata(tmp_path, *, channel: str) -> str:
    path = tmp_path / "oha-yachiyo-build.json"
    path.write_text(json.dumps({"channel": channel}), encoding="utf-8")
    return str(path)


def _write_metadata_at(path, *, channel: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"channel": channel}), encoding="utf-8")


def _clear_build_env(monkeypatch) -> None:
    for key in (
        "OHA_YACHIYO_DEV",
        "OHA_YACHIYO_BUILD_METADATA",
        "OHA_YACHIYO_BUILD_CHANNEL",
        "OHA_YACHIYO_RELEASE_BUILD",
        "OHA_YACHIYO_ALPHA_BUILD",
        "OHA_YACHIYO_PACKAGED_BUILD",
    ):
        monkeypatch.delenv(key, raising=False)


def test_development_features_require_dev_flag(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel="experimental"))

    assert build_metadata.development_features_enabled() is False

    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")

    assert build_metadata.development_features_enabled() is True


@pytest.mark.parametrize("channel", ["release", "alpha", "stable"])
def test_development_features_disabled_by_release_metadata(monkeypatch, tmp_path, channel):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel=channel))

    assert build_metadata.build_channel() == channel
    assert build_metadata.is_release_like_build() is True
    assert build_metadata.development_features_enabled() is False


@pytest.mark.parametrize("channel", ["release", "alpha", "stable"])
def test_development_features_disabled_by_release_channel_env(monkeypatch, channel):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_CHANNEL", channel)

    assert build_metadata.is_release_like_build() is True
    assert build_metadata.development_features_enabled() is False


@pytest.mark.parametrize("env_name", ["OHA_YACHIYO_RELEASE_BUILD", "OHA_YACHIYO_ALPHA_BUILD"])
def test_development_features_disabled_by_release_flag_env(monkeypatch, env_name):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv(env_name, "1")

    assert build_metadata.is_release_like_build() is True
    assert build_metadata.development_features_enabled() is False


def test_packaged_backend_reads_pyinstaller_meipass_metadata(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    meipass = tmp_path / "_MEIPASS"
    _write_metadata_at(
        meipass / "apps" / "frontend" / "public" / build_metadata.APP_BUILD_METADATA_FILE,
        channel="stable",
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert build_metadata.build_channel() == "stable"
    assert build_metadata.is_release_like_build() is True


def test_packaged_backend_reads_executable_adjacent_metadata(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    exe_dir = tmp_path / "Oha-Yachiyo.app" / "Contents" / "Resources" / "backend"
    exe_dir.mkdir(parents=True)
    executable = exe_dir / "oha-yachiyo-backend"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    _write_metadata_at(exe_dir / build_metadata.APP_BUILD_METADATA_FILE, channel="alpha")
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert build_metadata.build_channel() == "alpha"
    assert build_metadata.is_release_like_build() is True


def test_development_features_disabled_by_packaged_build(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel="experimental"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert build_metadata.is_packaged_build() is True
    assert build_metadata.development_features_enabled() is False


def test_development_features_disabled_by_packaged_build_env(monkeypatch, tmp_path):
    _clear_build_env(monkeypatch)
    monkeypatch.setenv("OHA_YACHIYO_DEV", "1")
    monkeypatch.setenv("OHA_YACHIYO_PACKAGED_BUILD", "1")
    monkeypatch.setenv("OHA_YACHIYO_BUILD_METADATA", _write_metadata(tmp_path, channel="experimental"))

    assert build_metadata.development_features_enabled() is False
