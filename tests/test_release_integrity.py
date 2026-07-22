"""Release provenance and signing evidence tests."""

from __future__ import annotations

import hashlib
import json
import plistlib
import subprocess

from scripts import release_integrity as integrity


def _completed(returncode: int, *, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _release_candidate_payload() -> dict[str, object]:
    return {
        "schema": integrity.RELEASE_CANDIDATE_SCHEMA,
        "source": {
            "commit": "a" * 40,
            "dirty": False,
            "fingerprint": "sha256:" + "b" * 64,
            "release_publishable": True,
        },
        "artifacts": {
            "dmg": {"name": "Oha-Yachiyo-main-latest.dmg", "sha256": "c" * 64},
            "zip": {
                "name": "Oha-Yachiyo-main-latest-arm64.zip",
                "sha256": "d" * 64,
            },
        },
        "app": {
            "bundle_id": "io.github.arisataki.oha-yachiyo",
            "version": "0.4.0",
            "short_version": "0.4.0",
            "executable": "Oha-Yachiyo",
            "signature_kind": "adhoc",
            "team_identifier": "",
        },
    }


def test_source_tree_fingerprint_tracks_untracked_content(monkeypatch, tmp_path):
    source = tmp_path / "new-source.txt"
    source.write_text("one", encoding="utf-8")
    commit = b"a" * 40

    def fake_git(_root, args):
        if args == ["rev-parse", "HEAD"]:
            return commit + b"\n"
        if args[:2] == ["status", "--porcelain=v1"]:
            return b"?? new-source.txt\0"
        if args[:2] == ["diff", "--binary"]:
            return b""
        if args[:3] == ["ls-files", "--others", "--exclude-standard"]:
            return b"new-source.txt\0"
        raise AssertionError(args)

    monkeypatch.setattr(integrity, "_run_git", fake_git)
    first = integrity.capture_source_tree_provenance(tmp_path)
    source.write_text("two", encoding="utf-8")
    second = integrity.capture_source_tree_provenance(tmp_path)

    assert first.dirty is True
    assert first.release_publishable is False
    assert first.source_tree_fingerprint.startswith("sha256:")
    assert first.source_tree_fingerprint != second.source_tree_fingerprint


def test_release_candidate_id_is_stable_and_excludes_candidate_id():
    payload = _release_candidate_payload()
    reordered = {
        "app": payload["app"],
        "artifacts": payload["artifacts"],
        "source": payload["source"],
        "schema": payload["schema"],
    }

    first = integrity.bind_release_candidate_id(payload)
    second = integrity.bind_release_candidate_id(reordered)

    assert first["candidate_id"] == second["candidate_id"]
    assert first["candidate_id"] == integrity.release_candidate_id(first)
    changed_id_only = dict(first)
    changed_id_only["candidate_id"] = "sha256:" + "f" * 64
    assert integrity.release_candidate_id(changed_id_only) == first["candidate_id"]
    assert b"candidate_id" not in integrity.canonical_release_candidate_payload(first)


def test_release_candidate_manifest_rejects_missing_and_tampered_fields():
    manifest = integrity.bind_release_candidate_id(_release_candidate_payload())
    assert integrity.validate_release_candidate_manifest(manifest) == manifest["candidate_id"]

    missing = json.loads(json.dumps(manifest))
    del missing["app"]["executable"]
    try:
        integrity.validate_release_candidate_manifest(missing)
    except RuntimeError as exc:
        assert "app.executable is required" in str(exc)
    else:
        raise AssertionError("missing App identity must fail closed")

    tampered = json.loads(json.dumps(manifest))
    tampered["artifacts"]["zip"]["sha256"] = "e" * 64
    try:
        integrity.validate_release_candidate_manifest(tampered)
    except RuntimeError as exc:
        assert "candidate_id does not match its content" in str(exc)
    else:
        raise AssertionError("tampered artifact identity must fail closed")


def test_latest_release_candidate_metadata_binds_nested_manifest():
    manifest = integrity.bind_release_candidate_id(_release_candidate_payload())
    latest = {
        "candidate_id": manifest["candidate_id"],
        "release_candidate_manifest": manifest,
    }
    assert (
        integrity.validate_latest_release_candidate_metadata(latest)
        == manifest["candidate_id"]
    )

    latest["candidate_id"] = "sha256:" + "f" * 64
    try:
        integrity.validate_latest_release_candidate_metadata(latest)
    except RuntimeError as exc:
        assert "must match release_candidate_manifest" in str(exc)
    else:
        raise AssertionError("latest JSON candidate id mismatch must fail closed")


def test_macos_app_identity_reads_required_plist_and_executable(tmp_path):
    app = tmp_path / "Oha-Yachiyo.app"
    executable_dir = app / "Contents" / "MacOS"
    executable_dir.mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": "io.github.arisataki.oha-yachiyo",
                "CFBundleVersion": "17",
                "CFBundleShortVersionString": "0.4.0",
                "CFBundleExecutable": "Oha-Yachiyo",
            },
            handle,
        )
    (executable_dir / "Oha-Yachiyo").write_bytes(b"Mach-O")

    result = integrity.inspect_macos_app_identity(
        app,
        signature_kind="developer-id",
        team_identifier="TEAM123456",
    )

    assert result.metadata() == {
        "bundle_id": "io.github.arisataki.oha-yachiyo",
        "version": "17",
        "short_version": "0.4.0",
        "executable": "Oha-Yachiyo",
        "signature_kind": "developer-id",
        "team_identifier": "TEAM123456",
    }


