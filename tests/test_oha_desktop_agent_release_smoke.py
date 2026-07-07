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
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "planner_owned_entrypoints"
    ][0]["owner"] == "runtime_planner"
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "planner_owned_entrypoints"
    ][0]["legacy_shape_preserved"] is True
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "cleanup_readiness"
    ] == "planner_covered_compat_cleanup_pending"
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "planner_covered_fallback_count"
    ] == 4
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "compatibility_cleanup_pending_count"
    ] == 4
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "remaining_fallback_contracts"
    ][0]["status"] == "planner_covered_compat_cleanup_pending"
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "remaining_fallback_contracts"
    ][0]["planner_coverage_status"] == "planner_covered"
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "remaining_fallback_contracts"
    ][0]["cleanup_blocker"] == "legacy_response_shape_compatibility"
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "remaining_fallback_contracts"
    ][0]["planner_evidence_prompts"]
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "remaining_fallback_contracts"
    ][0]["required_before_delete"]
    assert section_by_id["studio_tool_catalog"]["report"]["checks"][
        "cleanup_lists_planner_owned_entrypoints"
    ] is True
    assert section_by_id["studio_tool_catalog"]["report"]["checks"][
        "cleanup_lists_remaining_fallbacks"
    ] is True
    assert section_by_id["studio_tool_catalog"]["report"]["checks"][
        "cleanup_remaining_fallbacks_are_planner_covered"
    ] is True


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
    captured = capsys.readouterr()
    assert "oha desktop agent release smoke report:" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload == {
        "ok": True,
        "mode": "oha_desktop_agent_release_smoke",
        "section_count": 0,
        "failed_sections": [],
        "checks": {"all_sections_passed": True},
        "sections": [],
    }


def test_oha_desktop_agent_release_smoke_cli_can_print_full_report(
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
            "section_count": 1,
            "failed_sections": [],
            "checks": {"all_sections_passed": True},
            "sections": [
                {
                    "id": "deepagent_core",
                    "ok": True,
                    "mode": "deepagent_core",
                    "report": {"large": "evidence"},
                }
            ],
        },
    )

    exit_code = smoke.main(
        ["--report-json", str(output_path), "--print-full-report"]
    )

    assert exit_code == 0
    stdout_payload = json.loads(capsys.readouterr().out)
    assert stdout_payload["sections"][0]["report"] == {"large": "evidence"}
