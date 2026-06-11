"""Release artifact verifier tests."""

from __future__ import annotations

import plistlib
import re

from scripts import verify_release_artifacts as verifier

RELEASE_ELECTRON_SMOKE_SCRIPTS: tuple[str, ...] = (
    "scripts/smoke_chat_image_attachment_ui.mjs",
    "scripts/smoke_chat_cancel_ui.mjs",
    "scripts/smoke_chat_approval_ui.mjs",
    "scripts/smoke_chat_delegated_summary_ui.mjs",
    "scripts/smoke_chat_group_summary_ui.mjs",
    "scripts/smoke_activity_ui.mjs",
    "scripts/smoke_diagnostics_screenshot_ui.mjs",
    "scripts/smoke_live2d_settings_ui.mjs",
    "scripts/smoke_launcher_session_summary_ui.mjs",
    "scripts/smoke_proactive_tts_ui.mjs",
    "scripts/smoke_agent_studio_agents_ui.mjs",
    "scripts/smoke_agent_studio_skills_ui.mjs",
    "scripts/smoke_agent_studio_skill_mount_ui.mjs",
    "scripts/smoke_agent_run_detail_ui.mjs",
    "scripts/smoke_workflow_save_run_ui.mjs",
)


def _explicit_smoke_selectors() -> set[str]:
    selectors: set[str] = set()
    for script in RELEASE_ELECTRON_SMOKE_SCRIPTS:
        text = (verifier.ROOT / script).read_text(encoding="utf-8")
        for match in re.finditer(r'data-testid=(?:\\)?"([^"\\]+)(?:\\)?"', text):
            selector = match.group(1)
            if "$" in selector or "{" in selector:
                continue
            selectors.add(selector)
    return selectors


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


def test_verifier_binary_mode_scans_legacy_kernel_entrypoints(tmp_path):
    artifact = tmp_path / "Oha-Yachiyo-kernel-legacy.dmg"
    artifact.write_bytes(b"\x00Hermes installer\x00hermes_stream_bridge\x00hermes-cli\xff")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[artifact],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    messages = [finding.message for finding in findings]
    assert "contains legacy product token 'Hermes installer'" in messages
    assert "contains legacy product token 'hermes_stream_bridge'" in messages
    assert "contains legacy product token 'hermes-cli'" in messages


def test_verifier_scans_release_artifact_paths_for_legacy_kernel_entrypoints(tmp_path):
    resources = tmp_path / "Oha-Yachiyo.app" / "Contents" / "Resources"
    legacy_cli = resources / "bin" / "hermes-cli"
    legacy_cli.parent.mkdir(parents=True)
    legacy_cli.write_bytes(b"\xff\x00Oha-Yachiyo\xfe")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[resources],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    assert findings == [
        verifier.Finding(legacy_cli, "path contains legacy product token 'hermes-cli'")
    ]


def test_verifier_scans_legacy_protocol_and_workspace_tokens(tmp_path):
    resources = tmp_path / "Oha-Yachiyo.app" / "Contents" / "Resources"
    bundle = resources / "app.asar"
    old_workspace_config = resources / "configs" / "yachiyo.json"
    bundle.parent.mkdir(parents=True)
    old_workspace_config.parent.mkdir(parents=True)
    bundle.write_bytes(b"\x00run_yachiyo\x00yachiyo_group_dispatch\x00yachiyo_agent\xff")
    old_workspace_config.write_bytes(b'{"name":"Oha-Yachiyo"}')

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[resources],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    messages_by_path: dict = {}
    for finding in findings:
        messages_by_path.setdefault(finding.path, []).append(finding.message)
    assert "contains legacy product token 'run_yachiyo'" in messages_by_path[bundle]
    assert "contains legacy product token 'yachiyo_group_dispatch'" in messages_by_path[bundle]
    assert "contains legacy product token 'yachiyo_agent'" in messages_by_path[bundle]
    assert "path contains legacy product token 'configs/yachiyo.json'" in messages_by_path[old_workspace_config]


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