def test_signing_classifier_maps_adhoc_to_unsigned():
    result = integrity._classify_macos_signing(
        codesign_verify=_completed(0),
        codesign_display=_completed(
            0,
            stderr="Signature=adhoc\nTeamIdentifier=not set\n",
        ),
        stapler_validate=None,
    )

    assert result.mode == "unsigned"
    assert result.signature_kind == "adhoc"


def test_signing_classifier_rejects_invalid_adhoc_signature():
    try:
        integrity._classify_macos_signing(
            codesign_verify=_completed(1, stderr="invalid signature"),
            codesign_display=_completed(
                0,
                stderr="Signature=adhoc\nTeamIdentifier=not set\n",
            ),
            stapler_validate=None,
        )
    except RuntimeError as exc:
        assert "invalid ad-hoc code signature" in str(exc)
        assert "invalid signature" in str(exc)
    else:
        raise AssertionError("an invalid ad-hoc signature must fail closed")


def test_lipo_architecture_normalization_matches_electron_labels():
    assert integrity.normalize_macos_lipo_architecture("arm64\n") == "arm64"
    assert integrity.normalize_macos_lipo_architecture("x86_64\n") == "x64"

    for unsupported in ("", "i386", "x86_64 arm64"):
        try:
            integrity.normalize_macos_lipo_architecture(unsupported)
        except RuntimeError as exc:
            assert "exactly one supported architecture" in str(exc)
        else:
            raise AssertionError(f"unsupported lipo architecture should fail: {unsupported!r}")


def test_official_release_repository_matches_current_github_repository():
    assert (
        integrity.OFFICIAL_RELEASE_REPOSITORY
        == "kuguya-AI-app-develop/Hermes-Yachiyo"
    )


def test_signing_inspection_cli_writes_content_bound_adhoc_evidence(
    monkeypatch,
    tmp_path,
):
    dmg = tmp_path / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg.write_bytes(b"final dmg bytes")
    output = tmp_path / "release" / "macos-signing-inspection.json"
    monkeypatch.setattr(
        integrity,
        "inspect_macos_dmg_signing",
        lambda _path: integrity.MacOSSigningInspection(
            mode="unsigned",
            signature_kind="adhoc",
            authority="",
            team_identifier="",
            notarization_stapled=False,
        ),
    )

    assert integrity.main([str(dmg), "--output-json", str(output)]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "dmg_name": dmg.name,
        "dmg_sha256": hashlib.sha256(b"final dmg bytes").hexdigest(),
        "signing": "unsigned",
        "signature_kind": "adhoc",
        "authority": "",
        "team_identifier": "",
        "notarization_stapled": False,
    }


def test_signing_classifier_requires_valid_authority_for_self_signed_app():
    result = integrity._classify_macos_signing(
        codesign_verify=_completed(0),
        codesign_display=_completed(
            0,
            stderr="Authority=Oha-Yachiyo Self Signed\nTeamIdentifier=LOCALTEAM\n",
        ),
        stapler_validate=None,
    )

    assert result.mode == "self-signed-app-unsigned-dmg"
    assert result.authority == "Oha-Yachiyo Self Signed"


def test_signing_classifier_normalizes_missing_self_signed_team_identifier():
    result = integrity._classify_macos_signing(
        codesign_verify=_completed(0),
        codesign_display=_completed(
            0,
            stderr=(
                "Authority=Hermes-Yachiyo Self Signed\n"
                "TeamIdentifier=not set\n"
            ),
        ),
        stapler_validate=None,
    )

    assert result.mode == "self-signed-app-unsigned-dmg"
    assert result.signature_kind == "self-signed"
    assert result.team_identifier == ""


def test_signing_classifier_requires_notarized_developer_id_dmg():
    display = (
        "Authority=Developer ID Application: Example Corp (TEAM123456)\n"
        "TeamIdentifier=TEAM123456\n"
    )
    try:
        integrity._classify_macos_signing(
            codesign_verify=_completed(0),
            codesign_display=_completed(0, stderr=display),
            stapler_validate=_completed(1, stderr="ticket missing"),
        )
    except RuntimeError as exc:
        assert "notarization stapling" in str(exc)
    else:
        raise AssertionError("Developer ID without notarization should fail")

    result = integrity._classify_macos_signing(
        codesign_verify=_completed(0),
        codesign_display=_completed(0, stderr=display),
        stapler_validate=_completed(0, stdout="validated"),
    )
    assert result.mode == "developer-id-app-notarized-dmg"
    assert result.notarization_stapled is True


def test_dmg_signing_inspection_mounts_exact_app_and_detects_adhoc(
    monkeypatch,
    tmp_path,
):
    dmg = tmp_path / "Oha-Yachiyo-0.4.0-arm64.dmg"
    dmg.write_bytes(b"fake dmg")
    commands: list[list[str]] = []
    monkeypatch.setattr(integrity.sys, "platform", "darwin")

    def fake_command(command: list[str]):
        commands.append(command)
        if command[:2] == ["hdiutil", "attach"]:
            mount_dir = command[command.index("-mountpoint") + 1]
            (integrity.Path(mount_dir) / "Oha-Yachiyo.app").mkdir()
            return _completed(0)
        if command[:2] == ["codesign", "--verify"]:
            return _completed(0)
        if command[:2] == ["codesign", "-dv"]:
            return _completed(0, stderr="Signature=adhoc\nTeamIdentifier=not set\n")
        if command[:2] == ["hdiutil", "detach"]:
            return _completed(0)
        raise AssertionError(command)

    monkeypatch.setattr(integrity, "_command", fake_command)
    result = integrity.inspect_macos_dmg_signing(dmg)

    assert result.mode == "unsigned"
    assert any(command[:2] == ["hdiutil", "attach"] for command in commands)
    assert any(command[:2] == ["hdiutil", "detach"] for command in commands)
