#!/usr/bin/env python3
"""Build local release-candidate artifacts without leaving tracked metadata dirty."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.release_integrity import (
    MacOSSigningInspection,
    OFFICIAL_RELEASE_REPOSITORY,
    RELEASE_ARTIFACT_SHA256_RE,
    RELEASE_CANDIDATE_SCHEMA,
    RELEASE_SIGNING_MODES,
    SOURCE_TREE_FINGERPRINT_RE,
    bind_release_candidate_id,
    capture_source_tree_provenance,
    detect_electron_arch,
    inspect_macos_app_identity,
    inspect_macos_dmg_signing,
    validate_latest_release_candidate_metadata,
    validate_release_candidate_manifest,
)

BUILD_METADATA_FILE = ROOT / "apps" / "frontend" / "public" / "oha-yachiyo-build.json"
BACKEND_ARTIFACT = ROOT / "dist" / "backend" / (
    "oha-yachiyo-backend.exe" if sys.platform.startswith("win") else "oha-yachiyo-backend"
)
DESKTOP_PROVIDER_ARTIFACT = ROOT / "dist" / "desktop-provider" / (
    "oha-yachiyo-desktop-provider.exe"
    if sys.platform.startswith("win")
    else "oha-yachiyo-desktop-provider"
)
DESKTOP_BRIDGE_ARTIFACT = ROOT / "dist" / "desktop-provider" / (
    "oha-yachiyo-virtual-desktop-bridge.exe"
    if sys.platform.startswith("win")
    else "oha-yachiyo-virtual-desktop-bridge"
)
ELECTRON_DIST_DIR = ROOT / "dist" / "electron"
RELEASE_DIR = ROOT / "release"
MACOS_SIGNING_SCRIPT = "scripts/build_macos_self_signed_dmg.sh"
ADHOC_PACKAGING_SIGNING_MODE = "self-signed-app-unsigned-dmg"


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def _pyinstaller_available() -> bool:
    return importlib.util.find_spec("PyInstaller") is not None


def _ensure_pyinstaller_available() -> None:
    if _pyinstaller_available():
        return
    venv_python = ROOT / ".venv" / "bin" / "python"
    venv_hint = (
        f" Run `{venv_python} scripts/build_release_candidate_artifacts.py ...` "
        "from the project root if the project virtualenv is prepared."
        if venv_python.exists()
        else " Install PyInstaller into the selected Python environment first."
    )
    raise RuntimeError(
        f"PyInstaller is not available for {sys.executable}; cannot build the "
        f"packaged backend.{venv_hint}"
    )


def _restore_metadata(original: bytes | None) -> None:
    if original is None:
        try:
            BUILD_METADATA_FILE.unlink()
        except FileNotFoundError:
            pass
        return
    BUILD_METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    BUILD_METADATA_FILE.write_bytes(original)


def _select_dmg_artifact(*, version: str, arch: str) -> Path:
    candidates = sorted(ELECTRON_DIST_DIR.glob("*.dmg"))
    if len(candidates) != 1:
        names = ", ".join(path.name for path in candidates) or "none"
        raise RuntimeError(
            "expected exactly one Electron DMG under dist/electron; "
            f"found {len(candidates)}: {names}"
        )
    expected_name = f"Oha-Yachiyo-{version}-{arch}.dmg"
    candidate = candidates[0]
    if candidate.name != expected_name:
        raise RuntimeError(
            "Electron DMG filename does not match this build's version and architecture: "
            f"expected {expected_name}, found {candidate.name}"
        )
    return candidate


def _select_app_artifact() -> Path:
    candidates = sorted(
        path
        for path in ELECTRON_DIST_DIR.glob("*/Oha-Yachiyo.app")
        if path.is_dir()
    )
    if len(candidates) != 1:
        names = ", ".join(str(path.relative_to(ELECTRON_DIST_DIR)) for path in candidates)
        raise RuntimeError(
            "expected exactly one unpacked Oha-Yachiyo.app under dist/electron; "
            f"found {len(candidates)}: {names or 'none'}"
        )
    return candidates[0]


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return payload


def _expected_release_signing_mode(explicit: str | None) -> str | None:
    signing_mode = str(explicit or os.getenv("MACOS_SIGNING_MODE") or "").strip()
    if not signing_mode:
        return None
    if not isinstance(signing_mode, str) or signing_mode not in RELEASE_SIGNING_MODES:
        raise RuntimeError(f"unsupported expected release signing mode: {signing_mode}")
    return signing_mode


def _macos_packaging_command(expected_signing_mode: str | None) -> list[str]:
    """Build through the authoritative nested-component signing pipeline.

    Even an otherwise "unsigned" local RC needs an ad-hoc code signature so
    the embedded background helper keeps its dedicated Apple Events and Screen
    Capture entitlements.  electron-builder's generic ad-hoc pass applies the
    Electron entitlements to every nested code object, which is unsafe here.
    """

    configured_identity = str(os.getenv("MACOS_CODESIGN_IDENTITY") or "").strip()
    if expected_signing_mode == "developer-id-app-notarized-dmg":
        if not configured_identity.startswith("Developer ID Application:"):
            raise RuntimeError(
                "Developer ID packaging requires MACOS_CODESIGN_IDENTITY to name "
                "a Developer ID Application identity"
            )
        script_mode = expected_signing_mode
        identity = configured_identity
    elif expected_signing_mode == "self-signed-app-unsigned-dmg":
        if not configured_identity or configured_identity == "-":
            raise RuntimeError(
                "self-signed packaging requires MACOS_CODESIGN_IDENTITY to name "
                "an installed non-ad-hoc signing identity"
            )
        script_mode = expected_signing_mode
        identity = configured_identity
    elif expected_signing_mode == "unsigned":
        script_mode = ADHOC_PACKAGING_SIGNING_MODE
        identity = "-"
    else:
        identity = configured_identity or "-"
        script_mode = (
            "developer-id-app-notarized-dmg"
            if identity.startswith("Developer ID Application:")
            else ADHOC_PACKAGING_SIGNING_MODE
        )
    return [
        "/bin/bash",
        MACOS_SIGNING_SCRIPT,
        identity,
        script_mode,
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_signing_inspection(
    path: Path,
    *,
    dmg_path: Path,
) -> MacOSSigningInspection:
    payload = _read_json_object(path, "macOS signing inspection")
    if payload.get("schema_version") != 1:
        raise RuntimeError("macOS signing inspection schema_version must be 1")
    if payload.get("dmg_name") != dmg_path.name:
        raise RuntimeError(
            "macOS signing inspection DMG name does not match the staged artifact"
        )
    inspected_digest = payload.get("dmg_sha256")
    if not isinstance(inspected_digest, str) or not RELEASE_ARTIFACT_SHA256_RE.fullmatch(
        inspected_digest
    ):
        raise RuntimeError(
            "macOS signing inspection dmg_sha256 must be 64 lowercase hex digits"
        )
    actual_digest = _sha256_file(dmg_path)
    if inspected_digest != actual_digest:
        raise RuntimeError(
            "macOS signing inspection SHA256 does not match the staged DMG"
        )
    signing_mode = payload.get("signing")
    if not isinstance(signing_mode, str) or signing_mode not in RELEASE_SIGNING_MODES:
        raise RuntimeError(
            "macOS signing inspection has unsupported signing mode: "
            f"{signing_mode or 'missing'}"
        )
    signature_kind = payload.get("signature_kind")
    if (
        not isinstance(signature_kind, str)
        or not signature_kind
        or signature_kind != signature_kind.strip()
    ):
        raise RuntimeError("macOS signing inspection signature_kind is required")
    for field in ("authority", "team_identifier"):
        if not isinstance(payload.get(field), str):
            raise RuntimeError(f"macOS signing inspection {field} must be a string")
    notarization_stapled = payload.get("notarization_stapled")
    if not isinstance(notarization_stapled, bool):
        raise RuntimeError(
            "macOS signing inspection notarization_stapled must be a boolean"
        )
    if notarization_stapled != (
        signing_mode == "developer-id-app-notarized-dmg"
    ):
        raise RuntimeError(
            "macOS signing inspection notarization evidence is incompatible with "
            f"signing mode {signing_mode}"
        )
    return MacOSSigningInspection(
        mode=signing_mode,
        signature_kind=signature_kind,
        authority=str(payload["authority"]),
        team_identifier=str(payload["team_identifier"]),
        notarization_stapled=notarization_stapled,
    )


def _stage_release_channel_artifacts(
    dmg_path: Path,
    app_path: Path,
    build_metadata: dict[str, Any],
    *,
    signing_mode: str,
    signature_kind: str,
    architecture: str,
    team_identifier: str = "",
) -> dict[str, Path]:
    if not dmg_path.is_file():
        raise RuntimeError(f"Electron DMG was not produced: {dmg_path}")

    required_strings = (
        "name",
        "channel",
        "branch",
        "source_branch",
        "version",
        "base_version",
        "commit",
        "short_commit",
        "repository",
        "built_at",
        "source_tree_fingerprint",
    )
    missing = [
        field
        for field in required_strings
        if not str(build_metadata.get(field) or "").strip()
    ]
    for field in ("build_number", "run_number"):
        if not isinstance(build_metadata.get(field), int):
            missing.append(field)
    if missing:
        raise RuntimeError(
            "prepared app build metadata is incomplete: " + ", ".join(sorted(missing))
        )
    if not isinstance(build_metadata.get("dirty"), bool):
        raise RuntimeError("prepared app build metadata dirty must be a boolean")
    if not isinstance(build_metadata.get("release_publishable"), bool):
        raise RuntimeError(
            "prepared app build metadata release_publishable must be a boolean"
        )
    dirty = bool(build_metadata["dirty"])
    release_publishable = bool(build_metadata["release_publishable"])
    if release_publishable == dirty:
        raise RuntimeError(
            "prepared app build metadata release_publishable must be the inverse of dirty"
        )
    source_tree_fingerprint = str(build_metadata["source_tree_fingerprint"]).lower()
    if not SOURCE_TREE_FINGERPRINT_RE.fullmatch(source_tree_fingerprint):
        raise RuntimeError(
            "prepared app build metadata source_tree_fingerprint is invalid"
        )
    if architecture not in {"arm64", "x64"}:
        raise RuntimeError(f"unsupported Electron release architecture: {architecture}")
    expected_signature_kinds = {
        "unsigned": {"unsigned", "adhoc"},
        "self-signed-app-unsigned-dmg": {"self-signed"},
        "developer-id-app-notarized-dmg": {"developer-id"},
    }
    if signature_kind not in expected_signature_kinds.get(signing_mode, set()):
        raise RuntimeError(
            "detected macOS signature kind is incompatible with signing mode: "
            f"{signing_mode}/{signature_kind}"
        )

    app_identity = inspect_macos_app_identity(
        app_path,
        signature_kind=signature_kind,
        team_identifier=team_identifier,
    )

    channel = str(build_metadata["channel"])
    branch = str(build_metadata["branch"])
    version = str(build_metadata["version"])
    short_commit = str(build_metadata["short_commit"])
    build_number = int(build_metadata["build_number"])
    run_number = int(build_metadata["run_number"])
    repository = str(build_metadata["repository"])
    if app_identity.short_version != version:
        raise RuntimeError(
            "packaged macOS App short version does not match prepared build metadata: "
            f"expected {version}, found {app_identity.short_version}"
        )
    tag = f"{channel}-v{version}-build.{build_number}-{short_commit}"
    run_id = str(os.getenv("GITHUB_RUN_ID") or run_number).strip()
    if not run_id.isdigit():
        raise RuntimeError("GITHUB_RUN_ID must be numeric for release metadata")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    changelog_json_path = RELEASE_DIR / "changelog.json"
    changelog_markdown_path = RELEASE_DIR / "changelog.md"
    _run(
        [
            sys.executable,
            "scripts/generate_release_changelog.py",
            "--channel",
            channel,
            "--tag",
            tag,
            "--repository",
            repository,
            "--output-json",
            str(changelog_json_path.relative_to(ROOT)),
            "--output-markdown",
            str(changelog_markdown_path.relative_to(ROOT)),
        ]
    )
    changelog = _read_json_object(changelog_json_path, "release changelog")

    latest_dmg_name = f"Oha-Yachiyo-{branch}-latest.dmg"
    latest_zip_name = f"Oha-Yachiyo-{branch}-latest-{architecture}.zip"
    latest_json_name = f"Oha-Yachiyo-{branch}-latest.json"
    latest_dmg_path = RELEASE_DIR / latest_dmg_name
    latest_checksum_path = RELEASE_DIR / f"{latest_dmg_name}.sha256"
    latest_zip_path = RELEASE_DIR / latest_zip_name
    latest_zip_checksum_path = RELEASE_DIR / f"{latest_zip_name}.sha256"
    latest_json_path = RELEASE_DIR / latest_json_name
    shutil.copy2(dmg_path, latest_dmg_path)
    digest = _sha256_file(latest_dmg_path)
    latest_checksum_path.write_text(
        f"{digest}  {latest_dmg_name}\n",
        encoding="utf-8",
    )
    latest_zip_path.unlink(missing_ok=True)
    _run(
        [
            "ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app_path),
            str(latest_zip_path),
        ]
    )
    if not latest_zip_path.is_file():
        raise RuntimeError(f"Electron app ZIP was not produced: {latest_zip_path}")
    zip_digest = _sha256_file(latest_zip_path)
    latest_zip_checksum_path.write_text(
        f"{zip_digest}  {latest_zip_name}\n",
        encoding="utf-8",
    )

    release_candidate_manifest = bind_release_candidate_id(
        {
            "schema": RELEASE_CANDIDATE_SCHEMA,
            "source": {
                "commit": str(build_metadata["commit"]).lower(),
                "dirty": dirty,
                "fingerprint": source_tree_fingerprint,
                "release_publishable": release_publishable,
            },
            "artifacts": {
                "dmg": {"name": latest_dmg_name, "sha256": digest},
                "zip": {"name": latest_zip_name, "sha256": zip_digest},
            },
            "app": app_identity.metadata(),
        }
    )
    candidate_id = validate_release_candidate_manifest(release_candidate_manifest)

    latest_tag = f"{branch}-latest"
    release_metadata = {
        "name": str(build_metadata["name"]),
        "channel": channel,
        "branch": branch,
        "source_branch": str(build_metadata["source_branch"]),
        "version": version,
        "base_version": str(build_metadata["base_version"]),
        "commit": str(build_metadata["commit"]),
        "short_commit": short_commit,
        "build_number": build_number,
        "run_number": run_number,
        "run_id": run_id,
        "tag": tag,
        "signing": signing_mode,
        "signature_kind": signature_kind,
        "architecture": architecture,
        "dmg_name": latest_dmg_name,
        "sha256": digest,
        "download_url": (
            f"https://github.com/{repository}/releases/download/"
            f"{latest_tag}/{latest_dmg_name}"
        ),
        "zip_name": latest_zip_name,
        "zip_sha256": zip_digest,
        "zip_download_url": (
            f"https://github.com/{repository}/releases/download/"
            f"{latest_tag}/{latest_zip_name}"
        ),
        "latest_json_url": (
            f"https://github.com/{repository}/releases/download/"
            f"{latest_tag}/{latest_json_name}"
        ),
        "published_at": str(build_metadata["built_at"]),
        "changelog": changelog,
        "dirty": dirty,
        "source_tree_fingerprint": source_tree_fingerprint,
        "release_publishable": release_publishable,
        "candidate_id": candidate_id,
        "release_candidate_manifest": release_candidate_manifest,
    }
    validate_latest_release_candidate_metadata(release_metadata)
    latest_json_path.write_text(
        json.dumps(release_metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "release_dmg": latest_dmg_path,
        "release_checksum": latest_checksum_path,
        "release_zip": latest_zip_path,
        "release_zip_checksum": latest_zip_checksum_path,
        "release_metadata": latest_json_path,
        "release_changelog": changelog_json_path,
    }


def stage_existing_release_candidate_artifacts(
    *,
    dmg_path: Path,
    app_path: Path,
    build_metadata_path: Path,
    signing_inspection_path: Path,
    architecture: str,
    signing_mode: str | None = None,
    allow_dirty_local_rc: bool = False,
) -> dict[str, Path]:
    """Stage already-built macOS artifacts through the canonical RC manifest path."""

    if not dmg_path.is_file():
        raise RuntimeError(f"existing Electron DMG was not found: {dmg_path}")
    if not app_path.is_dir():
        raise RuntimeError(f"existing Electron App was not found: {app_path}")
    build_metadata = _read_json_object(
        build_metadata_path,
        "prepared app build metadata",
    )
    expected_dmg_name = (
        f"Oha-Yachiyo-{str(build_metadata.get('version') or '').strip()}-"
        f"{architecture}.dmg"
    )
    if dmg_path.name != expected_dmg_name:
        raise RuntimeError(
            "existing Electron DMG filename does not match build metadata and architecture: "
            f"expected {expected_dmg_name}, found {dmg_path.name}"
        )
    if bool(build_metadata.get("dirty")) and not allow_dirty_local_rc:
        raise RuntimeError(
            "prepared app build metadata is dirty; public/latest staging requires "
            "publishable source provenance"
        )
    inspection = _read_signing_inspection(
        signing_inspection_path,
        dmg_path=dmg_path,
    )
    expected_signing_mode = _expected_release_signing_mode(signing_mode)
    if (
        expected_signing_mode is not None
        and inspection.mode != expected_signing_mode
    ):
        raise RuntimeError(
            "actual packaged App signing mode does not match the expected mode: "
            f"expected {expected_signing_mode}, detected {inspection.mode}"
        )
    return _stage_release_channel_artifacts(
        dmg_path,
        app_path,
        build_metadata,
        signing_mode=inspection.mode,
        signature_kind=inspection.signature_kind,
        architecture=architecture,
        team_identifier=inspection.team_identifier,
    )


def build_release_candidate_artifacts(
    *,
    channel: str,
    repository: str | None = None,
    clean_backend: bool = True,
    clean_desktop_provider: bool = True,
    clean_electron: bool = True,
    built_at: str | None = None,
    signing_mode: str | None = None,
    allow_dirty_local_rc: bool = False,
) -> dict[str, Path]:
    _ensure_pyinstaller_available()
    source_provenance = capture_source_tree_provenance(ROOT)
    if source_provenance.dirty and not allow_dirty_local_rc:
        raise RuntimeError(
            "source tree is dirty; commit or discard source changes before building "
            "a publishable latest RC, or pass --allow-dirty-local-rc for an explicitly "
            "non-publishable local inspection build"
        )
    expected_signing_mode = _expected_release_signing_mode(signing_mode)
    release_repository = repository or OFFICIAL_RELEASE_REPOSITORY
    original_metadata = (
        BUILD_METADATA_FILE.read_bytes() if BUILD_METADATA_FILE.exists() else None
    )
    build_metadata: dict[str, Any]
    dmg_artifact: Path
    app_artifact: Path
    detected_signing_mode: str
    detected_signature_kind: str
    electron_arch: str
    try:
        metadata_command = [
            sys.executable,
            "scripts/prepare_app_build_metadata.py",
            "--channel",
            channel,
        ]
        metadata_command.extend(["--repository", release_repository])
        if built_at:
            metadata_command.extend(["--built-at", built_at])
        metadata_command.extend(
            [
                "--source-tree-fingerprint",
                source_provenance.source_tree_fingerprint,
                "--source-dirty" if source_provenance.dirty else "--source-clean",
            ]
        )
        _run(metadata_command)
        build_metadata = _read_json_object(
            BUILD_METADATA_FILE,
            "prepared app build metadata",
        )
        metadata_commit = str(build_metadata.get("commit") or "").strip().lower()
        if metadata_commit != source_provenance.commit:
            raise RuntimeError(
                "prepared app build metadata commit does not match source provenance HEAD"
            )
        for field_name, expected_value in source_provenance.metadata().items():
            if build_metadata.get(field_name) != expected_value:
                raise RuntimeError(
                    "prepared app build metadata does not match captured source "
                    f"provenance field {field_name}"
                )

        backend_command = [sys.executable, "scripts/build_backend.py"]
        if clean_backend:
            backend_command.append("--clean")
        _run(backend_command)

        desktop_provider_command = [
            sys.executable,
            "scripts/build_virtual_desktop_guest.py",
        ]
        if clean_desktop_provider:
            desktop_provider_command.append("--clean")
        _run(desktop_provider_command)

        if clean_electron:
            shutil.rmtree(ELECTRON_DIST_DIR, ignore_errors=True)
        _run(_macos_packaging_command(expected_signing_mode))
        electron_arch = detect_electron_arch(ROOT)
        dmg_artifact = _select_dmg_artifact(
            version=str(build_metadata.get("version") or "").strip(),
            arch=electron_arch,
        )
        app_artifact = _select_app_artifact()
        signing_inspection = inspect_macos_dmg_signing(dmg_artifact)
        detected_signing_mode = signing_inspection.mode
        detected_signature_kind = signing_inspection.signature_kind
        if (
            expected_signing_mode is not None
            and detected_signing_mode != expected_signing_mode
        ):
            raise RuntimeError(
                "actual packaged App signing mode does not match the expected mode: "
                f"expected {expected_signing_mode}, detected {detected_signing_mode}"
            )
    finally:
        _restore_metadata(original_metadata)

    post_build_provenance = capture_source_tree_provenance(ROOT)
    if post_build_provenance != source_provenance:
        raise RuntimeError(
            "source tree changed while release artifacts were being built; refusing "
            "to stage latest-channel artifacts"
        )
    release_artifacts = _stage_release_channel_artifacts(
        dmg_artifact,
        app_artifact,
        build_metadata,
        signing_mode=detected_signing_mode,
        signature_kind=detected_signature_kind,
        architecture=electron_arch,
        team_identifier=signing_inspection.team_identifier,
    )
    post_stage_provenance = capture_source_tree_provenance(ROOT)
    if post_stage_provenance != source_provenance:
        # Never leave a publishable latest descriptor behind after provenance drift.
        release_artifacts["release_metadata"].unlink(missing_ok=True)
        raise RuntimeError(
            "source tree changed while latest-channel artifacts were being staged"
        )

    return {
        "backend": BACKEND_ARTIFACT,
        "desktop_provider": DESKTOP_PROVIDER_ARTIFACT,
        "desktop_bridge": DESKTOP_BRIDGE_ARTIFACT,
        "dmg": dmg_artifact,
        "app": app_artifact,
        "metadata": BUILD_METADATA_FILE,
        **release_artifacts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-existing",
        action="store_true",
        help=(
            "Stage an existing DMG/App pair and prepared build metadata without "
            "rebuilding backend, desktop provider, or Electron."
        ),
    )
    parser.add_argument("--dmg", type=Path, help="Existing Electron DMG to stage.")
    parser.add_argument("--app", type=Path, help="Existing unpacked Oha-Yachiyo.app.")
    parser.add_argument(
        "--build-metadata",
        type=Path,
        help="Prepared oha-yachiyo-build.json embedded in the packaged App.",
    )
    parser.add_argument(
        "--signing-inspection-json",
        type=Path,
        help="Content-bound JSON emitted by scripts/release_integrity.py.",
    )
    parser.add_argument(
        "--architecture",
        choices=("arm64", "x64"),
        help="Electron architecture for an existing artifact pair.",
    )
    parser.add_argument(
        "--channel",
        default="experimental",
        choices=("stable", "alpha", "experimental"),
        help="Release channel metadata to embed in the packaged app.",
    )
    parser.add_argument(
        "--repository",
        help="GitHub owner/repo used for latest JSON URLs.",
    )
    parser.add_argument(
        "--built-at",
        help="Optional ISO timestamp for reproducible metadata tests.",
    )
    parser.add_argument(
        "--signing-mode",
        choices=RELEASE_SIGNING_MODES,
        help=(
            "Expected signing mode assertion. The recorded mode is always detected "
            "from the packaged App inside the DMG."
        ),
    )
    parser.add_argument(
        "--allow-dirty-local-rc",
        action="store_true",
        help=(
            "Allow a dirty working tree only for an explicitly non-publishable local "
            "RC inspection build. Public/latest/final signoff will reject it."
        ),
    )
    parser.add_argument(
        "--no-clean-backend",
        action="store_true",
        help="Do not pass --clean to scripts/build_backend.py.",
    )
    parser.add_argument(
        "--no-clean-desktop-provider",
        action="store_true",
        help="Do not pass --clean to the virtual desktop guest provider build.",
    )
    parser.add_argument(
        "--no-clean-electron",
        action="store_true",
        help="Do not remove old dist/electron output before running electron-builder.",
    )
    args = parser.parse_args(argv)
    try:
        if args.stage_existing:
            stage_inputs = {
                "--dmg": args.dmg,
                "--app": args.app,
                "--build-metadata": args.build_metadata,
                "--signing-inspection-json": args.signing_inspection_json,
                "--architecture": args.architecture,
            }
            missing = [name for name, value in stage_inputs.items() if value is None]
            if missing:
                parser.error(
                    "--stage-existing requires " + ", ".join(missing)
                )
            artifacts = stage_existing_release_candidate_artifacts(
                dmg_path=(args.dmg if args.dmg.is_absolute() else ROOT / args.dmg),
                app_path=(args.app if args.app.is_absolute() else ROOT / args.app),
                build_metadata_path=(
                    args.build_metadata
                    if args.build_metadata.is_absolute()
                    else ROOT / args.build_metadata
                ),
                signing_inspection_path=(
                    args.signing_inspection_json
                    if args.signing_inspection_json.is_absolute()
                    else ROOT / args.signing_inspection_json
                ),
                architecture=args.architecture,
                signing_mode=args.signing_mode,
                allow_dirty_local_rc=args.allow_dirty_local_rc,
            )
        else:
            artifacts = build_release_candidate_artifacts(
                channel=args.channel,
                repository=args.repository,
                clean_backend=not args.no_clean_backend,
                clean_desktop_provider=not args.no_clean_desktop_provider,
                clean_electron=not args.no_clean_electron,
                built_at=args.built_at,
                signing_mode=args.signing_mode,
                allow_dirty_local_rc=args.allow_dirty_local_rc,
            )
    except RuntimeError as exc:
        print(f"release candidate artifact build failed: {exc}", file=sys.stderr)
        return 1
    if not args.stage_existing:
        print(f"packaged backend: {artifacts['backend']}")
        print(f"virtual desktop guest provider: {artifacts['desktop_provider']}")
        print(f"virtual desktop host bridge: {artifacts['desktop_bridge']}")
        print(f"Electron DMG: {artifacts['dmg']}")
    print(f"release latest DMG: {artifacts['release_dmg']}")
    print(f"release latest app ZIP: {artifacts['release_zip']}")
    print(f"release latest metadata: {artifacts['release_metadata']}")
    if not args.stage_existing:
        print(f"restored tracked build metadata: {artifacts['metadata']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
