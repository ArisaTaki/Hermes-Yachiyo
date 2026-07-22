"""Release artifact verifier tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import run_electron_ui_smokes as smoke_runner
from scripts import release_integrity as integrity
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
    "scripts/smoke_agent_studio_groups_ui.mjs",
    "scripts/smoke_agent_studio_skills_ui.mjs",
    "scripts/smoke_agent_studio_skill_mount_ui.mjs",
    "scripts/smoke_agent_studio_skill_folders_ui.mjs",
    "scripts/smoke_agent_run_detail_ui.mjs",
    "scripts/smoke_chat_public_task_ui.mjs",
    "scripts/smoke_workflow_save_run_ui.mjs",
    "scripts/smoke_workflow_management_ui.mjs",
    "scripts/smoke_yachiyo_entry_routes_ui.mjs",
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


def _add_app_zip_contract(
    release_dir: Path,
    metadata: dict[str, object],
    *,
    branch: str,
    architecture: str = "arm64",
    repository: str = "kuguya-AI-app-develop/Hermes-Yachiyo",
) -> None:
    latest_tag = f"{branch}-latest"
    zip_name = f"Oha-Yachiyo-{branch}-latest-{architecture}.zip"
    zip_path = release_dir / zip_name
    zip_path.write_bytes(b"fake packaged app zip")
    zip_digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (release_dir / f"{zip_name}.sha256").write_text(
        f"{zip_digest}  {zip_name}\n",
        encoding="utf-8",
    )
    signing = str(metadata.get("signing") or "unsigned")
    metadata.update(
        {
            "signature_kind": {
                "unsigned": "adhoc",
                "self-signed-app-unsigned-dmg": "self-signed",
                "developer-id-app-notarized-dmg": "developer-id",
            }[signing],
            "architecture": architecture,
            "zip_name": zip_name,
            "zip_sha256": zip_digest,
            "zip_download_url": (
                f"https://github.com/{repository}/releases/download/"
                f"{latest_tag}/{zip_name}"
            ),
        }
    )


def _write_bound_release_candidate_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object], Path, integrity.SourceTreeProvenance]:
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg = release_dir / "Oha-Yachiyo-main-latest.dmg"
    dmg.write_bytes(b"bound release candidate dmg")
    dmg_digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (release_dir / f"{dmg.name}.sha256").write_text(
        f"{dmg_digest}  {dmg.name}\n",
        encoding="utf-8",
    )

    commit = "abc1234567890abc1234567890abc1234567890a"
    fingerprint = "sha256:" + "a" * 64
    metadata: dict[str, object] = {
        "name": "Oha-Yachiyo",
        "channel": "stable",
        "branch": "main",
        "source_branch": "main",
        "version": "0.4.0",
        "base_version": "0.4.0",
        "commit": commit,
        "short_commit": "abc1234",
        "build_number": 1,
        "run_number": 1,
        "run_id": "1",
        "tag": "stable-v0.4.0-build.1-abc1234",
        "signing": "unsigned",
        "dmg_name": dmg.name,
        "sha256": dmg_digest,
        "download_url": (
            "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/"
            f"releases/download/main-latest/{dmg.name}"
        ),
        "latest_json_url": (
            "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/"
            "download/main-latest/Oha-Yachiyo-main-latest.json"
        ),
        "published_at": "2026-06-12T00:00:00Z",
        "changelog": {},
        "dirty": False,
        "source_tree_fingerprint": fingerprint,
        "release_publishable": True,
    }
    _add_app_zip_contract(release_dir, metadata, branch="main")

    app_dir = tmp_path / "dist" / "electron" / "mac-arm64" / "Oha-Yachiyo.app"
    executable = app_dir / "Contents" / "MacOS" / "Oha-Yachiyo"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"packaged app executable")
    executable.chmod(0o755)
    info_path = app_dir / "Contents" / "Info.plist"
    with info_path.open("wb") as handle:
        plistlib.dump(
            {
                "CFBundleIdentifier": "io.github.arisataki.oha-yachiyo",
                "CFBundleVersion": "400",
                "CFBundleShortVersionString": "0.4.0",
                "CFBundleExecutable": "Oha-Yachiyo",
            },
            handle,
        )

    manifest = integrity.bind_release_candidate_id(
        {
            "schema": integrity.RELEASE_CANDIDATE_SCHEMA,
            "source": {
                "commit": commit,
                "dirty": False,
                "fingerprint": fingerprint,
                "release_publishable": True,
            },
            "artifacts": {
                "dmg": {"name": dmg.name, "sha256": dmg_digest},
                "zip": {
                    "name": metadata["zip_name"],
                    "sha256": metadata["zip_sha256"],
                },
            },
            "app": {
                "bundle_id": "io.github.arisataki.oha-yachiyo",
                "version": "400",
                "short_version": "0.4.0",
                "executable": "Oha-Yachiyo",
                "signature_kind": "adhoc",
                "team_identifier": "",
            },
        }
    )
    metadata["candidate_id"] = manifest["candidate_id"]
    metadata["release_candidate_manifest"] = manifest
    metadata_path = release_dir / "Oha-Yachiyo-main-latest.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    provenance = integrity.SourceTreeProvenance(
        commit=commit,
        dirty=False,
        source_tree_fingerprint=fingerprint,
    )
    return release_dir, metadata_path, metadata, app_dir, provenance


def _verify_bound_release_fixture(
    tmp_path: Path,
    release_dir: Path,
    app_dir: Path,
    *,
    require_bound: bool,
) -> list[verifier.Finding]:
    return verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir, app_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
        require_bound_release_candidate=require_bound,
    )


def test_final_verifier_accepts_content_bound_release_candidate(
    tmp_path,
    monkeypatch,
):
    release_dir, _metadata_path, _metadata, app_dir, provenance = (
        _write_bound_release_candidate_fixture(tmp_path)
    )
    monkeypatch.setattr(verifier, "capture_source_tree_provenance", lambda _root: provenance)

    assert _verify_bound_release_fixture(
        tmp_path,
        release_dir,
        app_dir,
        require_bound=True,
    ) == []


def test_final_verifier_rejects_legacy_unbound_but_nonfinal_keeps_compatibility(
    tmp_path,
    monkeypatch,
):
    release_dir, metadata_path, metadata, app_dir, provenance = (
        _write_bound_release_candidate_fixture(tmp_path)
    )
    metadata.pop("candidate_id")
    metadata.pop("release_candidate_manifest")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(verifier, "capture_source_tree_provenance", lambda _root: provenance)

    assert _verify_bound_release_fixture(
        tmp_path,
        release_dir,
        app_dir,
        require_bound=False,
    ) == []
    final_findings = _verify_bound_release_fixture(
        tmp_path,
        release_dir,
        app_dir,
        require_bound=True,
    )
    assert verifier.Finding(
        metadata_path,
        "final signoff rejects legacy_unbound release metadata; rebuild with "
        "oha-yachiyo.release-candidate.v1",
    ) in final_findings


def test_final_verifier_rejects_rebound_artifact_hash_and_current_source_mismatch(
    tmp_path,
    monkeypatch,
):
    release_dir, metadata_path, metadata, app_dir, provenance = (
        _write_bound_release_candidate_fixture(tmp_path)
    )
    manifest = dict(metadata["release_candidate_manifest"])
    artifacts = dict(manifest["artifacts"])
    artifacts["dmg"] = {
        "name": metadata["dmg_name"],
        "sha256": "f" * 64,
    }
    manifest["artifacts"] = artifacts
    rebound = integrity.bind_release_candidate_id(manifest)
    metadata["candidate_id"] = rebound["candidate_id"]
    metadata["release_candidate_manifest"] = rebound
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    stale_source = integrity.SourceTreeProvenance(
        commit=provenance.commit,
        dirty=False,
        source_tree_fingerprint="sha256:" + "b" * 64,
    )
    monkeypatch.setattr(
        verifier,
        "capture_source_tree_provenance",
        lambda _root: stale_source,
    )

    messages = {
        finding.message
        for finding in _verify_bound_release_fixture(
            tmp_path,
            release_dir,
            app_dir,
            require_bound=True,
        )
    }
    assert (
        "release candidate artifacts.dmg.sha256 does not match latest JSON sha256"
        in messages
    )
    assert "release candidate DMG content does not match its manifest sha256" in messages
    assert (
        "release candidate source.fingerprint does not match current source provenance"
        in messages
    )


def test_final_verifier_rejects_selected_packaged_app_identity_mismatch(
    tmp_path,
    monkeypatch,
):
    release_dir, _metadata_path, _metadata, app_dir, provenance = (
        _write_bound_release_candidate_fixture(tmp_path)
    )
    info_path = app_dir / "Contents" / "Info.plist"
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)
    info["CFBundleIdentifier"] = "invalid.bundle"
    with info_path.open("wb") as handle:
        plistlib.dump(info, handle)
    monkeypatch.setattr(verifier, "capture_source_tree_provenance", lambda _root: provenance)

    assert verifier.Finding(
        app_dir,
        "release candidate App bundle_id does not match selected packaged App identity",
    ) in _verify_bound_release_fixture(
        tmp_path,
        release_dir,
        app_dir,
        require_bound=True,
    )


def test_verifier_accepts_current_release_files():
    assert verifier.verify_release_artifacts() == []


def test_verifier_allows_exact_official_repository_identity_but_not_legacy_copy(
    tmp_path,
):
    official = tmp_path / "official.txt"
    official.write_text(
        "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases\n",
        encoding="utf-8",
    )
    legacy = tmp_path / "legacy.txt"
    legacy.write_text("Launch Hermes-Yachiyo\n", encoding="utf-8")

    official_findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[official],
        check_required_files=False,
        check_release_security_guards=False,
    )
    legacy_findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[legacy],
        check_required_files=False,
        check_release_security_guards=False,
    )

    assert official_findings == []
    assert any(
        finding.message == "contains legacy product token 'Hermes-Yachiyo'"
        for finding in legacy_findings
    )


def test_verifier_checks_release_security_guards():
    assert verifier.verify_release_artifacts(paths=[], check_required_files=False) == []


def test_verifier_requires_streaming_provider_smoke_contract_guards(tmp_path):
    script = tmp_path / "scripts" / "smoke_openai_compatible_stream.py"
    script.parent.mkdir(parents=True)
    script.write_text("def main():\n    return 0\n", encoding="utf-8")
    tests = tmp_path / "tests" / "test_streaming_provider_smoke.py"
    tests.parent.mkdir(parents=True)
    tests.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    native_script = tmp_path / "scripts" / "smoke_native_agent_full_chain.py"
    native_script.write_text("def main():\n    return 0\n", encoding="utf-8")
    native_tests = tmp_path / "tests" / "test_native_agent_full_chain_smoke.py"
    native_tests.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    workflow_script = tmp_path / "scripts" / "smoke_native_workflow_full_chain.py"
    workflow_script.write_text("def main():\n    return 0\n", encoding="utf-8")
    workflow_tests = tmp_path / "tests" / "test_native_workflow_full_chain_smoke.py"
    workflow_tests.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    ui_bridge_tests = tmp_path / "tests" / "test_ui_bridge_routes.py"
    ui_bridge_tests.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    agent_runtime = tmp_path / "apps" / "shell" / "agent_runtime.py"
    agent_runtime.parent.mkdir(parents=True)
    agent_runtime.write_text("def placeholder():\n    pass\n", encoding="utf-8")
    agent_studio = tmp_path / "apps" / "frontend" / "src" / "views" / "AgentStudioView.tsx"
    agent_studio.parent.mkdir(parents=True)
    agent_studio.write_text("export const placeholder = true;\n", encoding="utf-8")
    agent_runtime_tests = tmp_path / "tests" / "test_agent_runtime.py"
    agent_runtime_tests.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    rc_verifier = tmp_path / "scripts" / "verify_release_candidate.py"
    rc_verifier.write_text("def main():\n    return 0\n", encoding="utf-8")
    ui_runner = tmp_path / "scripts" / "run_electron_ui_smokes.py"
    ui_runner.write_text("def main():\n    return 0\n", encoding="utf-8")
    packaged_ui_smoke = tmp_path / "scripts" / "smoke_packaged_ui_sampling.mjs"
    packaged_ui_smoke.write_text("console.log('placeholder');\n", encoding="utf-8")
    packaged_chat_smoke = (
        tmp_path / "scripts" / "smoke_packaged_chat_native_file_upload.mjs"
    )
    packaged_chat_smoke.write_text("console.log('placeholder');\n", encoding="utf-8")
    release_smoke_summary = tmp_path / "scripts" / "summarize_release_smoke.py"
    release_smoke_summary.write_text("def main():\n    return 0\n", encoding="utf-8")

    findings = verifier._verify_streaming_provider_smoke_contract_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "real provider smoke helper must send a streamed tool-result follow-up request" in messages
    assert "real provider smoke helper must force the workspace_read tool during tool-call smoke" in messages
    assert "real provider smoke helper must strip tool-call arguments before printing summaries" in messages
    assert "real provider smoke helper must redact provider errors before printing stderr" in messages
    assert "provider smoke tests must cover tool-result follow-up without leaking arguments" in messages
    assert "provider smoke tests must assert forced workspace_read tool_choice wiring" in messages
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
    assert "provider smoke tests must cover Responses output_text.done list snapshots" in messages
    assert "provider smoke tests must cover zero-valued Responses indexes before fallback indexes" in messages
    assert "provider smoke tests must cover Responses content part done snapshots" in messages
    assert "provider smoke tests must cover Responses refusal done snapshots" in messages
    assert "provider smoke tests must cover object-shaped streaming tool arguments without leaks" in messages
    assert "provider smoke tests must cover indexless interleaved streaming tool-call deltas without leaks" in messages
    assert "provider smoke tests must cover SSE events split across response chunks" in messages
    assert "provider smoke tests must prove provider errors do not print API keys" in messages
    assert "native Agent full-chain smoke must keep runtime state in a temporary directory" in messages
    assert "native Agent full-chain smoke must use an in-memory credential store" in messages
    assert "native Agent full-chain smoke must exercise ModelProfileService readiness" in messages
    assert "native Agent full-chain smoke must exercise NativeRunEngine" in messages
    assert "native Agent full-chain smoke must exercise workspace.read" in messages
    assert "native Agent full-chain smoke must exercise artifact.write" in messages
    assert "native Agent full-chain smoke must exercise Workflow child Agent artifact flow" in messages
    assert "native Agent full-chain smoke must exercise terminal approval resume" in messages
    assert "native Agent full-chain smoke must exercise main chat model loop" in messages
    assert "native Agent full-chain smoke must fail instead of printing sensitive output" in messages
    assert "native Agent full-chain smoke tests must cover missing opt-in credentials" in messages
    assert "native Agent full-chain smoke tests must prove sensitive summaries are not printed" in messages
    assert "native Agent full-chain smoke tests must cover nested sensitive detail redaction" in messages
    assert "native Workflow full-chain smoke must keep runtime state in a temporary directory" in messages
    assert "native Workflow full-chain smoke must use an in-memory credential store" in messages
    assert "native Workflow full-chain smoke must exercise ModelProfileService readiness" in messages
    assert "native Workflow full-chain smoke must exercise NativeRunEngine" in messages
    assert "native Workflow full-chain smoke must exercise advanced Workflow orchestration" in messages
    assert "native Workflow full-chain smoke must require condition node replay events" in messages
    assert "native Workflow full-chain smoke must require subworkflow replay events" in messages
    assert "native Workflow full-chain smoke must require parallel replay events" in messages
    assert "native Workflow full-chain smoke must require loop replay events" in messages
    assert "native Workflow full-chain smoke must exercise Workflow budget boundaries" in messages
    assert "native Workflow full-chain smoke must fail instead of printing sensitive output" in messages
    assert "native Workflow full-chain smoke tests must cover missing opt-in credentials" in messages
    assert "native Workflow full-chain smoke tests must prove sensitive summaries are not printed" in messages
    assert "native Workflow full-chain smoke tests must cover nested sensitive detail redaction" in messages
    assert (
        "UI bridge route tests must cover Live2D and GPT-SoVITS resource import-save-test chain"
        in messages
    )
    assert (
        "UI bridge route tests must exercise GPT-SoVITS HTTP endpoints during TTS test"
        in messages
    )
    assert (
        "UI bridge route tests must import a Live2D archive through the public route handler"
        in messages
    )
    assert (
        "UI bridge route tests must import a GPT-SoVITS voice archive through the public route handler"
        in messages
    )
    assert (
        "UI bridge route tests must exercise proactive TTS test playback through the public route handler"
        in messages
    )
    assert "Native workflow runtime must recognize condition nodes as first-class Workflow nodes" in messages
    assert "Native workflow runtime must recognize parallel nodes as first-class Workflow nodes" in messages
    assert "Native workflow runtime must recognize subworkflow nodes as first-class Workflow nodes" in messages
    assert "Native workflow runtime must recognize loop nodes as first-class Workflow nodes" in messages
    assert (
        "Native workflow runtime must project condition node execution into timeline and replay events"
        in messages
    )
    assert "Native workflow runtime must select true/false condition branches from current context" in messages
    assert (
        "Native workflow runtime must project parallel node execution into timeline and replay events"
        in messages
    )
    assert "Native workflow runtime must plan parallel fan-out branches and fan-in targets" in messages
    assert "Native workflow runtime must tag parallel child events with parent branch context" in messages
    assert "Native workflow runtime must reuse completed parallel branch Agent results after approval" in messages
    assert "Native workflow runtime must execute child Workflow nodes and project their run status" in messages
    assert "Native workflow runtime must emit subworkflow node execution timeline events" in messages
    assert "Native workflow runtime must validate subworkflow node references before execution" in messages
    assert "Native workflow runtime must project loop node execution into timeline and replay events" in messages
    assert "Native workflow runtime must route loop continue/exit branches from current context" in messages
    assert "Native workflow runtime must enforce bounded loop execution" in messages
    assert "Native workflow runtime must enforce Workflow-level execution budgets" in messages
    assert "Native workflow runtime must expose a bounded Workflow step budget" in messages
    assert "Native workflow runtime must resume branch-aware Workflow execution by next node id" in messages
    assert "Native workflow runtime must locate parent Workflows waiting on child Workflow runs" in messages
    assert "Agent Studio must recognize condition, parallel, subworkflow, and loop nodes in the frontend contract" in messages
    assert "Agent Studio must preserve true/false Workflow branch metadata" in messages
    assert "Agent Studio Run Detail must display condition Workflow execution events" in messages
    assert "Agent Studio Run Detail must display parallel Workflow execution events" in messages
    assert "Agent Studio Run Detail must display subworkflow execution events" in messages
    assert "Agent Studio Run Detail must display loop execution events" in messages
    assert "Native workflow tests must execute both true and false condition branches" in messages
    assert "Native workflow tests must assert condition branch selection replay payloads" in messages
    assert "Native workflow tests must verify condition branches can merge into a shared artifact node" in messages
    assert (
        "Native workflow tests must execute parallel fan-out branches and merge them into a shared artifact node"
        in messages
    )
    assert "Native workflow tests must assert parallel fan-in replay payloads" in messages
    assert (
        "Native workflow tests must resume remaining parallel branches after child Agent approvals"
        in messages
    )
    assert "Native workflow tests must verify parallel approval results reach fan-in artifacts" in messages
    assert "Native workflow tests must assert parallel child branch replay payloads" in messages
    assert "Native workflow tests must execute subworkflow nodes and project child artifacts" in messages
    assert "Native workflow tests must assert subworkflow child Workflow replay payloads" in messages
    assert "Native workflow tests must verify subworkflow child artifacts are linked into the parent run" in messages
    assert "Native workflow tests must resume parent Workflows after nested subworkflow child approvals" in messages
    assert "Native workflow tests must verify nested subworkflow approval results reach parent artifacts" in messages
    assert "Native workflow tests must execute loop nodes until they exit into a shared artifact node" in messages
    assert "Native workflow tests must assert loop iteration replay payloads" in messages
    assert "Native workflow tests must verify loop nodes can exit into a shared artifact node" in messages
    assert "Native workflow tests must enforce Workflow context budget failures" in messages
    assert "Native workflow tests must preserve Workflow step budgets across child approval resume" in messages
    assert "Native workflow tests must enforce Workflow duration budget failures between nodes" in messages
    assert "release candidate verifier must define opt-in provider smoke environment variables" in messages
    assert "release candidate verifier must define provider smoke command contracts" in messages
    assert "release candidate verifier must run the real provider streaming smoke helper" in messages
    assert "release candidate verifier must define the native Agent full-chain smoke helper" in messages
    assert "release candidate verifier must run the native Agent full-chain smoke helper" in messages
    assert "release candidate verifier must define the native Workflow full-chain smoke helper" in messages
    assert "release candidate verifier must run the native Workflow full-chain smoke helper" in messages
    assert "release candidate verifier must run real provider text stream smoke" in messages
    assert "release candidate verifier text smoke must require streamed content" in messages
    assert "release candidate verifier provider smoke must assert finish_reason values" in messages
    assert "release candidate verifier provider smoke must assert stop finish_reason" in messages
    assert "release candidate verifier must run real provider tool-call stream smoke" in messages
    assert "release candidate verifier must run native Agent full-chain provider smoke" in messages
    assert "release candidate verifier must run native Workflow full-chain provider smoke" in messages
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
    assert "release candidate verifier must write source revision metadata to the RC report" in messages
    assert (
        "release candidate verifier must archive packaged Bridge status metadata from DMG smokes"
        in messages
    )
    assert (
        "release candidate verifier must compare packaged Bridge build metadata with source revision"
        in messages
    )
    assert (
        "release candidate verifier must archive packaged Electron app build metadata from Chat native file smoke"
        in messages
    )
    assert (
        "release candidate verifier final signoff must reject dirty source revisions"
        in messages
    )
    assert (
        "release candidate verifier final signoff must reject stale manual evidence source revisions"
        in messages
    )
    assert (
        "release candidate verifier final signoff must reject manual evidence without source revisions"
        in messages
    )
    assert (
        "release candidate verifier must print stale manual evidence source revision findings"
        in messages
    )
    assert (
        "release candidate verifier manual reports, drafts, and Markdown must preserve source revision metadata"
        in messages
    )
    assert "release candidate verifier must write manual check progress summary to the RC report" in messages
    assert "release candidate verifier must calculate manual check progress summary" in messages
    assert "release candidate verifier must expose read-only manual check status printing" in messages
    assert "release candidate verifier manual summary must list remaining check ids" in messages
    assert "release candidate verifier manual summary must list remaining next actions" in messages
    assert (
        "release candidate verifier manual summary must list recommended automation commands"
        in messages
    )
    assert (
        "release candidate verifier must print recommended automation commands for remaining checks"
        in messages
    )
    assert (
        "release candidate verifier Markdown checklist must include recommended automation commands"
        in messages
    )
    assert (
        "release candidate verifier manual summary must list supporting notes for remaining checks"
        in messages
    )
    assert "release candidate verifier manual summary must list automated evidence check ids" in messages
    assert "release candidate verifier must copy manual check details into reports" in messages
    assert "release candidate verifier must generate manual check templates" in messages
    assert "release candidate verifier must expose manual check template writing" in messages
    assert "release candidate verifier must generate editable manual check drafts" in messages
    assert "release candidate verifier must expose manual check draft writing" in messages
    assert "release candidate verifier must generate manual check Markdown checklists" in messages
    assert "release candidate verifier Markdown checklist must include fill instructions" in messages
    assert (
        "release candidate verifier Markdown checklist must explain checked items default to passed"
        in messages
    )
    assert "release candidate verifier Markdown checklist must explain evidence requirements" in messages
    assert "release candidate verifier Markdown checklist must include the final gate command" in messages
    assert "release candidate verifier Markdown checklist must name the final signoff report path" in messages
    assert "release candidate verifier must expose manual check Markdown writing" in messages
    assert "release candidate verifier manual check templates must preserve evidence prompts" in messages
    assert "release candidate verifier manual check templates must include next actions" in messages
    assert "release candidate verifier must load manual check evidence JSON" in messages
    assert "release candidate verifier must parse manual check Markdown evidence" in messages
    assert "release candidate verifier must accept previous RC reports as manual evidence input" in messages
    assert "release candidate verifier must preserve supporting evidence from previous RC reports" in messages
    assert (
        "release candidate verifier must attach UI smoke supporting evidence to current RC reports"
        in messages
    )
    assert "release candidate verifier must not auto-pass native file picker from UI smoke" in messages
    assert "release candidate verifier must auto-fill manual evidence from passed RC gates" in messages
    assert (
        "release candidate verifier must preserve packaged bridge evidence from partial DMG probes"
        in messages
    )
    assert (
        "release candidate verifier must report packaged bridge readiness from DMG probes"
        in messages
    )
    assert "release candidate verifier must report packaged screen probe results" in messages
    assert "release candidate verifier must report packaged UI sampling smoke results" in messages
    assert "release candidate verifier must report packaged Chat native file smoke results" in messages
    assert "release candidate verifier must name the packaged UI sampling smoke helper" in messages
    assert "release candidate verifier must name the packaged Chat native file smoke helper" in messages
    assert "release candidate verifier must expose packaged UI sampling verification" in messages
    assert "release candidate verifier must expose packaged Chat native file verification" in messages
    assert "release candidate verifier CLI must expose packaged screen recording smoke" in messages
    assert "release candidate verifier CLI must expose packaged UI sampling smoke" in messages
    assert "release candidate verifier CLI must expose packaged Chat native file smoke" in messages
    assert (
        "release candidate verifier screen probe evidence must avoid archiving screenshot bytes"
        in messages
    )
    assert (
        "release candidate verifier must report stable app launch paths for screen permission"
        in messages
    )
    assert "release candidate verifier must label automatically supplied manual evidence" in messages
    assert "release candidate verifier must refresh manual check status after automated gates" in messages
    assert "release candidate verifier must expose manual check evidence input" in messages
    assert "release candidate verifier must expose final manual signoff enforcement" in messages
    assert "release candidate verifier CLI must accept manual check evidence JSON" in messages
    assert (
        "release candidate verifier CLI must allow repeated manual check evidence JSON inputs"
        in messages
    )
    assert "release candidate verifier CLI must accept manual check evidence Markdown" in messages
    assert "release candidate verifier CLI must require complete manual checks for final signoff" in messages
    assert "release candidate verifier CLI must write manual check templates" in messages
    assert "release candidate verifier CLI must write editable manual check drafts" in messages
    assert "release candidate verifier CLI must write manual check Markdown checklists" in messages
    assert "release candidate verifier CLI must print manual check status without running artifact gates" in messages
    assert (
        "release candidate verifier CLI must explicitly mark provider smoke not_applicable only when requested"
        in messages
    )
    assert (
        "release candidate verifier CLI must pass provider not_applicable evidence into RC reports"
        in messages
    )
    assert "release candidate verifier must isolate provider smoke not_applicable draft handling" in messages
    assert "Electron UI smoke runner must expose dynamic smoke script discovery" in messages
    assert "Electron UI smoke runner must expose reusable report generation" in messages
    assert "Electron UI smoke runner must discover every scripts/smoke_*_ui.mjs file" in messages
    assert "Electron UI smoke runner must execute discovered smoke scripts with node" in messages
    assert "Electron UI smoke runner report must include script_count" in messages
    assert "packaged UI sampling smoke must define route samples" in messages
    assert "packaged UI sampling smoke must keep a minimum per-route timeout" in messages
    assert "packaged UI sampling smoke must connect to the packaged app DevTools port" in messages
    assert "packaged UI sampling smoke must use the DevTools websocket protocol" in messages
    assert "packaged UI sampling smoke must cover Workflow Studio" in messages
    assert "packaged UI sampling smoke must cover Chat composer selectors" in messages
    assert "packaged UI sampling smoke must cover Live2D settings selectors" in messages
    assert (
        "packaged Chat native file smoke must provide stable UI settings to prevent packaged-window reloads"
        in messages
    )
    assert (
        "packaged Chat native file smoke must isolate Electron user data and single-instance state"
        in messages
    )
    assert (
        "packaged Chat native file smoke must prove the technical run action stays hidden in Chat"
        in messages
    )
    assert (
        "packaged Chat native file smoke must record direct Agent Studio replay navigation"
        in messages
    )
    assert "packaged Chat native file smoke must use one global execution deadline" in messages
    assert "packaged Chat native file smoke must apply the global deadline to app startup" in messages
    assert "packaged Chat native file smoke must apply the global deadline to the full UI flow" in messages
    assert "packaged Chat native file smoke must expose a strict process cleanup ledger" in messages
    assert "packaged Chat native file smoke must record detached process cleanup state" in messages
    assert (
        "packaged Chat native file smoke must attest internal activity, tool, and recovery hiding"
        in messages
    )
    assert "packaged Chat native file smoke must inject internal recovery evidence" in messages
    assert (
        "packaged Chat native file smoke must await packaged Electron process-tree cleanup"
        in messages
    )
    assert (
        "packaged Chat native file smoke must escalate cleanup when graceful termination times out"
        in messages
    )
    assert (
        "packaged Chat native file smoke must remove isolated state after process cleanup"
        in messages
    )
    assert "release-smoke summary must retain the packaged Chat desktop-task item" in messages
    assert "release-smoke summary must require passed packaged Chat native file evidence" in messages
    assert "release-smoke summary must direct missing packaged Chat evidence to its RC smoke" in messages
    assert (
        "release candidate verifier must clean detached packaged Chat processes from a strict ledger"
        in messages
    )
    assert (
        "release candidate verifier must leave parent timeout budget for Chat smoke cleanup"
        in messages
    )
    assert (
        "release candidate verifier must reject missing internal-execution hiding evidence"
        in messages
    )
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


@pytest.mark.parametrize(
    "signing_mode",
    ["self-signed-app-unsigned-dmg", "developer-id-app-notarized-dmg"],
)
def test_verifier_validates_release_latest_json_checksum_contract(
    tmp_path,
    signing_mode,
):
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
        "signing": signing_mode,
        "dmg_name": dmg.name,
        "sha256": digest,
        "download_url": (
            "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/"
            f"releases/download/main-latest/{dmg.name}"
        ),
        "latest_json_url": (
            "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/"
            "download/main-latest/Oha-Yachiyo-main-latest.json"
        ),
        "published_at": "2026-06-12T00:00:00Z",
        "changelog": {"sections": []},
        "dirty": False,
        "source_tree_fingerprint": "sha256:" + "a" * 64,
        "release_publishable": True,
    }
    _add_app_zip_contract(release_dir, metadata, branch="main")
    if signing_mode == "developer-id-app-notarized-dmg":
        submission_id = "12345678-1234-1234-1234-123456789abc"
        (release_dir / "notarization.json").write_text(
            json.dumps({"id": submission_id, "status": "Accepted"}),
            encoding="utf-8",
        )
        (release_dir / "notarization-log.json").write_text(
            json.dumps({"jobId": submission_id, "status": "Accepted"}),
            encoding="utf-8",
        )
        (release_dir / "notarization-evidence.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "Accepted",
                    "submission_id": submission_id,
                    "dmg_name": dmg.name,
                    "dmg_sha256": digest,
                    "submission_file": "notarization.json",
                    "log_file": "notarization-log.json",
                }
            ),
            encoding="utf-8",
        )
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


def test_verifier_allows_dirty_rc_only_in_explicit_local_inspection_mode(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg = release_dir / "Oha-Yachiyo-oha-develop-latest.dmg"
    dmg.write_bytes(b"dirty local dmg")
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (release_dir / f"{dmg.name}.sha256").write_text(
        f"{digest}  {dmg.name}\n",
        encoding="utf-8",
    )
    metadata_path = release_dir / "Oha-Yachiyo-oha-develop-latest.json"
    metadata = {
        "name": "Oha-Yachiyo",
        "channel": "experimental",
        "branch": "oha-develop",
        "source_branch": "feature/local-rc",
        "version": "0.4.0",
        "base_version": "0.4.0",
        "commit": "abc1234567890abc1234567890abc1234567890a",
        "short_commit": "abc1234",
        "build_number": 1,
        "run_number": 1,
        "run_id": "1",
        "tag": "experimental-v0.4.0-build.1-abc1234",
        "signing": "unsigned",
        "dmg_name": dmg.name,
        "sha256": digest,
        "download_url": f"https://github.com/local/oha-yachiyo/releases/download/oha-develop-latest/{dmg.name}",
        "latest_json_url": f"https://github.com/local/oha-yachiyo/releases/download/oha-develop-latest/{metadata_path.name}",
        "published_at": "2026-06-12T00:00:00Z",
        "changelog": {"sections": []},
        "dirty": True,
        "source_tree_fingerprint": "sha256:" + "b" * 64,
        "release_publishable": False,
    }
    _add_app_zip_contract(
        release_dir,
        metadata,
        branch="oha-develop",
        repository="local/oha-yachiyo",
    )
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    strict_findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )
    assert any(
        finding.message
        == "public/latest/final release verification requires clean, publishable source provenance"
        for finding in strict_findings
    )

    local_findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[release_dir],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
        allow_nonpublishable_local_rc=True,
    )
    assert local_findings == []


def test_verifier_rejects_app_zip_content_not_bound_to_latest_metadata(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg = release_dir / "Oha-Yachiyo-main-latest.dmg"
    dmg.write_bytes(b"final dmg")
    dmg_digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (release_dir / f"{dmg.name}.sha256").write_text(
        f"{dmg_digest}  {dmg.name}\n",
        encoding="utf-8",
    )
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
        "run_id": "1",
        "tag": "stable-v0.4.0-build.1-abc1234",
        "signing": "unsigned",
        "dmg_name": dmg.name,
        "sha256": dmg_digest,
        "download_url": (
            "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/"
            f"releases/download/main-latest/{dmg.name}"
        ),
        "latest_json_url": (
            "https://github.com/kuguya-AI-app-develop/Hermes-Yachiyo/releases/"
            "download/main-latest/Oha-Yachiyo-main-latest.json"
        ),
        "published_at": "2026-06-12T00:00:00Z",
        "changelog": {},
        "dirty": False,
        "source_tree_fingerprint": "sha256:" + "a" * 64,
        "release_publishable": True,
    }
    _add_app_zip_contract(release_dir, metadata, branch="main")
    zip_path = release_dir / str(metadata["zip_name"])
    zip_path.write_bytes(b"tampered app zip")
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

    assert any(
        finding.path == zip_path
        and finding.message == "release latest ZIP content does not match latest JSON zip_sha256"
        for finding in findings
    )


def test_verifier_rejects_publishable_latest_metadata_with_nonofficial_urls(tmp_path):
    metadata_path = tmp_path / "Oha-Yachiyo-main-latest.json"
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
        "run_id": "1",
        "tag": "stable-v0.4.0-build.1-abc1234",
        "signing": "unsigned",
        "dmg_name": "Oha-Yachiyo-main-latest.dmg",
        "sha256": "a" * 64,
        "download_url": "http://127.0.0.1/releases/download/main-latest/Oha-Yachiyo-main-latest.dmg",
        "latest_json_url": "http://127.0.0.1/releases/download/main-latest/Oha-Yachiyo-main-latest.json",
        "published_at": "2026-06-12T00:00:00Z",
        "changelog": {},
        "dirty": False,
        "source_tree_fingerprint": "sha256:" + "c" * 64,
        "release_publishable": True,
    }
    metadata.update(
        {
            "signature_kind": "adhoc",
            "architecture": "arm64",
            "zip_name": "Oha-Yachiyo-main-latest-arm64.zip",
            "zip_sha256": "b" * 64,
            "zip_download_url": (
                "http://127.0.0.1/releases/download/main-latest/"
                "Oha-Yachiyo-main-latest-arm64.zip"
            ),
        }
    )

    messages = [
        finding.message
        for finding in verifier._verify_release_latest_json_metadata(
            metadata_path,
            metadata,
        )
    ]
    assert "publishable release latest JSON download_url must use the exact official HTTPS release URL" in messages
    assert "publishable release latest JSON latest_json_url must use the exact official HTTPS release URL" in messages
    assert "publishable release latest JSON zip_download_url must use the exact official HTTPS release URL" in messages


def test_verifier_rejects_signing_claim_mismatched_with_dmg_app(
    tmp_path,
    monkeypatch,
):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg = release_dir / "Oha-Yachiyo-main-latest.dmg"
    dmg.write_bytes(b"fake dmg")
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (release_dir / f"{dmg.name}.sha256").write_text(
        f"{digest}  {dmg.name}\n",
        encoding="utf-8",
    )
    (release_dir / "Oha-Yachiyo-main-latest.json").write_text(
        json.dumps(
            {
                "signing": "self-signed-app-unsigned-dmg",
                "dmg_name": dmg.name,
                "sha256": digest,
                "download_url": f"https://example.invalid/{dmg.name}",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        verifier,
        "inspect_macos_dmg_signing",
        lambda _path: SimpleNamespace(mode="unsigned"),
    )

    findings = verifier._verify_release_directory_artifacts(
        tmp_path,
        [release_dir],
        allow_nonpublishable_local_rc=True,
        inspect_macos_signing=True,
    )
    assert any(
        "signing does not match the packaged App inside its DMG" in finding.message
        for finding in findings
    )


def test_verifier_requires_complete_notarization_evidence_for_developer_id_release(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    metadata_path = release_dir / "Oha-Yachiyo-main-latest.json"

    findings = verifier._verify_release_notarization_evidence(
        release_dir,
        metadata_path,
        {"signing": "developer-id-app-notarized-dmg"},
    )

    assert findings == [
        verifier.Finding(
            release_dir / "notarization.json",
            "release notarization submission evidence is missing",
        ),
        verifier.Finding(
            release_dir / "notarization-log.json",
            "release notarization audit log is missing",
        ),
        verifier.Finding(
            release_dir / "notarization-evidence.json",
            "release notarization DMG evidence is missing",
        ),
    ]


def test_verifier_rejects_mismatched_notarization_evidence(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    metadata_path = release_dir / "Oha-Yachiyo-main-latest.json"
    (release_dir / "notarization.json").write_text(
        json.dumps({"id": "submission-1", "status": "Invalid"}),
        encoding="utf-8",
    )
    (release_dir / "notarization-log.json").write_text(
        json.dumps({"jobId": "submission-2", "status": "Invalid"}),
        encoding="utf-8",
    )
    (release_dir / "notarization-evidence.json").write_text(
        json.dumps(
            {
                "status": "Invalid",
                "submission_id": "submission-3",
                "dmg_sha256": "f" * 64,
                "submission_file": "wrong.json",
                "log_file": "wrong-log.json",
            }
        ),
        encoding="utf-8",
    )

    findings = verifier._verify_release_notarization_evidence(
        release_dir,
        metadata_path,
        {
            "signing": "developer-id-app-notarized-dmg",
            "sha256": "a" * 64,
        },
    )
    messages = [finding.message for finding in findings]

    assert "release notarization submission status must be Accepted" in messages
    assert "release notarization audit log status must be Accepted" in messages
    assert "release notarization audit log jobId must match submission id" in messages
    assert "release notarization DMG evidence status must be Accepted" in messages
    assert "release notarization DMG evidence submission_id must match submission id" in messages
    assert "release notarization DMG evidence must reference notarization.json" in messages
    assert "release notarization DMG evidence must reference notarization-log.json" in messages
    assert "release notarization DMG evidence hash must match latest JSON sha256" in messages


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
                "branch": "oha-develop",
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
                "dmg_name": "Oha-Yachiyo-oha-develop-latest.dmg",
                "sha256": digest,
                "download_url": "https://github.example/releases/download/oha-develop-latest/Oha-Yachiyo-oha-develop-latest.dmg",
                "latest_json_url": "https://github.example/releases/download/oha-develop-latest/Oha-Yachiyo-main-latest.json",
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


def test_verifier_checksum_manifests_bind_exact_dmg_and_zip_filenames(tmp_path):
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    dmg = release_dir / "Oha-Yachiyo-stable-v0.4.0-build.1-abc1234-arm64.dmg"
    app_zip = release_dir / "Oha-Yachiyo-stable-v0.4.0-build.1-abc1234-arm64.zip"
    dmg.write_bytes(b"dmg")
    app_zip.write_bytes(b"zip")
    (release_dir / f"{dmg.name}.sha256").write_text(
        f"{hashlib.sha256(b'dmg').hexdigest()}  wrong.dmg\n",
        encoding="utf-8",
    )
    (release_dir / f"{app_zip.name}.sha256").write_text(
        f"{hashlib.sha256(b'zip').hexdigest()}  wrong.zip\n",
        encoding="utf-8",
    )

    dmg_findings = verifier._verify_release_dmg_checksum_files(release_dir)
    zip_findings = verifier._verify_release_zip_checksum_files(release_dir)

    assert dmg_findings == [
        verifier.Finding(
            release_dir / f"{dmg.name}.sha256",
            "release DMG checksum file must reference its exact filename",
        )
    ]
    assert zip_findings == [
        verifier.Finding(
            release_dir / f"{app_zip.name}.sha256",
            "release ZIP checksum file must reference its exact filename",
        )
    ]


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
    assert "contains legacy product token 'Runtime: Yachiyo Agent Runtime'" in messages_by_path[bundle]
    assert "contains legacy product token 'yachiyo_agent'" not in messages_by_path[bundle]
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


def test_verifier_requires_packaging_backend_runtime_extra_resource(tmp_path):
    config = tmp_path / verifier.PACKAGING_CONFIG_FILE
    config.parent.mkdir(parents=True)
    current_config = (verifier.ROOT / verifier.PACKAGING_CONFIG_FILE).read_text(
        encoding="utf-8"
    )
    required_block = (
        "  - from: ../../dist/backend/runtime\n"
        "    to: backend/runtime"
    )
    assert required_block in current_config
    config.write_text(
        current_config.replace(
            required_block,
            "  - from: ../../dist/backend/runtime\n"
            "    to: backend/runtime-missing",
            1,
        ),
        encoding="utf-8",
    )

    findings = verifier._verify_release_packaging_guards(tmp_path)

    assert verifier.Finding(
        config,
        "macOS release packaging must include the packaged backend runtime",
    ) in findings


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
    assert "macOS release packaging must define a separate Cua Driver signing policy" in messages
    assert (
        "macOS release packaging signIgnore must contain only the exact Cua Driver path"
        in messages
    )
    assert "macOS release packaging must include Apple Events permission copy" in messages
    assert "macOS release packaging must include Documents folder permission copy" in messages
    assert "macOS release packaging must include Downloads folder permission copy" in messages
    assert "macOS release packaging must include microphone permission copy" in messages
    assert "macOS release packaging must include Screen Recording permission copy" in messages


def test_verifier_rejects_additional_electron_sign_ignore_paths(tmp_path):
    config = tmp_path / verifier.PACKAGING_CONFIG_FILE
    config.parent.mkdir(parents=True)
    config.write_text(
        "mac:\n"
        "  signIgnore:\n"
        "    - '/Contents/Resources/computer-use/macos/"
        "OhaCuaDriver\\.app/Contents/MacOS/cua-driver$'\n"
        "    - '/Contents/Resources/.*'\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_packaging_guards(tmp_path)

    assert verifier.Finding(
        config,
        "macOS release packaging signIgnore must contain only the exact Cua Driver path",
    ) in findings


def test_packaged_onefile_cli_smokes_allow_cold_start_time(monkeypatch, tmp_path):
    provider = tmp_path / "oha-yachiyo-desktop-provider"
    bridge = tmp_path / "oha-yachiyo-virtual-desktop-bridge"
    provider.write_bytes(b"provider")
    bridge.write_bytes(b"bridge")
    timeouts = []

    def fake_run(command, **kwargs):
        timeouts.append(kwargs["timeout"])
        if "--manifest" in command:
            stdout = json.dumps(
                {
                    "ok": True,
                    "desktop_session_kind": "virtual_desktop",
                    "capabilities": ["idempotent_tool_requests"],
                    "supported_tools": list(
                        verifier.PACKAGED_DESKTOP_PROVIDER_REQUIRED_TOOLS
                    ),
                }
            )
        else:
            stdout = "--ssh-target --remote-provider-executable"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)

    assert verifier._verify_packaged_desktop_provider_manifest(provider) == []
    assert verifier._verify_packaged_desktop_bridge_cli(bridge) == []
    assert timeouts == [
        verifier.PACKAGED_EXECUTABLE_SMOKE_TIMEOUT_SECONDS,
        verifier.PACKAGED_EXECUTABLE_SMOKE_TIMEOUT_SECONDS,
    ]
    assert verifier.PACKAGED_EXECUTABLE_SMOKE_TIMEOUT_SECONDS == 60


def test_verifier_requires_macos_signing_script_and_entitlements(tmp_path):
    script = tmp_path / verifier.MACOS_SIGNING_SCRIPT_FILE
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/usr/bin/env bash\n"
        "npx electron-builder --config electron-builder.yml --mac dmg\n",
        encoding="utf-8",
    )
    notarization_script = tmp_path / verifier.MACOS_NOTARIZATION_SCRIPT_FILE
    notarization_script.write_text("#!/usr/bin/env bash\necho incomplete\n", encoding="utf-8")
    entitlements = tmp_path / verifier.MACOS_ENTITLEMENTS_FILE
    entitlements.parent.mkdir(parents=True)
    entitlements.write_text("<plist><dict></dict></plist>\n", encoding="utf-8")

    findings = verifier._verify_macos_signing_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS signing script must build an unsigned app directory before signing" in messages
    assert "macOS signing script must sign the app with hardened runtime options" in messages
    assert "macOS signing script must request a secure timestamp for Developer ID releases" in messages
    assert "macOS signing script must apply the checked-in entitlements" in messages
    assert "macOS signing script must apply the dedicated Cua Driver entitlements" in messages
    assert "macOS signing script must sign backend binaries with the stable backend identifier" in messages
    assert "macOS signing script must apply the dedicated backend entitlements" in messages
    assert "macOS signing script must explicitly sign the standalone backend binary" in messages
    assert "macOS signing script must explicitly sign the embedded backend binary" in messages
    assert "macOS signing script must verify backend binaries after signing" in messages
    assert "macOS signing script must inspect backend signature metadata after signing" in messages
    assert "macOS signing script must inspect backend designated requirements after signing" in messages
    assert "macOS signing script must reject backend signatures with unstable identifiers" in messages
    assert "macOS signing script must reject cdhash-only backend designated requirements" in messages
    assert "macOS signing script must require the stable backend identifier in designated requirements" in messages
    assert "macOS signing script must verify the nested Cua Driver signature" in messages
    assert "macOS signing script must verify the final Cua Driver entitlements" in messages
    assert "macOS signing script must verify the signed app bundle" in messages
    assert "macOS signing script must create the unsigned DMG from the signed app bundle" in messages
    assert "macOS notarization script must submit the DMG with notarytool" in messages
    assert "macOS notarization script must wait for a final Apple notary result" in messages
    assert "macOS notarization script must retrieve the Apple notary audit log" in messages
    assert "macOS notarization script must staple the accepted ticket to the DMG" in messages
    assert "macOS notarization script must validate the stapled ticket" in messages
    assert "macOS notarization script must run a Gatekeeper assessment on the DMG" in messages
    assert "macOS entitlements must allow JIT for the Electron runtime" in messages
    assert "macOS entitlements must allow unsigned executable memory for Electron" in messages
    assert "macOS entitlements must disable library validation for packaged native modules" in messages
    assert any("could not read Cua Driver entitlements" in message for message in messages)


def test_verifier_rejects_broad_cua_driver_entitlements(tmp_path):
    script = tmp_path / verifier.MACOS_SIGNING_SCRIPT_FILE
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    notarization_script = tmp_path / verifier.MACOS_NOTARIZATION_SCRIPT_FILE
    notarization_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    app_entitlements = tmp_path / verifier.MACOS_ENTITLEMENTS_FILE
    app_entitlements.parent.mkdir(parents=True, exist_ok=True)
    app_entitlements.write_bytes(plistlib.dumps({}))
    cua_entitlements = tmp_path / verifier.CUA_DRIVER_ENTITLEMENTS_FILE
    cua_entitlements.write_bytes(
        plistlib.dumps(
            {
                **verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS,
                "com.apple.security.cs.allow-jit": True,
            }
        )
    )

    findings = verifier._verify_macos_signing_guards(tmp_path)

    assert verifier.Finding(
        cua_entitlements,
        "Cua Driver entitlements must contain exactly Apple Events and Screen Capture",
    ) in findings


def test_verifier_rejects_missing_backend_entitlements_file(tmp_path):
    script = tmp_path / verifier.MACOS_SIGNING_SCRIPT_FILE
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    notarization_script = tmp_path / verifier.MACOS_NOTARIZATION_SCRIPT_FILE
    notarization_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    app_entitlements = tmp_path / verifier.MACOS_ENTITLEMENTS_FILE
    app_entitlements.parent.mkdir(parents=True, exist_ok=True)
    app_entitlements.write_bytes(plistlib.dumps({}))
    cua_entitlements = tmp_path / verifier.CUA_DRIVER_ENTITLEMENTS_FILE
    cua_entitlements.write_bytes(plistlib.dumps(verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS))

    findings = verifier._verify_macos_signing_guards(tmp_path)

    assert verifier.Finding(
        tmp_path / verifier.BACKEND_ENTITLEMENTS_FILE,
        "could not read backend entitlements: FileNotFoundError",
    ) in findings


def test_verifier_rejects_broad_backend_entitlements(tmp_path):
    script = tmp_path / verifier.MACOS_SIGNING_SCRIPT_FILE
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    notarization_script = tmp_path / verifier.MACOS_NOTARIZATION_SCRIPT_FILE
    notarization_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    app_entitlements = tmp_path / verifier.MACOS_ENTITLEMENTS_FILE
    app_entitlements.parent.mkdir(parents=True, exist_ok=True)
    app_entitlements.write_bytes(plistlib.dumps({}))
    backend_entitlements = tmp_path / verifier.BACKEND_ENTITLEMENTS_FILE
    backend_entitlements.write_bytes(
        plistlib.dumps(
            {
                **verifier.PACKAGED_BACKEND_EXPECTED_ENTITLEMENTS,
                "com.apple.security.cs.allow-jit": True,
            }
        )
    )
    cua_entitlements = tmp_path / verifier.CUA_DRIVER_ENTITLEMENTS_FILE
    cua_entitlements.write_bytes(plistlib.dumps(verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS))

    findings = verifier._verify_macos_signing_guards(tmp_path)

    assert verifier.Finding(
        backend_entitlements,
        "backend entitlements must contain exactly disable-library-validation=true",
    ) in findings


def test_verifier_rejects_macos_signing_order_regressions(tmp_path):
    script_path = tmp_path / verifier.MACOS_SIGNING_SCRIPT_FILE
    script_path.parent.mkdir(parents=True, exist_ok=True)
    current_script = (verifier.ROOT / verifier.MACOS_SIGNING_SCRIPT_FILE).read_text(
        encoding="utf-8"
    )
    cua_sign = 'codesign "${cua_codesign_args[@]}" "${CUA_HELPER_PATH}"'
    backend_sign = 'codesign "${backend_codesign_args[@]}" "${PACKAGED_BACKEND_PATH}"'
    outer_sign = 'codesign "${codesign_args[@]}" "${APP_PATH}"'
    assert cua_sign in current_script
    assert backend_sign in current_script
    assert outer_sign in current_script
    mutated = current_script.replace(cua_sign + "\n", "", 1)
    mutated = mutated.replace(backend_sign + "\n", "", 1)
    mutated = mutated.replace(
        outer_sign + "\n",
        outer_sign + "\n" + cua_sign + "\n" + backend_sign + "\n",
        1,
    )
    script_path.write_text(mutated, encoding="utf-8")

    notarization_script = tmp_path / verifier.MACOS_NOTARIZATION_SCRIPT_FILE
    notarization_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    app_entitlements = tmp_path / verifier.MACOS_ENTITLEMENTS_FILE
    app_entitlements.parent.mkdir(parents=True, exist_ok=True)
    app_entitlements.write_text(
        "<plist><dict>"
        "<key>com.apple.security.cs.allow-jit</key><true/>"
        "<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>"
        "<key>com.apple.security.cs.disable-library-validation</key><true/>"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    backend_entitlements = tmp_path / verifier.BACKEND_ENTITLEMENTS_FILE
    backend_entitlements.write_bytes(
        plistlib.dumps(verifier.PACKAGED_BACKEND_EXPECTED_ENTITLEMENTS)
    )
    cua_entitlements = tmp_path / verifier.CUA_DRIVER_ENTITLEMENTS_FILE
    cua_entitlements.write_bytes(
        plistlib.dumps(verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS)
    )
    helper_info = tmp_path / verifier.CUA_DRIVER_HELPER_INFO_FILE
    helper_info.parent.mkdir(parents=True, exist_ok=True)
    helper_info.write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": verifier.PACKAGED_CUA_DRIVER_BINARY_NAME,
                "CFBundleIdentifier": verifier.PACKAGED_CUA_DRIVER_HELPER_BUNDLE_ID,
                "CFBundlePackageType": "APPL",
                "LSBackgroundOnly": True,
            }
        )
    )

    findings = verifier._verify_macos_signing_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS signing script must sign the Cua helper before signing the outer app bundle" in messages
    assert (
        "macOS signing script must sign standalone and embedded backend binaries before signing the outer app bundle"
        in messages
    )


def test_verifier_requires_release_packaging_docs_for_release_gates(tmp_path):
    doc = tmp_path / verifier.RELEASE_PACKAGING_DOC_FILE
    doc.parent.mkdir(parents=True)
    doc.write_text("# Release Packaging\n\nBuild and upload DMG.\n", encoding="utf-8")

    findings = verifier._verify_release_packaging_documentation(tmp_path)
    messages = [finding.message for finding in findings]

    assert "release packaging docs must document the dedicated Cua Driver entitlement policy" in messages
    assert "release packaging docs must require signing verification for certificate-free builds" in messages
    assert "release packaging docs must document that legacy develop is not an Oha release branch" in messages
    assert "release packaging docs must document the Oha experimental latest DMG name" in messages
    assert "release packaging docs must document the pre-dependency release guard" in messages
    assert "release packaging docs must document debug route guard coverage" in messages
    assert "release packaging docs must document release CredentialStore fallback guard coverage" in messages
    assert "release packaging docs must document final packaged app signature verification" in messages
    assert "release packaging docs must document final release artifact binary scanning" in messages
    assert "release packaging docs must document latest JSON DMG/ZIP checksum consistency checks" in messages
    assert "release packaging docs must document latest JSON metadata format validation" in messages
    assert "release packaging docs must document source provenance and publishability metadata" in messages
    assert "release packaging docs must document the explicit dirty local RC build mode" in messages
    assert "release packaging docs must document explicit non-publishable local inspection" in messages
    assert "release packaging docs must document reusable app build metadata preparation" in messages
    assert "release packaging docs must document local RC artifact build helper" in messages
    assert "release packaging docs must document local RC signoff refresh helper" in messages
    assert "release packaging docs must document public release preflight gate" in messages
    assert "release packaging docs must document public release gate coverage" in messages
    assert "release packaging docs must document public release gate release-smoke output" in messages
    assert "release packaging docs must document public release gate missing user path output" in messages
    assert "release packaging docs must document public release gate existing report inputs" in messages
    assert "release packaging docs must document strict public release gate mode" in messages
    assert "release packaging docs must document local RC public demo evidence output" in messages
    assert "release packaging docs must document local RC Oha product smoke evidence output" in messages
    assert "release packaging docs must document public demo release assessment fields" in messages
    assert "release packaging docs must document the 10-item release smoke checklist" in messages
    assert "release packaging docs must document local RC signoff resume/reuse mode" in messages
    assert "release packaging docs must document local RC signoff status shortcut" in messages
    assert "release packaging docs must document print-status public demo blocker output" in messages
    assert "release packaging docs must document local RC OS evidence shortcut" in messages
    assert "release packaging docs must document per-DMG/ZIP checksum file validation" in messages
    assert "release packaging docs must document the local RC verification entrypoint" in messages
    assert "release packaging docs must document the local RC DMG mount gate" in messages
    assert "release packaging docs must document the opt-in real desktop app open smoke" in messages
    assert "release packaging docs must document the opt-in real desktop UI inspection smoke" in messages
    assert "release packaging docs must document the opt-in real desktop interaction smoke" in messages
    assert "release packaging docs must document locked-session interaction evidence" in messages
    assert (
        "release packaging docs must document real desktop UI inspection smoke evidence fields"
        in messages
    )
    assert "release packaging docs must document real desktop app open smoke side effects" in messages
    assert "release packaging docs must document the local RC packaged app startup smoke" in messages
    assert "release packaging docs must document the local RC packaged screen recording smoke" in messages
    assert "release packaging docs must document the local RC real provider smoke gate" in messages
    assert "release packaging docs must document local RC helper cleans stale Electron artifacts" in messages
    assert "release packaging docs must document native Agent and Workflow full-chain provider smoke coverage" in messages
    assert "release packaging docs must document the local RC Electron UI smoke gate" in messages
    assert "release packaging docs must document the archived Electron UI smoke runner report" in messages
    assert "release packaging docs must document the archived Electron UI smoke report" in messages
    assert (
        "release packaging docs must document standalone Electron UI smoke signoff evidence merging"
        in messages
    )
    assert "release packaging docs must include public demo JSON in release smoke command" in messages
    assert "release packaging docs must document release smoke checks 10 user paths" in messages
    assert "release packaging docs must include public demo in release smoke user paths" in messages
    assert (
        "release packaging docs must document partial or blocked public demo release smoke behavior"
        in messages
    )
    assert "release packaging docs must document the source-only RC dry run" in messages
    assert (
        "release packaging docs must document the CI release-candidate gate and packaged app startup smoke before upload"
        in messages
    )
    assert "release packaging docs must document the archived RC verification report" in messages
    assert "release packaging docs must document the archived manual RC check template" in messages
    assert "release packaging docs must document the archived manual RC check draft" in messages
    assert "release packaging docs must document the archived manual RC check Markdown checklist" in messages
    assert "release packaging docs must document structured manual RC check statuses" in messages
    assert "release packaging docs must document manual RC check evidence input" in messages
    assert "release packaging docs must document manual RC check Markdown evidence input" in messages
    assert "release packaging docs must document manual RC check template generation" in messages
    assert "release packaging docs must document manual RC check draft generation" in messages
    assert "release packaging docs must document manual RC check Markdown generation" in messages
    assert (
        "release packaging docs must document recommended automation commands for remaining manual checks"
        in messages
    )
    assert "release packaging docs must document checked Markdown items default to passed" in messages
    assert "release packaging docs must document explicit Markdown not_applicable status" in messages
    assert "release packaging docs must document Markdown signoff evidence requirements" in messages
    assert (
        "release packaging docs must document direct no-provider Markdown signoff draft generation"
        in messages
    )
    assert "release packaging docs must document UI smoke supporting evidence notes" in messages
    assert "release packaging docs must document UI smoke does not auto-pass manual checks" in messages
    assert (
        "release packaging docs must document explicit provider-smoke not_applicable draft evidence"
        in messages
    )
    assert "release packaging docs must document final manual RC signoff enforcement" in messages
    assert (
        "release packaging docs must document stale manual evidence source revision rejection"
        in messages
    )
    assert (
        "release packaging docs must document missing manual evidence source revision rejection"
        in messages
    )
    assert "release packaging docs must document the Gatekeeper manual RC check id" in messages
    assert "release packaging docs must document the screen recording manual RC check id" in messages
    assert "release packaging docs must document the native Chat file upload manual RC check id" in messages
    assert "release packaging docs must document the packaged UI sampling manual RC check id" in messages


def test_verifier_requires_user_facing_release_docs_for_first_launch(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Oha-Yachiyo\n\n首次启动后配置模型。\n", encoding="utf-8")
    manual = tmp_path / "docs" / "user-manual.md"
    manual.parent.mkdir(parents=True)
    manual.write_text("# Oha-Yachiyo 使用手册\n\n首次启动后进入主窗口。\n", encoding="utf-8")
    public_release = tmp_path / "docs" / "public-release-readiness.md"
    public_release.write_text("# Public Release\n\nSupported product shape.\n", encoding="utf-8")
    contributing = tmp_path / "CONTRIBUTING.md"
    contributing.write_text("# Contributing\n\nTesting expectations.\n", encoding="utf-8")

    findings = verifier._verify_user_facing_release_docs(tmp_path)
    messages = [finding.message for finding in findings]

    assert "README must document Gatekeeper first-launch handling" in messages
    assert "README must document macOS Screen Recording permission" in messages
    assert "user manual must document Gatekeeper first-launch handling" in messages
    assert "user manual must document macOS Screen Recording permission" in messages
    assert "README must link the public release readiness guide" in messages
    assert "README must link the contribution guide" in messages
    assert "user manual must document the diagnostics bundle support path" in messages
    assert "public release readiness guide must document known limitations" in messages
    assert "public release readiness guide must state packaged runtime expectations" in messages
    assert "public release readiness guide must document the public demo smoke runner" in messages
    assert "public release readiness guide must document the public release gate runner" in messages
    assert "public release readiness guide must document strict public release gate mode" in messages
    assert "public release readiness guide must document public release gate release-smoke output" in messages
    assert "public release readiness guide must document strict release-smoke evidence enforcement" in messages
    assert "public release readiness guide must document public release gate existing report inputs" in messages
    assert "public release readiness guide must document RC public demo evidence output" in messages
    assert "public release readiness guide must document RC Oha product smoke evidence output" in messages
    assert "public release readiness guide must document desktop planner public demo evidence" in messages
    assert "public release readiness guide must document real desktop discovery public demo evidence" in messages
    assert "public release readiness guide must document granular real desktop demo flags" in messages
    assert "public release readiness guide must document WorkflowRun public demo evidence" in messages
    assert "contribution guide must document non-negotiable product boundaries" in messages
    assert "contribution guide must document public demo smoke evidence" in messages
    assert "contribution guide must document granular real desktop demo flags" in messages


_TEST_CUA_CONTENT_HASH_ALGORITHM = "mach-o-without-code-signature-v1"
_TEST_CUA_CONTENT_SHA256 = "c" * 64


def _packaged_fixture_executable(
    command,
    relative_path: Path,
) -> Path | None:
    if not isinstance(command, (list, tuple)) or not command:
        return None
    candidate = Path(command[0])
    relative_parts = relative_path.parts
    if (
        verifier.PACKAGED_APP_NAME not in candidate.parts
        or len(candidate.parts) < len(relative_parts)
        or candidate.parts[-len(relative_parts) :] != relative_parts
    ):
        return None
    return candidate


def _fixture_json_heredoc(script: str) -> str | None:
    match = re.search(r"cat <<'JSON'\n(?P<payload>\{.*?\})\nJSON(?:\n|$)", script, re.DOTALL)
    return match.group("payload") if match is not None else None


def _packaged_shell_fixture_text(path: Path) -> str | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if not payload.startswith(b"#!/bin/sh\n"):
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


@pytest.fixture(autouse=True)
def _run_packaged_shell_fixtures_deterministically(monkeypatch):
    """Keep verifier subprocess parsing real without executing temp shell fixtures.

    macOS may SIGKILL newly-created executable scripts in pytest's temporary tree.
    These fixtures model only the three shell scripts written below; real packaged
    binaries remain subject to the production subprocess and signature checks.
    """

    original_run = subprocess.run

    def run(command, *args, **kwargs):
        cua_driver = _packaged_fixture_executable(
            command,
            verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
            / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH,
        )
        if cua_driver is not None:
            script = _packaged_shell_fixture_text(cua_driver)
            if script is not None:
                arguments = [str(item) for item in command[1:]]
                if arguments == ["--version"]:
                    match = re.search(
                        r"cua-driver (?P<version>[0-9][A-Za-z0-9.+-]*)",
                        script,
                    )
                    if match is not None:
                        return subprocess.CompletedProcess(
                            command,
                            0,
                            stdout=f"cua-driver {match.group('version')}\n",
                            stderr="",
                        )
                elif arguments == ["manifest"]:
                    payload = _fixture_json_heredoc(script)
                    if payload is not None:
                        return subprocess.CompletedProcess(
                            command,
                            0,
                            stdout=f"{payload}\n",
                            stderr="",
                        )
                return subprocess.CompletedProcess(command, 2, stdout="", stderr="")

        desktop_provider = _packaged_fixture_executable(
            command,
            verifier.PACKAGED_DESKTOP_PROVIDER_RELATIVE_PATH,
        )
        if desktop_provider is not None:
            script = _packaged_shell_fixture_text(desktop_provider)
            if script is not None:
                payload = _fixture_json_heredoc(script)
                if payload is not None:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=f"{payload}\n",
                        stderr="",
                    )
                if "echo not-json" in script:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout="not-json\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 2, stdout="", stderr="")

        desktop_bridge = _packaged_fixture_executable(
            command,
            verifier.PACKAGED_DESKTOP_BRIDGE_RELATIVE_PATH,
        )
        if desktop_bridge is not None:
            script = _packaged_shell_fixture_text(desktop_bridge)
            if script is not None:
                help_match = re.search(r"echo '([^']*)'", script)
                if help_match is not None:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=f"{help_match.group(1)}\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 2, stdout="", stderr="")

        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(verifier.subprocess, "run", run)


def _stub_packaged_cua_content_digest(monkeypatch, *, digest=_TEST_CUA_CONTENT_SHA256):
    monkeypatch.setattr(
        verifier,
        "_sha256_macho_without_code_signature",
        lambda _path: digest,
        raising=False,
    )
    monkeypatch.setattr(
        verifier,
        "_run_codesign_verify",
        lambda _path, *, deep=False: None,
        raising=False,
    )
    monkeypatch.setattr(
        verifier,
        "_read_codesign_entitlements",
        lambda path: (
            dict(verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS)
            if Path(path).name == verifier.PACKAGED_CUA_DRIVER_BINARY_NAME
            else dict(verifier.PACKAGED_BACKEND_EXPECTED_ENTITLEMENTS)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        verifier,
        "_read_codesign_display",
        lambda _path: (
            "Identifier="
            f"{verifier.PACKAGED_BACKEND_IDENTIFIER}\n"
            "Signature=Authority-signed\n"
        ),
        raising=False,
    )
    monkeypatch.setattr(
        verifier,
        "_read_codesign_designated_requirement",
        lambda _path: (
            "designated => "
            f'identifier "{verifier.PACKAGED_BACKEND_IDENTIFIER}" and anchor trusted'
        ),
        raising=False,
    )


def test_packaged_cua_signing_policy_rejects_electron_jit_entitlements(
    monkeypatch,
    tmp_path,
):
    binary_path = tmp_path / "cua-driver"
    binary_path.write_bytes(b"fixture")
    monkeypatch.setattr(
        verifier,
        "_run_codesign_verify",
        lambda _path, *, deep=False: None,
    )
    monkeypatch.setattr(
        verifier,
        "_read_codesign_entitlements",
        lambda _path: {
            **verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS,
            "com.apple.security.cs.allow-jit": True,
        },
    )

    findings = verifier._verify_packaged_cua_code_signature(binary_path)

    assert findings == [
        verifier.Finding(
            binary_path,
            "packaged Cua Driver entitlements must contain exactly Apple Events and Screen Capture",
        )
    ]


def test_packaged_cua_signing_policy_fails_closed_on_invalid_signature(
    monkeypatch,
    tmp_path,
):
    binary_path = tmp_path / "cua-driver"
    binary_path.write_bytes(b"fixture")

    def reject_signature(_path, *, deep=False):
        raise RuntimeError("invalid signature")

    monkeypatch.setattr(verifier, "_run_codesign_verify", reject_signature)
    monkeypatch.setattr(
        verifier,
        "_read_codesign_entitlements",
        lambda _path: dict(verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS),
    )

    findings = verifier._verify_packaged_cua_code_signature(binary_path)

    assert findings == [
        verifier.Finding(
            binary_path,
            "packaged Cua Driver code signature verification failed: RuntimeError",
        )
    ]


def test_packaged_app_signing_policy_requires_deep_strict_verification(
    monkeypatch,
    tmp_path,
):
    app_dir = tmp_path / verifier.PACKAGED_APP_NAME
    app_dir.mkdir()
    captured = []

    def capture(path, *, deep=False):
        captured.append((path, deep))

    monkeypatch.setattr(verifier, "_run_codesign_verify", capture)

    assert verifier._verify_packaged_app_code_signature(app_dir) == []
    assert captured == [(app_dir, True)]


def test_codesign_helpers_use_fixed_argv_and_parse_xml_entitlements(
    monkeypatch,
    tmp_path,
):
    binary_path = tmp_path / "cua-driver; touch injected"
    binary_path.write_bytes(b"fixture")
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        if command[:3] == ["/usr/bin/codesign", "-d", "--verbose=4"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr=(
                    f"Identifier={verifier.PACKAGED_BACKEND_IDENTIFIER}\n"
                    "Signature=Authority-signed\n"
                ),
            )
        if command[:3] == ["/usr/bin/codesign", "-dr", "-"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="",
                stderr=(
                    "designated => "
                    f'identifier "{verifier.PACKAGED_BACKEND_IDENTIFIER}" and anchor trusted\n'
                ),
            )
        if "--entitlements" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=plistlib.dumps(
                    verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS
                ),
                stderr=b"",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)

    verifier._run_codesign_verify(binary_path, deep=True)
    display = verifier._read_codesign_display(binary_path)
    requirement = verifier._read_codesign_designated_requirement(binary_path)
    entitlements = verifier._read_codesign_entitlements(binary_path)

    assert commands[0][0] == [
        "/usr/bin/codesign",
        "--verify",
        "--deep",
        "--strict",
        "--verbose=2",
        str(binary_path),
    ]
    assert commands[1][0] == [
        "/usr/bin/codesign",
        "-d",
        "--verbose=4",
        str(binary_path),
    ]
    assert commands[2][0] == [
        "/usr/bin/codesign",
        "-dr",
        "-",
        str(binary_path),
    ]
    assert commands[3][0] == [
        "/usr/bin/codesign",
        "-d",
        "--entitlements",
        "-",
        "--xml",
        str(binary_path),
    ]
    assert "Identifier=" in display
    assert "designated => " in requirement
    assert entitlements == verifier.PACKAGED_CUA_DRIVER_EXPECTED_ENTITLEMENTS


def _write_packaged_cua_sidecar(root, app_dir, *, binary_mode=0o755):
    version = "0.7.1"
    tag = f"cua-driver-rs-v{version}"
    archive_sha = "a" * 64
    archive_url = (
        f"https://github.com/trycua/cua/releases/download/{tag}/"
        f"cua-driver-rs-{version}-darwin-universal-binary.tar.gz"
    )
    license_payload = b"MIT License\n"
    license_sha = hashlib.sha256(license_payload).hexdigest()
    license_url = f"https://raw.githubusercontent.com/trycua/cua/{tag}/LICENSE.md"
    lock_payload = {
        "schema_version": 1,
        "name": "cua-driver",
        "version": version,
        "tag": tag,
        "platform": "darwin-universal",
        "architectures": ["arm64", "x86_64"],
        "archive": {
            "name": f"cua-driver-rs-{version}-darwin-universal-binary.tar.gz",
            "url": archive_url,
            "sha256": archive_sha,
            "binary_member": "cua-driver",
            "binary_content_hash_algorithm": _TEST_CUA_CONTENT_HASH_ALGORITHM,
            "binary_content_sha256": _TEST_CUA_CONTENT_SHA256,
        },
        "license": {
            "name": "LICENSE.md",
            "url": license_url,
            "sha256": license_sha,
            "spdx": "MIT",
        },
    }
    lock_path = root / verifier.CUA_DRIVER_LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock_payload), encoding="utf-8")

    sidecar_dir = app_dir / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    binary_path = (
        sidecar_dir / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
    )
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    helper_info_path = (
        sidecar_dir / verifier.PACKAGED_CUA_DRIVER_INFO_RELATIVE_PATH
    )
    helper_info_path.write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": verifier.PACKAGED_CUA_DRIVER_BINARY_NAME,
                "CFBundleIdentifier": (
                    verifier.PACKAGED_CUA_DRIVER_HELPER_BUNDLE_ID
                ),
                "CFBundleName": "Oha Cua Driver",
                "CFBundlePackageType": "APPL",
                "CFBundleVersion": "1",
                "LSBackgroundOnly": True,
            }
        )
    )
    runtime_manifest = {
        "schema_version": "1",
        "binary_version": version,
        "mcp_invocation": {"command": str(binary_path), "args": ["mcp"]},
        "subcommands": [
            {
                "name": "mcp",
                "args": [
                    {"name": "--embedded", "type": "flag"},
                    {"name": "--host-bundle-id", "type": "string"},
                ],
            }
        ],
    }
    binary_path.write_text(
        "#!/bin/sh\n"
        "case \"${1:-}\" in\n"
        f"  --version) printf '%s\\n' 'cua-driver {version}' ;;\n"
        "  manifest) cat <<'JSON'\n"
        f"{json.dumps(runtime_manifest)}\n"
        "JSON\n"
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    binary_path.chmod(binary_mode)
    (sidecar_dir / verifier.PACKAGED_CUA_DRIVER_LICENSE_NAME).write_bytes(
        license_payload
    )
    packaged_manifest = {
        "schema_version": 1,
        "component": "cua-driver",
        "version": version,
        "tag": tag,
        "platform": "darwin-universal",
        "architectures": ["arm64", "x86_64"],
        "lock": {
            "path": "packaging/cua-driver.lock.json",
            "sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        },
        "source": {
            "archive_name": lock_payload["archive"]["name"],
            "archive_url": archive_url,
            "archive_sha256": archive_sha,
        },
        # Deliberately represents the pre-signing input, not this executable stub.
        "binary": {
            "file": "cua-driver",
            "sha256": "b" * 64,
            "content_hash_algorithm": _TEST_CUA_CONTENT_HASH_ALGORITHM,
            "content_sha256": _TEST_CUA_CONTENT_SHA256,
            "mode": "0755",
        },
        "license": {
            "file": "LICENSE.md",
            "spdx": "MIT",
            "source_url": license_url,
            "sha256": license_sha,
        },
        "validation": {
            "binary_version": version,
            "manifest_schema_version": "1",
            "embedded_mcp": True,
            "architectures": ["arm64", "x86_64"],
        },
    }
    (sidecar_dir / verifier.PACKAGED_CUA_DRIVER_MANIFEST_NAME).write_text(
        json.dumps(packaged_manifest),
        encoding="utf-8",
    )
    return sidecar_dir


def _write_packaged_app_bundle(
    root,
    *,
    app_dir=None,
    identifier=verifier.PACKAGED_APP_IDENTIFIER,
    executable_mode=0o755,
    backend_mode=0o755,
    desktop_provider_mode=0o755,
    include_desktop_provider=True,
    desktop_bridge_mode=0o755,
    include_desktop_bridge=True,
    include_asar=True,
    include_permission_copy=True,
    include_backend_metadata=True,
    include_cua_driver=True,
    cua_driver_mode=0o755,
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
                "NSScreenCaptureUsageDescription": "Oha-Yachiyo 需要读取当前屏幕内容。",
            }
        )
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    executable = macos_dir / "Oha-Yachiyo"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(executable_mode)
    if include_cua_driver:
        _write_packaged_cua_sidecar(
            root,
            app_dir,
            binary_mode=cua_driver_mode,
        )
    backend = app_dir / verifier.PACKAGED_BACKEND_RELATIVE_PATH
    backend.parent.mkdir(parents=True, exist_ok=True)
    backend_bytes = b"#!/bin/sh\nexit 0\n"
    if include_backend_metadata:
        backend_bytes += b"\n" + verifier.PACKAGED_BACKEND_BUILD_METADATA_MARKER + b"\n"
    backend.write_bytes(backend_bytes)
    backend.chmod(backend_mode)
    if include_desktop_provider:
        desktop_provider = app_dir / verifier.PACKAGED_DESKTOP_PROVIDER_RELATIVE_PATH
        desktop_provider.parent.mkdir(parents=True, exist_ok=True)
        desktop_provider.write_text(
            "#!/bin/sh\n"
            "cat <<'JSON'\n"
            + json.dumps(
                {
                    "ok": True,
                    "desktop_session_kind": "virtual_desktop",
                    "capabilities": ["idempotent_tool_requests"],
                    "supported_tools": list(
                        verifier.PACKAGED_DESKTOP_PROVIDER_REQUIRED_TOOLS
                    ),
                }
            )
            + "\nJSON\n",
            encoding="utf-8",
        )
        desktop_provider.chmod(desktop_provider_mode)
    if include_desktop_bridge:
        desktop_bridge = app_dir / verifier.PACKAGED_DESKTOP_BRIDGE_RELATIVE_PATH
        desktop_bridge.parent.mkdir(parents=True, exist_ok=True)
        desktop_bridge.write_text(
            "#!/bin/sh\n"
            "echo 'usage: bridge --ssh-target TARGET "
            "--remote-provider-executable PATH'\n",
            encoding="utf-8",
        )
        desktop_bridge.chmod(desktop_bridge_mode)
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


def test_verifier_accepts_packaged_app_bundle_structure(monkeypatch, tmp_path):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == []
    sidecar_dir = app_dir / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
    packaged_binary_sha = hashlib.sha256(
        (
            sidecar_dir / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
        ).read_bytes()
    ).hexdigest()
    recorded_unsigned_sha = json.loads(
        (sidecar_dir / verifier.PACKAGED_CUA_DRIVER_MANIFEST_NAME).read_text("utf-8")
    )["binary"]["sha256"]
    assert packaged_binary_sha != recorded_unsigned_sha


def test_verifier_discovers_packaged_app_when_paths_are_omitted(monkeypatch, tmp_path):
    _stub_packaged_cua_content_digest(monkeypatch)
    monkeypatch.setattr(verifier, "DEFAULT_SCAN_PATHS", ())
    _write_packaged_app_bundle(tmp_path)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=None,
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == []


def test_verifier_requires_complete_packaged_cua_driver_resources(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    sidecar_dir = app_dir / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
    for name in (
        verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH,
        verifier.PACKAGED_CUA_DRIVER_LICENSE_NAME,
        verifier.PACKAGED_CUA_DRIVER_MANIFEST_NAME,
        verifier.PACKAGED_CUA_DRIVER_INFO_RELATIVE_PATH,
    ):
        (sidecar_dir / name).unlink()

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )
    messages = [finding.message for finding in findings]

    assert "packaged Cua Driver binary is missing from app resources" in messages
    assert "packaged Cua Driver license is missing from app resources" in messages
    assert "packaged Cua Driver manifest is missing from app resources" in messages
    assert (
        "packaged Cua Driver helper Info.plist is missing from app resources"
        in messages
    )


def test_verifier_rejects_cua_helper_that_can_become_foreground(tmp_path):
    info_path = tmp_path / "Info.plist"
    info_path.write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": verifier.PACKAGED_CUA_DRIVER_BINARY_NAME,
                "CFBundleIdentifier": (
                    verifier.PACKAGED_CUA_DRIVER_HELPER_BUNDLE_ID
                ),
                "CFBundlePackageType": "APPL",
                "LSBackgroundOnly": False,
            }
        )
    )

    assert verifier._verify_packaged_cua_helper_info(info_path) == [
        verifier.Finding(
            info_path,
            "packaged Cua Driver helper must be an LSBackgroundOnly app bundle",
        )
    ]


@pytest.mark.parametrize(
    ("resource_name", "expected_message"),
    [
        (
            verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH,
            "packaged Cua Driver binary must not be a symlink",
        ),
        (
            verifier.PACKAGED_CUA_DRIVER_LICENSE_NAME,
            "packaged Cua Driver license must not be a symlink",
        ),
        (
            verifier.PACKAGED_CUA_DRIVER_MANIFEST_NAME,
            "packaged Cua Driver manifest must not be a symlink",
        ),
    ],
)
def test_verifier_rejects_packaged_cua_driver_resource_symlinks(
    tmp_path,
    resource_name,
    expected_message,
):
    app_dir = _write_packaged_app_bundle(tmp_path)
    sidecar_dir = app_dir / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
    resource_path = sidecar_dir / resource_name
    external_path = tmp_path / f"external-{Path(resource_name).name}"
    external_path.write_bytes(resource_path.read_bytes())
    if resource_name == verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH:
        external_path.chmod(0o755)
    resource_path.unlink()
    resource_path.symlink_to(external_path)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(resource_path, expected_message) in findings


@pytest.mark.parametrize(
    ("relative_directory", "expected_message"),
    [
        (
            Path("Contents/Resources/computer-use"),
            "packaged Cua Driver parent resource directory must be a real directory, not a symlink",
        ),
        (
            verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR,
            "packaged Cua Driver resource directory must be a real directory, not a symlink",
        ),
        (
            verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
            / verifier.PACKAGED_CUA_DRIVER_HELPER_NAME,
            "packaged Cua Driver helper app must be a real directory, not a symlink",
        ),
    ],
)
def test_verifier_rejects_packaged_cua_driver_ancestor_symlinks(
    tmp_path,
    relative_directory,
    expected_message,
):
    app_dir = _write_packaged_app_bundle(tmp_path)
    directory_path = app_dir / relative_directory
    external_path = tmp_path / f"external-{'-'.join(relative_directory.parts)}"
    directory_path.rename(external_path)
    directory_path.symlink_to(external_path, target_is_directory=True)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(directory_path, expected_message) in findings


def test_verifier_rejects_packaged_cua_driver_lock_and_runtime_mismatches(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    sidecar_dir = app_dir / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
    manifest_path = sidecar_dir / verifier.PACKAGED_CUA_DRIVER_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["tag"] = "cua-driver-rs-v9.9.9"
    manifest["architectures"] = ["arm64"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    binary_path = sidecar_dir / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
    binary_path.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = --version ]; then echo 'cua-driver 9.9.9'; exit 0; fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    binary_path.chmod(0o755)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )
    messages = [finding.message for finding in findings]

    assert "packaged Cua Driver manifest does not match the dependency lock" in messages
    assert "packaged Cua Driver version does not match the lock" in messages


def test_verifier_rejects_tampered_packaged_cua_license(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    license_path = (
        app_dir
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_LICENSE_NAME
    )
    license_path.write_text("tampered license\n", encoding="utf-8")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        license_path,
        "packaged Cua Driver license SHA256 does not match the lock",
    ) in findings


def test_verifier_rejects_packaged_cua_driver_without_embedded_manifest_contract(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    binary_path = (
        app_dir
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
    )
    runtime_manifest = {
        "schema_version": "1",
        "binary_version": "0.7.1",
        "mcp_invocation": {"args": ["mcp"]},
        "subcommands": [{"name": "mcp", "args": []}],
    }
    binary_path.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = --version ]; then echo 'cua-driver 0.7.1'; exit 0; fi\n"
        "if [ \"${1:-}\" = manifest ]; then cat <<'JSON'\n"
        f"{json.dumps(runtime_manifest)}\n"
        "JSON\n"
        "exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    binary_path.chmod(0o755)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        binary_path,
        "packaged Cua Driver runtime manifest lacks the embedded host contract",
    ) in findings


def test_verifier_accepts_packaged_app_bundle_from_explicit_resources_path(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
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


def test_packaged_app_verifier_does_not_fallback_outside_explicit_release_scope(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    _write_packaged_app_bundle(tmp_path)
    release_dir = tmp_path / "release"
    release_dir.mkdir()

    findings = verifier._verify_packaged_app_bundle(
        tmp_path,
        [release_dir],
    )

    assert findings == [
        verifier.Finding(
            release_dir,
            "explicit release verification paths must contain Oha-Yachiyo.app; "
            "refusing to verify an unrelated dist/electron app bundle",
        )
    ]


def _synthetic_signed_macho64(*, body: bytes, signature: bytes) -> bytes:
    header_size = 32
    command_size = 16
    signature_offset = header_size + command_size + len(body)
    header = struct.pack(
        "<IiiIIIII",
        0xFEEDFACF,
        0x0100000C,
        0,
        2,
        1,
        command_size,
        0,
        0,
    )
    signature_command = struct.pack(
        "<IIII",
        verifier._LC_CODE_SIGNATURE,
        command_size,
        signature_offset,
        len(signature),
    )
    return header + signature_command + body + signature


def test_verifier_ignores_legacy_identity_only_inside_macho_code_signature(
    tmp_path,
):
    binary_path = tmp_path / "Oha-Yachiyo"
    binary_path.write_bytes(
        _synthetic_signed_macho64(
            body=b"\0current product content\0",
            signature=b"\0Hermes-Yachiyo Self Signed\0",
        )
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[binary_path],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    assert findings == []


def test_verifier_still_rejects_legacy_identity_in_signed_macho_content(
    tmp_path,
):
    binary_path = tmp_path / "Oha-Yachiyo"
    binary_path.write_bytes(
        _synthetic_signed_macho64(
            body=b"\0Hermes-Yachiyo product content\0",
            signature=b"\0Oha-Yachiyo Self Signed\0",
        )
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[binary_path],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        binary_path,
        "contains legacy product token 'Hermes-Yachiyo'",
    ) in findings


def test_verifier_allows_locked_packaged_cua_legacy_content_only_at_exact_path(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path)
    binary_path = (
        app_dir
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
    )
    binary_path.write_text(
        binary_path.read_text("utf-8") + "\n# Hermes Agent hermes/config hermes-agent\n",
        encoding="utf-8",
    )
    binary_path.chmod(0o755)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[app_dir / "Contents" / "Resources"],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == []


@pytest.mark.parametrize(
    "relative_path",
    (
        Path("Contents/Resources/computer-use/macos/cua-driver-sibling"),
        Path("Contents/Resources/other/cua-driver"),
    ),
)
def test_verifier_still_rejects_legacy_content_outside_exact_packaged_cua_path(
    monkeypatch,
    tmp_path,
    relative_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path)
    other_binary = app_dir / relative_path
    other_binary.parent.mkdir(parents=True, exist_ok=True)
    other_binary.write_bytes(b"\x00Hermes Agent\x00hermes/config\x00hermes-agent\x00")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[app_dir / "Contents" / "Resources"],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert any(
        finding.path == other_binary and "contains legacy product token" in finding.message
        for finding in findings
    )


def test_verifier_does_not_exempt_packaged_cua_content_without_packaged_check(
    tmp_path,
):
    app_dir = _write_packaged_app_bundle(tmp_path)
    binary_path = (
        app_dir
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
    )
    binary_path.write_bytes(b"\x00Hermes Agent\x00")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[binary_path],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=False,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        binary_path,
        "contains legacy product token 'Hermes Agent'",
    ) in findings


def test_verifier_does_not_exempt_cua_shaped_path_in_another_app(tmp_path):
    binary_path = (
        tmp_path
        / "Other.app"
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
    )
    binary_path.parent.mkdir(parents=True)
    binary_path.write_bytes(b"\x00Hermes Agent\x00")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[binary_path],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        binary_path,
        "contains legacy product token 'Hermes Agent'",
    ) in findings


def test_verifier_keeps_path_token_scan_for_exact_packaged_cua_path(tmp_path):
    binary_path = (
        tmp_path
        / "Hermes Agent.app"
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
    )
    binary_path.parent.mkdir(parents=True)
    binary_path.write_bytes(b"\x00Hermes Agent\x00")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[binary_path],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        binary_path,
        "path contains legacy product token 'Hermes Agent'",
    ) in findings


def test_verifier_rejects_packaged_cua_content_digest_mismatch(monkeypatch, tmp_path):
    _stub_packaged_cua_content_digest(monkeypatch, digest="d" * 64)
    app_dir = _write_packaged_app_bundle(tmp_path)
    binary_path = (
        app_dir
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
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
        binary_path,
        "packaged Cua Driver canonical content SHA256 does not match the lock",
    ) in findings


def test_verifier_rejects_packaged_cua_manifest_content_digest_mismatch(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path)
    manifest_path = (
        app_dir
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_MANIFEST_NAME
    )
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["binary"]["content_sha256"] = "d" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        manifest_path,
        "packaged Cua Driver manifest does not match the dependency lock",
    ) in findings


@pytest.mark.parametrize(
    ("error", "error_name"),
    (
        (FileNotFoundError("codesign missing"), "FileNotFoundError"),
        (RuntimeError("codesign failed"), "RuntimeError"),
    ),
)
def test_verifier_fails_closed_when_packaged_cua_canonicalization_fails(
    monkeypatch,
    tmp_path,
    error,
    error_name,
):
    def fail_digest(_path):
        raise error

    monkeypatch.setattr(
        verifier,
        "_sha256_macho_without_code_signature",
        fail_digest,
    )
    app_dir = _write_packaged_app_bundle(tmp_path)
    binary_path = (
        app_dir
        / verifier.PACKAGED_CUA_DRIVER_RELATIVE_DIR
        / verifier.PACKAGED_CUA_DRIVER_BINARY_RELATIVE_PATH
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
        binary_path,
        f"packaged Cua Driver canonical content hash check failed: {error_name}",
    ) in findings


def test_packaged_cua_canonicalization_uses_disposable_copy_and_safe_codesign_argv(
    monkeypatch,
    tmp_path,
):
    binary_path = tmp_path / verifier.PACKAGED_CUA_DRIVER_BINARY_NAME
    original_bytes = b"not-a-real-mach-o"
    binary_path.write_bytes(original_bytes)
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        copied_path = Path(argv[-1])
        assert copied_path != binary_path
        assert copied_path.read_bytes() == original_bytes
        return SimpleNamespace(returncode=1, stdout="", stderr="invalid Mach-O")

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="codesign --remove-signature failed"):
        verifier._sha256_macho_without_code_signature(binary_path)

    assert captured["argv"][:2] == ["/usr/bin/codesign", "--remove-signature"]
    assert (
        captured["kwargs"]["timeout"]
        == verifier.PACKAGED_EXECUTABLE_SMOKE_TIMEOUT_SECONDS
    )
    assert "shell" not in captured["kwargs"]
    assert binary_path.read_bytes() == original_bytes


def test_verifier_reports_incomplete_packaged_app_bundle(tmp_path):
    app_dir = _write_packaged_app_bundle(
        tmp_path,
        identifier="io.github.arisataki.old-yachiyo",
        executable_mode=0o644,
        backend_mode=0o644,
        desktop_provider_mode=0o644,
        desktop_bridge_mode=0o644,
        cua_driver_mode=0o644,
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
    assert "packaged Cua Driver binary is not executable" in messages
    assert "packaged virtual desktop guest provider is not executable" in messages
    assert "packaged virtual desktop host bridge is not executable" in messages
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
    assert "packaged app Info.plist must include Screen Recording permission copy" in messages


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


def test_verifier_accepts_packaged_onedir_backend_build_metadata(monkeypatch, tmp_path):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path, include_backend_metadata=False)
    metadata_path = app_dir / verifier.PACKAGED_BACKEND_BUILD_METADATA_RELATIVE_PATH
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps({"channel": "stable"}), encoding="utf-8")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == []


@pytest.mark.parametrize(
    ("backend_display", "requirement", "expected_message"),
    (
        (
            "Identifier=io.github.arisataki.oha-yachiyo.backend\nSignature=adhoc\n",
            'designated => identifier "io.github.arisataki.oha-yachiyo.backend" and anchor trusted\n',
            "packaged backend executable must not use an ad-hoc signature",
        ),
        (
            "Identifier=io.github.arisataki.oha-yachiyo.backend-dev\nSignature=Authority-signed\n",
            'designated => identifier "io.github.arisataki.oha-yachiyo.backend-dev" and anchor trusted\n',
            f"packaged backend executable must use the stable identifier {verifier.PACKAGED_BACKEND_IDENTIFIER}",
        ),
        (
            "Identifier=io.github.arisataki.oha-yachiyo.backend\nSignature=Authority-signed\n",
            'designated => cdhash H"1234567890ABCDEF"\n',
            "packaged backend executable designated requirement must not be cdhash-only",
        ),
    ),
)
def test_verifier_rejects_packaged_backend_signing_regressions(
    monkeypatch,
    tmp_path,
    backend_display,
    requirement,
    expected_message,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    _write_packaged_app_bundle(tmp_path, include_backend_metadata=False)
    def fake_display(path):
        if Path(path).name == verifier.PACKAGED_APP_NAME:
            return "Authority=Oha-Yachiyo Self Signed\n"
        return backend_display

    monkeypatch.setattr(verifier, "_read_codesign_display", fake_display)
    monkeypatch.setattr(
        verifier,
        "_read_codesign_designated_requirement",
        lambda _path: requirement,
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert any(finding.message == expected_message for finding in findings)


def test_verifier_checks_standalone_backend_signature(monkeypatch, tmp_path):
    standalone_backend = tmp_path / "dist" / "backend" / "oha-yachiyo-backend"
    standalone_backend.parent.mkdir(parents=True, exist_ok=True)
    standalone_backend.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    standalone_backend.chmod(0o755)
    monkeypatch.setattr(verifier, "_run_codesign_verify", lambda _path, *, deep=False: None)
    monkeypatch.setattr(
        verifier,
        "_read_codesign_display",
        lambda _path: (
            f"Identifier={verifier.PACKAGED_BACKEND_IDENTIFIER}\n"
            "Signature=Authority-signed\n"
        ),
    )
    monkeypatch.setattr(
        verifier,
        "_read_codesign_designated_requirement",
        lambda _path: (
            "designated => "
            f'identifier "{verifier.PACKAGED_BACKEND_IDENTIFIER}" and anchor trusted\n'
        ),
    )
    monkeypatch.setattr(
        verifier,
        "_read_codesign_entitlements",
        lambda _path: dict(verifier.PACKAGED_BACKEND_EXPECTED_ENTITLEMENTS),
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[standalone_backend],
        check_required_files=False,
        check_release_security_guards=False,
        allow_binary_targets=True,
    )

    assert findings == []


def test_verifier_accepts_self_signed_backend_display_without_signature_field(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    _write_packaged_app_bundle(tmp_path)

    def fake_display(path):
        if Path(path).name == verifier.PACKAGED_APP_NAME:
            return "Authority=Oha-Yachiyo Self Signed\n"
        return (
            f"Identifier={verifier.PACKAGED_BACKEND_IDENTIFIER}\n"
            "Authority=Oha-Yachiyo Self Signed\n"
            "TeamIdentifier=LOCALTEAM\n"
        )

    monkeypatch.setattr(verifier, "_read_codesign_display", fake_display)
    monkeypatch.setattr(
        verifier,
        "_read_codesign_designated_requirement",
        lambda _path: (
            "designated => "
            f'identifier "{verifier.PACKAGED_BACKEND_IDENTIFIER}" and anchor trusted\n'
        ),
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == []


def test_verifier_allows_outer_adhoc_backend_cdhash_requirement(monkeypatch, tmp_path):
    _stub_packaged_cua_content_digest(monkeypatch)
    _write_packaged_app_bundle(tmp_path)

    def fake_display(path):
        if Path(path).name == verifier.PACKAGED_APP_NAME:
            return "Signature=adhoc\n"
        return (
            f"Identifier={verifier.PACKAGED_BACKEND_IDENTIFIER}\n"
            "Signature=adhoc\n"
        )

    monkeypatch.setattr(verifier, "_read_codesign_display", fake_display)
    monkeypatch.setattr(
        verifier,
        "_read_codesign_designated_requirement",
        lambda _path: 'designated => cdhash H"1234567890ABCDEF"\n',
    )

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert findings == []


@pytest.mark.parametrize(
    ("metadata_text", "expected_message"),
    (
        ("{", "packaged backend app build metadata is not valid JSON: JSONDecodeError"),
        ("[]", "packaged backend app build metadata must contain one JSON object"),
    ),
)
def test_verifier_rejects_invalid_packaged_onedir_backend_build_metadata(
    monkeypatch,
    tmp_path,
    metadata_text,
    expected_message,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path, include_backend_metadata=False)
    metadata_path = app_dir / verifier.PACKAGED_BACKEND_BUILD_METADATA_RELATIVE_PATH
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(metadata_text, encoding="utf-8")

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(metadata_path, expected_message) in findings


def test_verifier_rejects_symlinked_packaged_onedir_backend_build_metadata(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path, include_backend_metadata=False)
    metadata_path = app_dir / verifier.PACKAGED_BACKEND_BUILD_METADATA_RELATIVE_PATH
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    external_metadata = tmp_path / "external-build-metadata.json"
    external_metadata.write_text(json.dumps({"channel": "stable"}), encoding="utf-8")
    metadata_path.symlink_to(external_metadata)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        metadata_path,
        "packaged backend app build metadata must not be a symlink",
    ) in findings


def test_verifier_rejects_unreadable_packaged_onedir_backend_build_metadata(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path, include_backend_metadata=False)
    metadata_path = app_dir / verifier.PACKAGED_BACKEND_BUILD_METADATA_RELATIVE_PATH
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps({"channel": "stable"}), encoding="utf-8")
    metadata_path.chmod(0)

    try:
        findings = verifier.verify_release_artifacts(
            root=tmp_path,
            paths=[],
            check_required_files=False,
            check_release_security_guards=False,
            check_packaged_app_bundle=True,
            allow_binary_targets=True,
        )
    finally:
        metadata_path.chmod(0o644)

    assert verifier.Finding(
        metadata_path,
        "packaged backend app build metadata is not readable",
    ) in findings


def test_verifier_reports_missing_packaged_desktop_provider(tmp_path):
    app_dir = _write_packaged_app_bundle(
        tmp_path,
        include_desktop_provider=False,
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
        app_dir / verifier.PACKAGED_DESKTOP_PROVIDER_RELATIVE_PATH,
        "packaged virtual desktop guest provider is missing from app resources",
    ) in findings


def test_verifier_rejects_packaged_desktop_provider_with_invalid_manifest(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    desktop_provider = app_dir / verifier.PACKAGED_DESKTOP_PROVIDER_RELATIVE_PATH
    desktop_provider.write_text("#!/bin/sh\necho not-json\n", encoding="utf-8")
    desktop_provider.chmod(0o755)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        desktop_provider,
        "packaged virtual desktop guest provider returned invalid manifest JSON",
    ) in findings


def test_verifier_reports_missing_packaged_desktop_bridge(tmp_path):
    app_dir = _write_packaged_app_bundle(
        tmp_path,
        include_desktop_bridge=False,
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
        app_dir / verifier.PACKAGED_DESKTOP_BRIDGE_RELATIVE_PATH,
        "packaged virtual desktop host bridge is missing from app resources",
    ) in findings


def test_verifier_rejects_packaged_desktop_bridge_with_invalid_cli(tmp_path):
    app_dir = _write_packaged_app_bundle(tmp_path)
    desktop_bridge = app_dir / verifier.PACKAGED_DESKTOP_BRIDGE_RELATIVE_PATH
    desktop_bridge.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    desktop_bridge.chmod(0o755)

    findings = verifier.verify_release_artifacts(
        root=tmp_path,
        paths=[],
        check_required_files=False,
        check_release_security_guards=False,
        check_packaged_app_bundle=True,
        allow_binary_targets=True,
    )

    assert verifier.Finding(
        desktop_bridge,
        "packaged virtual desktop host bridge CLI is invalid",
    ) in findings


def test_dynamic_packaged_selector_gate_covers_release_electron_smoke_selectors():
    missing = sorted(
        (
            _explicit_smoke_selectors()
            - set(verifier.PACKAGED_UI_E2E_FORBIDDEN_SELECTORS)
        )
        - set(verifier._packaged_ui_e2e_required_selectors(verifier.ROOT))
    )

    assert missing == []
    assert set(verifier.PACKAGED_UI_E2E_FORBIDDEN_SELECTORS).isdisjoint(
        verifier._packaged_ui_e2e_required_selectors(verifier.ROOT)
    )


def test_packaged_selector_gate_forbids_consumer_hidden_launcher_internals():
    consumer_hidden = {
        f"{surface}-launcher-agent-task-{suffix}"
        for surface in ("bubble", "live2d")
        for suffix in (
            "open-studio",
            "planner-summary",
            "progress",
            "runtime-debug",
        )
    }

    assert consumer_hidden <= set(verifier.PACKAGED_UI_E2E_FORBIDDEN_SELECTORS)
    assert consumer_hidden.isdisjoint(
        verifier._packaged_ui_e2e_required_selectors(verifier.ROOT)
    )


def test_dynamic_packaged_attribute_gate_covers_release_electron_smoke_attributes():
    missing = sorted(
        (
            _explicit_smoke_data_attributes()
            - set(verifier.PACKAGED_UI_E2E_FORBIDDEN_DATA_ATTRIBUTES)
        )
        - set(verifier._packaged_ui_e2e_required_data_attributes(verifier.ROOT))
    )

    assert missing == []
    assert set(verifier.PACKAGED_UI_E2E_FORBIDDEN_DATA_ATTRIBUTES).isdisjoint(
        verifier._packaged_ui_e2e_required_data_attributes(verifier.ROOT)
    )


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
    assert (
        "Chat image Electron UI smoke must cover the desktop native image picker API path"
        in messages
    )
    assert (
        "Chat image Electron UI smoke must prove desktop image picker bypasses the hidden input"
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
        "packaged Electron app.asar must include UI E2E selector 'chat-composer-approval-canonical-hint'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'yachiyo-task-approval-approve'",
    ) in findings
    assert verifier.Finding(
        asar_path,
        "packaged Electron app.asar must include UI E2E selector 'yachiyo-task-approval-reject'",
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
    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E data attribute 'data-replan-recovery-request-id'",
    ) in findings
    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E data attribute 'data-replan-recovery-tool'",
    ) in findings
    assert verifier.Finding(
        app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH,
        "packaged Electron app.asar must include UI E2E data attribute 'data-replan-recovery-input'",
    ) in findings


def test_verifier_reports_packaged_app_development_only_ui_e2e_hook(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
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


def test_verifier_reports_packaged_app_deprecated_ui_e2e_selector(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path)
    asar_path = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
    deprecated_selector = verifier.PACKAGED_UI_E2E_FORBIDDEN_SELECTORS[0]
    with asar_path.open("ab") as asar:
        asar.write(b"\n" + deprecated_selector.encode("utf-8"))

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
            f"packaged Electron app.asar must not include deprecated UI E2E selector {deprecated_selector!r}",
        )
    ]


def test_verifier_reports_packaged_app_deprecated_ui_e2e_data_attribute(
    monkeypatch,
    tmp_path,
):
    _stub_packaged_cua_content_digest(monkeypatch)
    app_dir = _write_packaged_app_bundle(tmp_path)
    asar_path = app_dir / verifier.PACKAGED_ASAR_RELATIVE_PATH
    deprecated_attribute = verifier.PACKAGED_UI_E2E_FORBIDDEN_DATA_ATTRIBUTES[0]
    with asar_path.open("ab") as asar:
        asar.write(b"\n" + deprecated_attribute.encode("utf-8"))

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
            f"packaged Electron app.asar must not include deprecated UI E2E data attribute {deprecated_attribute!r}",
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

    assert "macOS release workflow must auto-release Oha experimental builds from oha-develop" in messages
    assert "macOS release workflow must expose an alpha release channel" in messages
    assert "macOS release workflow must label alpha releases separately" in messages
    assert "macOS release workflow must publish alpha builds to alpha-latest metadata" in messages
    assert "macOS release workflow must publish experimental Oha builds to oha-develop-latest metadata" in messages
    assert (
        "macOS release workflow must scan backend and desktop provider binaries"
        in messages
    )
    assert "macOS release workflow must discover packaged app resource directories" in messages
    assert "macOS release workflow must binary-scan packaged app resources" in messages
    assert "macOS release workflow must validate packaged app bundle structure" in messages
    assert "macOS release workflow must verify the final packaged app code signature when signing is enabled" in messages
    assert "macOS release workflow must binary-scan final release artifacts" in messages
    assert "macOS release workflow must run the local RC verification gate" in messages
    assert "macOS release workflow must run the public release preflight gate" in messages
    assert "macOS release workflow must invoke the public release preflight runner" in messages
    assert "macOS release workflow must expose an opt-in public demo evidence scope" in messages
    assert "macOS release workflow must pass public demo mode into the preflight gate" in messages
    assert "macOS release workflow must support full required public demo opt-in flags" in messages
    assert "macOS release workflow must pass public demo opt-in args to the preflight gate" in messages
    assert "macOS release workflow must keep public release gate nested evidence" in messages
    assert "macOS release workflow must archive a public release gate JSON report" in messages
    assert "macOS release workflow must archive a public release gate Markdown report" in messages
    assert "macOS release workflow must upload public release gate nested JSON evidence" in messages
    assert "macOS release workflow must upload public release gate nested Markdown evidence" in messages
    assert "macOS release workflow must upload public release gate diagnostics bundles" in messages
    assert (
        "macOS release workflow must run public release preflight after Python dependencies before smoke tests"
        in messages
    )
    assert (
        "macOS release workflow must install frontend dependencies before public release preflight for full demo UI smokes"
        in messages
    )
    assert "macOS release workflow must upload a release-candidate verification report" in messages
    assert "macOS release workflow must summarize release-smoke evidence after RC verification" in messages
    assert "macOS release workflow release-smoke summary must include public demo evidence" in messages
    assert (
        "macOS release workflow release-smoke summary must include Oha product smoke evidence"
        in messages
    )
    assert (
        "macOS release workflow release-smoke summary must include diagnostics bundle evidence"
        in messages
    )
    assert "macOS release workflow must archive release-smoke JSON evidence" in messages
    assert "macOS release workflow must archive release-smoke Markdown evidence" in messages
    assert (
        "macOS release workflow must fail when release-smoke report generation produces no JSON"
        in messages
    )
    assert (
        "macOS release workflow must explain missing release-smoke report failures"
        in messages
    )
    assert (
        "macOS release workflow must surface incomplete release-smoke evidence without hiding the report"
        in messages
    )
    assert "macOS release workflow must summarize release smoke after the RC report before upload" in messages
    assert "macOS release workflow must archive a manual RC check evidence template" in messages
    assert (
        "macOS release workflow must archive a manual RC check draft seeded from the RC report and Electron UI smoke report"
        in messages
    )
    assert "macOS release workflow must archive a manual RC check Markdown checklist seeded from the draft" in messages
    assert "macOS release workflow must generate manual RC check draft after the RC report before upload" in messages
    assert "macOS release workflow must generate manual RC check Markdown after the draft before upload" in messages


def test_verifier_rejects_oha_release_workflow_on_legacy_develop_branch(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Build macOS DMG\n"
        "on:\n"
        "  push:\n"
        "    branches:\n"
        "      - main\n"
        "      - develop\n"
        "jobs:\n"
        "  package-macos:\n"
        "    steps:\n"
        "      - name: Verify release-facing product identity and security guards\n"
        "        run: python scripts/verify_release_artifacts.py\n"
        "      - name: Prepare release metadata\n"
        "        run: |\n"
        "          LATEST_BRANCH=\"develop\"\n"
        "          echo \"https://github.example/releases/download/develop-latest/Oha-Yachiyo-develop-latest.dmg\"\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert "macOS release workflow must not auto-release Oha from the legacy develop branch" in messages
    assert "macOS release workflow must not publish Oha experimental metadata to develop-latest" in messages
    assert "macOS release workflow must not publish Oha experimental downloads under develop-latest" in messages
    assert "macOS release workflow must not publish Oha experimental DMGs as develop-latest" in messages


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
        "      - name: Import macOS signing certificate\n"
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


def test_verifier_requires_release_workflow_manual_draft_after_rc_report(tmp_path):
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
        "      - name: Prepare release metadata\n"
        "        run: mkdir -p release\n"
        "      - name: Verify release candidate artifacts\n"
        "        run: |\n"
        "          provider_smoke_args+=(--run-provider-smoke)\n"
        "          python scripts/verify_release_candidate.py --manual-checks-json release/rc-verification.json --write-manual-checks-draft release/manual-rc-checks.draft.json\n"
        "          python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --report-json release/rc-verification.json\n"
        "      - name: Upload DMG artifact\n"
        "        run: echo upload\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow must generate manual RC check draft after the RC report before upload"
        in messages
    )


def test_verifier_requires_release_workflow_manual_markdown_after_draft(tmp_path):
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
        "      - name: Prepare release metadata\n"
        "        run: mkdir -p release\n"
        "      - name: Verify release candidate artifacts\n"
        "        run: |\n"
        "          provider_smoke_args+=(--run-provider-smoke)\n"
        "          python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --report-json release/rc-verification.json\n"
        "          python scripts/verify_release_candidate.py --manual-checks-json release/manual-rc-checks.draft.json --write-manual-checks-markdown release/manual-rc-checks.md\n"
        "          python scripts/verify_release_candidate.py --manual-checks-json release/rc-verification.json --write-manual-checks-draft release/manual-rc-checks.draft.json\n"
        "      - name: Upload DMG artifact\n"
        "        run: echo upload\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow must generate manual RC check Markdown after the draft before upload"
        in messages
    )


def test_verifier_requires_release_workflow_provider_missing_status_args(tmp_path):
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
        "      - name: Prepare release metadata\n"
        "        run: mkdir -p release\n"
        "      - name: Verify release candidate artifacts\n"
        "        run: |\n"
        "          provider_smoke_args=()\n"
        "          provider_smoke_args+=(--run-provider-smoke)\n"
        "          python scripts/verify_release_candidate.py --write-manual-checks-template release/manual-rc-checks.template.json\n"
        "          python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --report-json release/rc-verification.json\n"
        "          python scripts/verify_release_candidate.py --manual-checks-json release/rc-verification.json --write-manual-checks-draft release/manual-rc-checks.draft.json\n"
        "          python scripts/verify_release_candidate.py --manual-checks-json release/manual-rc-checks.draft.json --write-manual-checks-markdown release/manual-rc-checks.md\n"
        "      - name: Upload DMG artifact\n"
        "        run: echo upload\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow must mark provider smoke not_applicable in archived signoff artifacts when secrets are missing"
        in messages
    )


def test_verifier_requires_release_workflow_dmg_app_startup_smoke(tmp_path):
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
        "      - name: Prepare release metadata\n"
        "        run: mkdir -p release\n"
        "      - name: Verify release candidate artifacts\n"
        "        run: |\n"
        "          provider_smoke_status_args+=(--mark-provider-smoke-not-applicable-if-missing)\n"
        "          python scripts/verify_release_candidate.py --write-manual-checks-template release/manual-rc-checks.template.json\n"
        "          python scripts/verify_release_candidate.py --require-artifacts --check-dmg-mount --report-json release/rc-verification.json\n"
        "          python scripts/verify_release_candidate.py --manual-checks-json release/rc-verification.json --write-manual-checks-draft release/manual-rc-checks.draft.json\n"
        "          python scripts/verify_release_candidate.py --manual-checks-json release/manual-rc-checks.draft.json --write-manual-checks-markdown release/manual-rc-checks.md\n"
        "      - name: Upload DMG artifact\n"
        "        run: echo upload\n",
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)
    messages = [finding.message for finding in findings]

    assert (
        "macOS release workflow must launch the app inside DMG artifacts during RC verification"
        in messages
    )


def test_verifier_requires_release_workflow_electron_native_focus_smoke(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    workflow.write_text(
        current_workflow.replace(" --run-electron-native-bridge-smoke", ""),
        encoding="utf-8",
    )

    findings = verifier._verify_release_workflow_guards(tmp_path)

    assert verifier.Finding(
        workflow,
        "macOS release workflow must verify a real foreground focus through the Electron native bridge",
    ) in findings


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
        "      - name: Import macOS signing certificate\n"
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
    assert "macOS release workflow smoke tests must cover AstrBot plugin Bridge HTTP E2E" in messages
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
        "      - name: Import macOS signing certificate\n"
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
        "      - name: Import macOS signing certificate\n"
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
    assert (
        "macOS release workflow must stage latest assets through the canonical release candidate builder"
        in messages
    )
    assert "macOS release workflow must compute a SHA256 checksum for the versioned DMG" in messages
    assert "macOS release workflow must upload release DMG artifacts" in messages
    assert "macOS release workflow must fail instead of choosing implicitly when multiple DMGs exist" in messages
    assert "macOS release workflow must upload release checksum artifacts" in messages


def test_verifier_requires_release_workflow_to_delegate_latest_metadata(tmp_path):
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
        "      - name: Import macOS signing certificate\n"
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

    assert (
        "macOS release workflow must delegate latest artifacts to the canonical release candidate builder"
        in messages
    )
    assert (
        "macOS release workflow must use the builder's explicit existing-artifact staging mode"
        in messages
    )
    assert (
        "macOS release workflow must bind content-bound signing evidence to the release candidate"
        in messages
    )
    assert (
        "macOS release workflow must not hand-write latest JSON outside the canonical release candidate builder"
        in messages
    )


def test_release_workflow_uses_canonical_existing_artifact_staging_command():
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/release-macos.yml"
    ).read_text(encoding="utf-8")
    metadata_step = verifier._release_workflow_step_block(
        workflow,
        "Prepare release metadata",
    )

    for required_text, _message in verifier.RELEASE_WORKFLOW_METADATA_REQUIRED_TEXT:
        assert required_text in metadata_step
    assert 'cat > "release/${LATEST_JSON}"' not in metadata_step
    assert 'cp "release/${LATEST_ZIP}" "release/${VERSIONED_ZIP}"' in metadata_step
    assert 'cp "${dmg_files[0]}" "release/${VERSIONED_DMG}"' in metadata_step


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
        "      - name: Import macOS signing certificate\n"
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
    assert "macOS release workflow must serialize publication per source ref" in messages
    assert "macOS release workflow dispatch must make GitHub Release publication explicit" in messages
    assert "macOS release workflow must validate publication channel against source branch" in messages
    assert (
        "macOS release workflow must gate publication validation behind push or explicit dispatch publication"
        in messages
    )
    assert (
        "macOS release workflow must success-gate both GitHub Release mutations after readiness enforcement"
        in messages
    )
    assert "macOS release workflow must keep a no-certificate unsigned release path" in messages
    assert "macOS release workflow must label the no-certificate path as unsigned" in messages
    assert "macOS release workflow must use the signed app build path when signing is configured" in messages
    assert "macOS release workflow must inspect actual final DMG signing evidence" in messages
    assert "macOS release workflow must derive signing metadata from the final DMG" in messages
    assert (
        "macOS release workflow must create a macOS-safe app ZIP through the canonical release candidate builder"
        in messages
    )
    assert "macOS release workflow must verify the packaged app architecture" in messages
    assert (
        "macOS release workflow must normalize lipo x86_64 to Electron x64 architecture"
        in messages
    )
    assert "macOS release workflow must upload the app ZIP" in messages
    assert "macOS release workflow must import signing material before building the DMG" in messages
    assert (
        "macOS release workflow must run the optional real virtual desktop smoke after guest build before signing"
        in messages
    )
    assert "macOS release workflow must accept a dedicated virtual desktop SSH key" in messages
    assert "macOS release workflow must require pinned virtual desktop SSH host keys" in messages
    assert (
        "macOS release workflow must create virtual desktop credentials with private permissions"
        in messages
    )
    assert (
        "macOS release workflow must enforce SSH host key verification for the virtual desktop"
        in messages
    )
    assert (
        "macOS release workflow must require a public-release-ready virtual desktop backend"
        in messages
    )
    assert (
        "macOS release workflow must merge real virtual desktop evidence into release smoke summary"
        in messages
    )


@pytest.mark.parametrize(
    ("old", "new", "expected_message"),
    [
        (
            "        id: release_smoke\n",
            "",
            "macOS release workflow must assign the release_smoke id to the final RC verification step",
        ),
        (
            "      - name: Upload DMG artifact\n        if: always()\n",
            "      - name: Upload DMG artifact\n",
            "macOS release workflow must upload release evidence even when RC verification is incomplete",
        ),
        (
            "        if: always() && (github.event_name == 'push' || inputs.publish_release == true)\n",
            "        if: always()\n",
            "macOS release workflow must enforce release-smoke readiness only for publication runs",
        ),
        (
            "        if: success() && (github.event_name == 'push' || inputs.publish_release == true)\n",
            "        if: github.event_name == 'push' || inputs.publish_release == true\n",
            "macOS release workflow must success-gate both GitHub Release mutations after readiness enforcement",
        ),
    ],
)
def test_release_workflow_hard_gate_guards(
    tmp_path,
    old: str,
    new: str,
    expected_message: str,
) -> None:
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8")
    assert old in current
    workflow.write_text(current.replace(old, new), encoding="utf-8")

    messages = [
        finding.message for finding in verifier._verify_release_workflow_guards(tmp_path)
    ]

    assert expected_message in messages


@pytest.mark.parametrize(
    ("old", "new", "expected_message"),
    [
        (
            "          release_smoke_status=0\n",
            "          echo release-smoke-status-initialized\n",
            "macOS release workflow RC step must initialize release_smoke_status to zero",
        ),
        (
            "            --output-markdown release/release-smoke.md || release_smoke_status=$?\n",
            "            --output-markdown release/release-smoke.md || echo summary-failed\n",
            "macOS release workflow RC step must capture release-smoke summary failures",
        ),
        (
            "            release_smoke_status=1\n",
            "            echo release-smoke-json-missing\n",
            "macOS release workflow RC step must mark missing release-smoke JSON as failed",
        ),
        (
            "            exit 1\n",
            "            echo publication-would-have-failed\n",
            "macOS release workflow readiness gate must exit 1 for missing or invalid status",
        ),
        (
            "            release/electron-ui-smoke.json \\\n",
            "",
            "macOS release workflow final summary must consume Electron UI evidence before writing release-smoke outputs",
        ),
    ],
)
def test_release_workflow_status_and_electron_evidence_guards_reject_noops(
    tmp_path,
    old: str,
    new: str,
    expected_message: str,
) -> None:
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8")
    assert old in current
    workflow.write_text(current.replace(old, new), encoding="utf-8")

    messages = [
        finding.message for finding in verifier._verify_release_workflow_guards(tmp_path)
    ]

    assert expected_message in messages


def test_release_workflow_requires_packaged_chat_native_file_smoke_in_final_rc(
    tmp_path,
) -> None:
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8")
    required_flag = " --run-dmg-chat-native-file-smoke"
    assert required_flag in current
    workflow.write_text(current.replace(required_flag, "", 1), encoding="utf-8")

    messages = [
        finding.message for finding in verifier._verify_release_workflow_guards(tmp_path)
    ]

    assert (
        "macOS release workflow final RC must run the packaged Chat native file smoke"
        in messages
    )


def test_release_workflow_requires_electron_ui_source_before_final_summary(tmp_path) -> None:
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(encoding="utf-8")
    source = (
        "python scripts/run_electron_ui_smokes.py "
        "--report-json release/electron-ui-smoke.json"
    )
    assert source in current
    mutated = current.replace(source, "echo electron-ui-smoke-deferred", 1)
    mutated = f"{mutated}\n# late source\n{source}\n"
    workflow.write_text(mutated, encoding="utf-8")

    messages = [
        finding.message for finding in verifier._verify_release_workflow_guards(tmp_path)
    ]

    assert (
        "macOS release workflow must generate Electron UI evidence before final release-smoke summary"
        in messages
    )


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
        "      - name: Import macOS signing certificate\n"
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
    assert "macOS release workflow must document the notarized Developer ID path" in messages
    assert "macOS release workflow must document screen recording permission setup" in messages


@pytest.mark.parametrize(
    ("required_text", "expected_message"),
    [
        (
            "python scripts/prepare_cua_driver.py --clean",
            "macOS release workflow must prepare the pinned Cua Driver after dependency installation",
        ),
        (
            "tests/test_cua_embedded_distribution.py",
            "macOS release workflow focused tests must cover embedded Cua distribution",
        ),
        (
            "tests/test_prepare_cua_driver.py",
            "macOS release workflow focused tests must cover Cua Driver preparation",
        ),
        (
            "npm --prefix apps/frontend run test:cua-mcp-bridge",
            "macOS release workflow must exercise the Electron-owned Cua bridge",
        ),
        (
            "tests/test_cua_socket_transport.py",
            "macOS release workflow focused tests must cover the backend Cua socket transport",
        ),
        (
            "tests/test_agent_runtime_desktop_execution_providers.py",
            "macOS release workflow focused tests must cover Cua bridge adapter reuse",
        ),
        (
            'test ! -L "${packaged_cua_file}"',
            "macOS release workflow must reject symlinked packaged Cua resources",
        ),
        (
            'test ! -L "${packaged_cua_dir}"',
            "macOS release workflow must reject symlinked packaged Cua resource directories",
        ),
        (
            'test -d "${packaged_cua_dir}"',
            "macOS release workflow must require real packaged Cua resource directories",
        ),
        (
            'test -f "${packaged_cua_file}"',
            "macOS release workflow must require packaged Cua resource files",
        ),
        (
            'test -x "${cua_driver}"',
            "macOS release workflow must require an executable packaged Cua Driver",
        ),
        (
            '"${cua_driver}" --version',
            "macOS release workflow must verify the packaged Cua Driver version",
        ),
        (
            '"${cua_driver}" manifest',
            "macOS release workflow must inspect the packaged Cua Driver manifest",
        ),
        (
            '{"--embedded", "--host-bundle-id"}',
            "macOS release workflow must require the embedded host manifest contract",
        ),
        (
            'lipo -archs "${cua_driver}"',
            "macOS release workflow must verify both packaged Cua Driver architectures",
        ),
        (
            'codesign --verify --strict --verbose=2 "${cua_driver}"',
            "macOS release workflow must verify the nested Cua Driver signature",
        ),
        (
            'codesign -d --entitlements - --xml "${cua_driver}"',
            "macOS release workflow must inspect the final Cua Driver entitlements",
        ),
        (
            '"com.apple.security.automation.apple-events": True',
            "macOS release workflow must require Apple Events for the Cua Driver",
        ),
        (
            '"com.apple.security.device.screen-capture": True',
            "macOS release workflow must require Screen Capture for the Cua Driver",
        ),
        (
            "MACOS_SIGNING_MODE=self-signed-app-unsigned-dmg",
            "macOS release workflow must ad-hoc sign no-certificate builds before verification",
        ),
        (
            "tests/test_cua_background_provider.py",
            "macOS release workflow must run the Cua background provider contract tests",
        ),
        (
            "tests/test_background_desktop_safety.py",
            "macOS release workflow must run background desktop safety tests",
        ),
    ],
)
def test_verifier_requires_embedded_cua_release_workflow_commands(
    tmp_path,
    required_text,
    expected_message,
):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    assert required_text in current_workflow
    workflow.write_text(
        current_workflow.replace(required_text, "removed-cua-release-guard", 1),
        encoding="utf-8",
    )

    messages = [
        finding.message
        for finding in verifier._verify_release_workflow_guards(tmp_path)
    ]

    assert expected_message in messages


def test_verifier_requires_cua_prepare_after_dependencies_before_tests(tmp_path):
    workflow = tmp_path / verifier.RELEASE_WORKFLOW_FILE
    workflow.parent.mkdir(parents=True)
    current_workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    prepare_step = (
        "      - name: Prepare embedded Cua Driver\n"
        "        run: python scripts/prepare_cua_driver.py --clean\n\n"
    )
    assert prepare_step in current_workflow
    late_workflow = current_workflow.replace(prepare_step, "", 1) + "\n" + prepare_step
    workflow.write_text(late_workflow, encoding="utf-8")

    messages = [
        finding.message
        for finding in verifier._verify_release_workflow_guards(tmp_path)
    ]

    assert (
        "macOS release workflow must prepare the embedded Cua Driver after dependencies before focused tests"
        in messages
    )


def _release_workflow_step_script(step_name: str) -> str:
    workflow = (verifier.ROOT / verifier.RELEASE_WORKFLOW_FILE).read_text(
        encoding="utf-8"
    )
    marker = f"      - name: {step_name}\n"
    section = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    run_block = section.split("        run: |\n", 1)[1]
    return "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in run_block.splitlines()
    )


def _virtual_desktop_workflow_env(tmp_path, **overrides: str) -> dict[str, str]:
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{Path(sys.executable).parent}:{env['PATH']}",
            "OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET": "",
            "OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_PRIVATE_KEY": "",
            "OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_KNOWN_HOSTS": "",
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
            "GITHUB_RUN_ID": "12345",
            "GITHUB_RUN_ATTEMPT": "1",
            "RUNNER_TEMP": str(runner_temp),
        }
    )
    env.update(overrides)
    return env


def test_virtual_desktop_workflow_step_records_not_configured_without_secrets(tmp_path):
    script = _release_workflow_step_script(
        "Run optional real virtual desktop provider smoke"
    )

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=_virtual_desktop_workflow_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(
        (tmp_path / "release" / "virtual-desktop-provider-smoke.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["status"] == "not_configured"
    assert len(report["required_secrets"]) == 3


def test_virtual_desktop_workflow_step_rejects_partial_secret_configuration(tmp_path):
    script = _release_workflow_step_script(
        "Run optional real virtual desktop provider smoke"
    )

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=_virtual_desktop_workflow_env(
            tmp_path,
            OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET="yachiyo@vm.example",
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "must be configured together" in result.stderr


def test_virtual_desktop_workflow_step_uses_private_files_and_cleans_them(tmp_path):
    script = _release_workflow_step_script(
        "Run optional real virtual desktop provider smoke"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    mode_report = tmp_path / "modes.txt"
    fake_python = fake_bin / "python"
    fake_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
command_path="$1"
shift
file_mode() {
  stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1"
}
if [[ "${command_path}" == *install_virtual_desktop_guest.py ]]; then
  identity=""
  known_hosts=""
  token=""
  manifest=""
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --identity-file) identity="$2"; shift 2 ;;
      --local-token-file) token="$2"; shift 2 ;;
      --manifest-out) manifest="$2"; shift 2 ;;
      --ssh-option)
        if [[ "$2" == UserKnownHostsFile=* ]]; then known_hosts="${2#*=}"; fi
        shift 2
        ;;
      *) shift ;;
    esac
  done
  printf '%s %s %s\n' \
    "$(file_mode "${identity}")" \
    "$(file_mode "${known_hosts}")" \
    "$(file_mode "${RUNNER_TEMP}/oha-yachiyo-vm-install.json")" \
    > "${MOCK_MODE_REPORT}"
  printf 'token\n' > "${token}"
  printf '{}\n' > "${manifest}"
  printf '{"ok":true}\n'
elif [[ "${command_path}" == *smoke_oha_desktop_agent_release.py ]]; then
  report=""
  while [[ "$#" -gt 0 ]]; do
    if [[ "$1" == "--report-json" ]]; then report="$2"; shift 2; else shift; fi
  done
  printf '{"ok":true,"public_release_ready":true}\n' > "${report}"
else
  echo "unexpected python command: ${command_path}" >&2
  exit 2
fi
""",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = _virtual_desktop_workflow_env(
        tmp_path,
        OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_TARGET="yachiyo@vm.example",
        OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_PRIVATE_KEY="private-key",
        OHA_YACHIYO_VIRTUAL_DESKTOP_SSH_KNOWN_HOSTS="vm.example ssh-ed25519 AAAA",
        MOCK_MODE_REPORT=str(mode_report),
    )
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert mode_report.read_text(encoding="utf-8").strip() == "600 600 600"
    assert json.loads(
        (tmp_path / "release" / "virtual-desktop-provider-smoke.json").read_text(
            encoding="utf-8"
        )
    )["public_release_ready"] is True
    runner_temp = Path(env["RUNNER_TEMP"])
    assert not any(runner_temp.iterdir())


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
