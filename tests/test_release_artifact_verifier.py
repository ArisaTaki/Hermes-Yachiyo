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
    messages = [finding.message for finding in findings]

    assert "macOS release packaging must disable local native dependency rebuilds" in messages
    assert "macOS release packaging must exclude rebuilt node-pty native artifacts" in messages
    assert "macOS release packaging must exclude Vite cache artifacts" in messages


def test_verifier_requires_packaging_macos_entitlements_and_usage_descriptions(tmp_path):
    config = tmp_path / verifier.PACKAGING_CONFIG_FILE
    config.parent.mkdir(parents=True)
    config.write_text(
        "productName: Oha-Yachiyo\n"
        "npmRebuild: false\n"
        "files:\n"
        "  - '!node_modules/node-pty/build/**'\n"
        "  - '!**/.vite/**'\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_packaging_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS release packaging must enable hardened runtime for the app bundle" in messages
    assert "macOS release packaging must use the checked-in app entitlements" in messages
    assert "macOS release packaging must use the checked-in inherited entitlements" in messages
    assert "macOS release packaging must include Apple Events permission copy" in messages
    assert "macOS release packaging must include Documents folder permission copy" in messages
    assert "macOS release packaging must include Downloads folder permission copy" in messages
    assert "macOS release packaging must include microphone permission copy" in messages


def test_verifier_requires_macos_signing_script_and_entitlements(tmp_path):
    script = tmp_path / verifier.MACOS_SIGNING_SCRIPT_FILE
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/usr/bin/env bash\n"
        "npx electron-builder --config electron-builder.yml --mac dmg\n",
        encoding="utf-8",
    )
    entitlements = tmp_path / verifier.MACOS_ENTITLEMENTS_FILE
    entitlements.parent.mkdir(parents=True)
    entitlements.write_text("<plist><dict></dict></plist>\n", encoding="utf-8")

    findings = verifier._verify_macos_signing_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS signing script must build an unsigned app directory before signing" in messages
    assert "macOS signing script must sign the app with hardened runtime options" in messages
    assert "macOS signing script must apply the checked-in entitlements" in messages
    assert "macOS signing script must verify the signed app bundle" in messages
    assert "macOS signing script must create the unsigned DMG from the signed app bundle" in messages
    assert "macOS entitlements must allow JIT for the Electron runtime" in messages
    assert "macOS entitlements must allow unsigned executable memory for Electron" in messages
    assert "macOS entitlements must disable library validation for packaged native modules" in messages


