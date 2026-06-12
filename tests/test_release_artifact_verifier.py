"""Release artifact verifier tests."""

from __future__ import annotations

import hashlib
import json
import plistlib
import re

from scripts import run_electron_ui_smokes as smoke_runner
from scripts import verify_release_artifacts as verifier

RELEASE_ELECTRON_SMOKE_SCRIPTS: tuple[str, ...] = (
    "scripts/smoke_chat_image_attachment_ui.mjs",
    "scripts/smoke_chat_run_detail_handoff_ui.mjs",
    "scripts/smoke_chat_agent_progress_ui.mjs",
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
    "scripts/smoke_agent_studio_skill_folders_ui.mjs",
    "scripts/smoke_agent_run_detail_ui.mjs",
    "scripts/smoke_workflow_save_run_ui.mjs",
    "scripts/smoke_workflow_management_ui.mjs",
)


def _release_workflow_electron_smoke_scripts() -> tuple[str, ...]:
    return tuple(str(path) for path in smoke_runner.electron_ui_smoke_scripts(verifier.ROOT))


def _explicit_smoke_selectors() -> set[str]:
    selectors: set[str] = set()
    for script in _release_workflow_electron_smoke_scripts():
        text = (verifier.ROOT / script).read_text(encoding="utf-8")
        for match in verifier.DATA_TESTID_SELECTOR_RE.finditer(text):
            selector = match.group("selector")
            if "$" in selector or "{" in selector:
                continue
            selectors.add(selector)
    return selectors


def _explicit_smoke_data_attributes() -> set[str]:
    attributes: set[str] = set()
    for script in _release_workflow_electron_smoke_scripts():
        text = (verifier.ROOT / script).read_text(encoding="utf-8")
        for match in verifier.DATA_ATTRIBUTE_RE.finditer(text):
            attribute = match.group(0)
            if attribute == "data-testid":
                continue
            attributes.add(attribute)
    return attributes


def test_verifier_accepts_current_release_files():
    assert verifier.verify_release_artifacts() == []


def test_verifier_checks_release_security_guards():
    assert verifier.verify_release_artifacts(paths=[], check_required_files=False) == []


def test_verifier_requires_streaming_provider_smoke_contract_guards(tmp_path):
    script = tmp_path / "scripts" / "smoke_openai_compatible_stream.py"
    script.parent.mkdir(parents=True)
    script.write_text("def main():\n    return 0\n", encoding="utf-8")
    tests = tmp_path / "tests" / "test_streaming_provider_smoke.py"
    tests.parent.mkdir(parents=True)
    tests.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    rc_verifier = tmp_path / "scripts" / "verify_release_candidate.py"
    rc_verifier.write_text("def main():\n    return 0\n", encoding="utf-8")
    ui_runner = tmp_path / "scripts" / "run_electron_ui_smokes.py"
    ui_runner.write_text("def main():\n    return 0\n", encoding="utf-8")

    findings = verifier._verify_streaming_provider_smoke_contract_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "real provider smoke helper must send a streamed tool-result follow-up request" in messages
    assert "real provider smoke helper must strip tool-call arguments before printing summaries" in messages
    assert "real provider smoke helper must redact provider errors before printing stderr" in messages
    assert "provider smoke tests must cover tool-result follow-up without leaking arguments" in messages
    assert (
        "provider smoke tests must prove synthetic tool-result content stays out of printed summaries"
        in messages
    )
    assert "provider smoke tests must cover CLI tool-result finish_reason wiring" in messages
    assert "provider smoke tests must cover Responses completed top-level finish_reason" in messages
    assert "provider smoke tests must cover Responses completed top-level stop_reason" in messages
    assert "real provider smoke helper must parse Responses reasoning summary done snapshots" in messages
    assert "real provider smoke helper must preserve zero-valued Responses indexes before fallback indexes" in messages
    assert "provider smoke tests must cover Responses reasoning summary done snapshots" in messages
    assert "provider smoke tests must cover Responses reasoning output item snapshots" in messages
    assert "provider smoke tests must cover zero-valued Responses indexes before fallback indexes" in messages
    assert "provider smoke tests must cover Responses content part done snapshots" in messages
    assert "provider smoke tests must cover Responses refusal done snapshots" in messages
    assert "provider smoke tests must cover object-shaped streaming tool arguments without leaks" in messages
    assert "provider smoke tests must cover indexless interleaved streaming tool-call deltas without leaks" in messages
    assert "provider smoke tests must cover SSE events split across response chunks" in messages
    assert "provider smoke tests must prove provider errors do not print API keys" in messages
    assert "release candidate verifier must define opt-in provider smoke environment variables" in messages
    assert "release candidate verifier must define provider smoke command contracts" in messages
    assert "release candidate verifier must run the real provider streaming smoke helper" in messages
    assert "release candidate verifier must run real provider text stream smoke" in messages
    assert "release candidate verifier text smoke must require streamed content" in messages
    assert "release candidate verifier provider smoke must assert finish_reason values" in messages
    assert "release candidate verifier provider smoke must assert stop finish_reason" in messages
    assert "release candidate verifier must run real provider tool-call stream smoke" in messages
    assert "release candidate verifier tool-call smoke must require streamed tool calls" in messages
    assert (
        "release candidate verifier tool-call smoke must verify streamed content after a tool result"
        in messages
    )
    assert "release candidate verifier tool-call smoke must assert the workspace_read tool call" in messages
    assert "release candidate verifier tool-call smoke must assert the README argument" in messages
    assert "release candidate verifier tool-call smoke must assert the README path JSON field" in messages
    assert "release candidate verifier tool-call smoke must assert tool_calls finish_reason" in messages
    assert (
        "release candidate verifier tool-call smoke must assert tool-result follow-up finish_reason"
        in messages
    )
    assert (
        "release candidate verifier provider smoke must fail explicitly when credentials are missing"
        in messages
    )
    assert "release candidate verifier must expose provider smoke verification" in messages
    assert "release candidate verifier must report whether provider smoke was requested" in messages
    assert "release candidate verifier must reuse the shared Electron UI smoke runner" in messages
    assert "release candidate verifier must define structured manual release checks" in messages
    assert "release candidate verifier must define allowed manual check statuses" in messages
    assert "release candidate verifier manual checks must support passed status" in messages
    assert "release candidate verifier manual checks must support failed status" in messages
    assert "release candidate verifier manual checks must support not_applicable status" in messages
    assert "release candidate verifier must track Gatekeeper first-launch manual status" in messages
    assert "release candidate verifier must track packaged bridge isolation manual status" in messages
    assert "release candidate verifier must track screen recording permission manual status" in messages
    assert "release candidate verifier must track native Chat file upload manual status" in messages
    assert "release candidate verifier must track packaged UI sampling manual status" in messages
    assert "release candidate verifier must track real provider smoke manual status" in messages
    assert "release candidate verifier manual checks must default to manual_required" in messages
    assert "release candidate verifier manual checks must declare the release signoff gate" in messages
    assert "release candidate verifier manual checks must describe required evidence" in messages
    assert (
        "release candidate verifier must write structured manual check statuses to the RC report"
        in messages
    )
    assert "release candidate verifier must write manual check progress summary to the RC report" in messages
    assert "release candidate verifier must calculate manual check progress summary" in messages
    assert "release candidate verifier manual summary must list remaining check ids" in messages
    assert "release candidate verifier manual summary must list remaining next actions" in messages
    assert "release candidate verifier manual summary must list automated evidence check ids" in messages
    assert "release candidate verifier must copy manual check details into reports" in messages
    assert "release candidate verifier must generate manual check templates" in messages
    assert "release candidate verifier must expose manual check template writing" in messages
    assert "release candidate verifier must generate editable manual check drafts" in messages
    assert "release candidate verifier must expose manual check draft writing" in messages
    assert "release candidate verifier manual check templates must preserve evidence prompts" in messages
    assert "release candidate verifier manual check templates must include next actions" in messages
    assert "release candidate verifier must load manual check evidence JSON" in messages
    assert "release candidate verifier must accept previous RC reports as manual evidence input" in messages
    assert "release candidate verifier must auto-fill manual evidence from passed RC gates" in messages
    assert "release candidate verifier must label automatically supplied manual evidence" in messages
    assert "release candidate verifier must refresh manual check status after automated gates" in messages
    assert "release candidate verifier must expose manual check evidence input" in messages
    assert "release candidate verifier must expose final manual signoff enforcement" in messages
    assert "release candidate verifier CLI must accept manual check evidence JSON" in messages
    assert "release candidate verifier CLI must require complete manual checks for final signoff" in messages
    assert "release candidate verifier CLI must write manual check templates" in messages
    assert "release candidate verifier CLI must write editable manual check drafts" in messages
    assert "Electron UI smoke runner must expose dynamic smoke script discovery" in messages
    assert "Electron UI smoke runner must expose reusable report generation" in messages
    assert "Electron UI smoke runner must discover every scripts/smoke_*_ui.mjs file" in messages
    assert "Electron UI smoke runner must execute discovered smoke scripts with node" in messages
    assert "Electron UI smoke runner report must include script_count" in messages
    assert "Electron UI smoke runner report must include per-script results" in messages
    assert "Electron UI smoke runner CLI must accept a report JSON output path" in messages


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


