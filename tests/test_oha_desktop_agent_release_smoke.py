from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

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


def _fake_generic_agent_report() -> dict[str, object]:
    return {
        "ok": True,
        "mode": "generic_agent_release_smoke",
        "scenario_count": 8,
        "passed_count": 8,
        "failed_count": 0,
        "scenarios": [
            {"id": scenario_id, "status": "passed", "returncode": 0}
            for scenario_id in (
                "file_resolution",
                "app_resolution",
                "browser_research",
                "media_alias",
                "permission_resume",
                "background_non_takeover",
                "bounded_recovery",
                "internal_visibility",
            )
        ],
    }


def _packaged_daily_provider_acceptance() -> dict[str, object]:
    revision = "0123456789abcdef0123456789abcdef01234567"
    fingerprint = f"sha256:{'b' * 64}"
    asar_sha256 = "a" * 64
    target = {"target_pid": 4312, "target_window_id": 9721}
    transport = {
        "provider_id": "cua-driver",
        "provider_kind": "background_desktop",
        "transport": "electron_bridge",
        "delivery_mode": "background",
        "foreground_takeover_required": False,
    }
    payload: dict[str, object] = {
        "schema_version": "oha-yachiyo.daily-provider-acceptance.v2",
        "status": "passed",
        "evidence_source": "local_packaged_tcc_acceptance",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "provider_kind": "background_desktop",
        "provider_id": "cua-driver",
        "desktop_session_kind": "background_desktop",
        "transport": "cua_mcp_electron_bridge",
        "packaged_app": True,
        "packaged_app_path": "/Applications/Oha-Yachiyo.app",
        "build_revision": revision,
        "host_bundle_id": "io.github.arisataki.oha-yachiyo",
        "host_attribution_verified": True,
        "foreground_takeover_required": False,
        "tcc": {
            "accessibility": "authorized",
            "screen_recording": "authorized",
        },
        "app_identity": {
            "bundle_id": "io.github.arisataki.oha-yachiyo",
            "version": "0.4.0",
            "app_asar_sha256": asar_sha256,
            "build_revision": revision,
            "source_tree_fingerprint": fingerprint,
        },
        "observations": {
            "bridge_status": {
                "build_metadata": {
                    "commit": revision,
                    "source_tree_fingerprint": fingerprint,
                }
            },
            "provider_health": {
                "checked": True,
                "ok": True,
                "status": "healthy",
                "provider_id": "cua-driver",
                "provider_kind": "background_desktop",
                "source": "cua_mcp_electron_bridge",
                "transport": "electron_bridge",
                "blocking_conditions": [],
            },
            "authorized_task": {
                "receipts": {
                    "launch": {
                        "tool_name": "app.open",
                        "output_preview": {
                            **target,
                            "agent_owned_target": True,
                            "self_activation_suppressed": True,
                            "launch_verified": True,
                            "desktop_execution_provider_transport": transport,
                        },
                    },
                    "observation": {
                        "tool_name": "desktop.ui_elements",
                        "output_preview": {
                            "target_bound": True,
                            "observation_verified": True,
                            "data": {
                                **target,
                                "frontmost": False,
                                "desktop_scope": "agent_owned_background",
                            },
                            "desktop_execution_provider_transport": transport,
                        },
                    },
                    "input": {
                        "tool_name": "desktop.type_into_ui_element",
                        "output_preview": {
                            "target_bound": True,
                            "action_dispatched": True,
                            "grounded_element": {
                                "pid": target["target_pid"],
                                "window_id": target["target_window_id"],
                                "selector_type": "element_token",
                                "label": "Display",
                            },
                            "desktop_execution_provider_evidence": {
                                "pid": target["target_pid"],
                                "window_id": target["target_window_id"],
                                "desktop_scope": "agent_owned_background",
                                "target_bound": True,
                            },
                            "desktop_execution_provider_transport": transport,
                        },
                    },
                    "verify": {
                        "tool_name": "desktop.verify",
                        "output_preview": {
                            "target_bound": True,
                            "postcondition_verified": True,
                            "verification_context_trusted": True,
                            "verification_method": (
                                "trusted_exact_typed_content_receipt"
                            ),
                            "observed_target": {
                                "pid": target["target_pid"],
                                "window_id": target["target_window_id"],
                                "agent_owned_target": True,
                            },
                            "desktop_execution_provider_transport": transport,
                        },
                    },
                }
            },
            "observer": {
                "frontmost_samples": [
                    {"bundle_id": "com.apple.finder", "pid": 101},
                    {"bundle_id": "com.apple.finder", "pid": 101},
                ],
                "frontmost_unchanged": True,
                "pointer_max_delta": 0.25,
                "samples": [
                    {
                        "label": "before_task",
                        "frontmost": {
                            "ok": True,
                            "bundle_id": "com.apple.finder",
                            "pid": 101,
                        },
                        "cursor": {"ok": True, "x": 40.0, "y": 50.0},
                    },
                    {
                        "label": "after_task",
                        "frontmost": {
                            "ok": True,
                            "bundle_id": "com.apple.finder",
                            "pid": 101,
                        },
                        "cursor": {"ok": True, "x": 40.1, "y": 50.1},
                    },
                ],
            },
            "permission_denial": {
                "checked": True,
                "ok": False,
                "status": "not_ready",
                "blocking_conditions": [
                    "desktop_permission_accessibility_required"
                ],
                "action_dispatched": False,
                "tool_call_count": 0,
                "tool_calls": [],
                "launch_attempted": False,
                "input_attempted": False,
                "foreground_fallback_used": False,
            },
        },
        "checks": {
            "packaged_bridge_ready": True,
            "background_launch_verified": True,
            "target_bound_observation_verified": True,
            "background_input_verified": True,
            "postcondition_verified": True,
            "foreground_app_unchanged": True,
            "pointer_not_taken_over": True,
            "keyboard_not_taken_over": True,
            "permission_denial_fails_closed": True,
        },
    }
    payload["evidence_digest"] = smoke._daily_provider_acceptance_digest(payload)
    return payload


