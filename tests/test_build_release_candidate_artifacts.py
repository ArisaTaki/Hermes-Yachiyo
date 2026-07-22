"""Local release-candidate artifact build helper tests."""

from __future__ import annotations

import hashlib
import json
import plistlib
import sys
from pathlib import Path

from scripts import build_release_candidate_artifacts as builder
from scripts import verify_release_artifacts as verifier
from scripts.release_integrity import MacOSSigningInspection, SourceTreeProvenance

COMMIT = "abcdef1234567890abcdef1234567890abcdef12"
FINGERPRINT = "sha256:" + "a" * 64
OFFICIAL_REPOSITORY = "kuguya-AI-app-develop/Hermes-Yachiyo"
ADHOC_PACKAGING_COMMAND = [
    "/bin/bash",
    "scripts/build_macos_self_signed_dmg.sh",
    "-",
    "self-signed-app-unsigned-dmg",
]


def _write_test_app(app_path) -> None:
    contents = app_path / "Contents"
    executable_dir = contents / "MacOS"
    executable_dir.mkdir(parents=True, exist_ok=True)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": "io.github.arisataki.oha-yachiyo",
                "CFBundleVersion": "0.4.0",
                "CFBundleShortVersionString": "0.4.0",
                "CFBundleExecutable": "Oha-Yachiyo",
            },
            handle,
        )
    (executable_dir / "Oha-Yachiyo").write_bytes(b"app executable")


def _skip_pyinstaller_preflight(monkeypatch) -> None:
    monkeypatch.setattr(builder, "_ensure_pyinstaller_available", lambda: None)
    monkeypatch.setattr(
        builder,
        "capture_source_tree_provenance",
        lambda _root: SourceTreeProvenance(
            commit=COMMIT,
            dirty=False,
            source_tree_fingerprint=FINGERPRINT,
        ),
    )
    monkeypatch.setattr(builder, "detect_electron_arch", lambda _root: "arm64")
    monkeypatch.setattr(
        builder,
        "inspect_macos_dmg_signing",
        lambda _path: MacOSSigningInspection(
            mode="unsigned",
            signature_kind="adhoc",
            authority="",
            team_identifier="",
            notarization_stapled=False,
        ),
    )


