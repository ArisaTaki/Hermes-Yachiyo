#!/usr/bin/env python3
"""Release provenance and macOS package integrity helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OFFICIAL_RELEASE_REPOSITORY = "kuguya-AI-app-develop/Hermes-Yachiyo"
SOURCE_TREE_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RELEASE_CANDIDATE_SCHEMA = "oha-yachiyo.release-candidate.v1"
RELEASE_CANDIDATE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RELEASE_ARTIFACT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RELEASE_SIGNING_MODES = (
    "unsigned",
    "self-signed-app-unsigned-dmg",
    "developer-id-app-notarized-dmg",
)


@dataclass(frozen=True)
class SourceTreeProvenance:
    commit: str
    dirty: bool
    source_tree_fingerprint: str

    @property
    def release_publishable(self) -> bool:
        return not self.dirty

    def metadata(self) -> dict[str, object]:
        return {
            "dirty": self.dirty,
            "source_tree_fingerprint": self.source_tree_fingerprint,
            "release_publishable": self.release_publishable,
        }


@dataclass(frozen=True)
class MacOSSigningInspection:
    mode: str
    signature_kind: str
    authority: str
    team_identifier: str
    notarization_stapled: bool


@dataclass(frozen=True)
class MacOSAppIdentity:
    bundle_id: str
    version: str
    short_version: str
    executable: str
    signature_kind: str
    team_identifier: str

    def metadata(self) -> dict[str, str]:
        return {
            "bundle_id": self.bundle_id,
            "version": self.version,
            "short_version": self.short_version,
            "executable": self.executable,
            "signature_kind": self.signature_kind,
            "team_identifier": self.team_identifier,
        }


def _normalized_team_identifier(value: str) -> str:
    normalized = str(value or "").strip()
    return "" if normalized.casefold() == "not set" else normalized


def inspect_macos_app_identity(
    app_path: Path,
    *,
    signature_kind: str,
    team_identifier: str,
) -> MacOSAppIdentity:
    """Read the identity embedded in an unpacked macOS App bundle.

    Signing identity is supplied by the content-bound DMG inspection. The App
    bundle supplies the fields used by LaunchServices and the updater ZIP.
    """

    app_path = app_path.resolve(strict=False)
    info_path = app_path / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeError(f"packaged macOS App identity could not be read: {exc}") from exc
    if not isinstance(info, dict):
        raise RuntimeError("packaged macOS App Info.plist must be a dictionary")

    plist_fields = {
        "bundle_id": "CFBundleIdentifier",
        "version": "CFBundleVersion",
        "short_version": "CFBundleShortVersionString",
        "executable": "CFBundleExecutable",
    }
    values = {
        name: str(info.get(plist_name) or "").strip()
        for name, plist_name in plist_fields.items()
    }
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise RuntimeError(
            "packaged macOS App identity is incomplete: " + ", ".join(missing)
        )
    executable = values["executable"]
    if Path(executable).name != executable or not (
        app_path / "Contents" / "MacOS" / executable
    ).is_file():
        raise RuntimeError(
            "packaged macOS App CFBundleExecutable does not identify a bundled executable"
        )
    return MacOSAppIdentity(
        bundle_id=values["bundle_id"],
        version=values["version"],
        short_version=values["short_version"],
        executable=executable,
        signature_kind=str(signature_kind or "").strip(),
        team_identifier=_normalized_team_identifier(team_identifier),
    )


def _release_candidate_json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"release candidate manifest must be canonical JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("release candidate manifest must be a JSON object")
    return decoded


def _required_mapping(
    payload: Mapping[str, Any],
    field: str,
) -> Mapping[str, Any]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise RuntimeError(f"release candidate manifest {field} must be an object")
    return value


def _required_string(payload: Mapping[str, Any], field: str, *, context: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"release candidate manifest {context}.{field} is required")
    if value != value.strip():
        raise RuntimeError(
            f"release candidate manifest {context}.{field} must not contain surrounding whitespace"
        )
    return value


def _validate_release_candidate_payload(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != RELEASE_CANDIDATE_SCHEMA:
        raise RuntimeError(
            f"release candidate manifest schema must be {RELEASE_CANDIDATE_SCHEMA}"
        )

    source = _required_mapping(payload, "source")
    commit = _required_string(source, "commit", context="source")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError(
            "release candidate manifest source.commit must be 40 lowercase hex digits"
        )
    fingerprint = _required_string(source, "fingerprint", context="source")
    if not SOURCE_TREE_FINGERPRINT_RE.fullmatch(fingerprint):
        raise RuntimeError(
            "release candidate manifest source.fingerprint must be sha256 plus 64 lowercase hex digits"
        )
    dirty = source.get("dirty")
    publishable = source.get("release_publishable")
    if not isinstance(dirty, bool):
        raise RuntimeError("release candidate manifest source.dirty must be a boolean")
    if not isinstance(publishable, bool):
        raise RuntimeError(
            "release candidate manifest source.release_publishable must be a boolean"
        )
    if publishable == dirty:
        raise RuntimeError(
            "release candidate manifest source.release_publishable must be the inverse of dirty"
        )

    artifacts = _required_mapping(payload, "artifacts")
    for artifact_name in ("dmg", "zip"):
        artifact = _required_mapping(artifacts, artifact_name)
        filename = _required_string(artifact, "name", context=f"artifacts.{artifact_name}")
        if Path(filename).name != filename:
            raise RuntimeError(
                f"release candidate manifest artifacts.{artifact_name}.name must be a filename"
            )
        digest = _required_string(
            artifact,
            "sha256",
            context=f"artifacts.{artifact_name}",
        )
        if not RELEASE_ARTIFACT_SHA256_RE.fullmatch(digest):
            raise RuntimeError(
                f"release candidate manifest artifacts.{artifact_name}.sha256 must be 64 lowercase hex digits"
            )

    app = _required_mapping(payload, "app")
    for field in (
        "bundle_id",
        "version",
        "short_version",
        "executable",
        "signature_kind",
    ):
        _required_string(app, field, context="app")
    executable = str(app["executable"])
    if Path(executable).name != executable:
        raise RuntimeError(
            "release candidate manifest app.executable must be an executable filename"
        )
    if not isinstance(app.get("team_identifier"), str):
        raise RuntimeError(
            "release candidate manifest app.team_identifier must be a string"
        )
    for optional_field in ("cdhash", "designated_requirement"):
        if optional_field in app:
            _required_string(app, optional_field, context="app")


def canonical_release_candidate_payload(manifest: Mapping[str, Any]) -> bytes:
    """Return stable bytes for the candidate identity, excluding ``candidate_id``."""

    canonical = _release_candidate_json_object(manifest)
    canonical.pop("candidate_id", None)
    _validate_release_candidate_payload(canonical)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def release_candidate_id(manifest: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(
        canonical_release_candidate_payload(manifest)
    ).hexdigest()


def bind_release_candidate_id(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical manifest copy with its content-derived candidate id."""

    bound = _release_candidate_json_object(manifest)
    bound.pop("candidate_id", None)
    bound["candidate_id"] = release_candidate_id(bound)
    return bound