def _write_packaged_app_bundle(
    root,
    *,
    identifier=verifier.PACKAGED_APP_IDENTIFIER,
    executable_mode=0o755,
    backend_mode=0o755,
    include_asar=True,
    include_permission_copy=True,
):
    app_dir = root / verifier.PACKAGED_APP_OUTPUT_DIR / "mac-arm64" / verifier.PACKAGED_APP_NAME
    contents = app_dir / "Contents"
    macos_dir = contents / "MacOS"
    resources_dir = contents / "Resources"
    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)
    info = {
        "CFBundleName": "Oha-Yachiyo",
        "CFBundleDisplayName": "Oha-Yachiyo",
        "CFBundleExecutable": "Oha-Yachiyo",
        "CFBundleIdentifier": identifier,
        "LSApplicationCategoryType": "public.app-category.productivity",
    }
    if include_permission_copy:
        info.update(
            {
                "NSAppleEventsUsageDescription": "Oha-Yachiyo 需要读取当前窗口标题和应用名称。",
                "NSDocumentsFolderUsageDescription": "Oha-Yachiyo 需要访问用户选择的项目文件。",
                "NSDownloadsFolderUsageDescription": "Oha-Yachiyo 需要访问用户选择导入的下载资源。",
                "NSMicrophoneUsageDescription": "Oha-Yachiyo 的语音相关功能可能需要访问麦克风输入。",
            }
        )
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    executable = macos_dir / "Oha-Yachiyo"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(executable_mode)
    backend = app_dir / verifier.PACKAGED_BACKEND_RELATIVE_PATH
    backend.parent.mkdir(parents=True, exist_ok=True)
    backend.write_bytes(b"#!/bin/sh\nexit 0\n")
    backend.chmod(backend_mode)
    if include_asar:
        asar = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
        asar.parent.mkdir(parents=True, exist_ok=True)
        asar.write_bytes("\n".join(verifier.PACKAGED_UI_E2E_REQUIRED_SELECTORS).encode("utf-8"))
    return app_dir


def test_verifier_accepts_packaged_app_bundle_structure(tmp_path):
    _write_packaged_app_bundle(tmp_path)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == []


def test_verifier_reports_incomplete_packaged_app_bundle(tmp_path):
    app_dir = _write_packaged_app_bundle(
        tmp_path,
        identifier="io.github.arisataki.old-yachiyo",
        executable_mode=0o644,
        backend_mode=0o644,
        include_asar=False,
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )
    messages = [finding.message for finding in findings]

    assert f"packaged app bundle identifier must be {verifier.PACKAGED_APP_IDENTIFIER}" in messages
    assert "packaged app main executable is not executable" in messages
    assert "packaged backend executable is not executable" in messages
    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar is missing from app resources",
    ) in findings


def test_verifier_reports_packaged_app_missing_permission_copy(tmp_path):
    _write_packaged_app_bundle(tmp_path, include_permission_copy=False)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )
    messages = [finding.message for finding in findings]

    assert "packaged app Info.plist must include Apple Events permission copy" in messages
    assert "packaged app Info.plist must include Documents folder permission copy" in messages
    assert "packaged app Info.plist must include Downloads folder permission copy" in messages
    assert "packaged app Info.plist must include microphone permission copy" in messages


def test_packaged_selector_gate_covers_release_electron_smoke_selectors():
    missing = sorted(
        _explicit_smoke_selectors()
        - set(verifier.PACKAGED_UI_E2E_REQUIRED_SELECTORS)
    )

    assert missing == []


