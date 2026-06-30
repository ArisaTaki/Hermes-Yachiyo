from __future__ import annotations

import json
import zipfile

from scripts import summarize_native_agent_capabilities as capability_summary
from scripts import summarize_release_smoke as release_smoke


def _capability(capability_id: str, status: str = "passed") -> dict[str, object]:
    definition = next(
        item
        for item in capability_summary.CAPABILITY_DEFINITIONS
        if item["id"] == capability_id
    )
    return {
        **definition,
        "category": capability_summary.capability_category(capability_id),
        "status": status,
        "evidence_summary": {"source": "test"},
    }


def _matrix_report(*capability_ids: str) -> dict[str, object]:
    capabilities = [_capability(capability_id) for capability_id in capability_ids]
    return {
        "native_agent_capability_matrix": {
            **capability_summary.capability_matrix_status_summary(capabilities),
            "status": "passed",
            "capabilities": capabilities,
        }
    }


def _diagnostics_zip(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "diagnostics/manifest.json",
            json.dumps(
                {
                    "ok": True,
                    "included_count": 1,
                    "redaction": {"applied": True},
                    "included": [{"source": "tmp/rc.json"}],
                }
            ),
        )


def test_release_smoke_summary_passes_with_required_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "rc.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            _matrix_report(
                "packaged_app_bridge_isolation",
                "source_agent_entrypoint_desktop_execution",
                "source_approval_resume_timeline",
                "source_yachiyo_route_approval",
                "source_group_run_timeline",
                "source_agent_entrypoint_data_analysis",
                "advanced_workflow_orchestration",
                "source_data_analysis_artifact",
            )
        ),
        encoding="utf-8",
    )
    diagnostics_zip = tmp_path / "tmp" / "diagnostics.zip"
    _diagnostics_zip(diagnostics_zip)

    summary = release_smoke.summarize_release_smoke(
        [report_path],
        diagnostics_zips=[diagnostics_zip],
    )

    assert summary["ok"] is True
    assert summary["status"] == "passed"
    assert summary["passed_count"] == summary["item_count"] == 8
    assert summary["missing_item_ids"] == []


def test_release_smoke_summary_reports_missing_items_and_next_actions(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "partial.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(_matrix_report("source_data_analysis_artifact")),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([report_path])

    assert summary["ok"] is False
    assert "diagnostics_export" in summary["missing_item_ids"]
    artifact = next(item for item in summary["items"] if item["id"] == "artifact_readback")
    assert artifact["status"] == "passed"
    packaged = next(item for item in summary["items"] if item["id"] == "packaged_launch")
    assert packaged["missing_evidence_ids"] == ["packaged_app_bridge_isolation"]
    commands = [item["command"] for item in summary["next_actions"]]
    assert any("collect_release_diagnostics.py" in command for command in commands)


def test_release_smoke_summary_accepts_raw_smoke_mode_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "group-run.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"ok": True, "mode": "group_run_timeline_smoke"}),
        encoding="utf-8",
    )

    summary = release_smoke.summarize_release_smoke([report_path])

    group_run = next(item for item in summary["items"] if item["id"] == "group_run")
    assert group_run["status"] == "passed"
    assert group_run["present_evidence_ids"] == ["source_group_run_timeline"]


def test_release_smoke_cli_writes_json_and_markdown(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(release_smoke, "ROOT", tmp_path)
    report_path = tmp_path / "tmp" / "partial.json"
    output_json = tmp_path / "tmp" / "summary.json"
    output_markdown = tmp_path / "tmp" / "summary.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(_matrix_report("source_data_analysis_artifact")),
        encoding="utf-8",
    )

    exit_code = release_smoke.main(
        [
            str(report_path),
            "--output-json",
            str(output_json),
            "--output-markdown",
            str(output_markdown),
        ]
    )

    assert exit_code == 1
    assert capsys.readouterr().out == ""
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["status"] == "incomplete"
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "# Oha-Yachiyo Release Smoke Summary" in markdown
    assert "`diagnostics_export`" in markdown
