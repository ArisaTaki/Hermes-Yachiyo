"""Local release-candidate artifact build helper tests."""

from __future__ import annotations

import sys

from scripts import build_release_candidate_artifacts as builder


def _skip_pyinstaller_preflight(monkeypatch) -> None:
    monkeypatch.setattr(builder, "_ensure_pyinstaller_available", lambda: None)


def test_build_release_candidate_artifacts_restores_tracked_metadata(
    monkeypatch,
    tmp_path,
):
    _skip_pyinstaller_preflight(monkeypatch)
    metadata_path = tmp_path / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"commit":"dev"}\n', encoding="utf-8")
    backend_path = tmp_path / "dist" / "backend" / "oha-yachiyo-backend"
    provider_path = (
        tmp_path / "dist" / "desktop-provider" / "oha-yachiyo-desktop-provider"
    )
    dmg_path = tmp_path / "dist" / "electron" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    legacy_dmg_path = tmp_path / "dist" / "electron" / "Hermes-Yachiyo-0.1.0-arm64.dmg"
    legacy_app_path = tmp_path / "dist" / "electron" / "mac-arm64" / "Hermes-Yachiyo.app"
    legacy_app_path.mkdir(parents=True)
    legacy_dmg_path.write_text("legacy dmg", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "BACKEND_ARTIFACT", backend_path)
    monkeypatch.setattr(builder, "DESKTOP_PROVIDER_ARTIFACT", provider_path)
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", dmg_path.parent)

    def fake_run(command: list[str]) -> None:
        commands.append(command)
        if command[:2] == [sys.executable, "scripts/prepare_app_build_metadata.py"]:
            metadata_path.write_text('{"commit":"abcdef1234567890"}\n', encoding="utf-8")
        elif command[:2] == [sys.executable, "scripts/build_backend.py"]:
            backend_path.parent.mkdir(parents=True)
            backend_path.write_text("backend", encoding="utf-8")
        elif command[:2] == [
            sys.executable,
            "scripts/build_virtual_desktop_guest.py",
        ]:
            provider_path.parent.mkdir(parents=True)
            provider_path.write_text("provider", encoding="utf-8")
        elif command == ["npm", "--prefix", "apps/frontend", "run", "dist:mac"]:
            dmg_path.parent.mkdir(parents=True)
            dmg_path.write_text("dmg", encoding="utf-8")

    monkeypatch.setattr(builder, "_run", fake_run)

    artifacts = builder.build_release_candidate_artifacts(
        channel="experimental",
        repository="owner/repo",
        built_at="2026-06-12T00:00:00Z",
    )

    assert commands == [
        [
            sys.executable,
            "scripts/prepare_app_build_metadata.py",
            "--channel",
            "experimental",
            "--repository",
            "owner/repo",
            "--built-at",
            "2026-06-12T00:00:00Z",
        ],
        [sys.executable, "scripts/build_backend.py", "--clean"],
        [sys.executable, "scripts/build_virtual_desktop_guest.py", "--clean"],
        ["npm", "--prefix", "apps/frontend", "run", "dist:mac"],
    ]
    assert metadata_path.read_text(encoding="utf-8") == '{"commit":"dev"}\n'
    assert not legacy_dmg_path.exists()
    assert not legacy_app_path.exists()
    assert artifacts == {
        "backend": backend_path,
        "desktop_provider": provider_path,
        "dmg": dmg_path,
        "metadata": metadata_path,
    }


def test_build_release_candidate_artifacts_restores_metadata_after_failure(
    monkeypatch,
    tmp_path,
):
    _skip_pyinstaller_preflight(monkeypatch)
    metadata_path = tmp_path / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"commit":"dev"}\n', encoding="utf-8")

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", tmp_path / "dist" / "electron")

    def fake_run(command: list[str]) -> None:
        if command[:2] == [sys.executable, "scripts/prepare_app_build_metadata.py"]:
            metadata_path.write_text('{"commit":"abcdef1234567890"}\n', encoding="utf-8")
        if command == ["npm", "--prefix", "apps/frontend", "run", "dist:mac"]:
            raise RuntimeError("frontend build failed")

    monkeypatch.setattr(builder, "_run", fake_run)

    try:
        builder.build_release_candidate_artifacts(channel="experimental")
    except RuntimeError as exc:
        assert "frontend build failed" in str(exc)
    else:
        raise AssertionError("frontend build failure should propagate")

    assert metadata_path.read_text(encoding="utf-8") == '{"commit":"dev"}\n'


def test_build_release_candidate_artifacts_can_preserve_electron_output(
    monkeypatch,
    tmp_path,
):
    _skip_pyinstaller_preflight(monkeypatch)
    metadata_path = tmp_path / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"commit":"dev"}\n', encoding="utf-8")
    backend_path = tmp_path / "dist" / "backend" / "oha-yachiyo-backend"
    dmg_path = tmp_path / "dist" / "electron" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    legacy_dmg_path = tmp_path / "dist" / "electron" / "Hermes-Yachiyo-0.1.0-arm64.dmg"
    legacy_dmg_path.parent.mkdir(parents=True)
    legacy_dmg_path.write_text("legacy dmg", encoding="utf-8")

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "BACKEND_ARTIFACT", backend_path)
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", dmg_path.parent)

    def fake_run(command: list[str]) -> None:
        if command[:2] == [sys.executable, "scripts/build_backend.py"]:
            backend_path.parent.mkdir(parents=True)
            backend_path.write_text("backend", encoding="utf-8")
        elif command == ["npm", "--prefix", "apps/frontend", "run", "dist:mac"]:
            dmg_path.write_text("dmg", encoding="utf-8")

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.build_release_candidate_artifacts(
        channel="experimental",
        clean_electron=False,
    )

    assert legacy_dmg_path.exists()


def test_build_release_candidate_artifacts_fails_fast_without_pyinstaller(
    monkeypatch,
    tmp_path,
):
    metadata_path = tmp_path / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"commit":"dev"}\n', encoding="utf-8")
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "_pyinstaller_available", lambda: False)
    monkeypatch.setattr(builder, "_run", lambda command: commands.append(command))

    try:
        builder.build_release_candidate_artifacts(channel="experimental")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("missing PyInstaller should fail before mutating metadata")

    assert "PyInstaller is not available" in message
    assert str(venv_python) in message
    assert "scripts/build_release_candidate_artifacts.py" in message
    assert metadata_path.read_text(encoding="utf-8") == '{"commit":"dev"}\n'
    assert commands == []


def test_build_release_candidate_artifacts_cli_reports_missing_pyinstaller(
    monkeypatch,
    tmp_path,
    capsys,
):
    venv_python = tmp_path / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "_pyinstaller_available", lambda: False)

    assert builder.main(["--channel", "experimental"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "release candidate artifact build failed:" in captured.err
    assert "PyInstaller is not available" in captured.err
    assert "Traceback" not in captured.err
