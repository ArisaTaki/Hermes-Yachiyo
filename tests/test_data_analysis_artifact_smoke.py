from __future__ import annotations

import json

from scripts import smoke_data_analysis_artifacts as smoke


def test_data_analysis_artifact_smoke_writes_and_reads_back_artifacts(tmp_path):
    evidence = smoke.run_smoke(tmp_path)

    assert evidence["ok"] is True
    assert evidence["result"]["source_kind"] == "csv"
    assert evidence["result"]["rows"] == 3
    assert evidence["result"]["columns"] == ["region", "revenue", "units"]
    assert evidence["result"]["artifact_paths"] == smoke.ARTIFACT_PATHS
    assert evidence["result"]["artifact_manifest"] == [
        {"path": "reports/sales.md", "kind": "markdown"},
        {"path": "reports/sales-summary.csv", "kind": "csv"},
        {"path": "reports/sales.html", "kind": "html"},
        {"path": "reports/sales-chart.png", "kind": "chart", "actual_kind": "image"},
    ]
    assert evidence["followup_snapshot"]["source_tool"] == "data.analyze"
    assert evidence["followup_snapshot"]["artifact_paths"] == smoke.ARTIFACT_PATHS
    assert "Data analysis result for inputs/sales.csv (csv)." in evidence["followup_snapshot"]["text"]
    assert {item["check"] for item in evidence["readback"]} == {
        "markdown_report",
        "csv_summary",
        "html_report",
        "png_signature",
    }
    assert all(item["exists"] for item in evidence["readback"])
    assert all(item["matched"] for item in evidence["readback"])


def test_data_analysis_artifact_smoke_cli_outputs_json(capsys, tmp_path):
    assert smoke.main(["--workdir", str(tmp_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "data_analysis_artifact_smoke"
    assert output["input_path"] == smoke.SAMPLE_PATH
    assert output["result"]["artifact_paths"] == smoke.ARTIFACT_PATHS
    assert output["followup_snapshot"]["source_tool"] == "data.analyze"
