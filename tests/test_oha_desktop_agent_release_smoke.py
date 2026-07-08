from __future__ import annotations

import json

from scripts import smoke_oha_desktop_agent_release as smoke


def test_oha_desktop_agent_release_smoke_covers_product_readiness(tmp_path) -> None:
    report = smoke.run_smoke(workdir=tmp_path / "oha-release-smoke")

    assert report["ok"] is True
    assert report["mode"] == "oha_desktop_agent_release_smoke"
    assert report["isolated_provider_smoke_requested"] is False
    assert report["isolated_provider_smoke_collected"] is False
    assert report["isolated_provider_backend"] == {}
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
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "daily_app_open_recommends_isolated_provider"
    ] is True
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "daily_media_playback_recommends_isolated_provider"
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
    ] == "legacy_fallbacks_eliminated"
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "planner_covered_fallback_count"
    ] == 0
    assert section_by_id["studio_tool_catalog"]["report"]["coverage"][
        "compatibility_cleanup_pending_count"
    ] == 0
    assert {
        contract["fallback_id"]
        for contract in section_by_id["studio_tool_catalog"]["report"]["coverage"][
            "remaining_fallback_contracts"
        ]
    } == set()
    assert section_by_id["studio_tool_catalog"]["report"]["checks"][
        "cleanup_lists_planner_owned_entrypoints"
    ] is True
    assert section_by_id["studio_tool_catalog"]["report"]["checks"][
        "cleanup_lists_remaining_fallbacks"
    ] is True
    assert section_by_id["studio_tool_catalog"]["report"]["checks"][
        "cleanup_remaining_fallbacks_are_planner_covered"
    ] is True


def test_oha_desktop_agent_release_smoke_can_include_isolated_provider(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda: {
            "ok": True,
            "mode": "isolated_desktop_provider_smoke",
            "covered_tools": ["desktop.list_apps", "app.open", "desktop.verify"],
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "loopback_session_harness",
            "desktop_backend_is_loopback": True,
            "desktop_backend_ready_for_public_release": False,
            "requires_real_virtual_desktop_backend": True,
        },
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "oha-release-smoke",
        run_isolated_provider_smoke=True,
    )

    assert report["ok"] is True
    assert report["isolated_provider_smoke_requested"] is True
    assert report["isolated_provider_smoke_collected"] is True
    assert report["checks"]["covers_isolated_desktop_provider"] is True
    section_by_id = {section["id"]: section for section in report["sections"]}
    assert section_by_id["isolated_desktop_provider"]["mode"] == (
        "isolated_desktop_provider_smoke"
    )
    assert section_by_id["isolated_desktop_provider"]["report"][
        "foreground_takeover_required"
    ] is False
    assert report["isolated_provider_backend"] == {
        "desktop_backend_kind": "loopback_session_harness",
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
    }


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
            "isolated_provider_smoke_requested": False,
            "isolated_provider_smoke_collected": False,
            "isolated_provider_backend": {},
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
        "isolated_provider_smoke_requested": False,
        "isolated_provider_smoke_collected": False,
        "isolated_provider_backend": {},
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


def test_oha_desktop_agent_release_smoke_cli_passes_isolated_provider_flag(
    tmp_path,
    monkeypatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run_smoke(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "ok": True,
            "mode": "oha_desktop_agent_release_smoke",
            "section_count": 0,
            "failed_sections": [],
            "checks": {"all_sections_passed": True},
            "sections": [],
        }

    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)

    exit_code = smoke.main(
        [
            "--run-isolated-provider-smoke",
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 0
    assert captured_kwargs["run_isolated_provider_smoke"] is True
