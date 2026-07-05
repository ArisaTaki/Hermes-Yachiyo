from __future__ import annotations

import json

from scripts import smoke_oha_desktop_agent_release as smoke


def test_oha_desktop_agent_release_smoke_covers_product_readiness(tmp_path) -> None:
    report = smoke.run_smoke(workdir=tmp_path / "oha-release-smoke")

    assert report["ok"] is True
    assert report["mode"] == "oha_desktop_agent_release_smoke"
    assert report["failed_sections"] == []
    assert report["checks"] == {
        "all_sections_passed": True,
        "covers_deepagent_core": True,
        "covers_desktop_executor": True,
        "covers_legacy_facade_planner_ownership": True,
        "covers_chat_bubble_live2d": True,
        "covers_agent_studio": True,
        "covers_groups_workflow": True,
        "covers_approval_gate": True,
        "covers_data_analysis": True,
        "covers_studio_debug_catalog": True,
    }

    section_by_id = {section["id"]: section for section in report["sections"]}
    assert section_by_id["deepagent_core"]["report"]["tool_steps"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert section_by_id["shared_daily_surfaces"]["report"]["checks"][
        "all_use_runtime_planner"
    ] is True
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "model_never_called"
    ] is True
    assert section_by_id["legacy_facade_planner_ownership"]["report"]["checks"][
        "legacy_parser_not_called"
    ] is True
    assert section_by_id["legacy_facade_planner_ownership"]["report"][
        "legacy_call_count"
    ] == 0
    assert section_by_id["agent_studio_orchestration"]["report"][
        "started_workflow_run_id"
    ] == "workflow-run-studio-planner"
    assert section_by_id["agent_studio_orchestration"]["report"][
        "started_group_run_id"
    ] == "group-run-studio-planner"
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "planner_owner"
    ] == "runtime_planner"


def test_oha_desktop_agent_release_smoke_cli_writes_report(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    output_path = tmp_path / "oha-release-smoke.json"

    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda **_kwargs: {
            "ok": True,
            "mode": "oha_desktop_agent_release_smoke",
            "section_count": 0,
            "failed_sections": [],
            "checks": {"all_sections_passed": True},
            "sections": [],
        },
    )

    exit_code = smoke.main(["--report-json", str(output_path)])

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["mode"] == "oha_desktop_agent_release_smoke"
    assert "oha desktop agent release smoke report:" in capsys.readouterr().err