def test_verifier_reports_packaged_app_missing_ui_e2e_selector(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    asar_path = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
    asar_path.write_bytes(b"chat-image-file-input\nagent-run-detail\n")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'workflow-save-and-run'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-header-image-attach-button'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-composer-attachment-preview'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-session-tab-create'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-group-agent-member-checkbox'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-group-dialog-submit'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-message-activity-open-run-detail'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-image-viewer-backdrop'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-image-viewer-close'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-header-stop-button'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-composer-stop-button'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'bubble-launcher-shell'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'live2d-launcher-reply-text'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-message-summary-status'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-message-approval-actions'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-message-approval-approve'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-message-open-run-detail'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-composer-approval-reject'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-composer-approval-reveal'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'live2d-launcher-recent-session'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'live2d-launcher-quick-input-field'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'live2d-launcher-quick-input-submit'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'proactive-tts-runtime-status'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'proactive-test-result'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'tts-test-text-page'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-approval'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-workflow-child-approval'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-workflow-child-reject'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-workflow-child-cancel'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-result'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-load-more-events'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-artifact-preview'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-rerun'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'workflow-studio'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'workflow-agent-palette-item'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'workflow-run-preview-step'",
    ) in findings


def test_verifier_reports_packaged_app_development_only_ui_e2e_hook(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    asar_path = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
    asar_path.write_bytes(
        "\n".join([*verifier.PACKAGED_UI_E2E_REQUIRED_SELECTORS, "oha-chat-e2e-add-image"]).encode("utf-8")
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == [
        verifier.Finding(
            asar_path,
            "packaged Electron app.asar must not include development-only UI E2E hook 'oha-chat-e2e-add-image'",
        )
    ]


def test_verifier_reports_packaged_app_wrong_category(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    info_path = app_dir / "Contents" / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info["LSApplicationCategoryType"] = "public.app-category.games"
    info_path.write_bytes(plistlib.dumps(info))

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        info_path,
        "packaged app Info.plist must keep the productivity app category",
    ) in findings


def test_verifier_reports_missing_packaged_app_bundle(tmp_path):
    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == [
        verifier.Finding(
            tmp_path / verifier.PACKAGED_APP_OUTPUT_DIR / verifier.PACKAGED_APP_NAME,
            "packaged app bundle must exist under dist/electron",
        )
    ]


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
    assert "macOS release workflow must validate packaged app bundle structure" in messages
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
    assert "macOS release workflow smoke tests must cover Task API protocol schemas" in messages
    assert "macOS release workflow smoke tests must cover AppState task lifecycle" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner native approval roundtrip" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner approval timeout projection" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner image attachment Native runtime flow" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner auto delegation Native runtime flow" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner group dispatch summary Native runtime flow" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner direct group summary Native runtime flow" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner rejected direct group summary Native runtime flow" in messages
    assert "macOS release workflow smoke tests must cover TaskRunner proactive screenshot Native runtime flow" in messages
    assert "macOS release workflow smoke tests must cover Native approval timeout replay idempotency" in messages
    assert "macOS release workflow smoke tests must cover main chat approved tool failure replay" in messages
    assert "macOS release workflow smoke tests must cover Agent approved tool failure projection" in messages
    assert "macOS release workflow smoke tests must cover main chat repeated approval idempotency" in messages
    assert "macOS release workflow smoke tests must cover main chat approval resume claim boundary" in messages
    assert "macOS release workflow smoke tests must cover main chat approval resume wait projection" in messages
    assert "macOS release workflow smoke tests must cover tool approval shared context boundary" in messages
    assert "macOS release workflow smoke tests must cover durable approval claim across runtime instances" in messages
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator claim projection boundary" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine approval resume claim boundary" in messages
    assert "macOS release workflow smoke tests must cover Agent approval resume wait projection" in messages
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator approved tool resume flow" in messages
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator fatal tool failure boundary" in messages
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator custom API resume flow" in messages
    assert "macOS release workflow smoke tests must cover approval approve route idempotency" in messages
    assert "macOS release workflow smoke tests must cover approval reject route idempotency" in messages
    assert "macOS release workflow smoke tests must cover concurrent Run cancellation idempotency" in messages
    assert "macOS release workflow smoke tests must cover UI Run cancel route idempotency" in messages
    assert "macOS release workflow smoke tests must cover Chat cancel late-output HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor Task-to-Run boundary" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor multi-turn context filtering" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor context size limit" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor image attachment payloads" in messages
    assert "macOS release workflow smoke tests must cover TaskRunLink replay projection" in messages
    assert "macOS release workflow smoke tests must cover TaskRunLink repository projection boundary" in messages
    assert "macOS release workflow smoke tests must cover RunEvent concurrent replay cursor projection" in messages
    assert "macOS release workflow smoke tests must cover runtime SQLite database guards" in messages
    assert "macOS release workflow smoke tests must cover Native runtime shutdown cancellation facts" in messages
    assert "macOS release workflow smoke tests must cover Native runtime shutdown resource closure" in messages
    assert "macOS release workflow smoke tests must cover write_patch boundary validation before approval" in messages
    assert "macOS release workflow smoke tests must cover ToolBroker symlink workspace escape guard" in messages
    assert "macOS release workflow smoke tests must cover workspace.write_patch schema validation contract" in messages
    assert "macOS release workflow smoke tests must cover workspace.write_patch single-file hash application" in messages
    assert "macOS release workflow smoke tests must cover workspace.write_patch hash and context mismatch refusal" in messages
    assert "macOS release workflow smoke tests must cover workspace.write_patch multifile and binary patch refusal" in messages
    assert "macOS release workflow smoke tests must cover terminal workspace argv and env scrub" in messages
    assert "macOS release workflow smoke tests must cover terminal startup structured sanitized errors" in messages
    assert "macOS release workflow smoke tests must cover terminal output redaction and truncation" in messages
    assert "macOS release workflow smoke tests must cover approved terminal failure output redaction" in messages
    assert "macOS release workflow smoke tests must cover terminal timeout process-group kill" in messages
    assert "macOS release workflow smoke tests must cover provider reasoning privacy for direct chat calls" in messages
    assert "macOS release workflow smoke tests must cover provider reasoning privacy for main chat loop" in messages
    assert "macOS release workflow smoke tests must cover provider exception redaction" in messages
    assert "macOS release workflow smoke tests must cover tool exception redaction" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine SSE object tool-call arguments" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Responses-style streaming tool calls" in messages
    assert "macOS release workflow smoke tests must cover OpenAI-compatible streaming provider contracts" in messages
    assert "macOS release workflow must expose opt-in real provider streaming smoke" in messages
    assert "macOS release workflow must wire opt-in provider smoke base URL secret" in messages
    assert "macOS release workflow must wire opt-in provider smoke model secret" in messages
    assert "macOS release workflow must wire opt-in provider smoke API key secret" in messages
    assert "macOS release workflow must run the real provider streaming smoke helper when configured" in messages
    assert "macOS release workflow provider smoke must require streamed content" in messages
    assert "macOS release workflow provider smoke must require streamed tool calls" in messages
    assert "macOS release workflow provider smoke must assert the workspace_read tool call" in messages
    assert "macOS release workflow provider smoke must assert the workspace_read README argument" in messages
    assert "macOS release workflow provider smoke must assert the workspace_read path JSON field" in messages
    assert "macOS release workflow provider smoke must assert tool-call finish_reason" in messages
    assert (
        "macOS release workflow must run opt-in real provider streaming smoke before packaged backend and DMG builds"
        in messages
    )
    assert "macOS release workflow smoke tests must cover legacy Hermes kernel removal" in messages
    assert "macOS release workflow smoke tests must cover Native runtime injection boundary" in messages
    assert "macOS release workflow smoke tests must cover AppRuntime Native service aggregation" in messages
    assert "macOS release workflow smoke tests must cover desktop backend Native startup" in messages
    assert "macOS release workflow smoke tests must cover desktop launcher startup wiring" in messages
    assert "macOS release workflow smoke tests must cover shell app Electron entrypoint" in messages
    assert "macOS release workflow smoke tests must cover desktop MainWindow API modes" in messages
    assert "macOS release workflow smoke tests must cover model capability and image input guards" in messages
    assert "macOS release workflow smoke tests must cover model profile credentials and provider contracts" in messages
    assert "macOS release workflow smoke tests must cover provider catalog metadata and cache redaction" in messages
    assert "macOS release workflow smoke tests must cover packaged backend build command guards" in messages
    assert "macOS release workflow smoke tests must cover release-like build metadata guards" in messages
    assert "macOS release workflow smoke tests must cover release-like CredentialStore guards" in messages
    assert "macOS release workflow smoke tests must cover runtime secret redaction verifier" in messages
    assert "macOS release workflow smoke tests must cover security logging redaction" in messages
    assert "macOS release workflow smoke tests must cover screenshot behavior" in messages
    assert "macOS release workflow smoke tests must cover proactive care" in messages
    assert "macOS release workflow smoke tests must cover launcher notifications and proactive attention" in messages
    assert "macOS release workflow smoke tests must cover ChatSession persistence" in messages
    assert "macOS release workflow smoke tests must cover ChatStore persistence and redaction" in messages
    assert "macOS release workflow smoke tests must cover ChatBridge session summary" in messages
    assert "macOS release workflow smoke tests must cover ActivityStore feed and redaction" in messages
    assert "macOS release workflow smoke tests must cover mature UI bridge routes" in messages
    assert "macOS release workflow smoke tests must cover mature frontend feature preservation" in messages
    assert "macOS release workflow smoke tests must cover mature UI flow contracts" in messages
    assert "macOS release workflow smoke tests must cover Chat image Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Chat cancel Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Chat approval Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Chat delegated summary Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Chat group summary Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Activity feed/detail Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover local screenshot Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Live2D settings Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover launcher session summary Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover proactive TTS Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Agent Studio agents Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Agent Studio skills Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Agent Studio skill mounting Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Agent Run Detail replay Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Workflow save-and-run Electron UI smoke" in messages
    assert "macOS release workflow smoke tests must cover Bridge Host Origin and session token guard" in messages
    assert "macOS release workflow smoke tests must cover Bridge loopback bind guard" in messages
    assert "macOS release workflow smoke tests must cover mutating Bridge token guard" in messages
    assert "macOS release workflow smoke tests must cover RunEvent HTTP replay pagination and filtering" in messages
    assert "macOS release workflow smoke tests must cover Chat image HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Chat image NativeRunEngine replay roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Chat approval failed tool HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Agent approval Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Agent approval reject Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Agent approval cancel Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow save-and-run latest canvas route contract" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval shared context boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval reject Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval cancel Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow child approval Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow child approval reject Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow child approval cancel Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow rerun artifact replay HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover group chat Native summary flow" in messages
    assert "macOS release workflow smoke tests must cover auto delegation Native summary flow" in messages
    assert "macOS release workflow smoke tests must cover manual TTS" in messages
    assert "macOS release workflow smoke tests must cover desktop display mode normalization" in messages
    assert "macOS release workflow smoke tests must cover settings effect policy" in messages
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
    from apps.core import build_metadata
    from apps.shell import credential_store

    class FakeDevFileCredentialStore:
        def __init__(self, _path):
            return None

        def close(self):
            return None

    monkeypatch.setattr(bridge_server, "_DEBUG_ROUTE_MODULES", ("apps.bridge.routes.debug",))
    monkeypatch.setattr(build_metadata, "development_features_enabled", lambda: True)
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
    assert "packaged build env must disable development features even when OHA_YACHIYO_DEV=1" in messages
    assert "packaged build env must disable debug routes even when OHA_YACHIYO_DEV=1" in messages
    assert "packaged build env must disable development credential fallback" in messages
    assert "packaged build env must not allow DevFileCredentialStore" in messages