def test_verifier_reports_tracked_frontend_generated_artifacts(monkeypatch, tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    captured: dict[str, list[str]] = {}

    class Completed:
        returncode = 0
        stdout = (
            "apps/frontend/.vite/deps/package.json\n"
            "apps/frontend/dist/index.html\n"
            "apps/frontend/dist-electron/main.js\n"
        )
        stderr = ""

    def fake_run(args, *_positional, **_kwargs):
        captured["args"] = list(args)
        return Completed()

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)

    findings = verifier._verify_tracked_generated_artifacts(tmp_path)

    assert captured["args"][-3:] == [
        "apps/frontend/.vite",
        "apps/frontend/dist",
        "apps/frontend/dist-electron",
    ]
    assert findings == [
        verifier.Finding(
            tmp_path / "apps/frontend/.vite/deps/package.json",
            "generated frontend build artifacts must not be tracked",
        ),
        verifier.Finding(
            tmp_path / "apps/frontend/dist/index.html",
            "generated frontend build artifacts must not be tracked",
        ),
        verifier.Finding(
            tmp_path / "apps/frontend/dist-electron/main.js",
            "generated frontend build artifacts must not be tracked",
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
        "      - name: Import macOS self-signing certificate\n"
        "        run: echo imported\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n"
        "      - name: Prepare release metadata\n"
        "        run: |\n"
        "          echo \"未使用 Apple Developer ID 签名或 notarization\"\n"
        "          echo \"首次启动应用时仍会显示未知开发者 / Gatekeeper 提示\"\n"
        "          echo \"主动桌面观察需要在 macOS 系统设置中允许 Oha-Yachiyo 使用屏幕录制权限\"\n"
        "      - name: Verify packaged release artifacts\n"
        "        run: python scripts/verify_release_artifacts.py --allow-binary release\n"
        "      - name: Upload DMG artifact\n"
        "        with:\n"
        "          path: |\n"
        "            release/*.json\n"
        "      - name: Create or update latest channel release\n"
        "        run: |\n"
        "          latest_assets=(\"release/${LATEST_JSON}\")\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)

    assert (
        verifier.Finding(
            workflow,
            "macOS release workflow must verify release guards before installing dependencies",
        )
        in findings
    )


def test_verifier_requires_release_workflow_release_scan_after_metadata(tmp_path):
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
        "      - name: Import macOS self-signing certificate\n"
        "        run: echo imported\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n"
        "      - name: Verify packaged app resources\n"
        "        run: |\n"
        "          package_scan_paths=(dist/backend)\n"
        "          find dist/electron -path '*/Oha-Yachiyo.app/Contents/Resources'\n"
        "          python scripts/verify_release_artifacts.py --allow-binary \"${package_scan_paths[@]}\"\n"
        "      - name: Verify packaged release artifacts\n"
        "        run: python scripts/verify_release_artifacts.py --allow-binary release\n"
        "      - name: Prepare release metadata\n"
        "        run: |\n"
        "          echo \"未使用 Apple Developer ID 签名或 notarization\"\n"
        "          echo \"首次启动应用时仍会显示未知开发者 / Gatekeeper 提示\"\n"
        "          echo \"主动桌面观察需要在 macOS 系统设置中允许 Oha-Yachiyo 使用屏幕录制权限\"\n"
        "      - name: Upload DMG artifact\n"
        "        with:\n"
        "          path: |\n"
        "            release/*.json\n"
        "      - name: Create or update latest channel release\n"
        "        run: |\n"
        "          latest_assets=(\"release/${LATEST_JSON}\")\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)

    assert verifier.Finding(
        workflow,
        "macOS release workflow must verify release artifacts after preparing release metadata",
    ) in findings


def test_verifier_requires_release_workflow_smoke_tests_before_packaging(tmp_path):
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
        "      - name: Build packaged backend\n"
        "        run: python scripts/build_backend.py --clean\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n"
        "      - name: Run smoke tests\n"
        "        run: python -m pytest tests/test_chat_api.py\n"
        "      - name: Verify packaged app resources\n"
        "        run: |\n"
        "          package_scan_paths=(dist/backend)\n"
        "          find dist/electron -path '*/Oha-Yachiyo.app/Contents/Resources'\n"
        "          python scripts/verify_release_artifacts.py --allow-binary \"${package_scan_paths[@]}\"\n"
        "      - name: Prepare release metadata\n"
        "        run: |\n"
        "          echo \"未使用 Apple Developer ID 签名或 notarization\"\n"
        "          echo \"首次启动应用时仍会显示未知开发者 / Gatekeeper 提示\"\n"
        "          echo \"主动桌面观察需要在 macOS 系统设置中允许 Oha-Yachiyo 使用屏幕录制权限\"\n"
        "      - name: Verify packaged release artifacts\n"
        "        run: python scripts/verify_release_artifacts.py --allow-binary release\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must run smoke tests before packaged backend and DMG builds" in messages
    assert "macOS release workflow smoke tests must cover screenshot behavior" in messages
    assert "macOS release workflow smoke tests must cover proactive care" in messages
    assert "macOS release workflow smoke tests must cover ChatSession persistence" in messages
    assert "macOS release workflow smoke tests must cover ChatBridge session summary" in messages
    assert "macOS release workflow smoke tests must cover ActivityStore feed and redaction" in messages
    assert "macOS release workflow smoke tests must cover mature UI bridge routes" in messages
    assert "macOS release workflow smoke tests must cover mature frontend feature preservation" in messages
    assert "macOS release workflow smoke tests must cover mature UI flow contracts" in messages
    assert "macOS release workflow smoke tests must cover Bridge Host Origin and session token guard" in messages
    assert "macOS release workflow smoke tests must cover Bridge loopback bind guard" in messages
    assert "macOS release workflow smoke tests must cover mutating Bridge token guard" in messages
    assert "macOS release workflow smoke tests must cover Chat image HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Agent approval Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow child approval Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow rerun artifact replay HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover group chat Native summary flow" in messages
    assert "macOS release workflow smoke tests must cover auto delegation Native summary flow" in messages
    assert "macOS release workflow smoke tests must cover manual TTS" in messages
    assert "macOS release workflow smoke tests must cover Live2D and mode settings" in messages


def test_verifier_requires_release_workflow_to_publish_metadata_json(tmp_path):
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
        "      - name: Import macOS self-signing certificate\n"
        "        run: echo imported\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n"
        "      - name: Verify packaged app resources\n"
        "        run: |\n"
        "          package_scan_paths=(dist/backend)\n"
        "          find dist/electron -path '*/Oha-Yachiyo.app/Contents/Resources'\n"
        "          python scripts/verify_release_artifacts.py --allow-binary \"${package_scan_paths[@]}\"\n"
        "      - name: Prepare release metadata\n"
        "        run: |\n"
        "          echo \"未使用 Apple Developer ID 签名或 notarization\"\n"
        "          echo \"首次启动应用时仍会显示未知开发者 / Gatekeeper 提示\"\n"
        "          echo \"主动桌面观察需要在 macOS 系统设置中允许 Oha-Yachiyo 使用屏幕录制权限\"\n"
        "      - name: Verify packaged release artifacts\n"
        "        run: python scripts/verify_release_artifacts.py --allow-binary release\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must upload release metadata JSON artifacts" in messages
    assert "macOS release workflow must publish latest channel JSON metadata" in messages


def test_verifier_requires_release_workflow_to_stage_and_upload_dmg_artifacts(tmp_path):
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
        "      - name: Import macOS self-signing certificate\n"
        "        run: echo imported\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n"
        "      - name: Verify packaged app resources\n"
        "        run: |\n"
        "          package_scan_paths=(dist/backend)\n"
        "          find dist/electron -path '*/Oha-Yachiyo.app/Contents/Resources'\n"
        "          python scripts/verify_release_artifacts.py --allow-binary \"${package_scan_paths[@]}\"\n"
        "      - name: Prepare release metadata\n"
        "        run: |\n"
        "          echo \"未使用 Apple Developer ID 签名或 notarization\"\n"
        "          echo \"首次启动应用时仍会显示未知开发者 / Gatekeeper 提示\"\n"
        "          echo \"主动桌面观察需要在 macOS 系统设置中允许 Oha-Yachiyo 使用屏幕录制权限\"\n"
        "          mkdir -p release\n"
        "          LATEST_SHA256=\"placeholder\"\n"
        "          cat > \"release/${LATEST_JSON}\" <<EOF\n"
        "          {\"version\":\"${RELEASE_VERSION}\",\"commit\":\"${GITHUB_SHA}\",\"build_number\":${BUILD_NUMBER},\"dmg_name\":\"${LATEST_DMG}\",\"sha256\":\"${LATEST_SHA256}\",\"download_url\":\"https://github.com/${GITHUB_REPOSITORY}/releases/download/${LATEST_TAG}/${LATEST_DMG}\"}\n"
        "          EOF\n"
        "      - name: Verify packaged release artifacts\n"
        "        run: python scripts/verify_release_artifacts.py --allow-binary release\n"
        "      - name: Upload DMG artifact\n"
        "        with:\n"
        "          path: |\n"
        "            release/*.json\n"
        "      - name: Create or update latest channel release\n"
        "        run: |\n"
        "          latest_assets=(\"release/${LATEST_JSON}\")\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must stage the versioned DMG for final artifact scanning" in messages
    assert "macOS release workflow must stage the latest DMG for final artifact scanning" in messages
    assert "macOS release workflow must compute a SHA256 checksum for the versioned DMG" in messages
    assert "macOS release workflow must upload release DMG artifacts" in messages
    assert "macOS release workflow must upload release checksum artifacts" in messages


def test_verifier_requires_release_workflow_latest_json_update_metadata_fields(tmp_path):
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
        "      - name: Import macOS self-signing certificate\n"
        "        run: echo imported\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n"
        "      - name: Verify packaged app resources\n"
        "        run: |\n"
        "          package_scan_paths=(dist/backend)\n"
        "          find dist/electron -path '*/Oha-Yachiyo.app/Contents/Resources'\n"
        "          python scripts/verify_release_artifacts.py --allow-binary \"${package_scan_paths[@]}\"\n"
        "      - name: Prepare release metadata\n"
        "        run: |\n"
        "          echo \"未使用 Apple Developer ID 签名或 notarization\"\n"
        "          echo \"首次启动应用时仍会显示未知开发者 / Gatekeeper 提示\"\n"
        "          echo \"主动桌面观察需要在 macOS 系统设置中允许 Oha-Yachiyo 使用屏幕录制权限\"\n"
        "          cat > \"release/${LATEST_JSON}\" <<EOF\n"
        "          {\"name\":\"Oha-Yachiyo\"}\n"
        "          EOF\n"
        "      - name: Verify packaged release artifacts\n"
        "        run: python scripts/verify_release_artifacts.py --allow-binary release\n"
        "      - name: Upload DMG artifact\n"
        "        with:\n"
        "          path: |\n"
        "            release/*.json\n"
        "      - name: Create or update latest channel release\n"
        "        run: |\n"
        "          latest_assets=(\"release/${LATEST_JSON}\")\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must compute a SHA256 checksum for the latest DMG" in messages
    assert "macOS release workflow latest JSON must include the release version" in messages
    assert "macOS release workflow latest JSON must include the source commit" in messages
    assert "macOS release workflow latest JSON must include the build number" in messages
    assert "macOS release workflow latest JSON must include the DMG filename" in messages
    assert "macOS release workflow latest JSON must include the latest DMG SHA256" in messages
    assert "macOS release workflow latest JSON must include the DMG download URL" in messages


def test_verifier_requires_release_workflow_signing_path_before_dmg_build(tmp_path):
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
        "        run: npm --prefix apps/frontend run dist:mac\n"
        "      - name: Import macOS self-signing certificate\n"
        "        run: echo too-late\n"
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
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must pass signing state into the Electron DMG build" in messages
    assert "macOS release workflow must use the signed app build path when signing is configured" in messages
    assert "macOS release workflow must import signing material before building the DMG" in messages


def test_verifier_requires_release_workflow_first_launch_permission_guidance(tmp_path):
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
        "      - name: Import macOS self-signing certificate\n"
        "        run: echo imported\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n"
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
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must document Gatekeeper first-launch handling" in messages
    assert "macOS release workflow must document current notarization status" in messages
    assert "macOS release workflow must document screen recording permission setup" in messages


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


def test_verifier_reports_release_debug_routes_and_dev_credential_fallback(monkeypatch):
    from apps.bridge import server as bridge_server
    from apps.shell import credential_store

    class FakeDevFileCredentialStore:
        def __init__(self, _path):
            return None

        def close(self):
            return None

    monkeypatch.setattr(bridge_server, "_DEBUG_ROUTE_MODULES", ("apps.bridge.routes.debug",))
    monkeypatch.setattr(bridge_server, "debug_routes_enabled", lambda: True)
    monkeypatch.setattr(credential_store, "development_credential_fallback_enabled", lambda: True)
    monkeypatch.setattr(credential_store, "DevFileCredentialStore", FakeDevFileCredentialStore)

    findings = verifier.verify_release_artifacts(paths=[], check_required_files=False)
    messages = [finding.message for finding in findings]

    assert "release builds must not register debug route modules" in messages
    for channel in verifier.RELEASE_SECURITY_CHANNELS:
        assert f"{channel} metadata must disable debug routes even when OHA_YACHIYO_DEV=1" in messages
        assert f"{channel} metadata must disable development credential fallback" in messages
        assert f"{channel} metadata must not allow DevFileCredentialStore" in messages