@pytest.fixture(autouse=True)
def _verified_direct_runtime_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.smoke_generic_agent_release,
        "run_smoke",
        _fake_generic_agent_report,
    )
    monkeypatch.setattr(
        smoke,
        "local_desktop_execution_runtime_probe",
        lambda: {
            "checked": True,
            "ok": True,
            "broker_dispatch_verified": True,
            "permission_probe_checked": True,
            "discovery_verified": True,
            "host_ready": True,
            "required_capabilities": [
                "desktop_execution",
                "active_window",
                "app_control",
                "foreground_activation",
                "foreground_input",
            ],
            "missing_permissions": [],
            "runtime_blocking_conditions": [],
            "blocking_conditions": [],
            "permission_action": "desktop.permissions",
            "discovery_action": "desktop.list_apps",
            "error": "",
        },
    )


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
    assert report["direct_desktop_release_ready"] is True
    assert report["default_daily_provider_release_ready"] is False
    assert report["public_release_ready"] is False
    assert report["public_release_readiness"]["ready"] is False
    assert report["public_release_readiness"]["blocking_conditions"] == [
        "default_daily_provider_release_evidence_required"
    ]
    assert report["failed_sections"] == []
    assert report["checks"] == {
        "all_sections_passed": True,
        "covers_deepagent_core": True,
        "covers_generic_agent_behaviors": True,
        "covers_desktop_executor": True,
        "covers_desktop_provider_execution_loop": True,
        "covers_legacy_facade_planner_ownership": True,
        "covers_chat_bubble_live2d": True,
        "covers_direct_desktop_runtime": True,
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
    assert section_by_id["generic_agent_behaviors"]["report"]["passed_count"] == 8
    assert section_by_id["deepagent_core"]["report"]["tool_steps"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.verify",
    ]
    assert section_by_id["shared_daily_surfaces"]["report"]["checks"][
        "all_use_runtime_planner"
    ] is True
    assert section_by_id["shared_daily_surfaces"]["report"]["checks"][
        "direct_recovery_keeps_daily_background_policy"
    ] is True
    assert section_by_id["shared_daily_surfaces"]["report"]["checks"][
        "direct_recovery_avoids_isolated_session_autostart"
    ] is True
    assert section_by_id["shared_daily_surfaces"]["report"]["direct_recovery_request"][
        "desktop_execution_policy"
    ]["avoid_user_foreground_takeover"] is True
    assert section_by_id["direct_desktop_runtime"]["ok"] is True
    assert section_by_id["direct_desktop_runtime"]["report"]["checks"][
        "constrained_input_executes_through_local_broker"
    ] is True
    assert section_by_id["direct_desktop_runtime"]["report"]["provider_kind"] == (
        "local_desktop"
    )
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "model_never_called"
    ] is True
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "daily_app_open_avoids_isolated_session_autostart"
    ] is True
    assert section_by_id["desktop_executor_before_model"]["report"]["checks"][
        "daily_media_playback_avoids_isolated_session_autostart"
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


def test_oha_desktop_agent_release_smoke_fails_when_generic_behaviors_fail(
    tmp_path,
    monkeypatch,
) -> None:
    failed_report = _fake_generic_agent_report()
    failed_report.update(
        {
            "ok": False,
            "passed_count": 7,
            "failed_count": 1,
            "failed_scenarios": ["bounded_recovery"],
        }
    )
    monkeypatch.setattr(
        smoke.smoke_generic_agent_release,
        "run_smoke",
        lambda: failed_report,
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "generic-failure",
        run_isolated_provider_smoke=False,
    )

    assert report["ok"] is False
    assert report["public_release_ready"] is False
    assert report["checks"]["covers_generic_agent_behaviors"] is False
    assert "generic_agent_behaviors" in report["failed_sections"]


def test_oha_desktop_agent_release_smoke_rejects_unverified_direct_runtime(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "local_desktop_execution_runtime_probe",
        lambda: {
            "checked": False,
            "ok": False,
            "broker_dispatch_verified": False,
            "permission_probe_checked": False,
            "discovery_verified": False,
            "host_ready": False,
            "blocking_conditions": ["local_desktop_runtime_not_checked"],
        },
        raising=False,
    )
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: _fake_dev_isolated_provider_report(),
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "oha-release-smoke",
        run_isolated_provider_smoke=False,
        public_release_required=True,
    )

    direct = next(
        section for section in report["sections"] if section["id"] == "direct_desktop_runtime"
    )
    assert direct["ok"] is False
    assert direct["report"]["checks"]["production_broker_probe_verified"] is False
    assert report["direct_desktop_release_ready"] is False
    assert report["public_release_ready"] is False


