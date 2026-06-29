from __future__ import annotations

import json

from scripts import smoke_browser_planner_artifacts as smoke


def test_browser_planner_artifact_smoke_covers_browser_tool_plans():
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    cases = {case["id"]: case for case in evidence["cases"]}
    assert set(cases) == {
        "current_page_report",
        "explicit_url_report",
        "current_page_screenshot",
        "search_report",
    }
    assert cases["current_page_report"]["requests"][0]["tool"] == "browser.extract_text"
    assert cases["explicit_url_report"]["requests"][0]["tool"] == (
        "browser.open_url_and_extract_text"
    )
    assert cases["current_page_screenshot"]["requests"][0]["tool"] == "browser.screenshot"
    assert cases["search_report"]["requests"][0]["tool"] == "browser.open_url"
    assert cases["current_page_screenshot"]["artifacts_expected"] == [
        "browser/current-page.png"
    ]
    assert all(case["checks"]["uses_browser_tool"] for case in cases.values())


def test_browser_planner_artifact_smoke_cli_outputs_json(capsys):
    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "browser_planner_artifact_smoke"
    assert output["case_count"] == len(smoke.BROWSER_PLANNER_CASES)


def test_browser_planner_artifact_smoke_cli_writes_report_json(tmp_path, capsys):
    report_path = tmp_path / "browser-planner-artifacts.json"

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "browser_planner_artifact_smoke"
    assert "browser planner artifact smoke report:" in captured.err
    assert str(report_path) in captured.err