def _prepared_build_metadata() -> dict[str, object]:
    return {
        "name": "Oha-Yachiyo",
        "channel": "experimental",
        "branch": "oha-develop",
        "source_branch": "phase-5/oha-yachiyo-runtime",
        "version": "0.4.0",
        "base_version": "0.4.0",
        "commit": COMMIT,
        "short_commit": "abcdef1",
        "build_number": 17,
        "run_number": 17,
        "repository": OFFICIAL_REPOSITORY,
        "latest_json_url": (
            f"https://github.com/{OFFICIAL_REPOSITORY}/releases/download/"
            "oha-develop-latest/Oha-Yachiyo-oha-develop-latest.json"
        ),
        "built_at": "2026-06-12T00:00:00Z",
        "dirty": False,
        "source_tree_fingerprint": FINGERPRINT,
        "release_publishable": True,
    }


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
    bridge_path = (
        tmp_path
        / "dist"
        / "desktop-provider"
        / "oha-yachiyo-virtual-desktop-bridge"
    )
    dmg_path = tmp_path / "dist" / "electron" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    app_path = tmp_path / "dist" / "electron" / "mac-arm64" / "Oha-Yachiyo.app"
    legacy_dmg_path = tmp_path / "dist" / "electron" / "Hermes-Yachiyo-0.1.0-arm64.dmg"
    legacy_app_path = tmp_path / "dist" / "electron" / "mac-arm64" / "Hermes-Yachiyo.app"
    release_dir = tmp_path / "release"
    legacy_app_path.mkdir(parents=True)
    legacy_dmg_path.write_text("legacy dmg", encoding="utf-8")
    commands: list[list[str]] = []

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "BACKEND_ARTIFACT", backend_path)
    monkeypatch.setattr(builder, "DESKTOP_PROVIDER_ARTIFACT", provider_path)
    monkeypatch.setattr(builder, "DESKTOP_BRIDGE_ARTIFACT", bridge_path)
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", dmg_path.parent)
    monkeypatch.setattr(builder, "RELEASE_DIR", release_dir)

    def fake_run(command: list[str]) -> None:
        commands.append(command)
        if command[:2] == [sys.executable, "scripts/prepare_app_build_metadata.py"]:
            metadata_path.write_text(
                json.dumps(_prepared_build_metadata()),
                encoding="utf-8",
            )
        elif command[:2] == [sys.executable, "scripts/build_backend.py"]:
            backend_path.parent.mkdir(parents=True)
            backend_path.write_text("backend", encoding="utf-8")
        elif command[:2] == [
            sys.executable,
            "scripts/build_virtual_desktop_guest.py",
        ]:
            provider_path.parent.mkdir(parents=True)
            provider_path.write_text("provider", encoding="utf-8")
            bridge_path.write_text("bridge", encoding="utf-8")
        elif command == ADHOC_PACKAGING_COMMAND:
            dmg_path.parent.mkdir(parents=True)
            dmg_path.write_text("dmg", encoding="utf-8")
            _write_test_app(app_path)
        elif command[:2] == [sys.executable, "scripts/generate_release_changelog.py"]:
            release_dir.mkdir(parents=True, exist_ok=True)
            (release_dir / "changelog.json").write_text(
                json.dumps({"generated_from": "git", "sections": []}),
                encoding="utf-8",
            )
            (release_dir / "changelog.md").write_text("## 更新日志\n", encoding="utf-8")
        elif command[0] == "ditto":
            (release_dir / "Oha-Yachiyo-oha-develop-latest-arm64.zip").write_bytes(
                b"app zip"
            )

    monkeypatch.setattr(builder, "_run", fake_run)

    artifacts = builder.build_release_candidate_artifacts(
        channel="experimental",
        repository=OFFICIAL_REPOSITORY,
        built_at="2026-06-12T00:00:00Z",
    )

    assert commands == [
        [
            sys.executable,
            "scripts/prepare_app_build_metadata.py",
            "--channel",
            "experimental",
            "--repository",
            OFFICIAL_REPOSITORY,
            "--built-at",
            "2026-06-12T00:00:00Z",
            "--source-tree-fingerprint",
            FINGERPRINT,
            "--source-clean",
        ],
        [sys.executable, "scripts/build_backend.py", "--clean"],
        [sys.executable, "scripts/build_virtual_desktop_guest.py", "--clean"],
        ADHOC_PACKAGING_COMMAND,
        [
            sys.executable,
            "scripts/generate_release_changelog.py",
            "--channel",
            "experimental",
            "--tag",
            "experimental-v0.4.0-build.17-abcdef1",
            "--repository",
            OFFICIAL_REPOSITORY,
            "--output-json",
            "release/changelog.json",
            "--output-markdown",
            "release/changelog.md",
        ],
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app_path),
            str(release_dir / "Oha-Yachiyo-oha-develop-latest-arm64.zip"),
        ],
    ]
    assert metadata_path.read_text(encoding="utf-8") == '{"commit":"dev"}\n'
    assert not legacy_dmg_path.exists()
    assert not legacy_app_path.exists()
    release_dmg = release_dir / "Oha-Yachiyo-oha-develop-latest.dmg"
    release_checksum = release_dir / f"{release_dmg.name}.sha256"
    release_zip = release_dir / "Oha-Yachiyo-oha-develop-latest-arm64.zip"
    release_zip_checksum = release_dir / f"{release_zip.name}.sha256"
    release_metadata = release_dir / "Oha-Yachiyo-oha-develop-latest.json"
    release_changelog = release_dir / "changelog.json"
    digest = hashlib.sha256(b"dmg").hexdigest()
    assert release_dmg.read_text(encoding="utf-8") == "dmg"
    assert release_checksum.read_text(encoding="utf-8") == f"{digest}  {release_dmg.name}\n"
    latest = json.loads(release_metadata.read_text(encoding="utf-8"))
    assert latest["sha256"] == digest
    assert latest["signature_kind"] == "adhoc"
    assert latest["architecture"] == "arm64"
    assert latest["zip_name"] == release_zip.name
    assert latest["zip_sha256"] == hashlib.sha256(b"app zip").hexdigest()
    assert latest["dmg_name"] == release_dmg.name
    assert latest["run_id"] == "17"
    assert latest["dirty"] is False
    assert latest["source_tree_fingerprint"] == FINGERPRINT
    assert latest["release_publishable"] is True
    manifest = latest["release_candidate_manifest"]
    assert latest["candidate_id"] == manifest["candidate_id"]
    assert manifest["schema"] == "oha-yachiyo.release-candidate.v1"
    assert manifest["source"] == {
        "commit": COMMIT,
        "dirty": False,
        "fingerprint": FINGERPRINT,
        "release_publishable": True,
    }
    assert manifest["artifacts"] == {
        "dmg": {"name": release_dmg.name, "sha256": digest},
        "zip": {
            "name": release_zip.name,
            "sha256": hashlib.sha256(b"app zip").hexdigest(),
        },
    }
    assert manifest["app"] == {
        "bundle_id": "io.github.arisataki.oha-yachiyo",
        "version": "0.4.0",
        "short_version": "0.4.0",
        "executable": "Oha-Yachiyo",
        "signature_kind": "adhoc",
        "team_identifier": "",
    }
    assert latest["changelog"] == {"generated_from": "git", "sections": []}
    assert verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    ) == []
    assert artifacts == {
        "backend": backend_path,
        "desktop_provider": provider_path,
        "desktop_bridge": bridge_path,
        "dmg": dmg_path,
        "app": app_path,
        "metadata": metadata_path,
        "release_dmg": release_dmg,
        "release_checksum": release_checksum,
        "release_zip": release_zip,
        "release_zip_checksum": release_zip_checksum,
        "release_metadata": release_metadata,
        "release_changelog": release_changelog,
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
            metadata_path.write_text(json.dumps(_prepared_build_metadata()), encoding="utf-8")
        if command == ADHOC_PACKAGING_COMMAND:
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
    app_path = tmp_path / "dist" / "electron" / "mac-arm64" / "Oha-Yachiyo.app"
    preserved_output = tmp_path / "dist" / "electron" / "preserved-output.txt"
    preserved_output.parent.mkdir(parents=True)
    preserved_output.write_text("preserved", encoding="utf-8")

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "BACKEND_ARTIFACT", backend_path)
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", dmg_path.parent)
    monkeypatch.setattr(builder, "_stage_release_channel_artifacts", lambda *_args, **_kwargs: {})

    def fake_run(command: list[str]) -> None:
        if command[:2] == [sys.executable, "scripts/prepare_app_build_metadata.py"]:
            metadata_path.write_text(json.dumps(_prepared_build_metadata()), encoding="utf-8")
        elif command[:2] == [sys.executable, "scripts/build_backend.py"]:
            backend_path.parent.mkdir(parents=True)
            backend_path.write_text("backend", encoding="utf-8")
        elif command == ADHOC_PACKAGING_COMMAND:
            dmg_path.write_text("dmg", encoding="utf-8")
            app_path.mkdir(parents=True)

    monkeypatch.setattr(builder, "_run", fake_run)

    builder.build_release_candidate_artifacts(
        channel="experimental",
        clean_electron=False,
    )

    assert preserved_output.exists()


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


