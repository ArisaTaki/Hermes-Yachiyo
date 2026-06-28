from __future__ import annotations

import json

from scripts import smoke_planner_runtime_tool_parity as smoke


def test_planner_runtime_tool_parity_covers_runtime_executable_tools():
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["case_count"] == 7
    case_by_id = {case["id"]: case for case in evidence["cases"]}
    assert case_by_id["generic_app_open"]["request_tools"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert case_by_id["app_scoped_ui_click"]["request_tools"] == [
        "desktop.list_apps",
        "app.focus",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    assert case_by_id["app_scoped_ui_click"]["approval_required_tools"] == [
        "desktop.click_ui_element"
    ]
    assert case_by_id["builtin_data_analysis"]["request_tools"] == ["data.analyze"]
    assert case_by_id["current_page_report"]["plan_tools"] == [
        "browser.extract_text",
        "artifact.write",
    ]
    assert case_by_id["explicit_terminal_command"]["approval_required_tools"] == [
        "terminal.run"
    ]


def test_planner_runtime_tool_parity_cli_outputs_json(capsys):
    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "planner_runtime_tool_parity_smoke"
    assert all(case["checks"]["request_tools_dispatched"] for case in output["cases"])
    assert all(case["checks"]["tools_have_model_descriptors"] for case in output["cases"])
