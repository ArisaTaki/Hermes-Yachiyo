from __future__ import annotations

import json

from scripts import smoke_desktop_planner_discovery as smoke


def test_desktop_planner_discovery_smoke_covers_discover_operate_verify():
    evidence = smoke.run_smoke()

    assert evidence["ok"] is True
    cases = {case["id"]: case for case in evidence["cases"]}
    assert set(cases) == {
        "generic_app_open",
        "generic_app_read_buttons",
        "app_scoped_click",
        "app_scoped_type",
    }
    assert [request["tool"] for request in cases["generic_app_open"]["requests"]] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert [request["tool"] for request in cases["generic_app_read_buttons"]["requests"]] == [
        "desktop.inspect_app",
    ]
    assert cases["app_scoped_click"]["requests"][0]["tool"] == "desktop.inspect_app"
    assert cases["app_scoped_click"]["requests"][1]["tool"] == (
        "app.focus_and_click_ui_element"
    )
    assert cases["app_scoped_type"]["requests"][0]["tool"] == "desktop.inspect_app"
    assert cases["app_scoped_type"]["requests"][1]["tool"] == (
        "app.focus_and_type_into_ui_element"
    )
    assert all(case["checks"]["uses_no_browser_tool"] for case in cases.values())


def test_desktop_planner_discovery_smoke_cli_outputs_json(capsys):
    assert smoke.main([]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["mode"] == "desktop_planner_discovery_smoke"
    assert output["case_count"] == len(smoke.DESKTOP_PLANNER_CASES)
