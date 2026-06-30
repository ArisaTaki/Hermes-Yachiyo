from __future__ import annotations

import json

from scripts import smoke_data_analysis_artifacts as smoke


def test_data_analysis_artifact_smoke_writes_and_reads_back_artifacts(tmp_path):
    evidence = smoke.run_smoke(tmp_path)

    assert evidence["ok"] is True
    assert evidence["case_count"] == 4
    assert evidence["source_kinds"] == ["csv", "json", "text_table", "xlsx"]
    assert evidence["checks"] == {
        "csv_case_passed": True,
        "all_cases_passed": True,
        "covers_csv_json_text_table_xlsx": True,
    }
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
    cases_by_id = {case["id"]: case for case in evidence["cases"]}
    assert set(cases_by_id) == {"csv", "json", "text_table", "xlsx"}
    for case_id, source_kind in {
        "csv": "csv",
        "json": "json",
        "text_table": "text_table",
        "xlsx": "xlsx",
    }.items():
        case = cases_by_id[case_id]
        assert case["ok"] is True
        assert case["result"]["source_kind"] == source_kind
        assert case["result"]["rows"] == 3
        assert case["result"]["columns"] == ["region", "revenue", "units"]
        assert case["followup_snapshot"]["source_tool"] == "data.analyze"
        assert case["followup_snapshot"]["artifact_paths"] == case["result"]["artifact_paths"]
        assert {item["check"] for item in case["readback"]} == {
            "markdown_report",
            "csv_summary",
            "html_report",
            "png_signature",
        }
        assert all(item["matched"] for item in case["readback"])


def test_data_analysis_artifact_smoke_cli_outputs_json(capsys, tmp_path):
    assert smoke.main(["--workdir", str(tmp_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "data_analysis_artifact_smoke"
    assert output["case_count"] == 4
    assert output["source_kinds"] == ["csv", "json", "text_table", "xlsx"]
    assert output["input_path"] == smoke.SAMPLE_PATH
    assert output["result"]["artifact_paths"] == smoke.ARTIFACT_PATHS
    assert output["followup_snapshot"]["source_tool"] == "data.analyze"


def test_data_analysis_artifact_smoke_cli_writes_report_json(capsys, tmp_path):
    report_path = tmp_path / "data-analysis-artifacts.json"
    workdir = tmp_path / "workspace"

    assert smoke.main(["--workdir", str(workdir), "--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "data_analysis_artifact_smoke"
    assert report["checks"]["covers_csv_json_text_table_xlsx"] is True
    assert [case["result"]["source_kind"] for case in report["cases"]] == [
        "csv",
        "json",
        "text_table",
        "xlsx",
    ]
    assert report["result"]["artifact_paths"] == smoke.ARTIFACT_PATHS
    assert "data analysis artifact smoke report:" in captured.err
    assert str(report_path) in captured.err
