"""Packaged backend build command tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import build_backend as build_backend_mod


def test_build_backend_stages_onedir_and_publishes_stable_layout(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(build_backend_mod, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(build_backend_mod, "BUILD_DIR", tmp_path / "build")
    stale_runtime = build_backend_mod.DIST_DIR / "runtime"
    stale_runtime.mkdir(parents=True)
    (stale_runtime / "obsolete-sidecar").write_text("stale", encoding="utf-8")
    output_name = (
        "oha-yachiyo-backend.exe"
        if build_backend_mod.os.name == "nt"
        else "oha-yachiyo-backend"
    )
    (build_backend_mod.DIST_DIR / output_name).write_text(
        "old-executable",
        encoding="utf-8",
    )

    def fake_run(command, *, cwd, check):
        commands.append((command, cwd, check))
        staged_bundle = (
            build_backend_mod.BUILD_DIR / "dist" / "oha-yachiyo-backend"
        )
        staged_runtime = staged_bundle / "runtime"
        staged_runtime.mkdir(parents=True)
        (staged_bundle / output_name).write_text("executable", encoding="utf-8")
        (staged_runtime / "python-sidecar").write_text("runtime", encoding="utf-8")

    monkeypatch.setattr(build_backend_mod.subprocess, "run", fake_run)

    output_path = build_backend_mod.build_backend()

    assert output_path.exists()
    assert output_path == build_backend_mod.DIST_DIR / output_path.name
    assert output_path.read_text(encoding="utf-8") == "executable"
    assert (build_backend_mod.DIST_DIR / "runtime" / "python-sidecar").read_text(
        encoding="utf-8"
    ) == "runtime"
    assert not (build_backend_mod.DIST_DIR / "runtime" / "obsolete-sidecar").exists()
    assert not (tmp_path / ".dist-staging").exists()
    assert not (tmp_path / ".dist-backup").exists()
    command, cwd, check = commands[0]
    assert cwd == build_backend_mod.ROOT
    assert check is True
    assert "--onedir" in command
    assert "--onefile" not in command
    contents_index = command.index("--contents-directory")
    assert command[contents_index + 1] == "runtime"
    dist_index = command.index("--distpath")
    assert Path(command[dist_index + 1]) == build_backend_mod.BUILD_DIR / "dist"
    collect_index = command.index("--collect-data")
    assert command[collect_index + 1] == "certifi"
    metadata_arg = (
        f"{build_backend_mod.BUILD_METADATA_FILE}"
        f"{build_backend_mod._data_separator()}apps/frontend/public"
    )
    assert "--add-data" in command
    assert metadata_arg in command


def test_build_backend_rolls_back_whole_bundle_when_publication_fails(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(build_backend_mod, "DIST_DIR", tmp_path / "dist")
    monkeypatch.setattr(build_backend_mod, "BUILD_DIR", tmp_path / "build")
    output_name = (
        "oha-yachiyo-backend.exe"
        if build_backend_mod.os.name == "nt"
        else "oha-yachiyo-backend"
    )
    old_runtime = build_backend_mod.DIST_DIR / "runtime"
    old_runtime.mkdir(parents=True)
    (build_backend_mod.DIST_DIR / output_name).write_text(
        "old-executable",
        encoding="utf-8",
    )
    (old_runtime / "old-sidecar").write_text("old-runtime", encoding="utf-8")

    def fake_run(command, *, cwd, check):
        staged_bundle = (
            build_backend_mod.BUILD_DIR / "dist" / "oha-yachiyo-backend"
        )
        staged_runtime = staged_bundle / "runtime"
        staged_runtime.mkdir(parents=True)
        (staged_bundle / output_name).write_text("new-executable", encoding="utf-8")
        (staged_runtime / "new-sidecar").write_text("new-runtime", encoding="utf-8")

    monkeypatch.setattr(build_backend_mod.subprocess, "run", fake_run)
    original_replace = Path.replace
    pending_bundle = tmp_path / ".dist-staging"

    def fail_pending_publish(path, target):
        if path == pending_bundle and Path(target) == build_backend_mod.DIST_DIR:
            raise OSError("simulated publish failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_pending_publish)

    with pytest.raises(OSError, match="simulated publish failure"):
        build_backend_mod.build_backend(clean=True)

    assert (build_backend_mod.DIST_DIR / output_name).read_text(
        encoding="utf-8"
    ) == "old-executable"
    assert (build_backend_mod.DIST_DIR / "runtime" / "old-sidecar").read_text(
        encoding="utf-8"
    ) == "old-runtime"
    assert not (build_backend_mod.DIST_DIR / "runtime" / "new-sidecar").exists()
    assert not (tmp_path / ".dist-staging").exists()
    assert not (tmp_path / ".dist-backup").exists()


def test_electron_builder_packages_backend_runtime_next_to_executable():
    config = (
        build_backend_mod.ROOT / "apps" / "frontend" / "electron-builder.yml"
    ).read_text(encoding="utf-8")

    assert "from: ../../dist/backend/oha-yachiyo-backend" in config
    assert "to: backend/oha-yachiyo-backend" in config
    assert "from: ../../dist/backend/runtime" in config
    assert "to: backend/runtime" in config