def test_build_release_candidate_artifacts_rejects_dirty_source_before_build(
    monkeypatch,
):
    commands: list[list[str]] = []
    monkeypatch.setattr(builder, "_ensure_pyinstaller_available", lambda: None)
    monkeypatch.setattr(
        builder,
        "capture_source_tree_provenance",
        lambda _root: SourceTreeProvenance(
            commit=COMMIT,
            dirty=True,
            source_tree_fingerprint=FINGERPRINT,
        ),
    )
    monkeypatch.setattr(builder, "_run", lambda command: commands.append(command))

    try:
        builder.build_release_candidate_artifacts(channel="experimental")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("dirty public/latest build should fail")

    assert "source tree is dirty" in message
    assert "--allow-dirty-local-rc" in message
    assert commands == []


def test_select_dmg_artifact_rejects_multiple_or_wrong_builds(monkeypatch, tmp_path):
    electron_dir = tmp_path / "dist" / "electron"
    electron_dir.mkdir(parents=True)
    current = electron_dir / "Oha-Yachiyo-0.4.0-arm64.dmg"
    stale = electron_dir / "Oha-Yachiyo-9.9.9-x64.dmg"
    current.write_bytes(b"current")
    stale.write_bytes(b"stale")
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", electron_dir)

    try:
        builder._select_dmg_artifact(version="0.4.0", arch="arm64")
    except RuntimeError as exc:
        assert "expected exactly one Electron DMG" in str(exc)
    else:
        raise AssertionError("multiple DMGs should be rejected")

    stale.unlink()
    assert builder._select_dmg_artifact(version="0.4.0", arch="arm64") == current
    try:
        builder._select_dmg_artifact(version="0.4.0", arch="x64")
    except RuntimeError as exc:
        assert "version and architecture" in str(exc)
    else:
        raise AssertionError("wrong DMG architecture should be rejected")


