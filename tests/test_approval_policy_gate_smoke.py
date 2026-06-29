from __future__ import annotations

import json

from scripts import smoke_approval_policy_gate as smoke


def test_approval_policy_gate_smoke_covers_low_and_medium_risk_plans():
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    cases = {case["id"]: case for case in evidence["planner_cases"]}
    assert set(cases) == {
        "low_risk_app_open",
        "low_risk_current_page_report",
        "medium_risk_app_click",
        "medium_risk_app_type",
        "medium_risk_browser_click",
    }
    assert cases["low_risk_app_open"]["approvals_required"] == []
    assert cases["low_risk_current_page_report"]["approvals_required"] == []
    assert cases["medium_risk_app_click"]["approvals_required"] == [
        "operate-foreground-ui"
    ]
    assert cases["medium_risk_app_type"]["approvals_required"] == [
        "operate-foreground-ui"
    ]
    assert cases["medium_risk_browser_click"]["approvals_required"] == [
        "click-current-page-element"
    ]
    assert all(case["checks"]["no_unexpected_approvals"] for case in cases.values())


def test_approval_policy_gate_smoke_covers_runtime_and_group_policy():
    evidence = smoke.run_smoke()

    assert evidence["runtime_policy"]["ok"] is True
    approval_required = evidence["runtime_policy"]["compiled"]["approval_required"]
    assert approval_required == {
        "terminal.run": True,
        "app.focus_and_click_ui_element": True,
        "browser.click": True,
    }
    assert evidence["group_policy"]["ok"] is True
    group_approval_tools = set(evidence["group_policy"]["approval_required_tools"])
    assert "app.focus_and_click_ui_element" in group_approval_tools
    assert "app.focus_and_type_into_ui_element" in group_approval_tools
    assert "browser.click" in group_approval_tools
    assert "browser.type_text" in group_approval_tools
    assert "desktop.submit_foreground" in group_approval_tools


def test_approval_policy_gate_smoke_cli_outputs_json(capsys):
    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "approval_policy_gate_smoke"
    assert output["planner_case_count"] == len(smoke.PLANNER_APPROVAL_CASES)


def test_approval_policy_gate_smoke_cli_writes_report_json(tmp_path, capsys):
    report_path = tmp_path / "approval-policy-gate.json"

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "approval_policy_gate_smoke"
    assert "approval policy gate smoke report:" in captured.err
    assert str(report_path) in captured.err