def test_public_release_does_not_treat_foreground_probe_as_daily_provider_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: _fake_dev_isolated_provider_report(),
    )
    report = smoke.run_smoke(
        workdir=tmp_path / "foreground-only",
        run_isolated_provider_smoke=True,
        public_release_required=True,
    )

    assert report["direct_desktop_release_ready"] is True
    assert report["default_daily_provider_release_ready"] is False
    assert report["public_release_ready"] is False
    assert report["default_daily_provider_release_blockers"] == [
        "default_daily_provider_release_evidence_required"
    ]


def test_public_release_accepts_explicit_packaged_tcc_daily_provider_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke.smoke_isolated_desktop_provider,
        "run_smoke",
        lambda **_kwargs: _fake_dev_isolated_provider_report(),
    )
    monkeypatch.setattr(
        smoke,
        "_packaged_app_identity_from_disk",
        lambda _path: {
            "ok": True,
            "location_valid": True,
            "bundle_id": "io.github.arisataki.oha-yachiyo",
            "version": "0.4.0",
            "app_asar_sha256": "a" * 64,
        },
    )
    acceptance_path = tmp_path / "daily-provider-acceptance.json"
    acceptance_path.write_text(
        json.dumps(_packaged_daily_provider_acceptance()),
        encoding="utf-8",
    )

    report = smoke.run_smoke(
        workdir=tmp_path / "packaged-background",
        run_isolated_provider_smoke=True,
        public_release_required=True,
        daily_provider_acceptance_json=acceptance_path,
    )

    assert report["daily_provider_acceptance"]["ok"] is True
    assert all(
        report["daily_provider_acceptance"]["derived_checks"].values()
    )
    assert report["default_daily_provider_release_source"] == (
        "local_packaged_tcc_acceptance"
    )
    assert report["default_daily_provider_release_ready"] is True
    assert report["default_daily_provider_release_blockers"] == []
    assert report["public_release_ready"] is report["ok"]