def test_stage_dirty_local_rc_records_nonpublishable_provenance(monkeypatch, tmp_path):
    dmg = tmp_path / "dist" / "electron" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg.parent.mkdir(parents=True)
    dmg.write_bytes(b"dirty local dmg")
    app = dmg.parent / "mac-arm64" / "Oha-Yachiyo.app"
    _write_test_app(app)
    release_dir = tmp_path / "release"
    metadata = _prepared_build_metadata()
    metadata.update(
        {
            "dirty": True,
            "release_publishable": False,
            "source_tree_fingerprint": "sha256:" + "b" * 64,
        }
    )
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "RELEASE_DIR", release_dir)

    def fake_run(command: list[str]) -> None:
        if command[:2] == [sys.executable, "scripts/generate_release_changelog.py"]:
            release_dir.mkdir(parents=True, exist_ok=True)
            (release_dir / "changelog.json").write_text(
                json.dumps({"generated_from": "git", "sections": []}),
                encoding="utf-8",
            )
            (release_dir / "changelog.md").write_text("## Changes\n", encoding="utf-8")
        elif command[0] == "ditto":
            (release_dir / "Oha-Yachiyo-oha-develop-latest-arm64.zip").write_bytes(
                b"dirty app zip"
            )
        else:
            raise AssertionError(command)

    monkeypatch.setattr(builder, "_run", fake_run)
    paths = builder._stage_release_channel_artifacts(
        dmg,
        app,
        metadata,
        signing_mode="unsigned",
        signature_kind="adhoc",
        architecture="arm64",
    )
    latest = json.loads(paths["release_metadata"].read_text(encoding="utf-8"))

    assert latest["dirty"] is True
    assert latest["release_publishable"] is False
    assert latest["source_tree_fingerprint"] == "sha256:" + "b" * 64
    assert latest["candidate_id"] == latest["release_candidate_manifest"]["candidate_id"]
    assert latest["release_candidate_manifest"]["source"]["dirty"] is True
    assert (
        latest["release_candidate_manifest"]["source"]["release_publishable"]
        is False
    )


def test_stage_existing_artifacts_uses_content_bound_inspection_and_candidate_manifest(
    monkeypatch,
    tmp_path,
):
    dmg = tmp_path / "dist" / "electron" / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg.parent.mkdir(parents=True)
    dmg.write_bytes(b"already signed dmg")
    app = dmg.parent / "mac-arm64" / "Oha-Yachiyo.app"
    _write_test_app(app)
    metadata_path = tmp_path / "oha-yachiyo-build.json"
    metadata_path.write_text(json.dumps(_prepared_build_metadata()), encoding="utf-8")
    inspection_path = tmp_path / "macos-signing-inspection.json"
    inspection_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dmg_name": dmg.name,
                "dmg_sha256": hashlib.sha256(b"already signed dmg").hexdigest(),
                "signing": "unsigned",
                "signature_kind": "adhoc",
                "authority": "",
                "team_identifier": "",
                "notarization_stapled": False,
            }
        ),
        encoding="utf-8",
    )
    release_dir = tmp_path / "release"
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "RELEASE_DIR", release_dir)

    def fake_run(command: list[str]) -> None:
        if command[:2] == [sys.executable, "scripts/generate_release_changelog.py"]:
            release_dir.mkdir(parents=True, exist_ok=True)
            (release_dir / "changelog.json").write_text(
                json.dumps({"generated_from": "git", "sections": []}),
                encoding="utf-8",
            )
            (release_dir / "changelog.md").write_text("## Changes\n", encoding="utf-8")
        elif command[0] == "ditto":
            Path(command[-1]).write_bytes(b"existing app zip")
        else:
            raise AssertionError(command)

    monkeypatch.setattr(builder, "_run", fake_run)
    artifacts = builder.stage_existing_release_candidate_artifacts(
        dmg_path=dmg,
        app_path=app,
        build_metadata_path=metadata_path,
        signing_inspection_path=inspection_path,
        architecture="arm64",
        signing_mode="unsigned",
    )
    latest = json.loads(artifacts["release_metadata"].read_text(encoding="utf-8"))

    assert latest["candidate_id"] == latest["release_candidate_manifest"]["candidate_id"]
    assert latest["release_candidate_manifest"]["artifacts"]["dmg"] == {
        "name": "Oha-Yachiyo-oha-develop-latest.dmg",
        "sha256": hashlib.sha256(b"already signed dmg").hexdigest(),
    }
    assert artifacts["release_dmg"].read_bytes() == b"already signed dmg"
    assert artifacts["release_zip"].read_bytes() == b"existing app zip"

    dmg.write_bytes(b"changed after inspection")
    try:
        builder.stage_existing_release_candidate_artifacts(
            dmg_path=dmg,
            app_path=app,
            build_metadata_path=metadata_path,
            signing_inspection_path=inspection_path,
            architecture="arm64",
        )
    except RuntimeError as exc:
        assert "inspection SHA256" in str(exc)
    else:
        raise AssertionError("staging must reject a DMG changed after inspection")


