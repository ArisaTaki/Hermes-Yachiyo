"""Local release-candidate artifact build helper tests."""

from __future__ import annotations

import sys

from scripts import build_release_candidate_artifacts as builder


def test_build_release_candidate_artifacts_restores_tracked_metadata(
    monkeypatch,
    tmp_path,
):
    metadata_path = tmp_path / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"commit":"dev"}\n', encoding="utf-8")
    backend_path = tmp_path / "dist" / "backend" / "oha-yachiyo-backend"
    dmg_path = tmp_path / "dist" / "electron" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "BACKEND_ARTIFACT", backend_path)
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", dmg_path.parent)

    def fake_run(command: list[str]) -> None:
        commands.append(command)
        if command[:2] == [sys.executable, "scripts/prepare_app_build_metadata.py"]:
            metadata_path.write_text('{"commit":"abcdef1234567890"}\n', encoding="utf-8")
        elif command[:2] == [sys.executable, "scripts/build_backend.py"]:
            backend_path.parent.mkdir(parents=True)
            backend_path.write_text("backend", encoding="utf-8")
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
        ["npm", "--prefix", "apps/frontend", "run", "dist:mac"],
    ]
    assert metadata_path.read_text(encoding="utf-8") == '{"commit":"dev"}\n'
    assert artifacts == {
        "backend": backend_path,
        "dmg": dmg_path,
        "metadata": metadata_path,
    }


def test_build_release_candidate_artifacts_restores_metadata_after_failure(
    monkeypatch,
    tmp_path,
):
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
