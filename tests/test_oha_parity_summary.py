from __future__ import annotations

import json
from pathlib import Path

from scripts import summarize_oha_parity as parity


def _write_product_identity_files(root: Path) -> None:
    (root / "apps/frontend").mkdir(parents=True)
    (root / "apps/frontend/electron-builder.yml").write_text(
        "\n".join(
            [
                "appId: io.github.arisataki.oha-yachiyo",
                "productName: Oha-Yachiyo",
                "dmg:",
                "  artifactName: Oha-Yachiyo-${version}-${arch}.${ext}",
            ]
        ),
        encoding="utf-8",
    )
    (root / ".github/workflows").mkdir(parents=True)
    (root / ".github/workflows/release-macos.yml").write_text(
        "branches:\n  - main\n  - oha-develop\n",
        encoding="utf-8",
    )
    (root / "docs").mkdir(parents=True)
    (root / "docs/release-packaging.md").write_text(
        "\n".join(
            [
                "`develop` 分支保留给彻底重构前的旧版发布线，不触发 Oha DMG",
                "Oha-Yachiyo-oha-develop-latest.dmg",
            ]
        ),
        encoding="utf-8",
    )


def _signoff_report() -> dict[str, object]:
    return {
        "checks": [
            {
                "id": "gatekeeper_first_launch",
                "status": "manual_required",
                "description": "Mount the DMG and launch Oha-Yachiyo.app.",
                "required_before": "public_release_signoff",
                "evidence_prompt": "Record Finder Control-click -> Open evidence.",
                "next_action": "Launch Oha-Yachiyo.app through Finder Control-click -> Open.",
                "notes": "Gatekeeper readiness collected.",
            },
            {
                "id": "packaged_bridge_isolation",
                "status": "passed",
                "evidence": "Packaged Bridge reached /status.",
                "evidence_source": "automated_rc_gate",
            },
            {
                "id": "screen_recording_permission",
                "status": "passed",
                "evidence": "Screen probe passed.",
                "evidence_source": "automated_rc_gate",
            },
            {
                "id": "chat_native_file_upload",
                "status": "passed",
                "evidence": "Native image upload passed.",
                "evidence_source": "automated_rc_gate",
            },
            {
                "id": "packaged_ui_sampling",
                "status": "passed",
                "evidence": "Packaged UI sampling passed.",
                "evidence_source": "automated_rc_gate",
            },
            {
                "id": "real_provider_smoke",
                "status": "passed",
                "evidence": "Provider full-chain smoke passed.",
                "evidence_source": "automated_rc_gate",
            },
            {
                "id": "external_integrations_smoke",
                "status": "manual_required",
                "description": "Run real external integrations smoke.",
                "required_before": "public_release_signoff",
                "evidence_prompt": "Archive tmp/external-integrations-smoke.json.",
                "next_action": "Run scripts/smoke_external_integrations.py with real resources.",
                "notes": "Still needs live2d_resource, gpt_sovits_tts, astrbot_plugin_bridge.",
            },
        ],
        "manual_release_candidate_check_summary": {
            "remaining_check_ids": [
                "gatekeeper_first_launch",
                "external_integrations_smoke",
            ],
            "status_counts": {
                "manual_required": 2,
                "passed": 5,
                "failed": 0,
                "not_applicable": 0,
            },
            "remaining_next_actions": [
                {
                    "id": "gatekeeper_first_launch",
                    "next_action": "Launch Oha-Yachiyo.app through Finder Control-click -> Open.",
                },
                {
                    "id": "external_integrations_smoke",
                    "next_action": "Run scripts/smoke_external_integrations.py with real resources.",
                },
            ],
            "remaining_commands": [
                {
                    "id": "gatekeeper_first_launch",
                    "command": "python scripts/verify_release_candidate.py --require-artifacts --check-gatekeeper-readiness",
                },
                {
                    "id": "external_integrations_smoke",
                    "command": "python scripts/smoke_external_integrations.py --bridge-url http://127.0.0.1:18420 --live2d-archive /path/to/yachiyo-live2d.zip --tts-voice-archive /path/to/yachiyo-gpt-sovits.zip --gpt-sovits-base-url http://127.0.0.1:9880 --astrbot --report-json tmp/external-integrations-smoke.json",
                },
            ],
        },
        "native_agent_capability_matrix": {
            "status": "passed",
            "ok": True,
            "capability_count": 13,
            "status_counts": {"passed": 13, "missing": 0},
            "missing_capability_ids": [],
            "source_reports": ["tmp/provider.json"],
            "capabilities": [{"id": "agent_multi_tool_pipeline", "status": "passed"}],
        },
    }


def test_oha_parity_summary_reports_remaining_release_blockers(tmp_path):
    _write_product_identity_files(tmp_path)
    report_path = tmp_path / "tmp" / "signoff.json"
    report_path.parent.mkdir()
    report_path.write_text(json.dumps(_signoff_report()), encoding="utf-8")

    summary = parity.summarize_parity(tmp_path, Path("tmp/signoff.json"))

    assert summary["ok"] is False
    assert summary["status"] == "incomplete"
    assert summary["area_count"] == 9
    assert summary["passed_area_count"] == 7
    assert summary["incomplete_area_ids"] == [
        "gatekeeper_first_launch",
        "external_integrations",
    ]
    areas = {area["id"]: area for area in summary["areas"]}
    assert areas["product_release_identity"]["status"] == "passed"
    assert areas["native_agent_capability_matrix"]["status"] == "passed"
    assert areas["native_agent_capability_matrix"]["capability_count"] == 13
    assert areas["gatekeeper_first_launch"]["required_evidence"] == (
        "Record Finder Control-click -> Open evidence."
    )
    assert "Finder Control-click" in areas["gatekeeper_first_launch"]["next_action"]
    assert "--check-gatekeeper-readiness" in areas["gatekeeper_first_launch"][
        "recommended_command"
    ]
    assert areas["external_integrations"]["status"] == "manual_required"
    assert areas["external_integrations"]["required_evidence"] == (
        "Archive tmp/external-integrations-smoke.json."
    )
    assert "--live2d-archive" in areas["external_integrations"]["recommended_command"]
    assert "live2d_resource" in areas["external_integrations"]["evidence_summary"]["notes_preview"]


def test_oha_parity_summary_marks_missing_product_identity_requirement(tmp_path):
    _write_product_identity_files(tmp_path)
    (tmp_path / ".github/workflows/release-macos.yml").write_text(
        "branches:\n  - main\n  - develop\n",
        encoding="utf-8",
    )
    report_path = tmp_path / "signoff.json"
    report_path.write_text(json.dumps(_signoff_report()), encoding="utf-8")

    summary = parity.summarize_parity(tmp_path, Path("signoff.json"))

    areas = {area["id"]: area for area in summary["areas"]}
    product = areas["product_release_identity"]
    assert product["status"] == "missing"
    assert "release_workflow_oha_branch" in product["missing_requirement_ids"]
    assert "product_release_identity" in summary["incomplete_area_ids"]


def test_oha_parity_summary_cli_writes_json(tmp_path, monkeypatch):
    _write_product_identity_files(tmp_path)
    report_path = tmp_path / "signoff.json"
    output_path = tmp_path / "parity.json"
    report_path.write_text(json.dumps(_signoff_report()), encoding="utf-8")
    monkeypatch.setattr(parity, "PROJECT_ROOT", tmp_path)

    assert parity.main([str(report_path), "--output-json", str(output_path)]) == 1
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "incomplete"
    assert payload["manual_remaining_check_ids"] == [
        "gatekeeper_first_launch",
        "external_integrations_smoke",
    ]