def test_stage_existing_cli_dispatches_without_rebuilding(monkeypatch, tmp_path, capsys):
    staged = {
        "release_dmg": tmp_path / "release" / "latest.dmg",
        "release_zip": tmp_path / "release" / "latest.zip",
        "release_metadata": tmp_path / "release" / "latest.json",
    }
    received: dict[str, object] = {}

    def fake_stage(**kwargs):
        received.update(kwargs)
        return staged

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "stage_existing_release_candidate_artifacts", fake_stage)
    monkeypatch.setattr(
        builder,
        "build_release_candidate_artifacts",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not rebuild")),
    )

    assert builder.main(
        [
            "--stage-existing",
            "--dmg",
            "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
            "--app",
            "dist/electron/mac-arm64/Oha-Yachiyo.app",
            "--build-metadata",
            "apps/frontend/public/oha-yachiyo-build.json",
            "--signing-inspection-json",
            "release/macos-signing-inspection.json",
            "--architecture",
            "arm64",
            "--signing-mode",
            "unsigned",
        ]
    ) == 0

    assert received == {
        "dmg_path": tmp_path / "dist/electron/Oha-Yachiyo-0.4.0-arm64.dmg",
        "app_path": tmp_path / "dist/electron/mac-arm64/Oha-Yachiyo.app",
        "build_metadata_path": tmp_path / "apps/frontend/public/oha-yachiyo-build.json",
        "signing_inspection_path": tmp_path / "release/macos-signing-inspection.json",
        "architecture": "arm64",
        "signing_mode": "unsigned",
        "allow_dirty_local_rc": False,
    }
    assert "release latest metadata:" in capsys.readouterr().out