def test_daily_provider_acceptance_rejects_generic_ok_payload(tmp_path) -> None:
    acceptance_path = tmp_path / "unverified-acceptance.json"
    acceptance_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    evidence = smoke._daily_provider_acceptance_evidence(acceptance_path)

    assert evidence["ok"] is False
    assert "daily_provider_acceptance_schema_version_matches_failed" in evidence[
        "blocking_conditions"
    ]
    assert "daily_provider_acceptance_tcc_accessibility_authorized_failed" in evidence[
        "blocking_conditions"
    ]
    assert "daily_provider_acceptance_background_input_verified_accepted_failed" in evidence[
        "blocking_conditions"
    ]


def test_daily_provider_acceptance_rejects_mutated_digest(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_packaged_app_identity_from_disk",
        lambda _path: {
            "ok": True,
            "location_valid": True,
            "bundle_id": "io.github.arisataki.oha-yachiyo",
            "version": "0.4.0",
            "app_asar_sha256": "a" * 64,
        },
    )
    payload = _packaged_daily_provider_acceptance()
    payload["provider_id"] = "mutated-after-collection"
    acceptance_path = tmp_path / "mutated-acceptance.json"
    acceptance_path.write_text(json.dumps(payload), encoding="utf-8")

    evidence = smoke._daily_provider_acceptance_evidence(acceptance_path)

    assert evidence["ok"] is False
    assert evidence["validation"]["evidence_digest_valid"] is False
    assert "daily_provider_acceptance_evidence_digest_valid_failed" in evidence[
        "blocking_conditions"
    ]


def test_daily_provider_acceptance_derives_target_binding_and_fail_closed(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_packaged_app_identity_from_disk",
        lambda _path: {
            "ok": True,
            "location_valid": True,
            "bundle_id": "io.github.arisataki.oha-yachiyo",
            "version": "0.4.0",
            "app_asar_sha256": "a" * 64,
        },
    )
    payload = _packaged_daily_provider_acceptance()
    observations = payload["observations"]
    assert isinstance(observations, dict)
    authorized_task = observations["authorized_task"]
    assert isinstance(authorized_task, dict)
    receipts = authorized_task["receipts"]
    assert isinstance(receipts, dict)
    input_receipt = receipts["input"]
    assert isinstance(input_receipt, dict)
    input_output = input_receipt["output_preview"]
    assert isinstance(input_output, dict)
    grounded_element = input_output["grounded_element"]
    assert isinstance(grounded_element, dict)
    grounded_element["window_id"] = 123456
    provider_evidence = input_output["desktop_execution_provider_evidence"]
    assert isinstance(provider_evidence, dict)
    provider_evidence["window_id"] = 123456
    permission_denial = observations["permission_denial"]
    assert isinstance(permission_denial, dict)
    permission_denial["tool_call_count"] = 1
    permission_denial["tool_calls"] = [{"tool": "app.open"}]
    payload["evidence_digest"] = smoke._daily_provider_acceptance_digest(payload)
    acceptance_path = tmp_path / "unbound-acceptance.json"
    acceptance_path.write_text(json.dumps(payload), encoding="utf-8")

    evidence = smoke._daily_provider_acceptance_evidence(acceptance_path)

    assert evidence["ok"] is False
    assert evidence["validation"]["authorized_receipts_share_target"] is False
    assert evidence["derived_checks"]["background_input_verified"] is False
    assert evidence["derived_checks"]["permission_denial_fails_closed"] is False
    assert (
        "daily_provider_acceptance_background_input_verified_derived_failed"
        in evidence["blocking_conditions"]
    )
    assert (
        "daily_provider_acceptance_permission_denial_fails_closed_derived_failed"
        in evidence["blocking_conditions"]
    )


