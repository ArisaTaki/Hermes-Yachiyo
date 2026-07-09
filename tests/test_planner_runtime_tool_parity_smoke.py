from __future__ import annotations

import json

from scripts import smoke_planner_runtime_tool_parity as smoke


def test_planner_runtime_tool_parity_covers_runtime_executable_tools():
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    assert evidence["case_count"] == len(smoke.PLANNER_TOOL_PARITY_CASES)
    case_by_id = {case["id"]: case for case in evidence["cases"]}
    assert set(case_by_id) == {case["id"] for case in smoke.PLANNER_TOOL_PARITY_CASES}
    assert case_by_id["generic_app_open"]["request_tools"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.verify",
    ]
    assert case_by_id["app_scoped_ui_click"]["request_tools"] == [
        "desktop.inspect_app",
        "app.focus_and_click_ui_element",
        "desktop.ui_elements",
    ]
    assert case_by_id["app_scoped_ui_click"]["approval_required_tools"] == [
        "app.focus_and_click_ui_element"
    ]
    assert case_by_id["builtin_data_analysis"]["request_tools"] == ["data.analyze"]
    assert case_by_id["visible_table_analysis"]["plan_tools"] == [
        "desktop.ui_elements",
        "data.analyze",
    ]
    assert case_by_id["visible_table_analysis"]["request_tools"] == [
        "desktop.ui_elements"
    ]
    assert case_by_id["visible_table_analysis"]["deferred_plan_tools"] == [
        "data.analyze"
    ]
    assert case_by_id["visible_table_analysis"]["request_continue_to_model"] == [True]
    assert case_by_id["visible_table_analysis_to_document_app"]["plan_tools"] == [
        "desktop.ui_elements",
        "data.analyze",
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    assert case_by_id["visible_table_analysis_to_document_app"]["deferred_plan_tools"] == [
        "data.analyze",
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    assert case_by_id["current_page_report"]["plan_tools"] == [
        "browser.extract_text",
        "artifact.write",
    ]
    assert case_by_id["current_page_report"]["deferred_plan_tools"] == [
        "artifact.write"
    ]
    assert case_by_id["current_page_summary_to_app"]["plan_tools"] == [
        "browser.extract_text",
        "artifact.write",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    assert case_by_id["current_page_summary_to_app"]["deferred_plan_tools"] == [
        "artifact.write",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    assert case_by_id["current_page_summary_to_document_app"]["plan_tools"] == [
        "browser.extract_text",
        "artifact.write",
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    assert case_by_id["current_page_summary_to_document_app"]["deferred_plan_tools"] == [
        "artifact.write",
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.ui_elements",
    ]
    assert case_by_id["capability_media_app_playback"]["request_tools"] == [
        "desktop.list_apps",
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
        "desktop.ui_elements",
    ]
    assert case_by_id["clipboard_send_to_slack"]["request_tools"] == [
        "app.focus",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
    ]
    assert case_by_id["clipboard_send_to_slack"]["plan_tools"] == [
        "app.focus",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.safe_shortcut",
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert case_by_id["clipboard_send_to_slack"]["deferred_plan_tools"] == [
        "desktop.ui_elements"
    ]
    assert case_by_id["clipboard_send_to_slack"]["approval_required_tools"] == [
        "desktop.submit_foreground"
    ]
    assert case_by_id["system_settings_bluetooth"]["request_tools"] == [
        "system.settings_open"
    ]
    assert case_by_id["file_organize_invoices"]["plan_tools"] == [
        "workspace.list",
        "artifact.write",
        "file.organize",
    ]
    assert case_by_id["file_organize_invoices"]["request_tools"] == ["workspace.list"]
    assert case_by_id["file_organize_invoices"]["deferred_plan_tools"] == [
        "artifact.write",
        "file.organize",
    ]
    assert case_by_id["file_organize_invoices"]["approval_required_tools"] == []
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
    assert all(
        case["checks"]["deferred_followup_boundary_present"]
        for case in output["cases"]
    )


def test_planner_runtime_tool_parity_cli_writes_report_json(tmp_path, capsys):
    report_path = tmp_path / "planner-runtime-tool-parity.json"

    assert smoke.main(["--report-json", str(report_path)]) == 0

    captured = capsys.readouterr()
    output = json.loads(captured.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output == report
    assert report["ok"] is True
    assert report["mode"] == "planner_runtime_tool_parity_smoke"
    assert "planner runtime tool parity smoke report:" in captured.err
    assert str(report_path) in captured.err