def test_build_explicit_dirty_local_rc_embeds_and_stages_nonpublishable_metadata(
    monkeypatch,
    tmp_path,
):
    metadata_path = tmp_path / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text('{"commit":"dev"}\n', encoding="utf-8")
    electron_dir = tmp_path / "dist" / "electron"
    dmg = electron_dir / "Oha-Yachiyo-0.4.0-arm64.dmg"
    app = electron_dir / "mac-arm64" / "Oha-Yachiyo.app"
    dirty_fingerprint = "sha256:" + "d" * 64
    provenance = SourceTreeProvenance(
        commit=COMMIT,
        dirty=True,
        source_tree_fingerprint=dirty_fingerprint,
    )
    commands: list[list[str]] = []
    staged: dict[str, object] = {}

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BUILD_METADATA_FILE", metadata_path)
    monkeypatch.setattr(builder, "ELECTRON_DIST_DIR", electron_dir)
    monkeypatch.setattr(builder, "_ensure_pyinstaller_available", lambda: None)
    monkeypatch.setattr(builder, "capture_source_tree_provenance", lambda _root: provenance)
    monkeypatch.setattr(builder, "detect_electron_arch", lambda _root: "arm64")
    monkeypatch.setattr(
        builder,
        "inspect_macos_dmg_signing",
        lambda _path: MacOSSigningInspection(
            mode="unsigned",
            signature_kind="adhoc",
            authority="",
            team_identifier="",
            notarization_stapled=False,
        ),
    )

    def fake_run(command: list[str]) -> None:
        commands.append(command)
        if command[:2] == [sys.executable, "scripts/prepare_app_build_metadata.py"]:
            prepared = _prepared_build_metadata()
            prepared.update(
                {
                    "dirty": True,
                    "source_tree_fingerprint": dirty_fingerprint,
                    "release_publishable": False,
                }
            )
            metadata_path.write_text(json.dumps(prepared), encoding="utf-8")
        elif (
            len(command) == 4
            and command[0] == "/bin/bash"
            and command[1] == "scripts/build_macos_self_signed_dmg.sh"
        ):
            electron_dir.mkdir(parents=True, exist_ok=True)
            dmg.write_bytes(b"dirty local rc")
            app.mkdir(parents=True)

    def fake_stage(
        _dmg,
        _app,
        build_metadata,
        *,
        signing_mode,
        signature_kind,
        architecture,
        team_identifier,
    ):
        staged.update(build_metadata)
        staged["signing"] = signing_mode
        staged["signature_kind"] = signature_kind
        staged["architecture"] = architecture
        staged["team_identifier"] = team_identifier
        return {}

    monkeypatch.setattr(builder, "_run", fake_run)
    monkeypatch.setattr(builder, "_stage_release_channel_artifacts", fake_stage)

    builder.build_release_candidate_artifacts(
        channel="experimental",
        allow_dirty_local_rc=True,
    )

    metadata_command = commands[0]
    assert "--source-dirty" in metadata_command
    assert dirty_fingerprint in metadata_command
    assert metadata_command[metadata_command.index("--repository") + 1] == OFFICIAL_REPOSITORY
    assert staged["dirty"] is True
    assert staged["release_publishable"] is False
    assert staged["source_tree_fingerprint"] == dirty_fingerprint
    assert staged["signing"] == "unsigned"
    assert staged["signature_kind"] == "adhoc"
    assert staged["architecture"] == "arm64"
    assert staged["team_identifier"] == ""
    assert metadata_path.read_text(encoding="utf-8") == '{"commit":"dev"}\n'

    monkeypatch.setenv("MACOS_CODESIGN_IDENTITY", "Oha-Yachiyo Self Signed")
    try:
        builder.build_release_candidate_artifacts(
            channel="experimental",
            allow_dirty_local_rc=True,
            signing_mode="self-signed-app-unsigned-dmg",
        )
    except RuntimeError as exc:
        assert "actual packaged App signing mode" in str(exc)
    else:
        raise AssertionError("caller-provided signing mode must not override inspection")

    changed_provenance = SourceTreeProvenance(
        commit=COMMIT,
        dirty=True,
        source_tree_fingerprint="sha256:" + "e" * 64,
    )
    captures = iter((provenance, changed_provenance))
    monkeypatch.setattr(
        builder,
        "capture_source_tree_provenance",
        lambda _root: next(captures),
    )
    staged.clear()
    try:
        builder.build_release_candidate_artifacts(
            channel="experimental",
            allow_dirty_local_rc=True,
        )
    except RuntimeError as exc:
        assert "source tree changed while release artifacts were being built" in str(exc)
    else:
        raise AssertionError("source provenance drift should block latest staging")
    assert staged == {}

    descriptor = tmp_path / "release" / "Oha-Yachiyo-oha-develop-latest.json"

    def drift_stage(
        _dmg,
        _app,
        _build_metadata,
        *,
        signing_mode,
        signature_kind,
        architecture,
        team_identifier,
    ):
        assert signing_mode == "unsigned"
        assert signature_kind == "adhoc"
        assert architecture == "arm64"
        assert team_identifier == ""
        descriptor.parent.mkdir(parents=True, exist_ok=True)
        descriptor.write_text("{}", encoding="utf-8")
        return {"release_metadata": descriptor}

    captures = iter((provenance, provenance, changed_provenance))
    monkeypatch.setattr(
        builder,
        "capture_source_tree_provenance",
        lambda _root: next(captures),
    )
    monkeypatch.setattr(builder, "_stage_release_channel_artifacts", drift_stage)
    try:
        builder.build_release_candidate_artifacts(
            channel="experimental",
            allow_dirty_local_rc=True,
        )
    except RuntimeError as exc:
        assert "source tree changed while latest-channel artifacts were being staged" in str(exc)
    else:
        raise AssertionError("post-stage provenance drift should fail closed")
    assert not descriptor.exists()