def test_daily_provider_acceptance_rejects_foreground_input_transport(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_packaged_app_identity_from_disk",
        lambda _path: {
            "ok": True,
            "location_valid": True,
            "bundle_id": "io.github.arisataki.oha-yachiyo",
            "version": "0.4.0",
            "app_asar_sha256": "a" * 64,
        },
    )
    payload = _packaged_daily_provider_acceptance()
    observations = payload["observations"]
    assert isinstance(observations, dict)
    authorized_task = observations["authorized_task"]
    assert isinstance(authorized_task, dict)
    receipts = authorized_task["receipts"]
    assert isinstance(receipts, dict)
    input_receipt = receipts["input"]
    assert isinstance(input_receipt, dict)
    input_output = input_receipt["output_preview"]
    assert isinstance(input_output, dict)
    transport = input_output["desktop_execution_provider_transport"]
    assert isinstance(transport, dict)
    transport["delivery_mode"] = "foreground"
    transport["foreground_takeover_required"] = True
    payload["evidence_digest"] = smoke._daily_provider_acceptance_digest(payload)
    acceptance_path = tmp_path / "foreground-transport.json"
    acceptance_path.write_text(json.dumps(payload), encoding="utf-8")

    evidence = smoke._daily_provider_acceptance_evidence(acceptance_path)

    assert evidence["ok"] is False
    assert evidence["derived_checks"]["background_input_verified"] is False
    assert evidence["derived_checks"]["keyboard_not_taken_over"] is False


def test_packaged_app_identity_requires_applications_location(tmp_path) -> None:
    app_path = tmp_path / "Oha-Yachiyo.app"
    app_path.mkdir()

    identity = smoke._packaged_app_identity_from_disk(app_path)

    assert identity == {
        "ok": False,
        "location_valid": False,
        "error": "packaged_app_must_be_installed_under_applications",
    }


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
        "provision_virtual_desktop_guest",
        "configure_virtual_desktop_provider",
        "attach_real_virtual_desktop_backend",
        "run_public_release_smoke",
    ]
    assert readiness["required_commands"]["public_release_smoke"].startswith(
        "python scripts/smoke_oha_desktop_agent_release.py "
        "--require-public-release-backend"
    )
    assert "run_virtual_desktop_guest_provider.py" in readiness[
        "required_commands"
    ]["guest_provider_manifest"]
    assert "run_ssh_virtual_desktop_provider.py" in readiness[
        "required_commands"
    ]["ssh_bridge_manifest"]
    assert "install_virtual_desktop_guest.py" in readiness[
        "required_commands"
    ]["install_guest"]


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
                    "--require-public-release-backend "
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
        "default_daily_provider_release_ready": False,
        "default_daily_provider_release_source": "",
        "default_daily_provider_release_blockers": [],
        "daily_provider_acceptance_requested": False,
        "daily_provider_acceptance": {},
        "direct_desktop_release_ready": False,
        "direct_desktop_backend": {},
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


def test_oha_desktop_agent_release_smoke_cli_explicit_backend_flag_requires_backend(
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
            "--require-public-release-backend",
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 1
    assert captured_kwargs["run_isolated_provider_smoke"] is True
    assert captured_kwargs["require_public_release_backend"] is True


def test_oha_desktop_agent_release_smoke_cli_public_release_uses_direct_desktop(
    tmp_path,
    monkeypatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    def fake_run_smoke(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "ok": True,
            "mode": "oha_desktop_agent_release_smoke",
            "public_release_required": True,
            "public_release_ready": True,
            "direct_desktop_release_ready": True,
            "section_count": 0,
            "failed_sections": [],
            "checks": {"covers_direct_desktop_runtime": True},
            "sections": [],
        }

    monkeypatch.setattr(smoke, "run_smoke", fake_run_smoke)

    exit_code = smoke.main(
        [
            "--public-release",
            "--skip-isolated-provider-smoke",
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 0
    assert captured_kwargs["run_isolated_provider_smoke"] is False
    assert captured_kwargs["public_release_required"] is True
    assert captured_kwargs["require_public_release_backend"] is False


def test_oha_desktop_agent_release_smoke_cli_public_release_uses_readiness_exit(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_smoke",
        lambda **_kwargs: {
            "ok": True,
            "mode": "oha_desktop_agent_release_smoke",
            "public_release_required": True,
            "public_release_ready": False,
            "section_count": 0,
            "failed_sections": [],
            "checks": {"all_sections_passed": True},
            "sections": [],
        },
    )

    exit_code = smoke.main(
        [
            "--public-release",
            "--skip-isolated-provider-smoke",
            "--report-json",
            str(tmp_path / "oha-release-smoke.json"),
        ]
    )

    assert exit_code == 1


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
