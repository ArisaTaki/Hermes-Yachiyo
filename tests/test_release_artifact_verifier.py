"""Release artifact verifier tests."""

from __future__ import annotations

from scripts import verify_release_artifacts as verifier


def test_verifier_accepts_current_release_files():
    assert verifier.verify_release_artifacts() == []


def test_verifier_checks_release_security_guards():
    assert verifier.verify_release_artifacts(paths=[], check_required_files=False) == []


def test_verifier_reports_legacy_product_tokens(tmp_path):
    release_file = tmp_path / "release.yml"
    release_file.write_text(f"name: {verifier.FORBIDDEN_TOKENS[0]}\n", encoding="utf-8")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_file],
        check_required_files=False,
    )

    assert len(findings) == 1
    assert findings[0].path == release_file
    assert "contains legacy product token" in findings[0].message


def test_verifier_rejects_legacy_build_metadata_filename(tmp_path):
    required = tmp_path / verifier.REQUIRED_FILES[0]
    required.parent.mkdir(parents=True)
    required.write_text('{"name": "Oha-Yachiyo"}\n', encoding="utf-8")
    legacy = tmp_path / verifier.FORBIDDEN_FILES[0]
    legacy.write_text("{}\n", encoding="utf-8")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[required],
    )

    assert any(finding.path == legacy for finding in findings)
    assert any(
        "legacy release metadata filename must not exist" in finding.message
        for finding in findings
    )


def test_verifier_reports_stable_channel_that_still_allows_dev_features(monkeypatch):
    from apps.core import build_metadata

    monkeypatch.setattr(build_metadata, "RELEASE_LIKE_CHANNELS", {"release", "alpha"})

    findings = verifier.verify_release_artifacts(paths=[], check_required_files=False)

    assert any("stable metadata must be treated as release-like" in finding.message for finding in findings)
    assert any("stable metadata must disable development features" in finding.message for finding in findings)
