from __future__ import annotations

import json

from scripts import smoke_oha_desktop_agent_release as smoke


def _fake_dev_isolated_provider_report() -> dict[str, object]:
    return {
        "ok": True,
        "mode": "isolated_desktop_provider_smoke",
        "covered_tools": ["desktop.list_apps", "app.open", "desktop.verify"],
        "desktop_session_kind": "isolated_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "keyboard_mouse_capture_supported": True,
        "desktop_backend_kind": "loopback_session_harness",
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
        "provider_contract": {
            "ok": False,
            "contract_version": "oha-yachiyo.desktop-provider.v1",
            "blocking_conditions": [
                "loopback_desktop_backend",
                "desktop_backend_not_release_ready",
                "real_virtual_desktop_backend_required",
            ],
        },
    }


def test_oha_desktop_agent_release_smoke_covers_product_readiness(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: _fake_dev_isolated_provider_report(),
    )

    report = smoke.run_smoke(workdir=tmp_path / "oha-release-smoke")

    assert report["ok"] is True
    assert report["mode"] == "oha_desktop_agent_release_smoke"
    assert report["isolated_provider_smoke_requested"] is True
    assert report["isolated_provider_smoke_collected"] is True
    assert report["isolated_provider_smoke_mode"] == "dev_loopback_provider_smoke"
    assert report["isolated_provider_dev_smoke_ready"] is True
    assert report["isolated_provider_release_ready"] is False
    assert report["isolated_provider_release_blockers"] == []
    assert report["failed_sections"] == []
    assert report["checks"] == {
        "all_sections_passed": True,
        "covers_deepagent_core": True,
        "covers_desktop_executor": True,
        "covers_desktop_provider_execution_loop": True,
        "covers_legacy_facade_planner_ownership": True,
        "covers_chat_bubble_live2d": True,
        "covers_agent_studio": True,
        "covers_groups_workflow": True,
        "covers_approval_gate": True,
        "covers_data_analysis": True,
        "covers_studio_debug_catalog": True,
        "covers_provider_session_observability": True,
        "covers_isolated_desktop_provider": True,
        "isolated_provider_dev_smoke_verified": True,
    }

    section_by_id = {section["id"]: section for section in report["sections"]}
    assert section_by_id["deepagent_core"]["report"]["tool_steps"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.verify",
    ]
    assert section_by_id["shared_daily_surfaces"]["report"]["checks"][
        "all_use_runtime_planner"
    ] is True
    assert section_by_id["shared_daily_surfaces"]["report"]["checks"][
        "direct_recovery_keeps_daily_sandbox_policy"
    ] is True
    assert section_by_id["shared_daily_surfaces"]["report"]["checks"][
        "direct_recovery_recommends_provider_session"
    ] is True
    assert section_by_id["shared_daily_surfaces"]["report"]["direct_recovery_request"][
        "desktop_execution_policy"
    ]["avoid_user_foreground_takeover"] is True
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "model_never_called"
    ] is True
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "daily_app_open_recommends_provider_session"
    ] is True
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "daily_media_playback_recommends_provider_session"
    ] is True
    assert section_by_id["desktop_provider_execution_loop"]["report"]["checks"][
        "provider_executes_sandbox_ready_request"
    ] is True
    assert section_by_id["desktop_provider_execution_loop"]["report"]["checks"][
        "provider_unavailable_requests_replan"
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
    assert section_by_id["provider_session_observability"]["report"]["checks"][
        "start_payload_projects_provider_session_event"
    ] is True
    assert section_by_id["provider_session_observability"]["report"]["checks"][
        "run_timeline_projects_provider_session_event"
    ] is True
    assert section_by_id["provider_session_observability"]["report"]["runtime_debug"][
        "desktop_provider_session_status"
    ] == "start_failed"
    assert section_by_id["provider_session_observability"]["report"]["runtime_debug"][
        "desktop_provider_session_foreground_takeover_required"
    ] is False
    assert section_by_id["provider_session_observability"]["report"]["checks"][
        "runtime_debug_surfaces_provider_manifest"
    ] is True
    assert section_by_id["provider_session_observability"]["report"]["runtime_debug"][
        "desktop_provider_manifest_ok"
    ] is False
    assert "desktop_provider_manifest_remote_endpoint_not_allowed" in section_by_id[
        "provider_session_observability"
    ]["report"]["runtime_debug"]["desktop_provider_manifest_blocking_conditions"]
    assert section_by_id["isolated_desktop_provider"]["ok"] is True
    assert section_by_id["isolated_desktop_provider"]["report"][
        "foreground_takeover_required"
    ] is False


def test_oha_desktop_agent_release_smoke_can_include_isolated_provider(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: _fake_dev_isolated_provider_report(),
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "oha-release-smoke",
        run_isolated_provider_smoke=True,
    )

    assert report["ok"] is True
    assert report["isolated_provider_smoke_requested"] is True
    assert report["isolated_provider_smoke_collected"] is True
    assert report["isolated_provider_smoke_mode"] == "dev_loopback_provider_smoke"
    assert report["isolated_provider_dev_smoke_ready"] is True
    assert report["isolated_provider_release_ready"] is False
    assert report["isolated_provider_release_blockers"] == []
    assert report["checks"]["covers_isolated_desktop_provider"] is True
    assert report["checks"]["isolated_provider_dev_smoke_verified"] is True
    assert "isolated_provider_release_backend_verified" not in report["checks"]
    section_by_id = {section["id"]: section for section in report["sections"]}
    assert section_by_id["isolated_desktop_provider"]["mode"] == (
        "isolated_desktop_provider_smoke"
    )
    assert section_by_id["isolated_desktop_provider"]["report"][
        "foreground_takeover_required"
    ] is False
    assert report["isolated_provider_backend"] == {
        "desktop_session_kind": "isolated_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "keyboard_mouse_capture_supported": True,
        "desktop_backend_kind": "loopback_session_harness",
        "desktop_backend_is_loopback": True,
        "desktop_backend_ready_for_public_release": False,
        "requires_real_virtual_desktop_backend": True,
        "provider_contract_ok": False,
        "provider_contract_version": "oha-yachiyo.desktop-provider.v1",
        "provider_contract_blocking_conditions": [
            "loopback_desktop_backend",
            "desktop_backend_not_release_ready",
            "real_virtual_desktop_backend_required",
        ],
        "provider_conformance_ok": False,
        "provider_conformance_mode": "release_smoke_backend_summary",
        "provider_conformance_smoke_ok": True,
        "provider_conformance_public_release_ready": False,
        "provider_conformance_release_candidate": False,
        "provider_conformance_release_blocking_conditions": [
            "loopback_desktop_backend",
            "desktop_backend_not_release_ready",
            "real_virtual_desktop_backend_required",
        ],
        "provider_conformance_missing_required_tools": [],
        "provider_conformance_failed_tools": [],
    }


def test_oha_desktop_agent_release_smoke_accepts_configured_virtual_provider(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: {
            "ok": True,
            "mode": "isolated_desktop_provider_smoke",
            "covered_tools": ["desktop.list_apps", "app.open", "desktop.verify"],
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "virtual_desktop",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "provider_contract": {
                "ok": True,
                "contract_version": "oha-yachiyo.desktop-provider.v1",
                "blocking_conditions": [],
            },
        },
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "oha-release-smoke",
        run_isolated_provider_smoke=True,
        use_configured_virtual_desktop_provider=True,
    )

    assert report["ok"] is True
    assert report["configured_virtual_desktop_provider_requested"] is True
    assert report["isolated_provider_smoke_mode"] == (
        "release_virtual_desktop_provider_smoke"
    )
    assert report["isolated_provider_release_ready"] is True
    assert report["isolated_provider_release_blockers"] == []
    assert report["checks"]["isolated_provider_release_backend_verified"] is True
    backend = report["isolated_provider_backend"]
    assert backend["provider_conformance_public_release_ready"] is True
    assert backend["provider_conformance_release_blocking_conditions"] == []


def test_oha_desktop_agent_release_smoke_public_release_requires_real_backend(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: _fake_dev_isolated_provider_report(),
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "oha-release-smoke",
        run_isolated_provider_smoke=True,
        require_public_release_backend=True,
    )

    assert report["ok"] is False
    assert report["public_release_required"] is True
    assert report["public_release_ready"] is False
    assert report["isolated_provider_release_ready"] is False
    assert report["checks"]["isolated_provider_release_backend_verified"] is False
    assert report["isolated_provider_release_blockers"] == [
        "loopback_desktop_backend",
        "desktop_backend_not_release_ready",
        "real_virtual_desktop_backend_required",
        "virtual_desktop_provider_not_configured",
    ]
    readiness = report["public_release_readiness"]
    assert readiness["ready"] is False
    assert readiness["blocking_conditions"] == report["isolated_provider_release_blockers"]
    assert [action["id"] for action in readiness["next_actions"]] == [
        "write_provider_manifest_template",
        "configure_virtual_desktop_provider",
        "attach_real_virtual_desktop_backend",
        "run_public_release_smoke",
    ]
    assert readiness["required_commands"]["public_release_smoke"].startswith(
        "python scripts/smoke_oha_desktop_agent_release.py --public-release"
    )


def test_oha_desktop_agent_release_smoke_public_release_accepts_configured_provider(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: {
            "ok": True,
            "mode": "isolated_desktop_provider_smoke",
            "covered_tools": ["desktop.list_apps", "app.open", "desktop.verify"],
            "desktop_session_kind": "virtual_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "desktop_backend_kind": "virtual_desktop",
            "desktop_backend_is_loopback": False,
            "desktop_backend_ready_for_public_release": True,
            "requires_real_virtual_desktop_backend": False,
            "provider_contract": {
                "ok": True,
                "contract_version": "oha-yachiyo.desktop-provider.v1",
                "blocking_conditions": [],
            },
            "provider_conformance": {
                "ok": True,
                "public_release_ready": True,
                "release_candidate": True,
                "release_blocking_conditions": [],
                "missing_required_tools": [],
                "failed_tools": [],
            },
        },
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "oha-release-smoke",
        run_isolated_provider_smoke=True,
        use_configured_virtual_desktop_provider=True,
        require_public_release_backend=True,
    )

    assert report["ok"] is True
    assert report["public_release_required"] is True
    assert report["public_release_ready"] is True
    assert report["isolated_provider_release_ready"] is True
    assert report["checks"]["isolated_provider_release_backend_verified"] is True
    assert report["isolated_provider_release_blockers"] == []
    assert report["public_release_readiness"]["ready"] is True
    assert report["public_release_readiness"]["next_actions"] == [
        {
            "id": "run_public_release_smoke",
            "title": "Run public release smoke",
            "reason": "This is the release gate for desktop-agent provider readiness.",
            "command": (
                "python scripts/smoke_oha_desktop_agent_release.py "
                "--public-release "
                "--report-json tmp/oha-desktop-agent-public-release-smoke.json"
            ),
        }
    ]


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
            "public_release_required": False,
            "public_release_ready": False,
            "section_count": 0,
            "failed_sections": [],
            "checks": {"all_sections_passed": True},
            "isolated_provider_smoke_requested": False,
            "configured_virtual_desktop_provider_requested": False,
            "isolated_provider_smoke_collected": False,
            "isolated_provider_dev_smoke_ready": False,
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
        "public_release_required": False,
        "public_release_ready": False,
        "public_release_readiness": {},
        "section_count": 0,
        "failed_sections": [],
        "checks": {"all_sections_passed": True},
        "isolated_provider_smoke_requested": False,
        "configured_virtual_desktop_provider_requested": False,
        "isolated_provider_smoke_collected": False,
        "isolated_provider_smoke_mode": "",
        "isolated_provider_dev_smoke_ready": False,
        "isolated_provider_release_ready": False,
        "isolated_provider_release_blockers": [],
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
    assert captured_kwargs["use_configured_virtual_desktop_provider"] is False


def test_oha_desktop_agent_release_smoke_cli_defaults_to_isolated_provider_smoke(
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
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 0
    assert captured_kwargs["run_isolated_provider_smoke"] is True


def test_oha_desktop_agent_release_smoke_cli_can_skip_isolated_provider_smoke(
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
            "--skip-isolated-provider-smoke",
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 0
    assert captured_kwargs["run_isolated_provider_smoke"] is False


def test_oha_desktop_agent_release_smoke_cli_passes_configured_provider_flag(
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
            "--use-configured-virtual-desktop-provider",
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 0
    assert captured_kwargs["run_isolated_provider_smoke"] is True
    assert captured_kwargs["use_configured_virtual_desktop_provider"] is True


def test_oha_desktop_agent_release_smoke_cli_public_release_requires_backend(
    tmp_path,
    monkeypatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run_smoke(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "ok": False,
            "mode": "oha_desktop_agent_release_smoke",
            "public_release_required": True,
            "public_release_ready": False,
            "section_count": 0,
            "failed_sections": [],
            "checks": {"isolated_provider_release_backend_verified": False},
            "isolated_provider_smoke_requested": True,
            "configured_virtual_desktop_provider_requested": False,
            "isolated_provider_smoke_collected": True,
            "isolated_provider_dev_smoke_ready": True,
            "isolated_provider_release_ready": False,
            "isolated_provider_release_blockers": [
                "virtual_desktop_provider_not_configured"
            ],
            "isolated_provider_backend": {},
            "sections": [],
        }

    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)

    exit_code = smoke.main(
        [
            "--public-release",
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 1
    assert captured_kwargs["run_isolated_provider_smoke"] is True
    assert captured_kwargs["require_public_release_backend"] is True


def test_oha_desktop_agent_release_smoke_cli_passes_provider_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    captured_kwargs: dict[str, object] = {}
    manifest_path = tmp_path / "provider-manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

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
            "--provider-manifest",
            str(manifest_path),
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 0
    assert captured_kwargs["run_isolated_provider_smoke"] is True
    assert captured_kwargs["provider_manifest"] == manifest_path


def test_oha_desktop_agent_release_smoke_cli_writes_provider_manifest_template(
    tmp_path,
    capsys,
) -> None:
    output_path = tmp_path / "provider-manifest.template.json"

    exit_code = smoke.main(
        [
            "--write-provider-manifest-template",
            str(output_path),
            "--provider-manifest-template-provider-id",
            "release-provider",
            "--provider-manifest-template-base-url",
            "http://127.0.0.1:39097",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["provider_id"] == "release-provider"
    assert payload["provider_kind"] == "sandbox_desktop"
    assert payload["desktop_session_kind"] == "virtual_desktop"
    assert payload["desktop_session_isolated"] is True
    assert payload["foreground_takeover_required"] is False
    assert payload["desktop_backend_is_loopback"] is False
    assert payload["desktop_backend_ready_for_public_release"] is True
    assert payload["endpoint_urls"]["execute"] == (
        "http://127.0.0.1:39097/tools/execute"
    )
    assert "desktop.list_apps" in payload["supported_tools"]
    assert "desktop.verify" in payload["supported_tools"]
    captured = capsys.readouterr()
    assert "oha virtual desktop provider manifest template:" in captured.err
    assert json.loads(captured.out)["provider_id"] == "release-provider"


def test_oha_desktop_agent_release_smoke_cli_validates_provider_manifest(
    tmp_path,
    capsys,
) -> None:
    manifest_path = tmp_path / "provider-manifest.json"
    report_path = tmp_path / "provider-manifest-validation.json"

    template = smoke.virtual_desktop_provider_manifest_template(
        provider_id="release-provider",
        base_url="http://127.0.0.1:39097",
    )
    manifest_path.write_text(
        json.dumps(template, ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = smoke.main(
        [
            "--validate-provider-manifest",
            str(manifest_path),
            "--report-json",
            str(report_path),
        ]
    )

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["mode"] == "virtual_desktop_provider_manifest_validation"
    assert report["runtime_checked"] is False
    assert report["provider_id"] == "release-provider"
    assert report["manifest_path"] == str(manifest_path)
    assert report["provider_conformance"]["mode"] == "manifest_contract_check"
    assert report["provider_conformance"]["runtime_checked"] is False
    assert report["provider_conformance"]["public_release_ready"] is True
    captured = capsys.readouterr()
    assert "oha virtual desktop provider manifest validation report:" in captured.err
    assert json.loads(captured.out)["ok"] is True


def test_oha_desktop_agent_release_smoke_cli_rejects_bad_provider_manifest(
    tmp_path,
    capsys,
) -> None:
    manifest_path = tmp_path / "bad-provider-manifest.json"
    manifest_path.write_text(
        json.dumps({"provider_kind": "local_desktop"}),
        encoding="utf-8",
    )

    exit_code = smoke.main(["--validate-provider-manifest", str(manifest_path)])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "desktop_provider_manifest_provider_id_missing" in payload[
        "blocking_conditions"
    ]
    assert "desktop_provider_manifest_wrong_provider_kind" in payload[
        "blocking_conditions"
    ]
    assert payload["provider_conformance"]["public_release_ready"] is False


def test_oha_desktop_agent_release_smoke_cli_rejects_remote_provider_manifest(
    tmp_path,
    capsys,
) -> None:
    manifest_path = tmp_path / "remote-provider-manifest.json"
    template = smoke.virtual_desktop_provider_manifest_template(
        provider_id="remote-provider",
        base_url="https://provider.example.com",
    )
    manifest_path.write_text(
        json.dumps(template, ensure_ascii=False),
        encoding="utf-8",
    )

    exit_code = smoke.main(["--validate-provider-manifest", str(manifest_path)])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["remote_endpoint_allowed"] is False
    assert payload["remote_endpoint_urls"]
    assert "desktop_provider_manifest_remote_endpoint_not_allowed" in payload[
        "blocking_conditions"
    ]
    assert payload["provider_conformance"]["public_release_ready"] is False