def validate_release_candidate_manifest(manifest: Mapping[str, Any]) -> str:
    """Fail closed when required provenance is missing or the manifest was changed."""

    canonical = _release_candidate_json_object(manifest)
    candidate_id = canonical.get("candidate_id")
    if not isinstance(candidate_id, str) or not RELEASE_CANDIDATE_ID_RE.fullmatch(
        candidate_id
    ):
        raise RuntimeError(
            "release candidate manifest candidate_id must be sha256 plus 64 lowercase hex digits"
        )
    expected = release_candidate_id(canonical)
    if candidate_id != expected:
        raise RuntimeError("release candidate manifest candidate_id does not match its content")
    return expected


def validate_latest_release_candidate_metadata(metadata: Mapping[str, Any]) -> str:
    """Validate the nested manifest and its duplicate latest-JSON candidate id."""

    manifest = metadata.get("release_candidate_manifest")
    if not isinstance(manifest, Mapping):
        raise RuntimeError(
            "release latest JSON release_candidate_manifest must be an object"
        )
    candidate_id = validate_release_candidate_manifest(manifest)
    if metadata.get("candidate_id") != candidate_id:
        raise RuntimeError(
            "release latest JSON candidate_id must match release_candidate_manifest"
        )
    return candidate_id


def macos_signing_inspection_payload(
    dmg_path: Path,
    inspection: MacOSSigningInspection,
) -> dict[str, object]:
    """Return public, content-bound signing evidence for a packaged DMG."""

    return {
        "schema_version": 1,
        "dmg_name": dmg_path.name,
        "dmg_sha256": _sha256_file(dmg_path),
        "signing": inspection.mode,
        "signature_kind": inspection.signature_kind,
        "authority": inspection.authority,
        "team_identifier": inspection.team_identifier,
        "notarization_stapled": inspection.notarization_stapled,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(root: Path, args: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise RuntimeError(f"could not inspect release source provenance: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            "could not inspect release source provenance"
            + (f": {detail}" if detail else f"; git exited with {completed.returncode}")
        )
    return completed.stdout


def _hash_untracked_path(digest: "hashlib._Hash", root: Path, relative_bytes: bytes) -> None:
    relative_text = os.fsdecode(relative_bytes)
    candidate = root / relative_text
    try:
        file_stat = candidate.lstat()
    except OSError as exc:
        raise RuntimeError(
            f"could not fingerprint untracked release source {relative_text!r}: {exc}"
        ) from exc

    digest.update(b"untracked\0")
    digest.update(relative_bytes)
    digest.update(b"\0")
    digest.update(str(stat.S_IMODE(file_stat.st_mode)).encode("ascii"))
    digest.update(b"\0")
    if stat.S_ISLNK(file_stat.st_mode):
        digest.update(b"symlink\0")
        digest.update(os.fsencode(os.readlink(candidate)))
        return
    if not stat.S_ISREG(file_stat.st_mode):
        raise RuntimeError(
            f"unsupported untracked release source type: {relative_text!r}"
        )
    digest.update(b"file\0")
    try:
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeError(
            f"could not fingerprint untracked release source {relative_text!r}: {exc}"
        ) from exc


def capture_source_tree_provenance(root: Path) -> SourceTreeProvenance:
    """Return a content-sensitive fingerprint for HEAD plus working-tree changes."""

    root = root.resolve(strict=False)
    commit = _run_git(root, ["rev-parse", "HEAD"]).decode("ascii", errors="strict").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise RuntimeError("release source provenance requires a 40-character Git HEAD")

    status_bytes = _run_git(
        root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    )
    tracked_diff = _run_git(
        root,
        ["diff", "--binary", "--full-index", "--no-ext-diff", "HEAD", "--"],
    )
    untracked_output = _run_git(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    untracked_paths = sorted(path for path in untracked_output.split(b"\0") if path)

    digest = hashlib.sha256()
    digest.update(b"oha-yachiyo-source-tree-v1\0")
    digest.update(commit.lower().encode("ascii"))
    digest.update(b"\0tracked-diff\0")
    digest.update(tracked_diff)
    for relative_bytes in untracked_paths:
        _hash_untracked_path(digest, root, relative_bytes)
    return SourceTreeProvenance(
        commit=commit.lower(),
        dirty=bool(status_bytes),
        source_tree_fingerprint=f"sha256:{digest.hexdigest()}",
    )


def detect_electron_arch(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["node", "-p", "process.arch"],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(f"could not determine Electron build architecture: {exc}") from exc
    arch = completed.stdout.strip()
    if completed.returncode != 0 or arch not in {"arm64", "x64"}:
        detail = completed.stderr.strip()
        raise RuntimeError(
            "could not determine a supported Electron build architecture"
            + (f": {detail}" if detail else f": {arch or 'unavailable'}")
        )
    return arch


def normalize_macos_lipo_architecture(value: str) -> str:
    """Map ``lipo -archs`` output to Electron's architecture labels."""

    architecture = " ".join(str(value or "").split())
    if architecture == "arm64":
        return "arm64"
    if architecture == "x86_64":
        return "x64"
    raise RuntimeError(
        "packaged macOS app must contain exactly one supported architecture; "
        f"lipo reported {architecture or 'none'}"
    )


def _command(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise RuntimeError(f"could not inspect macOS release signing: {exc}") from exc


def _command_detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def _display_field(display: str, name: str) -> str:
    prefix = f"{name}="
    for line in display.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return ""


def _classify_macos_signing(
    *,
    codesign_verify: subprocess.CompletedProcess[str],
    codesign_display: subprocess.CompletedProcess[str],
    stapler_validate: subprocess.CompletedProcess[str] | None,
) -> MacOSSigningInspection:
    display = "\n".join(
        part for part in (codesign_display.stdout, codesign_display.stderr) if part
    )
    signature = _display_field(display, "Signature")
    authorities = [
        line.removeprefix("Authority=").strip()
        for line in display.splitlines()
        if line.startswith("Authority=")
    ]
    authority = authorities[0] if authorities else ""
    team_identifier = _normalized_team_identifier(
        _display_field(display, "TeamIdentifier")
    )

    if codesign_display.returncode != 0:
        if signature:
            raise RuntimeError("packaged macOS app signature metadata could not be read")
        return MacOSSigningInspection(
            mode="unsigned",
            signature_kind="unsigned",
            authority="",
            team_identifier="",
            notarization_stapled=False,
        )

    if signature.casefold() == "adhoc":
        if codesign_verify.returncode != 0:
            detail = _command_detail(codesign_verify)
            raise RuntimeError(
                "packaged macOS app has an invalid ad-hoc code signature"
                + (f": {detail}" if detail else "")
            )
        return MacOSSigningInspection(
            mode="unsigned",
            signature_kind="adhoc",
            authority="",
            team_identifier="",
            notarization_stapled=False,
        )

    if codesign_verify.returncode != 0:
        detail = _command_detail(codesign_verify)
        raise RuntimeError(
            "packaged macOS app has an invalid code signature"
            + (f": {detail}" if detail else "")
        )

    developer_id = any(value.startswith("Developer ID Application:") for value in authorities)
    if developer_id:
        if stapler_validate is None or stapler_validate.returncode != 0:
            detail = _command_detail(stapler_validate) if stapler_validate is not None else ""
            raise RuntimeError(
                "Developer ID release DMG is missing valid notarization stapling"
                + (f": {detail}" if detail else "")
            )
        return MacOSSigningInspection(
            mode="developer-id-app-notarized-dmg",
            signature_kind="developer-id",
            authority=authority,
            team_identifier=team_identifier,
            notarization_stapled=True,
        )

    if not authorities:
        raise RuntimeError("packaged macOS app signature has no signing authority")
    return MacOSSigningInspection(
        mode="self-signed-app-unsigned-dmg",
        signature_kind="self-signed",
        authority=authority,
        team_identifier=team_identifier,
        notarization_stapled=False,
    )


def inspect_macos_dmg_signing(dmg_path: Path) -> MacOSSigningInspection:
    """Mount a DMG read-only and derive signing mode from its packaged App."""

    if sys.platform != "darwin":
        raise RuntimeError("macOS release signing inspection requires macOS")
    dmg_path = dmg_path.resolve(strict=False)
    if not dmg_path.is_file():
        raise RuntimeError(f"release DMG does not exist: {dmg_path}")

    mount_dir = Path(tempfile.mkdtemp(prefix="oha-yachiyo-signing-"))
    attached = False
    pending_error: BaseException | None = None
    try:
        attach = _command(
            [
                "hdiutil",
                "attach",
                str(dmg_path),
                "-nobrowse",
                "-readonly",
                "-mountpoint",
                str(mount_dir),
                "-quiet",
            ]
        )
        if attach.returncode != 0:
            detail = _command_detail(attach)
            raise RuntimeError(
                "release DMG could not be mounted for signing inspection"
                + (f": {detail}" if detail else "")
            )
        attached = True
        app_paths = sorted(path for path in mount_dir.glob("*.app") if path.is_dir())
        expected_app = mount_dir / "Oha-Yachiyo.app"
        if app_paths != [expected_app]:
            names = ", ".join(path.name for path in app_paths) or "none"
            raise RuntimeError(
                "release DMG must contain exactly one Oha-Yachiyo.app for signing "
                f"inspection; found {names}"
            )

        codesign_verify = _command(
            ["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(expected_app)]
        )
        codesign_display = _command(
            ["codesign", "-dv", "--verbose=4", str(expected_app)]
        )
        display = "\n".join(
            part for part in (codesign_display.stdout, codesign_display.stderr) if part
        )
        developer_id = "Authority=Developer ID Application:" in display
        stapler_validate = (
            _command(["xcrun", "stapler", "validate", str(dmg_path)])
            if developer_id
            else None
        )
        return _classify_macos_signing(
            codesign_verify=codesign_verify,
            codesign_display=codesign_display,
            stapler_validate=stapler_validate,
        )
    except BaseException as exc:
        pending_error = exc
        raise
    finally:
        if attached:
            detach = _command(["hdiutil", "detach", str(mount_dir), "-quiet"])
            if detach.returncode != 0 and pending_error is None:
                detail = _command_detail(detach)
                raise RuntimeError(
                    "release DMG could not be detached after signing inspection"
                    + (f": {detail}" if detail else "")
                )
        shutil.rmtree(mount_dir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a macOS DMG and write content-bound signing evidence."
    )
    parser.add_argument("dmg", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inspection = inspect_macos_dmg_signing(args.dmg)
        payload = macos_signing_inspection_payload(args.dmg, inspection)
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, RuntimeError) as exc:
        print(f"macOS release signing inspection failed: {exc}", file=sys.stderr)
        return 1
    print(args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