def test_verifier_validates_release_latest_json_checksum_contract(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg = release_dir / "Oha-Yachiyo-main-latest.dmg"
    dmg.write_bytes(b"fake main dmg bytes")
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (release_dir / f"{dmg.name}.sha256").write_text(f"{digest}  {dmg.name}\n", encoding="utf-8")
    metadata = {
        "name": "Oha-Yachiyo",
        "channel": "stable",
        "branch": "main",
        "source_branch": "main",
        "version": "0.4.0",
        "base_version": "0.4.0",
        "commit": "abc1234567890abc1234567890abc1234567890a",
        "short_commit": "abc1234",
        "build_number": 1,
        "run_number": 1,
        "run_id": "12345",
        "tag": "stable-v0.4.0-build.1-abc1234",
        "signing": "self-signed-app-unsigned-dmg",
        "dmg_name": dmg.name,
        "sha256": digest,
        "download_url": f"https://github.example/releases/download/main-latest/{dmg.name}",
        "latest_json_url": "https://github.example/releases/download/main-latest/Oha-Yachiyo-main-latest.json",
        "published_at": "2026-06-12T00:00:00Z",
        "changelog": {"sections": []},
    }
    (release_dir / "Oha-Yachiyo-main-latest.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    assert findings == []


def test_verifier_reports_release_latest_json_metadata_mismatches(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg = release_dir / "Oha-Yachiyo-main-latest.dmg"
    dmg.write_bytes(b"fake dmg")
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (release_dir / f"{dmg.name}.sha256").write_text(f"{digest}  {dmg.name}\n", encoding="utf-8")
    (release_dir / "Oha-Yachiyo-main-latest.json").write_text(
        json.dumps(
            {
                "name": "Wrong App",
                "channel": "experimental",
                "branch": "develop",
                "source_branch": "../feature branch",
                "version": "not-semver",
                "base_version": "not-semver",
                "commit": "abc123",
                "short_commit": "def9999",
                "build_number": "1",
                "run_number": "1",
                "run_id": "run-1",
                "tag": "experimental-v0.4.0-build.1-def9999",
                "signing": "notarized",
                "dmg_name": "Oha-Yachiyo-develop-latest.dmg",
                "sha256": digest,
                "download_url": "https://github.example/releases/download/develop-latest/Oha-Yachiyo-develop-latest.dmg",
                "latest_json_url": "https://github.example/releases/download/develop-latest/Oha-Yachiyo-main-latest.json",
                "published_at": "2026-06-12 00:00:00",
                "changelog": [],
            }
        ),
        encoding="utf-8",
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )
    messages = [finding.message for finding in findings if finding.path.name == "Oha-Yachiyo-main-latest.json"]

    assert "release latest JSON name must be Oha-Yachiyo" in messages
    assert "release latest JSON branch must match its filename" in messages
    assert "release latest JSON channel must match its filename branch" in messages
    assert "release latest JSON source_branch must be a safe branch name" in messages
    assert "release latest JSON dmg_name must match its filename branch" in messages
    assert "release latest JSON download_url must reference its latest channel tag" in messages
    assert "release latest JSON latest_json_url must reference its latest channel tag" in messages
    assert "release latest JSON version must be semver" in messages
    assert "release latest JSON base_version must be semver" in messages
    assert "release latest JSON commit must be a 40-character git SHA" in messages
    assert "release latest JSON short_commit must prefix commit" in messages
    assert "release latest JSON build_number must be an integer" in messages
    assert "release latest JSON run_number must be an integer" in messages
    assert "release latest JSON run_id must be numeric" in messages
    assert "release latest JSON signing must be a known signing mode" in messages
    assert "release latest JSON published_at must be UTC ISO-8601" in messages
    assert "release latest JSON tag must match channel version build and short_commit" in messages
    assert "release latest JSON changelog must be an object" in messages


def test_verifier_reports_release_latest_json_checksum_mismatches(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    main_dmg = release_dir / "Oha-Yachiyo-main-latest.dmg"
    main_dmg.write_bytes(b"main dmg")
    main_digest = hashlib.sha256(main_dmg.read_bytes()).hexdigest()
    (release_dir / f"{main_dmg.name}.sha256").write_text(f"{'0' * 64}  {main_dmg.name}\n", encoding="utf-8")
    (release_dir / "Oha-Yachiyo-main-latest.json").write_text(
        json.dumps(
            {
                "dmg_name": main_dmg.name,
                "sha256": main_digest,
                "download_url": f"https://github.example/releases/download/main-latest/{main_dmg.name}",
            }
        ),
        encoding="utf-8",
    )

    alpha_dmg = release_dir / "Oha-Yachiyo-alpha-latest.dmg"
    alpha_dmg.write_bytes(b"mutated alpha dmg")
    expected_alpha_digest = hashlib.sha256(b"expected alpha dmg").hexdigest()
    (release_dir / f"{alpha_dmg.name}.sha256").write_text(
        f"{expected_alpha_digest}  {alpha_dmg.name}\n",
        encoding="utf-8",
    )
    (release_dir / "Oha-Yachiyo-alpha-latest.json").write_text(
        json.dumps(
            {
                "dmg_name": alpha_dmg.name,
                "sha256": expected_alpha_digest,
                "download_url": f"https://github.example/releases/download/alpha-latest/{alpha_dmg.name}",
            }
        ),
        encoding="utf-8",
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )
    messages_by_path = {finding.path: finding.message for finding in findings}

    assert messages_by_path[release_dir / f"{main_dmg.name}.sha256"] == (
        "release latest DMG checksum does not match latest JSON sha256"
    )
    assert messages_by_path[alpha_dmg] == "release latest DMG content does not match latest JSON sha256"


def test_verifier_checks_every_release_dmg_checksum_file(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    latest_dmg = release_dir / "Oha-Yachiyo-main-latest.dmg"
    latest_dmg.write_bytes(b"latest dmg")
    latest_digest = hashlib.sha256(latest_dmg.read_bytes()).hexdigest()
    (release_dir / f"{latest_dmg.name}.sha256").write_text(f"{latest_digest}  {latest_dmg.name}\n", encoding="utf-8")
    (release_dir / "Oha-Yachiyo-main-latest.json").write_text(
        json.dumps(
            {
                "dmg_name": latest_dmg.name,
                "sha256": latest_digest,
                "download_url": f"https://github.example/releases/download/main-latest/{latest_dmg.name}",
            }
        ),
        encoding="utf-8",
    )

    versioned_dmg = release_dir / "Oha-Yachiyo-stable-v0.4.0-build.12-abc1234.dmg"
    versioned_dmg.write_bytes(b"versioned dmg")
    (release_dir / f"{versioned_dmg.name}.sha256").write_text(f"{'1' * 64}  {versioned_dmg.name}\n", encoding="utf-8")
    orphan_dmg = release_dir / "Oha-Yachiyo-alpha-v0.4.0-build.12-abc1234.dmg"
    orphan_dmg.write_bytes(b"orphan dmg")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )
    messages_by_path = {finding.path: finding.message for finding in findings}

    assert messages_by_path[versioned_dmg] == "release DMG content does not match checksum file"
    assert messages_by_path[release_dir / f"{orphan_dmg.name}.sha256"] == "release DMG checksum file is missing"


def test_verifier_binary_mode_scans_legacy_kernel_entrypoints(tmp_path):
    artifact = tmp_path / "Oha-Yachiyo-kernel-legacy.dmg"
    artifact.write_bytes(
        b"\x00HermesRuntime\x00hermes_runtime\x00Hermes installer\x00"
        b"Hermes setup\x00Hermes doctor\x00HERMES_HOME\x00HERMES_CONFIG\x00HERMES_PROFILE\x00"
        b"Hermes Agent\x00Hermes bridge\x00Hermes Bridge\x00HermesBridge\x00"
        b"HermesCapability\x00hermes_capability\x00hermes bridge\x00hermes_bridge\x00"
        b"hermes_stream_bridge\x00hermes-bridge\x00hermes-cli\xff"
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[artifact],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    messages = [finding.message for finding in findings]
    assert "contains legacy product token 'HermesRuntime'" in messages
    assert "contains legacy product token 'hermes_runtime'" in messages
    assert "contains legacy product token 'Hermes installer'" in messages
    assert "contains legacy product token 'Hermes setup'" in messages
    assert "contains legacy product token 'Hermes doctor'" in messages
    assert "contains legacy product token 'Hermes Agent'" in messages
    assert "contains legacy product token 'Hermes bridge'" in messages
    assert "contains legacy product token 'Hermes Bridge'" in messages
    assert "contains legacy product token 'HermesBridge'" in messages
    assert "contains legacy product token 'HermesCapability'" in messages
    assert "contains legacy product token 'hermes_capability'" in messages
    assert "contains legacy product token 'hermes bridge'" in messages
    assert "contains legacy product token 'hermes_bridge'" in messages
    assert "contains legacy product token 'HERMES_HOME'" in messages
    assert "contains legacy product token 'HERMES_CONFIG'" in messages
    assert "contains legacy product token 'HERMES_PROFILE'" in messages
    assert "contains legacy product token 'hermes_stream_bridge'" in messages
    assert "contains legacy product token 'hermes-bridge'" in messages
    assert "contains legacy product token 'hermes-cli'" in messages


def test_verifier_scans_release_artifact_paths_for_legacy_kernel_entrypoints(tmp_path):
    resources = tmp_path / "Oha-Yachiyo.app" / "Contents" / "Resources"
    legacy_cli = (
        resources
        / "HERMES_HOME"
        / "HERMES_CONFIG"
        / "HERMES_PROFILE"
        / "hermes_runtime"
        / "hermes_bridge"
        / "hermes-bridge"
        / "hermes-agent"
        / "hermes-doctor"
        / "hermes-cli"
    )
    legacy_cli.parent.mkdir(parents=True)
    legacy_cli.write_bytes(b"\xff\x00Oha-Yachiyo\xfe")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[resources],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    messages = [finding.message for finding in findings]
    assert "path contains legacy product token 'HERMES_HOME'" in messages
    assert "path contains legacy product token 'HERMES_CONFIG'" in messages
    assert "path contains legacy product token 'HERMES_PROFILE'" in messages
    assert "path contains legacy product token 'hermes_runtime'" in messages
    assert "path contains legacy product token 'hermes_bridge'" in messages
    assert "path contains legacy product token 'hermes-bridge'" in messages
    assert "path contains legacy product token 'hermes-agent'" in messages
    assert "path contains legacy product token 'hermes-doctor'" in messages
    assert "path contains legacy product token 'hermes-cli'" in messages


def test_verifier_scans_legacy_protocol_and_workspace_tokens(tmp_path):
    resources = tmp_path / "Oha-Yachiyo.app" / "Contents" / "Resources"
    bundle = resources / "app.asar"
    old_workspace_config = resources / "configs" / "yachiyo.json"
    bundle.parent.mkdir(parents=True)
    old_workspace_config.parent.mkdir(parents=True)
    bundle.write_bytes(
        b"\x00run_yachiyo\x00yachiyo_group_dispatch\x00yachiyo_agent\x00"
        b"Runtime: Yachiyo Agent Runtime\xff"
    )
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
    assert "contains legacy product token 'Runtime: Yachiyo Agent Runtime'" in messages_by_path[bundle]
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


def test_verifier_requires_release_packaging_docs_for_release_gates(tmp_path):
    doc = tmp_path / verifier.RELEASE_PACKAGING_DOC_FILE
    doc.parent.mkdir(parents=True)
    doc.write_text("# Release Packaging\n\nBuild and upload DMG.\n", encoding="utf-8")

    findings = verifier._verify_release_packaging_documentation(tmp_path)
    messages = [finding.message for finding in findings]

    assert "release packaging docs must document the pre-dependency release guard" in messages
    assert "release packaging docs must document debug route guard coverage" in messages
    assert "release packaging docs must document release CredentialStore fallback guard coverage" in messages
    assert "release packaging docs must document final packaged app signature verification" in messages
    assert "release packaging docs must document final release artifact binary scanning" in messages
    assert "release packaging docs must document latest JSON checksum consistency checks" in messages
    assert "release packaging docs must document latest JSON metadata format validation" in messages
    assert "release packaging docs must document reusable app build metadata preparation" in messages
    assert "release packaging docs must document per-DMG checksum file validation" in messages
    assert "release packaging docs must document the local RC verification entrypoint" in messages
    assert "release packaging docs must document the local RC DMG mount gate" in messages
    assert "release packaging docs must document the local RC packaged app startup smoke" in messages
    assert "release packaging docs must document the local RC real provider smoke gate" in messages
    assert "release packaging docs must document the local RC Electron UI smoke gate" in messages
    assert "release packaging docs must document the archived Electron UI smoke runner report" in messages
    assert "release packaging docs must document the archived Electron UI smoke report" in messages
    assert "release packaging docs must document the source-only RC dry run" in messages
    assert "release packaging docs must document the CI release-candidate gate before upload" in messages
    assert "release packaging docs must document the archived RC verification report" in messages
    assert "release packaging docs must document the archived manual RC check template" in messages
    assert "release packaging docs must document the archived manual RC check draft" in messages
    assert "release packaging docs must document structured manual RC check statuses" in messages
    assert "release packaging docs must document manual RC check evidence input" in messages
    assert "release packaging docs must document manual RC check template generation" in messages
    assert "release packaging docs must document manual RC check draft generation" in messages
    assert "release packaging docs must document final manual RC signoff enforcement" in messages
    assert "release packaging docs must document the Gatekeeper manual RC check id" in messages
    assert "release packaging docs must document the screen recording manual RC check id" in messages
    assert "release packaging docs must document the native Chat file upload manual RC check id" in messages
    assert "release packaging docs must document the packaged UI sampling manual RC check id" in messages


def _write_packaged_app_bundle(
    root,
    *,
    app_dir=None,
    identifier=verifier.PACKAGED_APP_IDENTIFIER,
    executable_mode=0o755,
    backend_mode=0o755,
    include_asar=True,
    include_permission_copy=True,
    include_backend_metadata=True,
):
    if app_dir is None:
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
    backend_bytes = b"#!/bin/sh\nexit 0\n"
    if include_backend_metadata:
        backend_bytes += b"\n" + verifier.PACKAGED_BACKEND_BUILD_METADATA_MARKER + b"\n"
    backend.write_bytes(backend_bytes)
    backend.chmod(backend_mode)
    if include_asar:
        asar = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
        asar.parent.mkdir(parents=True, exist_ok=True)
        asar.write_bytes(
            "\n".join(
                (
                    *verifier.PACKAGED_UI_E2E_REQUIRED_SELECTORS,
                    *verifier.PACKAGED_UI_E2E_REQUIRED_DATA_ATTRIBUTES,
                )
            ).encode("utf-8")
        )
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


def test_verifier_accepts_packaged_app_bundle_from_explicit_resources_path(tmp_path):
    app_dir = _write_packaged_app_bundle(
        tmp_path,
        app_dir=tmp_path / "mounted" / verifier.PACKAGED_APP_NAME,
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[app_dir / "Contents" / "Resources"],
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


def test_verifier_reports_packaged_backend_missing_build_metadata(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path, include_backend_metadata=False)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        app_dir / verifier.PACKAGED_BACKEND_RELATIVE_PATH,
        "packaged backend executable must include the app build metadata resource",
    ) in findings


def test_dynamic_packaged_selector_gate_covers_release_electron_smoke_selectors():
    missing = sorted(
        _explicit_smoke_selectors()
        - set(verifier._packaged_ui_e2e_required_selectors(verifier.ROOT))
    )

    assert missing == []


def test_dynamic_packaged_attribute_gate_covers_release_electron_smoke_attributes():
    missing = sorted(
        _explicit_smoke_data_attributes()
        - set(verifier._packaged_ui_e2e_required_data_attributes(verifier.ROOT))
    )

    assert missing == []


def test_release_electron_smoke_runner_discovers_expected_scripts():
    assert _release_workflow_electron_smoke_scripts() == tuple(sorted(RELEASE_ELECTRON_SMOKE_SCRIPTS))


def test_release_workflow_guard_accepts_discovered_electron_smoke_script_before_packaging(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    smoke = tmp_path / "scripts" / "smoke_new_mature_surface_ui.mjs"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env node\nconsole.log('new mature surface smoke');\n", encoding="utf-8")

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Electron UI smoke script "
        "scripts/smoke_new_mature_surface_ui.mjs"
    ) not in messages
    assert (
        "macOS release workflow Electron UI smoke must run before packaged backend and DMG builds: "
        "scripts/smoke_new_mature_surface_ui.mjs"
    ) not in messages


def test_release_workflow_guard_reports_weak_chat_image_file_input_smoke(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    smoke = tmp_path / verifier.CHAT_IMAGE_ATTACHMENT_SMOKE_SCRIPT
    smoke.parent.mkdir(parents=True)
    smoke.write_text(
        "#!/usr/bin/env node\n"
        "document.querySelector('[data-testid=\"chat-image-file-input\"]')?.dispatchEvent(new Event('change'));\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "Chat image Electron UI smoke must drive the hidden file input through CDP DOM.setFileInputFiles"
        in messages
    )
    assert (
        "Chat image Electron UI smoke must pass real filesystem image paths to the file input"
        in messages
    )
    assert (
        "Chat image Electron UI smoke must keep multi-image file input coverage"
        in messages
    )


def test_release_workflow_guard_reports_new_main_chat_provider_contract(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_agent_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_main_chat_model_loop_executes_future_openai_compatible_sse_frame():\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Main Chat provider contract "
        "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_future_openai_compatible_sse_frame"
    ) in messages


def test_release_workflow_guard_accepts_new_main_chat_provider_contract_before_packaging(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    test_path = "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_future_openai_compatible_sse_frame"
    workflow.write_text(
        current_workflow.replace(
            "            tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_stream_chunks_before_persisting \\\n",
            f"            {test_path} \\\n"
            "            tests/test_agent_runtime.py::test_main_chat_model_loop_coalesces_stream_chunks_before_persisting \\\n",
        ),
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_agent_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_main_chat_model_loop_executes_future_openai_compatible_sse_frame():\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Main Chat provider contract "
        f"{test_path}"
    ) not in messages
    assert (
        "macOS release workflow Main Chat provider contract must run before packaged backend and DMG builds: "
        f"{test_path}"
    ) not in messages


def test_release_workflow_guard_reports_late_main_chat_provider_contract(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    test_path = "tests/test_agent_runtime.py::test_main_chat_model_loop_executes_future_openai_compatible_sse_frame"
    workflow.write_text(
        current_workflow + f"\n# late provider contract\n{test_path}\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_agent_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_main_chat_model_loop_executes_future_openai_compatible_sse_frame():\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Main Chat provider contract "
        f"{test_path}"
    ) not in messages
    assert (
        "macOS release workflow Main Chat provider contract must run before packaged backend and DMG builds: "
        f"{test_path}"
    ) in messages


def test_release_workflow_guard_reports_new_agent_run_provider_contract(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_agent_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_agent_run_executes_future_http_sse_tool_call():\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Agent Run provider contract "
        "tests/test_agent_runtime.py::test_agent_run_executes_future_http_sse_tool_call"
    ) in messages


def test_release_workflow_guard_reports_new_agent_run_provider_message_contract(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_agent_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_agent_run_executes_future_provider_message_tool_calls():\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Agent Run provider contract "
        "tests/test_agent_runtime.py::test_agent_run_executes_future_provider_message_tool_calls"
    ) in messages


def test_release_workflow_guard_accepts_new_agent_run_provider_contract_before_packaging(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    test_path = "tests/test_agent_runtime.py::test_agent_run_executes_future_http_sse_tool_call"
    workflow.write_text(
        current_workflow.replace(
            "            tests/test_agent_runtime.py::test_agent_run_executes_streaming_tool_call_and_continues \\\n",
            f"            {test_path} \\\n"
            "            tests/test_agent_runtime.py::test_agent_run_executes_streaming_tool_call_and_continues \\\n",
        ),
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_agent_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_agent_run_executes_future_http_sse_tool_call():\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Agent Run provider contract "
        f"{test_path}"
    ) not in messages
    assert (
        "macOS release workflow Agent Run provider contract must run before packaged backend and DMG builds: "
        f"{test_path}"
    ) not in messages


def test_release_workflow_guard_reports_late_agent_run_provider_contract(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    test_path = "tests/test_agent_runtime.py::test_agent_run_executes_future_http_sse_tool_call"
    workflow.write_text(
        current_workflow + f"\n# late provider contract\n{test_path}\n",
        encoding="utf-8",
    )
    test_file = tmp_path / "tests" / "test_agent_runtime.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_agent_run_executes_future_http_sse_tool_call():\n"
        "    pass\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke tests must run Agent Run provider contract "
        f"{test_path}"
    ) not in messages
    assert (
        "macOS release workflow Agent Run provider contract must run before packaged backend and DMG builds: "
        f"{test_path}"
    ) in messages


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
        "packaged Electron app.asar must include UI E2E selector 'chat-message-copy'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'chat-code-copy'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'diagnostics-copy-output'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'agent-avatar-select'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'skill-source-picker'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'skill-card-open-location'",
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
        "packaged Electron app.asar must include UI E2E selector 'agent-run-detail-execution-open-child-run'",
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


def test_verifier_reports_packaged_app_missing_dynamic_smoke_selector(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    smoke = tmp_path / "scripts" / "smoke_new_mature_surface_ui.mjs"
    smoke.parent.mkdir(parents=True)
    smoke.write_text(
        "document.querySelector('[data-testid=\"new-mature-surface-open\"]');\n"
        "document.querySelector(\"[data-testid='new-mature-surface-delete']\");\n",
        encoding="utf-8",
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E selector 'new-mature-surface-open'",
    ) in findings
    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E selector 'new-mature-surface-delete'",
    ) in findings


def test_verifier_reports_packaged_app_missing_dynamic_smoke_data_attribute(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    smoke = tmp_path / "scripts" / "smoke_new_mature_surface_ui.mjs"
    smoke.parent.mkdir(parents=True)
    smoke.write_text(
        "document.querySelector('[data-mature-surface-id]')?.getAttribute('data-mature-surface-state');\n",
        encoding="utf-8",
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E data attribute 'data-mature-surface-id'",
    ) in findings
    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E data attribute 'data-mature-surface-state'",
    ) in findings


def test_verifier_reports_packaged_app_missing_required_run_handoff_data_attributes(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    asar_path = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
    asar_path.write_bytes("\n".join(verifier.PACKAGED_UI_E2E_REQUIRED_SELECTORS).encode("utf-8"))

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E data attribute 'data-run-id'",
    ) in findings
    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E data attribute 'data-run-status'",
    ) in findings


def test_verifier_reports_packaged_app_development_only_ui_e2e_hook(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    asar_path = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
    asar_path.write_bytes(
        "\n".join(
            [
                *verifier.PACKAGED_UI_E2E_REQUIRED_SELECTORS,
                *verifier.PACKAGED_UI_E2E_REQUIRED_DATA_ATTRIBUTES,
                "oha-chat-e2e-add-image",
            ]
        ).encode("utf-8")
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

    assert "macOS release workflow must expose an alpha release channel" in messages
    assert "macOS release workflow must label alpha releases separately" in messages
    assert "macOS release workflow must publish alpha builds to alpha-latest metadata" in messages
    assert "macOS release workflow must scan the packaged backend binary" in messages
    assert "macOS release workflow must discover packaged app resource directories" in messages
    assert "macOS release workflow must binary-scan packaged app resources" in messages
    assert "macOS release workflow must validate packaged app bundle structure" in messages
    assert "macOS release workflow must verify the final packaged app code signature when signing is enabled" in messages
    assert "macOS release workflow must binary-scan final release artifacts" in messages
    assert "macOS release workflow must run the local RC verification gate" in messages
    assert "macOS release workflow must upload a release-candidate verification report" in messages
    assert "macOS release workflow must archive a manual RC check evidence template" in messages
    assert "macOS release workflow must archive a manual RC check draft seeded from the RC report" in messages


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


def test_verifier_requires_release_workflow_rc_gate_before_upload(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    rc_step_start = current_workflow.index("\n      - name: Verify release candidate artifacts\n")
    upload_step_start = current_workflow.index(
        "\n      - name: Upload DMG artifact\n",
        rc_step_start,
    )
    workflow_without_rc_step = current_workflow[:rc_step_start] + current_workflow[upload_step_start:]
    workflow.write_text(
        workflow_without_rc_step
        + "\n      - name: Late release candidate verification\n"
        "        run: python scripts/verify_release_candidate.py --require-artifacts\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)

    assert verifier.Finding(
        workflow,
        "macOS release workflow must run local RC verification gate after preparing release artifacts before upload",
    ) in findings


def test_verifier_requires_build_metadata_before_packaged_backend(tmp_path):
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
        "      - name: Write app build metadata\n"
        "        run: python scripts/app_version.py current\n"
        "      - name: Build Electron DMG\n"
        "        env:\n"
        "          MACOS_SIGNING_ENABLED: true\n"
        "        run: scripts/build_macos_self_signed_dmg.sh \"Oha-Yachiyo Self Signed\"\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow must write app build metadata before packaged backend and DMG builds"
        in messages
    )


def test_verifier_requires_reusable_build_metadata_script(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    workflow.write_text(
        current_workflow.replace(
            "python scripts/prepare_app_build_metadata.py",
            "python scripts/app_version.py current",
        ),
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)

    assert verifier.Finding(
        workflow,
        "macOS release workflow must write app build metadata through scripts/prepare_app_build_metadata.py",
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
    assert "macOS release workflow smoke tests must cover RunProjectionCoordinator snapshot boundary" in messages
    assert "macOS release workflow smoke tests must cover Native approval timeout replay idempotency" in messages
    assert "macOS release workflow smoke tests must cover main chat approved tool failure replay" in messages
    assert "macOS release workflow smoke tests must cover Agent approved tool failure projection" in messages
    assert "macOS release workflow smoke tests must cover main chat repeated approval idempotency" in messages
    assert "macOS release workflow smoke tests must cover main chat approval resume claim boundary" in messages
    assert "macOS release workflow smoke tests must cover main chat approval resume wait projection" in messages
    assert "macOS release workflow smoke tests must cover ApprovalCoordinator input preview snapshot boundary" in messages
    assert "macOS release workflow smoke tests must cover tool approval shared context boundary" in messages
    assert "macOS release workflow smoke tests must cover durable approval claim across runtime instances" in messages
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator claim projection boundary" in messages
    assert "macOS release workflow smoke tests must cover ToolApprovalClaimProjection running payload boundary" in messages
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator resume orchestration states" in messages
    assert (
        "macOS release workflow smoke tests must cover ToolApprovalContinuationOutcome resume state projection boundary"
        in messages
    )
    assert "macOS release workflow smoke tests must cover NativeRunEngine approval resume claim boundary" in messages
    assert "macOS release workflow smoke tests must cover Agent approval resume wait projection" in messages
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator approved tool resume flow" in messages
    assert "macOS release workflow smoke tests must cover ToolApprovalExecutionRequest approved call boundary" in messages
    assert "macOS release workflow smoke tests must cover ToolApprovalExecutionFollowup remaining-tool boundary" in messages
    assert (
        "macOS release workflow smoke tests must cover ToolApprovalExecutionFailureProjection timeline boundary"
        in messages
    )
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator fatal tool failure boundary" in messages
    assert (
        "macOS release workflow smoke tests must cover ToolApprovalCustomApiContinuationRequest handoff boundary"
        in messages
    )
    assert "macOS release workflow smoke tests must cover ApprovalResumeCoordinator custom API resume flow" in messages
    assert "macOS release workflow smoke tests must cover custom API Agent start iteration normalization" in messages
    assert (
        "macOS release workflow smoke tests must cover ApprovalResumeProjectionCoordinator resume state projections"
        in messages
    )
    assert "macOS release workflow smoke tests must cover ToolApprovalResumeContext pending payload parsing" in messages
    assert "macOS release workflow smoke tests must cover pending approval snapshot isolation" in messages
    assert "macOS release workflow smoke tests must cover WorkflowChildOutcomeCoordinator projection boundary" in messages
    assert "macOS release workflow smoke tests must cover WorkflowParentRunLocator parent lookup boundary" in messages
    assert "macOS release workflow smoke tests must cover WorkflowResumePlanner child resume boundary" in messages
    assert "macOS release workflow smoke tests must cover WorkflowPathPlanner path snapshot boundary" in messages
    assert "macOS release workflow smoke tests must cover WorkflowRunStartProjector replay boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow child status projection boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow parent resume failure projection boundary" in messages
    assert "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator completed child handoff" in messages
    assert (
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator completed child replay idempotency"
        in messages
    )
    assert (
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator child approval replay idempotency"
        in messages
    )
    assert (
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator child cancellation replay idempotency"
        in messages
    )
    assert (
        "macOS release workflow smoke tests must cover WorkflowParentResumeCoordinator child failure replay idempotency"
        in messages
    )
    assert (
        "macOS release workflow smoke tests must cover WorkflowCancellationProjectionCoordinator child cancellation projection"
        in messages
    )
    assert "macOS release workflow smoke tests must cover Workflow agent-node child run handoff" in messages
    assert "macOS release workflow smoke tests must cover Workflow agent-node child run execution handoff" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval pause projection boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow start node projection boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow run completion projection boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow continuation failure projection boundary" in messages
    assert "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator approval pause projection" in messages
    assert "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator approval resume handoff" in messages
    assert "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator background failure projection" in messages
    assert "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator failure redaction boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow artifact node write boundary" in messages
    assert "macOS release workflow smoke tests must cover WorkflowContinuationCoordinator artifact node handoff" in messages
    assert "macOS release workflow smoke tests must cover approval approve route idempotency" in messages
    assert "macOS release workflow smoke tests must cover approval reject route idempotency" in messages
    assert "macOS release workflow smoke tests must cover concurrent Run cancellation idempotency" in messages
    assert (
        "macOS release workflow smoke tests must cover RunTransitionProjectionCoordinator child and workflow group projection"
        in messages
    )
    assert "macOS release workflow smoke tests must cover sensitive client_run_id rejection" in messages
    assert "macOS release workflow smoke tests must cover sensitive Agent/Workflow Idempotency-Key error redaction" in messages
    assert "macOS release workflow smoke tests must cover sensitive Agent Idempotency-Key persistence rejection" in messages
    assert "macOS release workflow smoke tests must cover sensitive Workflow Idempotency-Key persistence rejection" in messages
    assert "macOS release workflow smoke tests must cover UI Run cancel route idempotency" in messages
    assert "macOS release workflow smoke tests must cover Chat cancel late-output HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover missing-model executor structured failure" in messages
    assert "macOS release workflow smoke tests must cover missing-model executor selection" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor Task-to-Run boundary" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor multi-turn context filtering" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor context size limit" in messages
    assert "macOS release workflow smoke tests must cover NativeAgentExecutor image attachment payloads" in messages
    assert "macOS release workflow smoke tests must cover TaskRunLink replay projection" in messages
    assert "macOS release workflow smoke tests must cover TaskRunLink repository projection boundary" in messages
    assert "macOS release workflow smoke tests must cover RunArtifactRepository redaction and file reads" in messages
    assert "macOS release workflow smoke tests must cover RunGroupRepository summary redaction" in messages
    assert "macOS release workflow smoke tests must cover RunGroupRepository insert redaction" in messages
    assert "macOS release workflow smoke tests must cover legacy RunGroupRepository secret scrub" in messages
    assert "macOS release workflow smoke tests must cover RunRepository sensitive client_request_id rejection" in messages
    assert "macOS release workflow smoke tests must cover RunRepository artifact cleanup callback" in messages
    assert "macOS release workflow smoke tests must cover RunEvent concurrent replay cursor projection" in messages
    assert "macOS release workflow smoke tests must cover RunEvent payload snapshot boundary" in messages
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
    assert "macOS release workflow smoke tests must cover skill install env scrub" in messages
    assert "macOS release workflow smoke tests must cover terminal startup structured sanitized errors" in messages
    assert "macOS release workflow smoke tests must cover terminal output redaction and truncation" in messages
    assert "macOS release workflow smoke tests must cover approved terminal failure output redaction" in messages
    assert "macOS release workflow smoke tests must cover terminal timeout process-group kill" in messages
    assert "macOS release workflow smoke tests must cover streaming output completed-event persistence" in messages
    assert "macOS release workflow smoke tests must cover OpenAI SDK object stream completed-event persistence" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine canonical SSE content stream" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine coalesced SSE content frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine split SSE content frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine split UTF-8 SSE content frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine multiline SSE content data" in messages
    assert "macOS release workflow smoke tests must cover provider reasoning privacy for direct chat calls" in messages
    assert "macOS release workflow smoke tests must cover provider reasoning privacy for main chat loop" in messages
    assert "macOS release workflow smoke tests must cover provider exception redaction" in messages
    assert "macOS release workflow smoke tests must cover Workflow child provider exception redaction" in messages
    assert "macOS release workflow smoke tests must cover tool exception redaction" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine canonical SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine singular SSE tool-call frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine SSE object tool-call arguments" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine message-level SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine multiline SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine split-frame SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine interleaved SSE tool-call deltas" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine multi-choice same-index SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine indexless SSE tool-call deltas" in messages
    assert (
        "macOS release workflow smoke tests must cover NativeRunEngine indexless interleaved SSE tool-call deltas"
        in messages
    )
    assert "macOS release workflow smoke tests must cover NativeRunEngine legacy streaming function_call frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine provider message tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine OpenAI SDK object message tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Responses-style streaming tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Responses-style multiple tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Responses call_id main chat history" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run provider message tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run OpenAI SDK object message tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run streaming tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run split UTF-8 SSE content frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run split HTTP SSE content frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run coalesced HTTP SSE content frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run multiline HTTP SSE content data" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE content parts" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run streaming refusal deltas" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run refusal message fields" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses refusal.done snapshots" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run streaming reasoning privacy" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run reasoning privacy" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE provider error redaction" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run multiline HTTP SSE provider error redaction" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run split HTTP SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run singular HTTP SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run indexless interleaved HTTP SSE tool-call deltas" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run HTTP SSE object tool-call arguments" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run message-level HTTP SSE tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run legacy streaming function_call frames" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Responses call_id Agent Run history" in messages
    assert (
        "macOS release workflow smoke tests must cover NativeRunEngine Responses call_id over item id Agent Run history"
        in messages
    )
    assert "macOS release workflow smoke tests must cover NativeRunEngine Responses-style multiple Agent Run tool calls" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses output_text.done snapshots" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses output_item.done message snapshots" in messages
    assert "macOS release workflow smoke tests must cover NativeRunEngine Agent Run Responses content_part.done snapshots" in messages
    assert "macOS release workflow smoke tests must cover OpenAI-compatible streaming provider contracts" in messages
    assert "macOS release workflow must expose opt-in real provider smoke through the RC gate" in messages
    assert "macOS release workflow must wire opt-in provider smoke base URL secret" in messages
    assert "macOS release workflow must wire opt-in provider smoke model secret" in messages
    assert "macOS release workflow must wire opt-in provider smoke API key secret" in messages
    assert "macOS release workflow provider smoke must skip unless all opt-in secrets are configured" in messages
    assert "macOS release workflow provider smoke must report an explicit opt-in secret skip" in messages
    assert "macOS release workflow must pass opt-in provider smoke args to the RC verifier" in messages
    assert (
        "macOS release workflow must fold opt-in provider smoke into the RC verification report before upload"
        in messages
    )
    assert "macOS release workflow smoke tests must cover legacy Hermes kernel removal" in messages
    assert "macOS release workflow smoke tests must cover Native runtime injection boundary" in messages
    assert "macOS release workflow smoke tests must cover AppRuntime Native service aggregation" in messages
    assert "macOS release workflow smoke tests must cover desktop backend Native startup" in messages
    assert "macOS release workflow smoke tests must cover desktop launcher startup wiring" in messages
    assert "macOS release workflow smoke tests must cover shell app Electron entrypoint" in messages
    assert "macOS release workflow smoke tests must cover missing-model MainWindow readiness" in messages
    assert "macOS release workflow smoke tests must cover desktop MainWindow API modes" in messages
    assert "macOS release workflow smoke tests must cover model capability and image input guards" in messages
    assert "macOS release workflow smoke tests must cover model profile credentials and provider contracts" in messages
    assert "macOS release workflow smoke tests must cover provider catalog metadata and cache redaction" in messages
    assert "macOS release workflow smoke tests must cover packaged backend build command guards" in messages
    assert "macOS release workflow smoke tests must cover release-like build metadata guards" in messages
    assert "macOS release workflow smoke tests must cover local RC verification gate" in messages
    assert "macOS release workflow smoke tests must cover the shared Electron UI smoke runner" in messages
    assert "macOS release workflow smoke tests must cover release-like CredentialStore guards" in messages
    assert "macOS release workflow smoke tests must cover Bridge debug routes release metadata guard" in messages
    assert "macOS release workflow smoke tests must cover Bridge debug routes release channel env guard" in messages
    assert "macOS release workflow smoke tests must cover Bridge debug routes release flag env guard" in messages
    assert "macOS release workflow smoke tests must cover Bridge debug routes packaged build guard" in messages
    assert "macOS release workflow smoke tests must cover runtime secret redaction verifier" in messages
    assert "macOS release workflow smoke tests must cover security logging redaction" in messages
    assert "macOS release workflow smoke tests must cover screenshot behavior" in messages
    assert "macOS release workflow smoke tests must cover proactive care" in messages
    assert "macOS release workflow smoke tests must cover launcher notifications and proactive attention" in messages
    assert "macOS release workflow smoke tests must cover ChatSession persistence" in messages
    assert "macOS release workflow smoke tests must cover ChatStore persistence and redaction" in messages
    assert "macOS release workflow smoke tests must cover ChatBridge session summary" in messages
    assert "macOS release workflow smoke tests must cover missing-model Chat API readiness" in messages
    assert "macOS release workflow smoke tests must cover ActivityStore feed and redaction" in messages
    assert "macOS release workflow smoke tests must cover mature UI bridge routes" in messages
    assert "macOS release workflow smoke tests must cover mature frontend feature preservation" in messages
    assert "macOS release workflow smoke tests must cover mature UI flow contracts" in messages
    assert (
        "macOS release workflow smoke tests must run dynamic Electron UI smoke runner "
        "and archive its report"
    ) in messages
    assert "macOS release workflow smoke tests must cover Bridge Host Origin and session token guard" in messages
    assert "macOS release workflow smoke tests must cover Bridge loopback bind guard" in messages
    assert "macOS release workflow smoke tests must cover mutating Bridge token guard" in messages
    assert "macOS release workflow smoke tests must cover sensitive generic Run Idempotency-Key persistence rejection" in messages
    assert "macOS release workflow smoke tests must cover RunEvent HTTP replay pagination and filtering" in messages
    assert "macOS release workflow smoke tests must cover sensitive Chat Idempotency-Key rejection" in messages
    assert "macOS release workflow smoke tests must cover Chat image HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Chat image NativeRunEngine replay roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Chat approval failed tool HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Agent approval Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Agent approval reject Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Agent approval cancel Run Detail HTTP roundtrip" in messages
    assert "macOS release workflow smoke tests must cover Workflow save-and-run latest canvas route contract" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval shared context boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval resume context boundary" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval resume index validation" in messages
    assert "macOS release workflow smoke tests must cover Workflow approval resume coordinator boundary" in messages
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
    assert "macOS release workflow smoke tests must cover TTS command env scrub" in messages
    assert "macOS release workflow smoke tests must cover desktop display mode normalization" in messages
    assert "macOS release workflow smoke tests must cover settings effect policy" in messages
    assert "macOS release workflow smoke tests must cover Live2D and mode settings" in messages


def test_verifier_requires_individual_smoke_guards_before_packaging(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    late_smoke = "python scripts/run_electron_ui_smokes.py --report-json release/electron-ui-smoke.json"
    workflow.write_text(
        current_workflow.replace(f"          {late_smoke}\n", "")
        + f"\n      - name: Late Electron UI smoke runner\n        run: {late_smoke}\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow smoke guard must run before packaged backend and DMG builds: "
        "macOS release workflow smoke tests must run dynamic Electron UI smoke runner "
        "and archive its report"
    ) in messages


def test_verifier_allows_new_electron_ui_smoke_without_workflow_edits(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    smoke = tmp_path / "scripts" / "smoke_new_mature_surface_ui.mjs"
    smoke.parent.mkdir(parents=True)
    smoke.write_text("#!/usr/bin/env node\nconsole.log('new mature surface smoke');\n", encoding="utf-8")

    findings = verifier._verify_release_workflow_guards(tmp_path)

    assert all(
        "smoke_new_mature_surface_ui.mjs" not in finding.message
        for finding in findings
    )


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
    assert "macOS release workflow must fail instead of choosing implicitly when multiple DMGs exist" in messages
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
