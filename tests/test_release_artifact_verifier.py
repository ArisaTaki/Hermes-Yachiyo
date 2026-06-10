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
        check_release_security_guards=False,
    )

    assert len(findings) == 1
    assert findings[0].path == release_file
    assert "contains legacy product token" in findings[0].message


def test_verifier_rejects_non_utf8_targets_by_default(tmp_path):
    artifact = tmp_path / "Oha-Yachiyo-test.dmg"
    artifact.write_bytes(b"\xff\x00Oha-Yachiyo\xfe")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[artifact],
        check_required_files=False,
        check_release_security_guards=False,
    )

    assert findings == [
        verifier.Finding(artifact, "release verification target is not UTF-8 text")
    ]


def test_verifier_binary_mode_scans_legacy_tokens(tmp_path):
    clean_artifact = tmp_path / "Oha-Yachiyo-clean.dmg"
    clean_artifact.write_bytes(b"\xff\x00Oha-Yachiyo\xfe")
    legacy_artifact = tmp_path / "Oha-Yachiyo-legacy.dmg"
    legacy_artifact.write_bytes(b"\x00" + verifier.FORBIDDEN_TOKENS[1].encode("utf-8") + b"\x00\xff")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[clean_artifact, legacy_artifact],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    assert findings == [
        verifier.Finding(
            legacy_artifact,
            f"contains legacy product token {verifier.FORBIDDEN_TOKENS[1]!r}",
        )
    ]


def test_verifier_binary_mode_scans_nested_directories(tmp_path):
    resources = tmp_path / "Oha-Yachiyo.app" / "Contents" / "Resources"
    backend = resources / "backend" / "oha-yachiyo-backend"
    backend.parent.mkdir(parents=True)
    backend.write_bytes(b"\x00" + verifier.FORBIDDEN_TOKENS[0].encode("utf-8") + b"\xff")
    clean_asar = resources / "app.asar"
    clean_asar.write_bytes(b"\xff\x00Oha-Yachiyo\xfe")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[resources],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    assert findings == [
        verifier.Finding(
            backend,
            f"contains legacy product token {verifier.FORBIDDEN_TOKENS[0]!r}",
        )
    ]


def test_verifier_requires_packaging_to_exclude_rebuilt_node_pty(tmp_path):
    config = tmp_path / verifier.PACKAGING_CONFIG_FILE
    config.parent.mkdir(parents=True)
    config.write_text(
        "productName: Oha-Yachiyo\n"
        "files:\n"
        "  - node_modules/node-pty/lib/**\n"
        "  - node_modules/node-pty/prebuilds/darwin-arm64/**\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_packaging_guards(tmp_path)

    assert findings == [
        verifier.Finding(
            config,
            "macOS release packaging must disable local native dependency rebuilds",
        ),
        verifier.Finding(
            config,
            "macOS release packaging must exclude rebuilt node-pty native artifacts",
        ),
    ]


def test_verifier_requires_release_workflow_binary_scans_packaged_outputs(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Build macOS DMG\n"
        "jobs:\n"
        "  package-macos:\n"
        "    steps:\n"
        "      - name: Verify release-facing product identity and security guards\n"
        "        run: python scripts/verify_release_artifacts.py\n"
        "      - name: Install Python dependencies\n"
        "        run: python -m pip install -e .\n"
        "      - name: Build Electron DMG\n"
        "        run: npm --prefix apps/frontend run dist:mac\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must scan the packaged backend binary" in messages
    assert "macOS release workflow must discover packaged app resource directories" in messages
    assert "macOS release workflow must binary-scan packaged app resources" in messages
    assert "macOS release workflow must binary-scan final release artifacts" in messages


def test_verifier_requires_release_workflow_guard_before_dependency_install(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Build macOS DMG\n"
        "jobs:\n"
        "  package-macos:\n"
        "    steps:\n"
        "      - name: Install Python dependencies\n"
        "        run: python -m pip install -e .\n"
        "      - name: Verify release-facing product identity and security guards\n"
        "        run: python scripts/verify_release_artifacts.py\n"
        "      - name: Verify packaged app resources\n"
        "        run: |\n"
        "          package_scan_paths=(dist/backend)\n"
        "          find dist/electron -path '*/Oha-Yachiyo.app/Contents/Resources'\n"
        "          python scripts/verify_release_artifacts.py --allow-binary \"${package_scan_paths[@]}\"\n"
        "      - name: Verify packaged release artifacts\n"
        "        run: python scripts/verify_release_artifacts.py --allow-binary release\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)

    assert findings == [
        verifier.Finding(
            workflow,
            "macOS release workflow must verify release guards before installing dependencies",
        )
    ]


def test_verifier_rejects_legacy_build_metadata_filename(tmp_path):
    required = tmp_path / verifier.REQUIRED_FILES[0]
    required.parent.mkdir(parents=True)
    required.write_text('{"name": "Oha-Yachiyo"}\n', encoding="utf-8")
    legacy = tmp_path / verifier.FORBIDDEN_FILES[0]
    legacy.write_text("{}\n", encoding="utf-8")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[required],
        check_release_security_guards=False,
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
